# ip-006-platform

Internal customer platform. Next.js web app in `pages/`, with an API surface
covered by pytest against a sidecar Python service mounted at `/api/*` via a
Next.js rewrite. Unit tests live in Jest.

## What is in flight

- Billing rewrite from the legacy Ruby service to TypeScript handlers.
- Customer import pipeline that consumes a nightly S3 drop and dedupes by
  external ID before writing to Postgres.
- Feature-flag rollout using Statsig; the SDK is wrapped in a thin provider
  so handlers can read flags without pulling Statsig into every module.
- Search reindex job rebuilding the Meilisearch index from Postgres every
  four hours; queued via a Cloudflare Worker cron trigger.
- Admin impersonation flow behind a short-lived JWT that the ops team uses
  to debug tenant-scoped issues.
- Cost-observability dashboard that reads the Vercel usage API and posts a
  weekly summary to the #platform-cost Slack channel.

## External services we depend on

- Stripe for billing; webhooks arrive at `/api/stripe/webhook` and are
  verified against `STRIPE_WEBHOOK_SECRET`.
- Postmark for transactional mail; templates are stored in the Postmark
  dashboard, not in this repo.
- Segment for product analytics; events fan out to Amplitude and
  Customer.io.
- Statsig for feature flags; evaluated server-side in handlers and mirrored
  to the client via a hydration payload.

## Test layout

Unit tests live next to their modules as `*.test.ts` and run under Jest
(`pnpm test:unit`). API-contract tests live under `tests/api/` and run under
pytest (`pnpm test:api`) against a Python sidecar that stands in for the
upstream billing service during local runs. The two runners do not share
fixtures; each seeds its own database snapshot.

## Deploy pattern

Production is deployed by the ops team via a manually-triggered GitHub
Actions workflow that tags `release-<date>` and pushes to Vercel. We do not
auto-deploy on merge to main; a release manager runs the workflow after a
canary window closes clean. Staging redeploys on every merge to main.

## Historical incidents worth knowing

- 2025-11: A Meilisearch reindex deleted the prior index before the new one
  finished building, causing a twelve-minute search outage. Reindex now
  builds into a shadow index and atomically swaps.
- 2026-01: A Statsig fetch timeout during cold-start caused handlers to
  serve the default flag value for thirty seconds after deploy. We now
  prewarm the flag cache during the Next.js instrumentation hook.
- 2026-03: A Stripe webhook replay loop hit our idempotency table after a
  Postgres failover lost an unflushed transaction. We switched the
  idempotency store to Redis with a fourteen-day TTL.

## Team conventions

- All database migrations run against staging for at least forty-eight
  hours before a production apply.
- Feature flags default to off in code; on is an explicit rollout decision.
- Logs are structured JSON with a `trace_id` field; plain-string logs fail
  lint.
- PRs that touch `pages/api/` require a security-auditor review before
  merge, regardless of size.
- Every cron job writes a heartbeat row to `ops.cron_heartbeat` so the
  on-call dashboard can flag silent failures.
