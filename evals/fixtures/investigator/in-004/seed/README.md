# ops notes

## Observed incident

Operators report that the `daily_stats` row for a given day is sometimes
short on `kind="signup"` counts the morning after, compared to the count
they get by re-running the same window an hour later against the same
events table. The discrepancy does not reproduce every night.

Relevant facts operators have gathered:

- The events table receives writes from an ingest pipeline owned by a
  separate team. The ingest team documents that mobile-client events can
  arrive several minutes after the wall-clock time they were generated,
  and that the `ts` column is stamped by a server-side trigger on insert
  (not by the client).
- The nightly rollup runs at 02:00 UTC via cron.
- The `daily_stats` table has a primary key on `(day)` and the rollup
  path uses an upsert, so a re-run later in the day overwrites the
  earlier row.
- We do not have logs of what rows the rollup job actually read on the
  nights when the discrepancy appeared. The ingest pipeline also does
  not log per-event receipt timestamps.
- The `ts` column in events is not indexed by insert-order; its index is
  on `ts` alone.
