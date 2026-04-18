# Overfitting Rule

This rule applies from day one to any human edit to `content/` motivated wholly or partly by an eval TSV score. It is verbatim from `docs/planning/p2-self-improving-harness.md`.

> Any human edit to `content/` motivated wholly or partly by a TSV score must satisfy: "If this exact fixture disappeared, would this edit still be a worthwhile change to the harness?" If the answer is no, revert. Scores inform; they do not justify. Every such edit must note in the commit message which fixture(s) motivated it, so reviewers can apply this test.

This rule lands in P2 Phase 1 - not deferred to P3 - because P2 is exactly when humans first read scores and are tempted to nudge prompts. The rule is the mitigation for the "Overfitting to fixtures by humans reading scores" risk enumerated in the plan.

Every component-eval README must reference this file.
