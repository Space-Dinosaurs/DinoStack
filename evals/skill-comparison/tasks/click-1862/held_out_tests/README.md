# Held-out tests: click-1862

Extracted at runner start from fix commit `c9a1d7b5f4e2c8a6d3b9f1e5a7c2d8b4f6e3a9c1`
of `https://github.com/pallets/click`.

## Files expected after extraction

- `test_types.py`  (from `tests/test_types.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_types.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 20 s. Hard limit: 120 s.
