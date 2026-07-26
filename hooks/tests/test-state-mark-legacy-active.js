#!/usr/bin/env node
/**
 * Regression test: a legacy loop-state.json (status:"active", NO session_id
 * field, last_updated already stale by more than 10 minutes) must NEVER have
 * its last_updated refreshed by refreshLiveness, no matter how many turns
 * fire the per-turn cadence with an unrelated session id.
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

const stateMark = require(path.resolve(__dirname, '..', 'lib', 'state-mark.js'));

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

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-state-mark-legacy-'));
const agenticDir = path.join(tmpDir, '.agentic');
fs.mkdirSync(agenticDir, { recursive: true });
const loopStatePath = path.join(agenticDir, 'loop-state.json');

const STALE_TIMESTAMP = new Date(Date.now() - 11 * 60 * 1000).toISOString(); // 11 min ago

console.log('\nPlanting legacy active loop-state.json: no session_id, last_updated 11 min old');
fs.writeFileSync(loopStatePath, JSON.stringify({
  status: 'active',
  last_updated: STALE_TIMESTAMP,
}, null, 2));

console.log('Invoking refreshLiveness 3x with an unrelated sessionId ("some-other-session")');
for (let i = 1; i <= 3; i++) {
  stateMark.refreshLiveness(tmpDir, 'some-other-session');
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
