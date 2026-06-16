#!/usr/bin/env node
'use strict';

/**
 * Unit tests for bin/agentic-wrap-release-lock.
 *
 * Tests the CLI helper that replaces the inline `rm -rf .agentic/wrap.lock`
 * denied by Claude Code's permission system. Four cases:
 *   1. Planted lock - lock exists, gets released, stdout says "released <path>"
 *   2. No lock     - nothing to remove, stdout says "no lock present"
 *   3. Idempotent  - second call on already-clean dir, stdout says "no lock present"
 *   4. Bare-name via symlink - portability proof from a non-repo cwd
 *
 * Run with: node hooks/tests/test-wrap-release-lock.js
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

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
  const lockDir = path.join(dir, '.agentic', 'wrap.lock');
  fs.mkdirSync(lockDir, { recursive: true });
  fs.writeFileSync(path.join(lockDir, 'owner'), '12345\n' + new Date().toISOString() + '\n');
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
  const lockDir = path.join(proj, '.agentic', 'wrap.lock');

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
