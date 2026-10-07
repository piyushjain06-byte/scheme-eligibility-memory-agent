"""Conservative extraction of plainly stated, scheme-relevant profile facts."""
import re

from database.db import db
from database.models import CitizenProfile, UserMemory
from agent.memory import update_profile

INDIAN_STATES = ["Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal"]


def extract_explicit_facts(text):
    facts = {}
    age = re.search(r"\b(?:i am|i'm|aged)\s+(?:a\s+)?(\d{1,3})\s*(?:[- ]years?[- ]old|years? old)?\b", text, re.I)
    if age and 0 <= int(age.group(1)) <= 130:
        facts["age"] = int(age.group(1))
    income = re.search(r"\b(?:my\s+)?(?:family\s+)?income\s+(?:(?:is|of)\s+)?(?:around|about)?\s*(?:₹|rs\.?\s*)?([\d,.]+)\s*(lakh|lakhs|l|crore|crores)?", text, re.I)
    if income:
        amount = float(income.group(1).replace(",", ""))
        multiplier = 100000 if income.group(2) and income.group(2).lower().startswith("l") else (10000000 if income.group(2) else 1)
        facts["annual_income"] = int(amount * multiplier)
    if re.search(r"\b(?:i am|i'm)\s+not\s+(?:a\s+)?student\b", text, re.I):
        facts["student_status"] = False
    elif re.search(r"\b(?:i am|i'm)\s+(?:(?:a|an)\s+)?(?:\d{1,3}[- ]year[- ]old\s+)?(?:(?:engineering|medical|law|arts|science|commerce|diploma)\s+)?student\b|\bi am studying\b", text, re.I):
        facts["student_status"] = True
    if re.search(r"\b(?:i am|i'm)\s+(?:currently\s+)?(?:unemployed|not employed)\b", text, re.I):
        facts["employment_status"] = "unemployed"
    education = re.search(r"\b(?:i am|i'm)\s+(?:(?:a|an)\s+)?(?:\d{1,3}[- ]year[- ]old\s+)?(engineering|medical|law|arts|science|commerce|diploma)\s+student\b|\bi study\s+(engineering|medical|law|arts|science|commerce|diploma)\b", text, re.I)
    if education:
        facts["education_level"] = (education.group(1) or education.group(2)).lower()
    states = "|".join(re.escape(state) for state in sorted(INDIAN_STATES, key=len, reverse=True))
    origin = re.search(rf"\b(?:i am|i'm)\b[^.!?]{{0,80}}\bfrom\s+({states})\b|\b(?:i live in|i'm living in|i am living in|i'm based in|i am based in)\s+({states})\b", text, re.I)
    if origin:
        stated = (origin.group(1) or origin.group(2)).casefold()
        facts["state"] = next(value for value in INDIAN_STATES if value.casefold() == stated)
    return facts


def save_explicit_facts(user_id, text, message_id=None):
    facts = extract_explicit_facts(text)
    if not facts:
        return {}
    update_profile(user_id, **facts)
    for key, value in facts.items():
        fact = UserMemory.query.filter_by(user_id=user_id, key=key).first()
        if fact is None:
            fact = UserMemory(user_id=user_id, key=key, value=value)
            db.session.add(fact)
        else:
            fact.value = value
        fact.source_message_id = message_id
    db.session.commit()
    return facts


def list_memory(user_id):
    return [{"id": row.id, "key": row.key, "value": row.value,
             "source_message_id": row.source_message_id,
             "updated_at": row.updated_at.isoformat() if row.updated_at else None}
            for row in UserMemory.query.filter_by(user_id=user_id).order_by(UserMemory.key).all()]


def delete_memory(user_id, key=None):
    query = UserMemory.query.filter_by(user_id=user_id)
    if key:
        query = query.filter_by(key=key)
    count = query.delete(synchronize_session=False)
    if key:
        # Clearing a fact clears the corresponding structured profile field too.
        profile = CitizenProfile.query.filter_by(user_id=user_id).first()
        if profile and key in CitizenProfile.RULE_FIELDS:
            setattr(profile, key, None)
    else:
        profile = CitizenProfile.query.filter_by(user_id=user_id).first()
        if profile:
            for field in CitizenProfile.RULE_FIELDS:
                setattr(profile, field, None)
    db.session.commit()
    return count
