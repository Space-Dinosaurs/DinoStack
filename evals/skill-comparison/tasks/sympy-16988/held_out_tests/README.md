# Held-out tests: sympy-16988

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/sympy/sympy /tmp/sympy-16988-clone
cd /tmp/sympy-16988-clone
git checkout e727339af6dc22321b00f52d971cda39e4ce89fb

# Apply the test_patch from the SWE-bench_Lite dataset row for sympy__sympy-16988
# (this adds the failing test cases without revealing the fix)
git apply <test_patch>

cp sympy/sets/tests/test_sets.py <held_out_dir>/test_sets.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_sets.py`

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_sets.py::test_imageset \
       /scoring/tests/test_sets.py::test_intersection \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `test_imageset`
- `test_intersection`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
tests fail on an unmodified base commit.

## Time budget

Estimated: 35 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
