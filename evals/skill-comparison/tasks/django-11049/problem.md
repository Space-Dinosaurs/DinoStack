# Task: django-11049

**SWE-bench instance ID:** `django__django-11049`
**Difficulty:** single-file
**Repository:** https://github.com/django/django
**Base commit:** `a2b64e2cfe72839aac0a7765283bd5f3bb42b955`

## Problem description

`AuthenticationForm` clears the `username` field value on a failed login
even when `show_hidden_initial=True` is set on the field.

Django forms store the "previous value" in a hidden `<input>` whose name
is `initial-<field_name>`.  When `AuthenticationForm` invalidates on bad
credentials, its `__init__` resets the username value to `""`, causing
the re-rendered form to emit an empty `initial-username` hidden field.
Downstream JavaScript that reads this field for CSRF double-submit
protection therefore receives an empty string and breaks the flow.

## Reproduction

```python
from django.contrib.auth.forms import AuthenticationForm

data = {"username": "alice", "password": "wrong"}
form = AuthenticationForm(data=data)
form.is_valid()   # False - bad credentials
# form.fields["username"].initial should still be "alice"
# but it is "" after the failed validation
assert form.fields["username"].initial == "alice"   # AssertionError
```

## Expected behaviour

The `username` field should retain its submitted value as the initial value
after a failed login attempt so that the hidden initial widget renders
correctly.

## Held-out test reference

`tests/auth_tests/test_forms.py` (from fix commit
`de8e4a70a3e66ed93b72e73f1e67ddb0f7e152c0`).

The test class `AuthenticationFormTest` gains a new test method that:
1. Submits bad credentials.
2. Asserts `form.fields["username"].initial == submitted_username`.
3. Asserts the rendered HTML contains the correct hidden initial input.

## Constraints for the fix

- Modify only `django/contrib/auth/forms.py`.
- Do not change `AuthenticationForm`'s public constructor signature.
- All existing `test_forms.py` tests must still pass.
