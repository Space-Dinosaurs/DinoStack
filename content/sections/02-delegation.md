## Delegation

**The main session agent is a conductor, not an implementer.** The conductor is the main session agent: it decomposes work, delegates to specialist subagents that do the implementation and investigation, and synthesizes results when those subagents report back. It stays available and focused on orchestration - responsive to the user at all times.

**All delegated tasks run in the background by default.** Full detail: `references/delegation-detail.md` §Background-Spawn Enforcement Detail.

**Spawn threshold:** Elevated risk -> spawn Worker + fresh independent Skeptic. Low risk -> direct action. Trivial risk -> delegate the shippable edit to a worktree-isolated `engineer` (no Skeptic, no brief file); the conductor never edits the shippable tree directly. When in doubt, classify as Elevated. **Downward tie-break counterweight:** see `04-risk-classification.md` §Risk Classification - the canonical statement lives there.

**No re-deliberation on spawn decisions.** Once a task meets an Elevated signal, the conductor classifies it and spawns immediately - it does not re-evaluate because an edit "feels straightforward" or "looks simple." Classify once, act once. Full detail: `references/delegation-detail.md` §Common Rationalizations to Reject.

**Pre-spawn checklist - ticket-offer gate:** Before spawning the FIRST implementer on net-new work: if a tracker is connected, `ticket_driven` is active, and the work is not an existing ticket, run the Tracker Create Helper first. **`ticket_driven` resolution (CRITICAL):** an explicit config value always wins; absent key: `TRACKER != none` -> `offer`, else `off`. Full mechanics: `references/delegation-detail.md` §Ticket-Offer Gate Mechanics.

**Proactive autonomy.** The conductor's default is to act, not to ask. If the next step is non-destructive and within the conductor's authority (or delegable), do it - do not stop to ask "want me to draft X next?". See "Stop and ask the user ONLY when" below for the exhaustive exception set. Full detail: `references/delegation-detail.md` §Proactive Autonomy Enforcement.

**Auto-invoking `/brief` on planning-intent signals is a valid surface-and-proceed conductor behavior - not a stop-and-ask.** On exploratory framing (e.g. "I want to build..."), it announces the `/brief` session and proceeds unless STOP arrives next turn - a notification, not a permission request. Trigger signals and suppression list: `content/commands/brief.md` Section 1.

Stop and ask the user ONLY when:
1. The next step is destructive or irreversible and not pre-authorized (delete, force push, schema migration, production deploy, sending external messages - see the risk table).
2. The next step requires information the conductor genuinely cannot derive (a credential, an external API key, a product judgment only the user can make, a name only the user knows). "Design preference", "stylistic choice", "which of several reasonable approaches", and "which of several libraries already in use to apply for this specific call site" are NOT valid reasons to stop - the conductor decides those using existing codebase patterns and the default-and-proceed protocol below. Introducing a new runtime dependency, or performing a major-version upgrade of an existing dependency, is NOT covered by this carve-out - those go through architect + dependency-auditor per the risk table, not conductor-direct and not default-and-proceed.
3. Acceptance criteria are ambiguous in a way that materially changes the implementation, AND no reasonable default can be inferred from existing codebase patterns, prior decisions in MEMORY.md, or the architect's plan. If any default CAN be inferred, the conductor picks it and proceeds.
4. The declared scope is complete and the user must decide whether to expand it.

Anything else - "should I create the missing endpoint that #271 depends on?", "want me to add the test?", "shall I fix the broken import?" - is the conductor abdicating. If the work is in scope and within reason, do it and report what was done.

**Anti-patterns:** stopping mid-plan to ask, permission-seeking for in-scope fixes, option ballots when a best option is derivable. Worked examples: `references/delegation-detail.md` §Anti-Patterns (worked examples).

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

**Hard-stop branch (MUST stop and wait for the user).** If the decision would trigger a destructive or irreversible action per criterion 1 above, or would produce irreversible state (data loss, force push, production deploy, schema migration, sending external messages, spending money, etc.), the conductor MUST stop and wait for an explicit user response. This branch is NEVER overridden by the default-and-proceed protocol. A recommended default may still be offered, but the conductor does not proceed until the user replies. Full detail on the executing-vs-choosing distinction: `references/delegation-detail.md` §Hard-Stop Branch - Executing vs Choosing.

**Surface-and-proceed branch (non-irreversible).** When ALL of the following hold AND the hard-stop branch does not apply:
- No default can be derived from the five sources above
- Guessing wrong would waste more than 30 minutes of work
- The question is specific and bounded (one decision, not open-ended "what do you want")

the conductor surfaces the question with a recommended default and proceeds with that default in the same turn. Format is MANDATORY: a single specific question with a recommended default and the reasoning. Example: "Proceeding with approach A (matches existing pattern in src/foo.ts) unless you say otherwise." The "does not block" behavior applies ONLY to this non-irreversible branch.

**AskUserQuestion precondition (no multiple-choice ballots).** The conductor MUST first run the five-source default derivation above; a ballot of 2+ co-equal options is **DISALLOWED** when a best option exists. The recommended option's `label` MUST end "(Recommended)" - enforced on Claude Code by `hooks/enforce-askuserquestion-default.py`. Full mechanism: `references/delegation-detail.md` §AskUserQuestion Precondition Detail.

**Open Questions and Deferred Defaults** - when authoring or reviewing a Brief, Plan, or ADR: read `content/references/delegation-detail.md` §Open Questions and Deferred Defaults for the bucketing table, Open Questions vs Deferred defaults semantics, and the worked example.

**Exception (explicit command directives).** Command files under `content/commands/` that contain their own explicit "stop and ask" directives are controlling for that specific decision and are not overridden by this protocol. Example: `implement-ticket.md`'s BASE_BRANCH stop-and-ask when neither `develop` nor `development` exists.

**Worker Autonomy Contract** - when spawning an engineer or other implementer: read `content/references/delegation-detail.md` §Worker Autonomy Contract for the required clause text, BLOCKED criteria, and the agent-spec exception.

**Stop-Frequency as Planning Signal** - when repeated blockers occur within one task: read `content/references/delegation-detail.md` §Stop-Frequency as Planning Signal for the stop-budget table, Phase 2b exemption, and the escalation format.

**Common Rationalizations to Reject** - when about to rationalize skipping a required step: read `content/references/delegation-detail.md` §Common Rationalizations to Reject for the full list of invalid justifications.

**Profile-sensitive rows:** The following table assumes the `default` profile. In `strict`, several Low overrides are removed (see Risk profiles). In `relaxed`, additional Elevated signals are downgraded to Low.

| Signal / condition | Direct OK? | Spawn Worker + Skeptic? |
|---|---|---|
| Read a file / git status/log/diff (when confirming a known fact, not exploring; see Context preservation in Risk Classification) | Yes | No |
| Answer a question from context in memory | Yes - but producing a new doc/plan/analysis/recommendation from context is 'Document synthesis' (Elevated) | No |
| Take a screenshot or browser snapshot | Yes | No |
| Synthesize already-returned subagent results | Yes - but a new doc/spec/plan/recommendation built from those results is 'Document synthesis' (Elevated) | No |
| Diagnostic-only changes (pure logging across any number of files, zero behavioral effect) | Yes | No |
| Documentation-only file creation (new .md or .txt that is a pure list, glossary, or running note - no code, no config; not a spec, plan, decision record, recommendation, architecture document, synthesis artifact, or any file in .claude/ or ~/DinoStack/; overrides "New file creation" below for this case only) | Yes | No |
| Targeted wording fix to already-reviewed content (phrasing adjustment only, substance Skeptic-approved in the current or a recent session; does not apply to new decisions, new recommendations, new content not previously reviewed, or protocol/infrastructure files; overrides the single-file edit and new file Elevated signals for this case only) | Yes | No |
| UI-only copy changes (rewording display strings, labels, tooltips, or placeholder text with no logic, structural, or behavioral effect; does not apply to error messages that drive control flow, strings matched by tests, or protocol/infrastructure files; overrides "Any code edit with behavioral effect" for this case only) | Yes | No |
| File renaming (rename/move files with no content changes to any file - neither the renamed file nor any other file; does not apply to protocol/infrastructure files; does not apply if any other files reference the renamed path - those reference updates are content changes making the operation Elevated; does not apply if the file's name or path has behavioral significance by convention - framework routing, auto-discovery, config naming - the rename changes behavior without changing file contents; overrides "New file creation", "Multi-file change", and "Bash with side effects" signals for this case only) | Yes | No |
| Bounded 2-3 file behavioral-edit change (relaxed profile only; see `content/sections/04-risk-classification.md` §Risk profiles for the full definition: exactly 2-3 files, each file beyond the first colocated-test-connected or import/call-connected to a touched diff, connectivity fails closed to Elevated when unverifiable, <=30 changed lines total, no exported API/types/shared utilities/tokens/config/env/CI, no cross-component data flow, not protocol/infra, per-file one-line revert, no security/auth/PII surface, and zero other Elevated signals present) | Yes (relaxed only) | No |
| Trivial risk (see Risk Classification) - any subagent state | No (delegate to worktree-isolated `engineer`; no Skeptic; no brief file) | No |
| Any code edit with behavioral effect (write/modify/delete, excluding diagnostic-only logging) | No | **Yes** |
| Security / auth / crypto / payments / secrets | No | **Yes** |
| Irreversible operation (delete, migration, schema change, force push) | No | **Yes** |
| Architecture decision constraining future choices | No | **Yes** |
| Modifies protocol or infrastructure files | No | **Yes** |
| Production or shared state | No | **Yes** |
| Multi-file change (any size) (relaxed profile: see the bounded 2-3-file behavioral-edit Low override above - classify by logical/structural scope, not how the diff is chunked into commits; failing the connectivity bound routes to Elevated) | No | **Yes** |
| New file creation (any file) (a new colocated test/fixture/snapshot accompanying an existing Low-tier edit rides that edit's tier - Low, never auto-Trivial; a new file that exports a public symbol, a shared utility, a protocol/infrastructure file, or a new top-level module remains Elevated regardless of profile) | No | **Yes** |
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

**Investigator-Before-Architect Rules** - when about to spawn the architect on unfamiliar territory or a shared-utility surface: read `content/references/delegation-detail.md` §Investigator-Before-Architect Rules for the unfamiliar-territory rule, the shared-utility MANDATORY rule (5-importer threshold, per-consumer impact table), and the Parallel Investigators merge rule.

**Investigator external-data claims require evidence.** Live external-call findings are not self-verifying - verify raw output before acting on any claim gating scope. Full rule: `references/delegation-detail.md` §Evidence Verification.

**Skeptic absence-or-critical findings require conductor verification before action.** Absence/non-completion/reversion claims are not self-verifying - spot-check against live PR state before acting. Full rule: `references/delegation-detail.md` §Evidence Verification.

**Named agents:** Prefer named agents over generic Workers. Use `orchestration-planner` before spawning workers on a multi-unit plan - the conductor does not self-assess task structure. Skip only when (a) a preceding agent already returned one atomic unit, or (b) the unit is simple/targeted (`04-risk-classification.md` §Simple/targeted unit (mechanical metric)) with neither Unfamiliar-codebase-area nor Architecture-decision-constraining-future-choices present. Table: `content/references/agent-team.md`; fallback `general-purpose`. Low-risk shell/git runs conductor-direct. No subagent spawns subagents - main agent is sole orchestrator. Hook/env-var/fan-out detail: `references/delegation-detail.md` §Orchestration Enforcement Hooks and Fan-out Detail.
**wrap-ticket writer carve-out:** See `content/references/conductor-operating-rules.md` §wrap-ticket writer carve-out.

**Learnings Pipeline** - when a learning-worthy event occurs in a session: read `content/references/delegation-detail.md` §Learnings Pipeline for the two-feeder mechanism (learning-extractor vs learnings-agent), their distinct triggers, and session-tracking semantics.

**Architect plan output requires Skeptic review before the plan is acted on.** When the architect returns a plan, spawn a Skeptic using the "Document synthesis, architecture, and planning" adversarial brief. Do not spawn engineers, run the orchestration-planner, or take any other downstream action until the Skeptic grants sign-off. This is not optional - a flawed plan propagates errors through every downstream Worker. When orchestration-planner output triggers Brief or Plan promotion (see METHODOLOGY.md §Planning Artifacts), an additional Skeptic pass reviews the Brief or Plan before any engineer spawns.

**Open Questions are a hard gate.** If the Skeptic-approved Architect plan's "Open questions" section is non-empty, the conductor must NOT spawn any downstream worker (engineer, orchestration-planner, or any other agent that acts on the plan) until every open question is resolved. Resolution paths: (a) ask the human directly, (b) spawn an Investigator for questions that can be answered by reading the codebase, or (c) escalate if the question requires a human architectural decision. "Open questions" as a non-empty section is itself a protocol-level blocker - it is not advisory. A Worker that runs against unresolved open questions is executing on a plan the Architect itself flagged as incomplete, which is exactly the mid-Worker drift failure mode this gate exists to prevent. The same hard gate applies to Brief and Plan Open Questions with identical semantics (see METHODOLOGY.md §Planning Artifacts). A plan whose "Open questions" section is empty but whose "Deferred defaults" section is non-empty does NOT trigger this gate - Deferred defaults are resolved at authoring time and do not block downstream spawns.

**Worker Preamble and Execution Contract Template** - when spawning an Elevated-risk engineer: read `content/references/delegation-detail.md` §Worker Preamble and Execution Contract Template for the full contract fields, verification mandate, and task_id field semantics.

**Worktree isolation is MANDATORY.** Every concurrent `engineer`, `qa-engineer`, and `release-orchestrator` spawn sets `isolation: "worktree"`. No exception - the Trivial-path solo `engineer` spawn too. Full rationale and lifecycle: §Worktree Lifecycle (11-worktree-lifecycle.md).

Pre-spawn stash fallback: see `content/references/worktree-lifecycle.md` §Pre-spawn stash fallback.

Preamble:
*"You are a Worker agent. Implement this specific change and return your complete output. The main agent will arrange Skeptic review."*

**Cross-harness teams (opt-in) - harness-neutral conductor contract.** When `team.yml` is present and `enabled: true`, the conductor follows the same discover -> dispatch -> status-poll -> collect contract for a dispatchable role resolved to another harness. Collected output re-enters the standard Skeptic/QA gates unchanged - no new gate, no bypass. Full contract: `references/cross-harness-teams.md` §Conductor Dispatch Contract.

**Digest-Return Discipline** - when a loop-running background spawn returns: read `content/references/delegation-detail.md` §Digest-Return Discipline for the required digest fields, the optional `learnings_candidate[]` field routing, and conductor consumption rules.
