# Held-out tests: requests-3362

Extracted at runner start from fix commit `9a1c13d21e04264f9abb0cfbf7b7bf05e1ea2ca6`
of `https://github.com/psf/requests`.

## Files expected after extraction

- `test_requests.py`  (from `tests/test_requests.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_requests.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 15 s. Hard limit: 120 s.
