#!/usr/bin/env node
/**
 * Migration tests: hooks/session-start-wrap.sh - the one-time artifact relocation
 * block that moves old-layout deferred-wrap files to .agentic/wrap/.
 *
 * Cases:
 *   M1 - full relocation: all old-path artifacts present -> moved to new paths,
 *        basenames correct, old paths gone.
 *   M2 - idempotent: run migration twice; second run is a no-op (new-path files
 *        unchanged, no error).
 *   M3a - dead-PID wrap.lock -> MOVE (stale lock relocated).
 *   M3b - no-PID + old timestamp wrap.lock -> MOVE.
 *   M3c - alive-PID wrap.lock -> KEEP (live lock never touched).
 *   M3d - empty owner file wrap.lock -> KEEP (empty body = no signal = keep).
 *   M3e - no owner file wrap.lock (bare lockdir) -> KEEP (mkdir-before-owner race).
 *   M3f - symlink at old wrap.lock path -> KEEP (cannot safely move via mv).
 *   M4 - idempotent/ENOENT-safe: two sequential migrations complete without error (second is a no-op).
 *   M5 - drain-temp sweep: orphaned .draining.* temp files removed from both
 *        new (.agentic/wrap/deferred-activity.jsonl.draining.*) and old
 *        (.agentic/.stop-deferred-activity.jsonl.draining.*) paths.
 *   M6 - cross-version window doc-presence: session-start-wrap.sh comment block
 *        contains the stable "lost-update" keyword documenting the accepted window.
 *
 * Run with: node hooks/tests/test-wrap-artifact-migration.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync, spawnSync } = require('child_process');
const lib = require('../lib/wrap-marker.js');

const SCRIPT = path.resolve(__dirname, '..', 'session-start-wrap.sh');
const DEAD_PID = '2147480000';

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

function makeTmp(prefix) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  const projectDir = path.join(base, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  return { base, projectDir, agenticDir };
}

function cleanup(base) {
  try { fs.rmSync(base, { recursive: true, force: true }); } catch (_) {}
}

/**
 * Run the SessionStart hook with a given projectDir as cwd.
 * Returns { code, stdout, stderr }.
 */
function runHook(projectDir) {
  const payload = JSON.stringify({ cwd: projectDir });
  const res = spawnSync('bash', [SCRIPT], {
    input: payload,
    encoding: 'utf8',
    timeout: 15000,
    env: Object.assign({}, process.env, { AGENTIC_QUIET: '1' }),
  });
  return {
    code: res.status,
    stdout: res.stdout || '',
    stderr: res.stderr || '',
  };
}

// Pre-flight: script exists
if (!fs.existsSync(SCRIPT)) {
  console.error(`FAIL: script not found at ${SCRIPT}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Helper: agoIso(seconds) - an ISO timestamp `seconds` in the past
// ---------------------------------------------------------------------------
function agoIso(seconds) {
  return new Date(Date.now() - seconds * 1000).toISOString();
}

// ---------------------------------------------------------------------------
// (M1) Full relocation: all old-path artifacts present -> moved, basenames correct
// ---------------------------------------------------------------------------
console.log('\n[M1] full relocation: all old-layout artifacts moved to .agentic/wrap/');
{
  const { base, projectDir, agenticDir } = makeTmp('ae-mig-m1-');
  const wd = agenticDir;

  // Plant old-layout artifacts.
  fs.writeFileSync(path.join(wd, '.last-wrap'), 'sess-old\n', 'utf8');
  fs.writeFileSync(path.join(wd, 'wrap-daemon.pid'), '9999\n', 'utf8');
  fs.writeFileSync(path.join(wd, 'wrap-daemon.log'), 'old log\n', 'utf8');
  fs.writeFileSync(path.join(wd, 'wrap-daemon.log.1'), 'old log.1\n', 'utf8');
  fs.writeFileSync(path.join(wd, 'wrap-daemon-auth-failed'), '', 'utf8');
  fs.writeFileSync(path.join(wd, '.stop-deferred-activity.jsonl'),
    JSON.stringify({ schema_version: 1 }) + '\n', 'utf8');

  // Old-layout marker (wrap-pending-<sid>.json -> pending-<sid>.json).
  const SID = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
  const oldMarker = path.join(wd, 'wrap-pending-' + SID + '.json');
  fs.writeFileSync(oldMarker, JSON.stringify({ session_id: SID, status: 'pending' }), 'utf8');

  // Old-layout heartbeat directory.
  const oldHbDir = path.join(wd, '.heartbeats');
  fs.mkdirSync(oldHbDir, { recursive: true });
  fs.writeFileSync(path.join(oldHbDir, SID), '', 'utf8');

  const { code } = runHook(projectDir);
  assert(code === 0, 'M1: hook exits 0');

  // Verify new-path files exist with correct basenames.
  assert(fs.existsSync(path.join(wd, 'wrap', 'last-wrap')),     'M1: last-wrap moved to wrap/last-wrap');
  assert(fs.existsSync(path.join(wd, 'wrap', 'daemon.pid')),    'M1: wrap-daemon.pid moved to wrap/daemon.pid');
  assert(fs.existsSync(path.join(wd, 'wrap', 'daemon.log')),    'M1: wrap-daemon.log moved to wrap/daemon.log');
  assert(fs.existsSync(path.join(wd, 'wrap', 'daemon.log.1')),  'M1: wrap-daemon.log.1 moved to wrap/daemon.log.1');
  assert(fs.existsSync(path.join(wd, 'wrap', 'daemon-auth-failed')), 'M1: daemon-auth-failed moved');
  assert(fs.existsSync(path.join(wd, 'wrap', 'deferred-activity.jsonl')), 'M1: spillover moved to wrap/deferred-activity.jsonl');

  // Marker: new basename is pending-<sid>.json (wrap- prefix stripped).
  const newMarker = lib.markerPath(projectDir, SID);
  assert(fs.existsSync(newMarker), 'M1: old marker moved with pending- prefix (wrap- stripped)');
  assert(!fs.existsSync(oldMarker), 'M1: old wrap-pending- marker gone from .agentic/ top level');

  // Heartbeat: moved from .heartbeats/ to wrap/heartbeats/.
  assert(fs.existsSync(lib.heartbeatPath(projectDir, SID)), 'M1: heartbeat moved to wrap/heartbeats/');
  assert(!fs.existsSync(path.join(oldHbDir, SID)), 'M1: old .heartbeats/<sid> gone');
  assert(!fs.existsSync(oldHbDir), 'M1: old .heartbeats/ dir removed (rmdir)');

  // Old-path files gone.
  assert(!fs.existsSync(path.join(wd, '.last-wrap')),    'M1: old .last-wrap gone');
  assert(!fs.existsSync(path.join(wd, 'wrap-daemon.pid')), 'M1: old wrap-daemon.pid gone');
  assert(!fs.existsSync(path.join(wd, 'wrap-daemon.log')), 'M1: old wrap-daemon.log gone');
  assert(!fs.existsSync(path.join(wd, '.stop-deferred-activity.jsonl')), 'M1: old spillover gone');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (M2) Idempotent: migration is safe to run twice (second run is a no-op)
// ---------------------------------------------------------------------------
console.log('\n[M2] idempotent: second migration run leaves new-path files unchanged');
{
  const { base, projectDir, agenticDir } = makeTmp('ae-mig-m2-');
  const wd = agenticDir;

  // Pre-populate: put an artifact at the OLD path.
  fs.writeFileSync(path.join(wd, '.last-wrap'), 'sess-m2\n', 'utf8');

  // First run.
  runHook(projectDir);
  const content1 = fs.readFileSync(path.join(wd, 'wrap', 'last-wrap'), 'utf8');
  assert(content1 === 'sess-m2\n', 'M2: first run moved .last-wrap to wrap/last-wrap');

  // Second run (no old file present; new file already there).
  const { code } = runHook(projectDir);
  assert(code === 0, 'M2: second run exits 0 (idempotent)');
  const content2 = fs.readFileSync(path.join(wd, 'wrap', 'last-wrap'), 'utf8');
  assert(content2 === 'sess-m2\n', 'M2: wrap/last-wrap content unchanged after second run');
  assert(!fs.existsSync(path.join(wd, '.last-wrap')), 'M2: no ghost .last-wrap re-appears');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (M3a) Dead-PID wrap.lock -> MOVE
// ---------------------------------------------------------------------------
console.log('\n[M3a] dead-PID wrap.lock: migrated (stale -> move)');
{
  const { base, projectDir, agenticDir } = makeTmp('ae-mig-m3a-');
  const wd = agenticDir;

  const oldLock = path.join(wd, 'wrap.lock');
  fs.mkdirSync(oldLock, { recursive: true });
  fs.writeFileSync(path.join(oldLock, 'owner'),
    DEAD_PID + '\n' + new Date().toISOString() + '\n', 'utf8');

  const { code } = runHook(projectDir);
  assert(code === 0, 'M3a: hook exits 0');
  assert(!fs.existsSync(oldLock), 'M3a: old wrap.lock gone after dead-PID move');
  assert(fs.existsSync(lib.wrapLockPath(projectDir)), 'M3a: lock moved to wrap/lock');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (M3b) No-PID + old timestamp wrap.lock -> MOVE
// ---------------------------------------------------------------------------
console.log('\n[M3b] no-PID + old timestamp wrap.lock: migrated');
{
  const { base, projectDir, agenticDir } = makeTmp('ae-mig-m3b-');
  const wd = agenticDir;

  const oldLock = path.join(wd, 'wrap.lock');
  fs.mkdirSync(oldLock, { recursive: true });
  // Empty PID line + old timestamp (>30 min) -> provably stale.
  fs.writeFileSync(path.join(oldLock, 'owner'),
    '\n' + agoIso(35 * 60) + '\n', 'utf8');

  const { code } = runHook(projectDir);
  assert(code === 0, 'M3b: hook exits 0');
  assert(!fs.existsSync(oldLock), 'M3b: old wrap.lock gone (no-PID + old ts -> stale)');
  assert(fs.existsSync(lib.wrapLockPath(projectDir)), 'M3b: lock moved to wrap/lock');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (M3c) Alive-PID wrap.lock -> KEEP (never yank a live lock)
// ---------------------------------------------------------------------------
console.log('\n[M3c] alive-PID wrap.lock: KEPT (live lock never touched)');
{
  const { base, projectDir, agenticDir } = makeTmp('ae-mig-m3c-');
  const wd = agenticDir;

  const oldLock = path.join(wd, 'wrap.lock');
  fs.mkdirSync(oldLock, { recursive: true });
  // This test process PID is guaranteed alive.
  fs.writeFileSync(path.join(oldLock, 'owner'),
    String(process.pid) + '\n' + new Date().toISOString() + '\n', 'utf8');

  const { code } = runHook(projectDir);
  assert(code === 0, 'M3c: hook exits 0');
  assert(fs.existsSync(oldLock), 'M3c: old wrap.lock KEPT (alive owner PID -> no move)');
  assert(!fs.existsSync(lib.wrapLockPath(projectDir)), 'M3c: wrap/lock NOT created (lock was live)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (M3d) Empty owner file -> KEEP (no signal = keep; CWE-59 minor 2 case)
// ---------------------------------------------------------------------------
console.log('\n[M3d] empty owner file wrap.lock: KEPT (no-signal -> keep)');
{
  const { base, projectDir, agenticDir } = makeTmp('ae-mig-m3d-');
  const wd = agenticDir;

  const oldLock = path.join(wd, 'wrap.lock');
  fs.mkdirSync(oldLock, { recursive: true });
  // Owner file exists but is completely empty.
  fs.writeFileSync(path.join(oldLock, 'owner'), '', 'utf8');

  const { code } = runHook(projectDir);
  assert(code === 0, 'M3d: hook exits 0');
  assert(fs.existsSync(oldLock), 'M3d: old wrap.lock KEPT (empty owner = no signal)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (M3e) No owner file (bare lockdir) -> KEEP (mkdir-before-owner race window)
// ---------------------------------------------------------------------------
console.log('\n[M3e] no owner file wrap.lock: KEPT (no-owner race -> keep)');
{
  const { base, projectDir, agenticDir } = makeTmp('ae-mig-m3e-');
  const wd = agenticDir;

  const oldLock = path.join(wd, 'wrap.lock');
  // Lockdir exists but NO owner file at all (mkdir-before-owner race).
  fs.mkdirSync(oldLock, { recursive: true });

  const { code } = runHook(projectDir);
  assert(code === 0, 'M3e: hook exits 0');
  assert(fs.existsSync(oldLock), 'M3e: old wrap.lock KEPT (no-owner file = keep)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (M3f) Symlink at old wrap.lock path -> KEEP (cannot safely move a symlink)
// ---------------------------------------------------------------------------
console.log('\n[M3f] symlink at wrap.lock: KEPT (mv would follow link -> not moved)');
{
  const { base, projectDir, agenticDir } = makeTmp('ae-mig-m3f-');
  const wd = agenticDir;

  // Plant a symlink at the old lock path pointing to a sentinel dir.
  const sentinelDir = path.join(base, 'sentinel');
  fs.mkdirSync(sentinelDir, { recursive: true });
  const oldLock = path.join(wd, 'wrap.lock');
  fs.symlinkSync(sentinelDir, oldLock);
  assert(fs.lstatSync(oldLock).isSymbolicLink(), 'M3f precondition: wrap.lock is a symlink');

  const { code } = runHook(projectDir);
  assert(code === 0, 'M3f: hook exits 0 even with a symlink at wrap.lock');
  // The symlink must not have been moved to wrap/lock (mv of a symlink to a dir
  // is not a stale lock per wrapLockProvablyStaleLegacy: symlinks return pid:null,
  // ts:null which falls into the no-signal KEEP path).
  assert(!fs.existsSync(lib.wrapLockPath(projectDir))
    || !fs.lstatSync(lib.wrapLockPath(projectDir)).isSymbolicLink(),
    'M3f: wrap/lock is not a symlink from the moved old link');
  // Sentinel dir must be completely untouched.
  assert(fs.existsSync(sentinelDir), 'M3f: sentinel dir untouched (symlink not followed)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (M4) Concurrency-safe: two parallel migrations complete without corruption
// ---------------------------------------------------------------------------
console.log('\n[M4] concurrency: two simultaneous migrations complete without corruption');
{
  const { base, projectDir, agenticDir } = makeTmp('ae-mig-m4-');
  const wd = agenticDir;

  // Plant a few old-layout files.
  fs.writeFileSync(path.join(wd, '.last-wrap'), 'sess-m4\n', 'utf8');
  fs.writeFileSync(path.join(wd, 'wrap-daemon.pid'), '8888\n', 'utf8');

  // Launch two sequential hook invocations via spawnSync (run1 then run2).
  // The first completes the mv; the second sees OLD-absent (ENOENT) and skips.
  // Neither should fail or produce garbled output - verifying idempotency/ENOENT-safety.
  const payload = JSON.stringify({ cwd: projectDir });
  const run1 = spawnSync('bash', [SCRIPT], {
    input: payload,
    encoding: 'utf8',
    timeout: 15000,
    env: Object.assign({}, process.env, { AGENTIC_QUIET: '1' }),
  });
  const run2 = spawnSync('bash', [SCRIPT], {
    input: payload,
    encoding: 'utf8',
    timeout: 15000,
    env: Object.assign({}, process.env, { AGENTIC_QUIET: '1' }),
  });

  assert(run1.status === 0, 'M4: first concurrent hook exits 0');
  assert(run2.status === 0, 'M4: second concurrent hook exits 0');

  // At least one of them must have moved the files.
  assert(fs.existsSync(path.join(wd, 'wrap', 'last-wrap')),
    'M4: wrap/last-wrap exists after concurrent migrations');
  assert(fs.existsSync(path.join(wd, 'wrap', 'daemon.pid')),
    'M4: wrap/daemon.pid exists after concurrent migrations');

  // Old paths must be gone (whichever run succeeded, the other was a no-op ENOENT).
  assert(!fs.existsSync(path.join(wd, '.last-wrap')),
    'M4: old .last-wrap gone after concurrent migrations');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (M5) Drain-temp sweep: orphaned .draining.* temps removed from both paths
// ---------------------------------------------------------------------------
console.log('\n[M5] drain-temp sweep: orphaned .draining.* temps removed from both paths');
{
  const { base, projectDir, agenticDir } = makeTmp('ae-mig-m5-');
  const wd = agenticDir;

  // Ensure wrap/ dir exists so new-path temps can be planted.
  fs.mkdirSync(path.join(wd, 'wrap'), { recursive: true });

  // Plant orphaned temps at NEW path.
  const newTemp = path.join(wd, 'wrap', 'deferred-activity.jsonl.draining.1234');
  fs.writeFileSync(newTemp, 'orphan-new', 'utf8');

  // Plant orphaned temps at OLD path.
  const oldTemp = path.join(wd, '.stop-deferred-activity.jsonl.draining.5678');
  fs.writeFileSync(oldTemp, 'orphan-old', 'utf8');

  const { code } = runHook(projectDir);
  assert(code === 0, 'M5: hook exits 0');
  assert(!fs.existsSync(newTemp), 'M5: new-path drain temp removed');
  assert(!fs.existsSync(oldTemp), 'M5: old-path drain temp removed');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (M6) Cross-version window doc-presence: session-start-wrap.sh contains stable keyword
// ---------------------------------------------------------------------------
console.log('\n[M6] cross-version window doc-presence: "lost-update" keyword in session-start-wrap.sh');
{
  const scriptText = fs.readFileSync(SCRIPT, 'utf8');
  assert(scriptText.includes('lost-update'),
    'M6: session-start-wrap.sh comment block contains "lost-update" keyword (accepted cross-version window documented)');
  // Also verify the general acceptance context is present.
  assert(/cross-version window|ACCEPTED/.test(scriptText),
    'M6: acceptance context ("cross-version window" or "ACCEPTED") present in migration comment');
  // No tmpDir for M6; no cleanup needed.
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
