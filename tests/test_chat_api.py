import sys
from types import SimpleNamespace

import pytest

from app import create_app
from config import Config
from database.db import db
from database.models import Notification, Scheme, SchemeSource, User, UserTask


class TestConfig(Config):
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    OPENAI_API_KEY = "test-api-key"
    # Do not let a developer's local .env provider endpoint leak into fake-client tests.
    OPENAI_BASE_URL = ""
    OPENAI_CHAT_MODEL = "ft:test-model"
    LLM_MEMORY_EXTRACTION = False


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
        json={"username": username, "email": email, "password": "long-test-password", "consent": True},
    )


def _make_admin():
    admin = User(username="admin-test", email="admin@example.test", role="admin")
    admin.set_password("long-test-password")
    db.session.add(admin)
    db.session.commit()
    return admin


def _official_record(name="Sample State Education Scheme", **overrides):
    record = {
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
    record.update(overrides)
    return record


def _admin_client(app):
    with app.app_context():
        admin = _make_admin()
        admin_client = app.test_client()
        admin_client.post("/api/login", json={"username": admin.username, "password": "long-test-password"})
    return admin_client


def _publish(app, record):
    """Import + approve one source as admin; returns the admin client."""
    admin_client = _admin_client(app)
    imported = admin_client.post("/api/admin/sources/import", json={"records": [record]}).get_json()
    admin_client.post(f"/api/admin/sources/{imported['sources'][0]['id']}/review", json={"status": "VERIFIED"})
    return admin_client


def _install_fake_openai(monkeypatch, captured):
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
    # The reviewer sees the proposed rule in plain words next to the excerpt.
    assert source["proposed_rule_text"] == "(age between 18 and 25 AND student_status == True)"
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


def test_state_scheme_import_requires_a_real_state(client, app):
    admin_client = _admin_client(app)
    response = admin_client.post("/api/admin/sources/import",
                                 json={"records": [_official_record(jurisdiction="Somewhere")]})
    assert response.status_code == 400
    assert "jurisdiction" in response.get_json()["error"]


def test_chat_uses_verified_evidence_and_never_sends_profile_data(client, app, monkeypatch):
    user_id = _register(client).get_json()["user"]["id"]
    client.put(
        "/api/profile",
        json={"age": 20, "student_status": True, "annual_income": 123456, "state": "Karnataka"},
    )
    client.post("/api/logout")
    _publish(app, _official_record())

    client.post(
        "/api/login",
        json={"username": "citizen", "password": "long-test-password"},
    )
    captured = {}
    _install_fake_openai(monkeypatch, captured)
    response = client.post("/api/chat", json={"message": "Am I eligible for schemes?"})

    assert response.status_code == 200
    result = response.get_json()
    assert result["eligibility"][0]["status"] == "ELIGIBLE"
    assert result["citations"][0]["url"] == "https://education.gov.in/schemes/sample"
    assert result["citations"][0]["citation"] == "S1"
    assert result["answer"] == "You qualify [S1]."
    assert result["disclaimer"]
    sent_prompt = str(captured["messages"])
    assert "123456" not in sent_prompt
    assert "annual_income" in sent_prompt
    assert "Saved profile fields (names only; values remain private)" in sent_prompt
    # The exact values (age 20, income) are never sent, only which criteria were met.
    assert "(actual" not in sent_prompt
    with app.app_context():
        task = UserTask.query.filter_by(user_id=user_id, scheme_id=result["focus_scheme_ids"][0]).one()
        assert task.title == "Apply for Sample State Education Scheme"
        assert task.status == "PENDING"
        notification = Notification.query.filter_by(
            citizen_id=user_id, scheme_id=task.scheme_id, title="Scheme added to unfinished tasks"
        ).one()
        assert notification.notification_type == "TASK_REMINDER"
        task_id = task.id

    completed = client.post("/api/chat", json={
        "message": "I finished applying for Sample State Education Scheme",
        "conversation_id": result["conversation_id"],
    })
    assert completed.status_code == 200
    assert "removed it from your unfinished tasks" in completed.get_json()["answer"]
    with app.app_context():
        task = db.session.get(UserTask, task_id)
        assert task.status == "COMPLETED"
        assert task.verified is True
        notification = Notification.query.filter_by(
            citizen_id=user_id, scheme_id=task.scheme_id, title="Scheme added to unfinished tasks"
        ).one()
        assert notification.is_read is True


def test_combined_personal_disclosure_and_scholarship_search_runs_scheme_chat(client, app, monkeypatch):
    _register(client)
    _publish(app, _official_record(
        name="Delhi Student Scholarship",
        category="Scholarships",
        jurisdiction="Delhi",
        excerpt="Scholarship assistance for students aged 18 to 25.",
    ))
    captured = {}
    _install_fake_openai(monkeypatch, captured)

    response = client.post("/api/chat", json={"message": (
        "I am a 21-year-old engineering student from Delhi. "
        "My family's annual income is ₹2 lakh. I want to find scholarships."
    )})

    assert response.status_code == 200
    result = response.get_json()
    assert result["answer"] == "You qualify [S1]."
    assert result["citations"]
    assert result["remembered"]
    assert "Reviewed evidence" in captured["messages"][1]["content"]


def test_eligibility_answer_ignores_stale_assistant_income_after_profile_update(client, app, monkeypatch):
    _register(client)
    _publish(app, _official_record(
        name="Delhi Income-Limited Scholarship",
        category="Scholarships",
        jurisdiction="Delhi",
        excerpt="Applicants must have annual household income of 250000 or less.",
        rule={
            "logic": "AND",
            "conditions": [{"field": "annual_income", "operator": "<=", "value": 250000}],
        },
    ))
    captured = []

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            captured.append(kwargs)
            answer = (
                "Your family income of Rs. 200,000 may qualify [S1]."
                if len(captured) == 1
                else "Your updated income is above the listed limit [S1]."
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=answer))]
            )

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    initial = client.post("/api/chat", json={"message": (
        "I am a 21-year-old engineering student from Delhi. "
        "My family's annual income is ₹2 lakh. I want to find scholarships."
    )})
    assert initial.status_code == 200
    update = client.post("/api/chat", json={"message": "My family income is now ₹3 lakh. Update your memory."})
    assert update.status_code == 200
    assert client.get("/api/profile").get_json()["profile"]["annual_income"] == 300000

    response = client.post("/api/chat", json={
        "message": "Which scholarships can I apply for now?",
        "conversation_id": initial.get_json()["conversation_id"],
    })

    assert response.status_code == 200
    result = response.get_json()
    assert result["eligibility"][0]["status"] == "NOT_ELIGIBLE"
    latest_prompt = str(captured[-1]["messages"])
    assert "200,000" not in latest_prompt
    assert "200000" not in latest_prompt
    assert "300,000" not in latest_prompt
    assert "300000" not in latest_prompt
    assert "Recent assistant replies (continuity only): []" in latest_prompt
    assert "Saved profile fields (names only; values remain private)" in latest_prompt
    assert "annual_income" in latest_prompt
    assert "state" in latest_prompt
    assert "do not ask for fields marked as saved" in captured[-1]["messages"][0]["content"]


def test_additional_scheme_request_excludes_previously_cited_schemes(client, app, monkeypatch):
    _register(client)
    admin = _admin_client(app)
    for name in (
        "Delhi Student Scholarship One",
        "Delhi Student Scholarship Two",
        "Delhi Student Scholarship Three",
        "Delhi Student Scholarship Four",
    ):
        imported = admin.post("/api/admin/sources/import", json={
            "records": [_official_record(name=name, category="Scholarships", government_level="CENTRAL",
                                         jurisdiction="India")]
        }).get_json()
        source_id = imported["sources"][0]["id"]
        assert admin.post(
            f"/api/admin/sources/{source_id}/review", json={"status": "VERIFIED"}
        ).status_code == 200

    responses = []

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            responses.append(kwargs)
            answer = (
                "The first three are [S1], [S2], and [S3]."
                if len(responses) == 1
                else "Here is another option [S4]."
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=answer))]
            )

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    first = client.post("/api/chat", json={"message": "Which schemes can I apply for?"})
    assert first.status_code == 200
    first_result = first.get_json()
    first_names = {citation["scheme"] for citation in first_result["citations"]}
    assert len(first_names) == 3

    followup = client.post("/api/chat", json={
        "message": "Find additional scholarships; don't repeat the schemes you already listed.",
        "conversation_id": first_result["conversation_id"],
    })
    assert followup.status_code == 200
    followup_result = followup.get_json()
    followup_names = {citation["scheme"] for citation in followup_result["citations"]}
    assert followup_names
    assert first_names.isdisjoint(followup_names)


def test_scholarship_search_with_previous_knowledge_phrase_is_not_misrouted_to_recall(client, app, monkeypatch):
    _register(client)
    _publish(app, _official_record(
        name="Delhi Engineering Merit Scholarship",
        category="Scholarships",
        government_level="CENTRAL",
        jurisdiction="India",
        excerpt="Scholarship for engineering students with academic merit.",
    ))
    captured = {}
    _install_fake_openai(monkeypatch, captured)

    response = client.post("/api/chat", json={"message": (
        "I study at Delhi Technological University and scored 82%. "
        "Suggest scholarships according to my college, marks and previous knowledge."
    )})

    assert response.status_code == 200
    result = response.get_json()
    assert result["citations"]
    assert "Here is what I found in your saved history" not in result["answer"]
    assert "Reviewed evidence" in captured["messages"][1]["content"]
    assert "Relevant personal memory (user statements, for continuity only): []" in captured["messages"][1]["content"]


def test_state_scheme_is_not_eligible_for_residents_of_another_state(client, app, monkeypatch):
    _register(client)
    client.put("/api/profile", json={"age": 20, "student_status": True, "state": "maharashtra"})
    client.post("/api/logout")
    _publish(app, _official_record())
    client.post("/api/login", json={"username": "citizen", "password": "long-test-password"})
    _install_fake_openai(monkeypatch, {})
    result = client.post("/api/chat", json={"message": "Am I eligible for schemes?"}).get_json()
    row = result["eligibility"][0]
    assert row["status"] == "NOT_ELIGIBLE"
    assert row["failed_conditions"][-1]["field"] == "state"


def test_missing_state_is_asked_for_instead_of_assumed(client, app, monkeypatch):
    _register(client)
    client.put("/api/profile", json={"age": 20, "student_status": True})
    client.post("/api/logout")
    _publish(app, _official_record())
    client.post("/api/login", json={"username": "citizen", "password": "long-test-password"})
    _install_fake_openai(monkeypatch, {})
    row = client.post("/api/chat", json={"message": "Am I eligible for schemes?"}).get_json()["eligibility"][0]
    assert row["status"] == "NEEDS_INFORMATION" and "state" in row["missing_fields"]


def test_scheme_without_a_rule_is_reported_as_not_checkable(client, app, monkeypatch):
    _register(client)
    client.post("/api/logout")
    record = _official_record(manual_checks=["Hold a BPL ration card"])
    record.pop("rule")
    _publish(app, record)
    client.post("/api/login", json={"username": "citizen", "password": "long-test-password"})
    _install_fake_openai(monkeypatch, {})
    row = client.post("/api/chat", json={"message": "Am I eligible for schemes?"}).get_json()["eligibility"][0]
    assert row["status"] == "CANNOT_CHECK"
    assert row["manual_checks"] == ["Hold a BPL ration card"]


def test_chat_requires_login_and_verified_knowledge(client):
    assert client.post("/api/chat", json={"message": "schemes"}).status_code == 401
    _register(client)
    response = client.post("/api/chat", json={"message": "schemes"})
    assert response.status_code == 503


def test_profile_rejects_invalid_types_and_chat_rejects_oversized_messages(client):
    _register(client)
    assert client.put("/api/profile", json={"age": "twenty"}).status_code == 400
    assert client.put("/api/profile", json={"date_of_birth": "31-02-2000"}).status_code == 400
    assert client.post("/api/chat", json={"message": "x" * 2001}).status_code == 400


def test_home_page_serves_chat_interface(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Memory Agent" in response.data
