<!--
Purpose: Conductor operating rules reference for on-demand consultation.
         Covers permission-blocked fallback, methodology-file editing routing,
         parallel Investigator pattern, wrap-ticket writer carve-out (incl. the
         two lock-aware context.md auto-writers under the deferred-wrap feature),
         and the mandatory learnings capture gate (§learnings-agent). Anti-patterns
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
               content/commands/wrap.md (authoritative `/wrap` write paths and
               wrap/lock scope) and content/commands/wrap-deferred.md (the
               non-interactive single-pass enrichment the daemon runs; owns the
               `pending.json` marker data model and the spillover drain). The
               carve-out points to both rather than restating field semantics.
               hooks/stop-context.js and .opencode/plugins/session-context.ts (the
               two lock-aware context.md auto-writers the carve-out names) and
               hooks/wrap-daemon.js (the per-project daemon that drains the
               spillover by running `/wrap-deferred` headlessly).

Downstream consumers: content/sections/02-delegation.md (inline pointers from
                      each extracted block), content/agents/wrap-ticket.md
                      (required reading directive), content/agents/learnings-
                      agent.md (required reading directive), conductor (applies
                      mandatory trigger protocol at each capture gate).
                      hooks/post-tool-use-capture-nudge.js (the in-session
                      PostToolUse(Task) capture-gap nudge that mechanically
                      surfaces the §learnings-agent "spawn autonomously, do not
                      ask the user" rule mid-session).

Failure modes: Prose reference; does not auto-execute. Permission-blocked
               fallback requires immediate Skeptic on the applied edit -
               skipping that Skeptic is the critical failure mode. learnings-
               agent session file (.agentic/learnings-agent.session) is
               removed by Stop hook on exit; a missed removal blocks re-spawn.
               A mandatory trigger with no Capture: declaration is a protocol
               gap; the Stop-hook backstop is the mechanical catch.
               The deferred-wrap marker data model and lock semantics are owned by
               content/commands/wrap-deferred.md and hooks/wrap-daemon.js; this
               carve-out only summarizes that the two context.md auto-writers are
               lock-aware and that the daemon drains their spillover, and points
               there - it is not the implementation contract, so divergence from
               wrap-deferred.md is the drift risk to watch.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Delegation. Read that section first for the core conductor rules, spawn threshold, and stop-frequency table.

# Conductor operating rules - full reference

## Permission-blocked fallback

This fallback applies exclusively to protocol/infrastructure files that are NOT methodology documents - installer scripts (`install.sh`, `build.sh`), git hooks, project configs, and `settings.json`. It does NOT apply to any file under `~/DinoStack/` - those are governed by `/update-agentic-engineering` (see that command for the authoritative process). The boundary is physical location - any file under `~/DinoStack/` is governed by /update-agentic-engineering regardless of its role; any infrastructure file outside that path is governed by this fallback.

When all three conditions are met:

1. A Worker was spawned to apply an Edit to an infrastructure file outside `~/DinoStack/`.
2. The Worker's return output begins with or contains a BLOCKED status explicitly citing an Edit permission denial by the Claude Code permission system (exact form observed in practice: "BLOCKED - Edit permission was denied by the permission system").
3. No other unblocked edit path is available.

Then: the main session may apply the edit directly, followed immediately by spawning a Skeptic on the applied diff before any further action.

## Editing methodology files

Always route through `/update-agentic-engineering` for edits to `content/**`, `.codex/skill/**`, the build scripts (`.claude/build.sh`, `.codex/build.sh`, `.cursor/build.sh`), `hooks/**`, or `.codex/hooks/**`. These are the methodology and tooling source files; the command exists to handle the git sync (pull before edit, commit+push after) that prevents cross-machine conflicts. Note: `.claude/skills/agentic-engineering/**` files are hardlinks into `content/` (same inodes) - editing them is functionally editing `content/` and they remain in scope via the `content/**` rule. Files outside those paths - docs/, README, top-level config, and regenerated build artifacts under `.claude/commands/`, `.codex/commands/`, `.cursor/commands/` - may be edited directly under the normal Trivial/Elevated tiers; no special routing needed. If you find yourself about to Edit a methodology file in one of the in-scope paths, stop and invoke `/update-agentic-engineering` instead.

## Parallel Investigators

When investigation spans multiple independent surfaces (e.g., backend data layer, frontend components, and database schema each require separate mapping), the conductor MAY spawn multiple Investigators in a single message (parallel, background). Each Investigator scopes to one surface. The conductor then merges their briefs into a single input for one Architect. The Architect receives all surface findings together and makes design decisions on the complete picture. Example: a feature touching API routes, UI components, and a migration can fan out three Investigators (routes, UI, schema) in one message, then pass all three briefs to the Architect. The single-Architect rule still holds - do not spawn separate Architects per surface, as cross-surface consistency is the Architect's job.

## wrap-ticket writer carve-out

wrap-ticket is the **automated writer in Phase 11b** for `MEMORY.md`, `decisions.md` (resolver: AGENTS.md convention -> ./decisions.md -> docs/decisions.md -> docs/adr/ -> create at cwd), and `.agentic/context.md` (append-merge under `## Recent Focus` only). Operators retain manual write rights for these files. `/wrap` retains its own write paths and serializes with wrap-ticket via `.agentic/wrap/lock` (both acquire the same lock; concurrent runs are not permitted). wrap-ticket MUST NOT touch `.agentic/findings.md` (findings-curator owns), `.agentic/qa.md` (qa-engineer owns), `.agentic/tasks.jsonl` / `.agentic/loop-state.json` / `.agentic/batch-state.json` (conductor sole-writer), or any `AGENTS.md` (`/wrap` owns). wrap-ticket failure is soft-fail and NEVER blocks Phase 12 cleanup or PR completion.

**`.agentic/context.md` lock-aware auto-writers (deferred-wrap feature).** Under the deferred / background `/wrap` feature there are **two** lock-aware `context.md` auto-writers, not one: the Node Stop hook (`hooks/stop-context.js`) on Claude Code and the OpenCode plugin (`.opencode/plugins/session-context.ts`). Both check `.agentic/wrap/lock` before writing `context.md`; while the lock is held they **skip** their `context.md` write and append a spillover record to `.agentic/wrap/deferred-activity.jsonl`, which the per-project deferred-wrap daemon drains into the activity block when it runs `/wrap-deferred` and performs its own `context.md` write. Neither hook is "the one/only unlocked `context.md` writer" any longer - both serialize against the daemon's `/wrap-deferred` (and a manual `/wrap`) via `wrap/lock`. The daemon's headless `/wrap-deferred` likewise serializes its own `context.md` write via `.agentic/wrap/lock`, holding the lock only around the narrow Part-A read-merge-write window (not the whole flow); correctness otherwise rests on idempotency (the Part A merge dedups). The daemon is launched by the SessionStart hook (see the daemon `hooks/wrap-daemon.js`); it resumes each cleanly-ended session headlessly and runs the non-interactive single-pass `/wrap-deferred`, which is the sole consumer of the per-session `pending.json` marker - there is no in-session draft-formatter agent. For the `pending.json` / `last-wrap` / `deferred-activity.jsonl` data model and the daemon enrichment protocol, see `content/commands/wrap-deferred.md`.

The distinction in this carve-out between root `MEMORY.md` (wrap-ticket + learnings-agent, append-with-dedup) and `/wrap`'s own paths is unchanged by the deferred-wrap feature: root `MEMORY.md` is not a `/wrap` target and is not added to the `wrap/lock` scope.

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
background (the harness default). Before spawning, check
`.agentic/learnings-agent.session`; if present and its `session_id` matches the
current session, the agent is already active - send the event message to the running
agent rather than re-spawning. When `Capture: MUST` is declared, the conductor writes
the entry or spawns `learnings-agent` autonomously - do not ask the user whether to
capture, do not wait for acknowledgment.

The conductor's message contains: `event_type`, `description`, `resolution`,
`domain_tag`, `severity` (omit `severity` for KNW-producing event types). The agent
writes immediately to `.agentic/learnings.md` with no batching. The Stop hook removes
`.agentic/learnings-agent.session` on session exit.

Supported `event_type` values: `skeptic-resolved`, `error-fixed`,
`tool-failure-workaround`, `architectural-decision`, `cross-component-gotcha`,
`user-pattern`. The `learnings-agent` maps each type to LRN or KNW - see
`content/agents/learnings-agent.md` for the full mapping table.

### Routing hop for `learnings_candidate[]` (new input source)

When a Worker digest (engineer, investigator, or debugger return) contains a non-empty `learnings_candidate[]`, the conductor applies the following per entry BEFORE the trigger 1-5 sweep:

1. Run guardrail-first classification (steps a, b, c from capture-classification.md).
2. If `Capture: MUST`:
   a. If `kind == "workaround"`, also emit the `tool_failure_workaround` event with all four canonical fields:

      ```bash
      agentic-emit tool_failure_workaround - - \
        '{"session_uuid":"'"$CLAUDE_CODE_SESSION_ID"'","tool":"<tool/command named in fact if identifiable, else the entry domain_tag>","domain_tag":"<entry domain_tag>","note":"<entry fact>"}'
      ```

      For worker-internal discoveries where no distinct tool/command is named, `tool` falls back to the entry's `domain_tag` (a documented same-value fill, not a dropped field). All four keys are always present so `agentic-cost` does not miscount.
   b. Forward to `learnings-agent` with: `event_type` per the kind map (`workaround` -> `tool-failure-workaround`; `dead-end` -> `cross-component-gotcha`; `gotcha` -> `cross-component-gotcha`; `decision` -> `architectural-decision`), `description` = entry `fact`, `resolution` = entry `why`, `domain_tag` = entry `domain_tag`, and omit `severity` (all mapped types are KNW).
3. If `Capture: SKIP`: declare `Capture: SKIP - [reason]` inline and proceed.

**Relation to triggers 1-5.** `learnings_candidate[]` is a new INPUT SOURCE for the existing trigger machinery, not a 7th trigger. `kind: workaround` is a new input path for trigger 3; `kind: dead-end`/`gotcha` map to `cross-component-gotcha`; `kind: decision` is a new input path for trigger 5. Trigger 1 (investigator/debugger root cause) is NOT replaced - the conductor still evaluates the root cause under trigger 1 independently, and the `learnings_candidate[]` section on those agents' returns carries incidental discoveries only, never the root cause itself.

**Trivial-path engineers.** A Trivial engineer skips Skeptic and wrap-ticket, but the conductor still reads its return. `learnings_candidate[]` entries that pass `Capture: MUST` are still routed to `learnings-agent`. The lightweight Trivial posture (no Skeptic, no brief) is otherwise preserved.

**Cap discipline.** Workers emit at most 5 entries. If a malformed return carries more, the conductor processes the first 5 and logs a warning.

This is additive - `/wrap` still handles AGENTS.md updates, rolling session labels,
compression, and full session wrap. If learnings-agent fails, the conductor warns
and proceeds (soft-fail).
