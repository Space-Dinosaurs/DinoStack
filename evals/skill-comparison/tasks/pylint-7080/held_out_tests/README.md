# Held-out tests: pylint-7080

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/pylint-dev/pylint /tmp/pylint-7080-clone
cd /tmp/pylint-7080-clone
git checkout 3c5eca2ded3dd2b59ebaf23eb289453b5d2930f0

# Apply the test_patch from the SWE-bench_Lite dataset row for pylint-dev__pylint-7080
# (this adds the failing test case without revealing the fix)
git apply <test_patch>

cp tests/test_self.py <held_out_dir>/test_self.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_self.py`

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_self.py::TestRunTC::test_ignore_path_recursive_current_dir \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `tests/test_self.py::TestRunTC::test_ignore_path_recursive_current_dir`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
test fails on an unmodified base commit.

## Time budget

Estimated: 20 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
