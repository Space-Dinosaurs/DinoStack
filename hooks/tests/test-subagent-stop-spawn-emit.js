#!/usr/bin/env node
/**
 * Unit tests: subagent-stop-spawn-emit.js SubagentStop hook (DS-160).
 *
 * Test cases:
 *   1. emits-spawn-complete:        SubagentStop payload -> events.jsonl gets a
 *                                     spawn_complete event with source:"hook"
 *   2. no-stdout:                   hook produces no stdout
 *   3. exits-zero-malformed-stdin:  non-JSON stdin -> exit 0, no events.jsonl
 *   4. no-cwd-exits-cleanly:        payload missing cwd -> exit 0, no events.jsonl
 *   5. pairs-with-spawn-start:      a prior hook-emitted spawn_start in the same
 *                                    session -> spawn_complete's data.paired_spawn_id
 *                                    matches that spawn_start's data.spawn_id, and
 *                                    data.wall_seconds is a positive number
 *   6. unpaired-still-emits:        no prior spawn_start -> spawn_complete still
 *                                    emitted with paired_spawn_id:null,
 *                                    wall_seconds:null (never silently drops the event)
 *   7. skips-already-paired:        two prior spawn_starts, one already paired via
 *                                    an existing spawn_complete -> the new
 *                                    spawn_complete pairs to the UNPAIRED one, not
 *                                    the one already consumed
 *   8. session-scoped-matching:     a spawn_start from a DIFFERENT session_uuid is
 *                                    never matched, even if it is the only candidate
 *   9. creates-agentic-dir:         .agentic/ does not exist -> mkdir + events.jsonl
 *
 * Run with: node hooks/tests/test-subagent-stop-spawn-emit.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const hookPath = path.resolve(__dirname, '..', 'subagent-stop-spawn-emit.js');

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

function makeTmpProject() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'ae-subagent-stop-emit-test-'));
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

function runHook(payload, cwd, rawOverride) {
  const input = rawOverride !== undefined ? rawOverride : JSON.stringify(payload);
  const res = spawnSync('node', [hookPath], {
    input, cwd, timeout: 10000, encoding: 'utf8',
  });
  return { stdout: res.stdout || '', status: res.status };
}

function stopPayload(cwd, sessionId, overrides = {}) {
  return Object.assign({
    cwd,
    session_id: sessionId,
    hook_event_name: 'SubagentStop',
  }, overrides);
}

function readEvents(tmpDir) {
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');
  if (!fs.existsSync(eventsPath)) return [];
  return fs.readFileSync(eventsPath, 'utf8')
    .split('\n').filter(Boolean)
    .map(line => { try { return JSON.parse(line); } catch (_) { return null; } })
    .filter(Boolean);
}

function appendRaw(tmpDir, obj) {
  const agenticDir = path.join(tmpDir, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  fs.appendFileSync(path.join(agenticDir, 'events.jsonl'), JSON.stringify(obj) + '\n', 'utf8');
}

function hookSpawnStart(sessionId, spawnId, agent, tsOverride) {
  return {
    ts: tsOverride || new Date(Date.now() - 5000).toISOString(),
    phase: 'hook',
    event: 'spawn_start',
    agent: agent || 'engineer',
    task_id: null,
    data: { source: 'hook', session_uuid: sessionId, spawn_id: spawnId, tool_use_id: null, parent_agent_id: null, tokens_note: 'unavailable (harness)' },
  };
}

function hookSpawnComplete(sessionId, pairedSpawnId) {
  return {
    ts: new Date().toISOString(),
    phase: 'hook',
    event: 'spawn_complete',
    agent: 'engineer',
    task_id: null,
    data: { source: 'hook', session_uuid: sessionId, tool_use_id: null, agent_id: null, paired_spawn_id: pairedSpawnId, wall_seconds: 3, tokens_note: 'unavailable (harness)' },
  };
}

// ---------------------------------------------------------------------------
console.log('\nTest 1: emits-spawn-complete');
{
  const cwd = makeTmpProject();
  fs.mkdirSync(path.join(cwd, '.agentic'), { recursive: true });
  const { status } = runHook(stopPayload(cwd, 'sess-001'), cwd);
  assert(status === 0, 'hook exits 0');
  const events = readEvents(cwd);
  assert(events.length === 1, 'exactly one event appended');
  if (events.length >= 1) {
    assert(events[0].event === 'spawn_complete', `event === "spawn_complete" (got: ${events[0].event})`);
    assert(events[0].phase === 'hook', `phase === "hook" (got: ${events[0].phase})`);
    assert((events[0].data || {}).source === 'hook', 'data.source === "hook"');
  }
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
console.log('\nTest 2: no-stdout');
{
  const cwd = makeTmpProject();
  fs.mkdirSync(path.join(cwd, '.agentic'), { recursive: true });
  const { stdout, status } = runHook(stopPayload(cwd, 'sess-002'), cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout === '', `no stdout emitted (got: ${JSON.stringify(stdout)})`);
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
console.log('\nTest 3: exits-zero-malformed-stdin');
{
  const cwd = makeTmpProject();
  fs.mkdirSync(path.join(cwd, '.agentic'), { recursive: true });
  const { stdout, status } = runHook(null, cwd, 'not valid json {{{');
  assert(status === 0, 'exits 0 on malformed stdin');
  assert(stdout === '', 'no stdout on malformed stdin');
  const events = readEvents(cwd);
  assert(events.length === 0, 'no events emitted on malformed stdin');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
console.log('\nTest 4: no-cwd-exits-cleanly');
{
  const cwd = makeTmpProject();
  fs.mkdirSync(path.join(cwd, '.agentic'), { recursive: true });
  const payload = { session_id: 'sess-004', hook_event_name: 'SubagentStop' };
  const { status } = runHook(payload, cwd);
  assert(status === 0, 'exits 0 when cwd missing');
  const events = readEvents(cwd);
  assert(events.length === 0, 'no events when cwd missing');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
console.log('\nTest 5: pairs-with-spawn-start');
{
  const cwd = makeTmpProject();
  const startTs = new Date(Date.now() - 7000).toISOString();
  appendRaw(cwd, hookSpawnStart('sess-005', 'spawn-aaa', 'engineer', startTs));
  const { status } = runHook(stopPayload(cwd, 'sess-005'), cwd);
  assert(status === 0, 'hook exits 0');
  const events = readEvents(cwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    assert((complete.data || {}).paired_spawn_id === 'spawn-aaa',
      `paired_spawn_id === "spawn-aaa" (got: ${(complete.data || {}).paired_spawn_id})`);
    const wall = (complete.data || {}).wall_seconds;
    assert(typeof wall === 'number' && wall > 0, `wall_seconds is a positive number (got: ${wall})`);
    assert(complete.agent === 'engineer', `agent copied from matched spawn_start (got: ${complete.agent})`);
  }
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
console.log('\nTest 6: unpaired-still-emits');
{
  const cwd = makeTmpProject();
  fs.mkdirSync(path.join(cwd, '.agentic'), { recursive: true });
  const { status } = runHook(stopPayload(cwd, 'sess-006'), cwd);
  assert(status === 0, 'hook exits 0');
  const events = readEvents(cwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted even with no matching spawn_start');
  if (complete) {
    assert((complete.data || {}).paired_spawn_id === null, 'paired_spawn_id is null when unmatched');
    assert((complete.data || {}).wall_seconds === null, 'wall_seconds is null when unmatched');
  }
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
console.log('\nTest 7: skips-already-paired');
{
  const cwd = makeTmpProject();
  const t1 = new Date(Date.now() - 20000).toISOString();
  const t2 = new Date(Date.now() - 10000).toISOString();
  appendRaw(cwd, hookSpawnStart('sess-007', 'spawn-old', 'skeptic', t1));
  appendRaw(cwd, hookSpawnComplete('sess-007', 'spawn-old')); // already consumed
  appendRaw(cwd, hookSpawnStart('sess-007', 'spawn-new', 'engineer', t2));
  const { status } = runHook(stopPayload(cwd, 'sess-007'), cwd);
  assert(status === 0, 'hook exits 0');
  const events = readEvents(cwd);
  const completes = events.filter(e => e.event === 'spawn_complete');
  assert(completes.length === 2, 'two spawn_complete events total (one pre-seeded, one new)');
  const newComplete = completes[completes.length - 1];
  assert((newComplete.data || {}).paired_spawn_id === 'spawn-new',
    `new spawn_complete pairs to the unpaired spawn_start (got: ${(newComplete.data || {}).paired_spawn_id})`);
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
console.log('\nTest 8: session-scoped-matching');
{
  const cwd = makeTmpProject();
  appendRaw(cwd, hookSpawnStart('sess-other', 'spawn-wrong-session', 'engineer'));
  const { status } = runHook(stopPayload(cwd, 'sess-008'), cwd);
  assert(status === 0, 'hook exits 0');
  const events = readEvents(cwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete still emitted');
  if (complete) {
    assert((complete.data || {}).paired_spawn_id === null,
      `does not pair across sessions (got: ${(complete.data || {}).paired_spawn_id})`);
  }
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
console.log('\nTest 9: creates-agentic-dir');
{
  const cwd = makeTmpProject();
  assert(!fs.existsSync(path.join(cwd, '.agentic')), '.agentic/ does not exist before hook');
  const { status } = runHook(stopPayload(cwd, 'sess-009'), cwd);
  assert(status === 0, 'hook exits 0');
  assert(fs.existsSync(path.join(cwd, '.agentic')), '.agentic/ created by hook');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
