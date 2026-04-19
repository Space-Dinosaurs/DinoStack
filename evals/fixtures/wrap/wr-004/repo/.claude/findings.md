# Findings

## Promise-rejection handlers missing in webhook consumers (2026-02-14)

**Context:** two webhook routes lacked `.catch()` on a `fetch()` call inside the handler. Unhandled rejection crashed the worker once under sustained traffic.

**Pattern:** async code paths in webhook consumers that omit rejection handling risk silent worker crashes.

**Instances observed:** 2.

## Unawaited async inside webhook handlers silently drops errors (2026-03-01)

**Context:** a webhook handler called `await logEvent(...)` but the inner promise chain dropped a secondary fetch without awaiting it. Errors from the secondary call never propagated to the handler's try/catch.

**Pattern:** fire-and-forget async inside an otherwise-awaited handler loses error context and corrupts telemetry.

**Instances observed:** 3.

## Migration rollback not exercised in CI (2026-02-20)

**Context:** three migrations in a row merged without `down.sql` having been run in CI. One broke in staging when a rollback was attempted.

**Pattern:** merge gates that only run forward-apply miss schema-reversibility bugs.

**Instances observed:** 3.

## Tests import production-only config module (2026-02-25)

**Context:** `tests/orders.test.ts` imported `src/config/production.ts` directly, which reads env vars on load. CI passed by accident because the env vars happened to be set.

**Pattern:** tests that transitively require production config modules are brittle to env changes.

**Instances observed:** 1.

## Secrets committed via .env.example typo (2026-03-05)

**Context:** a real API key was pasted into `.env.example` instead of `.env` during an onboarding session. Caught by the secret scanner pre-commit hook.

**Pattern:** onboarding docs that show example env values invite typos into the wrong file.

**Instances observed:** 1.

## Feature flag checks inverted after refactor (2026-03-08)

**Context:** a refactor renamed `isEnabled` to `isDisabled` but left one callsite with the old semantics. Flag flipped the wrong direction for that path for 6 hours.

**Pattern:** flag-name refactors that flip polarity need a grep pass on every callsite.

**Instances observed:** 1.

## N+1 query in order history endpoint (2026-03-12)

**Context:** `/orders/:id/history` loaded line items in a loop instead of eager-loading. 2s p95 under 200 items.

**Pattern:** relationship loaders default to lazy; list endpoints need explicit eager-load.

**Instances observed:** 2.

## Docker image size creep from dev dependencies (2026-03-15)

**Context:** prod image grew from 180MB to 420MB over 3 weeks after dev deps started shipping in the runtime layer.

**Pattern:** single-stage Dockerfiles drift toward bundling dev deps unless the prune step is pinned.

**Instances observed:** 1.

## Clock-skew flakes in JWT tests (2026-03-18)

**Context:** JWT tests used real `Date.now()` with a 30s expiry window. Tests flaked on slower CI runners.

**Pattern:** time-sensitive test code needs injected clocks, not wallclock.

**Instances observed:** 1.

## Pagination cursor leaks internal IDs (2026-03-22)

**Context:** opaque-looking cursor was base64 of a raw DB id. External consumers could enumerate by incrementing.

**Pattern:** pagination cursors without HMAC or opaque re-encoding expose ordering information.

**Instances observed:** 1.

## CORS preflight blocked on auth header (2026-03-25)

**Context:** new auth header caused preflights to fail because the CORS config listed only the prior header.

**Pattern:** CORS allowed-headers lists are an audit surface after every auth change.

**Instances observed:** 1.

## Log redaction skipped on error path (2026-03-29)

**Context:** the happy-path logger redacted PII correctly; the error logger printed the full request body. One prod incident leaked user emails into logs.

**Pattern:** redaction that lives in one logger call but not its siblings is a recurring footgun.

**Instances observed:** 1.

## Retry storm from missing jitter (2026-04-03)

**Context:** retry backoff was deterministic exponential; a transient downstream outage produced synchronized retries that extended the outage by 8 minutes.

**Pattern:** retry policies without jitter amplify downstream outages.

**Instances observed:** 1.

## Dependency upgrade broke type inference silently (2026-04-08)

**Context:** a minor bump to the validation library relaxed a generic constraint. Existing callers compiled but lost a narrowing guarantee.

**Pattern:** minor version bumps in typed libraries can erode inference without a type error.

**Instances observed:** 1.
