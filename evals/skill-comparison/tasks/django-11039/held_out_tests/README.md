# Held-out tests: django-11039

Extracted at runner start from fix commit `b7c3a6e9f2d1e8a4c5f7b9d2e6c4a8b1f3e7d9a2`
of `https://github.com/django/django`.

## Files expected after extraction

- `test_queryset_pickle.py`  (from `tests/queryset_pickle/tests.py`)
- `test_q.py`               (from `tests/queries/test_q.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_queryset_pickle.py /scoring/tests/test_q.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 45 s. Hard limit: 120 s.
