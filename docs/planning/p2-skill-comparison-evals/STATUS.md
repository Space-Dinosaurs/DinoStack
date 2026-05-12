# Skill-Comparison Evals - Session Status

**Last updated:** 2026-05-12 - all implementation units merged to main.

## What landed on main

| PR | Commit | What |
|---|---|---|
| #61 | 7663068 | Plan-tier planning artifacts: brief / architect-plan / risk-register / rollback / verification-gate / orchestration.jsonl |
| #62 | 5c8aa88 | Skeleton: `evals/skill-comparison/` tree |
| #63 | 700bd22 | Tier 3 Docker isolator |
| #64 | 5ded63f | Canary: ae_rules_payload + assert_canary + real transcript (2 rounds + narrow) |
| #65 | 25009ec | Aggregator + config_discovery (8-condition matrix) |
| #66 | 03d389c | Engineer component manifest + scorer + loader validator (2 rounds + narrow) |
| #67 | fbc8b66 | Frozen task corpus: 12 SWE-bench-lite tasks - REAL SHAs verified (2 rounds + narrow) |
| #68 | 1607d72 | Runner + scoring (3 rounds: 2 Critical wiring bugs fixed - ae-rules-injected payload + Tier3Docker instantiation) |
| #69 | f4efdee | 7 condition spec YAMLs |
| #70 | 1c9f0bb | Full README + AGENTS.md + LEARNINGS append (2 rounds) |

## Implementation complete

All units from `orchestration.jsonl` merge_order 1-9 are landed. Only operator runtime work remains:

| Unit | Status |
|---|---|
| skeleton | DONE #62 |
| engineer-manifest | DONE #66 |
| tier3-isolator | DONE #63 |
| task-corpus | DONE #67 |
| aggregator-extension | DONE #65 |
| canary | DONE #64 |
| runner-scoring | DONE #68 |
| spec-yamls | DONE #69 |
| docs | DONE #70 |
| **sensitivity-check-POST-IMPL** | **PENDING - operator runtime** |

## Sensitivity check (operator runtime, merge_order 99)

Per orchestration.jsonl line 10:

> "Smoke: 2-3 tasks x 8 conditions x n=3 + n=5 baseline-vs-baseline; envelope populated; delta exceeds envelope on >=60% tasks OR plausible prompt edit moves >=60% tasks outside envelope. Then full corpus n>=3, n=5 methodology pair."

This is operator runtime activity, NOT an engineer spawn. Do NOT spawn engineer for merge_order 99. Failure two consecutive iterations triggers rollback.md.

### Recommended next step

1. Operator runs sensitivity smoke first (2-3 tasks x 8 conditions x n=3).
2. Inspect envelope; verify delta exceeds envelope on at least 60% of smoke tasks.
3. If smoke passes, run full corpus (12 tasks x 8 conditions, n=3 most conditions, n=5 baseline-vs-baseline pair).
4. Total cost budget: $250 / 75M tokens / 12h wall-clock per Brief.

## Critical lessons captured

Three durable learnings appended to `evals/LEARNINGS.md`:

1. **No fabricated data in corpus files.** Round-1 task-corpus had all 24 SHAs hallucinated. Engineers must fetch from canonical source (HuggingFace `princeton-nlp/SWE-bench_Lite`) and verify (gh api spot-check). Validator now enforces 40-char hex regex.

2. **Mock at the right boundary.** Round-1 PR #68 fix added `system_prompt=` kwarg to a call site but never added the parameter to `invoke_run`. Tests mocked the wrapper, hiding the TypeError. Mock at `subprocess.run` instead - the actual integration boundary.

3. **Tier 3 isolation must be wired, not just built.** PR #63 built `Tier3Docker` and PR #68's initial implementation passed `tier3_ctx=None` unconditionally. Building the isolator is half the work; the runner has to instantiate it.

Memory feedback also saved: `feedback_no_fabricated_data.md`.

## Files of record

- `docs/planning/p2-skill-comparison-evals/brief.md`
- `docs/planning/p2-skill-comparison-evals/architect-plan.md`
- `docs/planning/p2-skill-comparison-evals/risk-register.md`
- `docs/planning/p2-skill-comparison-evals/rollback.md`
- `docs/planning/p2-skill-comparison-evals/verification-gate.md`
- `docs/planning/p2-skill-comparison-evals/orchestration.jsonl`
- `evals/skill-comparison/README.md` (full doc)
- `evals/skill-comparison/AGENTS.md` (track conventions)
- `evals/LEARNINGS.md` (cross-eval lessons)
- This file
