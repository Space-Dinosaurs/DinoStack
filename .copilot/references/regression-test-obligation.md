# Regression Test Obligation for Fixed Skeptic Findings

## Overview

Every Critical or Major Skeptic finding that gets fixed is a latent regression. Without a test, the same bug can silently reappear in a future change. When a finding is fixed, the Worker proposes a test that would have caught it; the Skeptic verifies the test exists before granting sign-off.

This is a code-level mechanism: the regression test lives in the project's normal test suite, alongside existing tests for the affected module.

---

## Worker obligation

When a Worker fixes a Critical or Major Skeptic finding, it must:

1. Implement the fix.
2. Add a regression test — a test case (unit, integration, or eval) that would have **failed** without the fix and **passes** with it. The test lives in the project's normal test suite, alongside existing tests for the affected module.
3. Reference the test in the fix summary: `C1 (finding title) → fixed by [description]. Regression test added: [test file path, test name/description].`

If adding a regression test is genuinely not possible (e.g., the project has no test infrastructure, or the failure mode is a documentation error with no executable path), the Worker must state this explicitly with a reason. A missing test without explanation is a Major finding in the next Skeptic round.

## Skeptic verification

Before granting sign-off on a round where a Critical or Major finding was fixed:

- Verify a regression test was added (or a documented exception was given).
- Spot-check that the test actually targets the failure mode described in the finding — not a superficial test that happens to pass.
- If the test is absent without explanation, raise it as a **Major** finding: `Missing regression test for [finding title] — a test that would have caught this failure mode is required before sign-off.`
- **The pre-fix-failure property is required, and post-fix execution alone does not establish it.** Executing the test against the fixed code only proves the test currently passes - it does not prove the test would have failed before the fix, which is exactly the property that distinguishes a real regression test from a vacuous one. This property is established by one of two means, either of which is sufficient: (a) the Worker's summary explicitly attests to having run the test against the unfixed code first and observed it fail, or (b) the Skeptic itself executes the test against the pre-fix code (where feasible - e.g. stash or revert the fix, run the test, confirm it fails, then restore the fix) and confirms the failure directly.
- **Attempt execution before falling back to attestation.** If the test command is runnable in the Skeptic's review environment (Bash access plus the test's dependencies are present), execute it against the post-fix code and record the raw command and output in the sign-off - do not rely on the Worker's self-report when you are able to check it yourself. Where feasible, also execute it against the pre-fix code to verify (b) directly. Only when pre-fix execution is genuinely not possible (no Bash access in this review context, missing infra, an external dependency the review environment cannot reach, or reverting the fix is impractical) does the Skeptic rely on attestation alone for (a).
- **Verification scope (post-execution-attempt):** the Skeptic's obligation is, in order: (1) attempt to execute the test against the post-fix code and report the raw result; (2) where feasible, also execute it against the pre-fix code to independently confirm the failure - see (b) above; (3) if pre-fix execution was not performed, fall back to the Worker's attestation - see (a) above; (4) if NEITHER (a) nor (b) holds - the Worker gave no pre-fix attestation and the Skeptic could not verify pre-fix failure directly - raise a **Major** finding: `Regression test unverified for [finding title] - neither the Worker's attestation nor the Skeptic's own execution confirms the test fails against the unfixed code; an unverified regression test provides no more assurance than no test at all.`; (5) if (a) holds but (b) was not performed, raise a **Minor** finding instead: `Regression test attestation unverified by execution - execution against the pre-fix code was not possible ([reason]); relying on Worker self-report.` This Minor does not block sign-off but must always be listed; (6) regardless of the above, spot-check the test's target and the Worker's `raw_output` for fabricated evidence (a named test file/function that does not exist in the diff or repository) - fabrication is a **Critical** finding, not a Minor one, per `content/agents/skeptic.md` Step 12's `raw_output` spot-check.

## What counts as a regression test

The bar is correctness coverage of the failure mode, not test framework formality:

- **Code bugs:** a unit or integration test that exercises the specific input or state that triggered the bug.
- **Logic errors:** a test that exercises the branch, edge case, or ordering assumption that was wrong.
- **Missing validation:** a test that provides invalid input and asserts the correct rejection behavior.
- **Prompt / eval failures (LLM projects):** an eval case that demonstrates the model output failure mode, runnable via the project's eval harness.

A test that passes even without the fix does not count. The Worker should confirm (in its summary) that it verified the test fails on the unfixed code.

