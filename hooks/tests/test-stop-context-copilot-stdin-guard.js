#!/usr/bin/env node
/**
 * Integration tests: .copilot/hooks/stop-context-copilot.js and its
 * hand-duplicated mirror .github/hooks/stop-context-copilot.js bounded-
 * stdin-guard swap (docs/planning/cursor-stop-hook-plan.md Unit A item 8).
 * This port had zero existing test coverage before this unit.
 *
 * DS-176: both scripts are hand-duplicated copies of each other (not
 * build-generated), so every case below runs against BOTH hook paths -
 * see HOOK_SCRIPTS.
 *
 * Test cases (each run once per entry in HOOK_SCRIPTS):
 *   (a) open-but-silent stdin -> exit 0, elapsed <1200ms (CI slack over the
 *       1000ms production-defaults bar asserted at the shared-helper level
 *       in test-stdin-guard.js).
 *   (b) one normal-payload smoke -> context.md written at the port's
 *       existing output path (<repo root>/.agentic/context.md).
 *   (c) DS-176 regression: a drifted payload cwd deep inside a real repo
 *       writes .agentic/context.md at the REPO ROOT, not the drifted
 *       subdirectory - the .agentic/ write is anchored via
 *       hooks/lib/repo-root.js's resolveAgenticCwdWithDiagnostics, not the
 *       payload cwd verbatim.
 *   (d) DS-176 regression: no .git ancestor anywhere -> the write is
 *       SKIPPED entirely, never falls back to the unresolved payload cwd.
 *
 * Run with: node hooks/tests/test-stop-context-copilot-stdin-guard.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const { spawnSilentStdin, spawnDelayedChunks } = require('./lib/spawn-stdin-helpers.js');

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

const HOOK_SCRIPTS = [
  { label: '.copilot', path: path.resolve(__dirname, '..', '..', '.copilot', 'hooks', 'stop-context-copilot.js') },
  { label: '.github', path: path.resolve(__dirname, '..', '..', '.github', 'hooks', 'stop-context-copilot.js') },
];

for (const { label, path: hookScript } of HOOK_SCRIPTS) {
  if (!fs.existsSync(hookScript)) {
    console.error(`FAIL: ${label} hook not found at ${hookScript}`);
    process.exit(1);
  }
}

function makeTmp(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

/**
 * Creates a tmp fixture dir with a `.git` entry so it resolves as a repo
 * root under the DS-176 repo-root anchoring fix (the hook now walks up
 * from the payload cwd to the nearest `.git` ancestor and SKIPS the write
 * entirely when none is found).
 */
function makeGitFixture(prefix) {
  const dir = makeTmp(prefix);
  fs.mkdirSync(path.join(dir, '.git'));
  return dir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

// ---------------------------------------------------------------------------
// (a) open-but-silent stdin -> bounded exit
// ---------------------------------------------------------------------------

async function testOpenButSilentStdin(hookScript, label) {
  const tmpDir = makeTmp('ae-copilot-stdinguard-a-');
  try {
    const result = await spawnSilentStdin({
      cmd: process.execPath,
      args: [hookScript],
      env: process.env,
      maxWaitMs: 3000,
    });
    assert(!result.timedOut, `(a ${label}) hook exits on its own (not force-killed by the test harness)`);
    assert(result.code === 0, `(a ${label}) hook exits 0 (got: ${result.code})`);
    assert(
      result.elapsedMs < 1200,
      `(a ${label}) hook exits with bounded elapsed time under CI slack (${result.elapsedMs}ms, must be < 1200ms)`
    );
    assert(result.stdout.trim() === '{}', `(a ${label}) stdout is the empty-object success contract (got: ${JSON.stringify(result.stdout)})`);
  } finally {
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// (b) normal-payload smoke -> context.md written at <repo root>/.agentic/
// ---------------------------------------------------------------------------

async function testNormalPayloadWritesContext(hookScript, label) {
  const repoRoot = makeGitFixture('ae-copilot-stdinguard-b-');
  try {
    const payload = JSON.stringify({
      cwd: repoRoot,
      session_id: 'copilot-stdin-guard-smoke-session',
      last_assistant_message: 'copilot stdin-guard smoke test assistant message',
      model: 'copilot-test',
    });

    const result = await spawnDelayedChunks({
      cmd: process.execPath,
      args: [hookScript],
      env: process.env,
      chunks: [payload],
      gapMs: 0,
      holdOpenMs: 0,
      maxWaitMs: 5000,
    });

    assert(!result.timedOut, `(b ${label}) hook exits on its own (not force-killed by the test harness)`);
    assert(result.code === 0, `(b ${label}) hook exits 0 (got: ${result.code})`);
    assert(result.stdout.trim() === '{}', `(b ${label}) stdout is the empty-object success contract (got: ${JSON.stringify(result.stdout)})`);

    const contextPath = path.join(repoRoot, '.agentic', 'context.md');
    assert(fs.existsSync(contextPath), `(b ${label}) context.md written at ${contextPath}`);
    if (fs.existsSync(contextPath)) {
      const content = fs.readFileSync(contextPath, 'utf8');
      assert(content.includes('copilot stdin-guard smoke test assistant message'),
        `(b ${label}) context.md contains the delivered last_assistant_message`);
    }
  } finally {
    cleanup(repoRoot);
  }
}

// ---------------------------------------------------------------------------
// (c) DS-176 regression: drifted payload cwd -> write lands at repo root
//
// Reddening mutation: reverting the resolveAgenticCwdWithDiagnostics call
// back to using the payload cwd directly (the pre-fix state) makes this
// test fail for the wrong reason it was written to catch - context.md
// would be written at the DRIFTED subdirectory instead of the repo root.
// ---------------------------------------------------------------------------

async function testDriftedCwdWritesAtRepoRoot(hookScript, label) {
  const repoRoot = makeGitFixture('ae-copilot-stdinguard-c-');
  try {
    const driftedDir = path.join(repoRoot, 'sub', 'nested', 'drift');
    fs.mkdirSync(driftedDir, { recursive: true });

    const payload = JSON.stringify({
      cwd: driftedDir,
      session_id: 'copilot-drifted-cwd-session',
      last_assistant_message: 'drifted cwd regression',
      model: 'copilot-test',
    });

    const result = await spawnDelayedChunks({
      cmd: process.execPath,
      args: [hookScript],
      env: process.env,
      chunks: [payload],
      gapMs: 0,
      holdOpenMs: 0,
      maxWaitMs: 5000,
    });

    assert(result.code === 0, `(c ${label}) hook exits 0`);

    const rootContextPath = path.join(repoRoot, '.agentic', 'context.md');
    const driftedContextPath = path.join(driftedDir, '.agentic', 'context.md');
    assert(
      fs.existsSync(rootContextPath),
      `(c ${label}) .agentic/context.md written at the REPO ROOT, not the drifted subdirectory`
    );
    assert(
      !fs.existsSync(driftedContextPath),
      `(c ${label}) no phantom .agentic tree written at the drifted subdirectory`
    );
  } finally {
    cleanup(repoRoot);
  }
}

// ---------------------------------------------------------------------------
// (d) DS-176 regression: no .git ancestor anywhere -> write is SKIPPED
// entirely, never falls back to the unresolved cwd.
// ---------------------------------------------------------------------------

async function testNoGitAncestorSkipsWrite(hookScript, label) {
  const noGitDir = makeTmp('ae-copilot-stdinguard-d-');
  try {
    const payload = JSON.stringify({
      cwd: noGitDir,
      session_id: 'copilot-no-git-ancestor-session',
      last_assistant_message: 'no git ancestor regression',
      model: 'copilot-test',
    });

    const result = await spawnDelayedChunks({
      cmd: process.execPath,
      args: [hookScript],
      env: process.env,
      chunks: [payload],
      gapMs: 0,
      holdOpenMs: 0,
      maxWaitMs: 5000,
    });

    assert(result.code === 0, `(d ${label}) hook exits 0`);

    const contextPath = path.join(noGitDir, '.agentic', 'context.md');
    assert(
      !fs.existsSync(contextPath),
      `(d ${label}) write is SKIPPED, no .agentic tree created`
    );
  } finally {
    cleanup(noGitDir);
  }
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

async function main() {
  for (const { label, path: hookScript } of HOOK_SCRIPTS) {
    console.log(`\n=== ${label} ===`);

    console.log('(a) open-but-silent stdin -> bounded exit');
    await testOpenButSilentStdin(hookScript, label);

    console.log('\n(b) normal-payload smoke -> context.md written');
    await testNormalPayloadWritesContext(hookScript, label);

    console.log('\n(c) DS-176 regression: drifted cwd writes at repo root');
    await testDriftedCwdWritesAtRepoRoot(hookScript, label);

    console.log('\n(d) DS-176 regression: no .git ancestor skips the write');
    await testNoGitAncestorSkipsWrite(hookScript, label);
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
