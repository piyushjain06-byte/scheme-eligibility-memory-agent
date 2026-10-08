"""
agent/ratelimit.py — tiny in-memory sliding-window limiter.

State lives on the Flask app (app.extensions), so every app instance, including each test's, starts clean.
It is per-process: with several gunicorn workers use Flask-Limiter + Redis instead.
Set a limit to 0 in config to disable it.
"""
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import current_app, jsonify, request, session

_LOCK = threading.Lock()


def rate_limit(name, config_key, default, window=60, per_user=False):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            limit = current_app.config.get(config_key, default)
            if not limit:
                return view(*args, **kwargs)
            ident = session.get("user_id") if per_user and session.get("user_id") is not None else request.remote_addr
            now = time.monotonic()
            with _LOCK:
                store = current_app.extensions.setdefault("rate_limit_store", defaultdict(deque))
                hits = store[(name, ident)]
                while hits and now - hits[0] > window:
                    hits.popleft()
                if len(hits) >= limit:
                    retry = int(window - (now - hits[0])) + 1
                    response = jsonify(error="Too many requests. Please wait a moment and try again.")
                    response.status_code = 429
                    response.headers["Retry-After"] = str(retry)
                    return response
                hits.append(now)
            return view(*args, **kwargs)

        return wrapped

    return decorator
