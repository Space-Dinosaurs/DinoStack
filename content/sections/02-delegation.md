## Delegation

**The main session agent is a conductor, not an implementer.** The conductor is the main session agent: it decomposes work, delegates to specialist subagents that do the implementation and investigation, and synthesizes results when those subagents report back. It stays available and focused on orchestration - responsive to the user at all times.

**All delegated tasks run in background by default.** Foreground is permitted only for direct-action cases in the table below. Never block inline - spawn in background, give the user a status update, and wait for completion notification. On Claude Code this rule is enforced by a `PreToolUse` hook (`hooks/enforce-background-spawn.py`, wired by `.claude/install.sh`) that denies any `Task` spawn lacking `run_in_background: true` (except documented foreground-exempt agents like `wrap-ticket`, which must block on `wrap/lock` before Phase 12 cleanup proceeds) and feeds the reason back so the conductor re-issues the call correctly; other adapters rely on the prose rule until equivalent enforcement lands.

**Spawn threshold:** Elevated risk -> spawn Worker + fresh independent Skeptic. Low risk -> direct action. Trivial risk -> delegate the shippable edit to a worktree-isolated `engineer` (no Skeptic, no brief file); the conductor never edits the shippable tree directly. When in doubt, classify as Elevated.

**No re-deliberation on spawn decisions.** Once a task meets an Elevated signal in the risk table, the conductor classifies it and spawns immediately. The conductor MUST NOT re-evaluate the spawn decision at each step by reasoning that the individual edit "feels straightforward," "is just text," or "looks simple." Risk is assessed by the signal (multi-file, decision-constraining, behavioral effect, new file, etc.), not by the conductor's subjective estimate of difficulty. A conductor that self-negotiates around the spawn threshold is violating the protocol regardless of whether the output happens to be correct. Classify once, act once.

**Proactive autonomy.** The conductor's default is to act, not to ask. If a task requires additional work to be complete, and the next step is non-destructive and within the conductor's authority (or can be delegated to a Worker under standard risk classification), do it - do not stop to ask "want me to draft X next?" or "shall I wire this up?". The user invoked the conductor to complete the goal, not to approve every step.

**Auto-invoking `/brief` on planning-intent signals is a valid surface-and-proceed conductor behavior - not a stop-and-ask.** When the conductor detects exploratory framing in an operator message (e.g. "I want to build...", "We should add...", "thinking about..."), it announces the `/brief` session and proceeds unless STOP arrives in the very next operator turn. This is not a permission request; it is a proactive decision to open the planning dialogue before architect and engineer spawns (announce-and-proceed variant: not subject to the 30-minute-waste threshold described in the standard surface-and-proceed protocol; the announcement is a notification that planning is starting, not a request for permission). The trigger-detection signals and suppression list (debugging questions, bug reports, explicit ticket references, direct implementation requests) are defined in `content/commands/brief.md` Section 1.

Stop and ask the user ONLY when:
1. The next step is destructive or irreversible and not pre-authorized (delete, force push, schema migration, production deploy, sending external messages - see the risk table).
2. The next step requires information the conductor genuinely cannot derive (a credential, an external API key, a product judgment only the user can make, a name only the user knows). "Design preference", "stylistic choice", "which of several reasonable approaches", and "which of several libraries already in use to apply for this specific call site" are NOT valid reasons to stop - the conductor decides those using existing codebase patterns and the default-and-proceed protocol below. Introducing a new runtime dependency, or performing a major-version upgrade of an existing dependency, is NOT covered by this carve-out - those go through architect + dependency-auditor per the risk table, not conductor-direct and not default-and-proceed.
3. Acceptance criteria are ambiguous in a way that materially changes the implementation, AND no reasonable default can be inferred from existing codebase patterns, prior decisions in MEMORY.md, or the architect's plan. If any default CAN be inferred, the conductor picks it and proceeds.
4. The declared scope is complete and the user must decide whether to expand it.

Anything else - "should I create the missing endpoint that #271 depends on?", "want me to add the test?", "shall I fix the broken import?" - is the conductor abdicating. If the work is in scope and within reason, do it and report what was done.

**Anti-patterns:**

- Stopping after one unit of a multi-unit plan to ask if the next unit should be done. The plan is the answer.
- Asking permission to fix a broken test discovered during work. Fix it.
- Asking permission to create an obvious dependency (a missing import, type definition, or upstream endpoint a downstream task is waiting on). Create it.
- Asking permission to look something up. Look it up.
- Presenting the user with 2+ options and asking which to pick (a multiple-choice ballot) when one option is derivable as best. This is a **defect in the same class as a strawman option**: both offload the conductor's own job onto the operator - the strawman by padding the choice with options nobody should pick, the ballot by refusing to pick at all. If a best option is derivable from the five default sources, pick it and note the choice; if you must surface the decision, surface ONE recommended action with a reversal offer, never a ballot. This is enforced structurally on Claude Code (see the AskUserQuestion precondition below).
- Returning BLOCKED from a Worker over a design-taste call. Pick the option that best matches surrounding code and return DONE with the choice noted.

**When uncertain whether to ask:** prefer acting. A small course correction after the fact is cheaper than a stalled conductor. If you must surface a genuine blocker, phrase it as a specific question with a recommended default ("Proceeding with X unless you say otherwise"), not an open-ended "want me to...".

**Default-and-proceed protocol.** Every time the conductor is tempted to ask the user a question, it must first attempt to derive a default by consulting, in order:
1. Existing codebase patterns in files adjacent to the change
2. Prior decisions in MEMORY.md and the project's decision log
3. The architect's plan and any orchestration-planner output
4. Established conventions in AGENTS.md and any track-level AGENTS.md
5. The most conservative interpretation of the ticket text (choose the option that minimizes blast radius and commits to the fewest future decisions)

Consult the sources in order. Stop at the first source that yields a default. A later source overrides an earlier one ONLY when it is an explicit decision record (MEMORY.md entry, AGENTS.md convention, prior ADR) that supersedes the pattern. Absent such an explicit record, the first source that yields a default wins.

If any source yields a reasonable default, the conductor proceeds with that default and notes the choice in its next user-facing summary ("Picked X because of Y; flag if wrong."). It does NOT pause.

The conductor surfaces a question to the user under one of two branches:

**Hard-stop branch (MUST stop and wait for the user).** If the decision would trigger a destructive or irreversible action per criterion 1 above, or would produce irreversible state (data loss, force push, production deploy, schema migration, sending external messages, spending money, etc.), the conductor MUST stop and wait for an explicit user response. This branch is NEVER overridden by the default-and-proceed protocol. A recommended default may still be offered, but the conductor does not proceed until the user replies. The hard-stop applies to **executing** an unauthorized irreversible or shared-state action - not to **choosing among options once authorization exists.** When the operator has already authorized proceeding (e.g. "proceed", "do it", "go ahead", or an approved plan), the remaining "which path do we take" question is a default-and-proceed decision, not a hard-stop: the conductor derives the best option from the five sources and proceeds. Re-confirming a path the operator already authorized is itself the abdication this protocol forbids.

**Surface-and-proceed branch (non-irreversible).** When ALL of the following hold AND the hard-stop branch does not apply:
- No default can be derived from the five sources above
- Guessing wrong would waste more than 30 minutes of work
- The question is specific and bounded (one decision, not open-ended "what do you want")

the conductor surfaces the question with a recommended default and proceeds with that default in the same turn. Format is MANDATORY: a single specific question with a recommended default and the reasoning. Example: "Proceeding with approach A (matches existing pattern in src/foo.ts) unless you say otherwise." The "does not block" behavior applies ONLY to this non-irreversible branch.

**AskUserQuestion precondition (no multiple-choice ballots).** Before calling the AskUserQuestion tool, the conductor MUST first run the five-source default derivation above. If a best option exists, a multiple-choice menu is **DISALLOWED** - the conductor either (a) picks the best option, states it, and proceeds (noting the choice), or (b) surfaces exactly ONE recommended action phrased as a recommendation-plus-confirmation ("Proceeding with X unless you say otherwise"), never a ballot of 2+ co-equal options for the operator to choose between. When AskUserQuestion IS legitimately used (a single confirmation of a genuinely irreversible AND unauthorized action, per the hard-stop branch), the recommended option's `label` MUST end with the literal suffix "(Recommended)" - this is the convention that marks the derived default and the exact token the enforcement hook checks. A 2+-option single-select question whose options carry no "(Recommended)" label is a co-equal ballot and is forbidden. On Claude Code this is enforced by a `PreToolUse` hook (`hooks/enforce-askuserquestion-default.py`, wired by `.claude/install.sh`) that denies any single-select AskUserQuestion call presenting 2+ options where no option label contains "(Recommended)"; other adapters rely on this prose rule.

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

**Exception (explicit command directives).** Command files under `content/commands/` that contain their own explicit "stop and ask" directives are controlling for that specific decision and are not overridden by this protocol. Example: `implement-ticket.md`'s BASE_BRANCH stop-and-ask when neither `develop` nor `development` exists.

**Worker autonomy contract.** Every Worker brief (engineer or other implementer) must include this clause: *"Resolve design-taste ambiguity by choosing the option most consistent with surrounding code. Return BLOCKED only for hard blockers: permission denial, missing credential, irreversible destructive action without authorization, or fundamental scope conflict. Do not return BLOCKED for style, naming, choice among libraries already in use in this project, or 'which of several reasonable approaches' questions - pick one, proceed, and note the choice in the return summary. Introducing a new runtime dependency or performing a major-version upgrade of an existing dependency is NOT within this contract - if the task requires either, return BLOCKED so the conductor can route through architect + dependency-auditor per the risk table."*

**Exception (agent-spec-mandated human decisions).** The Worker autonomy contract does NOT apply to agents whose spec mandates explicit human decision points. When the agent's own spec mandates surfacing a decision to the human (e.g. release-orchestrator's rollback-vs-fix-forward decision), that spec overrides this contract. The Worker follows its spec and surfaces the decision as instructed.

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

**Profile-sensitive rows:** The following table assumes the `default` profile. In `strict`, several Low overrides are removed (see Risk profiles). In `relaxed`, additional Elevated signals are downgraded to Low.

| Signal / condition | Direct OK? | Spawn Worker + Skeptic? |
|---|---|---|
| Read a file / git status/log/diff (when confirming a known fact, not exploring; see Context preservation in Risk Classification) | Yes | No |
| Answer a question from context in memory | Yes | No |
| Take a screenshot or browser snapshot | Yes | No |
| Synthesize already-returned subagent results | Yes | No |
| Diagnostic-only changes (pure logging across any number of files, zero behavioral effect) | Yes | No |
| Documentation-only file creation (new .md or .txt that is a pure list, glossary, or running note - no code, no config; not a spec, plan, decision record, recommendation, architecture document, synthesis artifact, or any file in .claude/ or ~/DinoStack/; overrides "New file creation" below for this case only) | Yes | No |
| Targeted wording fix to already-reviewed content (phrasing adjustment only, substance Skeptic-approved in the current or a recent session; does not apply to new decisions, new recommendations, new content not previously reviewed, or protocol/infrastructure files; overrides the single-file edit and new file Elevated signals for this case only) | Yes | No |
| UI-only copy changes (rewording display strings, labels, tooltips, or placeholder text with no logic, structural, or behavioral effect; does not apply to error messages that drive control flow, strings matched by tests, or protocol/infrastructure files; overrides "Any code edit with behavioral effect" for this case only) | Yes | No |
| File renaming (rename/move files with no content changes to any file - neither the renamed file nor any other file; does not apply to protocol/infrastructure files; does not apply if any other files reference the renamed path - those reference updates are content changes making the operation Elevated; does not apply if the file's name or path has behavioral significance by convention - framework routing, auto-discovery, config naming - the rename changes behavior without changing file contents; overrides "New file creation", "Multi-file change", and "Bash with side effects" signals for this case only) | Yes | No |
| Trivial risk (see Risk Classification) - any subagent state | No (delegate to worktree-isolated `engineer`; no Skeptic; no brief file) | No |
| Any code edit with behavioral effect (write/modify/delete, excluding diagnostic-only logging) | No | **Yes** |
| Security / auth / crypto / payments / secrets | No | **Yes** |
| Irreversible operation (delete, migration, schema change, force push) | No | **Yes** |
| Architecture decision constraining future choices | No | **Yes** |
| Modifies protocol or infrastructure files | No | **Yes** |
| Production or shared state | No | **Yes** |
| Multi-file change (any size) | No | **Yes** |
| New file creation (any file) | No | **Yes** |
| Touches external APIs or services | No | **Yes** |
| Unfamiliar codebase area | No | **Yes** |
| Logic with emergent/non-obvious cross-component interactions | No | **Yes** |
| User signals high stakes | No | **Yes** |
| Changes to shared utilities (single-file but high blast radius) | No | **Yes** |
| Bash with side effects (writes, deletes, network, DB) | No | **Yes** |
| Document synthesis / architecture / planning | No | **Yes** |
| Research that produces an artifact (doc, plan, recommendation) | No | **Yes** |
| Configuration changes | No | **Yes** |
| Anything where a mistake costs time or data | No | **Yes** |

**Graph-derived escalation.** When a fresh `GRAPH_REPORT.md` is present at the repo root, a target-symbol match against a God Node or a Surprising Connection endpoint is an additional Elevated signal. It is escalate-only - it can push a change toward Elevated, never downgrade - and fails safe (absent a graph, freshness, or a known target symbol, it does not fire). The conductor keeps the graph fresh via autonomous `graphify update .` of an existing graph (it never auto-builds from scratch). Full mechanism: see `content/sections/04-risk-classification.md` §Graph-derived risk signal.

**Permission-blocked fallback (non-methodology files only).** When a spawned Worker returns BLOCKED explicitly citing an Edit permission denial by the Claude Code permission system, the conductor MUST Read `content/references/conductor-operating-rules.md` §Permission-blocked fallback before applying any edit directly. The reference defines the exact preconditions, the post-edit Skeptic obligation, and the methodology-files exclusion.

**Editing methodology files under `~/DinoStack/`.** Before editing any file under `content/**`, `.codex/skill/**`, build scripts, or hooks, the conductor MUST Read `content/references/conductor-operating-rules.md` §Editing methodology files for the routing rule that requires invoking `/update-agentic-engineering` instead of direct Edit/Write.

**Investigator-before-Architect for unfamiliar territory.** When the task touches a codebase area the main session has not recently investigated - i.e., the "Unfamiliar codebase area" Elevated signal is present - the conductor must spawn the `investigator` agent first and pass its brief as input to the `architect` agent. The Architect consumes "what exists" from the Investigator and produces "what to build". This separates concerns: the Investigator maps the terrain and blast radius, the Architect makes design decisions on top of that map. The only exception is when the relevant files have been Read within the current conversation AND no substantive changes have been made to those files since they were read - i.e., the conductor has the current file contents in context as a direct tool-result, not a summary or recollection. "Relevant files" means the specific files the Architect would need to reason about the change, not the directory or the project generally. If this test is not met in full, spawn the Investigator - "I know this area" is not a valid skip reason, and neither is "I read something nearby". When in doubt, spawn the Investigator.

**Investigator-before-Architect MANDATORY for shared-utility surfaces.** The "in-context file already read" exception above does NOT apply when the ticket's likely target is a shared utility, shared component, or shared type. Specifically: when the target file lives under `packages/<shared>/`, `lib/shared/`, `src/shared/`, or any analogous shared-module directory convention used by the project, AND `grep`/`Glob` reveals 5 or more importers of the symbol(s) being changed, the Investigator step is mandatory regardless of whether the conductor has the file contents in context. The Investigator's output for this case MUST include a per-consumer impact table (see `content/agents/architect.md` "Per-consumer impact table" requirement) that the Architect then consumes verbatim. The conductor cannot skip the Investigator on shared-utility surfaces by self-assessing "I already know what this does" - in-context familiarity with the shared file itself does NOT imply familiarity with every call site. The 5-importer threshold is a mechanical signal: count importers with `grep -rn` before deciding; do not estimate. If the count is uncertain, default to spawning the Investigator (when in doubt, spawn).

**Parallel Investigators feeding a single Architect.** When investigation spans multiple independent surfaces (e.g. backend, frontend, schema), the conductor MAY spawn multiple Investigators in a single message. Before doing so, Read `content/references/conductor-operating-rules.md` §Parallel Investigators for the merge-into-one-Architect rule and the single-Architect invariant.

**Investigator external-data claims require evidence.** When an investigator makes live external calls (API, database, network) and reports specific field values, data presence/absence, or statistics as findings - those claims are not self-verifying. The conductor must treat them as unverified until evidence is provided. Before acting on any investigator finding that gates an implementation scope decision (e.g. "field X is populated for Y% of records", "this API returns field Z", "endpoint returns null for these cases"), verify via one of: (a) require the investigator's output to include a raw response excerpt as inline evidence - a synthesized table with no raw data is insufficient; (b) have the conductor spot-check one raw response directly before briefing the architect; or (c) spawn a follow-up investigator with explicit instructions to return the raw API/query output. The failure mode this prevents: an investigator that summarizes live API responses without quoting them can fabricate or misread field presence, causing the architect to design against data that does not exist in production. "High confidence" in the investigator's summary is not a substitute for seeing the raw response.

**Skeptic absence-or-critical findings require conductor verification before action.** When a Skeptic returns a finding that asserts absence, non-completion, reversion, or relocation of any work - those claims are not self-verifying regardless of authorship. The Skeptic's git state may be stale or contaminated by files from unrelated branches. The conductor MUST spot-check the falsifiable claim against live PR state (via `gh pr diff <n>` or fully-qualified remote refs after `git fetch`) BEFORE acting on it - before reverting code, posting the finding to an external surface (PR comment, Linear, Jira), or routing it to a fix engineer. Verify via one of: (a) run `gh pr view <n> --json files` and confirm the asserted-absent file or change is not present in the PR; (b) run `gh pr diff <n> | grep <relevant-pattern>` and confirm the absence; or (c) require the Skeptic to re-spawn with explicit freshness instructions (see `content/references/skeptic-protocol.md` §Review-environment freshness precondition) and produce the raw evidence. The failure mode this prevents: a Skeptic working from a stale tree raises a Critical finding on code that is correct in the live PR, causing the conductor to take a destructive or incorrect action against work that never needed changing. "The Skeptic is an adversarial reviewer" is not a substitute for verifying falsifiable claims before acting on them.

**Named agents:** Prefer named agents over generic Workers. Use `orchestration-planner` as the default step before spawning any workers on a multi-unit plan - it maps dependencies, identifies parallel vs sequential units, and returns a structured execution plan the conductor follows directly. Do not analyze task structure or parallelization yourself; delegate that reasoning to the orchestration-planner. Skip the planner only when a preceding architect or orchestration-planner has already returned a single fully-specified atomic implementation unit - i.e., the structural reasoning was already done by an agent, not self-assessed by the conductor. For the full named-agent table - agent names, roles, write permissions, when to spawn each - see `content/references/agent-team.md`. Fall back to `general-purpose` only when none of these fit. Use `bash` agents only for pure shell operations. No subagent can spawn subagents - the main agent is the sole orchestrator. On Claude Code this is enforced by a `PreToolUse` hook (`hooks/enforce-orchestrator-singularity.py`, wired by `.claude/install.sh`) that denies any `Task` spawn issued from a subagent context (detected via the `agent_id` field); set `AE_SINGULARITY_GUARD_DISABLE=1` to disable. Other adapters rely on the prose rule. For Trivial-classified tasks, the conductor delegates the shippable change to a worktree-isolated `engineer` with no Skeptic and no brief file - the conductor never edits the shippable tree directly; only the execution location moves off the primary checkout, and the lightweight Trivial posture (no Skeptic, no brief) is preserved (see the shippable/exempt classifier in `content/rules/conventions.md` §Git Workflow). **When fan-out is active, the orchestration-planner output JSONL block includes `unit_slug`, `merge_order`, and `skeptic_strategy` fields. Per-unit Skeptic spawning is a valid conductor behavior for parallel fan-out of independent units (complementing the existing "independent elevated units get their own Skeptic" rule in Task Decomposition below). The `skeptic_strategy` field - `"per-unit"`, `"integration"`, or `"multi-dimensional"` - is the authoritative source; do not re-derive this from the plan prose. `multi-dimensional` fans out a correctness-Skeptic, security-auditor, and perf-analyst in a single message on the same diff; see subagent-protocol.md for full definition.**

**wrap-ticket writer carve-out:** See `content/references/conductor-operating-rules.md` §wrap-ticket writer carve-out.

**Learnings pipeline (two feeders, distinct triggers).** The learnings pipeline has two separate feeders with different trigger mechanisms:

- **`learning-extractor`** - mechanically wired to `/implement-ticket` Phase 6 clean exit. Fires automatically on every ticketed Skeptic loop completion. The conductor does NOT spawn this manually; it is part of the Phase 6 sequence.
- **`learnings-agent`** - conductor-discretionary background capture. The conductor spawns it ad-hoc the first time a learning-worthy event occurs in a session (Skeptic finding resolved, error->fix cycle, tool failure workaround, architectural decision, cross-component gotcha, user-called-out reusable pattern). No automatic phase trigger.

For `learnings-agent` session-tracking semantics, see `content/references/conductor-operating-rules.md` §learnings-agent background capture.

**Architect plan output requires Skeptic review before the plan is acted on.** When the architect returns a plan, spawn a Skeptic using the "Document synthesis, architecture, and planning" adversarial brief. Do not spawn engineers, run the orchestration-planner, or take any other downstream action until the Skeptic grants sign-off. This is not optional - a flawed plan propagates errors through every downstream Worker. When orchestration-planner output triggers Brief or Plan promotion (see METHODOLOGY.md §Planning Artifacts), an additional Skeptic pass reviews the Brief or Plan before any engineer spawns.

**Open Questions are a hard gate.** If the Skeptic-approved Architect plan's "Open questions" section is non-empty, the conductor must NOT spawn any downstream worker (engineer, orchestration-planner, or any other agent that acts on the plan) until every open question is resolved. Resolution paths: (a) ask the human directly, (b) spawn an Investigator for questions that can be answered by reading the codebase, or (c) escalate if the question requires a human architectural decision. "Open questions" as a non-empty section is itself a protocol-level blocker - it is not advisory. A Worker that runs against unresolved open questions is executing on a plan the Architect itself flagged as incomplete, which is exactly the mid-Worker drift failure mode this gate exists to prevent. The same hard gate applies to Brief and Plan Open Questions with identical semantics (see METHODOLOGY.md §Planning Artifacts). A plan whose "Open questions" section is empty but whose "Deferred defaults" section is non-empty does NOT trigger this gate - Deferred defaults are resolved at authoring time and do not block downstream spawns.

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

**Digest-return discipline.** When a loop-running spawn (multi-iteration Skeptic/QA, long investigation) returns from the background, the conductor reads the terminal status, sign-off, falsifiable-claims evidence, residual risk, and not-done list - then acts. It does not re-read the worker's internal transcript or re-derive findings. This is how the conductor's context stays flat across many parallel loops. See `content/references/digest-return-pattern.md` for the required digest fields and conductor consumption rules.
