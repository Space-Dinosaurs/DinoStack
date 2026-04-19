# Findings

<!-- Auto-managed by /wrap and /implement-ticket. Target: under 15 entries. Architect reads this at plan time. -->

## Log redaction skipped on error path (2026-01-14)

**Context:** the happy-path logger redacted PII but the error-logger path printed full request bodies. One incident leaked user emails into logs.

**Pattern:** redaction that lives in one logger call but not its siblings is a recurring footgun.

**Instances observed:** 2.

## Error-path logging bypasses PII redaction in catch blocks (2026-01-28)

**Context:** a catch block near the payments handler logged err.request directly, bypassing the redaction helper used on the success path.

**Pattern:** logger helpers applied on happy path but not in catch-block logging leak PII through error output.

**Instances observed:** 2.

## N+1 query in order history endpoint (2026-02-02)

**Context:** /orders/:id/history loaded line items in a loop instead of eager-loading. 2s p95 under 200 items.

**Pattern:** relationship loaders default to lazy; list endpoints need explicit eager-load.

**Instances observed:** 2.

## Migration rollback not exercised in CI (2026-02-09)

**Context:** three forward-only migrations merged without down.sql running in CI. One broke in staging when a rollback was attempted.

**Pattern:** merge gates that only run forward-apply miss schema-reversibility bugs.

**Instances observed:** 3.

## Tests import production-only config module (2026-02-16)

**Context:** tests/orders.test.ts imported src/config/production.ts directly. CI passed by accident because the env vars happened to be set.

**Pattern:** tests that transitively require production config modules are brittle to env changes.

**Instances observed:** 1.

## Clock-skew flakes in JWT tests (2026-02-20)

**Context:** JWT tests used real Date.now() with a 30s expiry window. Tests flaked on slower CI runners.

**Pattern:** time-sensitive test code needs injected clocks, not wallclock.

**Instances observed:** 1.

## Feature flag checks inverted after refactor (2026-02-24)

**Context:** a refactor renamed isEnabled to isDisabled but left one callsite with the old semantics. Flag flipped the wrong direction for that path for 6 hours.

**Pattern:** flag-name refactors that flip polarity need a grep pass on every callsite.

**Instances observed:** 1.

## Pagination cursor leaks internal IDs (2026-02-28)

**Context:** opaque-looking cursor was base64 of a raw DB id. External consumers could enumerate by incrementing.

**Pattern:** pagination cursors without HMAC or opaque re-encoding expose ordering information.

**Instances observed:** 1.

## CORS preflight blocked on auth header (2026-03-04)

**Context:** new auth header caused preflights to fail because the CORS config listed only the prior header.

**Pattern:** CORS allowed-headers lists are an audit surface after every auth change.

**Instances observed:** 1.

## Retry storm from missing jitter (2026-03-09)

**Context:** retry backoff was deterministic exponential; a transient outage produced synchronized retries that extended the outage by 8 minutes.

**Pattern:** retry policies without jitter amplify downstream outages.

**Instances observed:** 1.

## Dependency upgrade broke type inference silently (2026-03-14)

**Context:** a minor bump to zod relaxed a generic constraint. Callers compiled but lost a narrowing guarantee.

**Pattern:** minor version bumps in typed libraries can erode inference without a type error.

**Instances observed:** 1.

## Docker image size creep from dev dependencies (2026-03-18)

**Context:** prod image grew from 180MB to 420MB over 3 weeks after dev deps started shipping in the runtime layer.

**Pattern:** single-stage Dockerfiles drift toward bundling dev deps unless the prune step is pinned.

**Instances observed:** 1.

## Secrets committed via env example typo (2026-03-22)

**Context:** a real API key was pasted into .env.example instead of .env during onboarding. Caught by the secret scanner pre-commit hook.

**Pattern:** onboarding docs that show example env values invite typos into the wrong file.

**Instances observed:** 1.

## Unbounded fanout in webhook consumer (2026-03-26)

**Context:** a webhook consumer forked a downstream call per incoming event without any concurrency cap, exhausting sockets during a burst.

**Pattern:** async fanouts in consumers without a semaphore or queue saturate the connection pool.

**Instances observed:** 1.

## Snapshot-test drift after date formatter change (2026-04-02)

**Context:** snapshot tests captured locale-dependent date output. A Node minor bump changed the formatter and 30 snapshots went stale silently.

**Pattern:** snapshot tests that include locale-formatted values are fragile to runtime upgrades.

**Instances observed:** 1.
