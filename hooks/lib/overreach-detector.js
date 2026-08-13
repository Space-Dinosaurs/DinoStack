#!/usr/bin/env node

/**
 * Purpose: Unregistered detection lib for the conductor_overreach warn-only
 *          Stop-hook nudge. Given the Stop payload's `transcript_path` (the
 *          REAL Claude Code Stop payload field - the payload is
 *          {session_id, transcript_path, cwd, hook_event_name,
 *          stop_hook_active}; there is no `transcript` array field, and
 *          stop-context.js's own `payload.transcript` read has been
 *          silently empty on every recorded session - do not treat it as
 *          precedent), reads and parses the transcript JSONL file (the same
 *          per-line shape bin/ds-measure-conductor-tool-calls already
 *          parses) and computes how many investigation-shaped tool calls
 *          the conductor made this session with zero subagent spawns, after
 *          subtracting a mandated-preflight whitelist. A bounded read (size
 *          ceiling) and malformed-line tolerance protect against
 *          pathological transcript files.
 *
 * Public API (CommonJS):
 *   computeOverreach(transcriptPath, threshold, maxBytes) -> {
 *     available: boolean, conductor_tool_calls: number,
 *     live_or_completed_spawns: number, ratio_trigger: boolean,
 *     whitelisted_reads_excluded: number, transcript_note: string|null }
 *     `available` is false (transcript_note populated, all counts 0,
 *     ratio_trigger false) when the transcript could not be read or yielded
 *     zero parsed records - NEVER a silent zero-filled accumulator (the
 *     PR #723 readTranscriptTokens anti-pattern this mirrors the fix for:
 *     an unavailable measurement must be distinguishable from a real zero).
 *   computeOverreachFromBlocks(blocks, threshold) -> same shape minus
 *     `available`/`transcript_note` (always available given an in-memory
 *     block list) - the core algorithm, exported directly for unit tests
 *     that want to exercise it without a filesystem fixture.
 *   parseTranscriptBlocks(transcriptPath, maxBytes) -> { blocks: Array,
 *     parsedCount: number, note: string|null } - the file-reading/parsing
 *     layer, exported for reuse and direct testing.
 *   DEFAULT_THRESHOLD - number, the calibrated default (see
 *   bin/ds-measure-conductor-tool-calls; measured directly against the
 *   detector's own cumulative whole-transcript statistic on this machine's
 *   real transcripts - see that script's header for the live table).
 *   DEFAULT_MAX_TRANSCRIPT_BYTES - number, size ceiling above which a
 *     transcript is treated as unavailable ("skipped (transcript too
 *     large)") rather than partially summed.
 *
 * Upstream deps: Node built-ins only (fs). Callers
 *                (hooks/conductor-overreach-nudge.js) are responsible for
 *                reading .agentic/config.json's conductor_overreach_threshold
 *                key and passing the resolved threshold in.
 *
 * Downstream consumers: hooks/conductor-overreach-nudge.js (registered Stop
 *                        hook). hooks/tests/test-conductor-overreach-nudge.js
 *                        and hooks/tests/test-overreach-detector.js exercise
 *                        this module directly.
 *
 * Failure modes: never throws. A missing/unreadable/oversized transcript
 *                file, or one that yields zero parsed JSONL records
 *                (malformed/empty), returns available:false with a
 *                descriptive transcript_note - counts are 0 but explicitly
 *                marked non-authoritative, never presented as a real
 *                measurement. A transcript mixing valid and malformed lines
 *                is parsed from the valid lines only (parsedCount counts
 *                only those), no disclosure of which lines were dropped
 *                (same accepted-blemish precedent as
 *                hooks/subagent-stop-spawn-emit.js).
 *
 * Performance: single bounded read (fs.statSync + fs.readFileSync, gated by
 *              DEFAULT_MAX_TRANSCRIPT_BYTES) plus one pass over the parsed
 *              blocks. No subprocess calls.
 */

'use strict';

const fs = require('fs');

// Tool names treated as conductor investigation-shaped calls.
const INVESTIGATION_TOOLS = new Set(['Read', 'Grep', 'Glob']);

// Read-shaped Bash binaries (first token of the first pipeline segment).
const READ_SHAPED_BASH_BINARIES = new Set([
  'grep', 'rg', 'cat', 'head', 'tail', 'find', 'ls', 'wc',
]);
const READ_SHAPED_GIT_SUBCOMMANDS = new Set(['show', 'diff', 'log', 'status']);

// Subagent-spawn tool name. Measured against real transcripts on this
// harness (Claude Code v2.1.x): the spawn tool is named "Agent" - NOT
// "Task" (that name collides with the unrelated TaskCreate/TaskUpdate/
// TaskStop/TaskOutput todo-list tools, which must never be treated as
// spawns). See bin/ds-measure-conductor-tool-calls for the measurement.
const SPAWN_TOOL_NAME = 'Agent';

// Mandated-preflight whitelist: reads of these paths (substring match
// against the tool_input file_path/path/pattern field) are excluded.
const WHITELIST_PATH_SUBSTRINGS = [
  '.agentic/context.md',
  '.agentic/config.json',
  '.agentic/events.jsonl',
  '.agentic/skill-candidates.md',
];
const WHITELIST_PATH_RE = /content\/agents\/[^/]+\.md$/;

// A Read/Grep/Glob call within this many conductor tool_use events
// immediately following a subagent (Agent-tool) spawn's tool_result is
// treated as a post-spawn spot-check and excluded. CRITICAL FIX: the
// window is bound to the tool_use_id of an Agent block's OWN result -
// any other tool's tool_result (e.g. a Read/Bash result) must NOT open or
// extend this window. An earlier version reset the window on ANY
// tool_result, which measured 93.9% of investigation calls as
// "post-spawn spot-checks" in a zero-spawn session.
const POST_SPAWN_SPOTCHECK_WINDOW = 2;

// Size ceiling above which a transcript file is treated as unavailable
// rather than partially summed (mirrors hooks/subagent-stop-spawn-emit.js's
// 20 MiB transcript-too-large convention, sized down here since Stop-hook
// transcripts routinely run under 1 MB and a much larger file is
// atypical/pathological for this use case).
const DEFAULT_MAX_TRANSCRIPT_BYTES = 20 * 1024 * 1024;

// Calibrated default. See bin/ds-measure-conductor-tool-calls's header for
// the live measurement table (the detector's own cumulative
// whole-transcript statistic, NOT the calibrator's former max-consecutive-
// run-length statistic - those are different measures of different
// things). Config-reversible via .agentic/config.json's
// conductor_overreach_threshold key.
const DEFAULT_THRESHOLD = 12;

/**
 * @param {string} value
 * @returns {boolean}
 */
function _isWhitelistedPath(value) {
  if (!value || typeof value !== 'string') return false;
  for (const sub of WHITELIST_PATH_SUBSTRINGS) {
    if (value.includes(sub)) return true;
  }
  return WHITELIST_PATH_RE.test(value);
}

/**
 * @param {string} cmd
 * @returns {boolean}
 */
function _isReadShapedBash(cmd) {
  if (!cmd || typeof cmd !== 'string') return false;
  const firstSegment = cmd.split(/[|;&]/)[0].trim();
  const tokens = firstSegment.split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return false;
  const binary = tokens[0].split('/').pop();
  if (binary === 'git') {
    return tokens.length > 1 && READ_SHAPED_GIT_SUBCOMMANDS.has(tokens[1]);
  }
  return READ_SHAPED_BASH_BINARIES.has(binary);
}

/**
 * @param {object} toolInput
 * @returns {string}
 */
function _toolInputPath(toolInput) {
  if (!toolInput || typeof toolInput !== 'object') return '';
  for (const key of ['file_path', 'path', 'pattern', 'notebook_path']) {
    if (typeof toolInput[key] === 'string') return toolInput[key];
  }
  return '';
}

/**
 * Read and parse a Claude Code transcript JSONL file into a flat ordered
 * list of { type: 'tool_use'|'tool_result', name, id, tool_use_id, input }
 * blocks, in file order. Bounded by DEFAULT_MAX_TRANSCRIPT_BYTES (or the
 * caller-supplied maxBytes); malformed lines are skipped and do not count
 * toward parsedCount.
 *
 * @param {string} transcriptPath
 * @param {number} [maxBytes]
 * @returns {{ blocks: Array, parsedCount: number, note: string|null }}
 */
function parseTranscriptBlocks(transcriptPath, maxBytes) {
  const cap = typeof maxBytes === 'number' && maxBytes > 0
    ? maxBytes
    : DEFAULT_MAX_TRANSCRIPT_BYTES;

  if (!transcriptPath || typeof transcriptPath !== 'string') {
    return { blocks: [], parsedCount: 0, note: 'unavailable (transcript_path missing)' };
  }

  let stat;
  try {
    stat = fs.statSync(transcriptPath);
  } catch (_) {
    return { blocks: [], parsedCount: 0, note: 'unavailable (transcript not found)' };
  }

  if (!stat.isFile()) {
    return { blocks: [], parsedCount: 0, note: 'unavailable (transcript not found)' };
  }

  if (stat.size > cap) {
    return { blocks: [], parsedCount: 0, note: 'skipped (transcript too large)' };
  }

  let raw;
  try {
    raw = fs.readFileSync(transcriptPath, 'utf8');
  } catch (_) {
    return { blocks: [], parsedCount: 0, note: 'unavailable (transcript unreadable)' };
  }

  const blocks = [];
  let parsedCount = 0;

  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try {
      obj = JSON.parse(trimmed);
    } catch (_) {
      continue;
    }
    const msg = obj && obj.message;
    if (!msg || !Array.isArray(msg.content)) continue;
    parsedCount += 1;
    for (const block of msg.content) {
      if (!block || typeof block !== 'object') continue;
      if (block.type === 'tool_use') {
        blocks.push({
          type: 'tool_use',
          name: typeof block.name === 'string' ? block.name : '',
          id: typeof block.id === 'string' ? block.id : null,
          input: block.input || {},
        });
      } else if (block.type === 'tool_result') {
        blocks.push({
          type: 'tool_result',
          tool_use_id: typeof block.tool_use_id === 'string' ? block.tool_use_id : null,
        });
      }
    }
  }

  if (parsedCount === 0) {
    return { blocks: [], parsedCount: 0, note: 'unavailable (transcript unreadable)' };
  }

  return { blocks, parsedCount, note: null };
}

/**
 * Core algorithm: compute conductor-overreach counts from an in-memory,
 * ordered flat block list (as produced by parseTranscriptBlocks). Exported
 * directly so tests can exercise the algorithm without a filesystem
 * fixture.
 *
 * @param {Array} blocks
 * @param {number} [threshold] - defaults to DEFAULT_THRESHOLD.
 * @returns {{conductor_tool_calls: number, live_or_completed_spawns: number,
 *   ratio_trigger: boolean, whitelisted_reads_excluded: number}}
 */
function computeOverreachFromBlocks(blocks, threshold) {
  const thresh = typeof threshold === 'number' && threshold > 0 ? threshold : DEFAULT_THRESHOLD;

  let conductorToolCalls = 0;
  let spawns = 0;
  let whitelistedExcluded = 0;

  // Tracks tool_use ids for every tool_use block seen so far, so a
  // tool_result can be correlated back to the tool that produced it.
  const toolNameById = Object.create(null);

  // null = not inside a post-spawn spot-check window. A non-null integer
  // counts conductor tool_use events observed since the most recent
  // Agent-tool tool_result (and ONLY an Agent-tool tool_result - CRITICAL
  // FIX, see POST_SPAWN_SPOTCHECK_WINDOW's comment above).
  let sinceLastAgentResult = null;

  if (!Array.isArray(blocks)) {
    return {
      conductor_tool_calls: 0,
      live_or_completed_spawns: 0,
      ratio_trigger: false,
      whitelisted_reads_excluded: 0,
    };
  }

  for (const block of blocks) {
    if (!block || typeof block !== 'object') continue;

    if (block.type === 'tool_result') {
      const producerName = block.tool_use_id ? toolNameById[block.tool_use_id] : undefined;
      if (producerName === SPAWN_TOOL_NAME) {
        sinceLastAgentResult = 0;
      }
      // A non-Agent tool_result must NOT touch the window at all -
      // neither opening nor extending it.
      continue;
    }

    if (block.type !== 'tool_use') continue;

    const name = block.name || '';
    const toolInput = block.input || {};
    if (block.id) toolNameById[block.id] = name;

    if (sinceLastAgentResult !== null) sinceLastAgentResult += 1;

    if (name === SPAWN_TOOL_NAME) {
      spawns += 1;
      continue;
    }

    let isInvestigation = false;
    if (INVESTIGATION_TOOLS.has(name)) {
      isInvestigation = true;
    } else if (name === 'Bash') {
      const cmd = typeof toolInput.command === 'string' ? toolInput.command : '';
      if (_isReadShapedBash(cmd)) isInvestigation = true;
    }

    if (!isInvestigation) continue;

    const pathValue = _toolInputPath(toolInput);
    if (_isWhitelistedPath(pathValue)) {
      whitelistedExcluded += 1;
      continue;
    }

    if (sinceLastAgentResult !== null && sinceLastAgentResult <= POST_SPAWN_SPOTCHECK_WINDOW) {
      whitelistedExcluded += 1;
      continue;
    }

    conductorToolCalls += 1;
  }

  const ratioTrigger = conductorToolCalls > thresh && spawns === 0;

  return {
    conductor_tool_calls: conductorToolCalls,
    live_or_completed_spawns: spawns,
    ratio_trigger: ratioTrigger,
    whitelisted_reads_excluded: whitelistedExcluded,
  };
}

/**
 * Top-level entry point: read+parse the transcript file at transcriptPath
 * and compute conductor-overreach counts. Never throws; an unavailable
 * transcript returns available:false with a descriptive transcript_note
 * rather than a zero-filled accumulator indistinguishable from a real
 * zero-call session.
 *
 * @param {string} transcriptPath - payload.transcript_path from the real
 *   Stop payload.
 * @param {number} [threshold] - defaults to DEFAULT_THRESHOLD.
 * @param {number} [maxBytes] - defaults to DEFAULT_MAX_TRANSCRIPT_BYTES.
 * @returns {{available: boolean, conductor_tool_calls: number,
 *   live_or_completed_spawns: number, ratio_trigger: boolean,
 *   whitelisted_reads_excluded: number, transcript_note: string|null}}
 */
function computeOverreach(transcriptPath, threshold, maxBytes) {
  const parsed = parseTranscriptBlocks(transcriptPath, maxBytes);

  if (parsed.parsedCount === 0) {
    return {
      available: false,
      conductor_tool_calls: 0,
      live_or_completed_spawns: 0,
      ratio_trigger: false,
      whitelisted_reads_excluded: 0,
      transcript_note: parsed.note,
    };
  }

  const result = computeOverreachFromBlocks(parsed.blocks, threshold);
  return Object.assign({ available: true, transcript_note: null }, result);
}

module.exports = {
  computeOverreach,
  computeOverreachFromBlocks,
  parseTranscriptBlocks,
  DEFAULT_THRESHOLD,
  DEFAULT_MAX_TRANSCRIPT_BYTES,
};
