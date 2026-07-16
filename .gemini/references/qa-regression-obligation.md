# QA Regression Test Obligation for Fixed QA Findings

## Overview

Every qa-engineer FAIL on a runtime criterion that gets fixed is a latent regression. Without a regression test (or a curated index entry when a test is genuinely infeasible), the same bug can silently reappear in a future change. When a QA-fail is fixed, the Worker adds a regression test in the project's normal test suite that targets the failing scenario; the Skeptic on the QA-fix iteration verifies the test exists before granting sign-off.

This is the QA-side mirror of the Skeptic-side regression rule in `content/references/regression-test-obligation.md`. The two obligations are symmetric: a Critical/Major Skeptic finding gets a regression test, and a qa-engineer FAIL gets a regression test. Both close the same failure-mode-can-silently-reappear gap.

---

## Engineer obligation

When the conductor spawns a fix engineer in response to a qa-engineer FAIL, the engineer must:

1. Implement the fix.
2. Add a regression test - a unit, integration, e2e, or eval case in the project's normal test suite, alongside existing tests for the affected module, that would have **failed** without the fix and **passes** with it.
3. Reference the test in the fix summary: `QA fail (scenario id N: <title>) -> fixed by [description]. Regression test added: [test file path, test name].`

If adding a regression test is genuinely impossible (no test infrastructure exists for the affected surface; a visual conformance failure has no headless-testable observable; etc.), the engineer must state this explicitly with a reason AND append an entry to `.agentic/qa-regressions.md` using the schema below so the architect catches the surface next time via `qa_criteria`. A missing test with no explanation and no curated-index entry is a Major finding in the next Skeptic round.

## Skeptic verification

The parallel Skeptic on the QA-fix iteration (concurrent QA flow) verifies, before granting sign-off:

- A regression test was added, OR a documented exception was given with a `.agentic/qa-regressions.md` entry.
- The test targets the actual failing scenario - the scenario id and description match the qa-engineer's FAIL report. A superficial test that happens to pass on adjacent code does not count.
- The engineer's summary explicitly attests to running the test against the unfixed code first and observing the FAIL.

If the test is absent without explanation and no `.agentic/qa-regressions.md` entry was appended, raise it as a **Major** finding: `Missing regression test for QA scenario [id: title] - a test that would have caught this failure mode is required before sign-off.`

**The pre-fix-failure property is required, and post-fix execution alone does not establish it.** Executing the test against the fixed code only proves the test currently passes - it does not prove the test would have failed against the FAIL scenario before the fix, which is exactly the property that distinguishes a real regression test from a vacuous one. This property is established by one of two means, either of which is sufficient: (a) the engineer's summary explicitly attests to having run the test against the unfixed code first and observed it fail, or (b) the Skeptic itself executes the test against the pre-fix code (where feasible - e.g. stash or revert the fix, run the test, confirm it fails, then restore the fix) and confirms the failure directly.

**Attempt execution before falling back to attestation.** If the test command is runnable in the Skeptic's review environment (Bash access plus the test's dependencies are present), execute it against the post-fix code and record the raw command and output in the sign-off - do not rely on the engineer's self-report when you are able to check it yourself. Where feasible, also execute it against the pre-fix code to verify (b) directly. Only when pre-fix execution is genuinely not possible (no Bash access in this review context, missing infra, an external dependency the review environment cannot reach, or reverting the fix is impractical) does the Skeptic rely on attestation alone for (a).

**Verification scope (post-execution-attempt):** the Skeptic's obligation is, in order: (1) attempt to execute the test against the post-fix code and report the raw result; (2) where feasible, also execute it against the pre-fix code to independently confirm the failure - see (b) above; (3) if pre-fix execution was not performed, fall back to the engineer's attestation - see (a) above; (4) if NEITHER (a) nor (b) holds - the engineer gave no pre-fix attestation and the Skeptic could not verify pre-fix failure directly - raise a **Major** finding: `Regression test unverified for QA scenario [id: title] - neither the engineer's attestation nor the Skeptic's own execution confirms the test fails against the unfixed code; an unverified regression test provides no more assurance than no test at all.`; (5) if (a) holds but (b) was not performed, raise a **Minor** finding instead: `Regression test attestation unverified by execution for QA scenario [id: title] - execution against the pre-fix code was not possible ([reason]); relying on engineer self-report.` This Minor does not block sign-off but must always be listed; (6) regardless of the above, spot-check the test's target and the engineer's `raw_output` for fabricated evidence (a named test file/function that does not exist in the diff or repository) - fabrication is a **Critical** finding, not a Minor one, per `content/agents/skeptic.md` Step 12's `raw_output` spot-check.

## What counts as a regression test

The bar is correctness coverage of the failing scenario, not test framework formality:

- **Behavioral bugs:** a unit or integration test exercising the specific broken path (the input, state, or sequence that triggered the FAIL).
- **Visual conformance fails:** PREFER a Playwright/e2e assertion that checks the broken claim against the rendered DOM or computed style (color, position, presence, typography). Only fall back to a `.agentic/qa-regressions.md` entry when no automated assertion is feasible.
- **Other UI/UX regressions:** an e2e test that interacts with the actual rendered UI and asserts the corrected behavior.

A test that passes even without the fix does not count. The Worker should confirm (in its summary) that it verified the test fails on the unfixed code.

## `.agentic/qa-regressions.md` schema (canonical)

`.agentic/qa-regressions.md` is the curated cross-ticket index of QA-found behavioral regressions. Architects read this file when authoring `qa_criteria.scenarios[]` on any ticket touching a listed surface, so the scenario that broke before is explicitly verified again.

Schema:

```markdown
# QA Regressions

Curated index of QA-found behavioral regressions. Architects read this when authoring qa_criteria.scenarios[] on any ticket touching a listed surface.

## Entries

### [YYYY-MM-DD] <ticket_id>: <surface> - <one-line claim that broke>
- **Surface:** <file path or route or component name>
- **Scenario that failed:** <verbatim description from qa_criteria>
- **What broke:** <one-line verbatim claim or behavior>
- **Regression test:** <test file path + test name, or "none-feasible: <reason>">
- **Architect note:** <one line on what future qa_criteria should explicitly verify on this surface>
```

**Append-only.** Dedupe by `(surface, claim)`. If a matching key already exists, skip the write. The curator is fire-and-forget; the conductor triggers an emit at Phase 6b clean-exit when any iteration involved a QA FAIL. The curator is the sole writer of `.agentic/qa-regressions.md`.

## Cross-reference

The Skeptic-side equivalent for fixed Critical/Major Skeptic findings lives in `content/references/regression-test-obligation.md`. The two obligations are symmetric: both require a regression test (or a documented exception with curated-index entry) before sign-off, both attempt execution before falling back to attestation, both verify target alignment, and both treat a missing test without explanation as a Major finding in the next round.
