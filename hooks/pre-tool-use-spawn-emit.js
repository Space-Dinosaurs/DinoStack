#!/usr/bin/env node

/**
 * Purpose: Claude Code PreToolUse(Task/Agent) hook. On every subagent spawn,
 *          appends a spawn_start event to [cwd]/.agentic/events.jsonl with
 *          source:"hook" so the telemetry substrate is populated even in ad-hoc
 *          sessions that do not run /ds-implement-ticket (which emits conductor-side
 *          spawn_complete events). This provides deterministic events.jsonl
 *          creation in any session that spawns at least one subagent.
 *
 *          Additionally, when the spawned agent is 'architect', writes a
 *          timestamp sentinel to [cwd]/.agentic/.last-architect-spawn so the
 *          planning-artifact advisory hook (enforce-planning-artifact-spawn.py)
 *          can detect recent architect activity and suppress false-positive
 *          advisories during legitimate Brief/Plan authoring.
 *
 *          NOTE on PostToolUse: PostToolUse fires at async_launched (spawn LAUNCH),
 *          NOT at subagent completion, so there is no wall-time or token data
 *          available from hook payloads. This hook emits spawn_start only, with
 *          tokens_note:"unavailable (harness)" marking the limitation.
 *
 *          DS-160 correlation fields (pairs with hooks/subagent-stop-spawn-emit.js):
 *          each emitted event now carries a self-generated `data.spawn_id`
 *          (crypto.randomUUID(), never null) plus `data.tool_use_id` (from the
 *          PreToolUse payload's top-level `tool_use_id` field, best-effort - may
 *          be absent depending on harness version) and `data.parent_agent_id`
 *          (the top-level `agent_id` field, present only when THIS spawn call is
 *          itself being made from inside a running subagent, i.e. a nested spawn;
 *          null for a normal top-level launch). `spawn_id` is the primary
 *          correlation key the SubagentStop-side hook uses to pair a
 *          spawn_complete event back to this spawn_start; `tool_use_id` is
 *          carried for back-compat with the conductor-emitted schema in
 *          content/references/events-log.md and is not required for pairing.
 *
 * Public API: run() - invoked immediately at module load via run() call at the
 *             bottom of the file. Not imported in production; executed as a CLI
 *             script by the Claude Code PreToolUse(Task/Agent) hook.
 *
 * Upstream deps: Node built-ins only (fs, path, crypto) plus the local
 *                CommonJS module hooks/lib/stdin-guard.js (readStdinGuarded,
 *                bounded stdin reader). No npm dependencies.
 *                Reads PreToolUse payload from stdin (fd 0) via the bounded
 *                reader (see Failure modes).
 *                Writes [cwd]/.agentic/events.jsonl via appendFileSync.
 *                Writes [cwd]/.agentic/.last-architect-spawn via writeFileSync
 *                when agentName === 'architect'.
 *                Never reads other .agentic/ files.
 *
 * Downstream consumers: Claude Code PreToolUse(Task/Agent) hook (wired by
 *                        .claude/install.sh; matchers "Task" and "Agent").
 *                        hooks/subagent-stop-spawn-emit.js (SubagentStop hook)
 *                        reads events.jsonl backward to find this event's
 *                        `data.spawn_id` and pair it with a spawn_complete.
 *                        hooks/stop-context.js scanSessionAggregate() reads
 *                        spawn_start events with data.source==="hook" to count
 *                        spawns in ad-hoc sessions (double-count guard: skipped
 *                        when spawn_complete events exist in the same session).
 *                        hooks/lib/capture-gap.js detectCaptureGap() recognizes
 *                        hook spawn_start for debugger/investigator as
 *                        learning-worthy events (revives capture-gap trigger in
 *                        ad-hoc sessions).
 *
 * Failure modes: Fully fail-open. Entire body wrapped in try/catch; ALWAYS
 *                process.exit(0). Any fs error, parse error, or missing field
 *                is silently swallowed. NEVER writes to stdout (must not
 *                interfere with deny output from other PreToolUse hooks on the
 *                same Task/Agent matcher). NEVER denies: this hook is advisory
 *                telemetry only. mkdirSync({recursive:true}) ensures .agentic/
 *                exists before append, so the hook is safe to fire on a fresh
 *                project with no .agentic/ directory yet. Stdin is read via
 *                lib/stdin-guard.js's readStdinGuarded(), which never rejects
 *                and resolves '' if the spawning harness never closes stdin,
 *                bounding worst-case latency instead of blocking indefinitely
 *                on the previous synchronous fs.readFileSync('/dev/stdin')
 *                read; run() is now async, so the call site additionally
 *                chains `.catch(() => process.exit(0))` (still no stdout
 *                write, ever).
 *
 * Performance: Bounded by hooks/lib/stdin-guard.js's read path (first-byte
 *              timeout, inactivity timeout, absolute deadline, and a
 *              max-bytes cap - see that module for current defaults) rather
 *              than a single synchronous read; run() is async end-to-end
 *              (await readStdinGuarded(), then one JSON.parse, one mkdir,
 *              one appendFileSync). Runs on the PreToolUse critical path but
 *              never blocks it indefinitely - a slow or silent stdin
 *              resolves via one of stdin-guard's bounded routes instead of
 *              hanging.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { readStdinGuarded } = require('./lib/stdin-guard.js');

/**
 * Main entry point. Reads PreToolUse payload from stdin, emits spawn_start
 * event to events.jsonl, always exits 0.
 */
async function run() {
  try {
    // Read stdin with a bounded, never-rejecting reader (see lib/stdin-guard.js).
    const raw = await readStdinGuarded();
    let payload;
    try { payload = JSON.parse(raw); } catch (_) { process.exit(0); }

    // Only fire on Task/Agent spawns.
    const toolName = payload && payload.tool_name;
    if (toolName !== 'Task' && toolName !== 'Agent') process.exit(0);

    // Resolve cwd from payload (top-level field, same as other hooks).
    const cwd = (typeof payload.cwd === 'string' && payload.cwd.trim())
      ? payload.cwd.trim()
      : null;
    if (!cwd) process.exit(0);

    // Resolve session_id (top-level field on PreToolUse payload).
    const sessionId = (typeof payload.session_id === 'string' && payload.session_id.trim())
      ? payload.session_id.trim()
      : null;

    // Resolve agent name from tool_input.subagent_type.
    const toolInput = (payload && typeof payload.tool_input === 'object' && payload.tool_input)
      ? payload.tool_input
      : {};
    const agentName = (typeof toolInput.subagent_type === 'string' && toolInput.subagent_type.trim())
      ? toolInput.subagent_type.trim()
      : 'unknown';

    // Best-effort correlation fields (see DS-160 note in the header comment).
    const toolUseId = (typeof payload.tool_use_id === 'string' && payload.tool_use_id.trim())
      ? payload.tool_use_id.trim()
      : null;
    // agent_id present at the TOP LEVEL of a PreToolUse(Agent) payload means
    // THIS launch call is itself being made from inside a running subagent
    // (a nested spawn) - see hooks/enforce-orchestrator-singularity.py for the
    // same agent_id-presence convention.
    const parentAgentId = (typeof payload.agent_id === 'string' && payload.agent_id.trim())
      ? payload.agent_id.trim()
      : null;
    // Purpose-built correlation key: never null, generated fresh per spawn so
    // hooks/subagent-stop-spawn-emit.js can pair a spawn_complete back to this
    // exact spawn_start regardless of whether the harness threads tool_use_id
    // through to SubagentStop.
    const spawnId = crypto.randomUUID();

    // Ensure .agentic/ dir exists (safe to call even if it already exists).
    const agenticDir = path.join(cwd, '.agentic');
    fs.mkdirSync(agenticDir, { recursive: true });

    // Build and append the spawn_start event.
    const event = {
      ts: new Date().toISOString(),
      phase: 'hook',
      event: 'spawn_start',
      agent: agentName,
      task_id: null,
      data: {
        source: 'hook',
        session_uuid: sessionId || null,
        tokens_note: 'unavailable (harness)',
        spawn_id: spawnId,
        tool_use_id: toolUseId,
        parent_agent_id: parentAgentId,
      },
    };
    const eventsPath = path.join(agenticDir, 'events.jsonl');
    fs.appendFileSync(eventsPath, JSON.stringify(event) + '\n', 'utf8');

    // Write architect sentinel so the planning-artifact advisory hook can
    // detect a recent architect spawn and suppress false-positive warnings
    // during legitimate Brief/Plan authoring.
    if (agentName === 'architect') {
      const sentinelPath = path.join(agenticDir, '.last-architect-spawn');
      fs.writeFileSync(sentinelPath, new Date().toISOString(), 'utf8');
    }

    process.exit(0);
  } catch (_) {
    // Fully fail-open: any unexpected error -> silent exit 0.
    // Never block a spawn; never write to stdout.
    process.exit(0);
  }
}

run().catch(() => process.exit(0));
