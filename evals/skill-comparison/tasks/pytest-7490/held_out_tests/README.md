# Held-out tests: pytest-7490

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/pytest-dev/pytest /tmp/pytest-7490-clone
cd /tmp/pytest-7490-clone
git checkout 7f7a36478abe7dd1fa993b115d22606aa0e35e88

# Apply the test_patch from the SWE-bench_Lite dataset row for pytest-dev__pytest-7490
# (this adds the failing test cases without revealing the fix)
git apply <test_patch>

cp testing/test_skipping.py <held_out_dir>/test_skipping.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_skipping.py`

## Pytest invocation (score phase)

```bash
pytest "/scoring/tests/test_skipping.py::TestXFail::test_dynamic_xfail_set_during_runtest_failed" \
       "/scoring/tests/test_skipping.py::TestXFail::test_dynamic_xfail_set_during_runtest_passed_strict" \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `testing/test_skipping.py::TestXFail::test_dynamic_xfail_set_during_runtest_failed`
- `testing/test_skipping.py::TestXFail::test_dynamic_xfail_set_during_runtest_passed_strict`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
tests fail on an unmodified base commit.

## Time budget

Estimated: 40 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
