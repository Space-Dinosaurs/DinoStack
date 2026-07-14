#!/usr/bin/env node
/**
 * Purpose: stdin-guard hardening tests for hooks/session-end-wrap.js
 *          (docs/planning/cursor-stop-hook-plan.md Unit A item 7b). Two
 *          cases:
 *
 *          (a) open-but-silent stdin -> the hook must still exit 0 within the
 *              stdin-guard bound instead of hanging on the previous blocking
 *              `fs.readFileSync(0, 'utf8')` read.
 *          (b) HAPPY-PATH FINALIZATION REGRESSION (mandatory carry-forward
 *              from the plan round-3 Skeptic): the call-site restructure from
 *              `try { run(); } catch (_) {} process.exit(0);` to
 *              `run().catch(() => {}).finally(() => process.exit(0));` must
 *              NOT break finalization. A valid SessionEnd payload with a
 *              ready-eligible pending wrap marker (deferred_wrap_daemon:true
 *              in the fixture config.json - finalize is gated on
 *              deferredDaemonEnabled(cwd), so a missing toggle would make
 *              this test a false green regardless of the restructure) must
 *              still transition the marker to `ready` and remove the
 *              heartbeat. This proves the trailing synchronous
 *              process.exit(0) that used to fire before an async run()
 *              completed (silently skipping finalizeReady/removeHeartbeat)
 *              is gone.
 *
 * Run with: node hooks/tests/test-session-end-wrap-stdin-guard.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const lib = require('../lib/wrap-marker.js');
const { spawnSilentStdin, spawnDelayedChunks } = require('./lib/spawn-stdin-helpers.js');

const hookScript = path.resolve(__dirname, '..', 'session-end-wrap.js');
if (!fs.existsSync(hookScript)) {
  console.error(`FAIL: hook not found at ${hookScript}`);
  process.exit(1);
}

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

// realpath so safeCwd (path.resolve(cwd) === cwd) accepts the dir on macOS
// (mirrors test-session-end-wrap.js's fixture helper).
function makeProject(prefix) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  const projectDir = path.join(base, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  const heartbeatDir = path.join(agenticDir, 'wrap', 'heartbeats');
  fs.mkdirSync(heartbeatDir, { recursive: true });
  return { base, projectDir, agenticDir, heartbeatDir };
}

function cleanup(base) {
  try { fs.rmSync(base, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

function writeMarkerRaw(agenticDir, sessionId, overrides) {
  const projectDir = path.dirname(agenticDir);
  const p = lib.markerPath(projectDir, sessionId);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const marker = Object.assign({
    schema_version: 3,
    session_id: sessionId,
    staged_at: new Date().toISOString(),
    status: 'pending',
    claimed_by: null,
    claimed_kind: null,
    claimed_at: null,
    attempts: 0,
    project_root: projectDir,
    last_error: null,
  }, overrides || {});
  fs.writeFileSync(p, JSON.stringify(marker, null, 2), 'utf8');
  return marker;
}

function readMarker(agenticDir, sessionId) {
  const p = lib.markerPath(path.dirname(agenticDir), sessionId);
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return null; }
}

function touchHeartbeat(heartbeatDir, sessionId) {
  fs.writeFileSync(path.join(heartbeatDir, sessionId), '', 'utf8');
}

function heartbeatExists(heartbeatDir, sessionId) {
  return fs.existsSync(path.join(heartbeatDir, sessionId));
}

// ---------------------------------------------------------------------------
// (a) open-but-silent stdin -> bounded exit 0 (<1200ms)
// stdin is opened but never written to and never closed - the hook must
// still exit 0 within the stdin-guard bound rather than hanging.
// ---------------------------------------------------------------------------
async function testOpenSilentStdinBoundedExit() {
  console.log('\n[a] open-but-silent stdin -> bounded exit 0');
  const { base, projectDir } = makeProject('ae-se-sg-silent-');
  const result = await spawnSilentStdin({
    cmd: process.execPath,
    args: [hookScript],
    cwd: projectDir,
    maxWaitMs: 3000,
  });
  assert(!result.timedOut, `hook exits on its own within the bound (elapsed ${result.elapsedMs}ms, not force-killed)`);
  assert(result.code === 0, `hook exits 0 with open-but-silent stdin (got code ${result.code})`);
  assert(
    result.elapsedMs < 1200,
    `hook exits within the stdin-guard CI-slack bound of 1200ms (elapsed ${result.elapsedMs}ms)`
  );
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (b) HAPPY-PATH FINALIZATION REGRESSION
// A valid SessionEnd payload (piped via the shared spawnDelayedChunks helper
// with a single chunk and no gap/hold - the same fast-EOF delivery shape
// stdin-guard's 'end' path handles) with a ready-eligible pending marker and
// deferred_wrap_daemon:true must still finalize.
// ---------------------------------------------------------------------------
async function testHappyPathFinalizationRegression() {
  console.log('\n[b] HAPPY-PATH FINALIZATION REGRESSION: valid terminal payload still finalizes');
  const { base, projectDir, agenticDir, heartbeatDir } = makeProject('ae-se-sg-finalize-');
  const SID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
  writeMarkerRaw(agenticDir, SID, { status: 'pending' });
  touchHeartbeat(heartbeatDir, SID);
  // MANDATORY: deferred_wrap_daemon:true - finalizeReady/removeHeartbeat are
  // gated on deferredDaemonEnabled(cwd); without this the test would be a
  // false green regardless of whether the .finally() restructure is correct.
  fs.writeFileSync(
    path.join(agenticDir, 'config.json'),
    JSON.stringify({ deferred_wrap_daemon: true }),
    'utf8',
  );

  const payload = JSON.stringify({
    session_id: SID,
    cwd: projectDir,
    hook_event_name: 'SessionEnd',
    reason: 'logout',
  });
  const result = await spawnDelayedChunks({
    cmd: process.execPath,
    args: [hookScript],
    cwd: projectDir,
    chunks: [payload],
    gapMs: 0,
    holdOpenMs: 0, // end() immediately after writing - triggers the EOF path
  });
  assert(result.code === 0, 'hook exits 0 on a valid terminal payload');

  const marker = readMarker(agenticDir, SID);
  assert(
    marker && marker.status === 'ready',
    `pending marker finalized to ready despite the async run().catch().finally() restructure ` +
    `(got status: ${marker && marker.status})`
  );
  assert(
    !heartbeatExists(heartbeatDir, SID),
    'heartbeat removed after terminal finalize (finalizeReady/removeHeartbeat both ran to completion ' +
    'before process.exit(0) fired - proves .finally() waits for run() to settle, not a trailing ' +
    'synchronous process.exit(0) that would race the awaited stdin read)'
  );
  cleanup(base);
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------
async function main() {
  await testOpenSilentStdinBoundedExit();
  await testHappyPathFinalizationRegression();

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
