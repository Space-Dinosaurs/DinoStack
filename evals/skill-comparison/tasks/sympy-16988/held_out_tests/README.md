# Held-out tests: sympy-16988

Extracted at runner start from fix commit `c6c5c9f3f36e9b1a4e6d42e0e3d7e9b9a6f7c1e2`
of `https://github.com/sympy/sympy`.

## Files expected after extraction

- `test_arit.py`  (from `sympy/core/tests/test_arit.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_arit.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 35 s. Hard limit: 120 s.
