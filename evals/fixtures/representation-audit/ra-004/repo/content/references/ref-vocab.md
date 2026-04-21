# ref-vocab

A reference with a mix of the same qualifier phrase appearing in multiple places, imperative step sequences, and one borderline block that is NOT an R-signal candidate (a legitimate numbered procedural list where order matters).

## Sequence A - legitimate ordered steps (NOT an R3 candidate)

1. Clone the repo.
2. Install dependencies.
3. Run the test suite.
4. Fix any failures before opening a PR.

Order matters; these steps are not prose-shaped pseudocode.

## Repeated qualifier - deploy gate

A deploy may proceed only if the pre-flight gate has passed, unless the caller has explicitly overridden the gate with the `override` flag. The deploy tooling refuses to proceed if the pre-flight gate has not passed, unless the caller has explicitly overridden the gate with the `override` flag. The rollback runbook requires that a deploy has passed the pre-flight gate, unless the caller has explicitly overridden the gate with the `override` flag.

## Pseudocode-in-prose

When a failure is detected, first capture a screenshot, then copy the DOM snapshot, then save the console log, then save the network log, then diff against the baseline, then emit a verdict of PASS or FAIL, and if FAIL, open a Linear ticket and assign it to the on-call rotation.
