# Task: pylint-7080

**SWE-bench instance ID:** `pylint-dev__pylint-7080`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** single-file
**Repository:** https://github.com/pylint-dev/pylint
**Base commit:** `3c5eca2ded3dd2b59ebaf23eb289453b5d2930f0`

## Problem description

When running pylint with `--recursive=y`, the `ignore-paths` configuration
option is silently ignored, causing pylint to lint files that should be
excluded.

```ini
# pyproject.toml
[tool.pylint.MASTER]
ignore-paths = ["^src/gen/.*$"]
```

Running `pylint --recursive=y src/` still lints files under `src/gen/`
even though the pattern matches them.

The bug is in `pylint/lint/expand_modules.py` in the recursive path
expansion logic, which does not consult `ignore-paths` when collecting
files during recursive directory traversal.

## Expected behaviour

Files whose paths match any `ignore-paths` pattern should not be linted,
regardless of whether `--recursive=y` is used.

## Held-out test references

- `tests/test_self.py`

Test `test_ignore_path_recursive_current_dir` must transition from fail to pass.
