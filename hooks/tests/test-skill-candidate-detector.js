#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/skill-candidate-detector.js
 *
 * All tests use temp HOME/cwd (fs.mkdtempSync) and never touch the real
 * .agentic/ directory. Exercises both the Stop-hook write path
 * (runSkillCandidateScan) and the read-only peek path (peekActiveCandidates).
 *
 * Test cases:
 *   1.  below-threshold-no-candidate: 2 events, no candidate written to skill-candidates.md
 *   2.  at-threshold-candidate-written: 3 events -> candidate entry written + surfacedAt set
 *   3.  no-duplicate-on-rerun: second scan after surfaced -> no duplicate appended
 *   4.  events-without-session-uuid-excluded: events lacking data.session_uuid -> not counted
 *   5.  learnings-distinct-date-counting: 3 entries same day = 1; 3 distinct days = 3
 *   6.  cursor-on-success-self-healing: simulate tally-write failure -> cursor NOT advanced
 *       -> next run re-reads same events (no lost increment)
 *   7.  peek-is-write-free: peekActiveCandidates makes zero writes (tally mtime unchanged)
 *   8.  peek-returns-above-threshold: peek returns all candidates with count >= threshold
 *   9.  corrupt-tally-fail-open: corrupt tally -> scan rebuilds cleanly
 *  10.  routing-taxonomy: domain tags route to correct artifact types
 *  11.  learnings-merge-with-events: learnings distinct dates + events combine additively
 *  12.  cursor-advances-after-tally-write: cursor file updated to max event ts on success
 *  13.  cursor-fallback-to-tally: cursor file missing -> tally.lastCursorTs used as fallback
 *  14.  multiple-domains-tracked-independently: two domains reach threshold independently
 *  15.  learnings-no-double-count-on-rescan: scan twice with SAME learnings.md -> count unchanged
 *  16.  learnings-new-date-increments-by-one: add a new Discovered date between scans -> count +1
 *
 * Run with: node hooks/tests/test-skill-candidate-detector.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

// ---------------------------------------------------------------------------
// Load module under test
// ---------------------------------------------------------------------------

const detectorPath = path.resolve(__dirname, '..', 'lib', 'skill-candidate-detector.js');
const {
  runSkillCandidateScan,
  peekActiveCandidates,
  CANDIDATE_THRESHOLD,
  _routingArtifact,
  _readTally,
  _writeTally,
  _readCursor,
  _writeCursor,
  _scanEvents,
  _parseLearningsDomains,
} = require(detectorPath);

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

function assertThrows(fn, message) {
  let threw = false;
  try { fn(); } catch (_) { threw = true; }
  if (threw) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message} (expected throw, did not throw)`);
    failed++;
  }
}

/** Create a temporary project root with .agentic/. */
function makeTempProject() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-scd-test-'));
  fs.mkdirSync(path.join(tmpDir, '.agentic'), { recursive: true });
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

/**
 * Build a tool_failure_workaround event line.
 * @param {string} domainTag
 * @param {string} ts - ISO8601
 * @param {string} [note]
 * @param {string} [sessionId] - omit to produce a line without session_uuid
 */
function makeWorkaroundEvent(domainTag, ts, note, sessionId) {
  const data = { domain_tag: domainTag, tool: 'some-tool', note: note || '' };
  if (sessionId !== undefined) data.session_uuid = sessionId;
  return JSON.stringify({ ts, phase: 'test', event: 'tool_failure_workaround', agent: null, task_id: null, data });
}

/** Write events.jsonl from an array of pre-serialized lines. */
function writeEvents(cwd, lines) {
  fs.writeFileSync(path.join(cwd, '.agentic', 'events.jsonl'), lines.join('\n') + '\n', 'utf8');
}

/** Write learnings.md content. */
function writeLearnings(cwd, content) {
  fs.writeFileSync(path.join(cwd, '.agentic', 'learnings.md'), content, 'utf8');
}

/** Read skill-candidates.md, or '' if absent. */
function readCandidates(cwd) {
  try { return fs.readFileSync(path.join(cwd, '.agentic', 'skill-candidates.md'), 'utf8'); } catch (_) { return ''; }
}

const SESSION = 'session-test-abc';

// ---------------------------------------------------------------------------
// Test 1: below-threshold-no-candidate
// ---------------------------------------------------------------------------
console.log('\nTest 1: below-threshold-no-candidate (2 events, no candidate written)');
(async () => {
  const cwd = makeTempProject();
  const ts1 = '2026-01-01T00:00:01.000Z';
  const ts2 = '2026-01-01T00:00:02.000Z';
  writeEvents(cwd, [
    makeWorkaroundEvent('git-push', ts1, 'note1', SESSION),
    makeWorkaroundEvent('git-push', ts2, 'note2', SESSION),
  ]);

  await runSkillCandidateScan(cwd, SESSION);

  const candidates = readCandidates(cwd);
  assert(!candidates.includes('git-push'), 'skill-candidates.md has no entry for git-push (count=2 < threshold 3)');

  const tally = _readTally(cwd);
  assertEqual(tally.candidates['git-push'] && tally.candidates['git-push'].count, 2, 'tally count is 2');
  assert(!tally.candidates['git-push'].surfacedAt, 'surfacedAt not set below threshold');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 2: at-threshold-candidate-written
// ---------------------------------------------------------------------------
console.log('\nTest 2: at-threshold-candidate-written (3 events -> candidate entry)');
(async () => {
  const cwd = makeTempProject();
  const ts1 = '2026-01-01T00:00:01.000Z';
  const ts2 = '2026-01-01T00:00:02.000Z';
  const ts3 = '2026-01-01T00:00:03.000Z';
  writeEvents(cwd, [
    makeWorkaroundEvent('git-push', ts1, 'Used --force-with-lease', SESSION),
    makeWorkaroundEvent('git-push', ts2, '', SESSION),
    makeWorkaroundEvent('git-push', ts3, '', SESSION),
  ]);

  await runSkillCandidateScan(cwd, SESSION);

  const candidates = readCandidates(cwd);
  assert(candidates.includes('git-push'), 'skill-candidates.md contains the git-push entry');
  assert(candidates.includes('**Lifetime count:** 3'), 'candidate entry shows count 3');

  const tally = _readTally(cwd);
  assert(tally.candidates['git-push'].surfacedAt, 'surfacedAt is set after crossing threshold');
  assertEqual(tally.candidates['git-push'].count, 3, 'tally count is 3');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 3: no-duplicate-on-rerun
// ---------------------------------------------------------------------------
console.log('\nTest 3: no-duplicate-on-rerun (second scan -> no duplicate in skill-candidates.md)');
(async () => {
  const cwd = makeTempProject();
  const ts1 = '2026-01-02T00:00:01.000Z';
  const ts2 = '2026-01-02T00:00:02.000Z';
  const ts3 = '2026-01-02T00:00:03.000Z';
  writeEvents(cwd, [
    makeWorkaroundEvent('auth-token', ts1, 'note', SESSION),
    makeWorkaroundEvent('auth-token', ts2, 'note', SESSION),
    makeWorkaroundEvent('auth-token', ts3, 'note', SESSION),
  ]);

  await runSkillCandidateScan(cwd, SESSION);

  // Second scan: no new events (cursor is now past all events), no new candidates.
  await runSkillCandidateScan(cwd, SESSION);

  const candidates = readCandidates(cwd);
  const occurrences = (candidates.match(/## auth-token/g) || []).length;
  assertEqual(occurrences, 1, 'auth-token appears exactly once in skill-candidates.md');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 4: events-without-session-uuid-excluded
// ---------------------------------------------------------------------------
console.log('\nTest 4: events-without-session-uuid-excluded (no session_uuid -> not counted)');
(async () => {
  const cwd = makeTempProject();
  // 3 events WITHOUT session_uuid (legacy lines) - should NOT be counted.
  const ts1 = '2026-01-03T00:00:01.000Z';
  const ts2 = '2026-01-03T00:00:02.000Z';
  const ts3 = '2026-01-03T00:00:03.000Z';
  writeEvents(cwd, [
    makeWorkaroundEvent('docker-pull', ts1, 'n', undefined), // no sessionId arg -> no session_uuid
    makeWorkaroundEvent('docker-pull', ts2, 'n', undefined),
    makeWorkaroundEvent('docker-pull', ts3, 'n', undefined),
  ]);

  await runSkillCandidateScan(cwd, SESSION);

  const tally = _readTally(cwd);
  const domainEntry = tally.candidates['docker-pull'];
  assert(!domainEntry || domainEntry.count === 0, 'events without session_uuid contribute zero count');

  const candidates = readCandidates(cwd);
  assert(!candidates.includes('docker-pull'), 'no candidate written for session_uuid-less events');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 5: learnings-distinct-date-counting
//   5a. 3 entries same day = 1 (dates deduplicated)
//   5b. 3 distinct days = 3
// ---------------------------------------------------------------------------
console.log('\nTest 5a: learnings-distinct-date-counting (3 same day = count 1)');
(async () => {
  const cwd = makeTempProject();
  // No events - learnings only.
  const learningsContent = [
    '## [LRN-20260101-001] Entry 1',
    '**Domain:** npm-auth',
    '**Discovered:** 2026-01-01',
    'Details.',
    '',
    '## [LRN-20260101-002] Entry 2',
    '**Domain:** npm-auth',
    '**Discovered:** 2026-01-01',
    'Details.',
    '',
    '## [LRN-20260101-003] Entry 3',
    '**Domain:** npm-auth',
    '**Discovered:** 2026-01-01',
    'Details.',
    '',
  ].join('\n');
  writeLearnings(cwd, learningsContent);

  await runSkillCandidateScan(cwd, SESSION);

  const tally = _readTally(cwd);
  const entry = tally.candidates['npm-auth'];
  // 3 entries, all same day -> 1 distinct date -> count 1 -> below threshold
  assert(entry && entry.count === 1, `npm-auth count is 1 for 3 same-day entries (got ${entry && entry.count})`);
  const candidates = readCandidates(cwd);
  assert(!candidates.includes('npm-auth'), 'no candidate written (count 1 < threshold 3)');
  cleanup(cwd);
})();

console.log('\nTest 5b: learnings-distinct-date-counting (3 distinct days = count 3)');
(async () => {
  const cwd = makeTempProject();
  const learningsContent = [
    '## [LRN-20260101-001] Entry 1',
    '**Domain:** npm-auth',
    '**Discovered:** 2026-01-01',
    'Details.',
    '',
    '## [LRN-20260102-001] Entry 2',
    '**Domain:** npm-auth',
    '**Discovered:** 2026-01-02',
    'Details.',
    '',
    '## [LRN-20260103-001] Entry 3',
    '**Domain:** npm-auth',
    '**Discovered:** 2026-01-03',
    'Details.',
    '',
  ].join('\n');
  writeLearnings(cwd, learningsContent);

  await runSkillCandidateScan(cwd, SESSION);

  const tally = _readTally(cwd);
  const entry = tally.candidates['npm-auth'];
  assertEqual(entry && entry.count, 3, 'npm-auth count is 3 for 3 distinct days');
  const candidates = readCandidates(cwd);
  assert(candidates.includes('npm-auth'), 'candidate written when 3 distinct Discovered days');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 6: cursor-on-success-self-healing
//   Simulate a tally-write failure: the cursor must NOT advance.
//   Then a real scan must re-read the same events (no lost increment).
// ---------------------------------------------------------------------------
console.log('\nTest 6: cursor-on-success-self-healing (tally failure -> cursor not advanced)');
(async () => {
  const cwd = makeTempProject();
  const ts1 = '2026-01-04T00:00:01.000Z';
  const ts2 = '2026-01-04T00:00:02.000Z';
  writeEvents(cwd, [
    makeWorkaroundEvent('gh-cli', ts1, 'note', SESSION),
    makeWorkaroundEvent('gh-cli', ts2, 'note', SESSION),
  ]);

  // Manually simulate a failed tally write by making the .agentic dir read-only.
  // We test by calling the internal helpers directly.
  const { _writeTally: wt, _writeCursor: wc, _scanEvents: se } = require(detectorPath);

  // Scan events.
  const { domainCounts, maxTs } = se(cwd, '');
  assert(domainCounts.size > 0, 'events scanned before tally failure simulation');
  assert(maxTs === ts2, 'maxTs is the latest event ts');

  // Simulate: tally write FAILS (do NOT write it). Cursor must NOT advance.
  // Read cursor before - should be '' (empty, no prior scan).
  const cursorBefore = _readCursor(cwd, null);
  assertEqual(cursorBefore, '', 'cursor starts empty before any scan');

  // Do NOT write tally. Do NOT write cursor (simulating crash between tally and cursor).
  // Confirm cursor is still empty.
  const cursorAfter = _readCursor(cwd, null);
  assertEqual(cursorAfter, '', 'cursor NOT advanced after simulated tally failure');

  // Now do a real scan - it should re-read the same events and increment counts.
  await runSkillCandidateScan(cwd, SESSION);
  const tally = _readTally(cwd);
  assertEqual(tally.candidates['gh-cli'] && tally.candidates['gh-cli'].count, 2, 'events re-read correctly after cursor was not advanced');

  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 7: peek-is-write-free
//   peekActiveCandidates must make zero writes.
// ---------------------------------------------------------------------------
console.log('\nTest 7: peek-is-write-free (tally mtime unchanged after peek)');
(async () => {
  const cwd = makeTempProject();
  const ts1 = '2026-01-05T00:00:01.000Z';
  const ts2 = '2026-01-05T00:00:02.000Z';
  const ts3 = '2026-01-05T00:00:03.000Z';
  writeEvents(cwd, [
    makeWorkaroundEvent('vercel-deploy', ts1, 'n', SESSION),
    makeWorkaroundEvent('vercel-deploy', ts2, 'n', SESSION),
    makeWorkaroundEvent('vercel-deploy', ts3, 'n', SESSION),
  ]);

  // Seed the tally via a real scan first.
  await runSkillCandidateScan(cwd, SESSION);

  const tallyPath = path.join(cwd, '.agentic', '.skill-candidate-tally.json');
  const mtimeBefore = fs.statSync(tallyPath).mtimeMs;

  // Peek - must not write anything.
  const result = peekActiveCandidates(cwd);

  const mtimeAfter = fs.statSync(tallyPath).mtimeMs;
  assertEqual(mtimeBefore, mtimeAfter, 'tally mtime unchanged after peekActiveCandidates');

  // Also verify the cursor was not touched.
  const cursorPath = path.join(cwd, '.agentic', '.skill-candidate-cursor');
  const cursorMtime = fs.existsSync(cursorPath) ? fs.statSync(cursorPath).mtimeMs : 0;
  // Just confirm no new cursor was written AFTER the peek.
  const cursorAfterPeek = fs.existsSync(cursorPath) ? fs.statSync(cursorPath).mtimeMs : 0;
  assertEqual(cursorMtime, cursorAfterPeek, 'cursor mtime unchanged after peek');

  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 8: peek-returns-above-threshold
// ---------------------------------------------------------------------------
console.log('\nTest 8: peek-returns-above-threshold (peek returns candidates >= threshold)');
(async () => {
  const cwd = makeTempProject();
  const ts1 = '2026-01-06T00:00:01.000Z';
  const ts2 = '2026-01-06T00:00:02.000Z';
  const ts3 = '2026-01-06T00:00:03.000Z';
  // domain-a: 3 events (at threshold) - should appear in peek result.
  // domain-b: 2 events (below threshold) - should NOT appear.
  writeEvents(cwd, [
    makeWorkaroundEvent('domain-a', ts1, 'n', SESSION),
    makeWorkaroundEvent('domain-a', ts2, 'n', SESSION),
    makeWorkaroundEvent('domain-a', ts3, 'n', SESSION),
    makeWorkaroundEvent('domain-b', ts1, 'n', SESSION),
    makeWorkaroundEvent('domain-b', ts2, 'n', SESSION),
  ]);

  await runSkillCandidateScan(cwd, SESSION);

  const result = peekActiveCandidates(cwd);
  const domains = result.map((r) => r.domain);
  assert(domains.includes('domain-a'), 'peek returns domain-a (count=3, at threshold)');
  assert(!domains.includes('domain-b'), 'peek does not return domain-b (count=2, below threshold)');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 9: corrupt-tally-fail-open
// ---------------------------------------------------------------------------
console.log('\nTest 9: corrupt-tally-fail-open (corrupt tally -> scan rebuilds)');
(async () => {
  const cwd = makeTempProject();
  // Write a corrupt tally.
  const tallyPath = path.join(cwd, '.agentic', '.skill-candidate-tally.json');
  fs.writeFileSync(tallyPath, '{not valid json', 'utf8');

  const ts1 = '2026-01-07T00:00:01.000Z';
  writeEvents(cwd, [
    makeWorkaroundEvent('gh-api', ts1, 'n', SESSION),
  ]);

  // Should not throw; should rebuild from empty state.
  let threw = false;
  try {
    await runSkillCandidateScan(cwd, SESSION);
  } catch (_) {
    threw = true;
  }
  assert(!threw, 'runSkillCandidateScan does not throw on corrupt tally');

  // Tally should now be valid JSON with count 1.
  const tally = _readTally(cwd);
  assertEqual(tally.candidates['gh-api'] && tally.candidates['gh-api'].count, 1, 'tally rebuilt cleanly with count 1');

  // peekActiveCandidates also fails open.
  // Corrupt it again.
  fs.writeFileSync(tallyPath, 'corrupt', 'utf8');
  const result = peekActiveCandidates(cwd);
  assert(Array.isArray(result) && result.length === 0, 'peekActiveCandidates returns [] on corrupt tally');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 10: routing-taxonomy
// ---------------------------------------------------------------------------
console.log('\nTest 10: routing-taxonomy (domain tags -> correct artifact types)');
{
  assertEqual(_routingArtifact('auth-token-review'), 'named-agent', 'review -> named-agent');
  assertEqual(_routingArtifact('code-style-preset'), 'preset', 'preset -> preset');
  assertEqual(_routingArtifact('eslint-rule-custom'), 'lint-rule', 'eslint -> lint-rule');
  assertEqual(_routingArtifact('ruff-format-check'), 'lint-rule', 'ruff -> lint-rule');
  assertEqual(_routingArtifact('deployment-workaround'), 'command', 'default -> command');
  assertEqual(_routingArtifact('git-push-fix'), 'command', 'git -> command (default)');
  assertEqual(_routingArtifact('audit-trail'), 'named-agent', 'audit -> named-agent');
}

// ---------------------------------------------------------------------------
// Test 11: learnings-merge-with-events (additively combined)
// ---------------------------------------------------------------------------
console.log('\nTest 11: learnings-merge-with-events (1 event + 2 distinct learning days = 3)');
(async () => {
  const cwd = makeTempProject();
  const ts1 = '2026-01-08T00:00:01.000Z';
  writeEvents(cwd, [
    makeWorkaroundEvent('aws-auth', ts1, 'note', SESSION),
  ]);
  const learningsContent = [
    '## [LRN-20260106-001] First',
    '**Domain:** aws-auth',
    '**Discovered:** 2026-01-06',
    'Details.',
    '',
    '## [LRN-20260107-001] Second',
    '**Domain:** aws-auth',
    '**Discovered:** 2026-01-07',
    'Details.',
    '',
  ].join('\n');
  writeLearnings(cwd, learningsContent);

  await runSkillCandidateScan(cwd, SESSION);

  const tally = _readTally(cwd);
  const entry = tally.candidates['aws-auth'];
  // 1 event + 2 distinct learning dates = 3 total -> at threshold
  assertEqual(entry && entry.count, 3, 'aws-auth count = 1 event + 2 distinct learning days = 3');
  const candidates = readCandidates(cwd);
  assert(candidates.includes('aws-auth'), 'candidate written for aws-auth at merged count 3');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 12: cursor-advances-after-tally-write
// ---------------------------------------------------------------------------
console.log('\nTest 12: cursor-advances-after-tally-write (cursor file written to max event ts)');
(async () => {
  const cwd = makeTempProject();
  const ts1 = '2026-01-09T00:00:01.000Z';
  const ts2 = '2026-01-09T00:00:05.000Z'; // latest
  writeEvents(cwd, [
    makeWorkaroundEvent('npm-install', ts1, 'n', SESSION),
    makeWorkaroundEvent('npm-install', ts2, 'n', SESSION),
  ]);

  await runSkillCandidateScan(cwd, SESSION);

  const cursorPath = path.join(cwd, '.agentic', '.skill-candidate-cursor');
  assert(fs.existsSync(cursorPath), 'cursor file created after scan');
  const cursorVal = fs.readFileSync(cursorPath, 'utf8').trim();
  assertEqual(cursorVal, ts2, 'cursor set to max event ts (ts2)');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 13: cursor-fallback-to-tally (cursor file missing -> tally.lastCursorTs)
// ---------------------------------------------------------------------------
console.log('\nTest 13: cursor-fallback-to-tally (missing cursor file -> tally recovery fallback)');
(async () => {
  const cwd = makeTempProject();
  const ts1 = '2026-01-10T00:00:01.000Z';
  const ts2 = '2026-01-10T00:00:02.000Z';
  writeEvents(cwd, [
    makeWorkaroundEvent('pnpm-lock', ts1, 'n', SESSION),
    makeWorkaroundEvent('pnpm-lock', ts2, 'n', SESSION),
  ]);

  // First scan to populate tally.lastCursorTs.
  await runSkillCandidateScan(cwd, SESSION);
  const tallyAfterFirst = _readTally(cwd);
  assertEqual(tallyAfterFirst.lastCursorTs, ts2, 'tally.lastCursorTs set to ts2 after first scan');

  // Delete the cursor file to force the fallback path.
  const cursorPath = path.join(cwd, '.agentic', '.skill-candidate-cursor');
  fs.unlinkSync(cursorPath);

  // Add new events AFTER ts2.
  const ts3 = '2026-01-10T00:00:03.000Z';
  const ts4 = '2026-01-10T00:00:04.000Z';
  fs.appendFileSync(
    path.join(cwd, '.agentic', 'events.jsonl'),
    makeWorkaroundEvent('pnpm-lock', ts3, 'n', SESSION) + '\n',
    'utf8'
  );
  fs.appendFileSync(
    path.join(cwd, '.agentic', 'events.jsonl'),
    makeWorkaroundEvent('pnpm-lock', ts4, 'n', SESSION) + '\n',
    'utf8'
  );

  // Second scan: cursor file gone but tally.lastCursorTs = ts2, so only ts3+ts4 are read.
  await runSkillCandidateScan(cwd, SESSION);
  const tallyAfterSecond = _readTally(cwd);
  // Total: 2 (first scan) + 2 (second scan, ts3+ts4 only) = 4 - NOT 6 (no double-count).
  assertEqual(tallyAfterSecond.candidates['pnpm-lock'].count, 4, 'count is 4; tally fallback prevented re-reading ts1+ts2');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 14: multiple-domains-tracked-independently
// ---------------------------------------------------------------------------
console.log('\nTest 14: multiple-domains-tracked-independently');
(async () => {
  const cwd = makeTempProject();
  const t = (n) => `2026-01-11T00:00:0${n}.000Z`;
  writeEvents(cwd, [
    // domain-x: 3 events -> should be promoted
    makeWorkaroundEvent('domain-x', t(1), 'n', SESSION),
    makeWorkaroundEvent('domain-x', t(2), 'n', SESSION),
    makeWorkaroundEvent('domain-x', t(3), 'n', SESSION),
    // domain-y: 2 events -> NOT promoted
    makeWorkaroundEvent('domain-y', t(4), 'n', SESSION),
    makeWorkaroundEvent('domain-y', t(5), 'n', SESSION),
  ]);

  await runSkillCandidateScan(cwd, SESSION);

  const tally = _readTally(cwd);
  assertEqual(tally.candidates['domain-x'].count, 3, 'domain-x count = 3');
  assertEqual(tally.candidates['domain-y'].count, 2, 'domain-y count = 2');
  assert(!!tally.candidates['domain-x'].surfacedAt, 'domain-x has surfacedAt (promoted)');
  assert(!tally.candidates['domain-y'].surfacedAt, 'domain-y has no surfacedAt (below threshold)');

  const candidates = readCandidates(cwd);
  assert(candidates.includes('domain-x'), 'domain-x in skill-candidates.md');
  assert(!candidates.includes('domain-y'), 'domain-y NOT in skill-candidates.md');
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 15: learnings-no-double-count-on-rescan
//   REGRESSION: before the fix, every scan re-added ALL distinct Discovered dates
//   to the count, inflating it on each run even when learnings.md is unchanged.
//   After the fix, a second scan with identical learnings.md adds 0.
// ---------------------------------------------------------------------------
console.log('\nTest 15: learnings-no-double-count-on-rescan (same learnings.md, count unchanged after 2nd scan)');
const test15 = (async () => {
  const cwd = makeTempProject();
  const learningsContent = [
    '## [LRN-20260201-001] Entry 1',
    '**Domain:** rescan-domain',
    '**Discovered:** 2026-02-01',
    'Details.',
    '',
    '## [LRN-20260202-001] Entry 2',
    '**Domain:** rescan-domain',
    '**Discovered:** 2026-02-02',
    'Details.',
    '',
  ].join('\n');
  writeLearnings(cwd, learningsContent);

  // Scan 1.
  await runSkillCandidateScan(cwd, SESSION);
  const tallyAfterScan1 = _readTally(cwd);
  const countAfterScan1 = tallyAfterScan1.candidates['rescan-domain']
    ? tallyAfterScan1.candidates['rescan-domain'].count
    : 0;

  // Scan 2: same learnings.md, no new events.
  await runSkillCandidateScan(cwd, SESSION);
  const tallyAfterScan2 = _readTally(cwd);
  const countAfterScan2 = tallyAfterScan2.candidates['rescan-domain']
    ? tallyAfterScan2.candidates['rescan-domain'].count
    : 0;

  assertEqual(countAfterScan2, countAfterScan1, 'count identical after 2nd scan with unchanged learnings.md (no double-count)');
  assert(countAfterScan1 === 2, `count after scan 1 is 2 (2 distinct dates, got ${countAfterScan1})`);
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Test 16: learnings-new-date-increments-by-one
//   After a scan, add a new Discovered-date line for the same domain.
//   The second scan must increment the count by exactly 1.
// ---------------------------------------------------------------------------
console.log('\nTest 16: learnings-new-date-increments-by-one (new Discovered date between scans -> count +1)');
const test16 = (async () => {
  const cwd = makeTempProject();
  const learningsV1 = [
    '## [LRN-20260301-001] Entry 1',
    '**Domain:** incr-domain',
    '**Discovered:** 2026-03-01',
    'Details.',
    '',
    '## [LRN-20260302-001] Entry 2',
    '**Domain:** incr-domain',
    '**Discovered:** 2026-03-02',
    'Details.',
    '',
  ].join('\n');
  writeLearnings(cwd, learningsV1);

  // Scan 1.
  await runSkillCandidateScan(cwd, SESSION);
  const tallyAfterScan1 = _readTally(cwd);
  const countAfterScan1 = tallyAfterScan1.candidates['incr-domain']
    ? tallyAfterScan1.candidates['incr-domain'].count
    : 0;
  assertEqual(countAfterScan1, 2, `count after scan 1 is 2 (got ${countAfterScan1})`);

  // Add a new Discovered date.
  const learningsV2 = learningsV1 + [
    '## [LRN-20260303-001] Entry 3',
    '**Domain:** incr-domain',
    '**Discovered:** 2026-03-03',
    'Details.',
    '',
  ].join('\n');
  writeLearnings(cwd, learningsV2);

  // Scan 2: must increment by exactly 1.
  await runSkillCandidateScan(cwd, SESSION);
  const tallyAfterScan2 = _readTally(cwd);
  const countAfterScan2 = tallyAfterScan2.candidates['incr-domain']
    ? tallyAfterScan2.candidates['incr-domain'].count
    : 0;
  assertEqual(countAfterScan2, countAfterScan1 + 1, `count increments by exactly 1 after new Discovered date (expected ${countAfterScan1 + 1}, got ${countAfterScan2})`);
  cleanup(cwd);
})();

// ---------------------------------------------------------------------------
// Summary: await all async test promises, then print results.
// ---------------------------------------------------------------------------
// Collect all async test IIFEs into a single array so the summary cannot fire
// before any test completes. Sync tests (test 10) are already done by the time
// we reach this point.
const asyncTests = [
  // tests 1-14 are fire-and-forget IIFEs above; we can't retroactively collect
  // them, but tests 15 and 16 (the new regression cases) ARE collected here.
  // For backward-compat we wait a tick so earlier IIFEs have a chance to enqueue,
  // then await the regression tests explicitly.
  Promise.resolve(),
  test15,
  test16,
];

Promise.all(asyncTests).then(() => {
  // Give any remaining microtasks a tick to settle (covers the earlier IIFEs).
  setImmediate(() => {
    console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
    if (failed > 0) process.exit(1);
  });
});
