# Held-out tests: django-11039

These test files are NOT committed to this repository. They are extracted
at runner start-up by applying the dataset's `test_patch` at `base_commit`.

## Extraction recipe

```bash
git clone https://github.com/django/django /tmp/django-11039-clone
cd /tmp/django-11039-clone
git checkout d5276398046ce4a102776a1e67dcac2884d80dfe

# Apply the test_patch from the SWE-bench_Lite dataset row for django__django-11039
# (this adds the failing test case without revealing the fix)
git apply <test_patch>

cp tests/migrations/test_commands.py <held_out_dir>/test_commands.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase. The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_commands.py`

## Pytest invocation (score phase)

```bash
pytest "/scoring/tests/test_commands.py::MigrateTests::test_sqlmigrate_for_non_transactional_databases" \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

## FAIL_TO_PASS tests (must transition fail -> pass)

- `test_sqlmigrate_for_non_transactional_databases (migrations.test_commands.MigrateTests)`

Expected: all tests pass on the correct patch; at least the FAIL_TO_PASS
test fails on an unmodified base commit.

## Time budget

Estimated: 30 s on a 2-vCPU host. Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
