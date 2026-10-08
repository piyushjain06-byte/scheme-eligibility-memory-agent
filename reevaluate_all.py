"""Re-check every active scheme against every saved profile and create 'newly eligible' notifications.

Run it from cron (e.g. nightly) or after importing new rules:   python reevaluate_all.py
"""
from app import create_app
from database.models import Scheme
from agent.change_detection import reevaluate_scheme


def main():
    app = create_app()
    with app.app_context():
        total = 0
        for scheme in Scheme.query.filter_by(active=True).order_by(Scheme.id).all():
            result = reevaluate_scheme(scheme, record_unchanged=False)
            if result.get("error"):
                continue
            total += result["newly_eligible"]
            print(f"{scheme.name}: {result['evaluated']} checked, {result['newly_eligible']} newly eligible")
        print(f"Done. {total} notification(s) created.")


if __name__ == "__main__":
    main()
