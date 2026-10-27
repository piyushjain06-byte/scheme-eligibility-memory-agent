"""Speed-up patch: stops chat answers from hanging or crawling.

Run once from the project root (next to app.py):   python patch_speed.py
Backups are saved as <file>.speedbak. Then restart:  python app.py

What it fixes
  1. agent/llm.py   - the model client had NO timeout (default is 10 minutes), so one slow
                      provider call looked like the agent "never answers". Now 25s, no hidden retries.
  2. agent/chat.py  - a timeout now falls back to the instant rule-based answer instead of waiting;
                      fewer/shorter retries on 429/503; scheme + rule + source rows are loaded in
                      3 queries instead of hundreds (lazy-loading per scheme was the slow part with
                      a big dataset); eligibility questions no longer pay for an embedding call.
  3. agent/rag.py   - retrieve() can be limited to the few schemes already chosen, instead of
                      loading every chunk and embedding vector in the database on each question.
"""
import shutil
import sys
from pathlib import Path

PATCHES = {
    "agent/llm.py": [
        (
            '    if base_url:\n'
            '        return OpenAI(api_key=api_key, base_url=base_url)\n'
            '    return OpenAI(api_key=api_key)\n',
            '    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "25"))\n'
            '    kwargs = {"api_key": api_key}\n'
            '    if base_url:\n'
            '        kwargs["base_url"] = base_url\n'
            '    try:\n'
            '        return OpenAI(**kwargs, timeout=timeout, max_retries=0)\n'
            '    except TypeError:  # simple fake clients used in tests\n'
            '        return OpenAI(**kwargs)\n',
        ),
    ],
    "agent/chat.py": [
        ("MODEL_ATTEMPTS = 3\n", "MODEL_ATTEMPTS = 2\n"),
        (
            '            status = getattr(exc, "status_code", None)\n'
            '            if status not in (429, 500, 502, 503, 504):\n'
            '                raise\n',
            '            status = getattr(exc, "status_code", None)\n'
            '            timed_out = type(exc).__name__ in {"APITimeoutError", "APIConnectionError"}\n'
            '            if status not in (429, 500, 502, 503, 504) and not timed_out:\n'
            '                raise\n',
        ),
        (
            '            if attempt < MODEL_ATTEMPTS - 1:\n'
            '                time.sleep(2 * 2 ** attempt)  # 2s, 4s\n',
            '            if timed_out:\n'
            '                break  # the wait was already spent; answer from the rules instead\n'
            '            if attempt < MODEL_ATTEMPTS - 1:\n'
            '                time.sleep(1.5)\n',
        ),
        (
            '    sources = (\n'
            '        SchemeSource.query.filter_by(status="VERIFIED")\n'
            '        .join(Scheme)\n'
            '        .filter(Scheme.active.is_(True))\n'
            '        .all()\n'
            '    )\n',
            '    from sqlalchemy.orm import contains_eager\n'
            '    sources = (\n'
            '        SchemeSource.query.filter_by(status="VERIFIED")\n'
            '        .join(Scheme)\n'
            '        .filter(Scheme.active.is_(True))\n'
            '        .options(contains_eager(SchemeSource.scheme).selectinload(Scheme.sources),\n'
            '                 contains_eager(SchemeSource.scheme).selectinload(Scheme.rules))\n'
            '        .all()\n'
            '    )\n',
        ),
        (
            '    if hasattr(client, "embeddings") and _any_embedded_chunks():\n',
            '    if not eligibility_question and hasattr(client, "embeddings") and _any_embedded_chunks():\n',
        ),
        (
            '    retrieved = retrieve(retrieval_query, top_k=RETRIEVE_TOP_K, embedding=query_vector)\n',
            '    retrieved = retrieve(retrieval_query, top_k=RETRIEVE_TOP_K, embedding=query_vector,\n'
            '                         scheme_ids=[s.scheme_id for s in selected] if eligibility_question else None)\n',
        ),
    ],
    "agent/rag.py": [
        (
            '             verified_only=True, category=None, scheme_id=None, source_type=None,\n',
            '             verified_only=True, category=None, scheme_id=None, scheme_ids=None, source_type=None,\n',
        ),
        (
            '    if scheme_id is not None:\n'
            '        q = q.filter(Scheme.id == scheme_id)\n',
            '    if scheme_id is not None:\n'
            '        q = q.filter(Scheme.id == scheme_id)\n'
            '    if scheme_ids is not None:\n'
            '        q = q.filter(Scheme.id.in_(list(scheme_ids)))\n',
        ),
    ],
}


def main():
    root = Path(".")
    if not (root / "app.py").exists():
        sys.exit("Run this from the project root (app.py not found).")
    loaded = {}
    for name, edits in PATCHES.items():
        path = root / name
        if not path.exists():
            sys.exit(f"{name} not found.")
        text = path.read_text(encoding="utf-8")
        if "LLM_TIMEOUT_SECONDS" in text or "scheme_ids" in text and name.endswith("rag.py") or "contains_eager" in text:
            sys.exit(f"{name} looks already patched.")
        for number, (old, new) in enumerate(edits, 1):
            if text.count(old) != 1:
                sys.exit(f"{name}: edit {number} found {text.count(old)} matches (expected 1). Send me that file.")
            text = text.replace(old, new)
        loaded[path] = text
    for path, text in loaded.items():
        shutil.copyfile(path, str(path) + ".speedbak")
        path.write_text(text, encoding="utf-8")
        print("patched", path)
    print("Done. Restart the app. Optional in .env:  LLM_TIMEOUT_SECONDS=25")


if __name__ == "__main__":
    main()
