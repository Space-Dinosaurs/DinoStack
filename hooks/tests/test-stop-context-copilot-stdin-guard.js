#!/usr/bin/env node
/**
 * Integration tests: .copilot/hooks/stop-context-copilot.js bounded-stdin-
 * guard swap (docs/planning/cursor-stop-hook-plan.md Unit A item 8). This
 * port had zero existing test coverage before this unit.
 *
 * Test cases:
 *   (a) open-but-silent stdin -> exit 0, elapsed <1200ms (CI slack over the
 *       1000ms production-defaults bar asserted at the shared-helper level
 *       in test-stdin-guard.js).
 *   (b) one normal-payload smoke -> context.md written at the port's
 *       existing output path (<cwd>/.agentic/context.md).
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

const hookScript = path.resolve(__dirname, '..', '..', '.copilot', 'hooks', 'stop-context-copilot.js');
if (!fs.existsSync(hookScript)) {
  console.error(`FAIL: hook not found at ${hookScript}`);
  process.exit(1);
}

function makeTmp(prefix) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

// ---------------------------------------------------------------------------
// (a) open-but-silent stdin -> bounded exit
// ---------------------------------------------------------------------------

async function testOpenButSilentStdin() {
  const tmpDir = makeTmp('ae-copilot-stdinguard-a-');
  try {
    const result = await spawnSilentStdin({
      cmd: process.execPath,
      args: [hookScript],
      env: process.env,
      maxWaitMs: 3000,
    });
    assert(!result.timedOut, '(a) hook exits on its own (not force-killed by the test harness)');
    assert(result.code === 0, `(a) hook exits 0 (got: ${result.code})`);
    assert(
      result.elapsedMs < 1200,
      `(a) hook exits with bounded elapsed time under CI slack (${result.elapsedMs}ms, must be < 1200ms)`
    );
    assert(result.stdout.trim() === '{}', `(a) stdout is the empty-object success contract (got: ${JSON.stringify(result.stdout)})`);
  } finally {
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// (b) normal-payload smoke -> context.md written at <cwd>/.agentic/
// ---------------------------------------------------------------------------

async function testNormalPayloadWritesContext() {
  const tmpDir = makeTmp('ae-copilot-stdinguard-b-');
  try {
    const projectDir = path.join(tmpDir, 'project');
    fs.mkdirSync(projectDir, { recursive: true });

    const payload = JSON.stringify({
      cwd: projectDir,
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

    assert(!result.timedOut, '(b) hook exits on its own (not force-killed by the test harness)');
    assert(result.code === 0, `(b) hook exits 0 (got: ${result.code})`);
    assert(result.stdout.trim() === '{}', `(b) stdout is the empty-object success contract (got: ${JSON.stringify(result.stdout)})`);

    const contextPath = path.join(projectDir, '.agentic', 'context.md');
    assert(fs.existsSync(contextPath), `(b) context.md written at ${contextPath}`);
    if (fs.existsSync(contextPath)) {
      const content = fs.readFileSync(contextPath, 'utf8');
      assert(content.includes('copilot stdin-guard smoke test assistant message'),
        '(b) context.md contains the delivered last_assistant_message');
    }
  } finally {
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

async function main() {
  console.log('(a) open-but-silent stdin -> bounded exit');
  await testOpenButSilentStdin();

  console.log('\n(b) normal-payload smoke -> context.md written');
  await testNormalPayloadWritesContext();

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
