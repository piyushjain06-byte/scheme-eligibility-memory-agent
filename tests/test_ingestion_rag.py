import pytest

from app import create_app
from database.db import db
from database.models import DocumentChunk, EligibilityEvaluation, EligibilityRule, GovernmentDocument, Notification, Scheme, SchemeSource, User
from agent.ingestion import DatasetValidationError, import_records, load_dataset
from agent.rag import retrieve
from agent.chat import answer_chat
from agent.memory import update_profile
from agent.change_detection import reevaluate_scheme


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def record(**overrides):
    value = {
        "Scheme Name": "Verified Student Support", "Ministry": "Education Ministry",
        "Objective": "Support education for students", "Eligibility": "Students aged 18 or older",
        "Benefits": "Tuition assistance", "Required Documents": ["Identity proof"],
        "Application Process": "Apply through the official portal", "State/Central": "CENTRAL",
        "Category": "Education", "Source URL": "https://example.gov.in/student-support",
        "Last Updated": "2026-01-10", "Source Verified": True,
        "Source Type": "OFFICIAL_PAGE", "Scheme Status": "ACTIVE", "Exclusions": "None",
        "rule": {"logic": "AND", "conditions": [{"field": "age", "operator": ">=", "value": 18}]},
    }
    value.update(overrides)
    return value


def test_json_import_normalizes_schema_and_is_idempotent(app):
    with app.app_context():
        first = import_records([record()])
        second = import_records([record()])
        assert first == {"created": 1, "updated": 0, "skipped": 0, "total": 1}
        assert second["created"] == 0 and second["updated"] == 1
        result = retrieve("student tuition assistance", include_demo=False)
        assert result
        assert result[0]["scheme_name"] == "Verified Student Support"
        assert result[0]["verification_status"] == "VERIFIED"
        chunk = DocumentChunk.query.join(GovernmentDocument).filter(GovernmentDocument.source_type == "STRUCTURED_SCHEME").one()
        chunk.embedding = [1.0, 0.0]
        semantic = retrieve("unrelated wording", embedding=[1.0, 0.0])
        assert semantic[0]["chunk_id"] == chunk.id and semantic[0]["score"] == pytest.approx(1.0)


def test_demo_cannot_be_imported_as_verified_and_is_excluded_from_public_retrieval(app):
    with app.app_context():
        demo = record(**{"Scheme Name": "Test Only", "Source Verified": True,
                         "State/Central": "DEMO", "Source URL": "https://example.gov.demo/test"})
        import_records([demo])
        assert retrieve("tuition assistance", include_demo=False) == []
        assert retrieve("tuition assistance", include_demo=True, verified_only=False)


def test_unverified_scheme_is_pending_and_its_rule_is_not_active(app):
    with app.app_context():
        import_records([record(**{"Source Verified": False})])
        scheme = Scheme.query.filter_by(name="Verified Student Support").one()
        source = SchemeSource.query.filter_by(scheme_id=scheme.id).one()
        assert source.status == "PENDING"
        assert source.proposed_rule_json is not None
        assert scheme.latest_rule() is None


def test_duplicate_rows_are_rejected():
    with pytest.raises(DatasetValidationError, match="Duplicate scheme"):
        import_records([record(), record()])
    with pytest.raises(DatasetValidationError, match="Duplicate scheme"):
        from agent.ingestion import normalize_record
        from agent.ingestion import load_dataset
        import tempfile, json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as handle:
            json.dump([record(), record()], handle)
            path = handle.name
        try:
            load_dataset(path)
        finally:
            import os
            os.unlink(path)


def test_invalid_date_and_boolean_are_rejected():
    from agent.ingestion import normalize_record
    with pytest.raises(DatasetValidationError, match="last_updated"):
        normalize_record(record(**{"Last Updated": "not-a-date"}))
    with pytest.raises(DatasetValidationError, match="source_verified"):
        normalize_record(record(**{"Source Verified": "sometimes"}))


def test_demo_chat_is_explicitly_labeled_and_never_cites_placeholder_url(app):
    with app.app_context():
        demo = record(**{"Scheme Name": "Demo Student Grant", "State/Central": "DEMO",
                         "Source Verified": False, "is_demo": True})
        import_records([demo])
        user = User(username="demo-user", email="demo@example.test", password_hash="unused")
        db.session.add(user)
        db.session.commit()
        update_profile(user.id, age=21, student_status=True, annual_income=200000)
        result = answer_chat(user.id, "What schemes can I apply for?", None, None)
        assert result["demo"] is True
        assert "DEMO / TEST DATA ONLY" in result["answer"]
        assert result["citations"] == []
        assert "example.gov.demo" not in result["answer"]
        assert result["eligibility"][0]["status"] == "ELIGIBLE"
        followup = answer_chat(user.id, "What documents do I need?", None, None,
            history=[{"role": "assistant", "content": result["answer"]}])
        assert "Demo Student Grant" in followup["answer"]
        assert "No official application link or documents" in followup["answer"]


def test_admin_dataset_errors_are_saved_for_review(app):
    with app.app_context():
        admin = User(username="admin", email="admin@example.test", role="admin")
        admin.set_password("long-test-password")
        db.session.add(admin)
        db.session.commit()
    client = app.test_client()
    client.post("/api/login", json={"username": "admin", "password": "long-test-password"})
    response = client.post("/api/admin/schemes/import", json={"records": [{"Scheme Name": "Incomplete"}]})
    assert response.status_code == 400
    errors = client.get("/api/admin/ingestion/errors").json["errors"]
    assert len(errors) == 1
    assert "missing required fields" in errors[0]["error"]


def test_manual_reevaluation_notifies_only_on_new_eligibility(app):
    with app.app_context():
        user = User(username="change-user", email="change@example.test", password_hash="unused")
        scheme = Scheme(name="Rule change test", is_demo=True, government_level="DEMO")
        db.session.add_all([user, scheme])
        db.session.flush()
        db.session.add(EligibilityRule(scheme_id=scheme.id,
            rule_json={"field": "age", "operator": ">=", "value": 18}, version=1))
        update_profile(user.id, age=17)
        assert reevaluate_scheme(scheme)["newly_eligible"] == 0
        update_profile(user.id, age=18)
        assert reevaluate_scheme(scheme)["newly_eligible"] == 1
        assert reevaluate_scheme(scheme)["newly_eligible"] == 0
        assert Notification.query.filter_by(citizen_id=user.id, scheme_id=scheme.id).count() == 1
        assert EligibilityEvaluation.query.filter_by(citizen_id=user.profile.id, scheme_id=scheme.id).count() == 3
