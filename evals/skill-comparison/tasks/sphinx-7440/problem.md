# Task: sphinx-7440

**SWE-bench instance ID:** `sphinx-doc__sphinx-7440`
**Difficulty:** multi-file
**Repository:** https://github.com/sphinx-doc/sphinx
**Base commit:** `e1d2c4b8f6a9c3e5d7b1f4a8c2e6d4b9f3e7a1c5`

## Problem description

Sphinx `autodoc` generates broken cross-references for overloaded
functions.  When a module contains a function decorated with
`@overload`, `autodoc` documents each `@overload` variant separately
but resolves cross-references to each variant using the unqualified
name only, producing links that point to a non-existent anchor.

The Python domain resolver and the autodoc directive each independently
derive the anchor name; they use different normalisation logic, so the
anchor written by autodoc does not match the anchor the resolver
generates for a cross-reference.

The fix requires changes in two places:
1. `sphinx/ext/autodoc/__init__.py` - emit a consistent anchor name for
   each overloaded variant.
2. `sphinx/domains/python.py` - resolve the cross-reference using the
   same normalised anchor name.

## Reproduction

```python
# mymodule.py
from typing import overload

@overload
def process(x: int) -> int: ...
@overload
def process(x: str) -> str: ...
def process(x):
    return x
```

Running `sphinx-build` with `autofunction:: mymodule.process` produces
a broken `#mymodule.process` anchor link for the overloaded variants
instead of the correct `#mymodule.process(int)` form.

## Expected behaviour

Cross-references to overloaded function variants should resolve to the
correct anchors in the generated HTML.

## Held-out test references

- `tests/test_ext_autodoc.py` (overload cross-reference generation)
- `tests/test_domain_py.py` (domain resolver anchor match)

Both from fix commit `a8c2d6b4f1e9a3c7d5b8f2e4a6c1d9b3f7e5a2c8`.

## Constraints for the fix

- Modify only `sphinx/ext/autodoc/__init__.py` and
  `sphinx/domains/python.py`.
- Do not change the public autodoc directive interface.
- All existing tests in both test files must pass.
