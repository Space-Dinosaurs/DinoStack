#!/usr/bin/env node

/**
 * Purpose: Single source of truth for the deferred-`/wrap` per-session marker
 *          state machine and its companion on-disk artifacts (last-wrap sentinel,
 *          wrap/lock directory lock, daemon pid, auth-failed notice, .claude-host
 *          sentinel, heartbeats). Owns every read, transition, reclaim, janitor,
 *          lock, and heartbeat operation so that the Stop hook, the SessionEnd
 *          hook, and the wrap daemon all share one atomic, fail-open
 *          implementation. The single correctness invariant lives here: a
 *          `pending` marker becomes `ready` ONLY via finalizeReady on a genuine
 *          terminal SessionEnd - there is NO stale-sweep (CRITICAL-A).
 *
 * Public API (CommonJS, all exported on module.exports):
 *   Paths:
 *     markerPath(cwd, sessionId) -> .agentic/wrap/pending-<sessionId>.json
 *     lastWrapPath(cwd) -> .agentic/wrap/last-wrap
 *     wrapLockPath(cwd) -> .agentic/wrap/lock
 *     wrapLockOwnerPath(cwd) -> .agentic/wrap/lock/owner
 *     daemonPidPath(cwd) -> .agentic/wrap/daemon.pid
 *     wrapDaemonLogPath(cwd) -> .agentic/wrap/daemon.log
 *     authFailedPath(cwd) -> .agentic/wrap/daemon-auth-failed
 *     claudeHostPath(cwd) -> .agentic/wrap/claude-host
 *     heartbeatPath(cwd, sessionId) -> .agentic/wrap/heartbeats/<sessionId>
 *     stopDeferredActivityPath(cwd) -> .agentic/wrap/deferred-activity.jsonl
 *   Constants:
 *     SCHEMA_VERSION, MAX_DAEMON_LOG_BYTES (2 MB log rotation cap),
 *     MAX_CHILD_CAPTURE_BYTES (256 KB per-run child-output cap)
 *   Reads (unguarded):
 *     readMarker(cwd, sessionId), listReadyMarkers(cwd), listInProgressMarkers(cwd),
 *     liveMarkerForSession(cwd, sessionId), readLastWrap(cwd), wrapLockHeld(cwd),
 *     wrapLockStale(cwd, staleMs), heartbeatFresh(cwd, sessionId, freshMs),
 *     isClaudeHost(cwd)
 *   Loop-guard:
 *     daemonGuardActive() -> process.env.AGENTIC_WRAP_DAEMON === '1'
 *   Sentinel write (UNGUARDED, fail-open):
 *     ensureClaudeHost(cwd)
 *   Transitions (NO-OP under guard):
 *     writeMarker(cwd, marker), stagePending(cwd, sessionId, scan),
 *     finalizeReady(cwd, sessionId), claimMarker(cwd, sessionId, owner, kind, staleMs),
 *     transitionDone(cwd, sessionId), transitionGaveUp(cwd, sessionId, err)
 *   Reclaim / janitor (daemon-internal; NO-OP under guard):
 *     reclaimAbandonedInProgress(cwd, staleMs) -> {reclaimed:[], gaveUp:[]}
 *     cleanStalePending(cwd, ttlMs) -> {deleted:[]}
 *   Lock (NEVER prompts):
 *     acquireWrapLock(cwd, owner, staleMs) -> boolean, releaseWrapLock(cwd)
 *     readWrapLockOwner(cwd) -> { pid, ts } (symlink-guarded: guards both parent lock
 *       dir AND leaf owner against symlinks, no-follow; safe for any caller),
 *     clearProvablyStaleWrapLock(cwd, staleMs) -> boolean (daemon-side stale-lock clear)
 *     wrapLockProvablyStale(cwd, staleMs) -> boolean (staleness predicate, NEW path)
 *     wrapLockProvablyStaleLegacy(cwd, staleMs) -> boolean (staleness predicate, OLD path)
 *   Heartbeat:
 *     touchHeartbeat(cwd, sessionId) (NO-OP under guard), removeHeartbeat(cwd, sessionId)
 *
 * Upstream deps: Node built-ins only (fs, path). No npm dependencies.
 *                Reads/writes under [cwd]/.agentic/wrap/: pending-<id>.json markers,
 *                last-wrap, lock (directory) + lock/owner, daemon.pid,
 *                daemon-auth-failed, heartbeats/<id>, deferred-activity.jsonl.
 *                Also exposes a path helper for daemon.log (this lib does NOT
 *                write that log - the daemon does; the helper only derives the path).
 *                claudeHostPath resolves to [cwd]/.agentic/wrap/claude-host.
 *
 * Downstream consumers: hooks/stop-context.js (require this lib; stagePending,
 *                        touchHeartbeat, lock-aware reads), hooks/session-end-wrap.js
 *                        (finalizeReady, removeHeartbeat - U2), hooks/wrap-daemon.js
 *                        (listReadyMarkers, claimMarker, reclaimAbandonedInProgress,
 *                        cleanStalePending, acquireWrapLock, transitionDone/GaveUp - U3),
 *                        hooks/session-start-wrap.sh (self-heals the sentinel in bash;
 *                        ensureClaudeHost is the Node-callable equivalent, exported for
 *                        adapter use - U4).
 *
 * Failure modes: Every function is fail-open and NEVER throws to a hook - all fs
 *                errors are swallowed and a safe default is returned (false/null/[]
 *                / no-op). All write transitions are atomic (tmp + rename) so a
 *                crash mid-write never leaves a torn marker. Every transition,
 *                reclaim, janitor, and heartbeat-touch is a guarded NO-OP when
 *                daemonGuardActive() (AGENTIC_WRAP_DAEMON=1) - this is the
 *                loop-guard that prevents the daemon's own headless
 *                `/wrap-deferred` run from re-staging or re-finalizing markers.
 *                ensureClaudeHost is the SOLE intentionally-UNGUARDED writer
 *                (writing a true fact is harmless and self-heals existing installs).
 *                finalizeReady is the SOLE pending->ready transition (no sweep);
 *                reclaimAbandonedInProgress acts ONLY on daemon-claimed dead-PID
 *                stale in_progress markers and NEVER touches pending markers, so it
 *                cannot resume a live/idle session. cleanStalePending DELETES old
 *                pending markers AND stale `done` tombstones (never status-mutates any
 *                marker), so it likewise cannot promote a live session, and co-deletes
 *                each deleted marker's sibling heartbeat (PERF-Minor) inside the
 *                per-marker try/catch so a heartbeat-unlink error never aborts the
 *                sweep. done-tombstone age key: wrapped_at ?? staged_at;
 *                both-unparseable = skip; never touches ready / in_progress / gave_up.
 *                SECURITY (DoS hardening): every marker read is size-bounded
 *                (MAX_MARKER_BYTES, SEC-M2) and every directory scan filters
 *                filenames to the session-UUID shape BEFORE opening any file and
 *                caps the number processed per tick (MAX_MARKERS_PER_SCAN, SEC-M3),
 *                so a hostile repo cannot wedge a poll tick with a giant marker or a
 *                directory of tens of thousands of files. Both remain fail-open.
 *                LOCK CLEAR (daemon-side): clearProvablyStaleWrapLock removes the
 *                wrap/lock DIRECTORY (so the headless deferred-`/wrap` child, which runs
 *                with Bash removed and cannot `rm`, no longer re-flags a stale lock) but
 *                ONLY when the lock is PROVABLY dead/stale: a dead owner PID, OR (no PID)
 *                an owner timestamp older than staleMs. An ALIVE owner PID is
 *                authoritative-LIVE and the lock is KEPT regardless of timestamp age, so
 *                it NEVER removes a live lock. It is symlink-safe (CWE-59): lstat
 *                no-follow at the lock path, a symlink AT wrap/lock is unlinked (link
 *                only, never its target), a plain file is left alone, and rmSync runs
 *                ONLY on a confirmed real directory. readWrapLockOwner is likewise
 *                symlink-safe (CWE-59) at BOTH levels: (1) the parent lock dir is
 *                lstat-guarded - a wrap/lock symlink returns {null,null} before any child
 *                path is opened; (2) the leaf owner is lstat-guarded - a planted
 *                `wrap/lock/owner -> /etc/passwd` is detected and never read through.
 *                Both are fail-open (never throw), and (1) makes the reader self-sufficient
 *                for any caller without requiring a prior parent-level lstat.
 *                The ownerIsStale(owner, staleMs) helper is shared between
 *                wrapLockProvablyStale (new path) and wrapLockProvablyStaleLegacy (old
 *                path), single-sourcing the CWE-59 symlink-guarded owner read.
 *
 * Performance: standard. Synchronous fs only; no git, no network, no subprocess.
 *              listReadyMarkers / listInProgressMarkers glob one directory
 *              (readdirSync), filter names to the UUID shape, then stat-read at most
 *              MAX_MARKERS_PER_SCAN pending-<uuid>.json files once each.
 */

'use strict';

const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SCHEMA_VERSION = 3;
const MARKER_PREFIX = 'pending-';
const MARKER_SUFFIX = '.json';
// Default heartbeat freshness window (ms) - a heartbeat younger than this means
// the session is still emitting turns and a ready marker should be deferred.
const DEFAULT_HEARTBEAT_FRESH_MS = 120 * 1000;
const MAX_ATTEMPTS = 3;

// SEC-M2 (DoS, unbounded JSON read): a marker is a tiny fixed-shape JSON blob. A
// hostile repo could plant a multi-GB pending-<id>.json that the daemon
// re-reads every poll tick; cap the size and treat anything larger as unreadable
// (fail-open -> null). 64 KB is generous for the marker schema.
const MAX_MARKER_BYTES = 64 * 1024;
// SEC-M3 (DoS, unbounded scan): the session component of a marker filename is a
// Claude session UUID. Filter readdir results to this shape BEFORE reading any file
// so a directory full of hostile non-UUID pending-*.json files is never opened.
const SESSION_UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
// SEC-M3 cap: process at most this many markers per scan. A near-idle project has a
// handful; this only bites a pathologically large (likely hostile) directory, where
// reading every file each tick would be the DoS. We log when truncated.
const MAX_MARKERS_PER_SCAN = 1000;
// Rotation cap for the daemon-owned .agentic/wrap/daemon.log. The daemon (not this
// lib) writes the log; when the live file crosses this size it is renamed to
// .log.1 (single generation) and a fresh live file is started. 2 MB is generous for
// human-readable lifecycle + per-run outcome + captured child output lines.
const MAX_DAEMON_LOG_BYTES = 2 * 1024 * 1024;
// Per-run hard cap on the in-memory buffer that captures one headless /wrap-deferred
// child's stdout/stderr before it is flushed to the log. The daemon keeps the stream
// listener attached past the cap (drain-and-discard) so a chatty child cannot wedge
// on a full OS pipe; it just stops growing this buffer. 256 KB is ample for a wrap run.
const MAX_CHILD_CAPTURE_BYTES = 256 * 1024;

// ---------------------------------------------------------------------------
// Internal helpers (not exported)
// ---------------------------------------------------------------------------

/**
 * Reject cwd values that contain path-traversal components. Returns the resolved
 * cwd when clean, or null when traversal is detected (caller must bail).
 */
function safeCwd(cwd) {
  try {
    if (typeof cwd !== 'string' || !cwd) return null;
    const resolved = path.resolve(cwd);
    return resolved === cwd ? resolved : null;
  } catch (_) {
    return null;
  }
}

/** Sanitize a session id for use as a filename component (fail-open: null on bad input). */
function safeSessionId(sessionId) {
  if (typeof sessionId !== 'string') return null;
  const trimmed = sessionId.trim();
  if (!trimmed) return null;
  // Disallow path separators and traversal to keep markerPath inside .agentic/.
  if (trimmed.includes('/') || trimmed.includes('\\') || trimmed.includes('..')) return null;
  return trimmed;
}

function agenticDir(cwd) {
  return path.join(cwd, '.agentic');
}

/** Returns the .agentic/wrap/ subdirectory path for wrap runtime artifacts. */
function wrapDir(cwd) {
  return path.join(agenticDir(cwd), 'wrap');
}

/** Atomic write (tmp + rename). Fail-open: returns true on success, false otherwise. */
function atomicWriteJson(targetPath, obj) {
  try {
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    const tmpPath = targetPath + '.tmp';
    fs.writeFileSync(tmpPath, JSON.stringify(obj, null, 2), 'utf8');
    fs.renameSync(tmpPath, targetPath);
    return true;
  } catch (_) {
    return false;
  }
}

/**
 * Best-effort diagnostic to stderr - the lib is otherwise silent (its consumers own
 * stdout). NEVER throws; swallows any write error. Used only for the SEC-M3 scan-cap
 * truncation warning, a genuinely abnormal (likely hostile) condition worth surfacing.
 */
function warn(msg) {
  try { process.stderr.write('[wrap-marker] ' + msg + '\n'); } catch (_) { /* ignore */ }
}

/**
 * Read + parse a marker file by absolute path. Fail-open: null on any error.
 * SEC-M2: stat-then-read - skip an over-cap (or non-regular) file before loading its
 * bytes, so a planted multi-GB marker cannot wedge a scan.
 */
function readMarkerFile(absPath) {
  try {
    const st = fs.statSync(absPath); // throws if absent -> caught -> null
    if (!st.isFile() || st.size > MAX_MARKER_BYTES) return null;
    const raw = fs.readFileSync(absPath, 'utf8');
    const marker = JSON.parse(raw);
    return (marker && typeof marker === 'object') ? marker : null;
  } catch (_) {
    return null;
  }
}

/** Return true when the given PID is dead (ESRCH), false when alive or indeterminate. */
function pidIsDead(pid) {
  const n = Number(pid);
  if (!Number.isInteger(n) || n <= 0) return false; // unknown PID -> treat as alive (do not reclaim)
  try {
    process.kill(n, 0);
    return false; // signal delivered -> alive
  } catch (err) {
    if (err && err.code === 'ESRCH') return true;  // no such process -> dead
    if (err && err.code === 'EPERM') return false;  // exists, not ours -> alive, skip
    return false; // any other error -> conservatively treat as alive
  }
}

/** Parse an ISO8601 timestamp to ms; NaN-safe (returns null on bad input). */
function tsMs(iso) {
  if (typeof iso !== 'string' || !iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
}

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

function markerPath(cwd, sessionId) {
  const sid = safeSessionId(sessionId);
  if (!sid) return null;
  return path.join(wrapDir(cwd), MARKER_PREFIX + sid + MARKER_SUFFIX);
}

function lastWrapPath(cwd) {
  return path.join(wrapDir(cwd), 'last-wrap');
}

function wrapLockPath(cwd) {
  return path.join(wrapDir(cwd), 'lock');
}

function wrapLockOwnerPath(cwd) {
  return path.join(wrapDir(cwd), 'lock', 'owner');
}

function daemonPidPath(cwd) {
  return path.join(wrapDir(cwd), 'daemon.pid');
}

function wrapDaemonLogPath(cwd) {
  return path.join(wrapDir(cwd), 'daemon.log');
}

function authFailedPath(cwd) {
  return path.join(wrapDir(cwd), 'daemon-auth-failed');
}

function claudeHostPath(cwd) {
  return path.join(wrapDir(cwd), 'claude-host');
}

function heartbeatPath(cwd, sessionId) {
  const sid = safeSessionId(sessionId);
  if (!sid) return null;
  return path.join(wrapDir(cwd), 'heartbeats', sid);
}

/** Path for the spillover log written by the Stop hook when wrap/lock is held. */
function stopDeferredActivityPath(cwd) {
  return path.join(wrapDir(cwd), 'deferred-activity.jsonl');
}

// ---------------------------------------------------------------------------
// Loop-guard
// ---------------------------------------------------------------------------

function daemonGuardActive() {
  return process.env.AGENTIC_WRAP_DAEMON === '1';
}

// ---------------------------------------------------------------------------
// Reads (unguarded)
// ---------------------------------------------------------------------------

function readMarker(cwd, sessionId) {
  const p = markerPath(cwd, sessionId);
  if (!p) return null;
  return readMarkerFile(p);
}

/**
 * List every pending-*.json marker in .agentic/wrap/ in status `ready`, sorted by
 * staged_at ascending (FIFO). Each entry is { sessionId, path, marker }. Fail-open: [].
 */
function listReadyMarkers(cwd) {
  return listMarkersByStatus(cwd, 'ready');
}

/** List every pending-*.json marker in .agentic/wrap/ in status `in_progress`. Fail-open: []. */
function listInProgressMarkers(cwd) {
  return listMarkersByStatus(cwd, 'in_progress');
}

/** Shared scanner for listReadyMarkers / listInProgressMarkers. */
function listMarkersByStatus(cwd, wantStatus) {
  const out = [];
  try {
    const dir = wrapDir(cwd);
    let names;
    try {
      names = fs.readdirSync(dir);
    } catch (_) {
      return out; // .agentic/wrap/ absent -> no markers
    }
    // SEC-M3 (a) SHORT-CIRCUIT: keep only well-formed pending-<UUID>.json names
    // and validate the session component against the UUID shape BEFORE opening any
    // file. A directory full of hostile non-UUID pending-*.json files is thus
    // filtered with a cheap regex test and never read/parsed.
    const candidates = [];
    for (const name of names) {
      if (!name.startsWith(MARKER_PREFIX) || !name.endsWith(MARKER_SUFFIX)) continue;
      const sessionId = name.slice(MARKER_PREFIX.length, name.length - MARKER_SUFFIX.length);
      if (!sessionId || !SESSION_UUID_RE.test(sessionId)) continue;
      candidates.push({ sessionId, abs: path.join(dir, name) });
    }
    // SEC-M3 (b) CAP: never read+parse more than MAX_MARKERS_PER_SCAN files per tick.
    // A near-idle project has a handful; truncation only bites a pathologically large
    // (likely hostile) directory and is surfaced via warn(). Sorting happens below on
    // the (already bounded) results.
    let truncated = false;
    let scanned = candidates;
    if (candidates.length > MAX_MARKERS_PER_SCAN) {
      truncated = true;
      scanned = candidates.slice(0, MAX_MARKERS_PER_SCAN);
    }
    for (const c of scanned) {
      const marker = readMarkerFile(c.abs);
      if (!marker || marker.status !== wantStatus) continue;
      out.push({ sessionId: c.sessionId, path: c.abs, marker });
    }
    if (truncated) {
      warn('marker scan truncated at ' + MAX_MARKERS_PER_SCAN + ' of ' + candidates.length
        + ' candidate markers in ' + dir + ' (possible DoS; processing the first '
        + MAX_MARKERS_PER_SCAN + ')');
    }
  } catch (_) {
    return out;
  }
  // FIFO by staged_at ascending; markers with an unparseable staged_at sort last.
  out.sort((a, b) => {
    const ta = tsMs(a.marker && a.marker.staged_at);
    const tb = tsMs(b.marker && b.marker.staged_at);
    if (ta === null && tb === null) return 0;
    if (ta === null) return 1;
    if (tb === null) return -1;
    return ta - tb;
  });
  return out;
}

/**
 * Return true when this session's marker is LIVE (status pending / ready /
 * in_progress). done / gave_up / absent / unreadable -> false. Replaces the old
 * single-file liveMarkerExists. Fail-open: false.
 */
function liveMarkerForSession(cwd, sessionId) {
  const marker = readMarker(cwd, sessionId);
  if (!marker) return false;
  const s = marker.status;
  return s === 'pending' || s === 'ready' || s === 'in_progress';
}

function readLastWrap(cwd) {
  try {
    const p = lastWrapPath(cwd);
    if (!fs.existsSync(p)) return null;
    const raw = fs.readFileSync(p, 'utf8').trim();
    return raw || null;
  } catch (_) {
    return null;
  }
}

/**
 * Return true when a /wrap holds the lock at .agentic/wrap/lock (a DIRECTORY
 * created by atomic mkdir). Fail-open: false (treat unreadable as not-held).
 */
function wrapLockHeld(cwd) {
  try { return fs.existsSync(wrapLockPath(cwd)); }
  catch (_) { return false; }
}

/**
 * Return true when the wrap.lock directory exists AND its mtime is older than
 * staleMs (so it is safe to clear). Fail-open: false (never wrongly clear).
 */
function wrapLockStale(cwd, staleMs) {
  try {
    const p = wrapLockPath(cwd);
    const st = fs.statSync(p); // throws if absent
    const age = Date.now() - st.mtimeMs;
    return age > staleMs;
  } catch (_) {
    return false;
  }
}

/**
 * Return true when this session's heartbeat exists AND its mtime is younger than
 * freshMs (session still emitting turns). Missing heartbeat -> false (safe to
 * claim). Fail-open: false.
 */
function heartbeatFresh(cwd, sessionId, freshMs) {
  const window = (typeof freshMs === 'number' && freshMs > 0) ? freshMs : DEFAULT_HEARTBEAT_FRESH_MS;
  try {
    const p = heartbeatPath(cwd, sessionId);
    if (!p) return false;
    const st = fs.statSync(p); // throws if absent
    return (Date.now() - st.mtimeMs) < window;
  } catch (_) {
    return false; // missing/unreadable -> not fresh -> safe to claim
  }
}

function isClaudeHost(cwd) {
  try { return fs.existsSync(claudeHostPath(cwd)); }
  catch (_) { return false; }
}

// ---------------------------------------------------------------------------
// Sentinel write (UNGUARDED, fail-open)
// ---------------------------------------------------------------------------

/**
 * Create the .agentic/wrap/claude-host sentinel if absent (create-if-absent via
 * the 'wx' flag). Intentionally UNGUARDED: writing a true fact is harmless and
 * this self-heals existing installs that never re-ran install.sh (MAJOR-B).
 * Idempotent; swallows EEXIST and every other fs error.
 */
function ensureClaudeHost(cwd) {
  try {
    fs.mkdirSync(wrapDir(cwd), { recursive: true });
    fs.writeFileSync(claudeHostPath(cwd), '', { flag: 'wx' });
  } catch (_) {
    // EEXIST (already present) or any fs error - swallow; fail-open.
  }
}

// ---------------------------------------------------------------------------
// Transitions (NO-OP under guard)
// ---------------------------------------------------------------------------

/** Write a full marker object atomically for the given session. Guarded NO-OP. */
function writeMarker(cwd, marker) {
  if (daemonGuardActive()) return false;
  const safe = safeCwd(cwd);
  if (!safe) return false;
  if (!marker || typeof marker !== 'object') return false;
  const p = markerPath(safe, marker.session_id);
  if (!p) return false;
  return atomicWriteJson(p, marker);
}

/**
 * Stage a `pending` marker for this session if (and only if) staging is warranted.
 * Suppression (all must clear to proceed):
 *   - guarded NO-OP under AGENTIC_WRAP_DAEMON=1
 *   - this session already wrapped (.last-wrap === sessionId)
 *   - this session's marker is already ready / pending / in_progress (MAJOR-3)
 *     (a done / gave_up / absent marker does NOT suppress - re-staging is allowed)
 *   - this session's marker is `done` WITH a parseable `wrapped_at` (tombstone
 *     suppression: this session already completed /wrap; .last-wrap may have rolled
 *     to a different session but the tombstone remains as the durable backstop)
 *     NOTE: a `done` marker WITHOUT a parseable `wrapped_at` does NOT suppress
 *     (back-compat + recycled-id carve-out)
 *   - the session had no substantive activity
 * Uses only the already-computed scan counts (no git/subprocess). Fail-open.
 */
function stagePending(cwd, sessionId, scan) {
  if (daemonGuardActive()) return false;
  const safe = safeCwd(cwd);
  if (!safe) return false;
  const sid = safeSessionId(sessionId);
  if (!sid) return false;

  // Suppress if this session already wrapped.
  if (readLastWrap(safe) === sid) return false;

  // MAJOR-3: suppress on a LIVE marker (ready / pending / in_progress) for THIS
  // session. done / gave_up / absent do not suppress.
  if (liveMarkerForSession(safe, sid)) return false;

  // Tombstone suppression: a `done` marker WITH a parseable `wrapped_at` means this
  // session already completed /wrap; suppress re-staging even if .last-wrap has rolled
  // to a different session. A `done` marker WITHOUT a parseable `wrapped_at` (legacy /
  // recycled-id) does NOT suppress - re-staging proceeds normally.
  const self = readMarker(safe, sid);
  if (self && self.status === 'done' && tsMs(self.wrapped_at) !== null) return false;

  // Require substantive activity.
  const s = scan || {};
  const substantive = (s.uncommittedCount >= 1)
    || (s.pathsReferencedCount >= 1)
    || (s.recentFocusCount >= 1);
  if (!substantive) return false;

  const marker = {
    schema_version: SCHEMA_VERSION,
    session_id: sid,
    staged_at: new Date().toISOString(),
    status: 'pending',
    claimed_by: null,
    claimed_kind: null,
    claimed_at: null,
    attempts: 0,
    project_root: safe,
    last_error: null,
  };
  const p = markerPath(safe, sid);
  if (!p) return false;
  return atomicWriteJson(p, marker);
}

/**
 * Promote this session's marker from pending (or absent) to `ready`. This is the
 * SOLE pending->ready transition (no sweep, no daemon, no SessionStart - CRITICAL-A).
 * Writes `ready` ONLY when the current marker is pending or absent; no-op when it
 * is already ready / in_progress / done / gave_up (no-downgrade, idempotent).
 * Does NOT carry branch / head_sha. Guarded NO-OP. Fail-open.
 */
function finalizeReady(cwd, sessionId) {
  if (daemonGuardActive()) return false;
  const safe = safeCwd(cwd);
  if (!safe) return false;
  const sid = safeSessionId(sessionId);
  if (!sid) return false;

  const existing = readMarker(safe, sid);
  const status = existing && existing.status;
  // Only pending|absent are promotable. Anything else no-ops.
  if (status && status !== 'pending') return false;

  const base = (existing && typeof existing === 'object') ? existing : {
    schema_version: SCHEMA_VERSION,
    session_id: sid,
    staged_at: new Date().toISOString(),
    claimed_by: null,
    claimed_kind: null,
    claimed_at: null,
    attempts: 0,
    project_root: safe,
    last_error: null,
  };
  const marker = Object.assign({}, base, {
    schema_version: SCHEMA_VERSION,
    session_id: sid,
    status: 'ready',
    project_root: safe,
  });
  const p = markerPath(safe, sid);
  if (!p) return false;
  return atomicWriteJson(p, marker);
}

/**
 * Claim a `ready` marker, moving it to `in_progress` and stamping claimed_by /
 * claimed_kind / claimed_at and incrementing attempts. Returns the updated marker
 * object on success, or null when the marker is not claimable (absent / not ready /
 * already claimed by a live session within staleMs). Guarded NO-OP -> null.
 * Fail-open: null.
 */
function claimMarker(cwd, sessionId, owner, kind, staleMs) {
  if (daemonGuardActive()) return null;
  const safe = safeCwd(cwd);
  if (!safe) return null;
  const sid = safeSessionId(sessionId);
  if (!sid) return null;

  const existing = readMarker(safe, sid);
  if (!existing) return null;
  if (existing.status !== 'ready') return null;

  const marker = Object.assign({}, existing, {
    schema_version: SCHEMA_VERSION,
    status: 'in_progress',
    claimed_by: (owner === undefined || owner === null) ? null : owner,
    claimed_kind: (kind === undefined || kind === null) ? null : kind,
    claimed_at: new Date().toISOString(),
    attempts: (Number.isInteger(existing.attempts) ? existing.attempts : 0) + 1,
  });
  const p = markerPath(safe, sid);
  if (!p) return null;
  return atomicWriteJson(p, marker) ? marker : null;
}

/**
 * Mark this session's marker `done`, stamp `wrapped_at`, RETAIN the marker as a
 * per-session `wrapped_at`-stamped tombstone, and remove only the heartbeat.
 * The retained tombstone suppresses same-session re-staging (stagePending checks
 * for it) and is reaped by cleanStalePending after `deferred_wrap_pending_ttl_days`.
 * Guarded NO-OP. Fail-open.
 */
function transitionDone(cwd, sessionId) {
  if (daemonGuardActive()) return false;
  const safe = safeCwd(cwd);
  if (!safe) return false;
  const sid = safeSessionId(sessionId);
  if (!sid) return false;

  const p = markerPath(safe, sid);
  if (!p) return false;
  // RETAIN the marker as a per-session `wrapped_at`-stamped tombstone; remove only
  // the heartbeat. The tombstone prevents this session being re-staged after
  // .agentic/wrap/last-wrap rolls to a different session.
  const existing = readMarker(safe, sid) || { session_id: sid, project_root: safe };
  const marker = Object.assign({}, existing, {
    schema_version: SCHEMA_VERSION,
    session_id: sid,
    status: 'done',
    wrapped_at: new Date().toISOString(),
  });
  atomicWriteJson(p, marker);
  removeHeartbeat(safe, sid);
  return true;
}

/**
 * Mark this session's marker `gave_up` with last_error. Marker is RETAINED (a
 * manual-/wrap notice surface). Guarded NO-OP. Fail-open.
 */
function transitionGaveUp(cwd, sessionId, err) {
  if (daemonGuardActive()) return false;
  const safe = safeCwd(cwd);
  if (!safe) return false;
  const sid = safeSessionId(sessionId);
  if (!sid) return false;

  const p = markerPath(safe, sid);
  if (!p) return false;
  const existing = readMarker(safe, sid) || { session_id: sid, project_root: safe };
  const marker = Object.assign({}, existing, {
    schema_version: SCHEMA_VERSION,
    session_id: sid,
    status: 'gave_up',
    last_error: (typeof err === 'string' && err) ? err : (existing.last_error || null),
  });
  return atomicWriteJson(p, marker);
}

// ---------------------------------------------------------------------------
// Reclaim / janitor (daemon-internal; NO-OP under guard)
// ---------------------------------------------------------------------------

/**
 * Daemon-startup reclaim of markers a DEAD daemon abandoned in `in_progress`
 * (MAJOR-C). For each in_progress marker, reset to `ready` IFF:
 *   - claimed_kind === 'daemon', AND
 *   - claimed_at is older than staleMs, AND
 *   - claimed_by PID is dead (process.kill(pid, 0) -> ESRCH).
 * If attempts >= 3, the marker is moved to `gave_up` instead of `ready`.
 * NEVER touches pending markers, session-claimed markers, live-PID markers, or
 * fresh (within staleMs) markers. Guarded NO-OP -> {reclaimed:[], gaveUp:[]}.
 * Fail-open per marker. Returns { reclaimed: [sessionId...], gaveUp: [sessionId...] }.
 */
function reclaimAbandonedInProgress(cwd, staleMs) {
  const result = { reclaimed: [], gaveUp: [] };
  if (daemonGuardActive()) return result;
  const safe = safeCwd(cwd);
  if (!safe) return result;

  const inProgress = listInProgressMarkers(safe);
  for (const entry of inProgress) {
    try {
      const m = entry.marker;
      if (!m) continue;
      // Only daemon-claimed markers are eligible.
      if (m.claimed_kind !== 'daemon') continue;
      // Must be stale by claimed_at.
      const claimedMs = tsMs(m.claimed_at);
      if (claimedMs === null) continue;            // unparseable -> skip (do not touch)
      if ((Date.now() - claimedMs) <= staleMs) continue; // still fresh -> skip
      // Owning PID must be dead.
      if (!pidIsDead(m.claimed_by)) continue;      // alive or indeterminate -> skip

      const attempts = Number.isInteger(m.attempts) ? m.attempts : 0;
      if (attempts >= MAX_ATTEMPTS) {
        // Exhausted budget -> gave_up. Write directly (transitionGaveUp would also
        // work but we want to preserve the existing marker fields verbatim).
        const giveUp = Object.assign({}, m, {
          schema_version: SCHEMA_VERSION,
          status: 'gave_up',
          last_error: 'reclaimed-after-max-attempts',
        });
        if (atomicWriteJson(entry.path, giveUp)) result.gaveUp.push(entry.sessionId);
      } else {
        // Reset to ready; clear the claim so the daemon can re-claim it fresh.
        const reclaimed = Object.assign({}, m, {
          schema_version: SCHEMA_VERSION,
          status: 'ready',
          claimed_by: null,
          claimed_kind: null,
          claimed_at: null,
        });
        if (atomicWriteJson(entry.path, reclaimed)) result.reclaimed.push(entry.sessionId);
      }
    } catch (_) {
      // Fail-open per marker - skip and continue.
    }
  }
  return result;
}

/**
 * Bounded janitor (MINOR-1): DELETE `pending` markers whose staged_at is older
 * than ttlMs, AND DELETE `done` tombstones whose wrapped_at (or staged_at as
 * fallback) is older than ttlMs. DELETE-ONLY - it NEVER status-mutates any marker,
 * so it cannot promote a live/idle session (CRITICAL-A). Touches ONLY pending and
 * done markers; never touches ready / in_progress / gave_up.
 *
 * done-tombstone age key: tsMs(marker.wrapped_at) ?? tsMs(marker.staged_at).
 * When BOTH are unparseable, the tombstone is SKIPPED (left on disk) - same
 * conservative behavior as the pending fallback above.
 *
 * Guarded NO-OP -> {deleted:[]}. Fail-open per marker.
 * Returns { deleted: [sessionId...] }.
 */
function cleanStalePending(cwd, ttlMs) {
  const result = { deleted: [] };
  if (daemonGuardActive()) return result;
  const safe = safeCwd(cwd);
  if (!safe) return result;

  const pending = listMarkersByStatus(safe, 'pending');
  for (const entry of pending) {
    try {
      const stagedMs = tsMs(entry.marker && entry.marker.staged_at);
      if (stagedMs === null) continue;             // unparseable -> leave alone
      if ((Date.now() - stagedMs) <= ttlMs) continue; // still within TTL -> keep
      fs.unlinkSync(entry.path);                   // DELETE-ONLY (never mutate status)
      // PERF-Minor (orphan heartbeat leak): a session that staged a marker and then
      // abnormally terminated also leaves a sibling heartbeat file. When we delete the
      // stale pending marker, co-delete its heartbeat so it cannot accumulate. This is
      // delete-only and idempotent (removeHeartbeat is fail-open); a heartbeat-unlink
      // failure must NEVER abort the marker sweep, so it stays inside this try/catch.
      removeHeartbeat(safe, entry.sessionId);
      result.deleted.push(entry.sessionId);
    } catch (_) {
      // Fail-open per marker.
    }
  }

  // Sweep done tombstones older than ttlMs. Age key: wrapped_at ?? staged_at.
  // Both-unparseable -> SKIP (leave on disk). NEVER touches ready/in_progress/gave_up.
  const done = listMarkersByStatus(safe, 'done');
  for (const entry of done) {
    try {
      const m = entry.marker;
      const ageMs = tsMs(m && m.wrapped_at) ?? tsMs(m && m.staged_at);
      if (ageMs === null) continue;               // both timestamps unparseable -> skip
      if ((Date.now() - ageMs) <= ttlMs) continue; // still within TTL -> keep
      fs.unlinkSync(entry.path);                   // DELETE-ONLY
      removeHeartbeat(safe, entry.sessionId);      // idempotent co-delete
      result.deleted.push(entry.sessionId);
    } catch (_) {
      // Fail-open per marker.
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Lock management (NEVER prompts)
// ---------------------------------------------------------------------------

/**
 * Acquire the wrap.lock directory via atomic mkdir (O_EXCL semantics). On
 * collision, if the existing lock is stale (older than staleMs) it is force-cleared
 * (rm -rf) and acquisition is retried ONCE; otherwise acquisition fails. NEVER
 * prompts. Writes an owner file inside the lock dir for diagnostics. Returns true
 * on acquisition, false otherwise. Fail-open: false.
 */
function acquireWrapLock(cwd, owner, staleMs) {
  const safe = safeCwd(cwd);
  if (!safe) return false;
  const lockDir = wrapLockPath(safe);
  const tryMkdir = () => {
    try {
      fs.mkdirSync(path.dirname(lockDir), { recursive: true });
      fs.mkdirSync(lockDir); // throws EEXIST if held
      try {
        fs.writeFileSync(wrapLockOwnerPath(safe), String(owner == null ? '' : owner), 'utf8');
      } catch (_) {}
      return true;
    } catch (err) {
      if (err && err.code === 'EEXIST') return false;
      return false; // any other fs error -> treat as not acquired
    }
  };

  if (tryMkdir()) return true;

  // Collision: clear if stale, then retry once.
  if (wrapLockStale(safe, staleMs)) {
    try { fs.rmSync(lockDir, { recursive: true, force: true }); } catch (_) {}
    return tryMkdir();
  }
  return false;
}

/** Release the wrap.lock directory (rm -rf, idempotent). Fail-open. */
function releaseWrapLock(cwd) {
  const safe = safeCwd(cwd);
  if (!safe) return false;
  try {
    fs.rmSync(wrapLockPath(safe), { recursive: true, force: true });
    return true;
  } catch (_) {
    return false;
  }
}

// Local cap on the lock/owner read. The owner file is at most two short lines
// (a PID and an ISO timestamp); cap the read so a giant planted owner file cannot
// wedge a daemon tick. Mirrors the SEC-M2 stat-then-read discipline.
const MAX_OWNER_BYTES = 4 * 1024;

// ---------------------------------------------------------------------------
// Shared lock-staleness helpers (single-sourced, CWE-59 symlink-guarded)
// ---------------------------------------------------------------------------

/**
 * Symlink-guarded, CWE-59-safe owner-file reader. Reads the two-line owner body
 * at ownerPath under lockPath, guarding against symlinks at BOTH levels.
 * Returns { pid, ts } on success, { pid: null, ts: null } on any guard or error.
 * This is the ONE canonical reader used by readWrapLockOwner, wrapLockProvablyStale,
 * and wrapLockProvablyStaleLegacy so symlink protection is never copy-pasted.
 *
 * @param {string} lockPath - The lock directory path (lstat-checked no-follow).
 * @param {string} ownerPath - The owner file path inside the lock dir.
 */
function readOwnerAt(lockPath, ownerPath) {
  const empty = { pid: null, ts: null };
  try {
    // (1) PARENT guard: if the lock dir itself is a symlink, bail immediately.
    const lockSt = fs.lstatSync(lockPath); // throws if absent -> caught -> empty
    if (lockSt.isSymbolicLink()) return empty;

    // (2) LEAF guard: if the owner file is a symlink, bail without reading.
    const st = fs.lstatSync(ownerPath); // no-follow; throws ENOENT when absent -> empty
    if (st.isSymbolicLink()) return empty;
    if (!st.isFile()) return empty;
    if (st.size > MAX_OWNER_BYTES) return empty;
    const raw = fs.readFileSync(ownerPath, 'utf8');
    const lines = raw.split('\n');
    const pidNum = Number((lines[0] || '').trim());
    const pid = (Number.isInteger(pidNum) && pidNum > 0) ? pidNum : null;
    const tsRaw = (lines.length > 1 ? lines[1] : '').trim();
    const ts = tsRaw ? tsRaw : null;
    return { pid, ts };
  } catch (_) {
    return empty;
  }
}

/**
 * Evaluate the lock staleness predicate given an already-read owner object.
 * Returns true ONLY when the lock is PROVABLY stale:
 *   - dead owner PID (pidIsDead returns true), OR
 *   - no PID AND a parseable ts older than staleMs.
 * Returns false (KEEP) when:
 *   - PID is alive (authoritative-live),
 *   - no usable signal: no PID AND no parseable ts (mkdir-before-owner race),
 *   - both pid and ts are null (empty owner).
 * This predicate is the single source of truth shared by clearProvablyStaleWrapLock,
 * wrapLockProvablyStale, and wrapLockProvablyStaleLegacy.
 *
 * @param {{ pid: number|null, ts: string|null }} owner
 * @param {number} staleMs
 */
function ownerIsStale(owner, staleMs) {
  if (owner.pid !== null) {
    return pidIsDead(owner.pid); // alive -> KEEP; dead -> CLEAR
  }
  if (owner.ts !== null) {
    const tms = tsMs(owner.ts);
    return (tms !== null) && ((Date.now() - tms) > staleMs);
  }
  return false; // no usable signal -> KEEP (fail-open)
}

/**
 * Staleness predicate for the NEW lock path (.agentic/wrap/lock). Evaluates
 * whether the current lock is provably stale without performing any removal.
 * Returns false (KEEP) on: alive PID, no-usable-signal, any fs error, or a
 * symlink at the lock path. Returns true ONLY on dead PID OR (no PID + ts older
 * than staleMs). Used by session-start-wrap.sh's migration node one-liner.
 * Fail-open: false.
 *
 * @param {string} cwd
 * @param {number} staleMs
 */
function wrapLockProvablyStale(cwd, staleMs) {
  try {
    const lockPath = wrapLockPath(cwd);
    let st;
    try { st = fs.lstatSync(lockPath); } catch (_) { return false; } // absent -> KEEP (no lock)
    if (st.isSymbolicLink()) return false; // symlink -> KEEP (hostile artifact, not our lock)
    if (!st.isDirectory()) return false;   // plain file -> KEEP
    const owner = readOwnerAt(lockPath, wrapLockOwnerPath(cwd));
    return ownerIsStale(owner, staleMs);
  } catch (_) {
    return false; // fail-open
  }
}

/**
 * Staleness predicate for the LEGACY lock path (.agentic/wrap.lock). Identical
 * semantics to wrapLockProvablyStale but checks the OLD location. Used by
 * session-start-wrap.sh to decide whether to relocate an existing legacy lock.
 * Fail-open: false.
 *
 * @param {string} cwd
 * @param {number} staleMs
 */
function wrapLockProvablyStaleLegacy(cwd, staleMs) {
  const legacyLockPath = path.join(agenticDir(cwd), 'wrap.lock');
  const legacyOwnerPath = path.join(agenticDir(cwd), 'wrap.lock', 'owner');
  try {
    let st;
    try { st = fs.lstatSync(legacyLockPath); } catch (_) { return false; }
    if (st.isSymbolicLink()) return false;
    if (!st.isDirectory()) return false;
    const owner = readOwnerAt(legacyLockPath, legacyOwnerPath);
    return ownerIsStale(owner, staleMs);
  } catch (_) {
    return false; // fail-open
  }
}

/**
 * Read the wrap/lock/owner file into { pid, ts }. The owner body is 2-line
 * (PID + ISO timestamp, written by the interactive `/wrap`), 1-line (PID-only,
 * written by acquireWrapLock), empty, or absent.
 *   - line0 -> a positive integer PID, else null
 *   - line1 (if present) -> a trimmed non-empty ISO string, else null
 * Fail-open: { pid: null, ts: null } on any error.
 *
 * SECURITY (CWE-59, defense-in-depth): delegates to readOwnerAt which guards
 * against symlinks at BOTH levels (parent lock dir AND leaf owner file) so it is
 * safe for any caller, not just the parent-validating one.
 */
function readWrapLockOwner(cwd) {
  return readOwnerAt(wrapLockPath(cwd), wrapLockOwnerPath(cwd));
}

/**
 * Clear a PROVABLY-stale wrap.lock DIRECTORY (the headless deferred-`/wrap` child
 * runs with Bash removed and cannot `rm` it; the trusted daemon clears it instead).
 * Returns true IFF a real stale lock directory was removed; false otherwise. Never
 * throws (fail-open).
 *
 * Stale predicate (exact): CLEAR iff
 *   (owner.pid !== null && pidIsDead(owner.pid))                                 -- dead owner PID
 *   OR (owner.pid === null && owner.ts !== null && tsMs(owner.ts) !== null
 *       && (Date.now() - tsMs(owner.ts)) > staleMs)                              -- no PID + old timestamp
 * An ALIVE pid is authoritative-LIVE -> KEEP regardless of timestamp age (this is the
 * live-lock corruption guard: liveness, not age, drives the clear). No usable owner
 * signal (no PID and no parseable timestamp) -> KEEP, covering the interactive `/wrap`
 * mkdir-before-owner race. This must NEVER clear a live lock.
 *
 * SECURITY (CWE-59, models appendToLog's symlink discipline): the removal sequence
 * lstats the lock path no-follow and refuses to rmSync anything that is not a confirmed
 * real directory. A symlink AT wrap.lock is unlinked (link only, never its target); a
 * plain file is left alone. readWrapLockOwner is itself symlink-guarded.
 */
function clearProvablyStaleWrapLock(cwd, staleMs) {
  try {
    const lockPath = wrapLockPath(cwd);
    let st;
    try {
      st = fs.lstatSync(lockPath); // no-follow; ENOENT -> caught -> return false
    } catch (_) {
      return false; // no lock present
    }
    if (st.isSymbolicLink()) {
      // A symlink AT wrap.lock is a hostile artifact, not our lock. unlink removes ONLY
      // the link (never follows it / touches the target). Do NOT rmSync.
      try { fs.unlinkSync(lockPath); } catch (_) {}
      return false; // removed a hostile artifact, not a real lock
    }
    if (!st.isDirectory()) {
      return false; // a plain file at wrap.lock is not our (mkdir-created) lock; leave it
    }
    // Real directory: evaluate the stale predicate via the single-sourced helper.
    const owner = readWrapLockOwner(cwd);
    if (!ownerIsStale(owner, staleMs)) return false; // live / no usable signal -> KEEP
    // Confirmed real, stale directory. Step's lstat already proved the top-level path is
    // a directory (not a symlink), so rmSync(recursive) recurses into a directory we own;
    // any symlinks encountered DURING recursion are unlinked, not followed (rm -rf semantics).
    fs.rmSync(lockPath, { recursive: true, force: true });
    return true;
  } catch (_) {
    return false; // fail-open: never throw, never wrongly report a clear
  }
}

// ---------------------------------------------------------------------------
// Heartbeat
// ---------------------------------------------------------------------------

/**
 * Touch (create/update mtime) this session's heartbeat file. NO-OP under guard.
 * Local fs only - no git, no network. Fail-open.
 */
function touchHeartbeat(cwd, sessionId) {
  if (daemonGuardActive()) return false;
  const safe = safeCwd(cwd);
  if (!safe) return false;
  const p = heartbeatPath(safe, sessionId);
  if (!p) return false;
  try {
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const now = new Date();
    if (fs.existsSync(p)) {
      fs.utimesSync(p, now, now);
    } else {
      fs.writeFileSync(p, '', 'utf8');
    }
    return true;
  } catch (_) {
    return false;
  }
}

/** Remove this session's heartbeat file (idempotent). Fail-open. UNGUARDED (cleanup). */
function removeHeartbeat(cwd, sessionId) {
  const safe = safeCwd(cwd);
  if (!safe) return false;
  const p = heartbeatPath(safe, sessionId);
  if (!p) return false;
  try { fs.unlinkSync(p); } catch (_) {}
  return true;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

module.exports = {
  // constants (exported for consumers/tests)
  SCHEMA_VERSION,
  MAX_DAEMON_LOG_BYTES,
  MAX_CHILD_CAPTURE_BYTES,
  // paths
  markerPath,
  lastWrapPath,
  wrapLockPath,
  wrapLockOwnerPath,
  daemonPidPath,
  wrapDaemonLogPath,
  authFailedPath,
  claudeHostPath,
  heartbeatPath,
  stopDeferredActivityPath,
  // loop-guard
  daemonGuardActive,
  // reads
  readMarker,
  listReadyMarkers,
  listInProgressMarkers,
  liveMarkerForSession,
  readLastWrap,
  wrapLockHeld,
  wrapLockStale,
  heartbeatFresh,
  isClaudeHost,
  // sentinel
  ensureClaudeHost,
  // transitions
  writeMarker,
  stagePending,
  finalizeReady,
  claimMarker,
  transitionDone,
  transitionGaveUp,
  // reclaim / janitor
  reclaimAbandonedInProgress,
  cleanStalePending,
  // lock
  acquireWrapLock,
  releaseWrapLock,
  readWrapLockOwner,
  clearProvablyStaleWrapLock,
  wrapLockProvablyStale,
  wrapLockProvablyStaleLegacy,
  // heartbeat
  touchHeartbeat,
  removeHeartbeat,
};
