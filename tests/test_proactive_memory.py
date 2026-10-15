from datetime import datetime, timedelta

import pytest

from app import create_app
from database.db import db
from database.models import Notification, User, UserTask
from agent.notification_service import process_due_tasks
from agent.task_detection import process_message


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


def _user():
    user = User(username="citizen", email="citizen@example.test", password_hash="x")
    db.session.add(user)
    db.session.commit()
    return user


def test_task_detection_skips_hypotheticals_and_deduplicates(app):
    with app.app_context():
        user = _user()
        assert process_message(user.id, "If I wanted to apply for a scholarship, I might need an income certificate", 1, 1) is None
        first = process_message(user.id, "I want to apply for a scholarship; I still need my income certificate", 1, 2)
        second = process_message(user.id, "I need my income certificate for the scholarship", 1, 3)
        assert first.id == second.id
        assert UserTask.query.filter_by(user_id=user.id).count() == 1


def test_completion_stops_task_reminders_and_snooze_is_respected(app):
    with app.app_context():
        user = _user()
        task = UserTask(user_id=user.id, title="Collect income certificate", status="PENDING",
                        created_at=datetime.utcnow() - timedelta(days=2))
        db.session.add(task)
        db.session.commit()
        task.snoozed_until = datetime.utcnow() + timedelta(hours=2)
        db.session.commit()
        assert process_due_tasks() == 0
        process_message(user.id, "I collected my income certificate yesterday", 1, 10)
        db.session.commit()
        task = db.session.get(UserTask, task.id)
        assert task.status == "COMPLETED"
        assert process_due_tasks() == 0
        assert Notification.query.filter_by(citizen_id=user.id).count() == 0


def test_scheduler_is_idempotent_and_respects_disabled_preference(app):
    from database.models import NotificationPreference
    with app.app_context():
        user = _user()
        task = UserTask(user_id=user.id, title="Upload documents", status="PENDING",
                        created_at=datetime.utcnow() - timedelta(days=2))
        db.session.add(task)
        db.session.add(NotificationPreference(user_id=user.id, enabled=False))
        db.session.commit()
        assert process_due_tasks() == 0
        db.session.get(NotificationPreference, user.id).enabled = True
        db.session.commit()
        assert process_due_tasks() == 1
        assert process_due_tasks() == 0
        assert Notification.query.filter_by(citizen_id=user.id).count() == 1


def test_task_api_is_user_scoped(app):
    with app.app_context():
        owner = User(username="owner", email="owner@example.test")
        owner.set_password("owner-password")
        other = User(username="other", email="other@example.test")
        other.set_password("other-password")
        db.session.add_all([owner, other])
        db.session.commit()
        task = UserTask(user_id=other.id, title="Private application")
        db.session.add(task)
        db.session.commit()
        task_id = task.id
    client = app.test_client()
    assert client.post("/api/login", json={"username": "owner", "password": "owner-password"}).status_code == 200
    assert client.get("/api/tasks").json["tasks"] == []
    assert client.patch(f"/api/tasks/{task_id}", json={"status": "COMPLETED"}).status_code == 404
