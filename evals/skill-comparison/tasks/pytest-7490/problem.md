# Task: pytest-7490

**SWE-bench instance ID:** `_pytest__pytest-7490`
**Difficulty:** multi-file
**Repository:** https://github.com/pytest-dev/pytest
**Base commit:** `c4a8d6b2f5e1c9a3d7b8f2e4a6c8d1b3f5e9a7c2`

## Problem description

`CaptureFixture.readouterr()` silently drops buffered output when a test
raises a `BaseException` subclass (such as `KeyboardInterrupt` or
`SystemExit`) during teardown.

The capture subsystem uses an internal buffer that is flushed during
fixture finalization.  When the finalization path receives a
`BaseException`, `CaptureFixture.__exit__` is skipped (because
`BaseException` is not caught by the `except Exception` guard), so the
buffer is never flushed before the runner's teardown code clears it.

The fix requires changes in two places:
1. `src/_pytest/capture.py` - ensure `CaptureFixture.__exit__` is
   called even when `BaseException` propagates.
2. `src/_pytest/runner.py` - co-ordinate the capture cleanup order with
   the fixture teardown on the `BaseException` path.

## Reproduction

```python
import pytest

def test_keyboard_interrupt(capsys):
    print("important output")
    raise KeyboardInterrupt

# After the run, capsys.readouterr().out should contain "important output"
# but it is empty because the buffer was dropped.
```

## Expected behaviour

Output buffered via `capsys` (or `capfd`) should always be retrievable
via `readouterr()`, even when the test raises a `BaseException`.

## Held-out test references

- `testing/test_capture.py` (BaseException capture regression test)
- `testing/test_runner.py` (runner teardown order test)

Both from fix commit `b1d9c7a5f3e2d8a6c4b9f1e3d7a5c8b2f4e6d9a1`.

## Constraints for the fix

- Modify only `src/_pytest/capture.py` and `src/_pytest/runner.py`.
- Do not change the public `CaptureFixture` API.
- All existing tests in both test files must pass.
