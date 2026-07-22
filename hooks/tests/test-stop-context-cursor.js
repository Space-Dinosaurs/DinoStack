#!/usr/bin/env node
/**
 * Integration tests: .cursor/hooks/stop-context-cursor.js.
 *
 * Spawns the real hook as a subprocess (via hooks/tests/lib/spawn-stdin-helpers.js)
 * so the stdin-guard timing behavior and the require('../../hooks/lib/stdin-guard.js')
 * resolution are both exercised for real - a shimmed/in-process require would hide a
 * MODULE_NOT_FOUND regression (rubric R4).
 *
 * Test cases:
 *   (a) open-but-silent stdin -> stdout is exactly {} and exit 0, bounded <1200ms.
 *   (b) representative confirmed-schema Cursor payload (status/loop_count + base
 *       fields incl. workspace_roots pointing at a tmp fixture dir, conversation_id,
 *       model, transcript_path to a small fixture file) -> .agentic/context.md written
 *       in the fixture cwd with the expected fields, stdout exactly {}, exit 0, no
 *       MODULE_NOT_FOUND on stderr.
 *   (c) contingency: payload with NO workspace_roots and CURSOR_PROJECT_DIR /
 *       CLAUDE_PROJECT_DIR scrubbed from env -> exit 0, stdout {}, NO context.md
 *       created, empty stderr.
 *   (d) stdout-shape assertion (folded into every case above): parsed stdout is an
 *       object with NO followup_message key - the loop_limit landmine this hook must
 *       never trip.
 *   (e) oversized transcript: fixture transcript file > 256KB -> context.md contains
 *       '(transcript too large)' and the hook still exits fast.
 *   Regression (Skeptic Major): the cwd guard normalizes via path.resolve(), it must
 *       never reject a non-canonical-but-legitimate workspace root - a trailing slash
 *       and a '/./' segment both resolve to the same directory and .agentic/context.md
 *       IS written there (case b's mkdtempSync fixture can never carry either variant,
 *       so it cannot catch this on its own).
 *   Security regression (PR #453 review, Medium - TOCTOU + unbounded read):
 *     - toctou-symlink-swap-closed: a symlink retargeted (small -> oversized file)
 *       immediately after the path is first resolved (the exact race window the
 *       finding describes) must NOT leak the swapped-in file's content - the fd-based
 *       fstatSync/readSync pair stays bound to the originally-opened inode. Driven
 *       in-process via a monkeypatched fs.statSync/fs.openSync (a live microsecond
 *       race would be flaky; this reproduces the failure mode deterministically).
 *       Verified to reproduce the leak against the pre-fix path-based
 *       statSync+readFileSync implementation before this fix landed.
 *     - non-regular-fifo-no-hang: a FIFO with no writer must never hang the hook.
 *       Verified experimentally that the pre-fix implementation (fs.statSync passes a
 *       FIFO's 0-byte size gate, then fs.readFileSync blocks opening it) hangs past a
 *       bounded kill window; the fix's O_NONBLOCK open + stat.isFile() guard returns
 *       immediately without ever attempting a read.
 *     - non-regular-directory: a directory path also resolves to '(not available)'
 *       (steady-state confirmation of the explicit isFile() guard - this exact
 *       observable outcome is unchanged from the pre-fix EISDIR-exception fallback,
 *       so unlike the FIFO case above it is not a pre/post differential).
 *     - cap-boundary: a file exactly at TRANSCRIPT_MAX_BYTES is read in full; one byte
 *       over is rejected (bounded-read proof for the Math.min-capped buffer).
 *
 * Run with: node hooks/tests/test-stop-context-cursor.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const { spawnSilentStdin, spawnDelayedChunks } = require('./lib/spawn-stdin-helpers.js');

const HOOK_PATH = path.resolve(__dirname, '..', '..', '.cursor', 'hooks', 'stop-context-cursor.js');

// Required in-process (not spawned) only for the TOCTOU test below, which needs to
// monkeypatch fs.statSync/fs.openSync in the SAME process as the function under
// test. readTranscriptExcerpt is exported by stop-context-cursor.js only when
// required (require.main !== module inside that file), which holds here - this
// require does NOT invoke run() or perform any stdin/process side effects.
const { readTranscriptExcerpt } = require(HOOK_PATH);

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

/**
 * Shared stdout-shape assertion (case d, applied to every scenario): parsed
 * stdout must be exactly {} - an object with zero keys, and specifically no
 * followup_message key (the loop_limit landmine this hook must never trip).
 * @param {string} rawStdout
 * @param {string} label
 */
function assertStdoutShape(rawStdout, label) {
  let parsed;
  try {
    parsed = JSON.parse(rawStdout);
  } catch (_) {
    parsed = null;
  }
  assert(parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed), `${label}: stdout parses to a JSON object`);
  if (parsed) {
    assert(!('followup_message' in parsed), `${label}: stdout has NO followup_message key`);
    assert(Object.keys(parsed).length === 0, `${label}: stdout is exactly {} (no extra keys)`);
  }
}

function mkFixtureDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

// ---------------------------------------------------------------------------
// Case (a): open-but-silent stdin -> bounded exit
// ---------------------------------------------------------------------------

async function testOpenSilentStdin() {
  const result = await spawnSilentStdin({
    cmd: process.execPath,
    args: [HOOK_PATH],
    maxWaitMs: 3000,
  });
  assert(!result.timedOut, 'case a: process exits on its own (not force-killed)');
  assert(result.code === 0, 'case a: exits 0');
  assert(result.elapsedMs < 1200, `case a: resolves bounded, under 1200ms (${result.elapsedMs}ms)`);
  assertStdoutShape(result.stdout, 'case a');
}

// ---------------------------------------------------------------------------
// Case (b): representative confirmed-schema Cursor payload
// ---------------------------------------------------------------------------

async function testRepresentativePayload() {
  const fixtureCwd = mkFixtureDir('cursor-stop-test-b-');
  const transcriptPath = path.join(fixtureCwd, 'transcript.txt');
  fs.writeFileSync(transcriptPath, 'assistant: finished the refactor and ran the tests.\n', 'utf8');

  const payload = {
    status: 'completed',
    loop_count: 3,
    conversation_id: 'conv-abc-123',
    generation_id: 'gen-xyz-789',
    model: 'claude-sonnet-4.5',
    model_id: 'claude-sonnet-4-5-20250929',
    model_params: [],
    hook_event_name: 'stop',
    cursor_version: '1.4.0',
    workspace_roots: [fixtureCwd],
    user_email: null,
    transcript_path: transcriptPath,
  };

  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: [HOOK_PATH],
    chunks: [JSON.stringify(payload)],
    gapMs: 0,
    holdOpenMs: 0,
  });

  assert(result.code === 0, 'case b: exits 0');
  assert(!result.stderr.includes('MODULE_NOT_FOUND'), 'case b: no MODULE_NOT_FOUND on stderr (rubric R4)');
  assertStdoutShape(result.stdout, 'case b');

  const contextPath = path.join(fixtureCwd, '.agentic', 'context.md');
  assert(fs.existsSync(contextPath), 'case b: .agentic/context.md written in the fixture cwd');
  if (fs.existsSync(contextPath)) {
    const content = fs.readFileSync(contextPath, 'utf8');
    assert(content.includes('Cursor'), 'case b: content carries the Cursor harness label');
    assert(content.includes(fixtureCwd), 'case b: content records the project cwd');
    assert(content.includes('conv-abc-123'), 'case b: content records the session id (conversation_id)');
    assert(content.includes('claude-sonnet-4.5'), 'case b: content records the model');
    assert(content.includes('completed'), 'case b: content records the stop status');
    assert(
      content.includes('finished the refactor and ran the tests'),
      'case b: content includes the transcript excerpt as the last-activity hint'
    );
  }
}

// ---------------------------------------------------------------------------
// Case (c): contingency - no workspace_roots, env scrubbed -> guarded no-op
// ---------------------------------------------------------------------------

async function testContingencyNoWorkspaceRoot() {
  const fixtureCwd = mkFixtureDir('cursor-stop-test-c-');

  const payload = {
    status: 'completed',
    loop_count: 1,
    conversation_id: 'conv-no-workspace',
    model: 'claude-sonnet-4.5',
    hook_event_name: 'stop',
    cursor_version: '1.4.0',
    user_email: null,
    transcript_path: null,
    // Deliberately no workspace_roots field.
  };

  const env = Object.assign({}, process.env);
  delete env.CURSOR_PROJECT_DIR;
  delete env.CLAUDE_PROJECT_DIR;

  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: [HOOK_PATH],
    cwd: fixtureCwd,
    env,
    chunks: [JSON.stringify(payload)],
    gapMs: 0,
    holdOpenMs: 0,
  });

  assert(result.code === 0, 'case c: exits 0');
  assert(result.stderr.trim() === '', 'case c: stderr is empty');
  assertStdoutShape(result.stdout, 'case c');

  const contextPath = path.join(fixtureCwd, '.agentic', 'context.md');
  assert(!fs.existsSync(contextPath), 'case c: guarded safe no-op - no context.md created');
}

// ---------------------------------------------------------------------------
// Regression (Skeptic Major): a non-canonical-but-legitimate workspace root
// (trailing slash, or a '/./' segment) must still get context.md written -
// the cwd guard normalizes via path.resolve(), it must never reject. Case b
// cannot catch this: mkdtempSync never returns a trailing slash or a '/./'
// segment, so these need their own fixtures that deliberately construct one.
// ---------------------------------------------------------------------------

async function testTrailingSlashWorkspaceRoot() {
  const fixtureCwd = mkFixtureDir('cursor-stop-test-trailing-');
  const trailingSlashRoot = fixtureCwd + '/';

  const payload = {
    status: 'completed',
    loop_count: 2,
    conversation_id: 'conv-trailing-slash',
    model: 'claude-sonnet-4.5',
    hook_event_name: 'stop',
    cursor_version: '1.4.0',
    workspace_roots: [trailingSlashRoot],
    user_email: null,
    transcript_path: null,
  };

  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: [HOOK_PATH],
    chunks: [JSON.stringify(payload)],
    gapMs: 0,
    holdOpenMs: 0,
  });

  assert(result.code === 0, 'regression (trailing slash): exits 0');
  assertStdoutShape(result.stdout, 'regression (trailing slash)');

  const contextPath = path.join(path.resolve(trailingSlashRoot), '.agentic', 'context.md');
  assert(
    fs.existsSync(contextPath),
    'regression (trailing slash): .agentic/context.md IS written (normalized, not rejected)'
  );
}

async function testDotSegmentWorkspaceRoot() {
  const fixtureCwd = mkFixtureDir('cursor-stop-test-dotseg-');
  // Deliberately construct a workspace root containing a '/./' segment -
  // path.dirname/basename recombination that path.resolve() will normalize
  // back to fixtureCwd.
  const dotSegmentRoot = `${path.dirname(fixtureCwd)}/./${path.basename(fixtureCwd)}`;

  const payload = {
    status: 'completed',
    loop_count: 2,
    conversation_id: 'conv-dot-segment',
    model: 'claude-sonnet-4.5',
    hook_event_name: 'stop',
    cursor_version: '1.4.0',
    workspace_roots: [dotSegmentRoot],
    user_email: null,
    transcript_path: null,
  };

  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: [HOOK_PATH],
    chunks: [JSON.stringify(payload)],
    gapMs: 0,
    holdOpenMs: 0,
  });

  assert(result.code === 0, "regression (dot segment): exits 0");
  assertStdoutShape(result.stdout, 'regression (dot segment)');

  const contextPath = path.join(path.resolve(dotSegmentRoot), '.agentic', 'context.md');
  assert(
    fs.existsSync(contextPath),
    "regression (dot segment): .agentic/context.md IS written for a '/./'-containing root"
  );
}

// ---------------------------------------------------------------------------
// Case (e): oversized transcript -> skipped entirely, placeholder used
// ---------------------------------------------------------------------------

async function testOversizedTranscript() {
  const fixtureCwd = mkFixtureDir('cursor-stop-test-e-');
  const transcriptPath = path.join(fixtureCwd, 'big-transcript.txt');
  // > 256 KB so the statSync guard skips the read entirely.
  fs.writeFileSync(transcriptPath, 'x'.repeat(256 * 1024 + 1024), 'utf8');

  const payload = {
    status: 'completed',
    loop_count: 5,
    conversation_id: 'conv-big-transcript',
    model: 'claude-sonnet-4.5',
    hook_event_name: 'stop',
    cursor_version: '1.4.0',
    workspace_roots: [fixtureCwd],
    user_email: null,
    transcript_path: transcriptPath,
  };

  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: [HOOK_PATH],
    chunks: [JSON.stringify(payload)],
    gapMs: 0,
    holdOpenMs: 0,
  });

  assert(result.code === 0, 'case e: exits 0');
  assert(result.elapsedMs < 1200, `case e: still exits fast despite the oversized transcript (${result.elapsedMs}ms)`);
  assertStdoutShape(result.stdout, 'case e');

  const contextPath = path.join(fixtureCwd, '.agentic', 'context.md');
  assert(fs.existsSync(contextPath), 'case e: .agentic/context.md still written');
  if (fs.existsSync(contextPath)) {
    const content = fs.readFileSync(contextPath, 'utf8');
    assert(content.includes('(transcript too large)'), 'case e: content uses the oversized-transcript placeholder');
    assert(!content.includes('xxxxxxxxxx'), 'case e: the oversized transcript body was never read into content.md');
  }
}

// ---------------------------------------------------------------------------
// Security regression (PR #453 review, Medium): TOCTOU symlink swap must be
// closed. readTranscriptExcerpt must resolve the path exactly ONCE and check
// + read against the SAME fd, so a symlink retargeted between the size
// check and the read can never smuggle a different (oversized) file's
// content past the gate.
//
// Driven in-process (readTranscriptExcerpt required directly, not spawned)
// so fs.statSync/fs.openSync can be monkeypatched to deterministically fire
// the retarget immediately after the path is FIRST resolved - i.e. exactly
// the race window the finding describes. A live microsecond-scale race
// would be flaky to assert on; this reproduces the failure mode
// deterministically instead. Confirmed pre-fix: running this same swap
// against the old statSync+readFileSync implementation returns the
// oversized file's content (the gate is bypassed) instead of the original
// small file's content.
// ---------------------------------------------------------------------------

function testToctouSymlinkSwapClosed() {
  const fixtureCwd = mkFixtureDir('cursor-stop-test-toctou-');
  const smallPath = path.join(fixtureCwd, 'small.txt');
  const largePath = path.join(fixtureCwd, 'large.txt');
  const SMALL_CONTENT = 'SMALL-SAFE-CONTENT';
  fs.writeFileSync(smallPath, SMALL_CONTENT, 'utf8');
  fs.writeFileSync(largePath, 'B'.repeat(256 * 1024 + 1024), 'utf8');
  const symlinkPath = path.join(fixtureCwd, 'link');
  fs.symlinkSync(smallPath, symlinkPath);

  // Fire the retarget the first time the symlink path is resolved by either
  // implementation under test (statSync in the old code, openSync in the
  // fixed code) - right after that first call returns, before any read.
  let swapped = false;
  function maybeSwap(p) {
    if (!swapped && p === symlinkPath) {
      swapped = true;
      fs.unlinkSync(symlinkPath);
      fs.symlinkSync(largePath, symlinkPath);
    }
  }
  const origStatSync = fs.statSync;
  const origOpenSync = fs.openSync;
  fs.statSync = function (p, ...args) {
    const result = origStatSync.call(fs, p, ...args);
    maybeSwap(p);
    return result;
  };
  fs.openSync = function (p, ...args) {
    const result = origOpenSync.call(fs, p, ...args);
    maybeSwap(p);
    return result;
  };

  let result;
  try {
    result = readTranscriptExcerpt(symlinkPath);
  } finally {
    fs.statSync = origStatSync;
    fs.openSync = origOpenSync;
  }

  assert(swapped, 'toctou: the injected symlink retarget actually fired (precondition)');
  assert(
    result === SMALL_CONTENT,
    `toctou: result reflects the ORIGINALLY-opened (small) file, unaffected by the post-open retarget - got ${JSON.stringify((result || '').slice(0, 60))}`
  );
  assert(
    !/B{4,}/.test(result || ''),
    'toctou: result does NOT leak the swapped-in oversized file content (size gate not bypassed)'
  );
}

// ---------------------------------------------------------------------------
// Security regression (PR #453 review, Medium): non-regular file (FIFO) must
// never hang the hook. Pre-fix, fs.statSync(fifoPath) succeeds immediately
// (metadata-only) and a FIFO reports size 0 (passes the gate), but the
// subsequent fs.readFileSync(fifoPath) blocks opening it for reading with no
// writer connected - confirmed experimentally to hang past a bounded
// timeout against the pre-fix implementation. Post-fix, the fd is opened
// O_NONBLOCK (open() itself cannot hang) and stat.isFile() rejects the FIFO
// before any read is attempted.
// ---------------------------------------------------------------------------

async function testNonRegularFifoNoHang() {
  const fixtureCwd = mkFixtureDir('cursor-stop-test-fifo-');
  const fifoPath = path.join(fixtureCwd, 'transcript.fifo');

  let fifoAvailable = true;
  try {
    execFileSync('mkfifo', [fifoPath]);
  } catch (_) {
    fifoAvailable = false;
  }
  if (!fifoAvailable) {
    console.log('  SKIP: mkfifo unavailable on this platform - FIFO non-hang case skipped');
    return;
  }

  const payload = {
    status: 'completed',
    loop_count: 1,
    conversation_id: 'conv-fifo-nonregular',
    model: 'claude-sonnet-4.5',
    hook_event_name: 'stop',
    cursor_version: '1.4.0',
    workspace_roots: [fixtureCwd],
    user_email: null,
    transcript_path: fifoPath,
  };

  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: [HOOK_PATH],
    chunks: [JSON.stringify(payload)],
    gapMs: 0,
    holdOpenMs: 0,
    maxWaitMs: 3000,
  });

  assert(!result.timedOut, 'fifo: hook does NOT hang reading a writer-less FIFO (pre-fix hangs past this bound)');
  assert(result.code === 0, 'fifo: exits 0');
  assertStdoutShape(result.stdout, 'fifo');

  const contextPath = path.join(fixtureCwd, '.agentic', 'context.md');
  assert(fs.existsSync(contextPath), 'fifo: .agentic/context.md still written');
  if (fs.existsSync(contextPath)) {
    const content = fs.readFileSync(contextPath, 'utf8');
    assert(content.includes('(not available)'), 'fifo: non-regular file resolves to the not-available placeholder');
  }
}

// ---------------------------------------------------------------------------
// Non-regular file: a directory path also resolves to '(not available)'.
// Note: this exact observable outcome is UNCHANGED from the pre-fix
// implementation (which reached the same placeholder via readFileSync's
// EISDIR exception, not an explicit type check) - included as a
// steady-state confirmation of the new explicit stat.isFile() guard, not a
// pre/post differential. testNonRegularFifoNoHang above is the genuine
// differential for the "non-regular file" finding, since a directory never
// hangs but a FIFO does.
// ---------------------------------------------------------------------------

async function testNonRegularDirectory() {
  const fixtureCwd = mkFixtureDir('cursor-stop-test-dir-');
  const dirPath = path.join(fixtureCwd, 'a-directory');
  fs.mkdirSync(dirPath);

  const payload = {
    status: 'completed',
    loop_count: 1,
    conversation_id: 'conv-dir-nonregular',
    model: 'claude-sonnet-4.5',
    hook_event_name: 'stop',
    cursor_version: '1.4.0',
    workspace_roots: [fixtureCwd],
    user_email: null,
    transcript_path: dirPath,
  };

  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: [HOOK_PATH],
    chunks: [JSON.stringify(payload)],
    gapMs: 0,
    holdOpenMs: 0,
  });

  assert(result.code === 0, 'directory: exits 0');
  assertStdoutShape(result.stdout, 'directory');

  const contextPath = path.join(fixtureCwd, '.agentic', 'context.md');
  assert(fs.existsSync(contextPath), 'directory: .agentic/context.md still written');
  if (fs.existsSync(contextPath)) {
    const content = fs.readFileSync(contextPath, 'utf8');
    assert(content.includes('(not available)'), 'directory: non-regular file resolves to the not-available placeholder');
  }
}

// ---------------------------------------------------------------------------
// Bounded-read proof: a file exactly AT the cap is read in full; one byte
// OVER the cap is rejected. Both pre-fix and post-fix use the same strict
// `stat.size > TRANSCRIPT_MAX_BYTES` comparison, so this is a boundary-value
// sanity check (not a pre/post differential) confirming the fd-based
// fstatSync sees the same byte count the old statSync did, and that the new
// Math.min-capped buffer allocation reads the full file when exactly at the
// cap.
// ---------------------------------------------------------------------------

async function testCapBoundary() {
  const CAP = 256 * 1024;

  {
    const fixtureCwd = mkFixtureDir('cursor-stop-test-cap-at-');
    const transcriptPath = path.join(fixtureCwd, 'at-cap.txt');
    fs.writeFileSync(transcriptPath, 'A'.repeat(CAP), 'utf8');

    const payload = {
      status: 'completed', loop_count: 1, conversation_id: 'conv-cap-at',
      model: 'claude-sonnet-4.5', hook_event_name: 'stop', cursor_version: '1.4.0',
      workspace_roots: [fixtureCwd], user_email: null, transcript_path: transcriptPath,
    };
    const result = await spawnDelayedChunks({
      cmd: process.execPath, args: [HOOK_PATH], chunks: [JSON.stringify(payload)], gapMs: 0, holdOpenMs: 0,
    });
    assert(result.code === 0, 'cap-at: exits 0');
    const contextPath = path.join(fixtureCwd, '.agentic', 'context.md');
    const content = fs.existsSync(contextPath) ? fs.readFileSync(contextPath, 'utf8') : '';
    assert(!content.includes('(transcript too large)'), 'cap-at: a file exactly at the cap is NOT rejected');
    assert(content.includes('AAAA'), 'cap-at: a file exactly at the cap is actually read');
  }

  {
    const fixtureCwd = mkFixtureDir('cursor-stop-test-cap-over-');
    const transcriptPath = path.join(fixtureCwd, 'over-cap.txt');
    fs.writeFileSync(transcriptPath, 'A'.repeat(CAP + 1), 'utf8');

    const payload = {
      status: 'completed', loop_count: 1, conversation_id: 'conv-cap-over',
      model: 'claude-sonnet-4.5', hook_event_name: 'stop', cursor_version: '1.4.0',
      workspace_roots: [fixtureCwd], user_email: null, transcript_path: transcriptPath,
    };
    const result = await spawnDelayedChunks({
      cmd: process.execPath, args: [HOOK_PATH], chunks: [JSON.stringify(payload)], gapMs: 0, holdOpenMs: 0,
    });
    assert(result.code === 0, 'cap-over: exits 0');
    const contextPath = path.join(fixtureCwd, '.agentic', 'context.md');
    const content = fs.existsSync(contextPath) ? fs.readFileSync(contextPath, 'utf8') : '';
    assert(content.includes('(transcript too large)'), 'cap-over: one byte over the cap IS rejected');
  }
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

async function main() {
  console.log('Case a: open-but-silent stdin');
  await testOpenSilentStdin();

  console.log('Case b: representative confirmed-schema Cursor payload');
  await testRepresentativePayload();

  console.log('Case c: contingency - no workspace_roots, env scrubbed');
  await testContingencyNoWorkspaceRoot();

  console.log('Regression: trailing-slash workspace root (Skeptic Major)');
  await testTrailingSlashWorkspaceRoot();

  console.log('Regression: /./-segment workspace root');
  await testDotSegmentWorkspaceRoot();

  console.log('Case e: oversized transcript');
  await testOversizedTranscript();

  console.log('Security regression: TOCTOU symlink swap is closed (PR #453 review)');
  testToctouSymlinkSwapClosed();

  console.log('Security regression: non-regular FIFO does not hang the hook');
  await testNonRegularFifoNoHang();

  console.log('Non-regular file: directory resolves to (not available)');
  await testNonRegularDirectory();

  console.log('Bounded-read proof: cap boundary (at cap vs over cap)');
  await testCapBoundary();

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
