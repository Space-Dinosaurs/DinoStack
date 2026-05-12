# Task: scikit-learn-9274

**SWE-bench instance ID:** `scikit-learn__scikit-learn-9274`
**Difficulty:** multi-file
**Repository:** https://github.com/scikit-learn/scikit-learn
**Base commit:** `f3e8f4a2d6c9b1e7a5f3d8c2e6a4b8f1d3c7e9a5`

## Problem description

`Pipeline.fit` passes `sample_weight` incorrectly when a pipeline step
implements `fit_transform`.  The `sample_weight` keyword is routed
through `_fit` which calls `fit_transform` on steps that support it, but
the dispatch logic does not forward `sample_weight` to `fit_transform`
when the step's `fit_transform` signature accepts it.

This manifests as silent wrong-weight training (the weight array is
silently dropped), not an exception.

The fix requires changes in two places:
1. `sklearn/pipeline.py` - pass `sample_weight` in the `fit_transform`
   dispatch call inside `_fit`.
2. `sklearn/utils/validation.py` - ensure `check_consistent_length`
   validates the weight array shape against the sample count before the
   pipeline routes it.

## Reproduction

```python
import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression

X = np.random.randn(100, 5)
y = np.random.randn(100)
w = np.random.rand(100)

pipe = Pipeline([("scaler", StandardScaler()), ("reg", LinearRegression())])
pipe.fit(X, y, reg__sample_weight=w)
# Scaler is fitted without weights - wrong but no error raised
```

## Expected behaviour

`sample_weight` arrays routed through `Pipeline.fit` should be forwarded
to every step that accepts them, including steps that use `fit_transform`.

## Held-out test references

- `sklearn/tests/test_pipeline.py` (pipeline weight-routing test)
- `sklearn/preprocessing/tests/test_data.py` (StandardScaler weighted-fit
  regression guard)

Both from fix commit `d2c8b6a4f1e7c3d9b5a8f2e4c6a1d7b3f5e9c2a8`.

## Constraints for the fix

- Modify only `sklearn/pipeline.py` and `sklearn/utils/validation.py`.
- Do not change public Pipeline API.
- All existing tests in both test files must pass.
