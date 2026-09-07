import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """
    Central app configuration.
    Teammates: read values via app.config['KEY'] — don't hardcode paths/secrets
    elsewhere in routes/services.
    """
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'scheme_agent.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Demo admin credentials used by init_db.py — DEV/DEMO ONLY, never use in production
    DEMO_ADMIN_USERNAME = "admin"
    DEMO_ADMIN_EMAIL = "admin@demo.local"
    DEMO_ADMIN_PASSWORD = "Admin@123"
