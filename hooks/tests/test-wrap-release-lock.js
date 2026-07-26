#!/usr/bin/env node
'use strict';

/**
 * Unit tests for bin/agentic-wrap-release-lock.
 *
 * Tests the CLI helper that replaces the inline `rm -rf .agentic/wrap/lock`
 * denied by Claude Code's permission system. Cases 1-4 are UNCHANGED from the
 * pre-U3 file - releaseWrapLock's return contract changed from boolean to a
 * five-value string (U1), and this binary's job (U3) is to keep these four
 * outcomes green against that new contract with ZERO edits to the cases
 * themselves:
 *   1. Planted lock - lock exists, gets released, stdout says "released <path>"
 *   2. No lock     - nothing to remove, stdout says "no lock present"
 *   3. Idempotent  - second call on already-clean dir, stdout says "no lock present"
 *   4. Bare-name via symlink - portability proof from a non-repo cwd
 *
 * New cases (U3, DS-wrap-lock-liveness) exercise the owner-scoped refusal
 * paths that only fire for a schema-valid JSON descriptor (lock/owner.json) -
 * none of cases 1-4 plant one, so the tokenless live-pid refusal never fires
 * for them:
 *   5. token-scoped refusal   - descriptor carries a token; tokenless release
 *      is refused ("not-owner"), the matching --token releases it
 *   6. plain file at lock path - refused ("not-a-lock"), file survives (this
 *      is the case that fails pre-fix: today's `rmSync(force)` removes it)
 *   7. symlink-to-sentinel-dir at lock path - refused ("not-a-lock"); the
 *      link itself is unlinked (releaseWrapLock's own CWE-59 guard, U1
 *      behavior - a hostile symlink is not "our" lock), but the sentinel
 *      directory it pointed at is never touched and survives
 *   8. self-pid carve-out    - descriptor pid === the releasing process's own
 *      pid; tokenless release still succeeds (pins the daemon's own release
 *      path, which calls releaseWrapLock in-process, never via this CLI)
 *   9. role:'agent' (pid:null) descriptor - tokenless release by an unrelated
 *      process still succeeds (pins the interactive /ds-wrap Step 6 path)
 *
 * Run with: node hooks/tests/test-wrap-release-lock.js
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const lib = require('../lib/wrap-marker.js');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SCRIPT_PATH = path.join(REPO_ROOT, 'bin', 'agentic-wrap-release-lock');

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

function plantLock(dir) {
  const lockDir = lib.wrapLockPath(dir);
  fs.mkdirSync(lockDir, { recursive: true });
  fs.writeFileSync(path.join(lockDir, 'owner'), '12345\n' + new Date().toISOString() + '\n');
  return lockDir;
}

/** Plant a schema-valid JSON descriptor lock (lock/owner.json) via makeLockDescriptor. */
function plantLockJson(dir, overrides) {
  const lockDir = lib.wrapLockPath(dir);
  fs.mkdirSync(lockDir, { recursive: true });
  const descriptor = lib.makeLockDescriptor(Object.assign({ role: 'daemon', pid: null, token: null }, overrides));
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(dir), JSON.stringify(descriptor), 'utf8');
  return lockDir;
}

function runHelper(scriptOrBin, args, opts) {
  return execFileSync('node', [scriptOrBin, ...args], { encoding: 'utf8', ...opts });
}

// ---------------------------------------------------------------------------
// Pre-flight: script exists and is readable
// ---------------------------------------------------------------------------
console.log('\n[pre] script exists');
assert(fs.existsSync(SCRIPT_PATH), `bin/agentic-wrap-release-lock exists at ${SCRIPT_PATH}`);

// ---------------------------------------------------------------------------
// Case 1: Planted lock — lock exists, gets released
// ---------------------------------------------------------------------------
console.log('\n[1] planted lock — expect "released <path>"');
{
  const tmp = makeTmp('wrl-case1-');
  const lockDir = plantLock(tmp);
  let stdout;
  let threw = false;
  try {
    stdout = runHelper(SCRIPT_PATH, [tmp]);
  } catch (e) {
    threw = true;
    console.error('  threw:', e.message);
  }
  assert(!threw, 'case 1: helper exited 0 (no throw)');
  assert(typeof stdout === 'string' && stdout.includes('released'), `case 1: stdout includes "released" (got: ${JSON.stringify(stdout)})`);
  assert(!fs.existsSync(lockDir), 'case 1: lock dir no longer exists after release');
}

// ---------------------------------------------------------------------------
// Case 2: No lock — nothing to remove
// ---------------------------------------------------------------------------
console.log('\n[2] no lock — expect "no lock present"');
{
  const tmp = makeTmp('wrl-case2-');
  let stdout;
  let threw = false;
  try {
    stdout = runHelper(SCRIPT_PATH, [tmp]);
  } catch (e) {
    threw = true;
    console.error('  threw:', e.message);
  }
  assert(!threw, 'case 2: helper exited 0 (no throw)');
  assert(typeof stdout === 'string' && stdout.includes('no lock present'), `case 2: stdout includes "no lock present" (got: ${JSON.stringify(stdout)})`);
}

// ---------------------------------------------------------------------------
// Case 3: Idempotent — second call after case-1 cleanup
// ---------------------------------------------------------------------------
console.log('\n[3] idempotent — second call on clean dir');
{
  // Re-use a fresh tmp (case 1 dir was cleaned by the release)
  const tmp = makeTmp('wrl-case3-');
  plantLock(tmp);
  // First call
  runHelper(SCRIPT_PATH, [tmp]);
  // Second call — lock already gone
  let stdout;
  let threw = false;
  try {
    stdout = runHelper(SCRIPT_PATH, [tmp]);
  } catch (e) {
    threw = true;
    console.error('  threw:', e.message);
  }
  assert(!threw, 'case 3: second call exited 0 (no throw)');
  assert(typeof stdout === 'string' && stdout.includes('no lock present'), `case 3: second call says "no lock present" (got: ${JSON.stringify(stdout)})`);
}

// ---------------------------------------------------------------------------
// Case 4: Bare-name via symlink from a non-repo cwd (portability proof)
// ---------------------------------------------------------------------------
console.log('\n[4] bare-name via symlink from non-repo cwd');
{
  const bindir = makeTmp('wrl-bindir-');
  const proj = makeTmp('wrl-proj-');
  const symlinkPath = path.join(bindir, 'agentic-wrap-release-lock');
  fs.symlinkSync(SCRIPT_PATH, symlinkPath);
  plantLock(proj);
  const lockDir = lib.wrapLockPath(proj);

  let stdout;
  let threw = false;
  try {
    // Invoke the symlink directly (not relying on shell PATH resolution);
    // pass cwd via process.argv[2] rather than leaving it to process.cwd()
    stdout = runHelper(symlinkPath, [proj]);
  } catch (e) {
    threw = true;
    console.error('  threw:', e.message);
  }
  assert(!threw, 'case 4: symlinked helper exited 0 (no throw)');
  assert(typeof stdout === 'string' && stdout.includes('released'), `case 4: stdout includes "released" (got: ${JSON.stringify(stdout)})`);
  assert(!fs.existsSync(lockDir), 'case 4: lock dir removed when called via symlink');
  // No MODULE_NOT_FOUND means the lib loaded from the REPO correctly through the symlink
  assert(typeof stdout === 'string' && !stdout.includes('MODULE_NOT_FOUND'), 'case 4: no MODULE_NOT_FOUND (lib resolved via symlink-aware __dirname)');
}

// ---------------------------------------------------------------------------
// Case 5: token-scoped refusal (U3)
// ---------------------------------------------------------------------------
console.log('\n[5] token-scoped refusal — tokenless refused, matching --token releases');
{
  const tmp = makeTmp('wrl-case5-');
  const lockDir = plantLockJson(tmp, { role: 'daemon', pid: process.pid, token: 'T' });
  const o = lib.readWrapLockOwnerV2(tmp);
  assert(o.source === 'json', `case 5 precondition: readWrapLockOwnerV2 source is 'json' (got: ${JSON.stringify(o)})`);

  const tokenless = runHelper(SCRIPT_PATH, [tmp]);
  assert(tokenless.includes('not-owner'), `case 5: tokenless release is refused with "not-owner" (got: ${JSON.stringify(tokenless)})`);
  assert(fs.existsSync(lockDir), 'case 5: lock survives a tokenless release attempt');

  const withToken = runHelper(SCRIPT_PATH, [tmp, '--token=T']);
  assert(withToken.includes('released'), `case 5: --token=T releases the lock (got: ${JSON.stringify(withToken)})`);
  assert(!fs.existsSync(lockDir), 'case 5: lock dir is gone after the right-token release');
}

// ---------------------------------------------------------------------------
// Case 6: plain file at lock path (U3)
// Fails pre-fix: today's `rmSync(force:true)` removes a plain file too.
// ---------------------------------------------------------------------------
console.log('\n[6] plain file at lock path — refused as not-a-lock, file survives');
{
  const tmp = makeTmp('wrl-case6-');
  const lockPath = lib.wrapLockPath(tmp);
  fs.mkdirSync(path.dirname(lockPath), { recursive: true });
  fs.writeFileSync(lockPath, 'not-a-directory', 'utf8');

  const stdout = runHelper(SCRIPT_PATH, [tmp]);
  assert(stdout.includes('not-a-lock'), `case 6: stdout includes "not-a-lock" (got: ${JSON.stringify(stdout)})`);
  assert(fs.existsSync(lockPath) && fs.statSync(lockPath).isFile(), 'case 6: the plain file at the lock path survives');
  assert(stdout.includes('a file exists at the lock path; not removing'), `case 6: message accurately says a file exists and was left in place (got: ${JSON.stringify(stdout)})`);
  assert(stdout.includes('rm -rf'), 'case 6: message still recommends the manual rm -rf escape hatch (the file genuinely still exists)');
}

// ---------------------------------------------------------------------------
// Case 7: symlink-to-sentinel-dir at lock path (U3)
//
// DEVIATION FROM THE ORIGINAL BRIEF, verified against the ALREADY-COMMITTED
// (U1, out of this unit's scope) hooks/lib/wrap-marker.js releaseWrapLock:
// the symlink branch there deliberately DOES `fs.unlinkSync(lockDir)` before
// returning 'refused-not-a-lock' - "a symlink AT wrap/lock is a hostile
// artifact, not our lock. Unlink removes ONLY the link (never follows it /
// touches the target)". That CWE-59 discipline is U1's, not U3's to change,
// and it means the link does NOT survive a release attempt - only the
// sentinel it pointed at does (unlink never follows/touches the target).
// Asserting "the link survives" would therefore assert something provably
// false against the frozen lib; this case instead pins the behavior that IS
// true: the release is still refused (not-a-lock, never silently succeeds as
// "released"), the link is gone, and the sentinel directory is untouched.
// ---------------------------------------------------------------------------
console.log('\n[7] symlink-to-sentinel-dir at lock path — refused as not-a-lock, sentinel survives');
{
  const tmp = makeTmp('wrl-case7-');
  const sentinel = makeTmp('wrl-case7-sentinel-');
  const lockPath = lib.wrapLockPath(tmp);
  fs.mkdirSync(path.dirname(lockPath), { recursive: true });
  fs.symlinkSync(sentinel, lockPath);

  const stdout = runHelper(SCRIPT_PATH, [tmp]);
  assert(stdout.includes('not-a-lock'), `case 7: stdout includes "not-a-lock" (got: ${JSON.stringify(stdout)})`);
  assert(!stdout.includes('released'), 'case 7: stdout never claims "released" for a hostile symlink');
  let linkGone = false;
  try { fs.lstatSync(lockPath); } catch (_) { linkGone = true; }
  assert(linkGone, 'case 7: the hostile symlink itself is unlinked by releaseWrapLock\'s own CWE-59 guard (U1 behavior, not a regression - the link is never followed/its target is never touched)');
  assert(fs.existsSync(sentinel), 'case 7: the sentinel directory the link pointed at survives untouched');
  assert(stdout.includes('a symlink existed at the lock path and was removed'), `case 7: message accurately says the symlink was already removed, not "not removing" (got: ${JSON.stringify(stdout)})`);
  assert(!stdout.includes('rm -rf'), 'case 7: message does not recommend rm -rf against a path that no longer exists');
}

// ---------------------------------------------------------------------------
// Case 8: self-pid carve-out (U3)
// Released IN-PROCESS (lib.releaseWrapLock, not the CLI subprocess) so that
// releaseWrapLock's internal process.pid check is genuinely this same
// process - the daemon itself releases its own hold exactly this way
// (hooks/wrap-daemon.js calls releaseWrapLock(cwd, token) in-process, never
// via this CLI), so this is the sole pin for that carve-out.
// ---------------------------------------------------------------------------
console.log('\n[8] self-pid carve-out — descriptor pid === releasing process pid, tokenless release succeeds');
{
  const tmp = makeTmp('wrl-case8-');
  const lockDir = plantLockJson(tmp, { role: 'daemon', pid: process.pid, token: null });
  const o = lib.readWrapLockOwnerV2(tmp);
  assert(o.source === 'json', `case 8 precondition: readWrapLockOwnerV2 source is 'json' (got: ${JSON.stringify(o)})`);

  const result = lib.releaseWrapLock(tmp);
  assert(result === 'released', `case 8: self-pid tokenless release succeeds (got: ${JSON.stringify(result)})`);
  assert(!fs.existsSync(lockDir), 'case 8: lock dir is gone after the self-pid release');
}

// ---------------------------------------------------------------------------
// Case 9: role:'agent' (pid:null) descriptor - interactive /ds-wrap Step 6 (U3)
// ---------------------------------------------------------------------------
console.log('\n[9] role:agent (pid:null) descriptor — tokenless release by an unrelated process succeeds');
{
  const tmp = makeTmp('wrl-case9-');
  const lockDir = plantLockJson(tmp, { role: 'agent', pid: null, token: null });
  const o = lib.readWrapLockOwnerV2(tmp);
  assert(o.source === 'json', `case 9 precondition: readWrapLockOwnerV2 source is 'json' (got: ${JSON.stringify(o)})`);

  const stdout = runHelper(SCRIPT_PATH, [tmp]);
  assert(stdout.includes('released'), `case 9: tokenless release by an unrelated process succeeds (got: ${JSON.stringify(stdout)})`);
  assert(!fs.existsSync(lockDir), 'case 9: lock dir is gone after release');
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------
for (const d of tmpDirs) {
  try { fs.rmSync(d, { recursive: true, force: true }); } catch (_) { /* best-effort */ }
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
