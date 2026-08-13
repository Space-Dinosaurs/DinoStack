#!/usr/bin/env node

/**
 * Purpose: Registered top-level Stop hook. Thin wrapper around
 *          hooks/lib/overreach-detector.js's computeOverreach: reads the
 *          Stop payload from stdin, resolves the configured (or calibrated
 *          default) threshold, and on ratio_trigger appends a
 *          conductor_overreach event to .agentic/events.jsonl and emits an
 *          advisory additionalContext line. WARN-ONLY - never blocks the
 *          stop; every path exits 0.
 *
 * Public API: none (CLI entry point only, invoked by the Claude Code Stop
 *             hook per .claude/settings.json). Not imported by other
 *             modules.
 *
 * Upstream deps: Node built-ins (fs, path), hooks/lib/stdin-guard.js
 *                (readStdinGuarded), hooks/lib/overreach-detector.js
 *                (computeOverreach, DEFAULT_THRESHOLD). Reads
 *                [cwd]/.agentic/config.json (optional,
 *                conductor_overreach_threshold key; config-reversible).
 *
 * Downstream consumers: none - terminal hook. Appends to
 *                        [cwd]/.agentic/events.jsonl, read by bin/ds-cost
 *                        and content/references/events-log.md consumers.
 *
 * Failure modes: fail-open on any error - missing/malformed stdin, missing
 *                fields, unreadable/malformed config, or a write failure on
 *                events.jsonl all result in a silent exit 0. No suppression-
 *                mute logic exists anywhere in this hook by design (a prior
 *                design that grepped the transcript for an injected
 *                harness-suppression phrase and muted the advisory was
 *                removed by Skeptic Critical finding - do not re-derive it,
 *                and do not grep the transcript for injected-prompt
 *                phrases). The advisory fires unconditionally whenever
 *                ratio_trigger is true, regardless of transcript content.
 *
 * Performance: single stdin read + single transcript pass (see
 *              overreach-detector.js) + one best-effort file append.
 *              No subprocess calls.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const { readStdinGuarded } = require('./lib/stdin-guard.js');
const { computeOverreach, DEFAULT_THRESHOLD } = require('./lib/overreach-detector.js');

/**
 * @param {string} cwd
 * @returns {number}
 */
function _resolveThreshold(cwd) {
  try {
    const configPath = path.join(cwd, '.agentic', 'config.json');
    if (!fs.existsSync(configPath)) return DEFAULT_THRESHOLD;
    const raw = fs.readFileSync(configPath, 'utf8');
    const config = JSON.parse(raw);
    const v = config && config.conductor_overreach_threshold;
    if (typeof v === 'number' && v > 0) return v;
    return DEFAULT_THRESHOLD;
  } catch (_) {
    return DEFAULT_THRESHOLD;
  }
}

/**
 * Append a single conductor_overreach event line. Best-effort, atomic
 * single-line append (matches writeSessionTotal's pattern in
 * hooks/stop-context.js). Any error is swallowed.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {{conductor_tool_calls:number, live_or_completed_spawns:number,
 *   ratio_trigger:boolean, whitelisted_reads_excluded:number}} result
 */
function _appendEvent(cwd, sessionId, result) {
  try {
    const agenticDir = path.join(cwd, '.agentic');
    fs.mkdirSync(agenticDir, { recursive: true });
    const eventsPath = path.join(agenticDir, 'events.jsonl');
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      phase: 'stop',
      event: 'conductor_overreach',
      agent: null,
      task_id: null,
      data: {
        source: 'hook',
        session_uuid: sessionId || null,
        conductor_tool_calls: result.conductor_tool_calls,
        live_or_completed_spawns: result.live_or_completed_spawns,
        ratio_trigger: result.ratio_trigger,
        whitelisted_reads_excluded: result.whitelisted_reads_excluded,
      },
    });
    fs.appendFileSync(eventsPath, line + '\n');
  } catch (_) {
    // Silent failure - consistent with the other events.jsonl writers.
  }
}

async function run() {
  try {
    const raw = await readStdinGuarded();
    if (!raw || !raw.trim()) process.exit(0);

    let payload;
    try {
      payload = JSON.parse(raw);
    } catch (_) {
      process.exit(0);
    }

    const cwd = (typeof payload.cwd === 'string' && payload.cwd.trim())
      ? payload.cwd.trim()
      : null;
    if (!cwd) process.exit(0);

    const sessionId = (typeof payload.session_id === 'string' && payload.session_id.trim())
      ? payload.session_id.trim()
      : null;

    const transcript = Array.isArray(payload.transcript) ? payload.transcript : [];
    const threshold = _resolveThreshold(cwd);
    const result = computeOverreach(transcript, threshold);

    if (!result.ratio_trigger) process.exit(0);

    _appendEvent(cwd, sessionId, result);

    const advisory =
      `Advisory: this turn made ${result.conductor_tool_calls} investigation-shaped ` +
      'tool calls with zero subagent spawns; if this was diagnosis rather than ' +
      'fact-confirmation, consider whether it should have been delegated.';

    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'Stop',
        additionalContext: advisory,
      },
    }));
    process.exit(0);
  } catch (_) {
    // Fail-open: never block the stop.
    process.exit(0);
  }
}

run();
