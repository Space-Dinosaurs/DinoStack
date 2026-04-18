# evals - component eval harness (Phase 1)

This is the Phase 1 deliverable of the P2 self-improving-harness plan
(`docs/planning/p2-self-improving-harness.md`). It runs named-agent components
against labeled fixtures in isolation, aggregates scores across N runs, and
appends to a per-component TSV ledger.

Phase 1 ships one component end-to-end: **Skeptic** (Tier 1 isolation,
skeptic-lite scoring, 5 seeded fixtures).

## Prerequisites

- **Python 3.11+**
- **`claude` CLI on PATH**, authenticated and working. The runner probes
  `claude --version` at startup and fails with a clear error if absent. This is
  a hard prerequisite; there is no fallback. Install Claude Code from
  https://docs.claude.com/claude-code.
- **`git`** on PATH (used by the Tier 1 worktree isolator).
- `pip install -r evals/requirements.txt` (only `pyyaml>=6.0`).

The runner shells out to the CLI so the eval code path matches how a human
spawns the agent; it does **not** use the Anthropic SDK directly.

## Commands

From the repo root:

```
python -m evals.runner.cli list-components
python -m evals.runner.cli run skeptic                       # full N=3 over all fixtures
python -m evals.runner.cli run skeptic --fixture sk-001      # one fixture
python -m evals.runner.cli run skeptic --fixture sk-001 --n 1   # smoke
python -m evals.runner.cli show-results skeptic
```

Results land in:
- `evals/results/<component>.tsv` - committed, append-only ledger.
- `evals/results/<component>.runlog.jsonl` - gitignored per-run detail.
- `evals/.worktrees/` - gitignored Tier 1 worktrees; cleaned up after each run.

## TSV schema

```
commit  component_content_hash  fixture_hash  primary_score_median  primary_score_stdev  n_runs  status  diagnostic_json  description
```

- `component_content_hash` is the sha256 of the concatenated (sorted) file bytes
  of the component's `content_glob`.
- `fixture_hash` is the sha256 of the fixture YAML file.
- N=3 runs by default, serial. Median is the primary scalar; stdev is the
  diagnostic. The cache key pattern `(commit, content_hash, fixture_hash, N)`
  is implicit in the row columns.

## Overfitting Rule

Any human edit to `content/` motivated wholly or partly by a TSV score must
satisfy the rule in [`OVERFITTING-RULE.md`](./OVERFITTING-RULE.md). Read it
before reacting to a score.

## Isolation tiers

| Tier | Use | Phase 1 status |
|---|---|---|
| 1 | Read-only prompt components (Skeptic, conductor, Architect) | Implemented (git worktree) |
| 2 | Commands that write (/init-project, /wrap) | Stubbed - raises NotImplementedError |
| 3 | Code-executing components (Worker, Debugger) | Stubbed - raises NotImplementedError |

## How to add a new component eval

10-line recipe:

1. Create `evals/components/<name>.yaml` with the manifest fields (see
   `evals/components/skeptic.yaml` as the template).
2. Create `evals/fixtures/<name>/<fixture-id>/` with `fixture.yaml`, and any
   companion files the fixture references in `inputs` (e.g. `diff.patch`,
   `worker_output.md`).
3. Each fixture records the `protocol_sha` of the file in `content_glob` at
   labeling time.
4. Create `evals/scoring/<name>_lite.py` exposing
   `score(trace: dict, fixture: dict) -> {"primary": float, "diagnostic": dict, "status": str}`.
   Declare asymmetric costs explicitly (or justify symmetric).
5. If the component writes to disk or executes code, declare `tier: 2` or
   `tier: 3` in the manifest; Phase 1 only runs Tier 1. Tier 2/3 raise
   `NotImplementedError` until their isolators land.
6. Reference `evals/OVERFITTING-RULE.md` from the component's section in this
   README (or a per-component README if the component grows one).
7. Run `python -m evals.runner.cli run <name> --fixture <one> --n 1` as a
   smoke test.
8. Run the full eval: `python -m evals.runner.cli run <name>`.
9. Inspect `evals/results/<name>.tsv`; commit it.
10. Add the component to the phase-sequencing table in the planning doc if it
    is new.
