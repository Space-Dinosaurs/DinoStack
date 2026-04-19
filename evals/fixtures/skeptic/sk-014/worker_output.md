# Worker output - sk-014

**Task:** Extract the signed-cents formatting expression from
`StatementRow.formatted_delta` into a reusable helper on
`src/util/money.py`, since the billing service needs the same formatting
for a new adjustment-log endpoint next sprint.

**What I did:**
- Added `format_signed_cents(n)` to `src/util/money.py` with identical
  semantics to the inlined expression.
- Replaced the inlined expression in `StatementRow.formatted_delta` with
  a call to the new helper.
- Added unit tests for the new helper covering positive, negative, and
  zero cases. Updated the manifest header on `money.py` to reflect the
  new public name.

**Quality gates:** `pytest tests/util/ tests/reporting/` passes (11/11,
previous 9 + 2 new). ruff clean. mypy clean. The existing statement-
rendering snapshot test still matches byte-for-byte; behavior is
identical.
