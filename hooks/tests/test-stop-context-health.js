#!/usr/bin/env node
/**
 * Unit tests: stop-context.js telemetry-health counter (#266).
 *
 * Tests recordHealth, flushHealth, and healthOutcomes via the shim-load
 * pattern used by test-stop-context-telemetry.js.
 *
 * Test cases:
 *   M1a. recordHealth-success: recordHealth fires success -> last_success set,
 *        failures === 0.
 *   M1b. recordHealth-failure: recordHealth fires failure -> failures incremented,
 *        last_error and last_error_ts set.
 *   M1c. recordHealth-accumulates: multiple failures accumulate; success does not
 *        clear failures count.
 *   M1d. recordHealth-never-throws: even when healthOutcomes is pathological,
 *        recordHealth does not throw.
 *   M2.  forced-failure: stub fs.writeFileSync to throw for the health path;
 *        flushHealth does NOT throw, stubHit is true, file NOT written.
 *   M1e. flushHealth-writes-file: recordHealth then flushHealth -> file is valid
 *        JSON, targets present, correct fields.
 *   M1f. flushHealth-merges-existing: existing file has prior failures;
 *        flushHealth merges (cumulative failures).
 *   M1g. flushHealth-absent-file: no prior health file -> starts fresh, writes OK.
 *   M1h. flushHealth-corrupted-existing: corrupted existing file -> starts fresh.
 *   M1i. flushHealth-never-throws-bad-cwd: flushHealth with null cwd does not throw.
 *
 * Run with: node hooks/tests/test-stop-context-health.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

// ---------------------------------------------------------------------------
// Shim-load stop-context.js (same technique as test-stop-context-telemetry.js)
// ---------------------------------------------------------------------------

const hookPath = path.resolve(__dirname, '..', 'stop-context.js');
const hookSource = fs.readFileSync(hookPath, 'utf8');

const libMarkerAbs = path.resolve(__dirname, '..', 'lib', 'wrap-marker.js');
const libCaptureGapAbs = path.resolve(__dirname, '..', 'lib', 'capture-gap.js');

const shimmedSource = hookSource
  .replace(/^run\(\);\s*$/m, '// test shim: run() suppressed')
  .replace(
    /require\(['"]\.\/lib\/wrap-marker\.js['"]\)/,
    `require(${JSON.stringify(libMarkerAbs)})`
  )
  .replace(
    /require\(['"]\.\/lib\/capture-gap\.js['"]\)/,
    `require(${JSON.stringify(libCaptureGapAbs)})`
  );

// Guard: ensure all relative lib requires were rewritten.
// (skill-candidate-detector is loaded lazily inside a function, not at module
// scope, so we do NOT require its rewrite here.)
const relativeRequires = shimmedSource.match(/require\(['"]\.\/lib\/(?!skill-candidate).*?['"]\)/g) || [];
if (relativeRequires.length > 0) {
  console.error(
    '  FATAL: a relative ./lib/ require survived the shim re-anchor - '
    + 'update the rewrite in test-stop-context-health.js. Survivors: '
    + relativeRequires.join(', ')
  );
  process.exit(1);
}

const tmpShimPath = path.join(os.tmpdir(), `stop-ctx-health-shim-${Date.now()}.js`);
fs.writeFileSync(tmpShimPath, shimmedSource, 'utf8');
let helpers;
try {
  helpers = require(tmpShimPath);
} finally {
  try { fs.unlinkSync(tmpShimPath); } catch (_) { /* ignore */ }
}

const { recordHealth, flushHealth, healthOutcomes } = helpers;

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
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-stop-health-'));
  fs.mkdirSync(path.join(tmpDir, '.agentic'), { recursive: true });
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

function clearOutcomes() {
  Object.keys(healthOutcomes).forEach((k) => delete healthOutcomes[k]);
}

// ---------------------------------------------------------------------------
// M1a: recordHealth-success
// ---------------------------------------------------------------------------
console.log('\nM1a: recordHealth-success');
{
  clearOutcomes();
  recordHealth('testTarget', true, null);
  const o = healthOutcomes['testTarget'];
  assert(o !== undefined, 'testTarget entry created');
  assert(o.failures === 0, `failures === 0 (got: ${o && o.failures})`);
  assert(typeof o.last_success === 'string' && o.last_success.length > 0,
    `last_success is a non-empty string (got: ${o && o.last_success})`);
  assert(o.last_error === null, `last_error === null (got: ${o && o.last_error})`);
  assert(o.last_error_ts === null, `last_error_ts === null (got: ${o && o.last_error_ts})`);
}

// ---------------------------------------------------------------------------
// M1b: recordHealth-failure
// ---------------------------------------------------------------------------
console.log('\nM1b: recordHealth-failure');
{
  clearOutcomes();
  recordHealth('testTarget', false, 'EACCES: permission denied');
  const o = healthOutcomes['testTarget'];
  assert(o !== undefined, 'testTarget entry created on failure');
  assert(o.failures === 1, `failures === 1 (got: ${o && o.failures})`);
  assert(o.last_error === 'EACCES: permission denied',
    `last_error set (got: ${o && o.last_error})`);
  assert(typeof o.last_error_ts === 'string' && o.last_error_ts.length > 0,
    `last_error_ts is a non-empty string (got: ${o && o.last_error_ts})`);
  assert(o.last_success === null, `last_success === null after only failure (got: ${o && o.last_success})`);
}

// ---------------------------------------------------------------------------
// M1c: recordHealth-accumulates
// ---------------------------------------------------------------------------
console.log('\nM1c: recordHealth-accumulates (multiple failures do not reset)');
{
  clearOutcomes();
  recordHealth('acc', false, 'err1');
  recordHealth('acc', false, 'err2');
  recordHealth('acc', true, null);  // success does not clear failures count
  const o = healthOutcomes['acc'];
  assert(o.failures === 2, `failures === 2 after two failures (got: ${o && o.failures})`);
  assert(typeof o.last_success === 'string', 'last_success set after subsequent success');
  assert(o.last_error === 'err2', `last_error is most recent (got: ${o && o.last_error})`);
}

// ---------------------------------------------------------------------------
// M1d: recordHealth-never-throws
// ---------------------------------------------------------------------------
console.log('\nM1d: recordHealth-never-throws');
{
  clearOutcomes();
  let threw = false;
  try {
    // Pass non-string error message (non-Error throw case: _ && _.message = undefined -> null)
    recordHealth('safe', false, undefined);
    recordHealth(null, true, null);
    recordHealth(undefined, false, 'msg');
  } catch (_) {
    threw = true;
  }
  assert(!threw, 'recordHealth does not throw on pathological inputs');
}

// ---------------------------------------------------------------------------
// M1e: flushHealth-writes-file
// ---------------------------------------------------------------------------
console.log('\nM1e: flushHealth-writes-file');
{
  clearOutcomes();
  const tmpDir = makeTmpProject();
  recordHealth('writeSessionLog', true, null);
  recordHealth('writeLoopState', false, 'ENOSPC: no space left on device');

  try {
    flushHealth(tmpDir);
  } catch (err) {
    assert(false, `flushHealth must not throw: ${err.message}`);
  }

  const healthPath = path.join(tmpDir, '.agentic', '.telemetry-health.json');
  assert(fs.existsSync(healthPath), '.telemetry-health.json written');
  if (fs.existsSync(healthPath)) {
    let parsed;
    try {
      parsed = JSON.parse(fs.readFileSync(healthPath, 'utf8'));
      assert(true, 'health file is valid JSON');
    } catch (e) {
      assert(false, `health file is valid JSON (parse error: ${e.message})`);
    }
    if (parsed) {
      assert(typeof parsed.updated_at === 'string', 'updated_at is a string');
      assert(parsed.targets && typeof parsed.targets === 'object', 'targets object present');
      assert(parsed.targets.writeSessionLog !== undefined, 'writeSessionLog target present');
      assert(parsed.targets.writeLoopState !== undefined, 'writeLoopState target present');
      assert(parsed.targets.writeSessionLog.failures === 0,
        `writeSessionLog.failures === 0 (got: ${parsed.targets.writeSessionLog && parsed.targets.writeSessionLog.failures})`);
      assert(parsed.targets.writeLoopState.failures === 1,
        `writeLoopState.failures === 1 (got: ${parsed.targets.writeLoopState && parsed.targets.writeLoopState.failures})`);
      assert(parsed.targets.writeLoopState.last_error === 'ENOSPC: no space left on device',
        `writeLoopState.last_error correct (got: ${parsed.targets.writeLoopState && parsed.targets.writeLoopState.last_error})`);
    }
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// M1f: flushHealth-merges-existing (cumulative failures)
// ---------------------------------------------------------------------------
console.log('\nM1f: flushHealth-merges-existing');
{
  clearOutcomes();
  const tmpDir = makeTmpProject();
  const healthPath = path.join(tmpDir, '.agentic', '.telemetry-health.json');

  // Write a pre-existing file with 3 prior failures.
  const prior = {
    updated_at: '2026-01-01T00:00:00Z',
    targets: {
      writeLoopState: {
        failures: 3,
        last_success: '2026-01-01T00:00:00Z',
        last_error: 'prior error',
        last_error_ts: '2026-01-01T00:00:00Z',
      },
    },
  };
  fs.writeFileSync(healthPath, JSON.stringify(prior, null, 2), 'utf8');

  // This session adds 2 more failures.
  recordHealth('writeLoopState', false, 'new error 1');
  recordHealth('writeLoopState', false, 'new error 2');

  flushHealth(tmpDir);

  const parsed = JSON.parse(fs.readFileSync(healthPath, 'utf8'));
  // 3 prior + 2 new = 5 cumulative.
  assert(parsed.targets.writeLoopState.failures === 5,
    `cumulative failures === 5 (got: ${parsed.targets.writeLoopState.failures})`);
  assert(parsed.targets.writeLoopState.last_error === 'new error 2',
    `last_error is most recent session value (got: ${parsed.targets.writeLoopState.last_error})`);

  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// M1g: flushHealth-absent-file (starts fresh)
// ---------------------------------------------------------------------------
console.log('\nM1g: flushHealth-absent-file');
{
  clearOutcomes();
  const tmpDir = makeTmpProject();
  // No prior health file.
  recordHealth('writeSessionTotal', true, null);

  let threw = false;
  try {
    flushHealth(tmpDir);
  } catch (_) {
    threw = true;
  }

  assert(!threw, 'flushHealth does not throw when health file is absent');
  const healthPath = path.join(tmpDir, '.agentic', '.telemetry-health.json');
  assert(fs.existsSync(healthPath), 'health file created from scratch');
  if (fs.existsSync(healthPath)) {
    const parsed = JSON.parse(fs.readFileSync(healthPath, 'utf8'));
    assert(parsed.targets.writeSessionTotal !== undefined, 'writeSessionTotal present');
    assert(parsed.targets.writeSessionTotal.failures === 0,
      `failures === 0 (got: ${parsed.targets.writeSessionTotal && parsed.targets.writeSessionTotal.failures})`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// M1h: flushHealth-corrupted-existing (starts fresh on parse failure)
// ---------------------------------------------------------------------------
console.log('\nM1h: flushHealth-corrupted-existing');
{
  clearOutcomes();
  const tmpDir = makeTmpProject();
  const healthPath = path.join(tmpDir, '.agentic', '.telemetry-health.json');
  fs.writeFileSync(healthPath, '{ bad json !!', 'utf8');

  recordHealth('writePendingBuffer', true, null);

  let threw = false;
  try {
    flushHealth(tmpDir);
  } catch (_) {
    threw = true;
  }

  assert(!threw, 'flushHealth does not throw on corrupted existing file');
  if (fs.existsSync(healthPath)) {
    let parsed;
    try {
      parsed = JSON.parse(fs.readFileSync(healthPath, 'utf8'));
      assert(true, 'health file rewritten as valid JSON after corruption');
      assert(parsed.targets !== undefined, 'targets present in fresh file');
    } catch (e) {
      assert(false, `health file is valid JSON after rewrite (parse error: ${e.message})`);
    }
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// M1i: flushHealth-never-throws-bad-cwd
// ---------------------------------------------------------------------------
console.log('\nM1i: flushHealth-never-throws-bad-cwd');
{
  clearOutcomes();
  let threw = false;
  try {
    flushHealth(null);
    flushHealth(undefined);
    flushHealth('/this/path/does/not/exist/anywhere/agentic-test');
  } catch (_) {
    threw = true;
  }
  assert(!threw, 'flushHealth does not throw on null/undefined/invalid cwd');
}

// ---------------------------------------------------------------------------
// M2: forced-failure (privilege-independent)
// ---------------------------------------------------------------------------
console.log('\nM2: forced-failure (stub fs.writeFileSync to force failure branch)');
{
  clearOutcomes();
  const tmpDir = makeTmpProject();
  const healthFileSuffix = '.telemetry-health.json';

  const originalWriteFileSync = fs.writeFileSync;
  let stubHit = false;
  fs.writeFileSync = function (filePath, ...args) {
    if (typeof filePath === 'string' && filePath.endsWith(healthFileSuffix + '.tmp.' + process.pid)) {
      stubHit = true;
      throw new Error('STUB: simulated write failure for health file');
    }
    return originalWriteFileSync.call(this, filePath, ...args);
  };

  recordHealth('writeContextMd', false, 'ENOSPC');
  let threw = false;
  try {
    flushHealth(tmpDir);
  } catch (_) {
    threw = true;
  } finally {
    fs.writeFileSync = originalWriteFileSync;
  }

  assert(!threw, '(a) flushHealth does NOT throw when write is stubbed to fail');
  assert(stubHit === true, '(b) failure branch was reached (stub was hit)');
  const healthPath = path.join(tmpDir, '.agentic', '.telemetry-health.json');
  assert(!fs.existsSync(healthPath), '(c) health file NOT written when write fails');

  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
process.exit(0);
