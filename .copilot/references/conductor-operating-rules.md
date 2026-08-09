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
               spawn threshold, stop-frequency table, and §Standing authorizations
               live there).
               content/references/capture-classification.md (guardrail-first
               precedence chain and two-gate MUST/SHOULD/SKIP table).
               content/references/worktree-lifecycle.md §Standing authorizations
               (worked example of trigger 6's detection-not-tiebreak-execution
               clause: a harness conflict resolved by an existing standing
               authorization, with no tiebreak step run).
               content/agents/wrap-ticket.md, content/agents/learnings-agent.md.
               content/commands/ds-wrap.md (authoritative `/ds-wrap` write paths and
               wrap/lock scope) and content/commands/ds-wrap-deferred.md (the
               non-interactive single-pass enrichment the daemon runs; owns the
               `pending.json` marker data model and the spillover drain). The
               carve-out points to both rather than restating field semantics.
               hooks/stop-context.js and .opencode/plugins/session-context.ts (the
               two lock-aware context.md auto-writers the carve-out names) and
               hooks/wrap-daemon.js (the per-project daemon that drains the
               spillover by running `/ds-wrap-deferred` headlessly).

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
               content/commands/ds-wrap-deferred.md and hooks/wrap-daemon.js; this
               carve-out only summarizes that the two context.md auto-writers are
               lock-aware and that the daemon drains their spillover, and points
               there - it is not the implementation contract, so divergence from
               wrap-deferred.md is the drift risk to watch.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Delegation. Read that section first for the core conductor rules, spawn threshold, and stop-frequency table.

# Conductor operating rules - full reference

## Permission-blocked fallback

This fallback applies exclusively to protocol/infrastructure files that are NOT methodology documents - installer scripts (`install.sh`, `build.sh`), git hooks, project configs, and `settings.json`. It does NOT apply to any file under `~/DinoStack/` - those are governed by `/ds-update-agentic-engineering` (see that command for the authoritative process). The boundary is physical location - any file under `~/DinoStack/` is governed by /ds-update-agentic-engineering regardless of its role; any infrastructure file outside that path is governed by this fallback.

When all three conditions are met:

1. A Worker was spawned to apply an Edit to an infrastructure file outside `~/DinoStack/`.
2. The Worker's return output begins with or contains a BLOCKED status explicitly citing an Edit permission denial by the Claude Code permission system (exact form observed in practice: "BLOCKED - Edit permission was denied by the permission system").
3. No other unblocked edit path is available.

Then: the main session may apply the edit directly, followed immediately by spawning a Skeptic on the applied diff before any further action.

## Editing methodology files

Always route through `/ds-update-agentic-engineering` for edits to `content/**`, Codex native-skill generation inputs or outputs (`.codex/skill-frontmatter/**`, `.codex/skill-compatibility.yml`, `scripts/codex-skills.py`, `.codex/skills/**`), the build scripts (`.claude/build.sh`, `.codex/build.sh`, `.cursor/build.sh`), `hooks/**`, or `.codex/hooks/**`. These are the methodology and tooling source files; the command exists to handle the git sync (pull before edit, commit+push after) that prevents cross-machine conflicts. Note: `.claude/skills/dinostack/{agents,commands,references,rules}` are symlink blobs (mode `120000`) pointing at the sibling `content/` directories, not hardlinks - editing through them resolves to editing `content/` and they remain in scope via the `content/**` rule. Files outside those paths - docs/, README, top-level config, and regenerated build artifacts under `.claude/commands/`, `.codex/commands/`, `.cursor/commands/` - may be edited directly under the normal Trivial/Elevated tiers; no special routing needed. If you find yourself about to Edit a methodology file in one of the in-scope paths, stop and invoke `/ds-update-agentic-engineering` instead.

## Parallel Investigators

When investigation spans multiple independent surfaces (e.g., backend data layer, frontend components, and database schema each require separate mapping), the conductor MAY spawn multiple Investigators in a single message (parallel, background). Each Investigator scopes to one surface. The conductor then merges their briefs into a single input for one Architect. The Architect receives all surface findings together and makes design decisions on the complete picture. Example: a feature touching API routes, UI components, and a migration can fan out three Investigators (routes, UI, schema) in one message, then pass all three briefs to the Architect. The single-Architect rule still holds - do not spawn separate Architects per surface, as cross-surface consistency is the Architect's job.

## wrap-ticket writer carve-out

wrap-ticket is the **automated writer in Phase 11b** for `MEMORY.md`, `decisions.md` (resolver: AGENTS.md convention -> ./decisions.md -> docs/decisions.md -> docs/adr/ -> create at cwd), and `.agentic/_wrap.md` (append-merge under `## Recent Focus` only - **not** `.agentic/context.md`, which is now a derived rollup that would discard the write on the next turn; see the writer contract below). Operators retain manual write rights for these files. `/ds-wrap` retains its own write paths and serializes with wrap-ticket via `.agentic/wrap/lock` (the conductor acquires this lock on wrap-ticket's behalf before every Phase 11b spawn - see `content/commands/ds-implement-ticket.md` Phase 11b's bounded-wait acquisition contract; wrap-ticket itself has no Bash tool and never acquires the lock. `/ds-wrap` acquires it directly for its own pre-flight; concurrent holds are not permitted). wrap-ticket MUST NOT touch `.agentic/findings.md` (findings-curator owns), `.agentic/qa.md` (conductor owns - qa-engineer performs no file writes and returns entries as a payload instead), `.agentic/tasks.jsonl` / any loop-state file - the per-ticket `.agentic/loop-state-<LOOP_KEY>.json` and the legacy `.agentic/loop-state.json` alike - / `.agentic/batch-state.json` (conductor sole-writer across agents - not across sessions for `tasks.jsonl`; see `content/references/task-state-file.md`), or any `AGENTS.md` (`/ds-wrap` owns). wrap-ticket failure is soft-fail and NEVER blocks Phase 12 cleanup or PR completion.

**`.agentic/context.md` writer contract: a DERIVED rollup, deliberately lock-free.**

`.agentic/context.md` is not a file anyone writes directly. It is recomposed on every turn as a pure function of two inputs:

- **`.agentic/_wrap.md`** - the CURATED region: everything up to the `## Session Activity` sentinel, including `## Recent Focus` and its 10-slot rolling session-label window. Owned by `/ds-wrap` Part A, `/ds-wrap-deferred`, `wrap-ticket`, and a conductor-direct context write. The rolling-window algorithm in `content/references/wrap-context-format.md` is unchanged; only the path it reads and writes moved.
- **`.agentic/context.d/<session_id>.md`** - one per-session activity SHARD: everything from the sentinel onward, regenerated wholesale. Written by the Claude Stop hook (`hooks/stop-context.js`), the OpenCode plugin (`.opencode/plugins/session-context.ts`), and `bin/ds-migrate`.

**The read contract is unchanged:** every session still reads `.agentic/context.md` as its first action.

**What this replaces, and why it is stated at length.** The previous version of this paragraph asserted that there were "two lock-aware `context.md` auto-writers" which "both check `.agentic/wrap/lock` before writing" and therefore "both serialize against the daemon". Three of those claims were false:

1. There were **13 writer sites across 9 files**, not two.
2. The OpenCode plugin checked nothing - grepping `wrap/lock|wrapLock|lockHeld|deferred-activity|spill` in it returned **zero** matches, and it had two unconditional whole-file writers.
3. Checking a lock without ACQUIRING it provides **no mutual exclusion between the checkers**. Both Stop-hook writers checked and neither acquired, so two concurrent hooks both saw it free and both whole-file-wrote.

Compounding that, a `role:'agent'` lock carries `pid: null` by construction, so its liveness verdict is `live` forever and, on the default config (`deferred_wrap_daemon: false`), no code path could ever clear it. Measured live in this repo: a lock held **10.3 hours** by a dead pid, during which **49 `context.md` writes across 6 sessions were silently discarded** - from the file every session reads first, so all six started from stale context and none of them knew.

**The fix and its invariants.** Writers write session-private shards, so they cannot collide. The rollup is derivable, so a lost update SELF-HEALS on the next turn instead of losing data - which is what makes the rollup write safe WITHOUT a lock, and what lets a `WRAP-LOCK-STUCK` banner reach the operator through the very lock it is reporting. Do not add a lock check to the rollup write; doing so restores all three defects in one edit. `/ds-wrap`'s genuine read-modify-write of `_wrap.md` is the write this fix is scoped to protect - it is not the lock's only guarded file; the paragraph below gives the fuller, non-exhaustive scope. The lock also carries a `session_id` and is cleared by `ds-wrap-acquire-lock` once provably abandoned, so it can no longer be immortal.

`.agentic/wrap/deferred-activity.jsonl` is **no longer produced** - spillover existed only because a held lock skipped the write. `/ds-wrap` Part A still DRAINS a pre-existing file (the drain step is unchanged), so records preserved from before this change are not orphaned. The daemon is launched by the SessionStart hook (`hooks/wrap-daemon.js`); it resumes each cleanly-ended session headlessly and runs the non-interactive single-pass `/ds-wrap-deferred`, the sole consumer of the per-session `pending.json` marker - there is no in-session draft-formatter agent. For the `pending.json` / `last-wrap` / `deferred-activity.jsonl` data model and the daemon enrichment protocol, see `content/commands/ds-wrap-deferred.md`.

Root `MEMORY.md` is written by wrap-ticket and learnings-agent (append-with-dedup), `/ds-memory-update` (interactive), `/ds-init-project`'s CLAUDE.md-split Worker (one-time), and - as of DS-90 - `/ds-wrap` Part B (staging-drain promotion, capped 3/run) and Part E (compression). Because `/ds-wrap` performs a genuine read-modify-write of root `MEMORY.md`, it IS within the `wrap/lock` scope. The lock's actual scope is broader than a short list can stay accurate for: at minimum it also covers `_wrap.md`, `.agentic/compression-state.json`, `decisions.md` (shared with `/ds-implement-ticket` - see that command's "The lock is shared with" note), and - as of DS-90 - `.agentic/memory.md` and `.agentic/memory-pending.md`, both rewritten inside the held lock by Part B. Treat this as a non-exhaustive list of files known to be in scope, not a closed enumeration. `wrap-ticket` already serializes on that same lock before every Phase 11b spawn, so its own append-writes to `MEMORY.md` are unaffected by this addition. Part G commits root `MEMORY.md` when it survives gating, but Part G runs OUTSIDE the lock (after release) and authors no content of its own - it is a verbatim copy-and-commit of whatever Part B/E already wrote.

## learnings-agent background capture

> **MANDATORY PROTOCOL GATE.** This section replaces discretionary capture with a
> mandatory trigger protocol. The conductor MUST evaluate capture at each trigger
> below and emit a `Capture:` declaration. Skipping the declaration is a protocol
> gap. See `content/references/capture-classification.md` for the guardrail-first
> precedence chain that runs BEFORE this gate.

> **Two feeders, distinct triggers.** `learning-extractor` is mechanically wired to
> `/ds-implement-ticket` Phase 6 clean exit and fires automatically - the conductor does
> NOT spawn it manually. `learnings-agent` (described here) is triggered by the 7
> mandatory events below; the conductor spawns it the first time a trigger fires in
> a session.

### Mandatory triggers

The conductor MUST evaluate capture at each of these 7 events and emit a
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
   ds-emit tool_failure_workaround - - \
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

6. **An instruction-layer contradiction is detected and resolved by tiebreak.** Two
   same-tier instructions conflicted (see METHODOLOGY.md §Delegation, Equal-precedence
   tiebreak). Write KNW (`event_type: architectural-decision` when the resolution
   constrains future work, `cross-component-gotcha` otherwise) naming both loci by
   `file:line`, which tiebreak step applied, and the resolution. **Recording satisfies
   this trigger.** Guardrail-first still applies - a doc correction or a grep-able CI
   check is the durable fix and is the better capture - but it MAY be deferred to a
   follow-up unit or ticket: do NOT open a shippable edit mid-decision to satisfy this
   trigger. Never SKIP on the grounds that the tiebreak already resolved it; an
   unrecorded contradiction is re-litigated by every later session at full cost.

   **A host-harness instruction conflict counts as an instruction-layer contradiction
   for this trigger's purposes** - a harness system prompt that contradicts a
   standing AE rule is the same class of event as two same-tier AE instructions
   conflicting, and is evaluated on the same terms. This trigger fires on
   **detection**, not on tiebreak execution: it applies equally when a standing
   authorization or an existing AE rule resolved the conflict outright and no
   tiebreak step actually ran (see `content/references/worktree-lifecycle.md`
   §Standing authorizations and `content/sections/02-delegation.md` §Standing
   authorizations for a worked example). Because the harness prompt carries no
   `file:line` of its own, the entry must name the harness clause (quoted or
   closely paraphrased) alongside the AE locus by `file:line` that resolved it.

7. **End-of-task or end-of-session capture sweep.** Before declaring a task
   complete or closing a session, sweep for any trigger 1-6 events that occurred
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

When a Worker digest (engineer, investigator, or debugger return) contains a non-empty `learnings_candidate[]`, the conductor applies the following per entry BEFORE the trigger 1-6 sweep:

1. Run guardrail-first classification (steps a, b, c from capture-classification.md).
2. If `Capture: MUST`:
   a. If `kind == "workaround"`, also emit the `tool_failure_workaround` event with all four canonical fields:

      ```bash
      ds-emit tool_failure_workaround - - \
        '{"session_uuid":"'"$CLAUDE_CODE_SESSION_ID"'","tool":"<tool/command named in fact if identifiable, else the entry domain_tag>","domain_tag":"<entry domain_tag>","note":"<entry fact>"}'
      ```

      For worker-internal discoveries where no distinct tool/command is named, `tool` falls back to the entry's `domain_tag` (a documented same-value fill, not a dropped field). All four keys are always present so `ds-cost` does not miscount.
   b. Forward to `learnings-agent` with: `event_type` per the kind map (`workaround` -> `tool-failure-workaround`; `dead-end` -> `cross-component-gotcha`; `gotcha` -> `cross-component-gotcha`; `decision` -> `architectural-decision`), `description` = entry `fact`, `resolution` = entry `why`, `domain_tag` = entry `domain_tag`, and omit `severity` (all mapped types are KNW).
3. If `Capture: SKIP`: declare `Capture: SKIP - [reason]` inline and proceed.

**Relation to the mandatory triggers.** `learnings_candidate[]` is a new INPUT SOURCE for the existing trigger machinery, not an additional trigger. `kind: workaround` is a new input path for trigger 3; `kind: dead-end`/`gotcha` map to `cross-component-gotcha`; `kind: decision` is a new input path for trigger 5. Trigger 1 (investigator/debugger root cause) is NOT replaced - the conductor still evaluates the root cause under trigger 1 independently, and the `learnings_candidate[]` section on those agents' returns carries incidental discoveries only, never the root cause itself.

**Trivial-path engineers.** A Trivial engineer skips Skeptic and wrap-ticket, but the conductor still reads its return. `learnings_candidate[]` entries that pass `Capture: MUST` are still routed to `learnings-agent`. The lightweight Trivial posture (no Skeptic, no brief) is otherwise preserved.

**Cap discipline.** Workers emit at most 5 entries. If a malformed return carries more, the conductor processes the first 5 and logs a warning.

This is additive - `/ds-wrap` still handles AGENTS.md updates, rolling session labels,
compression, and full session wrap. If learnings-agent fails, the conductor warns
and proceeds (soft-fail).
