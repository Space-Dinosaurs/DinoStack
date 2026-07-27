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
// Bonus: candidatePaths(cwd) resolves legacy + per-ticket keyed siblings.
//
// This block REPLACES Unit 1's `_candidatePaths.length === 2` tripwire, which
// was installed specifically so a per-ticket keying extension would be
// visible. Deleting it rather than strengthening it is the cheapest green and
// is forbidden; assertion 5 is what makes the removal deliberate, since simply
// dropping the old block does not satisfy it.
// ---------------------------------------------------------------------------
console.log('\n[bonus] candidatePaths(cwd) resolves legacy + keyed loop-state candidates');
{
  const { tmpDir, agenticDir } = makeTmp('state-mark-candidates-');
  fs.writeFileSync(path.join(agenticDir, 'loop-state.json'), '{}');
  fs.writeFileSync(path.join(agenticDir, 'batch-state.json'), '{}');
  fs.writeFileSync(path.join(agenticDir, 'loop-state-DS-90.json'), '{}');
  fs.writeFileSync(path.join(agenticDir, 'loop-state-session-abc.json'), '{}');
  // Decoy: matches the prefix but is not .json - expansion rule 4 excludes it.
  fs.writeFileSync(path.join(agenticDir, 'loop-state-notjson.txt'), 'decoy');

  // 1. the public API is a function, not a static array.
  assert(typeof stateMark.candidatePaths === 'function', 'candidatePaths is exported as a function');

  // 2. returns exactly the four real paths, as a set, with the decoy absent.
  const got = stateMark.candidatePaths(tmpDir).slice().sort();
  const want = [
    '.agentic/batch-state.json',
    '.agentic/loop-state-DS-90.json',
    '.agentic/loop-state-session-abc.json',
    '.agentic/loop-state.json',
  ].sort();
  assert(
    JSON.stringify(got) === JSON.stringify(want),
    `candidatePaths returns exactly the four real paths, decoy excluded (got: ${JSON.stringify(got)})`
  );

  // 3. the two legacy rows are UNCONDITIONAL - a cwd with no .agentic/ at all
  //    still yields them (expansion rule 1: legacy detection can never be lost
  //    to a directory-read failure).
  const bareDir = fs.mkdtempSync(path.join(os.tmpdir(), 'state-mark-bare-'));
  const bare = stateMark.candidatePaths(bareDir).slice().sort();
  assert(
    JSON.stringify(bare) === JSON.stringify(['.agentic/batch-state.json', '.agentic/loop-state.json']),
    `candidatePaths on a cwd with no .agentic/ still returns exactly the two legacy paths (got: ${JSON.stringify(bare)})`
  );
  cleanup(bareDir);

  // 4. every keyed row's metadata deep-equals the legacy loop-state row's
  //    (expansion rule 2: keyed files inherit, they never author metadata).
  //    Observed through behavior the module exports: a keyed file at
  //    status:"active" with no session_id must be treated EXACTLY as the
  //    legacy file is - markInterrupted proceeds, and last_updated is NOT
  //    touched (touchTimestampOnTerminal:false inherited from the parent row).
  const activeNoSid = { status: 'active', last_updated: '2020-01-01T00:00:00.000Z' };
  fs.writeFileSync(path.join(agenticDir, 'loop-state.json'), JSON.stringify(activeNoSid));
  fs.writeFileSync(path.join(agenticDir, 'loop-state-DS-90.json'), JSON.stringify(activeNoSid));
  const keyedTargets = [];
  stateMark.markInterrupted(tmpDir, 'sess-meta', (target) => keyedTargets.push(target));
  const legacyAfter = JSON.parse(fs.readFileSync(path.join(agenticDir, 'loop-state.json'), 'utf8'));
  const keyedAfter = JSON.parse(fs.readFileSync(path.join(agenticDir, 'loop-state-DS-90.json'), 'utf8'));
  assert(
    keyedAfter.status === legacyAfter.status
      && keyedAfter.interrupt_reason === legacyAfter.interrupt_reason
      && keyedAfter.last_updated === activeNoSid.last_updated
      && legacyAfter.last_updated === activeNoSid.last_updated
      && keyedTargets.filter((t) => t === 'writeLoopState').length >= 2,
    'keyed row metadata (tsField / healthTarget / touchTimestampOnTerminal) is inherited verbatim from the legacy loop-state row'
  );

  // 5. the static export is GONE. Retaining it alongside the function would
  //    make the manifest's load-bearing "cannot drift from what the module
  //    reads" claim false on a correctness path.
  assert(
    stateMark._candidatePaths === undefined,
    `module.exports._candidatePaths is undefined - the static export is removed, not shadowed (got: ${JSON.stringify(stateMark._candidatePaths)})`
  );

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
