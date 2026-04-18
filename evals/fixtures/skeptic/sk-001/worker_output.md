# Worker output - sk-001

**Task:** Add a Redis-backed token-bucket rate limiter to the API gateway so we
can cap per-API-key request rates before they hit the origin service.

**What I did:**
- Added `src/ratelimit/bucket.py` (80 LOC) implementing `TokenBucket` with
  `allow(key)`, `refill(key)`, and a class-level `from_env()` constructor.
- Wired `TokenBucket.allow(api_key)` into `src/gateway/middleware.py`'s request
  hook; rejects with HTTP 429 on deny.
- Added unit tests in `tests/ratelimit/test_bucket.py` with a fake Redis.

**Quality gates:** `pytest -q` passes (41 tests). `ruff check` clean.
`mypy --strict src/ratelimit` clean.

**Out of scope:** did not migrate existing IP-based limiter in `legacy/` -
separate ticket.
