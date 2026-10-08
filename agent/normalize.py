"""
agent/normalize.py — canonical values for profile fields (pure: no DB, no network).

The same helpers are used when a value is SAVED (memory.py), when it is
EXTRACTED from chat (extraction.py) and when it is COMPARED with a scheme rule
(eligibility.py), so "obc", "OBC category" and "OBC" always mean the same thing.
"""
import re
from datetime import date

INDIAN_STATES = [
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh",
    "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry",
    "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal",
]

_STATE_ALIASES_RAW = {
    "orissa": "Odisha", "pondicherry": "Puducherry", "uttaranchal": "Uttarakhand", "tamilnadu": "Tamil Nadu",
    "jammu & kashmir": "Jammu and Kashmir", "j&k": "Jammu and Kashmir", "new delhi": "Delhi",
    "nct of delhi": "Delhi", "andaman & nicobar islands": "Andaman and Nicobar Islands",
    "andaman and nicobar": "Andaman and Nicobar Islands", "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
}

CITY_TO_STATE = {
    "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra", "nashik": "Maharashtra",
    "thane": "Maharashtra", "bengaluru": "Karnataka", "bangalore": "Karnataka", "mysuru": "Karnataka",
    "mysore": "Karnataka", "hubli": "Karnataka", "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu",
    "madurai": "Tamil Nadu", "hyderabad": "Telangana", "warangal": "Telangana", "visakhapatnam": "Andhra Pradesh",
    "vijayawada": "Andhra Pradesh", "kolkata": "West Bengal", "howrah": "West Bengal", "ahmedabad": "Gujarat",
    "surat": "Gujarat", "vadodara": "Gujarat", "rajkot": "Gujarat", "jaipur": "Rajasthan", "jodhpur": "Rajasthan",
    "udaipur": "Rajasthan", "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh", "varanasi": "Uttar Pradesh",
    "agra": "Uttar Pradesh", "noida": "Uttar Pradesh", "ghaziabad": "Uttar Pradesh", "prayagraj": "Uttar Pradesh",
    "allahabad": "Uttar Pradesh", "patna": "Bihar", "gaya": "Bihar", "bhopal": "Madhya Pradesh",
    "indore": "Madhya Pradesh", "gwalior": "Madhya Pradesh", "jabalpur": "Madhya Pradesh", "raipur": "Chhattisgarh",
    "ranchi": "Jharkhand", "jamshedpur": "Jharkhand", "bhubaneswar": "Odisha", "cuttack": "Odisha",
    "guwahati": "Assam", "thiruvananthapuram": "Kerala", "trivandrum": "Kerala", "kochi": "Kerala",
    "cochin": "Kerala", "kozhikode": "Kerala", "amritsar": "Punjab", "ludhiana": "Punjab",
    "dehradun": "Uttarakhand", "shimla": "Himachal Pradesh", "panaji": "Goa", "srinagar": "Jammu and Kashmir",
    "jammu": "Jammu and Kashmir", "imphal": "Manipur", "shillong": "Meghalaya", "aizawl": "Mizoram",
    "kohima": "Nagaland", "agartala": "Tripura", "gangtok": "Sikkim", "itanagar": "Arunachal Pradesh",
}


def _key(text):
    return re.sub(r"\s+", " ", str(text).replace("&", " and ")).strip().casefold()


_STATE_LOOKUP = {_key(state): state for state in INDIAN_STATES}
_STATE_LOOKUP.update({_key(alias): state for alias, state in _STATE_ALIASES_RAW.items()})

# Every place name a user might type (lower-case), longest first, for building regexes.
PLACE_NAMES = sorted(
    {state.casefold() for state in INDIAN_STATES} | set(_STATE_ALIASES_RAW) | set(CITY_TO_STATE),
    key=len, reverse=True,
)


def canonical_state(text):
    """Return the official state/UT name for text, or None."""
    return _STATE_LOOKUP.get(_key(text)) if text else None


def resolve_place(text):
    """State/UT for a state name, alias or well-known city; None if unknown."""
    return canonical_state(text) or CITY_TO_STATE.get(_key(text))


TEXT_FIELDS = {"gender", "state", "district", "occupation", "education_level",
               "marital_status", "employment_status", "category"}
BOOLEAN_FIELDS = {"disability_status", "student_status", "farmer_status"}
INTEGER_FIELDS = {"age", "family_size"}
TEXT_LIMITS = {"gender": 20, "state": 80, "district": 80, "occupation": 80, "education_level": 80,
               "marital_status": 30, "employment_status": 30, "category": 30}

_CATEGORY = {
    "gen": "GENERAL", "general": "GENERAL", "ur": "GENERAL", "unreserved": "GENERAL", "open": "GENERAL",
    "obc": "OBC", "other backward class": "OBC", "other backward classes": "OBC", "sc": "SC",
    "scheduled caste": "SC", "st": "ST", "scheduled tribe": "ST", "ews": "EWS",
    "economically weaker section": "EWS", "economically weaker sections": "EWS",
}
_GENDER = {
    "f": "female", "female": "female", "woman": "female", "girl": "female", "lady": "female",
    "m": "male", "male": "male", "man": "male", "boy": "male",
    "transgender": "other", "third gender": "other", "non-binary": "other", "nonbinary": "other", "other": "other",
}
_EMPLOYMENT = {
    "unemployed": "unemployed", "jobless": "unemployed", "not employed": "unemployed", "not working": "unemployed",
    "out of work": "unemployed", "without job": "unemployed", "seeking work": "unemployed",
    "looking for work": "unemployed", "looking for job": "unemployed",
    "self employed": "self-employed", "self-employed": "self-employed", "selfemployed": "self-employed",
    "own business": "self-employed", "employed": "employed", "working": "employed", "salaried": "employed",
    "in service": "employed", "retired": "retired", "pensioner": "retired",
}
_MARITAL = {
    "single": "single", "unmarried": "single", "never married": "single", "married": "married",
    "widow": "widowed", "widower": "widowed", "widowed": "widowed", "divorced": "divorced", "separated": "separated",
}
_OCCUPATION = {
    "farming": "farmer", "agriculturist": "farmer", "cultivator": "farmer", "kisan": "farmer",
    "laborer": "labourer", "labourer": "labourer", "daily wager": "labourer", "daily wage worker": "labourer",
    "daily-wage worker": "labourer", "housewife": "homemaker", "home maker": "homemaker", "fisherwoman": "fisherman",
}
_EDUCATION = {
    "post graduate": "postgraduate", "post graduation": "postgraduate", "postgraduation": "postgraduate",
    "pg": "postgraduate", "postgraduate": "postgraduate", "graduate": "graduate", "graduation": "graduate",
    "ug": "graduate", "undergraduate": "graduate",
}


def _squash(text):
    return re.sub(r"\s+", " ", text.strip())


def normalize_value(field, value):
    """Canonical form of one value; non-text values and unknown text pass through (stripped)."""
    if not isinstance(value, str):
        return value
    text = _squash(value)
    low = text.casefold().replace(".", "")
    if field == "category":
        stripped = re.sub(r"\s+(category|caste|quota)$", "", low)
        return _CATEGORY.get(low) or _CATEGORY.get(stripped) or text.upper()
    if field == "gender":
        return _GENDER.get(low, low)
    if field == "employment_status":
        return _EMPLOYMENT.get(low, low)
    if field == "marital_status":
        return _MARITAL.get(low, low)
    if field == "occupation":
        return _OCCUPATION.get(low, low)
    if field == "education_level":
        return _EDUCATION.get(low, low)
    if field == "state":
        return canonical_state(text) or text
    if field == "district":
        return text.title()
    return text


def normalize_memory(memory):
    return {key: normalize_value(key, value) for key, value in (memory or {}).items()}


def normalize_rule(node):
    """Copy of a rule tree whose text values are canonical (so rules and memory compare equal)."""
    if not isinstance(node, dict):
        return node
    out = dict(node)
    if "field" in node:
        value = node.get("value")
        field = node["field"]
        out["value"] = [normalize_value(field, v) for v in value] if isinstance(value, list) else normalize_value(field, value)
    elif isinstance(node.get("conditions"), list):
        out["conditions"] = [normalize_rule(child) for child in node["conditions"]]
    return out


def clean_fact(key, value):
    """Validate + normalise one fact. Returns the cleaned value or raises ValueError."""
    if key == "date_of_birth":
        try:
            dob = value if isinstance(value, date) else date.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError("date_of_birth must be YYYY-MM-DD") from exc
        today = date.today()
        if dob > today or today.year - dob.year > 130:
            raise ValueError("date_of_birth is out of range")
        return dob.isoformat()
    if key in BOOLEAN_FIELDS:
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            value = value.strip().lower() == "true"
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if key in INTEGER_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be a whole number")
        low, high = (0, 130) if key == "age" else (1, 50)
        if not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
        return value
    if key == "annual_income":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 10**12:
            raise ValueError("annual_income must be a non-negative number")
        return int(value) if float(value).is_integer() else float(value)
    if key in TEXT_FIELDS:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be non-empty text")
        cleaned = normalize_value(key, value)
        if len(cleaned) > TEXT_LIMITS[key]:
            raise ValueError(f"{key} is too long")
        return cleaned
    raise ValueError(f"unknown profile field {key!r}")
