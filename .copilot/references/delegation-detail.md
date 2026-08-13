<!--
Purpose: Detailed delegation-model reference blocks extracted from
         content/sections/02-delegation.md. Contains: Open Questions /
         Deferred Defaults bucketing rules + table + worked example; Worker
         autonomy contract + agent-spec exception; Stop-frequency planning
         signal + table; Common rationalizations to reject; Decision
         Stability and Contradiction Resolution (reversal counting, soft
         round cap, tripwire routing, anti-inversion test, worked example);
         Absence-claim scope axes (calibration worked example, both
         directions, for the four search-narrowness axes);
         Capability-unavailability scope axes (four surface axes, both
         directions, companion B INCONCLUSIVE-with-not-retried definition);
         Investigator-
         before-Architect rules (incl shared-utility-MANDATORY and Parallel
         Investigators); Harness-Injected Instruction Conflicts (collision
         catalog, delegation-suppression subsection, notice template,
         operator remedies, harness-vs-model diagnostic, DS-133
         unsupported-configuration policy and rejected consequence-detector
         record);
         Learnings pipeline; Worker preamble + execution contract template;
         AskUserQuestion and Operator Decisions enforcement mechanics (hook
         wiring, detection limits, kill switch); Operator Decisions block
         rationale (marker necessity, placement discipline); Digest-return
         discipline; Orchestration enforcement hooks + fan-out
         `skeptic_strategy` detail; Background-spawn enforcement detail.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/02-delegation.md (inline pointers replacing
            each verbose block); hooks/AGENTS.md (two inbound pointers into
            the Harness-Injected Instruction Conflicts section).

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

**Pre-architect planning-input scans are exempt from this budget.** The Phase 2b ambiguity scan in `/ds-implement-ticket` surfaces clarifying questions before any agent is spawned — no architect, investigator, or engineer has run yet. This is structurally different from a mid-work stop: it is bounded to exactly one operator turn, has a proceed-with-defaults fallback, and produces no work that needs to be discarded if the operator redirects. Phase 2b does not count against the per-task stop budget for any task shape.

When the threshold is exceeded, the conductor stops spawning Workers and surfaces a planning concern to the user instead of another piecemeal question. Format:

*"I've hit N blockers on this task: [bullet list of each blocker and why]. This is past the threshold for a [task shape] task and suggests the plan needs revisiting before we continue. Options: (a) re-spawn architect with these gaps, (b) answer the genuine Open Questions upfront and resume (Deferred defaults in the plan do not count toward this budget and do not block), or (c) descope. Recommendation: [pick one]."*

Then wait. Do NOT keep spawning Workers against an under-specified plan - that compounds the cost of the missing planning work and produces churn the user has to clean up later.

## Follow-up Ticket Creation Discipline

Applies to ANY decision to create a tracker ticket for work discovered
mid-session - whether via the Tracker Create Helper, a direct mcp__ tool
call, or a manual out-of-band call. This is prose discipline with NO
mechanical enforcement of the carve-out, the bar, or the batching rule
below - the only mechanical artifacts are the sink
(`.agentic/deferred-work.jsonl`, via `bin/ds-defer`) and its session-start
reader. A conductor that ignores this discipline is not mechanically
stopped.

1. **Execution-scope carve-out.** A discovery made during an in-progress
   unit (including at wrap/PR-summary time) is not "net-new work" for the
   Ticket-offer gate. Top-level, operator-raised asks are unaffected by
   everything below.
2. **Promotion bar.** A discovery earns a ticket only if (a) it blocks the
   current unit OR is independently schedulable with standalone value, AND
   (b) it is not fixable inline in under one Worker spawn's effort - a
   one-line fix is fixed inline, never deferred. Failing (a) or (b): record
   via `bin/ds-defer append --reason failed_promotion_bar` and move on.
3. **Batching is absolute - this is the actual branching-factor control,
   stronger than the bar above.** When 2 or more discoveries pass the bar
   in the same session, they are NEVER created as separate tickets. They
   are batched into exactly ONE ticket (one title, one numbered
   acceptance-criterion per item). A single bar-passing discovery becomes
   exactly one ticket. There is no branch under which a bar-passing item
   goes to the sink - the sink is reserved for bar failures and out-of-band
   discoveries only (item 4).
4. Manual/out-of-band discoveries (e.g. a direct API call bypassing every
   documented path) are recorded the same way:
   `bin/ds-defer append --reason out_of_band_manual_discovery`.
5. `/ds-feedback-triage` Step 4d is unaffected - its creates are already
   gated by an explicit per-batch human greenlight (`ds-feedback-triage.md`
   §"Step 2 - Group and present"), a stronger control than anything here.

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
- "The inputs have not changed but I am still not confident - let me re-read it once more" - re-reading a source already consulted produces no new evidence. If two same-tier instructions genuinely conflict, apply the equal-precedence tiebreak, act, and record it; confidence is not a terminating condition.

## Decision Stability and Contradiction Resolution

**Reversal counting.** A reversal is adopting position X then not-X on one decision with no new tool result, no new user message, and no new file content in between. Maintain the integer; "am I looping?" is not self-observable, "have I flipped this twice?" is.

**Soft round cap.** Two full re-derivation passes of one decision with no new input is tripwire-adjacent: take the terminal action rather than starting a third.

**Routing on tripwire** (mirrors R1's branch). Contradiction between instructions goes to the tiebreak. Everything else - a library choice, a naming call, a design-taste fork with no instruction conflict - takes the six-source derived default (falling to source 6's most-conservative reading if nothing earlier yields), acts, and notes the choice. "Record the conflict" does not apply where there is no conflict; inventing one to satisfy the rule is a defect.

**What is NOT an equal-precedence contradiction.** A general rule plus a named exception; a specific procedure refining a general convention; two statements resolvable by the six-source ordering or by reading one more file. Read first.

**The anti-inversion test, required before applying step 2.** Does the broad instruction read as a deliberate, recent, or policy-shaped statement the narrow file has not caught up to? Signals the broad file is authoritative and the narrow one stale: the broad text is a decision record or reads as one; it is more specific about intent while the narrow file is merely older; the narrow file's claim is an omission (a missing step) rather than a contrary assertion. When those signals are present, step 2 flips - the broad instruction wins and the narrow file is the defect. **When the staleness question cannot be answered from what is in hand, do not guess: fall to step 3.** A rule that always prefers the narrow file discards deliberate policy changes, which is worse than the loop this section ends.

**Declaration line format**, emitted at resolution: `Contradiction: <fileA:line> vs <fileB:line> - applied step <1|2|3>; proceeding with <resolution>. Recorded as intent-layer defect.`

**Worked example, both directions (historical - see Scope note).** *Direction A (narrow file correct):* at the time this contradiction existed, `content/rules/conventions.md:46` said root `MEMORY.md` was "written by `/ds-wrap`"; `content/commands/ds-wrap.md` had no promotion step and `content/references/conductor-operating-rules.md:111` (then :87) stated root `MEMORY.md` was not a `/ds-wrap` target. No decision record covered it and the broad line read as an unmaintained summary, so step 2 resolved: the command file governs its own command. Act, declare, record - and do not decide in-session whether `/ds-wrap` *should* promote, which is a feature decision and is ticket-shaped. *Direction B (broad file correct):* had `conventions.md:46` been edited last week as a deliberate policy change with `ds-wrap.md` merely not yet updated, the anti-inversion test flips step 2, the broad instruction governs, and the command file is the defect. Same rule, opposite outcome, decided by staleness and decision-record standing rather than scope alone.

**Why recording is the load-bearing half.** Every session re-encountering an unrecorded contradiction pays the tiebreak again. A recorded KNW entry can promote into root `MEMORY.md`, which is source 2 of the six-source chain, so the next session resolves by first-match-wins with zero deliberation. Recording is cheap and in-session; a doc fix is a shippable edit and is not.

**Scope note.** The worked example's contradiction is now RESOLVED (DS-90): `/ds-wrap` Part B is a genuine staging-drain promotion step into root `MEMORY.md` (capped 3/run), and `content/references/conductor-operating-rules.md` now states root `MEMORY.md` IS within the `wrap/lock` scope for exactly that reason - both files agree. The worked example above is retained as a historical illustration of the resolution procedure (Direction A / Direction B), not a description of current file state; do not treat it as evidence of a live contradiction.

## Absence-claim scope axes

Parent clause: `content/sections/02-delegation.md` §Skeptic absence-or-critical findings. That clause names four axes on which a search can be too narrow - the pattern, the file set, any closed list, and (implicitly) the git state the search ran against. This is the calibration anchor, run in both directions.

**Direction A (the search was too narrow - the claim is wrong).** DS-98's own history: the Global-context `n/a` rationale set was certified complete four separate times in two days, each certification made while fixing the previous one. Every check was a string-membership test against the list's current members, so every check passed and every check was wrong - a membership test can only ask "is this value in the list", never "is a legitimate value missing from it". Widening the grep pattern would not have helped; widening the file set would not have helped, because the list lived in one file. Only deriving the population independently - enumerating the actual spawn shapes the methodology supports, then diffing that against the enumerated set - surfaces the gap. That is why the closed-list axis needs its own method rather than "broaden the grep".

**Direction B (the search was adequate - the absence claim stands).** A Skeptic asserts a renamed config key has no remaining references. It greps the new and old spellings case-insensitively (pattern), across the full tree including YAML/TOML/JSON fixtures and deploy manifests rather than just the diff (file set), against a freshly fetched `origin/<head>` rather than a stale local checkout (git state), and the identifier is not drawn from any enumerated vocabulary, so the closed-list axis does not apply. Three axes exercised, the fourth correctly ruled out by inspection - the claim is certifiable. Note the asymmetry: ruling an axis out is a positive statement about the artifact, not a skipped step. "The closed-list axis does not apply here because X is not drawn from an enumeration" is a valid certification; silence on the axis is not.

## Capability-unavailability scope axes

Parent clause: `content/sections/02-delegation.md` §Capability-unavailability claims require an alternative surface. That clause names the minimum before reporting a capability unavailable or blocked: try at least one alternative surface and state which surfaces were tried. This is the calibration anchor for what counts as an alternative surface, run in both directions.

**The surface axes.** A capability probe can be too narrow on four axes: the surface set (API vs CLI vs dashboard vs SDK), the auth mechanism (one credential path vs another), the tool (one harness/tool vs another), and the read timing (an eventually-consistent state read once vs retried until the system's completion or propagation signal). A refusal on one cell of the surface matrix is not a refusal on the matrix.

**Direction A (the probe was too narrow - the claim is wrong or unverified).** Origin incidents: Railway provisioning was declared 'dashboard-only' after a single GraphQL `serviceCreate` call returned `Not Authorized`; the CLI was never tried, and `railway add -s <name>` created the service on the first try with the same project token. Separately, a capability was declared 'permanent' - that any created Railway service could not be deleted - from a GraphQL-only `serviceDelete` probe, in the same breath as arguing the CLI and GraphQL surfaces differ; the conclusion happened to hold (the CLI genuinely has no service-delete) but the reasoning was invalid, and the CLI was only checked afterwards when a Skeptic flagged the claim. Both are the one-probe generalization: evidence about one surface restated as a boundary of the whole system.

**Direction B (the negative claim stands - and is reportable).** A probe tried the CLI and the API, named both, and both refused with the same root-cause error. The claim is certifiable because the surface set was enumerated, not sampled. The asymmetry mirrors the absence-claim axes: ruling a surface out is a positive statement about having tried it, not a skipped step. 'I tried the CLI and the API' is a certification; silence on which surfaces were tried is not.

**Eventually-consistent negative reads (companion B).** For external state that converges over time, a negative read is a hypothesis until retried to the point that the system's own completion or propagation signal has fired (a deploy-queue green, a replication-lag report, a PR-status check) or a documented window for that system has elapsed - or the reporter discloses the read was not retried. **INCONCLUSIVE-with-not-retried** is the conductor-side status for this state: it means 'pending or unknown - not a verified failure'. It is distinct from the qa-engineer INCONCLUSIVE in `content/references/qa-gate.md` §INCONCLUSIVE classification, which is the qa-engineer's runtime-unavailability verdict (qa_unverified=true, surfaced to the operator with accept/abandon/provide-env options); the conductor-side status is a reporting discipline for the reporter's own claim, not an operator-acceptance decision, and it is never auto-promoted to a verified negative.

## Investigator-Before-Architect Rules

**Investigator-before-Architect for unfamiliar territory.** When the task touches a codebase area the main session has not recently investigated - i.e., the "Unfamiliar codebase area" Elevated signal is present - the conductor must spawn the `investigator` agent first and pass its brief as input to the `architect` agent. The Architect consumes "what exists" from the Investigator and produces "what to build". This separates concerns: the Investigator maps the terrain and blast radius, the Architect makes design decisions on top of that map. The only exception is when the relevant files have been Read within the current conversation AND no substantive changes have been made to those files since they were read - i.e., the conductor has the current file contents in context as a direct tool-result, not a summary or recollection. "Relevant files" means the specific files the Architect would need to reason about the change, not the directory or the project generally. If this test is not met in full, spawn the Investigator - "I know this area" is not a valid skip reason, and neither is "I read something nearby". When in doubt, spawn the Investigator.

**Investigator-before-Architect MANDATORY for shared-utility surfaces.** The "in-context file already read" exception above does NOT apply when the ticket's likely target is a shared utility, shared component, or shared type. Specifically: when the target file lives under `packages/<shared>/`, `lib/shared/`, `src/shared/`, or any analogous shared-module directory convention used by the project, AND `grep`/`Glob` reveals 5 or more importers of the symbol(s) being changed, the Investigator step is mandatory regardless of whether the conductor has the file contents in context. The Investigator's output for this case MUST include a per-consumer impact table (see `content/agents/architect.md` "Per-consumer impact table" requirement) that the Architect then consumes verbatim. The conductor cannot skip the Investigator on shared-utility surfaces by self-assessing "I already know what this does" - in-context familiarity with the shared file itself does NOT imply familiarity with every call site. The 5-importer threshold is a mechanical signal: count importers with `grep -rn` before deciding; do not estimate. If the count is uncertain, default to spawning the Investigator (when in doubt, spawn).

**Parallel Investigators feeding a single Architect.** When investigation spans multiple independent surfaces (e.g. backend, frontend, schema), the conductor MAY spawn multiple Investigators in a single message. Before doing so, Read `content/references/conductor-operating-rules.md` §Parallel Investigators for the merge-into-one-Architect rule and the single-Architect invariant.

## Harness-Injected Instruction Conflicts

Parent clause: `content/sections/02-delegation.md` §Host-harness instruction conflicts.

### Collision catalog

| Collision | Harness default (paraphrase) | AE locus | Resolution |
|---|---|---|---|
| **Approval scope** | "approval in one context doesn't extend to the next" | `content/sections/02-delegation.md` §Standing authorizations; `content/rules/conventions.md` §Git Workflow, Conductor preflight step 7 | The listed hygiene operations are durably authorized, so the harness carve-out is satisfied rather than overridden. An operator correction that an operation is routine updates the standing norm and is not instance-scoped. |
| **Delegation suppression** | "do not call the AgentTool unless the user requested it" / "Do not use workflows or deep-research unless the user requested it" (both variants observed) | `content/sections/02-delegation.md` §Delegation | See the Delegation suppression (Collision 2) subsection below, which quotes both lines. Remediation was settled in DS-133: unsupported configuration, no detection, no degraded mode. |
| **Act vs ask** | "confirm first for outward-facing or hard-to-reverse actions" | `content/sections/02-delegation.md` Hard-stop branch and Surface-and-proceed branch | Already arbitrated - the two branches partition the space by irreversibility. What was missing was the detection prompt and a definition of "pre-authorized", both now supplied. No new arbitration rule is added. |
| **Self-correction depth** | "avoid excessive self-correction; don't ruminate or give a detailed account of the mistake" | `content/references/conductor-operating-rules.md` §learnings-agent; `content/references/capture-classification.md` | When the operator *asks* why a rule was not followed, a causal account of the mechanism is the requested answer. The defect is the wrong kind of answer, not merely a short one - a rule restatement in place of a cause is a non-answer at any length. A written LRN/KNW entry is not conversational rumination, so capture classification is unaffected. Cross-reference the third disjunct of the new kernel detection prompt (`or a restatement of the rule feels like a sufficient answer to why you broke it`), which is phrased to fire on exactly this substitution. |

**Enforcement-hook prohibition (do not build the exploration guard).** No AE hook may deny conductor-side Read/Grep/Glob in order to force delegation. This is a flat prohibition, not a conditional one, and the reason is not the bridge-session deadlock: conductor-direct reads are methodology-*mandated* and precede the first spawn by construction - reading `.agentic/context.md` as the first action of every session, the meta-divergence and skill-candidate sweeps of `.agentic/events.jsonl` and `.agentic/skill-candidates.md`, `.agentic/config.json` toggle resolution before risk classification, and the target agent's `capabilities:` block at capability preflight. A call-count guard denies a fully compliant session before it denies a non-compliant one. Mandated conductor reads continue throughout the session too - the spot-check of a Skeptic absence-claim is post-spawn by construction - but the pre-spawn set alone settles it. Two further reasons close the door: the read carries no intent signal, so "confirming a known fact" (permitted) and "investigating an unfamiliar area" (must delegate) are the same payload; and in a session whose harness prompt already suppresses spawning, denying reads too leaves no permitted action at all.

Do not attempt to condition such a guard on whether spawning is available. **There is no such signal.** Session capability at runtime - which tools the harness will actually honour, what an injected system prompt forbids - has no payload representation and is not derivable from an on-disk artifact: a settings file states the operator's configured permission rules, which is not the same fact as what this session's harness will honour. An entrypoint marker may correlate with an injecting harness, but correlation with an entrypoint is not the capability, and gating on it requires the payload-capture discipline in `hooks/AGENTS.md` §Fail-open on absent tool_input fields first. `.agentic/events.jsonl` `spawn_start` records prove spawning *has* worked and can never prove it is unavailable. See `hooks/AGENTS.md` §No gating on inferred session capability for the hook-side rule; do not restate fail-open discipline here.

The rule stays prose-enforced, as it already is on ten of the eleven adapters. Mechanically, only non-blocking shapes are admissible: a warn-only PostToolUse nudge, or after-the-fact detection at a reflection point (the Stop hook already reads the transcript and runs the capture-gap backstop) that surfaces conductor-investigating *after* a turn instead of blocking it in advance. Calibrate any such threshold against measured session data before shipping it - a nudge that fires on a session of mandated preflight reads is the same defect as the deny-guard, only cheaper.

### Delegation suppression (Collision 2)

Real harness injections have been observed carrying both of the following lines, singly or together - the resolution below applies identically to either:

- "do not call the AgentTool unless the user requested it"
- "Do not use workflows or deep-research unless the user requested it"

A per-turn reminder naming this collision is wired into the risk-classification hook on adapters that execute a user-level pre-turn hook (Claude `UserPromptSubmit`, Codex `UserPromptSubmit`, Gemini `BeforeAgent`) - this closes the load-order gap for those adapters (the resolution rule is otherwise non-resident, loading only when `/dinostack` is invoked, so an injected line arriving on turn one would otherwise have nothing counteracting it). It does not, and cannot, establish that a suppressing bridge/remote-control entrypoint actually executes user-level hooks at all - the enforcement-hook prohibition above already states that session capability has no payload representation and is not derivable from an on-disk artifact.

Where the directive is conditional ("unless the user requested it"), the condition is already met whenever this methodology is active, because the operator installed it into their own instruction layer and its first delegation rule is that the conductor delegates rather than implements - a standing instruction that predates the session. The conductor treats the condition as satisfied and spawns normally, and this authorizes only delegation the methodology mandates, never anything the methodology itself gates.

Where the directive is unconditional and spawning genuinely fails, the conductor states that plainly at its first user-facing turn, with a remedy, rather than silently degrading into a direct implementer.

**Policy: unsupported configuration, not a degraded mode (DS-133).** Detection of the suppression is not implemented. AE does not refuse to activate, does not offer a degraded-mode switch, and does not claim to notice suppression. An affected session is an unsupported configuration, and the remedies listed with the notice template below are the fix, applied by the operator.

Three reasons stand behind that, and any future proposal to detect suppression has to answer all three rather than route around them. First, the activation preflight is bound to three file reads with no LLM reasoning (`content/sections/01-activation-preflight.md`, opening paragraph of §Activation preflight), and an injected directive has no file to read. Second, the capability has no payload representation and is not derivable from an on-disk artifact - the enforcement-hook prohibition above states this for hooks, and while that sentence is hook-scoped, the absence of a signal it relies on is a fact about the session rather than about hooks, so relocating the same inference to another layer does not create the signal. Third, the observed failure is *soft*: the model is discouraged and complies, so no spawn is attempted and no error exists to classify. A hard spawn failure is a different case, already handled by the unconditional branch above.

**A consequence-detector was specified and rejected; the reason is recorded so it need not be re-derived.** The idea was to stop asking "is spawning suppressed?" and instead report when a session committed shippable files with zero `spawn_start` events on record - a cause-agnostic fact about the session's own artifacts, emitted by hook code so that a compromised conductor's own judgment is not load-bearing. It fails on attribution rather than on capability inference: `spawn_start` events are keyed by `session_uuid`, git commits carry no session identity, and every proxy bridging the two is confounded. Three fully compliant shapes satisfy the predicate. A session doing nothing but its mandated base-sync and `git pull --ff-only` picks up a teammate's freshly merged commits. A cross-session loop resuming at a later phase squash-merges work whose engineer and Skeptic ran under a prior session's identifier, and the base-sync fast-forward at that phase's tail lands the resulting commit locally - the merge is the mechanism, not authorship. The landed squash commit is dated at merge time yet contains work reviewed under a prior session's identifier: fresh by date, foreign by authorship. A mandated `gh pr update-branch --rebase` rewrites committer dates and pulls an entire prior branch into any time window. So the detector would fire on mandated hygiene and on resumed reviewed work, which is the outcome the enforcement-hook prohibition above already names, at lower cost and with the same effect on operator attention. Surviving a compromised conductor is necessary but not sufficient: the surviving code still has to evaluate something it can compute. If a per-session commit-attribution signal is ever established, this analysis is the starting point rather than a settled bar.

**Notice template (unconditional branch).** When the directive is unconditional and spawning genuinely fails, emit at the first user-facing turn:

```
DELEGATION SUPPRESSED: this session's harness prompt forbids subagent spawns, so the
methodology's Worker + Skeptic review is not in force. Findings this session are
unreviewed.
  Remedies (any one):
    - ask for delegation explicitly in your next message
    - rerun from a local terminal entrypoint rather than a remote-control/bridge one
    - disable the harness's remote-control-at-startup setting, then restart
    - or keep this session for reads and diagnosis only and defer shippable edits
[phase: delegation-suppressed]
```

This notice is condition-scoped, not a session-start notice: it fires only on an affected entrypoint, whereas every notice in the stacked tally at `content/rules/conventions.md` §Session Context and Memory, the "stacked first-user-turn notices" line, has a trigger computed at preflight on every session. It is **not** one of those five and must not be added to that count.

**Harness-vs-model diagnostic.** Before attributing a compliance regression (the model ignoring delegation rules) to a model-version change, distinguish harness-cause from model-cause: run the identical prompt in a plain local terminal session versus the suspect entrypoint. Only a local-complies / other-fails split implicates the harness (an injected system prompt outranking the methodology); if both fail identically, the regression is model-side and should be investigated as such.

## Learnings Pipeline

**Learnings pipeline (two feeders, distinct triggers).** The learnings pipeline has two separate feeders with different trigger mechanisms:

- **`learning-extractor`** - mechanically wired to `/ds-implement-ticket` Phase 6 clean exit. Fires automatically on every ticketed Skeptic loop completion. The conductor does NOT spawn this manually; it is part of the Phase 6 sequence.
- **`learnings-agent`** - background capture spawned by the conductor the first time one of the mandatory capture triggers fires in a session. Trigger evaluation is MANDATORY and each trigger requires a `Capture:` declaration; the spawn itself is conductor-initiated rather than phase-wired. See `content/references/conductor-operating-rules.md` §learnings-agent background capture for the mandatory triggers and the declaration format.

For `learnings-agent` session-tracking semantics, see `content/references/conductor-operating-rules.md` §learnings-agent background capture.

## Worker Preamble and Execution Contract Template

**Worker preamble (when using engineer):** When spawning an `engineer` on an Elevated-risk task, include both the preamble sentence and the execution contract block below. Fill in all required fields (outputs, tool_scope, completion_conditions) before spawning; budget is optional (advisory, not enforced); output_paths is conditional (required when the architect plan pre-specifies paths, otherwise set to "conductor-directed"). The contract applies to Elevated-path engineer spawns only - Trivial-path solo spawns (see Risk Classification) keep the lightweight preamble with no contract block. For large tool outputs, see `content/references/evidence-on-disk.md` (spill/sketch/rehydrate protocol) - advisory.

**Worktree isolation is MANDATORY.** Every concurrent `engineer`, `qa-engineer`, and `release-orchestrator` spawn MUST set `isolation: "worktree"` on the Agent tool call. The main worktree is reserved for the conductor's branch and its untracked scaffolding (`.agentic/`, loop-state files - NOT in-flight planning artifacts, which are committed and pushed per `content/references/planning-artifacts.md` §Gate semantics as soon as they are authored, subject to the per-repo gitignore eligibility gate). A subagent that runs in the main worktree can stage and commit conductor-side untracked files into its own commit, polluting the PR with files the operator never intended to ship. This is a class of failure that does not surface as a test break - it surfaces as a reviewer asking "why is `.agentic/loop-state.json` in this PR?" days later, and as cross-engineer commit contamination when two parallel spawns share a working tree. Isolation is the primary mechanism that prevents both.

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
- brief_path: [path to the Brief governing this unit, or "n/a" if architect plan is the sole artifact - arrives already absolute in the engineer's contract, normalized at spawn construction]
- plan_path: [path to the Plan directory governing this unit, or "n/a" if Brief-tier or below - arrives already absolute in the engineer's contract, normalized at spawn construction]
- SESSION_KEY: [the session's learnings-shard key, derived once per session and passed verbatim on every spawn thereafter]

When `brief_path` or `plan_path` is populated, the engineer reads it before starting. Success criteria, non-goals, and the verification gate supersede any informal interpretation of the ticket. If the engineer discovers a conflict between the Brief and the architect plan, it returns BLOCKED so the conductor can resolve.

The `verification` field is **mandatory**. Its purpose is to force the conductor to specify *how the change will be verified before implementation begins*, not as a Skeptic afterthought. As coding gets cheaper, verification is the expensive thing, and the protocol reorganizes around verification rather than around shipping code. If the verification path is not knowable up front (truly novel surface, no existing tests, no feasible new test), state that explicitly as `"self-evident review"` and accept that the Skeptic and any QA gate are the only line of defense - do not leave the field blank.

The `SESSION_KEY` field is **mandatory and never omitted**. It is the one line in this template whose obligation is wider than the template itself: it belongs in **every** Worker's spawn prompt, including Trivial-path solo spawns and the non-`engineer` roles this contract does not otherwise cover. Omitting it raises no error - the Worker simply skips shard capture in silence, so the learning is lost with no signal. Derive the value once per session and pass that same value every time; the derivation rule, the harness caveats, and the reason the scope is blanket rather than per-role live in `content/references/subagent-protocol.md` §11 Output Expectations, "**`SESSION_KEY` at spawn time**".

The `task_id` field is included for Elevated multi-unit spawns only (when `.agentic/tasks.jsonl` is in use). Omit for Trivial or single-unit spawns. Workers receive `task_id` for identification; the conductor correlates the worker's return summary with the correct task entry and handles all writes to the task-state file.

## AskUserQuestion and Operator Decisions Enforcement Mechanics

Detail for the AskUserQuestion precondition kernel rule (`content/sections/02-delegation.md`). The hard-stop branch qualifier: AskUserQuestion is legitimately used only for a single confirmation of a genuinely irreversible AND unauthorized action, per the hard-stop branch - not for routine option surfacing.

**Tool-path enforcement.** On Claude Code, a `PreToolUse` hook (`hooks/enforce-askuserquestion-default.py`, wired by `.claude/install.sh`) denies any single-select AskUserQuestion call presenting 2+ options where no option label contains "(Recommended)" - the exact token the hook checks. Other adapters rely on the prose rule alone.

**Prose-path enforcement.** The same forbidden shape written as prose - a `## Operator decisions` block with 2+ items carrying no recommendation marker - is the prose form of a co-equal ballot and is ALSO mechanically enforced on Claude Code: a `Stop` hook (`hooks/enforce-no-abdication.py`, wired by `.claude/install.sh`) detects an `## Operator decisions` block where 2 or more items carry no derived-recommendation marker (a `Recommendation:` lead-in or a `(Recommended)` suffix) and blocks the turn, injecting a corrective directive. This check runs independently of the hook's permission-phrase negative gate, so irreversibility vocabulary in the ballot's items cannot suppress it.

**Detection limits.** The detector recognizes the common list, numbered, and bold-numbered item forms (`- `, `1. `, `**1.`); other item formats (a markdown table, a bold-led item with no number, an unconventional heading wording) are not caught - it is a floor, not a guarantee of coverage.

**Kill switch.** Set `AE_ABDICATION_GUARD_DISABLE=1` to disable (shared kill switch with the rest of that hook). Other adapters rely on the prose rule for both paths.

## Operator Decisions Block Rationale

Detail for the "Operator decisions go last in the turn" kernel rule (`content/sections/02-delegation.md`).

**Why the literal heading.** `## Operator decisions` is required verbatim, not `## Decisions` - the latter is a common heading in project instruction files and would collide with anything that later matches on that string.

**Item content.** Keep each item to the recommended action, one line of why, and the reversal offer.

**Why the marker is not stylistic.** The `(Recommended)` suffix (or `Recommendation:` lead-in) is the single convention that lets both the tool path and the prose path be mechanically distinguished from a co-equal ballot, and it is the exact token the prose-path enforcement checks. An item lacking that marker is indistinguishable, to the enforcement and to a reader, from an unresolved option in a ballot - even a hard-stop item genuinely requiring operator authorization still has one recommended action (the thing that needs doing, pending authorization) and states it with the marker. This block-specific marker requirement is ADDITIONAL to, not a replacement for, the general recommendation-plus-confirmation phrasing described in the surface-and-proceed branch and the AskUserQuestion precondition (e.g. "Proceeding with X unless you say otherwise") - that phrasing remains sufficient on its own for a single surface-and-proceed decision surfaced OUTSIDE this block, where the ballot check can never fire on one item; once 2 or more items live under this heading, each one additionally needs the explicit marker, because that is the only thing that lets the block's enforcement (and a reader) tell a resolved decision item from an unresolved ballot option.

**Cap and overflow.** Do not impose a numeric cap on the number of items - a cap with no overflow rule mechanically forces the conductor to hide a decision, which is the exact harm this rule exists to prevent.

**Placement discipline.** A decision the operator has to scroll past other content to find is a defect - nothing follows the heading (no status line, no next steps, no caveats, no phase breadcrumb, no "meanwhile"), and the turn ends there: no further tool calls. Explanation of why something failed belongs above the heading, and only when it is evidence a decision in this same turn rests on - no analysis inside the block itself. Any per-turn declaration required elsewhere in this methodology (a phase breadcrumb, a first-user-turn notice, a `Capture:` line) is satisfied only by text preceding this heading - never by anything after it.

## Digest-Return Discipline

**Digest-return discipline.** When a loop-running spawn (multi-iteration Skeptic/QA, long investigation) returns from the background, the conductor reads the terminal status, sign-off, falsifiable-claims evidence, residual risk, not-done list, and the optional `learnings_candidate[]` field - then acts. It does not re-read the worker's internal transcript or re-derive findings. This is how the conductor's context stays flat across many parallel loops. When `learnings_candidate[]` is non-empty, the conductor routes each entry through the guardrail-first gate (capture-classification.md) before forwarding `Capture: MUST` entries to `learnings-agent`; see `content/references/conductor-operating-rules.md` §learnings-agent for the routing algorithm. See `content/references/digest-return-pattern.md` for the full digest field list and conductor consumption rules.

## Orchestration Enforcement Hooks and Fan-out Detail

This section holds the mechanical hook detail behind the "Named agents" rule in `content/sections/02-delegation.md` - the acting rules (prefer orchestration-planner, skip-planner conditions, the simple/targeted-unit carve-out, mid-task reclassification, the `general-purpose` fallback, shell/git routing, no-subagent-spawns-subagents, and the Trivial-path worktree-isolated engineer rule) stay inline in the kernel; only the hook mechanics live here.

**Singularity hook.** On Claude Code this is enforced by a `PreToolUse` hook (`hooks/enforce-orchestrator-singularity.py`, wired by `.claude/install.sh`) that denies any `Agent` spawn issued from a subagent context (detected via the `agent_id` field); set `AE_SINGULARITY_GUARD_DISABLE=1` to disable. Other adapters rely on the prose rule.

**Tier-3 escalation hook.** The Mandatory Tier-3 review escalation rule (Risk Classification) is mechanically backstopped on Claude Code by a `PreToolUse` hook (`hooks/enforce-tier.py`, wired by `.claude/install.sh`) that denies an explicit sub-Opus `model` param on a `security-auditor` spawn (always) or a `skeptic` spawn whose brief matches a Tier-3 escalation signal; escalate-only and fail-open, it never blocks the omit-the-param role-default path and does not catch the novel-architecture signal (not keyword-detectable - the conductor and frontmatter default remain the controls there). The hook also backstops the authoring-role escalation (architect / adr-generator / product-discovery on Plan+ADR-tier units, per risk-config-and-tiers.md): it denies an explicit sub-Opus `model` param on those spawns when the brief matches an authoring escalation signal, but the structural Plan+ADR trigger is conductor-computed and invisible to the hook, so the conductor's explicit `model: opus` remains the primary control. Set `AE_TIER_GUARD_DISABLE=1` to disable. Other adapters rely on the prose rule.

**Planning-artifact hook.** The Brief/Plan authoring gate is backed by an advisory PreToolUse(Write/Edit) hook (`hooks/enforce-planning-artifact-spawn.py`) that warns when a `docs/planning/**` artifact is written without a recent architect spawn on record; warn-only, never blocks; set `AE_PLANNING_GUARD_DISABLE=1` to silence.

**Worktree-read hook (DS-150).** A worktree-isolated subagent is meant to reason only against the files inside its own worktree branch; a plain `Read` into the primary checkout defeats isolation silently and surfaces much later as "why did this engineer act on code that isn't in its diff?" On Claude Code this is enforced by a `PreToolUse(Read)` hook (`hooks/enforce-worktree-read.py`, wired by `.claude/install.sh`) that denies a subagent's (`agent_id` present) `Read` when the target resolves inside `CLAUDE_PROJECT_DIR` (the primary root) but outside the payload's `cwd` (the agent's own worktree root, `caller_root`) - and only when `caller_root` is itself a genuine worktree-isolated subdirectory of the primary root. All three operands (target, `caller_root`, `primary_root`) are `realpath`-normalized before the containment test, since isolation worktrees live *inside* the primary root and an unnormalized prefix test is not sufficient. A main-session call (`agent_id` absent) and a non-isolated subagent (`caller_root == primary_root`) always allow - this hook never denies conductor reads. Config-driven exemptions read from `worktree_read_guard_exemptions` in `<primary_root>/.agentic/config.json`, ships empty. Fail-open on any error; set `AE_WORKTREE_READ_GUARD_DISABLE=1` to disable. Other adapters rely on the prose rule in `hooks/AGENTS.md` §Worktree isolation scope.

**Worktree-write hook.** The write-side companion to the worktree-read hook, closing a gap the read hook and `enforce-shippable-edit.py` cannot: a subagent whose worktree was cleaned up mid-task and silently fell back to the primary checkout (`AGENTS.md`'s "across sequential spawns in one task the worktree is cleaned up between them and subsequent Workers fall back to the main tree" note) still carries a present, non-blank `agent_id`, so `enforce-shippable-edit.py`'s agent_id-absence check never fires, and the fallback lands shippable edits directly on the primary checkout. On Claude Code this is enforced by a `PreToolUse(Write/Edit/MultiEdit)` hook (`hooks/enforce-worktree-write.py`, wired by `.claude/install.sh`) that mirrors the read hook's `caller_root`/`primary_root` derivation and `realpath` normalization, denying only when the target resolves inside the primary checkout but outside the agent's own worktree-isolated `caller_root`. One deliberate divergence from the read hook: this hook additionally requires `caller_root`'s `.git` entry to resolve to a genuine LINKED worktree (its gitdir pointer contains a `/worktrees/` segment, not `/modules/`, and is not itself a real directory) before treating it as isolated - an ordinary repo subdirectory, a submodule checkout, or an independent nested clone as `caller_root` all fail open (ALLOW) here. The read hook has no such check and still treats any proper subdirectory of `primary_root` as isolated regardless of its `.git` state, so it retains that broader false positive. Deliberately kept as a separate hook, not merged into `enforce-shippable-edit.py`, since that hook is fail-open-CRITICAL (a false deny there blocks every conductor Write/Edit/MultiEdit for the whole session) and must not be perturbed by a second, unrelated deny axis. Uses a SEPARATE config-driven exemption key, `worktree_write_guard_exemptions` in `<primary_root>/.agentic/config.json` (not the read hook's `worktree_read_guard_exemptions` - writes carry a different risk profile). Fail-open on any error; set `AE_WORKTREE_WRITE_GUARD_DISABLE=1` to disable. Other adapters rely on the prose rule in `hooks/AGENTS.md` §Worktree isolation scope.

**Fan-out `skeptic_strategy` block.** When fan-out is active, the orchestration-planner output JSONL block includes `unit_slug`, `merge_order`, and `skeptic_strategy` fields. Per-unit Skeptic spawning is a valid conductor behavior for parallel fan-out of independent units (complementing the existing "independent elevated units get their own Skeptic" rule in Task Decomposition). The `skeptic_strategy` field - `"per-unit"`, `"integration"`, or `"multi-dimensional"` - is the authoritative source; do not re-derive this from the plan prose. `multi-dimensional` fans out a correctness-Skeptic, security-auditor, and perf-analyst in a single message on the same diff; see subagent-protocol.md for full definition.

## Background-Spawn Enforcement Detail

This section holds the forensic/mechanical detail behind the background-by-default rule in `content/sections/02-delegation.md` - the acting rules (background-by-default itself, the "omit `run_in_background`, never pass `false`" conductor norm, and the `wrap-ticket` synchronous carve-out) stay inline in the kernel; only the payload-capture history and the asymmetric allow/deny mechanics live here.

**Payload capture (2026-07-07).** The harness DOES pass `run_in_background` through to the PreToolUse hook payload for `Agent` spawns (confirmed by live payload capture 2026-07-07 - hook tool_input keys for an Agent spawn observed as `description`/`prompt`/`run_in_background`/`subagent_type`, correcting the earlier assumption that the field was stripped).

**Asymmetric allow/deny mechanics.** `hooks/enforce-background-spawn.py` enforces background-by-default on both `Task` and `Agent`, with an asymmetric rule per tool: on `Agent`, only an explicit `run_in_background: false` is denied - an absent field allows (Agent already backgrounds by default at the harness level, so omitting it is the correct norm) and `true` also allows; on `Task` (legacy), only `run_in_background: true` allows - absent, `false`, or any non-boolean value denies. The hook retains two active responsibilities: (a) `run_in_background` enforcement for both `Task` and `Agent` per the asymmetric rule above, and (b) cross-harness teamrun-sentinel suppression for both `Task` and `Agent` when `.agentic/teamrun/.active` is live.
