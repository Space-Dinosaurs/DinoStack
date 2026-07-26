#!/usr/bin/env node
/**
 * Regression tests: hooks/session-end-wrap.js's new markInterrupted step
 * (hooks/lib/state-mark.js), added so the terminal loop-state/batch-state
 * interrupted-mark lives on a once-per-session hook rather than the
 * per-turn Stop hook.
 *
 * Covers:
 *   (1) markInterrupted fires on each TERMINAL_REASONS value.
 *   (2) markInterrupted does NOT fire on reason:"resume".
 *   (3) markInterrupted fires even with deferred_wrap_daemon:false (default -
 *       i.e. it is NOT gated on that toggle, unlike finalizeReady above it).
 *   (4/AC7b) THE regression test: a loop-state.json owned by session A with
 *       last_updated = T where T is MORE than 10 minutes old. A terminal
 *       SessionEnd must set status->interrupted and interrupted_at, while
 *       leaving last_updated EXACTLY T (unchanged) - Contract A's
 *       resume-staleness gate reads only last_updated with no status
 *       exemption, so touching it here would make a freshly-interrupted loop
 *       look "recently live" for the full 10-minute window.
 *
 * Run with: node hooks/tests/test-session-end-wrap-state-mark.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

const hookScript = path.resolve(__dirname, '..', 'session-end-wrap.js');
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

// realpath so state-mark.js's traversal check (path.resolve(cwd) === cwd)
// accepts the dir on macOS (/tmp is a symlink to /private/tmp there).
function makeProject(prefix) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  const projectDir = path.join(base, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  return { base, projectDir, agenticDir };
}

function cleanup(base) {
  try { fs.rmSync(base, { recursive: true, force: true }); } catch (_) {}
}

function writeLoopState(agenticDir, obj) {
  fs.writeFileSync(path.join(agenticDir, 'loop-state.json'), JSON.stringify(obj, null, 2));
}

function readLoopState(agenticDir) {
  return JSON.parse(fs.readFileSync(path.join(agenticDir, 'loop-state.json'), 'utf8'));
}

function runHook(projectDir, rawStdin) {
  try {
    execSync(`node "${hookScript}"`, {
      input: rawStdin,
      encoding: 'utf8',
      cwd: projectDir,
      timeout: 10000,
      stdio: ['pipe', 'pipe', 'ignore'],
    });
    return 0;
  } catch (err) {
    return (err && typeof err.status === 'number') ? err.status : 1;
  }
}

function payload(obj) {
  return JSON.stringify(obj);
}

const TERMINAL_REASONS = ['clear', 'logout', 'prompt_input_exit', 'bypass_permissions_disabled', 'other'];

// ---------------------------------------------------------------------------
// (1) markInterrupted fires on each TERMINAL_REASONS value
// ---------------------------------------------------------------------------
console.log('\n[1] markInterrupted fires on each terminal reason');
{
  for (const reason of TERMINAL_REASONS) {
    const { base, projectDir, agenticDir } = makeProject('ae-se-sm-term-');
    const SID = 'aaaaaaaa-0000-0000-0000-000000000001';
    writeLoopState(agenticDir, { status: 'active', session_id: SID });

    const code = runHook(projectDir, payload({
      session_id: SID, cwd: projectDir, hook_event_name: 'SessionEnd', reason,
    }));
    assert(code === 0, `hook exits 0 on reason='${reason}'`);
    const state = readLoopState(agenticDir);
    assert(state.status === 'interrupted', `reason='${reason}' marks loop-state interrupted (got: ${state.status})`);
    assert(state.interrupt_reason === 'unknown', `reason='${reason}' sets interrupt_reason='unknown'`);
    cleanup(base);
  }
}

// ---------------------------------------------------------------------------
// (2) markInterrupted does NOT fire on reason:"resume"
// ---------------------------------------------------------------------------
console.log('\n[2] markInterrupted does NOT fire on reason=resume');
{
  const { base, projectDir, agenticDir } = makeProject('ae-se-sm-resume-');
  const SID = 'aaaaaaaa-0000-0000-0000-000000000002';
  writeLoopState(agenticDir, { status: 'active', session_id: SID });

  const code = runHook(projectDir, payload({
    session_id: SID, cwd: projectDir, hook_event_name: 'SessionEnd', reason: 'resume',
  }));
  assert(code === 0, 'hook exits 0 on reason=resume');
  const state = readLoopState(agenticDir);
  assert(state.status === 'active', `reason=resume leaves loop-state active (got: ${state.status})`);
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (3) markInterrupted fires even with deferred_wrap_daemon:false (default) -
//     it is NOT gated on that toggle, unlike finalizeReady.
// ---------------------------------------------------------------------------
console.log('\n[3] markInterrupted fires with deferred_wrap_daemon:false (not gated on the toggle)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-se-sm-flagoff-');
  const SID = 'aaaaaaaa-0000-0000-0000-000000000003';
  writeLoopState(agenticDir, { status: 'active', session_id: SID });
  fs.writeFileSync(
    path.join(agenticDir, 'config.json'),
    JSON.stringify({ deferred_wrap_daemon: false }),
    'utf8',
  );

  const code = runHook(projectDir, payload({
    session_id: SID, cwd: projectDir, hook_event_name: 'SessionEnd', reason: 'logout',
  }));
  assert(code === 0, 'hook exits 0 with deferred_wrap_daemon:false');
  const state = readLoopState(agenticDir);
  assert(state.status === 'interrupted',
    `deferred_wrap_daemon:false still marks loop-state interrupted (got: ${state.status})`);
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (4/AC7b) THE regression test: last_updated is NEVER touched, even when it
// is more than 10 minutes stale at the time of the terminal SessionEnd.
// ---------------------------------------------------------------------------
console.log('\n[4/AC7b] last_updated stays EXACTLY T (>10 min stale) after a terminal SessionEnd');
{
  const { base, projectDir, agenticDir } = makeProject('ae-se-sm-ac7b-');
  const SID = 'aaaaaaaa-0000-0000-0000-000000000004';
  const T = new Date(Date.now() - 11 * 60 * 1000).toISOString(); // 11 min ago
  writeLoopState(agenticDir, { status: 'active', session_id: SID, last_updated: T });

  const code = runHook(projectDir, payload({
    session_id: SID, cwd: projectDir, hook_event_name: 'SessionEnd', reason: 'other',
  }));
  assert(code === 0, 'hook exits 0');
  const state = readLoopState(agenticDir);
  assert(state.status === 'interrupted', `status -> interrupted (got: ${state.status})`);
  assert(typeof state.interrupted_at === 'string' && state.interrupted_at.length > 0,
    `interrupted_at is populated (got: ${state.interrupted_at})`);
  assert(state.last_updated === T,
    `last_updated stays EXACTLY the pre-existing stale value (expected: ${T}, got: ${state.last_updated})`);
  cleanup(base);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
