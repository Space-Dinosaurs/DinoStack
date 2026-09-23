#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/active-ticket.js (DS-246 mechanical task_id).
 *
 * Covers the tier order (batch_state, invocation, none), argument
 * tokenization, the veto and expiry staleness guards, the incremental scan
 * cache (corrupt, concurrent, appended), and two fixtures shaped on real
 * sessions where the operator switched tickets in plain text.
 *
 * Run with: node hooks/tests/test-active-ticket.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const libPath = path.resolve(__dirname, '..', 'lib', 'active-ticket.js');
const { resolveActiveTicket, invocationKeys, descriptionKeys } = require(libPath);

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

function eq(actual, expected, message) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  assert(a === e, `${message} (expected ${e}, got ${a})`);
}

const SID = 'sess-ticket-1';
let clock = Date.parse('2026-09-20T10:00:00.000Z');
function ts() {
  clock += 1000;
  return new Date(clock).toISOString();
}

const slash = (args) => ({
  type: 'user', timestamp: ts(),
  message: { role: 'user', content: `<command-message>ds-implement-ticket</command-message>\n<command-name>/ds-implement-ticket</command-name>\n<command-args>${args}</command-args>` },
});
const skill = (args) => ({
  type: 'assistant', timestamp: ts(),
  message: { role: 'assistant', content: [{ type: 'tool_use', id: `toolu_skill_${clock}`, name: 'Skill', input: { skill: 'ds-implement-ticket', args } }] },
});
const spawnUse = (id, description, name = 'Agent') => ({
  type: 'assistant', timestamp: ts(),
  message: { role: 'assistant', content: [{ type: 'tool_use', id, name, input: { description, subagent_type: 'engineer', prompt: 'p' } }] },
});
const say = (text) => ({ type: 'user', timestamp: ts(), message: { role: 'user', content: text } });

function fixture(records) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-active-ticket-'));
  const agenticDir = path.join(dir, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  const transcriptPath = path.join(dir, `${SID}.jsonl`);
  fs.writeFileSync(transcriptPath, records.map((r) => JSON.stringify(r)).join('\n') + '\n');
  return { dir, agenticDir, transcriptPath };
}

function append(fx, records) {
  fs.appendFileSync(fx.transcriptPath, records.map((r) => JSON.stringify(r)).join('\n') + '\n');
}

function resolve(fx, toolUseId, spawnDescription) {
  return resolveActiveTicket({
    agenticDir: fx.agenticDir, sessionId: SID, transcriptPath: fx.transcriptPath, toolUseId, spawnDescription,
  });
}

function cleanup(fx) {
  try { fs.rmSync(fx.dir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

// ---------------------------------------------------------------------------
console.log('\nTokenization');
eq(invocationKeys('AUT-983'), ['AUT-983'], 'bare key');
eq(invocationKeys('AUT-983 please also check the login flow'), ['AUT-983'], 'slash args with trailing prose');
eq(invocationKeys('AUT-983, AUT-984'), ['AUT-983', 'AUT-984'], 'comma-separated multi-key');
eq(invocationKeys('AUT-983 max_wallclock_min=90 goal_mode=open_goal'), ['AUT-983'], 'trailing key=value tokens stripped');
eq(invocationKeys('https://solara6.atlassian.net/browse/DS-246'), ['DS-246'], 'Jira /browse/ URL');
eq(invocationKeys('https://github.com/o/r/issues/42'), ['#42'], 'GitHub /issues/ URL maps to #N');
eq(invocationKeys('#42'), ['#42'], '#N form');
eq(invocationKeys('(AUT-983).'), ['AUT-983'], 'surrounding punctuation trimmed');
eq(descriptionKeys('Skeptic AUT-858 round 2 (see AUT-872)'), ['AUT-858', 'AUT-872'], 'description keys');
eq(descriptionKeys('Skeptic round 2'), [], 'description with no key');

// ---------------------------------------------------------------------------
console.log('\nTier order and invocation shapes');
{
  const fx = fixture([slash('AUT-100'), spawnUse('toolu_a', 'AUT-100 architect')]);
  fs.writeFileSync(path.join(fx.agenticDir, 'batch-state.json'), JSON.stringify({
    session_id: SID, status: 'active',
    tickets: [{ ticket_id: 'AUT-7', status: 'done' }, { ticket_id: 'AUT-8', status: 'in_progress' }],
  }));
  eq(resolve(fx, 'toolu_b', 'engineer'), { ticketId: 'AUT-8', source: 'batch_state', note: null },
    'batch-state in_progress ticket beats the invocation');
  fs.writeFileSync(path.join(fx.agenticDir, 'batch-state.json'), JSON.stringify({
    session_id: 'another-session', status: 'active', tickets: [{ ticket_id: 'AUT-8', status: 'in_progress' }],
  }));
  eq(resolve(fx, 'toolu_b', 'engineer').ticketId, 'AUT-100', 'a foreign batch is ignored');
  fs.writeFileSync(path.join(fx.agenticDir, 'batch-state.json'), JSON.stringify({
    session_id: SID, status: 'interrupted', tickets: [{ ticket_id: 'AUT-8', status: 'in_progress' }],
  }));
  eq(resolve(fx, 'toolu_b', 'engineer').ticketId, 'AUT-100', 'an inactive batch is ignored');
  fs.writeFileSync(path.join(fx.agenticDir, 'batch-state.json'), JSON.stringify({
    session_id: SID, status: 'active',
    tickets: [{ ticket_id: 'AUT-8', status: 'in_progress' }, { ticket_id: 'AUT-9', status: 'in_progress' }],
  }));
  eq(resolve(fx, 'toolu_b', 'engineer').source, 'invocation', 'two in_progress batch tickets fall through to the invocation');
  cleanup(fx);
}
{
  const fx = fixture([say('go'), skill('AUT-983')]);
  eq(resolve(fx, 'toolu_x', 'Architect plan'), { ticketId: 'AUT-983', source: 'invocation', note: null },
    'Skill tool_use invocation resolves');
  cleanup(fx);
}
{
  const fx = fixture([slash('AUT-983 also mind the flaky login test')]);
  eq(resolve(fx, 'toolu_x', '').ticketId, 'AUT-983', 'slash invocation with trailing prose resolves');
  cleanup(fx);
}
{
  const fx = fixture([slash('AUT-1 AUT-2')]);
  eq(resolve(fx, 'toolu_x', ''), { ticketId: null, source: 'none', note: 'invocation_ambiguous:AUT-1,AUT-2' },
    'multi-key args give none plus a note');
  cleanup(fx);
}
{
  const fx = fixture([slash('')]);
  eq(resolve(fx, 'toolu_x', '').note, 'invocation_no_key', 'keyless args give none plus a note');
  cleanup(fx);
}
{
  const fx = fixture([say('hello'), spawnUse('toolu_a', 'look around')]);
  eq(resolve(fx, 'toolu_b', ''), { ticketId: null, source: 'none', note: 'no_invocation' }, 'no invocation gives none');
  cleanup(fx);
}
eq(resolveActiveTicket({ agenticDir: os.tmpdir(), sessionId: SID, transcriptPath: '/nonexistent/x.jsonl' }),
  { ticketId: null, source: 'none', note: 'no_transcript' }, 'missing transcript gives none');
eq(resolveActiveTicket({ agenticDir: os.tmpdir(), sessionId: SID, transcriptPath: null }).note, 'no_transcript',
  'no transcript path gives none');

// ---------------------------------------------------------------------------
console.log('\nStaleness guards');
{
  const fx = fixture([slash('AUT-100'), spawnUse('toolu_a', 'AUT-100 architect plan')]);
  eq(resolve(fx, 'toolu_b', 'Skeptic round 1').ticketId, 'AUT-100', 'a description without keys is credited');
  eq(resolve(fx, 'toolu_b', 'AUT-100 engineer, see AUT-99').ticketId, 'AUT-100', 'a description naming T among others is credited');
  eq(resolve(fx, 'toolu_b', 'AUT-200 engineer'), { ticketId: null, source: 'none', note: 'invocation_vetoed:AUT-200' },
    'veto: a description naming only another key is not credited');

  append(fx, [say('ok, AUT-200 then'), spawnUse('toolu_c', 'AUT-200 architect')]);
  eq(resolve(fx, 'toolu_c', 'AUT-200 architect').note, 'invocation_vetoed:AUT-200', 'the vetoed spawn itself reports the veto');
  eq(resolve(fx, 'toolu_d', 'Skeptic round 1'), { ticketId: null, source: 'none', note: 'invocation_expired:AUT-200' },
    'expiry: a later keyless spawn is not credited once a spawn named another key');

  append(fx, [skill('AUT-300')]);
  eq(resolve(fx, 'toolu_e', 'Skeptic round 1').ticketId, 'AUT-300', 'a new invocation clears the expiry');
  cleanup(fx);
}
{
  // The spawn's own tool_use is already in the transcript and names another
  // key; excluded from expiry, it still reaches the veto only via its own
  // description - with an empty description it is credited.
  const fx = fixture([slash('AUT-100'), spawnUse('toolu_self', 'AUT-555 note')]);
  eq(resolve(fx, 'toolu_self', '').ticketId, 'AUT-100', "the spawn's own tool_use is excluded from expiry");
  eq(resolve(fx, 'toolu_other', '').note, 'invocation_expired:AUT-555', 'the same tool_use does expire other spawns');
  cleanup(fx);
}

// ---------------------------------------------------------------------------
console.log('\nSession-shaped fixtures');
{
  // 1b4d3786 shape: /ds-implement-ticket AUT-848, then the operator moves
  // to AUT-858 and AUT-872 in plain text with no new invocation. Each spawn
  // is resolved when issued, as the PreToolUse hook does.
  const fx = fixture([slash('AUT-848')]);
  const steps = [
    [[], 't1', 'AUT-848 architect plan', 'AUT-848'],
    [[spawnUse('t1', 'AUT-848 architect plan')], 't2', 'Skeptic plan review', 'AUT-848'],
    [[spawnUse('t2', 'Skeptic plan review'), say('great. now AUT-858')], 't3', 'AUT-858 architect plan', null],
    [[spawnUse('t3', 'AUT-858 architect plan')], 't4', 'Skeptic plan review', null],
    [[spawnUse('t4', 'Skeptic plan review'), say('and AUT-872')], 't5', 'AUT-872 engineer', null],
    [[spawnUse('t5', 'AUT-872 engineer')], 't6', 'QA', null],
  ];
  const got = steps.map(([records, id, desc]) => {
    if (records.length) append(fx, records);
    return resolve(fx, id, desc).ticketId;
  });
  eq(got, steps.map((s) => s[3]), '1b4d3786 replay: credited before the switch, none after');
  cleanup(fx);
}
{
  // 523b5075 shape: AUT-891 invoked; a keyless investigator before the
  // switch is credited; after "AUT-895 then" nothing is, until a Skill
  // invocation of AUT-897.
  const fx = fixture([slash('AUT-891')]);
  const steps = [
    [[], 'i1', 'Investigate import failure', 'AUT-891'],
    [[spawnUse('i1', 'Investigate import failure'), say('AUT-895 then')], 'i2', 'AUT-895 architect', null],
    [[spawnUse('i2', 'AUT-895 architect')], 'i3', 'Investigate flaky test', null],
    [[spawnUse('i3', 'Investigate flaky test'), skill('AUT-897')], 'i4', 'AUT-897 engineer', 'AUT-897'],
    [[spawnUse('i4', 'AUT-897 engineer')], 'i5', 'Run QA', 'AUT-897'],
  ];
  const got = steps.map(([records, id, desc]) => {
    if (records.length) append(fx, records);
    return resolve(fx, id, desc).ticketId;
  });
  eq(got, steps.map((s) => s[3]), '523b5075 replay: stale AUT-891 never credited after the switch');
  cleanup(fx);
}

// ---------------------------------------------------------------------------
console.log('\nScan cache');
{
  const fx = fixture([slash('AUT-100')]);
  resolve(fx, 't', '');
  const cachePath = path.join(fx.agenticDir, `.ticket-scan-${SID}.json`);
  const cache = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
  assert(cache.offset === fs.statSync(fx.transcriptPath).size, 'cache offset advances to the end of the scanned transcript');
  eq(cache.invocation && cache.invocation.key, 'AUT-100', 'cache records the invocation');

  append(fx, [skill('AUT-200')]);
  eq(resolve(fx, 't', '').ticketId, 'AUT-200', 'an appended invocation is picked up incrementally');

  fs.writeFileSync(cachePath, '{not json');
  eq(resolve(fx, 't', '').ticketId, 'AUT-200', 'a corrupt cache is treated as absent (full rescan)');
  fs.writeFileSync(cachePath, JSON.stringify({ path: fx.transcriptPath, offset: 10 ** 9, invocation: null, expired_by: [] }));
  eq(resolve(fx, 't', '').ticketId, 'AUT-200', 'a cache offset past EOF triggers a rescan');

  // Partial trailing line: not consumed, so it is read once complete.
  fs.appendFileSync(fx.transcriptPath, JSON.stringify(skill('AUT-300')).slice(0, 40));
  eq(resolve(fx, 't', '').ticketId, 'AUT-200', 'a partial trailing line is not consumed');
  cleanup(fx);
}
{
  const fx = fixture([slash('AUT-100'), spawnUse('toolu_a', 'AUT-100 architect')]);
  const script = `const r=require(${JSON.stringify(libPath)}).resolveActiveTicket({agenticDir:${JSON.stringify(fx.agenticDir)},sessionId:${JSON.stringify(SID)},transcriptPath:${JSON.stringify(fx.transcriptPath)},toolUseId:'x',spawnDescription:''});process.stdout.write(r.ticketId||'none');`;
  const procs = Array.from({ length: 8 }, () => new Promise((res) => {
    const child = spawn('node', ['-e', script]);
    let out = '';
    child.stdout.on('data', (d) => { out += d; });
    child.on('close', () => res(out));
  }));
  Promise.all(procs).then((outs) => {
    assert(outs.every((o) => o === 'AUT-100'), `8 concurrent resolvers all resolve AUT-100 (got ${outs.join(',')})`);
    const cachePath = path.join(fx.agenticDir, `.ticket-scan-${SID}.json`);
    let valid = false;
    try { valid = !!JSON.parse(fs.readFileSync(cachePath, 'utf8')).invocation; } catch (_) { valid = false; }
    assert(valid, 'cache is valid JSON after concurrent writes');
    const leftovers = fs.readdirSync(fx.agenticDir).filter((f) => f.includes('.tmp-'));
    eq(leftovers, [], 'no tmp files left behind');
    cleanup(fx);
    finish();
  });
}

function finish() {
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}
