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

const libMarkerAbs = path.resolve(__dirname, '..', 'lib', 'wrap-marker.js');
const libCaptureGapAbs = path.resolve(__dirname, '..', 'lib', 'capture-gap.js');
const libSkillDetectorAbs = path.resolve(__dirname, '..', 'lib', 'skill-candidate-detector.js');

const shimmedSource = hookSource
  .replace(/^run\(\);\s*$/m, '// test shim: run() suppressed')
  .replace(
    /require\(['"]\.\/lib\/wrap-marker\.js['"]\)/,
    `require(${JSON.stringify(libMarkerAbs)})`
  )
  .replace(
    /require\(['"]\.\/lib\/capture-gap\.js['"]\)/,
    `require(${JSON.stringify(libCaptureGapAbs)})`
  )
  + `\n
if (typeof module !== 'undefined') {
  module.exports = {
    scanSessionAggregate,
    writeSessionTotal,
    detectCaptureGap: require(${JSON.stringify(libCaptureGapAbs)}).detectCaptureGap,
  };
}
`;

// Guard: ensure all relative lib requires were rewritten.
// (skill-candidate-detector is loaded lazily inside a function, not at module
// scope, so we do NOT require its rewrite here - the lazy path will fail-open
// at test time since those code paths are gated on config toggles that are off
// by default in a temp dir without config.json.)
const relativeRequires = shimmedSource.match(/require\(['"]\.\/lib\/(?!skill-candidate).*?['"]\)/g) || [];
if (relativeRequires.length > 0) {
  console.error(
    '  FATAL: a relative ./lib/ require survived the shim re-anchor - '
    + 'update the rewrite in test-stop-context-telemetry.js. Survivors: '
    + relativeRequires.join(', ')
  );
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

function makeHookSpawnStart(agent, sessionId) {
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
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
