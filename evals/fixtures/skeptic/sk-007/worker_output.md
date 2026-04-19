# Worker output - sk-007

**Task:** Drop the `legacy_external_id` column from the `orders` table. It
was added three years ago as a bridge during the migration off the old Magento
storefront and we stopped writing to it eighteen months ago.

**What I did:**
- Added Alembic migration `20260419_drop_legacy_external_id.py`.
- Removed the column definition from the `Order` ORM model.

**Other repo artifacts that touch orders:** `src/reporting/monthly.py`
contains a reconciliation job that runs nightly:

```python
def build_legacy_reconciliation_rows(session) -> list[dict]:
    rows = session.execute(
        "SELECT id, customer_id, legacy_external_id, total_cents "
        "FROM orders WHERE legacy_external_id IS NOT NULL"
    ).fetchall()
    return [
        {"order_id": r[0], "external_ref": r[2], "amount_cents": r[3]}
        for r in rows
    ]
```

This is wired into the Celery beat schedule (`src/jobs/beat.py`). There is
also a CSV export endpoint in `src/api/admin_orders.py` that Marshmallow-
serializes the full Order model.

**Quality gates:** pytest passes against a fresh SQLite test DB. `alembic
upgrade head` runs cleanly on a fresh database.
