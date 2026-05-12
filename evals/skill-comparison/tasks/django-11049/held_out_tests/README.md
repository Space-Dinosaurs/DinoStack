# Held-out tests: django-11049

Extracted at runner start from fix commit `de8e4a70a3e66ed93b72e73f1e67ddb0f7e152c0`
of `https://github.com/django/django`.

## Files expected after extraction

- `test_forms.py`  (from `tests/auth_tests/test_forms.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_forms.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 30 s. Hard limit: 120 s.
