"""Demo data so the dashboards and charts are populated on first run."""
import random
import sqlite3
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

FMT = "%Y-%m-%dT%H:%M"
PW = "demo123"

FOODS = [
    ("Veg biryani", "Cooked meal", "veg", "portions", (20, 60)),
    ("Chapati & dal", "Cooked meal", "veg", "portions", (15, 50)),
    ("Idli & sambar", "Cooked meal", "veg", "portions", (20, 40)),
    ("Veg puff", "Bakery", "veg", "portions", (10, 30)),
    ("Bread loaves (sealed)", "Packaged / sealed", "veg", "kg", (3, 8)),
    ("Banana & apple", "Fruits", "veg", "kg", (4, 10)),
    ("Chicken fried rice", "Cooked meal", "non-veg", "portions", (10, 30)),
    ("Packed biscuits", "Packaged / sealed", "veg", "portions", (20, 60)),
]


def seed(path):
    random.seed(7)
    db = sqlite3.connect(path)
    now = datetime.now().replace(second=0, microsecond=0)
    ts = lambda d: d.strftime(FMT)
    h = generate_password_hash(PW)

    def user(name, email, role, org=None, phone=None, status="approved"):
        return db.execute(
            "INSERT INTO users (name,email,password_hash,role,organisation,phone,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (name, email, h, role, org, phone, status, ts(now - timedelta(days=170)))).lastrowid

    user("Admin", "admin@smartbite.in", "admin")
    c1 = user("Ramesh K", "main@smartbite.in", "canteen", "Main Canteen", "9800000001")
    c2 = user("Sunita R", "mess@smartbite.in", "canteen", "Hostel Mess", "9800000002")
    n1 = user("Anita", "annapurna@smartbite.in", "ngo", "Annapurna Food Foundation", "9800000011")
    n2 = user("Vikram", "hands@smartbite.in", "ngo", "Helping Hands Bangalore", "9800000012")
    user("Karthik", "newngo@smartbite.in", "ngo", "Seva Samithi (awaiting approval)", "9800000013",
         status="pending")
    user("Priya", "student@smartbite.in", "student")

    # ~5 months of history: most surplus gets rescued, some expires unclaimed
    for days_ago in range(150, 1, -1):
        if random.random() > 0.55:
            continue
        canteen = random.choice([c1, c2])
        food = random.choice(FOODS)
        qty = random.randint(*food[4])
        prepared = now - timedelta(days=days_ago, hours=random.randint(0, 3))
        safe = prepared + timedelta(hours=random.choice([4, 5, 6]))
        rescued = random.random() < 0.82
        cur = db.execute(
            """INSERT INTO food_listings (canteen_id,food_name,category,diet,quantity,unit,prepared_at,
               safe_until,pickup_location,safety_confirmed,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,1,?,?)""",
            (canteen, food[0], food[1], food[2], qty, food[3], ts(prepared), ts(safe),
             "Canteen back gate", "collected" if rescued else "expired", ts(prepared)))
        if rescued:
            when = prepared + timedelta(hours=random.randint(1, 3))
            db.execute(
                "INSERT INTO collection_requests (listing_id,ngo_id,pickup_time,status,created_at,collected_at) "
                "VALUES (?,?,?,'collected',?,?)",
                (cur.lastrowid, random.choice([n1, n2]), ts(when), ts(prepared), ts(when)))

    # Live listings (so the listings page is not empty)
    live = [
        (c1, "Veg biryani", "Cooked meal", "veg", 35, "portions", 2, 6, "Main Canteen counter 3"),
        (c1, "Veg puff", "Bakery", "veg", 18, "portions", 1, 4, "Main Canteen counter 1"),
        (c2, "Chapati & dal", "Cooked meal", "veg", 28, "portions", 3, 5, "Hostel Mess kitchen door"),
        (c2, "Banana & apple", "Fruits", "veg", 6, "kg", 1, 24, "Hostel Mess store room"),
        (c1, "Packed biscuits", "Packaged / sealed", "veg", 40, "portions", 1, 20, "Main Canteen store"),
    ]
    for cid, name, cat, diet, qty, unit, ago, left, loc in live:
        db.execute(
            """INSERT INTO food_listings (canteen_id,food_name,category,diet,quantity,unit,prepared_at,
               safe_until,pickup_location,notes,safety_confirmed,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,1,'available',?)""",
            (cid, name, cat, diet, qty, unit, ts(now - timedelta(hours=ago)),
             ts(now + timedelta(hours=left)), loc, "Unserved, kept covered.", ts(now)))
    db.commit()
    db.close()
