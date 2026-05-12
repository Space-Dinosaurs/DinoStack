# Held-out tests: scikit-learn-9274

Extracted at runner start from fix commit `d2c8b6a4f1e7c3d9b5a8f2e4c6a1d7b3f5e9c2a8`
of `https://github.com/scikit-learn/scikit-learn`.

## Files expected after extraction

- `test_pipeline.py`  (from `sklearn/tests/test_pipeline.py`)
- `test_data.py`      (from `sklearn/preprocessing/tests/test_data.py`)

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_pipeline.py /scoring/tests/test_data.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## Time budget

Estimated: 55 s. Hard limit: 120 s.
