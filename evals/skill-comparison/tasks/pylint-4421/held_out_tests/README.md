# Held-out tests: pylint-4421

Extracted at runner start from fix commit `c81eb1b28e5dc3d65a9e1b23f2b7f9ba07f3f28a`
of `https://github.com/PyCQA/pylint`.

## Files expected after extraction

- `test_lint.py`  (from `tests/test_lint.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_lint.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 20 s. Hard limit: 120 s.
