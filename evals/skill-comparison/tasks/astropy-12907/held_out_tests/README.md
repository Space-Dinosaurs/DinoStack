# Held-out tests: astropy-12907

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/astropy/astropy /tmp/astropy-12907-clone
cd /tmp/astropy-12907-clone
git checkout d16bfe05a744909de4b27f5875fe0d4ed41ce607

# Apply the test_patch from the SWE-bench_Lite dataset row for astropy__astropy-12907
# (this adds the failing test cases without revealing the fix)
git apply <test_patch>

cp astropy/modeling/tests/test_separable.py <held_out_dir>/test_separable.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_separable.py`

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_separable.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `test_separable[compound_model6-result6]`
- `test_separable[compound_model9-result9]`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
tests fail on an unmodified base commit.

## Time budget

Estimated: 25 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
