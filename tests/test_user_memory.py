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
    assert response.status_code == 200  # personal statements are acknowledged without a scheme model
    assert "remember" in response.get_json()["answer"].lower()
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


def test_chat_answers_bio_and_recalls_personal_details_without_schemes(app):
    client = app.test_client()
    client.post("/api/register", json={"username": "citizen", "email": "c@example.test", "password": "long-test-password"})

    bio = client.post("/api/chat", json={"message": "I am 28 and from Pune."})
    assert bio.status_code == 200
    assert "remember" in bio.get_json()["answer"].lower()

    profile_answer = client.post("/api/chat", json={"message": "What is my age and state?"})
    assert profile_answer.status_code == 200
    assert "age: 28" in profile_answer.get_json()["answer"]
    assert "state: Maharashtra" in profile_answer.get_json()["answer"]
    assert profile_answer.get_json()["citations"] == []

    disclosure = client.post("/api/chat", json={"message": "My favorite color is teal."})
    assert disclosure.status_code == 200
    favorite = client.post("/api/chat", json={"message": "What is my favorite color?"})
    assert favorite.status_code == 200
    assert "teal" in favorite.get_json()["answer"].lower()


def test_memory_recall_uses_latest_profile_and_only_matching_personal_details(app):
    client = app.test_client()
    client.post("/api/register", json={"username": "citizen", "email": "c@example.test", "password": "long-test-password"})
    client.post("/api/chat", json={"message": "I am a 21-year-old engineering student from Maharashtra, income around ₹2 lakh per year."})
    client.post("/api/chat", json={"message": "I am 22."})
    client.post("/api/chat", json={"message": "I am 28 and from Pune. My favorite color is teal."})

    favorite = client.post("/api/chat", json={"message": "What is my favorite color?"}).get_json()["answer"].lower()
    assert "teal" in favorite
    assert "22" not in favorite
    assert "21-year-old" not in favorite
    assert "income around" not in favorite

    overview = client.post("/api/chat", json={"message": "What do you remember about me?"}).get_json()["answer"].lower()
    assert "age: 28" in overview
    assert "annual income: rs. 200,000 per year" in overview
    assert "favorite color is teal" in overview
    assert "age: 22" not in overview
    assert "21-year-old" not in overview

    client.post("/api/chat", json={"message": "My favorite color is blue."})
    updated_favorite = client.post("/api/chat", json={"message": "What is my favorite color?"}).get_json()["answer"].lower()
    assert "blue" in updated_favorite
    assert "teal" not in updated_favorite
