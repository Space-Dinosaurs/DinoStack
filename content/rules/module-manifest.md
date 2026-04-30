# Module Manifests

## What it is

A module manifest is a short header block at the top of a non-trivial source file. It lives in the code itself so that comprehension travels with the code — not in Architect plans that get discarded after merge, not in wikis that drift, not in PR descriptions nobody reads six months later. This is the self-describing layer of the system: a reader should be able to open a file and immediately understand what it does, what it depends on, and what breaks if it misbehaves.

## When required

**Required** for any source file that meets one or more of these criteria:

- Exports a public symbol (function, class, type, constant) consumed by another module
- Over ~50 lines of non-trivial logic
- Implements a side-effecting operation: network call, disk I/O, database access, external service interaction, or any operation that cannot be safely retried without thought

**Exempt:**

- Test files and test fixtures
- Generated files (migration outputs, protobuf outputs, GraphQL codegen, etc.)
- One-off scripts not imported by anything else
- Trivial pure utility files (thin wrappers, simple formatters, constants-only files)

**Modified files:** a manifest must be updated when changes meaningfully alter purpose, public API, upstream dependencies, or failure/retry semantics. A manifest that no longer reflects the file is worse than no manifest — it is active misinformation.

## Required fields

Every manifest must cover these six fields. Omit a field only if it genuinely does not apply (e.g., "Performance: standard" is acceptable shorthand; leaving a failure modes field blank is not):

| Field | What to say |
|---|---|
| **Purpose** | One sentence. What this module does and why it exists. |
| **Public API** | The exports or entry points a caller should use. Not an exhaustive type dump — the canonical surface. |
| **Upstream dependencies** | What this module imports, calls, or consumes that it does not own. External libraries, internal modules, environment variables, config values. |
| **Downstream consumers** | Who uses this module. Best-effort: list known callers. "Unknown at creation" is acceptable for new modules; update it when consumers are identified. |
| **Failure modes** | How this module fails, and what the caller needs to know about retrying or recovering. Idempotency guarantees or lack thereof. |
| **Performance** | Expected latency, throughput, or memory profile if non-obvious. Omit or write "standard" if there is nothing a caller needs to know. |

## Format

Use the idiomatic comment or docstring syntax for the language. Do not invent a schema or force a rigid structure — the fields are required, the exact syntax is per-language.

**TypeScript / JavaScript:**

```typescript
/**
 * Purpose: Validates and normalizes incoming webhook payloads before they
 *          enter the processing pipeline.
 *
 * Public API: validateWebhook(raw: unknown): WebhookPayload
 *
 * Upstream deps: zod (schema validation), ./types (WebhookPayload type)
 *
 * Downstream consumers: src/handlers/webhook.ts, src/workers/ingest.ts
 *
 * Failure modes: throws WebhookValidationError on malformed input — callers
 *                must catch and return 400, not 500. No side effects; safe to
 *                retry or call multiple times on the same input.
 *
 * Performance: ~0.2 ms per call; zod parse is synchronous, no I/O.
 */
```

**Python:**

```python
"""
Purpose: Resolves feature flag values for a given user context, with local
         cache to avoid repeated network calls within a request lifecycle.

Public API: get_flag(flag_name: str, context: UserContext) -> bool

Upstream deps: flagsmith SDK, app.cache (RequestScopeCache), config.FLAGSMITH_URL

Downstream consumers: app.views.experiment, app.middleware.ab_test

Failure modes: falls back to flag default on SDK timeout or network error —
               never raises; callers can rely on always receiving a bool.
               Cache is request-scoped; not safe to share across threads.

Performance: first call per flag per request hits network (~50 ms);
             subsequent calls within the same request hit local cache (<1 ms).
"""
```

## Why

Comprehension should live in the code. An Architect plan describes what was decided; it does not travel with the file when the file is moved, refactored, or read by an engineer three months later who was not in that session. A module manifest embeds the essential context — the "why does this exist and what breaks if I change it" — directly in the artifact that persists. This is the self-describing layer of the dark code framework: systems that communicate their own structure rather than requiring external documentation to make sense of them.

A missing or stale manifest is **intent debt**: the artifact stops reflecting what the code is actually for. Technical debt lives in the code, cognitive debt lives in the people who hold the context in their heads, and intent debt lives in the artifacts that are supposed to encode that intent for everyone else. Intent debt is the most insidious of the three, because downstream agents (and humans) read the stale manifest, trust it, and drift further from what the code actually does. Keeping the manifest current is how this file pays down its share of that debt.

## Enforcement

Skeptic applies tiered enforcement:

- **Missing manifest** on a non-trivial module: **Minor finding** (does not block sign-off). Comprehension hygiene; flagged for awareness.
- **Stale manifest** (no longer reflects current purpose, public API, upstream dependencies, downstream consumers, failure modes, or performance characteristics): **Major finding** (blocks sign-off absent a compelling documented reason to defer). A stale manifest is active misinformation - worse than no manifest.
- **Stale manifest whose inaccuracy could cause a caller to mishandle a correctness or security path** (e.g., a documented "no side effects" claim that is no longer true, an idempotency guarantee that no longer holds, a failure-mode contract that has silently changed): **Critical finding**. The manifest is actively misleading callers on a load-bearing path.

Minor findings are addressed via the Minor-fix workflow (see `content/references/skeptic-protocol.md` Section 2 step 4 and Section 6). Major and Critical findings must be resolved before sign-off.

See `content/references/skeptic-protocol.md` for findings classification definitions.
