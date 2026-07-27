#!/usr/bin/env node
'use strict';

/**
 * End-to-end regression test for AC12 (DS-107), driven through the REAL Stop
 * hook process rather than the library in isolation.
 *
 * THE ASSERTION: a rollup carrying 3 session activity blocks still carries all 3
 * after a full Stop-hook turn.
 *
 * THE FAILURE MODE IT CATCHES: the retired wrap-coexistence path in
 * hooks/stop-context.js did `existing.indexOf(ACTIVITY_SENTINEL)` and sliced
 * everything after the FIRST sentinel away before appending exactly one fresh
 * block - "replace mode, most recent session only, not accumulated". On an
 * N-session rollup that destroys N-1 sessions' activity, which is a variant of
 * the very data-loss bug this change fixes. Restoring that slice makes this test
 * fail with 1 block where 3 are expected.
 *
 * Also pinned here, because they are the two ways the multi-block property can
 * be lost without the slice returning:
 *   - the curated `_wrap.md` region must be byte-unchanged by a Stop turn (AC17);
 *   - the derived marker must sit in the ACTIVITY-REGION header and NOT in the
 *     file header (AC12), since a header marker survives a legacy strip-and-append
 *     and defeats foreign-preservation detection.
 *
 * Run with: node hooks/tests/test-context-multiblock-survives.js
 * Argument-free invocation runs everything (auto-discovered by the
 * hooks/tests/test-*.js glob in .github/workflows/hooks-tests.yml).
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');
const R = require('../lib/context-rollup.js');

const hookScript = path.resolve(__dirname, '..', 'stop-context.js');

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
  const tmpDir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  const fakeHome = path.join(tmpDir, 'home');
  const projectDir = path.join(tmpDir, 'project');
  fs.mkdirSync(path.join(fakeHome, '.agentic'), { recursive: true });
  fs.mkdirSync(path.join(projectDir, '.agentic'), { recursive: true });
  return { tmpDir, fakeHome, projectDir };
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* best-effort */ }
}

function runHook(projectDir, fakeHome, sessionId, filePath) {
  execSync(`node "${hookScript}"`, {
    input: JSON.stringify({
      cwd: projectDir,
      session_id: sessionId,
      transcript: [{
        role: 'assistant',
        content: [{ type: 'tool_use', name: 'Edit', input: { file_path: filePath } }],
      }],
    }),
    encoding: 'utf8',
    env: { ...process.env, HOME: fakeHome },
    timeout: 10000,
    stdio: ['pipe', 'pipe', 'ignore'],
  });
}

// ---------------------------------------------------------------------------
// AC12: three sessions accumulate and survive a fourth turn
// ---------------------------------------------------------------------------
console.log('\n--- AC12: three session blocks survive a full Stop-hook turn ---');
{
  const { tmpDir, fakeHome, projectDir } = makeTmp('ae-multiblock-');
  const contextPath = path.join(projectDir, '.agentic', 'context.md');

  runHook(projectDir, fakeHome, 'sess-alpha', '/repo/src/alpha.js');
  runHook(projectDir, fakeHome, 'sess-beta', '/repo/src/beta.js');
  runHook(projectDir, fakeHome, 'sess-gamma', '/repo/src/gamma.js');

  let body = fs.readFileSync(contextPath, 'utf8');
  let blocks = (body.match(/^### Session /gm) || []).length;
  assert(blocks === 3, `three distinct sessions produce three blocks (got ${blocks})`);

  // A fourth turn by an ALREADY-PRESENT session must not evict the other two.
  runHook(projectDir, fakeHome, 'sess-alpha', '/repo/src/alpha2.js');
  body = fs.readFileSync(contextPath, 'utf8');
  blocks = (body.match(/^### Session /gm) || []).length;
  assert(blocks === 3,
    `AC12: all 3 blocks survive a full Stop-hook turn (got ${blocks}) - the retired `
    + 'indexOf-and-slice would leave exactly 1');
  assert(body.includes('/repo/src/beta.js') && body.includes('/repo/src/gamma.js'),
    'AC12: the OTHER sessions\' content specifically survives, not just the heading count');
  assert(body.includes('/repo/src/alpha2.js') && !body.includes('/repo/src/alpha.js'),
    "AC12: the re-running session's own block is REPLACED, not duplicated");

  // A brand-new session must not evict anyone either.
  runHook(projectDir, fakeHome, 'sess-delta', '/repo/src/delta.js');
  body = fs.readFileSync(contextPath, 'utf8');
  blocks = (body.match(/^### Session /gm) || []).length;
  assert(blocks === 4, `a fourth distinct session appends rather than replacing (got ${blocks})`);

  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// AC12 marker placement + AC17 curated-region immutability, end-to-end
// ---------------------------------------------------------------------------
console.log('\n--- AC12/AC17: marker placement and curated immutability ---');
{
  const { tmpDir, fakeHome, projectDir } = makeTmp('ae-multiblock-curated-');
  const contextPath = path.join(projectDir, '.agentic', 'context.md');
  const curatedPath = path.join(projectDir, '.agentic', '_wrap.md');

  const labels = 'ABCDEFGHIJ'.split('').map((c) => `[Session ${c}] focus ${c}`).join('\n\n');
  const curated = '# Session Context\n*Written by /ds-wrap on 2026-07-26.*\n*Project: p*\n\n'
    + '## Recent Focus\n' + labels + '\n\n## Watch Out For\n- the hardlink hazard\n';
  fs.writeFileSync(curatedPath, curated, 'utf8');

  runHook(projectDir, fakeHome, 'sess-one', '/repo/a.js');
  runHook(projectDir, fakeHome, 'sess-two', '/repo/b.js');

  assert(fs.readFileSync(curatedPath, 'utf8') === curated,
    'AC17: _wrap.md is byte-unchanged after two Stop-hook turns');

  const body = fs.readFileSync(contextPath, 'utf8');
  assert((body.match(/\[Session [A-J]\]/g) || []).length === 10,
    'AC17: all 10 curated session labels reach the rollup');

  const sentinelIdx = body.indexOf(R.ACTIVITY_SENTINEL);
  const markerIdx = body.indexOf(R.DERIVED_MARKER);
  assert(sentinelIdx > 0 && markerIdx > sentinelIdx,
    'AC12: the derived marker sits in the ACTIVITY-REGION header, after the sentinel');
  assert(body.slice(0, sentinelIdx).indexOf(R.DERIVED_MARKER) === -1,
    'AC12: the derived marker is ABSENT from the curated region and the file header');
  assert(body.slice(sentinelIdx).indexOf('## Recent Focus') === -1,
    'AC17: the composer never writes ## Recent Focus into the derived region');

  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// The lock does not suppress accumulation
// ---------------------------------------------------------------------------
console.log('\n--- accumulation is not suppressed by a held (or abandoned) lock ---');
{
  const { tmpDir, fakeHome, projectDir } = makeTmp('ae-multiblock-locked-');
  const contextPath = path.join(projectDir, '.agentic', 'context.md');
  fs.mkdirSync(path.join(projectDir, '.agentic', 'wrap', 'lock'), { recursive: true });

  runHook(projectDir, fakeHome, 'sess-l1', '/repo/l1.js');
  runHook(projectDir, fakeHome, 'sess-l2', '/repo/l2.js');

  const body = fs.readFileSync(contextPath, 'utf8');
  assert((body.match(/^### Session /gm) || []).length === 2,
    'both sessions accumulate while .agentic/wrap/lock is held (D2/D3 fix)');
  cleanup(tmpDir);
}

console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
