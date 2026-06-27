#!/usr/bin/env node
/**
 * Integration tests: skill-candidate detection wired into stop-context.js.
 *
 * All tests use temp HOME/cwd and NEVER touch the real .agentic/ directory.
 * The Stop hook is invoked as a child process (exactly as Claude Code does).
 *
 * Sub-tests:
 *   (a) scan-writes: seeded events.jsonl with >=3 tool_failure_workaround events
 *       sharing a domain_tag (with session_uuid present) -> hook exits 0 and
 *       .agentic/skill-candidates.md + .agentic/.skill-candidate-tally.json
 *       are written.
 *   (b) toggle-off-skips: skill_candidate_detection: false in config.json ->
 *       scan skipped; neither .skill-candidate-tally.json nor skill-candidates.md
 *       are written after the hook runs.
 *   (c) error-doesnt-break: simulated error in the scan (corrupt detector module
 *       monkey-patched via env override NOT possible, so we force a corrupt events
 *       line + absence of .agentic dir writability to ensure the hook never throws
 *       and exits 0; other write paths still complete [context.md written]).
 *
 * Run with: node hooks/tests/test-stop-context-skill-candidate.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync, spawnSync } = require('child_process');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const hookScript = path.resolve(__dirname, '..', 'stop-context.js');
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

function makeTmp(prefix) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const fakeHome = path.join(tmpDir, 'home');
  const projectDir = path.join(tmpDir, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  const identityDir = path.join(fakeHome, '.agentic');
  fs.mkdirSync(fakeHome, { recursive: true });
  fs.mkdirSync(projectDir, { recursive: true });
  fs.mkdirSync(agenticDir, { recursive: true });
  fs.mkdirSync(identityDir, { recursive: true });
  return { tmpDir, fakeHome, projectDir, agenticDir, identityDir };
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
}

/**
 * Run the Stop hook synchronously. Returns the spawnSync result.
 * stdio: ['pipe', 'pipe', 'pipe'] captures all output.
 */
function runHook(projectDir, fakeHome, sessionId) {
  const payload = JSON.stringify({
    cwd: projectDir,
    session_id: sessionId,
    transcript: [],
  });
  return spawnSync('node', [hookScript], {
    input: payload,
    encoding: 'utf8',
    env: { ...process.env, HOME: fakeHome },
    timeout: 15000,
    stdio: ['pipe', 'pipe', 'pipe'],
  });
}

/**
 * Build a single tool_failure_workaround event line.
 */
function makeWorkaroundEvent(domainTag, sessionUuid, ts) {
  return JSON.stringify({
    ts,
    phase: 'workaround',
    event: 'tool_failure_workaround',
    agent: null,
    data: {
      session_uuid: sessionUuid,
      domain_tag: domainTag,
      tool: 'Bash',
      note: `workaround for ${domainTag}`,
    },
  });
}

// ---------------------------------------------------------------------------
// Test (a): scan-writes
// 3 events sharing the same domain_tag -> skill-candidates.md + tally written
// ---------------------------------------------------------------------------

{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('sc-scan-writes-');
  try {
    console.log('\nTest (a): scan-writes - 3 events sharing domain_tag -> candidates + tally written');

    const sessionId = 'test-session-scan-001';
    const domainTag = 'adapter-rebuild';

    // Seed events.jsonl with exactly 3 matching events.
    const events = [
      makeWorkaroundEvent(domainTag, sessionId, '2026-06-01T10:00:01.000Z'),
      makeWorkaroundEvent(domainTag, sessionId, '2026-06-01T10:00:02.000Z'),
      makeWorkaroundEvent(domainTag, sessionId, '2026-06-01T10:00:03.000Z'),
    ].join('\n') + '\n';

    fs.writeFileSync(path.join(agenticDir, 'events.jsonl'), events, 'utf8');

    const result = runHook(projectDir, fakeHome, sessionId);

    assert(result.status === 0, 'hook exits with status 0');

    const tallyPath = path.join(agenticDir, '.skill-candidate-tally.json');
    const candidatesPath = path.join(agenticDir, 'skill-candidates.md');

    // The writes complete before exit because runSkillCandidateScan uses only
    // SYNCHRONOUS fs calls internally (no `await`), so the function body runs
    // to completion before the Promise yields. If real async I/O were ever added
    // to the detector, this guarantee would break. The retry loop below is a
    // belt-and-suspenders fallback; it should never fire in practice.
    let tallyExists = fs.existsSync(tallyPath);
    let candidatesExists = fs.existsSync(candidatesPath);

    // Brief retry if async write hasn't landed yet (shouldn't happen in practice).
    if (!tallyExists || !candidatesExists) {
      const deadline = Date.now() + 500;
      while (Date.now() < deadline) {
        tallyExists = fs.existsSync(tallyPath);
        candidatesExists = fs.existsSync(candidatesPath);
        if (tallyExists && candidatesExists) break;
        // Busy-wait 50ms
        const until = Date.now() + 50;
        while (Date.now() < until) { /* spin */ }
      }
    }

    assert(tallyExists, '.skill-candidate-tally.json written');
    assert(candidatesExists, 'skill-candidates.md written');

    if (tallyExists) {
      const tally = JSON.parse(fs.readFileSync(tallyPath, 'utf8'));
      assert(
        tally.candidates && tally.candidates[domainTag] &&
        tally.candidates[domainTag].count >= 3,
        `tally[${domainTag}].count >= 3`
      );
      assert(
        tally.candidates[domainTag].surfacedAt != null,
        `tally[${domainTag}].surfacedAt is set`
      );
    }

    if (candidatesExists) {
      const md = fs.readFileSync(candidatesPath, 'utf8');
      assert(md.includes(domainTag), `skill-candidates.md contains domain "${domainTag}"`);
    }
  } finally {
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// Test (b): toggle-off-skips
// skill_candidate_detection: false -> no tally, no candidates.md written
// ---------------------------------------------------------------------------

{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('sc-toggle-off-');
  try {
    console.log('\nTest (b): toggle-off-skips - skill_candidate_detection: false -> scan skipped');

    const sessionId = 'test-session-toggle-002';
    const domainTag = 'adapter-rebuild';

    // Seed events.jsonl with 3 matching events.
    const events = [
      makeWorkaroundEvent(domainTag, sessionId, '2026-06-01T10:00:01.000Z'),
      makeWorkaroundEvent(domainTag, sessionId, '2026-06-01T10:00:02.000Z'),
      makeWorkaroundEvent(domainTag, sessionId, '2026-06-01T10:00:03.000Z'),
    ].join('\n') + '\n';
    fs.writeFileSync(path.join(agenticDir, 'events.jsonl'), events, 'utf8');

    // Write config.json with detection explicitly disabled.
    fs.writeFileSync(
      path.join(agenticDir, 'config.json'),
      JSON.stringify({ skill_candidate_detection: false }),
      'utf8'
    );

    const result = runHook(projectDir, fakeHome, sessionId);

    assert(result.status === 0, 'hook exits with status 0');

    const tallyPath = path.join(agenticDir, '.skill-candidate-tally.json');
    const candidatesPath = path.join(agenticDir, 'skill-candidates.md');

    // Brief wait to rule out a race with async write.
    const deadline = Date.now() + 300;
    while (Date.now() < deadline) {
      if (fs.existsSync(tallyPath) || fs.existsSync(candidatesPath)) break;
      const until = Date.now() + 30;
      while (Date.now() < until) { /* spin */ }
    }

    assert(!fs.existsSync(tallyPath), '.skill-candidate-tally.json NOT written (toggle off)');
    assert(!fs.existsSync(candidatesPath), 'skill-candidates.md NOT written (toggle off)');
  } finally {
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// Test (c): error-doesnt-break
// A forced error in the scan (corrupt events.jsonl entries) does not throw out
// of the Stop hook; other write paths still complete (context.md is written).
// ---------------------------------------------------------------------------

{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('sc-error-safe-');
  try {
    console.log('\nTest (c): error-doesnt-break - corrupt events still exit 0; context.md written');

    const sessionId = 'test-session-error-003';

    // Seed events.jsonl with entirely corrupt/garbage lines so the scan
    // encounters parse errors on every line. The detector's top-level try/catch
    // absorbs these; the outer try/catch in stop-context.js is the second layer.
    const corruptEvents = 'not json at all\n}{invalid\n\n';
    fs.writeFileSync(path.join(agenticDir, 'events.jsonl'), corruptEvents, 'utf8');

    const result = runHook(projectDir, fakeHome, sessionId);

    assert(result.status === 0, 'hook exits with status 0 despite corrupt events');

    // context.md (path 1) should still be written - it does not depend on the
    // skill-candidate detection path.
    const contextPath = path.join(agenticDir, 'context.md');
    assert(fs.existsSync(contextPath), 'context.md still written (other paths unaffected)');

    // No stderr output from the hook itself (errors are fully swallowed).
    // The hook may write to stderr in special cases (pending buffer cap), but not
    // for skill-candidate errors.
    const stderr = (result.stderr || '').trim();
    assert(
      !stderr.includes('skill-candidate') && !stderr.includes('TypeError') && !stderr.includes('SyntaxError'),
      'no skill-candidate error leaked to stderr'
    );
  } finally {
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
