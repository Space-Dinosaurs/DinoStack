# Task: sympy-16988

**SWE-bench instance ID:** `sympy__sympy-16988`
**Difficulty:** single-file
**Repository:** https://github.com/sympy/sympy
**Base commit:** `a9e6f89c80e1dc9f7e62b3e1e30f5e14a0a3b012`

## Problem description

`Add.as_two_terms()` returns incorrect results for symbolic expressions
with more than two summands.  The method is documented to split an `Add`
into `(first_term, rest)`, but the implementation indexes directly into
`self.args` and discards the tail when there are 3+ terms:

```python
from sympy.abc import x, y, z
expr = x + y + z
a, b = expr.as_two_terms()
assert a + b == expr   # AssertionError for 3+ terms
```

## Reproduction

```python
from sympy.abc import x, y, z
from sympy import Add

expr = x + y + z
first, rest = expr.as_two_terms()
print(first + rest)   # x + y  (wrong; z is dropped)
```

## Expected behaviour

For an `Add` with n terms, `as_two_terms()` should return
`(args[0], Add(*args[1:]))` so that `first + rest == expr` always holds.

## Held-out test reference

`sympy/core/tests/test_arit.py` (from fix commit
`c6c5c9f3f36e9b1a4e6d42e0e3d7e9b9a6f7c1e2`).

The new test:
- Checks 2-term, 3-term, and 4-term expressions.
- Verifies `a + b == original_expr` in each case.
- Checks that `Mul.as_two_terms` is unaffected (regression guard).

## Constraints for the fix

- Modify only `sympy/core/add.py`.
- Do not change the public `as_two_terms` signature.
- All existing `test_arit.py` tests must pass.
