#!/usr/bin/env node
/**
 * Unit + integration tests: hooks/lib/spawn-events.js (DS-246).
 *
 *   - spawnEventsPath resolves a linked worktree cwd to the PRIMARY
 *     checkout's .agentic/events.jsonl.
 *   - readSessionEventsRaw merges only this session's primary-root hook
 *     spawn rows into the cwd-root file, ts-sorted; passes the cwd file
 *     through untouched when the roots agree; null when both are absent.
 *   - streamLines offsets, partial trailing line, flushTail.
 *   - QA 8: in a session rooted in a linked worktree, the real Stop hook's
 *     session_total counts spawns whose rows live at the primary root (and
 *     sums v2 per-run walls), and the real PostToolUse capture nudge fires
 *     for a debugger spawn_complete written to the primary root.
 *
 * Run with: node hooks/tests/test-spawn-events.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const { spawnEventsPath, readSessionEventsRaw, streamLines } = require(
  path.resolve(__dirname, '..', 'lib', 'spawn-events.js'));
const stopContextPath = path.resolve(__dirname, '..', 'stop-context.js');
const nudgePath = path.resolve(__dirname, '..', 'post-tool-use-capture-nudge.js');

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

function git(cwd, args) {
  return spawnSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.com', ...args],
    { cwd, encoding: 'utf8' });
}

/** A temp main checkout plus one linked worktree. */
function makeRepoWithWorktree() {
  const tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ae-spawn-events-')));
  const main = path.join(tmp, 'main');
  const wt = path.join(tmp, 'wt');
  fs.mkdirSync(main);
  git(main, ['init', '-q']);
  git(main, ['commit', '-q', '--allow-empty', '-m', 'init']);
  git(main, ['worktree', 'add', '-q', wt, '-b', 'wt']);
  fs.mkdirSync(path.join(main, '.agentic'), { recursive: true });
  fs.mkdirSync(path.join(wt, '.agentic'), { recursive: true });
  return { tmp, main, wt };
}

function row(ts, event, session, extra = {}, agent = 'engineer') {
  return JSON.stringify({ ts, phase: 'hook', event, agent, task_id: null,
    data: Object.assign({ source: 'hook', session_uuid: session }, extra) });
}

function cleanup(dir) {
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

// ---------------------------------------------------------------------------
console.log('\nspawnEventsPath');
{
  const { tmp, main, wt } = makeRepoWithWorktree();
  assert(spawnEventsPath(path.join(wt)) === path.join(main, '.agentic', 'events.jsonl'),
    'a linked worktree cwd resolves to the primary checkout events file');
  assert(spawnEventsPath(main) === path.join(main, '.agentic', 'events.jsonl'),
    'the main checkout resolves to itself');
  const plain = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ae-plain-')));
  assert(spawnEventsPath(plain) === path.join(plain, '.agentic', 'events.jsonl'),
    'a non-git cwd falls back to its own root');
  cleanup(plain);
  cleanup(tmp);
}

// ---------------------------------------------------------------------------
console.log('\nreadSessionEventsRaw');
{
  const { tmp, main, wt } = makeRepoWithWorktree();
  const S = 'sess-merge';
  fs.writeFileSync(path.join(wt, '.agentic', 'events.jsonl'), [
    row('2026-09-20T10:00:01.000Z', 'session_total', S),
    row('2026-09-20T10:00:05.000Z', 'tool_failure_workaround', S),
  ].join('\n') + '\n');
  fs.writeFileSync(path.join(main, '.agentic', 'events.jsonl'), [
    row('2026-09-20T10:00:03.000Z', 'spawn_start', S, { spawn_id: 'a' }),
    row('2026-09-20T10:00:04.000Z', 'spawn_start', 'other-session', { spawn_id: 'b' }),
    JSON.stringify({ ts: '2026-09-20T10:00:04.500Z', event: 'spawn_complete', agent: 'x', data: { source: 'conductor', session_uuid: S } }),
    row('2026-09-20T10:00:06.000Z', 'session_total', S),
    row('2026-09-20T10:00:07.000Z', 'spawn_complete', S, { paired_spawn_id: 'a' }),
    '{truncated',
  ].join('\n') + '\n');
  const merged = readSessionEventsRaw(wt, S).split('\n').filter(Boolean).map((l) => JSON.parse(l));
  const shape = merged.map((e) => `${e.ts.slice(17, 19)}:${e.event}`);
  assert(JSON.stringify(shape) === JSON.stringify(
    ['01:session_total', '03:spawn_start', '05:tool_failure_workaround', '07:spawn_complete']),
  `merges only this session's primary-root hook spawn rows, ts-sorted (got ${JSON.stringify(shape)})`);

  const cwdOnly = fs.readFileSync(path.join(main, '.agentic', 'events.jsonl'), 'utf8');
  assert(readSessionEventsRaw(main, S) === cwdOnly, 'same root: the cwd file is returned verbatim');
  assert(readSessionEventsRaw(wt, null) === fs.readFileSync(path.join(wt, '.agentic', 'events.jsonl'), 'utf8'),
    'no session id: no merge');
  fs.rmSync(path.join(wt, '.agentic', 'events.jsonl'));
  const mainOnly = readSessionEventsRaw(wt, S).split('\n').filter(Boolean);
  assert(mainOnly.length === 2, `cwd file absent: the session's primary rows alone (got ${mainOnly.length})`);
  fs.rmSync(path.join(main, '.agentic', 'events.jsonl'));
  assert(readSessionEventsRaw(wt, S) === null, 'both files absent: null');
  cleanup(tmp);
}

// ---------------------------------------------------------------------------
console.log('\nstreamLines');
{
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-stream-'));
  const f = path.join(dir, 'x.jsonl');
  fs.writeFileSync(f, 'one\ntwo\nthr');
  const seen = [];
  const res = streamLines(f, 0, (l) => seen.push(l));
  assert(JSON.stringify(seen) === '["one","two"]', `terminated lines delivered, partial held back (got ${JSON.stringify(seen)})`);
  assert(res.endOffset === 8 && res.size === 11, `endOffset stops after the last newline (got ${res.endOffset}/${res.size})`);
  const resumed = [];
  fs.appendFileSync(f, 'ee\n');
  streamLines(f, res.endOffset, (l) => resumed.push(l));
  assert(JSON.stringify(resumed) === '["three"]', 'resuming from endOffset yields the completed line');
  const tail = [];
  fs.appendFileSync(f, 'four');
  streamLines(f, 0, (l) => tail.push(l), { flushTail: true });
  assert(tail[tail.length - 1] === 'four', 'flushTail delivers an unterminated final line');
  const big = 'y'.repeat(3 * 1024 * 1024);
  fs.writeFileSync(f, `a\n${big}\nb\n`);
  const lens = [];
  streamLines(f, 0, (l) => lens.push(l.length));
  assert(JSON.stringify(lens) === JSON.stringify([1, big.length, 1]), 'a line spanning several 1 MiB chunks is reassembled');
  assert(streamLines(path.join(dir, 'missing'), 0, () => {}) === null, 'a missing file returns null');
  cleanup(dir);
}

// ---------------------------------------------------------------------------
console.log('\nQA 8: worktree-rooted session sees primary-root spawn rows');
{
  const { tmp, main, wt } = makeRepoWithWorktree();
  const S = 'sess-qa8';
  const fakeHome = path.join(tmp, 'home');
  fs.mkdirSync(path.join(fakeHome, '.agentic'), { recursive: true });
  const now = Date.now();
  const iso = (dt) => new Date(now + dt).toISOString();
  fs.writeFileSync(path.join(main, '.agentic', 'events.jsonl'), [
    row(iso(-60000), 'spawn_start', S, { spawn_id: 'e1' }),
    row(iso(-50000), 'spawn_complete', S, { paired_spawn_id: 'e1', telemetry_v: 2, run_index: 1, wall_seconds: 10 }),
    row(iso(-20000), 'spawn_complete', S, { paired_spawn_id: 'e1', telemetry_v: 2, run_index: 2, wall_seconds: 5 }),
    row(iso(-10000), 'spawn_start', S, { spawn_id: 'd1' }, 'debugger'),
    row(iso(-5000), 'spawn_complete', S, { paired_spawn_id: 'd1', telemetry_v: 2, run_index: 1, wall_seconds: 4 }, 'debugger'),
  ].join('\n') + '\n');
  const wtEvents = path.join(wt, '.agentic', 'events.jsonl');
  assert(!fs.existsSync(wtEvents), 'the worktree has no events.jsonl of its own before the Stop hook');

  const env = { ...process.env, HOME: fakeHome, AGENTIC_CONFIG_DIR: fakeHome, CLAUDE_CONFIG_DIR: fakeHome };
  // The in-session nudge runs first: the Stop hook's own backstop advances
  // the shared capture-gap cursor past the event once it fires.
  const nudge = spawnSync('node', [nudgePath], {
    input: JSON.stringify({ cwd: wt, session_id: S, tool_name: 'Agent', tool_response: { status: 'async_launched' } }),
    env, encoding: 'utf8', timeout: 20000,
  });
  let out = null;
  try { out = JSON.parse(nudge.stdout); } catch (_) { out = null; }
  assert(!!(out && out.hookSpecificOutput && /CAPTURE-NUDGE/.test(out.hookSpecificOutput.additionalContext)),
    `capture-gap nudge fires from the primary-root debugger spawn_complete (stdout: ${JSON.stringify((nudge.stdout || '').slice(0, 120))})`);

  spawnSync('node', [stopContextPath, '--cadence=turn'], {
    input: JSON.stringify({ cwd: wt, session_id: S, transcript: [] }), env, encoding: 'utf8', timeout: 20000,
  });
  const total = fs.existsSync(wtEvents)
    ? fs.readFileSync(wtEvents, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
      .filter((e) => e.event === 'session_total').pop()
    : null;
  assert(!!total, 'the Stop hook wrote a session_total at the worktree root');
  if (total) {
    assert(total.data.spawn_count === 2, `session_total.spawn_count counts the 2 primary-root spawns (got ${total.data.spawn_count})`);
    assert(total.data.wall_seconds === 19,
      `session_total.wall_seconds sums v2 run walls 10 + 5 + 4 (got ${total.data.wall_seconds})`);
  }
  assert(fs.existsSync(path.join(wt, '.agentic', '.capture-gap-last-sweep')),
    "the Stop hook's capture-gap backstop fired (its sweep cursor was written at the worktree root)");
  cleanup(tmp);
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
