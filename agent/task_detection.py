"""Conservative deterministic extraction of actionable work from citizen messages."""
import re
from datetime import date, datetime, time, timedelta

from database.db import db
from database.models import EpisodicMemory, TaskEvent, UserGoal, UserTask

_HYPOTHETICAL = re.compile(r"\b(if i|suppose|imagine|hypothetically|for example|might want to|could apply)\b", re.I)
_DONE = re.compile(r"\b(collected|got|received|submitted|uploaded|completed|finished|done|already have)\b", re.I)
_ACTION = re.compile(r"\b(need to|need my|still need|want to|plan to|started|haven't finished|have not finished|waiting for|must)\b", re.I)
_ITEM = re.compile(r"\b(income certificate|caste certificate|domicile certificate|disability certificate|documents?|application|scholarship|application status|bank account| Aadhaar)\b", re.I)


def _task_title(text):
    certificate = re.search(r"\b(income certificate|caste certificate|domicile certificate|disability certificate)\b", text, re.I)
    item = certificate or _ITEM.search(text)
    if not item:
        return None
    phrase = item.group(0).strip()
    if certificate:
        return "Collect " + phrase.lower()
    return phrase[0].upper() + phrase[1:].lower()


def process_message(user_id, text, conversation_id, message_id):
    """Record actionable task progress and meaningful events; never infer completion silently."""
    text = (text or "").strip()
    if not text or _HYPOTHETICAL.search(text):
        return None
    title = _task_title(text)
    if not title:
        return None
    existing = (UserTask.query.filter_by(user_id=user_id).filter(
        db.func.lower(UserTask.title) == title.lower()
    ).order_by(UserTask.updated_at.desc()).first())
    completed = bool(_DONE.search(text))
    actionable = bool(_ACTION.search(text))
    now = datetime.utcnow()
    if existing and completed and existing.status not in {"COMPLETED", "CANCELLED"}:
        old = existing.status
        existing.status, existing.completed_at, existing.verified = "COMPLETED", now, True
        existing.snoozed_until = None
        db.session.add(TaskEvent(task_id=existing.id, from_status=old, to_status="COMPLETED", source_message_id=message_id, note=text[:500]))
    elif actionable and not completed:
        goal = UserGoal.query.filter_by(user_id=user_id, status="ACTIVE").filter(
            db.func.lower(UserGoal.title).like("%scholarship%")
        ).first() if "scholarship" in text.lower() else None
        if "scholarship" in text.lower() and goal is None:
            goal = UserGoal(user_id=user_id, title="Find and apply for a suitable scholarship", description="Scholarship search and application")
            db.session.add(goal)
            db.session.flush()
        if existing:
            old = existing.status
            if existing.status in {"COMPLETED", "CANCELLED"}:
                existing.status, existing.completed_at = "PENDING", None
            existing.description = text[:1000]
            existing.goal_id = existing.goal_id or (goal.id if goal else None)
            existing.updated_at = now
            if old != existing.status:
                db.session.add(TaskEvent(task_id=existing.id, from_status=old, to_status=existing.status, source_message_id=message_id))
            task = existing
        else:
            task = UserTask(user_id=user_id, goal_id=goal.id if goal else None, conversation_id=conversation_id,
                            source_message_id=message_id, title=title, description=text[:1000],
                            next_action=title, status="PENDING")
            if re.search(r"\btomorrow\b", text, re.I):
                task.due_at = datetime.combine(date.today() + timedelta(days=1), time(9, 0))
            elif re.search(r"\btoday\b", text, re.I):
                task.due_at = datetime.utcnow()
            db.session.add(task)
            db.session.flush()
            db.session.add(TaskEvent(task_id=task.id, to_status="PENDING", source_message_id=message_id, note="Extracted from a direct action statement"))
        if goal:
            db.session.add(EpisodicMemory(user_id=user_id, conversation_id=conversation_id, source_message_id=message_id,
                                          event_type="GOAL_PROGRESS", summary=text[:1000], verification="USER_STATED"))
        return task
    return existing if completed else None
