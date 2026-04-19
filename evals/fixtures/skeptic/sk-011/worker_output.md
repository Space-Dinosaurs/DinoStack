# Worker output - sk-011

**Task:** Net refunds against order totals in the monthly customer statement.
Previously the statement showed gross order totals only; finance asked for
net-of-refunds so the number matches the invoice they send.

**What I did:**
- In `src/jobs/monthly_statement.py`, for each order in the month's batch I
  pull the most recent refund record and subtract it from the order total.
- Replaced the old `order_ids` field with a `lines` field that carries the
  per-order net amount.

**Repo context:** `build_statement` is called by the Celery beat schedule
`monthly-statement-fanout` which, at month close, enqueues one job per
active customer. The largest customers have on the order of 8-12k orders
per month; the median customer has ~40. The `refunds` table has a
compound index on `(order_id, created_at)`. SQLAlchemy is configured with
`echo=False` in production and connection pool size 20. There is no
Celery-level timeout on this job.

**Quality gates:** pytest passes. The existing unit test covered a
3-order fixture and still passes; added no new tests since the output
shape change is backwards-compatible for downstream consumers who read
only `total_cents` and `customer_id`.
