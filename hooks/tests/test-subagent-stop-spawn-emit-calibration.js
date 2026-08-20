#!/usr/bin/env node
/**
 * Unit tests: DS-178 unit A calibration additions to
 * hooks/subagent-stop-spawn-emit.js (readSidecar, scanTranscript's model/
 * attributionAgent/firstTimestamp extension, parseSkepticSignoff,
 * readRoundState, and their wiring into run()'s emitted event).
 *
 * These tests are ADDITIVE to hooks/tests/test-subagent-stop-spawn-emit.js
 * (pairing/wall_seconds/tokens fundamentals, unchanged - see that file's
 * own 14 cases, now exercising the fallback path since a sidecar is not
 * present in any of its fixtures).
 *
 * Test cases:
 *   1. sidecar-hit-agent-and-source:  a valid sidecar with a toolUseId that
 *                                       exactly matches a same-session
 *                                       spawn_start -> agent === sidecar's
 *                                       agentType, data.agent_source ===
 *                                       "sidecar".
 *   2. sidecar-miss-falls-back-to-fifo: no sidecar file at all -> pairing
 *                                       falls back to FIFO,
 *                                       data.agent_source === "paired_start".
 *   3. malformed-sidecar-invalid-json-never-blocks: sidecar file contains
 *                                       invalid JSON -> readSidecar()
 *                                       returns null, hook still exits 0
 *                                       and still emits spawn_complete.
 *   4. malformed-sidecar-empty-file-never-blocks: 0-byte sidecar file ->
 *                                       same as above.
 *   5. no-findings-yields-three-zeros: "Findings: No findings." in the
 *                                       last assistant message -> emitted
 *                                       findings_count === {0,0,0}, not
 *                                       absent.
 *   6. withheld-verdict:               "Sign-off withheld." literal ->
 *                                       signed_off === false.
 *   7. no-verdict-yields-calibration-note: a Findings: line present but
 *                                       NEITHER verdict literal present ->
 *                                       calibration_note set, no
 *                                       findings_count/signed_off.
 *   8. multi-findings-tie-break:       two "Findings:" lines in the last
 *                                       assistant message -> the LAST one
 *                                       wins for the emitted counts, and
 *                                       findings_parse_ambiguous === true.
 *   9. decoy-earlier-message-ignored:  an EARLIER assistant message
 *                                       carries the verbatim sign-off
 *                                       template (including "Sign-off
 *                                       granted.") but the LAST assistant
 *                                       message carries neither a Findings
 *                                       line nor a verdict -> the decoy is
 *                                       ignored entirely, calibration_note
 *                                       is set (not a false grant).
 *  10. tuid-index-hit:                 a populated skeptic-tuid-index.json
 *                                       plus a matching skeptic-round-*.json
 *                                       state file -> unit_key/iteration
 *                                       emitted with the correct values.
 *  11. tuid-index-miss-no-note:        no tuid-index file at all -> no
 *                                       unit_key/iteration emitted, and
 *                                       (given a normal sign-off parses)
 *                                       NO calibration_note either - a
 *                                       tuid-index miss is a silent
 *                                       omission, not a notable failure
 *                                       (mirrors paired_spawn_id:null on
 *                                       an unmatched spawn).
 *  12. model-precedence-sidecar-wins:  sidecar carries a model AND the
 *                                       transcript carries a DIFFERENT
 *                                       model -> the emitted model is the
 *                                       SIDECAR's value.
 *  13. model-precedence-transcript-fallback: sidecar carries no model ->
 *                                       the emitted model comes from the
 *                                       transcript.
 *  14. model-transcript-too-large-path: a transcript at/above
 *                                       MAX_TRANSCRIPT_BYTES (20 MiB), no
 *                                       sidecar model -> model absent,
 *                                       model_note === "skipped
 *                                       (transcript too large)".
 *  15. tokens-and-model-note-mutual-exclusion: on a transcript that DOES
 *                                       resolve but yields no usable
 *                                       tokens/model (empty assistant
 *                                       records) -> tokens is absent WITH
 *                                       tokens_note, model is absent WITH
 *                                       model_note, and neither ever
 *                                       appears alongside its counterpart
 *                                       value.
 *
 * Run with: node hooks/tests/test-subagent-stop-spawn-emit-calibration.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const hookPath = path.resolve(__dirname, '..', 'subagent-stop-spawn-emit.js');
const roundCapHookPath = path.resolve(__dirname, '..', 'enforce-skeptic-round-cap.py');

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

function makeTmpDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function cleanup(dir) {
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

function projectHash(cwd) {
  return String(cwd).replace(/\//g, '-');
}

function subagentsDir(configDir, cwd, sessionId) {
  const dir = path.join(configDir, 'projects', projectHash(cwd), sessionId, 'subagents');
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function writeSidecar(configDir, cwd, sessionId, agentId, obj) {
  const dir = subagentsDir(configDir, cwd, sessionId);
  fs.writeFileSync(path.join(dir, `agent-${agentId}.meta.json`), JSON.stringify(obj));
}

function writeSidecarRaw(configDir, cwd, sessionId, agentId, raw) {
  const dir = subagentsDir(configDir, cwd, sessionId);
  fs.writeFileSync(path.join(dir, `agent-${agentId}.meta.json`), raw);
}

function writeTranscript(configDir, cwd, sessionId, agentId, lines) {
  const dir = subagentsDir(configDir, cwd, sessionId);
  const raw = lines.map((l) => JSON.stringify(l)).join('\n') + '\n';
  fs.writeFileSync(path.join(dir, `agent-${agentId}.jsonl`), raw);
}

function assistantRecord(text, overrides = {}) {
  return Object.assign({
    type: 'assistant',
    timestamp: new Date().toISOString(),
    attributionAgent: 'skeptic',
    message: {
      role: 'assistant',
      model: 'claude-sonnet-5',
      content: [{ type: 'text', text }],
      usage: { input_tokens: 10, output_tokens: 20, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 },
    },
  }, overrides);
}

function userRecord(text, overrides = {}) {
  return Object.assign({
    type: 'user',
    timestamp: new Date().toISOString(),
    message: {
      role: 'user',
      content: [{ type: 'text', text }],
    },
  }, overrides);
}

function initGitRepo(dir) {
  spawnSync('git', ['init', '-q'], { cwd: dir });
  spawnSync('git', ['config', 'user.email', 'test@example.com'], { cwd: dir });
  spawnSync('git', ['config', 'user.name', 'Test'], { cwd: dir });
}

function gitCommit(dir, filename, contents, message) {
  fs.writeFileSync(path.join(dir, filename), contents);
  spawnSync('git', ['add', filename], { cwd: dir });
  spawnSync('git', ['commit', '-q', '-m', message], { cwd: dir });
}

function runHook(payload, cwd, configDir) {
  const env = Object.assign({}, process.env, { CLAUDE_CONFIG_DIR: configDir });
  const res = spawnSync('node', [hookPath], {
    input: JSON.stringify(payload), cwd, env, timeout: 10000, encoding: 'utf8',
  });
  return { stdout: res.stdout || '', status: res.status };
}

function stopPayload(cwd, sessionId, agentId, overrides = {}) {
  return Object.assign({
    cwd,
    session_id: sessionId,
    agent_id: agentId,
    hook_event_name: 'SubagentStop',
  }, overrides);
}

function readEvents(cwd) {
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
  if (!fs.existsSync(eventsPath)) return [];
  return fs.readFileSync(eventsPath, 'utf8')
    .split('\n').filter(Boolean)
    .map((line) => { try { return JSON.parse(line); } catch (_) { return null; } })
    .filter(Boolean);
}

function appendRaw(cwd, obj) {
  const agenticDir = path.join(cwd, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  fs.appendFileSync(path.join(agenticDir, 'events.jsonl'), JSON.stringify(obj) + '\n', 'utf8');
}

function hookSpawnStart(sessionId, spawnId, agent, toolUseId, tsOverride) {
  return {
    ts: tsOverride || new Date(Date.now() - 5000).toISOString(),
    phase: 'hook',
    event: 'spawn_start',
    agent: agent || 'engineer',
    task_id: null,
    data: { source: 'hook', session_uuid: sessionId, spawn_id: spawnId, tool_use_id: toolUseId || null, parent_agent_id: null },
  };
}

const GRANTED_SIGNOFF = [
  'Reviewed: hooks/subagent-stop-spawn-emit.js',
  'Findings: Critical: 0, Major: 0, Minor: 1',
  '- Minor - a style nit (file.js:10)',
  'Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.',
  'Manifest check: pass',
  'Test-CI-wiring check: n/a - no new test files in diff',
  'Neutrality check: pass',
  'No unresolved Critical or Major findings. Sign-off granted.',
].join('\n');

const WITHHELD_SIGNOFF = [
  'Reviewed: hooks/subagent-stop-spawn-emit.js',
  'Findings: Critical: 1, Major: 0, Minor: 0',
  '- Critical - a real bug (file.js:20)',
  'Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.',
  'Manifest check: pass',
  'Test-CI-wiring check: n/a - no new test files in diff',
  'Neutrality check: pass',
  'Sign-off withheld. The following must be resolved:',
  '- Critical: a real bug (file.js:20)',
].join('\n');

const NO_FINDINGS_SIGNOFF = [
  'Reviewed: hooks/subagent-stop-spawn-emit.js',
  'Findings: No findings.',
  'Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.',
  'Manifest check: pass',
  'Test-CI-wiring check: n/a - no new test files in diff',
  'Neutrality check: pass',
  'No unresolved Critical or Major findings. Sign-off granted.',
].join('\n');

// ---------------------------------------------------------------------------
console.log('\nTest 1: sidecar-hit-agent-and-source');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-001';
  const agentId = 'agentcal001';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'qa-engineer', toolUseId: 'toolu_sidecar_001', description: 'x', spawnDepth: 1,
  });
  const startTs = new Date(Date.now() - 3000).toISOString();
  appendRaw(cwd, hookSpawnStart(sessionId, 'spawn-cal-001', 'engineer', 'toolu_sidecar_001', startTs));
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert(complete.agent === 'qa-engineer', `agent === sidecar's agentType, not the spawn_start's stale "engineer" label (got: ${complete.agent})`);
    assert((complete.data || {}).agent_source === 'sidecar', `agent_source === "sidecar" (got: ${(complete.data || {}).agent_source})`);
    assert((complete.data || {}).paired_spawn_id === 'spawn-cal-001', 'paired via the sidecar toolUseId exact match');
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 2: sidecar-miss-falls-back-to-fifo');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-002';
  const agentId = 'agentcal002';
  // No sidecar file written at all.
  const startTs = new Date(Date.now() - 3000).toISOString();
  appendRaw(cwd, hookSpawnStart(sessionId, 'spawn-cal-002', 'skeptic', null, startTs));
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert(complete.agent === 'skeptic', `agent falls back to the matched spawn_start's agent (got: ${complete.agent})`);
    assert((complete.data || {}).agent_source === 'paired_start', `agent_source === "paired_start" (got: ${(complete.data || {}).agent_source})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 3: malformed-sidecar-invalid-json-never-blocks');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-003';
  const agentId = 'agentcal003';
  writeSidecarRaw(configDir, cwd, sessionId, agentId, 'not valid json {{{');
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0 despite malformed sidecar');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete still emitted with an invalid-JSON sidecar');
  if (complete) {
    assert(complete.agent === 'unknown', `agent falls back to "unknown" (got: ${complete.agent})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 4: malformed-sidecar-empty-file-never-blocks');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-004';
  const agentId = 'agentcal004';
  writeSidecarRaw(configDir, cwd, sessionId, agentId, '');
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0 despite empty sidecar file');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete still emitted with an empty sidecar file');
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 5: no-findings-yields-three-zeros');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-005';
  const agentId = 'agentcal005';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_005', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(NO_FINDINGS_SIGNOFF)]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const fc = (complete.data || {}).findings_count;
    assert(fc && fc.critical === 0 && fc.major === 0 && fc.minor === 0,
      `findings_count is explicit {0,0,0}, not absent (got: ${JSON.stringify(fc)})`);
    assert((complete.data || {}).signed_off === true, 'signed_off === true');
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 6: withheld-verdict');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-006';
  const agentId = 'agentcal006';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_006', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(WITHHELD_SIGNOFF)]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).signed_off === false, `signed_off === false (got: ${(complete.data || {}).signed_off})`);
    const fc = (complete.data || {}).findings_count;
    assert(fc && fc.critical === 1, `findings_count.critical === 1 (got: ${JSON.stringify(fc)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 7: no-verdict-yields-calibration-note');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-007';
  const agentId = 'agentcal007';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_007', description: 'x', spawnDepth: 1,
  });
  const noVerdictText = [
    'Reviewed: hooks/foo.js',
    'Findings: Critical: 0, Major: 0, Minor: 0',
    'Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.',
    // No "Sign-off granted." / "Sign-off withheld." literal anywhere.
  ].join('\n');
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(noVerdictText)]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).signed_off === undefined, 'signed_off absent when no verdict literal found');
    assert((complete.data || {}).findings_count === undefined, 'findings_count absent when no verdict literal found');
    assert(typeof (complete.data || {}).calibration_note === 'string' && (complete.data || {}).calibration_note.length > 0,
      `calibration_note is a non-empty string (got: ${JSON.stringify((complete.data || {}).calibration_note)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 8: multi-findings-tie-break');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-008';
  const agentId = 'agentcal008';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_008', description: 'x', spawnDepth: 1,
  });
  const multiFindingsText = [
    'Recall the required sign-off format:',
    'Findings: Critical: N, Major: N, Minor: N',
    '(fill in the actual counts below)',
    '',
    'Reviewed: hooks/foo.js',
    'Findings: Critical: 0, Major: 1, Minor: 2',
    '- Major - a real finding (file.js:5)',
    'Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.',
    'Manifest check: pass',
    'Test-CI-wiring check: n/a - no new test files in diff',
    'Neutrality check: pass',
    'No unresolved Critical or Major findings. Sign-off granted.',
  ].join('\n');
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(multiFindingsText)]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const fc = (complete.data || {}).findings_count;
    assert(fc && fc.major === 1 && fc.minor === 2,
      `the LAST Findings: line wins, not the templated first one (got: ${JSON.stringify(fc)})`);
    assert((complete.data || {}).findings_parse_ambiguous === true,
      `findings_parse_ambiguous === true (got: ${(complete.data || {}).findings_parse_ambiguous})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 9: decoy-earlier-message-ignored');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-009';
  const agentId = 'agentcal009';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_009', description: 'x', spawnDepth: 1,
  });
  const decoyEarlier = assistantRecord(GRANTED_SIGNOFF, { timestamp: new Date(Date.now() - 60000).toISOString() });
  const genuineLast = assistantRecord('Still investigating, no verdict yet - continuing the review.', {
    timestamp: new Date().toISOString(),
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [decoyEarlier, genuineLast]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).signed_off === undefined,
      `signed_off NOT taken from the earlier decoy message (got: ${(complete.data || {}).signed_off})`);
    assert(typeof (complete.data || {}).calibration_note === 'string' && (complete.data || {}).calibration_note.length > 0,
      'calibration_note set because the LAST message carries no verdict');
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 10: tuid-index-hit');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-010';
  const agentId = 'agentcal010';
  const toolUseId = 'toolu_cal_010';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId, description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(GRANTED_SIGNOFF)]);

  const agenticDir = path.join(cwd, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  const unitKey = 'feature-calib-test-abc1234567';
  // Round-3 fix (m2): pinned shape only - the legacy bare-string entry
  // plus live-state-file-read fallback is removed (see Test 10b below).
  fs.writeFileSync(path.join(agenticDir, 'skeptic-tuid-index.json'), JSON.stringify({
    [toolUseId]: { unit_key: unitKey, iteration: 2 },
  }));

  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).unit_key === unitKey, `unit_key === "${unitKey}" (got: ${(complete.data || {}).unit_key})`);
    assert((complete.data || {}).iteration === 2, `iteration === 2 (got: ${(complete.data || {}).iteration})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 10b: tuid-index-legacy-string-entry-is-a-miss (round-3, m2)');
{
  // Round-3 fix (m2): a legacy pre-round-2 bare-string index entry no
  // longer falls back to a live state-file read - it is now treated as a
  // miss like any other unresolvable entry, even when a matching
  // skeptic-round-*.json state file with a valid round_count exists.
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-010b';
  const agentId = 'agentcal010b';
  const toolUseId = 'toolu_cal_010b';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId, description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(GRANTED_SIGNOFF)]);

  const agenticDir = path.join(cwd, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  const unitKey = 'feature-calib-test-legacy-abc123';
  fs.writeFileSync(path.join(agenticDir, 'skeptic-tuid-index.json'), JSON.stringify({ [toolUseId]: unitKey }));
  fs.writeFileSync(path.join(agenticDir, `skeptic-round-${unitKey}.json`), JSON.stringify({
    round_count: 2, decision: null, unresolved_critical: false,
    last_round_fingerprint: null, last_decision_allow: true, last_decision_reason: '',
    tool_use_ids: [toolUseId], unit_key: unitKey,
  }));

  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).unit_key === undefined,
      `unit_key absent for a legacy bare-string entry, never live-read from state file (got: ${(complete.data || {}).unit_key})`);
    assert((complete.data || {}).iteration === undefined,
      `iteration absent for a legacy bare-string entry (got: ${(complete.data || {}).iteration})`);
    const note = (complete.data || {}).calibration_note;
    assert(typeof note === 'string' && note.indexOf('unit_key/iteration') !== -1,
      `calibration_note names the tuid-index miss for a legacy entry (got: ${JSON.stringify(note)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 10c: tuid-index-pinned-non-positive-iteration-is-a-miss (round-3, m2)');
{
  // Round-3 fix (m2): the `pinnedIteration > 0` guard is now exercised
  // directly - relaxing it to a bare not-null check must redden this test.
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-010c';
  const agentId = 'agentcal010c';
  const toolUseId = 'toolu_cal_010c';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId, description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(GRANTED_SIGNOFF)]);

  const agenticDir = path.join(cwd, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  fs.writeFileSync(path.join(agenticDir, 'skeptic-tuid-index.json'), JSON.stringify({
    [toolUseId]: { unit_key: 'feature-calib-test-zero-iter', iteration: 0 },
  }));

  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).unit_key === undefined,
      `unit_key absent when pinned iteration is 0 (got: ${(complete.data || {}).unit_key})`);
    assert((complete.data || {}).iteration === undefined,
      `iteration absent when pinned iteration is 0 (got: ${(complete.data || {}).iteration})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 11: tuid-index-miss-emits-note (round-2, M3)');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-011';
  const agentId = 'agentcal011';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_011', description: 'x', spawnDepth: 1,
  });
  // No skeptic-tuid-index.json written at all.
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(GRANTED_SIGNOFF)]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).unit_key === undefined, 'unit_key silently absent on a tuid-index miss');
    assert((complete.data || {}).iteration === undefined, 'iteration silently absent on a tuid-index miss');
    // Round-2 fix (M3): the plan's step 8 mandates a calibration_note
    // naming the miss on an omitted unit_key/iteration - a round-1
    // deliberate omission the Skeptic rejected. The note is a SHARED
    // field across all calibration misses on this completion (here also
    // including the unresolvable diff_lines, since this fixture's
    // transcript has no "Diff under review:" line in a user record).
    const note = (complete.data || {}).calibration_note;
    assert(typeof note === 'string' && note.indexOf('unit_key/iteration') !== -1,
      `calibration_note names the tuid-index miss (got: ${JSON.stringify(note)})`);
    assert((complete.data || {}).signed_off === true, 'signed_off still correctly emitted from the transcript');
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 11b: calibration-note-separator-pinned (round-3, m3)');
{
  // Round-3 fix (m3): the "; " join separator between calibration_note
  // clauses was previously asserted only via indexOf on one clause -
  // changing calibrationNoteParts.join('; ') to join(' / ') left the
  // suite green. This test pins the FULL string, byte-for-byte, with
  // exactly two known misses (tuid-index, diff_lines) and one known hit
  // (signed_off, via a real sign-off in the transcript).
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-011b';
  const agentId = 'agentcal011b';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_011b', description: 'x', spawnDepth: 1,
  });
  // No skeptic-tuid-index.json written at all (tuid-index miss).
  // No "Diff under review:" line in the transcript (diff_lines miss).
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(GRANTED_SIGNOFF)]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const d = complete.data || {};
    assert(d.signed_off === true, 'signed_off is a real hit, not a miss, in this fixture');
    const expected = 'unit_key/iteration: unavailable (tuid-index miss); '
      + 'diff_lines: unavailable (no spawn prompt found in transcript)';
    assert(d.calibration_note === expected,
      `calibration_note is exactly the two clauses joined by "; " (got: ${JSON.stringify(d.calibration_note)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 12: model-precedence-sidecar-wins');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-012';
  const agentId = 'agentcal012';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'engineer', toolUseId: 'toolu_cal_012', model: 'claude-opus-5', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [
    assistantRecord('doing work', { message: { role: 'assistant', model: 'claude-sonnet-5', content: [{ type: 'text', text: 'doing work' }], usage: { input_tokens: 5, output_tokens: 5, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 } } }),
  ]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).model === 'claude-opus-5',
      `model === sidecar's "claude-opus-5", NOT the transcript's "claude-sonnet-5" (got: ${(complete.data || {}).model})`);
    assert((complete.data || {}).model_note === undefined, 'no model_note when model is present');
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 13: model-precedence-transcript-fallback');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-013';
  const agentId = 'agentcal013';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'engineer', toolUseId: 'toolu_cal_013', description: 'x', spawnDepth: 1,
    // no model field on the sidecar
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord('doing work')]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).model === 'claude-sonnet-5',
      `model falls back to the transcript's value (got: ${(complete.data || {}).model})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 14: model-transcript-too-large-path');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-014';
  const agentId = 'agentcal014';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'engineer', toolUseId: 'toolu_cal_014', description: 'x', spawnDepth: 1,
  });
  const dir = subagentsDir(configDir, cwd, sessionId);
  const transcriptPath = path.join(dir, `agent-${agentId}.jsonl`);
  const filler = JSON.stringify(assistantRecord('x'.repeat(500))) + '\n';
  const targetBytes = 20 * 1024 * 1024 + 4096; // just over MAX_TRANSCRIPT_BYTES
  const fd = fs.openSync(transcriptPath, 'w');
  let written = 0;
  while (written < targetBytes) {
    fs.writeSync(fd, filler);
    written += filler.length;
  }
  fs.closeSync(fd);
  const sizeBefore = fs.statSync(transcriptPath).size;
  assert(sizeBefore >= 20 * 1024 * 1024, `fixture transcript exceeds MAX_TRANSCRIPT_BYTES (got ${sizeBefore} bytes)`);

  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).model === undefined, 'model absent on the too-large path');
    assert((complete.data || {}).model_note === 'skipped (transcript too large)',
      `model_note === "skipped (transcript too large)" (got: ${(complete.data || {}).model_note})`);
    assert((complete.data || {}).tokens === undefined, 'tokens also absent on the too-large path (same file, same skip)');
    assert((complete.data || {}).tokens_note === 'skipped (transcript too large)', 'tokens_note matches the same skip reason');
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 15: tokens-and-model-note-mutual-exclusion');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-015';
  const agentId = 'agentcal015';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'engineer', toolUseId: 'toolu_cal_015', description: 'x', spawnDepth: 1,
  });
  // A transcript that resolves and reads fine but has NO assistant records
  // at all - so both tokens and model must be reported absent-with-note.
  writeTranscript(configDir, cwd, sessionId, agentId, [
    { type: 'user', timestamp: new Date().toISOString(), message: { role: 'user', content: 'hi' } },
  ]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const d = complete.data || {};
    assert(d.tokens === undefined, 'tokens absent');
    assert(typeof d.tokens_note === 'string' && d.tokens_note.length > 0, 'tokens_note present as a non-empty string');
    assert(d.model === undefined, 'model absent');
    assert(typeof d.model_note === 'string' && d.model_note.length > 0, 'model_note present as a non-empty string');
    // Never both value and note for the same field.
    assert(!(('tokens' in d) && ('tokens_note' in d)), 'tokens and tokens_note never coexist');
    assert(!(('model' in d) && ('model_note' in d)), 'model and model_note never coexist');
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
// Round-2 (Skeptic findings M1-M5, m1, m2, m3, m5) test cases below.
// ---------------------------------------------------------------------------

console.log('\nTest 16: M1-agent-source-labels-provenance-not-pairing-tier-sidecar-toolUseId-only');
{
  // Sidecar carries a toolUseId (pairs via sidecar) but NO agentType - the
  // label must fall through to the matched spawn_start, and agent_source
  // must describe THAT (paired_start), not the pairing tier (sidecar).
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-016';
  const agentId = 'agentcal016';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    toolUseId: 'toolu_cal_016', description: 'x', spawnDepth: 1,
    // no agentType field
  });
  const startTs = new Date(Date.now() - 3000).toISOString();
  appendRaw(cwd, hookSpawnStart(sessionId, 'spawn-cal-016', 'engineer', 'toolu_cal_016', startTs));
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert(complete.agent === 'engineer', `agent falls back to the matched start's label (got: ${complete.agent})`);
    assert((complete.data || {}).agent_source === 'paired_start',
      `agent_source === "paired_start" - matches where the LABEL came from, not that the sidecar's toolUseId paired it (got: ${(complete.data || {}).agent_source})`);
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 17: M1-agent-source-labels-provenance-not-pairing-tier-agentType-only');
{
  // Sidecar carries agentType (labels via sidecar) but NO toolUseId - pairs
  // via FIFO instead, yet agent_source must still read "sidecar" because
  // that is where the LABEL came from.
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-017';
  const agentId = 'agentcal017';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'qa-engineer', description: 'x', spawnDepth: 1,
    // no toolUseId field
  });
  const startTs = new Date(Date.now() - 3000).toISOString();
  appendRaw(cwd, hookSpawnStart(sessionId, 'spawn-cal-017', 'engineer', null, startTs));
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert(complete.agent === 'qa-engineer', `agent === the sidecar's agentType (got: ${complete.agent})`);
    assert((complete.data || {}).agent_source === 'sidecar',
      `agent_source === "sidecar" - the label came from the sidecar even though pairing fell through to FIFO (got: ${(complete.data || {}).agent_source})`);
    assert((complete.data || {}).paired_spawn_id === 'spawn-cal-017', 'still paired via FIFO fallback');
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 18: M2-diff-lines-resolved-from-real-git-diff');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-018';
  const agentId = 'agentcal018';
  initGitRepo(cwd);
  gitCommit(cwd, 'file.txt', 'line1\nline2\nline3\n', 'initial');
  spawnSync('git', ['branch', 'feature'], { cwd });
  spawnSync('git', ['checkout', '-q', 'feature'], { cwd });
  gitCommit(cwd, 'file.txt', 'line1\nline2\nline3\nline4\nline5\n', 'add lines');
  spawnSync('git', ['checkout', '-q', '-'], { cwd }); // back to the default branch
  const defaultBranchRes = spawnSync('git', ['branch', '--show-current'], { cwd, encoding: 'utf8' });
  const defaultBranch = defaultBranchRes.stdout.trim();

  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_018', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [
    userRecord(`Review this.\n- **Diff under review:** git diff ${defaultBranch}...feature\n`),
    assistantRecord(GRANTED_SIGNOFF),
  ]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const d = complete.data || {};
    assert(d.diff_lines === 2, `diff_lines === 2 real added lines, measured by git diff --shortstat (got: ${JSON.stringify(d.diff_lines)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 19: M2-diff-lines-note-when-range-unresolvable');
{
  // A "Diff under review" line with a range that does not resolve in this
  // (non-git) cwd - must yield a calibration_note clause, never a
  // fabricated diff_lines value.
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-019';
  const agentId = 'agentcal019';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_019', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [
    userRecord('Review this.\n- **Diff under review:** git diff origin/main...feature/nonexistent\n'),
    assistantRecord(GRANTED_SIGNOFF),
  ]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const d = complete.data || {};
    assert(d.diff_lines === undefined, 'diff_lines absent when git diff cannot resolve the range (non-git cwd)');
    assert(typeof d.calibration_note === 'string' && d.calibration_note.indexOf('diff_lines') !== -1,
      `calibration_note names the diff_lines miss (got: ${JSON.stringify(d.calibration_note)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 20: M2-diff-lines-not-attempted-for-non-skeptic');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-020';
  const agentId = 'agentcal020';
  initGitRepo(cwd);
  gitCommit(cwd, 'file.txt', 'a\n', 'initial');
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'engineer', toolUseId: 'toolu_cal_020', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [
    userRecord('Implement this.\n- **Diff under review:** git diff main...feature\n'),
    assistantRecord('doing work'),
  ]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const d = complete.data || {};
    assert(d.diff_lines === undefined, 'diff_lines never attempted for a non-skeptic agent');
    assert(d.calibration_note === undefined, 'no calibration_note either - not applicable, not a miss');
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 21: m1-agent-note-on-attributionAgent-disagreement');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-021';
  const agentId = 'agentcal021';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'qa-engineer', toolUseId: 'toolu_cal_021', description: 'x', spawnDepth: 1,
  });
  // attributionAgent on the transcript records says "engineer", but the
  // sidecar's agentType says "qa-engineer" - a real disagreement.
  writeTranscript(configDir, cwd, sessionId, agentId, [
    assistantRecord('doing work', { attributionAgent: 'engineer' }),
  ]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert(complete.agent === 'qa-engineer', 'resolved agent is the sidecar label');
    const note = (complete.data || {}).agent_note;
    assert(typeof note === 'string' && note.indexOf('engineer') !== -1 && note.indexOf('qa-engineer') !== -1,
      `agent_note names both the disagreeing values (got: ${JSON.stringify(note)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 22: m1-no-agent-note-when-attribution-agrees');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-022';
  const agentId = 'agentcal022';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'qa-engineer', toolUseId: 'toolu_cal_022', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [
    assistantRecord('doing work', { attributionAgent: 'qa-engineer' }),
  ]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).agent_note === undefined, 'no agent_note when attributionAgent agrees with the resolved agent');
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 23: m5-signoff-tie-break-uses-last-literal-not-withheld-always-wins');
{
  // Both verdict literals appear in the last assistant message (e.g. the
  // Skeptic quoted skeptic.md's own sign-off-format section, which
  // contains both templates), with "Sign-off granted." appearing AFTER
  // "Sign-off withheld." - the real verdict is the LAST one, not
  // "withheld always wins whenever both are present."
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-023';
  const agentId = 'agentcal023';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_023', description: 'x', spawnDepth: 1,
  });
  const bothLiteralsText = [
    'Recall the sign-off format: "Sign-off withheld. The following must be resolved:" or',
    '"No unresolved Critical or Major findings. Sign-off granted."',
    '',
    'Reviewed: hooks/foo.js',
    'Findings: Critical: 0, Major: 0, Minor: 0',
    'Active search: I have applied the adversarial brief and actively searched for Critical and Major findings.',
    'Manifest check: pass',
    'Test-CI-wiring check: n/a - no new test files in diff',
    'Neutrality check: pass',
    'No unresolved Critical or Major findings. Sign-off granted.',
  ].join('\n');
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(bothLiteralsText)]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).signed_off === true,
      `signed_off === true - the LAST literal in the message is "granted" (got: ${(complete.data || {}).signed_off})`);
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 24: m2-iteration-zero-treated-as-miss');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-024';
  const agentId = 'agentcal024';
  const toolUseId = 'toolu_cal_024';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId, description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(GRANTED_SIGNOFF)]);

  const agenticDir = path.join(cwd, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  const unitKey = 'zero-round-unit-abc1234567';
  // Legacy (bare-string) index shape pointing at a state file whose
  // round_count is 0 - a legacy/hand-edited artifact, never written by the
  // round-cap hook itself on an allowed spawn.
  fs.writeFileSync(path.join(agenticDir, 'skeptic-tuid-index.json'), JSON.stringify({ [toolUseId]: unitKey }));
  fs.writeFileSync(path.join(agenticDir, `skeptic-round-${unitKey}.json`), JSON.stringify({
    round_count: 0, decision: null, unresolved_critical: false,
    last_round_fingerprint: null, last_decision_allow: true, last_decision_reason: '',
    tool_use_ids: [toolUseId], unit_key: unitKey,
  }));

  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const d = complete.data || {};
    assert(d.unit_key === undefined, 'unit_key absent when round_count is 0 (never a fabricated iteration)');
    assert(d.iteration === undefined, 'iteration absent when round_count is 0');
    assert(typeof d.calibration_note === 'string' && d.calibration_note.indexOf('unit_key/iteration') !== -1,
      `calibration_note names the miss (got: ${JSON.stringify(d.calibration_note)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 25: m3-iteration-uses-pinned-value-not-live-state');
{
  // Round-2 index shape: {unit_key, iteration} pinned at spawn time. The
  // LIVE state file's round_count has since advanced past the pinned
  // value (a later round completed, or the unit is mid-round) - the
  // emitted iteration must be the PINNED value, not the live one.
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-025';
  const agentId = 'agentcal025';
  const toolUseId = 'toolu_cal_025';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId, description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [assistantRecord(GRANTED_SIGNOFF)]);

  const agenticDir = path.join(cwd, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  const unitKey = 'pinned-iter-unit-abc1234567';
  fs.writeFileSync(path.join(agenticDir, 'skeptic-tuid-index.json'), JSON.stringify({
    [toolUseId]: { unit_key: unitKey, iteration: 1 },
  }));
  // Live state has since advanced to round 3 - must NOT be what's reported
  // for this (round-1) spawn's completion.
  fs.writeFileSync(path.join(agenticDir, `skeptic-round-${unitKey}.json`), JSON.stringify({
    round_count: 3, decision: null, unresolved_critical: false,
    last_round_fingerprint: null, last_decision_allow: true, last_decision_reason: '',
    tool_use_ids: [toolUseId], unit_key: unitKey,
  }));

  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const d = complete.data || {};
    assert(d.unit_key === unitKey, `unit_key === "${unitKey}" (got: ${d.unit_key})`);
    assert(d.iteration === 1, `iteration === 1 (the PINNED value at spawn time), NOT 3 (the live/advanced round_count) (got: ${d.iteration})`);
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 26: round4-m1-option-shaped-range-rejected-not-fabricated');
{
  // Round-4 regression test (M2): a "Diff under review" line whose range
  // is option-shaped to git (leading `-`) must be rejected before the
  // `git diff` subprocess call, not passed through as a real range - a
  // prompt-derived "-O/etc/passwd..HEAD" value would otherwise be
  // consumed by git as a flag and could report a fabricated `diff_lines:
  // 0` instead of a miss. Confirmed failing pre-fix (Mutation E: deleting
  // the `if (rangeArg.startsWith('-')) return ...` guard) reproduces
  // exactly that: {"diffLines":0,"diffLinesNote":null} - a fabricated
  // zero with no note.
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-026';
  const agentId = 'agentcal026';
  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_026', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [
    userRecord('Review this.\n- **Diff under review:** -O/etc/passwd..HEAD\n'),
    assistantRecord(GRANTED_SIGNOFF),
  ]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const d = complete.data || {};
    assert(d.diff_lines === undefined, 'diff_lines never fabricated for an option-shaped range');
    assert(typeof d.calibration_note === 'string' && d.calibration_note.indexOf('diff_lines') !== -1,
      `calibration_note names the diff_lines miss (got: ${JSON.stringify(d.calibration_note)})`);
    assert(d.calibration_note.indexOf('option-shaped') !== -1,
      `calibration_note distinguishes the rejected-shape cause from a plain absent-range miss (got: ${JSON.stringify(d.calibration_note)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 27: round4-wrong-note-rejected-shape-differs-from-absent-range');
{
  // Minor fix: the rejected-option-shape note (Test 26) must differ from
  // the plain "no range found" note (Test 19) - a range WAS found and
  // rejected in Test 26, vs. never found at all here. Conflating the two
  // makes the two miss classes indistinguishable in calibration_note.
  const cwdRejected = makeTmpDir('ae-calib-test-');
  const configDirRejected = makeTmpDir('ae-calib-config-');
  writeSidecar(configDirRejected, cwdRejected, 'sess-cal-027a', 'agentcal027a', {
    agentType: 'skeptic', toolUseId: 'toolu_cal_027a', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDirRejected, cwdRejected, 'sess-cal-027a', 'agentcal027a', [
    userRecord('Review this.\n- **Diff under review:** -O/etc/passwd..HEAD\n'),
    assistantRecord(GRANTED_SIGNOFF),
  ]);
  runHook(stopPayload(cwdRejected, 'sess-cal-027a', 'agentcal027a'), cwdRejected, configDirRejected);
  const rejectedNote = (readEvents(cwdRejected).find((e) => e.event === 'spawn_complete').data || {}).calibration_note;

  const cwdAbsent = makeTmpDir('ae-calib-test-');
  const configDirAbsent = makeTmpDir('ae-calib-config-');
  writeSidecar(configDirAbsent, cwdAbsent, 'sess-cal-027b', 'agentcal027b', {
    agentType: 'skeptic', toolUseId: 'toolu_cal_027b', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDirAbsent, cwdAbsent, 'sess-cal-027b', 'agentcal027b', [
    userRecord('Review this.\n- **Diff under review:** some free-form prose, no range here\n'),
    assistantRecord(GRANTED_SIGNOFF),
  ]);
  runHook(stopPayload(cwdAbsent, 'sess-cal-027b', 'agentcal027b'), cwdAbsent, configDirAbsent);
  const absentNote = (readEvents(cwdAbsent).find((e) => e.event === 'spawn_complete').data || {}).calibration_note;

  assert(typeof rejectedNote === 'string' && typeof absentNote === 'string',
    `both notes present (rejected: ${JSON.stringify(rejectedNote)}, absent: ${JSON.stringify(absentNote)})`);
  assert(rejectedNote !== absentNote,
    `rejected-shape note differs from absent-range note (rejected: ${JSON.stringify(rejectedNote)}, absent: ${JSON.stringify(absentNote)})`);
  cleanup(cwdRejected); cleanup(configDirRejected);
  cleanup(cwdAbsent); cleanup(configDirAbsent);
}

console.log('\nTest 28: round4-minor-tilde-caret-range-syntax-resolves');
{
  // Minor fix: `~` and `^` are ordinary git revision-suffix syntax
  // (`<sha>~1..<sha>`, `<sha>^..<sha>`) and must resolve, not be
  // rejected as NOTE_NO_RANGE by an overly narrow character class.
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-028';
  const agentId = 'agentcal028';
  initGitRepo(cwd);
  gitCommit(cwd, 'file.txt', 'line1\n', 'initial');
  gitCommit(cwd, 'file.txt', 'line1\nline2\n', 'second');
  const headRes = spawnSync('git', ['rev-parse', 'HEAD'], { cwd, encoding: 'utf8' });
  const head = headRes.stdout.trim();

  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_028', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [
    userRecord(`Review this.\n- **Diff under review:** ${head}~1..${head}\n`),
    assistantRecord(GRANTED_SIGNOFF),
  ]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const d = complete.data || {};
    assert(d.diff_lines === 1, `diff_lines === 1 for the tilde-suffixed range (got: ${JSON.stringify(d.diff_lines)})`);
    assert(d.calibration_note === undefined || d.calibration_note.indexOf('diff_lines') === -1,
      `no diff_lines miss reported (got: ${JSON.stringify(d.calibration_note)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

console.log('\nTest 29: round4-minor-caret-range-syntax-resolves');
{
  const cwd = makeTmpDir('ae-calib-test-');
  const configDir = makeTmpDir('ae-calib-config-');
  const sessionId = 'sess-cal-029';
  const agentId = 'agentcal029';
  initGitRepo(cwd);
  gitCommit(cwd, 'file.txt', 'line1\n', 'initial');
  gitCommit(cwd, 'file.txt', 'line1\nline2\n', 'second');
  const headRes = spawnSync('git', ['rev-parse', 'HEAD'], { cwd, encoding: 'utf8' });
  const head = headRes.stdout.trim();

  writeSidecar(configDir, cwd, sessionId, agentId, {
    agentType: 'skeptic', toolUseId: 'toolu_cal_029', description: 'x', spawnDepth: 1,
  });
  writeTranscript(configDir, cwd, sessionId, agentId, [
    userRecord(`Review this.\n- **Diff under review:** ${head}^..${head}\n`),
    assistantRecord(GRANTED_SIGNOFF),
  ]);
  const { status } = runHook(stopPayload(cwd, sessionId, agentId), cwd, configDir);
  assert(status === 0, 'hook exits 0');
  const complete = readEvents(cwd).find((e) => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const d = complete.data || {};
    assert(d.diff_lines === 1, `diff_lines === 1 for the caret-suffixed range (got: ${JSON.stringify(d.diff_lines)})`);
  }
  cleanup(cwd); cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);

// Reference so this file documents which sibling hook maintains the index
// consumed by Test 10/11 above, without importing it (the hook is a CLI
// script executed via subprocess by bin/tests/test_enforce_skeptic_round_cap.py,
// not a Node module).
void roundCapHookPath;
