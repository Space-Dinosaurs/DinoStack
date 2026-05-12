# Task: sphinx-7686

**SWE-bench instance ID:** `sphinx-doc__sphinx-7686`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** multi-file
**Repository:** https://github.com/sphinx-doc/sphinx
**Base commit:** `752d3285d250bbaf673cff25e83f03f247502021`

## Problem description

The `autosummary` extension includes imported members in the `members`
template variable even when `autosummary_imported_members = False`, polluting
generated API docs with symbols from re-exported modules.

For example, a module that does `from os.path import join` would include
`join` in its `members` list even when the user explicitly disabled imported
member inclusion, causing spurious entries in the generated summary tables.

The fix is in `sphinx/ext/autosummary/generate.py` in the logic that
populates the module's member list for the template context.

## Expected behaviour

When `autosummary_imported_members` is `False` (the default), symbols that
are imported from other modules should not appear in the `members` list
used by autosummary templates.

## Held-out test references

- `tests/roots/test-ext-autosummary/autosummary_dummy_module.py`
- `tests/test_ext_autosummary.py`

Tests `test_autosummary_generate_content_for_module` and
`test_autosummary_generate_content_for_module_skipped` must transition from
fail to pass.
