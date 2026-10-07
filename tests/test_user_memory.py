import pytest

from app import create_app
from database.db import db
from database.models import User
from agent.user_memory import extract_explicit_facts, save_explicit_facts


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    OPENAI_API_KEY = None


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_extract_only_explicit_scheme_facts():
    facts = extract_explicit_facts(
        "I am a 21-year-old engineering student from Maharashtra and family income is around ₹2 lakh per year."
    )
    assert facts == {"age": 21, "annual_income": 200000, "student_status": True,
                     "education_level": "engineering", "state": "Maharashtra"}
    assert extract_explicit_facts("I might be a student someday") == {}


def test_chat_saves_user_memory_and_conversations_can_be_cleared(app):
    client = app.test_client()
    client.post("/api/register", json={"username": "citizen", "email": "c@example.test", "password": "long-test-password"})
    response = client.post("/api/chat", json={"message": "I am 21-year-old engineering student from Maharashtra, income around ₹2 lakh per year."})
    assert response.status_code == 503  # no configured LLM/verified source; explicit memory still persists
    profile = client.get("/api/profile").json["profile"]
    assert profile["age"] == 21 and profile["state"] == "Maharashtra"
    assert profile["annual_income"] == 200000 and profile["student_status"] is True
    assert len(client.get("/api/memory").json["facts"]) == 5
    assert len(client.get("/api/conversations").json["conversations"]) == 1
    client.delete("/api/conversations")
    assert client.get("/api/conversations").json["conversations"] == []
    client.delete("/api/memory/age")
    assert client.get("/api/profile").json["profile"]["age"] is None
    client.delete("/api/memory")
    assert client.get("/api/memory").json["facts"] == []
