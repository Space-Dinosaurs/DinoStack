# Task: astropy-12907

**SWE-bench instance ID:** `astropy__astropy-12907`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** single-file
**Repository:** https://github.com/astropy/astropy
**Base commit:** `d16bfe05a744909de4b27f5875fe0d4ed41ce607`

## Problem description

`separability_matrix` does not compute separability correctly for nested
CompoundModels.

```python
from astropy.modeling import models as m
from astropy.modeling.separability import separability_matrix

cm = m.Linear1D(10) & m.Linear1D(5)
print(separability_matrix(m.Pix2Sky_TAN() | cm))
# Returns wrong result: all True instead of separability-aware values
```

The bug is in `_cstack` in `astropy/modeling/separable.py`. When building
the coordinate stack for a right sub-model, the code sets the lower-right
block to the scalar `1` instead of using the right submatrix `right`, causing
any nested compound model to report full non-separability.

## Expected behaviour

`separability_matrix` should return a matrix that reflects the actual
separability of the compound model's inputs and outputs.

## Held-out test references

- `astropy/modeling/tests/test_separable.py`

Tests `test_separable[compound_model6-result6]` and
`test_separable[compound_model9-result9]` must transition from fail to pass.
