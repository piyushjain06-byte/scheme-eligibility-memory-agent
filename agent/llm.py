"""
agent/llm.py - one place that builds the LLM client, so the provider can be switched from .env alone.

Put this file at  agent/llm.py.  Then in .env set (example: free Google Gemini):
    OPENAI_API_KEY=<your Gemini key from https://aistudio.google.com/apikey>
    OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
    OPENAI_CHAT_MODEL = "gemini-3.8-flash"
    EMBEDDING_MODEL=gemini-embedding-001
Leave OPENAI_BASE_URL empty to use OpenAI itself.
"""
import os


def make_client(api_key):
    from openai import OpenAI  # imported here so tests that fake the 'openai' module keep working
    try:
        from flask import current_app, has_app_context
        base_url = current_app.config.get("OPENAI_BASE_URL", "") if has_app_context() else os.environ.get("OPENAI_BASE_URL", "")
    except RuntimeError:
        base_url = os.environ.get("OPENAI_BASE_URL", "")
    base_url = (base_url or "").strip()
    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "25"))
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    try:
        return OpenAI(**kwargs, timeout=timeout, max_retries=0)
    except TypeError:  # simple fake clients used in tests
        return OpenAI(**kwargs)
