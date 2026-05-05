# Smoke Corpus Coverage Matrix

Binding per-condition dimension coverage for the 4 smoke fixtures.
Format: `AE:<status> / ICL:<status>` where status is one of:
  - `scored` - dimension is actively scored
  - `floored` - dimension floors at 0.0 by design (no architect plan / qa_criteria)
  - `N/A-both` - not-applicable to BOTH conditions (symmetric; must match)

The `verification-realism` dimension is ALWAYS floored for ICL-baseline
(no architect plan by design) and scored for AE-orchestrated (when plan
+ qa_criteria is present).

Skeptic Step-0 enforcement scenarios from `scenarios-todo.md` (authored by the
`skeptic-global-context` engineer, Stage 1) are binding test coverage targets.
These scenarios test conductor-level and Skeptic-level behavior. They are not
corpus tickets (no fixture YAML required) - they are unit/integration tests in
`tests/test_skeptic_step0.py`. See that file for the 4 scenario implementations.

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

## Skeptic Step-0 enforcement scenarios (from scenarios-todo.md)

These 4 scenarios from `scenarios-todo.md` are implemented as unit tests, not
corpus tickets. They verify conductor and Skeptic behavior at the protocol
boundary; they do not produce ticket-level scores.

| Scenario | Description | Test location |
|---|---|---|
| S1 - BLOCKED on incomplete prompt | Skeptic returns BLOCKED when Global-context block is missing a required field (e.g. qa_criteria). No review content emitted. | `tests/test_skeptic_step0.py::test_blocked_on_missing_field` |
| S2 - BLOCKED on non-enum n/a value | Skeptic returns BLOCKED when a Global-context field carries a bare `n/a` or non-enumerated `n/a - <string>`. Valid enum values do not trigger BLOCKED. | `tests/test_skeptic_step0.py::test_blocked_on_invalid_na_value` |
| S3 - Counter-and-escalate after 3 consecutive BLOCKED | After 3 consecutive `skeptic_blocked_input` returns on the same unit, conductor escalates and does not retry. Counter file at `.agentic/.spawn-block-counter-<unit_slug>` cleaned up after sign-off. | `tests/test_skeptic_step0.py::test_counter_escalate_after_three_blocked` |
| S4 - Plan-tier overflow fallback above 60K tokens | When combined Global-context input set exceeds 60K tokens, conductor switches to per-unit Skeptics plus lightweight integration Skeptic on findings only. Threshold inclusive (>= 60K). | `tests/test_skeptic_step0.py::test_plan_tier_overflow_fallback` |

Supplemental-context shape verification (companion to S1-S3): `security-auditor`
and `perf-analyst` receive `## Supplemental context` (not `## Global-context inputs`)
in multi-dim fan-out. Omitting `qa_criteria` from Supplemental-context does not
trigger BLOCKED. Covered by `tests/test_skeptic_step0.py::test_supplemental_context_shape`.

## Overfitting notice

Per `evals/OVERFITTING-RULE.md`: these fixtures are smoke validation only.
Do not tune scorer weights or detection patterns to chase individual fixture scores.
The corpus is diagnostic; calibration against it is overfitting.
