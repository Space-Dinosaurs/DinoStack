# Task: pylint-4421

**SWE-bench instance ID:** `pylint-dev__pylint-4421`
**Difficulty:** single-file
**Repository:** https://github.com/PyCQA/pylint
**Base commit:** `7bde060b61c13f0a51c6f85fb9b5f9ef6a23b52a`

## Problem description

`pylint --rcfile="path with spaces/pylintrc"` silently ignores the given
config file.  The `--rcfile` argument is processed by splitting on
whitespace before the file path is passed to the configuration parser,
so a path that contains spaces is treated as two separate (non-existent)
paths and the option falls back to the default config.

## Reproduction

```bash
mkdir -p "/tmp/my project"
echo "[MESSAGES CONTROL]" > "/tmp/my project/pylintrc"
echo "disable=all" >> "/tmp/my project/pylintrc"
pylint --rcfile="/tmp/my project/pylintrc" mymodule.py
# All warnings still emitted - config file was silently ignored
```

## Expected behaviour

`--rcfile` should accept any valid file path, including paths with spaces,
and apply the config directives from that file.

## Held-out test reference

`tests/test_lint.py` (from fix commit
`c81eb1b28e5dc3d65a9e1b23f2b7f9ba07f3f28a`).

The new test:
1. Writes a minimal `pylintrc` to a tempdir whose path contains a space.
2. Invokes pylint programmatically with `--rcfile=<spaced path>`.
3. Asserts the config was applied (e.g. a specific message is suppressed).

## Constraints for the fix

- Modify only `pylint/lint/run.py`.
- Do not change the public CLI interface.
- All existing `test_lint.py` tests must pass.
