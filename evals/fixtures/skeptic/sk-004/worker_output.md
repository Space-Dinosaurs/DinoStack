# Worker output - sk-004

**Task:** Implement password-reset request + confirm endpoints.

**What I did:**
- Added `src/auth/reset.py` with `request_reset(email)` and `confirm_reset(token, new_password)`.
- Tokens are generated via `secrets.token_urlsafe(32)`, hashed with SHA-1,
  and stored in the `password_resets` table alongside the user ID and an
  expiry timestamp.
- On confirm, we hash the provided token with SHA-1 and compare against the
  stored hash.
- Rate-limited to 3 requests per email per hour.

**Quality gates:** pytest passes, ruff clean.
