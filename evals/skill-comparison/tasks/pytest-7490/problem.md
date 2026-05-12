# Task: pytest-7490

**SWE-bench instance ID:** `pytest-dev__pytest-7490`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** single-file
**Repository:** https://github.com/pytest-dev/pytest
**Base commit:** `7f7a36478abe7dd1fa993b115d22606aa0e35e88`

## Problem description

In pytest 6, dynamically adding an `xfail` marker inside a running test no
longer causes the test failure to be ignored. This broke behaviour that was
reliable in pytest 5.

```python
import pytest

def test_dynamic_xfail(request):
    request.node.add_marker(pytest.mark.xfail())
    assert False  # Should be reported as XFAIL, not FAILED
```

In pytest 6, the above test is reported as `FAILED` instead of `XFAIL`,
because the dynamic marker is not checked at the failure-handling point in
`src/_pytest/skipping.py`.

## Expected behaviour

Dynamically adding an `xfail` marker during `runtest_call` should cause the
test to be treated as `XFAIL` (expected failure) just as a statically
declared `@pytest.mark.xfail` would.

## Held-out test references

- `testing/test_skipping.py`

Tests `TestXFail::test_dynamic_xfail_set_during_runtest_failed` and
`TestXFail::test_dynamic_xfail_set_during_runtest_passed_strict` must
transition from fail to pass.
