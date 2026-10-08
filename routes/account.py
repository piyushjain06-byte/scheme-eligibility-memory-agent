"""Citizen data rights: download everything we hold about you, or delete your account."""

from flask import Blueprint, jsonify, session

from database.db import db
from database.models import EligibilityEvaluation, UserMemory
from agent import memory
from agent.user_memory import list_memory
from routes.api import _authenticated_user, _json_body, login_required

account_bp = Blueprint("account", __name__)


@account_bp.get("/account/export")
@login_required
def export_account():
    user = _authenticated_user()
    profile = memory.get_or_create_profile(user.id)
    evaluations = (EligibilityEvaluation.query.filter_by(citizen_id=profile.id)
                   .order_by(EligibilityEvaluation.evaluated_at.desc()).limit(500).all())
    response = jsonify(
        user=user.to_dict(),
        profile=profile.to_dict(),
        remembered_facts=list_memory(user.id),
        conversations=[{"id": c.id, "title": c.title, "created_at": c.created_at.isoformat(),
                        "messages": [{"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
                                     for m in c.messages]} for c in user.conversations],
        eligibility_history=[e.to_dict() for e in evaluations],
        notifications=[n.to_dict() for n in user.notifications],
    )
    response.headers["Content-Disposition"] = "attachment; filename=my-scheme-agent-data.json"
    return response


@account_bp.delete("/account")
@login_required
def delete_account():
    """Permanently delete the signed-in citizen and everything stored about them. Needs the password."""
    user = _authenticated_user()
    body = _json_body() or {}
    if user.is_admin():
        return jsonify(error="Administrator accounts cannot be deleted here"), 403
    password = body.get("password")
    if not isinstance(password, str) or not user.check_password(password):
        return jsonify(error="Password confirmation failed"), 403
    # Facts reference messages, so remove them before the cascade deletes the conversations.
    UserMemory.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    db.session.expire(user)
    db.session.delete(user)
    db.session.commit()
    session.clear()
    return jsonify(deleted=True)
