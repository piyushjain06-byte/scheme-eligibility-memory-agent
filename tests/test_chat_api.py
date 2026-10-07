import sys
from types import SimpleNamespace

import pytest

from app import create_app
from config import Config
from database.db import db
from database.models import Scheme, SchemeSource, User


class TestConfig(Config):
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    OPENAI_API_KEY = "test-api-key"
    OPENAI_CHAT_MODEL = "ft:test-model"


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _register(client, username="citizen", email="citizen@example.test"):
    return client.post(
        "/api/register",
        json={"username": username, "email": email, "password": "long-test-password"},
    )


def _make_admin():
    admin = User(username="admin-test", email="admin@example.test", role="admin")
    admin.set_password("long-test-password")
    db.session.add(admin)
    db.session.commit()
    return admin


def _official_record(name="Sample State Education Scheme"):
    return {
        "name": name,
        "description": "Education assistance for eligible students.",
        "department": "Department of Education",
        "government_level": "STATE",
        "category": "Education",
        "benefits": "Education grant",
        "source_url": "https://education.gov.in/schemes/sample",
        "source_title": "Scheme notification",
        "publisher": "Department of Education",
        "excerpt": "Students aged 18 to 25 may apply.",
        "jurisdiction": "Karnataka",
        "rule": {
            "logic": "AND",
            "conditions": [
                {"field": "age", "operator": "between", "value": [18, 25]},
                {"field": "student_status", "operator": "==", "value": True},
            ],
        },
    }


def test_register_profile_update_and_login_memory(client):
    response = _register(client)
    assert response.status_code == 201
    assert client.put("/api/profile", json={"age": 20, "student_status": True}).status_code == 200
    client.post("/api/logout")

    login = client.post(
        "/api/login",
        json={"username": "citizen", "password": "long-test-password"},
    )
    assert login.status_code == 200
    profile = client.get("/api/profile").get_json()["profile"]
    assert profile["age"] == 20
    assert profile["student_status"] is True


def test_profile_rejects_unknown_fields(client):
    _register(client)
    response = client.put("/api/profile", json={"is_admin": True})
    assert response.status_code == 400


def test_scheme_import_is_pending_until_admin_review(client, app):
    _register(client)
    assert client.post(
        "/api/admin/sources/import", json={"records": [_official_record()]}
    ).status_code == 403

    client.post("/api/logout")
    with app.app_context():
        _make_admin()
    login = client.post(
        "/api/login",
        json={"username": "admin-test", "password": "long-test-password"},
    )
    assert login.status_code == 200

    imported = client.post(
        "/api/admin/sources/import", json={"records": [_official_record()]}
    )
    assert imported.status_code == 201
    source = imported.get_json()["sources"][0]
    assert source["status"] == "PENDING"
    assert source["rule_version"] == 0
    with app.app_context():
        scheme = Scheme.query.filter_by(name="Sample State Education Scheme").one()
        assert scheme.latest_rule() is None
    pending_sources = client.get("/api/admin/sources?status=PENDING").get_json()["sources"]
    assert pending_sources[0]["excerpt"] == "Students aged 18 to 25 may apply."
    assert client.post(
        f"/api/admin/sources/{source['id']}/review",
        json={"status": "VERIFIED", "review_notes": "Checked against notification"},
    ).get_json()["source"]["status"] == "VERIFIED"
    with app.app_context():
        scheme = Scheme.query.filter_by(name="Sample State Education Scheme").one()
        assert scheme.latest_rule().version == 1


def test_import_rejects_unknown_rule_fields(client, app):
    with app.app_context():
        _make_admin()
    client.post(
        "/api/login",
        json={"username": "admin-test", "password": "long-test-password"},
    )
    record = _official_record()
    record["rule"]["conditions"][0]["field"] = "aadhaar_number"
    response = client.post("/api/admin/sources/import", json={"records": [record]})
    assert response.status_code == 400


def test_import_rejects_rule_values_incompatible_with_profile_fields(client, app):
    with app.app_context():
        _make_admin()
    client.post(
        "/api/login",
        json={"username": "admin-test", "password": "long-test-password"},
    )
    record = _official_record()
    record["rule"]["conditions"][0] = {
        "field": "annual_income",
        "operator": "<=",
        "value": "250000",
    }
    response = client.post("/api/admin/sources/import", json={"records": [record]})
    assert response.status_code == 400
    assert "annual_income" in response.get_json()["error"]


def test_chat_uses_verified_evidence_and_never_sends_profile_data(client, app, monkeypatch):
    _register(client)
    client.put(
        "/api/profile",
        json={"age": 20, "student_status": True, "annual_income": 123456},
    )
    client.post("/api/logout")
    with app.app_context():
        admin = _make_admin()
        source_response = app.test_client()
        source_response.post(
            "/api/login",
            json={"username": admin.username, "password": "long-test-password"},
        )
        imported = source_response.post(
            "/api/admin/sources/import", json={"records": [_official_record()]}
        ).get_json()
        source_id = imported["sources"][0]["id"]
        source_response.post(
            f"/api/admin/sources/{source_id}/review", json={"status": "VERIFIED"}
        )

    client.post(
        "/api/login",
        json={"username": "citizen", "password": "long-test-password"},
    )
    captured = {}

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-api-key"
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="You qualify [S1]."))]
            )

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    response = client.post("/api/chat", json={"message": "Am I eligible for schemes?"})

    assert response.status_code == 200
    result = response.get_json()
    assert result["eligibility"][0]["status"] == "ELIGIBLE"
    assert result["citations"][0]["url"] == "https://education.gov.in/schemes/sample"
    assert result["citations"][0]["citation"] == "S1"
    assert result["answer"] == "You qualify [S1]."
    sent_prompt = str(captured["messages"])
    assert "123456" not in sent_prompt
    assert "annual_income" not in sent_prompt


def test_chat_requires_login_and_verified_knowledge(client):
    assert client.post("/api/chat", json={"message": "schemes"}).status_code == 401
    _register(client)
    response = client.post("/api/chat", json={"message": "schemes"})
    assert response.status_code == 503


def test_profile_rejects_invalid_types_and_chat_rejects_oversized_messages(client):
    _register(client)
    assert client.put("/api/profile", json={"age": "twenty"}).status_code == 400
    assert client.post("/api/chat", json={"message": "x" * 2001}).status_code == 400


def test_home_page_serves_chat_interface(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Ask about schemes" in response.data
