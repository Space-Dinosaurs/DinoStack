#!/usr/bin/env node
'use strict';

/**
 * Unit tests for wrapLockAbandoned / clearAbandonedWrapLock in
 * hooks/lib/wrap-marker.js - the D1 fix (DS-106).
 *
 * Regression coverage for the live defect: wrapLockVerdict returns 'live'
 * UNCONDITIONALLY for role:'agent' (row 10), and the interactive /ds-wrap
 * acquires with exactly --role=agent (which writes pid:null). With no pid to
 * liveness-check, the verdict never went stale, clearProvablyStaleWrapLock
 * refused, and its ONLY caller is a daemon that `deferred_wrap_daemon: false`
 * (the default) never launches. Measured consequence: a lock held 10.3 hours by
 * a dead pid, during which 49 context.md writes across 6 sessions were silently
 * discarded.
 *
 * Covers:
 *   AC1  - role:'agent', NO session_id, acquired_at 5h old -> ABANDONED (Arm B)
 *   AC2  - role:'agent', FRESH heartbeat, 45m old -> NOT abandoned (Arm A row A1)
 *   AC11 - wrapLockVerdict's 14 rows are untouched; the new logic performs its
 *          arithmetic OUTSIDE that function's no-arithmetic invariant
 *   plus the full Table A row set (A1-A6), the daemon/commit rows, the legacy
 *   rows (L1-L3), symlink/plain-file refusal, and fail-open behaviour.
 *
 * Run with: node hooks/tests/test-wrap-lock-abandoned.js
 * Argument-free invocation runs everything (auto-discovered by the
 * hooks/tests/test-*.js glob in .github/workflows/hooks-tests.yml).
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const lib = require('../lib/wrap-marker.js');

let passed = 0;
let failed = 0;
const tmpDirs = [];

function assert(condition, message) {
  if (condition) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message}`);
    failed++;
  }
}

function makeProject() {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'wrap-abandoned-')));
  tmpDirs.push(dir);
  return dir;
}

function agoIso(ms) {
  return new Date(Date.now() - ms).toISOString();
}

/** Plant a lock dir plus a JSON descriptor built by the SOLE producer. */
function plantJsonLock(cwd, params) {
  const lockDir = lib.wrapLockPath(cwd);
  fs.mkdirSync(lockDir, { recursive: true });
  const d = lib.makeLockDescriptor(params);
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(cwd), JSON.stringify(d), 'utf8');
  return lockDir;
}

/** Plant a lock dir plus a LEGACY owner body (verbatim). */
function plantLegacyLock(cwd, body) {
  const lockDir = lib.wrapLockPath(cwd);
  fs.mkdirSync(lockDir, { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerPath(cwd), body, 'utf8');
  return lockDir;
}

function plantHeartbeat(cwd, sessionId, ageMs) {
  const p = lib.heartbeatPath(cwd, sessionId);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, '', 'utf8');
  const t = new Date(Date.now() - ageMs);
  fs.utimesSync(p, t, t);
  return p;
}

const H = 60 * 60 * 1000;
const M = 60 * 1000;

// ---------------------------------------------------------------------------
// AC1 - the observed orphan: agent lock, NO session_id, 5h old
// ---------------------------------------------------------------------------
console.log('\n--- AC1 (row A5): pre-upgrade descriptor, no session_id ---');
{
  const cwd = makeProject();
  plantJsonLock(cwd, { role: 'agent', pid: null, acquiredAt: agoIso(5 * H) });
  assert(lib.wrapLockVerdict(cwd).verdict === 'live',
    'AC1 precondition: wrapLockVerdict still reports live (row 10 is why the orphan was immortal)');
  assert(lib.wrapLockAbandoned(cwd) === true,
    'AC1: a 5h-old role:agent lock with no session_id IS abandoned (Arm B)');
  assert(lib.clearAbandonedWrapLock(cwd) === true, 'AC1: clearAbandonedWrapLock removes it');
  assert(!fs.existsSync(lib.wrapLockPath(cwd)), 'AC1: the lock directory is gone');
  assert(lib.acquireWrapLock(cwd, '1\n' + new Date().toISOString(), 0,
    { role: 'agent', pid: null, sessionId: 'fresh-session' }) === true,
    'AC1: the lock is acquirable immediately after the clear');
}
{
  // Falsifying mutation for AC1: a 3h-old lock is under the 4h Arm B threshold.
  const cwd = makeProject();
  plantJsonLock(cwd, { role: 'agent', pid: null, acquiredAt: agoIso(3 * H) });
  assert(lib.wrapLockAbandoned(cwd) === false,
    'AC1 boundary: a 3h-old pid-blind lock is NOT abandoned (4h threshold is live, not a no-op)');
}

// ---------------------------------------------------------------------------
// AC2 - a live lock is never stolen
// ---------------------------------------------------------------------------
console.log('\n--- AC2 (row A1): fresh heartbeat, 45m old ---');
{
  const cwd = makeProject();
  const sid = 'live-session-uuid';
  plantJsonLock(cwd, { role: 'agent', pid: null, sessionId: sid, acquiredAt: agoIso(45 * M) });
  plantHeartbeat(cwd, sid, 10 * 1000); // 10s old = fresh
  assert(lib.wrapLockAbandoned(cwd) === false,
    'AC2: a 45m-old lock whose session is STILL heartbeating is NOT abandoned');
  assert(lib.clearAbandonedWrapLock(cwd) === false, 'AC2: clearAbandonedWrapLock refuses');
  assert(fs.existsSync(lib.wrapLockOwnerJsonPath(cwd)), 'AC2: the descriptor is untouched');
}
{
  // Falsifying mutation for AC2: drop the heartbeat-fresh conjunct -> the same
  // lock would be stolen. Proven by making the heartbeat STALE and nothing else.
  const cwd = makeProject();
  const sid = 'dead-session-uuid';
  plantJsonLock(cwd, { role: 'agent', pid: null, sessionId: sid, acquiredAt: agoIso(45 * M) });
  plantHeartbeat(cwd, sid, 40 * M); // stale
  assert(lib.wrapLockAbandoned(cwd) === true,
    'AC2 mutation-mirror (row A2): the SAME lock with a STALE heartbeat IS abandoned - '
    + 'so AC2 is testing the heartbeat conjunct, not a constant');
}

// ---------------------------------------------------------------------------
// Table A - remaining rows
// ---------------------------------------------------------------------------
console.log('\n--- Table A rows A3, A4, A6 ---');
{
  // A3: heartbeat stale but the lock itself is young - protects a long turn.
  const cwd = makeProject();
  const sid = 'young-lock';
  plantJsonLock(cwd, { role: 'agent', pid: null, sessionId: sid, acquiredAt: agoIso(5 * M) });
  plantHeartbeat(cwd, sid, 40 * M);
  assert(lib.wrapLockAbandoned(cwd) === false,
    'row A3: a stale heartbeat on a <30m-old lock does NOT abandon (protects one long turn)');
}
{
  // A4: session_id present, heartbeat file ABSENT -> falls to Arm B, not Arm A.
  const cwd = makeProject();
  plantJsonLock(cwd, { role: 'agent', pid: null, sessionId: 'no-hb', acquiredAt: agoIso(45 * M) });
  assert(lib.wrapLockAbandoned(cwd) === false,
    'row A4: no heartbeat FILE -> Arm B, so 45m is not enough (fail-safe for pre-ungate installs)');
  const cwd2 = makeProject();
  plantJsonLock(cwd2, { role: 'agent', pid: null, sessionId: 'no-hb', acquiredAt: agoIso(5 * H) });
  assert(lib.wrapLockAbandoned(cwd2) === true, 'row A4: the same lock at 5h IS abandoned via Arm B');
}
{
  // A6: schema-invalid descriptor degrades to the legacy reader.
  const cwd = makeProject();
  fs.mkdirSync(lib.wrapLockPath(cwd), { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(cwd), '{not json', 'utf8');
  fs.writeFileSync(lib.wrapLockOwnerPath(cwd), '999999\n' + agoIso(5 * H), 'utf8');
  assert(lib.wrapLockAbandoned(cwd) === true,
    'row A6: an unparseable descriptor degrades to the legacy reader, which Arm B ages out');
}

console.log('\n--- daemon/commit roles are NEVER aged out ---');
{
  const cwd = makeProject();
  plantJsonLock(cwd, { role: 'daemon', pid: process.pid, acquiredAt: agoIso(9 * H) });
  assert(lib.wrapLockAbandoned(cwd) === false,
    'a 9h-old daemon lock with a LIVE pid is not abandoned (liveness, not age, governs it)');
  const cwd2 = makeProject();
  plantJsonLock(cwd2, { role: 'commit', pid: 999999, acquiredAt: agoIso(9 * H) });
  assert(lib.wrapLockAbandoned(cwd2) === false,
    'a dead-pid daemon/commit lock is clearProvablyStaleWrapLock\'s business, not this predicate\'s');
}

console.log('\n--- legacy owner bodies (rows L1-L3) ---');
{
  const cwd = makeProject();
  plantLegacyLock(cwd, '3322\n' + agoIso(10 * H));
  assert(lib.wrapLockAbandoned(cwd) === true,
    'row L1: a 10.3h-style legacy 2-line body IS abandoned (this is the observed orphan shape)');
}
{
  const cwd = makeProject();
  plantLegacyLock(cwd, '3322\n' + agoIso(2 * H));
  assert(lib.wrapLockAbandoned(cwd) === false, 'row L1 boundary: a 2h-old legacy lock is kept');
}
{
  const cwd = makeProject();
  plantLegacyLock(cwd, '3322');
  assert(lib.wrapLockAbandoned(cwd) === false,
    'row L2: a 1-line daemon body is pid-checkable and belongs to the other clear path');
}
{
  const cwd = makeProject();
  plantLegacyLock(cwd, '3322\nnot-a-timestamp');
  assert(lib.wrapLockAbandoned(cwd) === false, 'row L3: a garbled timestamp KEEPS the lock');
  const cwd2 = makeProject();
  fs.mkdirSync(lib.wrapLockPath(cwd2), { recursive: true });
  assert(lib.wrapLockAbandoned(cwd2) === false,
    'row L3: an owner-less lock dir KEEPS (preserves the mkdir-before-owner race guard)');
}

// ---------------------------------------------------------------------------
// Lock absent / hostile artifacts
// ---------------------------------------------------------------------------
console.log('\n--- absent lock and hostile artifacts ---');
{
  const cwd = makeProject();
  assert(lib.wrapLockAbandoned(cwd) === false, 'no lock -> not abandoned');
  assert(lib.clearAbandonedWrapLock(cwd) === false, 'no lock -> nothing cleared');
}
{
  const cwd = makeProject();
  fs.mkdirSync(path.join(cwd, '.agentic', 'wrap'), { recursive: true });
  const target = path.join(cwd, 'sensitive');
  fs.mkdirSync(target);
  fs.writeFileSync(path.join(target, 'keep-me'), 'x', 'utf8');
  fs.symlinkSync(target, lib.wrapLockPath(cwd));
  assert(lib.wrapLockAbandoned(cwd) === false, 'a symlink AT the lock path is never "abandoned"');
  assert(lib.clearAbandonedWrapLock(cwd) === false, 'a symlink AT the lock path is not a clear');
  assert(fs.existsSync(path.join(target, 'keep-me')),
    'CWE-59: the symlink TARGET is never touched (only the link is unlinked)');
}
{
  const cwd = makeProject();
  fs.mkdirSync(path.join(cwd, '.agentic', 'wrap'), { recursive: true });
  fs.writeFileSync(lib.wrapLockPath(cwd), 'not a dir', 'utf8');
  assert(lib.wrapLockAbandoned(cwd) === false, 'a plain file at the lock path is refused');
  assert(lib.clearAbandonedWrapLock(cwd) === false, 'a plain file at the lock path is left alone');
  assert(fs.readFileSync(lib.wrapLockPath(cwd), 'utf8') === 'not a dir', 'the plain file is untouched');
}
{
  let threw = false;
  try {
    lib.wrapLockAbandoned(null);
    lib.wrapLockAbandoned('relative/path');
    lib.clearAbandonedWrapLock(undefined);
  } catch (_) { threw = true; }
  assert(!threw, 'fail-open: never throws on invalid cwd');
}

// ---------------------------------------------------------------------------
// AC11 - wrapLockVerdict's invariant and rows are untouched
// ---------------------------------------------------------------------------
console.log('\n--- AC11: wrapLockVerdict untouched ---');
{
  const src = fs.readFileSync(path.join(__dirname, '..', 'lib', 'wrap-marker.js'), 'utf8');
  const m = src.match(/\nfunction wrapLockVerdict\(cwd\) \{[\s\S]*?\n\}\n/);
  assert(!!m, 'AC11: wrapLockVerdict is locatable in the source');
  const bodyText = m ? m[0] : '';
  assert(bodyText.indexOf('Date.now()') === -1,
    'AC11: wrapLockVerdict still contains no Date.now() (no-arithmetic invariant intact)');
  assert(bodyText.indexOf('ABANDON_MS') === -1 && bodyText.indexOf('heartbeatFresh') === -1,
    'AC11: no abandonment logic leaked into wrapLockVerdict');
}
{
  // The four verdicts an abandoned lock can carry are unchanged by this unit.
  const cwd = makeProject();
  plantJsonLock(cwd, { role: 'agent', pid: null, acquiredAt: agoIso(5 * H) });
  const v = lib.wrapLockVerdict(cwd);
  assert(v.verdict === 'live' && v.source === 'json' && v.role === 'agent' && v.pid === null,
    'AC11: row 10 still returns live/json/agent/null on an abandoned lock (verdict and '
    + 'abandonment are separate axes by design)');
}

// ---------------------------------------------------------------------------
// Threshold overrides (used by the acquire helper and by tests)
// ---------------------------------------------------------------------------
console.log('\n--- threshold overrides ---');
{
  const cwd = makeProject();
  plantJsonLock(cwd, { role: 'agent', pid: null, acquiredAt: agoIso(10 * M) });
  assert(lib.wrapLockAbandoned(cwd, { legacyAbandonMs: 5 * M }) === true,
    'legacyAbandonMs override is honoured');
  assert(lib.wrapLockAbandoned(cwd, { legacyAbandonMs: 60 * M }) === false,
    'legacyAbandonMs override is honoured in the other direction');
  assert(lib.ABANDON_MS === 30 * M, 'ABANDON_MS default is 30 minutes');
  assert(lib.LEGACY_ABANDON_MS === 4 * H, 'LEGACY_ABANDON_MS default is 4 hours');
  assert(lib.STUCK_NOTICE_MS === lib.ABANDON_MS, 'STUCK_NOTICE_MS tracks ABANDON_MS');
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------
for (const d of tmpDirs) {
  try { fs.rmSync(d, { recursive: true, force: true }); } catch (_) { /* best-effort */ }
}

console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
