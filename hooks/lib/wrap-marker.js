#!/usr/bin/env node

/**
 * Purpose: Single source of truth for the deferred-`/ds-wrap` per-session marker
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
 *     wrapLockOwnerJsonPath(cwd) -> .agentic/wrap/lock/owner.json
 *     daemonPidPath(cwd) -> .agentic/wrap/daemon.pid
 *     wrapDaemonLogPath(cwd) -> .agentic/wrap/daemon.log
 *     authFailedPath(cwd) -> .agentic/wrap/daemon-auth-failed
 *     claudeHostPath(cwd) -> .agentic/wrap/claude-host
 *     heartbeatPath(cwd, sessionId) -> .agentic/wrap/heartbeats/<sessionId>
 *     stopDeferredActivityPath(cwd) -> .agentic/wrap/deferred-activity.jsonl
 *   Constants:
 *     SCHEMA_VERSION, MAX_DAEMON_LOG_BYTES (2 MB log rotation cap),
 *     MAX_CHILD_CAPTURE_BYTES (256 KB per-run child-output cap),
 *     ABANDON_MS (30 min - heartbeat-backed abandonment),
 *     LEGACY_ABANDON_MS (4 h - pid-blind age fallback),
 *     STUCK_NOTICE_MS (30 min - rollup banner threshold)
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
 *     acquireWrapLock(cwd, owner, staleMs, opts) -> boolean (staleMs is now an INERT
 *       positional slot - see LOCK CLEAR below; opts.role publishes a JSON descriptor)
 *     releaseWrapLock(cwd, token) -> 'absent'|'released'|'refused-not-a-lock'|
 *       'refused-not-owner'|'error' (a STRING, not a boolean - see LOCK CLEAR below;
 *       `if (releaseWrapLock(cwd))` is a correctness hazard, every non-'absent' string
 *       including the refusal strings is truthy)
 *     readWrapLockOwner(cwd) -> { pid, ts } (symlink-guarded: guards both parent lock
 *       dir AND leaf owner against symlinks, no-follow; safe for any caller; LEGACY
 *       2-line-body reader only - does not see a JSON descriptor)
 *     readWrapLockOwnerV2(cwd) -> { source:'json'|'legacy'|null, ... } (schema-validated
 *       JSON descriptor reader with legacy fallback; see LOCK CLEAR below)
 *     makeLockDescriptor({role, pid, token, acquiredAt, sessionId}) -> descriptor object
 *       (the SOLE producer of the JSON descriptor shape; throws TypeError on an invalid
 *       role/pid/token, but NEVER on sessionId - see the LOCK LIVENESS note below)
 *     wrapLockVerdict(cwd) -> { verdict: 'free'|'live'|'dead'|'unknown', ... } (total,
 *       time-independent liveness predicate; see LOCK CLEAR below)
 *     wrapLockAbandoned(cwd, opts) -> boolean (TIME-dependent abandonment predicate,
 *       deliberately SEPARATE from wrapLockVerdict's no-arithmetic invariant; see the
 *       LOCK LIVENESS note below)
 *     clearAbandonedWrapLock(cwd, opts) -> boolean (ACQUIRE-side self-heal; works on
 *       the default config, unlike the daemon-only clearProvablyStaleWrapLock)
 *     clearProvablyStaleWrapLock(cwd, staleMs) -> boolean (daemon-side stale-lock clear)
 *     wrapLockProvablyStale(cwd, staleMs) -> boolean (staleness predicate, NEW path)
 *     wrapLockProvablyStaleLegacy(cwd, staleMs) -> boolean (staleness predicate, OLD path)
 *   Heartbeat:
 *     touchHeartbeat(cwd, sessionId) (NO-OP under guard), removeHeartbeat(cwd, sessionId)
 *
 * Upstream deps: Node built-ins only (fs, path, os). No npm dependencies.
 *                Reads/writes under [cwd]/.agentic/wrap/: pending-<id>.json markers,
 *                last-wrap, lock (directory) + lock/owner, lock/owner.json (+ their
 *                .owner.tmp / .owner.json.tmp atomic-write staging files), daemon.pid,
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
 *                        adapter use - U4), bin/agentic-wrap-acquire-lock (acquireWrapLock,
 *                        wrapLockVerdict, wrapLockPath), bin/agentic-wrap-release-lock
 *                        (releaseWrapLock, readWrapLockOwnerV2, wrapLockPath).
 *
 * Failure modes: Every function is fail-open and NEVER throws to a hook - all fs
 *                errors are swallowed and a safe default is returned (false/null/[]
 *                / no-op). All write transitions are atomic (tmp + rename) so a
 *                crash mid-write never leaves a torn marker. Every transition,
 *                reclaim, janitor, and heartbeat-touch is a guarded NO-OP when
 *                daemonGuardActive() (AGENTIC_WRAP_DAEMON=1) - this is the
 *                loop-guard that prevents the daemon's own headless
 *                `/ds-wrap-deferred` run from re-staging or re-finalizing markers.
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
 *                wrap/lock DIRECTORY (so the headless deferred-`/ds-wrap` child, which runs
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
 *                path), single-sourcing the CWE-59 symlink-guarded owner read. The
 *                symlink + DoS-size guard itself is single-sourced ONE level deeper, in
 *                readGuardedFile, which both readOwnerAt (legacy 2-line body) and
 *                readWrapLockOwnerV2 (JSON descriptor) delegate to - the CWE-59
 *                discipline is never copy-pasted between the two readers.
 *                JSON-DESCRIPTOR PRECEDENCE (U1): clearProvablyStaleWrapLock now refuses
 *                unconditionally when a schema-validated JSON descriptor is present
 *                (lock/owner.json, read via readWrapLockOwnerV2) AND wrapLockVerdict
 *                independently classifies the lock as 'live' - this refusal is checked
 *                BEFORE the legacy owner-based staleness predicate below, so a live
 *                JSON-owned lock can never be cleared by the legacy path. It is a
 *                provable no-op against every pre-U1 fixture, which plants only the
 *                legacy `owner` file and never `owner.json`. wrapLockVerdict is the
 *                new total ('free'|'live'|'dead'|'unknown') liveness predicate: it is
 *                PID-BLIND for a 2-line legacy body (every interactive `/ds-wrap`
 *                writer's PID is a shell that has already exited by the time the owner
 *                file lands) but PID-aware for a 1-line legacy body (the daemon's PID
 *                is a genuinely live long-running process) and for any JSON descriptor
 *                whose role is 'daemon'/'commit' - collapsing that distinction either
 *                steals a live interactive lock or wedges a dead daemon lock forever.
 *                A JSON descriptor with role:'agent' is unconditionally 'live' forever
 *                (there is deliberately no TTL and no `boot` field on the descriptor -
 *                any finite TTL is a lock-steal with extra steps). wrapLockVerdict never
 *                performs an arithmetic time comparison; `ageMs` is computed only after
 *                the verdict is already decided, purely for callers' log messages.
 *                LOCK LIVENESS (DS-106): "role:'agent' is unconditionally live forever"
 *                is exactly why an abandoned interactive lock used to be IMMORTAL -
 *                measured live at 10.3 h, during which 49 context.md writes across 6
 *                sessions were silently discarded. wrapLockAbandoned is the additive
 *                fix: a SEPARATE, time-dependent predicate that never touches any of
 *                wrapLockVerdict's 14 rows nor its no-arithmetic invariant. Its liveness
 *                signal is the descriptor's `session_id` + that session's heartbeat file
 *                (Arm A), NOT a pid - putting a real pid in the agent descriptor would
 *                arm releaseWrapLock's tokenless refuse branch (which keys on
 *                `o.pid !== null`) and make /ds-wrap, which releases WITHOUT a token,
 *                leak a lock on every single run. Arm B is the pid-blind 4 h age
 *                fallback for a descriptor with no session_id, no heartbeat file, or a
 *                legacy 2-line body. `session_id` validation in makeLockDescriptor is
 *                PERMISSIVE (coerce to null, never throw) because that constructor runs
 *                inside acquireWrapLock's try whose catch removes the lock dir and
 *                returns false - a fail-loud validation would make /ds-wrap refuse to
 *                run on every harness that does not export CLAUDE_CODE_SESSION_ID.
 *                clearAbandonedWrapLock is the ACQUIRE-side clear path; the daemon-only
 *                clearProvablyStaleWrapLock is dead on the default config
 *                (`deferred_wrap_daemon: false` never launches the daemon).
 *
 * NOTE: `if (releaseWrapLock(cwd))` is a correctness hazard as of U1 - releaseWrapLock
 *       now returns one of five STRINGS ('absent'|'released'|'refused-not-a-lock'|
 *       'refused-not-owner'|'error'), all of which are truthy including the refusal
 *       strings. Compare against the exact string, e.g. `releaseWrapLock(cwd) ===
 *       'released'`.
 *
 * Performance: standard. Synchronous fs only; no git, no network, no subprocess.
 *              listReadyMarkers / listInProgressMarkers glob one directory
 *              (readdirSync), filter names to the UUID shape, then stat-read at most
 *              MAX_MARKERS_PER_SCAN pending-<uuid>.json files once each.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

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
// Per-run hard cap on the in-memory buffer that captures one headless /ds-wrap-deferred
// child's stdout/stderr before it is flushed to the log. The daemon keeps the stream
// listener attached past the cap (drain-and-discard) so a chatty child cannot wedge
// on a full OS pipe; it just stops growing this buffer. 256 KB is ample for a wrap run.
const MAX_CHILD_CAPTURE_BYTES = 256 * 1024;

// Cap on the lock/owner and lock/owner.json reads. The legacy owner body is at
// most two short lines (a PID and an ISO timestamp); the JSON descriptor is a
// small fixed-shape object. Cap both reads so a giant planted file cannot wedge
// a daemon tick. Mirrors the SEC-M2 stat-then-read discipline. Strict `>` (not
// `>=`): exactly MAX_OWNER_BYTES is read, one byte over is rejected.
const MAX_OWNER_BYTES = 4 * 1024;

// The only valid `role` values for a lock descriptor (see makeLockDescriptor).
const LOCK_DESCRIPTOR_ROLES = ['agent', 'daemon', 'commit'];

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

/**
 * Atomic write (pid-suffixed tmp + rename). Fail-open: returns true on success,
 * false otherwise. The tmp name is suffixed with this process's own pid so two
 * concurrent writers targeting the same targetPath never share one staging
 * path - single-writer atomicity only (see hooks/lib/state-mark.js for the
 * precedent this mirrors).
 */
function atomicWriteJson(targetPath, obj) {
  let tmpPath;
  try {
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    tmpPath = targetPath + '.tmp.' + process.pid;
    fs.writeFileSync(tmpPath, JSON.stringify(obj, null, 2), 'utf8');
    fs.renameSync(tmpPath, targetPath);
    return true;
  } catch (_) {
    // Only unlink OUR OWN pid-suffixed tmp - never a shared/fixed name another
    // concurrent process could own.
    if (tmpPath) {
      try { fs.unlinkSync(tmpPath); } catch (_e) { /* tmp absent or never created */ }
    }
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

/** Path to the schema-validated JSON lock descriptor (see makeLockDescriptor). */
function wrapLockOwnerJsonPath(cwd) {
  return path.join(wrapDir(cwd), 'lock', 'owner.json');
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
 * Return true when a /ds-wrap holds the lock at .agentic/wrap/lock (a DIRECTORY
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
 *     suppression: this session already completed /ds-wrap; .last-wrap may have rolled
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
  // session already completed /ds-wrap; suppress re-staging even if .last-wrap has rolled
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
 * manual-/ds-wrap notice surface). Guarded NO-OP. Fail-open.
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
 * Symlink-guarded, CWE-59-safe, size-bounded file reader. Reads the file at
 * leafPath, guarding against symlinks at BOTH levels: the parent lockPath
 * (a directory - the lock dir itself) AND the leaf file. Returns the raw utf8
 * contents on success, or null on any guard failure, non-file, over-cap size,
 * or fs error. NEVER throws. This is the ONE canonical size/symlink-guarded
 * reader shared by readOwnerAt (legacy 2-line body) and readWrapLockOwnerV2
 * (JSON descriptor) so the CWE-59 + DoS-cap discipline is never copy-pasted.
 *
 * Size check is strict `>`: a file of exactly maxBytes IS read; maxBytes + 1
 * is rejected.
 *
 * @param {string} lockPath - The lock directory path (lstat-checked no-follow).
 * @param {string} leafPath - The file path inside (or under) the lock dir.
 * @param {number} maxBytes - Strict upper bound on the leaf file's size.
 * @returns {string|null}
 */
function readGuardedFile(lockPath, leafPath, maxBytes) {
  try {
    // (1) PARENT guard: if the lock dir itself is a symlink, bail immediately.
    const lockSt = fs.lstatSync(lockPath); // throws if absent -> caught -> null
    if (lockSt.isSymbolicLink()) return null;

    // (2) LEAF guard: if the leaf file is a symlink (or not a regular file), or
    // over the size cap, bail without reading its bytes.
    const st = fs.lstatSync(leafPath); // no-follow; throws ENOENT when absent -> null
    if (st.isSymbolicLink()) return null;
    if (!st.isFile()) return null;
    if (st.size > maxBytes) return null;
    return fs.readFileSync(leafPath, 'utf8');
  } catch (_) {
    return null;
  }
}

/**
 * Construct the SOLE valid shape of a schema-validated JSON lock descriptor.
 * This is the ONE producer of the descriptor object written to
 * lock/owner.json - callers must never hand-build this shape.
 *
 * Validates at construction time (fail LOUD, not silent): an invalid `role`
 * or `pid` would otherwise publish a descriptor that readWrapLockOwnerV2's own
 * validator rejects, silently degrading it to `source:'legacy'` (or `null`)
 * and disabling the daemon-side live-lock protection this design depends on.
 * `acquiredAt` is NOT validated here - it exists solely so a test can backdate
 * a fixture; a garbage `acquiredAt` produces a descriptor that readWrapLockOwnerV2
 * correctly DETECTS as invalid (falls back to legacy/unknown), it does not
 * prevent an invalid descriptor from being constructed.
 *
 * `sessionId` is the ONE field validated PERMISSIVELY rather than fail-loud, and
 * the departure is deliberate (see the module manifest's LOCK LIVENESS note).
 * This constructor is called INSIDE acquireWrapLock's try block, whose catch
 * removes the lock directory and returns false. A throwing session_id validation
 * would therefore convert an unset CLAUDE_CODE_SESSION_ID into an acquisition
 * FAILURE - i.e. /ds-wrap would refuse to run on every harness that does not
 * export that variable. `session_id` is an OPTIONAL liveness hint with a defined
 * safe fallback (the pid-blind age rule in wrapLockAbandoned's Arm B), whereas
 * `role`/`pid`/`token` are correctness-critical. Empty/absent/non-string
 * coerces to null; a non-empty string is trimmed and kept.
 *
 * @param {{role: 'agent'|'daemon'|'commit', pid?: number|null, token?: string|null, acquiredAt?: string|null, sessionId?: string|null}} params
 * @throws {TypeError} on an out-of-enum role, a non-null non-positive-integer pid,
 *   or a non-null non-string (or empty-string) token. NEVER throws on sessionId.
 */
function makeLockDescriptor({ role, pid = null, token = null, acquiredAt = null, sessionId = null } = {}) {
  if (!LOCK_DESCRIPTOR_ROLES.includes(role)) {
    throw new TypeError(
      'makeLockDescriptor: role must be one of ' + LOCK_DESCRIPTOR_ROLES.join('/') + ' (got: ' + role + ')'
    );
  }
  if (pid !== null && !(Number.isInteger(pid) && pid > 0)) {
    throw new TypeError('makeLockDescriptor: pid must be null or a positive integer (got: ' + pid + ')');
  }
  if (token !== null && !(typeof token === 'string' && token.length > 0)) {
    throw new TypeError('makeLockDescriptor: token must be null or a non-empty string (got: ' + JSON.stringify(token) + ')');
  }
  // PERMISSIVE by design - never throws. See the doc block above.
  const session_id = safeSessionId(sessionId);
  return {
    schema_version: 1,
    role,
    pid,
    host: os.hostname(),
    acquired_at: acquiredAt || new Date().toISOString(),
    token,
    session_id,
  };
}

/**
 * Acquire the wrap/lock directory via atomic mkdir (O_EXCL semantics). This is
 * the SOLE exclusion primitive: mkdirSync returns EEXIST for every collision
 * shape (empty dir, symlink-to-dir, dangling symlink, plain file, case-
 * insensitive sibling - empirically verified), so no separate type-check is
 * needed before the attempt. There is NO auto-steal of a "stale" lock here -
 * see the module manifest's LOCK CLEAR discussion; the only path that ever
 * removes another holder's lock is the daemon-side clearProvablyStaleWrapLock.
 *
 * `owner` (when non-null) is written VERBATIM as the legacy 2-line body -
 * existing 3-arg callers (the daemon, agentic-wrap-acquire-lock) depend on
 * this untouched. `opts.role` (when present) additionally publishes a
 * schema-validated JSON descriptor via makeLockDescriptor - opts is fully
 * optional so 3-arg callers keep working unchanged. `staleMs` is retained
 * ONLY as an inert positional slot for signature compatibility; it is never
 * read.
 *
 * Publication is atomic (tmp + rename) and FAIL-CLOSED: if writing the owner
 * body or the JSON descriptor throws after the lock dir was created, the
 * directory is removed (never left as a phantom hold) - but ONLY when it is
 * still, by inode, the exact directory this call created AND no JSON
 * descriptor was ever successfully published (a descriptor on disk means a
 * concurrent reader may already be trusting this lock as live; removing it
 * out from under that reader would be worse than leaving a stale owner file).
 * The inode check is BEST-EFFORT and platform-dependent: Linux commonly
 * reuses a just-freed directory's inode number immediately (observed
 * 200/200 in a same-path rmdir+mkdir repro on ext4/tmpfs/overlay2), while
 * macOS/APFS empirically does not (0/200 in the same repro) - so the inode
 * half provides no protection against a same-path swap on Linux. The
 * !existsSync(ownerJsonPath) half is the only one of the two conditions
 * guaranteed cross-platform, since it never depends on inode reuse.
 *
 * Returns true on acquisition, false otherwise. Fail-open (never throws).
 *
 * @param {string} cwd
 * @param {string|number|null} [owner] - Legacy 2-line body content (verbatim).
 * @param {number} [staleMs] - INERT positional slot; retained for compatibility.
 * @param {{role: 'agent'|'daemon'|'commit', pid?: number|null, token?: string|null, sessionId?: string|null}} [opts]
 */
function acquireWrapLock(cwd, owner, staleMs, opts) {
  const safe = safeCwd(cwd);
  if (!safe) return false;
  const lockDir = wrapLockPath(safe);
  const ownerPath = wrapLockOwnerPath(safe);
  const ownerJsonPath = wrapLockOwnerJsonPath(safe);

  let ownedIno;
  try {
    // Both mkdir calls share one try: mkdirSync(dirname, {recursive:true}) can
    // throw ENOTDIR (a path segment is a file), and that must fail closed too.
    fs.mkdirSync(path.dirname(lockDir), { recursive: true });
    fs.mkdirSync(lockDir); // throws EEXIST if held (or any other collision shape)
    ownedIno = fs.lstatSync(lockDir).ino; // proves-ownership token for the fail-closed path below
  } catch (_) {
    return false; // EEXIST (already held) or any other fs error -> not acquired
  }

  try {
    fs.writeFileSync(ownerPath + '.tmp', String(owner == null ? '' : owner), 'utf8');
    fs.renameSync(ownerPath + '.tmp', ownerPath);

    if (opts && opts.role) {
      const descriptor = makeLockDescriptor(opts);
      fs.writeFileSync(ownerJsonPath + '.tmp', JSON.stringify(descriptor), 'utf8');
      fs.renameSync(ownerJsonPath + '.tmp', ownerJsonPath);
    }
    return true;
  } catch (_) {
    // Publication failed after we created the lock dir. Remove it ONLY if it
    // is still, by inode, the exact directory we created AND no JSON
    // descriptor was ever published (see function doc for the rationale).
    try {
      const stillOurs = fs.lstatSync(lockDir).ino === ownedIno;
      if (stillOurs && !fs.existsSync(ownerJsonPath)) {
        fs.rmSync(lockDir, { recursive: true, force: true });
      }
    } catch (_) { /* best-effort cleanup; still return false below */ }
    return false;
  }
}

/**
 * Release the wrap/lock directory. Symlink-guarded (CWE-59): lstat no-follow
 * at the lock path; a symlink AT the lock path is unlinked (link only, never
 * its target); a non-directory is left alone (refused).
 *
 * Owner-scoped: unlike the old bare rm -rf, this checks who may release.
 *   - A `token` argument matches ONLY against a published JSON descriptor's
 *     own non-null token; any other case with a token supplied is refused.
 *   - Without a token, a JSON descriptor whose pid is ALIVE and is NOT this
 *     process is refused (a live daemon/commit-role lock cannot be tokenlessly
 *     released by a different process). Two carve-outs are load-bearing:
 *     `pid === process.pid` lets a daemon release its own lock tokenlessly,
 *     and a `pid: null` (role:'agent') descriptor stays tokenless-releasable
 *     because the interactive /ds-wrap releases from a DIFFERENT process than
 *     the one that acquired it.
 *   - A legacy-owner-only lock (no JSON descriptor) is ALWAYS releasable -
 *     the documented path for interactive holders.
 *
 * Returns one of five strings (never a boolean - see the module manifest for
 * why `if (releaseWrapLock(cwd))` is now a correctness hazard):
 *   'absent'              - no lock present (nothing to do)
 *   'released'            - lock existed and was removed
 *   'refused-not-a-lock'  - lock path is a symlink or non-directory (untouched
 *                           except a planted symlink, which is unlinked)
 *   'refused-not-owner'   - token mismatch, or a live foreign-process owner
 *   'error'               - safeCwd rejection, or rmSync genuinely failed
 *
 * @param {string} cwd
 * @param {string} [token] - Must match a published descriptor's token exactly.
 */
function releaseWrapLock(cwd, token) {
  const safe = safeCwd(cwd);
  if (!safe) return 'error';
  const lockDir = wrapLockPath(safe);

  let st;
  try {
    st = fs.lstatSync(lockDir); // no-follow; ENOENT -> caught -> 'absent'
  } catch (_) {
    return 'absent';
  }
  if (st.isSymbolicLink()) {
    // A symlink AT wrap/lock is a hostile artifact, not our lock. Unlink
    // removes ONLY the link (never follows it / touches the target).
    try { fs.unlinkSync(lockDir); } catch (_) {}
    return 'refused-not-a-lock';
  }
  if (!st.isDirectory()) {
    return 'refused-not-a-lock'; // a plain file is not our (mkdir-created) lock; leave it
  }

  const hasToken = (typeof token === 'string' && token.length > 0);
  const o = readWrapLockOwnerV2(safe);

  if (hasToken) {
    if (!(o.source === 'json' && o.token !== null && o.token === token)) {
      return 'refused-not-owner';
    }
  } else if (o.source === 'json' && o.pid !== null && !pidIsDead(o.pid) && o.pid !== process.pid) {
    return 'refused-not-owner';
  }

  try {
    fs.rmSync(lockDir, { recursive: true, force: true });
    return 'released';
  } catch (_) {
    return 'error';
  }
}

// ---------------------------------------------------------------------------
// Shared lock-staleness helpers (single-sourced, CWE-59 symlink-guarded)
// ---------------------------------------------------------------------------

/**
 * Symlink-guarded, CWE-59-safe owner-file reader. Reads the two-line legacy
 * owner body at ownerPath under lockPath. Returns { pid, ts } on success,
 * { pid: null, ts: null } on any guard or error. This is the ONE canonical
 * legacy reader used by readWrapLockOwner, readWrapLockOwnerV2 (legacy
 * fallback), wrapLockProvablyStale, and wrapLockProvablyStaleLegacy so
 * symlink protection is never copy-pasted. Delegates the symlink/size guard
 * to readGuardedFile.
 *
 * @param {string} lockPath - The lock directory path (lstat-checked no-follow).
 * @param {string} ownerPath - The owner file path inside the lock dir.
 */
function readOwnerAt(lockPath, ownerPath) {
  const empty = { pid: null, ts: null };
  const raw = readGuardedFile(lockPath, ownerPath, MAX_OWNER_BYTES);
  if (raw === null) return empty;
  try {
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
 * Compute age in milliseconds from an ISO8601 timestamp string, purely for
 * callers' diagnostic/log messages. Returns null when ts is null or
 * unparseable. NEVER used to drive a verdict decision (see wrapLockVerdict,
 * which computes this only AFTER its verdict is already decided).
 *
 * @param {string|null} ts
 */
function ageMsFromTs(ts) {
  if (ts === null) return null;
  const tms = tsMs(ts);
  return (tms !== null) ? (Date.now() - tms) : null;
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
 * (PID + ISO timestamp, written by the interactive `/ds-wrap`), 1-line (PID-only,
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
 * Read the wrap/lock owner, preferring a SCHEMA-VALIDATED JSON descriptor
 * (lock/owner.json) over the legacy 2-line body (lock/owner). Unlike a bare
 * JSON.parse-succeeded check, EVERY field is validated before the result is
 * trusted as `source:'json'` - a descriptor that parses but fails validation
 * silently degrades to the legacy reader (and then to `source:null`), which
 * is exactly the fallback path a stale/corrupt/tampered descriptor should
 * take. This validation is load-bearing, not hygiene: it is what lets
 * wrapLockVerdict and clearProvablyStaleWrapLock trust `source:'json'` as an
 * unconditional signal.
 *
 * Returns one of:
 *   { source: 'json', role, pid, host, acquired_at, token, session_id }
 *   { source: 'legacy', pid, ts }
 *   { source: null }
 *
 * WRITER/READER-TOGETHER CONSTRAINT (do not split): `session_id` MUST appear in
 * the returned shape whenever makeLockDescriptor writes it. If the writer adds
 * the field and this reader's returned object does not carry it, the value is
 * silently dropped, wrapLockAbandoned sees `undefined`, and Arm A is inert with
 * NO error anywhere - a silent degradation in exactly the class this reader's
 * validation exists to prevent. `session_id` is validated ADDITIVELY-OPTIONAL:
 * a pre-upgrade descriptor with no `session_id` key still validates (and yields
 * null), so an old descriptor is never rejected into the legacy fallback.
 *
 * @param {string} cwd
 */
function readWrapLockOwnerV2(cwd) {
  const lockPath = wrapLockPath(cwd);
  const jsonRaw = readGuardedFile(lockPath, wrapLockOwnerJsonPath(cwd), MAX_OWNER_BYTES);
  if (jsonRaw !== null) {
    let d = null;
    try {
      d = JSON.parse(jsonRaw);
    } catch (_) {
      d = null;
    }
    const valid = d
      && typeof d === 'object'
      && !Array.isArray(d)
      && d.schema_version === 1
      && LOCK_DESCRIPTOR_ROLES.includes(d.role)
      && (d.pid === null || (Number.isInteger(d.pid) && d.pid > 0))
      && typeof d.host === 'string' && d.host.length > 0
      && typeof d.acquired_at === 'string' && tsMs(d.acquired_at) !== null
      && (d.token === null || (typeof d.token === 'string' && d.token.length > 0))
      // Additive-optional: absent (pre-upgrade descriptor) and null both pass.
      && (d.session_id === undefined || d.session_id === null
          || (typeof d.session_id === 'string' && d.session_id.length > 0));
    if (valid) {
      return {
        source: 'json',
        role: d.role,
        pid: d.pid,
        host: d.host,
        acquired_at: d.acquired_at,
        token: d.token,
        session_id: safeSessionId(d.session_id),
      };
    }
    // Falls through to the legacy reader below - an invalid/corrupt JSON
    // descriptor must NOT be trusted, but a legacy owner file may still exist.
  }
  const o = readOwnerAt(lockPath, wrapLockOwnerPath(cwd));
  if (o.pid !== null || o.ts !== null) return { source: 'legacy', pid: o.pid, ts: o.ts };
  return { source: null };
}

/**
 * Total liveness predicate for the wrap/lock directory. Returns exactly one
 * of 'free' | 'live' | 'dead' | 'unknown' (never anything else, never throws).
 *
 * MANDATORY invariant: no branch below performs an arithmetic comparison -
 * `>`, `<`, and `Date.now()` do not appear in this function. `ageMs` is
 * computed via ageMsFromTs ONLY after the verdict is already decided, purely
 * for callers' log messages; it never influences the decision. This is what
 * makes the predicate total and time-independent: an undefined comparison
 * cannot exist where no comparison exists.
 *
 * Decision table (see U1 brief for the full row-by-row rationale):
 *   1. safeCwd(cwd) === null                                    -> unknown
 *   2. lstat(lock) throws (absent)                               -> free
 *   3. lstat(lock).isSymbolicLink()                               -> unknown
 *   4. !lstat(lock).isDirectory()                                 -> unknown
 *   5. source === null                                            -> unknown
 *   6. legacy, pid!==null, ts!==null, tsMs(ts)!==null (2-line,
 *      interactive - PID-BLIND: liveness never checked)           -> live
 *   7. legacy, pid!==null, ts===null (1-line, daemon body)         -> pidIsDead(pid) ? dead : live
 *   8. legacy, pid===null, ts!==null, tsMs(ts)!==null              -> live
 *   9. legacy, ts non-null with tsMs(ts)===null (garbled)          -> unknown
 *  10. json, role==='agent'                                       -> live (unconditional, forever)
 *  11. json, role in {daemon,commit}, host !== os.hostname()       -> unknown
 *  12. json, role in {daemon,commit}, host matches, pid===null     -> unknown
 *  13. json, role in {daemon,commit}, host matches, pidIsDead(pid) -> dead
 *  14. otherwise (json, process role, host match, live pid)        -> live
 *
 * Rows 6/7 are NOT the same rule: every interactive `/ds-wrap` writer's owner
 * PID is a shell that has already exited by the time the owner file lands, so
 * for a 2-line body liveness must be PID-BLIND (age is the only signal). The
 * daemon's 1-line body's PID is a genuinely live long-running process, so
 * there liveness is both meaningful and required. Collapsing these either
 * steals a live interactive lock or wedges a dead daemon lock forever.
 *
 * @param {string} cwd
 * @returns {{verdict: 'free'|'live'|'dead'|'unknown', source: 'json'|'legacy'|null, role: string|null, pid: number|null, ts: string|null, ageMs: number|null}}
 */
function wrapLockVerdict(cwd) {
  try {
    const safe = safeCwd(cwd);
    if (!safe) return { verdict: 'unknown', source: null, role: null, pid: null, ts: null, ageMs: null };

    const lockPath = wrapLockPath(safe);
    let st;
    try {
      st = fs.lstatSync(lockPath); // no-follow; ENOENT -> caught -> 'free'
    } catch (_) {
      return { verdict: 'free', source: null, role: null, pid: null, ts: null, ageMs: null };
    }
    if (st.isSymbolicLink() || !st.isDirectory()) {
      return { verdict: 'unknown', source: null, role: null, pid: null, ts: null, ageMs: null };
    }

    const o = readWrapLockOwnerV2(safe);
    let verdict = 'unknown';
    let role = null;
    let pid = null;
    let ts = null;

    if (o.source === 'legacy') {
      pid = o.pid;
      ts = o.ts;
      if (pid !== null && ts !== null) {
        verdict = (tsMs(ts) !== null) ? 'live' : 'unknown';        // rows 6 / 9 (pid-blind)
      } else if (pid !== null) { // ts === null
        verdict = pidIsDead(pid) ? 'dead' : 'live';                 // row 7
      } else if (ts !== null) { // pid === null
        verdict = (tsMs(ts) !== null) ? 'live' : 'unknown';        // rows 8 / 9
      }
      // pid === null && ts === null is unreachable here: readWrapLockOwnerV2
      // would have returned source:null in that case (handled by row 5 above).
    } else if (o.source === 'json') {
      role = o.role;
      pid = o.pid;
      ts = o.acquired_at;
      if (role === 'agent') {
        verdict = 'live';                                          // row 10 (unconditional)
      } else if (o.host !== os.hostname()) {
        verdict = 'unknown';                                       // row 11
      } else if (pid === null) {
        verdict = 'unknown';                                       // row 12
      } else if (pidIsDead(pid)) {
        verdict = 'dead';                                          // row 13
      } else {
        verdict = 'live';                                          // row 14
      }
    }
    // o.source === null falls through with verdict still 'unknown' (row 5).

    return { verdict, source: o.source, role, pid, ts, ageMs: ageMsFromTs(ts) };
  } catch (_) {
    return { verdict: 'unknown', source: null, role: null, pid: null, ts: null, ageMs: null };
  }
}

/**
 * Clear a PROVABLY-stale wrap.lock DIRECTORY (the headless deferred-`/ds-wrap` child
 * runs with Bash removed and cannot `rm` it; the trusted daemon clears it instead).
 * Returns true IFF a real stale lock directory was removed; false otherwise. Never
 * throws (fail-open).
 *
 * Stale predicate (exact): CLEAR iff
 *   (owner.pid !== null && pidIsDead(owner.pid))                                 -- dead owner PID
 *   OR (owner.pid === null && owner.ts !== null && tsMs(owner.ts) !== null
 *       && the elapsed time since tsMs(owner.ts) exceeds staleMs)                -- no PID + old timestamp
 * An ALIVE pid is authoritative-LIVE -> KEEP regardless of timestamp age (this is the
 * live-lock corruption guard: liveness, not age, drives the clear). No usable owner
 * signal (no PID and no parseable timestamp) -> KEEP, covering the interactive `/ds-wrap`
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
    // JSON-descriptor precedence refusal: when a schema-validated descriptor is
    // present and wrapLockVerdict independently classifies it as 'live', refuse
    // unconditionally - the legacy owner-based staleness predicate below must
    // never override a live JSON-owned lock. Gated on source==='json', so this
    // is a provable no-op on every existing fixture (they plant only the
    // legacy `owner` file, never `owner.json`).
    const v2 = readWrapLockOwnerV2(cwd);
    if (v2.source === 'json' && wrapLockVerdict(cwd).verdict === 'live') return false;
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
// Abandoned-lock detection (D1)
// ---------------------------------------------------------------------------

/**
 * Age past which a role:'agent' lock whose session has STOPPED heartbeating is
 * considered abandoned. Mirrors session-start-wrap.sh's STALE_MS.
 */
const ABANDON_MS = 30 * 60 * 1000;

/**
 * Age past which a PID-BLIND lock carrying NO usable liveness signal at all
 * (no session_id, or a session_id with no heartbeat file) is considered
 * abandoned. Deliberately far above any plausible /ds-wrap run, and well below
 * the 10.3h orphan this fix exists to prevent.
 */
const LEGACY_ABANDON_MS = 4 * 60 * 60 * 1000;

/** Age past which the rollup composer emits a WRAP-LOCK-STUCK banner. */
const STUCK_NOTICE_MS = ABANDON_MS;

/**
 * Decide whether the wrap/lock is ABANDONED - i.e. its holder is gone and no
 * process or session will ever release it. This is the D1 fix: wrapLockVerdict
 * returns 'live' UNCONDITIONALLY for role:'agent' (row 10) because such a
 * descriptor carries `pid: null` by construction, so there is no process to
 * liveness-check and the verdict can never go stale. Without this predicate an
 * abandoned interactive lock is IMMORTAL - measured live at 10.3 hours, during
 * which 49 context.md writes across 6 sessions were silently discarded.
 *
 * DELIBERATELY NOT PART OF wrapLockVerdict. That function carries a MANDATORY
 * no-arithmetic invariant (see its doc block): no `>`, `<`, or `Date.now()`
 * appears in it, which is what makes it total and time-independent. Abandonment
 * is inherently a time comparison, so it lives here instead - a separate,
 * additive predicate that never changes any of wrapLockVerdict's 14 rows.
 *
 * Two arms:
 *
 *   Arm A (session heartbeat) - requires a role:'agent' JSON descriptor with a
 *     non-null `session_id` AND an EXISTING heartbeat file for that session.
 *     ABANDONED iff the heartbeat is stale beyond `abandonMs` AND the lock has
 *     itself been held longer than `abandonMs` (the second conjunct protects a
 *     single long turn that has not yet emitted its next heartbeat).
 *
 *   Arm B (pid-blind age) - the fallback whenever Arm A cannot apply: no
 *     descriptor, no session_id, or a session_id with NO heartbeat file. Also
 *     covers the legacy 2-line owner body (row 6, pid-blind 'live'). ABANDONED
 *     iff the lock is older than `legacyAbandonMs`.
 *
 * FAIL-SAFE in both directions. Arm A requires the heartbeat file to EXIST, so
 * any adapter that never writes one (or any pre-upgrade descriptor) degrades to
 * Arm B's much more conservative 4h rule rather than stealing a live lock. A
 * dead-pid daemon/commit lock is NOT this function's business - wrapLockVerdict
 * already classifies it 'dead' and clearProvablyStaleWrapLock removes it.
 *
 * Fail-open: false (never throws, never wrongly reports abandonment).
 *
 * @param {string} cwd
 * @param {{abandonMs?: number, legacyAbandonMs?: number}} [opts]
 * @returns {boolean}
 */
function wrapLockAbandoned(cwd, opts) {
  try {
    const o = opts || {};
    const abandonMs = (typeof o.abandonMs === 'number' && o.abandonMs >= 0) ? o.abandonMs : ABANDON_MS;
    const legacyAbandonMs = (typeof o.legacyAbandonMs === 'number' && o.legacyAbandonMs >= 0)
      ? o.legacyAbandonMs
      : LEGACY_ABANDON_MS;

    const safe = safeCwd(cwd);
    if (!safe) return false;

    // Only a confirmed real lock DIRECTORY can be abandoned. A symlink or a
    // plain file at the lock path is a hostile/foreign artifact - refuse.
    let st;
    try { st = fs.lstatSync(wrapLockPath(safe)); } catch (_) { return false; }
    if (st.isSymbolicLink() || !st.isDirectory()) return false;

    const owner = readWrapLockOwnerV2(safe);

    if (owner.source === 'json') {
      // daemon/commit descriptors carry a real pid; liveness (not age) governs
      // them and wrapLockVerdict already decides it. Never age them out here.
      if (owner.role !== 'agent') return false;

      const ageMs = ageMsFromTs(owner.acquired_at);
      if (ageMs === null) return false; // unparseable timestamp -> no signal -> KEEP

      const sid = safeSessionId(owner.session_id);
      if (sid) {
        const hbPath = heartbeatPath(safe, sid);
        let hbExists = false;
        try { hbExists = !!hbPath && fs.existsSync(hbPath); } catch (_) { hbExists = false; }
        if (hbExists) {
          // Arm A. A fresh heartbeat is authoritative-LIVE regardless of age.
          if (heartbeatFresh(safe, sid, abandonMs)) return false;      // row A1
          return ageMs > abandonMs;                                     // rows A2 / A3
        }
        // row A4: session_id present but no heartbeat file -> Arm B.
      }
      // row A5: no session_id (pre-upgrade descriptor / adapter without the
      // env var) -> Arm B.
      return ageMs > legacyAbandonMs;
    }

    if (owner.source === 'legacy') {
      // Row L1 (2-line interactive body): pid-blind, so age is the only signal.
      // Row L2 (1-line daemon body, ts === null) is pid-checkable and belongs to
      // clearProvablyStaleWrapLock, not here.
      if (owner.ts === null) return false;
      const ageMs = ageMsFromTs(owner.ts);
      if (ageMs === null) return false; // row L3: garbled ts -> KEEP
      return ageMs > legacyAbandonMs;
    }

    // source === null: no usable owner signal at all. This is the
    // mkdir-before-owner race window an interactive /ds-wrap passes through -
    // KEEP (row L3 semantics).
    return false;
  } catch (_) {
    return false; // fail-open: never wrongly report abandonment
  }
}

/**
 * Remove an ABANDONED wrap/lock directory. Returns true IFF a real abandoned
 * lock directory was removed; false otherwise. Never throws (fail-open).
 *
 * This is the ACQUIRE-SIDE self-heal that makes the fix work on the DEFAULT
 * config. Its sibling clearProvablyStaleWrapLock is only ever called from
 * wrap-daemon.js, which `deferred_wrap_daemon: false` (the default) never
 * launches - so on a default install NOTHING could clear an abandoned lock.
 * That is why this is a parallel path rather than a rewiring of the daemon's
 * crash-backstop semantics.
 *
 * SECURITY (CWE-59): mirrors clearProvablyStaleWrapLock's symlink discipline -
 * lstat no-follow, a symlink AT the lock path is unlinked (link only, never its
 * target) and reported as NOT a clear, a plain file is left alone.
 *
 * @param {string} cwd
 * @param {{abandonMs?: number, legacyAbandonMs?: number}} [opts]
 * @returns {boolean}
 */
function clearAbandonedWrapLock(cwd, opts) {
  try {
    const safe = safeCwd(cwd);
    if (!safe) return false;
    const lockPath = wrapLockPath(safe);

    let st;
    try { st = fs.lstatSync(lockPath); } catch (_) { return false; }
    if (st.isSymbolicLink()) {
      try { fs.unlinkSync(lockPath); } catch (_) {}
      return false; // removed a hostile artifact, not a real lock
    }
    if (!st.isDirectory()) return false;

    if (!wrapLockAbandoned(safe, opts)) return false;

    fs.rmSync(lockPath, { recursive: true, force: true });
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
  MAX_DAEMON_LOG_BYTES,
  MAX_CHILD_CAPTURE_BYTES,
  ABANDON_MS,
  LEGACY_ABANDON_MS,
  STUCK_NOTICE_MS,
  // paths
  markerPath,
  lastWrapPath,
  wrapLockPath,
  wrapLockOwnerPath,
  wrapLockOwnerJsonPath,
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
  readWrapLockOwnerV2,
  makeLockDescriptor,
  wrapLockVerdict,
  wrapLockAbandoned,
  clearAbandonedWrapLock,
  clearProvablyStaleWrapLock,
  wrapLockProvablyStale,
  wrapLockProvablyStaleLegacy,
  // heartbeat
  touchHeartbeat,
  removeHeartbeat,
};
