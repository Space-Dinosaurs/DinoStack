#!/usr/bin/env node
/**
 * Smoke test: stop-context.js session-log dual-write.
 *
 * Stubs ~/.agentic/identity.yml and a minimal events.jsonl, pipes a
 * synthetic Stop hook payload into stop-context.js, then asserts:
 *   1. .agentic/session-log/<developer_id>.jsonl was written.
 *   2. The written line parses as valid JSON with correct shape.
 *   3. developer_id matches the stubbed identity.
 *   4. event === 'session_total' and phase === 'session_end'.
 *
 * Run with: node hooks/tests/test-stop-context-session-log.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

// ---------------------------------------------------------------------------
// Set up isolated temp directories
// ---------------------------------------------------------------------------
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-stop-test-'));
const fakeHome = path.join(tmpDir, 'home');
const projectDir = path.join(tmpDir, 'project');
const agenticDir = path.join(projectDir, '.agentic');
const sessionLogDir = path.join(agenticDir, 'session-log');
const identityDir = path.join(fakeHome, '.agentic');

fs.mkdirSync(fakeHome, { recursive: true });
fs.mkdirSync(projectDir, { recursive: true });
fs.mkdirSync(agenticDir, { recursive: true });
fs.mkdirSync(identityDir, { recursive: true });

// ---------------------------------------------------------------------------
// Write stub identity file
// ---------------------------------------------------------------------------
fs.writeFileSync(
  path.join(identityDir, 'identity.yml'),
  'developer_id: testdev\ncreated_at: 2026-01-01T00:00:00Z\n',
  { mode: 0o600 },
);

// ---------------------------------------------------------------------------
// Write stub events.jsonl with one spawn_complete event
// ---------------------------------------------------------------------------
const stubEvent = JSON.stringify({
  ts: '2026-05-28T10:00:00Z',
  phase: 'spawn',
  event: 'spawn_complete',
  agent: 'engineer',
  task_id: 'task-1',
  data: {
    session_uuid: 'test-session-uuid',
    wall_seconds: 120,
    tokens: { input: 1000, output: 500, cache_creation: 100, cache_read: 50 },
  },
});
fs.writeFileSync(path.join(agenticDir, 'events.jsonl'), stubEvent + '\n');

// ---------------------------------------------------------------------------
// Build the Stop hook payload
// ---------------------------------------------------------------------------
const payload = JSON.stringify({
  cwd: projectDir,
  session_id: 'test-session-uuid',
  transcript: [],
});

// ---------------------------------------------------------------------------
// Locate stop-context.js
// ---------------------------------------------------------------------------
const hookScript = path.resolve(__dirname, '..', 'stop-context.js');
if (!fs.existsSync(hookScript)) {
  console.error(`FAIL: hook not found at ${hookScript}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Run the hook with HOME overridden so it reads our stub identity
// ---------------------------------------------------------------------------
try {
  execSync(`node "${hookScript}"`, {
    input: payload,
    encoding: 'utf8',
    env: { ...process.env, HOME: fakeHome },
    timeout: 10000,
  });
} catch (err) {
  // Hook exits 0 even on error - execSync throws on non-zero; but hook always
  // exits 0. If it threw, something unexpected happened.
  console.error('FAIL: hook execution threw:', err.message);
  cleanup();
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Assertions
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

// Assertion 1: session-log directory was created
assert(fs.existsSync(sessionLogDir), `session-log dir created at ${sessionLogDir}`);

// Assertion 2: developer JSONL file exists
const logFile = path.join(sessionLogDir, 'testdev.jsonl');
assert(fs.existsSync(logFile), `testdev.jsonl written at ${logFile}`);

if (fs.existsSync(logFile)) {
  const raw = fs.readFileSync(logFile, 'utf8').trim();
  let obj;
  try {
    obj = JSON.parse(raw);
    assert(true, 'session-log line is valid JSON');
  } catch (e) {
    assert(false, `session-log line is valid JSON (parse error: ${e.message})`);
  }

  if (obj) {
    // Assertion 3: developer_id matches
    assert(obj.developer_id === 'testdev', `developer_id === 'testdev' (got: ${obj.developer_id})`);

    // Assertion 4: event shape
    assert(obj.event === 'session_total', `event === 'session_total' (got: ${obj.event})`);
    assert(obj.phase === 'session_end', `phase === 'session_end' (got: ${obj.phase})`);

    // Assertion 5: data block present with tokens
    assert(obj.data && typeof obj.data.tokens === 'object', 'data.tokens is an object');

    // Assertion 6: project_slug is set
    assert(obj.project_slug === path.basename(projectDir), `project_slug === '${path.basename(projectDir)}'`);
  }
}

// ---------------------------------------------------------------------------
// Cleanup and result
// ---------------------------------------------------------------------------
function cleanup() {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
}
cleanup();

console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
