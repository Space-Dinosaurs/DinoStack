# Memory

- **2026-01-15:** Database migrations use Alembic (see `migrations/`). We deliberately chose Alembic over any ORM-auto-generated migration tool so every schema change is hand-reviewed SQL before it reaches prod.
- **2026-02-20:** Pricing tier lookups are cached in Redis with a 300s TTL; invalidation on tier updates is best-effort via pub/sub.
