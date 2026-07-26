#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/state-mark.js (refreshLiveness / markInterrupted).
 *
 * Loads the lib directly (no CLI subprocess spawn) and exercises both write
 * cadences against a temporary .agentic/ directory.
 *
 * Test cases:
 *   (a) refreshLiveness with a MATCHING session_id refreshes last_updated,
 *       leaves status:"active" untouched.
 *   (b) markInterrupted marks interrupted (status/interrupted_at/
 *       interrupt_reason) - this pins the TERMINAL-cadence contract only,
 *       NOT an endorsement of calling markInterrupted on every turn (that is
 *       exactly the bug this unit fixes - see hooks/session-end-wrap.js for
 *       the once-per-session caller).
 *   (c) a positively-differing session_id is untouched by BOTH functions.
 *   (d) refreshLiveness SKIPS absent/null/empty session_id, leaving the file
 *       BYTE-IDENTICAL - the Critical's regression test (Round 1: an
 *       unrelated session refreshing liveness on a legacy/unowned active
 *       loop-state would make it immortal and unrecoverable).
 *   (e) markInterrupted PROCEEDS on that same absent-session_id file
 *       (opposite polarity, deliberately asymmetric - see module manifest).
 *   (f) no orphan .tmp file on success or on corrupt-JSON input.
 *   (g) health label on the real code path: corrupt-JSON hits
 *       onOutcome('writeLoopState', false, ...) - literal target string.
 *
 * Run with: node hooks/tests/test-state-mark.js
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

function makeTmp(prefix) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const agenticDir = path.join(tmpDir, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  return { tmpDir, agenticDir };
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
}

function writeLoopState(agenticDir, obj) {
  fs.writeFileSync(path.join(agenticDir, 'loop-state.json'), JSON.stringify(obj, null, 2));
}

function readLoopStateRaw(agenticDir) {
  return fs.readFileSync(path.join(agenticDir, 'loop-state.json'), 'utf8');
}

function readLoopState(agenticDir) {
  return JSON.parse(readLoopStateRaw(agenticDir));
}

// ---------------------------------------------------------------------------
// (a) refreshLiveness with a MATCHING session_id refreshes last_updated
// ---------------------------------------------------------------------------
console.log('\n[a] refreshLiveness: matching session_id refreshes last_updated, status stays active');
{
  const { tmpDir, agenticDir } = makeTmp('ae-state-mark-a-');
  writeLoopState(agenticDir, { status: 'active', session_id: 'sess-a' });

  stateMark.refreshLiveness(tmpDir, 'sess-a');

  const state = readLoopState(agenticDir);
  assert(state.status === 'active', `status stays "active" (got: ${state.status})`);
  assert(typeof state.last_updated === 'string' && state.last_updated.length > 0,
    `last_updated is populated (got: ${state.last_updated})`);
  assert(state.interrupted_at === undefined, 'interrupted_at is NOT set by refreshLiveness');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (b) markInterrupted marks interrupted (TERMINAL cadence only - see header)
// ---------------------------------------------------------------------------
console.log('\n[b] markInterrupted: marks status/interrupted_at/interrupt_reason (terminal cadence)');
{
  const { tmpDir, agenticDir } = makeTmp('ae-state-mark-b-');
  writeLoopState(agenticDir, { status: 'active', session_id: 'sess-a' });

  stateMark.markInterrupted(tmpDir, 'sess-a');

  const state = readLoopState(agenticDir);
  assert(state.status === 'interrupted', `status === "interrupted" (got: ${state.status})`);
  assert(typeof state.interrupted_at === 'string' && state.interrupted_at.length > 0,
    `interrupted_at is populated (got: ${state.interrupted_at})`);
  assert(state.interrupt_reason === 'unknown', `interrupt_reason === "unknown" (got: ${state.interrupt_reason})`);
  // Deliberately NOT touched here - Contract A's resume-staleness gate reads
  // last_updated with no status exemption (see module manifest).
  assert(state.last_updated === undefined,
    'last_updated is NOT written by markInterrupted (see hooks/lib/state-mark.js manifest)');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (c) a positively-differing session_id is untouched by BOTH functions
// ---------------------------------------------------------------------------
console.log('\n[c] positively-differing session_id: untouched by refreshLiveness AND markInterrupted');
{
  const { tmpDir, agenticDir } = makeTmp('ae-state-mark-c-');
  const fixture = { status: 'active', session_id: 'sess-owner' };
  writeLoopState(agenticDir, fixture);
  const before = readLoopStateRaw(agenticDir);

  stateMark.refreshLiveness(tmpDir, 'sess-other');
  const afterRefresh = readLoopStateRaw(agenticDir);
  assert(afterRefresh === before, 'refreshLiveness does not modify a file owned by a differing session');

  stateMark.markInterrupted(tmpDir, 'sess-other');
  const afterMark = readLoopStateRaw(agenticDir);
  assert(afterMark === before, 'markInterrupted does not modify a file owned by a differing session');

  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (d) refreshLiveness SKIPS absent/null/empty session_id - THE Critical's
//     regression test. Byte-identical assertion is deliberate: any write at
//     all (even one that leaves status unchanged) would still be wrong here.
// ---------------------------------------------------------------------------
console.log('\n[d] refreshLiveness SKIPS absent/null/empty session_id (Critical regression test)');
{
  const scenarios = [
    { label: 'absent session_id field', fixture: { status: 'active' } },
    { label: 'null session_id', fixture: { status: 'active', session_id: null } },
    { label: 'empty-string session_id', fixture: { status: 'active', session_id: '' } },
  ];
  for (const { label, fixture } of scenarios) {
    const { tmpDir, agenticDir } = makeTmp('ae-state-mark-d-');
    writeLoopState(agenticDir, fixture);
    const before = readLoopStateRaw(agenticDir);

    stateMark.refreshLiveness(tmpDir, 'some-unrelated-session');

    const after = readLoopStateRaw(agenticDir);
    assert(after === before,
      `refreshLiveness leaves the file BYTE-IDENTICAL when ${label} (would otherwise make an unowned active loop immortal to every staleness reader)`);
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// (e) markInterrupted PROCEEDS on that same absent-session_id file (opposite
//     polarity, deliberate asymmetry)
// ---------------------------------------------------------------------------
console.log('\n[e] markInterrupted PROCEEDS on absent/null/empty session_id (deliberate asymmetry)');
{
  const scenarios = [
    { label: 'absent session_id field', fixture: { status: 'active' } },
    { label: 'null session_id', fixture: { status: 'active', session_id: null } },
    { label: 'empty-string session_id', fixture: { status: 'active', session_id: '' } },
  ];
  for (const { label, fixture } of scenarios) {
    const { tmpDir, agenticDir } = makeTmp('ae-state-mark-e-');
    writeLoopState(agenticDir, fixture);

    stateMark.markInterrupted(tmpDir, 'some-unrelated-session');

    const state = readLoopState(agenticDir);
    assert(state.status === 'interrupted',
      `markInterrupted proceeds and marks interrupted when ${label} (got status: ${state.status})`);
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// (f) no orphan .tmp on success or corrupt-JSON input
// ---------------------------------------------------------------------------
console.log('\n[f] no orphan .tmp files on success or corrupt-JSON input');
{
  // Success path (refreshLiveness).
  {
    const { tmpDir, agenticDir } = makeTmp('ae-state-mark-f1-');
    writeLoopState(agenticDir, { status: 'active', session_id: 'sess-a' });
    stateMark.refreshLiveness(tmpDir, 'sess-a');
    const tmpFiles = fs.readdirSync(agenticDir).filter((f) => f.endsWith('.tmp'));
    assert(tmpFiles.length === 0, `(refreshLiveness success) no .tmp remains (found: ${tmpFiles.join(', ') || 'none'})`);
    cleanup(tmpDir);
  }

  // Success path (markInterrupted).
  {
    const { tmpDir, agenticDir } = makeTmp('ae-state-mark-f2-');
    writeLoopState(agenticDir, { status: 'active', session_id: 'sess-a' });
    stateMark.markInterrupted(tmpDir, 'sess-a');
    const tmpFiles = fs.readdirSync(agenticDir).filter((f) => f.endsWith('.tmp'));
    assert(tmpFiles.length === 0, `(markInterrupted success) no .tmp remains (found: ${tmpFiles.join(', ') || 'none'})`);
    cleanup(tmpDir);
  }

  // Corrupt-JSON path: pre-plant a stale .tmp, feed corrupt loop-state.json,
  // confirm the catch-block cleanup removes it (mirrors #262's regression
  // pattern in test-stop-context-session-log.js sub-test 5).
  {
    const { tmpDir, agenticDir } = makeTmp('ae-state-mark-f3-');
    const loopStatePath = path.join(agenticDir, 'loop-state.json');
    fs.writeFileSync(loopStatePath, '{ bad json !!');
    const staleTmp = loopStatePath + '.tmp';
    fs.writeFileSync(staleTmp, 'stale content from a previous crashed session');

    stateMark.refreshLiveness(tmpDir, 'sess-a');

    const tmpFiles = fs.readdirSync(agenticDir).filter((f) => f.endsWith('.tmp'));
    assert(tmpFiles.length === 0,
      `(corrupt-JSON) stale .tmp cleaned up by catch block (found: ${tmpFiles.join(', ') || 'none'})`);
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// (g) health label on the real code path: corrupt-JSON hits
//     onOutcome('writeLoopState', false, ...) - literal target string.
// ---------------------------------------------------------------------------
console.log('\n[g] onOutcome health label: corrupt-JSON reports target "writeLoopState"');
{
  const { tmpDir, agenticDir } = makeTmp('ae-state-mark-g-');
  const loopStatePath = path.join(agenticDir, 'loop-state.json');
  fs.writeFileSync(loopStatePath, '{ bad json !!');

  const outcomes = [];
  const onOutcome = (target, success, errMsg) => outcomes.push({ target, success, errMsg });

  stateMark.refreshLiveness(tmpDir, 'sess-a', onOutcome);

  const loopStateOutcome = outcomes.find((o) => o.target === 'writeLoopState');
  assert(loopStateOutcome !== undefined, 'onOutcome called with target === "writeLoopState" (literal label)');
  if (loopStateOutcome) {
    assert(loopStateOutcome.success === false, `writeLoopState outcome success === false (got: ${loopStateOutcome.success})`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Bonus: candidate set is exactly the two legacy paths (Unit 1 scope pin).
// ---------------------------------------------------------------------------
console.log('\n[bonus] _candidatePaths is exactly the two legacy paths');
{
  assert(Array.isArray(stateMark._candidatePaths), '_candidatePaths is exported as an array');
  assert(stateMark._candidatePaths.length === 2, `_candidatePaths has exactly 2 entries (got: ${stateMark._candidatePaths.length})`);
  assert(stateMark._candidatePaths.includes('.agentic/loop-state.json'), '_candidatePaths includes .agentic/loop-state.json');
  assert(stateMark._candidatePaths.includes('.agentic/batch-state.json'), '_candidatePaths includes .agentic/batch-state.json');
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
