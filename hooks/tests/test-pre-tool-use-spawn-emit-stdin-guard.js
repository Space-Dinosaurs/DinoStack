#!/usr/bin/env node
/**
 * Purpose: stdin-guard hardening tests for hooks/pre-tool-use-spawn-emit.js
 *          (docs/planning/cursor-stop-hook-plan.md Unit A item 7b). Two
 *          cases:
 *
 *          (a) open-but-silent stdin -> the hook must still exit 0 within the
 *              stdin-guard bound instead of hanging on the previous blocking
 *              `fs.readFileSync('/dev/stdin', 'utf8')` read.
 *          (b) normal-payload smoke: a real Task spawn payload still emits a
 *              spawn_start event to events.jsonl (proves the guarded read
 *              swap did not break the hook's existing behavior - see
 *              test-spawn-emit.js Test 1 for the full existing coverage this
 *              smoke intentionally mirrors at a smaller scale).
 *
 * Run with: node hooks/tests/test-pre-tool-use-spawn-emit-stdin-guard.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const { spawnSilentStdin } = require('./lib/spawn-stdin-helpers.js');

const hookPath = path.resolve(__dirname, '..', 'pre-tool-use-spawn-emit.js');

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

function makeTmpProject() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-spawn-emit-sg-test-'));
  fs.mkdirSync(path.join(tmpDir, '.agentic'), { recursive: true });
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

function readEvents(tmpDir) {
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');
  if (!fs.existsSync(eventsPath)) return [];
  return fs.readFileSync(eventsPath, 'utf8')
    .split('\n').filter(Boolean)
    .map(line => { try { return JSON.parse(line); } catch (_) { return null; } })
    .filter(Boolean);
}

// ---------------------------------------------------------------------------
// (a) open-but-silent stdin -> bounded exit 0
// stdin is opened but never written to and never closed - the hook must
// still exit 0 within the stdin-guard bound rather than hanging.
// ---------------------------------------------------------------------------
async function testOpenSilentStdinBoundedExit() {
  console.log('\n[a] open-but-silent stdin -> bounded exit 0');
  const cwd = makeTmpProject();
  const result = await spawnSilentStdin({
    cmd: process.execPath,
    args: [hookPath],
    cwd,
    maxWaitMs: 3000,
  });
  assert(!result.timedOut, `hook exits on its own within the bound (elapsed ${result.elapsedMs}ms, not force-killed)`);
  assert(result.code === 0, `hook exits 0 with open-but-silent stdin (got code ${result.code})`);
  assert(
    result.elapsedMs < 1200,
    `hook exits within the stdin-guard CI-slack bound of 1200ms (elapsed ${result.elapsedMs}ms)`
  );
  assert(result.stdout === '', `no stdout emitted (got: ${JSON.stringify(result.stdout)})`);
  assert(readEvents(cwd).length === 0, 'no spawn_start event emitted (no real payload arrived)');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// (b) normal-payload smoke: existing behavior still works after the guarded
// read swap - a real Task spawn payload still emits spawn_start.
// ---------------------------------------------------------------------------
function testNormalPayloadSmoke() {
  console.log('\n[b] normal-payload smoke: spawn_start still emitted');
  const cwd = makeTmpProject();
  const payload = {
    cwd,
    session_id: 'sg-smoke-001',
    tool_name: 'Task',
    tool_input: { subagent_type: 'engineer', run_in_background: true },
  };
  const res = spawnSync('node', [hookPath], {
    input: JSON.stringify(payload), cwd, timeout: 10000, encoding: 'utf8',
  });
  assert(res.status === 0, `hook exits 0 (got status ${res.status})`);
  const events = readEvents(cwd);
  assert(events.length === 1, `exactly one spawn_start event appended (got ${events.length})`);
  if (events.length >= 1) {
    assert(events[0].event === 'spawn_start', `event === "spawn_start" (got: ${events[0].event})`);
    assert(events[0].agent === 'engineer', `agent === "engineer" (got: ${events[0].agent})`);
    assert((events[0].data || {}).source === 'hook', 'data.source === "hook"');
  }
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------
async function main() {
  await testOpenSilentStdinBoundedExit();
  testNormalPayloadSmoke();

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
