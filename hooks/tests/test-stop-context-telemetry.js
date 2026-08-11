#!/usr/bin/env node
/**
 * Unit tests: stop-context.js telemetry changes (Unit A of events-emission-fix).
 *
 * Tests the following via the shim-load pattern used by test-capture-gap.js:
 *   - scanSessionAggregate(): hook spawn_start counting (ad-hoc guard),
 *     double-count guard (skip hook starts when spawn_complete present),
 *     conductor_direct no longer counted.
 *   - writeSessionTotal() bootstrap: always creates events.jsonl even when no
 *     qualifying events exist (zero-aggregate fallback).
 *
 * Also tests capture-gap revival via hook spawn_start:
 *   - hooks/lib/capture-gap.js detectCaptureGap() fires for debugger/investigator
 *     hook spawn_start (revives trigger in ad-hoc sessions).
 *
 * Test cases:
 *   1. bootstrap-creates-events-jsonl:     Stop hook run on empty project ->
 *                                           events.jsonl created with session_total
 *   2. hook-spawn-start-counted-ad-hoc:   ad-hoc session (no spawn_complete) ->
 *                                           hook spawn_start counted in aggregate
 *   3. double-count-guard:                 session WITH spawn_complete ->
 *                                           hook spawn_starts skipped
 *   4. conductor-direct-not-counted:       conductor_direct events are excluded
 *   5. spawn-complete-still-counted:       spawn_complete still contributes wall/tokens
 *   6. capture-gap-hook-investigator:      hook spawn_start investigator ->
 *                                           detectCaptureGap fires (worthy)
 *   7. capture-gap-hook-debugger:          hook spawn_start debugger -> worthy
 *   8. capture-gap-hook-skeptic-degraded:  hook spawn_start skeptic -> NOT worthy
 *                                           (skeptic-findings trigger stays degraded)
 *   9. ticketed-session-hook-complete-not-double-counted (DS-160 Critical): a
 *      conductor spawn_complete PLUS a hook-emitted spawn_complete for the
 *      SAME spawn -> counted once, not twice.
 *  10. ad-hoc-lost-subagent-stop-still-counts (DS-160 Critical): an ad-hoc
 *      session with one completed spawn and one spawn whose SubagentStop
 *      never fired -> both spawns counted, not silently dropped.
 *  11. adhoc-no-session-id-unpaired-complete-not-double-counted (DS-160
 *      round-2 Major 1): an unpaired hook spawn_complete (paired_spawn_id:
 *      null, e.g. emitted when the SubagentStop payload carried no
 *      session_id) co-present with a real spawn_start for the same visible
 *      spawn -> counted once (via the spawn_start), not twice.
 *  12. paired-complete-resolves-to-nothing-not-double-counted (DS-160
 *      round-2 Major 1): a spawn_complete whose paired_spawn_id does not
 *      match any spawn_start in this session's view (e.g. the hook's own
 *      2MB tail window missed it) -> dropped as completion metadata, does
 *      NOT create a new spawn count.
 *
 * Run with: node hooks/tests/test-stop-context-telemetry.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

// ---------------------------------------------------------------------------
// Shim-load stop-context.js (same technique as test-capture-gap.js)
// ---------------------------------------------------------------------------

const hookPath = path.resolve(__dirname, '..', 'stop-context.js');
const hookSource = fs.readFileSync(hookPath, 'utf8');

const libDirAbs = path.resolve(__dirname, '..', 'lib');
const libCaptureGapAbs = path.join(libDirAbs, 'capture-gap.js');

// GENERIC re-anchor via hooks/tests/lib/hook-shim.js. This replaced a
// hand-maintained per-library .replace() chain plus a survivor assertion, which
// meant every new hooks/lib module broke this file (and four siblings) with a
// FATAL naming the file to patch - exactly what adding hooks/lib/context-rollup.js
// did. skill-candidate-detector is deliberately NOT rewritten: it is required
// lazily inside a function, and its code path is gated on a config toggle that is
// off by default in a temp dir with no config.json.
const { reanchorHookRequires } = require('./lib/hook-shim.js');

let shimmedSource;
try {
  shimmedSource = reanchorHookRequires(
    // Match both the old bare `run();` call and the current
    // `run().catch(() => { ... });` form (stop-context.js now reads stdin via
    // the async readStdinGuarded() and needs a .catch() at the call site).
    hookSource.replace(/^run\(\).*;\s*$/m, '// test shim: run() suppressed'),
    libDirAbs
  ) + `\n
if (typeof module !== 'undefined') {
  module.exports = {
    scanSessionAggregate,
    writeSessionTotal,
    detectCaptureGap: require(${JSON.stringify(libCaptureGapAbs)}).detectCaptureGap,
  };
}
`;
} catch (shimErr) {
  console.error('  FATAL: ' + shimErr.message);
  process.exit(1);
}

const tmpShimPath = path.join(os.tmpdir(), `stop-ctx-tel-shim-${Date.now()}.js`);
fs.writeFileSync(tmpShimPath, shimmedSource, 'utf8');
let helpers;
try {
  helpers = require(tmpShimPath);
} finally {
  try { fs.unlinkSync(tmpShimPath); } catch (_) { /* ignore */ }
}

const { scanSessionAggregate, writeSessionTotal, detectCaptureGap } = helpers;

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

function makeTmpProject() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-stop-tel-'));
  fs.mkdirSync(path.join(tmpDir, '.agentic'), { recursive: true });
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

function makeSpawnComplete(agent, sessionId, wallSeconds, tokens) {
  return JSON.stringify({
    ts: new Date().toISOString(),
    phase: 'spawn',
    event: 'spawn_complete',
    agent,
    task_id: 'T-1',
    data: {
      session_uuid: sessionId,
      wall_seconds: wallSeconds || 10,
      tokens: tokens || { input: 100, output: 50, cache_creation: 0, cache_read: 0 },
    },
  });
}

function makeHookSpawnStart(agent, sessionId, spawnId) {
  return JSON.stringify({
    ts: new Date().toISOString(),
    phase: 'hook',
    event: 'spawn_start',
    agent,
    task_id: null,
    data: {
      source: 'hook',
      session_uuid: sessionId,
      tokens_note: 'unavailable (harness)',
      spawn_id: spawnId || undefined,
      tool_use_id: null,
      parent_agent_id: null,
    },
  });
}

function makeHookSpawnComplete(agent, sessionId, pairedSpawnId, wallSeconds) {
  return JSON.stringify({
    ts: new Date().toISOString(),
    phase: 'hook',
    event: 'spawn_complete',
    agent,
    task_id: null,
    data: {
      source: 'hook',
      session_uuid: sessionId,
      tool_use_id: null,
      agent_id: null,
      paired_spawn_id: pairedSpawnId || null,
      wall_seconds: wallSeconds === undefined ? 3 : wallSeconds,
      tokens_note: 'unavailable (harness)',
    },
  });
}

function makeConductorDirect(sessionId) {
  return JSON.stringify({
    ts: new Date().toISOString(),
    phase: 'inline',
    event: 'conductor_direct',
    agent: null,
    task_id: null,
    data: {
      session_uuid: sessionId,
      wall_seconds: 5,
      tokens: { input: 200, output: 100, cache_creation: 0, cache_read: 0 },
    },
  });
}

// ---------------------------------------------------------------------------
// Test 1: bootstrap-creates-events-jsonl
// ---------------------------------------------------------------------------
console.log('\nTest 1: bootstrap-creates-events-jsonl');
{
  const tmpDir = makeTmpProject();
  const projectDir = tmpDir;
  const eventsPath = path.join(projectDir, '.agentic', 'events.jsonl');

  // Remove the .agentic/ dir so the bootstrap must create it.
  fs.rmSync(path.join(projectDir, '.agentic'), { recursive: true, force: true });

  // Run writeSessionTotal with no existing events.jsonl.
  try {
    writeSessionTotal(projectDir, 'test-bootstrap-sess');
  } catch (err) {
    assert(false, `writeSessionTotal must not throw: ${err.message}`);
  }

  assert(fs.existsSync(eventsPath), 'events.jsonl created by bootstrap');
  if (fs.existsSync(eventsPath)) {
    const lines = fs.readFileSync(eventsPath, 'utf8').split('\n').filter(Boolean);
    assert(lines.length === 1, `exactly one line appended (got: ${lines.length})`);
    if (lines.length >= 1) {
      let ev;
      try { ev = JSON.parse(lines[0]); } catch (_) {}
      assert(ev && ev.event === 'session_total',
        `event === "session_total" (got: ${ev && ev.event})`);
      assert(ev && ev.data && ev.data.spawn_count === 0,
        `spawn_count === 0 on zero-aggregate (got: ${ev && ev.data && ev.data.spawn_count})`);
    }
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 2: hook-spawn-start-counted-ad-hoc
// ---------------------------------------------------------------------------
console.log('\nTest 2: hook-spawn-start-counted-ad-hoc');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-adhoc-002';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');

  // Ad-hoc session: only hook spawn_start events, no spawn_complete.
  fs.writeFileSync(eventsPath,
    makeHookSpawnStart('investigator', sessionId) + '\n'
    + makeHookSpawnStart('debugger', sessionId) + '\n',
    'utf8'
  );

  const agg = scanSessionAggregate(eventsPath, sessionId);
  assert(agg !== null, 'aggregate not null for ad-hoc session');
  if (agg) {
    assert(agg.spawn_count === 2,
      `spawn_count === 2 (hook starts counted in ad-hoc session) (got: ${agg.spawn_count})`);
    assert(agg.by_agent['investigator'] && agg.by_agent['investigator'].spawns === 1,
      `by_agent.investigator.spawns === 1 (got: ${agg.by_agent['investigator'] && agg.by_agent['investigator'].spawns})`);
    assert(agg.by_agent['debugger'] && agg.by_agent['debugger'].spawns === 1,
      `by_agent.debugger.spawns === 1 (got: ${agg.by_agent['debugger'] && agg.by_agent['debugger'].spawns})`);
    // Tokens should be 0 (hook spawns carry no token data).
    const totalTokens = Object.values(agg.tokens).reduce((a, b) => a + b, 0);
    assert(totalTokens === 0,
      `total tokens === 0 for hook-only spawns (got: ${totalTokens})`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 3: double-count-guard
// ---------------------------------------------------------------------------
console.log('\nTest 3: double-count-guard (hook spawn_starts skipped when spawn_complete present)');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-mixed-003';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');

  // Mixed session: one conductor spawn_complete + two hook spawn_starts.
  // The hook spawn_starts must be SKIPPED by the double-count guard.
  fs.writeFileSync(eventsPath,
    makeSpawnComplete('engineer', sessionId, 30, { input: 500, output: 200, cache_creation: 0, cache_read: 0 }) + '\n'
    + makeHookSpawnStart('investigator', sessionId) + '\n'
    + makeHookSpawnStart('debugger', sessionId) + '\n',
    'utf8'
  );

  const agg = scanSessionAggregate(eventsPath, sessionId);
  assert(agg !== null, 'aggregate not null for mixed session');
  if (agg) {
    assert(agg.spawn_count === 1,
      `spawn_count === 1 (only spawn_complete counted, hook starts skipped) (got: ${agg.spawn_count})`);
    assert(agg.by_agent['engineer'] && agg.by_agent['engineer'].spawns === 1,
      `only engineer counted (got: ${JSON.stringify(agg.by_agent)})`);
    assert(!agg.by_agent['investigator'],
      `investigator NOT counted (double-count guard active)`);
    assert(!agg.by_agent['debugger'],
      `debugger NOT counted (double-count guard active)`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 4: conductor-direct-not-counted
// ---------------------------------------------------------------------------
console.log('\nTest 4: conductor-direct-not-counted');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-cd-004';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');

  // Only conductor_direct events. conductor_direct is no longer counted.
  // The file is non-empty so scanSessionAggregate does NOT return null,
  // but the aggregate has all-zero counts (no qualifying events contributed).
  fs.writeFileSync(eventsPath,
    makeConductorDirect(sessionId) + '\n'
    + makeConductorDirect(sessionId) + '\n',
    'utf8'
  );

  const agg = scanSessionAggregate(eventsPath, sessionId);
  // File is non-empty -> agg is not null (zero struct returned, not null).
  // The key assertion: spawn_count === 0 and tokens all zero (conductor_direct excluded).
  assert(agg !== null, 'agg not null (file non-empty, zero struct returned)');
  if (agg) {
    assert(agg.spawn_count === 0,
      `spawn_count === 0 (conductor_direct not counted) (got: ${agg.spawn_count})`);
    const totalTokens = Object.values(agg.tokens).reduce((a, b) => a + b, 0);
    assert(totalTokens === 0,
      `total tokens === 0 (conductor_direct tokens not counted) (got: ${totalTokens})`);
    assert(Object.keys(agg.by_agent).length === 0,
      `by_agent empty (no qualifying agents) (got: ${JSON.stringify(agg.by_agent)})`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 5: spawn-complete-still-counted
// ---------------------------------------------------------------------------
console.log('\nTest 5: spawn-complete-still-counted (wall_seconds + tokens)');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-sc-005';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');
  const tokens = { input: 1000, output: 500, cache_creation: 100, cache_read: 50 };

  fs.writeFileSync(eventsPath,
    makeSpawnComplete('skeptic', sessionId, 45, tokens) + '\n',
    'utf8'
  );

  const agg = scanSessionAggregate(eventsPath, sessionId);
  assert(agg !== null, 'aggregate not null');
  if (agg) {
    assert(agg.spawn_count === 1, `spawn_count === 1 (got: ${agg.spawn_count})`);
    assert(agg.wall_seconds === 45, `wall_seconds === 45 (got: ${agg.wall_seconds})`);
    assert(agg.tokens.input === 1000, `tokens.input === 1000 (got: ${agg.tokens.input})`);
    assert(agg.tokens.output === 500, `tokens.output === 500 (got: ${agg.tokens.output})`);
    assert(agg.by_agent['skeptic'] && agg.by_agent['skeptic'].spawns === 1,
      `by_agent.skeptic counted`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 6: capture-gap-hook-investigator (revives trigger in ad-hoc sessions)
// ---------------------------------------------------------------------------
console.log('\nTest 6: capture-gap-hook-investigator (worthy)');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-cg-006';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');

  fs.writeFileSync(eventsPath,
    makeHookSpawnStart('investigator', sessionId) + '\n',
    'utf8'
  );

  const result = detectCaptureGap(tmpDir, sessionId);
  assert(result && result.shouldNudge === true,
    `shouldNudge === true for hook investigator spawn_start (got: ${result && result.shouldNudge})`);
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 7: capture-gap-hook-debugger
// ---------------------------------------------------------------------------
console.log('\nTest 7: capture-gap-hook-debugger (worthy)');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-cg-007';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');

  fs.writeFileSync(eventsPath,
    makeHookSpawnStart('debugger', sessionId) + '\n',
    'utf8'
  );

  const result = detectCaptureGap(tmpDir, sessionId);
  assert(result && result.shouldNudge === true,
    `shouldNudge === true for hook debugger spawn_start (got: ${result && result.shouldNudge})`);
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 8: capture-gap-hook-skeptic-degraded (NOT worthy)
// ---------------------------------------------------------------------------
console.log('\nTest 8: capture-gap-hook-skeptic-degraded (NOT worthy)');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-cg-008';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');

  // Hook spawn_start for skeptic - no findings_count, no signed_off data.
  // Per plan: skeptic-with-findings trigger stays degraded for hook spawns.
  fs.writeFileSync(eventsPath,
    makeHookSpawnStart('skeptic', sessionId) + '\n',
    'utf8'
  );

  const result = detectCaptureGap(tmpDir, sessionId);
  assert(!result || result.shouldNudge !== true,
    `shouldNudge NOT true for hook skeptic spawn_start (degraded trigger) (got: ${result && result.shouldNudge})`);
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 9: ticketed-session-hook-complete-not-double-counted (DS-160 Critical fix)
// ---------------------------------------------------------------------------
console.log('\nTest 9: ticketed-session-hook-complete-not-double-counted');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-ticketed-009';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');

  // One real spawn: BOTH the conductor's own spawn_complete (300s) AND the
  // hook-emitted spawn_complete for the SAME spawn (SubagentStop also fired).
  // Before the fix, both were counted unconditionally -> 2 spawns / 601s.
  fs.writeFileSync(eventsPath,
    makeSpawnComplete('engineer', sessionId, 300, { input: 500, output: 200, cache_creation: 0, cache_read: 0 }) + '\n'
    + makeHookSpawnStart('engineer', sessionId, 'spawn-ticketed-1') + '\n'
    + makeHookSpawnComplete('engineer', sessionId, 'spawn-ticketed-1', 301) + '\n',
    'utf8'
  );

  const agg = scanSessionAggregate(eventsPath, sessionId);
  assert(agg !== null, 'aggregate not null');
  if (agg) {
    assert(agg.spawn_count === 1,
      `spawn_count === 1 (conductor spawn_complete only, hook variant excluded) (got: ${agg.spawn_count})`);
    assert(agg.wall_seconds === 300,
      `wall_seconds === 300 (only the conductor-emitted figure, not 300+301) (got: ${agg.wall_seconds})`);
    assert(agg.by_agent['engineer'] && agg.by_agent['engineer'].spawns === 1,
      `by_agent.engineer.spawns === 1 (got: ${agg.by_agent['engineer'] && agg.by_agent['engineer'].spawns})`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 10: ad-hoc-lost-subagent-stop-still-counts (DS-160 Critical fix)
// ---------------------------------------------------------------------------
console.log('\nTest 10: ad-hoc-lost-subagent-stop-still-counts');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-adhoc-010';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');

  // Ad-hoc session, two real spawns: spawn A completes normally (paired
  // spawn_start + spawn_complete); spawn B's SubagentStop is LOST (only a
  // spawn_start, no matching spawn_complete ever arrives). Before the fix,
  // the mere presence of ANY spawn_complete (even hook-emitted) in the
  // session flipped the "ticketed" guard and dropped spawn B entirely
  // (2 spawns -> reported total of 1).
  fs.writeFileSync(eventsPath,
    makeHookSpawnStart('engineer', sessionId, 'spawn-a') + '\n'
    + makeHookSpawnComplete('engineer', sessionId, 'spawn-a', 42) + '\n'
    + makeHookSpawnStart('skeptic', sessionId, 'spawn-b') + '\n',
    // spawn-b's SubagentStop never fires - no matching spawn_complete line.
    'utf8'
  );

  const agg = scanSessionAggregate(eventsPath, sessionId);
  assert(agg !== null, 'aggregate not null');
  if (agg) {
    assert(agg.spawn_count === 2,
      `spawn_count === 2 (both spawns counted despite lost SubagentStop) (got: ${agg.spawn_count})`);
    assert(agg.by_agent['engineer'] && agg.by_agent['engineer'].spawns === 1,
      `by_agent.engineer.spawns === 1 (got: ${agg.by_agent['engineer'] && agg.by_agent['engineer'].spawns})`);
    assert(agg.by_agent['skeptic'] && agg.by_agent['skeptic'].spawns === 1,
      `by_agent.skeptic.spawns === 1 (lost-stop spawn still counted) (got: ${agg.by_agent['skeptic'] && agg.by_agent['skeptic'].spawns})`);
    assert(agg.wall_seconds === 42,
      `wall_seconds === 42 (spawn-a's paired complete; spawn-b contributes 0) (got: ${agg.wall_seconds})`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 11: adhoc-no-session-id-unpaired-complete-not-double-counted
// ---------------------------------------------------------------------------
console.log('\nTest 11: adhoc-no-session-id-unpaired-complete-not-double-counted');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-adhoc-011';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');

  // One real spawn: its spawn_start. Its SubagentStop fired but the payload
  // carried NO session_id, so subagent-stop-spawn-emit.js could not pair it
  // (findMatch returns null unconditionally when sessionId is absent) - the
  // resulting spawn_complete has paired_spawn_id:null AND session_uuid:null
  // (mirrors `session_uuid: sessionId || null` in the real hook). Before the
  // fix, this unpaired complete was counted as its OWN spawn (agent
  // "unknown") in addition to the real spawn_start -> spawn_count 2 for 1
  // real spawn.
  fs.writeFileSync(eventsPath,
    makeHookSpawnStart('engineer', sessionId, 'spawn-only-real') + '\n'
    + JSON.stringify({
      ts: new Date().toISOString(),
      phase: 'hook',
      event: 'spawn_complete',
      agent: 'unknown',
      task_id: null,
      data: {
        source: 'hook', session_uuid: null, tool_use_id: null,
        agent_id: null, paired_spawn_id: null, wall_seconds: null,
        tokens_note: 'unavailable (harness)',
      },
    }) + '\n',
    'utf8'
  );

  const agg = scanSessionAggregate(eventsPath, sessionId);
  assert(agg !== null, 'aggregate not null');
  if (agg) {
    assert(agg.spawn_count === 1,
      `spawn_count === 1 (unpaired complete from a session-id-less SubagentStop `
      + `must not add a second spawn) (got: ${agg.spawn_count})`);
    assert(!agg.by_agent['unknown'],
      `no "unknown" agent row from the unpaired complete (got: ${JSON.stringify(agg.by_agent)})`);
    assert(agg.by_agent['engineer'] && agg.by_agent['engineer'].spawns === 1,
      `by_agent.engineer.spawns === 1 (got: ${agg.by_agent['engineer'] && agg.by_agent['engineer'].spawns})`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Test 12: paired-complete-resolves-to-nothing-not-double-counted
// ---------------------------------------------------------------------------
console.log('\nTest 12: paired-complete-resolves-to-nothing-not-double-counted');
{
  const tmpDir = makeTmpProject();
  const sessionId = 'sess-adhoc-012';
  const eventsPath = path.join(tmpDir, '.agentic', 'events.jsonl');

  // One real spawn (spawn-real). A SECOND spawn_complete claims
  // paired_spawn_id "spawn-vanished" - a spawn_id with NO corresponding
  // spawn_start anywhere in this session's view (simulates the hook's own
  // bounded tail window missing the original spawn_start when it emitted
  // this record). Before the fix, "existing not found -> still count it
  // once" created a phantom second spawn.
  fs.writeFileSync(eventsPath,
    makeHookSpawnStart('engineer', sessionId, 'spawn-real') + '\n'
    + makeHookSpawnComplete('skeptic', sessionId, 'spawn-vanished', 99) + '\n',
    'utf8'
  );

  const agg = scanSessionAggregate(eventsPath, sessionId);
  assert(agg !== null, 'aggregate not null');
  if (agg) {
    assert(agg.spawn_count === 1,
      `spawn_count === 1 (a paired_spawn_id resolving to nothing is dropped, `
      + `not counted as a phantom spawn) (got: ${agg.spawn_count})`);
    assert(!agg.by_agent['skeptic'],
      `no "skeptic" agent row from the phantom-paired complete (got: ${JSON.stringify(agg.by_agent)})`);
    assert(agg.by_agent['engineer'] && agg.by_agent['engineer'].spawns === 1,
      `by_agent.engineer.spawns === 1 (got: ${agg.by_agent['engineer'] && agg.by_agent['engineer'].spawns})`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
