# Held-out tests: requests-3362

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/psf/requests /tmp/requests-3362-clone
cd /tmp/requests-3362-clone
git checkout 36453b95b13079296776d11b09cab2567ea3e703

# Apply the test_patch from the SWE-bench_Lite dataset row for psf__requests-3362
# (this adds the failing test case without revealing the fix)
git apply <test_patch>

cp tests/test_requests.py <held_out_dir>/test_requests.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_requests.py`

## Pytest invocation (score phase)

```bash
pytest "/scoring/tests/test_requests.py::TestRequests::test_response_decode_unicode" \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `tests/test_requests.py::TestRequests::test_response_decode_unicode`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
test fails on an unmodified base commit.

## Time budget

Estimated: 15 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
