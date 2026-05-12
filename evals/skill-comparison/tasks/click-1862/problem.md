# Task: click-1862

**SWE-bench instance ID:** `pallets__click-1862`
**Difficulty:** design-y
**Repository:** https://github.com/pallets/click
**Base commit:** `d7b3a9c5f2e1d8a4c6b8f3e5a9d2c7b1f4e6a8d3`

## Problem description

`click.Choice` has no built-in mechanism for case-insensitive matching.
Users who need case-insensitive choices must subclass `Choice` and
override `convert()`.  This is unnecessarily complex for such a common
use case.

The fix requires a small API extension:
1. `src/click/types.py` - add `case_sensitive: bool = True` parameter to
   `Choice.__init__` and update `Choice.convert` to normalise the input
   (and the choices list) to lowercase when `case_sensitive=False`.
2. `src/click/core.py` - update the choice completion / help-text path to
   honour the new parameter (display choices in the original casing; the
   comparison is case-insensitive).

This is a design-y task because the implementer must decide:
- Whether to normalise input to lowercase or uppercase.
- Whether `choices` displayed in help text should preserve original case
  or be lowercased.
- How `get_metavar()` should represent the choice set.

The canonical solution normalises to lowercase for comparison, preserves
original case in help text, and adds a `case_sensitive` attribute on the
`Choice` instance.

## Reproduction

```python
import click

@click.command()
@click.argument("colour", type=click.Choice(["RED", "GREEN", "BLUE"],
                                             case_sensitive=False))
def pick(colour):
    click.echo(colour)
```

Before the fix: `TypeError: __init__() got an unexpected keyword argument
'case_sensitive'`.

## Expected behaviour

`click.Choice(["RED", "GREEN", "BLUE"], case_sensitive=False)` should
accept `red`, `RED`, `Red`, etc. and return the value normalised to
lowercase.

## Held-out test reference

`tests/test_types.py` (from fix commit
`c9a1d7b5f4e2c8a6d3b9f1e5a7c2d8b4f6e3a9c1`).

The new tests:
1. Verify case-insensitive `Choice` accepts mixed-case input.
2. Verify default (`case_sensitive=True`) is unchanged.
3. Verify `get_metavar()` output.
4. Verify `convert()` returns the normalised-case value.

## Constraints for the fix

- Modify only `src/click/types.py` and `src/click/core.py`.
- The new `case_sensitive` parameter must default to `True` to preserve
  backward compatibility.
- All existing `test_types.py` tests must pass.
