# Worker output - sk-010

**Task:** Implement the free-tier pricing rebate described in the product
spec (PROD-4412): free-tier subscribers pay nothing on their first 100 usage
units in a billing period, and the standard per-unit rate thereafter.

**What I did:**
- Added a `free` branch to `compute_charge` in `src/billing/pricing.py` that
  subtracts the first 100 units and charges at the standard rate for the
  overage.
- Tightened two existing test names for readability.

**Quality gates:** `pytest tests/billing/` passes (both tests green). ruff
clean. mypy clean. No other call sites of `compute_charge` required changes.

**Out of scope:** UI display of the rebate line-item is PROD-4413, separate
PR.
