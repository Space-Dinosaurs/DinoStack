#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/skill-candidate-deep-cluster.js
 *
 * All tests use temp dirs (fs.mkdtempSync) and never touch the real .agentic/.
 * Covers both the library (mergeClusterResults) and the CLI entrypoint.
 *
 * Test cases:
 *   (a) one-cluster-one-session: 1 cluster, 1 session -> count 1, wrapSessionsApplied=[sid]
 *   (b) same-session-dedup: same session re-merged -> count stays 1
 *   (c) three-distinct-sessions-surface: 3 distinct sessions same domain -> count 3,
 *       appended once to skill-candidates.md, surfacedAt set
 *   (d) fourth-session-no-second-append: 4th session after surfaced -> count 4,
 *       no second ## heading in skill-candidates.md
 *   (e) dismiss-not-revived: entry with surfacedAt set (simulate dismissed state) ->
 *       merge does NOT re-append/revive
 *   (f) suggested-artifact-derivation: LLM hint valid -> used; invalid hint -> taxonomy
 *       fallback; absent -> taxonomy; 'review' keyword -> named-agent
 *   (g) cli-contract: valid invocation merges; empty sid / missing file / [] -> exit 0 no-op
 *   (h) coexistence: tally with existing learnDatesApplied (events path data) is updated
 *       additively; learnDatesApplied untouched by wrap merge
 *
 * Also runs existing detector suite to confirm additive wrapSessionsApplied field
 * does not break V1 behavior.
 *
 * Run with: node hooks/tests/test-skill-candidate-deep-cluster.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

// ---------------------------------------------------------------------------
// Load modules under test
// ---------------------------------------------------------------------------

const helperPath = path.resolve(__dirname, '..', 'lib', 'skill-candidate-deep-cluster.js');
const detectorPath = path.resolve(__dirname, '..', 'lib', 'skill-candidate-detector.js');

const { mergeClusterResults } = require(helperPath);
const { _readTally, CANDIDATE_THRESHOLD } = require(detectorPath);

// ---------------------------------------------------------------------------
// Test harness
// ---------------------------------------------------------------------------

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

function assertDeepEqual(actual, expected, message) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message} (expected ${e}, got ${a})`);
    failed++;
  }
}

/** Create a temporary project root with .agentic/. */
function makeTempProject() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-dctest-'));
  fs.mkdirSync(path.join(tmpDir, '.agentic'), { recursive: true });
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

/** Read skill-candidates.md, or '' if absent. */
function readCandidates(cwd) {
  try {
    return fs.readFileSync(path.join(cwd, '.agentic', 'skill-candidates.md'), 'utf8');
  } catch (_) {
    return '';
  }
}

/** Count occurrences of a heading in the candidates file. */
function countHeadings(cwd, domain) {
  const content = readCandidates(cwd);
  return (content.match(new RegExp(`## ${domain}`, 'g')) || []).length;
}

// ---------------------------------------------------------------------------
// Test (a): one-cluster-one-session
// ---------------------------------------------------------------------------
console.log('\nTest (a): one-cluster-one-session');
{
  const cwd = makeTempProject();
  const sid = 'session-aaa';
  const clusters = [{ domain: 'adapter-rebuild', exampleNote: 'Had to rebuild all 10 adapters manually.' }];

  mergeClusterResults(cwd, sid, clusters);

  const tally = _readTally(cwd);
  const entry = tally.candidates['adapter-rebuild'];

  assert(!!entry, 'tally has adapter-rebuild entry');
  assertEqual(entry.count, 1, 'count is 1');
  assert(Array.isArray(entry.wrapSessionsApplied), 'wrapSessionsApplied is an array');
  assertEqual(entry.wrapSessionsApplied.length, 1, 'wrapSessionsApplied has 1 entry');
  assertEqual(entry.wrapSessionsApplied[0], sid, 'wrapSessionsApplied[0] is the session id');
  assert(!!entry.firstSeen, 'firstSeen is set');
  assert(!!entry.lastSeen, 'lastSeen is set');
  assert(!entry.surfacedAt, 'surfacedAt not set (count 1 < threshold)');
  assertEqual(readCandidates(cwd), '', 'skill-candidates.md not written below threshold');

  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (b): same-session-dedup
// ---------------------------------------------------------------------------
console.log('\nTest (b): same-session-dedup');
{
  const cwd = makeTempProject();
  const sid = 'session-bbb';
  const clusters = [{ domain: 'adapter-rebuild', exampleNote: 'Rebuilt adapters again.' }];

  mergeClusterResults(cwd, sid, clusters);
  mergeClusterResults(cwd, sid, clusters); // same session, same domain

  const tally = _readTally(cwd);
  const entry = tally.candidates['adapter-rebuild'];

  assertEqual(entry.count, 1, 'count stays 1 on same-session re-merge (dedup)');
  assertEqual(entry.wrapSessionsApplied.length, 1, 'wrapSessionsApplied length stays 1');

  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (c): three-distinct-sessions-surface
// ---------------------------------------------------------------------------
console.log('\nTest (c): three-distinct-sessions-surface');
{
  const cwd = makeTempProject();
  const domain = 'skeptic-context-block';

  mergeClusterResults(cwd, 'sid-c1', [{ domain, exampleNote: 'First instance.' }]);
  mergeClusterResults(cwd, 'sid-c2', [{ domain, exampleNote: 'Second instance.' }]);
  mergeClusterResults(cwd, 'sid-c3', [{ domain, exampleNote: 'Third instance.' }]);

  const tally = _readTally(cwd);
  const entry = tally.candidates[domain];

  assertEqual(entry.count, 3, 'count is 3 after 3 distinct sessions');
  assertEqual(entry.wrapSessionsApplied.length, 3, 'wrapSessionsApplied has 3 entries');
  assert(!!entry.surfacedAt, 'surfacedAt is set after crossing threshold');

  const headings = countHeadings(cwd, domain);
  assertEqual(headings, 1, 'skill-candidates.md has exactly one ## heading for the domain');

  const candidates = readCandidates(cwd);
  assert(candidates.includes(`## ${domain}`), 'domain heading present in skill-candidates.md');
  assert(candidates.includes('**Count:** 3'), 'count 3 in candidates file');
  assert(candidates.includes('**Status:** open'), 'status is open');

  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (d): fourth-session-no-second-append
// ---------------------------------------------------------------------------
console.log('\nTest (d): fourth-session-no-second-append');
{
  const cwd = makeTempProject();
  const domain = 'wrap-deferred-manual';

  mergeClusterResults(cwd, 'sid-d1', [{ domain, exampleNote: 'e1' }]);
  mergeClusterResults(cwd, 'sid-d2', [{ domain, exampleNote: 'e2' }]);
  mergeClusterResults(cwd, 'sid-d3', [{ domain, exampleNote: 'e3' }]);
  mergeClusterResults(cwd, 'sid-d4', [{ domain, exampleNote: 'e4' }]);

  const tally = _readTally(cwd);
  assertEqual(tally.candidates[domain].count, 4, 'count is 4 after 4 sessions');

  const headings = countHeadings(cwd, domain);
  assertEqual(headings, 1, 'skill-candidates.md still has exactly one heading (no second append)');

  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (e): dismiss-not-revived
// ---------------------------------------------------------------------------
console.log('\nTest (e): dismiss-not-revived (surfacedAt already set -> no re-append)');
{
  const cwd = makeTempProject();
  const domain = 'pr-review-checklist';

  // Simulate a tally entry that was already surfaced (by events path or prior wrap).
  const { _writeTally: wt } = require(detectorPath);
  const existingTally = {
    version: 1,
    lastCursorTs: null,
    candidates: {
      [domain]: {
        count: 4,
        exampleNote: 'Existing example.',
        firstSeen: '2026-01-01T00:00:00.000Z',
        lastSeen: '2026-01-04T00:00:00.000Z',
        suggestedArtifact: 'named-agent',
        surfacedAt: '2026-01-04T00:00:00.000Z', // already surfaced
        learnDatesApplied: [],
        wrapSessionsApplied: ['sid-old-1', 'sid-old-2', 'sid-old-3', 'sid-old-4'],
      },
    },
  };
  wt(cwd, existingTally);

  // Write an existing candidates file with the heading (as if it was surfaced before).
  const existingCandidates = `# Skill Candidates\n\nDetected recurring friction patterns.\n\n## ${domain}\n**Count:** 4\n**Status:** open\n`;
  fs.writeFileSync(path.join(cwd, '.agentic', 'skill-candidates.md'), existingCandidates, 'utf8');

  // Now merge a new session.
  mergeClusterResults(cwd, 'sid-e-new', [{ domain, exampleNote: 'New session friction.' }]);

  // Count must increment.
  const tally = _readTally(cwd);
  assertEqual(tally.candidates[domain].count, 5, 'count increments to 5');

  // No second heading appended.
  const headings = countHeadings(cwd, domain);
  assertEqual(headings, 1, 'still only one heading in skill-candidates.md (not re-appended)');

  // surfacedAt unchanged from original.
  assertEqual(tally.candidates[domain].surfacedAt, '2026-01-04T00:00:00.000Z', 'surfacedAt unchanged');

  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (f): suggested-artifact-derivation
// ---------------------------------------------------------------------------
console.log('\nTest (f): suggested-artifact-derivation');
{
  const cwd = makeTempProject();

  // f1: valid LLM hint 'preset' -> used as-is.
  mergeClusterResults(cwd, 'sid-f1', [{ domain: 'tone-style', exampleNote: 'n', suggestedArtifact: 'preset' }]);
  let tally = _readTally(cwd);
  assertEqual(tally.candidates['tone-style'].suggestedArtifact, 'preset', 'valid LLM hint "preset" is used');

  // f2: invalid LLM hint -> taxonomy fallback (keyword 'audit' -> named-agent).
  mergeClusterResults(cwd, 'sid-f2', [{ domain: 'code-audit', exampleNote: 'n', suggestedArtifact: 'invalid-thing' }]);
  tally = _readTally(cwd);
  assertEqual(tally.candidates['code-audit'].suggestedArtifact, 'named-agent', 'invalid hint falls back to taxonomy ("audit" -> named-agent)');

  // f3: absent hint -> taxonomy (keyword 'lint' -> lint-rule).
  mergeClusterResults(cwd, 'sid-f3', [{ domain: 'eslint-custom', exampleNote: 'n' }]);
  tally = _readTally(cwd);
  assertEqual(tally.candidates['eslint-custom'].suggestedArtifact, 'lint-rule', 'absent hint falls back to taxonomy ("eslint" -> lint-rule)');

  // f4: no taxonomy match -> 'command' default.
  mergeClusterResults(cwd, 'sid-f4', [{ domain: 'git-push-workaround', exampleNote: 'n' }]);
  tally = _readTally(cwd);
  assertEqual(tally.candidates['git-push-workaround'].suggestedArtifact, 'command', 'no keyword match defaults to "command"');

  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (g): CLI contract
// ---------------------------------------------------------------------------
console.log('\nTest (g): cli-contract');
{
  const cwd = makeTempProject();
  const tmpJson = path.join(cwd, 'clusters.json');

  // g1: valid invocation -> merges.
  const clusters = [{ domain: 'cli-domain', exampleNote: 'Via CLI.' }];
  fs.writeFileSync(tmpJson, JSON.stringify(clusters), 'utf8');

  let result;
  try {
    result = execFileSync(process.execPath, [helperPath, cwd, 'session-cli-g1', tmpJson], { encoding: 'utf8' });
    assert(true, 'CLI exits 0 on valid invocation');
  } catch (e) {
    assert(false, `CLI should exit 0 but threw: ${e.message}`);
  }

  let tally = _readTally(cwd);
  assertEqual(tally.candidates['cli-domain'] && tally.candidates['cli-domain'].count, 1, 'CLI merge incremented count to 1');

  // g2: empty session_id -> exit 0, no writes.
  const cwdG2 = makeTempProject();
  const tmpG2 = path.join(cwdG2, 'c.json');
  fs.writeFileSync(tmpG2, JSON.stringify([{ domain: 'd', exampleNote: 'e' }]), 'utf8');

  try {
    execFileSync(process.execPath, [helperPath, cwdG2, '', tmpG2], { encoding: 'utf8' });
    assert(true, 'CLI exits 0 with empty session_id');
  } catch (e) {
    assert(false, `CLI should exit 0 with empty session_id but threw: ${e.message}`);
  }
  tally = _readTally(cwdG2);
  assert(!tally.candidates['d'], 'no write when session_id is empty');

  cleanup(cwdG2);

  // g3: missing clusters file -> exit 0, no writes.
  const cwdG3 = makeTempProject();
  try {
    execFileSync(process.execPath, [helperPath, cwdG3, 'sid-g3', '/nonexistent/file.json'], { encoding: 'utf8' });
    assert(true, 'CLI exits 0 when clusters file is missing');
  } catch (e) {
    assert(false, `CLI should exit 0 with missing file but threw: ${e.message}`);
  }
  tally = _readTally(cwdG3);
  assert(Object.keys(tally.candidates).length === 0, 'no writes when clusters file is missing');

  cleanup(cwdG3);

  // g4: empty array [] -> exit 0, no writes.
  const cwdG4 = makeTempProject();
  const tmpG4 = path.join(cwdG4, 'empty.json');
  fs.writeFileSync(tmpG4, '[]', 'utf8');

  try {
    execFileSync(process.execPath, [helperPath, cwdG4, 'sid-g4', tmpG4], { encoding: 'utf8' });
    assert(true, 'CLI exits 0 with empty array');
  } catch (e) {
    assert(false, `CLI should exit 0 with [] but threw: ${e.message}`);
  }
  tally = _readTally(cwdG4);
  assert(Object.keys(tally.candidates).length === 0, 'no writes for [] clusters array');

  cleanup(cwdG4);
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (h): coexistence with learnDatesApplied (events path data untouched)
// ---------------------------------------------------------------------------
console.log('\nTest (h): coexistence - learnDatesApplied untouched by wrap merge');
{
  const cwd = makeTempProject();
  const { _writeTally: wt } = require(detectorPath);
  const domain = 'npm-auth';

  // Pre-seed a tally with events-path data (learnDatesApplied + count from events path).
  const seedTally = {
    version: 1,
    lastCursorTs: '2026-01-05T00:00:00.000Z',
    candidates: {
      [domain]: {
        count: 2,
        exampleNote: 'Existing events note.',
        firstSeen: '2026-01-03T00:00:00.000Z',
        lastSeen: '2026-01-04T00:00:00.000Z',
        suggestedArtifact: 'command',
        surfacedAt: null,
        learnDatesApplied: ['2026-01-03', '2026-01-04'],
        wrapSessionsApplied: [],
      },
    },
  };
  wt(cwd, seedTally);

  // Wrap merge adds 1 via a new session, hitting threshold 3.
  mergeClusterResults(cwd, 'sid-h1', [{ domain, exampleNote: 'Wrap session friction.' }]);

  const tally = _readTally(cwd);
  const entry = tally.candidates[domain];

  assertEqual(entry.count, 3, 'count incremented from 2 to 3 (events 2 + wrap 1)');
  assert(!!entry.surfacedAt, 'surfacedAt set when hitting threshold');

  // learnDatesApplied must be untouched.
  assertDeepEqual(entry.learnDatesApplied, ['2026-01-03', '2026-01-04'], 'learnDatesApplied unchanged by wrap merge');

  // wrapSessionsApplied has the new session.
  assert(entry.wrapSessionsApplied.includes('sid-h1'), 'wrapSessionsApplied includes new session');

  // Candidate appended to file.
  const headings = countHeadings(cwd, domain);
  assertEqual(headings, 1, 'candidate written once when wrap crosses threshold');

  // lastCursorTs in tally is preserved (wrap path does not touch it).
  assertEqual(tally.lastCursorTs, '2026-01-05T00:00:00.000Z', 'lastCursorTs preserved by wrap merge');

  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Summary + run existing detector suite
// ---------------------------------------------------------------------------

// Give all synchronous tests a moment then report, then run detector suite.
setImmediate(() => {
  console.log(`\n--- Deep-cluster test results: ${passed} passed, ${failed} failed ---`);

  if (failed > 0) {
    process.exit(1);
  }

  // Run existing detector suite to verify additive wrapSessionsApplied field
  // does not break V1 behavior.
  console.log('\n--- Running existing detector suite (regression check) ---');
  try {
    const output = execFileSync(
      process.execPath,
      [path.resolve(__dirname, 'test-skill-candidate-detector.js')],
      { encoding: 'utf8', timeout: 30000 }
    );
    // Print detector suite output so CI captures it.
    process.stdout.write(output);
    console.log('\n--- Detector suite: PASS ---');
  } catch (e) {
    // execFileSync throws on non-zero exit.
    process.stdout.write(e.stdout || '');
    process.stderr.write(e.stderr || '');
    console.error('\n--- Detector suite: FAIL ---');
    process.exit(1);
  }
});
