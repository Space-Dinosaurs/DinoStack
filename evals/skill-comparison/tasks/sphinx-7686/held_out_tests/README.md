# Held-out tests: sphinx-7686

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/sphinx-doc/sphinx /tmp/sphinx-7686-clone
cd /tmp/sphinx-7686-clone
git checkout 752d3285d250bbaf673cff25e83f03f247502021

# Apply the test_patch from the SWE-bench_Lite dataset row for sphinx-doc__sphinx-7686
# (this adds the failing test cases without revealing the fix)
git apply <test_patch>

cp tests/roots/test-ext-autosummary/autosummary_dummy_module.py \
   <held_out_dir>/autosummary_dummy_module.py
cp tests/test_ext_autosummary.py <held_out_dir>/test_ext_autosummary.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `autosummary_dummy_module.py`
- `test_ext_autosummary.py`

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_ext_autosummary.py::test_autosummary_generate_content_for_module \
       /scoring/tests/test_ext_autosummary.py::test_autosummary_generate_content_for_module_skipped \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `tests/test_ext_autosummary.py::test_autosummary_generate_content_for_module`
- `tests/test_ext_autosummary.py::test_autosummary_generate_content_for_module_skipped`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
tests fail on an unmodified base commit.

## Time budget

Estimated: 60 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
