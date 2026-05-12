# Task: django-11039

**SWE-bench instance ID:** `django__django-11039`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** single-file
**Repository:** https://github.com/django/django
**Base commit:** `d5276398046ce4a102776a1e67dcac2884d80dfe`

## Problem description

`sqlmigrate` wraps its output in `BEGIN`/`COMMIT` even when the target
database does not support transactional DDL (e.g. MySQL with DDL statements
that cause implicit commits).

This misleads users and tools that parse `sqlmigrate` output, because the
`BEGIN`/`COMMIT` wrapper implies atomicity that the database cannot provide.

The fix is in `django/core/management/commands/sqlmigrate.py` to check
whether the database connection supports transactional DDL before emitting
the `BEGIN`/`COMMIT` wrapper.

## Expected behaviour

When the database does not support transactional DDL, `sqlmigrate` output
should not include `BEGIN`/`COMMIT` wrapper statements.

## Held-out test references

- `tests/migrations/test_commands.py`

Test `test_sqlmigrate_for_non_transactional_databases` must transition from
fail to pass.
