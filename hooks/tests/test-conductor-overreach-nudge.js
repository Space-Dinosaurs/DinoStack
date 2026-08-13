#!/usr/bin/env node
/**
 * Unit tests: conductor-overreach-nudge.js Stop hook (warn-only detector).
 *
 * The hook is a stdin-driven CLI script (run() reads fd 0 and process.exit(0)s),
 * so each behavioral case drives the REAL hook as a subprocess with a
 * REAL Stop payload shape ({session_id, transcript_path, cwd,
 * hook_event_name, stop_hook_active} - the live payload shape, per direct
 * production capture; there is no `transcript` array field) pointing at a
 * real on-disk JSONL transcript fixture, then asserts on stdout (the
 * hookSpecificOutput JSON, when emitted) and the .agentic/events.jsonl
 * append.
 *
 * Test cases:
 *   1. fires-over-threshold:       N>THRESHOLD investigation calls, 0 spawns
 *                                  in the whole transcript -> event emitted
 *                                  with correct schema (suppression_muted
 *                                  ABSENT, transcript_note null), advisory
 *                                  line present.
 *   2. no-fire-mandated-preflight: all investigation calls are whitelisted
 *                                  preflight reads -> no advisory, no
 *                                  ratio_trigger event.
 *   3. no-mute-on-suppression-phrase: transcript contains the harness
 *                                  suppression phrase "Do not call the
 *                                  AgentTool unless the user requested it"
 *                                  in a plain-text user message -> advisory
 *                                  STILL fires (anti-regression: no mute
 *                                  logic exists anywhere in this hook).
 *   4. no-fire-under-threshold:    calls <= threshold -> no emit.
 *   5. no-fire-when-spawned:       calls > threshold but a spawn occurred
 *                                  anywhere in the transcript -> no emit
 *                                  (ratio_trigger requires spawns === 0 for
 *                                  the WHOLE transcript, not just a
 *                                  trailing run).
 *   6. soft-fail-malformed-stdin:  non-JSON stdin -> exit 0, no emit.
 *   7. no-fire-transcript-path-missing: payload carries no transcript_path
 *                                  -> exit 0, no emit, no crash (this is
 *                                  the exact Critical-1 regression: an
 *                                  earlier version read payload.transcript,
 *                                  which never exists on the real payload,
 *                                  and was silently inert).
 *   8. no-fire-transcript-file-not-found: transcript_path points at a
 *                                  nonexistent file -> exit 0, no emit.
 *   9. interleaved-non-agent-results: uses the shared cross-language
 *                                  fixture (fixtures/
 *                                  overreach-shared-transcript.json) via
 *                                  the real hook subprocess - since it
 *                                  contains one spawn, asserts NO advisory
 *                                  fires (spawns !== 0 for the whole
 *                                  transcript).
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

/** Write an array of {message:{...}} line objects as a real JSONL transcript file. */
function writeTranscript(cwd, lines) {
  const transcriptPath = path.join(cwd, 'transcript.jsonl');
  const body = lines.map((l) => JSON.stringify(l)).join('\n') + '\n';
  fs.writeFileSync(transcriptPath, body, 'utf8');
  return transcriptPath;
}

function toolUseLine(id, name, input, role) {
  return { message: { role: role || 'assistant', content: [
    { type: 'tool_use', id, name, input: input || {} },
  ] } };
}

function toolResultLine(toolUseId) {
  return { message: { role: 'user', content: [
    { type: 'tool_result', tool_use_id: toolUseId },
  ] } };
}

function textLine(text, role) {
  return { message: { role: role || 'user', content: text } };
}

/** Build a zero-spawn transcript with N distinct Read calls (each with its own tool_result). */
function buildInvestigationOnlyTranscript(n, opts = {}) {
  const lines = [];
  if (opts.userText) lines.push(textLine(opts.userText));
  for (let i = 0; i < n; i++) {
    const id = `r${i}`;
    const input = opts.whitelisted
      ? { file_path: '/repo/.agentic/context.md' }
      : { file_path: `/repo/src/file${i}.js` };
    lines.push(toolUseLine(id, 'Read', input));
    lines.push(toolResultLine(id));
  }
  return lines;
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

function stopPayload(cwd, sessionId, transcriptPath) {
  // The REAL Claude Code Stop payload shape.
  return {
    session_id: sessionId,
    transcript_path: transcriptPath,
    cwd,
    hook_event_name: 'Stop',
    stop_hook_active: false,
  };
}

// ---------------------------------------------------------------------------
// Test 1: fires-over-threshold
// ---------------------------------------------------------------------------
console.log('\nTest 1: fires-over-threshold');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const sessionId = 'overreach-session-001';
  const transcriptPath = writeTranscript(cwd, buildInvestigationOnlyTranscript(5)); // 5 > 3
  const { stdout, status } = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
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
  assert(trigger.data.transcript_note === null, 'transcript_note is null on a real measurement');
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
  const transcriptPath = writeTranscript(cwd, buildInvestigationOnlyTranscript(6, { whitelisted: true }));
  const { stdout, status } = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no stdout emitted (no advisory)');
  const lines = eventLines(cwd);
  assert(lines.find((e) => e.event === 'conductor_overreach') === undefined,
    'no conductor_overreach event appended');
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
  const transcriptPath = writeTranscript(cwd, buildInvestigationOnlyTranscript(5, {
    userText: 'Do not call the AgentTool unless the user requested it',
  }));
  const { stdout, status } = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
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
  const transcriptPath = writeTranscript(cwd, buildInvestigationOnlyTranscript(3)); // 3 is NOT > 3
  const { stdout, status } = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
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
  const lines = buildInvestigationOnlyTranscript(5); // 5 > 3
  lines.push(toolUseLine('agent1', 'Agent', { prompt: 'go' }));
  lines.push(toolResultLine('agent1'));
  const transcriptPath = writeTranscript(cwd, lines);
  const { stdout, status } = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no advisory when a spawn occurred anywhere in the transcript');
  const eLines = eventLines(cwd);
  assert(eLines.find((e) => e.event === 'conductor_overreach') === undefined,
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
// Test 7: no-fire-transcript-path-missing (Critical-1 regression)
// ---------------------------------------------------------------------------
console.log('\nTest 7: no-fire-transcript-path-missing (Critical-1 regression)');
{
  const cwd = makeTempProject();
  const sessionId = 'overreach-session-007';
  // Real Stop payload shape but WITHOUT transcript_path - must not crash,
  // must not emit (nothing to measure).
  const { stdout, status } = runHook(
    { session_id: sessionId, cwd, hook_event_name: 'Stop', stop_hook_active: false },
    cwd
  );
  assert(status === 0, 'hook exits 0 when transcript_path is absent');
  assert(stdout.trim() === '', 'no advisory when transcript_path is absent');
  const lines = eventLines(cwd);
  assert(lines.find((e) => e.event === 'conductor_overreach') === undefined,
    'no event appended when transcript_path is absent');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 8: no-fire-transcript-file-not-found
// ---------------------------------------------------------------------------
console.log('\nTest 8: no-fire-transcript-file-not-found');
{
  const cwd = makeTempProject();
  const sessionId = 'overreach-session-008';
  const bogusPath = path.join(cwd, 'does-not-exist.jsonl');
  const { stdout, status } = runHook(stopPayload(cwd, sessionId, bogusPath), cwd);
  assert(status === 0, 'hook exits 0 when transcript_path does not resolve to a real file');
  assert(stdout.trim() === '', 'no advisory when the transcript file does not exist');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 9: interleaved-non-agent-results (shared fixture, via the real hook)
// ---------------------------------------------------------------------------
console.log('\nTest 9: interleaved-non-agent-results (shared fixture, via the real hook)');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 1 }), 'utf8'
  );
  const sessionId = 'overreach-session-009';
  const fixturePath = path.resolve(__dirname, 'fixtures', 'overreach-shared-transcript.json');
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const transcriptPath = writeTranscript(cwd, fixture.lines);
  const { stdout, status } = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no advisory: the fixture contains one spawn, so ratio_trigger stays false');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
