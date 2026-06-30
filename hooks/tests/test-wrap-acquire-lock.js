#!/usr/bin/env node
'use strict';

/**
 * Unit tests for bin/agentic-wrap-acquire-lock.
 *
 * Tests the CLI helper that poll-waits for the /wrap directory lock, exiting
 * when acquired or after a timeout. Six cases:
 *   1. acquire-when-free        - no lock; expect exit 0, stdout "acquired"
 *   2. blocked-then-acquired    - plant lock; release after ~1.5s; expect exit 0,
 *                                 stdout "acquired" AND at least one "waiting" line
 *   3. timeout                  - plant lock that stays; expect exit 2, "timeout"
 *   4. stale-needs-manual       - owner ts 31 min in the past; expect exit 4
 *   5. unreadable-owner         - empty owner file; expect exit 3
 *   6. symlink-portability      - invoke via symlink from non-repo cwd; expect exit 0
 *
 * Run with: node hooks/tests/test-wrap-acquire-lock.js
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');
const lib = require('../lib/wrap-marker.js');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SCRIPT_PATH = path.join(REPO_ROOT, 'bin', 'agentic-wrap-acquire-lock');

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

function makeTmp(prefix) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  tmpDirs.push(dir);
  return dir;
}

function plantLock(dir, ownerContent) {
  const lockDir = lib.wrapLockPath(dir);
  fs.mkdirSync(lockDir, { recursive: true });
  const owner = ownerContent !== undefined
    ? ownerContent
    : ('99999\n' + new Date().toISOString() + '\n');
  fs.writeFileSync(lib.wrapLockOwnerPath(dir), owner, 'utf8');
  return lockDir;
}

/**
 * Run the helper synchronously via execFileSync. Returns {stdout, exitCode}.
 * Never throws - always returns the exit code.
 */
function runHelper(scriptOrBin, args, extraOpts) {
  try {
    const stdout = execFileSync('node', [scriptOrBin, ...args], {
      encoding: 'utf8',
      timeout: 30000,
      ...extraOpts,
    });
    return { stdout: stdout || '', exitCode: 0 };
  } catch (e) {
    return { stdout: e.stdout || '', exitCode: e.status !== null ? e.status : -1 };
  }
}

// ---------------------------------------------------------------------------
// Pre-flight: script exists and is readable
// ---------------------------------------------------------------------------
console.log('\n[pre] script exists');
assert(fs.existsSync(SCRIPT_PATH), `bin/agentic-wrap-acquire-lock exists at ${SCRIPT_PATH}`);

// ---------------------------------------------------------------------------
// Case 1: acquire-when-free — no lock present
// ---------------------------------------------------------------------------
console.log('\n[1] acquire-when-free — no lock present');
{
  const tmp = makeTmp('wal-case1-');
  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=5000', '--poll-ms=500']);
  assert(exitCode === 0, `case 1: helper exited 0 (got: ${exitCode})`);
  assert(stdout.includes('acquired'), `case 1: stdout includes "acquired" (got: ${JSON.stringify(stdout)})`);
  // Clean up the lock we acquired
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 2: blocked-then-acquired-after-release
// Use spawnSync with a Node wrapper script that plants a lock, spawns the
// acquire helper in the background, waits 1.5s, releases the lock, then waits
// for the child to finish. All synchronous from the test runner's perspective.
// ---------------------------------------------------------------------------
console.log('\n[2] blocked-then-acquired-after-release');
{
  const tmp = makeTmp('wal-case2-');
  plantLock(tmp);

  // We run a small inline Node script that:
  //  - spawns agentic-wrap-acquire-lock as a child process
  //  - waits 1.5s via setTimeout, then releases the lock
  //  - waits for the child to exit
  //  - exits with the child's exit code + prints child stdout
  const wrapper = `
'use strict';
const { spawn } = require('child_process');
const lib = require(${JSON.stringify(path.join(REPO_ROOT, 'hooks', 'lib', 'wrap-marker.js'))});
const tmp = ${JSON.stringify(tmp)};
const scriptPath = ${JSON.stringify(SCRIPT_PATH)};
let out = '';
const child = spawn('node', [scriptPath, tmp, '--timeout-ms=10000', '--poll-ms=500'], {
  stdio: ['ignore', 'pipe', 'inherit'],
});
child.stdout.on('data', (d) => { out += d.toString(); });
child.on('exit', (code) => {
  process.stdout.write(out);
  process.exit(code || 0);
});
setTimeout(() => {
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}, 1500);
`;
  const result = spawnSync('node', ['-e', wrapper], {
    encoding: 'utf8',
    timeout: 20000,
  });

  const exitCode = result.status;
  const stdout = result.stdout || '';
  assert(exitCode === 0, `case 2: helper exited 0 after lock released (got: ${exitCode})`);
  assert(stdout.includes('acquired'), `case 2: stdout includes "acquired" (got: ${JSON.stringify(stdout)})`);
  assert(stdout.includes('waiting'), `case 2: stdout includes at least one "waiting" line (got: ${JSON.stringify(stdout)})`);
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 3: timeout — plant lock that stays; expect exit 2, stdout "timeout"
// ---------------------------------------------------------------------------
console.log('\n[3] timeout — lock stays planted');
{
  const tmp = makeTmp('wal-case3-');
  plantLock(tmp);
  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=1200', '--poll-ms=300'], {
    timeout: 10000,
  });
  assert(exitCode === 2, `case 3: exit code is 2 (timeout) (got: ${exitCode})`);
  assert(stdout.includes('timeout'), `case 3: stdout includes "timeout" (got: ${JSON.stringify(stdout)})`);
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 4: stale-needs-manual — owner ts 31 min in the past; expect exit 4
// Binary passes MAX_SAFE_INTEGER to acquireWrapLock so auto-clear never fires;
// the stale detection comes from reading owner.ts age in the binary.
// ---------------------------------------------------------------------------
console.log('\n[4] stale-needs-manual — owner ts 31 min old');
{
  const tmp = makeTmp('wal-case4-');
  const staleTs = new Date(Date.now() - 31 * 60 * 1000).toISOString();
  plantLock(tmp, '12345\n' + staleTs + '\n');

  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=5000', '--poll-ms=500'], {
    timeout: 10000,
  });
  assert(exitCode === 4, `case 4: exit code is 4 (stale-needs-manual) (got: ${exitCode})`);
  assert(stdout.includes('stale-needs-manual'), `case 4: stdout includes "stale-needs-manual" (got: ${JSON.stringify(stdout)})`);
  // The lock must still exist - the binary does NOT auto-remove it
  assert(fs.existsSync(lib.wrapLockPath(tmp)), 'case 4: lock still present (binary never auto-removes)');
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 5: unreadable-owner — empty owner file; expect exit 3
// ---------------------------------------------------------------------------
console.log('\n[5] unreadable-owner — empty owner file');
{
  const tmp = makeTmp('wal-case5-');
  // Create the lock directory manually, then write an EMPTY owner file.
  fs.mkdirSync(lib.wrapLockPath(tmp), { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerPath(tmp), '', 'utf8');

  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=5000', '--poll-ms=500'], {
    timeout: 10000,
  });
  assert(exitCode === 3, `case 5: exit code is 3 (unreadable-owner) (got: ${exitCode})`);
  assert(stdout.includes('unreadable-owner'), `case 5: stdout includes "unreadable-owner" (got: ${JSON.stringify(stdout)})`);
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 6: symlink-portability — invoke via symlink from non-repo cwd
// ---------------------------------------------------------------------------
console.log('\n[6] symlink-portability — invoke via symlink from non-repo cwd');
{
  const bindir = makeTmp('wal-bindir-');
  const proj = makeTmp('wal-proj-');
  const symlinkPath = path.join(bindir, 'agentic-wrap-acquire-lock');
  fs.symlinkSync(SCRIPT_PATH, symlinkPath);

  const { stdout, exitCode } = runHelper(symlinkPath, [proj, '--timeout-ms=5000', '--poll-ms=500'], {
    timeout: 10000,
  });
  assert(exitCode === 0, `case 6: symlinked helper exited 0 (got: ${exitCode})`);
  assert(stdout.includes('acquired'), `case 6: stdout includes "acquired" (got: ${JSON.stringify(stdout)})`);
  assert(!stdout.includes('MODULE_NOT_FOUND'), 'case 6: no MODULE_NOT_FOUND (lib resolved via symlink-aware __dirname)');
  // Clean up the acquired lock
  try { lib.releaseWrapLock(proj); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 7: NaN/unparseable-timestamp fall-through
// Owner file has a valid PID on line 0 but "not-a-date" on line 1.
// Date.parse("not-a-date") = NaN -> Number.isFinite(NaN) = false -> the
// stale-needs-manual (exit 4) branch must NOT fire. The binary must fall
// through to "waiting" and eventually time out (exit 2).
// Also asserts the lock dir is NOT removed (binary never auto-removes).
// ---------------------------------------------------------------------------
console.log('\n[7] NaN-timestamp — garbage line-1 must fall through to timeout, not exit 4');
{
  const tmp = makeTmp('wal-case7-');
  // Plant lock with a valid PID but unparseable timestamp on line 1.
  plantLock(tmp, '99999\nnot-a-date\n');

  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=1200', '--poll-ms=300'], {
    timeout: 10000,
  });
  assert(exitCode === 2, `case 7: exit code is 2 (timeout, not 4 stale) (got: ${exitCode})`);
  assert(stdout.includes('timeout'), `case 7: stdout includes "timeout" (got: ${JSON.stringify(stdout)})`);
  assert(stdout.includes('waiting'), `case 7: stdout includes at least one "waiting" line (got: ${JSON.stringify(stdout)})`);
  // Lock dir must still exist - binary must not remove it on NaN timestamp
  assert(fs.existsSync(lib.wrapLockPath(tmp)), 'case 7: lock dir still present (binary never auto-removes on NaN ts)');
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 8: bad-flag argument fallback
// Passing --timeout-ms=abc produces NaN from Number(). Verify the binary
// still acquires correctly (exit 0) when no lock is held, proving a NaN
// timeout does not cause a crash or instant-exit misbehavior.
// ---------------------------------------------------------------------------
console.log('\n[8] bad-flag fallback — --timeout-ms=abc must not crash; should still acquire');
{
  const tmp = makeTmp('wal-case8-');
  // No lock planted; binary should acquire immediately regardless of the bad flag.
  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=abc', '--poll-ms=300'], {
    timeout: 10000,
  });
  assert(exitCode === 0, `case 8: exit code is 0 (acquired despite bad --timeout-ms) (got: ${exitCode})`);
  assert(stdout.includes('acquired'), `case 8: stdout includes "acquired" (got: ${JSON.stringify(stdout)})`);
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------
for (const d of tmpDirs) {
  try { fs.rmSync(d, { recursive: true, force: true }); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
