# Task: matplotlib-18869

**SWE-bench instance ID:** `matplotlib__matplotlib-18869`
**Difficulty:** single-file
**Repository:** https://github.com/matplotlib/matplotlib
**Base commit:** `b0efbc5b87cc87b4f75a4ef1a6b79e0c0d8f3046`

## Problem description

`Figure.set_size_inches` raises `TypeError` when called with a single
positional argument that is a 2-tuple (or list), e.g.:

```python
fig.set_size_inches((8, 6))
```

The signature is `set_size_inches(w, h=None, ...)`.  When a 2-tuple is
passed as `w`, the method should unpack it into `(w, h)` per the
docstring's advertised usage, but instead it passes the tuple as-is to
the internal size setter, which expects two separate floats.

## Reproduction

```python
import matplotlib.pyplot as plt
fig = plt.figure()
fig.set_size_inches((8, 6))  # TypeError: invalid size
```

## Expected behaviour

`fig.set_size_inches((8, 6))` should be equivalent to
`fig.set_size_inches(8, 6)` and set the figure to 8 x 6 inches.

## Held-out test reference

`lib/matplotlib/tests/test_figure.py` (from fix commit
`f18d73d84b6fe03cbdb7efb35a02c48a2d8ff07d`).

The relevant test function verifies:
- `set_size_inches((8, 6))` sets width=8 and height=6.
- `set_size_inches(8, 6)` still works (no regression).
- `set_size_inches([8, 6])` (list form) also works.

## Constraints for the fix

- Modify only `lib/matplotlib/figure.py`.
- Do not change the public method signature.
- All existing `test_figure.py` tests must pass.
