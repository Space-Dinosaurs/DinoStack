# Held-out tests: sphinx-7440

Extracted at runner start from fix commit `a8c2d6b4f1e9a3c7d5b8f2e4a6c1d9b3f7e5a2c8`
of `https://github.com/sphinx-doc/sphinx`.

## Files expected after extraction

- `test_ext_autodoc.py`  (from `tests/test_ext_autodoc.py`)
- `test_domain_py.py`    (from `tests/test_domain_py.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_ext_autodoc.py /scoring/tests/test_domain_py.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 60 s. Hard limit: 120 s.
