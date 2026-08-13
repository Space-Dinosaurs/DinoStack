#!/usr/bin/env node

/**
 * Purpose: Unregistered detection lib for the conductor_overreach warn-only
 *          Stop-hook nudge. Given the Stop payload's `transcript` array
 *          (main-session message history, same shape stop-context.js
 *          already consumes for its own extraction), computes how many
 *          investigation-shaped tool calls the conductor made this session
 *          with zero subagent spawns, after subtracting a mandated-preflight
 *          whitelist. Pure function, no I/O beyond the optional config read
 *          the caller passes in - this module does not touch the filesystem
 *          itself so it stays trivially testable with synthetic transcripts.
 *
 * Public API (CommonJS): computeOverreach(transcript, threshold) -> {
 *   conductor_tool_calls: number, live_or_completed_spawns: number,
 *   ratio_trigger: boolean, whitelisted_reads_excluded: number }
 *   DEFAULT_THRESHOLD - number, the calibrated default (see
 *   bin/ds-measure-conductor-tool-calls; measured against 60 real session
 *   transcripts on this machine, recommended_threshold=3).
 *
 * Upstream deps: none (Node built-ins only, no fs/child_process). Callers
 *                (hooks/conductor-overreach-nudge.js) are responsible for
 *                reading .agentic/config.json's conductor_overreach_threshold
 *                key and passing the resolved threshold in.
 *
 * Downstream consumers: hooks/conductor-overreach-nudge.js (registered Stop
 *                        hook). hooks/tests/test-conductor-overreach-nudge.js
 *                        exercises this module indirectly via fixtures piped
 *                        through the wrapper script.
 *
 * Failure modes: never throws. A malformed or non-array transcript is
 *                treated as empty (all counts zero, ratio_trigger false).
 *                No suppression-mute logic exists anywhere in this module by
 *                design - a prior design that grepped the transcript for an
 *                injected harness-suppression phrase and muted the advisory
 *                was removed by Skeptic Critical finding; do not re-derive
 *                it here.
 *
 * Performance: single pass over the transcript array, O(total tool_use
 *              blocks). No subprocess calls.
 */

'use strict';

// Tool names treated as conductor investigation-shaped calls.
const INVESTIGATION_TOOLS = new Set(['Read', 'Grep', 'Glob']);

// Read-shaped Bash binaries (first token of the first pipeline segment).
const READ_SHAPED_BASH_BINARIES = new Set([
  'grep', 'rg', 'cat', 'head', 'tail', 'find', 'ls', 'wc',
]);
const READ_SHAPED_GIT_SUBCOMMANDS = new Set(['show', 'diff', 'log', 'status']);

// Subagent-spawn tool name. Measured against 60 real transcripts on this
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
// immediately following a spawn's tool_result is treated as a post-spawn
// spot-check and excluded.
const POST_SPAWN_SPOTCHECK_WINDOW = 2;

// Calibrated default (bin/ds-measure-conductor-tool-calls, 60-transcript
// sample, recommended_threshold=3). Config-reversible via
// .agentic/config.json's conductor_overreach_threshold key.
const DEFAULT_THRESHOLD = 3;

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
 * Compute conductor-overreach counts for a Stop-payload transcript array.
 *
 * @param {Array} transcript - payload.transcript (array of message objects
 *   with .role and .content, matching the shape stop-context.js consumes).
 * @param {number} [threshold] - defaults to DEFAULT_THRESHOLD.
 * @returns {{conductor_tool_calls: number, live_or_completed_spawns: number,
 *   ratio_trigger: boolean, whitelisted_reads_excluded: number}}
 */
function computeOverreach(transcript, threshold) {
  const thresh = typeof threshold === 'number' && threshold > 0 ? threshold : DEFAULT_THRESHOLD;

  let conductorToolCalls = 0;
  let spawns = 0;
  let whitelistedExcluded = 0;

  if (!Array.isArray(transcript)) {
    return {
      conductor_tool_calls: 0,
      live_or_completed_spawns: 0,
      ratio_trigger: false,
      whitelisted_reads_excluded: 0,
    };
  }

  // Track how many conductor tool_use events have occurred since the most
  // recent tool_result block, to detect the post-spawn spot-check window.
  let sinceLastResult = null;

  for (const msg of transcript) {
    if (!msg || !Array.isArray(msg.content)) continue;
    for (const block of msg.content) {
      if (!block || typeof block !== 'object') continue;

      if (block.type === 'tool_result') {
        sinceLastResult = 0;
        continue;
      }
      if (block.type !== 'tool_use') continue;

      const name = typeof block.name === 'string' ? block.name : '';
      const toolInput = block.input || {};

      if (sinceLastResult !== null) sinceLastResult += 1;

      if (name === SPAWN_TOOL_NAME) {
        spawns += 1;
        sinceLastResult = null;
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

      if (sinceLastResult !== null && sinceLastResult <= POST_SPAWN_SPOTCHECK_WINDOW) {
        whitelistedExcluded += 1;
        continue;
      }

      conductorToolCalls += 1;
    }
  }

  const ratioTrigger = conductorToolCalls > thresh && spawns === 0;

  return {
    conductor_tool_calls: conductorToolCalls,
    live_or_completed_spawns: spawns,
    ratio_trigger: ratioTrigger,
    whitelisted_reads_excluded: whitelistedExcluded,
  };
}

module.exports = {
  computeOverreach,
  DEFAULT_THRESHOLD,
};
