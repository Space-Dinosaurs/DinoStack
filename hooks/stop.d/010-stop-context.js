#!/usr/bin/env node

/**
 * Purpose: Reads the Claude Code Stop hook JSON payload from stdin and writes
 *          session context to disk so the next session's Workers have lightweight
 *          context about what was happening. Also marks any active orchestration
 *          loop as interrupted so the next session can offer to resume. Writes
 *          per-developer session telemetry via a three-branch identity gate:
 *          confirmed identity -> per-project log + global mirror; provisional
 *          identity or no identity -> pending buffer (~/.agentic/session-log/.pending/);
 *          no identity also appends a one-time nudge to context.md. Runs a
 *          capture-gap backstop that detects learning-worthy sessions with no
 *          captured learnings and appends a nudge to context.md.
 *
 * Public API: run() — invoked immediately at module load via run() call at
 *             bottom of file. Not imported; executed as a CLI script by the
 *             Claude Code Stop hook. Internal helpers: writeLoopState(cwd),
 *             writeBatchState(cwd, sessionId), scanSessionAggregate(eventsPath, sessionId),
 *             writeSessionTotal(cwd, sessionId), computeSessionTotals(cwd, sessionId),
 *             getIdentity(cwd), writeSessionLog(cwd, identity, sessionId),
 *             writeSessionLogGlobal(identity, sessionId, data),
 *             writePendingBuffer(cwd, sessionId),
 *             appendIdentityNudgeToContextMd(repoRoot),
 *             detectCaptureGap(cwd, sessionId),
 *             appendCaptureGapNoticeToContextMd(cwd, residualOnly),
 *             wrapLockHeld(cwd) (thin alias to wrap-marker lib),
 *             appendSpilloverRecord(cwd, record),
 *             writeContextMdOrSpill(cwd, outputPath, projectDir, body, record),
 *             stageWrapPending(cwd, sessionId, scan) (thin alias to wrap-marker
 *             lib stagePending). The marker reads/transitions (readLastWrap,
 *             liveMarkerForSession - which replaces the former liveMarkerExists -
 *             stagePending, touchHeartbeat, etc.) now live in
 *             hooks/lib/wrap-marker.js, the single source of truth.
 *
 * Upstream deps: Node built-ins only (fs, path, os, child_process) plus the
 *                local CommonJS module hooks/lib/wrap-marker.js (the deferred-/wrap
 *                marker single source of truth - lock gate, per-session staging,
 *                heartbeat; loaded via a lazy try/catch IIFE at module scope -
 *                if the lib is absent a fail-open shim is substituted so the
 *                script degrades gracefully rather than crashing at load time).
 *                Relocated to hooks/stop.d/010-stop-context.js; require path is
 *                '../lib/wrap-marker.js' (one dir deeper than the former
 *                hooks/stop-context.js location). No npm dependencies. Reads
 *                from stdin (fd 0).
 *                Reads/writes
 *                ~/.claude/projects/[hash]/context.md,
 *                [cwd]/.agentic/loop-state.json,
 *                [cwd]/.agentic/batch-state.json,
 *                [cwd]/.agentic/session-log/<developer_id>.jsonl,
 *                ~/.agentic/session-log/<developer_id>.jsonl (global mirror),
 *                ~/.agentic/session-log/.pending/<session_uuid>.json (pending buffer),
 *                ~/.agentic/identity.yml (read-only, global),
 *                [cwd]/.agentic/identity.yml (read-only, project-local; takes precedence
 *                over global when confirmed, per 4-tier resolution in getIdentity(cwd)),
 *                [cwd]/.agentic/config.json (read-only, deferred_wrap_daemon toggle),
 *                [cwd]/.agentic/events.jsonl (read-only for capture-gap backstop),
 *                [cwd]/.agentic/learnings.md (read-only for capture-gap backstop),
 *                [cwd]/.agentic/.capture-gap-last-sweep (pagination cursor; atomic
 *                tmp+rename on write).
 *                Via wrap-marker.js it also touches [cwd]/.agentic/wrap/heartbeats/<session_id>
 *                (per-turn liveness mtime) and may stage
 *                [cwd]/.agentic/wrap/pending-<session_id>.json (per-session marker).
 *
 * Downstream consumers: Claude Code Stop hook (configured in
 *                        ~/.claude/settings.json or project .claude/settings.json).
 *                        Output files are read by Worker agents at session start.
 *                        bin/agentic-cost team reads .agentic/session-log/ for
 *                        team-level aggregation.
 *                        bin/agentic-cost operator reads ~/.agentic/session-log/*.jsonl
 *                        for global operator rollup. The .pending/ subdir is NOT
 *                        globbed by agentic-cost (operator or team) - it is consumed
 *                        only by agentic-identity confirm/init via flushPendingBuffer.
 *
 * Failure modes: Lib-absent degrade: if hooks/lib/wrap-marker.js cannot be
 *                required at module load (e.g. missing lib in a stripped install),
 *                a fail-open shim is substituted (wrapLockHeld -> false,
 *                stopDeferredActivityPath -> path.join(cwd, '.agentic', 'wrap',
 *                'deferred-activity.jsonl'), stagePending -> false,
 *                touchHeartbeat -> false). The script continues to run; wrap-marker
 *                dependent paths (lock gate, spillover, staging, heartbeat) silently
 *                degrade to no-ops.
 *                All other failures are silent (process.exit(0)). Eleven independent
 *                write paths: (1) context.md write is best-effort; any fs error
 *                is swallowed and the file may not be written. (2) loop-state.json
 *                write is also best-effort; any fs error is swallowed independently
 *                of path (1). (3) events.jsonl write is best-effort; any fs error
 *                is swallowed independently of paths (1) and (2). The append
 *                failure model is identical to context.md - the next session
 *                can re-derive totals from per-spawn events if needed.
 *                (4) writeBatchState writes interrupted-status to
 *                .agentic/batch-state.json on session exit; aborts silently on
 *                session_id mismatch with the file's owner, on missing file, or
 *                on parse error. Best-effort silent-fail; failure of
 *                writeBatchState does not block writeSessionTotal.
 *                (5) writeSessionLog appends to .agentic/session-log/<dev>.jsonl;
 *                any fs error is swallowed independently of all other paths.
 *                (6) appendIdentityNudgeToContextMd appends to context.md; any
 *                fs error is swallowed independently. Because the nudge is a
 *                context.md writer, it is deferred while wrapLockHeld(cwd) is
 *                true (the sentinel is consumed atomically with the nudge, so
 *                deferring both fires the one-time nudge on a later unlocked
 *                session rather than losing it).
 *                (7) writeSessionLogGlobal appends to ~/.agentic/session-log/<dev>.jsonl;
 *                any fs error is swallowed independently of the per-project write
 *                (path 5) - a global failure never affects the per-project write.
 *                (8) writePendingBuffer writes atomically (tmp+rename) to
 *                ~/.agentic/session-log/.pending/<uuid>.json; enforces cap-100
 *                (drops oldest by ts with one stderr notice); any fs error swallowed
 *                independently of all other paths.
 *                (9) appendCaptureGapNoticeToContextMd appends to context.md; any
 *                fs error is swallowed independently. The .capture-gap-last-sweep
 *                cursor update is also best-effort and never blocks exit.
 *                (10) appendSpilloverRecord appends one JSONL record to
 *                .agentic/wrap/deferred-activity.jsonl when wrapLockHeld(cwd) is
 *                true (a /wrap holds .agentic/wrap/lock); in that case BOTH
 *                context.md write paths (path 1) are skipped so the background
 *                enrichment's locked Part-A merge is not clobbered, and the
 *                skipped activity is spilled instead for the enrichment to drain.
 *                Append-only, fail-open.
 *                (11) wrapMarker.touchHeartbeat writes/utimes
 *                .agentic/wrap/heartbeats/<session_id> once per turn (per-session
 *                liveness mtime); no-op under the AGENTIC_WRAP_DAEMON loop-guard;
 *                any fs error swallowed independently of all other paths.
 *                Marker staging (stageWrapPending -> wrap-marker lib) shares this
 *                fail-open discipline and is never counted as blocking exit.
 *                All eleven paths are independent - a failure in one does not
 *                affect the others. The 10-minute implicit-interrupt heuristic
 *                handles missed loop-state writes. cwd values with path
 *                traversal components are rejected for the loop-state and
 *                batch-state writes (defence in depth).
 *
 *                Lock-aware interactions: wrapLockHeld(cwd) (a single fail-open
 *                fs.existsSync on .agentic/wrap/lock, a DIRECTORY created by
 *                /wrap) gates path 1; it is re-checked immediately before each
 *                context.md writeFileSync to minimize TOCTOU. stageWrapPending
 *                (delegated to wrap-marker lib stagePending) stages a per-session
 *                .agentic/wrap/pending-<session_id>.json marker (schema_version 3,
 *                atomic tmp+rename, NORMATIVE schema in content/commands/wrap.md)
 *                so the next session or the daemon can complete enrichment for an
 *                un-wrapped session; staging is suppressed when the current
 *                session_id equals .agentic/wrap/last-wrap (this session already
 *                wrapped), when this session's marker is already ready / pending /
 *                in_progress (MAJOR-3), when the session had no substantive
 *                activity, or under the AGENTIC_WRAP_DAEMON loop-guard. Staging is
 *                fail-open and never blocks exit.
 *
 * Performance: ~5-20 ms typical; one git status subprocess call (5 s timeout)
 *              plus one git diff subprocess call for the capture-gap backstop
 *              (5 s timeout, soft-fail). Synchronous I/O throughout; runs as a
 *              short-lived CLI process.
 */

/**
 * Claude Code Stop Hook — Session Context Writer
 *
 * Reads the Stop hook JSON payload from stdin and writes a minimal context.md
 * file to ~/.claude/projects/[hash]/ so that the next session's Workers have
 * lightweight context about what was happening.
 *
 * Design goals:
 *  - Silent failure: any error exits 0, nothing written to stderr
 *  - No external dependencies: only Node built-ins
 *  - Fast: no LLM call, pure text extraction
 *  - /wrap coexistence: if context.md was written by /wrap (detected by
 *    "# Session Context\n*Written by /wrap" at the file start), the Stop hook
 *    appends a "Session Activity" block rather than overwriting. Any previous
 *    activity block is replaced, not accumulated - most recent session only.
 *    /wrap content is preserved indefinitely; only another /wrap run replaces
 *    the whole file. The Stop hook is the fallback for sessions where /wrap
 *    was never run.
 *
 * Output path: ~/.claude/projects/[hash]/context.md
 *   where hash = cwd with every '/' replaced by '-' (leading '-' is kept)
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

// Single source of truth for the deferred-/wrap marker state machine, lock,
// heartbeat, and sentinel. The local helpers that previously lived in this file
// (wrapLockHeld, readLastWrap, liveMarkerExists, stageWrapPending) are now
// delegated to this lib so stop-context.js, the SessionEnd hook, and the daemon
// share one atomic, fail-open implementation.
const wrapMarker = (() => {
  try {
    return require('../lib/wrap-marker.js');
  } catch (_) {
    return {
      wrapLockHeld: () => false,
      stopDeferredActivityPath: (cwd) => require('path').join(cwd, '.agentic', 'wrap', 'deferred-activity.jsonl'),
      stagePending: () => false,
      touchHeartbeat: () => false,
    };
  }
})();

/**
 * Read the `deferred_wrap_daemon` toggle from [cwd]/.agentic/config.json.
 * Fail-open: absent file, unreadable file, parse error, or absent key all
 * resolve to false. This is an OUTER config gate; the in-lib daemonGuardActive()
 * inner guard inside touchHeartbeat is PRESERVED (they serve different purposes).
 * Sister implementation: hooks/session-end-wrap.js deferredDaemonEnabled (keep in sync).
 *
 * @param {string} cwd - Project root directory.
 * @returns {boolean}
 */
function deferredDaemonEnabled(cwd) {
  try {
    const configPath = path.join(cwd, '.agentic', 'config.json');
    const raw = fs.readFileSync(configPath, 'utf8');
    const config = JSON.parse(raw);
    return config && config.deferred_wrap_daemon === true;
  } catch (_) {
    return false;
  }
}

/**
 * Write interrupted status to loop-state.json if an active loop exists.
 * Called from ALL exit paths so the loop-state write is never skipped.
 * Silent failure: any error is swallowed independently of the context write.
 * @param {string} cwd - Verified project directory (already traversal-checked by caller).
 */
function writeLoopState(cwd) {
  // M3: Reject cwd values with traversal components before any path join.
  // path.resolve normalizes '..' segments; if the result differs from the
  // input, cwd was not a clean absolute path and could escape the project dir.
  const resolvedCwd = path.resolve(cwd);
  if (resolvedCwd !== cwd) {
    // cwd contains traversal components - skip loop-state write silently.
    return;
  }

  try {
    const loopStatePath = path.join(cwd, '.agentic', 'loop-state.json');
    if (fs.existsSync(loopStatePath)) {
      const loopState = JSON.parse(fs.readFileSync(loopStatePath, 'utf-8'));
      if (loopState.status === 'active') {
        loopState.status = 'interrupted';
        loopState.interrupted_at = new Date().toISOString();
        loopState.interrupt_reason = 'unknown'; // cannot distinguish rate_limit vs crash at hook time
        const tmpPath = loopStatePath + '.tmp';
        fs.writeFileSync(tmpPath, JSON.stringify(loopState, null, 2));
        fs.renameSync(tmpPath, loopStatePath);
      }
    }
  } catch (_) {
    // Silent failure - the 10-minute implicit-interrupt heuristic handles missed writes
  }
}

/**
 * Write interrupted status to batch-state.json if an active batch exists AND
 * the file is owned by the current session. Mirrors writeLoopState but with
 * an additional session_id ownership check (the Stop hook must not steal
 * another session's batch state). Silent failure: any error swallowed.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid from the Stop payload.
 */
function writeBatchState(cwd, sessionId) {
  // Reject cwd values with traversal components before any path join.
  const resolvedCwd = path.resolve(cwd);
  if (resolvedCwd !== cwd) {
    return;
  }

  try {
    const batchStatePath = path.join(cwd, '.agentic', 'batch-state.json');
    if (!fs.existsSync(batchStatePath)) return;
    const batchState = JSON.parse(fs.readFileSync(batchStatePath, 'utf-8'));

    // Ownership check: do not steal another session's batch state.
    // If the file's session_id is a non-empty string and does not match the
    // current session, abort silently.
    if (typeof batchState.session_id === 'string'
        && batchState.session_id.length > 0
        && batchState.session_id !== sessionId) {
      return;
    }

    if (batchState.status !== 'active') return;

    const nowIso = new Date().toISOString();
    batchState.status = 'interrupted';
    batchState.interrupted_at = nowIso;
    batchState.interrupt_reason = 'unknown';
    batchState.updated_at = nowIso;

    const tmpPath = batchStatePath + '.tmp';
    fs.writeFileSync(tmpPath, JSON.stringify(batchState, null, 2));
    fs.renameSync(tmpPath, batchStatePath);
  } catch (_) {
    // Silent failure - best-effort write; resume-time logic tolerates absent mark.
  }
}

/**
 * Scan events.jsonl and return aggregate totals for the current session.
 * Returns null if the file is absent, empty, or unreadable.
 *
 * The returned by_agent map uses the rich token structure (4 bands) needed by
 * writeSessionTotal. writeSessionLog re-shapes it to its own output format.
 *
 * @param {string} eventsPath - Absolute path to events.jsonl.
 * @param {string|null} sessionId - Current session uuid (null = include all).
 * @returns {{wall_seconds: number, tokens: object, spawn_count: number,
 *            by_agent: object}|null}
 */
function scanSessionAggregate(eventsPath, sessionId) {
  if (!fs.existsSync(eventsPath)) return null;
  const raw = fs.readFileSync(eventsPath, 'utf8');
  if (!raw.trim()) return null;

  const lines = raw.split('\n');
  let totalWall = 0;
  let spawnCount = 0;
  const totalTokens = { input: 0, output: 0, cache_creation: 0, cache_read: 0 };
  const byAgent = {};

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try { obj = JSON.parse(trimmed); } catch (_) { continue; }
    const ev = obj && obj.event;
    if (ev !== 'spawn_complete' && ev !== 'conductor_direct') continue;
    const data = (obj && obj.data) || {};
    // Filter to current session when session_uuid is present on the
    // event payload. Events without session_uuid are included
    // unconditionally (tolerant of pre-instrumentation events).
    if (sessionId && data.session_uuid && data.session_uuid !== sessionId) {
      continue;
    }
    const wall = Number(data.wall_seconds) || 0;
    totalWall += wall;
    const tokens = data.tokens || {};
    for (const k of ['input', 'output', 'cache_creation', 'cache_read']) {
      totalTokens[k] += Number(tokens[k]) || 0;
    }
    if (ev === 'spawn_complete') {
      spawnCount += 1;
      const agentName = obj.agent || 'unknown';
      if (!byAgent[agentName]) {
        byAgent[agentName] = {
          spawns: 0, wall_seconds: 0,
          tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
        };
      }
      byAgent[agentName].spawns += 1;
      byAgent[agentName].wall_seconds += wall;
      for (const k of ['input', 'output', 'cache_creation', 'cache_read']) {
        byAgent[agentName].tokens[k] += Number(tokens[k]) || 0;
      }
    }
  }

  return {
    wall_seconds: Number(totalWall.toFixed(3)),
    tokens: totalTokens,
    spawn_count: spawnCount,
    by_agent: byAgent,
  };
}

/**
 * Append a single session_total event to .agentic/events.jsonl summing
 * spawn_complete + conductor_direct events for the current session.
 * Best-effort: any fs / parse failure is swallowed silently.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid from the Stop payload.
 */
function writeSessionTotal(cwd, sessionId) {
  try {
    const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
    const agg = scanSessionAggregate(eventsPath, sessionId);
    if (!agg) return;

    const totalLine = JSON.stringify({
      ts: new Date().toISOString(),
      phase: 'session_end',
      event: 'session_total',
      agent: null,
      task_id: null,
      data: {
        wall_seconds: agg.wall_seconds,
        tokens: agg.tokens,
        spawn_count: agg.spawn_count,
        by_agent: agg.by_agent,
        session_uuid: sessionId || null,
      },
    });
    fs.appendFileSync(eventsPath, totalLine + '\n');
  } catch (_) {
    // Silent failure - consistent with context.md / loop-state.json paths.
  }
}

/**
 * Remove the learnings-agent session marker if it belongs to the current session.
 * Silent failure: any error is swallowed.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid from the Stop payload.
 */
function removeLearningsAgentSession(cwd, sessionId) {
  // Reject cwd values with traversal components before any path join.
  const resolvedCwd = path.resolve(cwd);
  if (resolvedCwd !== cwd) {
    return;
  }

  try {
    const markerPath = path.join(cwd, '.agentic', 'learnings-agent.session');
    if (!fs.existsSync(markerPath)) return;
    const raw = fs.readFileSync(markerPath, 'utf8');
    const marker = JSON.parse(raw);
    if (typeof marker.session_id === 'string' && marker.session_id === sessionId) {
      fs.unlinkSync(markerPath);
    }
  } catch (_) {
    // Silent failure
  }
}

/**
 * Parse a YAML identity file at filePath. Returns {developer_id, provisional} or null.
 * Silent on ENOENT or any parse error.
 *
 * @param {string} filePath - Absolute path to the identity.yml file.
 * @returns {{developer_id: string, provisional: boolean}|null}
 */
function _parseIdentityFile(filePath) {
  try {
    if (!fs.existsSync(filePath)) return null;
    const raw = fs.readFileSync(filePath, 'utf8');
    const m = raw.match(/^developer_id:\s*(\S+)\s*$/m);
    if (!m) return null;
    const pm = raw.match(/^provisional:\s*(true|false)\s*$/m);
    const provisional = pm ? pm[1] === 'true' : false;
    return { developer_id: m[1], provisional };
  } catch (_) {
    return null;
  }
}

/**
 * Resolve effective identity via 4-tier total ordering:
 *   project-confirmed > global-confirmed > project-provisional > global-provisional > null
 *
 * Reads project file (<cwd>/.agentic/identity.yml) and global file
 * (~/.agentic/identity.yml) using two synchronous existsSync+readFileSync calls
 * (~1ms, Node built-ins only, no subprocess).
 *
 * The existing three-branch write-vs-buffer gate (identity && !identity.provisional)
 * remains valid: confirmed at either scope -> direct write; provisional -> pending buffer.
 *
 * @param {string} cwd - The repo working directory (already validated by run()).
 * @returns {{developer_id: string, provisional: boolean}|null}
 */
function getIdentity(cwd) {
  const projectPath = path.join(cwd, '.agentic', 'identity.yml');
  const globalPath = path.join(os.homedir(), '.agentic', 'identity.yml');

  const projId = _parseIdentityFile(projectPath);
  const globId = _parseIdentityFile(globalPath);

  // Pass 1: first confirmed candidate in [project, global] order
  if (projId && !projId.provisional) return projId;
  if (globId && !globId.provisional) return globId;

  // Pass 2: first provisional candidate in [project, global] order
  if (projId) return projId;
  if (globId) return globId;

  return null;
}

/**
 * Append a one-time identity nudge to .agentic/context.md.
 * Silent on any fs error. Idempotent via sentinel at ~/.agentic/.identity-nudged.
 *
 * @param {string} repoRoot - Verified project directory.
 */
function appendIdentityNudgeToContextMd(repoRoot) {
  try {
    const contextPath = path.join(repoRoot, '.agentic', 'context.md');
    const nudge = [
      '',
      '---',
      '[agentic-engineering] No developer identity set. Session telemetry is local-only.',
      'To enable team telemetry: agentic-identity init <handle>',
      'Sentinel: ~/.agentic/.identity-nudged (delete to re-nudge)',
    ].join('\n') + '\n';
    fs.appendFileSync(contextPath, nudge, 'utf8');
  } catch (_) {
    // Silent failure
  }
}

/**
 * Compute session totals by scanning events.jsonl, shaped for writeSessionLog.
 * The by_agent map uses a flat tokens_total (sum of 4 bands) for the session-log
 * format, distinct from the 4-band structure used in writeSessionTotal.
 * Returns null on failure.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid.
 * @returns {{wall_seconds: number, tokens: object, spawn_count: number, by_agent: object}|null}
 */
function computeSessionTotals(cwd, sessionId) {
  try {
    const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
    const agg = scanSessionAggregate(eventsPath, sessionId);
    if (!agg) return null;

    // Re-shape by_agent: flatten 4-band tokens to a single tokens_total for the
    // session-log format consumed by agentic-cost team.
    const byAgentFlat = {};
    for (const [name, entry] of Object.entries(agg.by_agent)) {
      const t = entry.tokens || {};
      byAgentFlat[name] = {
        spawns: entry.spawns,
        wall_seconds: entry.wall_seconds,
        tokens_total: (Number(t.input) || 0) + (Number(t.output) || 0)
          + (Number(t.cache_creation) || 0) + (Number(t.cache_read) || 0),
      };
    }

    return {
      wall_seconds: agg.wall_seconds,
      tokens: agg.tokens,
      spawn_count: agg.spawn_count,
      by_agent: byAgentFlat,
    };
  } catch (_) {
    return null;
  }
}

/**
 * Write a session-log line to .agentic/session-log/<developer_id>.jsonl.
 * Creates the directory if needed. Silent failure on any fs error.
 *
 * @param {string} cwd - Verified project directory.
 * @param {{developer_id: string}} identity - Identity from getIdentity().
 * @param {string|null} sessionId - Current session uuid.
 */
function writeSessionLog(cwd, identity, sessionId) {
  try {
    // Resolve project slug and branch best-effort
    const projectSlug = path.basename(cwd);
    let branch = '';
    try {
      const { execSync: _exec } = require('child_process');
      branch = _exec('git symbolic-ref --short HEAD', {
        cwd, timeout: 3000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
    } catch (_) {
      // Not a git repo or detached HEAD - leave branch as empty string
    }

    const totals = computeSessionTotals(cwd, sessionId);
    const data = totals || {
      wall_seconds: 0,
      tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
      spawn_count: 0,
      by_agent: {},
    };

    const logLine = JSON.stringify({
      ts: new Date().toISOString(),
      phase: 'session_end',
      event: 'session_total',
      agent: null,
      task_id: null,
      developer_id: identity.developer_id,
      session_uuid: sessionId || null,
      project_slug: projectSlug,
      branch,
      data,
    });

    const sessionLogDir = path.join(cwd, '.agentic', 'session-log');
    fs.mkdirSync(sessionLogDir, { recursive: true });
    const logFile = path.join(sessionLogDir, `${identity.developer_id}.jsonl`);
    fs.appendFileSync(logFile, logLine + '\n', 'utf8');
  } catch (_) {
    // Silent failure - consistent with all other write paths
  }
}

/**
 * Write the same session-log line that writeSessionLog writes per-project,
 * but to the global operator mirror: ~/.agentic/session-log/<dev>.jsonl.
 * Independent of the per-project write - a failure here never affects it.
 * Creates the directory if needed. Silent failure on any fs error.
 *
 * @param {{developer_id: string, provisional: boolean}} identity - From getIdentity().
 * @param {string|null} sessionId - Current session uuid.
 * @param {{wall_seconds: number, tokens: object, spawn_count: number, by_agent: object}} data - Telemetry.
 */
function writeSessionLogGlobal(identity, sessionId, data) {
  try {
    const globalLogDir = path.join(os.homedir(), '.agentic', 'session-log');
    fs.mkdirSync(globalLogDir, { recursive: true });
    const logLine = JSON.stringify({
      ts: new Date().toISOString(),
      phase: 'session_end',
      event: 'session_total',
      agent: null,
      task_id: null,
      developer_id: identity.developer_id,
      session_uuid: sessionId || null,
      project_slug: data.project_slug || null,
      branch: data.branch || '',
      data: {
        wall_seconds: data.wall_seconds,
        tokens: data.tokens,
        spawn_count: data.spawn_count,
        by_agent: data.by_agent,
      },
    });
    const logFile = path.join(globalLogDir, `${identity.developer_id}.jsonl`);
    fs.appendFileSync(logFile, logLine + '\n', 'utf8');
  } catch (_) {
    // Silent failure - independent of per-project write
  }
}

/**
 * Generate a UUID v4 using crypto.randomUUID when available (Node 14.17+),
 * falling back to a Math.random-based implementation for older runtimes.
 *
 * @returns {string} UUID v4 string.
 */
function generateUuid() {
  try {
    const crypto = require('crypto');
    if (typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
  } catch (_) { /* no crypto module */ }
  // Fallback: RFC 4122 v4 via Math.random
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Write unattributed session telemetry to the pending buffer.
 * Used when identity is null (no identity) or provisional (not yet confirmed).
 * Writes atomically via tmp+rename to ~/.agentic/session-log/.pending/<uuid>.json.
 * Enforces a cap of 100 pending files: when at or above cap, deletes the single
 * oldest file by `ts` field and emits one stderr notice before writing.
 * No developer_id field in the pending record - it is unattributed until flush.
 * Silent failure on any fs error.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid (uuid v4 generated if null).
 */
function writePendingBuffer(cwd, sessionId) {
  try {
    const pendingDir = path.join(os.homedir(), '.agentic', 'session-log', '.pending');
    fs.mkdirSync(pendingDir, { recursive: true });

    // Enforce cap-100: count existing pending files
    let existingFiles = [];
    try {
      existingFiles = fs.readdirSync(pendingDir).filter((f) => f.endsWith('.json'));
    } catch (_) { /* silent */ }

    if (existingFiles.length >= 100) {
      // Parse ts from each file, find oldest, delete it
      let oldestTs = null;
      let oldestFile = null;
      for (const fname of existingFiles) {
        try {
          const raw = fs.readFileSync(path.join(pendingDir, fname), 'utf8');
          const obj = JSON.parse(raw);
          const ts = obj.ts || '';
          if (oldestTs === null || ts < oldestTs) {
            oldestTs = ts;
            oldestFile = fname;
          }
        } catch (_) { /* skip unreadable files */ }
      }
      if (oldestFile) {
        try { fs.unlinkSync(path.join(pendingDir, oldestFile)); } catch (_) { /* silent */ }
        process.stderr.write('agentic-engineering: pending buffer at cap (100); oldest session dropped\n');
      }
    }

    // Compute telemetry
    const totals = computeSessionTotals(cwd, sessionId);
    const data = totals || {
      wall_seconds: 0,
      tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
      spawn_count: 0,
      by_agent: {},
    };

    // Resolve metadata
    const projectSlug = path.basename(cwd);
    const repoRoot = cwd;
    let branch = '';
    try {
      branch = execSync('git symbolic-ref --short HEAD', {
        cwd, timeout: 3000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
    } catch (_) { /* detached HEAD or non-git dir */ }

    const sessionUuid = sessionId || generateUuid();
    const record = {
      schema_version: 1,
      session_uuid: sessionUuid,
      ts: new Date().toISOString(),
      project_slug: projectSlug,
      repo_root: repoRoot,
      branch,
      data: {
        wall_seconds: data.wall_seconds,
        tokens: data.tokens,
        spawn_count: data.spawn_count,
        by_agent: data.by_agent,
      },
    };

    // Atomic write: tmp + rename
    const outFile = path.join(pendingDir, `${sessionUuid}.json`);
    const tmpFile = outFile + '.tmp';
    fs.writeFileSync(tmpFile, JSON.stringify(record, null, 2), 'utf8');
    fs.renameSync(tmpFile, outFile);
  } catch (_) {
    // Silent failure - consistent with all other write paths
  }
}

// OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
// Thin alias: the implementation lives in hooks/lib/wrap-marker.js so the lock
// gate is shared with the SessionEnd hook and the daemon. Fail-open in the lib.
function wrapLockHeld(cwd) {
  return wrapMarker.wrapLockHeld(cwd);
}

/**
 * Append one spillover record to .agentic/wrap/deferred-activity.jsonl.
 * Called only when wrapLockHeld(cwd) is true and a context.md write was therefore
 * skipped; the background enrichment drains this file into the context.md activity
 * block when it next writes (inside the held Part-A lock). Append-only, fail-open.
 *
 * @param {string} cwd - Verified project directory.
 * @param {object} record - Spillover record (NORMATIVE schema in wrap.md).
 */
function appendSpilloverRecord(cwd, record) {
  try {
    const spilloverPath = wrapMarker.stopDeferredActivityPath(cwd);
    fs.mkdirSync(path.dirname(spilloverPath), { recursive: true });
    fs.appendFileSync(spilloverPath, JSON.stringify(record) + '\n', 'utf8');
  } catch (_) {
    // Silent failure - spillover is best-effort; a missed record is tolerated.
  }
}

/**
 * Write context.md, OR spill the activity when a /wrap holds the lock.
 * Lock-aware: if wrapLockHeld(cwd) is true, the context.md write is skipped and
 * one spillover record is appended instead (so the enrichment's locked Part-A
 * merge is not clobbered). The lock is re-checked immediately before the
 * writeFileSync to minimize the TOCTOU window. Silent-fail on any fs error.
 * Shared by both context.md write paths (the /wrap-coexistence append and the
 * normal write) so the lock-gate logic lives in exactly one place.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string} outputPath - Absolute path to context.md.
 * @param {string} projectDir - Absolute path to the .agentic/ directory.
 * @param {string} body - The full context.md content to write.
 * @param {object} spilloverRecord - Record to spill when the lock is held.
 */
function writeContextMdOrSpill(cwd, outputPath, projectDir, body, spilloverRecord) {
  // OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
  if (wrapLockHeld(cwd)) {
    appendSpilloverRecord(cwd, spilloverRecord);
    return;
  }
  try {
    fs.mkdirSync(projectDir, { recursive: true });
    // Re-check immediately before the write to minimize the TOCTOU window.
    if (wrapLockHeld(cwd)) {
      appendSpilloverRecord(cwd, spilloverRecord);
    } else {
      fs.writeFileSync(outputPath, body, 'utf8');
    }
  } catch (_) {
    // Silent failure
  }
}

/**
 * Stage a per-session .agentic/wrap/pending-<session_id>.json enrichment marker
 * (schema_version 3) so the next session in this project (or the daemon) can
 * complete enrichment for a session that exited un-wrapped. The full staging
 * predicate, the MAJOR-3 ready/pending/in_progress suppression, the .last-wrap
 * suppression, the substantive-activity gate, the atomic tmp+rename write, and
 * the loop-guard NO-OP all live in hooks/lib/wrap-marker.js (single source of
 * truth). NORMATIVE marker schema lives in content/commands/wrap.md.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid from the Stop payload.
 * @param {{uncommittedCount: number, pathsReferencedCount: number,
 *          recentFocusCount: number}} scan - Already-computed activity counts.
 */
function stageWrapPending(cwd, sessionId, scan) {
  wrapMarker.stagePending(cwd, sessionId, scan);
}

// ---------------------------------------------------------------------------
// Capture-gap backstop helpers
// ---------------------------------------------------------------------------

/**
 * Guardrail glob patterns used to detect test / lint / schema files added
 * during the session. Matched against the basename of each changed path.
 * @type {RegExp[]}
 */
const GUARDRAIL_PATTERNS = [
  /test/i,
  /spec/i,
  /\.eslintrc/i,
  /\.schema\./i,
  /ruff\.toml/i,
  /mypy\.ini/i,
];

/**
 * Normalize a string into tokens for domain-proximity matching.
 * Splits on '/', '.', '-', '_' and lowercases; filters tokens shorter than 4
 * chars (too generic to carry domain signal).
 *
 * @param {string} str
 * @returns {string[]}
 */
function _tokenize(str) {
  return str.toLowerCase().split(/[\/.\-_]/).filter((t) => t.length >= 4);
}

/**
 * Detect whether this session has learning-worthy events with no learnings
 * captured. Pure function: reads files, runs one git subprocess, returns a
 * result object. Never throws - all errors are absorbed and return
 * { shouldNudge: false }.
 *
 * Three conditions must ALL hold for shouldNudge === true:
 *   (a) At least one learning-worthy event this session (debugger/investigator
 *       spawn_complete, skeptic spawn_complete with major/critical resolved, or
 *       tool_failure_workaround). Events without session_uuid are DELIBERATELY
 *       EXCLUDED (inverse of scanSessionAggregate which includes absent uuids
 *       for back-compat). This exclusion prevents false nags from legacy event
 *       lines whose session cannot be determined. Self-heals after one post-upgrade
 *       session where emits carry session_uuid.
 *   (b) No today-dated [LRN- or [KNW- entries in .agentic/learnings.md.
 *   (c) No domain-proximate guardrail added this session (suppression). The
 *       suppressor checks git diff --name-only origin/HEAD..HEAD (all session
 *       commits since branch diverged from upstream - primary) falling back to
 *       git diff --name-only HEAD~1 HEAD (single-commit fallback when no
 *       upstream ref exists). If guardrails were added but none are domain-
 *       proximate with the event domain tokens, residualOnly is set true and
 *       the nudge still fires with residual-WHY wording.
 *
 * @param {string} cwd - Project root (absolute, already validated by run()).
 * @param {string|null} sessionId - Stop payload session_id (harness uuid).
 * @returns {{ shouldNudge: boolean, residualOnly: boolean }}
 */
function detectCaptureGap(cwd, sessionId) {
  try {
    if (!sessionId) return { shouldNudge: false, residualOnly: false };

    // --- (a) Scan events.jsonl for learning-worthy events this session ---
    const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');

    // Pagination: read only lines after the last sweep cursor.
    let lastSweepTs = '';
    try {
      const cursorPath = path.join(cwd, '.agentic', '.capture-gap-last-sweep');
      if (fs.existsSync(cursorPath)) {
        lastSweepTs = fs.readFileSync(cursorPath, 'utf8').trim();
      }
    } catch (_) { /* silent */ }

    let rawEvents = '';
    try {
      if (fs.existsSync(eventsPath)) {
        rawEvents = fs.readFileSync(eventsPath, 'utf8');
      }
    } catch (_) { return { shouldNudge: false, residualOnly: false }; }

    const eventLines = rawEvents.split('\n');
    // On cold start (no cursor), cap to the last 100 lines.
    const linesToScan = lastSweepTs
      ? eventLines
      : eventLines.slice(-100);

    const LEARNING_AGENTS = new Set(['debugger', 'investigator']);
    let hasLearningWorthyEvent = false;
    const eventDomainTokens = new Set();

    for (const line of linesToScan) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let obj;
      try { obj = JSON.parse(trimmed); } catch (_) { continue; }

      const data = (obj && obj.data) || {};

      // DELIBERATE: lines without data.session_uuid are EXCLUDED here.
      // This is the inverse of scanSessionAggregate (which includes absent uuids
      // for back-compat). The backstop must not nag on legacy event lines from
      // prior sessions that lack session attribution - that would cause false
      // positives on every session until the file rotates. scanSessionAggregate
      // keeps absent=include for back-compat; only this backstop uses absent=exclude.
      if (!data.session_uuid || data.session_uuid !== sessionId) continue;

      // Pagination: skip lines at or before the last sweep timestamp.
      if (lastSweepTs && obj.ts && obj.ts <= lastSweepTs) continue;

      const ev = obj.event;
      const agentName = (obj.agent || '').toLowerCase();

      let worthy = false;
      if (ev === 'tool_failure_workaround') {
        worthy = true;
      } else if (ev === 'spawn_complete') {
        if (LEARNING_AGENTS.has(agentName)) {
          worthy = true;
        } else if (agentName === 'skeptic') {
          const fc = data.findings_count || {};
          if ((Number(fc.critical) || 0) > 0 || (Number(fc.major) || 0) > 0) {
            if (data.signed_off) worthy = true;
          }
        }
      }

      if (worthy) {
        hasLearningWorthyEvent = true;
        // Collect domain tokens from domain_tag and tool references
        for (const src of [data.domain_tag, data.tool]) {
          if (typeof src === 'string' && src) {
            for (const tok of _tokenize(src)) eventDomainTokens.add(tok);
          }
        }
      }
    }

    if (!hasLearningWorthyEvent) return { shouldNudge: false, residualOnly: false };

    // --- (b) Check .agentic/learnings.md for today-dated entries ---
    const todayStr = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
    try {
      const learningsPath = path.join(cwd, '.agentic', 'learnings.md');
      if (fs.existsSync(learningsPath)) {
        const learningsRaw = fs.readFileSync(learningsPath, 'utf8');
        // Match [LRN-YYYYMMDD-XXX] or [KNW-YYYYMMDD-XXX] with today's date, OR
        // a "Discovered: YYYY-MM-DD" line dated today.
        const dateCompact = todayStr.replace(/-/g, '');
        const hasToday =
          learningsRaw.includes(`[LRN-${dateCompact}`) ||
          learningsRaw.includes(`[KNW-${dateCompact}`) ||
          learningsRaw.includes(`Discovered: ${todayStr}`);
        if (hasToday) return { shouldNudge: false, residualOnly: false };
      }
    } catch (_) { /* silent - absent learnings.md means no learning captured */ }

    // --- (c) Guardrail suppression ---
    // Collect names of guardrail files added this session via git diff.
    // Primary: git diff --name-only origin/HEAD..HEAD  (all commits since branch diverged)
    // Fallback: git diff --name-only HEAD~1 HEAD       (last commit only; used when no upstream)
    let changedPaths = [];
    try {
      let diffOutput = '';
      try {
        diffOutput = execSync(
          'git diff --name-only origin/HEAD..HEAD',
          { cwd, timeout: 5000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }
        );
      } catch (_primaryErr) {
        // No upstream ref - fall back to last commit only.
        try {
          diffOutput = execSync(
            'git diff --name-only HEAD~1 HEAD',
            { cwd, timeout: 5000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }
          );
        } catch (_) { /* no commits yet or non-git dir; diffOutput stays '' */ }
      }
      changedPaths = diffOutput.split('\n').map((p) => p.trim()).filter(Boolean);
    } catch (_) { /* soft-fail: no suppression applied */ }

    const addedGuardrailPaths = changedPaths.filter((p) => {
      const base = path.basename(p);
      if (GUARDRAIL_PATTERNS.some((re) => re.test(base))) return true;
      // Also match directory segments: tests/, evals/, spec/
      return /(?:^|\/)(?:tests|evals|spec)\//i.test(p + '/');
    });

    if (addedGuardrailPaths.length === 0) {
      // No guardrails added - fire standard nudge.
      return { shouldNudge: true, residualOnly: false };
    }

    // Check domain proximity: does any guardrail path share a >=4-char token
    // with any event domain token?
    let domainProximate = false;
    if (eventDomainTokens.size > 0) {
      for (const gp of addedGuardrailPaths) {
        const gpTokens = _tokenize(gp);
        if (gpTokens.some((t) => eventDomainTokens.has(t))) {
          domainProximate = true;
          break;
        }
      }
    }

    if (domainProximate) {
      // Domain-proximate guardrail added - suppress nudge entirely.
      return { shouldNudge: false, residualOnly: false };
    }

    // Guardrails added but none domain-proximate - fire with residual-WHY text.
    return { shouldNudge: true, residualOnly: true };
  } catch (_) {
    // Top-level safety net: any unexpected error -> no nudge (never blocks exit).
    return { shouldNudge: false, residualOnly: false };
  }
}

/**
 * Append a capture-gap nudge to .agentic/context.md. Sentinel-gated per session
 * via .agentic/.capture-gap-last-sweep (ISO8601 UTC; absent = cold start). The
 * cursor is updated atomically (tmp+rename) after a successful append so the same
 * session does not nag twice. Silent failure on any fs error.
 *
 * When residualOnly === true the nudge text emphasises that a guardrail was added
 * but is not domain-proximate, so only the residual WHY / dead-end reasoning needs
 * capturing. When residualOnly === false the standard nudge fires.
 *
 * @param {string} cwd - Verified project root.
 * @param {boolean} residualOnly - True when a guardrail was added but none were
 *   domain-proximate with the learning-worthy event.
 */
function appendCaptureGapNoticeToContextMd(cwd, residualOnly) {
  try {
    const contextPath = path.join(cwd, '.agentic', 'context.md');
    const cursorPath = path.join(cwd, '.agentic', '.capture-gap-last-sweep');

    let nudgeText;
    if (residualOnly) {
      nudgeText = [
        '',
        '---',
        'CAPTURE-GAP: a related test or guardrail was added this session, but it is not',
        'domain-proximate to the learning-worthy event (root cause / tool workaround).',
        'Capture only the residual WHY and any dead-ends the test does not encode:',
        'spawn learnings-agent or add an LRN/KNW entry to .agentic/learnings.md.',
        '(If the guardrail fully captures it, ignore this.)',
      ].join('\n') + '\n';
    } else {
      nudgeText = [
        '',
        '---',
        'CAPTURE-GAP: this session resolved a root cause / worked around a tool failure',
        'but recorded no learning. If there is a non-obvious WHY beyond what a test or',
        'the diff already shows, capture it: spawn learnings-agent or add an LRN/KNW',
        'entry to .agentic/learnings.md. (If the test you added fully captures it, ignore this.)',
      ].join('\n') + '\n';
    }

    fs.appendFileSync(contextPath, nudgeText, 'utf8');

    // Update pagination cursor atomically so the same session doesn't fire twice.
    try {
      const nowIso = new Date().toISOString();
      const tmpCursor = cursorPath + '.tmp';
      fs.writeFileSync(tmpCursor, nowIso, 'utf8');
      fs.renameSync(tmpCursor, cursorPath);
    } catch (_) { /* silent - cursor update failure is non-fatal */ }
  } catch (_) {
    // Silent failure - consistent with all other context.md append paths.
  }
}

function run() {
  // --- 1. Read stdin ---
  let raw = '';
  try {
    raw = fs.readFileSync(0, 'utf8');
  } catch (_) {
    process.exit(0);
  }

  if (!raw.trim()) process.exit(0);

  // --- 2. Parse JSON ---
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (_) {
    process.exit(0);
  }

  // --- 3. Extract fields (all optional — guard every access) ---
  const cwd = (typeof payload.cwd === 'string' && payload.cwd.trim()) ? payload.cwd.trim() : null;
  if (!cwd) process.exit(0);

  const sessionId = (typeof payload.session_id === 'string' && payload.session_id.trim())
    ? payload.session_id.trim()
    : null;

  // --- 3b. Touch this session's heartbeat (per-turn liveness signal) ---
  // Pure wastefulness defense: the daemon defers claiming a `ready` marker whose
  // session still emits turns. Local fs only (no git/network); no-op under the
  // loop-guard; fail-open. Never blocks exit.
  // OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
  if (sessionId && deferredDaemonEnabled(cwd)) wrapMarker.touchHeartbeat(cwd, sessionId);

  const transcript = Array.isArray(payload.transcript) ? payload.transcript : [];

  // --- 4. Compute output path ---
  // Write context.md to the project's .agentic/ directory. Claude Code treats
  // any .claude/ directory (project-local OR global) as a sensitive file
  // location, so writing there still triggers the permission prompt even when
  // allow rules are set. .agentic/ is the same convention already used for
  // loop-state.json and is not subject to that check.
  const projectDir = path.join(cwd, '.agentic');
  const outputPath = path.join(projectDir, 'context.md');

  // --- 5. Extract recent user messages (last 3, truncated to ~150 chars) ---
  const userMessages = [];
  for (const msg of transcript) {
    if (!msg || msg.role !== 'user') continue;
    let text = '';
    if (typeof msg.content === 'string') {
      text = msg.content.trim();
    } else if (Array.isArray(msg.content)) {
      // Concatenate all text blocks
      for (const block of msg.content) {
        if (block && block.type === 'text' && typeof block.text === 'string') {
          text += block.text;
        }
      }
      text = text.trim();
    }
    if (text) userMessages.push(text);
  }
  const recentUserMessages = userMessages.slice(-3);

  // --- 6. Extract files touched from tool calls in transcript ---
  // Note: "Paths Referenced" in the output includes both file accesses (Read/Edit/Write/MultiEdit)
  // and search directories (Glob/Grep `path` arguments). Both categories appear in the same section.
  const filePaths = new Set();
  const fileToolNames = new Set(['Read', 'Edit', 'Write', 'MultiEdit']);

  for (const msg of transcript) {
    if (!msg) continue;
    const blocks = Array.isArray(msg.content) ? msg.content : [];
    for (const block of blocks) {
      if (!block || block.type !== 'tool_use') continue;
      const name = block.name || '';
      const input = block.input || {};

      if (fileToolNames.has(name)) {
        // Read, Edit, Write, MultiEdit all use file_path
        if (typeof input.file_path === 'string' && input.file_path.trim()) {
          filePaths.add(input.file_path.trim());
        }
      } else if (name === 'Glob' || name === 'Grep') {
        // Glob and Grep use path (directory or file to search in)
        if (typeof input.path === 'string' && input.path.trim()) {
          filePaths.add(input.path.trim());
        }
      } else if (name === 'Bash' || name === 'bash') {
        // Try to extract file paths from Bash commands via simple heuristic:
        // look for arguments that look like absolute paths
        const cmd = typeof input.command === 'string' ? input.command : '';
        const matches = cmd.match(/(?:^|\s)(\/[^\s"'\\;|&<>]+)/g);
        if (matches) {
          for (const m of matches) {
            const p = m.trim();
            // Only include paths that look like files (have an extension or are in known dirs)
            if (p.includes('.') || p.startsWith('/Users/') || p.startsWith('/home/')) {
              // Skip paths that are clearly flags or short tokens
              if (p.length > 4 && !p.startsWith('/.')) {
                // Require at least /Users/name/dir/file depth (4+ slashes) to avoid
                // capturing bare directories like /Users/alice or /home/bob
                if ((p.match(/\//g) || []).length >= 4) {
                  filePaths.add(p);
                }
              }
            }
          }
        }
      }
    }
  }

  // --- 7. Extract unique tools used from transcript tool_use blocks ---
  const toolsUsedSet = new Set();
  for (const msg of transcript) {
    if (!msg) continue;
    const blocks = Array.isArray(msg.content) ? msg.content : [];
    for (const block of blocks) {
      if (block && block.type === 'tool_use' && typeof block.name === 'string' && block.name.trim()) {
        toolsUsedSet.add(block.name.trim());
      }
    }
  }
  const uniqueTools = [...toolsUsedSet].sort();

  // --- 7b. Detect uncommitted changes via git status --porcelain ---
  const uncommittedFiles = [];
  try {
    const gitStatus = execSync('git status --porcelain', { cwd, timeout: 5000, encoding: 'utf8' });
    for (const line of gitStatus.split('\n')) {
      if (!line.trim()) continue;
      const statusCode = line.slice(0, 2).trim();
      const filePath = line.slice(3).trim();
      // Only include tracked modified/added/deleted/renamed files; skip untracked (??)
      if (statusCode && !statusCode.includes('?') && filePath) {
        uncommittedFiles.push({ statusCode, filePath });
      }
    }
  } catch (_) {
    // Silent failure if git isn't available or cwd isn't a repo
  }
  const uncommittedFilesLimited = uncommittedFiles.slice(0, 30);

  // --- 8. Format content ---
  const dateStr = new Date().toISOString().slice(0, 10);

  const recentFocusLines = recentUserMessages.length > 0
    ? recentUserMessages.map(m => {
        const truncated = m.length > 150 ? m.slice(0, 147) + '...' : m;
        // Indent continuation lines to keep the list readable
        return '- ' + truncated.replace(/\n/g, ' ');
      }).join('\n')
    : '(no user messages captured)';

  const pathsReferencedLines = filePaths.size > 0
    ? [...filePaths].sort().map(p => '- ' + p).join('\n')
    : '(none detected)';

  const toolsLine = uniqueTools.length > 0
    ? uniqueTools.join(', ')
    : '(none recorded)';

  const uncommittedChangesLines = uncommittedFilesLimited.length > 0
    ? uncommittedFilesLimited.map(({ statusCode, filePath }) => `- ${statusCode} ${filePath}`).join('\n')
    : '(working tree clean)';

  // --- 8b. Deferred-wrap inputs (lock-aware skip + marker staging) ---
  // OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
  // The spillover record (NORMATIVE schema in content/commands/wrap.md) is built
  // from the already-computed scan vars - no new git/subprocess calls. It is
  // appended only when wrapLockHeld(cwd) is true and the context.md write is
  // therefore skipped. spilloverScan carries the substantive-activity counts the
  // marker-staging predicate needs.
  const pathsReferencedArr = [...filePaths].sort();
  const uncommittedArr = uncommittedFilesLimited.map(
    ({ statusCode, filePath }) => `${statusCode} ${filePath}`
  );
  const spilloverRecord = {
    schema_version: 1,
    ts: new Date().toISOString(),
    session_id: sessionId,
    recent_focus: recentUserMessages,
    paths_referenced: pathsReferencedArr,
    uncommitted: uncommittedArr,
    tools_used: uniqueTools,
  };
  const spilloverScan = {
    uncommittedCount: uncommittedFiles.length,
    pathsReferencedCount: filePaths.size,
    recentFocusCount: recentUserMessages.length,
  };

  const content = `# Session Context
*Auto-updated by Stop hook — ${dateStr}. Overwritten each turn. Not committed to git.*
*Project: ${cwd}*

## Recent Focus
${recentFocusLines}

## Paths Referenced
${pathsReferencedLines}

## Uncommitted Changes
${uncommittedChangesLines}

## Tools Used
${toolsLine}
`;

  // --- 9. Append/replace session activity on /wrap-authored files ---
  // If existing context.md was written by /wrap (detected by exact two-line
  // startsWith to avoid false matches from user messages in ## Recent Focus),
  // append a "Session Activity" block rather than overwriting. Any previous
  // activity block is stripped first (replace mode — most recent session only,
  // not accumulated). /wrap content is preserved; only another /wrap run
  // replaces the whole file. The Stop hook is the fallback for sessions where
  // /wrap was never run.
  try {
    const existing = fs.readFileSync(outputPath, 'utf8');
    if (existing.startsWith('# Session Context\n*Written by /wrap')) {
      // Strip any previous Session Activity block (sentinel marks its start).
      const ACTIVITY_SENTINEL = '\n\n---\n\n## Session Activity\n';
      const sentinelIdx = existing.indexOf(ACTIVITY_SENTINEL);
      const wrapContent = sentinelIdx >= 0
        ? existing.slice(0, sentinelIdx)
        : existing.trimEnd();

      // Build and append the fresh activity block.
      const activityBlock = `${ACTIVITY_SENTINEL}*Auto-appended by Stop hook — ${dateStr}. Replaced each session.*

### Recent Messages
${recentFocusLines}

### Paths Referenced
${pathsReferencedLines}

### Uncommitted Changes
${uncommittedChangesLines}

### Tools Used
${toolsLine}
`;
      // Lock-aware context.md write: skip + spill while a /wrap holds the lock.
      writeContextMdOrSpill(cwd, outputPath, projectDir, wrapContent + activityBlock, spilloverRecord);
      // M1: write loop-state on ALL exit paths, including the wrap-coexistence path.
      writeLoopState(cwd);
      // Mirror to batch-state.json (sibling envelope; ordered after loop-state
      // so per-ticket inner state is marked first, then outer batch envelope).
      writeBatchState(cwd, sessionId);
      // Write session_total to events.jsonl on this exit path too.
      writeSessionTotal(cwd, sessionId);
      // Three-branch identity gate (independent of all other paths).
      try {
        const identity = getIdentity(cwd);
        if (identity && !identity.provisional) {
          // Confirmed identity: per-project write + global mirror
          writeSessionLog(cwd, identity, sessionId);
          // Build shared metadata for global mirror
          const totals = computeSessionTotals(cwd, sessionId);
          const globalData = Object.assign(
            {
              wall_seconds: 0,
              tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
              spawn_count: 0,
              by_agent: {},
            },
            totals,
            { project_slug: path.basename(cwd), branch: '' }
          );
          try {
            globalData.branch = execSync('git symbolic-ref --short HEAD', {
              cwd, timeout: 3000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
            }).trim();
          } catch (_) { /* detached HEAD or non-git dir */ }
          writeSessionLogGlobal(identity, sessionId, globalData);
        } else {
          // Provisional or no identity: pending buffer
          writePendingBuffer(cwd, sessionId);
          // OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
          // The identity nudge is a context.md writer; defer it while a /wrap
          // holds the lock so the locked Part-A merge is not clobbered. The
          // sentinel is consumed atomically with the nudge, so skipping both
          // here means the one-time nudge fires on a later unlocked session
          // rather than being lost.
          if (!identity && !wrapLockHeld(cwd)) {
            // No identity at all: also nudge once
            const sentinelPath = path.join(os.homedir(), '.agentic', '.identity-nudged');
            try {
              fs.mkdirSync(path.join(os.homedir(), '.agentic'), { recursive: true });
              fs.writeFileSync(sentinelPath, '', { flag: 'wx' });
              // Write succeeded - sentinel did not exist, so nudge once
              appendIdentityNudgeToContextMd(cwd);
            } catch (_nudgeErr) {
              // EEXIST means sentinel already written - skip nudge silently
            }
          }
        }
      } catch (_) {
        // Silent failure - never block session exit
      }
      // Capture-gap backstop on wrap-coexistence exit path.
      try {
        const gap = detectCaptureGap(cwd, sessionId);
        if (gap.shouldNudge) {
          appendCaptureGapNoticeToContextMd(cwd, gap.residualOnly);
        }
      } catch (_) { /* silent */ }
      removeLearningsAgentSession(cwd, sessionId);
      // Stage the wrap-pending marker (after the context.md decision, on every
      // exit path). Gated on deferredDaemonEnabled so the flag-off default never
      // accumulates markers. Fail-open; never blocks exit.
      // OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
      if (deferredDaemonEnabled(cwd)) stageWrapPending(cwd, sessionId, spilloverScan);
      process.exit(0);
    }
  } catch (_) {
    // File does not exist or is unreadable - proceed to write normally.
  }

  // --- 10. Write file (silent failure on any error) ---
  // Lock-aware context.md write: skip + spill while a /wrap holds the lock.
  writeContextMdOrSpill(cwd, outputPath, projectDir, content, spilloverRecord);

  // --- 11. Write interrupted status to loop-state.json if an active loop exists ---
  // Delegated to writeLoopState() which is also called from the wrap-coexistence
  // path (section 9) so the write executes on ALL exit paths.
  writeLoopState(cwd);

  // --- 11b. Mirror interrupted status to batch-state.json if owned by this session ---
  // Independent best-effort write; ordered after loop-state so per-ticket inner
  // state is marked first, then the outer batch envelope.
  writeBatchState(cwd, sessionId);

  // --- 12. Append session_total event to .agentic/events.jsonl if present ---
  // Independent best-effort write; any failure swallowed.
  writeSessionTotal(cwd, sessionId);

  // --- 13. Three-branch identity gate: session log, global mirror, or pending buffer ---
  // Independent best-effort write; any failure swallowed. Never blocks exit.
  try {
    const identity = getIdentity(cwd);
    if (identity && !identity.provisional) {
      // Confirmed identity: per-project write + global mirror
      writeSessionLog(cwd, identity, sessionId);
      // Build shared metadata for global mirror
      const totals = computeSessionTotals(cwd, sessionId);
      const globalData = Object.assign(
        {
          wall_seconds: 0,
          tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
          spawn_count: 0,
          by_agent: {},
        },
        totals,
        { project_slug: path.basename(cwd), branch: '' }
      );
      try {
        globalData.branch = execSync('git symbolic-ref --short HEAD', {
          cwd, timeout: 3000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
        }).trim();
      } catch (_) { /* detached HEAD or non-git dir */ }
      writeSessionLogGlobal(identity, sessionId, globalData);
    } else {
      // Provisional or no identity: pending buffer
      writePendingBuffer(cwd, sessionId);
      // OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
      // Defer the identity nudge (a context.md writer) while a /wrap holds the
      // lock; the sentinel is consumed atomically with the nudge, so skipping
      // both defers the one-time nudge to a later unlocked session.
      if (!identity && !wrapLockHeld(cwd)) {
        // No identity at all: also nudge once
        const sentinelPath = path.join(os.homedir(), '.agentic', '.identity-nudged');
        try {
          fs.mkdirSync(path.join(os.homedir(), '.agentic'), { recursive: true });
          fs.writeFileSync(sentinelPath, '', { flag: 'wx' });
          // Sentinel did not exist - nudge once
          appendIdentityNudgeToContextMd(cwd);
        } catch (_nudgeErr) {
          // EEXIST: sentinel already written, skip nudge
        }
      }
    }
  } catch (_) {
    // Silent failure
  }

  // --- 14. Remove learnings-agent session marker if owned by this session ---
  removeLearningsAgentSession(cwd, sessionId);

  // --- 15. Capture-gap backstop (path 9 - independent of all other paths) ---
  // Detects learning-worthy sessions with no captured learnings and appends a
  // nudge to context.md. Silent failure; never blocks exit.
  try {
    const gap = detectCaptureGap(cwd, sessionId);
    if (gap.shouldNudge) {
      appendCaptureGapNoticeToContextMd(cwd, gap.residualOnly);
    }
  } catch (_) { /* silent */ }

  // --- 16. Stage the wrap-pending marker (deferred-wrap safety-net) ---
  // Runs after the context.md decision, on this exit path. Gated on
  // deferredDaemonEnabled so the flag-off default never accumulates markers.
  // Fail-open; never blocks exit. Staged only when no live marker exists, this
  // session has not already wrapped (.last-wrap), and the session had substantive
  // activity.
  // OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
  if (deferredDaemonEnabled(cwd)) stageWrapPending(cwd, sessionId, spilloverScan);

  process.exit(0);
}

run();
