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

const hookScript = path.resolve(__dirname, '..', 'stop-context.js');
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

function runHook(projectDir, fakeHome, sessionId, cadence) {
  const payload = JSON.stringify({
    cwd: projectDir,
    session_id: sessionId,
    transcript: [],
  });
  // cadence is optional: omitted -> the hook's fallback dispatch
  // (markInterrupted, today's pre-existing behavior); pass 'turn' to exercise
  // the --cadence=turn refreshLiveness dispatch (hooks/lib/state-mark.js).
  const cadenceFlag = cadence ? ` --cadence=${cadence}` : '';
  // stdio: ['pipe', 'pipe', 'ignore'] silences stray git stderr ("fatal: not a
  // git repository") that appears when the tmp dir is not a git repo.
  execSync(`node "${hookScript}"${cadenceFlag}`, {
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
  assert(contextContent.includes('ds-identity init'), 'identity nudge appended to context.md');

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
// Sub-test 5: No orphan .tmp files after a normal hook run (#262 regression),
// and (DS-109) the catch-path cleanup is scoped to our own pid-suffixed tmp
// only - a peer's in-flight staging file at the same base name must survive.
// ---------------------------------------------------------------------------
console.log('\n[5] No orphan tmp files: loop-state atomic write leaves no tmp.<pid> on success or failure; peer tmp survives');
{
  // A tmp file this write path can leave behind is always named
  // `<file>.tmp.<pid>` post-DS-109 - match that shape, not a bare `.tmp`
  // suffix.
  const isOwnStyleTmp = (f) => /\.tmp\.\d+$/.test(f);

  // Three scenarios in one sub-test:
  // (a) normal success path: active loop-state -> atomic write -> rename -> no tmp
  // (b) failure path, own tmp: loop-state.json is corrupt JSON -> catch fires
  //     early, no tmp ever written by US -> catch cleanup is a no-op.
  // (c) DS-109 regression: a PEER's in-flight staging file - at the legacy
  //     fixed name, or at a different pid's suffixed name - must survive our
  //     unrelated catch-path cleanup untouched.
  //
  // Both invocations pass --cadence=turn (this hook's install.sh-wired
  // default) so the atomic write path exercised here is refreshLiveness, not
  // markInterrupted. Scenario (a)'s fixture session_id ('test-session-uuid')
  // deliberately MATCHES the sessionId passed to runHook: under
  // refreshLiveness's POSITIVE-match ownership predicate (hooks/lib/state-mark.js),
  // an absent/differing session_id would skip the write entirely, making this
  // scenario vacuous (it would pass trivially with no write ever attempted).

  // --- (a) success path ---
  const { tmpDir, fakeHome, projectDir, agenticDir, identityDir } = makeTmp('ae-stop-t5a-');
  fs.writeFileSync(path.join(identityDir, 'identity.yml'), STUB_IDENTITY, { mode: 0o600 });
  // Active loop-state triggers the atomic write path.
  fs.writeFileSync(
    path.join(agenticDir, 'loop-state.json'),
    JSON.stringify({ status: 'active', session_id: 'test-session-uuid' }),
  );
  try { runHook(projectDir, fakeHome, 'test-session-uuid', 'turn'); } catch (_) {}
  const tmpFilesA = fs.readdirSync(agenticDir).filter(isOwnStyleTmp);
  assert(tmpFilesA.length === 0,
    `(a) no tmp.<pid> in .agentic/ after successful atomic write (found: ${tmpFilesA.join(', ') || 'none'})`);
  cleanup(tmpDir);

  // --- (b) failure path, no tmp ever created by us: corrupt loop-state ->
  //     JSON.parse throws before tmpPath is assigned -> catch cleanup is a
  //     no-op (nothing of ours to remove).
  const { tmpDir: tmpDir2, fakeHome: fakeHome2, projectDir: proj2,
    agenticDir: ag2, identityDir: id2 } = makeTmp('ae-stop-t5b-');
  fs.writeFileSync(path.join(id2, 'identity.yml'), STUB_IDENTITY, { mode: 0o600 });
  // Corrupt loop-state.json -> JSON.parse throws -> catch block fires.
  const loopStatePath2 = path.join(ag2, 'loop-state.json');
  fs.writeFileSync(loopStatePath2, '{ bad json !!');
  try { runHook(proj2, fakeHome2, 'test-session-uuid', 'turn'); } catch (_) {}
  const tmpFilesB = fs.readdirSync(ag2).filter(isOwnStyleTmp);
  assert(tmpFilesB.length === 0,
    `(b) no own-style tmp.<pid> remains after a no-write failure (found: ${tmpFilesB.join(', ') || 'none'})`);
  cleanup(tmpDir2);

  // --- (c) DS-109: a peer's in-flight staging file must survive our
  //     unrelated catch-path failure, whether it uses the legacy fixed name
  //     or a different pid's suffixed name.
  const { tmpDir: tmpDir3, fakeHome: fakeHome3, projectDir: proj3,
    agenticDir: ag3, identityDir: id3 } = makeTmp('ae-stop-t5c-');
  fs.writeFileSync(path.join(id3, 'identity.yml'), STUB_IDENTITY, { mode: 0o600 });
  const loopStatePath3 = path.join(ag3, 'loop-state.json');
  fs.writeFileSync(loopStatePath3, '{ bad json !!');
  const legacyFixedNamePeerTmp = loopStatePath3 + '.tmp';
  const foreignPid = String(process.pid) + '9'; // guaranteed not our own pid
  const peerTmp = loopStatePath3 + '.tmp.' + foreignPid;
  fs.writeFileSync(legacyFixedNamePeerTmp, 'PEER_INFLIGHT_DATA_LEGACY_NAME');
  fs.writeFileSync(peerTmp, 'PEER_INFLIGHT_DATA_PID_SUFFIXED');
  try { runHook(proj3, fakeHome3, 'test-session-uuid', 'turn'); } catch (_) {}
  assert(
    fs.existsSync(legacyFixedNamePeerTmp) && fs.readFileSync(legacyFixedNamePeerTmp, 'utf8') === 'PEER_INFLIGHT_DATA_LEGACY_NAME',
    'DS-109: a peer\'s legacy fixed-name .tmp file survives our unrelated catch-path cleanup, untouched'
  );
  assert(
    fs.existsSync(peerTmp) && fs.readFileSync(peerTmp, 'utf8') === 'PEER_INFLIGHT_DATA_PID_SUFFIXED',
    'DS-109: a peer\'s pid-suffixed .tmp.<otherpid> file survives our unrelated catch-path cleanup, untouched'
  );
  cleanup(tmpDir3);
}

// ---------------------------------------------------------------------------
// Sub-test 6: M3 — health file written on full hook run (integration)
// ---------------------------------------------------------------------------
console.log('\n[6] M3 integration: health file written and valid after full hook run');
{
  // Full run with STUB_IDENTITY and a spawn_complete event.
  // Asserts: (a) hook exits 0, (b) .telemetry-health.json exists and is valid
  // JSON, (c) targets.writeSessionLogGlobal present with failures === 0 and
  // populated last_success — proves recordHealth fired and flushHealth ran at
  // the real exit with cwd in scope.
  const { tmpDir, fakeHome, projectDir, agenticDir, identityDir } = makeTmp('ae-stop-t6-');

  fs.writeFileSync(path.join(identityDir, 'identity.yml'), STUB_IDENTITY, { mode: 0o600 });
  fs.writeFileSync(path.join(agenticDir, 'events.jsonl'), STUB_EVENT + '\n');

  try {
    runHook(projectDir, fakeHome, 'test-session-uuid');
  } catch (err) {
    console.error('  FAIL: hook execution threw:', err.message);
    cleanup(tmpDir);
    process.exit(1);
  }

  const healthPath = path.join(agenticDir, '.telemetry-health.json');
  assert(fs.existsSync(healthPath), '.telemetry-health.json exists after full hook run');
  if (fs.existsSync(healthPath)) {
    let parsed;
    try {
      parsed = JSON.parse(fs.readFileSync(healthPath, 'utf8'));
      assert(true, '.telemetry-health.json is valid JSON');
    } catch (e) {
      assert(false, `.telemetry-health.json is valid JSON (parse error: ${e.message})`);
      parsed = null;
    }
    if (parsed) {
      assert(parsed.targets && typeof parsed.targets === 'object',
        'targets object present in health file');
      // writeSessionLogGlobal fires on the confirmed-identity path (STUB_IDENTITY).
      const wslg = parsed.targets && parsed.targets.writeSessionLogGlobal;
      assert(wslg !== undefined, 'targets.writeSessionLogGlobal present');
      if (wslg !== undefined) {
        assert(wslg.failures === 0,
          `writeSessionLogGlobal.failures === 0 (got: ${wslg.failures})`);
        assert(typeof wslg.last_success === 'string' && wslg.last_success.length > 0,
          `writeSessionLogGlobal.last_success populated (got: ${wslg.last_success})`);
      }
    }
  }
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
