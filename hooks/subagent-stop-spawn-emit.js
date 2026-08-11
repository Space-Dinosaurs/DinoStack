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
 *          variant in ds-implement-ticket.md Phase 6/7/10a). Both records
 *          MAY exist on disk for the same spawn, but consumers do NOT sum
 *          them additively: hooks/stop-context.js scanSessionAggregate()
 *          (and bin/ds-cost's _aggregate_by_agent()) apply a double-count
 *          guard - when a session has a conductor-emitted (non-hook)
 *          spawn_complete, ALL hook-emitted telemetry for that session
 *          (both spawn_start and spawn_complete) is excluded from the
 *          count, treating the conductor's record as authoritative. This
 *          hook's own event is still written to disk either way (telemetry
 *          write is unconditional and does not know about session type);
 *          it is the CONSUMER that decides whether to count it.
 *
 *          Pairing: this hook does NOT receive the launching PreToolUse
 *          call's `spawn_id` directly from the harness (SubagentStop's
 *          payload shape is not documented to carry it). Instead it
 *          reconstructs the pairing by scanning [cwd]/.agentic/events.jsonl
 *          backward for the most recent unmatched `spawn_start` event
 *          (data.source==="hook") whose `data.session_uuid` EXACTLY equals
 *          this payload's `session_id` - session scoping is REQUIRED, not
 *          best-effort: when either side lacks a session id, or this
 *          payload's `session_id` is absent, pairing is skipped entirely
 *          (degrades to unpaired) rather than falling through to an
 *          unscoped FIFO match across sessions. Among same-session
 *          candidates, an exact `data.tool_use_id` match wins first, then
 *          FIFO (oldest unmatched spawn_start for that session wins).
 *          "Unmatched" is tracked by scanning the same window for prior
 *          spawn_complete events and excluding any spawn_id already
 *          referenced by `data.paired_spawn_id`. This is a best-effort
 *          heuristic, not a hard guarantee - see Failure modes.
 *
 *          `data.wall_seconds` is computed as (this event's ts - the matched
 *          spawn_start's ts) when a match is found; when no match is found,
 *          the event is still emitted (a "reliably-paired timestamp" per
 *          DS-160's own fallback allowance) with wall_seconds:null and
 *          paired_spawn_id:null, so a real completion signal exists even
 *          when pairing fails. A computed wall_seconds beyond
 *          MAX_SANE_WALL_SECONDS (86400 = 24h) is capped at that ceiling and
 *          `data.suspect` is set true, rather than trusted outright - guards
 *          against a stale/mismatched pairing silently inflating a
 *          cost/telemetry rollup.
 *
 * Public API: run() - invoked immediately at module load via run() call at
 *             the bottom of the file. Not imported in production; executed
 *             as a CLI script by the Claude Code SubagentStop hook.
 *
 * Upstream deps: Node built-ins only (fs, path). No npm dependencies. Reads
 *                SubagentStop payload from stdin (fd 0) via the bounded
 *                reader hooks/lib/stdin-guard.js (readStdinGuarded).
 *                Reads [cwd]/.agentic/events.jsonl - bounded on BOTH the
 *                byte axis (readRecentEvents() reads at most MAX_TAIL_BYTES
 *                from the tail via fs.statSync + fs.readSync at a computed
 *                offset, never a full-file fs.readFileSync once the file
 *                exceeds that size) and the line axis (MAX_SCAN_LINES) - to
 *                find the matching spawn_start.
 *                Writes [cwd]/.agentic/events.jsonl via appendFileSync.
 *
 * Downstream consumers: Claude Code SubagentStop hook (wired by
 *                        .claude/install.sh). hooks/stop-context.js
 *                        scanSessionAggregate() and bin/ds-cost's
 *                        _aggregate_by_agent() both read `data.wall_seconds`
 *                        from hook-emitted spawn_complete events into
 *                        session/cost aggregates, ONLY for sessions with no
 *                        conductor-emitted spawn_complete (double-count
 *                        guard - see the Purpose section above); this is the
 *                        first source of non-zero wall_seconds for hook-only
 *                        ad-hoc sessions (token fields remain zero - harness
 *                        ceiling, unchanged, out of DS-160 scope).
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
 *                No serialization between concurrent SubagentStop
 *                invocations (Skeptic finding, Minor): if two subagents in
 *                the same session complete close enough together that their
 *                hook invocations overlap, both can read events.jsonl before
 *                either has appended its own spawn_complete, and both can
 *                independently select the SAME unmatched spawn_start as
 *                their match (a TOCTOU race on the pairedIds exclusion set).
 *                The result is double-pairing: two spawn_complete records
 *                both claiming the same paired_spawn_id, one of which is
 *                therefore wrong. This is accepted, not mitigated, for two
 *                reasons: (1) this file is telemetry-only, fail-open, and
 *                advisory - a mispaired wall_seconds is a data-quality
 *                blemish, not a correctness or safety issue, and (2) actually
 *                closing the race would require either a file lock around
 *                the read-match-append sequence (adds latency and a new
 *                failure mode to a hook that currently cannot block or deny)
 *                or a re-read-and-recheck-pairedIds step immediately before
 *                the append (narrows the window but cannot close it without
 *                a lock, since the check-then-append is still not atomic).
 *                Neither is judged worth the added complexity for a rare,
 *                low-severity race in an advisory-only signal.
 *
 * Performance: Bounded by hooks/lib/stdin-guard.js's read path (same as
 *              hooks/pre-tool-use-spawn-emit.js). The events.jsonl scan is
 *              bounded on BOTH axes, independent of overall file size:
 *              readRecentEvents() first fs.statSync()s the file and, when it
 *              exceeds MAX_TAIL_BYTES, opens an fd and reads only the last
 *              MAX_TAIL_BYTES bytes (fs.readSync at a computed offset, not a
 *              full fs.readFileSync) before splitting into lines and further
 *              capping at MAX_SCAN_LINES lines. events.jsonl is a
 *              cross-session, append-only, single-writer-by-protocol file
 *              with NO size cap or rotation (see
 *              content/references/events-log.md "Atomicity" - "Records are
 *              not size-bounded") - it is NOT scoped to ~50KB per session in
 *              practice (a prior version of this comment claimed otherwise;
 *              that claim was false - this repo's own events.jsonl was
 *              observed at 2.4MB, and it grows unboundedly over the file's
 *              lifetime). Bounding the read protects this hook, which runs on
 *              every subagent COMPLETION (a much higher-frequency call site
 *              than "once per session"), from an O(file size) read cost.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { readStdinGuarded } = require('./lib/stdin-guard.js');

const MAX_SCAN_LINES = 5000;
// Bounds the raw byte read regardless of events.jsonl's total size (see
// Performance note above - the file has no size cap or rotation). 2MB is
// generously above what MAX_SCAN_LINES worth of JSONL lines will ever need.
const MAX_TAIL_BYTES = 2 * 1024 * 1024;

/**
 * Parse the tail of events.jsonl (bounded to MAX_TAIL_BYTES raw bytes, then
 * further bounded to MAX_SCAN_LINES lines) into an array of parsed JSON
 * objects, skipping malformed lines. Reads at most MAX_TAIL_BYTES from disk
 * regardless of the file's total size - never a full fs.readFileSync of an
 * unbounded, cross-session, append-only file.
 */
function readRecentEvents(eventsPath) {
  let stat;
  try { stat = fs.statSync(eventsPath); } catch (_) { return []; }
  const size = stat.size;
  if (size === 0) return [];

  let raw;
  let truncatedHead = false;
  try {
    if (size <= MAX_TAIL_BYTES) {
      raw = fs.readFileSync(eventsPath, 'utf8');
    } else {
      const fd = fs.openSync(eventsPath, 'r');
      try {
        const start = size - MAX_TAIL_BYTES;
        const buf = Buffer.alloc(MAX_TAIL_BYTES);
        fs.readSync(fd, buf, 0, MAX_TAIL_BYTES, start);
        raw = buf.toString('utf8');
        truncatedHead = true;
      } finally {
        fs.closeSync(fd);
      }
    }
  } catch (_) { return []; }

  if (!raw.trim()) return [];
  let lines = raw.split('\n').filter(l => l.trim());
  // When we only read a tail window, the FIRST line of that window may be a
  // truncated fragment of a longer line that started before the window -
  // drop it explicitly rather than rely on JSON.parse's try/catch to skip
  // a corrupt partial object (which it would, but dropping it up front
  // avoids treating a merely-truncated valid line as "malformed").
  if (truncatedHead && lines.length > 0) {
    lines = lines.slice(1);
  }
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
 *   2. FIFO: oldest unmatched hook-emitted spawn_start for this session_uuid,
 *      oldest first (candidates are in file order already, since
 *      events.jsonl is append-only).
 * "Unmatched" excludes any spawn_id already referenced by a prior
 * spawn_complete's data.paired_spawn_id in the scanned window.
 *
 * Session scoping is REQUIRED, not best-effort: a candidate is only eligible
 * when this SubagentStop's sessionId AND the candidate spawn_start's
 * data.session_uuid are BOTH present and equal. Prior to this fix, a null
 * sessionId (or a candidate with no session_uuid) short-circuited the
 * session filter entirely (`if (sessionId && d.session_uuid && ...)`),
 * allowing FIFO to pair across sessions - and across months, once nothing
 * ahead of it in the scan window carried a session_uuid at all. When either
 * side is missing a session id, this function degrades to unpaired (returns
 * null) rather than guessing.
 */
function findMatch(events, sessionId, toolUseId) {
  if (!sessionId) return null;

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
    // Session scoping is mandatory: both sides must carry a session id and
    // they must match. A candidate with no session_uuid is never eligible.
    if (!d.session_uuid || d.session_uuid !== sessionId) continue;
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

// Sanity ceiling on wall_seconds: any pairing that would produce a duration
// beyond this is almost certainly a stale/mismatched pair (e.g. a spawn_start
// that was never cleaned up across an interrupted session) rather than a
// genuine 24h+ subagent run. Rather than reject the pairing outright (the
// completion signal itself is still real and should not be lost), mark the
// event with data.suspect:true and cap the reported wall_seconds so a single
// bad pairing cannot silently inflate a cost/telemetry rollup by orders of
// magnitude. 86400 = 24 hours, generously above any real subagent run.
const MAX_SANE_WALL_SECONDS = 86400;

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
    let suspect = false;
    if (match) {
      pairedSpawnId = match.spawnId;
      agentName = match.agent || 'unknown';
      const startMs = Date.parse(match.startTs);
      const nowMs = Date.parse(nowIso);
      if (!Number.isNaN(startMs) && !Number.isNaN(nowMs) && nowMs >= startMs) {
        wallSeconds = Number(((nowMs - startMs) / 1000).toFixed(3));
        // Sanity ceiling: cap and flag rather than trust a pairing that
        // implies an implausibly long-running spawn (see MAX_SANE_WALL_SECONDS
        // comment above findMatch).
        if (wallSeconds > MAX_SANE_WALL_SECONDS) {
          wallSeconds = MAX_SANE_WALL_SECONDS;
          suspect = true;
        }
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
        suspect: suspect,
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
