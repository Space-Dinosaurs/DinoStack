# Verification Gate

**Tests that must pass:**

- Unit:
  - `evals-baseline-capture`: `python -m evals.baseline.validate evals/baselines/2026-05-pre-icl-restructure.json` exits 0.
  - `eval-harness-v1`: pytest passes for all 12 `qa_criteria` scenarios in the unit's architect plan.
  - `skeptic-global-context`: `grep` for `Section 4.5` returns hits in `content/agents/skeptic.md` and `content/references/skeptic-protocol.md`; supplemental-context block present in skeptic.md; counter file convention documented; handoff artifacts committed; Skeptic sign-off granted.
- Integration:
  - `eval-harness-v1`: `bun evals/icl-vs-orchestration/run.ts --smoke` exits 0 (smoke-mode end-to-end run on the smoke corpus).
- E2E: n/a for this Plan (no user-facing surface).

**Cross-unit verification:**

- Cross-unit (baseline-capture -> harness): the eval-harness-v1 Stage-3 baseline run reads `evals/baselines/2026-05-pre-icl-restructure.json` and consumes `git.agentic_engineering_sha` as the AE-orchestrated `content_sha` input. Integration test: a fixture run asserts the harness opens the baseline JSON, reads the SHA field, and pins `ae-orchestrated.yaml` to it without manual intervention.

**qa-engineer triggered?** Yes for `eval-harness-v1`; No for the other two units.
- `evals-baseline-capture`: `qa_skip = pure-backend-library` (per-unit `qa_criteria`); QA does not fire.
- `eval-harness-v1`: `qa_skip = null` per the unit's architect plan; **12 scenarios per architect plan; runtime QA fires.** Methods are a mix of `runtime-required` and `api`. The qa-engineer is spawned per the standard concurrent-with-Skeptic flow on this unit's diff.
- `skeptic-global-context`: `qa_skip = docs-only` (per-unit `qa_criteria`); QA does not fire.

Confirm against each unit's `qa_criteria` block before opening the PR; an absent or non-matching `qa_skip` flips the trigger.

**Manual smoke check:**

- `evals-baseline-capture`: operator spot-reads the baseline JSON schema to confirm the recorded structure matches the validator contract (per the unit's `manual_smoke: "none"`, this is operator-only spot-read for confidence; not gate-bearing).
- `eval-harness-v1`: per the unit's architect plan `manual_smoke` field verbatim - "Operator inspects a successful smoke report by eye for one ticket per class: confirms diff captured; all 6 dimensions present with status in {scored, floored, not-applicable} matching the per-condition binding in COVERAGE.md exactly; symmetric-dimset invariant holds; cost_usd consistent with token totals at expected per-token rates; raw_trace_path resolves; correctness_method, ae_execution_mode, output_coherence_method='fixed-common-pair-binarized-v1', output_coherence_taxonomy_version='v1', rationale_extraction_method_count fields all populated and reflect the operator-resolved Open Questions and round-4 scorer choices." This is in addition to the qa-engineer's automated runtime verification of the 12 scenarios.
- `skeptic-global-context`: operator spot-reads three updated `content/` files to confirm Section 4.5 wiring renders correctly and the manifest updates are coherent (per the unit's `manual_smoke: "none"`, operator-only spot-read for confidence; not gate-bearing).

**Whole-plan completion criteria (verified after all units land, not per-unit):**

- `grep` for `Section 4.5` returns hits across all 28 catalogued spawn sites (future units add the remaining sites beyond the 2 touched in `skeptic-global-context`).
- All 7 manifest updates across the plan's content files are verified by spot-read.

**Rollback signal:**

- Post-merge - if the broader ICL restructure's Stage 6 vs Stage 3 comparison declares "ICL wins" by >2x at the same model tier, that is a rollback signal for the broader restructure (NOT this Plan; out of scope).
- For this Plan specifically, a smoke-mode crash on `bun evals/icl-vs-orchestration/run.ts --smoke` is the immediate rollback trigger for `eval-harness-v1`. A validator non-zero exit on the recorded baseline JSON is the trigger for `evals-baseline-capture`. A grep-miss on Section 4.5 wiring across the catalogued spawn sites is the trigger for `skeptic-global-context`.

**New regression tests required by findings flywheel?** No. This is a greenfield Plan; no `.agentic/findings.md` entries cite these surfaces.
