#!/usr/bin/env node

/**
 * Purpose: Claude Code SubagentStop hook. Fires deterministically when a
 *          subagent (Task/Agent spawn) actually finishes running - unlike
 *          PostToolUse(Task/Agent), which fires at spawn LAUNCH time, not
 *          completion (see hooks/pre-tool-use-spawn-emit.js header note).
 *          Prior to DS-160, `spawn_complete` was emitted ONLY via prose
 *          instructions telling the conductor LLM to run `bin/ds-emit
 *          spawn_complete ...` inline after each Agent tool call returns
 *          (content/commands/ds-implement-ticket.md). That mechanism is an
 *          LLM-semantic event with no deterministic trigger and has been
 *          observed to fire on well under 1% of real spawns (6 of ~1,640
 *          spawn_start records in this repo's own events.jsonl, none after
 *          2026-07-10). This hook closes that gap: it appends a
 *          `spawn_complete` event to [cwd]/.agentic/events.jsonl on every
 *          subagent completion, with `data.source:"hook"` (same convention
 *          as hooks/pre-tool-use-spawn-emit.js's hook-emitted spawn_start),
 *          independent of whether the conductor also emits its own richer
 *          conductor-side spawn_complete (e.g. the Skeptic calibration
 *          variant in ds-implement-ticket.md Phase 6/7/10a). Both may exist
 *          for the same spawn; consumers treat spawn_complete as additive,
 *          not exclusive (see hooks/stop-context.js scanSessionAggregate()).
 *
 *          Pairing: this hook does NOT receive the launching PreToolUse
 *          call's `spawn_id` directly from the harness (SubagentStop's
 *          payload shape is not documented to carry it). Instead it
 *          reconstructs the pairing by scanning [cwd]/.agentic/events.jsonl
 *          backward for the most recent unmatched `spawn_start` event
 *          (data.source==="hook") whose `data.session_uuid` matches this
 *          payload's `session_id`, preferring an exact `data.tool_use_id`
 *          match when both sides carry one, then falling back to FIFO
 *          (oldest unmatched spawn_start for that session wins). "Unmatched"
 *          is tracked by scanning the same window for prior spawn_complete
 *          events and excluding any spawn_id already referenced by
 *          `data.paired_spawn_id`. This is a best-effort heuristic, not a
 *          hard guarantee - see Failure modes.
 *
 *          `data.wall_seconds` is computed as (this event's ts - the matched
 *          spawn_start's ts) when a match is found; when no match is found,
 *          the event is still emitted (a "reliably-paired timestamp" per
 *          DS-160's own fallback allowance) with wall_seconds:null and
 *          paired_spawn_id:null, so a real completion signal exists even
 *          when pairing fails.
 *
 * Public API: run() - invoked immediately at module load via run() call at
 *             the bottom of the file. Not imported in production; executed
 *             as a CLI script by the Claude Code SubagentStop hook.
 *
 * Upstream deps: Node built-ins only (fs, path). No npm dependencies. Reads
 *                SubagentStop payload from stdin (fd 0) via the bounded
 *                reader hooks/lib/stdin-guard.js (readStdinGuarded).
 *                Reads [cwd]/.agentic/events.jsonl (bounded to the last
 *                MAX_SCAN_LINES lines) to find the matching spawn_start.
 *                Writes [cwd]/.agentic/events.jsonl via appendFileSync.
 *
 * Downstream consumers: Claude Code SubagentStop hook (wired by
 *                        .claude/install.sh). hooks/stop-context.js
 *                        scanSessionAggregate() sums `data.wall_seconds` from
 *                        spawn_complete events into session_total (this is
 *                        the first source of non-zero wall_seconds for
 *                        hook-only ad-hoc sessions; token fields remain zero
 *                        - harness ceiling, unchanged, out of DS-160 scope).
 *                        hooks/lib/capture-gap.js detectCaptureGap() already
 *                        recognizes spawn_complete for debugger/investigator
 *                        and Skeptic-with-findings triggers.
 *
 * Failure modes: Fully fail-open, mirroring hooks/pre-tool-use-spawn-emit.js.
 *                Entire body wrapped in try/catch; ALWAYS process.exit(0).
 *                Any fs error, parse error, or missing field is silently
 *                swallowed. NEVER writes to stdout. NEVER denies (advisory
 *                telemetry only). The SubagentStop payload shape is NOT
 *                empirically verified against a live harness capture in this
 *                repo as of DS-160 (only `session_id`, `cwd`, and best-effort
 *                `tool_use_id`/`agent_id`/`agent_type` are read, each with a
 *                typeof guard and a null fallback) - if the harness omits a
 *                field this hook expects, pairing degrades to the FIFO
 *                fallback or, in the worst case, an unpaired spawn_complete
 *                with wall_seconds:null. It never crashes or blocks on a
 *                missing/renamed field. Live-payload verification against a
 *                real Claude Code session is a recommended fast follow-up
 *                (flagged, not blocking, in the DS-160 PR report).
 *
 * Performance: Bounded by hooks/lib/stdin-guard.js's read path (same as
 *              hooks/pre-tool-use-spawn-emit.js). The events.jsonl scan reads
 *              at most the last MAX_SCAN_LINES lines (default 5000) via a
 *              single fs.readFileSync + string split, not a streaming tail -
 *              acceptable because this hook runs on subagent COMPLETION, not
 *              on the spawn-launch critical path, and events.jsonl is
 *              documented (content/references/events-log.md) to operate at a
 *              ~50KB-per-session budget.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { readStdinGuarded } = require('./lib/stdin-guard.js');

const MAX_SCAN_LINES = 5000;

/**
 * Parse the tail of events.jsonl (bounded to MAX_SCAN_LINES lines) into
 * an array of parsed JSON objects, skipping malformed lines.
 */
function readRecentEvents(eventsPath) {
  if (!fs.existsSync(eventsPath)) return [];
  let raw;
  try { raw = fs.readFileSync(eventsPath, 'utf8'); } catch (_) { return []; }
  if (!raw.trim()) return [];
  const lines = raw.split('\n').filter(l => l.trim());
  const tail = lines.length > MAX_SCAN_LINES ? lines.slice(-MAX_SCAN_LINES) : lines;
  const out = [];
  for (const line of tail) {
    try { out.push(JSON.parse(line)); } catch (_) { /* skip malformed */ }
  }
  return out;
}

/**
 * Find the best-effort matching spawn_start for this SubagentStop, and
 * return { spawnId, startTs, agent } or null when nothing matches.
 *
 * Matching preference order:
 *   1. Exact data.tool_use_id match (when both sides carry one).
 *   2. FIFO: oldest unmatched hook-emitted spawn_start for this session_uuid.
 * "Unmatched" excludes any spawn_id already referenced by a prior
 * spawn_complete's data.paired_spawn_id in the scanned window.
 */
function findMatch(events, sessionId, toolUseId) {
  const pairedIds = new Set();
  for (const ev of events) {
    if (ev && ev.event === 'spawn_complete') {
      const d = ev.data || {};
      if (d.paired_spawn_id) pairedIds.add(d.paired_spawn_id);
    }
  }

  const candidates = [];
  for (const ev of events) {
    if (!ev || ev.event !== 'spawn_start') continue;
    const d = ev.data || {};
    if (d.source !== 'hook') continue;
    if (!d.spawn_id || pairedIds.has(d.spawn_id)) continue;
    if (sessionId && d.session_uuid && d.session_uuid !== sessionId) continue;
    candidates.push({ spawnId: d.spawn_id, startTs: ev.ts, agent: ev.agent, toolUseId: d.tool_use_id || null });
  }

  if (candidates.length === 0) return null;

  if (toolUseId) {
    const exact = candidates.find(c => c.toolUseId === toolUseId);
    if (exact) return exact;
  }

  // FIFO fallback: candidates are in file order (oldest first) already,
  // since events.jsonl is append-only.
  return candidates[0];
}

/**
 * Main entry point. Reads SubagentStop payload from stdin, emits a best-effort
 * spawn_complete event to events.jsonl, always exits 0.
 */
async function run() {
  try {
    const raw = await readStdinGuarded();
    let payload;
    try { payload = JSON.parse(raw); } catch (_) { process.exit(0); }

    const cwd = (payload && typeof payload.cwd === 'string' && payload.cwd.trim())
      ? payload.cwd.trim()
      : null;
    if (!cwd) process.exit(0);

    const sessionId = (payload && typeof payload.session_id === 'string' && payload.session_id.trim())
      ? payload.session_id.trim()
      : null;
    const toolUseId = (payload && typeof payload.tool_use_id === 'string' && payload.tool_use_id.trim())
      ? payload.tool_use_id.trim()
      : null;
    // Best-effort: the subagent's own identity, if the harness threads it
    // through to SubagentStop (mirrors the agent_id convention documented in
    // hooks/enforce-orchestrator-singularity.py). Not required for pairing.
    const agentId = (payload && typeof payload.agent_id === 'string' && payload.agent_id.trim())
      ? payload.agent_id.trim()
      : null;

    const agenticDir = path.join(cwd, '.agentic');
    fs.mkdirSync(agenticDir, { recursive: true });
    const eventsPath = path.join(agenticDir, 'events.jsonl');

    const events = readRecentEvents(eventsPath);
    const match = findMatch(events, sessionId, toolUseId);

    const nowIso = new Date().toISOString();
    let wallSeconds = null;
    let pairedSpawnId = null;
    let agentName = 'unknown';
    if (match) {
      pairedSpawnId = match.spawnId;
      agentName = match.agent || 'unknown';
      const startMs = Date.parse(match.startTs);
      const nowMs = Date.parse(nowIso);
      if (!Number.isNaN(startMs) && !Number.isNaN(nowMs) && nowMs >= startMs) {
        wallSeconds = Number(((nowMs - startMs) / 1000).toFixed(3));
      }
    }

    const event = {
      ts: nowIso,
      phase: 'hook',
      event: 'spawn_complete',
      agent: agentName,
      task_id: null,
      data: {
        source: 'hook',
        session_uuid: sessionId || null,
        tool_use_id: toolUseId,
        agent_id: agentId,
        paired_spawn_id: pairedSpawnId,
        wall_seconds: wallSeconds,
        tokens_note: 'unavailable (harness)',
      },
    };
    fs.appendFileSync(eventsPath, JSON.stringify(event) + '\n', 'utf8');

    process.exit(0);
  } catch (_) {
    // Fully fail-open: any unexpected error -> silent exit 0.
    process.exit(0);
  }
}

run().catch(() => process.exit(0));
