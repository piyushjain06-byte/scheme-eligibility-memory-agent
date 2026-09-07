"""
App entry point — application factory.

Teammates: register your blueprints in create_app() below, in the marked
section. Don't add routes directly to this file.
"""

from flask import Flask

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

    # ------------------------------------------------------------------
    # Blueprint registration — Members 2-4, uncomment/add your blueprint
    # as you build it. Each route file should expose a Blueprint object.
    # ------------------------------------------------------------------
    # from routes.auth import auth_bp
    # from routes.citizen import citizen_bp
    # from routes.schemes import schemes_bp
    # from routes.agent import agent_bp
    # from routes.admin import admin_bp
    #
    # app.register_blueprint(auth_bp)
    # app.register_blueprint(citizen_bp)
    # app.register_blueprint(schemes_bp)
    # app.register_blueprint(agent_bp)
    # app.register_blueprint(admin_bp, url_prefix="/admin")
    # ------------------------------------------------------------------

    @app.route("/")
    def index():
        return (
            "Scheme Eligibility Memory Agent — backend foundation is running. "
            "Run init_db.py first if you haven't. Routes/templates from the "
            "rest of the team plug in via create_app()."
        )

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
