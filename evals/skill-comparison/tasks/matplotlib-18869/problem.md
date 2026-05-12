# Task: matplotlib-18869

**SWE-bench instance ID:** `matplotlib__matplotlib-18869`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** multi-file
**Repository:** https://github.com/matplotlib/matplotlib
**Base commit:** `b7d05919865fc0c37a0164cf467d5d5513bd0ede`

## Problem description

matplotlib lacks an easily comparable version info tuple at the top level.
Users who need to check "is this matplotlib >= 3.5.0" must parse the version
string manually, which is error-prone.

The request is to expose a `__version_info__` tuple (similar to Python's
`sys.version_info`) at `matplotlib.__version_info__` that can be compared
programmatically.

The fix requires adding a `_parse_to_version_info` helper and the
`__version_info__` attribute to `lib/matplotlib/__init__.py`.

## Expected behaviour

```python
import matplotlib
assert matplotlib.__version_info__ >= (3, 5, 0)
# Works for release candidates too:
# matplotlib.__version_info__ for "3.5.0rc2" == (3, 5, 0, 'rc', 2)
```

## Held-out test references

- `lib/matplotlib/tests/test_matplotlib.py`

Four `test_parse_to_version_info` parametrize cases must transition from
fail to pass.
