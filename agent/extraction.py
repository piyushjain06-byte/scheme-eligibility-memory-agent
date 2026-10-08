"""
agent/extraction.py — conservative extraction of plainly stated profile facts (pure: no DB, no network).

Rules of thumb:
  * only FIRST-PERSON, present-tense statements count ("I am 21", "my income is 2 lakh");
  * hedged / hypothetical sentences are ignored ("I might be a student", "if I am 25 ...");
  * clauses about other people are removed ("my father is a farmer") before matching;
  * every value is validated + normalised by normalize.clean_fact before it is returned.
"""
import json
import re
from datetime import date

from agent.normalize import PLACE_NAMES, clean_fact, resolve_place

_HEDGE = re.compile(
    r"\b(?:might|maybe|perhaps|probably|possibly|someday|one day|if i|if my|suppose|what if|"
    r"i was|i wish|used to|i will be|going to be)\b", re.I)
_THIRD = re.compile(
    r"\b(?:my|his|her|their)\s+(?:father|dad|mother|mom|mum|brother|sister|wife|husband|spouse|son|daughter|"
    r"friend|uncle|aunt|neighbou?r|cousin|grand\w+|parents?|boss|colleague|relative)\b"
    r".*?(?=\s+(?:and|but)\s+(?:i|i'm|im|my|we)\b|[,;]|$)", re.I)
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z₹])|\n+")

_I = r"(?:i am|i'm|im)"

# ---- age -------------------------------------------------------------------------------
_AGE = [
    re.compile(rf"\b{_I}\s+(?:a\s+|an\s+)?(\d{{1,3}})[\s-]*(?:years?|yrs?)[\s-]*old\b", re.I),
    re.compile(rf"\b{_I}\s+aged\s+(\d{{1,3}})\b", re.I),
    re.compile(r"\b(?:my age is|i turned|i have turned)\s+(\d{1,3})\b", re.I),
    re.compile(rf"\b{_I}\s+(\d{{1,3}})(?=\s*(?:$|[,.;!?])|\s+(?:and|but|from|so|with|living)\b)", re.I),
]

# ---- date of birth (DD/MM/YYYY, ISO, "12 May 2003") --------------------------------------
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DOB_CTX = r"(?:born\s+on|date\s+of\s+birth(?:\s+is)?|d\.?o\.?b\.?(?:\s+is)?)\s*[:\-]?\s*"
_DOB_ISO = re.compile(_DOB_CTX + r"(\d{4})-(\d{2})-(\d{2})\b", re.I)
_DOB_NUM = re.compile(_DOB_CTX + r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b", re.I)
_DOB_TXT = re.compile(_DOB_CTX + r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?,?\s+(\d{4})\b", re.I)

# ---- income ----------------------------------------------------------------------------
_NOUN = re.compile(
    r"\b((?:(?:my|our|family|household|annual|monthly|yearly|total|combined)\s+)*)(?:income|salary|earnings?)\b(.{0,60})", re.I)
_EARN = re.compile(r"\bi\s+(?:earn|make|get)\s+(.{0,60})", re.I)
_MONEY = re.compile(
    r"(?:rs\.?|inr|₹)?\s*(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|lacs?|lpa|crores?|cr|k|thousand|l)?(?![a-z])\s*"
    r"(?:rupees\b)?\s*(?:/|per\s+|a\s+|each\s+|every\s+)?(month|monthly|mo|year|yearly|annum|annual|pa)?(?![a-z])", re.I)
_NOT_AMOUNT = re.compile(r"\s*(?:in|for|during|since|from)\b", re.I)

# ---- place -----------------------------------------------------------------------------
_PLACES = "|".join(re.escape(name) for name in PLACE_NAMES)
_FROM = re.compile(rf"\b{_I}\b[^.!?]{{0,80}}?\bfrom\s+(?:the\s+state\s+of\s+)?({_PLACES})\b", re.I)
_LIVE = re.compile(
    r"\b(?:i live in|i'm living in|i am living in|i stay in|i reside in|i'm based in|i am based in|i belong to|"
    r"i'm a resident of|i am a resident of|i'm a native of|i am a native of|my state is|resident of|domicile of)"
    rf"\s+(?:the\s+state\s+of\s+)?({_PLACES})\b", re.I)
_DISTRICT = re.compile(r"\bmy district is\s+([A-Za-z][A-Za-z ]{1,38}?)(?=\s*(?:$|[,.;!?])|\s+and\b)", re.I)

# ---- student / education -----------------------------------------------------------------
_NOT_STUDENT = re.compile(rf"\b{_I}\s+not\s+(?:a\s+)?(?:student|studying)\b", re.I)
_STUDENT = re.compile(
    rf"\b{_I}\s+(?:currently\s+)?(?:an?\s+)?(?:\d{{1,3}}[- ]year[- ]old\s+)?"
    r"(?:(?!(?:parent|teacher|father|mother|guardian|tutor|of|for)\b)[a-z-]+\s+){0,2}student\b"
    rf"|\b{_I}\s+(?:currently\s+)?(?:studying|pursuing|enrolled in|doing my)\b|\bi study\b", re.I)
_EDU_FIELD = re.compile(
    rf"\b{_I}\s+(?:(?:a|an)\s+)?(?:\d{{1,3}}[- ]year[- ]old\s+)?(engineering|medical|law|arts|science|commerce|diploma)\s+student\b"
    r"|\bi study\s+(engineering|medical|law|arts|science|commerce|diploma)\b", re.I)
_EDU_DONE = re.compile(
    r"\bi(?:'ve| have)?\s+(?:completed|passed|cleared|finished)\s+(?:my\s+)?"
    r"(10th|12th|graduation|post[- ]?graduation|diploma)\b", re.I)
_EDU_IS = re.compile(rf"\b{_I}\s+(?:a\s+)?(post[- ]?graduate|graduate)\b", re.I)

# ---- employment / occupation -------------------------------------------------------------
_UNEMPLOYED = re.compile(
    rf"\b{_I}\s+(?:currently\s+|presently\s+)?(?:unemployed|jobless|not employed|not working|out of (?:a )?work|without (?:a )?job)\b"
    r"|\bi (?:do not|don't|dont) have (?:a )?job\b", re.I)
_SELF_EMP = re.compile(rf"\b{_I}\s+(?:a\s+)?self[- ]?employed\b", re.I)
_EMPLOYED = re.compile(rf"\b{_I}\s+(?:currently\s+)?(?:employed|salaried)\b|\b{_I}\s+(?:currently\s+)?working\s+(?:in|at|for|as)\b|\bi have a job\b", re.I)
_OCC_NAMES = ("farmer|labou?rer|daily wage worker|daily wager|teacher|driver|shopkeeper|fisherman|fisherwoman|weaver|"
              "artisan|carpenter|tailor|nurse|doctor|engineer|street vendor|vendor|homemaker|housewife|mason|"
              "electrician|plumber|farm worker|agricultural worker|potter|blacksmith|cobbler|barber")
_OCC = re.compile(rf"\b{_I}\s+(?:a\s+|an\s+)?(?:small\s+|marginal\s+|landless\s+)?({_OCC_NAMES})\b", re.I)
_WORK_AS = re.compile(r"\bi work as\s+(?:a\s+|an\s+)?([a-z]+(?:\s[a-z]+){0,2}?)(?=\s+(?:in|at|for|and|but)\b|[,.;!?]|$)", re.I)
_NOT_FARMER = re.compile(rf"\b{_I}\s+not\s+(?:a\s+)?farmer\b", re.I)

# ---- other fields ----------------------------------------------------------------------
_GENDER = re.compile(
    rf"\b{_I}\s+(?:a\s+|an\s+)?(?:\d{{1,3}}[\s-]*years?[\s-]*old\s+)?(?:(?!student\b)[a-z-]+\s+)?"
    r"(female|woman|girl|lady|male|man|boy|transgender)\b", re.I)
_CATEGORY = re.compile(
    rf"\b(?:{_I}|i belong to|my category is)\s+(?:a\s+|an\s+|in\s+|the\s+)?(sc|st|obc|ews)\b(?:\s+(?:category|caste|class))?"
    rf"|\b(?:{_I}|i belong to|my category is)\s+(?:in\s+|the\s+)?(general)\s+(?:category|caste)\b"
    r"|\b(sc|st|obc|ews)\s+(?:category|caste)\b|\bcategory\s+(?:is\s+)?(sc|st|obc|ews|general)\b", re.I)
_NO_DISABILITY = re.compile(
    r"\b(?:i do not|i don't|i dont|i have no|i am not|i'm not)\s+(?:have\s+)?(?:any\s+)?(?:a\s+)?"
    r"(?:disability|disabled|differently[- ]abled|handicapped)\b", re.I)
_DISABILITY = re.compile(
    r"\b(?:i am|i'm|i have|i've)\s+(?:a\s+|an\s+)?(?:(?:physical|visual|hearing|locomotor|mental|intellectual)\s+)?"
    r"(?:disability|disabled|differently[- ]abled|handicapped|visually impaired|hearing impaired|"
    r"physically challenged|physically handicapped|divyang|divyangjan|blind|deaf)\b", re.I)
_MARITAL = re.compile(
    rf"\b{_I}\s+(?:currently\s+)?(?:a\s+)?(married|unmarried|single|widowed|widow|widower|divorced|separated)\b", re.I)
_FAMILY = [
    re.compile(r"\bfamily (?:of|size is|has|consists of)\s+(\d{1,2})\b", re.I),
    re.compile(r"\b(\d{1,2})\s+(?:members|people|persons)\s+(?:are\s+)?in\s+(?:my|our)\s+(?:family|household)\b", re.I),
    re.compile(r"\b(?:we are|there are)\s+(\d{1,2})\s*(?:members|people|persons)?\s+in\s+(?:my|our|the)\s+(?:family|household)\b", re.I),
]

_MULTIPLIER = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "lpa": 1e5, "l": 1e5,
               "crore": 1e7, "crores": 1e7, "cr": 1e7, "k": 1e3, "thousand": 1e3}


def _money(prefix, tail):
    if _NOT_AMOUNT.match(tail):
        return None
    match = _MONEY.search(tail)
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    amount *= _MULTIPLIER.get((match.group(2) or "").lower(), 1)
    period = (match.group(3) or "").lower()
    if period in {"month", "monthly", "mo"} or "monthly" in prefix.lower():
        amount *= 12
    return int(round(amount))


def _date_of_birth(s):
    for pattern, order in ((_DOB_ISO, "ymd"), (_DOB_NUM, "dmy"), (_DOB_TXT, "dMy")):
        match = pattern.search(s)
        if not match:
            continue
        a, b, c = match.groups()
        try:
            if order == "ymd":
                return date(int(a), int(b), int(c)).isoformat()
            if order == "dmy":
                return date(int(c), int(b), int(a)).isoformat()
            month = _MONTHS.get(b[:3].lower())
            return date(int(c), month, int(a)).isoformat() if month else None
        except ValueError:
            return None
    return None


def _extract_sentence(s):
    facts = {}
    for pattern in _AGE:
        match = pattern.search(s)
        if match:
            facts["age"] = int(match.group(1))
            break
    dob = _date_of_birth(s)
    if dob:
        facts["date_of_birth"] = dob

    noun, earn = _NOUN.search(s), _EARN.search(s)
    value = _money(noun.group(1), noun.group(2)) if noun else (_money("", earn.group(1)) if earn else None)
    if value is not None:
        facts["annual_income"] = value

    place = _FROM.search(s) or _LIVE.search(s)
    if place:
        state = resolve_place(place.group(1))
        if state:
            facts["state"] = state
    district = _DISTRICT.search(s)
    if district:
        facts["district"] = district.group(1).strip()

    if _NOT_STUDENT.search(s):
        facts["student_status"] = False
    elif _STUDENT.search(s):
        facts["student_status"] = True
    edu = _EDU_FIELD.search(s)
    if edu:
        facts["education_level"] = (edu.group(1) or edu.group(2)).lower()
    else:
        done = _EDU_DONE.search(s) or _EDU_IS.search(s)
        if done:
            facts["education_level"] = done.group(1)

    if _UNEMPLOYED.search(s):
        facts["employment_status"] = "unemployed"
    elif _SELF_EMP.search(s):
        facts["employment_status"] = "self-employed"
    elif _EMPLOYED.search(s):
        facts["employment_status"] = "employed"

    if _NOT_FARMER.search(s):
        facts["farmer_status"] = False
    occupation = _OCC.search(s) or _WORK_AS.search(s)
    if occupation:
        facts["occupation"] = occupation.group(1)
        if occupation.group(1).lower() == "farmer":
            facts["farmer_status"] = True
            facts["occupation"] = "farmer"

    gender = _GENDER.search(s)
    if gender:
        facts["gender"] = gender.group(1)
    category = _CATEGORY.search(s)
    if category:
        facts["category"] = next(group for group in category.groups() if group)
    if _NO_DISABILITY.search(s):
        facts["disability_status"] = False
    elif _DISABILITY.search(s):
        facts["disability_status"] = True
    marital = _MARITAL.search(s)
    if marital:
        facts["marital_status"] = marital.group(1)
    for pattern in _FAMILY:
        match = pattern.search(s)
        if match:
            facts["family_size"] = int(match.group(1))
            break
    return facts


def extract_explicit_facts(text):
    """Return {field: cleaned value} for facts the user plainly states about themselves."""
    raw = {}
    for sentence in _SPLIT.split(text or ""):
        if not sentence.strip() or _HEDGE.search(sentence):
            continue
        raw.update(_extract_sentence(_THIRD.sub(" ", sentence)))
    facts = {}
    for key, value in raw.items():
        try:
            facts[key] = clean_fact(key, value)
        except ValueError:
            continue
    return facts


# ---- optional LLM-assisted extraction (validation is shared with the regex path) ----------
LLM_KEYS = {"age", "date_of_birth", "gender", "state", "district", "annual_income", "occupation", "education_level",
            "family_size", "marital_status", "disability_status", "student_status", "employment_status",
            "category", "farmer_status"}
LLM_SYSTEM_PROMPT = (
    "Extract profile facts that the USER states about THEMSELVES in the message. Reply with one JSON object only. "
    "Allowed keys: age (integer), date_of_birth (YYYY-MM-DD), gender, state (Indian state/UT), district, "
    "annual_income (rupees per YEAR as a number; convert lakh/crore/monthly), occupation, education_level, "
    "family_size (integer), marital_status, disability_status (bool), student_status (bool), "
    "employment_status, category (GENERAL/OBC/SC/ST/EWS), farmer_status (bool). "
    "Include a key ONLY if it is stated explicitly and currently true for the user. Ignore other people, "
    "hypotheticals and questions. Never guess. If nothing qualifies reply {}."
)
_GROUNDED = {"district", "occupation", "education_level"}
_CUES = {
    "annual_income": r"income|earn|salary|lakh|lac|lpa|crore|₹|\brs\b|rupee",
    "student_status": r"student|study|studying|pursuing|college|school|university",
    "farmer_status": r"farm|agricult|kisan|cultivat",
    "disability_status": r"disab|handicap|divyang|differently|blind|deaf|impair",
}


def parse_llm_facts(raw, source_text):
    """Validate an LLM reply: JSON object, known keys, clean values, and evidence in the user's own words."""
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        data = json.loads(raw[start:end])
    except (ValueError, AttributeError):
        return {}
    if not isinstance(data, dict):
        return {}
    text = source_text.casefold()
    digits = set(re.findall(r"\d+", source_text))
    facts = {}
    for key, value in data.items():
        if key not in LLM_KEYS or value is None:
            continue
        try:
            cleaned = clean_fact(key, value)
        except ValueError:
            continue
        if key in _GROUNDED and str(value).casefold() not in text:
            continue
        if key == "state" and not any(name in text and resolve_place(name) == cleaned for name in PLACE_NAMES):
            continue
        if key in {"age", "family_size"} and str(cleaned) not in digits:
            continue
        if key in _CUES and not re.search(_CUES[key], source_text, re.I):
            continue
        facts[key] = cleaned
    return facts
