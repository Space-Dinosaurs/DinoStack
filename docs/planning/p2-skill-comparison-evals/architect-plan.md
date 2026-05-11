# Architect plan: Skill-Comparison Evals

This document holds the architecture, component reuse map, Tier 3 isolator decision, eval matrix shape, canary plan, documentation plan, and per-unit decomposition for the skill-comparison eval tree. The Brief (`./brief.md`) holds problem framing, success criteria, constraints, verification, and QA criteria; this file is referenced from the Brief's "Linked artifacts" field.

## Directory layout (new tree)

```
evals/skill-comparison/
  README.md                       # what this measures, how to run, caveats; MUST include production-layer table from Brief
  AGENTS.md                       # per-track agent notes
  runner.py                       # 8-condition matrix driver; reuses evals/runner/*
  config_discovery.py             # mirrors aggregate_benchmark dynamic discovery
  aggregate.py                    # n-condition rollup with deltas-vs-baseline
  scoring.py                      # pass/fail + diff-hygiene diagnostics
  ae_rules_payload.py             # builds the AE-rules-injected system-prompt blob from content/
  canary/                         # canary transcripts + assertion script
  specs/
    methodology.yaml              # baseline vs baseline+ae-rules-injected
    engineer.yaml                 # baseline vs baseline+engineer-direct
    architect.yaml
    investigator.yaml
    debugger.yaml
    skeptic.yaml
    qa-engineer.yaml
  tasks/
    corpus.yaml                   # task selection list + per-task metadata
    <task_slug>/                  # seeded repo state, held-out tests, problem
  results/
    skill-comparison.tsv
```

All new non-trivial modules (runner, scoring, isolator, ae_rules_payload, aggregate, harness glue) carry a module manifest per `content/rules/module-manifest.md`.

## Component reuse map

| Reused as-is | From | Why |
|---|---|---|
| `invoker.run_session` (agent mode) | evals/runner/invoker.py:154-217 | Already does the two-level Task spawn correctly. |
| `isolator.tier_1` / `tier_2` | evals/runner/isolator.py | Worktree + HOME redirect. |
| `normalizer`, `aggregator`, `tsv_writer`, `loader`, `prompt` | evals/runner/ | Output parsing, TSV append, fixture loading. |
| `cost_gate`, `smoke_gate`, `report` shape | evals/icl_vs_orchestration/ | Multi-condition head-to-head template; BudgetExceeded exit-3 pattern reused for our $250 / 75 M-token ceiling. |
| `aggregate_benchmark.py` discovery pattern | skill-creator | Dynamic config-dir discovery for N conditions. |

## New code needed

- `evals/skill-comparison/runner.py`: orchestrates the 8-condition matrix per task; for each cell, calls `invoker.run_session` in conductor or agent mode depending on condition; for the `ae-rules-injected` condition, attaches the payload from `ae_rules_payload.build()` as the conductor's system prompt. ~150 LOC.
- `evals/skill-comparison/ae_rules_payload.py`: reads `content/SKILL.md`, `content/sections/*.md`, `content/rules/*.md`, `content/references/*.md`, `content/commands/*.md` in that order; concatenates with stable separator headers; returns a string. Content-globbed for cache invalidation. The `content_glob` field in every spec YAML referencing this payload MUST list EXACTLY these five glob entries in this order so the cache key matches. ~55 LOC.
- `evals/skill-comparison/aggregate.py`: extends `aggregate_benchmark`'s rollup to N>2 conditions with per-condition delta-vs-baseline and a baseline-noise-envelope column derived from baseline-vs-baseline replicate stdev. ~50 LOC.
- `evals/skill-comparison/scoring.py`: runs held-out pytest in isolation, parses pass/fail, computes diff-hygiene (lines touched, files touched, scope-creep flag). ~120 LOC.
- Tier 3 Docker isolator: ~200 LOC in `evals/runner/isolator.py` with a `tier_3_docker` function plus `Dockerfile.swebench` and entrypoint script; includes the held-out-leakage unit test (scenario 3 of QA criteria).
- `engineer.yaml` component manifest (filling the gap noted by Investigator 2): ~12 LOC.

## Tier 3 decision: BUILD IT (minimal)

SWE-bench tasks need a sandbox to run held-out tests. Tier 2 (worktree + HOME redirect) is insufficient because the engineer/repair task may execute arbitrary code from the seeded repo, and we want network denial plus filesystem containment. Build a minimal Tier 3:

- Single base image `python:3.11-slim` plus per-task overlay for dependencies.
- `--network none` by default; per-task opt-in network allowed if a task requires it (none in the v1 corpus).
- HOME redirect inside the container; auth symlinks NOT mounted (the agent inside the container is the SUT, not the harness; if the SUT itself needs Claude credentials to run subagents, mount via separate ro path).
- Volume mount of the worktree (rw) and the held-out test set (ro, separate path so the agent cannot read tests during the fix phase). Mount layout is asserted by the leakage unit test (QA scenario 3).
- Timeout enforced by `docker run --stop-timeout` plus a wall-clock guard in `isolator.py`.

The "minimal" framing matters: Python-only, pytest-only, single base image, v1.

Rejected alternative: descope to Tier-2-runnable tasks (e.g. fixture-style code review or planner-output critique). Rejected because the question we are answering is "do these agents help solve real bugs?" - a code-review-only corpus answers a different question and would not be defensible as the headline result.

## Eval matrix shape

8 conditions, one TSV:
- `baseline` (vanilla Claude conductor, no AE rules payload, no per-agent target)
- `ae-rules-injected` (conductor with AE content payload injected inline as system prompt)
- `engineer-direct`, `architect-direct`, `investigator-direct`, `debugger-direct`, `skeptic-direct`, `qa-engineer-direct` (bare two-level Task spawn of the named agent)

The "methodology-level pair" is `baseline` vs `ae-rules-injected`. The "per-agent pairs" are `baseline` vs each `<agent>-direct`.

Config naming convention (compatible with `aggregate_benchmark` dynamic discovery): each condition is a directory name under a per-task results tree. The discovery loop globs `iteration-N/eval-X/<condition>/run-N/grading.json`. Conditions: `baseline`, `ae-rules-injected`, `engineer-direct`, etc. Aggregate produces a row per condition and a delta row per `(<agent>-direct, baseline)` and `(ae-rules-injected, baseline)`.

n=3 per cell minimum; n=5 floor on the methodology-level pair (this is the headline number, and the same n=5 replicates establish the baseline noise envelope used by the sensitivity check).

Task corpus size: 10-15 SWE-bench-lite tasks for v1. Difficulty mix per the Brief's Constraints section. This mix is hypothesis-driven: per-agent deltas should appear on the tasks that match each agent's strength (investigator on the multi-file ones, architect on the design-y ones, etc.). If all agents show identical deltas across all task tiers, that is a strong signal that the eval is not discriminating.

## Scoring rubric

Primary: binary pass/fail on the held-out test suite. `score_primary = 1.0` if all held-out tests pass, else `0.0`. No partial credit on the primary score - either the bug is fixed or it is not.

Diagnostics (recorded but not aggregated into the primary score):
- `lines_touched`, `files_touched` (diff size)
- `scope_creep_flag`: true if files touched fall outside the bug's known surface (per task manifest)
- `held_out_failures`: list of failing test ids
- `time_to_solution_sec`, `tool_calls`, `subagent_spawns`

Diagnostics are reported alongside but kept out of the primary score to avoid the LEARNINGS.md:14-19 floor/ceiling failure mode. If we want a composite later, fine; v1 is binary plus diagnostics.

## Canary verification plan (before authoring per-agent specs or seeding non-baseline runs)

Single-agent canary: pick `skeptic` (smallest scope, well-understood frontmatter). Steps:

1. Run a one-off invocation of a known fixture (reuse one from `evals/components/skeptic/`) via `invoker.run_session(mode="agent", agent_name="skeptic")` under the Tier 3 isolator.
2. Capture the stream-json transcript to `evals/skill-comparison/canary/skeptic.jsonl`.
3. Run the assertion script (in unit 4 diff) which parses the transcript and confirms: an inner `Task` tool_use with `subagent_type: "skeptic"` appears, AND the inner agent's system prompt includes the frontmatter-declared tool list (Read/Grep/Glob/Task), NOT the outer session's tool list.
4. Compare the inner agent's behavior to the same fixture run through `evals/components/skeptic`'s native `invoker.run_session` (no isolator wrapping). Outputs should be substantively equivalent (allowing for normal LLM nondeterminism).

If step 3 or 4 fails, halt all downstream work. Surface to the operator with the failed assertion and the captured transcript. Do not seed any non-baseline cells until the canary returns green or the eval design is revised.

## Documentation plan

| Doc | Location | Audience |
|---|---|---|
| Brief | `./brief.md` (this directory) | reviewers, future maintainers |
| README | `evals/skill-comparison/README.md` | anyone running the eval; explains what is measured, what is not, how to read TSV; **MUST include the `ae-rules-injected` condition label (not `ae-skill`) and the production-layer table from the Brief verbatim**; includes baseline confound caveat (below) |
| Per-track AGENTS.md | `evals/skill-comparison/AGENTS.md` | agents operating in this subtree |
| Inline spec docs | `evals/skill-comparison/specs/*.yaml` headers | spec maintainers |
| LEARNINGS append | `evals/LEARNINGS.md` (post-implementation) | future eval authors |

**Baseline confound caveat (documented in README and risk register):** Baseline measurement includes the operator's `~/.claude/CLAUDE.md` global instructions, which may already reference the agentic-engineering skill or its conventions. The methodology-vs-baseline delta may therefore be compressed by this prior. The published report states this explicitly; baseline is NOT silently treated as methodology-free. A future tightening could strip `~/.claude/CLAUDE.md` for the baseline condition, but that diverges from real-user experience and is out of scope for v1.

## Interaction with existing `/auto-harness` (evals/auto/)

Orthogonal. `/auto-harness` is the karpathy-loop for self-improvement on a single component eval. This new tree is a multi-condition outcome eval. No code dependency in either direction. Both write to TSV ledgers under `evals/results/`; the filenames are distinct (`auto-harness.tsv` vs `skill-comparison.tsv`). The Overfitting Rule applies equally to both - any `content/` edit motivated by a `skill-comparison.tsv` score must cite the task fixture and pass the counterfactual.

Potential future integration (out of scope for v1): auto-harness could be pointed at the per-agent specs in this tree to auto-tune each agent against the task corpus. Document as a possible follow-up; do not build.

## Per-unit decomposition (for orchestration-planner)

Anticipated units (planner will refine):

1. **`engineer.yaml` component manifest** (Trivial; unblocks any downstream that wants the full 6-agent component eval set).
2. **Tier 3 Docker isolator** (Elevated; new code in `evals/runner/isolator.py` + Dockerfile + entrypoint; MUST include the held-out-leakage unit test asserting an in-container process cannot read the held-out test path during the fix phase, and asserting the rw fix-phase mount and ro held-out mount are at distinct paths). Parallelizable with unit 3.
3. **Task corpus selection + seeding** (Elevated; pick 10-15 SWE-bench-lite tasks per the frozen selection criteria, seed each as `evals/skill-comparison/tasks/<slug>/`, commit corpus.yaml to git; no post-hoc edits once unit 8 runs). Parallelizable with unit 2.
4. **Canary verification** (Elevated; author `ae_rules_payload.py` (globs SKILL.md + sections + rules + references + commands per the ordering rationale above), canary assertion script, run canary on `skeptic` via direct two-level Task spawn, save transcript, document outcome). Blocks every downstream non-baseline cell. Depends on unit 2.
5. **Runner + aggregate + scoring** (Elevated; `runner.py`, `aggregate.py`, `scoring.py`). Depends on units 2 and 3.
6. **Spec YAMLs (8 conditions)** (Low; thin YAML files; condition label is `ae-rules-injected`, not `ae-skill`). Sequential after units 1, 4, 5.
7. **Smoke run + sensitivity check** (Elevated; n=3 on 2-3 tasks across all 8 conditions plus n=5 baseline-vs-baseline replicates on the methodology pair to establish the noise envelope; verify discrimination per LEARNINGS.md:62-65). Depends on unit 6.
8. **Full baseline run + docs** (Elevated; n>=3 across full corpus, n=5 on methodology pair, write README and AGENTS.md including the production-layer table verbatim and the `ae-rules-injected` label, append LEARNINGS). Depends on unit 7.

Likely parallel batches:
- Batch A: units 1, 2, 3 (all independent or only-loosely-coupled).
- Batch B: unit 4 (after 2), unit 5 (after 2, 3).
- Batch C: unit 6 (after 1, 4, 5).
- Batch D: unit 7.
- Batch E: unit 8.
