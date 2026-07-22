#!/usr/bin/env node
/**
 * Integration tests: hooks/stop-context.js bounded-stdin-guard swap.
 *
 * Verifies the hook still meets its two core properties after the
 * fs.readFileSync(0) -> readStdinGuarded() swap (docs/planning/
 * cursor-stop-hook-plan.md Unit A item 6): (a) it never hangs a spawning
 * harness that opens stdin and never writes/closes it, and (b) a slow,
 * multi-chunk payload delivered over more than 2 seconds is still read in
 * full and produces the same on-disk output as a fast delivery.
 *
 * Test cases:
 *   (a) open-but-silent stdin -> exit 0, elapsed <1200ms (CI slack over the
 *       1000ms production-defaults bar asserted at the shared-helper level
 *       in test-stdin-guard.js).
 *   (b) slow-chunked valid Claude Stop payload delivered over >2s (via
 *       spawnDelayedChunks) -> .agentic/context.md AND .agentic/events.jsonl
 *       are written correctly in a tmp fixture project dir, matching the
 *       fixture pattern used by test-stop-context-deferred-wrap.js /
 *       test-stop-context-session-log.js.
 *
 * Run with: node hooks/tests/test-stop-context-stdin-guard.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const { spawnSilentStdin, spawnDelayedChunks } = require('./lib/spawn-stdin-helpers.js');

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

const hookScript = path.resolve(__dirname, '..', 'stop-context.js');
if (!fs.existsSync(hookScript)) {
  console.error(`FAIL: hook not found at ${hookScript}`);
  process.exit(1);
}

function makeTmp(prefix) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  const fakeHome = path.join(tmpDir, 'home');
  const projectDir = path.join(tmpDir, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  fs.mkdirSync(fakeHome, { recursive: true });
  fs.mkdirSync(projectDir, { recursive: true });
  fs.mkdirSync(agenticDir, { recursive: true });
  return { tmpDir, fakeHome, projectDir, agenticDir };
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

// ---------------------------------------------------------------------------
// (a) open-but-silent stdin -> bounded exit
// ---------------------------------------------------------------------------

async function testOpenButSilentStdin() {
  const { tmpDir, fakeHome } = makeTmp('ae-stop-stdinguard-a-');
  try {
    const result = await spawnSilentStdin({
      cmd: process.execPath,
      args: [hookScript],
      env: { ...process.env, HOME: fakeHome },
      maxWaitMs: 3000,
    });
    assert(!result.timedOut, '(a) hook exits on its own (not force-killed by the test harness)');
    assert(result.code === 0, `(a) hook exits 0 (got: ${result.code})`);
    assert(
      result.elapsedMs < 1200,
      `(a) hook exits with bounded elapsed time under CI slack (${result.elapsedMs}ms, must be < 1200ms)`
    );
  } finally {
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// (b) slow-chunked valid payload (>2s total delivery) -> full write
// ---------------------------------------------------------------------------

async function testSlowChunkedPayloadWritesCorrectly() {
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-stop-stdinguard-b-');
  try {
    const sessionId = 'stdin-guard-slow-chunk-session';
    const payload = JSON.stringify({
      cwd: projectDir,
      session_id: sessionId,
      transcript: [
        {
          role: 'user',
          content: 'slow-chunked stdin-guard integration test message '.repeat(4),
        },
      ],
    });

    // Split into 3 chunks so no prefix is independently a complete JSON
    // document - exercises the inactivity re-arm across chunks (same
    // technique as test-stdin-guard.js's slow-chunked case), not a lucky
    // early parse on an intermediate chunk.
    const third = Math.floor(payload.length / 3);
    const chunks = [
      payload.slice(0, third),
      payload.slice(third, third * 2),
      payload.slice(third * 2),
    ];

    const result = await spawnDelayedChunks({
      cmd: process.execPath,
      args: [hookScript],
      env: { ...process.env, HOME: fakeHome },
      chunks,
      gapMs: 1100,
      holdOpenMs: 200,
      maxWaitMs: 10000,
    });

    assert(!result.timedOut, '(b) hook exits on its own (not force-killed by the test harness)');
    assert(result.code === 0, `(b) hook exits 0 (got: ${result.code})`);
    assert(
      result.elapsedMs > 2000,
      `(b) total chunked delivery exceeded 2s as required (${result.elapsedMs}ms)`
    );

    const contextPath = path.join(agenticDir, 'context.md');
    assert(fs.existsSync(contextPath), '(b) .agentic/context.md written after slow-chunked delivery');
    if (fs.existsSync(contextPath)) {
      const content = fs.readFileSync(contextPath, 'utf8');
      assert(content.startsWith('# Session Context'), '(b) context.md has the expected header');
      assert(content.includes('slow-chunked stdin-guard integration test message'),
        '(b) context.md Recent Focus reflects the fully-delivered transcript (no truncation)');
    }

    const eventsPath = path.join(agenticDir, 'events.jsonl');
    assert(fs.existsSync(eventsPath), '(b) .agentic/events.jsonl written after slow-chunked delivery');
    if (fs.existsSync(eventsPath)) {
      const lines = fs.readFileSync(eventsPath, 'utf8').trim().split('\n').filter(Boolean);
      const totals = lines.map((l) => { try { return JSON.parse(l); } catch (_) { return null; } })
        .filter((o) => o && o.event === 'session_total');
      assert(totals.length === 1, `(b) exactly one session_total event written (got: ${totals.length})`);
      if (totals.length === 1) {
        assert(totals[0].data && totals[0].data.session_uuid === sessionId,
          '(b) session_total event carries the correct session_uuid');
      }
    }
  } finally {
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

async function main() {
  console.log('(a) open-but-silent stdin -> bounded exit');
  await testOpenButSilentStdin();

  console.log('\n(b) slow-chunked valid payload (>2s) -> context.md + events.jsonl written');
  await testSlowChunkedPayloadWritesCorrectly();

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
