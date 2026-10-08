"""
agent/memory.py — the agent's persistent "memory" of a citizen.

This module is the ONLY place that should write CitizenProfile rows. Everything else (rule_engine, agent,
routes) goes through these functions so the memory contract stays in one place.

CitizenProfile holds the VALUES (single source of truth). UserMemory rows hold metadata about each value
(source, confirmed, previous value, last checked) and are kept in sync by sync_memory_rows(), so a fact entered
through the profile form and a fact picked up from chat appear in the same "what I remember" list.

Public API:
    get_profile(user_id)                        -> CitizenProfile | None
    get_or_create_profile(user_id)              -> CitizenProfile
    save_profile(user_id, **fields)             -> CitizenProfile
    update_profile(user_id, *, source=..., **f) -> CitizenProfile
    get_memory_dict(user_id)                    -> dict
    get_missing_attributes(user_id, fields=None)-> list[str]
    is_profile_complete(user_id)                -> bool
    profile_completion(user_id)                 -> int
    sync_memory_rows(profile, ...)              -> None
"""

from datetime import date, datetime

from database.db import db
from database.models import CitizenProfile, UserMemory
from agent.normalize import normalize_value

MEMORY_KEYS = list(CitizenProfile.RULE_FIELDS) + ["date_of_birth"]


class ProfileNotFoundError(Exception):
    """Raised when a lookup expects an existing profile but none exists."""


def get_profile(user_id: int) -> CitizenProfile | None:
    """Return the citizen's stored profile, or None if they have none yet."""
    return CitizenProfile.query.filter_by(user_id=user_id).first()


def get_or_create_profile(user_id: int) -> CitizenProfile:
    """Return the citizen's profile, creating an empty one if this is their first interaction."""
    profile = get_profile(user_id)
    if profile is None:
        profile = CitizenProfile(user_id=user_id)
        db.session.add(profile)
        db.session.commit()
    return profile


def _coerce(key, value):
    if key == "date_of_birth":
        return date.fromisoformat(value) if isinstance(value, str) else value
    return normalize_value(key, value)


def _json_safe(value):
    return value.isoformat() if isinstance(value, date) else value


def _apply_allowed_fields(profile: CitizenProfile, fields: dict) -> dict:
    """
    Write only known, non-None fields onto the profile (values are normalised first). Returns
    {field: previous_value} for the fields that actually changed.

    - A stated date of birth wins over an age in the same call.
    - A different explicit age replaces any stored date of birth (the old one would now be wrong).
    """
    allowed = set(CitizenProfile.RULE_FIELDS) | {"full_name", "date_of_birth"}
    if fields.get("date_of_birth") is not None:
        fields = {k: v for k, v in fields.items() if k != "age"}
    changes = {}
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        value = _coerce(key, value)
        if key == "age":
            current = profile.current_age()
            if current == value:
                continue
            changes["age"] = current
            profile.date_of_birth = None
            profile.age = value
            continue
        old = getattr(profile, key)
        if old != value:
            setattr(profile, key, value)
            changes[key] = _json_safe(old)
    if profile.date_of_birth:
        profile.age = profile.current_age()  # keep the stored column aligned with the derived age
    return changes


def sync_memory_rows(profile: CitizenProfile, *, changes=None, source="profile", message_id=None) -> None:
    """Align UserMemory metadata rows with the profile (the source of truth). Does not commit."""
    changes = changes or {}
    values = profile.to_memory_dict()
    values["date_of_birth"] = profile.date_of_birth.isoformat() if profile.date_of_birth else None
    rows = {row.key: row for row in UserMemory.query.filter_by(user_id=profile.user_id).all()}
    now = datetime.utcnow()
    for key in MEMORY_KEYS:
        value, row, changed = values.get(key), rows.get(key), key in changes
        if value is None:
            if row is not None:
                db.session.delete(row)
            continue
        by_user = changed and source == "profile"
        if row is None:
            db.session.add(UserMemory(
                user_id=profile.user_id, key=key, value=value,
                source=source if changed else "profile",
                source_message_id=message_id if changed else None,
                confirmed=by_user, last_confirmed_at=now if by_user else None,
                previous_value=changes.get(key) if changed else None))
        elif row.value != value or changed:
            row.value = value
            if changed:
                row.previous_value = changes[key]
                row.source = source
                row.source_message_id = message_id
                row.confirmed = by_user
                row.last_confirmed_at = now if by_user else None


def save_profile(user_id: int, **fields) -> CitizenProfile:
    """Create-or-update entry point used by the initial profile form (same semantics as update_profile)."""
    return update_profile(user_id, **fields)


def update_profile(user_id: int, *, source: str = "profile", source_message_id=None, **fields) -> CitizenProfile:
    """
    Merge the given fields into the citizen's stored memory. None values mean "not supplied", not "clear
    this field", so the agent never forgets something it was told earlier. `source` is "profile" for values the
    citizen typed into the form, "chat" for facts picked up from a message.
    """
    profile = get_or_create_profile(user_id)
    changes = _apply_allowed_fields(profile, fields)
    sync_memory_rows(profile, changes=changes, source=source, message_id=source_message_id)
    db.session.commit()
    return profile


def get_memory_dict(user_id: int) -> dict:
    """Plain dict the rule engine consumes; all-None if no profile exists yet."""
    profile = get_profile(user_id)
    if profile is None:
        return {field: None for field in CitizenProfile.RULE_FIELDS}
    return profile.to_memory_dict()


def get_missing_attributes(user_id: int, fields: list | None = None) -> list:
    """Which memory fields are still unknown (optionally only among `fields`)."""
    profile = get_profile(user_id)
    if profile is None:
        return list(fields) if fields is not None else list(CitizenProfile.RULE_FIELDS)
    return profile.missing_fields(required_fields=fields)


def is_profile_complete(user_id: int) -> bool:
    """True once every RULE_FIELD has been supplied at least once."""
    return len(get_missing_attributes(user_id)) == 0


def profile_completion(user_id: int) -> int:
    """Percentage (0-100) of RULE_FIELDS that are filled in."""
    profile = get_profile(user_id)
    if profile is None:
        return 0
    return profile.completion_percentage()