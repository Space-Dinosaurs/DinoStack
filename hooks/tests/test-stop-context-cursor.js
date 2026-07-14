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
 *
 * Run with: node hooks/tests/test-stop-context-cursor.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const { spawnSilentStdin, spawnDelayedChunks } = require('./lib/spawn-stdin-helpers.js');

const HOOK_PATH = path.resolve(__dirname, '..', '..', '.cursor', 'hooks', 'stop-context-cursor.js');

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

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
