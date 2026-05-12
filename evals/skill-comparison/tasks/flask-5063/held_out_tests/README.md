# Held-out tests: flask-5063

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/pallets/flask /tmp/flask-5063-clone
cd /tmp/flask-5063-clone
git checkout 182ce3dd15dfa3537391c3efaf9c3ff407d134d4

# Apply the test_patch from the SWE-bench_Lite dataset row for pallets__flask-5063
# (this adds the failing test cases without revealing the fix)
git apply <test_patch>

cp tests/test_cli.py <held_out_dir>/test_cli.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_cli.py`

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_cli.py::TestRoutes::test_subdomain \
       /scoring/tests/test_cli.py::TestRoutes::test_host \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `tests/test_cli.py::TestRoutes::test_subdomain`
- `tests/test_cli.py::TestRoutes::test_host`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
tests fail on an unmodified base commit.

## Time budget

Estimated: 25 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
