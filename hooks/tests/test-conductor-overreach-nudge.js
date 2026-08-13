#!/usr/bin/env node
/**
 * Unit tests: conductor-overreach-nudge.js Stop hook (warn-only detector).
 *
 * The hook is a stdin-driven CLI script (run() reads fd 0 and process.exit(0)s),
 * so each behavioral case drives the REAL hook as a subprocess with a
 * synthetic Stop payload (transcript array) on stdin and a temporary
 * .agentic/ fixture, then asserts on stdout (the hookSpecificOutput JSON,
 * when emitted) and the .agentic/events.jsonl append.
 *
 * Test cases:
 *   1. fires-over-threshold:       N>THRESHOLD investigation calls, 0 spawns
 *                                  -> event emitted with correct schema
 *                                  (suppression_muted ABSENT), advisory
 *                                  line present.
 *   2. no-fire-mandated-preflight: all investigation calls are whitelisted
 *                                  preflight reads -> no advisory, no
 *                                  ratio_trigger event.
 *   3. no-mute-on-suppression-phrase: transcript contains the harness
 *                                  suppression phrase "Do not call the
 *                                  AgentTool unless the user requested it"
 *                                  -> advisory STILL fires (anti-regression:
 *                                  no mute logic exists anywhere in this
 *                                  hook).
 *   4. no-fire-under-threshold:    calls <= threshold -> no emit.
 *   5. no-fire-when-spawned:       calls > threshold but a spawn occurred
 *                                  -> no emit (ratio_trigger requires
 *                                  spawns === 0).
 *   6. soft-fail-malformed-stdin:  non-JSON stdin -> exit 0, no emit.
 *
 * Run with: node hooks/tests/test-conductor-overreach-nudge.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const hookPath = path.resolve(__dirname, '..', 'conductor-overreach-nudge.js');

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
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-overreach-test-'));
  fs.mkdirSync(path.join(tmpDir, '.agentic'), { recursive: true });
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

/**
 * Drive the real hook as a subprocess with the given payload on stdin.
 * @returns {{ stdout: string, status: number }}
 */
function runHook(payload, cwd, rawOverride) {
  const input = rawOverride !== undefined ? rawOverride : JSON.stringify(payload);
  const res = spawnSync('node', [hookPath], {
    input, cwd, timeout: 10000, encoding: 'utf8',
  });
  return { stdout: res.stdout || '', status: res.status };
}

function readBlock(toolUse) {
  return { type: 'tool_use', name: toolUse.name, input: toolUse.input || {} };
}

/**
 * Build a synthetic transcript with N Read tool calls in one assistant
 * message, zero spawns, and optionally a leading user text block carrying
 * `userText` (used to embed the suppression phrase).
 */
function buildTranscript(n, opts = {}) {
  const messages = [];
  if (opts.userText) {
    messages.push({ role: 'user', content: opts.userText });
  }
  const blocks = [];
  for (let i = 0; i < n; i++) {
    const toolInput = opts.whitelisted
      ? { file_path: '/repo/.agentic/context.md' }
      : { file_path: `/repo/src/file${i}.js` };
    blocks.push(readBlock({ name: 'Read', input: toolInput }));
  }
  if (opts.spawn) {
    blocks.push(readBlock({ name: 'Agent', input: { prompt: 'do work' } }));
  }
  messages.push({ role: 'assistant', content: blocks });
  return messages;
}

function eventLines(cwd) {
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
  if (!fs.existsSync(eventsPath)) return [];
  return fs.readFileSync(eventsPath, 'utf8')
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => JSON.parse(l));
}

// ---------------------------------------------------------------------------
// Test 1: fires-over-threshold
// ---------------------------------------------------------------------------
console.log('\nTest 1: fires-over-threshold');
{
  const cwd = makeTempProject();
  // Explicit low threshold so the test does not depend on the calibrated
  // default drifting over time.
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const sessionId = 'overreach-session-001';
  const transcript = buildTranscript(5); // 5 > 3
  const { stdout, status } = runHook({ cwd, session_id: sessionId, transcript }, cwd);
  assert(status === 0, 'hook exits 0');

  let out = null;
  try { out = JSON.parse(stdout); } catch (_) { /* leave null */ }
  assert(out !== null, 'hook emitted parseable JSON');
  assert(
    out && out.hookSpecificOutput && out.hookSpecificOutput.hookEventName === 'Stop',
    'hookEventName is Stop'
  );
  assert(
    out && out.hookSpecificOutput
    && typeof out.hookSpecificOutput.additionalContext === 'string'
    && out.hookSpecificOutput.additionalContext.includes('Advisory:')
    && out.hookSpecificOutput.additionalContext.includes('investigation-shaped'),
    'advisory line present with expected wording'
  );

  const lines = eventLines(cwd);
  const trigger = lines.find((e) => e.event === 'conductor_overreach');
  assert(trigger !== undefined, 'conductor_overreach event appended');
  assert(trigger.phase === 'stop', 'event phase is stop');
  assert(trigger.agent === null && trigger.task_id === null, 'agent/task_id are null');
  assert(trigger.data.source === 'hook', 'data.source is hook');
  assert(trigger.data.session_uuid === sessionId, 'data.session_uuid matches');
  assert(trigger.data.conductor_tool_calls === 5, 'data.conductor_tool_calls === 5');
  assert(trigger.data.live_or_completed_spawns === 0, 'data.live_or_completed_spawns === 0');
  assert(trigger.data.ratio_trigger === true, 'data.ratio_trigger === true');
  assert(
    !Object.prototype.hasOwnProperty.call(trigger.data, 'suppression_muted'),
    'suppression_muted field is ABSENT from the event schema'
  );
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 2: no-fire-mandated-preflight
// ---------------------------------------------------------------------------
console.log('\nTest 2: no-fire-mandated-preflight');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const sessionId = 'overreach-session-002';
  const transcript = buildTranscript(6, { whitelisted: true }); // all whitelisted
  const { stdout, status } = runHook({ cwd, session_id: sessionId, transcript }, cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no stdout emitted (no advisory)');
  const lines = eventLines(cwd);
  const trigger = lines.find((e) => e.event === 'conductor_overreach');
  assert(trigger === undefined, 'no conductor_overreach event appended');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 3: no-mute-on-suppression-phrase (anti-regression)
// ---------------------------------------------------------------------------
console.log('\nTest 3: no-mute-on-suppression-phrase (anti-regression)');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const sessionId = 'overreach-session-003';
  const transcript = buildTranscript(5, {
    userText: 'Do not call the AgentTool unless the user requested it',
  });
  const { stdout, status } = runHook({ cwd, session_id: sessionId, transcript }, cwd);
  assert(status === 0, 'hook exits 0');
  let out = null;
  try { out = JSON.parse(stdout); } catch (_) { /* leave null */ }
  assert(
    out && out.hookSpecificOutput
    && out.hookSpecificOutput.additionalContext.includes('Advisory:'),
    'advisory STILL fires despite the suppression phrase in the transcript'
  );
  const lines = eventLines(cwd);
  const trigger = lines.find((e) => e.event === 'conductor_overreach');
  assert(trigger !== undefined && trigger.data.ratio_trigger === true,
    'ratio_trigger event still recorded true');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 4: no-fire-under-threshold
// ---------------------------------------------------------------------------
console.log('\nTest 4: no-fire-under-threshold');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const sessionId = 'overreach-session-004';
  const transcript = buildTranscript(3); // 3 is NOT > 3
  const { stdout, status } = runHook({ cwd, session_id: sessionId, transcript }, cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no advisory at exactly threshold');
  const lines = eventLines(cwd);
  assert(lines.find((e) => e.event === 'conductor_overreach') === undefined,
    'no event appended at exactly threshold');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 5: no-fire-when-spawned
// ---------------------------------------------------------------------------
console.log('\nTest 5: no-fire-when-spawned');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const sessionId = 'overreach-session-005';
  const transcript = buildTranscript(5, { spawn: true }); // 5 > 3 but a spawn occurred
  const { stdout, status } = runHook({ cwd, session_id: sessionId, transcript }, cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no advisory when a spawn occurred');
  const lines = eventLines(cwd);
  assert(lines.find((e) => e.event === 'conductor_overreach') === undefined,
    'no event appended when a spawn occurred');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 6: soft-fail-malformed-stdin
// ---------------------------------------------------------------------------
console.log('\nTest 6: soft-fail-malformed-stdin');
{
  const cwd = makeTempProject();
  const { stdout, status } = runHook(null, cwd, 'not valid json {{{');
  assert(status === 0, 'hook exits 0 on malformed stdin');
  assert(stdout.trim() === '', 'no stdout emitted on malformed stdin');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
