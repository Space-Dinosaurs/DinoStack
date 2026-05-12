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
`/agentic-engineering` activation. Explicit per-layer disclosure (reproduced
verbatim from the Brief's "Measurement equivalence" section):

- **Exercised:** Rules-text injection into the outer conductor's system prompt (concatenated SKILL.md + sections + rules + references + commands).
- **Exercised:** Named-agent invocation via two-level Task spawn, frontmatter intact (per the canary).
- **NOT exercised:** Activation preflight (`~/.claude/agentic-engineering.json` mode/profile/preset resolution; AGENTS.md marker scan).
- **NOT exercised:** MEMORY.md auto-injection at session start.
- **NOT exercised:** First-activation sentinel file (`.agentic/.activated`) and one-time notice.
- **NOT exercised:** Stop hook writes to `.agentic/context.md` between turns.
- **NOT exercised:** Per-command preflight re-checks at top of each slash-command body.
- **NOT exercised:** `.agentic/` runtime state files (events.jsonl, tasks.jsonl, loop-state.json) and any behavior conditioned on their presence.

The score delta between `baseline` and `ae-rules-injected` captures the effect
of the rules payload only; it does not capture preflight, memory injection, or
Stop hook behavior. The cost difference is part of what is measured, not a
confounder - `ae_rules_payload.py` builds a ~143k-token system prompt (~571 KB
raw), which is reported alongside the score.

## Measurement caveats

**The `baseline` vs `ae-rules-injected` comparison measures MORE than just the
rules payload.** `baseline` runs raw Claude Code with no AE content injected.
`ae-rules-injected` runs Claude Code with the full AE methodology text in its
system prompt. These two conditions differ in more than just the presence of
the rules text: the AE rules explicitly instruct the conductor to spawn
subagents via two-level Task, apply risk classification thresholds, run Skeptic
loops, and follow delegation protocols. This changes the runtime behavior of
the session - the number of agent spawns, the token usage pattern, the
wall-clock time, and the output discipline all shift. A delta between `baseline`
and `ae-rules-injected` is therefore the **combined effect** of: (a) the rules
payload itself as inert text, and (b) the runtime behavior the rules induce in
the conductor. These two components cannot be separated by this eval design.

The per-agent conditions (`engineer-direct`, `architect-direct`, etc.) partially
decompose this confound. Each `-direct` condition spawns a single named agent
via bare two-level Task with no additional system prompt, so the comparison
`<agent>-direct` vs `baseline` isolates the agent's specific prompting from the
orchestration layer. However, the `-direct` conditions do not sum to the
`ae-rules-injected` condition: production AE applies orchestration logic on top
of individual agent invocations, and that orchestration effect is measured only
in aggregate by the methodology pair. Readers should interpret per-agent deltas
as "does this agent's prompt produce better raw output?" and the methodology
delta as "does the full rules payload - including its behavioral side effects -
produce better end-to-end outcomes?"

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

The sensitivity check (see "How to run") verifies that the
baseline-vs-ae-rules-injected delta exceeds the baseline noise envelope on
>=60% of in-scope tasks before the eval is considered discriminating.

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
python evals/skill-comparison/runner.py \
  --tasks-yaml evals/skill-comparison/tasks/corpus.yaml \
  --dry-run
```

Validates corpus YAML, condition specs, and isolator connectivity without
spending tokens.

### Sensitivity check (methodology pair only, n=5)

```bash
python evals/skill-comparison/runner.py \
  --tasks-yaml evals/skill-comparison/tasks/corpus.yaml \
  --conditions baseline ae-rules-injected \
  --n-replicates-methodology 5
```

Runs baseline twice (n=5 each) to establish the noise envelope, then runs
`ae-rules-injected` n=5. Exits with a summary of whether the delta exceeds
the envelope on >=60% of tasks. **Run this before the full corpus.**

### Full corpus run

```bash
python evals/skill-comparison/runner.py \
  --tasks-yaml evals/skill-comparison/tasks/corpus.yaml \
  --n-replicates 3 \
  --n-replicates-methodology 5
```

Runs all 8 conditions across the full task corpus. The methodology pair
(`baseline` vs `ae-rules-injected`) uses n=5; all other conditions use n=3.
Budget ceiling: $250 / 75 M tokens. The runner halts and emits a partial
report on breach (exit code 3).

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--tasks-yaml` | (required) | Path to task corpus YAML (e.g. `tasks/corpus.yaml`). |
| `--results-tsv` | auto-derived | Path to output TSV ledger. Defaults to `results/skill-comparison.tsv`. |
| `--conditions` | all conditions | Space-separated list of condition names to run (e.g. `baseline ae-rules-injected`). Omit to run all 8. |
| `--n-replicates` | `3` | Replicate count per (task, condition) cell, except the methodology pair. |
| `--n-replicates-methodology` | `5` | Replicate count for `baseline` and `ae-rules-injected` cells (the methodology pair noise envelope). |
| `--tier3` | `auto` | Docker isolation mode. `auto` uses Tier 3 in production; `off` skips Docker (for dry-run / unit tests). |
| `--force` | off | Re-run cells already present in the TSV (bypass resume skip). |
| `--dry-run` | off | Validate config and isolator connectivity; skip all Claude calls. |
| `--content-root` | auto-derived | Path to `content/` directory for AE-rules payload builder. |
| `--max-usd` | `250.0` | Hard cost ceiling in USD; runner halts and emits partial report on breach (exit 3). |
| `--max-tokens` | `75000000` | Hard token ceiling; same halt-and-partial-report behavior. |
| `--max-wall-seconds` | `43200.0` | Hard wall-clock ceiling (12 hours); same halt behavior. |

### Aggregating results

```bash
python evals/skill-comparison/aggregate.py results/skill-comparison.tsv
```

Produces a summary table with median and stdev per condition, delta-vs-baseline
per condition, and the baseline noise envelope column.

## TSV schema (`results/skill-comparison.tsv`)

Columns are defined by `_TSV_HEADER` in `runner.py`. The append-only ledger
has exactly these 16 columns, in order:

| Column | Type | Description |
|---|---|---|
| `task_slug` | string | Task identifier from `corpus.yaml` (e.g. `django__django-12345`). |
| `condition` | string | One of the 8 condition names (e.g. `baseline`, `ae-rules-injected`). |
| `replicate` | int | 1-indexed replicate number within the (task, condition) cell. |
| `status` | string | Outcome of the run: `pass`, `fail`, `error`, `timeout`, or `budget_exceeded`. |
| `pass_fail` | string | Simplified binary result: `pass` or `fail`. Derived from held-out test results. |
| `score_primary` | float | 1.0 if all held-out tests pass, else 0.0. Primary metric for aggregate comparisons. |
| `lines_touched` | int | Lines changed in the agent-produced diff. Diff-hygiene diagnostic. |
| `files_touched` | int | Number of files changed in the diff. Diff-hygiene diagnostic. |
| `scope_creep_flag` | bool | True if any file touched falls outside the task's known surface area. |
| `held_out_failures` | string | Comma-separated list of failing held-out test IDs; empty string on full pass. |
| `cost_usd` | float | Estimated cost in USD for this run (best-effort; may be 0.0 if not reported by the CLI). |
| `tokens_input` | int | Input tokens consumed by the session. |
| `tokens_output` | int | Output tokens generated by the session. |
| `latency_ms` | int | Wall-clock milliseconds from session start to scoring completion. |
| `invocation_mode` | string | How the condition was invoked: `conductor`, `agent-direct`, or `dry-run`. |
| `diagnostics_json` | string | JSON blob of additional per-run diagnostics (scorer details, error traces, etc.). |

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
