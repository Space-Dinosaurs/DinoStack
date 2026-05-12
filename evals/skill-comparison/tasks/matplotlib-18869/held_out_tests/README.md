# Held-out tests: matplotlib-18869

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/matplotlib/matplotlib /tmp/matplotlib-18869-clone
cd /tmp/matplotlib-18869-clone
git checkout b7d05919865fc0c37a0164cf467d5d5513bd0ede

# Apply the test_patch from the SWE-bench_Lite dataset row for matplotlib__matplotlib-18869
# (this adds the failing test cases without revealing the fix)
git apply <test_patch>

cp lib/matplotlib/tests/test_matplotlib.py <held_out_dir>/test_matplotlib.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_matplotlib.py`

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_matplotlib.py -k "test_parse_to_version_info" \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `test_parse_to_version_info[3.5.0-version_tuple0]`
- `test_parse_to_version_info[3.5.0rc2-version_tuple1]`
- `test_parse_to_version_info[3.5.0.dev820+g6768ef8c4c-version_tuple2]`
- `test_parse_to_version_info[1.2.3-version_tuple3]`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
tests fail on an unmodified base commit.

## Time budget

Estimated: 40 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
