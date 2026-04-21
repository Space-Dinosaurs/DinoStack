# src/auth/middleware.py (relevant excerpt)
# Wraps every incoming request; authenticates via session token header.

import time


class SessionCache:
    """In-process cache of validated session rows.

    NOTE: the README says this is a "warm cache to avoid a DB hit per
    request", but the implementation never evicts and has no size cap.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple] = {}

    def get(self, token: str):
        return self._store.get(token)

    def put(self, token: str, row: tuple) -> None:
        # Bug: no eviction, no TTL, no max size.
        self._store[token] = row


_cache = SessionCache()


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        token = environ.get("HTTP_X_SESSION_TOKEN", "")
        row = _cache.get(token)
        if row is None:
            row = self._load_session_from_db(token)
            _cache.put(token, row)
        environ["session"] = row
        return self.app(environ, start_response)

    def _load_session_from_db(self, token: str):
        # loader elided; returns (user_id, role, expiry_ts)
        ...
