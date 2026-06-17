#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/wrap-marker.js - the deferred-`/wrap` marker state
 * machine, reclaim, janitor, lock, sentinel and per-session isolation.
 *
 * Covers architect-plan verification-gate cases at the LIB level:
 *   (19) reclaimAbandonedInProgress resets ONLY daemon-claimed + dead-PID + stale
 *        in_progress -> ready; does NOT touch session-claimed / live-PID / fresh /
 *        any pending; moves to gave_up at attempts >= 3 (MAJOR-C).
 *   (5 / MAJOR-3) finalizeReady no-downgrade + stagePending suppresses on
 *        ready/pending/in_progress (the late-finalize / late-stage regress guard
 *        at the lib level).
 *   (3 / CRITICAL-A) cleanStalePending is DELETE-ONLY (deletes old pending, never
 *        status-mutates) - it can never promote a live/idle session to ready.
 *   (6) liveMarkerForSession semantics.
 *   (18) per-session marker isolation (two sessions' markers never collide).
 *   (13 portion) loop-guard (AGENTIC_WRAP_DAEMON=1) no-ops every transition.
 *   (20 portion) ensureClaudeHost is UNGUARDED (writes even under the guard).
 *
 * This file exercises the lib directly (require) - no child process, no `claude`
 * CLI, no network. Fake project dirs under the OS tmpdir are realpath'd so the
 * lib's safeCwd (`path.resolve(cwd) === cwd`) accepts them on platforms where
 * tmpdir is a symlink (macOS /tmp -> /private/tmp).
 *
 * Run with: node hooks/tests/test-wrap-marker-reclaim.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const lib = require('../lib/wrap-marker.js');

// ---------------------------------------------------------------------------
// Harness (matches test-stop-context-deferred-wrap.js conventions)
// ---------------------------------------------------------------------------

let passed = 0;
let failed = 0;

function assert(condition, message) {
  if (condition) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message}`);
    failed++;
  }
}

// realpath so safeCwd (path.resolve(cwd) === cwd) accepts the dir on macOS.
function makeProject(prefix) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  const projectDir = path.join(base, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  return { base, projectDir, agenticDir };
}

function cleanup(base) {
  try { fs.rmSync(base, { recursive: true, force: true }); } catch (_) {}
}

// Build + write a marker directly to disk (bypassing the guarded transitions so a
// test can set up arbitrary fixture state regardless of the loop-guard).
function writeMarkerRaw(agenticDir, sessionId, overrides) {
  const marker = Object.assign({
    schema_version: 3,
    session_id: sessionId,
    staged_at: new Date().toISOString(),
    status: 'pending',
    claimed_by: null,
    claimed_kind: null,
    claimed_at: null,
    attempts: 0,
    project_root: path.dirname(agenticDir),
    last_error: null,
  }, overrides || {});
  fs.writeFileSync(
    path.join(agenticDir, 'wrap-pending-' + sessionId + '.json'),
    JSON.stringify(marker, null, 2),
    'utf8'
  );
  return marker;
}

function readRaw(agenticDir, sessionId) {
  const p = path.join(agenticDir, 'wrap-pending-' + sessionId + '.json');
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return null; }
}

function markerExists(agenticDir, sessionId) {
  return fs.existsSync(path.join(agenticDir, 'wrap-pending-' + sessionId + '.json'));
}

// A timestamp `seconds` in the past, ISO8601.
function agoIso(seconds) {
  return new Date(Date.now() - seconds * 1000).toISOString();
}

// A PID that is (essentially certainly) dead. PID 1 is alive; a huge PID is dead.
const DEAD_PID = 2147480000; // ~2^31, no such process -> ESRCH
const LIVE_PID = process.pid; // this test process - definitely alive

// Make sure the loop-guard is OFF for the bulk of the suite.
delete process.env.AGENTIC_WRAP_DAEMON;

// ---------------------------------------------------------------------------
// (19 / MAJOR-C) reclaimAbandonedInProgress
// ---------------------------------------------------------------------------
console.log('\n[19] reclaimAbandonedInProgress: daemon-claimed + dead-PID + stale only');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-reclaim-');
  const STALE_MS = 30 * 60 * 1000; // 30 min

  // (A) ELIGIBLE: daemon-claimed, dead PID, stale claimed_at, attempts < 3 -> ready.
  writeMarkerRaw(agenticDir, 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', {
    status: 'in_progress', claimed_kind: 'daemon', claimed_by: DEAD_PID,
    claimed_at: agoIso(40 * 60), attempts: 1,
  });
  // (B) INELIGIBLE: session-claimed (not daemon) -> untouched.
  writeMarkerRaw(agenticDir, 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', {
    status: 'in_progress', claimed_kind: 'session', claimed_by: DEAD_PID,
    claimed_at: agoIso(40 * 60), attempts: 1,
  });
  // (C) INELIGIBLE: daemon-claimed but PID alive -> untouched.
  writeMarkerRaw(agenticDir, 'cccccccc-cccc-cccc-cccc-cccccccccccc', {
    status: 'in_progress', claimed_kind: 'daemon', claimed_by: LIVE_PID,
    claimed_at: agoIso(40 * 60), attempts: 1,
  });
  // (D) INELIGIBLE: daemon-claimed, dead PID, but FRESH claimed_at -> untouched.
  writeMarkerRaw(agenticDir, 'dddddddd-dddd-dddd-dddd-dddddddddddd', {
    status: 'in_progress', claimed_kind: 'daemon', claimed_by: DEAD_PID,
    claimed_at: agoIso(10), attempts: 1,
  });
  // (E) INELIGIBLE: pending (never in_progress) -> NEVER touched (CRITICAL-A).
  writeMarkerRaw(agenticDir, 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', {
    status: 'pending', claimed_kind: null, claimed_by: null,
    claimed_at: null, attempts: 0, staged_at: agoIso(40 * 60),
  });
  // (F) ELIGIBLE but EXHAUSTED: attempts >= 3 -> gave_up (not ready).
  writeMarkerRaw(agenticDir, 'ffffffff-ffff-ffff-ffff-ffffffffffff', {
    status: 'in_progress', claimed_kind: 'daemon', claimed_by: DEAD_PID,
    claimed_at: agoIso(40 * 60), attempts: 3,
  });

  const res = lib.reclaimAbandonedInProgress(projectDir, STALE_MS);

  assert(res && Array.isArray(res.reclaimed) && Array.isArray(res.gaveUp),
    'reclaim returns { reclaimed:[], gaveUp:[] }');
  assert(res.reclaimed.includes('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'),
    'eligible daemon/dead/stale marker reported as reclaimed');
  assert(readRaw(agenticDir, 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa').status === 'ready',
    'eligible marker reset in_progress -> ready');
  const a = readRaw(agenticDir, 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');
  assert(a.claimed_by === null && a.claimed_kind === null && a.claimed_at === null,
    'reclaimed marker clears claim fields');
  assert(a.attempts === 1, 'reclaimed marker preserves bumped attempts (1)');

  assert(readRaw(agenticDir, 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb').status === 'in_progress',
    'session-claimed marker NOT touched');
  assert(readRaw(agenticDir, 'cccccccc-cccc-cccc-cccc-cccccccccccc').status === 'in_progress',
    'daemon-claimed but live-PID marker NOT touched');
  assert(readRaw(agenticDir, 'dddddddd-dddd-dddd-dddd-dddddddddddd').status === 'in_progress',
    'fresh (not-yet-stale) daemon marker NOT touched');
  assert(readRaw(agenticDir, 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee').status === 'pending',
    'pending marker NEVER touched by reclaim (CRITICAL-A)');

  assert(res.gaveUp.includes('ffffffff-ffff-ffff-ffff-ffffffffffff'),
    'attempts>=3 eligible marker reported as gaveUp');
  const f = readRaw(agenticDir, 'ffffffff-ffff-ffff-ffff-ffffffffffff');
  assert(f.status === 'gave_up', 'attempts>=3 eligible marker -> gave_up (not ready)');
  assert(f.last_error === 'reclaimed-after-max-attempts',
    'gave_up marker records last_error reclaimed-after-max-attempts');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (5 / MAJOR-3) finalizeReady no-downgrade
// ---------------------------------------------------------------------------
console.log('\n[5/MAJOR-3] finalizeReady is the SOLE pending->ready and never downgrades');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-final-');
  const SID = '11111111-1111-1111-1111-111111111111';

  // absent -> finalize creates a `ready` marker directly (no branch/sha).
  assert(lib.finalizeReady(projectDir, SID) === true, 'finalizeReady(absent) succeeds');
  let m = readRaw(agenticDir, SID);
  assert(m.status === 'ready', 'finalize from absent -> ready');
  assert(!('branch' in m) && !('head_sha' in m), 'ready marker carries no branch/head_sha');

  // already ready -> no-op (idempotent, no downgrade).
  assert(lib.finalizeReady(projectDir, SID) === false, 'finalizeReady(ready) is a no-op');
  assert(readRaw(agenticDir, SID).status === 'ready', 'ready stays ready (no regress)');

  // in_progress -> finalize must NOT downgrade to ready.
  writeMarkerRaw(agenticDir, SID, { status: 'in_progress', claimed_kind: 'daemon', claimed_by: LIVE_PID, claimed_at: agoIso(5), attempts: 1 });
  assert(lib.finalizeReady(projectDir, SID) === false, 'finalizeReady(in_progress) is a no-op');
  assert(readRaw(agenticDir, SID).status === 'in_progress', 'in_progress NOT downgraded to ready');

  // pending -> finalize promotes (the sole legal transition).
  writeMarkerRaw(agenticDir, SID, { status: 'pending', claimed_kind: null, claimed_by: null, claimed_at: null });
  assert(lib.finalizeReady(projectDir, SID) === true, 'finalizeReady(pending) promotes');
  assert(readRaw(agenticDir, SID).status === 'ready', 'pending -> ready (sole transition)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (5 / MAJOR-3) stagePending suppression
// ---------------------------------------------------------------------------
console.log('\n[5/MAJOR-3] stagePending suppresses on a live (ready/pending/in_progress) marker');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-stage-');
  const SID = '22222222-2222-2222-2222-222222222222';
  const substantive = { uncommittedCount: 1, pathsReferencedCount: 1, recentFocusCount: 0 };

  // ready -> suppress (do not re-stage / no regress to pending).
  writeMarkerRaw(agenticDir, SID, { status: 'ready' });
  assert(lib.stagePending(projectDir, SID, substantive) === false, 'stage suppressed when marker is ready');
  assert(readRaw(agenticDir, SID).status === 'ready', 'ready NOT regressed to pending by stage (MAJOR-3)');

  // pending -> suppress (already staged).
  writeMarkerRaw(agenticDir, SID, { status: 'pending' });
  assert(lib.stagePending(projectDir, SID, substantive) === false, 'stage suppressed when marker is pending');

  // in_progress -> suppress.
  writeMarkerRaw(agenticDir, SID, { status: 'in_progress', claimed_kind: 'daemon', claimed_by: LIVE_PID, claimed_at: agoIso(5) });
  assert(lib.stagePending(projectDir, SID, substantive) === false, 'stage suppressed when marker is in_progress');

  // done WITHOUT wrapped_at -> NOT suppressed (re-staging allowed); back-compat +
  // recycled-id carve-out regression guard: a `done` marker lacking `wrapped_at`
  // must never be treated as a completion tombstone.
  writeMarkerRaw(agenticDir, SID, { status: 'done' });
  assert(lib.stagePending(projectDir, SID, substantive) === true, 'stage allowed when prior marker is done without wrapped_at');
  assert(readRaw(agenticDir, SID).status === 'pending', 'done-without-wrapped_at marker re-staged to pending');

  // non-substantive -> suppressed regardless.
  const SID2 = '33333333-3333-3333-3333-333333333333';
  const nonSub = { uncommittedCount: 0, pathsReferencedCount: 0, recentFocusCount: 0 };
  assert(lib.stagePending(projectDir, SID2, nonSub) === false, 'stage suppressed for non-substantive session');
  assert(!markerExists(agenticDir, SID2), 'no marker written for non-substantive session');

  // .last-wrap == sid -> suppressed (already wrapped).
  const SID3 = '44444444-4444-4444-4444-444444444444';
  fs.writeFileSync(path.join(agenticDir, '.last-wrap'), SID3 + '\n', 'utf8');
  assert(lib.stagePending(projectDir, SID3, substantive) === false, 'stage suppressed when .last-wrap names this session');
  assert(!markerExists(agenticDir, SID3), 'no marker for an already-wrapped session');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (3 / CRITICAL-A) cleanStalePending is DELETE-ONLY
// ---------------------------------------------------------------------------
console.log('\n[3/CRITICAL-A] cleanStalePending deletes old pending, never status-mutates');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-janitor-');
  const TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

  // old pending -> DELETED.
  writeMarkerRaw(agenticDir, '55555555-5555-5555-5555-555555555555', {
    status: 'pending', staged_at: agoIso(8 * 24 * 60 * 60),
  });
  // fresh pending -> KEPT.
  writeMarkerRaw(agenticDir, '66666666-6666-6666-6666-666666666666', {
    status: 'pending', staged_at: agoIso(60),
  });
  // old READY -> NOT a pending marker, so the janitor must leave it (and never
  // promote/demote anything; this proves it cannot mutate a non-pending status).
  writeMarkerRaw(agenticDir, '77777777-7777-7777-7777-777777777777', {
    status: 'ready', staged_at: agoIso(8 * 24 * 60 * 60),
  });

  const res = lib.cleanStalePending(projectDir, TTL_MS);

  assert(res && Array.isArray(res.deleted), 'janitor returns { deleted:[] }');
  assert(res.deleted.includes('55555555-5555-5555-5555-555555555555'),
    'old pending marker reported deleted');
  assert(!markerExists(agenticDir, '55555555-5555-5555-5555-555555555555'),
    'old pending marker is gone from disk');
  assert(markerExists(agenticDir, '66666666-6666-6666-6666-666666666666'),
    'fresh pending marker is kept');
  assert(readRaw(agenticDir, '66666666-6666-6666-6666-666666666666').status === 'pending',
    'fresh pending marker status unchanged');
  assert(markerExists(agenticDir, '77777777-7777-7777-7777-777777777777'),
    'old ready marker is NOT deleted by the pending-only janitor');
  assert(readRaw(agenticDir, '77777777-7777-7777-7777-777777777777').status === 'ready',
    'old ready marker is NEVER status-mutated by the janitor (delete-only, CRITICAL-A)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (6) liveMarkerForSession semantics
// ---------------------------------------------------------------------------
console.log('\n[6] liveMarkerForSession: pending/ready/in_progress live; done/gave_up/absent not');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-live-');
  const SID = '88888888-8888-8888-8888-888888888888';

  assert(lib.liveMarkerForSession(projectDir, SID) === false, 'absent marker -> not live');
  for (const st of ['pending', 'ready', 'in_progress']) {
    writeMarkerRaw(agenticDir, SID, { status: st });
    assert(lib.liveMarkerForSession(projectDir, SID) === true, `${st} marker -> live`);
  }
  for (const st of ['done', 'gave_up']) {
    writeMarkerRaw(agenticDir, SID, { status: st });
    assert(lib.liveMarkerForSession(projectDir, SID) === false, `${st} marker -> not live`);
  }
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (18) per-session marker isolation
// ---------------------------------------------------------------------------
console.log('\n[18] per-session marker isolation: two sessions never collide');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-iso-');
  const S1 = 'aaaa1111-aaaa-1111-aaaa-111111111111';
  const S2 = 'bbbb2222-bbbb-2222-bbbb-222222222222';
  const sub = { uncommittedCount: 1, pathsReferencedCount: 0, recentFocusCount: 0 };

  assert(lib.stagePending(projectDir, S1, sub) === true, 'stage S1 succeeds');
  assert(lib.finalizeReady(projectDir, S2) === true, 'finalize S2 (different session) succeeds');

  assert(lib.markerPath(projectDir, S1) !== lib.markerPath(projectDir, S2),
    'distinct sessions resolve to distinct marker paths');
  assert(readRaw(agenticDir, S1).status === 'pending', 'S1 marker is pending (isolated)');
  assert(readRaw(agenticDir, S2).status === 'ready', 'S2 marker is ready (isolated)');

  // transitionDone(S1) must not affect S2; S1 marker RETAINED as done+wrapped_at tombstone.
  lib.transitionDone(projectDir, S1);
  const s1Done = readRaw(agenticDir, S1);
  assert(markerExists(agenticDir, S1) && s1Done && s1Done.status === 'done',
    'S1 marker RETAINED as done tombstone after transitionDone');
  assert(Number.isFinite(Date.parse(s1Done.wrapped_at)),
    'S1 done tombstone has a parseable wrapped_at timestamp');
  assert(readRaw(agenticDir, S2).status === 'ready', 'S2 marker untouched by S1 transitionDone');

  // listReadyMarkers sees only S2.
  const ready = lib.listReadyMarkers(projectDir);
  assert(ready.length === 1 && ready[0].sessionId === S2,
    'listReadyMarkers returns only the ready session (S2)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (13 portion) loop-guard no-ops every transition
// ---------------------------------------------------------------------------
console.log('\n[13] loop-guard (AGENTIC_WRAP_DAEMON=1) no-ops every transition');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-guard-');
  const SID = 'cccc3333-cccc-3333-cccc-333333333333';
  const sub = { uncommittedCount: 1, pathsReferencedCount: 1, recentFocusCount: 1 };

  process.env.AGENTIC_WRAP_DAEMON = '1';
  try {
    assert(lib.daemonGuardActive() === true, 'daemonGuardActive() true under guard');
    assert(lib.stagePending(projectDir, SID, sub) === false, 'stagePending no-op under guard');
    assert(lib.finalizeReady(projectDir, SID) === false, 'finalizeReady no-op under guard');
    assert(!markerExists(agenticDir, SID), 'no marker written by guarded stage/finalize');

    // Seed a ready marker on disk (raw), then prove guarded transitions no-op it.
    writeMarkerRaw(agenticDir, SID, { status: 'ready' });
    assert(lib.claimMarker(projectDir, SID, 'pid', 'daemon', 1000) === null, 'claimMarker no-op (null) under guard');
    assert(readRaw(agenticDir, SID).status === 'ready', 'marker still ready after guarded claim');
    assert(lib.transitionDone(projectDir, SID) === false, 'transitionDone no-op under guard');
    assert(markerExists(agenticDir, SID), 'marker NOT unlinked by guarded transitionDone');
    assert(lib.transitionGaveUp(projectDir, SID, 'x') === false, 'transitionGaveUp no-op under guard');
    assert(lib.writeMarker(projectDir, { session_id: SID, status: 'done' }) === false, 'writeMarker no-op under guard');

    // Reclaim + janitor are also guarded no-ops.
    writeMarkerRaw(agenticDir, SID, { status: 'in_progress', claimed_kind: 'daemon', claimed_by: DEAD_PID, claimed_at: agoIso(40 * 60), attempts: 1 });
    const r = lib.reclaimAbandonedInProgress(projectDir, 1000);
    assert(r.reclaimed.length === 0 && r.gaveUp.length === 0, 'reclaim no-op under guard');
    assert(readRaw(agenticDir, SID).status === 'in_progress', 'in_progress marker untouched by guarded reclaim');
    const j = lib.cleanStalePending(projectDir, 0);
    assert(j.deleted.length === 0, 'janitor no-op under guard');

    // touchHeartbeat is guarded.
    assert(lib.touchHeartbeat(projectDir, SID) === false, 'touchHeartbeat no-op under guard');
  } finally {
    delete process.env.AGENTIC_WRAP_DAEMON;
  }
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (20 portion) ensureClaudeHost is UNGUARDED
// ---------------------------------------------------------------------------
console.log('\n[20] ensureClaudeHost: create-if-absent, idempotent, UNGUARDED, fail-open');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-host-');
  const hostPath = path.join(agenticDir, '.claude-host');

  // absent -> created (guard OFF).
  assert(!fs.existsSync(hostPath), 'sentinel absent at start');
  lib.ensureClaudeHost(projectDir);
  assert(fs.existsSync(hostPath), 'ensureClaudeHost creates the sentinel when absent');
  assert(lib.isClaudeHost(projectDir) === true, 'isClaudeHost true after create');

  // present -> idempotent no-op (does not throw / truncate).
  fs.writeFileSync(hostPath, 'sentinel-body', 'utf8');
  lib.ensureClaudeHost(projectDir);
  assert(fs.readFileSync(hostPath, 'utf8') === 'sentinel-body',
    'ensureClaudeHost does not overwrite an existing sentinel');

  // UNGUARDED: writes even under the loop-guard (writing a true fact is harmless).
  const { base: base2, projectDir: proj2, agenticDir: ag2 } = makeProject('ae-mr-host2-');
  const host2 = path.join(ag2, '.claude-host');
  process.env.AGENTIC_WRAP_DAEMON = '1';
  try {
    assert(!fs.existsSync(host2), 'second sentinel absent at start');
    lib.ensureClaudeHost(proj2);
    assert(fs.existsSync(host2), 'ensureClaudeHost writes EVEN under the loop-guard (unguarded)');
  } finally {
    delete process.env.AGENTIC_WRAP_DAEMON;
  }

  cleanup(base);
  cleanup(base2);
}

// ---------------------------------------------------------------------------
// (SEC-M2) oversized marker file is skipped (fail-open), not parsed
// ---------------------------------------------------------------------------
console.log('\n[SEC-M2] oversized marker file is skipped (treated as unreadable), small one read');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-sizecap-');
  const BIG = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
  const SMALL = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';

  // A valid `ready` marker, but padded past the 64 KB cap with a huge field.
  const bigMarker = {
    schema_version: 3, session_id: BIG, staged_at: new Date().toISOString(),
    status: 'ready', claimed_by: null, claimed_kind: null, claimed_at: null,
    attempts: 0, project_root: projectDir, last_error: null,
    _pad: 'x'.repeat(70 * 1024), // > MAX_MARKER_BYTES (64 KB)
  };
  fs.writeFileSync(
    path.join(agenticDir, 'wrap-pending-' + BIG + '.json'),
    JSON.stringify(bigMarker, null, 2), 'utf8'
  );
  // A normal small `ready` marker.
  writeMarkerRaw(agenticDir, SMALL, { status: 'ready' });

  // Direct read of the oversized marker is null (skipped before parse).
  assert(lib.readMarker(projectDir, BIG) === null,
    'oversized marker read returns null (size cap, fail-open)');
  // The small marker is still readable.
  assert(lib.readMarker(projectDir, SMALL) !== null,
    'small marker still readable alongside an oversized sibling');

  // The scan skips the oversized marker but returns the small one.
  const ready = lib.listReadyMarkers(projectDir);
  const ids = ready.map((e) => e.sessionId);
  assert(!ids.includes(BIG), 'listReadyMarkers excludes the oversized marker');
  assert(ids.includes(SMALL), 'listReadyMarkers still includes the small ready marker');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (SEC-M3a) non-UUID marker filenames are short-circuited (never read)
// ---------------------------------------------------------------------------
console.log('\n[SEC-M3a] non-UUID wrap-pending-*.json filenames are filtered before any read');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-uuidfilter-');
  const VALID = 'cccccccc-cccc-cccc-cccc-cccccccccccc';

  // A valid ready marker (UUID session component).
  writeMarkerRaw(agenticDir, VALID, { status: 'ready' });
  // Hostile non-UUID filenames carrying a `ready` payload - MUST be ignored because
  // their session component does not match the UUID shape (filtered before read).
  for (const bad of ['not-a-uuid', '../escape', 'x'.repeat(300), 'short', '']) {
    // Guard against an empty component producing the bare prefix file; skip empty.
    const fname = 'wrap-pending-' + bad + '.json';
    try {
      fs.writeFileSync(path.join(agenticDir, fname),
        JSON.stringify({ status: 'ready', session_id: bad }, null, 2), 'utf8');
    } catch (_) { /* '../escape' may be rejected by the fs; that is fine */ }
  }

  const ready = lib.listReadyMarkers(projectDir);
  assert(ready.length === 1 && ready[0].sessionId === VALID,
    'listReadyMarkers returns ONLY the UUID-named ready marker (non-UUID names short-circuited)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (SEC-M3b) per-scan count cap: at most MAX_MARKERS_PER_SCAN processed
// ---------------------------------------------------------------------------
console.log('\n[SEC-M3b] per-scan count cap: a pathologically large marker dir is bounded');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-scancap-');

  // Plant > 1000 valid-UUID `ready` markers. The cap is 1000, so the scan must
  // process AT MOST 1000 (proving it does not read every file on a hostile dir).
  const TOTAL = 1100;
  for (let i = 0; i < TOTAL; i++) {
    // Deterministic distinct UUIDs: 12-hex tail from the index.
    const tail = i.toString(16).padStart(12, '0');
    const sid = 'dddddddd-dddd-dddd-dddd-' + tail;
    writeMarkerRaw(agenticDir, sid, { status: 'ready' });
  }

  // Silence the expected truncation warning during the assertion.
  const origWrite = process.stderr.write;
  let warned = false;
  process.stderr.write = function (chunk) {
    if (typeof chunk === 'string' && /scan truncated/.test(chunk)) { warned = true; return true; }
    return origWrite.apply(process.stderr, arguments);
  };
  let ready;
  try {
    ready = lib.listReadyMarkers(projectDir);
  } finally {
    process.stderr.write = origWrite;
  }

  assert(ready.length === 1000,
    `scan processes at most MAX_MARKERS_PER_SCAN (got ${ready.length}, expected 1000)`);
  assert(warned === true, 'scan emits a truncation warning when capped');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (PERF-Minor) cleanStalePending co-deletes the sibling heartbeat
// ---------------------------------------------------------------------------
console.log('\n[PERF] cleanStalePending co-deletes a deleted stale marker\'s sibling heartbeat');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-hbleak-');
  const TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
  const STALE = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee';
  const FRESH = 'ffffffff-ffff-ffff-ffff-ffffffffffff';

  // A stale pending marker (older than TTL) + its sibling heartbeat.
  writeMarkerRaw(agenticDir, STALE, { status: 'pending', staged_at: agoIso(8 * 24 * 60 * 60) });
  lib.touchHeartbeat(projectDir, STALE);
  // A fresh pending marker + heartbeat that must SURVIVE.
  writeMarkerRaw(agenticDir, FRESH, { status: 'pending', staged_at: agoIso(60) });
  lib.touchHeartbeat(projectDir, FRESH);

  const staleHb = lib.heartbeatPath(projectDir, STALE);
  const freshHb = lib.heartbeatPath(projectDir, FRESH);
  assert(fs.existsSync(staleHb), 'stale session heartbeat exists before janitor');
  assert(fs.existsSync(freshHb), 'fresh session heartbeat exists before janitor');

  const res = lib.cleanStalePending(projectDir, TTL_MS);

  assert(res.deleted.includes(STALE), 'stale pending marker reported deleted');
  assert(!markerExists(agenticDir, STALE), 'stale pending marker removed from disk');
  assert(!fs.existsSync(staleHb), 'stale session sibling heartbeat co-deleted (no orphan leak)');
  // The fresh marker and its heartbeat are untouched.
  assert(markerExists(agenticDir, FRESH), 'fresh pending marker kept');
  assert(fs.existsSync(freshHb), 'fresh session heartbeat NOT deleted (only stale co-deleted)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (A) A-B-A end-to-end: same session not re-staged after .last-wrap rolls
// ---------------------------------------------------------------------------
console.log('\n[A] A-B-A end-to-end: tombstone suppresses re-staging after .last-wrap rolls to B');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-aba-');
  const SID_A = 'aaaaaaaa-aaaa-4aaa-aaaa-000000000001';
  const SID_B = 'bbbbbbbb-bbbb-4bbb-bbbb-000000000002';
  const substantive = { uncommittedCount: 1, pathsReferencedCount: 1, recentFocusCount: 0 };

  // Stage A's marker.
  assert(lib.stagePending(projectDir, SID_A, substantive) === true, '[A] stagePending(A) succeeds');

  // Transition A to done (retention path).
  assert(lib.transitionDone(projectDir, SID_A) === true, '[A] transitionDone(A) succeeds');

  // A is retained as done+wrapped_at.
  const aDone = readRaw(agenticDir, SID_A);
  assert(aDone && aDone.status === 'done', '[A] A marker retained as done');
  assert(Number.isFinite(Date.parse(aDone.wrapped_at)), '[A] A done marker has parseable wrapped_at');

  // Simulate .last-wrap rolling to B (another session wrapped after A).
  fs.writeFileSync(path.join(agenticDir, '.last-wrap'), SID_B + '\n', 'utf8');

  // A should NOT be re-staged even though .last-wrap != A.
  assert(lib.stagePending(projectDir, SID_A, substantive) === false,
    '[A] stagePending(A) suppressed by done+wrapped_at tombstone after .last-wrap rolled to B');

  // A's marker is still done (not regressed to pending).
  assert(readRaw(agenticDir, SID_A).status === 'done',
    '[A] A done tombstone not regressed to pending by attempted re-staging');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (B) recycled-id: done WITHOUT wrapped_at is still stageable
// ---------------------------------------------------------------------------
console.log('\n[B] recycled-id: done without wrapped_at is NOT a tombstone; staging proceeds');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-recycle-');
  const SID_C = 'cccccccc-cccc-4ccc-cccc-000000000003';
  const substantive = { uncommittedCount: 1, pathsReferencedCount: 1, recentFocusCount: 0 };

  // Write a done marker WITHOUT wrapped_at (legacy / recycled-id).
  writeMarkerRaw(agenticDir, SID_C, { status: 'done' /* no wrapped_at */ });

  // Must be stageable (not suppressed).
  assert(lib.stagePending(projectDir, SID_C, substantive) === true,
    '[B] stagePending(C) allowed: done without wrapped_at is not a tombstone');
  assert(readRaw(agenticDir, SID_C).status === 'pending',
    '[B] C marker became pending (recycled from done-without-wrapped_at)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (C) janitor done-sweep: keeps ready/gave_up/in_progress; skips both-unparseable done
// ---------------------------------------------------------------------------
console.log('\n[C] janitor done-sweep: old done deleted, fresh kept, ready/gave_up/in_progress untouched');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-donesweep-');
  const TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

  // Old done+wrapped_at: should be DELETED.
  const OLD_DONE = 'dddddddd-dddd-4ddd-dddd-000000000004';
  writeMarkerRaw(agenticDir, OLD_DONE, {
    status: 'done',
    wrapped_at: agoIso(8 * 24 * 60 * 60),
    staged_at: agoIso(8 * 24 * 60 * 60),
  });

  // Fresh done+wrapped_at: should be KEPT.
  const FRESH_DONE = 'eeeeeeee-eeee-4eee-eeee-000000000005';
  writeMarkerRaw(agenticDir, FRESH_DONE, {
    status: 'done',
    wrapped_at: agoIso(60),
    staged_at: agoIso(60),
  });

  // Old pending: should be DELETED (existing behavior).
  const OLD_PEND = 'ffffffff-ffff-4fff-ffff-000000000006';
  writeMarkerRaw(agenticDir, OLD_PEND, {
    status: 'pending',
    staged_at: agoIso(8 * 24 * 60 * 60),
  });

  // Old ready: should NOT be touched.
  const OLD_READY = '11111111-1111-4111-1111-000000000007';
  writeMarkerRaw(agenticDir, OLD_READY, {
    status: 'ready',
    staged_at: agoIso(8 * 24 * 60 * 60),
  });

  // Old gave_up: should NOT be touched.
  const OLD_GAVEUP = '22222222-2222-4222-2222-000000000008';
  writeMarkerRaw(agenticDir, OLD_GAVEUP, {
    status: 'gave_up',
    staged_at: agoIso(8 * 24 * 60 * 60),
  });

  // Old in_progress: should NOT be touched.
  const OLD_INPROG = '33333333-3333-4333-3333-000000000009';
  writeMarkerRaw(agenticDir, OLD_INPROG, {
    status: 'in_progress',
    staged_at: agoIso(8 * 24 * 60 * 60),
  });

  // Done with BOTH timestamps unparseable: should be SKIPPED (kept).
  const BOTH_UNPARSE = '44444444-4444-4444-4444-000000000010';
  writeMarkerRaw(agenticDir, BOTH_UNPARSE, {
    status: 'done',
    wrapped_at: 'not-a-date',
    staged_at: 'also-not-a-date',
  });

  // Done with unparseable wrapped_at but parseable old staged_at: age falls back to
  // staged_at -> should be DELETED.
  const UNPARSE_WAT = '55555555-5555-4555-5555-000000000011';
  writeMarkerRaw(agenticDir, UNPARSE_WAT, {
    status: 'done',
    wrapped_at: 'not-a-date',
    staged_at: agoIso(8 * 24 * 60 * 60),
  });

  const res = lib.cleanStalePending(projectDir, TTL_MS);

  // Old done deleted.
  assert(res.deleted.includes(OLD_DONE), '[C] old done tombstone reported deleted');
  assert(!markerExists(agenticDir, OLD_DONE), '[C] old done tombstone removed from disk');

  // Fresh done kept.
  assert(markerExists(agenticDir, FRESH_DONE), '[C] fresh done tombstone kept');

  // Old pending deleted (existing behavior preserved).
  assert(res.deleted.includes(OLD_PEND), '[C] old pending marker reported deleted');
  assert(!markerExists(agenticDir, OLD_PEND), '[C] old pending marker removed from disk');

  // ready / gave_up / in_progress all untouched.
  assert(markerExists(agenticDir, OLD_READY) && readRaw(agenticDir, OLD_READY).status === 'ready',
    '[C] old ready marker NOT touched by janitor');
  assert(markerExists(agenticDir, OLD_GAVEUP) && readRaw(agenticDir, OLD_GAVEUP).status === 'gave_up',
    '[C] old gave_up marker NOT touched by janitor');
  assert(markerExists(agenticDir, OLD_INPROG) && readRaw(agenticDir, OLD_INPROG).status === 'in_progress',
    '[C] old in_progress marker NOT touched by janitor');

  // Both-unparseable done: SKIPPED (kept on disk).
  assert(markerExists(agenticDir, BOTH_UNPARSE),
    '[C] done with both timestamps unparseable is SKIPPED (not deleted)');

  // Unparseable wrapped_at but parseable old staged_at: DELETED (age derived from staged_at).
  assert(!markerExists(agenticDir, UNPARSE_WAT),
    '[C] done with unparseable wrapped_at but old staged_at is DELETED (age from staged_at)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (D) un-guarded retention: transitionDone without daemon env retains tombstone
// ---------------------------------------------------------------------------
console.log('\n[D] un-guarded transitionDone: marker retained as done+wrapped_at');
{
  const { base, projectDir, agenticDir } = makeProject('ae-mr-ungrd-');
  const SID_D = '66666666-6666-4666-6666-000000000012';

  // Ensure guard is OFF.
  delete process.env.AGENTIC_WRAP_DAEMON;

  writeMarkerRaw(agenticDir, SID_D, { status: 'ready' });
  assert(lib.transitionDone(projectDir, SID_D) === true,
    '[D] transitionDone returns true when unguarded');
  const dDone = readRaw(agenticDir, SID_D);
  assert(dDone && dDone.status === 'done',
    '[D] marker retained as done tombstone');
  assert(Number.isFinite(Date.parse(dDone.wrapped_at)),
    '[D] done tombstone has parseable wrapped_at');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
