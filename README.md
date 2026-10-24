# SmartBite — A Digital Food Waste Reduction Platform

A web app that connects **college canteens**, **students** and **NGOs / volunteers** to cut edible food waste:
canteens list safe surplus food, students see what is available, verified NGOs request and collect it,
and every collection feeds waste analytics.

## Run it
```bash
pip install -r requirements.txt
python app.py            # open http://127.0.0.1:5000
```
First run creates `smartbite.db` (SQLite) and loads demo data (5 months of sample history + live listings).
Demo accounts, password `demo123`: `admin@smartbite.in`, `main@smartbite.in` (canteen),
`annapurna@smartbite.in` (NGO), `student@smartbite.in`. Delete `smartbite.db` to reset.

## Features
- Roles: canteen staff, student (view only), NGO/volunteer, admin. Canteen and NGO sign-ups need admin approval.
- Listing lifecycle: available -> requested -> collected, or expired (auto-closed at the safe-until time).
- Food safety: three mandatory confirmations, safe-until at most 24 h after preparation, pickup inside the safe window.
- Analytics: kg saved/wasted, meals, CO2e avoided (estimate), rescue rate, monthly chart, category table, CSV export.
- Security: hashed passwords, CSRF tokens, parameterised SQL, role checks on every route.

## Architecture
```
Browser (HTML/CSS/JS) -> Flask routes (app.py) -> SQLite (users, food_listings, collection_requests)
                              |- expiry check on every request
                              |- analytics queries -> /api/stats (JSON) -> JS bar chart
```

## Impact assumptions (top of app.py)
0.4 kg per portion/meal, 2.5 kg CO2e avoided per kg of food kept out of waste. Demo data is illustrative.
