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
 *          MAX_SANE_WALL_SECONDS (86400 = 24h) yields wall_seconds:null
 *          (never a fabricated ceiling value) with `data.suspect` set true,
 *          rather than trusted outright - guards against a stale/mismatched
 *          pairing silently inflating a cost/telemetry rollup.
 *
 * Public API: run() - invoked immediately at module load via run() call at
 *             the bottom of the file. Not imported in production; executed
 *             as a CLI script by the Claude Code SubagentStop hook.
 *
 * Upstream deps: Node built-ins only (fs, path, os via
 *                hooks/lib/config-dir.js). No npm dependencies. Reads
 *                SubagentStop payload from stdin (fd 0) via the bounded
 *                reader hooks/lib/stdin-guard.js (readStdinGuarded).
 *                Reads [cwd]/.agentic/events.jsonl - bounded on BOTH the
 *                byte axis (readRecentEvents() reads at most MAX_TAIL_BYTES
 *                from the tail via fs.statSync + fs.readSync at a computed
 *                offset, never a full-file fs.readFileSync once the file
 *                exceeds that size) and the line axis (MAX_SCAN_LINES) - to
 *                find the matching spawn_start. Reads
 *                hooks/lib/config-dir.js (resolveClaudeConfigDir) and, when
 *                a transcript resolves, the subagent's own transcript JSONL
 *                under <config_dir>/projects/... (size-capped at
 *                MAX_TRANSCRIPT_BYTES, read synchronously).
 *                Writes [cwd]/.agentic/events.jsonl via appendFileSync.
 *
 * Downstream consumers: Claude Code SubagentStop hook (wired by
 *                        .claude/install.sh). hooks/stop-context.js
 *                        scanSessionAggregate() and bin/ds-cost's
 *                        _aggregate_by_agent() both read `data.wall_seconds`
 *                        (and, as of the token-resolution addition,
 *                        `data.tokens` when present) from hook-emitted
 *                        spawn_complete events into session/cost
 *                        aggregates, ONLY for sessions with no
 *                        conductor-emitted spawn_complete (double-count
 *                        guard - see the Purpose section above); this is the
 *                        first source of non-zero wall_seconds AND non-zero
 *                        tokens for hook-only ad-hoc sessions.
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
 *                **Token resolution (post-DS-160 addition).** `data.tokens`
 *                (`{input, output, cache_creation, cache_read}`, summed
 *                across the subagent's own transcript JSONL) is populated
 *                when the transcript can be found and read; it is ABSENT
 *                (never zero-filled) when unresolvable - a zero that looks
 *                like a measurement is the exact failure mode this addition
 *                removes. The transcript path is resolved the same way
 *                bin/ds-parse-subagent-usage resolves it: under the active
 *                harness config dir (hooks/lib/config-dir.js
 *                resolveClaudeConfigDir(), NOT a hardcoded ~/.claude - see
 *                that module's header for the measured root cause this
 *                fixes), primary construction from `cwd`+`session_id`+
 *                `agent_id`, falling back to a bounded scan (first
 *                MAX_PROJECT_DIRS_SCAN entries of
 *                `readdirSync(configDir/projects)`) when the primary path
 *                does not exist. Requires `agent_id` (best-effort,
 *                harness-supplied - see the field read above); when the
 *                harness omits it, or the transcript FILE cannot be
 *                located, `data.tokens_note` is
 *                `"unavailable (transcript not found)"`. When the
 *                transcript IS located but yields zero assistant-turn
 *                records carrying a usable `usage` block (round-2 fix:
 *                this is the same note for an empty file, a wholly
 *                malformed/non-JSONL file, and a genuinely turn-less
 *                transcript alike - readTranscriptTokens() tracks whether
 *                ANY record actually parsed and never treats a
 *                successful-but-vacuous read as a real zero measurement),
 *                `data.tokens_note` is
 *                `"unavailable (transcript unreadable)"`, and no `tokens`
 *                key is emitted either way. A transcript at or above
 *                MAX_TRANSCRIPT_BYTES (20 MiB) is SKIPPED entirely
 *                (`data.tokens_note: "skipped (transcript too large)"`) -
 *                never partial-summed, same never-fabricate principle as
 *                the `wall_seconds` sanity-cap treatment above. `tokens`
 *                and `tokens_note` are mutually exclusive on a given event.
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
 * Performance: Token resolution adds, once per SubagentStop invocation (not
 *              per events.jsonl line): at most one fs.statSync (primary
 *              transcript path), an optional bounded readdirSync scan
 *              (first MAX_PROJECT_DIRS_SCAN entries under
 *              configDir/projects, only on primary-path miss), and one
 *              synchronous fs.readFileSync of the resolved transcript,
 *              size-capped at MAX_TRANSCRIPT_BYTES (20 MiB) - a transcript
 *              at or above that size is skipped entirely rather than read.
 *              This stays inside the hook's overall 5s timeout
 *              (.claude/install.sh) alongside the rest of this hook's work.
 *
 *              The events.jsonl scan itself is bounded by
 *              hooks/lib/stdin-guard.js's read path (same as
 *              hooks/pre-tool-use-spawn-emit.js). The events.jsonl scan is
 *              bounded on BOTH axes, independent of overall file size:
 *              readRecentEvents() first fs.statSync()s the file and, when it
 *              exceeds MAX_TAIL_BYTES, opens an fd and reads only the last
 *              MAX_TAIL_BYTES bytes (fs.readSync at a computed offset, not a
 *              full fs.readFileSync) before splitting into lines and further
 *              capping at MAX_SCAN_LINES lines. events.jsonl is a
 *              cross-session, append-only, multi-writer file (this hook is
 *              itself one of the writers) with NO size cap or rotation (see
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
const { resolveClaudeConfigDir } = require('./lib/config-dir.js');

// Bounds the readdirSync fallback scan when the primary transcript path
// (constructed from cwd's project hash) does not exist - mirrors
// bin/ds-parse-subagent-usage's glob fallback but bounded on directory
// COUNT rather than left as an unbounded glob, matching this file's
// existing MAX_SCAN_LINES/MAX_TAIL_BYTES bounding discipline. readdirSync's
// entry order is unspecified, so any bound short of "every project dir"
// leaves SOME machine's tail unreachable on a primary-path miss; this fails
// SAFE either way (a miss emits `data.tokens_note`, never a wrong number),
// but round-2 raised the bound from 200 to 1000 after a real dev machine
// was observed with 251 entries under ~/.claude/projects - comfortably
// above the old bound and not comfortably below a plausible future one.
const MAX_PROJECT_DIRS_SCAN = 1000;

// A transcript at or above this size is SKIPPED entirely (never
// partial-summed) - see the token-resolution doc-comment note above.
const MAX_TRANSCRIPT_BYTES = 20 * 1024 * 1024;

/**
 * Claude Code's cwd->project-hash substitution scheme: every '/' becomes
 * '-'. Mirrors bin/ds-parse-subagent-usage's _project_hash_from_cwd().
 */
function projectHashFromCwd(cwd) {
  return String(cwd).replace(/\//g, '-');
}

/**
 * Resolve the subagent's own transcript path, or null when unresolvable.
 * Requires both sessionId and agentId (the harness-supplied SubagentStop
 * agent_id, best-effort - see the field read in run()); without agentId
 * there is no way to select which transcript under a session belongs to
 * THIS subagent, so this function does not guess.
 *
 * Primary: <configDir>/projects/<projectHash(cwd)>/<sessionId>/subagents/
 *          agent-<agentId>.jsonl
 * Fallback: the same filename under the first MAX_PROJECT_DIRS_SCAN
 *           entries of readdirSync(<configDir>/projects) - bounded scan,
 *           not an unbounded glob.
 */
function resolveTranscriptPath(configDir, cwd, sessionId, agentId) {
  if (!sessionId || !agentId) return null;

  const projectHash = projectHashFromCwd(cwd);
  const primary = path.join(
    configDir, 'projects', projectHash, sessionId, 'subagents', `agent-${agentId}.jsonl`
  );
  try {
    if (fs.statSync(primary).isFile()) return primary;
  } catch (_) { /* fall through to bounded scan */ }

  const projectsDir = path.join(configDir, 'projects');
  let entries;
  try {
    entries = fs.readdirSync(projectsDir);
  } catch (_) {
    return null;
  }
  const bounded = entries.slice(0, MAX_PROJECT_DIRS_SCAN);
  for (const entry of bounded) {
    const candidate = path.join(projectsDir, entry, sessionId, 'subagents', `agent-${agentId}.jsonl`);
    try {
      if (fs.statSync(candidate).isFile()) return candidate;
    } catch (_) { /* continue scanning */ }
  }
  return null;
}

/**
 * Sum token usage across all assistant turns in a transcript JSONL, or
 * return a descriptive note when unresolvable. Never returns a zero-filled
 * tokens object as a stand-in for "unresolved" - a real zero (genuinely no
 * assistant turns yet) and "we could not read this" are kept distinct by
 * tracking whether at least one assistant-with-usage record ACTUALLY
 * parsed, not merely whether the file opened without throwing. Round-2 fix:
 * a prior version returned the untouched {0,0,0,0} accumulator as a
 * "success" whenever the file was 0 bytes or wholly unparseable JSONL,
 * which is indistinguishable downstream from a real zero-token
 * measurement - exactly the fabrication this function exists to prevent.
 *
 * Returns { tokens: {input,output,cache_creation,cache_read}, note: null }
 * when at least one assistant-with-usage record parsed, or
 * { tokens: null, note: <string> } when tokens could not be determined
 * (file missing, oversized, or found but yielding zero parsed records).
 */
function readTranscriptTokens(transcriptPath) {
  let stat;
  try {
    stat = fs.statSync(transcriptPath);
  } catch (_) {
    return { tokens: null, note: 'unavailable (transcript not found)' };
  }
  if (!stat.isFile()) {
    return { tokens: null, note: 'unavailable (transcript not found)' };
  }
  if (stat.size >= MAX_TRANSCRIPT_BYTES) {
    return { tokens: null, note: 'skipped (transcript too large)' };
  }

  let raw;
  try {
    raw = fs.readFileSync(transcriptPath, 'utf8');
  } catch (_) {
    return { tokens: null, note: 'unavailable (transcript not found)' };
  }

  const tokens = { input: 0, output: 0, cache_creation: 0, cache_read: 0 };
  let parsedCount = 0;
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try { obj = JSON.parse(trimmed); } catch (_) { continue; }
    if (!obj || obj.type !== 'assistant') continue;
    const usage = obj.message && obj.message.usage;
    if (!usage || typeof usage !== 'object') continue;
    parsedCount += 1;
    tokens.input += Number(usage.input_tokens) || 0;
    tokens.output += Number(usage.output_tokens) || 0;
    tokens.cache_creation += Number(usage.cache_creation_input_tokens) || 0;
    tokens.cache_read += Number(usage.cache_read_input_tokens) || 0;
  }
  if (parsedCount === 0) {
    // File opened and read fine, but nothing usable parsed out of it - an
    // empty file, wholly malformed JSONL, and a genuinely turn-less
    // transcript are all indistinguishable from "we could not determine
    // this" from the caller's perspective, and must never be reported as
    // a real zero-token measurement.
    return { tokens: null, note: 'unavailable (transcript unreadable)' };
  }
  return { tokens, note: null };
}

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
        // fs.readSync's return value is the ACTUAL bytes read, which can be
        // less than requested (e.g. the file was concurrently truncated
        // between the stat() above and this read - events.jsonl is
        // append-only by protocol but this hook does not assume that
        // holds under every failure mode). Buffer.alloc zero-fills, so
        // ignoring bytesRead and stringifying the whole buffer would splice
        // NUL padding onto the END of the read - which is the NEWEST data
        // (the read starts partway through the file and reads toward EOF),
        // silently corrupting the very lines this hook most needs to parse
        // correctly. Slice to bytesRead before decoding.
        const bytesRead = fs.readSync(fd, buf, 0, MAX_TAIL_BYTES, start);
        raw = buf.subarray(0, bytesRead).toString('utf8');
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
// completion signal itself is still real and should not be lost, and
// paired_spawn_id is still useful for forensics), the event is marked
// data.suspect:true with data.wall_seconds:null - NOT a fabricated ceiling
// value. A round-2 Skeptic fix: an earlier version of this ceiling clamped
// wall_seconds to 86400 instead of nulling it, which silently injected a
// false 24h duration into consumer aggregates (hooks/stop-context.js
// scanSessionAggregate, bin/ds-cost) for every suspect pairing - worse than
// the unbounded figure it replaced, since it was indistinguishable from a
// real measurement. Consumers already treat wall_seconds:null as a 0
// contribution (Number(null)||0), which is the correct behavior for a
// suspect pairing: count the spawn, contribute nothing to its duration.
// 86400 = 24 hours, generously above any real subagent run.
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
        // Sanity ceiling: null out (never fabricate a ceiling value) and
        // flag rather than trust a pairing that implies an implausibly
        // long-running spawn (see MAX_SANE_WALL_SECONDS comment above
        // findMatch).
        if (wallSeconds > MAX_SANE_WALL_SECONDS) {
          wallSeconds = null;
          suspect = true;
        }
      }
    }

    // Token resolution: try to find and read the subagent's own transcript.
    // tokens is populated ONLY on success; tokens_note is populated ONLY on
    // failure - never both, never a zero-filled tokens object standing in
    // for "unresolved" (see the token-resolution doc-comment above).
    let tokens = null;
    let tokensNote = null;
    try {
      const configDir = resolveClaudeConfigDir();
      const transcriptPath = resolveTranscriptPath(configDir, cwd, sessionId, agentId);
      if (transcriptPath) {
        const result = readTranscriptTokens(transcriptPath);
        if (result.tokens) {
          tokens = result.tokens;
        } else {
          tokensNote = result.note;
        }
      } else {
        tokensNote = 'unavailable (transcript not found)';
      }
    } catch (_) {
      // Token resolution must never block emitting the completion signal
      // itself - fall through with tokensNote unset from this branch.
      tokensNote = tokensNote || 'unavailable (transcript not found)';
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
        ...(tokens ? { tokens } : {}),
        ...(tokensNote ? { tokens_note: tokensNote } : {}),
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
