"""Saving, listing, confirming and forgetting facts the citizen has stated (extraction itself lives in extraction.py)."""
import logging
from datetime import datetime

from database.db import db
from database.models import CitizenProfile, UserMemory
from agent import memory as profile_memory
from agent.extraction import LLM_SYSTEM_PROMPT, extract_explicit_facts, parse_llm_facts  # noqa: F401  (re-exported)
from agent.normalize import INDIAN_STATES  # noqa: F401  (re-exported for older imports)

logger = logging.getLogger(__name__)

# Facts that quietly go out of date. Age is exempt when a date of birth is stored.
STALE_AFTER_DAYS = {"age": 180, "annual_income": 365, "employment_status": 365, "occupation": 365, "family_size": 365}


def extract_facts_with_llm(api_key, model, text):
    """Optional second extractor. Its output passes through the same validation as the regex path."""
    from agent.llm import make_client  # OpenAI or an OpenAI-compatible provider, chosen via OPENAI_BASE_URL
    response = make_client(api_key).chat.completions.create(
        model=model, temperature=0,
        messages=[{"role": "system", "content": LLM_SYSTEM_PROMPT}, {"role": "user", "content": text}],
    )
    return parse_llm_facts(response.choices[0].message.content or "", text)


def _snapshot(user_id):
    profile = profile_memory.get_profile(user_id)
    if profile is None:
        return {}
    data = profile.to_memory_dict()
    data["date_of_birth"] = profile.date_of_birth.isoformat() if profile.date_of_birth else None
    return data


def save_explicit_facts(user_id, text, message_id=None, llm=None):
    """
    Save plainly stated facts and return what actually changed, as
    [{"key", "value", "previous"}], so the chat can show "Remembered: age 21" and let the user correct it.
    `llm` = {"api_key", "model"} switches on the optional LLM extractor (regex facts take precedence).
    """
    facts = extract_explicit_facts(text)
    if llm:
        try:
            facts = {**extract_facts_with_llm(llm["api_key"], llm["model"], text), **facts}
        except Exception:
            logger.exception("LLM memory extraction failed; using rule-based extraction only")
    if not facts:
        return []
    before = _snapshot(user_id)
    profile_memory.update_profile(user_id, source="chat", source_message_id=message_id, **facts)
    after = _snapshot(user_id)
    return [{"key": key, "value": after.get(key), "previous": before.get(key)}
            for key in facts if after.get(key) != before.get(key)]


def list_memory(user_id):
    profile = profile_memory.get_or_create_profile(user_id)
    profile_memory.sync_memory_rows(profile)  # also picks up facts saved before metadata existed
    db.session.commit()
    now = datetime.utcnow()
    result = []
    for row in UserMemory.query.filter_by(user_id=user_id).order_by(UserMemory.key).all():
        checked = row.last_confirmed_at or row.updated_at or row.created_at
        limit = STALE_AFTER_DAYS.get(row.key)
        stale = bool(limit and checked and (now - checked).days >= limit
                     and not (row.key == "age" and profile.date_of_birth))
        result.append({
            "id": row.id, "key": row.key, "value": row.value, "source": row.source,
            "source_message_id": row.source_message_id, "confirmed": bool(row.confirmed), "stale": stale,
            "previous_value": row.previous_value,
            "last_confirmed_at": row.last_confirmed_at.isoformat() if row.last_confirmed_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })
    return result


def confirm_memory(user_id, key):
    """Mark a remembered fact as checked by the citizen. Returns False if there is no such fact."""
    profile_memory.sync_memory_rows(profile_memory.get_or_create_profile(user_id))
    row = UserMemory.query.filter_by(user_id=user_id, key=key).first()
    if row is None:
        return False
    row.confirmed = True
    row.last_confirmed_at = datetime.utcnow()
    db.session.commit()
    return True


def delete_memory(user_id, key=None):
    """Forget one fact (or all). The profile value is cleared too, because the profile is the source of truth."""
    query = UserMemory.query.filter_by(user_id=user_id)
    if key:
        query = query.filter_by(key=key)
    count = query.delete(synchronize_session=False)
    profile = CitizenProfile.query.filter_by(user_id=user_id).first()
    if profile:
        for name in ([key] if key else profile_memory.MEMORY_KEYS):
            if name == "date_of_birth":
                profile.date_of_birth = None
            elif name == "age":
                profile.age = None
                profile.date_of_birth = None  # an age derived from a date of birth goes with it
            elif name in CitizenProfile.RULE_FIELDS:
                setattr(profile, name, None)
    db.session.commit()
    return count