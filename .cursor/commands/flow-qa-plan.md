# /flow-qa-plan - Generate Manual QA Test Plan from Implementation

Generate a structured manual QA test plan from implemented code. The user provides `$ARGUMENTS` describing the scope - a branch name, commit range, plan doc path, ticket reference file, list of ticket IDs, or a feature description. The output is a markdown document that human testers can follow without codebase familiarity.

This command produces a document, not executable tests. It covers happy paths, error paths, edge cases, and cross-cutting concerns.

## Your job (main agent)

You are the conductor. You never write the test plan directly. You assemble context, decompose implementation areas, and delegate discovery, synthesis, and review to Worker and Skeptic subagents.

Tell the user: "Starting flow-qa-plan for: $ARGUMENTS. I'll analyze the implementation, discover testable behaviors, and generate a structured QA test plan."

---

## Phase 0 - Initialization

### Step 0.1 - Parse the scope

Read `$ARGUMENTS`. Determine the scope of work:

- **Branch/commit range:** Run `git diff` and `git log` to identify changed files and commits.
- **Plan doc path:** Read the plan document to understand intended behavior.
- **Ticket reference file:** Read the file and fetch ticket details.
- **Ticket IDs:** Fetch ticket details from the tracker.
- **Feature description:** Use it as-is to guide file discovery.

Read the changed/relevant files. Build a list of functional areas (e.g., "API endpoints", "UI components", "CI pipeline", "data storage", "worker jobs").

### Step 0.2 - Confirm with the user

Present:
- The functional areas discovered and what each covers
- Suggested output path (default: `docs/qa/[feature]-test-plan.md`)
- Ask: "Where should I write the test plan? Should I adjust the scope?"

Wait for user confirmation before proceeding. The user may add, remove, or rename areas.

If `$ARGUMENTS` is empty or ambiguous, ask the user to clarify before proceeding.

### Step 0.3 - Start tracking

Create a TodoWrite with entries for each functional area's discovery, plus Synthesis, Review, and Write. Mark them `pending`.

---

## Phase 1 - Discovery

For each functional area, spawn a **background general-purpose Task** (`run_in_background: true`) with this prompt:

---
You are a Worker agent. Analyze the implementation code for the area described below and extract every testable behavior. Return structured findings only - do not write test plan prose.

**Area:** [area name and description]

**Files to read:** [list of file paths in this area]

**Context:** [paste relevant CLAUDE.md sections, AGENTS.md, project conventions]

Read every file listed. For each file, extract:
- **Happy path behaviors:** What the code does when inputs are valid and systems are healthy.
- **Error path behaviors:** What happens with invalid inputs, missing data, network failures, permission errors.
- **Edge cases:** Boundary values, empty collections, concurrent access, large payloads, special characters.
- **Preconditions:** What must be true before the behavior can be tested (auth state, data in DB, feature flags, environment variables).
- **Dependencies:** External services, databases, other components that must be running or mocked.
- **Cross-cutting concerns:** Auth/CORS/caching/rate-limiting that affects this area.

Return your findings as a structured list grouped by file, with each behavior tagged as happy/error/edge. Include the source file and approximate line range for traceability.
---

Wait for all discovery Workers to return before proceeding.

---

## Phase 2 - Synthesis

Spawn a single **background general-purpose Task** (`run_in_background: true`) with this prompt:

---
You are a Worker agent. Synthesize the discovery findings below into a structured manual QA test plan document. Return the complete markdown document.

**Feature:** [feature name/description]

**Branch:** [branch name if applicable]

**Discovery findings:**
[paste all discovery Worker outputs]

Write the test plan using this exact format:

```
# [Feature] - Manual QA Test Plan
*Generated: YYYY-MM-DD | Branch: [branch] | Scope: [description]*

## Prerequisites
[Environment setup, test data, tools needed, services that must be running]

## Test Areas

### [Area Name] (e.g., "Performance Query API")

#### [TC-NNN]: [Test Name]
- **Priority:** P0/P1/P2
- **Preconditions:** [what must be true before testing]
- **Steps:**
  1. [specific action with exact values, URLs, or commands]
  2. [specific action]
- **Expected Result:** [precise observable outcome - what to see, what status code, what data]
- **Notes:** [edge cases, gotchas, related tickets]

## Cross-Cutting Concerns
[Tests that span multiple areas - CORS, auth, error handling patterns]

## Environment Matrix
[If applicable - browsers, devices, network conditions to test across]

## Known Limitations
[Things that cannot be tested manually, deferred scope, assumptions]
```

Rules for the test plan:
- Use sequential test case IDs: TC-001, TC-002, etc.
- Priority: P0 = blocks release, P1 = should test before release, P2 = nice to verify
- Steps must be specific enough for a tester unfamiliar with the codebase
- Expected results must be precise enough to distinguish pass from fail
- Every endpoint/component/feature needs at least one happy path AND one error/edge case
- Preconditions must include exact setup steps, not vague references
- Do NOT use em dashes anywhere - use regular hyphens instead
---

Wait for the synthesis Worker to return.

---

## Phase 3 - Review

Spawn a **fresh background general-purpose Task** (`run_in_background: true`) as Skeptic with:

- The complete synthesized test plan
- The discovery findings for cross-reference
- The implementation file paths for verification
- This adversarial brief verbatim:

> "Is this test plan complete? For each endpoint, component, and feature in the implementation: is there at least one test case that exercises the happy path, and at least one that exercises error/edge behavior? Are preconditions specific enough that a tester unfamiliar with the codebase can set up the test? Are expected results precise enough to distinguish pass from fail? Are there any behaviors in the code that are not covered by any test case? Check for: missing error path coverage, untested filter combinations, missing cross-origin/auth scenarios, and any assumption about test data that is not documented in prerequisites."

- The resolved issues preflight list:
  - Round 1: "No prior rounds. This is round 1."
  - Rounds 2+: "The following issues were identified and resolved in prior rounds. Do not re-raise them unless you believe the resolution is genuinely insufficient: [list each resolved finding as: C1/M1/etc: description - resolution applied]"
- These instructions verbatim:

> "Classify all findings as Critical, Major, or Minor. Grant sign-off only when there are no unresolved Critical or Major findings. Before granting sign-off, include in your response the line: 'Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.' Do not grant sign-off without this statement. Use the required sign-off format:
>
> Reviewed: [list of components/aspects examined]
> Findings: Critical: N, Major: N, Minor: N - or 'No findings.'
> [List any findings with classification]
> Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.
> No unresolved Critical or Major findings. Sign-off granted."

The Skeptic is always a fresh spawn - never resumed from a prior round.

### Read findings

A valid sign-off contains all four mandatory elements:
- (a) a line beginning "Reviewed:"
- (b) a line beginning "Findings:"
- (c) an "Active search:" line
- (d) the exact phrase "No unresolved Critical or Major findings. Sign-off granted."

If any element is missing: spawn a new Skeptic with explicit format instructions. Limit: 3 format re-invocations.

If sign-off is achieved: proceed to Phase 4 (Write).

If Critical or Major findings remain: spawn a new **background general-purpose Task** (`run_in_background: true`) Worker to revise the test plan with the findings. Provide the current test plan, the findings verbatim, and the discovery data. Update the resolved issues preflight list with each addressed finding and its resolution. Then return to Review with the revised plan and a fresh Skeptic.

**Escalation:** After the same finding is contested for 2 or more re-routes, stop and escalate to the human.

---

## Phase 4 - Write

After clean sign-off, write the signed-off test plan verbatim to the agreed output path using the Write tool. This is a mechanical operation - no Worker needed.

Mark the Write step as `completed` in TodoWrite.

Report completion to the user with:
- Output file path
- Number of test areas covered
- Number of test cases by priority (P0/P1/P2)
- Any known limitations or deferred scope

---

## Notes

- The main agent is the sole orchestrator. It delegates discovery, synthesis, and review to Workers/Skeptics. The final Write is direct (mechanical file write).
- Workers are always `general-purpose` type, always `run_in_background: true`.
- Skeptics are always fresh spawns - never resumed, never continued from a prior round.
- The adversarial brief is passed to the Skeptic verbatim - never softened or summarized.
- This command makes no assumptions about project structure, toolchain, or ticket system.
- Priority classification: P0 = blocks release, P1 = should test before release, P2 = nice to verify.
- When this command is active, the main agent's normal risk classification and Skeptic Protocol rules are suspended. The command's own review loop (Discovery - Synthesis - Review with fresh Skeptic - Fix - Write) provides equivalent rigor.
- Do NOT use em dashes anywhere in generated content - use regular hyphens instead.
