# Task: astropy-7606

**SWE-bench instance ID:** `astropy__astropy-7606`
**Difficulty:** single-file
**Repository:** https://github.com/astropy/astropy
**Base commit:** `0df94ff7097961e92b43d75d0e12c0db5a682b80`

## Problem description

`NDData` arithmetic operations (addition, subtraction, multiplication,
division) fail with an `AttributeError` when one operand carries a unit
(e.g. `u.m`) and the other has `unit=None`.

Specifically, the internal `_arithmetic` method attempts to call
`.unit.decompose()` on an operand before checking whether that operand
has a non-None unit.  The fix requires adding a guard so that a
`None`-unit operand is treated as dimensionless during arithmetic
propagation.

## Reproduction

```python
from astropy.nddata import NDData
import astropy.units as u

a = NDData([1, 2, 3], unit=u.m)
b = NDData([1, 2, 3])          # unit=None
result = a.add(b)              # raises AttributeError: 'NoneType' has no attribute 'decompose'
```

## Expected behaviour

The operation should succeed, treating `b` as dimensionless, and return
an `NDData` object whose unit is the unit of `a`.

## Held-out test reference

`astropy/tests/test_nddata.py` (checked out from fix commit
`9ab04dcd5d7c57d0d7b6fe75de91bb8a87d0a18f`).

The test verifies:
- `NDData.add` with a unitless operand returns correct values and unit.
- `NDData.multiply` / `.divide` behave analogously.
- No regression on the existing all-unit and all-dimensionless cases.

## Constraints for the fix

- Modify only `astropy/nddata/nddata.py` (single-file fix).
- Do not change the public API signature of `_arithmetic` or `add/subtract/multiply/divide`.
- All existing `test_nddata.py` tests must still pass.
