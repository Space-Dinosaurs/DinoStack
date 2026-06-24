#!/usr/bin/env node

/**
 * Purpose: Claude Code PostToolUse(Task) hook that surfaces an in-session
 *          capture-gap nudge. When a Task spawn launches (async_launched) and the
 *          session has a learning-worthy event with no learning captured yet, the
 *          hook prints a hookSpecificOutput.additionalContext message so the
 *          conductor emits its Capture: declaration and spawns learnings-agent
 *          autonomously - in-session, not waiting for the Stop-hook backstop. This
 *          closes the gap where free-form (non-/implement-ticket) sessions skip
 *          mandatory capture or ask the user.
 *
 * Public API: run() - invoked immediately at module load via run() call at the
 *             bottom of the file. Not imported in production; executed as a CLI
 *             script by the Claude Code PostToolUse(Task) hook. The test loads it
 *             via a tmp shim that suppresses run() and exercises the body.
 *
 * Upstream deps: Node built-ins only (fs, path) plus the local CommonJS module
 *                hooks/lib/capture-gap.js (detectCaptureGap). No npm dependencies.
 *                Reads PostToolUse payload from stdin (fd 0); reads
 *                [cwd]/.agentic/.capture-gap-surfaced (dedup tracker, fail-open);
 *                detectCaptureGap reads [cwd]/.agentic/events.jsonl,
 *                [cwd]/.agentic/learnings.md, [cwd]/.agentic/.capture-gap-last-sweep
 *                (cursor READ only), and runs one git diff subprocess.
 *                Writes ONLY [cwd]/.agentic/.capture-gap-surfaced (atomic
 *                tmp+rename). NEVER writes .capture-gap-last-sweep (owned by
 *                stop-context.js) and NEVER writes learnings.md / context.md.
 *
 * Downstream consumers: Claude Code PostToolUse(Task) hook (wired by
 *                        .claude/install.sh; matcher "Task"). The conductor reads
 *                        the additionalContext message next to the Task tool result.
 *
 * Failure modes: Fully soft-fail. The entire body is wrapped in try/catch and
 *                always process.exit(0) - the hook NEVER blocks a spawn, never
 *                writes to stderr, never emits non-JSON to stdout. Malformed
 *                stdin, a non-Task tool, a non-async_launched response, an absent
 *                dedup tracker, a detector error, or a tracker-write failure all
 *                resolve to a silent exit 0. The dedup tracker is fail-open: a
 *                missing or unreadable tracker is treated as "not yet surfaced"
 *                so the nudge fires (a duplicate nudge is cheaper than a missed
 *                one). The (session_id, lastEventTs) tuple keys the dedup so a
 *                single worthy event nudges at most once per session.
 *
 * Performance: ~5-20 ms typical; detectCaptureGap's git subprocess (5 s timeout)
 *              runs only once a worthy event is found, so the common no-event
 *              spawn costs a single events.jsonl read and returns early.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { detectCaptureGap } = require('./lib/capture-gap.js');

// Verbatim nudge texts (handoff section 3). The standard variant fires when no
// guardrail was added this session; the residualOnly variant fires when a
// guardrail was added but is not domain-proximate to the learning-worthy event.
const NUDGE_STANDARD =
  'CAPTURE-NUDGE: a learning-worthy event occurred this session (debugger/investigator root '
  + 'cause, skeptic major/critical resolved, or tool-failure workaround) but no learning has '
  + 'been captured yet. Emit your Capture: declaration now. If Capture: MUST, spawn '
  + 'learnings-agent autonomously - do not ask the user whether to capture.';

const NUDGE_RESIDUAL =
  'CAPTURE-NUDGE: a related guardrail was added this session but is not domain-proximate to '
  + 'the learning-worthy event. Emit your Capture: declaration now for any residual WHY or '
  + 'dead-end reasoning. If Capture: MUST, spawn learnings-agent autonomously.';

/**
 * Read the dedup tracker and return true if this (session_id, lastEventTs) tuple
 * was already surfaced this session. Fail-open: a missing or unreadable tracker
 * returns false (treat as "not surfaced" so the nudge fires).
 *
 * Tracker format: one JSON object per line, { session_id, last_event_ts }.
 *
 * @param {string} cwd - Project root.
 * @param {string} sessionId
 * @param {string|null} lastEventTs
 * @returns {boolean}
 */
function alreadySurfaced(cwd, sessionId, lastEventTs) {
  try {
    const trackerPath = path.join(cwd, '.agentic', '.capture-gap-surfaced');
    if (!fs.existsSync(trackerPath)) return false;
    const raw = fs.readFileSync(trackerPath, 'utf8');
    for (const line of raw.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let obj;
      try { obj = JSON.parse(trimmed); } catch (_) { continue; }
      if (obj && obj.session_id === sessionId && obj.last_event_ts === lastEventTs) {
        return true;
      }
    }
    return false;
  } catch (_) {
    // Fail-open: on any read error, treat as not surfaced (fire the nudge).
    return false;
  }
}

/**
 * Append a dedup entry for this (session_id, lastEventTs) tuple. Atomic via
 * read-existing + tmp-write + rename so a concurrent reader never sees a partial
 * file. Silent failure - a missed write at worst re-nudges next spawn.
 *
 * @param {string} cwd - Project root.
 * @param {string} sessionId
 * @param {string|null} lastEventTs
 */
function recordSurfaced(cwd, sessionId, lastEventTs) {
  const agenticDir = path.join(cwd, '.agentic');
  const trackerPath = path.join(agenticDir, '.capture-gap-surfaced');
  fs.mkdirSync(agenticDir, { recursive: true });

  let existing = '';
  try {
    if (fs.existsSync(trackerPath)) existing = fs.readFileSync(trackerPath, 'utf8');
  } catch (_) { /* fall through with empty existing */ }

  const entry = JSON.stringify({ session_id: sessionId, last_event_ts: lastEventTs });
  const body = (existing && !existing.endsWith('\n')) ? existing + '\n' : existing;
  const next = body + entry + '\n';

  const tmpPath = trackerPath + '.tmp';
  fs.writeFileSync(tmpPath, next, 'utf8');
  fs.renameSync(tmpPath, trackerPath);
}

function run() {
  try {
    // --- 1. Read + parse stdin ---
    let raw = '';
    try {
      raw = fs.readFileSync(0, 'utf8');
    } catch (_) {
      process.exit(0);
    }
    if (!raw.trim()) process.exit(0);

    let payload;
    try {
      payload = JSON.parse(raw);
    } catch (_) {
      process.exit(0);
    }

    // --- 2. Gate on tool_name === "Task" && tool_response.status === "async_launched" ---
    // Background Task spawns (which this methodology mandates) fire PostToolUse at
    // LAUNCH with status "async_launched"; the subagent output is not yet available,
    // so the signal source is events.jsonl via detectCaptureGap, not tool_response.
    const toolName = payload && payload.tool_name;
    const toolResponse = (payload && payload.tool_response) || {};
    if (toolName !== 'Task') process.exit(0);
    if (toolResponse.status !== 'async_launched') process.exit(0);

    // --- 3. Resolve cwd + session_id (top-level fields on the PostToolUse payload) ---
    const cwd = (typeof payload.cwd === 'string' && payload.cwd.trim())
      ? payload.cwd.trim()
      : null;
    if (!cwd) process.exit(0);

    const sessionId = (typeof payload.session_id === 'string' && payload.session_id.trim())
      ? payload.session_id.trim()
      : null;
    if (!sessionId) process.exit(0);

    // --- 4. Detect capture gap (shared detector; pure read-only) ---
    const gap = detectCaptureGap(cwd, sessionId);
    if (!gap || gap.shouldNudge !== true) process.exit(0);

    // --- 5. Dedup on (session_id, lastEventTs) ---
    if (alreadySurfaced(cwd, sessionId, gap.lastEventTs)) process.exit(0);

    // --- 6. Record + emit ---
    try {
      recordSurfaced(cwd, sessionId, gap.lastEventTs);
    } catch (_) {
      // Tracker write failed - still emit the nudge once; a missed dedup record
      // at worst re-nudges on the next spawn, which is acceptable.
    }

    const additionalContext = gap.residualOnly ? NUDGE_RESIDUAL : NUDGE_STANDARD;
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PostToolUse',
        additionalContext,
      },
      suppressOutput: true,
    }));
    process.exit(0);
  } catch (_) {
    // Soft-fail: any unexpected error -> silent exit 0. Never block a spawn.
    process.exit(0);
  }
}

run();
