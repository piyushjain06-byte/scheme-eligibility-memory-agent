"""Conservative deterministic extraction of actionable work from citizen messages."""
import re
from datetime import date, datetime, time, timedelta

from database.db import db
from database.models import EpisodicMemory, TaskEvent, UserGoal, UserTask

_HYPOTHETICAL = re.compile(r"\b(if i|suppose|imagine|hypothetically|for example|might want to|could apply)\b", re.I)
_DONE = re.compile(r"\b(collected|got|received|submitted|uploaded|completed|finished|done|already have)\b", re.I)
_ACTION = re.compile(r"\b(need to|need my|still need|want to|plan to|started|haven't finished|have not finished|waiting for|must)\b", re.I)
_ITEM = re.compile(r"\b(income certificate|caste certificate|domicile certificate|disability certificate|documents?|application|scholarship|application status|bank account| Aadhaar)\b", re.I)
_SCHEME_MENTION = re.compile(r"\b(schemes?|scholarships?|pensions?|benefits?)\b", re.I)
_SCHEME_SEARCH_ACTION = re.compile(
    r"\b(which|what|find|search|recommend|suggest|list|show|give|tell|apply|eligible|qualify)\b", re.I)
_APPLICATION_COMPLETION = re.compile(
    r"\b(?:i\s+(?:(?:have|just)\s+)?(?:finished|completed|submitted|applied)|"
    r"i(?:'ve| have)\s+(?:finished|completed|submitted|applied)|"
    r"i\s+am\s+done\s+(?:with\s+)?(?:applying|the application))\b",
    re.I,
)


def is_scheme_search_request(text):
    """Whether the user is asking for scheme recommendations rather than discussing one scheme."""
    return bool(_SCHEME_MENTION.search(text or "") and _SCHEME_SEARCH_ACTION.search(text or ""))


def is_application_completion_message(text):
    """Whether the user explicitly says they submitted/applied for an application."""
    return bool(text and not _HYPOTHETICAL.search(text) and _APPLICATION_COMPLETION.search(text))


def create_scheme_application_tasks(user_id, scheme_ids, conversation_id, message_id):
    """Track recommended real schemes as idempotent open application tasks and notifications."""
    from database.models import Notification, NotificationPreference, Scheme

    created = []
    for scheme_id in dict.fromkeys(scheme_ids or []):
        scheme = db.session.get(Scheme, scheme_id)
        if scheme is None or not scheme.active or scheme.is_demo:
            continue
        existing = UserTask.query.filter_by(user_id=user_id, scheme_id=scheme.id).order_by(
            UserTask.updated_at.desc()).first()
        if existing:
            continue
        title = f"Apply for {scheme.name}"
        task = UserTask(
            user_id=user_id, scheme_id=scheme.id, conversation_id=conversation_id,
            source_message_id=message_id, title=title,
            description="Scheme recommended in chat. Ask the assistant for application steps, then tell it when you have applied.",
            next_action=f"Review the application steps for {scheme.name}",
            status="PENDING",
        )
        db.session.add(task)
        db.session.flush()
        db.session.add(TaskEvent(
            task_id=task.id, to_status="PENDING", source_message_id=message_id,
            note="Created from a scheme recommendation",
        ))
        preference = db.session.get(NotificationPreference, user_id)
        if preference is None or preference.enabled:
            db.session.add(Notification(
                citizen_id=user_id, scheme_id=scheme.id, title="Scheme added to unfinished tasks",
                message=title, notification_type="TASK_REMINDER",
                dedupe_key=f"task:{task.id}:recommended",
            ))
        created.append(task)
    return created


def complete_scheme_application_tasks(user_id, text, message_id):
    """Complete matching application tasks after an explicit first-person completion statement."""
    from database.models import Notification, Scheme

    if not is_application_completion_message(text):
        return []
    tasks = UserTask.query.filter_by(user_id=user_id).filter(
        UserTask.scheme_id.isnot(None),
        UserTask.status.in_(["PENDING", "IN_PROGRESS", "WAITING", "SNOOZED"]),
    ).order_by(UserTask.updated_at.desc()).all()
    normalized_text = " ".join(re.findall(r"[a-z0-9]+", text.lower()))
    mentioned = [
        task for task in tasks
        if (scheme := db.session.get(Scheme, task.scheme_id)) is not None
        and " ".join(re.findall(r"[a-z0-9]+", scheme.name.lower())) in normalized_text
    ]
    if mentioned:
        matched = mentioned
    elif len(tasks) == 1 and not re.search(r"\bfor\s+\w+", text, re.I):
        matched = tasks
    else:
        return []

    now = datetime.utcnow()
    for task in matched:
        previous = task.status
        task.status = "COMPLETED"
        task.completed_at = now
        task.verified = True
        task.snoozed_until = None
        task.updated_at = now
        db.session.add(TaskEvent(
            task_id=task.id, from_status=previous, to_status="COMPLETED",
            source_message_id=message_id, note=text[:500],
        ))
        Notification.query.filter_by(
            citizen_id=user_id, dedupe_key=f"task:{task.id}:recommended",
        ).update({"is_read": True}, synchronize_session=False)
    return matched


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
