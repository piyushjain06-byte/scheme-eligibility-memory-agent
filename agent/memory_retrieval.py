"""Compact keyword based personal-memory retrieval, isolated from scheme RAG."""
import re

from agent.extraction import extract_explicit_facts
from database.models import Conversation, EpisodicMemory, Message, UserGoal, UserTask

_MEMORY_STOP_WORDS = {
    "about", "and", "are", "did", "do", "for", "from", "have", "how", "is", "it",
    "me", "my", "of", "the", "this", "to", "was", "what", "when", "where", "which",
    "who", "with", "you",
}
_USER_DISCLOSURE = re.compile(
    r"^\s*(?:i(?:['’](?:m|ve)|\s+(?:am|have|like|love|prefer|enjoy|work|live|study|"
    r"studied|speak|play|follow|was born|own|grew up))\b|"
    r"my\s+(?:name|favorite|favourite|hobby|job|goal|dream|language|interest|"
    r"music|sport|food|color|colour)\b)",
    re.IGNORECASE,
)
_MEMORY_TOPIC = re.compile(
    r"\bmy\s+(favorite|favourite)\s+([a-z][a-z ]{0,30}?)\s+(?:is|are|was|were)\b",
    re.IGNORECASE,
)


def _memory_sentences(content, terms, broad_recall):
    """Keep only relevant non-profile sentences; profile facts have a canonical latest value."""
    sentences = re.split(r"(?<=[.!?])\s+|[\r\n]+", content)
    selected = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence or extract_explicit_facts(sentence):
            continue
        words = {word.lower().strip(".,?!:;()[]{}\"'") for word in sentence.split()}
        if broad_recall or terms & words:
            selected.append(sentence)
    return selected


def is_user_disclosure(text):
    """Whether a message starts with a plain first-person personal statement."""
    return isinstance(text, str) and _USER_DISCLOSURE.search(text) is not None


def retrieve_user_statements(user_id, query, limit=4):
    """Find relevant first-person statements in this user's saved chat history."""
    query_text = (query or "").strip()
    terms = {
        word.lower().strip(".,?!:;()[]{}\"'")
        for word in query_text.split()
        if len(word) > 2 and word.lower().strip(".,?!:;()[]{}\"'") not in _MEMORY_STOP_WORDS
    }
    query_lower = query_text.lower()
    broad_recall = any(phrase in query_lower for phrase in (
        "what do you know about me", "what do you remember about me", "tell me about myself",
        "what have i told you about myself", "what did i tell you about myself",
        "my bio", "my profile",
    ))
    messages = (
        Message.query.join(Conversation, Message.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user_id, Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(200)
        .all()
    )
    matches = {}
    for message in messages:
        content = message.content.strip()
        if not content or content.casefold() == query_text.casefold() or not _USER_DISCLOSURE.search(content):
            continue
        for sentence in _memory_sentences(content, terms, broad_recall):
            words = {word.lower().strip(".,?!:;()[]{}\"'") for word in sentence.split()}
            overlap = len(terms & words)
            topic_match = _MEMORY_TOPIC.search(sentence)
            topic = (
                f"{topic_match.group(1).lower()} {topic_match.group(2).strip().lower()}"
                if topic_match else sentence.casefold()
            )
            previous = matches.get(topic)
            candidate = (overlap, message.created_at, sentence)
            if previous is None or candidate[:2] > previous[:2]:
                matches[topic] = candidate
    ranked = sorted(matches.values(), key=lambda row: (row[0], row[1]), reverse=True)
    return [f"You previously shared: {sentence[:300]}" for _, _, sentence in ranked[:limit]]


def retrieve_personal_context(user_id, query, limit=6):
    terms = {w.lower().strip(".,?!:;()[]{}\"'") for w in (query or "").split() if len(w) > 2}
    rows = []
    for task in UserTask.query.filter_by(user_id=user_id).filter(UserTask.status.in_(["PENDING", "IN_PROGRESS", "WAITING", "SNOOZED"])).all():
        text = f"{task.title} {task.description or ''} {task.next_action or ''}"
        overlap = len(terms & {w.lower().strip(".,?!:;()[]{}\"'") for w in text.split()})
        if overlap or any(word in (query or "").lower() for word in ("continue", "previous", "last time", "still need", "left")):
            rows.append((overlap + 2, task.updated_at, f"Open task: {task.title} ({task.status}). {task.description or ''}"))
    for goal in UserGoal.query.filter_by(user_id=user_id, status="ACTIVE").all():
        text = f"{goal.title} {goal.description or ''}"
        overlap = len(terms & {w.lower().strip(".,?!:;()[]{}\"'") for w in text.split()})
        if overlap:
            rows.append((overlap + 1, goal.updated_at, f"Active goal: {goal.title}."))
    for episode in EpisodicMemory.query.filter_by(user_id=user_id).order_by(EpisodicMemory.created_at.desc()).limit(50).all():
        overlap = len(terms & {w.lower().strip(".,?!:;()[]{}\"'") for w in episode.summary.split()})
        if overlap:
            rows.append((overlap, episode.created_at, f"Past event: {episode.summary}"))
    rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [row[2][:500] for row in rows[:limit]]
