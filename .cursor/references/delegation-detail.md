<!--
Purpose: Detailed delegation-model reference blocks extracted from
         content/sections/02-delegation.md. Contains: Open Questions /
         Deferred Defaults bucketing rules + table + worked example; Worker
         autonomy contract + agent-spec exception; Stop-frequency planning
         signal + table; Common rationalizations to reject; Investigator-
         before-Architect rules (incl shared-utility-MANDATORY + Parallel
         Investigators); Learnings pipeline; Worker preamble + execution
         contract template; Digest-return discipline.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/02-delegation.md (inline pointers replacing
            each verbose block).

Upstream deps: content/sections/02-delegation.md (parent section; read
               that section first for the full delegation model overview,
               spawn threshold rules, and signal table).

Downstream consumers: conductor (Worker preamble and execution-contract
                      template); content/sections/12-protocol-details.md
                      (Delegation Protocol Details entry); any agent that
                      authors a Brief or Plan (Open Questions / Deferred
                      defaults bucketing).

Failure modes: Prose reference; does not auto-execute. Stale content
               (divergence from parent section) is the primary risk - the
               parent section is authoritative and this file is a copy.

Performance: Standard.
-->

> Parent section: `content/sections/02-delegation.md`. Read that section first for the full delegation model, spawn threshold, and signal table.

## Open Questions and Deferred Defaults

**Exception (Open Questions) and Deferred defaults.** Artifacts produced by the architect (and by the conductor when it authors a Brief, Plan, or ADR) use two distinct sections with different semantics. Categorization is set at authoring time, not changed by the conductor at gate time.

Use this table to bucket each parked choice:

| Condition | Section |
|---|---|
| No derivable default OR irreversible OR load-bearing fork | **Open Questions** |
| Reversible AND a default is derivable AND not a load-bearing fork | **Deferred defaults** |

**Open Questions** items are a protocol-level blocker and are NOT resolvable by this protocol. Resolution paths: (a) re-spawn the architect to resolve or re-categorize, (b) ask the user the specific question directly, or (c) descope. Conductor-derived defaults do not close an Open Question.

**Deferred defaults** items are reversible choices the author has already derived a default for. The author records each item with its derived default under a "Deferred defaults" subsection, noting "revisit at implementation if context changes." The conductor does not stop, does not ask the operator, and does not spawn any resolution agent for these items - it proceeds with the recorded defaults.

The author derives the default first. If a default is derivable and the choice is reversible, it is authored as a Deferred default - the conductor never has to be asked. Only non-defaultable, irreversible, or load-bearing-fork items become Open Questions. When the conductor receives a plan whose "Open Questions" section contains an item that appears reversible or defaultable (a mis-bucketing), the correction path is to re-spawn the architect, not for the conductor to self-rebucket.

**Worked example.** ADR-0008 (cloud multi-device, Proposed) ends with 8 parked choices, each with a conductor-derived recommendation, each reversible (a Proposed ADR commits no code), with no downstream worker pending. The ADR author lists all 8 under a "Default decisions (reversible; revisit at implementation)" subsection - the "Deferred defaults" analogue - records each derived default inline, and proceeds. None of the 8 ever enter the "Open Questions" section. The conductor is never gated. No ballot is presented to the operator.

## Worker Autonomy Contract

**Worker autonomy contract.** Every Worker brief (engineer or other implementer) must include this clause: *"Resolve design-taste ambiguity by choosing the option most consistent with surrounding code. Return BLOCKED only for hard blockers: permission denial, missing credential, irreversible destructive action without authorization, or fundamental scope conflict. Do not return BLOCKED for style, naming, choice among libraries already in use in this project, or 'which of several reasonable approaches' questions - pick one, proceed, and note the choice in the return summary. Introducing a new runtime dependency or performing a major-version upgrade of an existing dependency is NOT within this contract - if the task requires either, return BLOCKED so the conductor can route through architect + dependency-auditor per the risk table."*

**Exception (agent-spec-mandated human decisions).** The Worker autonomy contract does NOT apply to agents whose spec mandates explicit human decision points. When the agent's own spec mandates surfacing a decision to the human (e.g. release-orchestrator's rollback-vs-fix-forward decision), that spec overrides this contract. The Worker follows its spec and surfaces the decision as instructed.

## Stop-Frequency as Planning Signal

**Stop-frequency is a planning signal.** Repeated genuine blockers within a single task indicate the plan is under-specified, not that the conductor is being appropriately cautious. Continuing to ask piecemeal questions papers over the structural gap and burns operator attention. Track stops against task complexity:

| Task shape | Max genuine stops before flagging the plan |
|---|---|
| Trivial or single-unit | 0 - one blocker means it was not well-scoped |
| Single-unit Elevated | 1 |
| Multi-unit plan (2-5 units) | 2 across the whole plan |
| Large multi-unit plan (6+ units) | 3 across the whole plan |

**Pre-architect planning-input scans are exempt from this budget.** The Phase 2b ambiguity scan in `/implement-ticket` surfaces clarifying questions before any agent is spawned — no architect, investigator, or engineer has run yet. This is structurally different from a mid-work stop: it is bounded to exactly one operator turn, has a proceed-with-defaults fallback, and produces no work that needs to be discarded if the operator redirects. Phase 2b does not count against the per-task stop budget for any task shape.

When the threshold is exceeded, the conductor stops spawning Workers and surfaces a planning concern to the user instead of another piecemeal question. Format:

*"I've hit N blockers on this task: [bullet list of each blocker and why]. This is past the threshold for a [task shape] task and suggests the plan needs revisiting before we continue. Options: (a) re-spawn architect with these gaps, (b) answer the genuine Open Questions upfront and resume (Deferred defaults in the plan do not count toward this budget and do not block), or (c) descope. Recommendation: [pick one]."*

Then wait. Do NOT keep spawning Workers against an under-specified plan - that compounds the cost of the missing planning work and produces churn the user has to clean up later.

## Common Rationalizations to Reject

**Common rationalizations to reject:**

- "Looks simple" - not a Low signal
- "Following the spirit, not the letter" - violating the letter is violating the spirit
- "Only one file / few lines" - line count is not a risk signal
- "I already reviewed it myself" - self-review is for Low risk only
- "Moving fast, can skip this once" - speed is not a Low signal
- "The Skeptic will catch any mistakes" - the Skeptic reviews Worker output; it does not excuse skipping risk classification or spawning a Worker
- "This change is too minor to bother with a Worker" - delegate on risk signals, not on size; the Worker overhead is small, the cost of an unreviewed error is not
- "I can figure out the task structure / parallelization myself" or "this is obviously a single-unit task" - conductor does not self-assess task structure, unit count, or parallelization; delegate that reasoning to the orchestration-planner; the only valid skip is when a preceding agent has already returned a single atomic unit
- "The change is obviously fine and a Skeptic would just rubber-stamp it" - that gut feel is itself a **cognitive-surrender flag**, not a green light. The instinct that review is unnecessary is precisely when independent review is most valuable. Reclassify as Elevated and spawn the Skeptic anyway.
- "I have subagent output in hand, so writing from it is just synthesizing results" - synthesis means aggregating what agents returned into a conductor update, not authoring a new document, specification, plan, or recommendation. The moment the output is a new artifact, it is "Document synthesis" (Elevated) regardless of whether the inputs came from subagents.

## Investigator-Before-Architect Rules

**Investigator-before-Architect for unfamiliar territory.** When the task touches a codebase area the main session has not recently investigated - i.e., the "Unfamiliar codebase area" Elevated signal is present - the conductor must spawn the `investigator` agent first and pass its brief as input to the `architect` agent. The Architect consumes "what exists" from the Investigator and produces "what to build". This separates concerns: the Investigator maps the terrain and blast radius, the Architect makes design decisions on top of that map. The only exception is when the relevant files have been Read within the current conversation AND no substantive changes have been made to those files since they were read - i.e., the conductor has the current file contents in context as a direct tool-result, not a summary or recollection. "Relevant files" means the specific files the Architect would need to reason about the change, not the directory or the project generally. If this test is not met in full, spawn the Investigator - "I know this area" is not a valid skip reason, and neither is "I read something nearby". When in doubt, spawn the Investigator.

**Investigator-before-Architect MANDATORY for shared-utility surfaces.** The "in-context file already read" exception above does NOT apply when the ticket's likely target is a shared utility, shared component, or shared type. Specifically: when the target file lives under `packages/<shared>/`, `lib/shared/`, `src/shared/`, or any analogous shared-module directory convention used by the project, AND `grep`/`Glob` reveals 5 or more importers of the symbol(s) being changed, the Investigator step is mandatory regardless of whether the conductor has the file contents in context. The Investigator's output for this case MUST include a per-consumer impact table (see `content/agents/architect.md` "Per-consumer impact table" requirement) that the Architect then consumes verbatim. The conductor cannot skip the Investigator on shared-utility surfaces by self-assessing "I already know what this does" - in-context familiarity with the shared file itself does NOT imply familiarity with every call site. The 5-importer threshold is a mechanical signal: count importers with `grep -rn` before deciding; do not estimate. If the count is uncertain, default to spawning the Investigator (when in doubt, spawn).

**Parallel Investigators feeding a single Architect.** When investigation spans multiple independent surfaces (e.g. backend, frontend, schema), the conductor MAY spawn multiple Investigators in a single message. Before doing so, Read `content/references/conductor-operating-rules.md` §Parallel Investigators for the merge-into-one-Architect rule and the single-Architect invariant.

## Learnings Pipeline

**Learnings pipeline (two feeders, distinct triggers).** The learnings pipeline has two separate feeders with different trigger mechanisms:

- **`learning-extractor`** - mechanically wired to `/implement-ticket` Phase 6 clean exit. Fires automatically on every ticketed Skeptic loop completion. The conductor does NOT spawn this manually; it is part of the Phase 6 sequence.
- **`learnings-agent`** - conductor-discretionary background capture. The conductor spawns it ad-hoc the first time a learning-worthy event occurs in a session (Skeptic finding resolved, error->fix cycle, tool failure workaround, architectural decision, cross-component gotcha, user-called-out reusable pattern). No automatic phase trigger.

For `learnings-agent` session-tracking semantics, see `content/references/conductor-operating-rules.md` §learnings-agent background capture.

## Worker Preamble and Execution Contract Template

**Worker preamble (when using engineer):** When spawning an `engineer` on an Elevated-risk task, include both the preamble sentence and the execution contract block below. Fill in all required fields (outputs, tool_scope, completion_conditions) before spawning; budget is optional (advisory, not enforced); output_paths is conditional (required when the architect plan pre-specifies paths, otherwise set to "conductor-directed"). The contract applies to Elevated-path engineer spawns only - Trivial-path solo spawns (see Risk Classification) keep the lightweight preamble with no contract block.

**Worktree isolation is MANDATORY.** Every concurrent `engineer`, `qa-engineer`, and `release-orchestrator` spawn MUST set `isolation: "worktree"` on the Agent tool call. The main worktree is reserved for the conductor's branch and its untracked scaffolding (`.agentic/`, in-flight planning artifacts, loop-state files). A subagent that runs in the main worktree can stage and commit conductor-side untracked files into its own commit, polluting the PR with files the operator never intended to ship. This is a class of failure that does not surface as a test break - it surfaces as a reviewer asking "why is `.agentic/loop-state.json` in this PR?" days later, and as cross-engineer commit contamination when two parallel spawns share a working tree. Isolation is the primary mechanism that prevents both.

There is no in-place exception. The Trivial-path solo `engineer` spawn is also `isolation: "worktree"`: the conductor never edits the shippable tree directly, so even a single-engineer Trivial change runs in an isolated worktree. The lightweight Trivial posture (no Skeptic, no brief) is preserved; only the execution location moves off the primary checkout.

Pre-spawn stash fallback: see `content/references/worktree-lifecycle.md` §Pre-spawn stash fallback.

Preamble:
*"You are a Worker agent. Implement this specific change and return your complete output. The main agent will arrange Skeptic review."*

Execution contract template:
- outputs: [what artifact(s) the Worker must produce - e.g. "modified files committed to branch", "diff only", "summary report only"]
- budget: [rough max tool-call count, or omit; advisory, not enforced]
- tool_scope: [expected tool categories - e.g. "Read, Glob, Grep, Edit"; documentation only, does not override the harness-level Agent tool grants]
- completion_conditions: [acceptance criteria verbatim from architect plan or ticket, plus any quality-gate pass requirements]
- verification: [how this unit will be verified after it lands - existing test path that exercises it, new test the Worker must add, manual QA trigger pattern, or "self-evident review" if no test path is feasible]
- output_paths: [specific file paths the Worker is expected to write or modify, or "conductor-directed" if paths emerge during implementation]
- task_id: [unique task identifier for multi-unit correlation, or omit for single-unit]
- brief_path: [path to the Brief governing this unit, or "n/a" if architect plan is the sole artifact]
- plan_path: [path to the Plan directory governing this unit, or "n/a" if Brief-tier or below]

When `brief_path` or `plan_path` is populated, the engineer reads it before starting. Success criteria, non-goals, and the verification gate supersede any informal interpretation of the ticket. If the engineer discovers a conflict between the Brief and the architect plan, it returns BLOCKED so the conductor can resolve.

The `verification` field is **mandatory**. Its purpose is to force the conductor to specify *how the change will be verified before implementation begins*, not as a Skeptic afterthought. As coding gets cheaper, verification is the expensive thing, and the protocol reorganizes around verification rather than around shipping code. If the verification path is not knowable up front (truly novel surface, no existing tests, no feasible new test), state that explicitly as `"self-evident review"` and accept that the Skeptic and any QA gate are the only line of defense - do not leave the field blank.

The `task_id` field is included for Elevated multi-unit spawns only (when `.agentic/tasks.jsonl` is in use). Omit for Trivial or single-unit spawns. Workers receive `task_id` for identification; the conductor correlates the worker's return summary with the correct task entry and handles all writes to the task-state file.

## Digest-Return Discipline

**Digest-return discipline.** When a loop-running spawn (multi-iteration Skeptic/QA, long investigation) returns from the background, the conductor reads the terminal status, sign-off, falsifiable-claims evidence, residual risk, not-done list, and the optional `learnings_candidate[]` field - then acts. It does not re-read the worker's internal transcript or re-derive findings. This is how the conductor's context stays flat across many parallel loops. When `learnings_candidate[]` is non-empty, the conductor routes each entry through the guardrail-first gate (capture-classification.md) before forwarding `Capture: MUST` entries to `learnings-agent`; see `content/references/conductor-operating-rules.md` §learnings-agent for the routing algorithm. See `content/references/digest-return-pattern.md` for the full digest field list and conductor consumption rules.
