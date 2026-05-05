# Smoke Corpus Coverage Matrix

Binding per-condition dimension coverage for the 4 smoke fixtures.
Format: `AE:<status> / ICL:<status>` where status is one of:
  - `scored` - dimension is actively scored
  - `floored` - dimension floors at 0.0 by design (no architect plan / qa_criteria)
  - `N/A-both` - not-applicable to BOTH conditions (symmetric; must match)

The `verification-realism` dimension is ALWAYS floored for ICL-baseline
(no architect plan by design) and scored for AE-orchestrated (when plan
+ qa_criteria is present).

NOTE: Skeptic Step-0 enforcement scenarios from `scenarios-todo.md` will be
added to this matrix once that file is delivered by the skeptic-global-context
engineer. See architect-plan-eval-harness-v1.md step 16 for the dependency note.

| Fixture (class)        | correctness              | scope-discipline         | quality-gate-pass        | regression-test-presence | verification-realism      | output-coherence         |
|------------------------|--------------------------|--------------------------|--------------------------|--------------------------|---------------------------|--------------------------|
| `s-trivial-typo`       | AE:scored / ICL:scored   | AE:scored / ICL:scored   | AE:scored / ICL:scored   | N/A-both                 | AE:scored / ICL:floored   | AE:scored / ICL:scored   |
| `s-single-elev-bug`    | AE:scored / ICL:scored   | AE:scored / ICL:scored   | AE:scored / ICL:scored   | AE:scored / ICL:scored   | AE:scored / ICL:floored   | AE:scored / ICL:scored   |
| `s-brief-tier-feature` | AE:scored / ICL:scored   | AE:scored / ICL:scored   | AE:scored / ICL:scored   | AE:scored / ICL:scored   | AE:scored / ICL:floored   | AE:scored / ICL:scored   |
| `s-plan-tier-cross`    | AE:scored / ICL:scored   | AE:scored / ICL:scored   | AE:scored / ICL:scored   | AE:scored / ICL:scored   | AE:scored / ICL:floored   | AE:scored / ICL:scored   |

## Binding assertions (for Scenario 1 evidence)

- `verification-realism` ICL is ALWAYS `floored` (score=0.0) because ICL produces
  no architect plan by design.
- `regression-test-presence` is `N/A-both` for `s-trivial-typo` because
  `expects_regression_test: false` is set symmetrically on that ticket.
- All other cells are `scored` on both conditions.
- The `symmetric-dimset` invariant holds: the `N/A-both` cells are identical
  across AE and ICL for each fixture.

## Overfitting notice

Per `evals/OVERFITTING-RULE.md`: these fixtures are smoke validation only.
Do not tune scorer weights or detection patterns to chase individual fixture scores.
The corpus is diagnostic; calibration against it is overfitting.
