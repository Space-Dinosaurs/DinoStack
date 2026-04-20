# Memory

<!-- Stable facts about this project: architecture, key paths, decisions and their rationale. -->

- **2026-02-10:** Public API rate limit is 100 requests/sec per token, enforced by the Redis-backed fixed-window middleware in `src/middleware/rateLimit.ts`. 60-second window, per-token key.
- **2026-03-02:** Auth tokens are opaque 32-byte random strings (base64url), not JWTs; validation is a single Redis GET against the token hash.
