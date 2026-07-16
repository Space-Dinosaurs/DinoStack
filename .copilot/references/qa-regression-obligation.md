# QA Regression Test Obligation for Fixed QA Findings

## Overview

Every qa-engineer FAIL on a runtime criterion that gets fixed is a latent regression. Without a regression test (or a curated index entry when a test is genuinely infeasible), the same bug can silently reappear in a future change. When a QA-fail is fixed, the Worker adds a regression test in the project's normal test suite that targets the failing scenario; the Skeptic on the QA-fix iteration verifies the test exists before granting sign-off.

This is the QA-side mirror of the Skeptic-side regression rule in `content/references/regression-test-obligation.md`. The two obligations are symmetric: a Critical/Major Skeptic finding gets a regression test, and a qa-engineer FAIL gets a regression test. Both close the same failure-mode-can-silently-reappear gap.

---

## Engineer obligation

When the conductor spawns a fix engineer in response to a qa-engineer FAIL, the engineer must:

1. Implement the fix.
2. Add a regression test - a unit, integration, e2e, or eval case in the project's normal test suite, alongside existing tests for the affected module, that would have **failed** without the fix and **passes** with it.
3. Reference the test in the fix summary, including the pre-fix attestation: `QA fail (scenario id N: <title>) -> fixed by [description]. Regression test added: [test file path, test name]. Confirmed failing pre-fix: [what was observed when the test was run against the unfixed code].`

If adding a regression test is genuinely impossible (no test infrastructure exists for the affected surface; a visual conformance failure has no headless-testable observable; etc.), the engineer must state this explicitly with a reason AND append an entry to `.agentic/qa-regressions.md` using the schema below so the architect catches the surface next time via `qa_criteria`. A missing test with no explanation and no curated-index entry is a Major finding in the next Skeptic round.

## Skeptic verification

The parallel Skeptic on the QA-fix iteration (concurrent QA flow) verifies, before granting sign-off:

- A regression test was added, OR a documented exception was given with a `.agentic/qa-regressions.md` entry.
- The test targets the actual failing scenario - the scenario id and description match the qa-engineer's FAIL report. A superficial test that happens to pass on adjacent code does not count.
- The engineer's summary explicitly attests to running the test against the unfixed code first and observing the FAIL.

If the test is absent without explanation and no `.agentic/qa-regressions.md` entry was appended, raise it as a **Major** finding: `Missing regression test for QA scenario [id: title] - a test that would have caught this failure mode is required before sign-off.`

**The pre-fix-failure property is required, and post-fix execution alone does not establish it.** Executing the test against the fixed code only proves the test currently passes - it does not prove the test would have failed against the FAIL scenario before the fix, which is exactly the property that distinguishes a real regression test from a vacuous one. This property is established by one of two means, either of which is sufficient: (a) the engineer's summary explicitly attests to having run the test against the unfixed code first and observed it fail, or (b) the Skeptic itself executes the test against the pre-fix code in an **ephemeral scratch worktree at a run-unique path** - `<scratch>` must be unique per invocation (e.g. `mktemp -d` or `.agentic/skeptic-scratch/$(date +%s)-$$`), never a fixed literal path, so a successive fix round or a concurrent `skeptic_strategy: multi-dimensional` peer reviewing the same diff cannot collide on it - (where feasible - e.g. `git worktree add <scratch> <base-sha>` to create it at the pre-fix base, `git -C <scratch> checkout <head-sha> -- <test-paths>` to apply only the test file(s) from the diff on top of it - not the fix itself - run the test inside `<scratch>`, confirm it fails for the reason the scenario describes, then `git worktree remove --force <scratch>` - `--force` is required because the prior checkout step leaves the scratch worktree with staged changes, which a plain `git worktree remove` refuses to delete) and confirms the failure directly. Never check out the pre-fix base in place in the tree you are reviewing from - that mutates a working tree the Skeptic does not own, and is unsafe when the tree is shared across parallel Skeptic strategies (e.g. `skeptic_strategy: multi-dimensional`). With a scratch worktree there is nothing to restore afterward; removing the worktree is sufficient. A collection, import, or file-not-found error is NOT a pre-fix failure and does not satisfy (b) - when the fix and its regression test are committed together, reverting the fix in place also deletes the test, so the resulting error proves only that the test file is missing, not that the pre-fix code exhibits the bug.

**Attempt execution before falling back to attestation.** If the test command is runnable in the Skeptic's review environment (Bash access plus the test's dependencies are present), execute it against the post-fix code and record the raw command and output in the sign-off - do not rely on the engineer's self-report when you are able to check it yourself. Where feasible, also verify (b) directly using an ephemeral scratch worktree at a run-unique `<scratch>` path: `git worktree add <scratch> <base-sha>`, then `git -C <scratch> checkout <head-sha> -- <test-paths>` to apply only the test file(s) from the diff (not the fix), run the same command inside `<scratch>`, confirm it fails for the reason the scenario describes, then `git worktree remove --force <scratch>`. Do not check out the pre-fix base or stash/revert the fix in place in the tree you are reviewing from - that mutates a working tree the Skeptic does not own and, when the test shipped in the same commit, also removes the test, producing a collection/import/file-not-found error that is NOT a pre-fix failure. Only when pre-fix execution is genuinely not possible (no Bash access in this review context, missing infra, an external dependency the review environment cannot reach, or reverting the fix is impractical) does the Skeptic rely on attestation alone for (a).

**Verification scope (post-execution-attempt):** the Skeptic's obligation is, in order: (1) attempt to execute the test against the post-fix code and report the raw result; (2) where feasible, also execute it against the pre-fix code to independently confirm the failure - see (b) above; (3) if pre-fix execution was not performed, fall back to the engineer's attestation - see (a) above; (4) if NEITHER (a) nor (b) holds, distinguish two cases: (4a) no genuine attempt was made - the engineer gave no pre-fix attestation and the Skeptic did not attempt to execute the test against the pre-fix code at all - raise a **Major** finding: `Regression test unverified for QA scenario [id: title] - neither the engineer's attestation nor the Skeptic's own execution confirms the test fails against the unfixed code; an unverified regression test provides no more assurance than no test at all.`; (4b) a genuine attempt at (b) was made but was infeasible - the Skeptic attempted the pre-fix-execution procedure above (created the scratch worktree at the pre-fix base, applied only the test file(s), attempted to run) and it was genuinely not possible (missing infra, an external dependency the review environment cannot reach, or reverting the fix is impractical) - do not block; paste the attempted command and its actual error output and raise a **Minor** finding instead: `Regression test unverified for QA scenario [id: title] - the engineer gave no pre-fix attestation and pre-fix execution was attempted but not possible in this review environment ([reason]); relying on post-fix execution alone. Attempted: [command]. Error: [pasted error output].` This Minor does not block sign-off but must always be listed. (No-Bash-access falls under case (4a) above, not here - without Bash there is no command to attempt and no error output to paste, so it cannot satisfy this case's own precondition.); (5) if (a) holds but (b) was not performed, do not settle for a prose excuse - paste the attempted command and its actual error output alongside the stated reason, then raise a **Minor** finding instead: `Regression test attestation unverified by execution for QA scenario [id: title] - execution against the pre-fix code was not possible in this review environment ([reason]). Attempted: [command]. Error: [pasted error output]; relying on engineer self-report.` This Minor does not block sign-off but must always be listed; (6) regardless of the above, spot-check the test's target and the engineer's `raw_output` for fabricated evidence (a named test file/function that does not exist in the diff or repository) - fabrication is a **Critical** finding, not a Minor one, per `content/agents/skeptic.md` Step 12's `raw_output` spot-check.

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
