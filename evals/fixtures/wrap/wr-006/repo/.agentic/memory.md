# Memory

Accumulated stable facts for payments-core. Auto-managed by /wrap.

## Database

- **2026-02-05:** Postgres connection string lives in `DATABASE_URL`. Local dev uses port 5433 (not 5432) to avoid colliding with the system Postgres. Overrides via `PAYMENTS_DB_URL` are ignored by the pool; this was an intentional change after the 2026-01 incident.
- **2026-02-12:** Migrations run via `npm run migrate:up`. The migration tool is `db-migrate@1.4.2` pinned in package.json. Do not bump across major versions without rerunning the full replay suite locally.
- **2026-02-18:** Row-level locks on `payments` table use `SELECT ... FOR UPDATE SKIP LOCKED` inside the idempotency worker. Anything else deadlocks under concurrent refunds.

## Money handling

- **2026-02-22:** All monetary amounts are stored and transmitted as integer minor-units (cents for USD, pence for GBP). The `Money` type in `src/money.ts` enforces this; never import `Big` or `decimal.js` - they were removed after the 2026-01 rounding bug.
- **2026-02-28:** Currency conversion goes through `src/fx.ts` which pulls rates from the internal rate service at `http://rates.svc.internal:8080`. Caching is 60 seconds; do not drop the cache without load testing.

## Idempotency

- **2026-03-04:** Idempotency keys live in `payments_idempotency` with a 24-hour TTL enforced by a nightly purge job. The key format is `pay_<uuid4>`; external callers supply it in the `Idempotency-Key` header.
- **2026-03-10:** The idempotency worker is at `src/workers/idempotency.ts`. It must be the sole writer to `payments_idempotency`; any other writer breaks the SKIP LOCKED invariant noted above.

## Webhooks

- **2026-03-15:** Stripe webhook signature verification uses `STRIPE_WEBHOOK_SECRET` loaded at boot. Signature mismatches return 400 immediately and do not enqueue a retry.
- **2026-03-20:** Webhook retries are handled by a separate `retry-router` process listening on queue `payments.webhook.retry`; do not retry inline inside the request handler.

## Deployment

- **2026-03-25:** Deploys go through GitHub Actions workflow `.github/workflows/deploy-prod.yml`. The `release-orchestrator` agent is the only writer to `CHANGELOG.md` and version bumps.
- **2026-03-30:** Rollback is `kubectl rollout undo deployment/payments-core -n payments`. Do not manually edit the deployment spec; it is managed by Argo.

## Testing

- **2026-04-05:** The test DB is created fresh per CI run via `scripts/ci-db-bootstrap.sh`. Local dev can reuse a long-lived DB seeded with `npm run seed:dev`.
- **2026-04-10:** Integration tests live under `tests/integration/` and require `DATABASE_URL` pointing at a non-production database. A guard at the top of each file aborts if `NODE_ENV === 'production'`.
