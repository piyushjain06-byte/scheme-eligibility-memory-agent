"""
Unit tests for agent/memory.py. Uses an in-memory SQLite DB via the app
factory so tests never touch the real dev database file.

Run with: python -m pytest tests/test_memory.py -v
"""

import pytest

from app import create_app
from config import Config
from database.db import db
from database.models import User, CitizenProfile
from agent import memory


class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    TESTING = True


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def user(app):
    u = User(username="citizen1", email="c1@test.com", role="citizen")
    u.set_password("pw")
    db.session.add(u)
    db.session.commit()
    return u


# ---------------------------------------------------------------------
# get_profile / get_or_create_profile
# ---------------------------------------------------------------------

def test_get_profile_returns_none_when_absent(app, user):
    assert memory.get_profile(user.id) is None


def test_get_or_create_profile_creates_empty_profile(app, user):
    profile = memory.get_or_create_profile(user.id)
    assert profile.id is not None
    assert profile.user_id == user.id
    assert profile.age is None


def test_get_or_create_profile_is_idempotent(app, user):
    first = memory.get_or_create_profile(user.id)
    second = memory.get_or_create_profile(user.id)
    assert first.id == second.id


# ---------------------------------------------------------------------
# save_profile / update_profile
# ---------------------------------------------------------------------

def test_save_profile_sets_fields(app, user):
    profile = memory.save_profile(user.id, age=22, student_status=True, annual_income=180000)
    assert profile.age == 22
    assert profile.student_status is True
    assert profile.annual_income == 180000


def test_update_profile_merges_without_clearing_existing_fields(app, user):
    memory.save_profile(user.id, age=22, gender="female")
    updated = memory.update_profile(user.id, annual_income=150000)
    # earlier fields must still be there — the agent never forgets what
    # it already knows just because a later call didn't repeat it
    assert updated.age == 22
    assert updated.gender == "female"
    assert updated.annual_income == 150000


def test_update_profile_none_values_do_not_overwrite_existing_data(app, user):
    memory.save_profile(user.id, age=22)
    updated = memory.update_profile(user.id, age=None, gender="male")
    assert updated.age == 22  # untouched
    assert updated.gender == "male"


def test_update_profile_ignores_unknown_fields(app, user):
    profile = memory.update_profile(user.id, age=30, not_a_real_field="whatever")
    assert profile.age == 30
    assert not hasattr(profile, "not_a_real_field") or getattr(profile, "not_a_real_field", None) is None


# ---------------------------------------------------------------------
# get_memory_dict
# ---------------------------------------------------------------------

def test_get_memory_dict_all_none_when_no_profile(app, user):
    mem = memory.get_memory_dict(user.id)
    assert set(mem.keys()) == set(CitizenProfile.RULE_FIELDS)
    assert all(v is None for v in mem.values())


def test_get_memory_dict_reflects_saved_fields(app, user):
    memory.save_profile(user.id, age=25, occupation="farmer")
    mem = memory.get_memory_dict(user.id)
    assert mem["age"] == 25
    assert mem["occupation"] == "farmer"
    assert mem["gender"] is None


# ---------------------------------------------------------------------
# get_missing_attributes / is_profile_complete / profile_completion
# ---------------------------------------------------------------------

def test_get_missing_attributes_no_profile_returns_all_fields(app, user):
    missing = memory.get_missing_attributes(user.id)
    assert set(missing) == set(CitizenProfile.RULE_FIELDS)


def test_get_missing_attributes_narrows_to_requested_fields(app, user):
    memory.save_profile(user.id, age=25)
    missing = memory.get_missing_attributes(user.id, fields=["age", "gender", "annual_income"])
    assert missing == ["gender", "annual_income"]


def test_get_missing_attributes_empty_once_all_filled(app, user):
    all_fields = {f: True for f in CitizenProfile.RULE_FIELDS}
    # give numeric-looking fields sane types instead of blanket True
    all_fields.update({"age": 30, "annual_income": 50000.0, "family_size": 3,
                        "gender": "female", "state": "MH", "district": "Pune",
                        "occupation": "teacher", "education_level": "graduate",
                        "marital_status": "single", "employment_status": "employed",
                        "category": "GENERAL"})
    memory.save_profile(user.id, **all_fields)
    assert memory.get_missing_attributes(user.id) == []
    assert memory.is_profile_complete(user.id) is True


def test_is_profile_complete_false_when_fields_missing(app, user):
    memory.save_profile(user.id, age=25)
    assert memory.is_profile_complete(user.id) is False


def test_profile_completion_percentage(app, user):
    assert memory.profile_completion(user.id) == 0
    memory.save_profile(user.id, age=25)
    pct = memory.profile_completion(user.id)
    assert 0 < pct < 100


def test_profile_completion_zero_when_no_profile_row(app, user):
    assert memory.profile_completion(user.id) == 0