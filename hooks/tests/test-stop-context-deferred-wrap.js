#!/usr/bin/env node
/**
 * Smoke tests: stop-context.js deferred-wrap behavior (U2 + U3).
 *
 * Sub-tests:
 *   (a) wrap/lock DIRECTORY present (normal write path) -> context.md NOT
 *       written + exactly one spillover record appended to
 *       .agentic/wrap/deferred-activity.jsonl (valid JSON, correct shape).
 *   (b) lock absent -> context.md written as today (no regression); no
 *       spillover file created.
 *   (c) .agentic/wrap/last-wrap contains the current session_id -> no marker staged
 *       (this session already wrapped).
 *   (d) substantive payload (an Edit tool_use in the transcript) + lock absent
 *       + no last-wrap -> per-session pending-<session_id>.json marker
 *       staged with valid JSON and the NORMATIVE schema_version 3 fields.
 *   (e) read-only/clean session (transcript with only a Read tool_use, clean
 *       tree, no .last-wrap) -> no marker staged.
 *   (f) wrap/lock present on the /wrap-coexistence path (existing context.md
 *       authored by /wrap) -> /wrap content preserved (NOT overwritten) + one
 *       spillover record appended.
 *
 * Fake-HOME isolation is used throughout so the test never touches the real
 * ~/.agentic/. The tmp project dir is intentionally NOT a git repo, so the
 * hook's `git status` yields no uncommitted files - substantive activity in
 * (d)/(e) is driven entirely by the transcript tool_use blocks.
 *
 * Run with: node hooks/tests/test-stop-context-deferred-wrap.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');
const lib = require('../lib/wrap-marker.js');

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

/**
 * Run the hook with a custom transcript. transcript defaults to [] (no activity).
 * Fake-HOME isolation via env.HOME so the real ~/.agentic/ is never touched.
 */
function runHook(projectDir, fakeHome, sessionId, transcript) {
  const payload = JSON.stringify({
    cwd: projectDir,
    session_id: sessionId,
    transcript: Array.isArray(transcript) ? transcript : [],
  });
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

// .agentic/wrap/lock is a DIRECTORY (atomic mkdir lock) - create it as such.
function makeWrapLock(projectDir) {
  const lockDir = lib.wrapLockPath(projectDir);
  fs.mkdirSync(lockDir, { recursive: true });
}

// Write a flag-on config.json so stageWrapPending / touchHeartbeat fire.
// Required for tests that assert markers or heartbeats ARE created, since those
// paths are now gated on deferredDaemonEnabled(cwd).
function writeFlagOnConfig(projectDir) {
  const agenticDir = path.join(projectDir, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  fs.writeFileSync(
    path.join(agenticDir, 'config.json'),
    JSON.stringify({ deferred_wrap_daemon: true }),
    'utf8',
  );
}

// A transcript fragment with an Edit tool_use (substantive activity).
const EDIT_TRANSCRIPT = [
  {
    role: 'assistant',
    content: [
      { type: 'text', text: 'editing' },
      { type: 'tool_use', name: 'Edit', input: { file_path: '/Users/dev/project/src/app.js' } },
    ],
  },
];

// A transcript fragment with only a Read tool_use (read-only, non-substantive:
// Read paths ARE counted as paths_referenced, so to model a truly clean
// read-only session we use a transcript with no file paths and no user message).
const READONLY_TRANSCRIPT = [
  {
    role: 'assistant',
    content: [
      { type: 'tool_use', name: 'Bash', input: { command: 'echo hi' } },
    ],
  },
];

// ---------------------------------------------------------------------------
// (a) wrap.lock present (normal path) -> context.md NOT written + one spillover
// ---------------------------------------------------------------------------
console.log('\n[a] wrap/lock present (normal path): context.md skipped + spillover appended');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-a-');
  makeWrapLock(projectDir);
  const contextPath = path.join(agenticDir, 'context.md');
  const spilloverPath = lib.stopDeferredActivityPath(projectDir);

  try {
    runHook(projectDir, fakeHome, 'sess-a', EDIT_TRANSCRIPT);
  } catch (err) {
    assert(false, `hook must not throw when lock is held (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(!fs.existsSync(contextPath), 'context.md NOT written while wrap/lock held');
  assert(fs.existsSync(spilloverPath), 'spillover file created');
  if (fs.existsSync(spilloverPath)) {
    const lines = fs.readFileSync(spilloverPath, 'utf8').trim().split('\n').filter(Boolean);
    assert(lines.length === 1, `exactly one spillover record (got ${lines.length})`);
    let rec;
    try {
      rec = JSON.parse(lines[0]);
      assert(true, 'spillover record is valid JSON');
    } catch (e) {
      assert(false, `spillover record is valid JSON (parse error: ${e.message})`);
    }
    if (rec) {
      assert(rec.schema_version === 1, 'spillover schema_version === 1');
      assert(rec.session_id === 'sess-a', `spillover session_id === 'sess-a' (got ${rec.session_id})`);
      assert(Array.isArray(rec.recent_focus), 'recent_focus is an array');
      assert(Array.isArray(rec.paths_referenced), 'paths_referenced is an array');
      assert(Array.isArray(rec.uncommitted), 'uncommitted is an array');
      assert(Array.isArray(rec.tools_used), 'tools_used is an array');
      assert(rec.paths_referenced.includes('/Users/dev/project/src/app.js'),
        'paths_referenced captured the edited file');
      assert(rec.tools_used.includes('Edit'), 'tools_used captured Edit');
    }
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (b) lock absent -> context.md written (no regression); no spillover
// ---------------------------------------------------------------------------
console.log('\n[b] lock absent: context.md written, no spillover');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-b-');
  const contextPath = path.join(agenticDir, 'context.md');
  const spilloverPath = lib.stopDeferredActivityPath(projectDir);

  try {
    runHook(projectDir, fakeHome, 'sess-b', EDIT_TRANSCRIPT);
  } catch (err) {
    assert(false, `hook must not throw with lock absent (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(fs.existsSync(contextPath), 'context.md written when lock absent');
  if (fs.existsSync(contextPath)) {
    const c = fs.readFileSync(contextPath, 'utf8');
    assert(c.startsWith('# Session Context'), 'context.md has expected header');
  }
  assert(!fs.existsSync(spilloverPath), 'no spillover file created when lock absent');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (c) .last-wrap == current session_id -> no marker staged
// ---------------------------------------------------------------------------
console.log('\n[c] last-wrap == current session_id: no marker staged');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-c-');
  // last-wrap names the CURRENT session - it already wrapped.
  const lastWrapP = lib.lastWrapPath(projectDir);
  fs.mkdirSync(path.dirname(lastWrapP), { recursive: true });
  fs.writeFileSync(lastWrapP, 'sess-c\n', 'utf8');
  const markerPath = lib.markerPath(projectDir, 'sess-c');

  try {
    runHook(projectDir, fakeHome, 'sess-c', EDIT_TRANSCRIPT);
  } catch (err) {
    assert(false, `hook must not throw (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(!fs.existsSync(markerPath),
    'per-session marker NOT staged when current session already wrapped');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (d) substantive payload (Edit) + lock absent + no last-wrap -> marker staged
// ---------------------------------------------------------------------------
console.log('\n[d] substantive payload: per-session pending marker staged (schema_version 3)');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-d-');
  const markerPath = lib.markerPath(projectDir, 'sess-d');
  // Flag-on config required: stageWrapPending is now gated on deferredDaemonEnabled(cwd).
  writeFlagOnConfig(projectDir);

  try {
    runHook(projectDir, fakeHome, 'sess-d', EDIT_TRANSCRIPT);
  } catch (err) {
    assert(false, `hook must not throw (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(fs.existsSync(markerPath), 'per-session marker staged for substantive session');
  if (fs.existsSync(markerPath)) {
    let m;
    try {
      m = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
      assert(true, 'per-session marker is valid JSON');
    } catch (e) {
      assert(false, `per-session marker is valid JSON (parse error: ${e.message})`);
    }
    if (m) {
      assert(m.schema_version === 3, `marker schema_version === 3 (got ${m.schema_version})`);
      assert(m.session_id === 'sess-d', `marker session_id === 'sess-d' (got ${m.session_id})`);
      assert(m.status === 'pending', `marker status === 'pending' (got ${m.status})`);
      assert(m.claimed_by === null, 'marker claimed_by === null');
      assert(m.claimed_kind === null, 'marker claimed_kind === null');
      assert(m.claimed_at === null, 'marker claimed_at === null');
      assert(m.attempts === 0, 'marker attempts === 0');
      assert(m.project_root === projectDir, 'marker project_root === project dir');
      assert(m.last_error === null, 'marker last_error === null');
      assert(!('branch' in m), 'marker has no branch field (dropped in v3)');
      assert(!('head_sha' in m), 'marker has no head_sha field (dropped in v3)');
      assert(typeof m.staged_at === 'string' && m.staged_at.length > 0, 'marker staged_at is a non-empty string');
    }
  }
  // No leftover tmp file from the atomic write.
  assert(!fs.existsSync(markerPath + '.tmp'), 'no leftover pending-sess-d.json.tmp');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (e) read-only/clean session -> no marker staged
// ---------------------------------------------------------------------------
console.log('\n[e] read-only/clean session: no marker staged');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-e-');
  const markerPath = lib.markerPath(projectDir, 'sess-e');

  try {
    // READONLY_TRANSCRIPT: a Bash `echo hi` with no file paths, no user message,
    // clean (non-git) tree -> zero uncommitted, zero paths, zero recent-focus.
    runHook(projectDir, fakeHome, 'sess-e', READONLY_TRANSCRIPT);
  } catch (err) {
    assert(false, `hook must not throw (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(!fs.existsSync(markerPath),
    'per-session marker NOT staged for a non-substantive session');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (f) wrap.lock present on /wrap-coexistence path -> /wrap content preserved
// ---------------------------------------------------------------------------
console.log('\n[f] wrap/lock present (/wrap-coexistence path): /wrap content preserved + spillover');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-f-');
  makeWrapLock(projectDir);
  const contextPath = path.join(agenticDir, 'context.md');
  const spilloverPath = lib.stopDeferredActivityPath(projectDir);

  // Pre-seed a /wrap-authored context.md (pinned header prefix).
  const wrapBody = '# Session Context\n*Written by /wrap on 2026-06-11. Preserved by Stop hook. Not committed to git.*\n\n## Recent Focus\n- prior wrap content\n';
  fs.writeFileSync(contextPath, wrapBody, 'utf8');

  try {
    runHook(projectDir, fakeHome, 'sess-f', EDIT_TRANSCRIPT);
  } catch (err) {
    assert(false, `hook must not throw on coexistence path with lock held (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  const after = fs.readFileSync(contextPath, 'utf8');
  assert(after === wrapBody, '/wrap-authored context.md left untouched while lock held');
  assert(fs.existsSync(spilloverPath), 'spillover appended on coexistence path');
  if (fs.existsSync(spilloverPath)) {
    const lines = fs.readFileSync(spilloverPath, 'utf8').trim().split('\n').filter(Boolean);
    assert(lines.length === 1, `exactly one spillover record on coexistence path (got ${lines.length})`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (g) per-turn heartbeat touch (U1 liveness signal)
// ---------------------------------------------------------------------------
console.log('\n[g] per-turn heartbeat: a substantive Stop touches .agentic/wrap/heartbeats/<session_id>');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-g-');
  const heartbeatPath = lib.heartbeatPath(projectDir, 'sess-g');
  // Flag-on config required: touchHeartbeat is now gated on deferredDaemonEnabled(cwd).
  writeFlagOnConfig(projectDir);

  try {
    runHook(projectDir, fakeHome, 'sess-g', EDIT_TRANSCRIPT);
  } catch (err) {
    assert(false, `hook must not throw (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(fs.existsSync(heartbeatPath),
    'Stop hook touches this session heartbeat under wrap/heartbeats/ (daemon liveness signal)');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (h) per-session marker isolation: two distinct sessions -> two distinct markers
// ---------------------------------------------------------------------------
console.log('\n[h] per-session staging: two distinct sessions stage two distinct markers (no collision)');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-h-');
  const m1 = lib.markerPath(projectDir, 'sess-h1');
  const m2 = lib.markerPath(projectDir, 'sess-h2');
  // Flag-on config required: stageWrapPending is now gated on deferredDaemonEnabled(cwd).
  writeFlagOnConfig(projectDir);

  try {
    runHook(projectDir, fakeHome, 'sess-h1', EDIT_TRANSCRIPT);
    runHook(projectDir, fakeHome, 'sess-h2', EDIT_TRANSCRIPT);
  } catch (err) {
    assert(false, `hook must not throw (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(fs.existsSync(m1) && fs.existsSync(m2),
    'each session stages its own per-session marker');
  if (fs.existsSync(m1) && fs.existsSync(m2)) {
    const j1 = JSON.parse(fs.readFileSync(m1, 'utf8'));
    const j2 = JSON.parse(fs.readFileSync(m2, 'utf8'));
    assert(j1.session_id === 'sess-h1' && j2.session_id === 'sess-h2',
      'each marker records its own session_id (no cross-contamination)');
    assert(j1.status === 'pending' && j2.status === 'pending',
      'both markers staged as pending');
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (i) loop-guard (case 13, Stop-hook portion): AGENTIC_WRAP_DAEMON=1 -> no marker,
//     no heartbeat. The daemon's own headless /wrap-deferred run still fires Stop;
//     under the guard the Stop hook must NOT re-stage or re-touch.
// ---------------------------------------------------------------------------
console.log('\n[i] loop-guard: under AGENTIC_WRAP_DAEMON=1 the Stop hook stages no marker + touches no heartbeat');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-i-');
  const markerPath = lib.markerPath(projectDir, 'sess-i');
  const heartbeatPath = lib.heartbeatPath(projectDir, 'sess-i');

  const payload = JSON.stringify({
    cwd: projectDir, session_id: 'sess-i', transcript: EDIT_TRANSCRIPT,
  });
  try {
    execSync(`node "${hookScript}"`, {
      input: payload,
      encoding: 'utf8',
      env: { ...process.env, HOME: fakeHome, AGENTIC_WRAP_DAEMON: '1' },
      timeout: 10000,
      stdio: ['pipe', 'pipe', 'ignore'],
    });
  } catch (err) {
    assert(false, `hook must not throw under the guard (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(!fs.existsSync(markerPath),
    'no marker staged under the loop-guard (case 13)');
  assert(!fs.existsSync(heartbeatPath),
    'no heartbeat touched under the loop-guard (case 13)');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (j) flag-OFF: no config (default) -> ZERO markers + ZERO heartbeats across N turns;
//     context.md IS still written (gate must not break normal context writing).
// (k) flag-ON companion: with config flag true, markers + heartbeats DO appear.
//
// These cases ARE regression tests: they MUST fail against pre-fix code
// (where staging/heartbeat ran regardless of the flag) and pass after the fix.
// ---------------------------------------------------------------------------
console.log('\n[j] flag-OFF (no config): N turns produce zero pending markers, zero heartbeats; context.md written');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-j-');
  // NO config.json written - deferred_wrap_daemon defaults to false.
  const contextPath = path.join(agenticDir, 'context.md');
  const markerPath1 = lib.markerPath(projectDir, 'sess-j1');
  const markerPath2 = lib.markerPath(projectDir, 'sess-j2');
  const markerPath3 = lib.markerPath(projectDir, 'sess-j3');
  const hb1 = lib.heartbeatPath(projectDir, 'sess-j1');
  const hb2 = lib.heartbeatPath(projectDir, 'sess-j2');
  const hb3 = lib.heartbeatPath(projectDir, 'sess-j3');

  try {
    runHook(projectDir, fakeHome, 'sess-j1', EDIT_TRANSCRIPT);
    runHook(projectDir, fakeHome, 'sess-j2', EDIT_TRANSCRIPT);
    runHook(projectDir, fakeHome, 'sess-j3', EDIT_TRANSCRIPT);
  } catch (err) {
    assert(false, `hook must not throw with flag off (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  // ZERO markers staged when flag is off.
  assert(!fs.existsSync(markerPath1), 'flag-OFF: no marker staged for sess-j1');
  assert(!fs.existsSync(markerPath2), 'flag-OFF: no marker staged for sess-j2');
  assert(!fs.existsSync(markerPath3), 'flag-OFF: no marker staged for sess-j3');

  // ZERO heartbeats written when flag is off.
  assert(!fs.existsSync(hb1), 'flag-OFF: no heartbeat for sess-j1');
  assert(!fs.existsSync(hb2), 'flag-OFF: no heartbeat for sess-j2');
  assert(!fs.existsSync(hb3), 'flag-OFF: no heartbeat for sess-j3');

  // context.md STILL written (gate must not break normal context writing).
  assert(fs.existsSync(contextPath), 'flag-OFF: context.md IS still written');
  if (fs.existsSync(contextPath)) {
    const c = fs.readFileSync(contextPath, 'utf8');
    assert(c.startsWith('# Session Context'), 'flag-OFF: context.md has expected header');
  }
  cleanup(tmpDir);
}

console.log('\n[k] flag-ON (deferred_wrap_daemon:true): markers + heartbeats DO appear');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-dw-k-');
  // Flag-on config written.
  writeFlagOnConfig(projectDir);
  const markerPath = lib.markerPath(projectDir, 'sess-k');
  const hb = lib.heartbeatPath(projectDir, 'sess-k');

  try {
    runHook(projectDir, fakeHome, 'sess-k', EDIT_TRANSCRIPT);
  } catch (err) {
    assert(false, `hook must not throw with flag on (got: ${err.message})`);
    cleanup(tmpDir);
    process.exit(1);
  }

  assert(fs.existsSync(markerPath), 'flag-ON: marker staged for substantive session');
  assert(fs.existsSync(hb), 'flag-ON: heartbeat written for session');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (case 12 note) "non-Claude -> no marker staged" is NOT a Stop-hook behavior.
// ---------------------------------------------------------------------------
// Verification-gate case (12) ("non-Claude / no .claude-host sentinel -> no marker
// staged") is enforced at the `/wrap` Step 0a sentinel gate
// (`[ -f "$cwd/.agentic/wrap/claude-host" ]`), which is PROSE executed by the model -
// it is NOT a gate in this Node Stop hook. The Stop hook only ever runs on Claude
// Code in the first place; it stages a marker on any substantive, unlocked,
// not-already-wrapped session regardless of the sentinel (verified empirically:
// the marker is staged with no `.claude-host` file present). A Stop-hook-level
// "non-Claude" assertion would therefore assert behavior the hook does not have.
// Coverage for the sentinel gate lives in the `/wrap` Step 0a contract and the
// SessionStart self-heal path (ensureClaudeHost, covered in
// test-wrap-marker-reclaim.js [20]); the structural extraction is checked in
// test-wrap-context-format-golden.js. Recording the gap here rather than skipping
// it silently.

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
