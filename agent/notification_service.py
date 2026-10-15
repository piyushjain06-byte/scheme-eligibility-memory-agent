"""Idempotent in-app reminders for due, unfinished tasks."""
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError

from database.db import db
from database.models import Notification, NotificationPreference, UserTask


def _quiet_now(pref, now):
    if not pref or not pref.quiet_start or not pref.quiet_end:
        return False
    try:
        current = (now + timedelta(minutes=pref.timezone_offset_minutes or 0)).strftime("%H:%M")
        if pref.quiet_start <= pref.quiet_end:
            return pref.quiet_start <= current < pref.quiet_end
        return current >= pref.quiet_start or current < pref.quiet_end
    except (TypeError, ValueError):
        return False


def process_due_tasks(now=None, cooldown_hours=24):
    """Create at most one reminder per task per cooldown; safe to rerun from cron."""
    now = now or datetime.utcnow()
    sent = 0
    tasks = UserTask.query.filter(UserTask.status.in_(["PENDING", "IN_PROGRESS", "WAITING", "SNOOZED"])).all()
    for task in tasks:
        pref = db.session.get(NotificationPreference, task.user_id)
        if pref and not pref.enabled or _quiet_now(pref, now):
            continue
        due = task.due_at or task.created_at + timedelta(days=1)
        if due > now or task.snoozed_until and task.snoozed_until > now:
            continue
        if task.last_notified_at and task.last_notified_at > now - timedelta(hours=cooldown_hours):
            continue
        bucket = int(now.timestamp() // (cooldown_hours * 3600))
        try:
            with db.session.begin_nested():
                db.session.add(Notification(citizen_id=task.user_id, scheme_id=task.scheme_id,
                    title="A task is waiting for you", message=task.title, notification_type="TASK_REMINDER",
                    dedupe_key=f"task:{task.id}:reminder:{bucket}"))
                db.session.flush()
        except IntegrityError:
            continue
        task.last_notified_at = now
        task.notification_count = (task.notification_count or 0) + 1
        sent += 1
    db.session.commit()
    return sent
