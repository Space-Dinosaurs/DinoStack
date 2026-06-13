#!/usr/bin/env node

/**
 * Purpose: Single source of truth for the deferred-`/wrap` per-session marker
 *          state machine and its companion on-disk artifacts (last-wrap sentinel,
 *          wrap.lock directory lock, daemon pid, auth-failed notice, .claude-host
 *          sentinel, heartbeats). Owns every read, transition, reclaim, janitor,
 *          lock, and heartbeat operation so that the Stop hook, the SessionEnd
 *          hook, and the wrap daemon all share one atomic, fail-open
 *          implementation. The single correctness invariant lives here: a
 *          `pending` marker becomes `ready` ONLY via finalizeReady on a genuine
 *          terminal SessionEnd - there is NO stale-sweep (CRITICAL-A).
 *
 * Public API (CommonJS, all exported on module.exports):
 *   Paths:
 *     markerPath(cwd, sessionId) -> .agentic/wrap-pending-<sessionId>.json
 *     lastWrapPath(cwd), wrapLockPath(cwd), wrapLockOwnerPath(cwd),
 *     daemonPidPath(cwd), authFailedPath(cwd), claudeHostPath(cwd),
 *     heartbeatPath(cwd, sessionId)
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
 *   Heartbeat:
 *     touchHeartbeat(cwd, sessionId) (NO-OP under guard), removeHeartbeat(cwd, sessionId)
 *
 * Upstream deps: Node built-ins only (fs, path). No npm dependencies.
 *                Reads/writes under [cwd]/.agentic/: wrap-pending-<id>.json markers,
 *                .last-wrap, wrap.lock (directory) + wrap.lock/owner, wrap-daemon.pid,
 *                wrap-daemon-auth-failed, .claude-host, .heartbeats/<id>.
 *
 * Downstream consumers: hooks/stop-context.js (require this lib; stagePending,
 *                        touchHeartbeat, lock-aware reads), hooks/session-end-wrap.js
 *                        (finalizeReady, removeHeartbeat - U2), hooks/wrap-daemon.js
 *                        (listReadyMarkers, claimMarker, reclaimAbandonedInProgress,
 *                        cleanStalePending, acquireWrapLock, transitionDone/GaveUp - U3),
 *                        hooks/session-start-wrap.sh (ensureClaudeHost via node - U4).
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
 *                pending markers (never status-mutates them), so it likewise cannot
 *                promote a live session.
 *
 * Performance: standard. Synchronous fs only; no git, no network, no subprocess.
 *              listReadyMarkers / listInProgressMarkers glob one directory
 *              (readdirSync) and stat-read each wrap-pending-*.json once.
 */

'use strict';

const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SCHEMA_VERSION = 3;
const MARKER_PREFIX = 'wrap-pending-';
const MARKER_SUFFIX = '.json';
// Default heartbeat freshness window (ms) - a heartbeat younger than this means
// the session is still emitting turns and a ready marker should be deferred.
const DEFAULT_HEARTBEAT_FRESH_MS = 120 * 1000;
const MAX_ATTEMPTS = 3;

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

/** Read + parse a marker file by absolute path. Fail-open: null on any error. */
function readMarkerFile(absPath) {
  try {
    if (!fs.existsSync(absPath)) return null;
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
  return path.join(agenticDir(cwd), MARKER_PREFIX + sid + MARKER_SUFFIX);
}

function lastWrapPath(cwd) {
  return path.join(agenticDir(cwd), '.last-wrap');
}

function wrapLockPath(cwd) {
  return path.join(agenticDir(cwd), 'wrap.lock');
}

function wrapLockOwnerPath(cwd) {
  return path.join(agenticDir(cwd), 'wrap.lock', 'owner');
}

function daemonPidPath(cwd) {
  return path.join(agenticDir(cwd), 'wrap-daemon.pid');
}

function authFailedPath(cwd) {
  return path.join(agenticDir(cwd), 'wrap-daemon-auth-failed');
}

function claudeHostPath(cwd) {
  return path.join(agenticDir(cwd), '.claude-host');
}

function heartbeatPath(cwd, sessionId) {
  const sid = safeSessionId(sessionId);
  if (!sid) return null;
  return path.join(agenticDir(cwd), '.heartbeats', sid);
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
 * List every wrap-pending-*.json marker in status `ready`, sorted by staged_at
 * ascending (FIFO). Each entry is { sessionId, path, marker }. Fail-open: [].
 */
function listReadyMarkers(cwd) {
  return listMarkersByStatus(cwd, 'ready');
}

/** List every wrap-pending-*.json marker in status `in_progress`. Fail-open: []. */
function listInProgressMarkers(cwd) {
  return listMarkersByStatus(cwd, 'in_progress');
}

/** Shared scanner for listReadyMarkers / listInProgressMarkers. */
function listMarkersByStatus(cwd, wantStatus) {
  const out = [];
  try {
    const dir = agenticDir(cwd);
    let names;
    try {
      names = fs.readdirSync(dir);
    } catch (_) {
      return out; // .agentic/ absent -> no markers
    }
    for (const name of names) {
      if (!name.startsWith(MARKER_PREFIX) || !name.endsWith(MARKER_SUFFIX)) continue;
      const sessionId = name.slice(MARKER_PREFIX.length, name.length - MARKER_SUFFIX.length);
      if (!sessionId) continue;
      const abs = path.join(dir, name);
      const marker = readMarkerFile(abs);
      if (!marker || marker.status !== wantStatus) continue;
      out.push({ sessionId, path: abs, marker });
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
 * Return true when a /wrap holds the lock at .agentic/wrap.lock (a DIRECTORY
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
 * Create the .agentic/.claude-host sentinel if absent (create-if-absent via the
 * 'wx' flag). Intentionally UNGUARDED: writing a true fact is harmless and this
 * self-heals existing installs that never re-ran install.sh (MAJOR-B). Idempotent;
 * swallows EEXIST and every other fs error.
 */
function ensureClaudeHost(cwd) {
  try {
    const dir = agenticDir(cwd);
    fs.mkdirSync(dir, { recursive: true });
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
 * Mark this session's marker `done`, then unlink both the marker and the
 * session's heartbeat. Guarded NO-OP. Fail-open.
 */
function transitionDone(cwd, sessionId) {
  if (daemonGuardActive()) return false;
  const safe = safeCwd(cwd);
  if (!safe) return false;
  const sid = safeSessionId(sessionId);
  if (!sid) return false;

  const p = markerPath(safe, sid);
  if (!p) return false;
  // Best-effort: write `done` (records the terminal status before unlink), then
  // unlink the marker and heartbeat. A crash between the two still leaves a
  // `done` marker, which is harmless (no consumer acts on `done`).
  const existing = readMarker(safe, sid) || { session_id: sid, project_root: safe };
  const marker = Object.assign({}, existing, {
    schema_version: SCHEMA_VERSION,
    session_id: sid,
    status: 'done',
  });
  atomicWriteJson(p, marker);
  try { fs.unlinkSync(p); } catch (_) {}
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
 * than ttlMs. DELETE-ONLY - it NEVER status-mutates a pending marker, so it
 * cannot promote a live/idle session (CRITICAL-A). Touches ONLY pending markers.
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
  // paths
  markerPath,
  lastWrapPath,
  wrapLockPath,
  wrapLockOwnerPath,
  daemonPidPath,
  authFailedPath,
  claudeHostPath,
  heartbeatPath,
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
  // heartbeat
  touchHeartbeat,
  removeHeartbeat,
};
