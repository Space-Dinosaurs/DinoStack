# Architectural notes

- Billing handlers are the TypeScript rewrite target; the legacy Ruby
  service is read-only and will be decommissioned after parity is proven.
- Postgres is the source of truth for customer records; Meilisearch is a
  derived index rebuilt on a four-hour cron.
- Authorization is tenant-scoped via a `tenant_id` column on every
  customer-facing table; admin impersonation routes through a short-lived
  JWT minted by the ops console.
- Observability ships to Datadog via OpenTelemetry; trace IDs propagate
  from the edge through the Python sidecar.
- Secrets are managed in 1Password and synced into Vercel and the GitHub
  Actions environment via the 1Password CLI during the release workflow.
