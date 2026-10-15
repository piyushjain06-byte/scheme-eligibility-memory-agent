"""
App entry point — application factory.

Teammates: register your blueprints in create_app() below, in the marked
section. Don't add routes directly to this file.
"""

from flask import Flask, render_template

from config import Config
from database.db import db


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    # Import models so they're registered on SQLAlchemy's metadata before
    # db.create_all() / migrations run. Keep this import even though it
    # looks unused.
    from database import models  # noqa: F401

    from routes.api import api_bp
    from routes.account import account_bp

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(account_bp, url_prefix="/api")

    @app.cli.command("process-due-notifications")
    def process_due_notifications():
        """Create due in-app task reminders; invoke periodically from cron or Task Scheduler."""
        from agent.notification_service import process_due_tasks
        print(f"Created {process_due_tasks()} task reminder(s).")

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
