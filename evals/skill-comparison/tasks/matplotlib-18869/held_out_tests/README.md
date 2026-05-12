# Held-out tests: matplotlib-18869

Extracted at runner start from fix commit `f18d73d84b6fe03cbdb7efb35a02c48a2d8ff07d`
of `https://github.com/matplotlib/matplotlib`.

## Files expected after extraction

- `test_figure.py`  (from `lib/matplotlib/tests/test_figure.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_figure.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 40 s. Hard limit: 120 s.
