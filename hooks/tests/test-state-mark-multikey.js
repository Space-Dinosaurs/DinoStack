#!/usr/bin/env node
/**
 * Purpose: pin the per-ticket keying property that is the whole point of
 *          keyed loop-state files - two sessions working two different
 *          tickets in ONE checkout each keep their own bookkeeping, so
 *          neither cadence function can touch the other session's file.
 *          Complements hooks/tests/test-state-mark.js's candidatePaths()
 *          set assertions with the behavioral half: enumeration is not
 *          the same property as per-file ownership being honored.
 *
 * Test cases:
 *   (a) refreshLiveness with session A's id refreshes ONLY
 *       loop-state-DS-90.json (A's file); loop-state-DS-91.json (B's file)
 *       stays byte-identical. Then the mirror with B's id.
 *   (b) markInterrupted with session A's id marks ONLY A's file; B's file
 *       stays byte-identical (positive differing match aborts per-file).
 *   (c) both LEGACY paths remain in the candidate set even when keyed files
 *       are present - the legacy .agentic/loop-state.json and
 *       .agentic/batch-state.json rows are unconditional (expansion rule 1),
 *       so a repo mid-migration never loses legacy detection.
 *
 * Upstream deps: Node built-ins only (fs, os, path) plus hooks/lib/state-mark.js.
 *                Operates entirely inside a fresh os.tmpdir() sandbox; touches
 *                no repo file.
 *
 * Downstream consumers: none (leaf test). Discovered by the
 *                       `for f in hooks/tests/test-*.js` loop in CI and in
 *                       the ds-implement-ticket verification command.
 *
 * Failure modes: exits 1 with a per-assertion FAIL line on any miss; the
 *                verdict is derived from its own pass/fail counters, not from
 *                a bare shell test.
 *
 * Performance: standard - a handful of small fs writes, no subprocess spawn.
 *
 * Run with: node hooks/tests/test-state-mark-multikey.js
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

const SESSION_A = 'sess-aaaaaaaa';
const SESSION_B = 'sess-bbbbbbbb';
const STALE = '2020-01-01T00:00:00.000Z';

function makeTmp() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'state-mark-multikey-'));
  const agenticDir = path.join(tmpDir, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  return { tmpDir, agenticDir };
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
}

// Two keyed files, two distinct owners, one checkout.
function plantTwoTickets(agenticDir) {
  fs.writeFileSync(
    path.join(agenticDir, 'loop-state-DS-90.json'),
    JSON.stringify({ ticket_id: 'DS-90', loop_key: 'DS-90', session_id: SESSION_A, status: 'active', last_updated: STALE }, null, 2)
  );
  fs.writeFileSync(
    path.join(agenticDir, 'loop-state-DS-91.json'),
    JSON.stringify({ ticket_id: 'DS-91', loop_key: 'DS-91', session_id: SESSION_B, status: 'active', last_updated: STALE }, null, 2)
  );
}

function raw(agenticDir, name) {
  return fs.readFileSync(path.join(agenticDir, name), 'utf8');
}

// ---------------------------------------------------------------------------
// (a) refreshLiveness touches exactly the invoking session's keyed file.
// ---------------------------------------------------------------------------
console.log('[a] refreshLiveness touches exactly one keyed file per session');
{
  const { tmpDir, agenticDir } = makeTmp();
  plantTwoTickets(agenticDir);
  const beforeA = raw(agenticDir, 'loop-state-DS-90.json');
  const beforeB = raw(agenticDir, 'loop-state-DS-91.json');

  stateMark.refreshLiveness(tmpDir, SESSION_A);
  assert(raw(agenticDir, 'loop-state-DS-90.json') !== beforeA, "session A's refresh updated loop-state-DS-90.json");
  assert(raw(agenticDir, 'loop-state-DS-91.json') === beforeB, "session A's refresh left loop-state-DS-91.json BYTE-IDENTICAL (no cross-ticket contention)");
  assert(JSON.parse(raw(agenticDir, 'loop-state-DS-90.json')).status === 'active', "A's file is still status:active (liveness cadence never changes status)");

  const afterA = raw(agenticDir, 'loop-state-DS-90.json');
  stateMark.refreshLiveness(tmpDir, SESSION_B);
  assert(raw(agenticDir, 'loop-state-DS-91.json') !== beforeB, "session B's refresh updated loop-state-DS-91.json");
  assert(raw(agenticDir, 'loop-state-DS-90.json') === afterA, "session B's refresh left loop-state-DS-90.json BYTE-IDENTICAL");
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (b) markInterrupted marks exactly the invoking session's keyed file.
// ---------------------------------------------------------------------------
console.log('\n[b] markInterrupted marks exactly one keyed file per session');
{
  const { tmpDir, agenticDir } = makeTmp();
  plantTwoTickets(agenticDir);
  const beforeB = raw(agenticDir, 'loop-state-DS-91.json');

  stateMark.markInterrupted(tmpDir, SESSION_A);
  assert(JSON.parse(raw(agenticDir, 'loop-state-DS-90.json')).status === 'interrupted', "session A's terminal mark set loop-state-DS-90.json to interrupted");
  assert(raw(agenticDir, 'loop-state-DS-91.json') === beforeB, "session A's terminal mark left loop-state-DS-91.json BYTE-IDENTICAL (foreign owner aborts)");
  assert(JSON.parse(raw(agenticDir, 'loop-state-DS-90.json')).last_updated === STALE, "A's last_updated was NOT touched on the terminal mark (touchTimestampOnTerminal:false inherited)");
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (c) both legacy paths stay in the candidate set alongside keyed files.
//     Expansion rule 1 - the legacy .agentic/loop-state.json and
//     .agentic/batch-state.json rows are UNCONDITIONAL, so a repo that is
//     mid-migration (a legacy file plus keyed siblings) still gets its legacy
//     file detected, adopted and cleaned rather than silently orphaned.
// ---------------------------------------------------------------------------
console.log('\n[c] legacy candidates survive alongside keyed candidates');
{
  const { tmpDir, agenticDir } = makeTmp();
  plantTwoTickets(agenticDir);
  fs.writeFileSync(path.join(agenticDir, 'loop-state.json'), JSON.stringify({ status: 'active', last_updated: STALE }, null, 2));
  fs.writeFileSync(path.join(agenticDir, 'batch-state.json'), JSON.stringify({ status: 'active', updated_at: STALE }, null, 2));

  const paths = stateMark.candidatePaths(tmpDir);
  assert(paths.includes('.agentic/loop-state.json'), 'candidate set still includes the legacy .agentic/loop-state.json');
  assert(paths.includes('.agentic/batch-state.json'), 'candidate set still includes .agentic/batch-state.json');
  assert(paths.includes('.agentic/loop-state-DS-90.json') && paths.includes('.agentic/loop-state-DS-91.json'), 'candidate set includes both keyed siblings');
  assert(paths.length === 4, `candidate set is exactly 4 entries (got ${paths.length}: ${JSON.stringify(paths)})`);
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
