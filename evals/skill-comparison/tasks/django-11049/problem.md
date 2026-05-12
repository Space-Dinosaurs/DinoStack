# Task: django-11049

**SWE-bench instance ID:** `django__django-11049`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** single-file
**Repository:** https://github.com/django/django
**Base commit:** `17455e924e243e7a55e8a38f45966d8cbb27c273`

## Problem description

The error message for an invalid `DurationField` input shows the wrong
expected format example. When a user enters `"14:00"` (which Django
interprets as 14 minutes, producing `00:14:00`), the error message says
the expected format is `[DD] [HH:[MM:]]ss[.uuuuuu]`, but the actual
expected format example in the message is incorrect.

The fix is in `django/db/models/fields/__init__.py` to update the error
message format string to show the correct expected format.

## Expected behaviour

The DurationField validation error message should display the correct
expected format so users understand what input is accepted.

## Held-out test references

- `tests/model_fields/test_durationfield.py`

Test `test_invalid_string` must transition from fail to pass.
