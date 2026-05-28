# ADR: Team-level telemetry aggregation and visualization

- Status: Proposed
- Date: 2026-05-28
- Authors: conductor (drafted for future-session implementation)
- Related: `docs/planning/gap-1-cost-latency-observability.md`, `content/references/events-log.md`

## Context

The agentic-engineering methodology instruments per-spawn telemetry into `.agentic/events.jsonl` (schema in `content/references/events-log.md`). Each project's events file captures wall_seconds, full token breakdown (input / output / cache_creation / cache_read), agent name, model tier, task_id, Skeptic findings, and session_total rollups. The Stop hook writes the session_total entry; the conductor writes everything else.

Today the file is:

- **Per-project.** Lives at `<project>/.agentic/events.jsonl`.
- **Per-machine.** Gitignored; never replicated.
- **Inspected via CLI only.** `/agentic-cost` and `/agentic-calibrate` render tables from the local file.

This works for a solo developer auditing their own runs. It does not work for a team that needs to answer questions like:

- How much are we spending per engineer per week?
- Which agents dominate cost across the team?
- Is Skeptic finding-density drifting up or down month over month?
- Which projects burn the most clock time per merged PR?
- Are some engineers hitting rate limits or stalling on review loops more than others?

There is no shipper, no central store, and no dashboard. Codex and Gemini sessions also emit nothing (V2-deferred).

## Decision

Build a thin team-telemetry pipeline in three layers, scoped to the smallest thing that delivers cross-engineer visibility.

### Layer 1: Shipper (per developer)

A small daemon or cron job that tails `.agentic/events.jsonl` files across all projects on a developer's machine and ships new lines to a central store. Properties:

- **Opt-in via `~/.agentic/telemetry.yml`.** Absent file = no shipping (preserves current local-only default).
- **Discovers project event files** by scanning a configured list of project roots (default: `~/Documents/Development/**/.agentic/events.jsonl`, configurable).
- **Tracks cursor per file** in `~/.agentic/telemetry-state.json` (last shipped byte offset). Resumes after restart.
- **Adds developer identity** at ship time: `{developer_id, machine_id, project_slug}` envelope around each raw event. Identity comes from `telemetry.yml` (operator-set, e.g. github handle); no auto-discovery from git config to avoid leaking personal email.
- **Batching:** ships every 60s or every 100 events, whichever first. Backpressure via local queue file.
- **Failure mode:** ship failures are silent and retried; never blocks the conductor; never modifies events.jsonl.

### Layer 2: Store

Pick the cheapest store that supports SQL and timeseries queries. Two options on the table:

- **Option A: SQLite + Litestream to S3.** Single-file DB, Litestream replicates to S3 continuously. Cheap, simple, single-writer (the shipper aggregator). Good for teams under ~10 engineers.
- **Option B: ClickHouse Cloud or BigQuery.** Real columnar OLAP. Better for >10 engineers or >1M events / month. ~$30-50/month floor.

**Recommendation:** start with Option A. Migrate to B when query time on the dashboard exceeds 2s or storage exceeds 5 GB. Schema is identical (one wide table mirroring the JSONL with the identity envelope columns).

The aggregator is a small HTTP endpoint (Cloudflare Worker or single Fly.io container) that accepts batched events from the shippers, validates the envelope, appends to the store. No queue, no fan-out, no schema service.

### Layer 3: Dashboard

A single-page dashboard (Grafana on Option A/B, or a small Next.js page hitting the store directly). MVP charts:

- **Tokens per developer per week** (stacked area by agent).
- **Wall-clock per developer per week** (stacked area by agent).
- **USD cost per developer per week** (derived from `~/.agentic/pricing.yml`, shipped as a reference table).
- **Top 10 most expensive sessions** (drill-down to per-spawn detail).
- **Skeptic findings density over time** (per project, per developer).
- **Spawn count by agent type** (rolling 30-day).

Auth: GitHub OAuth restricted to a configured org. No PII beyond developer handle.

## Alternatives considered

1. **Do nothing; rely on per-developer `/agentic-cost`.** Rejected: cannot answer team-level questions; cost overruns surface only after someone manually reports them.
2. **Sync `events.jsonl` via git.** Rejected: the file is append-only and high-churn; git history would balloon; merge conflicts on every push.
3. **Push directly from conductor (no shipper daemon).** Rejected: adds network failure surface to the hot path; violates "never block the conductor on telemetry" invariant. The Stop hook is also too narrow - it fires only at clean session exit, which misses crashed sessions.
4. **Anthropic Console / native usage dashboard.** Rejected: only shows API-key-level spend, not per-agent / per-task attribution. Useful as a sanity check but does not answer the questions above.
5. **Adopt an existing observability tool (Honeycomb, Datadog, etc.).** Deferred. Possible later for richer querying, but the schema is small and the volume is low. Native first.

## Consequences

**Positive:**
- Team gets per-developer, per-project, per-agent cost and time visibility.
- Skeptic calibration signals become a team-level trend, not a per-laptop metric.
- Schema reuse: zero changes to `events.jsonl` writers; the shipper is purely additive.
- Opt-in design preserves current behavior for any developer who does not configure telemetry.

**Negative:**
- New infrastructure to operate (aggregator endpoint + store + dashboard).
- Identity envelope is a small privacy surface; needs an explicit team agreement on what's captured (handle yes, email no, source content no).
- Codex / Gemini sessions remain dark until V2 schema work lands; team metrics will under-count those flows.

**Neutral:**
- Cost: Option A is roughly $5/month (S3 + Cloudflare Worker free tier); dashboard hosting free on Grafana Cloud free tier or self-hosted.

## Open questions

1. **Identity model.** GitHub handle as developer_id is the obvious default; confirm before implementation.
2. **Store choice.** Default to Option A unless someone has a strong preference for ClickHouse / BigQuery up front.
3. **Aggregator hosting.** Cloudflare Worker vs Fly.io vs Vercel Function. Pick whichever the team already pays for.
4. **Pricing source.** Ship `~/.agentic/pricing.yml` per developer (current model), or maintain a single central pricing table the dashboard reads? Central is simpler and avoids drift.
5. **Backfill.** Do we backfill historical `events.jsonl` files on first install, or only ship new events? Recommend new-events-only for the MVP to avoid initial-burst spikes.
6. **PR / merge correlation.** Worth joining telemetry to git history (which session produced which PR) for cost-per-merged-PR metrics? Deferred to v2.

## Implementation sketch

Five units, each independently shippable:

1. **Shipper daemon** (`packages/telemetry-shipper/`): Go or Rust single-binary; reads `telemetry.yml`; tails event files; POSTs batches. Tier 2 engineer task.
2. **Aggregator endpoint** (`packages/telemetry-aggregator/`): single HTTP handler; validates envelope; appends to store. Tier 2.
3. **Store provisioning** (`infra/telemetry/`): Litestream + S3 bucket + SQLite schema migration. Tier 2.
4. **Dashboard** (`apps/telemetry-dashboard/`): Grafana JSON definitions OR a Next.js page; six MVP charts. Tier 2.
5. **Docs + opt-in flow** (`docs/technical/team-telemetry.md`): how to enable, what gets captured, how to opt out. Tier 1.

Each unit gets its own Brief; the bundle is a Plan-tier task (cross-track architectural change, persistent state, multi-package).

## Verification

- Shipper unit tests: cursor recovery after crash, no-double-ship under concurrent project sessions, opt-out preserves no-network behavior.
- Aggregator: schema validation rejects malformed envelopes; idempotent on duplicate event_id.
- End-to-end: a session run on one developer's machine appears in the dashboard within 2 minutes.
- Cost: verify monthly bill stays under $10 for a 5-engineer team across the first month.
