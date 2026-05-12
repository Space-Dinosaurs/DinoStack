# Held-out tests: astropy-7606

These test files are NOT committed to this repository.  They are
extracted at runner start-up from the fix commit of the upstream repo.

## Extraction recipe

```bash
git clone https://github.com/astropy/astropy /tmp/astropy-7606-clone
cd /tmp/astropy-7606-clone
git checkout 9ab04dcd5d7c57d0d7b6fe75de91bb8a87d0a18f
cp astropy/tests/test_nddata.py <held_out_dir>/test_nddata.py
```

The runner (`evals/skill-comparison/runner.py`) performs this extraction
automatically before launching the score phase.  The held-out dir is
mounted read-only at `/scoring/tests` inside the Tier 3 container; it is
NOT mounted during the fix phase.

## Files expected after extraction

- `test_nddata.py`

## Pytest invocation (score phase)

```bash
pytest /scoring/tests/test_nddata.py \
  --noconftest --rootdir=/scoring/tests --confcutdir=/scoring \
  -x -q
```

Expected: all tests pass on the correct patch, >=1 test fails on an
unmodified (unfixed) base commit.

## Time budget

Estimated: 25 s on a 2-vCPU host.  Hard limit: 120 s (enforced by Tier 3
`--stop-timeout`).
