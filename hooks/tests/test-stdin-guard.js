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
 *   12. DS-82 production importer inventory parses JavaScript with espree,
 *       detects only real static CommonJS/ESM imports and re-exports of the
 *       shared guard, and traverses in-repository symlinks without cycles or
 *       repository escapes. Generated Codex skill resource mirrors under the
 *       exact production-root prefix .codex/skills are excluded because they
 *       expose canonical files rather than independent production consumers;
 *       other in-repository symlinks and independently tracked mirrors remain
 *       part of the inventory.
 *
 * Run with: node hooks/tests/test-stdin-guard.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const EventEmitter = require('events');
const espree = require('espree');
const eslintScope = require('eslint-scope');

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
// Case 12 (DS-82): fail-closed production importer inventory. Parsing with
// espree distinguishes executable imports from comments, strings, regexes,
// and member calls while retaining expressions inside template interpolation.
// ---------------------------------------------------------------------------

const productionImporterExtensions = new Set(['.js', '.cjs', '.mjs']);
const productionImporterIgnoredDirectories = new Set([
  '.agentic',
  '.git',
  'node_modules',
  'test',
  'tests',
]);
const productionImporterIgnoredRootDirectories = new Set([
  '.codex/skills',
]);

function isWithinDirectory(rootDirectory, candidatePath) {
  const relativePath = path.relative(rootDirectory, candidatePath);
  return relativePath === ''
    || (!path.isAbsolute(relativePath)
      && relativePath !== '..'
      && !relativePath.startsWith(`..${path.sep}`));
}

function parseJavaScript(source, filename) {
  const extension = path.extname(filename);
  const sourceTypes = extension === '.mjs'
    ? ['module']
    : extension === '.cjs'
      ? ['script']
      : ['module', 'script'];
  const failures = [];
  for (const sourceType of sourceTypes) {
    try {
      return {
        ast: espree.parse(source, {
          ecmaVersion: 'latest',
          sourceType,
          range: true,
        }),
        sourceType,
      };
    } catch (error) {
      failures.push(`${sourceType}: ${error.message}`);
    }
  }
  throw new Error(`Cannot parse importer candidate ${filename}: ${failures.join('; ')}`);
}

function visitAst(node, visitor) {
  if (!node || typeof node !== 'object') return;
  if (typeof node.type === 'string') visitor(node);
  for (const [key, child] of Object.entries(node)) {
    if (key === 'loc' || key === 'range' || key === 'tokens' || key === 'comments') continue;
    if (Array.isArray(child)) {
      for (const item of child) visitAst(item, visitor);
    } else {
      visitAst(child, visitor);
    }
  }
}

function staticString(node) {
  return node?.type === 'Literal' && typeof node.value === 'string'
    ? node.value
    : null;
}

function importedSpecifiers(source, filename) {
  const { ast, sourceType } = parseJavaScript(source, filename);
  const scopeManager = eslintScope.analyze(ast, {
    ecmaVersion: 2022,
    sourceType,
    ignoreEval: true,
  });
  const unresolvedGlobalRequires = new Set();
  for (const scope of scopeManager.scopes) {
    for (const reference of scope.through) {
      if (reference.identifier.name === 'require') {
        unresolvedGlobalRequires.add(reference.identifier);
      }
    }
  }

  const specifiers = [];
  visitAst(ast, (node) => {
    if (
      node.type === 'ImportDeclaration'
      || node.type === 'ExportNamedDeclaration'
      || node.type === 'ExportAllDeclaration'
    ) {
      const specifier = staticString(node.source);
      if (specifier !== null) specifiers.push(specifier);
      return;
    }
    if (node.type === 'ImportExpression') {
      const specifier = staticString(node.source);
      if (specifier !== null) specifiers.push(specifier);
      return;
    }
    if (
      node.type === 'CallExpression'
      && node.callee?.type === 'Identifier'
      && node.callee.name === 'require'
      && unresolvedGlobalRequires.has(node.callee)
      && node.arguments.length === 1
    ) {
      const specifier = staticString(node.arguments[0]);
      if (specifier !== null) specifiers.push(specifier);
    }
  });
  return specifiers;
}

function sourceImportsStdinGuard(source, sourcePath, guardRealPath) {
  for (const specifier of importedSpecifiers(source, sourcePath)) {
    if (
      path.basename(specifier) !== 'stdin-guard.js'
      || (!specifier.startsWith('./') && !specifier.startsWith('../'))
    ) {
      continue;
    }
    const candidatePath = path.resolve(path.dirname(sourcePath), specifier);
    let candidateRealPath;
    try {
      candidateRealPath = fs.realpathSync(candidatePath);
    } catch (error) {
      throw new Error(
        `Importer ${sourcePath} references an unreadable stdin guard ${specifier}: ${error.message}`
      );
    }
    if (candidateRealPath === guardRealPath) return true;
  }
  return false;
}

function discoverProductionImporters(rootDirectory) {
  const rootRealPath = fs.realpathSync(rootDirectory);
  const guardRealPath = fs.realpathSync(path.join(rootRealPath, 'hooks/lib/stdin-guard.js'));
  const discovered = new Set();

  function walkDirectory(directory, relativeDirectory, ancestorRealPaths) {
    const directoryRealPath = fs.realpathSync(directory);
    if (!isWithinDirectory(rootRealPath, directoryRealPath)) {
      throw new Error(`Importer inventory symlink escapes repository scope: ${directory}`);
    }
    if (ancestorRealPaths.has(directoryRealPath)) return;
    const nextAncestors = new Set(ancestorRealPaths);
    nextAncestors.add(directoryRealPath);

    const entries = fs.readdirSync(directory, { withFileTypes: true })
      .sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const entryPath = path.join(directory, entry.name);
      const relativePath = relativeDirectory
        ? `${relativeDirectory}/${entry.name}`
        : entry.name;
      let entryKind = entry;

      if (entry.isSymbolicLink()) {
        const targetRealPath = fs.realpathSync(entryPath);
        if (!isWithinDirectory(rootRealPath, targetRealPath)) {
          throw new Error(`Importer inventory symlink escapes repository scope: ${relativePath}`);
        }
        entryKind = fs.statSync(entryPath);
      }

      if (entryKind.isDirectory()) {
        if (
          productionImporterIgnoredDirectories.has(entry.name)
          || productionImporterIgnoredRootDirectories.has(relativePath)
        ) {
          continue;
        }
        walkDirectory(entryPath, relativePath, nextAncestors);
        continue;
      }
      if (
        !entryKind.isFile()
        || !productionImporterExtensions.has(path.extname(entry.name))
      ) {
        continue;
      }
      const source = fs.readFileSync(entryPath, 'utf8');
      const sourceRealPath = fs.realpathSync(entryPath);
      if (sourceImportsStdinGuard(source, sourceRealPath, guardRealPath)) {
        discovered.add(relativePath);
      }
    }
  }

  walkDirectory(rootDirectory, '', new Set());
  return [...discovered].sort();
}

function writeFixture(root, relativePath, source) {
  const destination = path.join(root, relativePath);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, source, 'utf8');
}

function testImporterScannerExactRegressions() {
  const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'stdin-guard-inventory-'));
  const outsideRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'stdin-guard-inventory-outside-'));
  try {
    writeFixture(fixtureRoot, 'hooks/lib/stdin-guard.js', "'use strict';\n");
    writeFixture(
      fixtureRoot,
      'hooks/control-regex.js',
      "if (ok) /require('stdin-guard.js')/.test(value);\n"
    );
    writeFixture(
      fixtureRoot,
      'hooks/member-call.js',
      "loader.require('./stdin-guard.js');\n"
    );
    writeFixture(
      fixtureRoot,
      'hooks/template.js',
      'const loaded = `${require("./lib/stdin-guard.js")}`;\n'
    );
    writeFixture(
      fixtureRoot,
      'hooks/static-esm.js',
      "import { readStdinGuarded } from './lib/stdin-guard.js';\n"
    );
    writeFixture(
      fixtureRoot,
      'hooks/comment-only.js',
      "// require('./lib/stdin-guard.js');\n"
    );
    writeFixture(
      fixtureRoot,
      'hooks/string-only.js',
      "const example = \"require('./lib/stdin-guard.js')\";\n"
    );
    writeFixture(
      fixtureRoot,
      'hooks/regex-only.js',
      "const example = /require\\('.\\/lib\\/stdin-guard\\.js'\\)/;\n"
    );
    writeFixture(
      fixtureRoot,
      'hooks/shadowed-require.js',
      "function load(require) { return require('./lib/stdin-guard.js'); }\n"
    );
    writeFixture(fixtureRoot, 'other/stdin-guard.js', "'use strict';\n");
    writeFixture(
      fixtureRoot,
      'hooks/different-guard.js',
      "require('../other/stdin-guard.js');\n"
    );
    writeFixture(
      fixtureRoot,
      'production/common.cjs',
      "const { readStdinGuarded } = require('../hooks/lib/stdin-guard.js');\n"
    );
    writeFixture(
      fixtureRoot,
      'production/module.mjs',
      "import guard from '../hooks/lib/stdin-guard.js';\n"
    );
    writeFixture(
      fixtureRoot,
      'production/dynamic.mjs',
      "const guard = await import('../hooks/lib/stdin-guard.js');\n"
    );
    writeFixture(
      fixtureRoot,
      'production/named-reexport.mjs',
      "export { readStdinGuarded } from '../hooks/lib/stdin-guard.js';\n"
    );
    writeFixture(
      fixtureRoot,
      'production/star-reexport.mjs',
      "export * from '../hooks/lib/stdin-guard.js';\n"
    );
    writeFixture(
      fixtureRoot,
      'tests/symlink-target/linked.js',
      "require('../../hooks/lib/stdin-guard.js');\n"
    );
    fs.symlinkSync(
      path.join('tests', 'symlink-target'),
      path.join(fixtureRoot, 'linked-production'),
      'dir'
    );
    fs.symlinkSync(fixtureRoot, path.join(fixtureRoot, 'tests/symlink-target/cycle'), 'dir');
    fs.mkdirSync(
      path.join(fixtureRoot, '.codex/skills/agentic-engineering'),
      { recursive: true }
    );
    fs.symlinkSync(
      '../../../hooks',
      path.join(fixtureRoot, '.codex/skills/agentic-engineering/hooks'),
      'dir'
    );
    fs.mkdirSync(path.join(fixtureRoot, '.codex/skills/brief'), { recursive: true });
    fs.symlinkSync(
      '../agentic-engineering',
      path.join(fixtureRoot, '.codex/skills/brief/resources'),
      'dir'
    );

    const fixtureConsumers = discoverProductionImporters(fixtureRoot);
    const expectedFixtureConsumers = [
      'hooks/static-esm.js',
      'hooks/template.js',
      'linked-production/linked.js',
      'production/common.cjs',
      'production/dynamic.mjs',
      'production/module.mjs',
      'production/named-reexport.mjs',
      'production/star-reexport.mjs',
    ];
    assert(
      !fixtureConsumers.includes('hooks/control-regex.js'),
      'case 12 (DS-82 exact 1): regex literal after a control-flow paren is not an importer'
    );
    assert(
      !fixtureConsumers.includes('hooks/member-call.js'),
      'case 12 (DS-82 exact 2): member require call is not an importer'
    );
    assert(
      fixtureConsumers.includes('hooks/template.js'),
      'case 12 (DS-82 exact 3): require inside template interpolation is an importer'
    );
    assert(
      !fixtureConsumers.includes('hooks/comment-only.js')
        && !fixtureConsumers.includes('hooks/string-only.js')
        && !fixtureConsumers.includes('hooks/regex-only.js'),
      'case 12: comments, strings, and regex literals do not satisfy importer discovery'
    );
    assert(
      !fixtureConsumers.includes('hooks/shadowed-require.js')
        && !fixtureConsumers.includes('hooks/different-guard.js'),
      'case 12: only global require calls resolving to the shared guard are importers'
    );
    assert(
      fixtureConsumers.includes('production/common.cjs')
        && fixtureConsumers.includes('production/module.mjs')
        && fixtureConsumers.includes('hooks/static-esm.js'),
      'case 12: .js, .cjs, and .mjs static CommonJS/ESM importers are discovered'
    );
    assert(
      fixtureConsumers.includes('production/dynamic.mjs')
        && fixtureConsumers.includes('production/named-reexport.mjs')
        && fixtureConsumers.includes('production/star-reexport.mjs'),
      'case 12: dynamic imports and named/star ESM re-exports are discovered'
    );
    assert(
      fixtureConsumers.includes('linked-production/linked.js'),
      'case 12: importer reached through an in-repository directory symlink is discovered'
    );
    assert(
      !fixtureConsumers.some((consumer) => consumer.startsWith('.codex/skills/'))
        && fixtureConsumers.includes('linked-production/linked.js'),
      'case 12: generated Codex skill resource mirrors are excluded without hiding '
        + 'other in-repository symlink consumers'
    );
    assert(
      JSON.stringify(fixtureConsumers) === JSON.stringify(expectedFixtureConsumers),
      'case 12: fixture importer set is exact and symlink cycles terminate '
        + `(discovered=${JSON.stringify(fixtureConsumers)})`
    );

    const outsideSentinel = path.join(outsideRoot, 'sentinel.txt');
    fs.writeFileSync(outsideSentinel, 'preserve\n', 'utf8');
    fs.symlinkSync(outsideRoot, path.join(fixtureRoot, 'escaped-production'), 'dir');
    let escapeError = null;
    try {
      discoverProductionImporters(fixtureRoot);
    } catch (error) {
      escapeError = error;
    }
    assert(
      escapeError?.message.includes('escapes repository scope'),
      'case 12: importer inventory fails closed on a directory symlink escaping the repository'
    );
    assert(
      fs.readFileSync(outsideSentinel, 'utf8') === 'preserve\n',
      'case 12: repository-escape rejection leaves the external target untouched'
    );
  } finally {
    fs.rmSync(fixtureRoot, { recursive: true, force: true });
    fs.rmSync(outsideRoot, { recursive: true, force: true });
  }

  const repoRoot = path.resolve(__dirname, '..', '..');
  const expectedConsumers = [
    '.codex/hooks/stop-context-codex.js',
    '.copilot/hooks/stop-context-copilot.js',
    '.cursor/hooks/stop-context-cursor.js',
    '.gemini/hooks/stop-context-gemini.js',
    '.github/hooks/stop-context-copilot.js',
    'hooks/post-tool-use-capture-nudge.js',
    'hooks/pre-tool-use-spawn-emit.js',
    'hooks/session-end-wrap.js',
    'hooks/stop-context.js',
  ].sort();
  const consumers = discoverProductionImporters(repoRoot);
  assert(
    JSON.stringify(consumers) === JSON.stringify(expectedConsumers),
    'case 12: discovered production importer set exactly matches canonical consumers '
      + `(discovered=${JSON.stringify(consumers)})`
  );
  assert(
    consumers.includes('.copilot/hooks/stop-context-copilot.js')
      && consumers.includes('.github/hooks/stop-context-copilot.js'),
    'case 12: independently tracked production mirror paths remain individually accounted for'
  );
  for (const relativePath of consumers) {
    const source = fs.readFileSync(path.join(repoRoot, relativePath), 'utf8');
    assert(
      /^(?:#![^\n]*\n)?\s*\/\*\*/.test(source),
      `case 12: ${relativePath} retains a leading module manifest`
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

    console.log('Case 12: DS-82 exact importer-scanner regressions');
    testImporterScannerExactRegressions();
  } finally {
    try { fs.unlinkSync(fixturePath); } catch (_) { /* ignore */ }
    try { fs.unlinkSync(fixtureNoExitPath); } catch (_) { /* ignore */ }
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
