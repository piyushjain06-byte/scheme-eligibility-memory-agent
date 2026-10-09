import os
import secrets
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# override=True: values in .env win over any stale/placeholder variable already set on the computer
# (e.g. a leftover OPENAI_API_KEY=your_api_key_here), which otherwise silently replaces your real key.
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)


def _flag(name, default):
    return os.environ.get(name, default).lower() == "true"


class Config:
    """
    Central app configuration.
    Teammates: read values via app.config['KEY'] — don't hardcode paths/secrets
    elsewhere in routes/services.
    """
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("SESSION_COOKIE_SECURE", "false")
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024  # reject oversized request bodies

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'scheme_agent.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    OPENAI_CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

    # Optional LLM-assisted fact extraction (off by default). Output is validated like the rule-based path.
    LLM_MEMORY_EXTRACTION = _flag("LLM_MEMORY_EXTRACTION", "false")
    OPENAI_EXTRACTION_MODEL = os.environ.get("OPENAI_EXTRACTION_MODEL", "gpt-4o-mini")

    # Privacy: registration must include explicit consent to store profile details (DPDP-style notice).
    REQUIRE_CONSENT = _flag("REQUIRE_CONSENT", "true")

    # Requests per minute (0 disables). In-memory and per process; use Redis-backed limiting with many workers.
    RATE_LIMIT_LOGIN = int(os.environ.get("RATE_LIMIT_LOGIN", "10"))
    RATE_LIMIT_REGISTER = int(os.environ.get("RATE_LIMIT_REGISTER", "5"))
    RATE_LIMIT_CHAT = int(os.environ.get("RATE_LIMIT_CHAT", "20"))

    # Demo admin credentials used by init_db.py — DEV/DEMO ONLY. Override DEMO_ADMIN_PASSWORD outside local use.
    DEMO_ADMIN_USERNAME = "admin"
    DEMO_ADMIN_EMAIL = "admin@demo.local"
    DEMO_ADMIN_PASSWORD = os.environ.get("DEMO_ADMIN_PASSWORD", "Admin@123")