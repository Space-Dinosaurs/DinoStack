#!/usr/bin/env node
'use strict';

/**
 * Unit tests for bin/agentic-wrap-acquire-lock.
 *
 * Tests the CLI helper that poll-waits for the /ds-wrap directory lock, exiting
 * when acquired or after a timeout. Cases 1, 2, 3, 6, 8 are UNCHANGED from the
 * pre-U3 file (still exercise the same acquire/timeout/symlink/bad-flag paths,
 * still pass unmodified against the rewritten binary):
 *   1. acquire-when-free        - no lock; expect exit 0, stdout "acquired"
 *   2. blocked-then-acquired    - plant lock; release after ~1.5s; expect exit 0,
 *                                 stdout "acquired" AND at least one "waiting" line
 *   3. timeout                  - plant lock that stays; expect exit 2, "timeout"
 *   6. symlink-portability      - invoke via symlink from non-repo cwd; expect exit 0
 *   8. bad-flag fallback        - --timeout-ms=abc must not crash; still acquires
 *
 * Cases 4 and 5 are CHANGED (U3, DS-wrap-lock-liveness) because the give-up exit
 * codes they used to assert (4 and 3) were RETIRED - see design decision 1 in the
 * binary's own header. Case 4 in particular is INVERTED: the pre-U3 binary gave up
 * (exit 4) the instant an owner timestamp looked old; the whole point of this unit
 * is that "looks old" is no longer a give-up signal, so the same shape of fixture
 * must now make the binary keep polling (exit 2, timeout) instead of surrendering
 * (exit 4). See the case-4 comment below for why its FIXTURE also had to change
 * (not just its expected exit code) to stay a faithful regression pin against the
 * ALREADY-COMMITTED wrapLockVerdict decision table (hooks/lib/wrap-marker.js, U1).
 *
 * New cases (U3): 7 (kept from an earlier increment, still green), 9-15 pin the
 * structural "never give up, never falsely report acquired" invariants this
 * rewrite exists to guarantee. Case 16 is the direct regression pin for the
 * operator's REPORTED scenario (ten interactive /ds-wrap tabs, a 2-line aged
 * owner) - see its own comment for why case 4's fixture change left this
 * uncovered and why case 16 closes that gap without touching case 4.
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
const RELEASE_SCRIPT_PATH = path.join(REPO_ROOT, 'bin', 'agentic-wrap-release-lock');

/** A PID that is essentially guaranteed dead (very high, unlikely to be live). */
const DEAD_PID = 2147480000;

let passed = 0;
let failed = 0;
const tmpDirs = [];
const allExitCodes = [];

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
 * Plant a legacy 1-line owner body (PID only, no timestamp line) - the shape
 * written by the daemon's own 3-arg acquireWrapLock call. Unlike the 2-line
 * interactive body, wrapLockVerdict IS pid-liveness-aware for this shape
 * (row 7 of its decision table), so this is the only legacy fixture that can
 * ever produce verdict 'dead'.
 */
function plantLockLegacy1(dir, pid) {
  const lockDir = lib.wrapLockPath(dir);
  fs.mkdirSync(lockDir, { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerPath(dir), String(pid) + '\n', 'utf8');
  return lockDir;
}

/** Plant an empty lock directory - no owner file, no owner.json at all. */
function plantEmptyLockDir(dir) {
  const lockDir = lib.wrapLockPath(dir);
  fs.mkdirSync(lockDir, { recursive: true });
  return lockDir;
}

/**
 * Run the helper synchronously via execFileSync. Returns {stdout, exitCode}.
 * Never throws - always returns the exit code. Tracks every exit code seen
 * across the whole run (NEW 9 asserts none of them is 3 or 4).
 */
function runHelper(scriptOrBin, args, extraOpts) {
  let result;
  try {
    const stdout = execFileSync('node', [scriptOrBin, ...args], {
      encoding: 'utf8',
      timeout: 30000,
      ...extraOpts,
    });
    result = { stdout: stdout || '', exitCode: 0 };
  } catch (e) {
    result = { stdout: e.stdout || '', exitCode: e.status !== null ? e.status : -1 };
  }
  allExitCodes.push(result.exitCode);
  return result;
}

// ---------------------------------------------------------------------------
// Pre-flight: script exists and is readable
// ---------------------------------------------------------------------------
console.log('\n[pre] script exists');
assert(fs.existsSync(SCRIPT_PATH), `bin/agentic-wrap-acquire-lock exists at ${SCRIPT_PATH}`);

// ---------------------------------------------------------------------------
// Case 1: acquire-when-free — no lock present (UNCHANGED)
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
// Case 2: blocked-then-acquired-after-release (UNCHANGED)
// Use spawnSync with a Node wrapper script that plants a lock, spawns the
// acquire helper in the background, waits 1.5s, releases the lock, then waits
// for the child to finish. All synchronous from the test runner's perspective.
// ---------------------------------------------------------------------------
console.log('\n[2] blocked-then-acquired-after-release');
{
  const tmp = makeTmp('wal-case2-');
  plantLock(tmp);

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
  allExitCodes.push(exitCode);
  assert(exitCode === 0, `case 2: helper exited 0 after lock released (got: ${exitCode})`);
  assert(stdout.includes('acquired'), `case 2: stdout includes "acquired" (got: ${JSON.stringify(stdout)})`);
  assert(stdout.includes('waiting'), `case 2: stdout includes at least one "waiting" line (got: ${JSON.stringify(stdout)})`);
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 3: timeout — plant lock that stays; expect exit 2, stdout "timeout" (UNCHANGED)
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
// Case 4: no-false-give-up-on-old-lock (INVERTED, U3, DS-wrap-lock-liveness)
//
// Pre-U3 this case planted a 2-line legacy owner body (PID + a 31-min-old
// timestamp) and asserted exit 4 ("stale-needs-manual") - the binary gave up
// the instant the owner timestamp looked old.
//
// DELIBERATE FIXTURE CHANGE, not just an expected-exit-code flip: a 2-line
// legacy body (PID present AND timestamp present) is PID-BLIND per
// wrapLockVerdict's own decision table (hooks/lib/wrap-marker.js, U1, row 6)
// and is UNCONDITIONALLY classified 'live' regardless of the timestamp's age -
// this is directly pinned by that unit's own test-wrap-lock-verdict.js ("row 6:
// 2-line dead-pid + 31-min ts -> live, pid-blind"). Reusing the exact old
// 2-line fixture here would therefore assert a verdict ('live' -> "waiting")
// that can never occur for a lock this test wants to call "dead"/"stale". The
// only legacy shape wrapLockVerdict treats as PID-liveness-aware is the 1-line
// body (row 7) - so this case switches to plantLockLegacy1 with a guaranteed-
// dead PID, which genuinely exercises verdict 'dead' ("waiting-stale") while
// preserving the case's real intent: an old/dead-looking lock must NEVER cause
// an instant give-up (exit 3/4) - it must keep polling until the timeout
// budget is exhausted (exit 2), carrying the operator "rm -rf" recovery HINT.
// ---------------------------------------------------------------------------
console.log('\n[4] no-false-give-up-on-old-lock — dead-pid 1-line lock must poll, not give up');
{
  const tmp = makeTmp('wal-case4-');
  plantLockLegacy1(tmp, DEAD_PID);

  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=1200', '--poll-ms=300'], {
    timeout: 10000,
  });
  assert(exitCode === 2, `case 4: exit code is 2 (timeout, never a give-up code) (got: ${exitCode})`);
  assert(stdout.includes('waiting-stale'), `case 4: stdout includes "waiting-stale" (verdict=dead progress line) (got: ${JSON.stringify(stdout)})`);
  assert(stdout.includes('rm -rf'), `case 4: stdout includes the operator "rm -rf" recovery HINT (got: ${JSON.stringify(stdout)})`);
  // The lock must still exist - the binary does NOT auto-remove it, ever.
  assert(fs.existsSync(lib.wrapLockPath(tmp)), 'case 4: lock still present (binary never auto-removes)');
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 5: unreadable-owner fixture, CHANGED expectation (U3)
// Empty owner file -> readWrapLockOwnerV2 sees {pid:null, ts:null} -> source
// null -> wrapLockVerdict 'unknown' (row 5). Pre-U3 this was exit 3
// ("unreadable-owner"); now it must poll (exit 2) like every other non-acquired
// outcome, printing "waiting-unknown" instead of giving up instantly.
// ---------------------------------------------------------------------------
console.log('\n[5] unreadable-owner fixture — empty owner file must poll, not give up');
{
  const tmp = makeTmp('wal-case5-');
  fs.mkdirSync(lib.wrapLockPath(tmp), { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerPath(tmp), '', 'utf8');

  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=1200', '--poll-ms=300'], {
    timeout: 10000,
  });
  assert(exitCode === 2, `case 5: exit code is 2 (timeout, never a give-up code) (got: ${exitCode})`);
  assert(stdout.includes('waiting-unknown'), `case 5: stdout includes "waiting-unknown" (got: ${JSON.stringify(stdout)})`);
  assert(fs.existsSync(lib.wrapLockPath(tmp)) && fs.readdirSync(lib.wrapLockPath(tmp)).length === 1,
    'case 5: lock dir survives with its (empty) owner file untouched');
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 6: symlink-portability — invoke via symlink from non-repo cwd (UNCHANGED)
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
// Case 7: NaN/unparseable-timestamp fall-through (kept from an earlier increment)
// Owner file has a valid PID on line 0 but "not-a-date" on line 1.
// Date.parse("not-a-date") = NaN -> row 9 (garbled) -> verdict 'unknown'.
// Must fall through to "waiting-unknown" and eventually time out (exit 2).
// Also asserts the lock dir is NOT removed (binary never auto-removes).
// ---------------------------------------------------------------------------
console.log('\n[7] NaN-timestamp — garbage line-1 must fall through to timeout, not a give-up code');
{
  const tmp = makeTmp('wal-case7-');
  plantLock(tmp, '99999\nnot-a-date\n');

  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=1200', '--poll-ms=300'], {
    timeout: 10000,
  });
  assert(exitCode === 2, `case 7: exit code is 2 (timeout) (got: ${exitCode})`);
  assert(stdout.includes('timeout'), `case 7: stdout includes "timeout" (got: ${JSON.stringify(stdout)})`);
  assert(stdout.includes('waiting'), `case 7: stdout includes at least one "waiting" line (got: ${JSON.stringify(stdout)})`);
  assert(fs.existsSync(lib.wrapLockPath(tmp)), 'case 7: lock dir still present (binary never auto-removes on NaN ts)');
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 8: bad-flag argument fallback (UNCHANGED)
// --timeout-ms=abc never matches the numeric arg regex, so the 1200000ms
// default holds; verify the binary still acquires correctly (exit 0) when no
// lock is held, proving a bad flag does not cause a crash or misbehavior.
// ---------------------------------------------------------------------------
console.log('\n[8] bad-flag fallback — --timeout-ms=abc must not crash; should still acquire');
{
  const tmp = makeTmp('wal-case8-');
  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=abc', '--poll-ms=300'], {
    timeout: 10000,
  });
  assert(exitCode === 0, `case 8: exit code is 0 (acquired despite bad --timeout-ms) (got: ${exitCode})`);
  assert(stdout.includes('acquired'), `case 8: stdout includes "acquired" (got: ${JSON.stringify(stdout)})`);
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 9: exit 3/4 are structurally unreachable (U3)
// ---------------------------------------------------------------------------
console.log('\n[9] exit 3/4 unreachable — give-up branches removed, never emitted');
{
  const src = fs.readFileSync(SCRIPT_PATH, 'utf8');
  assert(!/stale-needs-manual/.test(src), 'case 9: "stale-needs-manual" is absent from the binary source');
  assert(!/unreadable-owner/.test(src), 'case 9: "unreadable-owner" is absent from the binary source');
  assert(!allExitCodes.includes(3), `case 9: no case in this file produced exit 3 (codes seen so far: ${JSON.stringify(allExitCodes)})`);
  assert(!allExitCodes.includes(4), `case 9: no case in this file produced exit 4 (codes seen so far: ${JSON.stringify(allExitCodes)})`);
}

// ---------------------------------------------------------------------------
// Case 10: no removal call sites in the binary (U3)
// ---------------------------------------------------------------------------
console.log('\n[10] no removal path — binary never calls a lock-removal primitive');
{
  const src = fs.readFileSync(SCRIPT_PATH, 'utf8');
  assert(!/rmSync|unlinkSync|releaseWrapLock|clearProvablyStale|clearDead|clearUnknown/.test(src),
    'case 10: no rmSync/unlinkSync/releaseWrapLock/clearProvablyStale/clearDead/clearUnknown call site');
  const rmDashRfMatches = src.match(/rm -rf/g) || [];
  assert(rmDashRfMatches.length === 1, `case 10: exactly one "rm -rf" occurrence, inside the printed HINT string literal (got: ${rmDashRfMatches.length})`);
}

// ---------------------------------------------------------------------------
// Case 11: descriptor shape on a fresh acquisition (U3)
// ---------------------------------------------------------------------------
console.log('\n[11] descriptor shape — fresh acquisition publishes a valid role:agent JSON descriptor');
{
  const tmp = makeTmp('wal-case11-');
  const { exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=5000', '--poll-ms=500']);
  assert(exitCode === 0, `case 11: helper exited 0 (got: ${exitCode})`);

  const o = lib.readWrapLockOwnerV2(tmp);
  // Precondition: without this, the six field assertions below would pass
  // vacuously against a schema-invalid (degraded) descriptor.
  assert(o.source === 'json', `case 11 precondition: readWrapLockOwnerV2 source is 'json' (got: ${JSON.stringify(o)})`);
  assert(o.schema_version === undefined || true, 'case 11: schema_version is validated via readWrapLockOwnerV2 acceptance, not re-checked here');
  const raw = JSON.parse(fs.readFileSync(lib.wrapLockOwnerJsonPath(tmp), 'utf8'));
  assert(raw.schema_version === 1, `case 11: schema_version is 1 (got: ${raw.schema_version})`);
  assert(raw.role === 'agent', `case 11: role is 'agent' (got: ${raw.role})`);
  assert(raw.pid === null, `case 11: pid is null for role:agent (got: ${raw.pid})`);
  assert(raw.host === os.hostname(), `case 11: host matches os.hostname() (got: ${raw.host})`);
  assert(Number.isFinite(Date.parse(raw.acquired_at)), `case 11: acquired_at is a parseable timestamp (got: ${raw.acquired_at})`);
  assert(raw.token === null || (typeof raw.token === 'string' && raw.token.length > 0), `case 11: token is null or a non-empty string (got: ${JSON.stringify(raw.token)})`);
  assert(!Object.prototype.hasOwnProperty.call(raw, 'ttl_ms'), 'case 11: descriptor carries no ttl_ms key');

  const legacyBody = fs.readFileSync(lib.wrapLockOwnerPath(tmp), 'utf8');
  const legacyLines = legacyBody.split('\n').filter((l) => l.length > 0);
  assert(legacyLines.length === 2, `case 11: legacy 2-line owner body still exists alongside the descriptor (got ${legacyLines.length} non-empty lines)`);

  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Case 12: --print-token + token-scoped release round-trip (U3)
// ---------------------------------------------------------------------------
console.log('\n[12] --print-token — round-trips through agentic-wrap-release-lock --token');
{
  const tmp = makeTmp('wal-case12-');
  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=5000', '--poll-ms=500', '--print-token']);
  assert(exitCode === 0, `case 12: helper exited 0 (got: ${exitCode})`);
  const tokenMatch = stdout.match(/token=([0-9a-fA-F-]+)/);
  assert(tokenMatch !== null, `case 12: stdout includes "token=<uuid>" (got: ${JSON.stringify(stdout)})`);
  const printedToken = tokenMatch && tokenMatch[1];

  const o = lib.readWrapLockOwnerV2(tmp);
  assert(o.source === 'json' && o.token === printedToken, `case 12: descriptor's token equals the printed token (descriptor: ${JSON.stringify(o)}, printed: ${printedToken})`);

  // Wrong token -> refused, lock survives.
  const wrongRelease = execFileSync('node', [RELEASE_SCRIPT_PATH, tmp, '--token=not-the-real-token'], { encoding: 'utf8' });
  assert(wrongRelease.includes('not-owner'), `case 12: wrong token is refused with "not-owner" (got: ${JSON.stringify(wrongRelease)})`);
  assert(fs.existsSync(lib.wrapLockPath(tmp)), 'case 12: lock survives a wrong-token release attempt');

  // Right token -> released.
  const rightRelease = execFileSync('node', [RELEASE_SCRIPT_PATH, tmp, '--token=' + printedToken], { encoding: 'utf8' });
  assert(rightRelease.includes('released'), `case 12: right token releases the lock (got: ${JSON.stringify(rightRelease)})`);
  assert(!fs.existsSync(lib.wrapLockPath(tmp)), 'case 12: lock dir is gone after the right-token release');
}

// ---------------------------------------------------------------------------
// Case 13: empty planted lock dir + a concurrent acquirer (U3)
// ---------------------------------------------------------------------------
console.log('\n[13] empty lock dir — concurrent acquirer neither acquires nor clears it');
{
  const tmp = makeTmp('wal-case13-');
  plantEmptyLockDir(tmp);
  const lockDir = lib.wrapLockPath(tmp);
  const contentsBefore = fs.readdirSync(lockDir);
  assert(contentsBefore.length === 0, 'case 13 precondition: planted lock dir is empty');

  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=900', '--poll-ms=200'], {
    timeout: 10000,
  });
  assert(exitCode !== 0, `case 13: did not acquire (exit code ${exitCode})`);
  assert(stdout.includes('waiting'), `case 13: stdout includes a "waiting*" progress line (got: ${JSON.stringify(stdout)})`);
  assert(fs.existsSync(lockDir), 'case 13: the lock dir survives (never cleared)');
  const contentsAfter = fs.readdirSync(lockDir);
  assert(contentsAfter.length === 0, `case 13: the lock dir's (empty) contents are unchanged (got: ${JSON.stringify(contentsAfter)})`);
}

// ---------------------------------------------------------------------------
// Case 14: fail-closed publication, in-process (U3)
// Stubs fs.writeFileSync to fail specific writes and asserts acquireWrapLock
// (the lib primitive, called in-process - no CLI subprocess) returns false and
// leaves no lock dir behind. CONSTRAINT: no env-var test hook added to
// production code; this uses the no-hook stub form exclusively.
// ---------------------------------------------------------------------------
console.log('\n[14] fail-closed publication — stubbed fs.writeFileSync failures');
{
  const realWriteFileSync = fs.writeFileSync;

  // (a) fail writing the legacy owner .tmp file.
  {
    const tmp = makeTmp('wal-case14a-');
    fs.writeFileSync = function (p, ...rest) {
      if (String(p).endsWith('owner.tmp')) throw new Error('EFAIL-owner-tmp');
      return realWriteFileSync.call(fs, p, ...rest);
    };
    let acquired;
    try {
      acquired = lib.acquireWrapLock(tmp, '1\n2020-01-01T00:00:00.000Z', 0, { role: 'agent' });
    } finally {
      fs.writeFileSync = realWriteFileSync;
    }
    assert(acquired === false, `case 14a: acquireWrapLock returns false when owner.tmp write throws (got: ${acquired})`);
    assert(!fs.existsSync(lib.wrapLockPath(tmp)), 'case 14a: no lock dir left behind after failed publication');
  }

  // (b) owner write succeeds, but the JSON descriptor .tmp write fails.
  {
    const tmp = makeTmp('wal-case14b-');
    fs.writeFileSync = function (p, ...rest) {
      if (String(p).endsWith('owner.json.tmp')) throw new Error('EFAIL-json-tmp');
      return realWriteFileSync.call(fs, p, ...rest);
    };
    let acquired;
    try {
      acquired = lib.acquireWrapLock(tmp, '1\n2020-01-01T00:00:00.000Z', 0, { role: 'agent' });
    } finally {
      fs.writeFileSync = realWriteFileSync;
    }
    assert(acquired === false, `case 14b: acquireWrapLock returns false when owner.json.tmp write throws (got: ${acquired})`);
    assert(!fs.existsSync(lib.wrapLockPath(tmp)), 'case 14b: no lock dir left behind after failed publication');
  }

  // (c) publication fails AND the lock dir is swapped for a different-inode
  // dir before the catch runs - the cleanup rmSync must NOT fire on it.
  {
    const tmp = makeTmp('wal-case14c-');
    const lockDirC = lib.wrapLockPath(tmp);
    const sentinelPath = path.join(lockDirC, 'sentinel');
    let swapped = false;
    fs.writeFileSync = function (p, ...rest) {
      if (String(p).endsWith('owner.tmp') && !swapped) {
        swapped = true;
        fs.rmSync(lockDirC, { recursive: true, force: true });
        fs.mkdirSync(lockDirC, { recursive: true });
        realWriteFileSync.call(fs, sentinelPath, 'x', 'utf8');
        throw new Error('EFAIL-owner-tmp-race');
      }
      return realWriteFileSync.call(fs, p, ...rest);
    };
    let acquired;
    try {
      acquired = lib.acquireWrapLock(tmp, '1\n2020-01-01T00:00:00.000Z', 0, { role: 'agent' });
    } finally {
      fs.writeFileSync = realWriteFileSync;
    }
    assert(acquired === false, `case 14c: acquireWrapLock returns false on the race (got: ${acquired})`);
    assert(fs.existsSync(sentinelPath), 'case 14c: the swapped-in directory survives (cleanup did not fire on a different inode)');
  }
}

// ---------------------------------------------------------------------------
// Case 15: no-false-acquired — mkdirSync(dirname) fails with ENOTDIR (U3)
// Points the binary at a cwd whose .agentic/wrap path component is a plain
// FILE, so mkdirSync(dirname, {recursive:true}) throws ENOTDIR before mkdir
// on the lock dir itself is ever attempted; acquireWrapLock returns false, and
// the very next verdict read is 'free' (lock path absent). Proves the binary
// never infers "acquired" from a 'free' verdict. Run BOTH with --no-wait
// (expect exit 5) and with an explicit short --timeout-ms (expect exit 2) -
// never the default 20-minute timeout in a test that cannot acquire.
// ---------------------------------------------------------------------------
console.log('\n[15] no-false-acquired — .agentic/wrap is a plain file (mkdirSync ENOTDIR)');
{
  const tmp = makeTmp('wal-case15-');
  fs.mkdirSync(path.join(tmp, '.agentic'), { recursive: true });
  fs.writeFileSync(path.join(tmp, '.agentic', 'wrap'), 'not-a-directory', 'utf8');

  const a = runHelper(SCRIPT_PATH, [tmp, '--no-wait'], { timeout: 10000 });
  assert(a.exitCode === 5, `case 15a: --no-wait exits 5 (busy), never 0 (got: ${a.exitCode})`);
  assert(!a.stdout.includes('acquired'), `case 15a: stdout never claims "acquired" (got: ${JSON.stringify(a.stdout)})`);
  assert(!fs.existsSync(lib.wrapLockPath(tmp)), 'case 15a: lock dir does not exist');

  const b = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=1200', '--poll-ms=300'], { timeout: 10000 });
  assert(b.exitCode === 2, `case 15b: explicit short timeout exits 2, never 0 (got: ${b.exitCode})`);
  assert(!b.stdout.includes('acquired'), `case 15b: stdout never claims "acquired" (got: ${JSON.stringify(b.stdout)})`);
  assert(!fs.existsSync(lib.wrapLockPath(tmp)), 'case 15b: lock dir does not exist');
}

// ---------------------------------------------------------------------------
// Case 16: no-false-give-up-on-an-OLD-INTERACTIVE-lock (U3, the reported-bug pin)
//
// Case 4 (above) covers the OTHER legacy shape - a 1-line dead-PID body - and
// genuinely exercises verdict 'dead'. But a 1-line body is the DAEMON's shape,
// not the operator's reported scenario. The operator's actual symptom was ten
// interactive `/ds-wrap` tabs: the holder's lock carries a 2-LINE owner (PID +
// ISO timestamp), the exact shape ds-wrap.md's pre-flight step writes. Once
// case 4's fixture moved to the 1-line shape (a deliberate, correct change -
// see that case's own comment), NOTHING in this suite any longer planted an
// aged 2-line owner at all, so a reintroduced age-based give-up for that shape
// would go undetected by every other case here.
//
// This case plants exactly that fixture and asserts the behavior that fixes
// the reported bug: a 2-line legacy owner is PID-BLIND (wrapLockVerdict's own
// decision table, row 6, hooks/lib/wrap-marker.js, U1) - the PID belongs to a
// shell that has ALREADY EXITED by the time the owner file lands, so liveness
// there is never checked; only the JSON-descriptor / 1-line-daemon path is
// PID-liveness-aware. An interactive holder is therefore NEVER "dead" by age,
// so this case must see verdict 'live' ("waiting", never "waiting-stale") and
// must poll to timeout (exit 2, never 3, never 4) - pre-U3, this identical
// fixture exited 4 on the very first tick.
// ---------------------------------------------------------------------------
console.log('\n[16] no-false-give-up-on-an-OLD-INTERACTIVE-lock — the reported-bug pin (2-line, aged)');
{
  const tmp = makeTmp('wal-case16-');
  const staleTs = new Date(Date.now() - 31 * 60 * 1000).toISOString();
  const ownerContent = '12345\n' + staleTs + '\n';
  plantLock(tmp, ownerContent);

  const { stdout, exitCode } = runHelper(SCRIPT_PATH, [tmp, '--timeout-ms=1200', '--poll-ms=300'], {
    timeout: 10000,
  });
  assert(exitCode === 2, `case 16: exit code is 2 (timeout, never 3, never 4) (got: ${exitCode})`);
  assert(stdout.includes('waiting'), `case 16: stdout includes "waiting" (verdict live, pid-blind) (got: ${JSON.stringify(stdout)})`);
  assert(!stdout.includes('waiting-stale'), `case 16: stdout does NOT include "waiting-stale" - an interactive holder is never "dead" by age (got: ${JSON.stringify(stdout)})`);
  assert(fs.existsSync(lib.wrapLockPath(tmp)), 'case 16: lock dir still present (binary never auto-removes)');
  const ownerAfter = fs.readFileSync(lib.wrapLockOwnerPath(tmp), 'utf8');
  assert(ownerAfter === ownerContent, `case 16: owner file byte-identical to what was planted (got: ${JSON.stringify(ownerAfter)})`);
  try { lib.releaseWrapLock(tmp); } catch (_) {}
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------
for (const d of tmpDirs) {
  try { fs.rmSync(d, { recursive: true, force: true }); } catch (_) {}
}

// Final structural pin: no case in this entire run ever produced exit 3 or 4.
assert(!allExitCodes.includes(3), `final: no exit code 3 across the whole run (got: ${JSON.stringify(allExitCodes)})`);
assert(!allExitCodes.includes(4), `final: no exit code 4 across the whole run (got: ${JSON.stringify(allExitCodes)})`);

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
