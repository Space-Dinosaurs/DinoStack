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
- **Verification scope:** Skeptic cannot independently verify that the test fails on the unfixed code. Its obligation is to verify the test targets the correct failure mode and that the Worker's summary explicitly attests to having run the test against the unfixed code first. A Worker summary that does not include this attestation is insufficient - the Skeptic should treat the absence as though no confirmation was given.

## What counts as a regression test

The bar is correctness coverage of the failure mode, not test framework formality:

- **Code bugs:** a unit or integration test that exercises the specific input or state that triggered the bug.
- **Logic errors:** a test that exercises the branch, edge case, or ordering assumption that was wrong.
- **Missing validation:** a test that provides invalid input and asserts the correct rejection behavior.
- **Prompt / eval failures (LLM projects):** an eval case that demonstrates the model output failure mode, runnable via the project's eval harness.

A test that passes even without the fix does not count. The Worker should confirm (in its summary) that it verified the test fails on the unfixed code.

