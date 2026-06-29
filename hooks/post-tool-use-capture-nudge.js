#!/usr/bin/env node

/**
 * Purpose: Claude Code PostToolUse(Task/Agent) hook. Runs two independent advisory
 *          nudges on every background subagent spawn (async_launched):
 *
 *          1. Capture-gap nudge (always active): when a learning-worthy event exists
 *             but no learning has been captured yet, emits a CAPTURE-NUDGE so the
 *             conductor can spawn learnings-agent in-session rather than waiting for
 *             the Stop-hook backstop.
 *
 *          2. Skill-candidate nudge (Layer 2, opt-in): when both
 *             skill_candidate_detection !== false AND skill_candidate_nudge === true
 *             in [cwd]/.agentic/config.json, calls peekActiveCandidates() (read-only
 *             - never writes the tally or advances the cursor) and emits a
 *             SKILL-CANDIDATE-NUDGE for each candidate not yet nudged this session.
 *             Default: off (skill_candidate_nudge defaults to false when absent).
 *
 * Public API: run() - invoked immediately at module load via run() call at the
 *             bottom of the file. Not imported in production; executed as a CLI
 *             script by the Claude Code PostToolUse(Task/Agent) hook. The test loads
 *             it via a tmp shim that suppresses run() and exercises the body.
 *
 * Upstream deps: Node built-ins only (fs, path) plus two local CommonJS modules:
 *                hooks/lib/capture-gap.js (detectCaptureGap) and
 *                hooks/lib/skill-candidate-detector.js (peekActiveCandidates).
 *                No npm dependencies.
 *                Reads PostToolUse payload from stdin (fd 0); reads
 *                [cwd]/.agentic/.capture-gap-surfaced (capture dedup tracker, fail-open);
 *                [cwd]/.agentic/.skill-candidates-in-session (skill dedup, JSONL
 *                {session_id, candidate_id}, fail-open);
 *                [cwd]/.agentic/config.json (read-only, skill_candidate_detection +
 *                skill_candidate_nudge toggles);
 *                detectCaptureGap reads [cwd]/.agentic/events.jsonl,
 *                [cwd]/.agentic/learnings.md, [cwd]/.agentic/.capture-gap-last-sweep
 *                (cursor READ only), and runs one git diff subprocess.
 *                peekActiveCandidates reads [cwd]/.agentic/.skill-candidate-tally.json
 *                (READ-ONLY - never writes the tally or cursor).
 *                Writes ONLY [cwd]/.agentic/.capture-gap-surfaced (atomic tmp+rename)
 *                and [cwd]/.agentic/.skill-candidates-in-session (atomic append).
 *                NEVER writes .capture-gap-last-sweep (owned by stop-context.js),
 *                .skill-candidate-tally.json, .skill-candidate-cursor, or any other
 *                tally/cursor file.
 *
 * Downstream consumers: Claude Code PostToolUse(Task/Agent) hook (wired by
 *                        .claude/install.sh; matchers "Task" and "Agent"). The
 *                        conductor reads the additionalContext message next to the
 *                        spawn tool result.
 *
 * Failure modes: Fully soft-fail. The entire body is wrapped in try/catch and
 *                always process.exit(0) - the hook NEVER blocks a spawn, never
 *                writes to stderr, never emits non-JSON to stdout. Malformed
 *                stdin, a non-Task/Agent tool, a non-async_launched response, an absent
 *                dedup tracker, a detector error, or a tracker-write failure all
 *                resolve to a silent exit 0. Both dedup trackers are fail-open: a
 *                missing or unreadable tracker is treated as "not yet surfaced"
 *                so the nudge fires (a duplicate nudge is cheaper than a missed one).
 *                The skill-candidate nudge path is independently gated; an error
 *                in it never suppresses the capture-gap nudge.
 *
 * Performance: ~5-30 ms typical; detectCaptureGap's git subprocess (5 s timeout)
 *              runs only once a worthy event is found, so the common no-event
 *              spawn costs a single events.jsonl read and returns early. The skill
 *              peek adds one tally file read only when both toggles are enabled.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { detectCaptureGap } = require('./lib/capture-gap.js');
const { peekActiveCandidates } = require('./lib/skill-candidate-detector.js');

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

// Skill-candidate nudge text. {domain}, {artifact}, and {count} are substituted per candidate.
const SKILL_NUDGE_TEMPLATE =
  'SKILL-CANDIDATE-NUDGE: recurring friction pattern detected for domain "{domain}" '
  + '(lifetime count: {count}, suggested artifact: {artifact}). '
  + 'This may warrant a new skill. Run /skill-candidates to review the backlog, '
  + 'or invoke the skill-creator skill to convert this pattern into a reusable skill.';

/**
 * Read the skill_candidate_detection and skill_candidate_nudge toggles from
 * [cwd]/.agentic/config.json.
 *
 * - skill_candidate_detection: default TRUE when absent/unreadable (master toggle).
 *   Only disabled when explicitly set to false (boolean). Consistent with
 *   stop-context.js skillCandidateDetectionEnabled.
 * - skill_candidate_nudge: default FALSE when absent/unreadable (Layer 2 opt-in).
 *   Only enabled when explicitly set to true (boolean). Default-off by design.
 *
 * Returns { detectionEnabled: boolean, nudgeEnabled: boolean }.
 * Fail-open on any error: detection defaults true, nudge defaults false.
 *
 * @param {string} cwd - Project root.
 * @returns {{ detectionEnabled: boolean, nudgeEnabled: boolean }}
 */
function readSkillConfig(cwd) {
  try {
    const configPath = path.join(cwd, '.agentic', 'config.json');
    const raw = fs.readFileSync(configPath, 'utf8');
    const config = JSON.parse(raw);
    const detectionEnabled = !(config && config.skill_candidate_detection === false);
    const nudgeEnabled = !!(config && config.skill_candidate_nudge === true);
    return { detectionEnabled, nudgeEnabled };
  } catch (_) {
    // Absent/unreadable/invalid config: master default on, nudge default off.
    return { detectionEnabled: true, nudgeEnabled: false };
  }
}

/**
 * Read the skill-candidate in-session dedup tracker. Returns a Set of
 * "session_id:candidate_id" keys that have already been nudged this session.
 * Fail-open: missing or unreadable tracker returns an empty Set (fires nudge).
 *
 * Tracker format: JSONL, one { session_id, candidate_id } per line.
 *
 * @param {string} cwd - Project root.
 * @returns {Set<string>} keys in the form "session_id:candidate_id"
 */
function readSkillNudgeSurfaced(cwd) {
  try {
    const trackerPath = path.join(cwd, '.agentic', '.skill-candidates-in-session');
    if (!fs.existsSync(trackerPath)) return new Set();
    const raw = fs.readFileSync(trackerPath, 'utf8');
    const result = new Set();
    for (const line of raw.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let obj;
      try { obj = JSON.parse(trimmed); } catch (_) { continue; }
      if (obj && typeof obj.session_id === 'string' && typeof obj.candidate_id === 'string') {
        result.add(`${obj.session_id}:${obj.candidate_id}`);
      }
    }
    return result;
  } catch (_) {
    return new Set();
  }
}

/**
 * Atomically append a dedup entry for (session_id, candidate_id) to the
 * in-session tracker. Uses read-existing + tmp-write + rename for atomicity.
 * Silent failure: a missed write at worst re-nudges on the next spawn.
 *
 * @param {string} cwd - Project root.
 * @param {string} sessionId
 * @param {string} candidateId - domain slug used as the candidate identifier
 */
function recordSkillNudgeSurfaced(cwd, sessionId, candidateId) {
  const agenticDir = path.join(cwd, '.agentic');
  const trackerPath = path.join(agenticDir, '.skill-candidates-in-session');
  fs.mkdirSync(agenticDir, { recursive: true });

  let existing = '';
  try {
    if (fs.existsSync(trackerPath)) existing = fs.readFileSync(trackerPath, 'utf8');
  } catch (_) { /* fall through with empty existing */ }

  const entry = JSON.stringify({ session_id: sessionId, candidate_id: candidateId });
  const body = (existing && !existing.endsWith('\n')) ? existing + '\n' : existing;
  const next = body + entry + '\n';

  const tmpPath = trackerPath + '.tmp';
  fs.writeFileSync(tmpPath, next, 'utf8');
  fs.renameSync(tmpPath, trackerPath);
}

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

    // --- 2. Gate on tool_name in {"Task","Agent"} && tool_response.status === "async_launched" ---
    // Background subagent spawns (which this methodology mandates) fire PostToolUse at
    // LAUNCH with status "async_launched"; the subagent output is not yet available,
    // so the signal source is events.jsonl via detectCaptureGap, not tool_response.
    // Claude Code renamed the spawn tool from "Task" to "Agent"; accept both names so
    // the nudge keeps firing across CC versions (install.sh wires both matchers).
    const toolName = payload && payload.tool_name;
    const toolResponse = (payload && payload.tool_response) || {};
    if (toolName !== 'Task' && toolName !== 'Agent') process.exit(0);
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

    // --- 4. Capture-gap nudge path ---
    // Runs first; emits and exits if a capture gap is found and not yet surfaced.
    // Falls through to the skill-nudge path when no gap exists or already surfaced.
    const gap = detectCaptureGap(cwd, sessionId);
    if (gap && gap.shouldNudge === true && !alreadySurfaced(cwd, sessionId, gap.lastEventTs)) {
      // Record dedup + emit. On tracker write failure, still emit (cheap duplicate
      // nudge is acceptable; a missed dedup record at worst re-nudges next spawn).
      try {
        recordSurfaced(cwd, sessionId, gap.lastEventTs);
      } catch (_) { /* soft-fail */ }

      const additionalContext = gap.residualOnly ? NUDGE_RESIDUAL : NUDGE_STANDARD;
      process.stdout.write(JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PostToolUse',
          additionalContext,
        },
        suppressOutput: true,
      }));
      process.exit(0);
    }

    // --- 5. Skill-candidate Layer-2 nudge path ---
    // Runs when the capture-gap path did not fire (no gap, or already surfaced).
    // Independently gated on both skill toggles; read-only peek on the tally.
    runSkillNudge(cwd, sessionId);

    process.exit(0);
  } catch (_) {
    // Soft-fail: any unexpected error -> silent exit 0. Never block a spawn.
    process.exit(0);
  }
}

/**
 * Skill-candidate Layer-2 nudge path. Runs independently after the capture-gap
 * path (which may have already exited). Called from run() only when the capture-gap
 * path determines the tool/response is a valid async_launched Task/Agent spawn.
 *
 * Gating: both skill_candidate_detection !== false AND skill_candidate_nudge === true
 * must hold. Out-of-the-box the nudge is SILENT (nudge defaults false).
 *
 * Peek is READ-ONLY: peekActiveCandidates never writes the tally or cursor.
 *
 * @param {string} cwd - Project root.
 * @param {string} sessionId - Session uuid for dedup keying.
 */
function runSkillNudge(cwd, sessionId) {
  try {
    // Gate 1: both toggles must be on.
    const { detectionEnabled, nudgeEnabled } = readSkillConfig(cwd);
    if (!detectionEnabled || !nudgeEnabled) return;

    // Gate 2: read active candidates (read-only peek; never writes).
    const candidates = peekActiveCandidates(cwd);
    if (!candidates || candidates.length === 0) return;

    // Gate 3: per-candidate dedup (one nudge per candidate per session).
    const alreadySurfacedSet = readSkillNudgeSurfaced(cwd);
    const toNudge = candidates.filter((c) => {
      const key = `${sessionId}:${c.domain}`;
      return !alreadySurfacedSet.has(key);
    });
    if (toNudge.length === 0) return;

    // Record dedup entries BEFORE emitting (fail-open: a write error still emits).
    for (const c of toNudge) {
      try {
        recordSkillNudgeSurfaced(cwd, sessionId, c.domain);
      } catch (_) { /* soft-fail; at worst re-nudges next spawn */ }
    }

    // Compose and emit the nudge for all unseen candidates.
    const lines = toNudge.map((c) =>
      SKILL_NUDGE_TEMPLATE
        .replace('{domain}', c.domain)
        .replace('{count}', String(c.count))
        .replace('{artifact}', c.suggestedArtifact || 'command')
    );
    const additionalContext = lines.join('\n');

    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PostToolUse',
        additionalContext,
      },
      suppressOutput: true,
    }));
  } catch (_) {
    // Soft-fail: skill nudge errors never propagate or block the spawn.
  }
}

run();
