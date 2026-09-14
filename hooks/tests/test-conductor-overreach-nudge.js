#!/usr/bin/env node
/**
 * Unit tests: conductor-overreach-nudge.js Stop hook (advisory detector).
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
 *   10. no-refire-on-stop-hook-active: stop_hook_active:true with a
 *                                  transcript that WOULD trigger -> no
 *                                  advisory on stdout, no conductor_overreach
 *                                  event appended, exit 0 (regression for the
 *                                  unbreakable-loop bug: additionalContext
 *                                  from a Stop hook is surfaced by the
 *                                  harness as feedback that continues the
 *                                  turn, so an unguarded re-entrant fire
 *                                  never terminates).
 *   11. fires-when-stop-hook-active-false: same triggering transcript with
 *                                  stop_hook_active:false (and, separately,
 *                                  the field omitted entirely) -> advisory
 *                                  emitted and event appended, i.e. the
 *                                  first-fire behavior from test 1 is
 *                                  unaffected by the new guard.
 *   12. no-refire-second-fresh-stop-same-session: Layer 2 regression. Two
 *                                  independent (non-re-entrant,
 *                                  stop_hook_active:false) Stop calls with
 *                                  the SAME session_id and the same
 *                                  triggering transcript -> the first fires
 *                                  (advisory + event), the second does NOT
 *                                  (no advisory, no additional event) -
 *                                  backstops CC bug #54360, under which
 *                                  Layer 1 (stop_hook_active) can fail to
 *                                  propagate.
 *   13. no-fire-without-session-id: ratio_trigger true but no session_id in
 *                                  the payload -> no advisory, no event,
 *                                  exit 0 (Layer 2 has no key to bind a
 *                                  sentinel to, so it fails toward silence
 *                                  rather than emit unbounded).
 *   14. sentinel-write-failure-no-emit: the Layer 2 sentinel write is
 *                                  sabotaged (`.agentic` is a plain file,
 *                                  not a directory) -> no advisory, no
 *                                  event, exit 0 (fail-toward-silence,
 *                                  mirroring hooks/lib/loop_guard.py's
 *                                  write_counter contract: an action whose
 *                                  loop-bound write fails must not emit).
 *   15. prune-removes-aged-sentinel-keeps-fresh: a pre-existing
 *                                  .conductor-overreach-fired-<id> sentinel
 *                                  older than the 7-day retention window is
 *                                  removed by the current session's
 *                                  triggering stop, while a fresh
 *                                  (same-age-bucket) sentinel for a
 *                                  different session is left alone -
 *                                  regression for the unbounded-
 *                                  accumulation Minor (one zero-byte file
 *                                  per session, forever, with no prune).
 *   16. rename-failure-no-tmp-residue: unit-tests _markFired directly via
 *                                  the shim-load pattern (same technique as
 *                                  hooks/tests/test-stop-context-health.js),
 *                                  since driving this through the real
 *                                  hook subprocess is not viable - any
 *                                  pre-existing entry at the sentinel's own
 *                                  path (file OR directory) makes _hasFired
 *                                  report "already fired" and exit before
 *                                  _markFired is ever reached. fs.renameSync
 *                                  is stubbed to throw for exactly this
 *                                  sentinel's tmp path -> _markFired
 *                                  returns false (same fail-toward-silence
 *                                  contract as test 14) AND the orphaned
 *                                  `.tmp.<pid>` staging file is not left
 *                                  behind - regression for the tmp-file-
 *                                  leak Minor.
 *
 * Run with: node hooks/tests/test-conductor-overreach-nudge.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const hookPath = path.resolve(__dirname, '..', 'conductor-overreach-nudge.js');

// ---------------------------------------------------------------------------
// Shim-load conductor-overreach-nudge.js (same technique as
// hooks/tests/test-stop-context-health.js) - used only by Test 16, which
// needs to call _markFired directly (see that test's comment for why the
// real-hook-subprocess route cannot exercise the rename-failure path).
// ---------------------------------------------------------------------------
const { reanchorHookRequires } = require('./lib/hook-shim.js');

let internals;
{
  const hookSource = fs.readFileSync(hookPath, 'utf8');
  const shimmedSource = reanchorHookRequires(
    hookSource.replace(/^run\(\);\s*$/m, '// test shim: run() suppressed'),
    path.resolve(__dirname, '..', 'lib')
  );
  const tmpShimPath = path.join(os.tmpdir(), `overreach-nudge-shim-${Date.now()}.js`);
  fs.writeFileSync(tmpShimPath, shimmedSource, 'utf8');
  try {
    internals = require(tmpShimPath);
  } finally {
    try { fs.unlinkSync(tmpShimPath); } catch (_) { /* ignore */ }
  }
}
const { _markFired, _sentinelPath: _internalSentinelPath } = internals;

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
  const fixtureCase = fixture.cases.find((c) => c.name === 'interleaved-non-agent-results');
  const transcriptPath = writeTranscript(cwd, fixtureCase.lines);
  const { stdout, status } = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no advisory: the fixture contains one spawn, so ratio_trigger stays false');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 10: no-refire-on-stop-hook-active (regression for the unbreakable loop)
// ---------------------------------------------------------------------------
console.log('\nTest 10: no-refire-on-stop-hook-active');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const sessionId = 'overreach-session-010';
  const transcriptPath = writeTranscript(cwd, buildInvestigationOnlyTranscript(5)); // 5 > 3
  const payload = stopPayload(cwd, sessionId, transcriptPath);
  payload.stop_hook_active = true;
  const { stdout, status } = runHook(payload, cwd);
  assert(status === 0, 'hook exits 0 on re-entrant stop_hook_active:true');
  assert(stdout.trim() === '', 'no advisory emitted when stop_hook_active is true');
  const lines = eventLines(cwd);
  assert(lines.find((e) => e.event === 'conductor_overreach') === undefined,
    'no conductor_overreach event appended when stop_hook_active is true');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 11: fires-when-stop-hook-active-false (existing behavior intact)
// ---------------------------------------------------------------------------
console.log('\nTest 11: fires-when-stop-hook-active-false');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const sessionId = 'overreach-session-011a';
  const transcriptPath = writeTranscript(cwd, buildInvestigationOnlyTranscript(5)); // 5 > 3
  const payload = stopPayload(cwd, sessionId, transcriptPath); // stop_hook_active: false
  const { stdout, status } = runHook(payload, cwd);
  assert(status === 0, 'hook exits 0 with stop_hook_active:false');
  let out = null;
  try { out = JSON.parse(stdout); } catch (_) { /* leave null */ }
  assert(
    out && out.hookSpecificOutput
    && out.hookSpecificOutput.additionalContext.includes('Advisory:'),
    'advisory emitted when stop_hook_active is false'
  );
  const lines = eventLines(cwd);
  assert(lines.find((e) => e.event === 'conductor_overreach') !== undefined,
    'conductor_overreach event appended when stop_hook_active is false');
  cleanup(cwd);

  // Field omitted entirely (not every harness call is guaranteed to send it).
  const cwd2 = makeTempProject();
  fs.writeFileSync(
    path.join(cwd2, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const sessionId2 = 'overreach-session-011b';
  const transcriptPath2 = writeTranscript(cwd2, buildInvestigationOnlyTranscript(5));
  const payload2 = {
    session_id: sessionId2,
    transcript_path: transcriptPath2,
    cwd: cwd2,
    hook_event_name: 'Stop',
    // stop_hook_active intentionally omitted
  };
  const { stdout: stdout2, status: status2 } = runHook(payload2, cwd2);
  assert(status2 === 0, 'hook exits 0 with stop_hook_active omitted');
  let out2 = null;
  try { out2 = JSON.parse(stdout2); } catch (_) { /* leave null */ }
  assert(
    out2 && out2.hookSpecificOutput
    && out2.hookSpecificOutput.additionalContext.includes('Advisory:'),
    'advisory emitted when stop_hook_active is omitted'
  );
  cleanup(cwd2);
}

// ---------------------------------------------------------------------------
// Test 12: no-refire-second-fresh-stop-same-session (Layer 2 regression)
// ---------------------------------------------------------------------------
console.log('\nTest 12: no-refire-second-fresh-stop-same-session');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const sessionId = 'overreach-session-012';
  const transcriptPath = writeTranscript(cwd, buildInvestigationOnlyTranscript(5)); // 5 > 3

  const first = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
  assert(first.status === 0, 'first (fresh) stop exits 0');
  let out1 = null;
  try { out1 = JSON.parse(first.stdout); } catch (_) { /* leave null */ }
  assert(
    out1 && out1.hookSpecificOutput
    && out1.hookSpecificOutput.additionalContext.includes('Advisory:'),
    'first stop fires the advisory'
  );
  assert(
    eventLines(cwd).filter((e) => e.event === 'conductor_overreach').length === 1,
    'exactly one conductor_overreach event after the first stop'
  );

  // A second, INDEPENDENT (non-re-entrant) Stop call - same session_id,
  // same triggering transcript. Layer 1 alone would refire here since
  // stop_hook_active is false; Layer 2 must still suppress it.
  const second = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
  assert(second.status === 0, 'second (fresh) stop exits 0');
  assert(second.stdout.trim() === '', 'second stop (same session) does not refire the advisory');
  assert(
    eventLines(cwd).filter((e) => e.event === 'conductor_overreach').length === 1,
    'still exactly one conductor_overreach event after the second stop'
  );
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 13: no-fire-without-session-id
// ---------------------------------------------------------------------------
console.log('\nTest 13: no-fire-without-session-id');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );
  const transcriptPath = writeTranscript(cwd, buildInvestigationOnlyTranscript(5)); // 5 > 3
  const payload = {
    transcript_path: transcriptPath,
    cwd,
    hook_event_name: 'Stop',
    stop_hook_active: false,
    // session_id intentionally omitted
  };
  const { stdout, status } = runHook(payload, cwd);
  assert(status === 0, 'exits 0 without session_id');
  assert(stdout.trim() === '', 'no advisory without session_id (Layer 2 has no key to bind a sentinel to)');
  assert(
    eventLines(cwd).find((e) => e.event === 'conductor_overreach') === undefined,
    'no event appended without session_id'
  );
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 14: sentinel-write-failure-no-emit (Layer 2 fail-toward-silence)
// ---------------------------------------------------------------------------
console.log('\nTest 14: sentinel-write-failure-no-emit');
{
  const cwd = makeTempProject();
  // Sabotage the sentinel write: replace the .agentic DIRECTORY with a
  // plain FILE, so _markFired's mkdirSync(agenticDir, {recursive:true})
  // throws (EEXIST on a non-directory) and returns false. Use a threshold-
  // free trigger (> DEFAULT_THRESHOLD=12) since config.json can no longer
  // be written under a file-shaped .agentic.
  fs.rmSync(path.join(cwd, '.agentic'), { recursive: true, force: true });
  fs.writeFileSync(path.join(cwd, '.agentic'), '', 'utf8');
  const sessionId = 'overreach-session-014';
  const transcriptPath = writeTranscript(cwd, buildInvestigationOnlyTranscript(15)); // 15 > 12
  const { stdout, status } = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
  assert(status === 0, 'exits 0 when the Layer 2 sentinel write fails');
  assert(stdout.trim() === '', 'no advisory when the sentinel cannot be persisted');
  cleanup(cwd);
}

/** Mirrors the hook's own _sentinelPath sanitization for test-side setup. */
function _testSentinelPath(cwd, sessionId) {
  const safeId = sessionId.replace(/[^a-zA-Z0-9_-]/g, '_');
  return path.join(cwd, '.agentic', `.conductor-overreach-fired-${safeId}`);
}

// ---------------------------------------------------------------------------
// Test 15: prune-removes-aged-sentinel-keeps-fresh
// ---------------------------------------------------------------------------
console.log('\nTest 15: prune-removes-aged-sentinel-keeps-fresh');
{
  const cwd = makeTempProject();
  fs.writeFileSync(
    path.join(cwd, '.agentic', 'config.json'),
    JSON.stringify({ conductor_overreach_threshold: 3 }), 'utf8'
  );

  // Pre-existing sentinel older than the 7-day retention window.
  const oldSentinel = _testSentinelPath(cwd, 'old-session');
  fs.writeFileSync(oldSentinel, '');
  const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000);
  fs.utimesSync(oldSentinel, eightDaysAgo, eightDaysAgo);

  // Pre-existing sentinel well within the retention window.
  const freshSentinel = _testSentinelPath(cwd, 'fresh-session');
  fs.writeFileSync(freshSentinel, '');

  const sessionId = 'overreach-session-015';
  const transcriptPath = writeTranscript(cwd, buildInvestigationOnlyTranscript(5)); // 5 > 3
  const { status } = runHook(stopPayload(cwd, sessionId, transcriptPath), cwd);
  assert(status === 0, 'triggering stop exits 0');

  assert(!fs.existsSync(oldSentinel), 'the aged (>7d) sentinel was pruned');
  assert(fs.existsSync(freshSentinel), 'the fresh sentinel was left alone');
  assert(fs.existsSync(_testSentinelPath(cwd, sessionId)), "the current session's own sentinel was written");
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 16: rename-failure-no-tmp-residue
// ---------------------------------------------------------------------------
console.log('\nTest 16: rename-failure-no-tmp-residue');
{
  const cwd = makeTempProject();
  const sessionId = 'overreach-session-016';
  // MUST use the module's own _sentinelPath, not the local _testSentinelPath
  // duplicate: resolveAgenticCwd realpath-normalizes cwd (e.g. macOS's
  // /var -> /private/var symlink), so a locally-recomputed path from the
  // raw (unnormalized) cwd silently diverges from what _markFired actually
  // operates on - existsSync-based assertions in tests 12/13/15 don't
  // notice this (the OS resolves the symlink transparently either way),
  // but this test's stub match is a STRING comparison and needs the exact
  // path _markFired will pass to fs.renameSync.
  const sentinelPath = _internalSentinelPath(cwd, sessionId);

  // Stub fs.renameSync to fail ONLY for this sentinel's own tmp path -
  // real hooks/tests/test-stop-context-health.js precedent (M2). Since
  // conductor-overreach-nudge.js does `const fs = require('fs');` at
  // module scope, and the shimmed copy shares the SAME core 'fs' module
  // object as this test file, patching the method here is visible inside
  // _markFired too.
  const originalRenameSync = fs.renameSync;
  let stubHit = false;
  fs.renameSync = function (oldPath, newPath, ...rest) {
    if (typeof oldPath === 'string' && oldPath.startsWith(sentinelPath + '.tmp.')) {
      stubHit = true;
      const err = new Error('EISDIR: simulated rename failure');
      err.code = 'EISDIR';
      throw err;
    }
    return originalRenameSync.call(this, oldPath, newPath, ...rest);
  };

  let result;
  try {
    result = _markFired(cwd, sessionId);
  } finally {
    fs.renameSync = originalRenameSync;
  }

  assert(stubHit === true, 'the renameSync stub was actually hit (test exercises the real failure path)');
  assert(result === false, '_markFired returns false when renameSync fails');
  assert(!fs.existsSync(sentinelPath), 'the sentinel itself was never created (rename never completed)');

  const agenticDir = path.join(cwd, '.agentic');
  const leaked = fs.readdirSync(agenticDir).filter((n) => n.includes('.tmp.'));
  assert(leaked.length === 0, `no orphaned .tmp.<pid> file left behind (found: ${JSON.stringify(leaked)})`);
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
