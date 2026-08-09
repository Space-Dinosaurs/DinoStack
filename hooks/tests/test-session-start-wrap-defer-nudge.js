#!/usr/bin/env node
/**
 * Regression tests: hooks/session-start-wrap.sh - the deferred-work
 * open-count nudge (4th systemMessage contributor).
 *
 * Cases:
 *   D1 - normal PATH, scripts/lib/repo-dir.sh present (dev-checkout layout):
 *        2 open deferred-work items -> nudge present, correct count.
 *   D2 - PATH stripped of ~/.local/bin, repo-dir.sh present: nudge still
 *        present (proves the resolve_repo_dir path carries it, not PATH).
 *   D3 - DEPLOYED layout regression guard: scripts/lib/repo-dir.sh is
 *        ABSENT (mirrors the real hooks-snapshot dir, which
 *        sync_hooks_snapshot only ever populates with hooks/ and bin/ -
 *        never scripts/) AND PATH is stripped of ~/.local/bin. The inline
 *        fallback (mirroring hooks/lib/version-check-core.sh's identical
 *        precedent) must still resolve AE_REPO_DIR from
 *        ~/.agentic/agentic-engineering-config.json and surface the nudge.
 *        Without the inline fallback this is the exact production layout
 *        where the primary resolver branch is dead code.
 *   D4 - 0 open entries: composed message is unchanged from the
 *        3-contributor baseline (no defer_msg line, no trailing blank
 *        section).
 *
 * Run with: node hooks/tests/test-session-start-wrap-defer-nudge.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SCRIPT = path.resolve(__dirname, '..', 'session-start-wrap.sh');
const DS_DEFER = path.resolve(REPO_ROOT, 'bin', 'ds-defer');

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
  return fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
}

function cleanup(p) {
  try { fs.rmSync(p, { recursive: true, force: true }); } catch (_) {}
}

function seedFakeHome(repoDir) {
  const fakeHome = makeTmp('ae-defer-nudge-home-');
  fs.mkdirSync(path.join(fakeHome, '.agentic'), { recursive: true });
  fs.writeFileSync(
    path.join(fakeHome, '.agentic', 'agentic-engineering-config.json'),
    JSON.stringify({ repo_dir: repoDir }),
    'utf8',
  );
  return fakeHome;
}

function appendDeferItems(projectDir, n) {
  for (let i = 0; i < n; i++) {
    execFileSync('python3', [
      DS_DEFER, 'append', '--repo', projectDir,
      '--description', `smoke item ${i}`, '--reason', 'failed_promotion_bar',
    ], { stdio: 'ignore' });
  }
}

function strippedPath() {
  return process.env.PATH
    .split(path.delimiter)
    .filter((p) => !p.includes('.local/bin'))
    .join(path.delimiter);
}

/**
 * Run the SessionStart hook (given script path) with a given projectDir as
 * cwd, a fake HOME, and an optional PATH override. AGENTIC_QUIET is
 * explicitly unset so the composed systemMessage is populated.
 */
function runHook(scriptPath, projectDir, fakeHome, pathOverride) {
  const payload = JSON.stringify({ cwd: projectDir });
  const env = Object.assign({}, process.env, {
    HOME: fakeHome,
    AGENTIC_WRAP_DAEMON: '1', // never spawn the real daemon from a test
  });
  delete env.AGENTIC_QUIET;
  if (pathOverride) {
    env.PATH = pathOverride;
  }
  const res = spawnSync('bash', [scriptPath], {
    input: payload,
    encoding: 'utf8',
    timeout: 20000,
    env,
  });
  let systemMessage = '';
  try {
    systemMessage = JSON.parse(res.stdout || '{}').systemMessage || '';
  } catch (_) {
    // leave empty; assertions below will fail visibly on bad JSON
  }
  return { code: res.status, stdout: res.stdout || '', stderr: res.stderr || '', systemMessage };
}

if (!fs.existsSync(SCRIPT)) {
  console.error(`FAIL: script not found at ${SCRIPT}`);
  process.exit(1);
}
if (!fs.existsSync(DS_DEFER)) {
  console.error(`FAIL: bin/ds-defer not found at ${DS_DEFER}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// (D1) normal PATH, repo-dir.sh present, 2 open entries -> nudge present
// ---------------------------------------------------------------------------
console.log('\n[D1] dev-checkout layout, normal PATH, 2 open entries');
{
  const projectDir = makeTmp('ae-defer-nudge-d1-');
  fs.mkdirSync(path.join(projectDir, '.agentic'), { recursive: true });
  appendDeferItems(projectDir, 2);
  const fakeHome = seedFakeHome(REPO_ROOT);

  const { code, systemMessage } = runHook(SCRIPT, projectDir, fakeHome, null);
  assert(code === 0, 'D1: hook exits 0');
  assert(/^2 deferred-work item\(s\) pending/m.test(systemMessage) || systemMessage.includes('2 deferred-work item(s) pending'),
    `D1: systemMessage contains the 2-item nudge (got: ${JSON.stringify(systemMessage)})`);

  cleanup(projectDir);
  cleanup(fakeHome);
}

// ---------------------------------------------------------------------------
// (D2) PATH stripped of ~/.local/bin, repo-dir.sh present: nudge still present
// ---------------------------------------------------------------------------
console.log('\n[D2] dev-checkout layout, PATH stripped of ~/.local/bin, 2 open entries');
{
  const projectDir = makeTmp('ae-defer-nudge-d2-');
  fs.mkdirSync(path.join(projectDir, '.agentic'), { recursive: true });
  appendDeferItems(projectDir, 2);
  const fakeHome = seedFakeHome(REPO_ROOT);

  const { code, systemMessage } = runHook(SCRIPT, projectDir, fakeHome, strippedPath());
  assert(code === 0, 'D2: hook exits 0');
  assert(systemMessage.includes('2 deferred-work item(s) pending'),
    `D2: systemMessage still contains the nudge with ~/.local/bin stripped from PATH (got: ${JSON.stringify(systemMessage)})`);

  cleanup(projectDir);
  cleanup(fakeHome);
}

// ---------------------------------------------------------------------------
// (D3) DEPLOYED layout: scripts/lib/repo-dir.sh absent + PATH stripped ->
// inline fallback must still resolve AE_REPO_DIR and surface the nudge.
// ---------------------------------------------------------------------------
console.log('\n[D3] DEPLOYED hooks-snapshot layout (no scripts/lib/repo-dir.sh), PATH stripped, 2 open entries');
{
  const projectDir = makeTmp('ae-defer-nudge-d3-');
  fs.mkdirSync(path.join(projectDir, '.agentic'), { recursive: true });
  appendDeferItems(projectDir, 2);
  const fakeHome = seedFakeHome(REPO_ROOT);

  // Build a fake snapshot dir containing ONLY hooks/ and bin/ - mirroring
  // sync_hooks_snapshot's real source set (scripts/lib/repo-dir.sh has
  // no equivalent under a real hooks-snapshot dir).
  const fakeSnapshot = makeTmp('ae-defer-nudge-snapshot-');
  fs.cpSync(path.join(REPO_ROOT, 'hooks'), path.join(fakeSnapshot, 'hooks'), { recursive: true });
  fs.cpSync(path.join(REPO_ROOT, 'bin'), path.join(fakeSnapshot, 'bin'), { recursive: true });
  const snapshotScript = path.join(fakeSnapshot, 'hooks', 'session-start-wrap.sh');
  assert(fs.existsSync(snapshotScript), 'D3: fake snapshot script exists');
  assert(!fs.existsSync(path.join(fakeSnapshot, 'scripts', 'lib', 'repo-dir.sh')),
    'D3: precondition - scripts/lib/repo-dir.sh is absent from the fake deployed snapshot');

  const { code, systemMessage, stderr } = runHook(snapshotScript, projectDir, fakeHome, strippedPath());
  assert(code === 0, `D3: hook exits 0 (stderr: ${stderr})`);
  assert(systemMessage.includes('2 deferred-work item(s) pending'),
    `D3: deployed-layout inline fallback surfaces the nudge (got: ${JSON.stringify(systemMessage)})`);

  cleanup(projectDir);
  cleanup(fakeHome);
  cleanup(fakeSnapshot);
}

// ---------------------------------------------------------------------------
// (D4) 0 open entries: composed message unchanged from the 3-contributor
// baseline (no defer_msg line).
// ---------------------------------------------------------------------------
console.log('\n[D4] 0 open deferred-work entries: no nudge line appended');
{
  const projectDir = makeTmp('ae-defer-nudge-d4-');
  fs.mkdirSync(path.join(projectDir, '.agentic'), { recursive: true });
  const fakeHome = seedFakeHome(REPO_ROOT);

  const { code, systemMessage } = runHook(SCRIPT, projectDir, fakeHome, null);
  assert(code === 0, 'D4: hook exits 0');
  assert(!systemMessage.includes('deferred-work item(s) pending'),
    `D4: no deferred-work nudge present with 0 open items (got: ${JSON.stringify(systemMessage)})`);

  cleanup(projectDir);
  cleanup(fakeHome);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
