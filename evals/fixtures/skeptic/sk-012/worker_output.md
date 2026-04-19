# Worker output - sk-012

**Task:** Add a reusable pagination helper. The frontend needs a `has_next`
boolean so the "Next page" button can be enabled or disabled without
issuing an extra request.

**What I did:**
- Added `src/api/paginate.py` with a single function `paginate(query, page,
  page_size)` that returns `{page, page_size, items, has_next}`.
- Added two unit tests: one for a mid-range page (page 1 of 25 items at
  page_size 10, expects `has_next=True`), and one for the partial last page
  (page 3 of 25 at page_size 10, expects `has_next=False`).

**Design note:** I considered running a separate `COUNT(*)` query to
determine total and derive `has_next` from `page * page_size < total`, but
chose to avoid the extra round-trip. Inferring `has_next` from the returned
row count is cheaper.

**Quality gates:** `pytest tests/api/test_paginate.py` passes (2/2). ruff
clean. mypy clean.
