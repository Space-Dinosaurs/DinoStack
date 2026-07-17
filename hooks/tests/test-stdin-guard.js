#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/stdin-guard.js readStdinGuarded().
 *
 * readStdinGuarded operates directly on process.stdin, so each timing-
 * sensitive case drives the REAL module as a subprocess via a small fixture
 * script (written once to a tmp dir, reused across cases) fed through a real
 * OS pipe with hooks/tests/lib/spawn-stdin-helpers.js. The one case that
 * needs a genuine stream 'error' event (case 6) runs in-process instead,
 * because a plain OS pipe has no reliable, portable way to deliver a read
 * error (closing the write end always looks like EOF to the reader, not an
 * error) - a fake EventEmitter swapped in for process.stdin is the
 * deterministic way to exercise that branch.
 *
 * Test cases:
 *   1a. never-writes-never-closes, small overridden timeouts -> resolves ''
 *       promptly (fast test).
 *   1b. never-writes-never-closes, production defaults -> resolves '' in
 *       under 1000ms.
 *   2.  fast normal close resolves with full content immediately (EOF path).
 *   3.  complete valid JSON payload delivered, stdin held open after (no
 *       EOF) -> resolves promptly via early-parse, well under the
 *       inactivity window.
 *   4.  slow-chunked valid payload, gaps under the inactivity window, total
 *       delivery >2s -> resolves with the full untruncated content.
 *   5.  malformed (never-parseable) payload + stdin held open -> resolves
 *       via the inactivity backstop (bounded), content is what arrived.
 *   6.  stream error event -> resolves gracefully with accumulated content.
 *   7.  tryParse: null disables early-completion - same input as case 3
 *       resolves only via the inactivity backstop, not early.
 *   8.  REGRESSION (Skeptic Major finding): a process that calls
 *       readStdinGuarded and never calls process.exit() itself must still
 *       exit on its own once resolved, even when the writer holds the pipe
 *       open indefinitely. pause() alone does not release the underlying
 *       pipe handle from the event loop in that scenario - only unref()
 *       does. This case hangs on the pre-fix code and passes on the fix.
 *   9.  multi-byte UTF-8 codepoint split mid-sequence across two raw-Buffer
 *       chunks -> the resolved string is intact (locks the
 *       setEncoding('utf8') / StringDecoder claim in the manifest).
 *   10. REGRESSION (Major 1 - absolute deadline): continuous non-JSON
 *       chunks, each gap smaller than inactivityTimeoutMs, with total
 *       duration exceeding an overridden small absoluteTimeoutMs -> resolves
 *       via the absolute deadline, not the inactivity window or EOF. Hangs
 *       past the deadline on pre-fix code (no absolute-timeout concept
 *       existed), which this case's elapsed-time bound catches.
 *   11. REGRESSION (Major 1 - byte cap): a payload larger than an
 *       overridden small maxStdinBytes -> resolves early with whatever has
 *       accumulated once the cap is crossed, not at EOF. Resolves much later
 *       (via EOF) on pre-fix code (no byte-cap concept existed), which this
 *       case's elapsed-time bound catches.
 *
 * Run with: node hooks/tests/test-stdin-guard.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const EventEmitter = require('events');

const { readStdinGuarded } = require('../lib/stdin-guard.js');
const { spawnSilentStdin, spawnDelayedChunks } = require('./lib/spawn-stdin-helpers.js');

// ---------------------------------------------------------------------------
// Harness
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

// ---------------------------------------------------------------------------
// Fixture: a tiny standalone runner that calls readStdinGuarded() against
// its own real process.stdin and prints the result as JSON on stdout.
// argv[2] is a JSON-encoded options object; "tryParse": "none" is translated
// to the literal `null` (disables early-completion) since a function cannot
// cross a command-line boundary.
// ---------------------------------------------------------------------------

const libPathAbs = path.resolve(__dirname, '..', 'lib', 'stdin-guard.js');
const fixtureSource = `
'use strict';
const { readStdinGuarded } = require(${JSON.stringify(libPathAbs)});
let opts = {};
try { opts = JSON.parse(process.argv[2] || '{}'); } catch (_) { opts = {}; }
if (opts.tryParse === 'none') { opts.tryParse = null; }
const start = Date.now();
readStdinGuarded(opts).then((result) => {
  const elapsedMs = Date.now() - start;
  process.stdout.write(JSON.stringify({ elapsedMs, length: result.length, content: result }));
  process.exit(0);
});
`;
const fixturePath = path.join(os.tmpdir(), `stdin-guard-fixture-${process.pid}-${Date.now()}.js`);
fs.writeFileSync(fixturePath, fixtureSource, 'utf8');

function fixtureArgs(opts) {
  return [fixturePath, JSON.stringify(opts || {})];
}

function parseFixtureStdout(stdout) {
  try {
    return JSON.parse(stdout);
  } catch (_) {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Second fixture (case 8 / Major regression): identical to the fixture
// above EXCEPT it deliberately never calls process.exit(). The whole point
// is to prove the process can terminate on its own once readStdinGuarded
// resolves and cleans up - even when the writer never closes the pipe -
// which only holds true once cleanup() actually releases the underlying
// stdin handle from the event loop (stdin.unref(), not just pause()).
// ---------------------------------------------------------------------------

const fixtureNoExitSource = `
'use strict';
const { readStdinGuarded } = require(${JSON.stringify(libPathAbs)});
let opts = {};
try { opts = JSON.parse(process.argv[2] || '{}'); } catch (_) { opts = {}; }
if (opts.tryParse === 'none') { opts.tryParse = null; }
const start = Date.now();
readStdinGuarded(opts).then((result) => {
  const elapsedMs = Date.now() - start;
  process.stdout.write(JSON.stringify({ elapsedMs, length: result.length, content: result }));
  // No process.exit() call here - see file header for why.
});
`;
const fixtureNoExitPath = path.join(os.tmpdir(), `stdin-guard-fixture-noexit-${process.pid}-${Date.now()}.js`);
fs.writeFileSync(fixtureNoExitPath, fixtureNoExitSource, 'utf8');

function fixtureNoExitArgs(opts) {
  return [fixtureNoExitPath, JSON.stringify(opts || {})];
}

// ---------------------------------------------------------------------------
// Cases 1a / 1b: never-writes-never-closes
// ---------------------------------------------------------------------------

async function testNeverWritesSmallTimeouts() {
  const result = await spawnSilentStdin({
    cmd: process.execPath,
    args: fixtureArgs({ firstByteTimeoutMs: 100, inactivityTimeoutMs: 200 }),
    maxWaitMs: 3000,
  });
  assert(!result.timedOut, 'case 1a: child exits on its own (not force-killed)');
  assert(result.code === 0, 'case 1a: child exits 0');
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 1a: fixture printed valid JSON result');
  if (parsed) {
    assert(parsed.content === '', 'case 1a: resolves with empty string (no bytes ever arrived)');
    assert(parsed.elapsedMs < 1000, `case 1a: resolves promptly with overridden timeouts (${parsed.elapsedMs}ms)`);
  }
}

async function testNeverWritesProductionDefaults() {
  const result = await spawnSilentStdin({
    cmd: process.execPath,
    args: fixtureArgs({}), // production defaults: 750ms / 5000ms
    maxWaitMs: 3000,
  });
  assert(!result.timedOut, 'case 1b: child exits on its own (not force-killed)');
  assert(result.code === 0, 'case 1b: child exits 0');
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 1b: fixture printed valid JSON result');
  if (parsed) {
    assert(parsed.content === '', 'case 1b: resolves with empty string at production defaults');
    assert(
      parsed.elapsedMs < 1000,
      `case 1b: PRODUCTION-DEFAULTS resolution time = ${parsed.elapsedMs}ms (must be < 1000ms)`
    );
  }
  console.log(`  [timing] production-defaults never-writes-never-closes: elapsedMs=${
    parsed && parsed.elapsedMs
  } processElapsedMs=${result.elapsedMs}`);
}

// ---------------------------------------------------------------------------
// Case 2: fast normal close resolves with full content immediately
// ---------------------------------------------------------------------------

async function testFastNormalClose() {
  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: fixtureArgs({}),
    chunks: ['hello world'],
    gapMs: 0,
    holdOpenMs: 0, // end() immediately after writing - triggers the EOF path
  });
  assert(result.code === 0, 'case 2: child exits 0');
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 2: fixture printed valid JSON result');
  if (parsed) {
    assert(parsed.content === 'hello world', 'case 2: resolves with the full written content');
    assert(parsed.elapsedMs < 500, `case 2: resolves near-instantly on EOF (${parsed.elapsedMs}ms)`);
  }
}

// ---------------------------------------------------------------------------
// Case 3: complete valid JSON, stdin held open after -> early-parse
// ---------------------------------------------------------------------------

async function testEarlyParseWithStdinHeldOpen() {
  const payload = JSON.stringify({ foo: 'bar', n: 42 });
  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: fixtureArgs({}), // default inactivityTimeoutMs 5000 - proves early-parse, not luck
    chunks: [payload],
    gapMs: 0,
    holdOpenMs: 300, // pipe stays open well past resolution; never reaches EOF or inactivity
  });
  assert(result.code === 0, 'case 3: child exits 0');
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 3: fixture printed valid JSON result');
  if (parsed) {
    assert(parsed.content === payload, 'case 3: resolves with the full valid-JSON payload');
    assert(
      parsed.elapsedMs < 250,
      `case 3: resolves via early-parse well under the 5000ms inactivity window (${parsed.elapsedMs}ms)`
    );
  }
}

// ---------------------------------------------------------------------------
// Case 4: slow-chunked valid payload, gaps under inactivity window,
// total delivery >2s -> full untruncated content
// ---------------------------------------------------------------------------

async function testSlowChunkedNoTruncation() {
  const fullPayload = JSON.stringify({
    session: 'abc-123',
    note: 'x'.repeat(200),
    tail: 'end-marker',
  });
  // Split mid-string so no prefix is independently valid JSON - this
  // exercises the inactivity re-arm across chunks, not a lucky early parse
  // on an intermediate chunk.
  const third = Math.floor(fullPayload.length / 3);
  const chunks = [
    fullPayload.slice(0, third),
    fullPayload.slice(third, third * 2),
    fullPayload.slice(third * 2),
  ];

  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: fixtureArgs({}), // default inactivityTimeoutMs 5000, gaps well under it
    chunks,
    gapMs: 1100,
    holdOpenMs: 200,
  });
  assert(result.code === 0, 'case 4: child exits 0');
  assert(
    result.elapsedMs > 2000,
    `case 4: total delivery exceeded 2s as required (${result.elapsedMs}ms)`
  );
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 4: fixture printed valid JSON result');
  if (parsed) {
    assert(
      parsed.content === fullPayload,
      'case 4: full payload delivered with no truncation across slow chunks'
    );
    assert(
      JSON.stringify(JSON.parse(parsed.content)) === JSON.stringify(JSON.parse(fullPayload)),
      'case 4: reassembled content round-trips through JSON.parse identically'
    );
  }
}

// ---------------------------------------------------------------------------
// Case 5: malformed payload, stdin held open -> inactivity backstop
// ---------------------------------------------------------------------------

async function testMalformedPayloadInactivityBackstop() {
  const malformed = 'this is not json {{{';
  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: fixtureArgs({ inactivityTimeoutMs: 300 }),
    chunks: [malformed],
    gapMs: 0,
    holdOpenMs: 1500, // held open well past the 300ms inactivity window
  });
  assert(result.code === 0, 'case 5: child exits 0');
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 5: fixture printed valid JSON result');
  if (parsed) {
    assert(parsed.content === malformed, 'case 5: resolves with the malformed content that arrived');
    assert(
      parsed.elapsedMs >= 250 && parsed.elapsedMs < 1200,
      `case 5: resolves via the bounded inactivity backstop, not instantly (${parsed.elapsedMs}ms)`
    );
  }
}

// ---------------------------------------------------------------------------
// Case 6: stream 'error' event -> resolves gracefully with accumulated
// content. Run in-process with a fake stdin (see file header for rationale).
// ---------------------------------------------------------------------------

async function testStreamErrorResolvesGracefully() {
  const originalDescriptor = Object.getOwnPropertyDescriptor(process, 'stdin');
  const fake = new EventEmitter();
  fake.setEncoding = () => {};
  fake.pause = () => {};
  fake.resume = () => {};

  Object.defineProperty(process, 'stdin', { value: fake, configurable: true });
  try {
    const promise = readStdinGuarded({ firstByteTimeoutMs: 5000, inactivityTimeoutMs: 5000 });
    fake.emit('data', 'partial-before-error');
    fake.emit('error', new Error('simulated stream error'));
    const result = await promise;
    assert(result === 'partial-before-error', 'case 6: resolves with content accumulated before the error');
  } finally {
    Object.defineProperty(process, 'stdin', originalDescriptor);
  }
}

// ---------------------------------------------------------------------------
// Case 7: tryParse: null disables early-completion
// ---------------------------------------------------------------------------

async function testTryParseNullDisablesEarlyCompletion() {
  const payload = JSON.stringify({ foo: 'bar', n: 42 });
  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: fixtureArgs({ tryParse: 'none', inactivityTimeoutMs: 300 }),
    chunks: [payload],
    gapMs: 0,
    holdOpenMs: 1000, // held open well past the 300ms inactivity window
  });
  assert(result.code === 0, 'case 7: child exits 0');
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 7: fixture printed valid JSON result');
  if (parsed) {
    assert(parsed.content === payload, 'case 7: full valid-JSON payload still delivered (via backstop, not early-parse)');
    assert(
      parsed.elapsedMs >= 250,
      `case 7: tryParse:null disables the early-parse shortcut - resolution waited for the ` +
      `inactivity backstop instead of firing near-instantly like case 3 (${parsed.elapsedMs}ms)`
    );
  }
}

// ---------------------------------------------------------------------------
// Case 8 (Skeptic Major regression): process exits naturally without ever
// calling process.exit() itself, even when the writer holds the pipe open
// well past resolution. Uses the no-exit fixture and a bounded maxWaitMs so
// a regression fails the suite fast instead of hanging it forever.
// ---------------------------------------------------------------------------

async function testNaturalExitWithoutProcessExitCall() {
  const payload = JSON.stringify({ ok: true, marker: 'natural-exit-regression' });
  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: fixtureNoExitArgs({}),
    chunks: [payload],
    gapMs: 0,
    holdOpenMs: 3000, // writer holds the pipe open well past when resolution+cleanup happens
    maxWaitMs: 6000,  // safety net: fail fast, not hang forever, if the fix regresses
  });
  assert(!result.timedOut, 'case 8 (Major regression): process exits naturally, is not force-killed by the test harness');
  assert(result.code === 0, 'case 8 (Major regression): process exits 0');
  assert(
    result.elapsedMs < 2000,
    `case 8 (Major regression): process exited naturally well before the writer closed the pipe ` +
    `at 3000ms (${result.elapsedMs}ms) - proves stdin.unref() actually releases the event loop, not just pause()`
  );
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 8 (Major regression): fixture printed valid JSON result before exiting');
  if (parsed) {
    assert(parsed.content === payload, 'case 8 (Major regression): full payload delivered before natural exit');
  }
}

// ---------------------------------------------------------------------------
// Case 9 (Minor-1): a multi-byte UTF-8 codepoint split mid-sequence across
// two raw-Buffer chunks reassembles intact.
// ---------------------------------------------------------------------------

async function testMultiByteCodepointSplitAcrossChunks() {
  const prefixBuf = Buffer.from('abc-', 'utf8');
  const emojiBuf = Buffer.from('\u{1F600}', 'utf8'); // 4-byte UTF-8 sequence
  const suffixBuf = Buffer.from('-xyz', 'utf8');
  const fullBuf = Buffer.concat([prefixBuf, emojiBuf, suffixBuf]);
  const expectedText = fullBuf.toString('utf8');

  // Split 2 bytes into the emoji's 4-byte sequence - deliberately mid-codepoint.
  const splitPoint = prefixBuf.length + 2;
  const chunk1 = fullBuf.subarray(0, splitPoint);
  const chunk2 = fullBuf.subarray(splitPoint);

  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: fixtureArgs({ tryParse: 'none' }), // plain text, not JSON - isolate the codepoint concern
    chunks: [chunk1, chunk2],
    gapMs: 50, // force two distinct 'data' events, not one coalesced read
    holdOpenMs: 0, // end() right after writing - resolves via EOF
  });
  assert(result.code === 0, 'case 9 (Minor-1): child exits 0');
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 9 (Minor-1): fixture printed valid JSON result');
  if (parsed) {
    assert(
      parsed.content === expectedText,
      `case 9 (Minor-1): multi-byte UTF-8 codepoint split across two chunks reassembles intact ` +
      `(got ${JSON.stringify(parsed.content)})`
    );
  }
}

// ---------------------------------------------------------------------------
// Case 10 (Major-1 regression): absolute deadline backstop. A writer that
// keeps sending non-JSON chunks faster than inactivityTimeoutMs would keep
// the pre-fix reader alive forever (or until EOF/pipe-close). With an
// overridden small absoluteTimeoutMs, resolution must happen at the
// deadline, independent of chunk activity and well before the pipe is
// eventually closed.
// ---------------------------------------------------------------------------

async function testAbsoluteDeadlineBackstop() {
  const chunks = ['not-json-', 'still-not-json-', 'never-parses-'];
  const fullContent = chunks.join('');
  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: fixtureArgs({ absoluteTimeoutMs: 300, inactivityTimeoutMs: 5000 }),
    chunks,
    gapMs: 100, // each gap well under the 5000ms inactivity window
    holdOpenMs: 3000, // pipe held open well past the 300ms absolute deadline
  });
  assert(result.code === 0, 'case 10 (Major-1 regression): child exits 0');
  assert(
    result.elapsedMs < 1500,
    `case 10 (Major-1 regression): resolves via the absolute deadline, not the 5000ms ` +
    `inactivity window or the 3000ms hold-open/EOF (${result.elapsedMs}ms)`
  );
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 10 (Major-1 regression): fixture printed valid JSON result');
  if (parsed) {
    assert(
      parsed.elapsedMs >= 250 && parsed.elapsedMs < 1200,
      `case 10 (Major-1 regression): resolved via the absolute-deadline window (~300ms), not ` +
      `instantly and not after the full 3000ms hold-open (${parsed.elapsedMs}ms)`
    );
    assert(
      parsed.content === fullContent,
      'case 10 (Major-1 regression): resolves with all chunks accumulated before the deadline fired'
    );
  }
}

// ---------------------------------------------------------------------------
// Case 11 (Major-1 regression): byte-cap backstop. A payload larger than an
// overridden small maxStdinBytes must resolve early with whatever has
// accumulated, rather than growing unboundedly until EOF/pipe-close.
// ---------------------------------------------------------------------------

async function testMaxStdinBytesBackstop() {
  const chunk1 = 'a'.repeat(80);
  const chunk2 = 'b'.repeat(80); // total 160 bytes > overridden 100-byte cap
  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: fixtureArgs({ maxStdinBytes: 100 }),
    chunks: [chunk1, chunk2],
    gapMs: 50,
    holdOpenMs: 2000, // pipe held open well past when the byte cap should fire
  });
  assert(result.code === 0, 'case 11 (Major-1 regression): child exits 0');
  assert(
    result.elapsedMs < 1500,
    `case 11 (Major-1 regression): resolves via the byte cap, not the 2000ms hold-open/EOF or ` +
    `the 750/5000ms default timers (${result.elapsedMs}ms)`
  );
  const parsed = parseFixtureStdout(result.stdout);
  assert(!!parsed, 'case 11 (Major-1 regression): fixture printed valid JSON result');
  if (parsed) {
    assert(
      parsed.content === chunk1 + chunk2,
      'case 11 (Major-1 regression): resolves with all bytes accumulated up to and including ' +
      'the chunk that crossed the cap (no truncation mid-chunk)'
    );
    assert(
      parsed.length > 100,
      `case 11 (Major-1 regression): accumulated length (${parsed.length}) exceeds the ` +
      `overridden 100-byte cap, proving the cap is a backstop, not a hard truncation`
    );
  }
}

// ---------------------------------------------------------------------------
// Sanity: module loads clean with no side effects at require time
// ---------------------------------------------------------------------------

function testModuleExports() {
  const mod = require('../lib/stdin-guard.js');
  assert(typeof mod.readStdinGuarded === 'function', 'sanity: readStdinGuarded is exported as a function');
  assert(mod.DEFAULT_FIRST_BYTE_TIMEOUT_MS === 750, 'sanity: DEFAULT_FIRST_BYTE_TIMEOUT_MS is 750');
  assert(mod.DEFAULT_INACTIVITY_TIMEOUT_MS === 5000, 'sanity: DEFAULT_INACTIVITY_TIMEOUT_MS is 5000');
  assert(mod.DEFAULT_ABSOLUTE_TIMEOUT_MS === 10000, 'sanity: DEFAULT_ABSOLUTE_TIMEOUT_MS is 10000');
  assert(mod.DEFAULT_MAX_STDIN_BYTES === 10 * 1024 * 1024, 'sanity: DEFAULT_MAX_STDIN_BYTES is 10 MiB');
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

async function main() {
  try {
    testModuleExports();

    console.log('Case 1a: never-writes-never-closes, small overridden timeouts');
    await testNeverWritesSmallTimeouts();

    console.log('Case 1b: never-writes-never-closes, PRODUCTION DEFAULTS');
    await testNeverWritesProductionDefaults();

    console.log('Case 2: fast normal close resolves with full content immediately');
    await testFastNormalClose();

    console.log('Case 3: complete valid JSON, stdin held open -> early-parse');
    await testEarlyParseWithStdinHeldOpen();

    console.log('Case 4: slow-chunked valid payload (>2s), no truncation');
    await testSlowChunkedNoTruncation();

    console.log('Case 5: malformed payload, stdin held open -> inactivity backstop');
    await testMalformedPayloadInactivityBackstop();

    console.log('Case 6: stream error event resolves gracefully');
    await testStreamErrorResolvesGracefully();

    console.log('Case 7: tryParse: null disables early-completion');
    await testTryParseNullDisablesEarlyCompletion();

    console.log('Case 8: REGRESSION - process exits naturally without calling process.exit()');
    await testNaturalExitWithoutProcessExitCall();

    console.log('Case 9: multi-byte UTF-8 codepoint split across two chunks');
    await testMultiByteCodepointSplitAcrossChunks();

    console.log('Case 10: REGRESSION - absolute deadline backstop (Major 1)');
    await testAbsoluteDeadlineBackstop();

    console.log('Case 11: REGRESSION - byte-cap backstop (Major 1)');
    await testMaxStdinBytesBackstop();
  } finally {
    try { fs.unlinkSync(fixturePath); } catch (_) { /* ignore */ }
    try { fs.unlinkSync(fixtureNoExitPath); } catch (_) { /* ignore */ }
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
