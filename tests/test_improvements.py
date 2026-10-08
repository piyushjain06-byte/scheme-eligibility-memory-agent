"""Tests for normalisation, extraction, jurisdiction, rate limiting, and (DB-backed) memory/consent behaviour."""
from types import SimpleNamespace

import pytest

from agent.eligibility import evaluate_scheme, rule_to_text, scheme_state
from agent.extraction import extract_explicit_facts, parse_llm_facts
from agent.normalize import canonical_state, clean_fact, normalize_memory, normalize_rule, normalize_value

AGE_RULE = {"logic": "AND", "conditions": [{"field": "age", "operator": ">=", "value": 18}]}


def scheme(level="CENTRAL", jurisdiction="India", manual=None):
    source = SimpleNamespace(status="VERIFIED", jurisdiction=jurisdiction)
    return SimpleNamespace(government_level=level, sources=[source], manual_checks=manual or [])


# ---------------- normalisation ----------------
def test_values_have_one_canonical_form():
    assert normalize_value("category", "obc category") == "OBC"
    assert normalize_value("category", "Scheduled Caste") == "SC"
    assert normalize_value("employment_status", "Jobless") == "unemployed"
    assert normalize_value("gender", "Woman") == "female"
    assert normalize_value("state", "maharashtra") == "Maharashtra"
    assert canonical_state("Orissa") == "Odisha"
    assert normalize_memory({"category": "gen"}) == {"category": "GENERAL"}


def test_rules_written_with_different_casing_still_match():
    rule = {"logic": "AND", "conditions": [{"field": "category", "operator": "in", "value": ["sc", "Obc"]}]}
    assert normalize_rule(rule)["conditions"][0]["value"] == ["SC", "OBC"]
    result = evaluate_scheme(scheme(), rule, {"category": "obc category"})
    assert result["status"] == "ELIGIBLE"


def test_clean_fact_rejects_nonsense():
    with pytest.raises(ValueError):
        clean_fact("age", 400)
    with pytest.raises(ValueError):
        clean_fact("student_status", "maybe")
    assert clean_fact("annual_income", 250000.0) == 250000


# ---------------- extraction ----------------
def test_extraction_handles_natural_phrasing():
    assert extract_explicit_facts("I'm 22, from Pune. I earn 30000 per month.") == {
        "age": 22, "state": "Maharashtra", "annual_income": 360000}
    assert extract_explicit_facts("my family income is 2.5 lakhs")["annual_income"] == 250000
    assert extract_explicit_facts("I am a farmer from Bihar")["farmer_status"] is True


def test_extraction_ignores_false_positives():
    assert extract_explicit_facts("I am 5 feet tall") == {}
    assert extract_explicit_facts("If I am 25, can I apply?") == {}
    assert extract_explicit_facts("My father is a farmer and I am a student.") == {"student_status": True}
    assert "occupation" not in extract_explicit_facts("My father is a farmer")


def test_date_of_birth_is_extracted_in_indian_format():
    assert extract_explicit_facts("my dob is 12/05/2003")["date_of_birth"] == "2003-05-12"


def test_llm_output_is_validated_and_grounded():
    text = "I am 30 and live in Kochi"
    assert parse_llm_facts('{"age": 30, "state": "Kerala", "made_up": 1}', text) == {"age": 30, "state": "Kerala"}
    assert parse_llm_facts('{"age": 41}', text) == {}              # number not in the message
    assert parse_llm_facts('{"state": "Goa"}', text) == {}          # place not in the message
    assert parse_llm_facts("not json", text) == {}


# ---------------- jurisdiction + manual checks ----------------
def test_state_scheme_requires_matching_state():
    karnataka = scheme("STATE", "Karnataka")
    assert scheme_state(karnataka) == "Karnataka"
    assert evaluate_scheme(karnataka, AGE_RULE, {"age": 30, "state": "Karnataka"})["status"] == "ELIGIBLE"
    other = evaluate_scheme(karnataka, AGE_RULE, {"age": 30, "state": "Maharashtra"})
    assert other["status"] == "NOT_ELIGIBLE" and other["failed_conditions"][-1]["field"] == "state"
    unknown = evaluate_scheme(karnataka, AGE_RULE, {"age": 30})
    assert unknown["status"] == "NEEDS_INFORMATION" and "state" in unknown["missing_fields"]
    assert evaluate_scheme(karnataka, AGE_RULE, {"age": 10, "state": "Karnataka"})["status"] == "NOT_ELIGIBLE"


def test_central_scheme_ignores_state_and_lists_manual_checks():
    result = evaluate_scheme(scheme(manual=["Hold a BPL ration card"]), AGE_RULE, {"age": 30})
    assert result["status"] == "ELIGIBLE" and result["manual_checks"] == ["Hold a BPL ration card"]


def test_rule_summary_is_readable():
    rule = {"logic": "AND", "conditions": [{"field": "age", "operator": "between", "value": [18, 25]},
                                           {"field": "student_status", "operator": "==", "value": True}]}
    assert rule_to_text(rule) == "(age between 18 and 25 AND student_status == True)"


# ---------------- rate limiting (plain Flask, no database) ----------------
def test_rate_limit_returns_429_then_recovers_per_app():
    from flask import Flask
    from agent.ratelimit import rate_limit

    def make_app():
        app = Flask(__name__)
        app.config["RL"] = 2

        @app.get("/x")
        @rate_limit("x", "RL", 2)
        def view():
            return "ok"
        return app

    client = make_app().test_client()
    assert [client.get("/x").status_code for _ in range(3)] == [200, 200, 429]
    assert make_app().test_client().get("/x").status_code == 200  # a fresh app starts with a clean slate


# ---------------- DB-backed behaviour (needs the project's dependencies installed) ----------------
pytest.importorskip("flask_sqlalchemy")
from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from database.db import db  # noqa: E402
from database.models import User  # noqa: E402
from agent import memory  # noqa: E402
from agent.user_memory import delete_memory, list_memory, save_explicit_facts  # noqa: E402


class StrictConfig(Config):
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True
    OPENAI_API_KEY = None
    REQUIRE_CONSENT = True


@pytest.fixture
def app():
    app = create_app(StrictConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _user(app):
    user = User(username="u1", email="u1@test.com", role="citizen")
    user.set_password("long-test-password")
    db.session.add(user)
    db.session.commit()
    return user


def test_profile_form_facts_show_up_in_memory_list_and_forgetting_clears_both(app):
    user = _user(app)
    memory.update_profile(user.id, age=30, state="karnataka", category="obc")
    facts = {f["key"]: f for f in list_memory(user.id)}
    assert facts["state"]["value"] == "Karnataka" and facts["category"]["value"] == "OBC"
    assert facts["age"]["source"] == "profile" and facts["age"]["confirmed"] is True
    delete_memory(user.id, "state")
    assert memory.get_memory_dict(user.id)["state"] is None
    assert "state" not in {f["key"] for f in list_memory(user.id)}


def test_chat_facts_are_unconfirmed_and_report_what_changed(app):
    user = _user(app)
    first = save_explicit_facts(user.id, "I am 21 and from Pune")
    assert {item["key"] for item in first} == {"age", "state"}
    assert all(f["confirmed"] is False and f["source"] == "chat" for f in list_memory(user.id))
    second = save_explicit_facts(user.id, "I am 22")
    assert second == [{"key": "age", "value": 22, "previous": 21}]


def test_date_of_birth_keeps_age_current(app):
    from datetime import date
    user = _user(app)
    memory.update_profile(user.id, date_of_birth="2000-06-15")
    today = date.today()
    expected = today.year - 2000 - ((today.month, today.day) < (6, 15))
    assert memory.get_memory_dict(user.id)["age"] == expected
    memory.update_profile(user.id, age=expected + 5)  # an explicit different age replaces the DOB
    assert memory.get_profile(user.id).date_of_birth is None


def test_registration_requires_consent_and_account_can_be_deleted(app):
    client = app.test_client()
    body = {"username": "citizen", "email": "c@example.test", "password": "long-test-password"}
    assert client.post("/api/register", json=body).status_code == 400
    assert client.post("/api/register", json={**body, "consent": True}).status_code == 201
    client.put("/api/profile", json={"age": 20})
    export = client.get("/api/account/export").get_json()
    assert export["profile"]["age"] == 20 and export["user"]["consent_at"]
    assert client.delete("/api/account", json={"password": "wrong-password!"}).status_code == 403
    assert client.delete("/api/account", json={"password": "long-test-password"}).status_code == 200
    assert client.get("/api/profile").status_code == 401
    assert User.query.filter_by(username="citizen").first() is None


def test_login_is_rate_limited(app):
    app.config["RATE_LIMIT_LOGIN"] = 3
    client = app.test_client()
    codes = [client.post("/api/login", json={"username": "nobody", "password": "x"}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]
