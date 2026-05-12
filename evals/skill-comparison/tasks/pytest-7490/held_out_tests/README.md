# Held-out tests: pytest-7490

Extracted at runner start from fix commit `b1d9c7a5f3e2d8a6c4b9f1e3d7a5c8b2f4e6d9a1`
of `https://github.com/pytest-dev/pytest`.

## Files expected after extraction

- `test_capture.py`  (from `testing/test_capture.py`)
- `test_runner.py`   (from `testing/test_runner.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_capture.py /scoring/tests/test_runner.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 50 s. Hard limit: 120 s.
