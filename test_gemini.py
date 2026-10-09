"""
test_gemini.py - diagnoses your .env + agent/llm.py with Gemini / OpenAI. Never prints your full key.

Put it in the project root (next to app.py) and run:   python test_gemini.py
"""
import json
import os
import urllib.error
import urllib.request

from config import BASE_DIR, Config  # loads .env
from agent.llm import make_client


def mask(key):
    return f"{key[:3]}...{key[-2:]} (length {len(key)})" if key else "(empty)"


def native_check(key, model):
    """Call Gemini's own endpoint (not the OpenAI-style one) to see if the KEY itself works."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps({"contents": [{"parts": [{"text": "Reply with one word: ok"}]}]}).encode()
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        text = data["candidates"][0]["content"]["parts"][0].get("text", "").strip()
        print("NATIVE GEMINI PASS -> key works on Gemini's own endpoint:", text[:60])
        return True
    except urllib.error.HTTPError as exc:
        print("NATIVE GEMINI FAIL -> HTTP", exc.code, exc.read().decode("utf-8", "replace")[:300])
    except Exception as exc:
        print("NATIVE GEMINI FAIL ->", type(exc).__name__, str(exc)[:200])
    return False


def main():
    key, model, emb = Config.OPENAI_API_KEY, Config.OPENAI_CHAT_MODEL, Config.EMBEDDING_MODEL
    print("Base URL  :", os.environ.get("OPENAI_BASE_URL") or "(default OpenAI)")
    print("Chat model:", model, "| Embedding model:", emb)
    print("Key used  :", mask(key))

    # python-dotenv does NOT override variables already set in Windows; check for that.
    try:
        from dotenv import dotenv_values
        file_key = (dotenv_values(os.path.join(BASE_DIR, ".env")).get("OPENAI_API_KEY") or "").strip()
        print("Key in .env:", mask(file_key))
        if file_key and key and file_key != key:
            print("WARNING: a different OPENAI_API_KEY is set in your computer's environment and it overrides .env!")
            print("         Remove it (Windows: search 'Edit environment variables') or close and reopen the terminal/VS Code.")
        if file_key != file_key.strip("\"' "):
            print("WARNING: .env value has quotes/spaces around it.")
    except Exception as exc:
        print("(could not read .env directly:", exc, ")")

    if not key or "PASTE" in key or "tumhari" in key.lower():
        print("FAIL: OPENAI_API_KEY is empty or still a placeholder.")
        return
    print()

    native_ok = native_check(key, model) if os.environ.get("OPENAI_BASE_URL", "").find("generativelanguage") != -1 else None

    client = make_client(key)
    try:
        reply = client.chat.completions.create(
            model=model, temperature=0,
            messages=[{"role": "user", "content": "Reply with exactly: [S1] ok"}])
        print("CHAT PASS ->", (reply.choices[0].message.content or "").strip()[:80])
    except Exception as exc:
        print("CHAT FAIL ->", type(exc).__name__, str(exc)[:300])

    try:
        vec = client.embeddings.create(model=emb, input="student scholarship").data[0].embedding
        print("EMBEDDING PASS -> vector length", len(vec))
    except Exception as exc:
        print("EMBEDDING FAIL ->", type(exc).__name__, str(exc)[:200])
        print("(Embeddings are optional: use --no-embeddings and chat still works.)")

    if native_ok is True:
        print("\nVerdict: your key is fine; only the OpenAI-style endpoint rejects it. Tell Claude this result.")
    elif native_ok is False:
        print("\nVerdict: the key itself is not accepted. Re-copy it with the 'Copy key' button or create a new one.")


if __name__ == "__main__":
    main()