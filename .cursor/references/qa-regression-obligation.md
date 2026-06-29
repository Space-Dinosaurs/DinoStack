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

**Verification scope:** Skeptic cannot independently verify that the test fails on the unfixed code (parallel to the Skeptic-side rule). Its obligation is to verify the test targets the correct scenario and that the Worker's summary explicitly attests to having run the test against the unfixed code first. A Worker summary that does not include this attestation is insufficient - the Skeptic should treat the absence as though no confirmation was given.

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

The Skeptic-side equivalent for fixed Critical/Major Skeptic findings lives in `content/references/regression-test-obligation.md`. The two obligations are symmetric: both require a regression test (or a documented exception with curated-index entry) before sign-off, both verify target alignment without re-executing the test on the unfixed code, and both treat a missing test without explanation as a Major finding in the next round.
