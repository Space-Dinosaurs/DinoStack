> **Prerequisite:** If the /engineering skill has not been loaded in this session, invoke it first before proceeding.

# /flow-dev - Sequential Plan/Work/Review Pipeline

Execute ordered, dependent work where coherence across steps matters more than speed. The user provides `$ARGUMENTS` describing the work - a plan doc path, a list of steps, a single feature description, or a reference to tickets in a tracker.

All work stays on the current branch. Each step produces an atomic commit. Steps execute sequentially so each step's plan is informed by the actual output of prior steps.

## Your job (main agent)

You are the conductor. You never implement or plan directly. For every step, you assemble context and spawn a planning Worker to write the implementation spec, then an implementation Worker to build it, then a Skeptic to review it.

Tell the user: "Starting flow-dev for: $ARGUMENTS. I'll decompose the work, confirm the steps with you, and then execute the full pipeline."

---

## Phase 0 - Initialization

### Step 0.1 - Parse the work

Read `$ARGUMENTS`. If it references a file path, read the file. If it references tickets, read the ticket details. Decompose the work into ordered steps with dependency relationships.

Each step needs:
- A short name (used in commit messages and progress tracking)
- A description of what the step accomplishes
- Its dependencies (which prior steps must complete first)
- The type of work (used to select the adversarial brief later)

### Step 0.2 - Identify phases

Group steps into phases based on dependencies. Steps within the same phase share no inter-dependencies but depend on prior phases. Execution is still sequential within a phase. After Phase 1 completes, the main agent spawns a Worker to create a living spec doc that provides accumulated context for all subsequent planning Workers.

### Step 0.3 - Confirm with the user

Present the decomposed steps and phases to the user. Include:
- The ordered step list with names and descriptions
- Phase groupings
- The branch the work will happen on (current branch)
- Ask: "What command should I run as a quality check after each step? This should be a fast check (lint, typecheck, unit tests) - not a long-running integration or end-to-end test. (e.g. `npm run lint`, `make check`, `cargo clippy`). Enter 'none' to skip."

Wait for user confirmation before proceeding. The user may reorder, add, remove, or modify steps.

### Resume protocol

If picking up a /flow-dev pipeline mid-execution in a new session (e.g. after context ran out): re-confirm the quality check command with the user before continuing. Do not inherit whatever command was set in the prior session without asking. State clearly which step you are resuming from.

### Step 0.4 - Start tracking

Create a TodoWrite with all steps in `pending` state.

---

## Step Execution Loop

For every step in every phase, run this loop. After all Phase 1 steps complete, proceed to Spec Doc Creation before starting Phase 2.

### 1. Plan

Mark the step as `in_progress` in TodoWrite.

Assemble context for the planning Worker, then spawn a **background general-purpose Task** (`run_in_background: true`) with this prompt:

---
You are a Worker agent. Write a detailed implementation spec for the step described below. Do not implement anything. Return only the spec. If existing plans, specs, or ticket details are provided in the context, use them as your starting point. Review and refine them into an actionable implementation spec rather than writing from scratch. Flag any gaps or inconsistencies you find in the existing plans.

**Step:** [step name and description]

**Context dump:**
[Assembled by the main agent - see below for what to include]

**Prior step output (most recent):** [summary of what the last step produced - file paths, interfaces, patterns. "None - this is the first step." if no prior steps]

**Relevant file paths to read:** [list files the planning Worker should read for context]

Write an implementation spec containing:
- Exact file paths to create or modify
- Interface shapes and type signatures (if applicable)
- Naming conventions to follow (must be consistent with any established conventions)
- Acceptance criteria - what "done" looks like
- Quality check command: [command from Step 0.3, or "none"]
- Any conventions from prior steps that must be maintained

Read the files listed above before writing the spec. Return the complete spec.
---

**What to include in the context dump:**

- **Before the spec doc exists (Phase 1):** Read the project's CLAUDE.md, relevant AGENTS.md files, existing code in the areas the step will touch, and any project conventions. Include all of this in the context dump. The richer context compensates for the absence of a spec doc.
- **After the spec doc exists (Phase 2+):** Paste the living spec doc content. Add targeted file reads only for areas the step will touch that aren't already covered by the spec doc.

When the planning Worker returns, review the spec briefly for coherence with prior steps. If it contradicts established conventions, note the conflict and either fix the spec yourself (if the fix is obvious) or spawn a new planning Worker with the correction.

### 2. Work

Spawn a **background general-purpose Task** (`run_in_background: true`) with this prompt:

---
You are a Worker agent. Implement the task fully and return your complete output. The main agent will arrange Skeptic review.

**Step:** [step name]

**Implementation spec:**
[paste the complete implementation spec from the Plan phase]

**Context:**
[paste relevant CLAUDE.md sections, project conventions, and any project-specific instructions]

**Session context:**
[paste the content of `~/.claude/projects/[hash]/context.md`]

The adversarial brief below will be used by the Skeptic reviewing your output. Write your implementation knowing you will be evaluated against it.

**Adversarial brief:** [select from the adversarial brief selection table below based on the step's work type]

Implement the spec fully. If the spec includes a quality check command, run it after implementation and fix any failures. Return your complete output including: files created/modified, quality check results, and anything the next step needs to know.
---

### 3. Review

When the Worker returns, spawn a **fresh background general-purpose Task** (`run_in_background: true`) with:

- The Worker's complete output
- The implementation spec the Worker was given
- The adversarial brief verbatim (selected from the table below based on the step's work type)
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

The Skeptic is always a fresh spawn - never resumed, never continued from a prior round.

### 4. Read findings

A valid sign-off contains all four mandatory elements as distinct lines:
- (a) a line beginning "Reviewed:"
- (b) a line beginning "Findings:"
- (c) an "Active search:" line
- (d) the exact phrase "No unresolved Critical or Major findings. Sign-off granted."

If any element is missing: spawn a new Skeptic with explicit format instructions. This format re-invocation is not counted as a new adversarial round. Limit: 3 format re-invocations. If still noncompliant after 3, escalate to the human.

If sign-off is achieved: proceed to step 5 (Commit).

If Critical or Major findings remain: proceed to step 4a (Fix).

### 4a. Fix

Spawn a **background general-purpose Task** (`run_in_background: true`) with:

---
You are a Worker agent. Address the Skeptic findings below and return your revised output.

**Step:** [step name]

**Implementation spec:** [paste spec]

**Skeptic findings:**
[paste findings verbatim]

**Prior output:**
[paste prior Worker output or file paths]

For each Critical or Major finding: fix it, or document a specific reason why it is not a real problem. If the spec includes a quality check command, re-run it after fixes. Return your revised complete output.
---

Update the resolved issues preflight list with each addressed finding and its resolution.

Return to step 3 (Review) with the revised output.

**Escalation:** After the same finding is contested for 2 or more re-routes without resolution, stop. Escalate to the human with the full exchange, the contested findings, and both Worker and Skeptic positions.

### 5. Commit

After clean sign-off, commit with an atomic, descriptive message. Format:

```
[step-name] description of what changed
```

Stage specific files by name (never `git add -A` or `git add .`). Do not push.

### 6. Update tracking and spec

Mark the step as `completed` in TodoWrite.

**If this is the last step of Phase 1:** proceed to Spec Doc Creation before starting Phase 2.

**If Phase 2+ and the living spec doc exists:** spawn a **background general-purpose Task** (`run_in_background: true`) Worker to update `.flow-dev-context.md` with any new conventions, interface shapes, file paths, or naming patterns established by this step. Provide the Worker with the current spec doc content and a summary of what the step produced. Keep the doc concise - conventions and interfaces, not full code.

---

## Spec Doc Creation

After all Phase 1 steps complete, assemble a summary of the conventions, interfaces, file paths, and decisions established during Phase 1. Then spawn a **background general-purpose Task** (`run_in_background: true`) Worker to create the living spec doc at `.flow-dev-context.md` in the project root. This file is temporary and should be gitignored.

Provide the Worker with the assembled summary and instruct it to write a spec doc capturing:
- Conventions established so far (naming, file organization, patterns)
- Interface shapes and type signatures created
- Key file paths created or modified
- Decisions made during Phase 1 that affect subsequent steps
- Quality check command being used

Keep it concise. This is a reference for planning Workers, not a full code dump.

For all subsequent phases, the planning Worker receives this spec doc as its primary context instead of the richer codebase reads used in Phase 1.

---

## Completion

After all steps across all phases complete:

1. Summarize to the user:
   - What was done (one line per step)
   - How many commits were created
   - Any Skeptic findings that were addressed (and how)
   - Any escalations that occurred and their resolutions

2. Ask the user: "Should I clean up `.flow-dev-context.md` or leave it for reference?"

3. If the user wants cleanup, delete the file. Otherwise leave it.

---

## Adversarial brief selection

Pick the single best match for each step based on its work type. If multiple apply, use the first match.

| Work type | Use this brief |
|---|---|
| Smart contracts, on-chain logic | "A financially motivated attacker has the source code and will look for: reentrancy, access control gaps, signature replay attacks, fee bypass, and any path to transfer an asset without valid authorization. Assume the attacker will read every public function, every state variable, and every event. Assume they will attempt direct contract interaction, bypassing any app-layer controls." |
| Auth, sessions, tokens, middleware | "An attacker controls one compromised account and one compromised device. What can they access, modify, or forge? Look for: session fixation, token replay, insufficient binding between session and device, privilege escalation paths, and any state the server trusts without re-verifying." |
| API endpoints, HTTP handlers | "An attacker can send arbitrary HTTP requests including malformed inputs, missing fields, oversized payloads, replayed tokens, and concurrent requests designed to hit race conditions. Look for: missing input validation, authentication that can be bypassed, rate limiting gaps, and any endpoint that mutates state without idempotency guarantees." |
| Cryptographic ops, signature verification | "An attacker will try to produce a valid-looking signature without the private key. They will also try replay attacks with previously valid signatures. Look for: weak randomness in nonce generation, missing domain separation, algorithm confusion attacks, and any verification path that skips a check under certain conditions." |
| DB schema, migrations, data models | "Is the migration idempotent - what happens if it runs twice? What is the state of the data after partial failure, and can it be recovered without data corruption? Look for: double-run risk (non-idempotent operations), partial failure paths (what if the migration fails halfway?), data loss risk (irreversible column drops, non-nullable additions to tables with existing data), and rollback path (is there a down migration, and is it tested?)." |
| Async jobs, data pipelines, queues | "What happens if this job runs twice? What happens if it crashes halfway? What is the state after partial failure, and can it be safely retried without double-processing or data corruption? Look for: non-idempotent operations, missing rollback logic, state that can diverge between systems, and silent failure modes." |
| Document synthesis, architecture, planning | "Check for internal consistency: does the document contradict itself, and are conclusions supported by the reasoning given? Surface assumptions: what is stated as fact but is actually assumed, and what would break if those assumptions are wrong? Check for prior decision conflicts: does this contradict established decisions or architectural constraints? Identify completeness gaps: what important questions does this document fail to answer, and what edge cases does it not address? Evaluate readability for the intended audience: would the engineer who needs to act on this have enough information to do so correctly and without guessing?" |
| All other tasks | "Assume this code will be deployed to production and maintained by engineers who did not write it. Find: logic errors, edge cases that cause silent failures, missing error handling, incorrect assumptions about input ranges or ordering, and any assumption that will break under realistic load or adversarial input." |

---

## Notes

- The main agent is the sole orchestrator. It never implements or plans directly - it assembles context and delegates to Worker and Skeptic subagents (planning Workers write specs, implementation Workers build code).
- Workers are always `general-purpose` type, always `run_in_background: true`.
- Skeptics are always fresh spawns - never resumed, never continued from a prior round.
- The adversarial brief is passed to the Skeptic verbatim - never softened or summarized.
- The living spec doc is a working artifact, not a deliverable. Keep it concise.
- If the quality check command fails after a Worker's implementation, the Worker should fix it before returning. If the Worker cannot fix it, it returns the failure details and the main agent escalates to the human.
- This skill makes no assumptions about toolchain, ticket system, branch strategy, or project structure. It works with whatever the project uses.
- When this skill is active, the main agent's normal risk classification and Skeptic Protocol rules are suspended for the duration of the /flow-dev execution. The skill's own per-step review loop (Plan - Work - Review with fresh Skeptic - Fix - Commit) provides equivalent rigor, so applying the Skeptic Protocol on top would be redundant double review.
