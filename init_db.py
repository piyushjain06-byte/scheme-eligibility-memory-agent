"""
Database initialization script.

Run this once (and again any time you want a clean slate):

    python init_db.py

It will:
  1. Drop and recreate all tables.
  2. Create a demo admin account (DEV/DEMO ONLY — see Config).
  3. Load data/demo_schemes.json and insert each scheme + its v1 rule.
"""

import json
import os
from datetime import datetime

from app import create_app
from config import Config
from database.db import db
from database.models import EligibilityRule, Scheme, User

DEMO_SCHEMES_PATH = os.path.join(os.path.dirname(__file__), "data", "demo_schemes.json")


def create_demo_admin():
    existing = User.query.filter_by(username=Config.DEMO_ADMIN_USERNAME).first()
    if existing:
        print(f"Admin '{Config.DEMO_ADMIN_USERNAME}' already exists — skipping.")
        return existing

    admin = User(
        username=Config.DEMO_ADMIN_USERNAME,
        email=Config.DEMO_ADMIN_EMAIL,
        role="admin",
    )
    admin.set_password(Config.DEMO_ADMIN_PASSWORD)
    db.session.add(admin)
    db.session.commit()
    print(f"Created demo admin: {Config.DEMO_ADMIN_USERNAME}")
    return admin


def seed_demo_schemes(json_path=DEMO_SCHEMES_PATH):
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Demo scheme data not found at {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        schemes_data = json.load(f)

    created = 0
    for entry in schemes_data:
        if Scheme.query.filter_by(name=entry["name"]).first():
            continue  # already seeded

        scheme = Scheme(
            name=entry["name"],
            description=entry.get("description"),
            department=entry.get("department"),
            government_level=entry.get("government_level", "DEMO"),
            category=entry.get("category"),
            benefits=entry.get("benefits"),
            application_url=entry.get("application_url"),
            active=True,
            rule_version=1,
        )
        db.session.add(scheme)
        db.session.flush()  # assign scheme.id before creating the rule row

        rule = EligibilityRule(
            scheme_id=scheme.id,
            rule_json=entry["rule"],
            version=1,
            effective_from=datetime.utcnow(),
        )
        db.session.add(rule)
        created += 1

    db.session.commit()
    print(f"Seeded {created} demo scheme(s).")


def main():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        print("Tables created.")

        create_demo_admin()
        seed_demo_schemes()

        print("\nDatabase initialization complete.")
        print("---------------------------------------------")
        print("DEMO ADMIN LOGIN (development/demo only):")
        print(f"  username: {Config.DEMO_ADMIN_USERNAME}")
        print(f"  password: {Config.DEMO_ADMIN_PASSWORD}")
        print("---------------------------------------------")


if __name__ == "__main__":
    main()
