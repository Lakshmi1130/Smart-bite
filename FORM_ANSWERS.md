# SmartBite — Submission Form Answers

## Why Does This Problem Matter?
Roughly one-third of all food produced is lost or wasted, and college canteens and hostel messes are a steady source: food is cooked for estimated demand, and whatever is left after meal times is usually thrown away even though it is still safe. Every kilogram wasted also wastes the water, energy and land used to grow and cook it, and rotting food in landfill releases methane, a potent greenhouse gas. At the same time, many people nearby go hungry. There is no simple, trusted way for a canteen to tell anyone about its surplus before it expires, so good food ends up in the bin.

## Proposed Digital Solution
SmartBite is a web application that connects college canteens, students and verified NGOs / volunteers.
1. Canteen staff list surplus food (name, quantity, preparation time, safe-until time, pickup point) after confirming three food-safety checks.
2. Students browse the live list of available food, and verified NGOs / volunteers request a pickup time inside the safe window.
3. The canteen approves the request and marks it collected at handover.
4. The system closes listings automatically when they pass their safe-until time, and an analytics dashboard shows food saved, food wasted, meals provided, CO2 avoided, monthly trends and collection records (with CSV export).
Admin approval of canteen and NGO accounts keeps the platform trustworthy.

## Technology Used (tick these)
- [x] Web Application
- [x] Data Analytics
- [x] Other: Python Flask, SQLite database, HTML/CSS/JavaScript, role-based authentication
- [ ] Optional if you add the future roadmap: Machine Learning (surplus prediction), Mobile Application (PWA), Cloud Computing (hosted deployment)
Leave AI, Deep Learning, IoT, GIS, Blockchain, Computer Vision and Sensors unticked, since the prototype does not use them.

## Input Data Required
- Canteen entries: food name, category, veg/non-veg, quantity and unit, preparation time, safe-until time, pickup location, notes, safety confirmation. Source: canteen staff through the dashboard.
- User data: name, organisation, contact, role. Source: registration, verified by admin.
- Collection data: requested pickup time, approval status, collection timestamp. Source: NGOs and canteen staff.
- Conversion factors for impact estimates: about 0.4 kg per portion, about 2.5 kg CO2e per kg of food waste. Source: published food-waste studies (FAO / WRAP style averages).
- Future: historical listings and canteen footfall to predict daily surplus.

## How Does the System Work?
**Input:** Canteen staff enter surplus food details and safety confirmations; NGOs submit collection requests with a pickup time.
**Processing:** The Flask backend validates every entry (safe window of at most 24 hours, pickup before expiry, safety checks, role permissions), stores records in SQLite, auto-expires listings past their safe-until time, tracks status (available, requested, collected, expired), and calculates kg saved/wasted, meals, CO2e avoided and the rescue rate.
**Output:** A live list of available food for students and NGOs, request and approval screens for canteens, and an analytics dashboard with monthly charts, category breakdown, collection records and a CSV report.

## Expected Environmental Benefits
- Less edible food sent to landfill, so lower methane emissions from decomposing waste.
- Avoided CO2e: each kg of food rescued avoids about 2.5 kg CO2e.
- Saves the water, energy and land already used to grow, transport and cook the food.
- Less waste to collect and dispose of on campus, lowering disposal costs and pollution.
- Waste data shows canteens what they over-produce, so they cook less and waste less in future.
- Builds a habit of responsible consumption among students and staff.

## Developed System / Prototype / Architecture Link
GitHub repository link: (upload the project folder to GitHub and paste the repository link here)
The repository contains the full working Flask app, a README with run steps, and the architecture diagram.
