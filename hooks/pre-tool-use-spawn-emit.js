#!/usr/bin/env node

/**
 * Purpose: Claude Code PreToolUse(Task/Agent) hook. On every subagent spawn,
 *          appends a spawn_start event to [cwd]/.agentic/events.jsonl with
 *          source:"hook" so the telemetry substrate is populated even in ad-hoc
 *          sessions that do not run /implement-ticket (which emits conductor-side
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
 * Public API: run() - invoked immediately at module load via run() call at the
 *             bottom of the file. Not imported in production; executed as a CLI
 *             script by the Claude Code PreToolUse(Task/Agent) hook.
 *
 * Upstream deps: Node built-ins only (fs, path). No npm dependencies.
 *                Reads PreToolUse payload from stdin (fd 0).
 *                Writes [cwd]/.agentic/events.jsonl via appendFileSync.
 *                Writes [cwd]/.agentic/.last-architect-spawn via writeFileSync
 *                when agentName === 'architect'.
 *                Never reads other .agentic/ files.
 *
 * Downstream consumers: Claude Code PreToolUse(Task/Agent) hook (wired by
 *                        .claude/install.sh; matchers "Task" and "Agent").
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
 *                project with no .agentic/ directory yet.
 *
 * Performance: ~1-3 ms typical (one JSON parse, one mkdir, one appendFileSync).
 *              Runs synchronously on the PreToolUse critical path but is bounded
 *              and fail-open, so latency impact is negligible.
 */

'use strict';

const fs = require('fs');
const path = require('path');

/**
 * Main entry point. Reads PreToolUse payload from stdin, emits spawn_start
 * event to events.jsonl, always exits 0.
 */
function run() {
  try {
    // Read full stdin synchronously.
    const raw = fs.readFileSync('/dev/stdin', 'utf8');
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

run();
