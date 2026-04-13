# The Finding → Eval Flywheel

## Overview

Every Critical or Major Skeptic finding that gets fixed is a latent regression. Without a test, the same bug can silently reappear in a future change. Without a record, the same pattern of mistake repeats across future tasks with no signal that the pattern was already encountered. The flywheel closes both loops:

1. **Per-finding regression test** — when a finding is fixed, the Worker proposes a test that would have caught it. Skeptic verifies the test exists before granting sign-off.
2. **Pattern promotion** — recurring finding categories are persisted to `.claude/findings.md`. Architect reads this file at plan time so prior lessons shape future plans.

These are two distinct mechanisms with different scopes: the regression test is code-level (lives in the test suite, catches the specific failure mode); the pattern entry is session-level (lives in a project file, informs future planning).

---

## Part 1: Per-Finding Regression Test

### Worker obligation

When a Worker fixes a Critical or Major Skeptic finding, it must:

1. Implement the fix.
2. Add a regression test — a test case (unit, integration, or eval) that would have **failed** without the fix and **passes** with it. The test lives in the project's normal test suite, alongside existing tests for the affected module.
3. Reference the test in the fix summary: `C1 (finding title) → fixed by [description]. Regression test added: [test file path, test name/description].`

If adding a regression test is genuinely not possible (e.g., the project has no test infrastructure, or the failure mode is a documentation error with no executable path), the Worker must state this explicitly with a reason. A missing test without explanation is a Major finding in the next Skeptic round.

### Skeptic verification

Before granting sign-off on a round where a Critical or Major finding was fixed:

- Verify a regression test was added (or a documented exception was given).
- Spot-check that the test actually targets the failure mode described in the finding — not a superficial test that happens to pass.
- If the test is absent without explanation, raise it as a **Major** finding: `Missing regression test for [finding title] — a test that would have caught this failure mode is required before sign-off.`
- **Verification scope:** Skeptic cannot independently verify that the test fails on the unfixed code. Its obligation is to verify the test targets the correct failure mode and that the Worker's summary explicitly attests to having run the test against the unfixed code first. A Worker summary that does not include this attestation is insufficient - the Skeptic should treat the absence as though no confirmation was given.

### What counts as a regression test

The bar is correctness coverage of the failure mode, not test framework formality:

- **Code bugs:** a unit or integration test that exercises the specific input or state that triggered the bug.
- **Logic errors:** a test that exercises the branch, edge case, or ordering assumption that was wrong.
- **Missing validation:** a test that provides invalid input and asserts the correct rejection behavior.
- **Prompt / eval failures (LLM projects):** an eval case that demonstrates the model output failure mode, runnable via the project's eval harness.

A test that passes even without the fix does not count. The Worker should confirm (in its summary) that it verified the test fails on the unfixed code.

---

## Part 2: Pattern Promotion to `.claude/findings.md`

### What `.claude/findings.md` is

A project-level file that accumulates finding patterns. It is not a log of every finding — it is a curated set of recurring or high-impact patterns that should shape future work. The file lives at `.claude/findings.md` alongside `.claude/qa.md` and `.claude/work-tracking.md`.

Entries are short. A single entry answers: what is the pattern, where does it tend to appear, and how should it be avoided going forward.

### Entry format

```
## [Category name]

**Pattern:** [One sentence describing the recurring failure mode]
**Where it bites:** [The type of code, phase, or scenario where this shows up]
**How to avoid:** [Concrete guidance for the Architect or Worker — specific enough to act on]
**Example:** [Link to PR or commit, or brief description of the canonical instance — optional]
```

Example:

```
## Missing idempotency in async job handlers

**Pattern:** Job handlers that mutate external state (database writes, API calls) without
checking whether the operation already completed, causing double-processing on retry.
**Where it bites:** Any background job or webhook handler that can be retried by the queue
or caller on failure.
**How to avoid:** Architect plan must include an idempotency key or check-before-write step
for any handler that produces external side effects. Skeptic brief should include the
data-pipelines template.
**Example:** PR #47 — charge duplication on payment webhook retry
```

### When to promote

The conductor (or the main agent in the `/implement-ticket` flow) checks after Skeptic sign-off whether any Major or Critical finding from the just-completed task warrants a `.claude/findings.md` entry.

**Promote if any of the following are true:**

- The same finding category has appeared in 2 or more prior tasks in this project (pattern confirmed).
- The finding has outsized blast radius: a class of bug that, if repeated, would be expensive or dangerous (data loss, security, production outages).
- The finding is novel but represents a recurring failure mode in systems like this one (e.g., the first time idempotency was missed in a job handler in a project that will have many job handlers).

**Do not promote:**

- One-off typos, style issues, or minor naming problems.
- Findings that are already covered by an existing entry (update the existing entry instead of duplicating).
- Every finding from every PR — the file should remain scannable, not a dump.

### File size and pruning

Target under 15 entries. The file must remain scannable - Architect reads it unconditionally on every plan, so unbounded growth inflates every spawn on long-running projects. When adding a new entry would push the file past 15 entries, the conductor (promote step) is responsible for consolidating entries that describe the same underlying failure mode, or retiring entries that no longer apply to the current shape of the codebase.

### Who reads `.claude/findings.md`

- **Architect (required):** at plan time, read `.claude/findings.md` if it exists. Cite any entries that apply to the current task in the plan's "Trade-offs and constraints" or "Known limitations" section. A plan that ignores an applicable findings entry is incomplete.
- **Skeptic (required):** at review time, treat `.claude/findings.md` entries as known anti-patterns. If the Worker's implementation repeats a pattern documented in findings, raise it as a **Major** finding — `Repeats documented pattern from .claude/findings.md: [category name].`
- **Worker (optional):** may read findings for context when implementing a task where the Architect has cited relevant entries.

### Who writes `.claude/findings.md`

The conductor (main agent) is responsible for the promote step after any Skeptic sign-off - in `/implement-ticket` (Phase 6c), in `/wrap` (Part D), and in any ad-hoc Worker+Skeptic cycle. The promote step is defined in `agent-methodology.md` §Post-sign-off finding promotion. The conductor:

1. Reads the Skeptic's findings from the just-completed task.
2. Applies the promotion criteria above.
3. If promotion is warranted: reads the current `.claude/findings.md` (or creates it if absent), adds or updates the relevant entry, and confirms the write.
4. Keeps the step lightweight — the file must not become a bureaucratic artifact. A promote step that takes more effort than the task itself is miscalibrated.

---

## Summary: The Two Loops

| Loop | Trigger | Actor | Output | Lives in |
|---|---|---|---|---|
| Regression test | Critical/Major finding fixed | Worker + Skeptic verification | Test case that catches the failure mode | Project test suite |
| Pattern promotion | Sign-off granted on task with Major+ finding | Conductor | Entry in `.claude/findings.md` | `.claude/findings.md` |
