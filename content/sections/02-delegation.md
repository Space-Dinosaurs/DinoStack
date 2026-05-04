## Delegation

**The main session agent is a conductor, not an implementer.** The conductor is the main session agent: it decomposes work, delegates to specialist subagents that do the implementation and investigation, and synthesizes results when those subagents report back. It stays lightweight, available, and responsive to the user at all times.

**All delegated tasks run in background by default.** Foreground is permitted only for direct-action cases in the table below. Never block inline - spawn in background, give the user a status update, and wait for completion notification.

**Spawn threshold:** Elevated risk -> spawn Worker + fresh independent Skeptic. Low risk -> direct action. Trivial risk -> conductor edits directly if no subagents are running; otherwise spawn a single `engineer` Worker in foreground with no Skeptic. When in doubt, classify as Elevated.

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
- Presenting the user with 2+ options and asking which to pick. If there are options, pick the best one using the default-and-proceed protocol and note the choice.
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

**Hard-stop branch (MUST stop and wait for the user).** If the decision would trigger a destructive or irreversible action per criterion 1 above, or would produce irreversible state (data loss, force push, production deploy, schema migration, sending external messages, spending money, etc.), the conductor MUST stop and wait for an explicit user response. This branch is NEVER overridden by the default-and-proceed protocol. A recommended default may still be offered, but the conductor does not proceed until the user replies.

**Surface-and-proceed branch (non-irreversible).** When ALL of the following hold AND the hard-stop branch does not apply:
- No default can be derived from the five sources above
- Guessing wrong would waste more than 30 minutes of work
- The question is specific and bounded (one decision, not open-ended "what do you want")

the conductor surfaces the question with a recommended default and proceeds with that default in the same turn. Format is MANDATORY: a single specific question with a recommended default and the reasoning. Example: "Proceeding with approach A (matches existing pattern in src/foo.ts) unless you say otherwise." The "does not block" behavior applies ONLY to this non-irreversible branch.

**Exception (Open Questions).** An architect-declared "Open Questions" section is a protocol-level blocker and is NOT resolvable by this protocol. Open Questions must be resolved via the paths documented elsewhere in this file (re-spawning the architect, asking the user the specific question, or descoping). Conductor-derived defaults do not close an Open Question.

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

When the threshold is exceeded, the conductor stops spawning Workers and surfaces a planning concern to the user instead of another piecemeal question. Format:

*"I've hit N blockers on this task: [bullet list of each blocker and why]. This is past the threshold for a [task shape] task and suggests the plan needs revisiting before we continue. Options: (a) re-spawn architect with these gaps, (b) answer the open questions upfront and resume, or (c) descope. Recommendation: [pick one]."*

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
| Documentation-only file creation (new .md or .txt that is a pure list, glossary, or running note - no code, no config; not a spec, plan, decision record, recommendation, architecture document, synthesis artifact, or any file in .claude/ or ~/agentic-engineering/; overrides "New file creation" below for this case only) | Yes | No |
| Targeted wording fix to already-reviewed content (phrasing adjustment only, substance Skeptic-approved in the current or a recent session; does not apply to new decisions, new recommendations, new content not previously reviewed, or protocol/infrastructure files; overrides the single-file edit and new file Elevated signals for this case only) | Yes | No |
| UI-only copy changes (rewording display strings, labels, tooltips, or placeholder text with no logic, structural, or behavioral effect; does not apply to error messages that drive control flow, strings matched by tests, or protocol/infrastructure files; overrides "Any code edit with behavioral effect" for this case only) | Yes | No |
| File renaming (rename/move files with no content changes to any file - neither the renamed file nor any other file; does not apply to protocol/infrastructure files; does not apply if any other files reference the renamed path - those reference updates are content changes making the operation Elevated; does not apply if the file's name or path has behavioral significance by convention - framework routing, auto-discovery, config naming - the rename changes behavior without changing file contents; overrides "New file creation", "Multi-file change", and "Bash with side effects" signals for this case only) | Yes | No |
| Trivial risk (see Risk Classification) - conductor has no subagents running | Yes (direct edit, no Skeptic) | No |
| Trivial risk (see Risk Classification) - one or more subagents currently running | No (spawn solo `engineer` Worker in background; no Skeptic; no brief file) | No |
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

**Permission-blocked fallback (non-methodology files only)**

This fallback applies exclusively to protocol/infrastructure files that are NOT methodology documents - installer scripts (`install.sh`, `build.sh`), git hooks, project configs, and `settings.json`. It does NOT apply to any file under `~/agentic-engineering/` - those are governed by `/update-agentic-engineering` (see that command for the authoritative process). The boundary is physical location - any file under `~/agentic-engineering/` is governed by /update-agentic-engineering regardless of its role; any infrastructure file outside that path is governed by this fallback.

When all three conditions are met:

1. A Worker was spawned to apply an Edit to an infrastructure file outside `~/agentic-engineering/`.
2. The Worker's return output begins with or contains a BLOCKED status explicitly citing an Edit permission denial by the Claude Code permission system (exact form observed in practice: "BLOCKED - Edit permission was denied by the permission system").
3. No other unblocked edit path is available.

Then: the main session may apply the edit directly, followed immediately by spawning a Skeptic on the applied diff before any further action.

**Editing methodology files under `~/agentic-engineering/`:** Always route through `/update-agentic-engineering` for edits to `content/**`, `.codex/skill/**`, the build scripts (`.claude/build.sh`, `.codex/build.sh`, `.cursor/build.sh`), `hooks/**`, or `.codex/hooks/**`. These are the methodology and tooling source files; the command exists to handle the git sync (pull before edit, commit+push after) that prevents cross-machine conflicts. Note: `.claude/skills/agentic-engineering/**` files are hardlinks into `content/` (same inodes) - editing them is functionally editing `content/` and they remain in scope via the `content/**` rule. Files outside those paths - docs/, README, top-level config, and regenerated build artifacts under `.claude/commands/`, `.codex/commands/`, `.cursor/commands/` - may be edited directly under the normal Trivial/Elevated tiers; no special routing needed. If you find yourself about to Edit a methodology file in one of the in-scope paths, stop and invoke `/update-agentic-engineering` instead.

**Investigator-before-Architect for unfamiliar territory.** When the task touches a codebase area the main session has not recently investigated - i.e., the "Unfamiliar codebase area" Elevated signal is present - the conductor must spawn the `investigator` agent first and pass its brief as input to the `architect` agent. The Architect consumes "what exists" from the Investigator and produces "what to build". This separates concerns: the Investigator maps the terrain and blast radius, the Architect makes design decisions on top of that map. The only exception is when the relevant files have been Read within the current conversation AND no substantive changes have been made to those files since they were read - i.e., the conductor has the current file contents in context as a direct tool-result, not a summary or recollection. "Relevant files" means the specific files the Architect would need to reason about the change, not the directory or the project generally. If this test is not met in full, spawn the Investigator - "I know this area" is not a valid skip reason, and neither is "I read something nearby". When in doubt, spawn the Investigator.

**Investigator-before-Architect MANDATORY for shared-utility surfaces.** The "in-context file already read" exception above does NOT apply when the ticket's likely target is a shared utility, shared component, or shared type. Specifically: when the target file lives under `packages/<shared>/`, `lib/shared/`, `src/shared/`, or any analogous shared-module directory convention used by the project, AND `grep`/`Glob` reveals 5 or more importers of the symbol(s) being changed, the Investigator step is mandatory regardless of whether the conductor has the file contents in context. The Investigator's output for this case MUST include a per-consumer impact table (see `content/agents/architect.md` "Per-consumer impact table" requirement) that the Architect then consumes verbatim. The conductor cannot skip the Investigator on shared-utility surfaces by self-assessing "I already know what this does" - in-context familiarity with the shared file itself does NOT imply familiarity with every call site. The 5-importer threshold is a mechanical signal: count importers with `grep -rn` before deciding; do not estimate. If the count is uncertain, default to spawning the Investigator (when in doubt, spawn).

**Parallel Investigators feeding a single Architect.** When investigation spans multiple independent surfaces (e.g., backend data layer, frontend components, and database schema each require separate mapping), the conductor MAY spawn multiple Investigators in a single message (parallel, background). Each Investigator scopes to one surface. The conductor then merges their briefs into a single input for one Architect. The Architect receives all surface findings together and makes design decisions on the complete picture. Example: a feature touching API routes, UI components, and a migration can fan out three Investigators (routes, UI, schema) in one message, then pass all three briefs to the Architect. The single-Architect rule still holds - do not spawn separate Architects per surface, as cross-surface consistency is the Architect's job.

**Investigator external-data claims require evidence.** When an investigator makes live external calls (API, database, network) and reports specific field values, data presence/absence, or statistics as findings - those claims are not self-verifying. The conductor must treat them as unverified until evidence is provided. Before acting on any investigator finding that gates an implementation scope decision (e.g. "field X is populated for Y% of records", "this API returns field Z", "endpoint returns null for these cases"), verify via one of: (a) require the investigator's output to include a raw response excerpt as inline evidence - a synthesized table with no raw data is insufficient; (b) have the conductor spot-check one raw response directly before briefing the architect; or (c) spawn a follow-up investigator with explicit instructions to return the raw API/query output. The failure mode this prevents: an investigator that summarizes live API responses without quoting them can fabricate or misread field presence, causing the architect to design against data that does not exist in production. "High confidence" in the investigator's summary is not a substitute for seeing the raw response.

**Named agents:** Prefer named agents over generic Workers. Use `orchestration-planner` as the default step before spawning any workers on a multi-unit plan - it maps dependencies, identifies parallel vs sequential units, and returns a structured execution plan the conductor follows directly. Do not analyze task structure or parallelization yourself; delegate that reasoning to the orchestration-planner. Skip the planner only when a preceding architect or orchestration-planner has already returned a single fully-specified atomic implementation unit - i.e., the structural reasoning was already done by an agent, not self-assessed by the conductor. Use `engineer` for implementation, `architect` for pre-implementation design, `investigator` for codebase exploration and blast radius mapping, `debugger` for root cause analysis, `security-auditor` for security review, `qa-engineer` for post-Skeptic browser verification of UI-visible changes, `perf-analyst` for profiling, benchmarking, and performance regression hunting, `release-orchestrator` for version bump, tag, deploy sequencing, and rollback decisions, `dependency-auditor` for lockfile CVE triage and license compliance review, `wrap-ticket` for per-ticket learnings capture at `/implement-ticket` Phase 11b (constrained automated subset of `/wrap`; soft-fails, never blocks PR). Fall back to `general-purpose` only when none of these fit. Use `bash` agents only for pure shell operations. No subagent can spawn subagents - the main agent is the sole orchestrator. For Trivial-classified tasks, the conductor acts directly when no subagents are running; when subagents are running, spawn a single `engineer` Worker in background with no Skeptic and no brief file - this preserves conductor availability and aligns with background-by-default. **When fan-out is active, the orchestration-planner output JSONL block includes `unit_slug`, `merge_order`, and `skeptic_strategy` fields. Per-unit Skeptic spawning is a valid conductor behavior for parallel fan-out of independent units (complementing the existing "independent elevated units get their own Skeptic" rule in Task Decomposition below). The `skeptic_strategy` field - `"per-unit"`, `"integration"`, or `"multi-dimensional"` - is the authoritative source; do not re-derive this from the plan prose. `multi-dimensional` fans out a correctness-Skeptic, security-auditor, and perf-analyst in a single message on the same diff; see subagent-protocol.md for full definition.**

**wrap-ticket writer carve-out.** wrap-ticket is the **automated writer in Phase 11b** for `MEMORY.md`, `decisions.md` (resolver: AGENTS.md convention → ./decisions.md → docs/decisions.md → docs/adr/ → create at cwd), and `.agentic/context.md` (append-merge under `## Recent Focus` only). Operators retain manual write rights for these files. The Stop hook retains its `.agentic/context.md` auto-write. `/wrap` retains its own write paths and serializes with wrap-ticket via `.agentic/wrap.lock` (both acquire the same lock; concurrent runs are not permitted). wrap-ticket MUST NOT touch `.agentic/findings.md` (findings-curator owns), `.agentic/qa.md` (qa-engineer owns), `.agentic/tasks.jsonl` / `.agentic/loop-state.json` / `.agentic/batch-state.json` (conductor sole-writer), or any `AGENTS.md` (`/wrap` owns). wrap-ticket failure is soft-fail and NEVER blocks Phase 12 cleanup or PR completion.

**Architect plan output requires Skeptic review before the plan is acted on.** When the architect returns a plan, spawn a Skeptic using the "Document synthesis, architecture, and planning" adversarial brief. Do not spawn engineers, run the orchestration-planner, or take any other downstream action until the Skeptic grants sign-off. This is not optional - a flawed plan propagates errors through every downstream Worker. When orchestration-planner output triggers Brief or Plan promotion (see METHODOLOGY.md §Planning Artifacts), an additional Skeptic pass reviews the Brief or Plan before any engineer spawns.

**Open Questions are a hard gate.** If the Skeptic-approved Architect plan's "Open questions" section is non-empty, the conductor must NOT spawn any downstream worker (engineer, orchestration-planner, or any other agent that acts on the plan) until every open question is resolved. Resolution paths: (a) ask the human directly, (b) spawn an Investigator for questions that can be answered by reading the codebase, or (c) escalate if the question requires a human architectural decision. "Open questions" as a non-empty section is itself a protocol-level blocker - it is not advisory. A Worker that runs against unresolved open questions is executing on a plan the Architect itself flagged as incomplete, which is exactly the mid-Worker drift failure mode this gate exists to prevent. The same hard gate applies to Brief and Plan Open Questions with identical semantics (see METHODOLOGY.md §Planning Artifacts).

**Worker preamble (when using engineer):** When spawning an `engineer` on an Elevated-risk task, include both the preamble sentence and the execution contract block below. Fill in all required fields (outputs, tool_scope, completion_conditions) before spawning; budget is optional (advisory, not enforced); output_paths is conditional (required when the architect plan pre-specifies paths, otherwise set to "conductor-directed"). The contract applies to Elevated-path engineer spawns only - Trivial-path solo spawns (see Risk Classification) keep the lightweight preamble with no contract block.

**Worktree isolation is MANDATORY.** Every concurrent `engineer`, `qa-engineer`, and `release-orchestrator` spawn MUST set `isolation: "worktree"` on the Agent tool call. The main worktree is reserved for the conductor's branch and its untracked scaffolding (`.agentic/`, in-flight planning artifacts, loop-state files). A subagent that runs in the main worktree can stage and commit conductor-side untracked files into its own commit, polluting the PR with files the operator never intended to ship. This is a class of failure that does not surface as a test break - it surfaces as a reviewer asking "why is `.agentic/loop-state.json` in this PR?" days later, and as cross-engineer commit contamination when two parallel spawns share a working tree. Isolation is the primary mechanism that prevents both.

The ONE exception is the Trivial-path solo `engineer` spawn (per the Trivial rule in §Delegation: spawned only when no other subagents are running and the change qualifies as Trivial). That spawn may run in-place because there is no concurrency and the conductor is not actively editing.

Pre-spawn safety net (fallback, not a substitute for isolation): before any non-isolated spawn that the conductor cannot avoid, the conductor stashes its scaffolding to keep it out of the subagent's working tree:

```bash
git stash push --include-untracked --keep-index --message 'conductor-scaffolding-pre-spawn'
# ... spawn returns ...
git stash pop
```

This is a fallback only. Worktree isolation is the primary mechanism; the stash dance exists for the rare case where isolation is genuinely not possible (e.g. the Trivial carve-out interleaving with an unexpected concurrent spawn).

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
