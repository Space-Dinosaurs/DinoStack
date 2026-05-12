# Held-out tests: django-11049

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/django/django /tmp/django-11049-clone
cd /tmp/django-11049-clone
git checkout 17455e924e243e7a55e8a38f45966d8cbb27c273

# Apply the test_patch from the SWE-bench_Lite dataset row for django__django-11049
# (this adds the failing test case without revealing the fix)
git apply <test_patch>

cp tests/model_fields/test_durationfield.py <held_out_dir>/test_durationfield.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_durationfield.py`

## Pytest invocation (score phase)

```bash
pytest "/scoring/tests/test_durationfield.py::TestValidation::test_invalid_string" \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `test_invalid_string (model_fields.test_durationfield.TestValidation)`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
test fails on an unmodified base commit.

## Time budget

Estimated: 20 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
