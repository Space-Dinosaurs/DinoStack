#!/usr/bin/env node
/**
 * Regression test: a legacy loop-state.json (status:"active", NO session_id
 * field, last_updated already stale by more than 10 minutes) must NEVER have
 * its last_updated refreshed, no matter how many turns fire the per-turn
 * cadence with an unrelated session id.
 *
 * This spawns the REAL hooks/stop-context.js CLI with --cadence=turn three
 * times (not hooks/lib/state-mark.js directly) - a Skeptic finding on the
 * original direct-lib version noted that calling refreshLiveness() in-process
 * exercises the lib but NOT stop-context.js's own --cadence parsing/dispatch
 * ternary, so an inverted or defaulted dispatch in stop-context.js itself
 * would still pass a lib-only version of this test. See
 * hooks/tests/test-stop-context-cadence.js for the sibling CLI-level cases
 * (flagless fallback, --cadence=bogus fallback, matching-session positive
 * control).
 *
 * This is the exact Round-1 Critical scenario: a legacy or unowned
 * loop-state.json present in every consumer repo on day one, refreshed every
 * turn by an unrelated session, would become invisible to the 10-minute
 * staleness heuristic and to every reaper - an immortal, unrecoverable loop.
 *
 * Run with: node hooks/tests/test-state-mark-legacy-active.js
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

/**
 * Spawn the real stop-context.js CLI with --cadence=turn against fakeHome,
 * feeding sessionId as the payload's session_id. stdio's stderr is ignored to
 * silence stray git noise ("fatal: not a git repository") in a non-git tmp
 * dir, matching the convention used by the sibling stop-context tests.
 */
function runHookCadenceTurn(projectDir, fakeHome, sessionId) {
  const payload = JSON.stringify({
    cwd: projectDir,
    session_id: sessionId,
    transcript: [],
  });
  execSync(`node "${hookScript}" --cadence=turn`, {
    input: payload,
    encoding: 'utf8',
    env: { ...process.env, HOME: fakeHome },
    timeout: 10000,
    stdio: ['pipe', 'pipe', 'ignore'],
  });
}

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-state-mark-legacy-'));
const fakeHome = path.join(tmpDir, 'home');
const projectDir = path.join(tmpDir, 'project');
const agenticDir = path.join(projectDir, '.agentic');
fs.mkdirSync(fakeHome, { recursive: true });
fs.mkdirSync(agenticDir, { recursive: true });
const loopStatePath = path.join(agenticDir, 'loop-state.json');

const STALE_TIMESTAMP = new Date(Date.now() - 11 * 60 * 1000).toISOString(); // 11 min ago

console.log('\nPlanting legacy active loop-state.json: no session_id, last_updated 11 min old');
fs.writeFileSync(loopStatePath, JSON.stringify({
  status: 'active',
  last_updated: STALE_TIMESTAMP,
}, null, 2));

console.log('Invoking the real stop-context.js CLI 3x with --cadence=turn and an unrelated sessionId ("some-other-session")');
for (let i = 1; i <= 3; i++) {
  try {
    runHookCadenceTurn(projectDir, fakeHome, 'some-other-session');
  } catch (err) {
    assert(false, `invocation ${i}: hook must not throw (got: ${err.message})`);
    continue;
  }
  const state = JSON.parse(fs.readFileSync(loopStatePath, 'utf8'));
  assert(state.last_updated === STALE_TIMESTAMP,
    `after invocation ${i}: last_updated unchanged (got: ${state.last_updated})`);
  assert(state.status === 'active', `after invocation ${i}: status still "active" (got: ${state.status})`);
}

try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}

console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
