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

  // done -> NOT suppressed (re-staging allowed); a substantive new session re-stages.
  writeMarkerRaw(agenticDir, SID, { status: 'done' });
  assert(lib.stagePending(projectDir, SID, substantive) === true, 'stage allowed when prior marker is done');
  assert(readRaw(agenticDir, SID).status === 'pending', 'done marker re-staged to pending');

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

  // transitionDone(S1) must not affect S2.
  lib.transitionDone(projectDir, S1);
  assert(!markerExists(agenticDir, S1), 'S1 marker unlinked after done');
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
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
