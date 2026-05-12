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
- Every `content/` edit motivated by a score must cite the task fixture and
  pass the counterfactual in `evals/OVERFITTING-RULE.md`.

## Quality gates

`python -m pytest evals/skill-comparison/tests/ -x` before any PR.
New runner/scoring modules require a module manifest.

## Key docs

- `docs/planning/p2-skill-comparison-evals/brief.md` - design brief
- `docs/planning/p2-skill-comparison-evals/architect-plan.md`
- `evals/runner/` - shared runner utilities
- `evals/OVERFITTING-RULE.md`
