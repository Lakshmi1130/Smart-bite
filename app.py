"""SmartBite - a digital food waste reduction platform for college canteens.

Roles
  canteen : staff who post surplus food and approve / hand over collections
  student : can browse available surplus food (read-only)
  ngo     : volunteers / food-recovery organisations; must be approved by admin
  admin   : approves canteen + NGO accounts, sees all reports
"""
import csv
import io
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SMARTBITE_DB", os.path.join(BASE_DIR, "smartbite.db"))
FMT = "%Y-%m-%dT%H:%M"

# Estimates used for the impact numbers (shown as estimates in the UI)
KG_PER_PORTION = 0.4      # average cooked portion weight
KG_PER_MEAL = 0.4         # one meal ~ 400 g of food
CO2_PER_KG = 2.5          # kg CO2e avoided per kg of food kept out of waste
MAX_SAFE_HOURS = 24       # safe-until can be at most 24h after preparation

CATEGORIES = ["Cooked meal", "Bakery", "Snacks", "Packaged / sealed", "Fruits", "Beverages"]
UNITS = ["portions", "kg"]

app = Flask(__name__)


def _secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE_DIR, ".secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app.config["SECRET_KEY"] = _secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student','canteen','ngo','admin')),
    organisation TEXT,
    phone TEXT,
    status TEXT NOT NULL DEFAULT 'approved' CHECK (status IN ('approved','pending','rejected')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canteen_id INTEGER NOT NULL REFERENCES users(id),
    food_name TEXT NOT NULL,
    category TEXT NOT NULL,
    diet TEXT NOT NULL DEFAULT 'veg' CHECK (diet IN ('veg','non-veg')),
    quantity REAL NOT NULL CHECK (quantity > 0),
    unit TEXT NOT NULL CHECK (unit IN ('portions','kg')),
    prepared_at TEXT NOT NULL,
    safe_until TEXT NOT NULL,
    pickup_location TEXT NOT NULL,
    notes TEXT,
    safety_confirmed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN ('available','requested','collected','expired','withdrawn')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES food_listings(id),
    ngo_id INTEGER NOT NULL REFERENCES users(id),
    pickup_time TEXT NOT NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','rejected','collected','cancelled','expired')),
    created_at TEXT NOT NULL,
    collected_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_status ON food_listings(status);
CREATE INDEX IF NOT EXISTS idx_requests_listing ON collection_requests(listing_id);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def q(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def run(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur


def now():
    return datetime.now().replace(second=0, microsecond=0)


def now_s():
    return now().strftime(FMT)


def parse_dt(value):
    try:
        return datetime.strptime(value, FMT)
    except (TypeError, ValueError):
        return None


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.commit()
    empty = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    db.close()
    if empty:
        from seed import seed
        seed(DB_PATH)


# ----------------------------------------------------------------------------
# Expiry: any listing past its safe-until time is closed automatically
# ----------------------------------------------------------------------------
def expire_listings():
    t = now_s()
    db = get_db()
    db.execute(
        """UPDATE collection_requests SET status='expired'
           WHERE status IN ('pending','approved') AND listing_id IN
             (SELECT id FROM food_listings
              WHERE status IN ('available','requested') AND safe_until < ?)""", (t,))
    db.execute("UPDATE food_listings SET status='expired' "
               "WHERE status IN ('available','requested') AND safe_until < ?", (t,))
    db.commit()


# ----------------------------------------------------------------------------
# Auth, CSRF, template helpers
# ----------------------------------------------------------------------------
@app.before_request
def before():
    if request.endpoint == "static":
        return
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "Invalid or missing form token. Please go back and retry.")
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = q("SELECT * FROM users WHERE id=?", (uid,), one=True)
        if g.user is None or g.user["status"] != "approved":
            session.pop("uid", None)
            g.user = None
    expire_listings()


@app.context_processor
def inject():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return {"csrf": session["_csrf"], "user": g.get("user"), "now_s": now_s()}


@app.template_filter("dt")
def fmt_dt(value):
    d = parse_dt(value)
    return d.strftime("%d %b, %I:%M %p") if d else (value or "-")


@app.template_filter("timeleft")
def timeleft(value):
    d = parse_dt(value)
    if not d:
        return ""
    mins = int((d - now()).total_seconds() // 60)
    if mins <= 0:
        return "expired"
    h, m = divmod(mins, 60)
    return f"{h}h {m}m left" if h else f"{m}m left"


@app.template_filter("urgent")
def urgent(value):
    d = parse_dt(value)
    return bool(d and 0 < (d - now()).total_seconds() < 3600)


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                flash("Please log in to continue.", "info")
                return redirect(url_for("login", next=request.path))
            if roles and g.user["role"] not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def kg_sql(prefix=""):
    return (f"CASE {prefix}unit WHEN 'kg' THEN {prefix}quantity "
            f"ELSE {prefix}quantity * {KG_PER_PORTION} END")


# ----------------------------------------------------------------------------
# Analytics
# ----------------------------------------------------------------------------
def month_keys(n=6):
    d = now().replace(day=1)
    keys = []
    for _ in range(n):
        keys.append(d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    return list(reversed(keys))


def stats(canteen_id=None):
    where, args = "", ()
    if canteen_id:
        where, args = " AND canteen_id=?", (canteen_id,)
    kg = kg_sql()
    row = q(f"""SELECT
        COALESCE(SUM(CASE WHEN status='collected' THEN {kg} END),0) AS saved_kg,
        COALESCE(SUM(CASE WHEN status='expired' THEN {kg} END),0) AS wasted_kg,
        SUM(status='collected') AS collected, SUM(status='expired') AS expired,
        SUM(status IN ('available','requested')) AS active,
        COUNT(*) AS total
        FROM food_listings WHERE status!='withdrawn'{where}""", args, one=True)
    saved, wasted = row["saved_kg"] or 0, row["wasted_kg"] or 0
    closed = (row["collected"] or 0) + (row["expired"] or 0)
    return {
        "saved_kg": round(saved, 1),
        "wasted_kg": round(wasted, 1),
        "meals": int(round(saved / KG_PER_MEAL)),
        "co2_kg": round(saved * CO2_PER_KG, 1),
        "collected": row["collected"] or 0,
        "expired": row["expired"] or 0,
        "active": row["active"] or 0,
        "total": row["total"] or 0,
        "rescue_rate": round(100 * (row["collected"] or 0) / closed) if closed else 0,
    }


def monthly(canteen_id=None, n=6):
    keys = month_keys(n)
    where, args = "", ()
    if canteen_id:
        where, args = " AND canteen_id=?", (canteen_id,)
    kg = kg_sql()
    out = {k: {"month": k, "saved": 0.0, "wasted": 0.0} for k in keys}
    for r in q(f"""SELECT strftime('%Y-%m', r.collected_at) m, SUM({kg_sql('l.')}) v
                   FROM collection_requests r JOIN food_listings l ON l.id=r.listing_id
                   WHERE r.status='collected'{where.replace('canteen_id','l.canteen_id')}
                   GROUP BY m""", args):
        if r["m"] in out:
            out[r["m"]]["saved"] = round(r["v"], 1)
    for r in q(f"""SELECT strftime('%Y-%m', safe_until) m, SUM({kg}) v FROM food_listings
                   WHERE status='expired'{where} GROUP BY m""", args):
        if r["m"] in out:
            out[r["m"]]["wasted"] = round(r["v"], 1)
    res = []
    for k in keys:
        item = out[k]
        item["label"] = datetime.strptime(k, "%Y-%m").strftime("%b %Y")
        res.append(item)
    return res


# ----------------------------------------------------------------------------
# Public pages
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", s=stats(), **{"categories": CATEGORIES})


@app.route("/listings")
def listings():
    cat = request.args.get("category", "")
    diet = request.args.get("diet", "")
    sql = ("SELECT l.*, u.organisation AS canteen_name, u.name AS staff_name "
           "FROM food_listings l JOIN users u ON u.id=l.canteen_id "
           "WHERE l.status IN ('available','requested')")
    args = []
    if cat in CATEGORIES:
        sql += " AND l.category=?"
        args.append(cat)
    if diet in ("veg", "non-veg"):
        sql += " AND l.diet=?"
        args.append(diet)
    sql += " ORDER BY l.status='requested', l.safe_until ASC"
    rows = q(sql, args)
    default_pickup = (now() + timedelta(minutes=30)).strftime(FMT)
    return render_template("listings.html", items=rows, categories=CATEGORIES,
                           cat=cat, diet=diet, default_pickup=default_pickup)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name, email = f.get("name", "").strip(), f.get("email", "").strip().lower()
        pw, role = f.get("password", ""), f.get("role", "")
        org, phone = f.get("organisation", "").strip(), f.get("phone", "").strip()
        err = None
        if role not in ("student", "canteen", "ngo"):
            err = "Choose a valid account type."
        elif not name or "@" not in email:
            err = "Enter your name and a valid email."
        elif len(pw) < 6:
            err = "Password must be at least 6 characters."
        elif role in ("canteen", "ngo") and not org:
            err = "Organisation / canteen name is required."
        elif q("SELECT 1 FROM users WHERE email=?", (email,), one=True):
            err = "An account with this email already exists."
        if err:
            flash(err, "error")
            return render_template("register.html", form=f), 400
        status = "approved" if role == "student" else "pending"
        run("INSERT INTO users (name,email,password_hash,role,organisation,phone,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (name, email, generate_password_hash(pw), role, org or None, phone or None,
             status, now_s()))
        if status == "pending":
            flash("Account created. An admin must verify it before you can log in.", "success")
        else:
            flash("Account created. You can log in now.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        u = q("SELECT * FROM users WHERE email=?", (email,), one=True)
        if not u or not check_password_hash(u["password_hash"], request.form.get("password", "")):
            flash("Incorrect email or password.", "error")
            return render_template("login.html"), 401
        if u["status"] == "pending":
            flash("Your account is waiting for admin verification.", "info")
            return render_template("login.html"), 403
        if u["status"] == "rejected":
            flash("This account was not approved.", "error")
            return render_template("login.html"), 403
        session.clear()
        session["uid"] = u["id"]
        nxt = request.args.get("next", "")
        if nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(home_for(u["role"]))
    return render_template("login.html")


def home_for(role):
    return {"canteen": "/canteen", "ngo": "/ngo", "admin": "/admin"}.get(role, "/listings")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------------
# Canteen dashboard
# ----------------------------------------------------------------------------
@app.route("/canteen")
@login_required("canteen")
def canteen():
    uid = g.user["id"]
    mine = q("SELECT * FROM food_listings WHERE canteen_id=? AND status!='withdrawn' "
             "ORDER BY created_at DESC LIMIT 30", (uid,))
    reqs = q("""SELECT r.*, l.food_name, l.quantity, l.unit, l.safe_until, l.pickup_location,
                       u.name AS ngo_contact, u.organisation AS ngo_name, u.phone AS ngo_phone
                FROM collection_requests r
                JOIN food_listings l ON l.id=r.listing_id
                JOIN users u ON u.id=r.ngo_id
                WHERE l.canteen_id=? AND r.status IN ('pending','approved')
                ORDER BY r.pickup_time""", (uid,))
    t = now()
    return render_template(
        "canteen.html", mine=mine, reqs=reqs, s=stats(uid), categories=CATEGORIES, units=UNITS,
        prepared_default=t.strftime(FMT),
        safe_default=(t + timedelta(hours=4)).strftime(FMT),
        loc_default=g.user["organisation"] or "")


@app.route("/canteen/listings", methods=["POST"])
@login_required("canteen")
def add_listing():
    f = request.form
    name = f.get("food_name", "").strip()
    cat, unit, diet = f.get("category"), f.get("unit"), f.get("diet", "veg")
    prepared, safe = parse_dt(f.get("prepared_at")), parse_dt(f.get("safe_until"))
    loc, notes = f.get("pickup_location", "").strip(), f.get("notes", "").strip()
    try:
        qty = float(f.get("quantity", ""))
    except ValueError:
        qty = 0
    err = None
    if not name or not loc:
        err = "Food name and pickup location are required."
    elif cat not in CATEGORIES or unit not in UNITS or diet not in ("veg", "non-veg"):
        err = "Invalid category, unit or diet type."
    elif not (0 < qty <= 5000):
        err = "Enter a quantity greater than 0."
    elif not prepared or not safe:
        err = "Enter valid preparation and safe-until times."
    elif prepared > now() + timedelta(minutes=5):
        err = "Preparation time cannot be in the future."
    elif safe <= now():
        err = "Safe-until time must be in the future."
    elif safe > prepared + timedelta(hours=MAX_SAFE_HOURS):
        err = f"Safe-until cannot be more than {MAX_SAFE_HOURS} hours after preparation."
    elif not all(f.get(k) for k in ("safe1", "safe2", "safe3")):
        err = "Confirm all three food-safety checks before listing."
    if err:
        flash(err, "error")
    else:
        run("""INSERT INTO food_listings (canteen_id,food_name,category,diet,quantity,unit,
               prepared_at,safe_until,pickup_location,notes,safety_confirmed,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,1,'available',?)""",
            (g.user["id"], name, cat, diet, qty, unit, prepared.strftime(FMT),
             safe.strftime(FMT), loc, notes or None, now_s()))
        flash(f"'{name}' is now listed for collection.", "success")
    return redirect(url_for("canteen"))


@app.route("/canteen/listings/<int:lid>/withdraw", methods=["POST"])
@login_required("canteen")
def withdraw_listing(lid):
    l = q("SELECT * FROM food_listings WHERE id=? AND canteen_id=?", (lid, g.user["id"]), one=True)
    if not l:
        abort(404)
    if l["status"] != "available":
        flash("Only listings with no active request can be withdrawn.", "error")
    else:
        run("UPDATE food_listings SET status='withdrawn' WHERE id=?", (lid,))
        flash("Listing withdrawn.", "info")
    return redirect(url_for("canteen"))


@app.route("/canteen/requests/<int:rid>/<action>", methods=["POST"])
@login_required("canteen")
def handle_request(rid, action):
    r = q("""SELECT r.*, l.canteen_id, l.status AS lstatus FROM collection_requests r
             JOIN food_listings l ON l.id=r.listing_id WHERE r.id=?""", (rid,), one=True)
    if not r or r["canteen_id"] != g.user["id"]:
        abort(404)
    if action == "approve" and r["status"] == "pending":
        run("UPDATE collection_requests SET status='approved' WHERE id=?", (rid,))
        flash("Request approved. The NGO can come at the agreed time.", "success")
    elif action == "reject" and r["status"] in ("pending", "approved"):
        run("UPDATE collection_requests SET status='rejected' WHERE id=?", (rid,))
        run("UPDATE food_listings SET status='available' WHERE id=? AND status='requested'",
            (r["listing_id"],))
        flash("Request rejected. The food is available again.", "info")
    elif action == "collected" and r["status"] == "approved":
        run("UPDATE collection_requests SET status='collected', collected_at=? WHERE id=?",
            (now_s(), rid))
        run("UPDATE food_listings SET status='collected' WHERE id=?", (r["listing_id"],))
        flash("Marked as collected. Added to your impact report.", "success")
    else:
        flash("That action is not possible for this request.", "error")
    return redirect(url_for("canteen"))


# ----------------------------------------------------------------------------
# NGO / volunteers
# ----------------------------------------------------------------------------
@app.route("/listings/<int:lid>/request", methods=["POST"])
@login_required("ngo")
def request_collection(lid):
    l = q("SELECT * FROM food_listings WHERE id=?", (lid,), one=True)
    if not l:
        abort(404)
    pickup = parse_dt(request.form.get("pickup_time"))
    if l["status"] != "available":
        flash("Sorry, this food is no longer available.", "error")
    elif not pickup or pickup < now() - timedelta(minutes=1):
        flash("Choose a valid pickup time that is not in the past.", "error")
    elif pickup > parse_dt(l["safe_until"]):
        flash("Pickup time must be before the food's safe-until time.", "error")
    else:
        run("INSERT INTO collection_requests (listing_id,ngo_id,pickup_time,message,status,created_at) "
            "VALUES (?,?,?,?, 'pending', ?)",
            (lid, g.user["id"], pickup.strftime(FMT),
             request.form.get("message", "").strip()[:300] or None, now_s()))
        run("UPDATE food_listings SET status='requested' WHERE id=?", (lid,))
        flash("Request sent to the canteen. You will see approval on your dashboard.", "success")
    return redirect(url_for("ngo"))


@app.route("/ngo")
@login_required("ngo")
def ngo():
    rows = q("""SELECT r.*, l.food_name, l.quantity, l.unit, l.safe_until, l.pickup_location,
                       u.organisation AS canteen_name, u.phone AS canteen_phone
                FROM collection_requests r
                JOIN food_listings l ON l.id=r.listing_id
                JOIN users u ON u.id=l.canteen_id
                WHERE r.ngo_id=? ORDER BY r.created_at DESC""", (g.user["id"],))
    kg = q(f"""SELECT COALESCE(SUM({kg_sql('l.')}),0) v FROM collection_requests r
               JOIN food_listings l ON l.id=r.listing_id
               WHERE r.ngo_id=? AND r.status='collected'""", (g.user["id"],), one=True)["v"]
    return render_template("ngo.html", rows=rows, collected_kg=round(kg, 1))


@app.route("/ngo/requests/<int:rid>/cancel", methods=["POST"])
@login_required("ngo")
def cancel_request(rid):
    r = q("SELECT * FROM collection_requests WHERE id=? AND ngo_id=?", (rid, g.user["id"]), one=True)
    if not r:
        abort(404)
    if r["status"] in ("pending", "approved"):
        run("UPDATE collection_requests SET status='cancelled' WHERE id=?", (rid,))
        run("UPDATE food_listings SET status='available' WHERE id=? AND status='requested'",
            (r["listing_id"],))
        flash("Request cancelled. The food is available to others again.", "info")
    return redirect(url_for("ngo"))


# ----------------------------------------------------------------------------
# Admin
# ----------------------------------------------------------------------------
@app.route("/admin")
@login_required("admin")
def admin():
    pending = q("SELECT * FROM users WHERE status='pending' ORDER BY created_at")
    users = q("SELECT * FROM users WHERE status!='pending' AND role!='admin' ORDER BY role, name")
    counts = {r["role"]: r["c"] for r in q(
        "SELECT role, COUNT(*) c FROM users WHERE status='approved' GROUP BY role")}
    return render_template("admin.html", pending=pending, users=users, counts=counts, s=stats())


@app.route("/admin/users/<int:uid>/<action>", methods=["POST"])
@login_required("admin")
def admin_user(uid, action):
    if action not in ("approve", "reject"):
        abort(404)
    u = q("SELECT * FROM users WHERE id=? AND role!='admin'", (uid,), one=True)
    if not u:
        abort(404)
    run("UPDATE users SET status=? WHERE id=?",
        ("approved" if action == "approve" else "rejected", uid))
    flash(f"{u['name']} {'approved' if action == 'approve' else 'rejected'}.", "success")
    return redirect(url_for("admin"))


# ----------------------------------------------------------------------------
# Reports / analytics
# ----------------------------------------------------------------------------
def report_scope():
    return g.user["id"] if g.user["role"] == "canteen" else None


@app.route("/reports")
@login_required("canteen", "admin")
def reports():
    cid = report_scope()
    kg = kg_sql("l.")
    records = q(f"""SELECT r.collected_at, l.food_name, l.category, l.quantity, l.unit,
                           {kg} AS kg, c.organisation AS canteen, n.organisation AS ngo
                    FROM collection_requests r
                    JOIN food_listings l ON l.id=r.listing_id
                    JOIN users c ON c.id=l.canteen_id
                    JOIN users n ON n.id=r.ngo_id
                    WHERE r.status='collected' {'AND l.canteen_id=?' if cid else ''}
                    ORDER BY r.collected_at DESC LIMIT 100""", (cid,) if cid else ())
    by_cat = q(f"""SELECT category, SUM(CASE WHEN status='collected' THEN {kg_sql()} ELSE 0 END) saved,
                          SUM(CASE WHEN status='expired' THEN {kg_sql()} ELSE 0 END) wasted
                   FROM food_listings WHERE status IN ('collected','expired')
                   {'AND canteen_id=?' if cid else ''} GROUP BY category ORDER BY saved DESC""",
               (cid,) if cid else ())
    return render_template("reports.html", s=stats(cid), months=monthly(cid), records=records,
                           by_cat=by_cat, scope_name=g.user["organisation"] if cid else "All canteens")


@app.route("/reports/export.csv")
@login_required("canteen", "admin")
def export_csv():
    cid = report_scope()
    rows = q(f"""SELECT r.collected_at, c.organisation AS canteen, l.food_name, l.category,
                        l.quantity, l.unit, ROUND({kg_sql('l.')},2) AS approx_kg, n.organisation AS collected_by
                 FROM collection_requests r
                 JOIN food_listings l ON l.id=r.listing_id
                 JOIN users c ON c.id=l.canteen_id
                 JOIN users n ON n.id=r.ngo_id
                 WHERE r.status='collected' {'AND l.canteen_id=?' if cid else ''}
                 ORDER BY r.collected_at DESC""", (cid,) if cid else ())
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["collected_at", "canteen", "food", "category", "quantity", "unit",
                "approx_kg", "collected_by"])
    for r in rows:
        w.writerow(list(r))
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=smartbite_collections.csv"})


@app.route("/api/stats")
def api_stats():
    cid = g.user["id"] if g.user and g.user["role"] == "canteen" and request.args.get("scope") == "mine" else None
    return jsonify({"summary": stats(cid), "monthly": monthly(cid)})


@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, msg="You don't have access to this page."), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, msg="That page doesn't exist."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, msg=getattr(e, "description", "Bad request")), 400


init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1",
            port=int(os.environ.get("PORT", 5000)))
