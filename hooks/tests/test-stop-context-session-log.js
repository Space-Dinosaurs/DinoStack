#!/usr/bin/env node
/**
 * Smoke tests: stop-context.js session-log dual-write.
 *
 * Sub-tests:
 *   1. Happy path: identity present + events.jsonl with one spawn_complete ->
 *      session-log file written with correct shape.
 *   2. Missing identity: ~/.agentic/identity.yml absent -> hook runs without
 *      throwing; session-log file NOT written; identity nudge appended to
 *      .agentic/context.md; sentinel ~/.agentic/.identity-nudged created.
 *   3. Empty events.jsonl: identity present but events.jsonl empty -> session-log
 *      line written with by_agent: {} and spawn_count: 0.
 *   4. Write failure (silent-fail): session-log dir is a file (unwriteable) ->
 *      hook does NOT throw; other writes (context.md) still complete.
 *
 * Run with: node hooks/tests/test-stop-context-session-log.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const hookScript = path.resolve(__dirname, '..', 'stop.d', '010-stop-context.js');
if (!fs.existsSync(hookScript)) {
  console.error(`FAIL: hook not found at ${hookScript}`);
  process.exit(1);
}

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

function runHook(projectDir, fakeHome, sessionId) {
  const payload = JSON.stringify({
    cwd: projectDir,
    session_id: sessionId,
    transcript: [],
  });
  // stdio: ['pipe', 'pipe', 'ignore'] silences stray git stderr ("fatal: not a
  // git repository") that appears when the tmp dir is not a git repo.
  execSync(`node "${hookScript}"`, {
    input: payload,
    encoding: 'utf8',
    env: { ...process.env, HOME: fakeHome },
    timeout: 10000,
    stdio: ['pipe', 'pipe', 'ignore'],
  });
}

function makeTmp(prefix) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const fakeHome = path.join(tmpDir, 'home');
  const projectDir = path.join(tmpDir, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  const identityDir = path.join(fakeHome, '.agentic');
  fs.mkdirSync(fakeHome, { recursive: true });
  fs.mkdirSync(projectDir, { recursive: true });
  fs.mkdirSync(agenticDir, { recursive: true });
  fs.mkdirSync(identityDir, { recursive: true });
  return { tmpDir, fakeHome, projectDir, agenticDir, identityDir };
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
}

const STUB_IDENTITY = 'developer_id: testdev\ncreated_at: 2026-01-01T00:00:00Z\n';
const STUB_EVENT = JSON.stringify({
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

// ---------------------------------------------------------------------------
// Sub-test 1: Happy path
// ---------------------------------------------------------------------------
console.log('\n[1] Happy path: identity present, events.jsonl with spawn_complete');
{
  const { tmpDir, fakeHome, projectDir, agenticDir, identityDir } = makeTmp('ae-stop-t1-');
  const sessionLogDir = path.join(agenticDir, 'session-log');

  fs.writeFileSync(path.join(identityDir, 'identity.yml'), STUB_IDENTITY, { mode: 0o600 });
  fs.writeFileSync(path.join(agenticDir, 'events.jsonl'), STUB_EVENT + '\n');

  try {
    runHook(projectDir, fakeHome, 'test-session-uuid');
  } catch (err) {
    console.error('  FAIL: hook execution threw:', err.message);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(fs.existsSync(sessionLogDir), 'session-log dir created');
  const logFile = path.join(sessionLogDir, 'testdev.jsonl');
  assert(fs.existsSync(logFile), 'testdev.jsonl written');
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
      assert(obj.developer_id === 'testdev', `developer_id === 'testdev' (got: ${obj.developer_id})`);
      assert(obj.event === 'session_total', `event === 'session_total' (got: ${obj.event})`);
      assert(obj.phase === 'session_end', `phase === 'session_end' (got: ${obj.phase})`);
      assert(obj.data && typeof obj.data.tokens === 'object', 'data.tokens is an object');
      assert(obj.project_slug === path.basename(projectDir), `project_slug === '${path.basename(projectDir)}'`);
    }
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Sub-test 2: Missing identity file
// ---------------------------------------------------------------------------
console.log('\n[2] Missing identity: no ~/.agentic/identity.yml');
{
  const { tmpDir, fakeHome, projectDir, agenticDir, identityDir } = makeTmp('ae-stop-t2-');
  const sessionLogDir = path.join(agenticDir, 'session-log');

  // Do NOT write identity.yml - that is the point of this test
  fs.writeFileSync(path.join(agenticDir, 'events.jsonl'), STUB_EVENT + '\n');

  try {
    runHook(projectDir, fakeHome, 'test-session-uuid');
  } catch (err) {
    assert(false, `hook must not throw when identity is absent (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(!fs.existsSync(sessionLogDir) || fs.readdirSync(sessionLogDir).length === 0,
    'session-log NOT written when identity is absent');

  // Nudge appended to context.md
  const contextPath = path.join(agenticDir, 'context.md');
  let contextContent = '';
  try { contextContent = fs.readFileSync(contextPath, 'utf8'); } catch (_) {}
  assert(contextContent.includes('agentic-identity init'), 'identity nudge appended to context.md');

  // Sentinel created
  const sentinelPath = path.join(fakeHome, '.agentic', '.identity-nudged');
  assert(fs.existsSync(sentinelPath), 'identity-nudged sentinel created at ~/.agentic/.identity-nudged');

  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Sub-test 3: Empty events.jsonl
// ---------------------------------------------------------------------------
console.log('\n[3] Empty events.jsonl: identity present, events.jsonl empty');
{
  const { tmpDir, fakeHome, projectDir, agenticDir, identityDir } = makeTmp('ae-stop-t3-');
  const sessionLogDir = path.join(agenticDir, 'session-log');

  fs.writeFileSync(path.join(identityDir, 'identity.yml'), STUB_IDENTITY, { mode: 0o600 });
  fs.writeFileSync(path.join(agenticDir, 'events.jsonl'), '');

  try {
    runHook(projectDir, fakeHome, 'test-session-uuid');
  } catch (err) {
    console.error('  FAIL: hook execution threw:', err.message);
    cleanup(tmpDir);
    process.exit(1);
  }

  const logFile = path.join(sessionLogDir, 'testdev.jsonl');
  assert(fs.existsSync(logFile), 'session-log written even when events.jsonl is empty');
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
      assert(obj.data && typeof obj.data.by_agent === 'object'
        && Object.keys(obj.data.by_agent).length === 0, 'by_agent is empty object');
      assert(obj.data && obj.data.spawn_count === 0, 'spawn_count is 0');
    }
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Sub-test 4: Write failure (silent-fail)
// ---------------------------------------------------------------------------
console.log('\n[4] Write failure: session-log dir is an existing file (unwriteable path)');
{
  const { tmpDir, fakeHome, projectDir, agenticDir, identityDir } = makeTmp('ae-stop-t4-');

  fs.writeFileSync(path.join(identityDir, 'identity.yml'), STUB_IDENTITY, { mode: 0o600 });
  fs.writeFileSync(path.join(agenticDir, 'events.jsonl'), STUB_EVENT + '\n');

  // Create a regular file at the path the hook would use as a directory.
  // mkdirSync({recursive:true}) will fail or the appendFileSync will fail because
  // the parent "directory" is actually a file.
  const sessionLogDir = path.join(agenticDir, 'session-log');
  fs.writeFileSync(sessionLogDir, 'this is a file, not a dir');

  let threw = false;
  try {
    runHook(projectDir, fakeHome, 'test-session-uuid');
  } catch (_) {
    threw = true;
  }

  assert(!threw, 'hook does NOT throw when session-log write fails');

  // Other writes (context.md) should still complete
  const contextPath = path.join(agenticDir, 'context.md');
  assert(fs.existsSync(contextPath), 'context.md still written despite session-log failure');

  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
