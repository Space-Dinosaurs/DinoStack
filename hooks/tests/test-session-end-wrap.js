#!/usr/bin/env node
/**
 * Smoke tests: hooks/session-end-wrap.js - the SessionEnd hook (U2).
 *
 * Covers architect-plan verification-gate cases:
 *   (1) finalize-on-terminal-reason writes `ready` (no branch/sha).
 *   (2) reason:"resume" does NOT finalize - the marker stays `pending`
 *       (CRITICAL-A: never auto-wrapped; manual /wrap recovers).
 *   (3) a stale `pending` marker is NEVER auto-promoted by any SessionEnd path
 *       (only a terminal reason on a pending marker promotes; resume / unknown
 *       / absent-reason leave it pending).
 *   (5 / MAJOR-3) a late terminal SessionEnd after `ready` does NOT regress
 *       ready -> pending.
 *   (13 portion) under AGENTIC_WRAP_DAEMON=1 the hook exits 0 WITHOUT finalize or
 *       launch (loop-guard).
 *   plus: heartbeat removed on terminal finalize, retained on resume; fail-open on
 *       malformed / empty stdin.
 *
 * The `deferred_wrap_daemon` toggle is left UNSET (no config) throughout, so the
 * hook never launches a real daemon - these tests are hermetic (no `claude`, no
 * network, fake project dirs under the OS tmpdir, realpath'd for safeCwd).
 *
 * Run with: node hooks/tests/test-session-end-wrap.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');
const lib = require('../lib/wrap-marker.js');

const hookScript = path.resolve(__dirname, '..', 'session-end-wrap.js');
if (!fs.existsSync(hookScript)) {
  console.error(`FAIL: hook not found at ${hookScript}`);
  process.exit(1);
}

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
  const heartbeatDir = path.join(agenticDir, 'wrap', 'heartbeats');
  fs.mkdirSync(heartbeatDir, { recursive: true });
  return { base, projectDir, agenticDir, heartbeatDir };
}

function cleanup(base) {
  try { fs.rmSync(base, { recursive: true, force: true }); } catch (_) {}
}

function writeMarkerRaw(agenticDir, sessionId, overrides) {
  const projectDir = path.dirname(agenticDir);
  const p = lib.markerPath(projectDir, sessionId);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const marker = Object.assign({
    schema_version: 3,
    session_id: sessionId,
    staged_at: new Date().toISOString(),
    status: 'pending',
    claimed_by: null,
    claimed_kind: null,
    claimed_at: null,
    attempts: 0,
    project_root: projectDir,
    last_error: null,
  }, overrides || {});
  fs.writeFileSync(p, JSON.stringify(marker, null, 2), 'utf8');
  return marker;
}

function readMarker(agenticDir, sessionId) {
  const p = lib.markerPath(path.dirname(agenticDir), sessionId);
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return null; }
}

function touchHeartbeat(heartbeatDir, sessionId) {
  fs.writeFileSync(path.join(heartbeatDir, sessionId), '', 'utf8');
}

function heartbeatExists(heartbeatDir, sessionId) {
  return fs.existsSync(path.join(heartbeatDir, sessionId));
}

/**
 * Run the SessionEnd hook with a raw stdin string and an optional extra env. The
 * toggle is unset (no config file) so no daemon launches. Returns the exit code
 * (the hook always exits 0; a throw here is a test failure).
 */
function runHook(projectDir, rawStdin, extraEnv) {
  const env = Object.assign({}, process.env, extraEnv || {});
  // The guard must never leak in from a parent run; only set it when extraEnv asks.
  if (!extraEnv || extraEnv.AGENTIC_WRAP_DAEMON === undefined) {
    delete env.AGENTIC_WRAP_DAEMON;
  }
  try {
    execSync(`node "${hookScript}"`, {
      input: rawStdin,
      encoding: 'utf8',
      env,
      cwd: projectDir,
      timeout: 10000,
      stdio: ['pipe', 'pipe', 'ignore'],
    });
    return 0;
  } catch (err) {
    return (err && typeof err.status === 'number') ? err.status : 1;
  }
}

function payload(obj) {
  return JSON.stringify(obj);
}

const TERMINAL_REASONS = ['clear', 'logout', 'prompt_input_exit', 'bypass_permissions_disabled', 'other'];

// ---------------------------------------------------------------------------
// (1) finalize-on-terminal-reason writes `ready` (no branch/sha)
// ---------------------------------------------------------------------------
console.log('\n[1] terminal reason finalizes a pending marker to ready (no branch/sha)');
{
  for (const reason of TERMINAL_REASONS) {
    const { base, projectDir, agenticDir } = makeProject('ae-se-fin-');
    const SID = '11111111-1111-1111-1111-111111111111';
    writeMarkerRaw(agenticDir, SID, { status: 'pending' });

    const code = runHook(projectDir, payload({
      session_id: SID, cwd: projectDir, hook_event_name: 'SessionEnd', reason,
    }));
    assert(code === 0, `hook exits 0 on reason='${reason}'`);
    const m = readMarker(agenticDir, SID);
    assert(m && m.status === 'ready', `reason='${reason}' finalizes pending -> ready`);
    assert(m && !('branch' in m) && !('head_sha' in m),
      `reason='${reason}' ready marker carries no branch/head_sha`);
    cleanup(base);
  }
}

// ---------------------------------------------------------------------------
// (2)+(3) reason:"resume" does NOT finalize; stale pending never auto-promoted
// ---------------------------------------------------------------------------
console.log('\n[2/3] reason=resume (and unknown / absent) leaves the marker pending');
{
  for (const reason of ['resume', 'unknown_reason', '']) {
    const { base, projectDir, agenticDir } = makeProject('ae-se-res-');
    const SID = '22222222-2222-2222-2222-222222222222';
    // A deliberately STALE pending marker (staged long ago) - must NOT be promoted.
    writeMarkerRaw(agenticDir, SID, {
      status: 'pending', staged_at: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(),
    });

    const obj = { session_id: SID, cwd: projectDir, hook_event_name: 'SessionEnd' };
    if (reason !== '') obj.reason = reason;
    const code = runHook(projectDir, payload(obj));

    assert(code === 0, `hook exits 0 on reason='${reason || '(absent)'}'`);
    const m = readMarker(agenticDir, SID);
    assert(m && m.status === 'pending',
      `reason='${reason || '(absent)'}' leaves the stale marker pending (CRITICAL-A: not auto-promoted)`);
    cleanup(base);
  }
}

// ---------------------------------------------------------------------------
// (5 / MAJOR-3) late terminal SessionEnd after `ready` does NOT regress
// ---------------------------------------------------------------------------
console.log('\n[5/MAJOR-3] a late terminal SessionEnd does NOT regress ready -> pending');
{
  const { base, projectDir, agenticDir } = makeProject('ae-se-late-');
  const SID = '33333333-3333-3333-3333-333333333333';
  writeMarkerRaw(agenticDir, SID, { status: 'ready' });

  const code = runHook(projectDir, payload({
    session_id: SID, cwd: projectDir, hook_event_name: 'SessionEnd', reason: 'logout',
  }));
  assert(code === 0, 'hook exits 0 on a late terminal SessionEnd');
  assert(readMarker(agenticDir, SID).status === 'ready',
    'late terminal SessionEnd leaves ready unchanged (no regress to pending)');

  // Also: a late terminal SessionEnd over an in_progress marker must not downgrade.
  writeMarkerRaw(agenticDir, SID, { status: 'in_progress', claimed_kind: 'daemon', claimed_by: process.pid, claimed_at: new Date().toISOString(), attempts: 1 });
  runHook(projectDir, payload({ session_id: SID, cwd: projectDir, hook_event_name: 'SessionEnd', reason: 'other' }));
  assert(readMarker(agenticDir, SID).status === 'in_progress',
    'late terminal SessionEnd leaves in_progress unchanged (no downgrade)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (13) loop-guard: AGENTIC_WRAP_DAEMON=1 -> exit 0, no finalize, no launch
// ---------------------------------------------------------------------------
console.log('\n[13] under AGENTIC_WRAP_DAEMON=1 the hook no-ops (no finalize, no heartbeat removal)');
{
  const { base, projectDir, agenticDir, heartbeatDir } = makeProject('ae-se-guard-');
  const SID = '44444444-4444-4444-4444-444444444444';
  writeMarkerRaw(agenticDir, SID, { status: 'pending' });
  touchHeartbeat(heartbeatDir, SID);

  const code = runHook(projectDir, payload({
    session_id: SID, cwd: projectDir, hook_event_name: 'SessionEnd', reason: 'logout',
  }), { AGENTIC_WRAP_DAEMON: '1' });

  assert(code === 0, 'hook exits 0 under the loop-guard');
  assert(readMarker(agenticDir, SID).status === 'pending',
    'guarded hook does NOT finalize (marker stays pending)');
  assert(heartbeatExists(heartbeatDir, SID),
    'guarded hook does NOT remove the heartbeat');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// heartbeat removed on terminal finalize; retained on resume
// ---------------------------------------------------------------------------
console.log('\n[hb] heartbeat removed on terminal finalize, retained on resume');
{
  // terminal -> heartbeat removed.
  const { base, projectDir, agenticDir, heartbeatDir } = makeProject('ae-se-hb1-');
  const SID = '55555555-5555-5555-5555-555555555555';
  writeMarkerRaw(agenticDir, SID, { status: 'pending' });
  touchHeartbeat(heartbeatDir, SID);
  runHook(projectDir, payload({ session_id: SID, cwd: projectDir, hook_event_name: 'SessionEnd', reason: 'clear' }));
  assert(!heartbeatExists(heartbeatDir, SID), 'heartbeat removed on terminal finalize');
  cleanup(base);

  // resume -> heartbeat retained (session may continue).
  const p2 = makeProject('ae-se-hb2-');
  const SID2 = '66666666-6666-6666-6666-666666666666';
  writeMarkerRaw(p2.agenticDir, SID2, { status: 'pending' });
  touchHeartbeat(p2.heartbeatDir, SID2);
  runHook(p2.projectDir, payload({ session_id: SID2, cwd: p2.projectDir, hook_event_name: 'SessionEnd', reason: 'resume' }));
  assert(heartbeatExists(p2.heartbeatDir, SID2), 'heartbeat retained on resume (non-terminal)');
  cleanup(p2.base);
}

// ---------------------------------------------------------------------------
// fail-open on malformed / empty / non-object stdin
// ---------------------------------------------------------------------------
console.log('\n[fo] fail-open: malformed / empty / non-object stdin all exit 0 with no side effects');
{
  const { base, projectDir, agenticDir } = makeProject('ae-se-fo-');
  const SID = '77777777-7777-7777-7777-777777777777';
  writeMarkerRaw(agenticDir, SID, { status: 'pending' });

  for (const [label, raw] of [
    ['empty stdin', ''],
    ['whitespace stdin', '   \n  '],
    ['malformed JSON', '{not valid json'],
    ['JSON array (non-object handling)', '[1,2,3]'],
    ['JSON null', 'null'],
    ['object missing cwd', payload({ session_id: SID, reason: 'logout' })],
  ]) {
    const code = runHook(projectDir, raw);
    assert(code === 0, `exit 0 on ${label}`);
  }
  // None of the malformed inputs should have finalized the pending marker.
  assert(readMarker(agenticDir, SID).status === 'pending',
    'no malformed input finalized the marker (all left it pending)');
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
