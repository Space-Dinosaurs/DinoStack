#!/usr/bin/env node
/**
 * Unit tests: relocated hook require paths.
 *
 * Verifies that the two JS hooks relocated into .d/ directories correctly
 * resolve '../lib/wrap-marker.js' (one level deeper than the former hooks/ root)
 * and degrade gracefully when the lib is absent (lazy-require shim engaged).
 *
 * Cases for each of stop.d/010-stop-context.js and sessionend.d/010-session-end-wrap.js:
 *   R-PRESENT  - lib PRESENT: hook loads and runs without MODULE_NOT_FOUND on
 *                '../lib/wrap-marker.js'. We run the hook as a subprocess with a
 *                minimal valid payload so it exercises the lazy-require path.
 *   R-ABSENT   - lib ABSENT: temporarily rename hooks/lib/wrap-marker.js aside so
 *                it cannot be required; the hook still exits 0 (shim engaged, no
 *                uncaught throw). Always restores via try/finally.
 *
 * Run with: node hooks/tests/test-relocated-require-paths.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const HOOKS_DIR = path.resolve(__dirname, '..');
const LIB_PATH = path.join(HOOKS_DIR, 'lib', 'wrap-marker.js');
const LIB_ASIDE_PATH = LIB_PATH + '.aside';

const STOP_HOOK = path.join(HOOKS_DIR, 'stop.d', '010-stop-context.js');
const SESSIONEND_HOOK = path.join(HOOKS_DIR, 'sessionend.d', '010-session-end-wrap.js');

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

function assertEqual(actual, expected, message) {
  if (actual === expected) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`);
    failed++;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Create a temp project dir with .agentic/ subdirs that hooks expect. */
function makeTempProject() {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'rr-test-')));
  fs.mkdirSync(path.join(base, '.agentic', 'wrap', 'heartbeats'), { recursive: true });
  return base;
}

/** Run a hook as a subprocess with a minimal payload. Returns { status, stderr }. */
function runHook(hookPath, projectDir) {
  const fakeHome = fs.mkdtempSync(path.join(os.tmpdir(), 'rr-home-'));
  const payload = JSON.stringify({
    cwd: projectDir,
    session_id: 'test-session-rr',
    transcript: [],
    stop_reason: 'end_turn',
    reason: 'end_turn',
  });
  const result = spawnSync('node', [hookPath], {
    input: payload,
    encoding: 'utf8',
    timeout: 15000,
    env: Object.assign({}, process.env, { HOME: fakeHome }),
  });
  try { fs.rmSync(fakeHome, { recursive: true, force: true }); } catch (_) { /* ignore */ }
  return { status: result.status, stderr: result.stderr || '', stdout: result.stdout || '' };
}

// Guard: the hooks must exist before we can test them
if (!fs.existsSync(STOP_HOOK)) {
  console.error(`FAIL: stop hook not found at ${STOP_HOOK}`);
  process.exit(1);
}
if (!fs.existsSync(SESSIONEND_HOOK)) {
  console.error(`FAIL: session-end hook not found at ${SESSIONEND_HOOK}`);
  process.exit(1);
}
if (!fs.existsSync(LIB_PATH)) {
  console.error(`FAIL: lib not found at ${LIB_PATH}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Test R1: stop.d/010-stop-context.js - lib PRESENT
// ---------------------------------------------------------------------------
console.log('\nTest R1: stop-context lib-present (no MODULE_NOT_FOUND)');
{
  const projectDir = makeTempProject();
  try {
    const { status, stderr } = runHook(STOP_HOOK, projectDir);
    // exit 0 or any clean exit - what matters is no MODULE_NOT_FOUND crash
    const hasModuleNotFound = stderr.includes('MODULE_NOT_FOUND');
    assert(!hasModuleNotFound, 'R1: stop-context no MODULE_NOT_FOUND with lib present');
    // Hook may exit non-zero for other reasons (e.g. missing identity), but must not
    // crash at require() time. Accept any exit code except a node crash on require.
    assert(!stderr.includes("Cannot find module '../lib/wrap-marker.js'"),
      'R1: stop-context resolves ../lib/wrap-marker.js correctly');
  } finally {
    try { fs.rmSync(projectDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Test R2: stop.d/010-stop-context.js - lib ABSENT (shim engaged)
// ---------------------------------------------------------------------------
console.log('\nTest R2: stop-context lib-absent (shim exits 0, no uncaught throw)');
{
  const projectDir = makeTempProject();
  // Rename lib aside - always restore in finally
  let libMoved = false;
  try {
    fs.renameSync(LIB_PATH, LIB_ASIDE_PATH);
    libMoved = true;
    const { status } = runHook(STOP_HOOK, projectDir);
    assertEqual(status, 0, 'R2: stop-context exits 0 with lib absent (lazy-require shim)');
  } finally {
    if (libMoved) {
      try { fs.renameSync(LIB_ASIDE_PATH, LIB_PATH); } catch (e) {
        console.error(`  FATAL: could not restore lib: ${e.message}`);
        process.exit(1);
      }
    }
    try { fs.rmSync(projectDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Test R3: sessionend.d/010-session-end-wrap.js - lib PRESENT
// ---------------------------------------------------------------------------
console.log('\nTest R3: session-end-wrap lib-present (no MODULE_NOT_FOUND)');
{
  const projectDir = makeTempProject();
  try {
    const { status, stderr } = runHook(SESSIONEND_HOOK, projectDir);
    const hasModuleNotFound = stderr.includes('MODULE_NOT_FOUND');
    assert(!hasModuleNotFound, 'R3: session-end-wrap no MODULE_NOT_FOUND with lib present');
    assert(!stderr.includes("Cannot find module '../lib/wrap-marker.js'"),
      'R3: session-end-wrap resolves ../lib/wrap-marker.js correctly');
  } finally {
    try { fs.rmSync(projectDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Test R4: sessionend.d/010-session-end-wrap.js - lib ABSENT (shim engaged)
// ---------------------------------------------------------------------------
console.log('\nTest R4: session-end-wrap lib-absent (shim exits 0, no uncaught throw)');
{
  const projectDir = makeTempProject();
  let libMoved = false;
  try {
    fs.renameSync(LIB_PATH, LIB_ASIDE_PATH);
    libMoved = true;
    const { status } = runHook(SESSIONEND_HOOK, projectDir);
    assertEqual(status, 0, 'R4: session-end-wrap exits 0 with lib absent (lazy-require shim)');
  } finally {
    if (libMoved) {
      try { fs.renameSync(LIB_ASIDE_PATH, LIB_PATH); } catch (e) {
        console.error(`  FATAL: could not restore lib: ${e.message}`);
        process.exit(1);
      }
    }
    try { fs.rmSync(projectDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
  }
}

// Verify lib is still present after all tests (sanity check)
assert(fs.existsSync(LIB_PATH), 'post-test: lib/wrap-marker.js is restored');

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
if (failed > 0) process.exit(1);
