"""Compact keyword based personal-memory retrieval, isolated from scheme RAG."""
from database.models import EpisodicMemory, UserGoal, UserTask


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
