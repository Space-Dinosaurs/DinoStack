<!--
Purpose: Conductor operating rules reference for on-demand consultation.
         Covers permission-blocked fallback, methodology-file editing routing,
         parallel Investigator pattern, wrap-ticket writer carve-out, and
         the mandatory learnings capture gate (§learnings-agent). Anti-patterns
         and Common rationalizations were reverted to content/sections/02-
         delegation.md (hot-path rules belong inline, not in a reference).

Public API: Read-only reference. Load on trigger when conductor encounters a
            permission-blocked Worker return, methodology-file edit request,
            multi-surface investigation need, wrap-ticket sequencing question,
            or any mandatory-capture trigger (see §learnings-agent).

Upstream deps: content/sections/02-delegation.md (parent section; gate rules,
               spawn threshold, and stop-frequency table live there).
               content/references/capture-classification.md (guardrail-first
               precedence chain and two-gate MUST/SHOULD/SKIP table).
               content/agents/wrap-ticket.md, content/agents/learnings-agent.md.

Downstream consumers: content/sections/02-delegation.md (inline pointers from
                      each extracted block), content/agents/wrap-ticket.md
                      (required reading directive), content/agents/learnings-
                      agent.md (required reading directive), conductor (applies
                      mandatory trigger protocol at each capture gate).

Failure modes: Prose reference; does not auto-execute. Permission-blocked
               fallback requires immediate Skeptic on the applied edit -
               skipping that Skeptic is the critical failure mode. learnings-
               agent session file (.agentic/learnings-agent.session) is
               removed by Stop hook on exit; a missed removal blocks re-spawn.
               A mandatory trigger with no Capture: declaration is a protocol
               gap; the Stop-hook backstop is the mechanical catch.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Delegation. Read that section first for the core conductor rules, spawn threshold, and stop-frequency table.

# Conductor operating rules - full reference

## Permission-blocked fallback

This fallback applies exclusively to protocol/infrastructure files that are NOT methodology documents - installer scripts (`install.sh`, `build.sh`), git hooks, project configs, and `settings.json`. It does NOT apply to any file under `~/agentic-engineering/` - those are governed by `/update-agentic-engineering` (see that command for the authoritative process). The boundary is physical location - any file under `~/agentic-engineering/` is governed by /update-agentic-engineering regardless of its role; any infrastructure file outside that path is governed by this fallback.

When all three conditions are met:

1. A Worker was spawned to apply an Edit to an infrastructure file outside `~/agentic-engineering/`.
2. The Worker's return output begins with or contains a BLOCKED status explicitly citing an Edit permission denial by the Claude Code permission system (exact form observed in practice: "BLOCKED - Edit permission was denied by the permission system").
3. No other unblocked edit path is available.

Then: the main session may apply the edit directly, followed immediately by spawning a Skeptic on the applied diff before any further action.

## Never idle behind review

**Principle: review gates the merge, not the existence of the PR.** Ship-then-review-in-parallel. A background Skeptic or QA agent is a gate on merging, never a barrier the conductor sits behind in silence. The defect this rule fixes: an engineer returns gated-clean, shippable code, the conductor has already spawned a background review, and the conductor then ends its turn in a passive "waiting on the review agent" state - producing minutes-to-hours of user-facing silence on a change that was ready to ship. Background spawning is correct; going silent behind it is the failure.

**Trigger.** The engineer's output passes the project's typecheck/lint/build gates. At that moment the conductor:

1. Opens the PR immediately. Mark it draft when a Skeptic or QA pass is still outstanding; mark it ready when review is already clean.
2. Spawns (or continues) the Skeptic/QA review in parallel, running against the open PR.
3. Folds any real findings in as follow-up commits on the same branch, and flips the draft to ready once review is clean.

The open PR is the surface the review runs against. The review still gates the merge - a draft PR does not merge until review is clean - but it does not gate the PR's existence.

**Prohibition.** The conductor MUST NOT end a turn whose only remaining "next step" is waiting on a background review when a shippable, gated-clean artifact already exists. If there is something to ship, ship it (draft) and let the review run concurrently; do not return to the user with "waiting on the Skeptic/QA agent" as the sole next action.

**Wait cap.** If a background review or QA agent runs long past a reasonable wall-clock bound and a gated-clean artifact exists, the conductor proceeds - opens the PR, posts status - and reconciles the agent's findings when they return. A slow review agent must never translate into user-facing silence.

**Match orchestration weight to task size.** Size the agent chain to the risk. A small single-surface change does not warrant a long serial investigator -> engineer -> Skeptic relay run to completion before any user-facing progress; size the relay to the Risk Classification and risk-profile tiers (see METHODOLOGY.md §Risk Classification and the risk profiles) rather than running the heaviest chain by reflex. Lighter tasks ship sooner and review in parallel.

**Consistency.** This is the same parallel-by-default philosophy as concurrent QA + Skeptic (see METHODOLOGY.md §QA Gate): review runs alongside, not in front of, the work. The hard-stop branch is never bypassed - a draft PR is fine, but an irreversible or destructive action without authorization is not. Opening a draft PR is reversible (close it); executing a migration, force push, production deploy, or external send is not. Ship-then-review applies to the reversible ship step only.

## Editing methodology files

Always route through `/update-agentic-engineering` for edits to `content/**`, `.codex/skill/**`, the build scripts (`.claude/build.sh`, `.codex/build.sh`, `.cursor/build.sh`), `hooks/**`, or `.codex/hooks/**`. These are the methodology and tooling source files; the command exists to handle the git sync (pull before edit, commit+push after) that prevents cross-machine conflicts. Note: `.claude/skills/agentic-engineering/**` files are hardlinks into `content/` (same inodes) - editing them is functionally editing `content/` and they remain in scope via the `content/**` rule. Files outside those paths - docs/, README, top-level config, and regenerated build artifacts under `.claude/commands/`, `.codex/commands/`, `.cursor/commands/` - may be edited directly under the normal Trivial/Elevated tiers; no special routing needed. If you find yourself about to Edit a methodology file in one of the in-scope paths, stop and invoke `/update-agentic-engineering` instead.

## Parallel Investigators

When investigation spans multiple independent surfaces (e.g., backend data layer, frontend components, and database schema each require separate mapping), the conductor MAY spawn multiple Investigators in a single message (parallel, background). Each Investigator scopes to one surface. The conductor then merges their briefs into a single input for one Architect. The Architect receives all surface findings together and makes design decisions on the complete picture. Example: a feature touching API routes, UI components, and a migration can fan out three Investigators (routes, UI, schema) in one message, then pass all three briefs to the Architect. The single-Architect rule still holds - do not spawn separate Architects per surface, as cross-surface consistency is the Architect's job.

## wrap-ticket writer carve-out

wrap-ticket is the **automated writer in Phase 11b** for `MEMORY.md`, `decisions.md` (resolver: AGENTS.md convention -> ./decisions.md -> docs/decisions.md -> docs/adr/ -> create at cwd), and `.agentic/context.md` (append-merge under `## Recent Focus` only). Operators retain manual write rights for these files. The Stop hook retains its `.agentic/context.md` auto-write. `/wrap` retains its own write paths and serializes with wrap-ticket via `.agentic/wrap.lock` (both acquire the same lock; concurrent runs are not permitted). wrap-ticket MUST NOT touch `.agentic/findings.md` (findings-curator owns), `.agentic/qa.md` (qa-engineer owns), `.agentic/tasks.jsonl` / `.agentic/loop-state.json` / `.agentic/batch-state.json` (conductor sole-writer), or any `AGENTS.md` (`/wrap` owns). wrap-ticket failure is soft-fail and NEVER blocks Phase 12 cleanup or PR completion.

## learnings-agent background capture

> **MANDATORY PROTOCOL GATE.** This section replaces discretionary capture with a
> mandatory trigger protocol. The conductor MUST evaluate capture at each trigger
> below and emit a `Capture:` declaration. Skipping the declaration is a protocol
> gap. See `content/references/capture-classification.md` for the guardrail-first
> precedence chain that runs BEFORE this gate.

> **Two feeders, distinct triggers.** `learning-extractor` is mechanically wired to
> `/implement-ticket` Phase 6 clean exit and fires automatically - the conductor does
> NOT spawn it manually. `learnings-agent` (described here) is triggered by the 6
> mandatory events below; the conductor spawns it the first time a trigger fires in
> a session.

### Mandatory triggers

The conductor MUST evaluate capture at each of these 6 events and emit a
`Capture:` declaration (format below) before proceeding:

1. **Investigator or debugger returns a root cause.** Any investigator/debugger
   brief that names a root cause is a trigger. Apply guardrail-first (can a test
   encode this?) then write KNW or LRN as appropriate.

2. **A Critical or Major Skeptic finding is resolved.** After sign-off, evaluate
   whether the fix pattern is generalizable. LRN if the bug recurs, KNW if it is
   env/tooling knowledge.

3. **A tool or command failure is worked around.** At the workaround moment, the
   conductor MUST also emit a `tool_failure_workaround` event to `.agentic/events.jsonl`:

   ```bash
   agentic-emit tool_failure_workaround - - \
     '{"session_uuid":"'"$CLAUDE_CODE_SESSION_ID"'","tool":"<name>","domain_tag":"<tag>","note":"<one sentence>"}'
   ```

   Then declare a Capture decision. The `tool_failure_workaround` event type is
   defined in `content/references/events-log.md`; this is the emit site. KNW is
   the typical entry type for tool/env workarounds.

4. **An error->fix loop closes** (especially after multiple attempts). When an
   engineer fix pass resolves a quality-gate failure that required more than one
   attempt, evaluate whether the fix pattern is worth recording. LRN if the bug
   class will recur; SKIP if the diff already makes it self-evident.

5. **An architectural decision is made during implementation.** When the conductor
   or a Worker makes a design choice that constrains future work (not just a
   style preference), evaluate capture. KNW is the typical type; MEMORY.md is
   the alternative home if it is project-wide and permanent.

6. **End-of-task or end-of-session capture sweep.** Before declaring a task
   complete or closing a session, sweep for any trigger 1-5 events that occurred
   but were not yet evaluated. Declare `Capture: SKIP` or `Capture: MUST` for
   each outstanding event. This is the last-resort catch before the Stop-hook
   backstop fires.

### Per-trigger declaration format

Mirrors the Risk declaration block. Emit at the trigger event:

```
Capture: MUST - [signal]. Writing KNW/LRN entry.
Capture: SKIP - [guardrail added | already in AGENTS.md | one-off].
```

A trigger event with no declaration is a protocol gap. The Stop-hook backstop
(`hooks/stop-context.js` `detectCaptureGap`) is the mechanical catch for missed
declarations, but the conductor's inline declaration is the primary gate.

### Guardrail-first precedence

Before writing any entry, run the three-step check from
`content/references/capture-classification.md`:

(a) Can this be a guardrail (test, type, lint rule, schema, assertion, CI check)?
    If yes, write the guardrail and SKIP the learning (or write only the residual WHY).
(b) Already covered by an existing guardrail, AGENTS.md, MEMORY.md, or the diff? SKIP.
(c) Apply the two-gate MUST/SHOULD/SKIP table from capture-classification.md.

### Spawning learnings-agent

When `Capture: MUST` is declared, the conductor spawns `learnings-agent` in the
background with `run_in_background: true`. Before spawning, check
`.agentic/learnings-agent.session`; if present and its `session_id` matches the
current session, the agent is already active - send the event message to the running
agent rather than re-spawning.

The conductor's message contains: `event_type`, `description`, `resolution`,
`domain_tag`, `severity` (omit `severity` for KNW-producing event types). The agent
writes immediately to `.agentic/learnings.md` with no batching. The Stop hook removes
`.agentic/learnings-agent.session` on session exit.

Supported `event_type` values: `skeptic-resolved`, `error-fixed`,
`tool-failure-workaround`, `architectural-decision`, `cross-component-gotcha`,
`user-pattern`. The `learnings-agent` maps each type to LRN or KNW - see
`content/agents/learnings-agent.md` for the full mapping table.

This is additive - `/wrap` still handles AGENTS.md updates, rolling session labels,
compression, and full session wrap. If learnings-agent fails, the conductor warns
and proceeds (soft-fail).
