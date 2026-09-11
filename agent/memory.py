"""
agent/memory.py — the agent's persistent "memory" of a citizen.

This module is the ONLY place that should read or write CitizenProfile rows.
Everything else (rule_engine, agent, routes) goes through these functions
instead of touching the model directly, so the memory contract stays in one
place.

Public API:
    get_profile(user_id)                       -> CitizenProfile | None
    get_or_create_profile(user_id)              -> CitizenProfile
    save_profile(user_id, **fields)             -> CitizenProfile
    update_profile(user_id, **fields)           -> CitizenProfile
    get_memory_dict(user_id)                    -> dict
    get_missing_attributes(user_id, fields=None)-> list[str]
    is_profile_complete(user_id)                -> bool
    profile_completion(user_id)                 -> int
"""

from database.db import db
from database.models import CitizenProfile


class ProfileNotFoundError(Exception):
    """Raised when a lookup expects an existing profile but none exists."""


def get_profile(user_id: int) -> CitizenProfile | None:
    """Return the citizen's stored profile, or None if they have none yet."""
    return CitizenProfile.query.filter_by(user_id=user_id).first()


def get_or_create_profile(user_id: int) -> CitizenProfile:
    """
    Return the citizen's profile, creating an empty one (memory placeholder)
    if this is their first interaction with the agent.
    """
    profile = get_profile(user_id)
    if profile is None:
        profile = CitizenProfile(user_id=user_id)
        db.session.add(profile)
        db.session.commit()
    return profile


def _apply_allowed_fields(profile: CitizenProfile, fields: dict) -> list:
    """
    Write only known, non-None fields onto the profile. Returns the list of
    field names that were actually changed, so callers (e.g. the change
    detector) know what moved.

    Silently ignores keys that aren't real columns, so a chat/route layer
    can pass through a loosely-validated dict without blowing up the model.
    """
    allowed = set(CitizenProfile.RULE_FIELDS) | {"full_name", "date_of_birth"}
    changed = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if value is None:
            continue
        if getattr(profile, key) != value:
            setattr(profile, key, value)
            changed.append(key)
    return changed


def save_profile(user_id: int, **fields) -> CitizenProfile:
    """
    Create-or-update entry point used by the initial profile form. Same
    semantics as update_profile — kept as a distinct name so route code
    reads clearly ("save" for the first-time form, "update" afterwards).
    """
    return update_profile(user_id, **fields)


def update_profile(user_id: int, **fields) -> CitizenProfile:
    """
    Merge the given fields into the citizen's stored memory. Only touches
    fields that are actually provided (None values are treated as "not
    supplied", not as "clear this field") so the agent never forgets
    something it was told in an earlier session.
    """
    profile = get_or_create_profile(user_id)
    _apply_allowed_fields(profile, fields)
    db.session.commit()
    return profile


def get_memory_dict(user_id: int) -> dict:
    """
    Flatten the citizen's memory into the plain dict the rule engine
    consumes. Returns a dict of all-None RULE_FIELDS if no profile exists
    yet, rather than raising, so callers can always evaluate against it.
    """
    profile = get_profile(user_id)
    if profile is None:
        return {field: None for field in CitizenProfile.RULE_FIELDS}
    return profile.to_memory_dict()


def get_missing_attributes(user_id: int, fields: list | None = None) -> list:
    """
    Which memory fields are still unknown for this citizen.

    If `fields` is given (e.g. the specific fields a scheme's rule needs),
    only those are checked — this is what lets the agent ask a citizen for
    just the one missing field a scheme needs, instead of the whole profile
    again. If omitted, checks every RULE_FIELD.
    """
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