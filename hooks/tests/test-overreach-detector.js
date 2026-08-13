#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/overreach-detector.js's computeOverreach /
 * parseTranscriptBlocks / computeOverreachFromBlocks.
 *
 * Test cases:
 *   1. shared-fixture-equivalence: loads hooks/tests/fixtures/
 *      overreach-shared-transcript.json (also exercised by
 *      bin/tests/test_ds_measure_conductor_tool_calls.py for cross-language
 *      equivalence) and runs EVERY case in its `cases` array through
 *      computeOverreach, asserting the result matches each case's
 *      `expected` block exactly. The fixture covers both the Critical-2
 *      regression (interleaved non-Agent tool_results before any spawn)
 *      and, as of Skeptic round-3 Minor 1/2, the failure paths (an empty
 *      transcript and a wholly malformed one) - pinning that both the JS
 *      detector and the Python calibrator report `available:false` on
 *      those two cases, not a real zero.
 *   2. window-binds-to-agent-result-only (isolated mutation-style check):
 *      directly constructs a block list where a non-Agent tool_result
 *      immediately precedes a Read call with no Agent spawn anywhere -
 *      asserts the Read is NOT whitelisted.
 *   3. missing-transcript-path: transcriptPath is null -> available:false,
 *      transcript_note starts with "unavailable".
 *   4. transcript-file-not-found: a path that does not exist on disk ->
 *      available:false, descriptive note.
 *   5. transcript-file-empty: a real empty file -> available:false
 *      (zero parsed records), descriptive note.
 *   6. transcript-file-malformed-only: a file containing only non-JSON
 *      garbage lines -> available:false, zero parsed records.
 *   7. transcript-file-too-large: a file exceeding a caller-supplied
 *      maxBytes -> available:false, "skipped (transcript too large)".
 *   8. mixed-valid-and-malformed-lines: a file with some malformed lines
 *      interleaved with valid ones -> parses only the valid lines, still
 *      available:true.
 *
 * Run with: node hooks/tests/test-overreach-detector.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const {
  computeOverreach,
  computeOverreachFromBlocks,
  parseTranscriptBlocks,
} = require('../lib/overreach-detector.js');

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

function writeTranscriptFile(lines) {
  const tmpFile = path.join(
    fs.mkdtempSync(path.join(os.tmpdir(), 'ae-overreach-detector-test-')),
    'transcript.jsonl'
  );
  const body = lines.map((l) => JSON.stringify(l)).join('\n') + '\n';
  fs.writeFileSync(tmpFile, body, 'utf8');
  return tmpFile;
}

/** Write a fixture case (either structured `lines` or literal `raw_lines`) to a real file. */
function writeFixtureCase(fixtureCase) {
  if (Array.isArray(fixtureCase.raw_lines)) {
    const tmpFile = path.join(
      fs.mkdtempSync(path.join(os.tmpdir(), 'ae-overreach-detector-test-')),
      'transcript.jsonl'
    );
    fs.writeFileSync(tmpFile, fixtureCase.raw_lines.join('\n') + '\n', 'utf8');
    return tmpFile;
  }
  return writeTranscriptFile(fixtureCase.lines || []);
}

// ---------------------------------------------------------------------------
// Test 1: shared-fixture-equivalence (all cases, incl. failure paths)
// ---------------------------------------------------------------------------
console.log('\nTest 1: shared-fixture-equivalence (all cases, incl. failure paths)');
{
  const fixturePath = path.resolve(__dirname, 'fixtures', 'overreach-shared-transcript.json');
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));

  for (const fixtureCase of fixture.cases) {
    const transcriptPath = writeFixtureCase(fixtureCase);
    const result = computeOverreach(transcriptPath, 1);
    const expected = fixtureCase.expected;
    const label = fixtureCase.name;

    assert(
      result.available === expected.available,
      `[${label}] available === ${expected.available} (got ${result.available})`
    );

    if (expected.available === false) {
      assert(
        result.conductor_tool_calls === 0
          && result.live_or_completed_spawns === 0
          && result.whitelisted_reads_excluded === 0,
        `[${label}] all counts are 0 (never fabricated) when unavailable`
      );
      assert(
        typeof result.transcript_note === 'string' && result.transcript_note.length > 0,
        `[${label}] transcript_note is populated when unavailable`
      );
      continue;
    }

    assert(
      result.conductor_tool_calls === expected.conductor_tool_calls,
      `[${label}] conductor_tool_calls === ${expected.conductor_tool_calls} `
        + `(got ${result.conductor_tool_calls})`
    );
    assert(
      result.live_or_completed_spawns === expected.live_or_completed_spawns,
      `[${label}] live_or_completed_spawns === ${expected.live_or_completed_spawns} `
        + `(got ${result.live_or_completed_spawns})`
    );
    assert(
      result.whitelisted_reads_excluded === expected.whitelisted_reads_excluded,
      `[${label}] whitelisted_reads_excluded === ${expected.whitelisted_reads_excluded} `
        + `(got ${result.whitelisted_reads_excluded})`
    );
  }
}

// ---------------------------------------------------------------------------
// Test 2: window-binds-to-agent-result-only
// ---------------------------------------------------------------------------
console.log('\nTest 2: window-binds-to-agent-result-only');
{
  // No Agent spawn anywhere. A Bash tool_result immediately precedes a
  // Read call. Under the pre-fix bug this would have opened a spot-check
  // window and whitelisted the Read call.
  const blocks = [
    { type: 'tool_use', id: 'b1', name: 'Bash', input: { command: 'ls /repo' } },
    { type: 'tool_result', tool_use_id: 'b1' },
    { type: 'tool_use', id: 'r1', name: 'Read', input: { file_path: '/repo/x.js' } },
  ];
  const result = computeOverreachFromBlocks(blocks, 0);
  assert(result.conductor_tool_calls === 2, `both calls counted (got ${result.conductor_tool_calls})`);
  assert(result.whitelisted_reads_excluded === 0, 'nothing whitelisted (no Agent spawn ever occurred)');
}

// ---------------------------------------------------------------------------
// Test 3: missing-transcript-path
// ---------------------------------------------------------------------------
console.log('\nTest 3: missing-transcript-path');
{
  const result = computeOverreach(null, 1);
  assert(result.available === false, 'available is false');
  assert(
    typeof result.transcript_note === 'string' && result.transcript_note.startsWith('unavailable'),
    `transcript_note starts with "unavailable" (got ${JSON.stringify(result.transcript_note)})`
  );
  assert(result.conductor_tool_calls === 0, 'conductor_tool_calls is 0 (not fabricated)');
  assert(result.ratio_trigger === false, 'ratio_trigger is false');
}

// ---------------------------------------------------------------------------
// Test 4: transcript-file-not-found
// ---------------------------------------------------------------------------
console.log('\nTest 4: transcript-file-not-found');
{
  const bogusPath = path.join(os.tmpdir(), `ae-overreach-does-not-exist-${Date.now()}.jsonl`);
  const result = computeOverreach(bogusPath, 1);
  assert(result.available === false, 'available is false');
  assert(
    result.transcript_note === 'unavailable (transcript not found)',
    `transcript_note is "unavailable (transcript not found)" (got ${JSON.stringify(result.transcript_note)})`
  );
}

// ---------------------------------------------------------------------------
// Test 5: transcript-file-empty
// ---------------------------------------------------------------------------
console.log('\nTest 5: transcript-file-empty');
{
  const emptyPath = writeTranscriptFile([]);
  // writeTranscriptFile always writes at least a trailing newline; force
  // genuinely empty content.
  fs.writeFileSync(emptyPath, '', 'utf8');
  const result = computeOverreach(emptyPath, 1);
  assert(result.available === false, 'available is false for an empty file');
  assert(
    result.transcript_note === 'unavailable (transcript unreadable)',
    `transcript_note reflects zero parsed records (got ${JSON.stringify(result.transcript_note)})`
  );
}

// ---------------------------------------------------------------------------
// Test 6: transcript-file-malformed-only
// ---------------------------------------------------------------------------
console.log('\nTest 6: transcript-file-malformed-only');
{
  const tmpFile = path.join(
    fs.mkdtempSync(path.join(os.tmpdir(), 'ae-overreach-detector-test-')),
    'transcript.jsonl'
  );
  fs.writeFileSync(tmpFile, 'not json\n{{{ also not json\nnope\n', 'utf8');
  const result = computeOverreach(tmpFile, 1);
  assert(result.available === false, 'available is false when nothing parses');
  assert(
    result.transcript_note === 'unavailable (transcript unreadable)',
    `transcript_note reflects zero parsed records (got ${JSON.stringify(result.transcript_note)})`
  );
}

// ---------------------------------------------------------------------------
// Test 7: transcript-file-too-large
// ---------------------------------------------------------------------------
console.log('\nTest 7: transcript-file-too-large');
{
  const fixturePath = path.resolve(__dirname, 'fixtures', 'overreach-shared-transcript.json');
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const fixtureCase = fixture.cases.find((c) => c.name === 'interleaved-non-agent-results');
  const transcriptPath = writeTranscriptFile(fixtureCase.lines);
  const tinyMaxBytes = 10; // smaller than the real file
  const result = computeOverreach(transcriptPath, 1, tinyMaxBytes);
  assert(result.available === false, 'available is false when the file exceeds maxBytes');
  assert(
    result.transcript_note === 'skipped (transcript too large)',
    `transcript_note is "skipped (transcript too large)" (got ${JSON.stringify(result.transcript_note)})`
  );
}

// ---------------------------------------------------------------------------
// Test 8: mixed-valid-and-malformed-lines
// ---------------------------------------------------------------------------
console.log('\nTest 8: mixed-valid-and-malformed-lines');
{
  const validLine = JSON.stringify({
    message: { role: 'assistant', content: [
      { type: 'tool_use', id: 'x1', name: 'Read', input: { file_path: '/repo/y.js' } },
    ] },
  });
  const tmpFile = path.join(
    fs.mkdtempSync(path.join(os.tmpdir(), 'ae-overreach-detector-test-')),
    'transcript.jsonl'
  );
  fs.writeFileSync(tmpFile, `garbage line\n${validLine}\nmore garbage\n`, 'utf8');
  const result = computeOverreach(tmpFile, 0);
  assert(result.available === true, 'available is true when at least one line parses');
  assert(result.conductor_tool_calls === 1, `the one valid Read call is counted (got ${result.conductor_tool_calls})`);
  assert(result.transcript_note === null, 'transcript_note is null on a successful parse');
}

// ---------------------------------------------------------------------------
// Test 9: parseTranscriptBlocks exposed directly
// ---------------------------------------------------------------------------
console.log('\nTest 9: parseTranscriptBlocks exposed directly');
{
  const result = parseTranscriptBlocks(null);
  assert(result.parsedCount === 0, 'parsedCount is 0 for a null path');
  assert(result.note === 'unavailable (transcript_path missing)', 'note reflects the missing path');
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
