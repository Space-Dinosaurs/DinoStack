#!/usr/bin/env node
/**
 * CLI-level regression tests: hooks/stop-context.js's --cadence dispatch.
 *
 * These tests spawn the REAL stop-context.js binary end-to-end (not
 * hooks/lib/state-mark.js directly), so a wiring bug in stop-context.js's own
 * --cadence argv parsing or dispatch ternary is caught. hooks/tests/
 * test-state-mark.js and test-state-mark-legacy-active.js exercise (or, for
 * the legacy fixture, now also spawn) the lib; this file is the sole test
 * asserting loop-state.json outcomes through stop-context.js's own dispatch
 * line:
 *
 *   const stateMarkFn = cadence === 'turn' ? stateMark.refreshLiveness : stateMark.markInterrupted;
 *
 * If that ternary is inverted, Test 1 (turn -> stays active) and the legacy
 * fixture in test-state-mark-legacy-active.js both fail. If the fallback
 * default silently changes from 'session' to 'turn', Tests 2 and 3 below
 * (flagless / --cadence=bogus) both fail - this is the one non-reversible
 * direction the plan names: Pi's flagless session_shutdown call would
 * silently stop writing the terminal interrupted-mark.
 *
 * Test cases:
 *   1. --cadence=turn, matching session_id, active loop-state -> last_updated
 *      ADVANCES, status stays "active" (positive control for the turn
 *      dispatch - proves refreshLiveness actually ran, not just "nothing
 *      changed").
 *   2. flagless invocation (no --cadence arg at all - the Pi session_shutdown
 *      path; also stop-context.js's own historical pre-cadence behavior) ->
 *      status becomes "interrupted" (fallback dispatch is markInterrupted).
 *   3. --cadence=bogus (unrecognized value) -> status becomes "interrupted"
 *      (unrecognized falls back to markInterrupted, same as flagless).
 *
 * Run with: node hooks/tests/test-stop-context-cadence.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

const hookScript = path.resolve(__dirname, '..', 'stop-context.js');
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

function makeTmp(prefix) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const fakeHome = path.join(tmpDir, 'home');
  const projectDir = path.join(tmpDir, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  fs.mkdirSync(fakeHome, { recursive: true });
  fs.mkdirSync(agenticDir, { recursive: true });
  return { tmpDir, fakeHome, projectDir, agenticDir };
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
}

function writeLoopState(agenticDir, obj) {
  fs.writeFileSync(path.join(agenticDir, 'loop-state.json'), JSON.stringify(obj, null, 2));
}

function readLoopState(agenticDir) {
  return JSON.parse(fs.readFileSync(path.join(agenticDir, 'loop-state.json'), 'utf8'));
}

/**
 * Spawn the real stop-context.js CLI. cadenceFlag is the raw CLI argument
 * string to append (e.g. ' --cadence=turn', ' --cadence=bogus', or '' for a
 * flagless invocation) - the caller controls this explicitly so each test
 * case's intent is visible at the call site.
 */
function runHook(projectDir, fakeHome, sessionId, cadenceFlag) {
  const payload = JSON.stringify({
    cwd: projectDir,
    session_id: sessionId,
    transcript: [],
  });
  execSync(`node "${hookScript}"${cadenceFlag}`, {
    input: payload,
    encoding: 'utf8',
    env: { ...process.env, HOME: fakeHome },
    timeout: 10000,
    stdio: ['pipe', 'pipe', 'ignore'],
  });
}

const SESSION_ID = 'cadence-test-session-uuid';

// ---------------------------------------------------------------------------
// Test 1: --cadence=turn, matching session_id -> last_updated ADVANCES,
// status stays "active".
// ---------------------------------------------------------------------------
console.log('\n[1] --cadence=turn + matching session_id: last_updated advances, status stays active');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-cadence-t1-');
  const STALE = new Date(Date.now() - 5 * 60 * 1000).toISOString(); // 5 min ago (still < 10 min)
  writeLoopState(agenticDir, { status: 'active', session_id: SESSION_ID, last_updated: STALE });

  try {
    runHook(projectDir, fakeHome, SESSION_ID, ' --cadence=turn');
  } catch (err) {
    assert(false, `hook must not throw (got: ${err.message})`);
  }

  const state = readLoopState(agenticDir);
  assert(state.status === 'active', `status stays "active" (got: ${state.status})`);
  assert(state.last_updated !== STALE,
    `last_updated ADVANCES past the pre-existing value (before: ${STALE}, after: ${state.last_updated})`);
  assert(state.interrupted_at === undefined, 'interrupted_at is NOT set on --cadence=turn');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 2: flagless invocation (no --cadence arg) -> status becomes
// "interrupted" (the Pi session_shutdown fallback path).
// ---------------------------------------------------------------------------
console.log('\n[2] flagless invocation (no --cadence arg): status becomes interrupted (Pi fallback path)');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-cadence-t2-');
  writeLoopState(agenticDir, { status: 'active', session_id: SESSION_ID });

  try {
    runHook(projectDir, fakeHome, SESSION_ID, '');
  } catch (err) {
    assert(false, `hook must not throw (got: ${err.message})`);
  }

  const state = readLoopState(agenticDir);
  assert(state.status === 'interrupted', `flagless invocation marks interrupted (got: ${state.status})`);
  assert(state.interrupt_reason === 'unknown', 'interrupt_reason is "unknown"');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 3: --cadence=bogus (unrecognized value) -> status becomes
// "interrupted" (unrecognized falls back the same as flagless).
// ---------------------------------------------------------------------------
console.log('\n[3] --cadence=bogus (unrecognized value): status becomes interrupted (fallback dispatch)');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-cadence-t3-');
  writeLoopState(agenticDir, { status: 'active', session_id: SESSION_ID });

  try {
    runHook(projectDir, fakeHome, SESSION_ID, ' --cadence=bogus');
  } catch (err) {
    assert(false, `hook must not throw (got: ${err.message})`);
  }

  const state = readLoopState(agenticDir);
  assert(state.status === 'interrupted', `--cadence=bogus marks interrupted (got: ${state.status})`);
  assert(state.interrupt_reason === 'unknown', 'interrupt_reason is "unknown"');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
