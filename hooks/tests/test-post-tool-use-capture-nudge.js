#!/usr/bin/env node
/**
 * Unit tests: post-tool-use-capture-nudge.js PostToolUse(Task) in-session nudge.
 *
 * The hook is a stdin-driven CLI script (run() reads fd 0 and process.exit(0)s),
 * so each behavioral case drives the REAL hook as a subprocess with a controlled
 * payload on stdin and a temporary .agentic/ fixture, then asserts on the hook's
 * stdout (the hookSpecificOutput JSON) and the .capture-gap-surfaced tracker.
 *
 * In addition, a tmp-shim load (same technique as test-capture-gap.js's loader)
 * suppresses run() and re-anchors the relative ./lib/capture-gap.js require to an
 * absolute path, proving the hook's lib require resolves from /tmp - the
 * fragility guard mirrors test-capture-gap.js so a changed require form fails loud.
 *
 * Test cases:
 *   1. fires-when-worthy-event:       debugger spawn_complete -> additionalContext emitted
 *   2. dedup-suppresses-repeat:       second identical spawn -> no second emit
 *   3. no-fire-when-no-worthy-event:  empty events.jsonl -> no emit
 *   4. no-fire-when-wrong-tool:       tool_name is a non-spawn tool (Bash) -> no emit
 *   5. no-fire-when-not-async-launched: status !== "async_launched" -> no emit
 *   6. soft-fail-on-malformed-stdin:  non-JSON stdin -> exit 0, no emit, no throw
 *   7. residualOnly-wording:          unrelated guardrail -> residual nudge text
 *   8. fires-when-tool-name-Agent:    REGRESSION (CC Task->Agent rename) -
 *                                     tool_name "Agent" -> nudge fires. Under the
 *                                     old `!== 'Task'` guard this early-exited
 *                                     and the nudge was silently disabled.
 *
 * Run with: node hooks/tests/test-post-tool-use-capture-nudge.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync, spawnSync } = require('child_process');

const hookPath = path.resolve(__dirname, '..', 'post-tool-use-capture-nudge.js');

// ---------------------------------------------------------------------------
// Tmp-shim load (mirrors test-capture-gap.js): suppress run(), re-anchor the
// relative ./lib/capture-gap.js require to an absolute path so the /tmp shim can
// resolve it. We do not export helpers (the hook's surface is run() over stdin);
// this load only proves the require rewrite + fragility guard hold.
// ---------------------------------------------------------------------------
const hookSource = fs.readFileSync(hookPath, 'utf8');
const libCaptureGapAbs = path.resolve(__dirname, '..', 'lib', 'capture-gap.js');
const libSkillDetectorAbs = path.resolve(__dirname, '..', 'lib', 'skill-candidate-detector.js');
const shimmedSource = hookSource
  // Suppress the trailing bare run() call so requiring the shim does not read stdin.
  .replace(/^run\(\);\s*$/m, '// test shim: run() suppressed')
  // Re-anchor relative lib requires to absolute paths so the /tmp shim can resolve them.
  .replace(
    /require\(['"]\.\/lib\/capture-gap\.js['"]\)/,
    `require(${JSON.stringify(libCaptureGapAbs)})`
  )
  .replace(
    /require\(['"]\.\/lib\/skill-candidate-detector\.js['"]\)/,
    `require(${JSON.stringify(libSkillDetectorAbs)})`
  );

// Fail loud if any relative ./lib/ require survived the re-anchor (require text changed form).
if (/require\(['"]\.\/lib\//.test(shimmedSource)) {
  console.error(
    '  FATAL: a relative ./lib/ require survived the shim re-anchor - update the '
    + 'rewrite in test-post-tool-use-capture-nudge.js so the /tmp shim can resolve it.'
  );
  process.exit(1);
}

const tmpShimPath = path.join(os.tmpdir(), `post-tool-use-shim-${Date.now()}.js`);
fs.writeFileSync(tmpShimPath, shimmedSource, 'utf8');
try {
  require(tmpShimPath); // must load without reading stdin or throwing
} finally {
  try { fs.unlinkSync(tmpShimPath); } catch (_) { /* ignore */ }
}

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

function makeTempProject() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-ptu-test-'));
  fs.mkdirSync(path.join(tmpDir, '.agentic'), { recursive: true });
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

function makeEvent(sessionId, event, agent, extra = {}) {
  return JSON.stringify({
    ts: new Date().toISOString(),
    phase: 'test',
    event,
    agent: agent || null,
    task_id: null,
    data: Object.assign({ session_uuid: sessionId }, extra),
  });
}

/**
 * Drive the real hook as a subprocess with the given payload on stdin.
 * Returns { stdout, status }. spawnSync (not execSync) so a clean exit 0 with
 * empty stdout is captured rather than treated as an error.
 *
 * @param {object} payload
 * @param {string} cwd
 * @param {string|null} rawOverride - raw stdin string (bypasses JSON.stringify)
 * @returns {{ stdout: string, status: number }}
 */
function runHook(payload, cwd, rawOverride) {
  const input = rawOverride !== undefined ? rawOverride : JSON.stringify(payload);
  const res = spawnSync('node', [hookPath], {
    input, cwd, timeout: 10000, encoding: 'utf8',
  });
  return { stdout: res.stdout || '', status: res.status };
}

function taskPayload(cwd, sessionId, overrides = {}) {
  return Object.assign({
    cwd,
    session_id: sessionId,
    tool_name: 'Task',
    tool_response: { status: 'async_launched' },
  }, overrides);
}

// ---------------------------------------------------------------------------
// Test 1: fires-when-worthy-event
// ---------------------------------------------------------------------------
console.log('\nTest 1: fires-when-worthy-event');
{
  const cwd = makeTempProject();
  const sessionId = 'ptu-session-001';
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'events.jsonl'),
    makeEvent(sessionId, 'spawn_complete', 'debugger') + '\n', 'utf8'
  );

  const { stdout, status } = runHook(taskPayload(cwd, sessionId), cwd);
  assert(status === 0, 'hook exits 0');
  let out = null;
  try { out = JSON.parse(stdout); } catch (_) { /* leave null */ }
  assert(out !== null, 'hook emitted parseable JSON');
  assert(
    out && out.hookSpecificOutput && out.hookSpecificOutput.hookEventName === 'PostToolUse',
    'hookEventName is PostToolUse'
  );
  assert(
    out && out.hookSpecificOutput
    && out.hookSpecificOutput.additionalContext.includes('CAPTURE-NUDGE')
    && out.hookSpecificOutput.additionalContext.includes('learning-worthy event occurred'),
    'additionalContext carries the standard CAPTURE-NUDGE text'
  );
  assert(out && out.suppressOutput === true, 'suppressOutput is true');
  // Tracker was written.
  const trackerPath = path.join(cwd, '.agentic', '.capture-gap-surfaced');
  assert(fs.existsSync(trackerPath), 'dedup tracker written after firing');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 2: dedup-suppresses-repeat
// ---------------------------------------------------------------------------
console.log('\nTest 2: dedup-suppresses-repeat');
{
  const cwd = makeTempProject();
  const sessionId = 'ptu-session-002';
  // A fixed-ts event so both spawns see the SAME lastEventTs tuple.
  const fixedEvent = JSON.stringify({
    ts: '2026-06-24T10:00:00.000Z',
    phase: 'test',
    event: 'spawn_complete',
    agent: 'debugger',
    task_id: null,
    data: { session_uuid: sessionId },
  });
  fs.writeFileSync(path.join(cwd, '.agentic', 'events.jsonl'), fixedEvent + '\n', 'utf8');

  const first = runHook(taskPayload(cwd, sessionId), cwd);
  assert(first.stdout.includes('CAPTURE-NUDGE'), 'first spawn emits nudge');

  const second = runHook(taskPayload(cwd, sessionId), cwd);
  assert(second.status === 0, 'second spawn exits 0');
  assert(second.stdout.trim() === '', 'second spawn (same tuple) emits nothing - dedup');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 3: no-fire-when-no-worthy-event
// ---------------------------------------------------------------------------
console.log('\nTest 3: no-fire-when-no-worthy-event');
{
  const cwd = makeTempProject();
  const sessionId = 'ptu-session-003';
  // events.jsonl absent -> no worthy event.
  const { stdout, status } = runHook(taskPayload(cwd, sessionId), cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no nudge emitted when no worthy event');
  assert(
    !fs.existsSync(path.join(cwd, '.agentic', '.capture-gap-surfaced')),
    'no tracker written when no worthy event'
  );
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 4: no-fire-when-wrong-tool
// ---------------------------------------------------------------------------
console.log('\nTest 4: no-fire-when-wrong-tool');
{
  const cwd = makeTempProject();
  const sessionId = 'ptu-session-004';
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'events.jsonl'),
    makeEvent(sessionId, 'spawn_complete', 'debugger') + '\n', 'utf8'
  );
  // tool_name is Bash, not Task - must not fire even though a worthy event exists.
  const payload = taskPayload(cwd, sessionId, { tool_name: 'Bash' });
  const { stdout, status } = runHook(payload, cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no nudge emitted for non-Task tool');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 5: no-fire-when-not-async-launched
// ---------------------------------------------------------------------------
console.log('\nTest 5: no-fire-when-not-async-launched');
{
  const cwd = makeTempProject();
  const sessionId = 'ptu-session-005';
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'events.jsonl'),
    makeEvent(sessionId, 'spawn_complete', 'debugger') + '\n', 'utf8'
  );
  // tool_response.status is "completed" (foreground), not "async_launched".
  const payload = taskPayload(cwd, sessionId, { tool_response: { status: 'completed' } });
  const { stdout, status } = runHook(payload, cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no nudge emitted when status !== async_launched');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 6: soft-fail-on-malformed-stdin
// ---------------------------------------------------------------------------
console.log('\nTest 6: soft-fail-on-malformed-stdin');
{
  const cwd = makeTempProject();
  const { stdout, status } = runHook(null, cwd, '{ this is not json');
  assert(status === 0, 'hook exits 0 on malformed stdin (soft-fail)');
  assert(stdout.trim() === '', 'no output on malformed stdin');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 7: residualOnly-wording
// A guardrail file is added but is NOT domain-proximate to the event, so the
// detector returns residualOnly=true and the hook must emit the residual text.
// ---------------------------------------------------------------------------
console.log('\nTest 7: residualOnly-wording');
{
  const cwd = makeTempProject();
  const sessionId = 'ptu-session-007';
  let ok = true;
  try {
    execSync('git init -b main', { cwd, stdio: 'pipe' });
    execSync('git config user.email "test@test.com"', { cwd, stdio: 'pipe' });
    execSync('git config user.name "Test"', { cwd, stdio: 'pipe' });
    fs.writeFileSync(path.join(cwd, 'README.md'), 'initial\n');
    execSync('git add README.md', { cwd, stdio: 'pipe' });
    execSync('git commit -m "init"', { cwd, stdio: 'pipe' });

    // Unrelated guardrail (payments domain), event domain is git -> no overlap.
    fs.mkdirSync(path.join(cwd, 'tests'), { recursive: true });
    fs.writeFileSync(path.join(cwd, 'tests', 'test-stripe-checkout.js'), '// test\n');
    execSync('git add tests/test-stripe-checkout.js', { cwd, stdio: 'pipe' });
    execSync('git commit -m "add unrelated test"', { cwd, stdio: 'pipe' });

    fs.writeFileSync(
      path.join(cwd, '.agentic', 'events.jsonl'),
      makeEvent(sessionId, 'tool_failure_workaround', null, {
        domain_tag: 'git', tool: 'git-push',
      }) + '\n', 'utf8'
    );
  } catch (e) {
    ok = false;
    console.log(`  SKIP: git fixture setup failed (${(e.message || '').split('\n')[0]})`);
  }

  if (ok) {
    const { stdout, status } = runHook(taskPayload(cwd, sessionId), cwd);
    assert(status === 0, 'hook exits 0');
    let out = null;
    try { out = JSON.parse(stdout); } catch (_) { /* leave null */ }
    assert(out !== null, 'hook emitted parseable JSON (residual case)');
    const ctx = out && out.hookSpecificOutput ? out.hookSpecificOutput.additionalContext : '';
    assert(
      ctx.includes('CAPTURE-NUDGE') && ctx.includes('related guardrail was added this session'),
      'residual case emits the residual CAPTURE-NUDGE wording'
    );
    assert(
      !ctx.includes('learning-worthy event occurred this session'),
      'residual case does NOT use the standard wording'
    );
  }
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 8: fires-when-tool-name-Agent (REGRESSION: CC Task->Agent rename)
// Identical to Test 1 but with tool_name "Agent". Under the pre-fix guard
// (`if (toolName !== 'Task') process.exit(0)`) this early-exited and emitted
// nothing - the nudge was silently disabled for every Agent spawn. The fixed
// guard (`toolName !== 'Task' && toolName !== 'Agent'`) must let it fire.
// ---------------------------------------------------------------------------
console.log('\nTest 8: fires-when-tool-name-Agent (regression)');
{
  const cwd = makeTempProject();
  const sessionId = 'ptu-session-008';
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'events.jsonl'),
    makeEvent(sessionId, 'spawn_complete', 'debugger') + '\n', 'utf8'
  );

  // tool_name is "Agent" (post-rename) - a worthy event exists, so the nudge
  // MUST fire. This asserts the dual Task/Agent guard.
  const payload = taskPayload(cwd, sessionId, { tool_name: 'Agent' });
  const { stdout, status } = runHook(payload, cwd);
  assert(status === 0, 'hook exits 0');
  let out = null;
  try { out = JSON.parse(stdout); } catch (_) { /* leave null */ }
  assert(out !== null, 'Agent spawn emits parseable JSON (regression guard)');
  assert(
    out && out.hookSpecificOutput
    && out.hookSpecificOutput.additionalContext.includes('CAPTURE-NUDGE'),
    'Agent spawn emits the CAPTURE-NUDGE text (would have been silent pre-fix)'
  );
  assert(
    fs.existsSync(path.join(cwd, '.agentic', '.capture-gap-surfaced')),
    'dedup tracker written after Agent spawn fires'
  );
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
if (failed > 0) process.exit(1);
