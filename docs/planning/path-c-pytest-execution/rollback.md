# Rollback

**Procedure:** revert the merge commit on `feature/path-c-pytest-execution`. All changes are confined to `evals/icl_vs_orchestration/` plus two ticket.yaml files plus AGENTS.md. No DB migration, no API contract, no production state.

**Steps:**
1. `git revert <merge-sha>` on `feature/path-c-pytest-execution` or `main` after merge.
2. Force-fresh local state: `git checkout main && git reset --hard origin/main`.
3. No env-var or config rollback needed.
4. Old smoke runs on disk (`results/<id>/results-v1.json`) remain valid; they pre-date Path C and do not contain `test_execution` fields.

**Constraints:** revert leaves the corpus and harness in pre-Path-C state. Any smoke runs executed during the Path C window that wrote `test_execution` blocks will still parse correctly (the keyword fallback path runs when `test_execution` is absent in the stored dict, but a stored `test_execution` does NOT cause harm; correctness.py first-path is forward-only).

**No data loss risk.** No external systems are touched.
