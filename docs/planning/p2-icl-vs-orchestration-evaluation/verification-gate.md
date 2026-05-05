# Verification Gate

**Tests that must pass:**

- Unit:
  - `evals-baseline-capture`: `python -m evals.baseline.validate evals/baselines/2026-05-pre-icl-restructure.json` exits 0.
  - `eval-harness-v1`: pytest passes for all 12 `qa_criteria` scenarios in the unit's architect plan.
  - `skeptic-global-context`: `grep` for `Section 4.5` returns hits across all 28 catalogued spawn sites; the 7 manifest updates are verified by spot-read.
- Integration:
  - `eval-harness-v1`: `bun evals/icl-vs-orchestration/run.ts --smoke` exits 0 (smoke-mode end-to-end run on the smoke corpus).
- E2E: n/a for this Plan (no user-facing surface).

**qa-engineer triggered?** No for any unit.
- `evals-baseline-capture`: `qa_skip = pure-backend-library` (per-unit `qa_criteria`).
- `eval-harness-v1`: `qa_skip = pure-backend-library` (per-unit `qa_criteria`).
- `skeptic-global-context`: `qa_skip = docs-only` (per-unit `qa_criteria`).

Confirm against each unit's `qa_criteria` block before opening the PR; an absent or non-matching `qa_skip` flips the trigger.

**Manual smoke check:**

- `evals-baseline-capture`: operator spot-reads the baseline JSON schema to confirm the recorded structure matches the validator contract.
- `eval-harness-v1`: operator inspects one report per ticket class (the corpus partitions) to confirm the harness produced legible, complete output for that class.
- `skeptic-global-context`: operator spot-reads three updated `content/` files to confirm Section 4.5 wiring renders correctly and the manifest updates are coherent.

**Rollback signal:**

- Post-merge - if the broader ICL restructure's Stage 6 vs Stage 3 comparison declares "ICL wins" by >2x at the same model tier, that is a rollback signal for the broader restructure (NOT this Plan; out of scope).
- For this Plan specifically, a smoke-mode crash on `bun evals/icl-vs-orchestration/run.ts --smoke` is the immediate rollback trigger for `eval-harness-v1`. A validator non-zero exit on the recorded baseline JSON is the trigger for `evals-baseline-capture`. A grep-miss on Section 4.5 wiring across the catalogued spawn sites is the trigger for `skeptic-global-context`.

**New regression tests required by findings flywheel?** No. This is a greenfield Plan; no `.agentic/findings.md` entries cite these surfaces.
