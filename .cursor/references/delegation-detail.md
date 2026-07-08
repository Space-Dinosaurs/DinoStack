<!--
Purpose: Detailed delegation-model reference blocks extracted from
         content/sections/02-delegation.md. Contains: Background-spawn
         enforcement detail; Ticket-offer gate mechanics; Proactive autonomy
         enforcement; Open Questions / Deferred Defaults bucketing rules +
         table + worked example; Worker autonomy contract + agent-spec
         exception; Stop-frequency planning signal + table; Common
         rationalizations to reject; Anti-patterns (worked examples);
         Hard-stop branch executing-vs-choosing detail; AskUserQuestion
         precondition detail; Evidence verification (investigator external-
         data + Skeptic absence-or-critical claims); Investigator-before-
         Architect rules (incl shared-utility-MANDATORY + Parallel
         Investigators); Orchestration enforcement hooks + fan-out detail;
         Learnings pipeline; Worker preamble + execution contract template;
         Digest-return discipline.

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

## Background-Spawn Enforcement Detail

Foreground is permitted only for direct-action cases in the table below. Never block inline - spawn in the background, give the user a status update, and wait for completion notification. On the current Claude Code harness, `Agent` spawns run in the background by default; the harness DOES pass `run_in_background` through to the PreToolUse hook payload for `Agent` spawns (confirmed by live payload capture 2026-07-07 - hook tool_input keys for an Agent spawn observed as `description`/`prompt`/`run_in_background`/`subagent_type`, correcting the earlier assumption that the field was stripped). `hooks/enforce-background-spawn.py` enforces background-by-default on BOTH `Task` and `Agent`, with an asymmetric rule per tool: on `Agent`, only an explicit `run_in_background: false` is denied - an absent field allows (Agent already backgrounds by default at the harness level, so omitting it is the correct norm) and `true` also allows; on `Task` (legacy), only `run_in_background: true` allows - absent, `false`, or any non-boolean value denies. The conductor norm on Claude Code: omit `run_in_background` entirely on `Agent` spawns and rely on the harness default; never pass `false`. The hook retains two active responsibilities: (a) `run_in_background` enforcement for both `Task` and `Agent` per the asymmetric rule above, and (b) cross-harness teamrun-sentinel suppression for both `Task` and `Agent` when `.agentic/teamrun/.active` is live. The one sanctioned synchronous agent is `wrap-ticket`, which runs to completion in line because it must block on `wrap.lock` before Phase 12 cleanup proceeds; treat that as a behavioral property of `wrap-ticket`, not a general exemption.

## Ticket-Offer Gate Mechanics

**Ticket-offer gate.** Trigger: `TRACKER != none` AND `ticket_driven` active AND net-new work that did NOT arrive as an existing ticket ID is about to spawn its first implementer (architect, engineer, or orchestration-planner) -> conductor runs the Tracker Create Helper (cross-ref `content/commands/implement-ticket.md` §Tracker Create Helper) before proceeding.

This makes "tracker connected => offer by default" true with zero migration - no config change needed on existing projects with a connected tracker.

- **`offer` mode (surface-and-proceed):** emit `Creating ticket for this work - reply STOP to skip and proceed ad-hoc.` If no STOP arrives in one turn: invoke the Create Helper. On CREATE_STATUS=created: route via `/implement-ticket <CREATED_TICKET_ID>`. On CREATE_STATUS=failed or skipped: emit the soft-fail/skip line and proceed ad-hoc.

- **`require` mode (hard gate):** do not spawn any implementer before a ticket exists. Invoke the Create Helper immediately. On created: route to `/implement-ticket <CREATED_TICKET_ID>`. On failed: surface the error and WAIT for operator resolution. On a classifier-defined tracker where create is unavailable (would be `skipped`): do NOT silently proceed - surface the conflict (`ticket_driven=require but tracker '<type>' has no create integration - proceed ad-hoc this once, or stop?`) and WAIT for the operator.

**Exemptions:** existing-ticket arrivals (ticket ID resolved in Phase 0, or invocation was `/implement-ticket <ID>`) skip the gate entirely. `TRACKER=none` projects skip the gate regardless of the `ticket_driven` value.

## Proactive Autonomy Enforcement

On Claude Code this rule is enforced by a Stop hook (`hooks/enforce-no-abdication.py`, wired by `.claude/install.sh`) that detects a permission-seeking interrogative in the final assistant message and blocks the session stop, injecting a "proceed" directive; enabled by default; set `abdication_guard_enabled: false` in `.agentic/config.json` to opt out; disable per-session via `AE_ABDICATION_GUARD_DISABLE=1`; other adapters rely on the prose rule.

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

## Anti-Patterns (worked examples)

- Stopping after one unit of a multi-unit plan to ask if the next unit should be done. The plan is the answer.
- Asking permission to fix a broken test discovered during work. Fix it.
- Asking permission to create an obvious dependency (a missing import, type definition, or upstream endpoint a downstream task is waiting on). Create it.
- Asking permission to look something up. Look it up.
- Presenting the user with 2+ options and asking which to pick (a multiple-choice ballot) when one option is derivable as best. This is a **defect in the same class as a strawman option**: both offload the conductor's own job onto the operator - the strawman by padding the choice with options nobody should pick, the ballot by refusing to pick at all. If a best option is derivable from the five default sources, pick it and note the choice; if you must surface the decision, surface ONE recommended action with a reversal offer, never a ballot. This is enforced structurally on Claude Code (see §AskUserQuestion Precondition Detail below).
- Returning BLOCKED from a Worker over a design-taste call. Pick the option that best matches surrounding code and return DONE with the choice noted.

## Hard-Stop Branch - Executing vs Choosing

The hard-stop applies to **executing** an unauthorized irreversible or shared-state action - not to **choosing** among options once authorization exists. When the operator has already authorized proceeding (e.g. "proceed", "do it", "go ahead", or an approved plan), the remaining "which path do we take" question is a default-and-proceed decision, not a hard-stop: the conductor derives the best option from the five sources and proceeds. Re-confirming a path the operator already authorized is itself the abdication this protocol forbids.

## AskUserQuestion Precondition Detail

If a best option exists, a multiple-choice menu is **DISALLOWED** - the conductor either (a) picks the best option, states it, and proceeds (noting the choice), or (b) surfaces exactly ONE recommended action phrased as a recommendation-plus-confirmation ("Proceeding with X unless you say otherwise"), never a ballot of 2+ co-equal options for the operator to choose between. When AskUserQuestion IS legitimately used (a single confirmation of a genuinely irreversible AND unauthorized action, per the hard-stop branch), the recommended option's `label` MUST end with the literal suffix "(Recommended)" - this is the convention that marks the derived default and the exact token the enforcement hook checks. A 2+-option single-select question whose options carry no "(Recommended)" label is a co-equal ballot and is forbidden. On Claude Code this is enforced by a `PreToolUse` hook (`hooks/enforce-askuserquestion-default.py`, wired by `.claude/install.sh`) that denies any single-select AskUserQuestion call presenting 2+ options where no option label contains "(Recommended)"; other adapters rely on this prose rule.

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

## Evidence Verification

**Investigator external-data claims require evidence.** When an investigator makes live external calls (API, database, network) and reports specific field values, data presence/absence, or statistics as findings - those claims are not self-verifying. The conductor must treat them as unverified until evidence is provided. Before acting on any investigator finding that gates an implementation scope decision (e.g. "field X is populated for Y% of records", "this API returns field Z", "endpoint returns null for these cases"), verify via one of: (a) require the investigator's output to include a raw response excerpt as inline evidence - a synthesized table with no raw data is insufficient; (b) have the conductor spot-check one raw response directly before briefing the architect; or (c) spawn a follow-up investigator with explicit instructions to return the raw API/query output. The failure mode this prevents: an investigator that summarizes live API responses without quoting them can fabricate or misread field presence, causing the architect to design against data that does not exist in production. "High confidence" in the investigator's summary is not a substitute for seeing the raw response.

**Skeptic absence-or-critical findings require conductor verification before action.** When a Skeptic returns a finding that asserts absence, non-completion, reversion, or relocation of any work - those claims are not self-verifying regardless of authorship. The Skeptic's git state may be stale or contaminated by files from unrelated branches. The conductor MUST spot-check the falsifiable claim against live PR state (via `gh pr diff <n>` or fully-qualified remote refs after `git fetch`) BEFORE acting on it - before reverting code, posting the finding to an external surface (PR comment, Linear, Jira), or routing it to a fix engineer. Verify via one of: (a) run `gh pr view <n> --json files` and confirm the asserted-absent file or change is not present in the PR; (b) run `gh pr diff <n> | grep <relevant-pattern>` and confirm the absence; or (c) require the Skeptic to re-spawn with explicit freshness instructions (see `content/references/skeptic-protocol.md` §Review-environment freshness precondition) and produce the raw evidence. The failure mode this prevents: a Skeptic working from a stale tree raises a Critical finding on code that is correct in the live PR, causing the conductor to take a destructive or incorrect action against work that never needed changing. "The Skeptic is an adversarial reviewer" is not a substitute for verifying falsifiable claims before acting on them.

## Orchestration Enforcement Hooks and Fan-out Detail

On Claude Code this is enforced by a `PreToolUse` hook (`hooks/enforce-orchestrator-singularity.py`, wired by `.claude/install.sh`) that denies any `Agent` spawn issued from a subagent context (detected via the `agent_id` field); set `AE_SINGULARITY_GUARD_DISABLE=1` to disable. Other adapters rely on the prose rule.

The Mandatory Tier-3 review escalation rule (Risk Classification) is mechanically backstopped on Claude Code by a `PreToolUse` hook (`hooks/enforce-tier.py`, wired by `.claude/install.sh`) that denies an explicit sub-Opus `model` param on a `security-auditor` spawn (always) or a `skeptic` spawn whose brief matches a Tier-3 escalation signal; escalate-only and fail-open, it never blocks the omit-the-param role-default path and does not catch the novel-architecture signal (not keyword-detectable - the conductor and frontmatter default remain the controls there). Set `AE_TIER_GUARD_DISABLE=1` to disable. Other adapters rely on the prose rule.

The Brief/Plan authoring gate is backed by an advisory PreToolUse(Write/Edit) hook (`hooks/enforce-planning-artifact-spawn.py`) that warns when a `docs/planning/**` artifact is written without a recent architect spawn on record; warn-only, never blocks; set `AE_PLANNING_GUARD_DISABLE=1` to silence.

For Trivial-classified tasks, the conductor delegates the shippable change to a worktree-isolated `engineer` with no Skeptic and no brief file - the conductor never edits the shippable tree directly; only the execution location moves off the primary checkout, and the lightweight Trivial posture (no Skeptic, no brief) is preserved (see the shippable/exempt classifier in `content/rules/conventions.md` §Git Workflow).

**When fan-out is active, the orchestration-planner output JSONL block includes `unit_slug`, `merge_order`, and `skeptic_strategy` fields. Per-unit Skeptic spawning is a valid conductor behavior for parallel fan-out of independent units (complementing the existing "independent elevated units get their own Skeptic" rule in Task Decomposition below). The `skeptic_strategy` field - `"per-unit"`, `"integration"`, or `"multi-dimensional"` - is the authoritative source; do not re-derive this from the plan prose. `multi-dimensional` fans out a correctness-Skeptic, security-auditor, and perf-analyst in a single message on the same diff; see subagent-protocol.md for full definition.**

## Learnings Pipeline

**Learnings pipeline (two feeders, distinct triggers).** The learnings pipeline has two separate feeders with different trigger mechanisms:

- **`learning-extractor`** - mechanically wired to `/implement-ticket` Phase 6 clean exit. Fires automatically on every ticketed Skeptic loop completion. The conductor does NOT spawn this manually; it is part of the Phase 6 sequence.
- **`learnings-agent`** - conductor-discretionary background capture. The conductor spawns it ad-hoc the first time a learning-worthy event occurs in a session (Skeptic finding resolved, error->fix cycle, tool failure workaround, architectural decision, cross-component gotcha, user-called-out reusable pattern). No automatic phase trigger.

For `learnings-agent` session-tracking semantics, see `content/references/conductor-operating-rules.md` §learnings-agent background capture.

## Worker Preamble and Execution Contract Template

**Worker preamble (when using engineer):** When spawning an `engineer` on an Elevated-risk task, include both the preamble sentence and the execution contract block below. Fill in all required fields (outputs, tool_scope, completion_conditions) before spawning; budget is optional (advisory, not enforced); output_paths is conditional (required when the architect plan pre-specifies paths, otherwise set to "conductor-directed"). The contract applies to Elevated-path engineer spawns only - Trivial-path solo spawns (see Risk Classification) keep the lightweight preamble with no contract block.

Worktree isolation is MANDATORY for every concurrent `engineer`, `qa-engineer`, and `release-orchestrator` spawn (no exception, including Trivial-path solo spawns) - full rationale and lifecycle: `content/sections/11-worktree-lifecycle.md` §Worktree Lifecycle.

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
