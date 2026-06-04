# Brief: Auto-Identity + Three-Dimension Tracking (V1)

Tier: Plan (6 Elevated units). Architect plan: `docs/planning/auto-identity-tracking.md` (Skeptic-vetted, 5 rounds). Orchestration DAG: planner output (this directory).

## Problem
Per-operator token/time tracking requires a manual `agentic-identity init`, so it is almost never set and team/operator telemetry is dark. Make identity automatic (derive -> confirm-once -> persist) without ever attributing telemetry under an unconfirmed/wrong handle, and surface the operator (cross-repo) dimension.

## Success criteria
1. `agentic-identity auto` derives a handle from `gh`, writes it `provisional: true`; telemetry + PR `Developer:` trailer stay deferred until confirmed.
2. No telemetry gap: sessions before confirmation are buffered (`~/.agentic/session-log/.pending/`) and flushed (race-safe, deduped) onto the confirmed handle - zero data loss, zero wrong-attribution.
3. Global operator mirror + `agentic-cost operator` give cross-repo rollup; `agentic-cost team` unchanged.
4. Commit template always emits `Signed-off-by` (DCO fix) composed with `Co-Authored-By` + conditional `Developer:` trailer.
5. Existing manually-init'd identities keep working (absent `provisional` == confirmed; zero migration).
6. All 8 adapters + drift baseline regenerated; adapter-sync + methodology-drift + DCO CI gates green.

## Non-goals (V1)
- U7 team-distribution auto-commit (DESCOPED - fast-follow; must run in engineer worktree, not main).
- Cross-machine operator-mirror merge.
- Session-log rotation.

## Verification
Per-unit acceptance criteria = orchestration JSONL `acceptance_criteria`. Feature-level = architect plan QA `manual_smoke` (13 cases). qa_skip: `pure-backend-library` (CLI + hook, no browser surface) - rationale: verified by CLI invocation + filesystem inspection; qa-engineer adds no value over unit/integration + manual smoke.

## qa_criteria
```yaml
qa_skip: pure-backend-library
qa_skip_rationale: CLI tools + Stop hook + doc changes; no browser/UI surface. Verified via CLI + filesystem.
scenarios: []
```
