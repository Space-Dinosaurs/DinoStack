# Verification Gate

**Tests that must pass:**
- Unit: `pytest evals/runner/tests/test_isolator_tier3.py` (held-out leakage isolator test, unit 2); `pytest evals/skill-comparison/tests/test_ae_rules_payload.py` (payload byte-equivalence + glob ordering, unit 4); `pytest evals/skill-comparison/tests/test_aggregate.py` (n-condition rollup + delta + envelope columns, unit 5).
- Integration: canary stream-json assertion script (unit 4) exits 0 on `skeptic` direct-spawn transcript; smoke-run rollup (unit 7) produces a TSV with all 8 conditions populated on 2-3 tasks at n=3 plus n=5 baseline-vs-baseline replicates.
- E2E: full matrix run (unit 8) produces `evals/results/skill-comparison.tsv` with all 8 conditions x full corpus at n>=3 (n=5 on methodology pair), and `aggregate.py` rollup with sensitivity-check column shows discrimination per LEARNINGS.md:62-65 (delta exceeds envelope on >=60% of in-scope tasks).

**qa-engineer triggered?** Yes. Triggers:
- Unit 4 (canary): runtime-required - stream-json transcript inspection (QA scenario 1).
- Unit 7 (smoke + sensitivity): runtime-required - TSV inspection and rollup script exit code (QA scenario 2).
- Unit 2 (isolator): runtime-required - in-container leakage test (QA scenario 3).
- Unit 8 (full run + docs): api - README grep assertion that `ae-rules-injected` label is present and `ae-skill` is absent, and production-layer table is included (QA scenario 4).

**Manual smoke check:** After the first full matrix run completes, operator spot-checks one row per condition in `evals/results/skill-comparison.tsv` to confirm status/score/held-out fields are populated and non-degenerate. Operator also reads `evals/skill-comparison/README.md` and confirms the condition is named `ae-rules-injected` and the production-layer table is reproduced verbatim from the Brief.

**Rollback signal:** sensitivity check fails on two consecutive corpus iterations AND no plausible prompt edit moves >=60% of tasks outside the envelope - the eval is not discriminating; trigger `./rollback.md`. Single-run failure or transient Docker flake is NOT a rollback signal (retry).

**New regression tests required by findings flywheel?** No `.agentic/findings.md` entries currently mandate regression coverage for this work; if any are added during implementation, the responsible engineer adds the regression test in the same diff as the fix and lists the entry ID here.
