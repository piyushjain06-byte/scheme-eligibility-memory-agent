"""Session-based API for citizen memory, chat, and source review."""

from datetime import date, datetime, timezone
from functools import wraps
import math
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, request, session

from database.db import db
from database.models import CitizenProfile, Conversation, EligibilityRule, EpisodicMemory, GovernmentDocument, IngestionRun, Message, Notification, NotificationPreference, Scheme, SchemeSource, TaskEvent, User, UserGoal, UserMemory, UserTask
from agent import memory
from agent.chat import (
    ChatConfigurationError,
    KnowledgeBaseUnavailableError,
    answer_chat,
)
from agent.eligibility import rule_to_text
from agent.normalize import canonical_state
from agent.ratelimit import rate_limit
from agent.rule_engine import InvalidRuleError, evaluate_rule
from agent.user_memory import confirm_memory, delete_memory, list_memory, save_explicit_facts
from agent.task_detection import process_message as process_task_message
from agent.memory_retrieval import retrieve_personal_context

api_bp = Blueprint("api", __name__)

PROFILE_STRING_LIMITS = {
    "full_name": 120,
    "gender": 20,
    "state": 80,
    "district": 80,
    "occupation": 80,
    "education_level": 80,
    "marital_status": 30,
    "employment_status": 30,
    "category": 30,
}
PROFILE_BOOLEAN_FIELDS = {"disability_status", "student_status", "farmer_status"}


def _json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None
    return body


def _profile_validation_error(fields):
    for name, value in fields.items():
        if value is None:
            continue
        if name in PROFILE_BOOLEAN_FIELDS:
            if not isinstance(value, bool):
                return f"{name} must be a boolean"
        elif name == "age":
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 130:
                return "age must be an integer from 0 to 130"
        elif name == "family_size":
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                return "family_size must be a positive integer"
        elif name == "annual_income":
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or (isinstance(value, float) and not math.isfinite(value))
                or value < 0
                or value > 10**15
            ):
                return "annual_income must be a finite non-negative number"
        elif name == "date_of_birth":
            try:
                dob = date.fromisoformat(value) if isinstance(value, str) else None
            except ValueError:
                dob = None
            if dob is None:
                return "date_of_birth must be a date in YYYY-MM-DD format"
            if dob > date.today() or date.today().year - dob.year > 130:
                return "date_of_birth is out of range"
        elif not isinstance(value, str) or len(value) > PROFILE_STRING_LIMITS[name]:
            return f"{name} must be a string no longer than {PROFILE_STRING_LIMITS[name]} characters"
    return None


def _authenticated_user():
    user_id = session.get("user_id")
    return db.session.get(User, user_id) if user_id is not None else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if _authenticated_user() is None:
            return jsonify(error="Authentication required"), 401
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _authenticated_user()
        if user is None:
            return jsonify(error="Authentication required"), 401
        if not user.is_admin():
            return jsonify(error="Administrator access required"), 403
        return view(*args, **kwargs)

    return wrapped


@api_bp.post("/register")
@rate_limit("register", "RATE_LIMIT_REGISTER", 5)
def register():
    body = _json_body()
    if body is None:
        return jsonify(error="A JSON object is required"), 400
    username = body.get("username")
    email = body.get("email")
    password = body.get("password")
    if not all(isinstance(value, str) and value.strip() for value in (username, email, password)):
        return jsonify(error="username, email, and password are required"), 400
    if len(password) < 12 or len(password) > 256:
        return jsonify(error="Password must be between 12 and 256 characters"), 400
    if len(username.strip()) > 80 or len(email.strip()) > 120:
        return jsonify(error="username or email is too long"), 400
    consent = body.get("consent") is True
    if current_app.config.get("REQUIRE_CONSENT", False) and not consent:
        return jsonify(error="You must agree to the storage of your profile details to register"), 400
    if User.query.filter(
        db.or_(User.username == username.strip(), User.email == email.strip().lower())
    ).first():
        return jsonify(error="Username or email is already registered"), 409

    user = User(username=username.strip(), email=email.strip().lower(), role="citizen",
                consent_at=datetime.utcnow() if consent else None)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    session.clear()
    session["user_id"] = user.id
    return jsonify(user=user.to_dict()), 201


@api_bp.post("/login")
@rate_limit("login", "RATE_LIMIT_LOGIN", 10)
def login():
    body = _json_body()
    if body is None:
        return jsonify(error="A JSON object is required"), 400
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify(error="username and password are required"), 400

    user = User.query.filter_by(username=username.strip()).first()
    if user is None or not user.check_password(password):
        return jsonify(error="Invalid username or password"), 401
    session.clear()
    session["user_id"] = user.id
    return jsonify(user=user.to_dict())


@api_bp.post("/logout")
def logout():
    session.clear()
    return jsonify(status="ok")


@api_bp.get("/profile")
@login_required
def get_profile():
    user = _authenticated_user()
    profile = memory.get_or_create_profile(user.id)
    return jsonify(profile=profile.to_dict())


@api_bp.put("/profile")
@login_required
def update_profile():
    body = _json_body()
    if body is None:
        return jsonify(error="A JSON object is required"), 400
    allowed = set(CitizenProfile.RULE_FIELDS)
    allowed.update({"full_name", "date_of_birth"})
    unknown = set(body) - allowed
    if unknown:
        return jsonify(error="Unknown profile fields", fields=sorted(unknown)), 400
    validation_error = _profile_validation_error(body)
    if validation_error:
        return jsonify(error=validation_error), 400
    profile = memory.update_profile(_authenticated_user().id, source="profile", **body)
    return jsonify(profile=profile.to_dict())


@api_bp.post("/chat")
@login_required
@rate_limit("chat", "RATE_LIMIT_CHAT", 20, per_user=True)
def chat():
    body = _json_body()
    if body is None or not isinstance(body.get("message"), str):
        return jsonify(error="message must be a string"), 400
    if len(body["message"]) > 2000:
        return jsonify(error="message must be no longer than 2000 characters"), 400
    user_id = _authenticated_user().id
    conversation_id = body.get("conversation_id")
    conversation = db.session.get(Conversation, conversation_id) if conversation_id else None
    if conversation is not None and conversation.user_id != user_id:
        return jsonify(error="Conversation not found"), 404
    if conversation is None:
        conversation = Conversation(user_id=user_id, title=body["message"].strip()[:160])
        db.session.add(conversation)
        db.session.flush()
    # Keep continuity from previous assistant replies without forwarding prior
    # user messages (which may contain personal details) to the hosted model.
    history = [{"role": "assistant", "content": item.content}
               for item in conversation.messages if item.role == "assistant"][-5:]
    conversation.updated_at = datetime.now(timezone.utc)
    user_message = Message(conversation_id=conversation.id, role="user", content=body["message"])
    db.session.add(user_message)
    db.session.flush()
    llm = None
    if current_app.config.get("LLM_MEMORY_EXTRACTION") and current_app.config.get("OPENAI_API_KEY"):
        llm = {"api_key": current_app.config["OPENAI_API_KEY"],
               "model": current_app.config.get("OPENAI_EXTRACTION_MODEL",
                          current_app.config.get("OPENAI_CHAT_MODEL", "gemini-3.5-flash-lite"))}
    remembered = save_explicit_facts(user_id, body["message"], user_message.id, llm=llm)
    process_task_message(user_id, body["message"], conversation.id, user_message.id)
    personal_context = retrieve_personal_context(user_id, body["message"])
    recall_request = any(term in body["message"].lower() for term in
                         ("last week", "previous", "previously", "what did we", "which scheme did",
                          "what documents did i still need", "continue helping", "continue my",
                          "what did you say", "what did i say", "recall", "remember what",
                          "from before", "as i said", "what i told you", "from last time",
                          "earlier you said", "you told me", "continue from", "going back to"))
    try:
        result = ({"answer": "Here is what I found in your saved history: " + " ".join(personal_context),
                   "citations": [], "eligibility": [], "focus_scheme_ids": conversation.focus_scheme_ids or []}
                  if recall_request and personal_context else
                  {"answer": "I don't have a saved relevant conversation or unfinished task to recall yet. Tell me which application or scheme you mean, and I can help continue.",
                   "citations": [], "eligibility": [], "focus_scheme_ids": conversation.focus_scheme_ids or []}
                  if recall_request else answer_chat(
            user_id=user_id,
            message=body["message"],
            api_key=current_app.config.get("OPENAI_API_KEY"),
            model=current_app.config.get("OPENAI_CHAT_MODEL"),
            history=history,
            embedding_model=current_app.config.get("EMBEDDING_MODEL", "text-embedding-3-small"),
            focus_scheme_ids=conversation.focus_scheme_ids,
            personal_context=personal_context,
        ))
    except ChatConfigurationError as exc:
        return jsonify(error=str(exc), remembered=remembered), 503
    except KnowledgeBaseUnavailableError as exc:
        return jsonify(error=str(exc), remembered=remembered), 503
    except ValueError as exc:
        return jsonify(error=str(exc), remembered=remembered), 400
    if result.get("focus_scheme_ids"):
        conversation.focus_scheme_ids = result["focus_scheme_ids"]
        for scheme_id in result["focus_scheme_ids"][:5]:
            scheme = db.session.get(Scheme, scheme_id)
            if scheme:
                db.session.add(EpisodicMemory(user_id=user_id, conversation_id=conversation.id,
                    source_message_id=user_message.id, scheme_id=scheme_id, event_type="SCHEME_DISCUSSION",
                    summary=f"Discussed {scheme.name}: {body['message'][:700]}", verification="USER_STATED"))
    db.session.add(Message(conversation_id=conversation.id, role="assistant", content=result["answer"]))
    db.session.commit()
    return jsonify({**result, "conversation_id": conversation.id, "memory": list_memory(user_id),
                    "remembered": remembered})


@api_bp.get("/memory")
@login_required
def get_memory():
    user = _authenticated_user()
    profile = memory.get_or_create_profile(user.id)
    return jsonify(profile=profile.to_dict(), facts=list_memory(user.id))


@api_bp.get("/tasks")
@login_required
def list_tasks():
    user_id = _authenticated_user().id
    rows = UserTask.query.filter_by(user_id=user_id).order_by(UserTask.updated_at.desc()).all()
    return jsonify(tasks=[{"id": t.id, "goal_id": t.goal_id, "title": t.title, "description": t.description,
        "next_action": t.next_action, "status": t.status, "priority": t.priority,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "snoozed_until": t.snoozed_until.isoformat() if t.snoozed_until else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "verified": t.verified, "notification_count": t.notification_count} for t in rows])


@api_bp.patch("/tasks/<int:task_id>")
@login_required
def update_task(task_id):
    user_id = _authenticated_user().id
    task = UserTask.query.filter_by(id=task_id, user_id=user_id).first()
    if task is None:
        return jsonify(error="Task not found"), 404
    body = _json_body()
    if body is None or set(body) - {"status", "snooze_hours", "title"}:
        return jsonify(error="Provide status, snooze_hours, or title"), 400
    if "title" in body:
        if not isinstance(body["title"], str) or not body["title"].strip() or len(body["title"]) > 200:
            return jsonify(error="title must be a non-empty string up to 200 characters"), 400
        task.title = body["title"].strip()
    if "snooze_hours" in body:
        hours = body["snooze_hours"]
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 720:
            return jsonify(error="snooze_hours must be an integer from 1 to 720"), 400
        from datetime import timedelta
        task.status = "SNOOZED"
        task.snoozed_until = datetime.utcnow() + timedelta(hours=hours)
    if "status" in body:
        status = body["status"]
        allowed = {"PENDING", "IN_PROGRESS", "WAITING", "COMPLETED", "CANCELLED"}
        if status not in allowed:
            return jsonify(error="Unsupported task status"), 400
        old = task.status
        task.status = status
        task.completed_at = datetime.utcnow() if status == "COMPLETED" else None
        task.verified = status == "COMPLETED"
        task.snoozed_until = None
        db.session.add(TaskEvent(task_id=task.id, from_status=old, to_status=status, note="Updated by user"))
    task.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(task_id=task.id, status=task.status, snoozed_until=task.snoozed_until.isoformat() if task.snoozed_until else None)


@api_bp.delete("/tasks/<int:task_id>")
@login_required
def delete_task(task_id):
    task = UserTask.query.filter_by(id=task_id, user_id=_authenticated_user().id).first()
    if task is None:
        return jsonify(error="Task not found"), 404
    db.session.delete(task)
    db.session.commit()
    return jsonify(deleted=task_id)


@api_bp.get("/goals")
@login_required
def list_goals():
    rows = UserGoal.query.filter_by(user_id=_authenticated_user().id).order_by(UserGoal.updated_at.desc()).all()
    return jsonify(goals=[{"id": g.id, "title": g.title, "description": g.description, "status": g.status,
                           "scheme_id": g.scheme_id, "task_ids": [t.id for t in g.tasks]} for g in rows])


@api_bp.patch("/goals/<int:goal_id>")
@login_required
def update_goal(goal_id):
    goal = UserGoal.query.filter_by(id=goal_id, user_id=_authenticated_user().id).first()
    if goal is None:
        return jsonify(error="Goal not found"), 404
    body = _json_body()
    if body is None or set(body) - {"status", "title"}:
        return jsonify(error="Provide status or title"), 400
    if "status" in body:
        if body["status"] not in {"ACTIVE", "PAUSED", "COMPLETED", "CANCELLED"}:
            return jsonify(error="Unsupported goal status"), 400
        goal.status = body["status"]
    if "title" in body:
        if not isinstance(body["title"], str) or not body["title"].strip() or len(body["title"]) > 200:
            return jsonify(error="title must be a non-empty string up to 200 characters"), 400
        goal.title = body["title"].strip()
    goal.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(goal_id=goal.id, status=goal.status, title=goal.title)


@api_bp.get("/notification-preferences")
@login_required
def get_notification_preferences():
    pref = db.session.get(NotificationPreference, _authenticated_user().id)
    return jsonify(enabled=pref.enabled if pref else True,
                   quiet_start=pref.quiet_start if pref else None, quiet_end=pref.quiet_end if pref else None,
                   timezone_offset_minutes=pref.timezone_offset_minutes if pref else 0)


@api_bp.put("/notification-preferences")
@login_required
def put_notification_preferences():
    body = _json_body()
    if body is None or set(body) - {"enabled", "quiet_start", "quiet_end", "timezone_offset_minutes"}:
        return jsonify(error="Invalid preference fields"), 400
    if "enabled" in body and not isinstance(body["enabled"], bool):
        return jsonify(error="enabled must be boolean"), 400
    offset = body.get("timezone_offset_minutes")
    if offset is not None and (isinstance(offset, bool) or not isinstance(offset, int) or not -720 <= offset <= 840):
        return jsonify(error="timezone_offset_minutes must be between -720 and 840"), 400
    for key in ("quiet_start", "quiet_end"):
        value = body.get(key)
        if value is not None and (not isinstance(value, str) or not __import__("re").fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value)):
            return jsonify(error=f"{key} must use HH:MM"), 400
    pref = db.session.get(NotificationPreference, _authenticated_user().id)
    if pref is None:
        pref = NotificationPreference(user_id=_authenticated_user().id)
        db.session.add(pref)
    for key in ("enabled", "quiet_start", "quiet_end", "timezone_offset_minutes"):
        if key in body:
            setattr(pref, key, body[key])
    db.session.commit()
    return jsonify(enabled=pref.enabled, quiet_start=pref.quiet_start, quiet_end=pref.quiet_end,
                   timezone_offset_minutes=pref.timezone_offset_minutes)


@api_bp.delete("/memory")
@login_required
def clear_memory():
    user = _authenticated_user()
    count = delete_memory(user.id)
    return jsonify(deleted=count, profile=memory.get_or_create_profile(user.id).to_dict())


@api_bp.delete("/memory/<string:key>")
@login_required
def delete_memory_fact(key):
    user = _authenticated_user()
    count = delete_memory(user.id, key)
    return jsonify(deleted=count)


@api_bp.post("/memory/<string:key>/confirm")
@login_required
def confirm_memory_fact(key):
    if not confirm_memory(_authenticated_user().id, key):
        return jsonify(error="No remembered fact with that key"), 404
    return jsonify(confirmed=key)


@api_bp.put("/memory/<string:key>")
@login_required
def update_memory_fact(key):
    user = _authenticated_user()
    body = _json_body()
    if key not in memory.MEMORY_KEYS or body is None or "value" not in body:
        return jsonify(error="A known profile key and JSON value are required"), 400
    value = body["value"]
    if value is None:
        return jsonify(error="Use DELETE to clear a remembered value"), 400
    error = _profile_validation_error({key: value})
    if error:
        return jsonify(error=error), 400
    memory.update_profile(user.id, source="profile", **{key: value})
    fact = UserMemory.query.filter_by(user_id=user.id, key=key).first()
    return jsonify(fact={"key": key, "value": fact.value if fact else value})


@api_bp.get("/conversations")
@login_required
def list_conversations():
    user = _authenticated_user()
    conversations = Conversation.query.filter_by(user_id=user.id).order_by(Conversation.updated_at.desc()).limit(50).all()
    return jsonify(conversations=[{"id": row.id, "title": row.title,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
        "messages": [{"role": item.role, "content": item.content, "created_at": item.created_at.isoformat()} for item in row.messages]}
        for row in conversations])


@api_bp.delete("/conversations")
@login_required
def clear_conversations():
    user = _authenticated_user()
    conversations = Conversation.query.filter_by(user_id=user.id).all()
    ids = [conversation.id for conversation in conversations]
    if ids:
        message_ids = db.session.query(Message.id).filter(Message.conversation_id.in_(ids))
        UserMemory.query.filter(UserMemory.source_message_id.in_(
            message_ids
        )).update({UserMemory.source_message_id: None}, synchronize_session=False)
        EpisodicMemory.query.filter(EpisodicMemory.conversation_id.in_(ids)).update(
            {EpisodicMemory.conversation_id: None, EpisodicMemory.source_message_id: None}, synchronize_session=False)
        UserTask.query.filter(UserTask.conversation_id.in_(ids)).update(
            {UserTask.conversation_id: None, UserTask.source_message_id: None}, synchronize_session=False)
        TaskEvent.query.filter(TaskEvent.source_message_id.in_(message_ids)).update(
            {TaskEvent.source_message_id: None}, synchronize_session=False)
        for conversation in conversations:
            db.session.delete(conversation)
    db.session.commit()
    return jsonify(deleted=len(conversations))


@api_bp.post("/admin/sources/<int:source_id>/review")
@admin_required
def review_source(source_id):
    body = _json_body()
    if body is None:
        return jsonify(error="A JSON object is required"), 400
    status = body.get("status")
    notes = body.get("review_notes", "")
    if status not in {"VERIFIED", "REJECTED"}:
        return jsonify(error="status must be VERIFIED or REJECTED"), 400
    if not isinstance(notes, str):
        return jsonify(error="review_notes must be a string"), 400

    source = db.session.get(SchemeSource, source_id)
    if source is None:
        return jsonify(error="Source record not found"), 404
    parsed_url = urlparse(source.source_url)
    if status == "VERIFIED" and parsed_url.scheme != "https":
        return jsonify(error="Only HTTPS source URLs can be verified"), 400
    new_rule_created = False
    if (
        status == "VERIFIED"
        and source.status != "VERIFIED"
        and source.proposed_rule_json is not None
        and source.rule_version == 0
    ):
        latest_rule = source.scheme.latest_rule()
        version = latest_rule.version + 1 if latest_rule else 1
        db.session.add(
            EligibilityRule(
                scheme_id=source.scheme_id,
                rule_json=source.proposed_rule_json,
                version=version,
                effective_from=datetime.now(timezone.utc),
            )
        )
        source.rule_version = version
        source.scheme.rule_version = version
        new_rule_created = True
    source.status = status
    source.reviewed_at = datetime.now(timezone.utc)
    source.review_notes = notes.strip() or None
    source.last_verified = source.reviewed_at if status == "VERIFIED" else None
    verified_source = SchemeSource.query.filter_by(scheme_id=source.scheme_id, status="VERIFIED").first()
    source.scheme.source_verified = verified_source is not None
    source.scheme.last_verified = source.reviewed_at if status == "VERIFIED" else source.scheme.last_verified
    if status == "VERIFIED":
        source.scheme.source_url = source.source_url
        source.scheme.source_type = source.source_type
    if status == "VERIFIED":
        from agent.rag import index_scheme, ingest_document
        index_scheme(source.scheme)
        ingest_document(source.scheme, title=source.source_title, content=source.excerpt,
            source_url=source.source_url, source_type=source.source_type, verified=True)
    else:
        GovernmentDocument.query.filter_by(scheme_id=source.scheme_id, source_url=source.source_url).update(
            {"verification_status": "REJECTED"}, synchronize_session=False)
    db.session.commit()
    if new_rule_created:
        # Proactive change detection: citizens who now qualify under the newly approved rule are notified.
        try:
            from agent.change_detection import reevaluate_scheme as run_reevaluation
            run_reevaluation(source.scheme)
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Automatic re-evaluation after source approval failed")
    return jsonify(source=source.to_dict())


def _source_for_review(source):
    """Source record plus a plain-English rendering of the proposed rule, to compare with the excerpt."""
    rule = source.proposed_rule_json
    return {**source.to_dict(), "scheme": source.scheme.name, "manual_checks": source.scheme.manual_checks or [],
            "proposed_rule_json": rule, "proposed_rule_text": rule_to_text(rule) if rule else None}


@api_bp.get("/admin/sources")
@admin_required
def list_sources():
    status = request.args.get("status", "PENDING")
    if status not in {"PENDING", "VERIFIED", "REJECTED"}:
        return jsonify(error="status must be PENDING, VERIFIED, or REJECTED"), 400
    sources = (
        SchemeSource.query.filter_by(status=status)
        .order_by(SchemeSource.id.asc())
        .limit(100)
        .all()
    )
    return jsonify(sources=[_source_for_review(source) for source in sources])


@api_bp.post("/admin/sources/import")
@admin_required
def import_sources():
    body = _json_body()
    records = body.get("records") if body else None
    if not isinstance(records, list) or not records:
        return jsonify(error="records must be a non-empty array"), 400
    if len(records) > 100:
        return jsonify(error="Import is limited to 100 records per request"), 400

    created = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            return jsonify(error=f"Record {index} must be an object"), 400
        required = ("name", "source_url", "source_title", "publisher", "excerpt", "jurisdiction")
        if any(not isinstance(record.get(key), str) or not record[key].strip() for key in required):
            return jsonify(error=f"Record {index} is missing required non-empty fields"), 400
        parsed_url = urlparse(record["source_url"])
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            return jsonify(error=f"Record {index} source_url must be an HTTPS URL"), 400
        rule = record.get("rule")
        if rule is not None and not isinstance(rule, dict):
            return jsonify(error=f"Record {index} rule must be an object"), 400
        manual_checks = record.get("manual_checks")
        if manual_checks is not None and (
            not isinstance(manual_checks, list) or any(not isinstance(item, str) for item in manual_checks)
        ):
            return jsonify(error=f"Record {index} manual_checks must be a list of strings"), 400
        field_limits = {
            "name": 150,
            "description": 10000,
            "department": 120,
            "government_level": 30,
            "category": 80,
            "benefits": 10000,
            "application_url": 255,
            "source_title": 255,
            "publisher": 255,
            "jurisdiction": 100,
        }
        for key, limit in field_limits.items():
            value = record.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > limit):
                return jsonify(error=f"Record {index} field {key} must be at most {limit} characters"), 400
        if len(record["excerpt"]) > 20000:
            return jsonify(error=f"Record {index} excerpt is too long"), 400
        if str(record.get("government_level", "STATE")).upper() == "STATE" and not canonical_state(record["jurisdiction"]):
            return jsonify(error=f"Record {index} STATE schemes need a jurisdiction naming the state or union territory"), 400
        if rule is not None:
            try:
                evaluate_rule(rule, {field: None for field in CitizenProfile.RULE_FIELDS})
                unknown_fields = _rule_fields(rule) - set(CitizenProfile.RULE_FIELDS)
                _validate_rule_values(rule)
            except (InvalidRuleError, TypeError, ValueError) as exc:
                return jsonify(error=f"Record {index} has an invalid rule: {exc}"), 400
            if unknown_fields:
                return jsonify(
                    error=f"Record {index} rule contains unknown profile fields",
                    fields=sorted(unknown_fields),
                ), 400

    try:
        for record in records:
            scheme = Scheme.query.filter_by(name=record["name"].strip()).first()
            if scheme is None:
                scheme = Scheme(
                    name=record["name"].strip(),
                    description=record.get("description"),
                    department=record.get("department"),
                    government_level=record.get("government_level", "STATE"),
                    category=record.get("category"),
                    benefits=record.get("benefits"),
                    application_url=record.get("application_url"),
                    manual_checks=record.get("manual_checks") or [],
                    active=True,
                    rule_version=1,
                )
                db.session.add(scheme)
                db.session.flush()
            elif record.get("manual_checks") is not None:
                scheme.manual_checks = record["manual_checks"]
            existing_source = SchemeSource.query.filter_by(
                scheme_id=scheme.id, source_url=record["source_url"].strip()
            ).first()
            if existing_source is not None:
                continue
            source = SchemeSource(
                scheme_id=scheme.id,
                source_url=record["source_url"].strip(),
                source_title=record["source_title"].strip(),
                publisher=record["publisher"].strip(),
                excerpt=record["excerpt"].strip(),
                jurisdiction=canonical_state(record["jurisdiction"]) or record["jurisdiction"].strip(),
                proposed_rule_json=record.get("rule"),
                status="PENDING",
            )
            db.session.add(source)
            db.session.flush()
            created.append(_source_for_review(source))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return jsonify(imported=len(created), sources=created), 201


@api_bp.post("/admin/schemes/import")
@admin_required
def import_schemes():
    body = _json_body()
    records = body.get("records") if body else None
    if not isinstance(records, list) or not records:
        return jsonify(error="records must be a non-empty array"), 400
    if len(records) > 100:
        return jsonify(error="Import is limited to 100 records per request"), 400
    run = IngestionRun(initiated_by=_authenticated_user().id, source_name="admin-json-import")
    db.session.add(run)
    db.session.commit()
    try:
        from agent.ingestion import import_records
        result = import_records(records, embedding_model=current_app.config.get("EMBEDDING_MODEL", "text-embedding-3-small"))
    except (ValueError, InvalidRuleError) as exc:
        db.session.rollback()
        run = db.session.get(IngestionRun, run.id)
        run.status, run.error, run.finished_at = "FAILED", str(exc)[:10000], datetime.now(timezone.utc)
        db.session.commit()
        return jsonify(error=str(exc), ingestion_run_id=run.id), 400
    run = db.session.get(IngestionRun, run.id)
    run.status, run.result, run.finished_at = "SUCCEEDED", result, datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({**result, "ingestion_run_id": run.id}), 201


@api_bp.get("/admin/ingestion/errors")
@admin_required
def ingestion_errors():
    runs = IngestionRun.query.filter_by(status="FAILED").order_by(IngestionRun.created_at.desc()).limit(100).all()
    return jsonify(errors=[{"id": row.id, "source_name": row.source_name,
        "error": row.error, "created_at": row.created_at.isoformat()} for row in runs])


@api_bp.post("/admin/index/rebuild")
@admin_required
def rebuild_index():
    from agent.rag import _embeddings, index_scheme
    from agent.llm import make_client  # OpenAI or an OpenAI-compatible provider, chosen via OPENAI_BASE_URL
    api_key = current_app.config.get("OPENAI_API_KEY")
    client = make_client(api_key) if api_key else None
    schemes = Scheme.query.order_by(Scheme.id).all()
    for scheme in schemes:
        index_scheme(scheme, client=client, embedding_model=current_app.config.get("EMBEDDING_MODEL", "text-embedding-3-small"))
    if client:
        from database.models import DocumentChunk
        chunks = DocumentChunk.query.filter(DocumentChunk.embedding.is_(None)).all()
        for start in range(0, len(chunks), 64):
            batch = chunks[start:start + 64]
            vectors = _embeddings(client, [chunk.text for chunk in batch], current_app.config.get("EMBEDDING_MODEL", "text-embedding-3-small"))
            for chunk, vector in zip(batch, vectors):
                chunk.embedding = vector
    db.session.commit()
    return jsonify(indexed=len(schemes), semantic=client is not None)


@api_bp.post("/admin/documents/import")
@admin_required
def import_document_text():
    body = _json_body()
    if body is None or not isinstance(body.get("scheme_id"), int) or not isinstance(body.get("content"), str):
        return jsonify(error="scheme_id and content are required"), 400
    if len(body["content"]) > 2_000_000:
        return jsonify(error="document text is too large"), 413
    scheme = db.session.get(Scheme, body["scheme_id"])
    if scheme is None:
        return jsonify(error="Scheme not found"), 404
    source_url = body.get("source_url")
    if source_url is not None and (not isinstance(source_url, str) or urlparse(source_url).scheme != "https"):
        return jsonify(error="source_url must be an HTTPS URL"), 400
    try:
        from agent.rag import ingest_document
        document = ingest_document(scheme,
            title=str(body.get("title") or scheme.name)[:255], content=body["content"],
            source_url=source_url, source_type=str(body.get("source_type") or "DOCUMENT")[:40])
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    return jsonify(document={"id": document.id, "scheme_id": document.scheme_id,
        "title": document.title, "source_url": document.source_url,
        "verification_status": document.verification_status,
        "chunks": len(document.chunks)}), 201


@api_bp.post("/admin/schemes/<int:scheme_id>/reevaluate")
@admin_required
def reevaluate_scheme(scheme_id):
    scheme = db.session.get(Scheme, scheme_id)
    if scheme is None:
        return jsonify(error="Scheme not found"), 404
    from agent.change_detection import reevaluate_scheme as run_reevaluation
    result = run_reevaluation(scheme)
    if result.get("error"):
        return jsonify(error=result["error"]), 409
    return jsonify(result)


@api_bp.get("/notifications")
@login_required
def list_notifications():
    rows = Notification.query.filter_by(citizen_id=_authenticated_user().id).order_by(Notification.created_at.desc()).limit(50).all()
    return jsonify(notifications=[row.to_dict() for row in rows],
                   unread=sum(1 for row in rows if not row.is_read))


@api_bp.post("/notifications/read")
@login_required
def mark_notifications_read():
    updated = Notification.query.filter_by(citizen_id=_authenticated_user().id, is_read=False).update(
        {"is_read": True}, synchronize_session=False)
    db.session.commit()
    return jsonify(updated=updated)


def _rule_fields(node):
    if "field" in node:
        return {node["field"]}
    found = set()
    for child in node.get("conditions", []):
        found.update(_rule_fields(child))
    return found


def _rule_leaves(node):
    if "field" in node:
        return [node]
    return [leaf for child in node.get("conditions", []) for leaf in _rule_leaves(child)]


def _validate_rule_values(rule):
    text_fields = {
        "gender", "state", "district", "occupation", "education_level",
        "marital_status", "employment_status", "category",
    }
    boolean_fields = {"disability_status", "student_status", "farmer_status"}
    integer_fields = {"age", "family_size"}
    numeric_fields = integer_fields | {"annual_income"}

    for condition in _rule_leaves(rule):
        field = condition.get("field")
        operator = condition.get("operator")
        expected = condition.get("value")
        if not isinstance(field, str) or not field or "value" not in condition:
            raise ValueError("each condition needs a non-empty field and a value")
        if field not in CitizenProfile.RULE_FIELDS:
            continue
        if operator in {"<", "<=", ">", ">=", "between"} and field not in numeric_fields:
            raise ValueError(f"operator {operator!r} requires a numeric profile field")
        if operator == "between":
            if not isinstance(expected, list) or len(expected) != 2:
                raise ValueError("'between' requires a two-item list")
            values = expected
        elif operator == "in":
            if not isinstance(expected, list) or not expected:
                raise ValueError("'in' requires a non-empty list")
            values = expected
        else:
            values = [expected]

        for value in values:
            if field in boolean_fields:
                valid = isinstance(value, bool)
            elif field in integer_fields:
                valid = isinstance(value, int) and not isinstance(value, bool)
            elif field == "annual_income":
                valid = (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and (isinstance(value, int) or math.isfinite(value))
                    and value >= 0
                )
            else:
                valid = isinstance(value, str)
            if not valid:
                raise ValueError(f"value type does not match profile field {field!r}")

        if operator == "between" and expected[0] > expected[1]:
            raise ValueError("'between' lower bound must not exceed upper bound")
