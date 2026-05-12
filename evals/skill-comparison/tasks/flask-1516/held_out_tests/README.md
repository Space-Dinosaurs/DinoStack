# Held-out tests: flask-1516

Extracted at runner start from fix commit `9c7b1d6e4f5a8c2e3d7b9a1c5e3f6a2d8b4c7e1f`
of `https://github.com/pallets/flask`.

## Files expected after extraction

- `test_app.py`  (from `tests/test_app.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_app.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 18 s. Hard limit: 120 s.
