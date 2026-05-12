# Held-out tests: sklearn-10297

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/scikit-learn/scikit-learn /tmp/sklearn-10297-clone
cd /tmp/sklearn-10297-clone
git checkout b90661d6a46aa3619d3eec94d5281f5888add501

# Apply the test_patch from the SWE-bench_Lite dataset row for scikit-learn__scikit-learn-10297
# (this adds the failing test case without revealing the fix)
git apply <test_patch>

cp sklearn/linear_model/tests/test_ridge.py <held_out_dir>/test_ridge.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_ridge.py`

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_ridge.py::test_ridge_classifier_cv_store_cv_values \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `sklearn/linear_model/tests/test_ridge.py::test_ridge_classifier_cv_store_cv_values`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
test fails on an unmodified base commit.

## Time budget

Estimated: 55 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
