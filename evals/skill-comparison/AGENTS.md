# evals/skill-comparison

Outcome-driven eval tree. Measures AE methodology and named-agent impact on
real software-engineering tasks (SWE-bench-lite). Primary metric: binary
pass/fail on held-out test suite.

## The 8 conditions

| Condition | Invocation shape |
|---|---|
| `baseline` | Bare Claude conductor; no AE payload; no per-agent target. |
| `ae-rules-injected` | Conductor with AE methodology text as system prompt via `ae_rules_payload.py`. NEVER label this `ae-skill`. |
| `engineer-direct` | Two-level Task spawn of `engineer` agent. |
| `architect-direct` | Two-level Task spawn of `architect` agent. |
| `investigator-direct` | Two-level Task spawn of `investigator` agent. |
| `debugger-direct` | Two-level Task spawn of `debugger` agent. |
| `skeptic-direct` | Two-level Task spawn of `skeptic` agent. |
| `qa-engineer-direct` | Two-level Task spawn of `qa-engineer` agent. |

## Conventions

- Condition names are exact - they are discovery keys for `config_discovery.py`
  and `aggregate.py`. Do not rename.
- Task corpus: `princeton-nlp/SWE-bench_Lite` only. Real SHAs; no fabrication.
- Corpus is frozen before any run; immutable once a baseline cell has run.
- Per-agent conditions use two-level Task spawn via
  `invoker.run_session(mode="agent", agent_name=<name>)`. Top-level
  `claude -p "follow <agent>"` does not preserve frontmatter.
- When testing, mock at `subprocess.run` or the real integration boundary,
  not at a wrapper function. Wrapper mocks hide kwarg mismatches.
- `--import-mode=append` is required on all Tier 3 pytest invocations when
  held-out tests live inside the repo tree; prevents `/scoring/tests` from
  shadowing `/workspace/repo`.
- Per-task `dockerfile` routing in `corpus.yaml` selects the sandbox image per
  task (e.g., `Dockerfile.swebench-py310` for Python 3.10 tasks).
- `post_seed_commands` in `corpus.yaml` apply patches before the fix phase runs
  (e.g., collections.abc migration, numpy alias fixes, version file writing for
  SCM version resolution).
- `use_pytest_timeout: false` in task metadata disables pytest-timeout for old
  pytest versions incompatible with `pytest-timeout==2.4.0`.
- Old pytest (pre-7.x) needs extra deps (`more_itertools`, `colorama`, `toml`,
  `attrs`) installed in the Docker image.
- Every `content/` edit motivated by a score must cite the task fixture and
  pass the counterfactual in `evals/OVERFITTING-RULE.md`.

## Gotchas

- Docker layer cache masks Dockerfile changes; `docker rmi -f` +
  `force_rebuild=True` is required after any `Dockerfile.swebench` edit.
- pytest path shadowing: default import mode puts `/scoring/tests` ahead of
  `/workspace/repo`. `--import-mode=append` is the fix.
- Network-isolated containers may fail SCM version resolution; write version
  files directly in `post_seed_commands`.
- Python 3.10 removed `collections.MutableMapping`; old repos need
  `collections.abc` patches in `post_seed_commands`.

## Quality gates

`python -m pytest evals/skill-comparison/tests/ -x` before any PR.
New runner/scoring modules require a module manifest.

## Key docs

- `docs/planning/p2-skill-comparison-evals/brief.md` - design brief
- `docs/planning/p2-skill-comparison-evals/architect-plan.md`
- `evals/runner/` - shared runner utilities
- `evals/OVERFITTING-RULE.md`
