# Held-out tests: django-11019

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/django/django /tmp/django-11019-clone
cd /tmp/django-11019-clone
git checkout 93e892bb645b16ebaf287beb5fe7f3ffe8d10408

# Apply the test_patch from the SWE-bench_Lite dataset row for django__django-11019
# (this adds the failing test cases without revealing the fix)
git apply <test_patch>

cp tests/admin_inlines/tests.py <held_out_dir>/test_admin_inlines.py
cp tests/admin_widgets/test_autocomplete_widget.py <held_out_dir>/test_autocomplete_widget.py
cp tests/forms_tests/tests/test_media.py <held_out_dir>/test_media.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_admin_inlines.py`
- `test_autocomplete_widget.py`
- `test_media.py`

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_media.py \
       /scoring/tests/test_admin_inlines.py \
       /scoring/tests/test_autocomplete_widget.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

All 16 `FormsMediaTestCase` tests in `test_media.py`:
- `test_combine_media`
- `test_construction`
- `test_form_media`
- `test_media_inheritance`
- `test_media_inheritance_from_mixin`
- `test_media_inheritance_single_type`
- `test_multi_media`
- `test_merge_css_three_way`
- `test_merge_js_three_way`
- `test_merge_warning`
- `test_merge`
- `test_media_deduplication`
- `test_media_ordering`
- `test_add_js_to_media`
- `test_add_css_to_media`
- `test_empty_media`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
tests fail on an unmodified base commit.

## Time budget

Estimated: 90 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
