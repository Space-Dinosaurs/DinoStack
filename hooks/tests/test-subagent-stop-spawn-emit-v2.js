#!/usr/bin/env node
/**
 * DS-246 telemetry v2 tests for hooks/subagent-stop-spawn-emit.js and
 * hooks/pre-tool-use-spawn-emit.js. Hook-level cases drive the REAL hooks as
 * subprocesses against temp fixtures; run-boundary cases also call the
 * exported scanTranscript() in-process.
 *
 *   QA 1  worktree cwd -> spawn_complete lands in the primary checkout's
 *         events.jsonl, nothing in the worktree's.
 *   QA 2  agent_type '' / absent with no sidecar -> subagent_stop_internal
 *         only (no start consumed); an unresolvable real stop still emits a
 *         spawn_complete whose tokens_note names the tiers tried; a
 *         following engineer stop pairs by tool_use_id.
 *   QA 3  tokens == an independent python per-message.id dedupe with the
 *         5m/1h split; model is the resolved transcript id (not the sidecar
 *         alias, never <synthetic>), under a non-default CLAUDE_CONFIG_DIR
 *         and a worktree cwd resolved through the parent-session path.
 *   QA 4  task_id for architect/skeptic/qa-engineer/engineer spawns from a
 *         Skill invocation, a slash invocation with prose, and batch-state;
 *         veto and expiry notes after a plain-text ticket switch; the stop
 *         copies task_id from its paired start.
 *   QA 7a a resumed agent's 2nd stop: run_index 2, pair_method resume, wall
 *         from the resume boundary, run-only run_tokens; a mid-run
 *         compaction summary leaves run_index 1 with wall from the start; a
 *         qa-engineer FAIL run then PASS run each emit qa_result + task_id.
 *   Step 8 boundary cases (image-only, coordinator message, null-stop
 *         resume, cut-off re-prompt, no transcript), BLOCKED qa result,
 *         indented result lines, readRoundState primary-root fallback.
 *
 * Run with: node hooks/tests/test-subagent-stop-spawn-emit-v2.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const stopHook = path.resolve(__dirname, '..', 'subagent-stop-spawn-emit.js');
const startHook = path.resolve(__dirname, '..', 'pre-tool-use-spawn-emit.js');
const { scanTranscript, parseQaResult, isInternalAgent } = require(stopHook);

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

const NOW = Date.now();
const at = (secondsAgo) => new Date(NOW - secondsAgo * 1000).toISOString();

function usage(input, output, cacheRead, c5m, c1h) {
  return {
    input_tokens: input, output_tokens: output, cache_read_input_tokens: cacheRead,
    cache_creation_input_tokens: c5m + c1h,
    cache_creation: { ephemeral_5m_input_tokens: c5m, ephemeral_1h_input_tokens: c1h },
  };
}

/** One assistant chunk. opts: text, tool (bool), stop, u (usage), model. */
function asst(secondsAgo, id, opts = {}) {
  const content = [];
  if (opts.text) content.push({ type: 'text', text: opts.text });
  if (opts.tool) content.push({ type: 'tool_use', id: `tu_${id}`, name: 'Bash', input: {} });
  if (!content.length) content.push({ type: 'thinking', thinking: '' });
  return {
    type: 'assistant', timestamp: at(secondsAgo), attributionAgent: opts.agent,
    message: {
      id, role: 'assistant', model: opts.model || 'claude-opus-5-20260901',
      stop_reason: opts.stop === undefined ? null : opts.stop, content,
      usage: opts.u || usage(1, 1, 0, 0, 0),
    },
  };
}
const userText = (secondsAgo, text, extra = {}) => Object.assign(
  { type: 'user', timestamp: at(secondsAgo), message: { role: 'user', content: text } }, extra);
const toolResult = (secondsAgo) => ({
  type: 'user', timestamp: at(secondsAgo),
  message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'x', content: 'ok' }] },
});

function mkdtemp(prefix) {
  return fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
}

function cleanup(dir) {
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

function git(cwd, args) {
  return spawnSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.com', ...args], { cwd, encoding: 'utf8' });
}

/**
 * A sandbox: project root (plain dir, or a main checkout + linked worktree
 * when gitWorktree), a non-default config dir, and a parent-session
 * transcript directory OUTSIDE <config>/projects/<hash(cwd)> so only the
 * parent_session tier can find subagent files.
 */
function sandbox(sessionId, gitWorktree) {
  const tmp = mkdtemp('ae-v2-');
  const configDir = path.join(tmp, 'alt-config');
  const parentDir = path.join(configDir, 'projects', '-somewhere-else');
  fs.mkdirSync(path.join(parentDir, sessionId, 'subagents'), { recursive: true });
  const parentTranscript = path.join(parentDir, `${sessionId}.jsonl`);
  fs.writeFileSync(parentTranscript, '');
  let main = path.join(tmp, 'proj');
  let cwd = main;
  fs.mkdirSync(main);
  if (gitWorktree) {
    git(main, ['init', '-q']);
    git(main, ['commit', '-q', '--allow-empty', '-m', 'init']);
    cwd = path.join(tmp, 'wt');
    git(main, ['worktree', 'add', '-q', cwd, '-b', 'wt']);
  }
  return { tmp, configDir, parentDir, parentTranscript, main, cwd, sessionId };
}

function writeSub(sb, agentId, records, sidecar) {
  const dir = path.join(sb.parentDir, sb.sessionId, 'subagents');
  if (records) {
    fs.writeFileSync(path.join(dir, `agent-${agentId}.jsonl`), records.map((r) => JSON.stringify(r)).join('\n') + '\n');
  }
  if (sidecar) fs.writeFileSync(path.join(dir, `agent-${agentId}.meta.json`), JSON.stringify(sidecar));
  return path.join(dir, `agent-${agentId}.jsonl`);
}

function env(sb) {
  return Object.assign({}, process.env, { CLAUDE_CONFIG_DIR: sb.configDir, AGENTIC_CONFIG_DIR: '' });
}

function runStop(sb, agentId, extra = {}) {
  const payload = Object.assign({
    cwd: sb.cwd, session_id: sb.sessionId, agent_id: agentId, agent_type: 'engineer',
    transcript_path: sb.parentTranscript, hook_event_name: 'SubagentStop',
  }, extra);
  return spawnSync('node', [stopHook], { input: JSON.stringify(payload), cwd: sb.cwd, env: env(sb), encoding: 'utf8', timeout: 15000 });
}

function runStart(sb, toolUseId, subagentType, description) {
  const payload = {
    tool_name: 'Agent', cwd: sb.cwd, session_id: sb.sessionId, tool_use_id: toolUseId,
    transcript_path: sb.parentTranscript,
    tool_input: { subagent_type: subagentType, description, prompt: 'p' },
  };
  return spawnSync('node', [startHook], { input: JSON.stringify(payload), cwd: sb.cwd, env: env(sb), encoding: 'utf8', timeout: 15000 });
}

function eventsAt(root) {
  const p = path.join(root, '.agentic', 'events.jsonl');
  if (!fs.existsSync(p)) return [];
  return fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

function seed(root, rows) {
  fs.mkdirSync(path.join(root, '.agentic'), { recursive: true });
  fs.appendFileSync(path.join(root, '.agentic', 'events.jsonl'), rows.map((r) => JSON.stringify(r)).join('\n') + '\n');
}

function hookStart(sessionId, spawnId, agent, secondsAgo, toolUseId, taskId = null) {
  return {
    ts: at(secondsAgo), phase: 'hook', event: 'spawn_start', agent, task_id: taskId,
    data: { source: 'hook', telemetry_v: 2, session_uuid: sessionId, spawn_id: spawnId, tool_use_id: toolUseId },
  };
}

function hookComplete(sessionId, spawnId, agent, secondsAgo) {
  return {
    ts: at(secondsAgo), phase: 'hook', event: 'spawn_complete', agent, task_id: null,
    data: { source: 'hook', telemetry_v: 2, session_uuid: sessionId, paired_spawn_id: spawnId, run_index: 1 },
  };
}

const last = (rows, event) => rows.filter((e) => e.event === event).pop();
const near = (x, want, tol) => typeof x === 'number' && Math.abs(x - want) <= tol;

// ---------------------------------------------------------------------------
console.log('\nQA 1: a worktree SubagentStop lands in the primary checkout');
{
  const sb = sandbox('sess-qa1', true);
  seed(sb.main, [hookStart(sb.sessionId, 'sp1', 'engineer', 30, 'toolu_qa1')]);
  writeSub(sb, 'aqa1', [asst(20, 'm1', { text: 'done', stop: 'end_turn' })], { agentType: 'engineer', toolUseId: 'toolu_qa1' });
  const mainBefore = eventsAt(sb.main).length;
  const wtBefore = eventsAt(sb.cwd).length;
  runStop(sb, 'aqa1');
  const mainAfter = eventsAt(sb.main);
  console.log(`    evidence: main events.jsonl lines ${mainBefore} -> ${mainAfter.length}; worktree ${wtBefore} -> ${eventsAt(sb.cwd).length}`);
  assert(mainAfter.length === mainBefore + 1 && mainAfter[mainAfter.length - 1].event === 'spawn_complete',
    'exactly one spawn_complete appended to the MAIN checkout events.jsonl');
  assert(!fs.existsSync(path.join(sb.cwd, '.agentic', 'events.jsonl')), "nothing written to the worktree's events.jsonl");
  const c = last(mainAfter, 'spawn_complete');
  assert(c.data.paired_spawn_id === 'sp1' && c.data.pair_method === 'tool_use_id',
    `pairs to the main-root start by tool_use_id (got ${c.data.paired_spawn_id}/${c.data.pair_method})`);
  assert(c.data.telemetry_v === 2, 'row is telemetry_v 2');
  cleanup(sb.tmp);
}

// ---------------------------------------------------------------------------
console.log('\nQA 2: internal agents, unresolvable stops, then a real pairing');
{
  const sb = sandbox('sess-qa2', false);
  seed(sb.main, [hookStart(sb.sessionId, 'spE', 'engineer', 60, 'toolu_eng')]);
  runStop(sb, 'internal1', { agent_type: '' });
  runStop(sb, 'internal2', { agent_type: undefined });
  runStop(sb, 'lost1', { agent_type: 'investigator' });
  writeSub(sb, 'eng1', [asst(10, 'm1', { text: 'ok', stop: 'end_turn' })], { agentType: 'engineer', toolUseId: 'toolu_eng' });
  runStop(sb, 'eng1', { agent_type: 'engineer' });
  const rows = eventsAt(sb.main).slice(1);
  console.log(`    evidence: ${JSON.stringify(rows.map((r) => [r.event, r.agent, r.data.reason || r.data.tokens_note || r.data.paired_spawn_id]))}`);
  assert(rows.length === 4, `four rows appended (got ${rows.length})`);
  assert(rows[0].event === 'subagent_stop_internal' && rows[0].data.reason === 'agent_type empty, no sidecar'
    && rows[0].data.agent_id === 'internal1', "agent_type '' with no sidecar -> subagent_stop_internal only");
  assert(rows[1].event === 'subagent_stop_internal' && rows[1].data.reason === 'agent_type absent, no sidecar',
    'absent agent_type with no sidecar -> subagent_stop_internal only');
  assert(rows[2].event === 'spawn_complete' && rows[2].agent === 'investigator' && rows[2].data.paired_spawn_id === null
    && /transcript not found; tried: parent_session, cwd_hash, scan/.test(rows[2].data.tokens_note)
    && /tried:/.test(rows[2].data.model_note),
  `unresolvable real stop still emits spawn_complete with the tiers tried (got ${rows[2].data.tokens_note})`);
  assert(rows[3].event === 'spawn_complete' && rows[3].data.paired_spawn_id === 'spE' && rows[3].data.pair_method === 'tool_use_id',
    'the following engineer stop pairs by tool_use_id - the internal stops consumed no start');
  cleanup(sb.tmp);
}
assert(isInternalAgent({ agent_type: null }, null) === true, 'isInternalAgent: null agent_type counts as empty');
assert(isInternalAgent({ agent_type: '' }, '/x/agent-a.meta.json') === false, 'isInternalAgent: a sidecar makes it real');

// ---------------------------------------------------------------------------
console.log('\nQA 3: deduped tokens, 5m/1h split and resolved model');
{
  const sb = sandbox('sess-qa3', true);
  seed(sb.main, [hookStart(sb.sessionId, 'sp3', 'engineer', 120, 'toolu_qa3')]);
  const transcript = writeSub(sb, 'aqa3', [
    asst(110, 'msg_a', { model: '<synthetic>', u: usage(0, 0, 0, 0, 0) }),
    asst(100, 'msg_b', { u: usage(3, 5, 1000, 200, 300) }),
    asst(99, 'msg_b', { tool: true, u: usage(3, 5, 1000, 200, 300) }),
    asst(98, 'msg_b', { tool: true, stop: 'tool_use', u: usage(3, 405, 1000, 200, 300) }),
    toolResult(97),
    asst(90, 'msg_c', { text: 'done', stop: 'end_turn', u: usage(2, 50, 1500, 40, 0) }),
  ], { agentType: 'engineer', toolUseId: 'toolu_qa3', model: 'opus' });
  runStop(sb, 'aqa3');
  const c = last(eventsAt(sb.main), 'spawn_complete');
  const py = spawnSync('python3', ['-c', `
import json,sys
last={}
for line in open(sys.argv[1]):
    r=json.loads(line)
    if r.get('type')!='assistant': continue
    m=r['message']; u=m.get('usage')
    if u: last[m['id']]=u
t=dict(input=0,output=0,cache_creation=0,cache_read=0,cache_creation_5m=0,cache_creation_1h=0)
for u in last.values():
    t['input']+=u['input_tokens']; t['output']+=u['output_tokens']
    t['cache_read']+=u['cache_read_input_tokens']; t['cache_creation']+=u['cache_creation_input_tokens']
    t['cache_creation_5m']+=u['cache_creation']['ephemeral_5m_input_tokens']
    t['cache_creation_1h']+=u['cache_creation']['ephemeral_1h_input_tokens']
print(json.dumps(t,sort_keys=True))`, transcript], { encoding: 'utf8' });
  const expected = JSON.parse(py.stdout);
  const got = c.data.tokens || {};
  const gotSorted = JSON.stringify(Object.keys(got).sort().reduce((o, k) => { o[k] = got[k]; return o; }, {}));
  console.log(`    evidence: hook tokens ${gotSorted}; python ${JSON.stringify(expected)}; model ${c.data.model} (${c.data.model_source}); transcript_source ${c.data.transcript_source}`);
  assert(gotSorted === JSON.stringify(expected), 'hook tokens equal the independent python per-message.id recomputation');
  assert(got.output === 455 && got.cache_read === 2500, 'the repeated msg_b usage counted once (output 405 + 50)');
  assert(c.data.model === 'claude-opus-5-20260901' && c.data.model_source === 'transcript',
    'model is the resolved transcript id, not the sidecar alias "opus" or <synthetic>');
  assert(c.data.transcript_source === 'parent_session', 'transcript found via the parent-session path under a worktree cwd');
  cleanup(sb.tmp);
}

// ---------------------------------------------------------------------------
console.log('\nQA 4: task_id for every spawn type, and the staleness guards');
{
  const sb = sandbox('sess-qa4', false);
  const tr = (records) => fs.appendFileSync(sb.parentTranscript, records.map((r) => JSON.stringify(r)).join('\n') + '\n');
  const agentUse = (id, description) => ({
    type: 'assistant', timestamp: at(1),
    message: { role: 'assistant', content: [{ type: 'tool_use', id, name: 'Agent', input: { description } }] },
  });
  tr([{ type: 'assistant', timestamp: at(50), message: { role: 'assistant', content: [
    { type: 'tool_use', id: 'toolu_skill', name: 'Skill', input: { skill: 'ds-implement-ticket', args: 'AUT-983' } }] } }]);
  const types = ['architect', 'skeptic', 'qa-engineer', 'engineer'];
  for (const t of types) {
    tr([agentUse(`tu_${t}`, `${t} pass`)]);
    runStart(sb, `tu_${t}`, t, `${t} pass`);
  }
  let starts = eventsAt(sb.main).filter((e) => e.event === 'spawn_start');
  console.log(`    evidence (Skill): ${JSON.stringify(starts.map((e) => [e.agent, e.task_id, e.data.task_id_source]))}`);
  assert(starts.length === 4 && starts.every((e) => e.task_id === 'AUT-983' && e.data.task_id_source === 'invocation'
    && e.data.telemetry_v === 2), 'Skill invocation: all four spawn types carry task_id AUT-983 (invocation)');

  tr([userText(40, '<command-name>/ds-implement-ticket</command-name>\n<command-args>AUT-990 and keep the diff small</command-args>')]);
  runStart(sb, 'tu_slash', 'engineer', 'implement');
  tr([agentUse('tu_switch', 'AUT-991 architect')]);
  runStart(sb, 'tu_switch', 'architect', 'AUT-991 architect');
  tr([agentUse('tu_after', 'Skeptic review')]);
  runStart(sb, 'tu_after', 'skeptic', 'Skeptic review');
  fs.writeFileSync(path.join(sb.main, '.agentic', 'batch-state.json'), JSON.stringify({
    session_id: sb.sessionId, status: 'active', tickets: [{ ticket_id: 'AUT-995', status: 'in_progress' }],
  }));
  runStart(sb, 'tu_batch', 'qa-engineer', 'QA');
  starts = eventsAt(sb.main).filter((e) => e.event === 'spawn_start').slice(4);
  console.log(`    evidence (slash/veto/expiry/batch): ${JSON.stringify(starts.map((e) => [e.agent, e.task_id, e.data.task_id_source, e.data.task_id_note || null]))}`);
  assert(starts[0].task_id === 'AUT-990' && starts[0].data.task_id_source === 'invocation', 'slash invocation with trailing prose resolves');
  assert(starts[1].task_id === null && starts[1].data.task_id_note === 'invocation_vetoed:AUT-991', 'a spawn naming only another key is vetoed');
  assert(starts[2].task_id === null && starts[2].data.task_id_note === 'invocation_expired:AUT-991', 'a later keyless spawn is expired');
  assert(starts[3].task_id === 'AUT-995' && starts[3].data.task_id_source === 'batch_state', 'active batch-state wins');

  writeSub(sb, 'aarch', [asst(5, 'm1', { text: 'plan', stop: 'end_turn' })], { agentType: 'architect', toolUseId: 'tu_architect', description: 'architect pass' });
  runStop(sb, 'aarch', { agent_type: 'architect' });
  const c = last(eventsAt(sb.main), 'spawn_complete');
  assert(c.task_id === 'AUT-983' && c.data.task_id_source === 'paired_start', 'the stop copies task_id from its paired start');
  cleanup(sb.tmp);
}

// ---------------------------------------------------------------------------
console.log('\nQA 7a: resumed runs, compaction, and per-run QA results');
{
  const sb = sandbox('sess-qa7', false);
  // Run 1: start 300s ago, first stop recorded 200s ago. Run 2 resumes at
  // 60s ago; idle time 200s..60s must not count toward run 2's wall.
  seed(sb.main, [
    hookStart(sb.sessionId, 'spR', 'engineer', 300, 'toolu_res', 'AUT-7'),
    hookComplete(sb.sessionId, 'spR', 'engineer', 200),
  ]);
  writeSub(sb, 'ares', [
    userText(299, 'initial brief'),
    asst(290, 'r1a', { tool: true, stop: 'tool_use', u: usage(10, 10, 100, 50, 0) }),
    toolResult(285),
    asst(205, 'r1b', { text: 'run 1 done', stop: 'end_turn', u: usage(10, 20, 200, 0, 0) }),
    userText(60, 'please also fix X', { isMeta: true }),
    asst(40, 'r2a', { text: 'run 2 done', stop: 'end_turn', u: usage(5, 7, 300, 0, 25) }),
  ], { agentType: 'engineer', toolUseId: 'toolu_res' });
  runStop(sb, 'ares');
  const c = last(eventsAt(sb.main), 'spawn_complete');
  console.log(`    evidence: run_index ${c.data.run_index}, pair_method ${c.data.pair_method}, run_start_ts ${c.data.run_start_ts}, wall ${c.data.wall_seconds}, run_tokens ${JSON.stringify(c.data.run_tokens)}, task_id ${c.task_id}`);
  assert(c.data.run_index === 2 && c.data.pair_method === 'resume', 'second stop: run_index 2, pair_method resume');
  assert(c.data.run_start_ts === at(60), 'run_start_ts is the resume boundary');
  assert(near(c.data.wall_seconds, 60, 5), `wall measured from the resume boundary (~60s, got ${c.data.wall_seconds})`);
  assert(c.data.run_tokens && c.data.run_tokens.output === 7 && c.data.run_tokens.cache_creation_1h === 25
    && c.data.tokens.output === 37, 'run_tokens holds run 2 only; tokens stays cumulative');
  assert(c.task_id === 'AUT-7', 'task_id copied from the paired start');
  cleanup(sb.tmp);
}
{
  const sb = sandbox('sess-qa7c', false);
  seed(sb.main, [hookStart(sb.sessionId, 'spC', 'engineer', 120, 'toolu_cmp')]);
  writeSub(sb, 'acmp', [
    userText(119, 'brief'),
    asst(110, 'c1', { tool: true, stop: 'tool_use' }),
    toolResult(100),
    userText(95, 'This session is being continued from a previous conversation...', { isCompactSummary: true }),
    asst(80, 'c2', { text: 'done', stop: 'end_turn' }),
  ], { agentType: 'engineer', toolUseId: 'toolu_cmp' });
  runStop(sb, 'acmp');
  const c = last(eventsAt(sb.main), 'spawn_complete');
  console.log(`    evidence (compaction): run_index ${c.data.run_index}, run_start_ts ${c.data.run_start_ts}, wall ${c.data.wall_seconds}`);
  assert(c.data.run_index === 1 && c.data.run_start_ts === at(120) && near(c.data.wall_seconds, 120, 5),
    'a mid-run compaction summary does not start a run: run_index 1, wall from the start');
  cleanup(sb.tmp);
}
{
  const sb = sandbox('sess-qa7q', false);
  fs.appendFileSync(sb.parentTranscript, JSON.stringify(userText(400,
    '<command-name>/ds-implement-ticket</command-name><command-args>AUT-42</command-args>')) + '\n');
  runStart(sb, 'toolu_qa', 'qa-engineer', 'QA pass');
  const sub = writeSub(sb, 'aqa', [
    userText(300, 'verify'),
    asst(250, 'q1', { stop: 'end_turn', text: 'Report.\n```yaml\nresult: FAIL\ncriteria:\n  - id: 1\n    result: PASS\nblocking_count: 2\n```' }),
  ], { agentType: 'qa-engineer', toolUseId: 'toolu_qa' });
  runStop(sb, 'aqa', { agent_type: 'qa-engineer' });
  // The resume happens after the first stop was recorded, in real time.
  const later = (ms) => ({ timestamp: new Date(Date.now() + ms).toISOString() });
  fs.appendFileSync(sub, [
    Object.assign(userText(0, 'fixed, re-verify', { isMeta: true }), later(0)),
    Object.assign(asst(0, 'q2', { stop: 'end_turn', text: '```yaml\nresult: PASS\ncriteria:\n  - id: 1\n    result: FAIL\nblocking_count: 0\n```' }), later(1)),
  ].map((r) => JSON.stringify(r)).join('\n') + '\n');
  runStop(sb, 'aqa', { agent_type: 'qa-engineer' });
  const qa = eventsAt(sb.main).filter((e) => e.event === 'spawn_complete');
  console.log(`    evidence: ${JSON.stringify(qa.map((e) => [e.agent, e.task_id, e.data.run_index, e.data.qa_result, e.data.qa_blocking_count]))}`);
  assert(qa.length === 2, 'two qa-engineer runs, two spawn_complete rows');
  assert(qa[0].data.qa_result === 'FAIL' && qa[0].data.qa_blocking_count === 2 && qa[0].data.run_index === 1,
    'run 1 records FAIL with blocking_count 2 (indented criteria results ignored)');
  assert(qa[1].data.qa_result === 'PASS' && qa[1].data.qa_blocking_count === 0 && qa[1].data.run_index === 2,
    "run 2 records PASS from its own text, not run 1's");
  assert(qa.every((e) => e.task_id === 'AUT-42'), 'both runs carry task_id AUT-42');
  cleanup(sb.tmp);
}

// ---------------------------------------------------------------------------
console.log('\nStep 8: run-boundary edge cases (scanTranscript)');
function scanOf(records, priorSecondsAgo) {
  const dir = mkdtemp('ae-v2-scan-');
  const p = path.join(dir, 'agent-x.jsonl');
  fs.writeFileSync(p, records.map((r) => JSON.stringify(r)).join('\n') + '\n');
  const out = scanTranscript(p, priorSecondsAgo === null ? null : at(priorSecondsAgo));
  cleanup(dir);
  return out;
}
{
  const img = scanOf([
    userText(100, 'brief'), asst(90, 'a', { tool: true, stop: 'tool_use' }), toolResult(85),
    userText(84, '[Image: original 100x100, displayed at 100x100.]', { isMeta: true }),
    { type: 'user', timestamp: at(83), message: { role: 'user', content: [{ type: 'image', source: {} }] } },
    asst(70, 'b', { text: 'done', stop: 'end_turn' }),
  ], null);
  assert(img.runStartTs === null && img.lastText === 'done', 'image-only records never start a run');

  const coord = scanOf([
    userText(100, 'brief'), asst(90, 'a', { text: 'finished', stop: 'end_turn' }),
    userText(89, 'The coordinator sent a message while you were working: ...', { isMeta: true }),
    asst(80, 'b', { text: 'ack', stop: 'end_turn' }),
  ], null);
  assert(coord.runStartTs === null && coord.lastText === 'ack', 'end_turn + coordinator message with no prior completion: still run 1');

  const nullStop = scanOf([
    userText(100, 'brief'), asst(90, 'a', { tool: true, stop: 'tool_use' }), toolResult(88),
    asst(80, 'b', { text: 'final answer', stop: null }),
    userText(30, 'resume please', { isMeta: true }),
    asst(20, 'c', { text: 'run 2 answer', stop: 'end_turn', u: usage(1, 9, 0, 0, 0) }),
  ], 70);
  assert(nullStop.runStartTs === at(30) && nullStop.lastText === 'run 2 answer' && nullStop.runTokens.output === 9,
    `a null-stop final text followed by a resume starts run 2 at the resume (got ${nullStop.runStartTs})`);

  const cutOff = scanOf([
    userText(100, 'brief'), asst(90, 'a', { text: 'partial', stop: null }),
    userText(89, 'Your response above was cut off mid-stream. Continue.', { isMeta: true }),
    asst(80, 'b', { text: 'complete', stop: 'end_turn' }),
  ], null);
  assert(cutOff.runStartTs === null && cutOff.lastText === 'complete', 'a cut-off re-prompt does not start a run');

  const compactOnResume = scanOf([
    userText(100, 'brief'), asst(90, 'a', { text: 'done', stop: 'end_turn' }),
    userText(40, 'Summary of earlier work', { isCompactSummary: true }),
    userText(39, 'resume', { isMeta: true }),
    asst(20, 'b', { text: 'again', stop: 'end_turn' }),
  ], 60);
  assert(compactOnResume.runStartTs === at(39), 'a compaction record before the resume is transparent; the resume is the boundary');

  const noBoundary = scanOf([userText(100, 'brief'), asst(90, 'a', { tool: true, stop: 'tool_use' }), toolResult(80)], 50);
  assert(noBoundary.runStartTs === null && noBoundary.runTokens === null, 'no boundary after the prior completion: runStartTs and runTokens null');
}
{
  const sb = sandbox('sess-s8', false);
  seed(sb.main, [
    hookStart(sb.sessionId, 'spN', 'engineer', 300, 'toolu_n'),
    hookComplete(sb.sessionId, 'spN', 'engineer', 200),
  ]);
  writeSub(sb, 'an', null, { agentType: 'engineer', toolUseId: 'toolu_n' });
  runStop(sb, 'an');
  const c = last(eventsAt(sb.main), 'spawn_complete');
  assert(c.data.run_index === 2 && c.data.wall_seconds === null && c.data.wall_note === 'unavailable (transcript not found)',
    `no transcript, one prior completion: run_index 2, wall null with a note (got ${c.data.run_index}/${c.data.wall_seconds})`);
  cleanup(sb.tmp);
}

// ---------------------------------------------------------------------------
console.log('\nQA result parsing and Skeptic round-state fallback');
{
  const blocked = parseQaResult('```yaml\nresult: BLOCKED\nblocking_count: 1\n```');
  assert(blocked.qaResult === 'BLOCKED', 'BLOCKED is recorded (an overall result per qa-engineer.md)');
  assert(parseQaResult('```yaml\nresult: PARTIAL\n```').qaResult === 'PARTIAL', 'PARTIAL is recorded');
  assert(parseQaResult('  result: PASS\n').qaResultNote !== undefined, 'an indented result line alone is not a run result');
  assert(parseQaResult('result: PASS\nlater:\nresult: FAIL\n').qaResult === 'FAIL', 'the last top-level result line wins');
}
{
  const sb = sandbox('sess-rs', true);
  fs.mkdirSync(path.join(sb.main, '.agentic'), { recursive: true });
  fs.writeFileSync(path.join(sb.main, '.agentic', 'skeptic-tuid-index.json'),
    JSON.stringify({ toolu_sk: { unit_key: 'DS-1-u1', iteration: 2 } }));
  writeSub(sb, 'ask', [asst(5, 'm', { text: 'Findings: No findings.\nSign-off granted.', stop: 'end_turn' })],
    { agentType: 'skeptic', toolUseId: 'toolu_sk' });
  runStop(sb, 'ask', { agent_type: 'skeptic' });
  const c = last(eventsAt(sb.main), 'spawn_complete');
  assert(c.data.unit_key === 'DS-1-u1' && c.data.iteration === 2,
    'readRoundState falls back to the primary root when the worktree root has no index');
  assert(c.data.signed_off === true, 'Skeptic sign-off parsed from the run text');
  cleanup(sb.tmp);
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
