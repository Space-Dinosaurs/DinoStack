# Task: sklearn-10297

**SWE-bench instance ID:** `scikit-learn__scikit-learn-10297`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** multi-file
**Repository:** https://github.com/scikit-learn/scikit-learn
**Base commit:** `b90661d6a46aa3619d3eec94d5281f5888add501`

## Problem description

`RidgeClassifierCV` raises an error when `store_cv_values=True` is passed,
even though the parameter is documented in the class's docstring.

```python
from sklearn.linear_model import RidgeClassifierCV
import numpy as np

X = np.array([[1, 2], [3, 4], [5, 6]])
y = np.array([0, 1, 0])
clf = RidgeClassifierCV(store_cv_values=True)
clf.fit(X, y)  # raises TypeError: __init__() got an unexpected keyword argument
```

The parameter exists in the docstring but was never implemented in the
underlying `__init__` or `fit` methods of `RidgeClassifierCV`.

## Expected behaviour

`RidgeClassifierCV(store_cv_values=True).fit(X, y)` should succeed and
store per-fold cross-validation values in `clf.cv_values_`.

## Held-out test references

- `sklearn/linear_model/tests/test_ridge.py`

Test `test_ridge_classifier_cv_store_cv_values` must transition from fail
to pass.
