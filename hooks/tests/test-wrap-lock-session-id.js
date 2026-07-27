#!/usr/bin/env node
'use strict';

/**
 * Unit tests for the `session_id` lock-descriptor field (DS-106) - the liveness
 * signal that makes an abandoned role:'agent' lock detectable at all.
 *
 * Covers:
 *   AC6  - a tokenless releaseWrapLock on a role:'agent' lock still returns
 *          'released'. THE PREDICTED COUPLING: putting a real pid in the agent
 *          descriptor to make it liveness-checkable would arm releaseWrapLock's
 *          `o.pid !== null` refuse branch, and /ds-wrap releases WITHOUT a token,
 *          so it would leak a lock on EVERY run. Using session_id instead of a
 *          pid routes around the coupling; this AC pins that it stays routed around.
 *   AC13 - session_id ROUND-TRIPS: written by makeLockDescriptor, returned by
 *          readWrapLockOwnerV2, consumed by wrapLockAbandoned. Adding the writer
 *          field without the reader's returned shape drops it silently and makes
 *          Arm A inert WITH NO ERROR ANYWHERE.
 *   AC14 - acquisition SUCCEEDS with the session id empty/unset, and the
 *          descriptor validates with session_id:null. makeLockDescriptor is
 *          called INSIDE acquireWrapLock's try whose catch removes the lock dir
 *          and returns false, so fail-loud validation would make /ds-wrap refuse
 *          to run on every harness that does not export CLAUDE_CODE_SESSION_ID.
 *   AC15 - the CLI flag and the /ds-wrap call sites use CLAUDE_CODE_SESSION_ID
 *          and NOT the two dead vars bin/agentic-migrate reads (both measured empty).
 *
 * Run with: node hooks/tests/test-wrap-lock-session-id.js
 * Argument-free invocation runs everything (auto-discovered by the
 * hooks/tests/test-*.js glob in .github/workflows/hooks-tests.yml).
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
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
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'wrap-sid-')));
  tmpDirs.push(dir);
  return dir;
}

const REPO = path.join(__dirname, '..', '..');
const ACQUIRE = path.join(REPO, 'bin', 'agentic-wrap-acquire-lock');
const SID = 'f176f720-a218-4cac-84a0-1489abe7aa1d';

// ---------------------------------------------------------------------------
// AC13 - writer/reader-together round trip
// ---------------------------------------------------------------------------
console.log('\n--- AC13: session_id round trip ---');
{
  const d = lib.makeLockDescriptor({ role: 'agent', pid: null, sessionId: SID });
  assert(d.session_id === SID, 'AC13 writer: makeLockDescriptor emits session_id');

  const cwd = makeProject();
  fs.mkdirSync(lib.wrapLockPath(cwd), { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(cwd), JSON.stringify(d), 'utf8');
  const o = lib.readWrapLockOwnerV2(cwd);
  assert(o.source === 'json', 'AC13: a session_id-bearing descriptor still validates as source:json');
  assert(o.session_id === SID,
    'AC13 reader: readWrapLockOwnerV2 RETURNS session_id (dropping it makes Arm A inert with no error)');

  // Consumer: Arm A only reaches its heartbeat branch if the id survived both hops.
  const hb = lib.heartbeatPath(cwd, SID);
  fs.mkdirSync(path.dirname(hb), { recursive: true });
  fs.writeFileSync(hb, '', 'utf8');
  const old = new Date(Date.now() - 40 * 60 * 1000);
  fs.utimesSync(hb, old, old);
  // 45m lock + stale heartbeat -> Arm A says abandoned. Under Arm B (which is
  // what an inert session_id would fall through to) 45m is far below 4h, so a
  // dropped session_id yields FALSE here. This assertion is the round-trip proof.
  const backdated = lib.makeLockDescriptor({
    role: 'agent', pid: null, sessionId: SID,
    acquiredAt: new Date(Date.now() - 45 * 60 * 1000).toISOString(),
  });
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(cwd), JSON.stringify(backdated), 'utf8');
  assert(lib.wrapLockAbandoned(cwd) === true,
    'AC13 consumer: wrapLockAbandoned reaches Arm A only because session_id survived writer AND reader');
}
{
  // Pre-upgrade descriptor: session_id absent entirely must still validate.
  const cwd = makeProject();
  fs.mkdirSync(lib.wrapLockPath(cwd), { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(cwd), JSON.stringify({
    schema_version: 1, role: 'agent', pid: null, host: os.hostname(),
    acquired_at: new Date().toISOString(), token: null,
  }), 'utf8');
  const o = lib.readWrapLockOwnerV2(cwd);
  assert(o.source === 'json' && o.session_id === null,
    'additive-optional: a pre-upgrade descriptor with NO session_id key still validates (never '
    + 'rejected into the legacy fallback)');
}
{
  // A structurally invalid session_id must reject the descriptor, not be trusted.
  const cwd = makeProject();
  fs.mkdirSync(lib.wrapLockPath(cwd), { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(cwd), JSON.stringify({
    schema_version: 1, role: 'agent', pid: null, host: os.hostname(),
    acquired_at: new Date().toISOString(), token: null, session_id: 42,
  }), 'utf8');
  assert(lib.readWrapLockOwnerV2(cwd).source !== 'json',
    'a non-string session_id degrades the descriptor to the legacy fallback (validation is real)');
}

// ---------------------------------------------------------------------------
// AC14 - permissive validation
// ---------------------------------------------------------------------------
console.log('\n--- AC14: permissive session_id validation ---');
{
  for (const [label, value] of [['undefined', undefined], ['null', null], ['empty string', ''],
    ['whitespace', '   '], ['number', 42], ['object', {}]]) {
    let d = null;
    let threw = false;
    try { d = lib.makeLockDescriptor({ role: 'agent', pid: null, sessionId: value }); } catch (_) { threw = true; }
    assert(!threw && d && d.session_id === null,
      `AC14: sessionId ${label} coerces to null WITHOUT throwing`);
  }
  // The siblings must stay fail-loud - the departure is scoped to session_id only.
  let roleThrew = false;
  try { lib.makeLockDescriptor({ role: 'bogus' }); } catch (_) { roleThrew = true; }
  assert(roleThrew, 'AC14 scope: role validation is still fail-loud');
  let pidThrew = false;
  try { lib.makeLockDescriptor({ role: 'agent', pid: -1 }); } catch (_) { pidThrew = true; }
  assert(pidThrew, 'AC14 scope: pid validation is still fail-loud');
}
{
  // The behavioural consequence: acquisition succeeds with no session id.
  const cwd = makeProject();
  const ok = lib.acquireWrapLock(cwd, '1\n' + new Date().toISOString(), 0,
    { role: 'agent', pid: null, token: null, sessionId: '' });
  assert(ok === true, 'AC14: acquireWrapLock SUCCEEDS with an empty session id');
  assert(lib.readWrapLockOwnerV2(cwd).session_id === null, 'AC14: the descriptor carries session_id:null');
  assert(fs.existsSync(lib.wrapLockPath(cwd)), 'AC14: the lock dir was NOT removed by the fail-closed catch');
}

// ---------------------------------------------------------------------------
// AC6 - the tokenless release path must stay open
// ---------------------------------------------------------------------------
console.log('\n--- AC6: tokenless release of a role:agent lock ---');
{
  const cwd = makeProject();
  lib.acquireWrapLock(cwd, '1\n' + new Date().toISOString(), 0,
    { role: 'agent', pid: null, token: 'some-token', sessionId: SID });
  const o = lib.readWrapLockOwnerV2(cwd);
  assert(o.pid === null,
    'AC6 precondition: the agent descriptor carries pid:null even WITH a session_id - putting a '
    + 'real pid here arms releaseWrapLock:o.pid!==null and /ds-wrap leaks a lock every run');
  assert(lib.releaseWrapLock(cwd) === 'released',
    "AC6: tokenless releaseWrapLock on a role:'agent' lock returns 'released'");
  assert(!fs.existsSync(lib.wrapLockPath(cwd)), 'AC6: the lock is actually gone');
}
{
  // Mirror of the predicted coupling: a real pid DOES arm the refuse branch.
  // This proves AC6 is testing a live property, not a constant.
  const cwd = makeProject();
  fs.mkdirSync(lib.wrapLockPath(cwd), { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(cwd), JSON.stringify(
    lib.makeLockDescriptor({ role: 'agent', pid: 1, sessionId: SID })), 'utf8');
  assert(lib.releaseWrapLock(cwd) === 'refused-not-owner',
    'AC6 coupling proof: an agent descriptor carrying a LIVE foreign pid IS refused tokenlessly');
}

// ---------------------------------------------------------------------------
// AC15 - the CLI flag, and the dead-env-var trap
// ---------------------------------------------------------------------------
console.log('\n--- AC15: --session-id flag and env-var trap ---');
{
  const cwd = makeProject();
  const out = execFileSync(process.execPath,
    [ACQUIRE, cwd, '--role=agent', '--no-wait', '--session-id=' + SID],
    { encoding: 'utf8' });
  assert(out.startsWith('acquired '), 'AC15: --session-id is accepted and the lock is acquired');
  assert(lib.readWrapLockOwnerV2(cwd).session_id === SID,
    'AC15: the CLI-supplied session id reaches the published descriptor');
}
{
  // Empty value must not break acquisition - this is the every-non-Claude-adapter path.
  const cwd = makeProject();
  const out = execFileSync(process.execPath,
    [ACQUIRE, cwd, '--role=agent', '--no-wait', '--session-id='],
    { encoding: 'utf8' });
  assert(out.startsWith('acquired '), 'AC15/AC14: --session-id= (empty) still acquires');
  assert(lib.readWrapLockOwnerV2(cwd).session_id === null, 'AC15: an empty value publishes session_id:null');
}
{
  // The helper self-heals an abandoned lock rather than reporting busy.
  const cwd = makeProject();
  fs.mkdirSync(lib.wrapLockPath(cwd), { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(cwd), JSON.stringify(
    lib.makeLockDescriptor({
      role: 'agent', pid: null,
      acquiredAt: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString(),
    })), 'utf8');
  const out = execFileSync(process.execPath,
    [ACQUIRE, cwd, '--role=agent', '--no-wait', '--session-id=' + SID],
    { encoding: 'utf8' });
  assert(out.indexOf('cleared-abandoned-lock') !== -1,
    'AC1/AC15: the acquire helper ANNOUNCES the self-heal (silence is the bug being fixed)');
  assert(out.indexOf('acquired ') !== -1, 'AC1/AC15: the helper then acquires the lock');
}
{
  // A LIVE lock is never stolen by the acquire-side self-heal.
  const cwd = makeProject();
  fs.mkdirSync(lib.wrapLockPath(cwd), { recursive: true });
  const hb = lib.heartbeatPath(cwd, SID);
  fs.mkdirSync(path.dirname(hb), { recursive: true });
  fs.writeFileSync(hb, '', 'utf8');
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(cwd), JSON.stringify(
    lib.makeLockDescriptor({
      role: 'agent', pid: null, sessionId: SID,
      acquiredAt: new Date(Date.now() - 45 * 60 * 1000).toISOString(),
    })), 'utf8');
  let code = 0;
  let out = '';
  try {
    out = execFileSync(process.execPath,
      [ACQUIRE, cwd, '--role=agent', '--no-wait', '--session-id=other-session'],
      { encoding: 'utf8' });
  } catch (e) {
    code = e.status;
    out = String(e.stdout || '');
  }
  assert(code === 5 && out.startsWith('busy '),
    'AC2: a 45m lock with a FRESH heartbeat is reported busy, never stolen');
  assert(fs.existsSync(lib.wrapLockOwnerJsonPath(cwd)), 'AC2: the live descriptor is intact');
}
{
  // The env-var trap, pinned at the source level.
  //
  // Scoped to a READ SITE, not to any mention of the name. A bare-name gate would
  // trip on the very comment that documents the trap ("AGENTIC_SESSION_ID and
  // CLAUDE_SESSION_UUID are both measured EMPTY - do not read them"), which is a
  // gate that fails on its own correct implementation. What must never appear is
  // a shell expansion, a process.env access, or an os.environ.get of either name.
  const DEAD_VAR_READ = /(?:\$\{?|process\.env(?:iron)?\.|environ\.get\(\s*['"]|env\[['"])(?:AGENTIC_SESSION_ID|CLAUDE_SESSION_UUID)/;
  const acquireSrc = fs.readFileSync(ACQUIRE, 'utf8');
  const wrapMd = fs.readFileSync(path.join(REPO, 'content', 'commands', 'ds-wrap.md'), 'utf8');
  for (const [label, src] of [['bin/agentic-wrap-acquire-lock', acquireSrc], ['content/commands/ds-wrap.md', wrapMd]]) {
    assert(!DEAD_VAR_READ.test(src),
      `AC15: ${label} READS neither dead env var from the agentic-migrate precedent (both measured empty)`);
  }
  // Prove the gate is live in the other direction - it must catch a real read.
  assert(DEAD_VAR_READ.test('--session-id="$AGENTIC_SESSION_ID"')
    && DEAD_VAR_READ.test('os.environ.get("CLAUDE_SESSION_UUID")')
    && DEAD_VAR_READ.test('process.env.AGENTIC_SESSION_ID')
    && !DEAD_VAR_READ.test('AGENTIC_SESSION_ID is empty; do not use it'),
    'AC15 gate self-check: the pattern catches real reads and ignores prose mentions');
  assert(DEAD_VAR_READ.test('--session-id="$CLAUDE_CODE_SESSION_ID"') === false,
    'AC15 gate self-check: the CORRECT variable is not matched by the dead-var pattern');
  const invocations = (wrapMd.match(/agentic-wrap-acquire-lock[^\n]*--session-id/g) || []).length;
  assert(invocations >= 2,
    `AC15: --session-id appears on the SAME LINE as at least 2 acquire invocations (got ${invocations})`);
  assert(wrapMd.indexOf('CLAUDE_CODE_SESSION_ID') !== -1,
    'AC15: ds-wrap.md sources the id from CLAUDE_CODE_SESSION_ID');
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------
for (const d of tmpDirs) {
  try { fs.rmSync(d, { recursive: true, force: true }); } catch (_) { /* best-effort */ }
}

console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
