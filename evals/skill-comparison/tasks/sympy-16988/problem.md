# Task: sympy-16988

**SWE-bench instance ID:** `sympy__sympy-16988`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** single-file
**Repository:** https://github.com/sympy/sympy
**Base commit:** `e727339af6dc22321b00f52d971cda39e4ce89fb`

## Problem description

`Intersection` does not remove duplicates, returning `EmptySet` instead of
the correct `Piecewise` expression when the same set appears more than once.

```python
from sympy import *
x = Symbol('x')

>>> Intersection({1}, {1}, {x})
EmptySet()  # WRONG

>>> Intersection({1}, {x})
{1}         # correct (Piecewise simplification)
```

The expected answer for `Intersection({1}, {1}, {x})` is
`Piecewise(({1}, Eq(x, 1)), (S.EmptySet, True))` or `{1}` depending on
simplification.

The bug is in `sympy/sets/sets.py` in the `Intersection` evaluation logic
which fails to deduplicate argument sets before computing.

## Expected behaviour

`Intersection` should deduplicate its arguments and return the correct
result regardless of whether the same set is passed multiple times.

## Held-out test references

- `sympy/sets/tests/test_sets.py`

Tests `test_imageset` and `test_intersection` must transition from fail to pass.
