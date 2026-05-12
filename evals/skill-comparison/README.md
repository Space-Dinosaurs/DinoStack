# evals/skill-comparison

Outcome-driven evaluation of the AE methodology and named-agent suite vs a raw
Claude Code baseline on SWE-bench-lite tasks. Unlike `evals/components/`
(which measures per-agent prompt correctness on synthetic fixtures), this tree
asks: **"does using this agent yield a better solution to a real bug than not
using it?"**

## Purpose

We have no measured evidence for two implicit AE claims:

1. The methodology, applied end-to-end, produces better engineering outcomes
   than a vanilla Claude session.
2. Each of the 6 core named agents contributes positively when used in
   isolation on a real software-engineering task.

This eval provides that evidence via an 8-condition matrix run against a
frozen, representative SWE-bench-lite corpus.

## Conditions

| Condition | What it measures |
|---|---|
| `baseline` | Vanilla Claude conductor, no AE rules payload, no per-agent target. |
| `ae-rules-injected` | AE methodology content injected inline into the conductor's system prompt. Methodology-level pair with `baseline`. |
| `engineer-direct` | Bare two-level Task spawn of the `engineer` named agent. |
| `architect-direct` | Bare two-level Task spawn of the `architect` named agent. |
| `investigator-direct` | Bare two-level Task spawn of the `investigator` named agent. |
| `debugger-direct` | Bare two-level Task spawn of the `debugger` named agent. |
| `skeptic-direct` | Bare two-level Task spawn of the `skeptic` named agent. |
| `qa-engineer-direct` | Bare two-level Task spawn of the `qa-engineer` named agent. |

Naming is intentional: `ae-rules-injected` because we inject AE rules text
into the system prompt; we do NOT replicate the full production
`/agentic-engineering` activation pipeline. See "Baseline confound and
measurement fairness" below.

## Production-layer disclosure

The `ae-rules-injected` condition is NOT bit-identical to production
`/agentic-engineering` activation. Explicit per-layer disclosure:

| Layer | Exercised? |
|---|---|
| Rules-text injection into the outer conductor's system prompt (concatenated SKILL.md + sections + rules + references + commands) | YES |
| Named-agent invocation via two-level Task spawn, frontmatter intact (per the canary) | YES |
| Activation preflight (`~/.claude/agentic-engineering.json` mode/profile/preset resolution; AGENTS.md marker scan) | NO |
| MEMORY.md auto-injection at session start | NO |
| First-activation sentinel file (`.agentic/.activated`) and one-time notice | NO |
| Stop hook writes to `.agentic/context.md` between turns | NO |
| Per-command preflight re-checks at top of each slash-command body | NO |
| `.agentic/` runtime state files (events.jsonl, tasks.jsonl, loop-state.json) and any behavior conditioned on their presence | NO |

The score delta between `baseline` and `ae-rules-injected` captures the effect
of the rules payload only; it does not capture preflight, memory injection, or
Stop hook behavior. The cost difference is part of what is measured, not a
confounder - `ae_rules_payload.py` builds a ~143k-token system prompt (~571 KB
raw), which is reported alongside the score.

## Baseline confound and measurement fairness

**The `baseline` condition is not methodology-free.** Any Claude Code session
inherits the global `~/.claude/CLAUDE.md` if one is present on the runner
machine. If that file imports methodology rules, the baseline is already
rules-injected to some degree.

What the eval captures is the **envelope** of delta attributable to the
`ae-rules-injected` payload specifically, over whatever baseline behavior the
runner environment produces. For the eval to be comparable across machines and
time, the runner must document the state of `~/.claude/CLAUDE.md` (or its
absence) in the run header, and baseline-vs-baseline replicates (n=5 on the
methodology pair) establish the noise floor the delta must exceed.

The sensitivity check (see "Running the eval") verifies that the
baseline-vs-ae-rules-injected delta exceeds the baseline noise envelope on
>=60% of in-scope tasks before the eval is considered discriminating.

The per-agent conditions (`<agent>-direct`) do not inject a system prompt;
they spawn the named agent directly via two-level Task. The comparison for
those conditions is `<agent>-direct` vs `baseline` where neither injects any
additional system prompt, so the confound does not apply.

## Repository layout

```
evals/skill-comparison/
  README.md                       # this file
  AGENTS.md                       # per-track agent notes
  runner.py                       # 8-condition matrix driver
  config_discovery.py             # dynamic discovery of condition dirs
  aggregate.py                    # n-condition rollup with deltas-vs-baseline
  scoring.py                      # pass/fail + diff-hygiene diagnostics
  ae_rules_payload.py             # builds AE-rules-injected system-prompt blob
  canary/                         # canary transcripts + assertion script
  specs/
    methodology.yaml              # baseline vs ae-rules-injected
    engineer.yaml
    architect.yaml
    investigator.yaml
    debugger.yaml
    skeptic.yaml
    qa-engineer.yaml
  tasks/
    corpus.yaml                   # task selection list + per-task metadata
    <task_slug>/                  # seeded repo state, held-out tests, problem
  results/
    skill-comparison.tsv          # ledger; append-only
```

## How to run

### Prerequisites

- Docker daemon running (required for Tier 3 isolator; `docker info` must succeed).
- `evals/runner/` dependencies installed (`pip install -r evals/runner/requirements.txt`).
- Task corpus committed to git (`tasks/corpus.yaml` and task subdirectories present).
- Run from repo root or `evals/skill-comparison/` directory.

### Dry-run (smoke test, no real Claude calls)

```bash
python evals/skill-comparison/runner.py --dry-run
```

Validates corpus YAML, condition specs, and isolator connectivity without
spending tokens.

### Sensitivity check (methodology pair only, n=5)

```bash
python evals/skill-comparison/runner.py \
  --conditions baseline ae-rules-injected \
  --n 5 \
  --sensitivity-check
```

Runs baseline twice (n=5 each) to establish the noise envelope, then runs
`ae-rules-injected` n=5. Exits with a summary of whether the delta exceeds
the envelope on >=60% of tasks. **Run this before the full corpus.**

### Full corpus run

```bash
python evals/skill-comparison/runner.py \
  --conditions all \
  --n 3 \
  --methodology-n 5
```

Runs all 8 conditions across the full task corpus. The methodology pair
(`baseline` vs `ae-rules-injected`) uses n=5; all other conditions use n=3.
Budget ceiling: $250 / 75 M tokens. The runner halts and emits a partial
report on breach (exit code 3).

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--conditions` | `all` | Comma- or space-separated list of conditions to run, or `all`. |
| `--n` | `3` | Minimum replicate count per cell (except methodology pair). |
| `--methodology-n` | `5` | Replicate count for `baseline` and `ae-rules-injected`. |
| `--tier3` | enabled | Use Tier 3 Docker isolator. Pass `--no-tier3` to fall back to Tier 2 (code-review-only tasks only). |
| `--force` | off | Re-run cells even if results already exist in the TSV. |
| `--dry-run` | off | Validate config and connectivity; skip Claude calls. |
| `--sensitivity-check` | off | Run baseline-noise-envelope measurement before the main run. |
| `--tasks` | `corpus.yaml` | Path to task corpus YAML (default: `tasks/corpus.yaml`). |
| `--output` | `results/skill-comparison.tsv` | Path to output TSV. |

### Aggregating results

```bash
python evals/skill-comparison/aggregate.py results/skill-comparison.tsv
```

Produces a summary table with median and stdev per condition, delta-vs-baseline
per condition, and the baseline noise envelope column.

## TSV schema (`results/skill-comparison.tsv`)

| Column | Type | Description |
|---|---|---|
| `run_id` | string | UUID per run. |
| `task_slug` | string | Task identifier from `corpus.yaml` (e.g. `django__django-12345`). |
| `condition` | string | One of the 8 condition names. |
| `replicate` | int | 1-indexed replicate number within the (task, condition) cell. |
| `status` | string | `pass`, `fail`, `error`, `timeout`, `budget_exceeded`. |
| `score_primary` | float | 1.0 if all held-out tests pass, else 0.0. |
| `held_out_failures` | string | Comma-separated list of failing test IDs (empty on pass). |
| `lines_touched` | int | Lines changed in the diff. |
| `files_touched` | int | Files changed in the diff. |
| `scope_creep_flag` | bool | True if files touched fall outside the task's known surface. |
| `time_to_solution_sec` | float | Wall-clock seconds from start to scoring. |
| `tool_calls` | int | Total tool calls in the session. |
| `subagent_spawns` | int | Number of sub-agent Task spawns. |
| `tokens_input` | int | Input tokens consumed. |
| `tokens_output` | int | Output tokens consumed. |
| `cost_usd` | float | Estimated cost in USD (best-effort; may be 0 if not reported). |
| `run_ts` | string | ISO8601 UTC timestamp of the run start. |
| `runner_sha` | string | Git SHA of the repo at run time. |
| `condition_spec_hash` | string | SHA256 of the condition's YAML spec (for invalidation). |

## Corpus

Source: `princeton-nlp/SWE-bench_Lite` (MIT-licensed subset).

Selection criteria (documented in `tasks/corpus.yaml` header):
- Difficulty mix: 60% single-file-with-failing-test / 30% multi-file / 10% design-y.
- License-permissive; no GPU; no network required at fix time.
- Fits in 1 GB container RAM.
- Held-out pytest runs in <120 s.
- 10-15 tasks for v1.

**The corpus is frozen and committed to git before any run.** No post-hoc
additions or substitutions once a baseline cell has run against the list.
Corpus changes after first run require a new eval generation (new TSV path).

## Pointers

| Component | Location |
|---|---|
| Shared runner utilities | `evals/runner/` |
| Aggregator base pattern | `evals/icl_vs_orchestration/` |
| Per-agent condition specs | `evals/skill-comparison/specs/` |
| Canary assertion script | `evals/skill-comparison/canary/` |
| AE-rules payload builder | `evals/skill-comparison/ae_rules_payload.py` |
| Scoring logic | `evals/skill-comparison/scoring.py` |
| Design brief | `docs/planning/p2-skill-comparison-evals/brief.md` |
| Architect plan | `docs/planning/p2-skill-comparison-evals/architect-plan.md` |
| Overfitting rule | `evals/OVERFITTING-RULE.md` |
| Component-level evals | `evals/components/` |
