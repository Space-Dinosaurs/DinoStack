# evals/runner

Runtime components for the AE eval harness (Tier 1, 2, 3).

## Dockerfile.swebench (Tier 3 image)

**Base image: `python:3.9-slim` (v1.3.0)**

Python 3.9 is required for compatibility with legacy SWE-bench-lite tasks. Many
corpus tasks predate Python 3.10 and use patterns that were removed in 3.10 -
most notably `collections.MutableMapping` (moved to `collections.abc` in 3.3,
fully removed in 3.10). Smoke v10 confirmed the failure in requests-3362.

### Per-task version routing (future)

Some newer corpus tasks may require Python 3.11+:

- `astropy-12907`
- `sphinx-7686`
- `sklearn-10297`

If/when those tasks fail due to syntax or stdlib incompatibilities not present
in 3.9, add per-task image routing in `isolator.py` rather than bumping the
default base. Python 3.9 unblocks 7+ of the 12 smoke corpus tasks and is the
correct default for the current corpus mix.

### Build

```bash
docker build -f evals/runner/Dockerfile.swebench -t ae-eval-swebench:latest .
```

### Security model

- All dependencies installed at BUILD time (network available).
- No `pip install` at RUN time - container runs with `--network none` and
  `--read-only` rootfs.
- Score-phase pytest is invoked with `--noconftest --rootdir=/scoring/tests
  --confcutdir=/scoring` to prevent agent-planted conftest.py from executing.

See `Dockerfile.swebench` header for the full security model.
