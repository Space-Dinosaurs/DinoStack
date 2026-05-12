# Task: django-11019

**SWE-bench instance ID:** `django__django-11019`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** design-y
**Repository:** https://github.com/django/django
**Base commit:** `93e892bb645b16ebaf287beb5fe7f3ffe8d10408`

## Problem description

Merging 3 or more `Media` objects throws unnecessary
`MediaOrderConflictWarning` messages. The current merge algorithm uses a
simple list-based approach that does not handle transitive dependency
ordering, producing spurious warnings when the ordering is actually
resolvable.

```python
from django import forms

class ColorPicker(forms.Widget):
    class Media:
        js = ["color-picker.js"]

class SimpleTextWidget(forms.Widget):
    class Media:
        js = ["text-editor.js"]

class FancyTextWidget(forms.Widget):
    class Media:
        js = ["text-editor.js", "text-editor-extras.js", "color-picker.js"]

class MyForm(forms.Form):
    background_color = forms.CharField(widget=ColorPicker)
    intro = forms.CharField(widget=SimpleTextWidget)
    body = forms.CharField(widget=FancyTextWidget)

# Results in unnecessary MediaOrderConflictWarning
print(MyForm().media)
```

The fix requires redesigning the merge strategy in `django/forms/widgets.py`
to correctly handle transitive ordering constraints when merging 3+ media
objects.

## Expected behaviour

When a consistent ordering exists across all media dependencies, no
`MediaOrderConflictWarning` should be raised. Warnings should only appear
when a genuine circular dependency makes consistent ordering impossible.

## Held-out test references

- `tests/admin_inlines/tests.py`
- `tests/admin_widgets/test_autocomplete_widget.py`
- `tests/forms_tests/tests/test_media.py`

16 tests in `test_media.py::FormsMediaTestCase` must transition from fail
to pass.

## Constraints for the fix

- Modify `django/forms/widgets.py` only (or minimally add helpers).
- Do not change the `Media` public API or the `MediaOrderConflictWarning`
  exception type.
- All existing admin tests for media ordering must also pass.
