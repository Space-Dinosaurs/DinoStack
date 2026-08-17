#!/usr/bin/env node
/**
 * Regression tests: hooks/session-start-wrap.sh - the worktree-accumulation
 * nudge (5th systemMessage contributor, ds-cleanup-worktrees --dry-run).
 *
 * Cases:
 *   W1 - normal PATH, scripts/lib/repo-dir.sh present (dev-checkout layout):
 *        6 non-root worktrees (>= the 5-worktree threshold) -> nudge
 *        present, correct count.
 *   W2 - PATH stripped of ~/.local/bin, repo-dir.sh present: nudge still
 *        present (proves the resolve_repo_dir path carries it, not PATH).
 *   W3 - DEPLOYED layout regression guard: scripts/lib/repo-dir.sh is
 *        ABSENT (mirrors the real hooks-snapshot dir) AND PATH is stripped
 *        of ~/.local/bin. The inline fallback must still resolve
 *        AE_REPO_DIR and surface the nudge.
 *   W4 - below threshold (2 non-root worktrees, threshold is 5): composed
 *        message contains no worktree nudge line.
 *   W5 - report-only invariant: after W1 runs, every worktree the hook
 *        observed is STILL PRESENT on disk - the SessionStart call site
 *        must never remove anything regardless of the count.
 *
 * Run with: node hooks/tests/test-session-start-wrap-worktree-nudge.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SCRIPT = path.resolve(__dirname, '..', 'session-start-wrap.sh');
const DS_CLEANUP = path.resolve(REPO_ROOT, 'bin', 'ds-cleanup-worktrees');

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

function git(cwd, args) {
  return execFileSync('git', ['-C', cwd, ...args], { encoding: 'utf8' });
}

function seedFakeHome(repoDir) {
  const fakeHome = makeTmp('ae-wt-nudge-home-');
  fs.mkdirSync(path.join(fakeHome, '.agentic'), { recursive: true });
  fs.writeFileSync(
    path.join(fakeHome, '.agentic', 'agentic-engineering-config.json'),
    JSON.stringify({ repo_dir: repoDir }),
    'utf8',
  );
  return fakeHome;
}

/**
 * Builds a project repo with a real bare `origin` remote and `n` non-root
 * isolation worktrees, each on its own never-pushed branch (so every
 * worktree resolves REMOVE-eligible under ds-cleanup-worktrees' own
 * predicate - irrelevant to this nudge, which only counts entries, but
 * keeps the fixture minimal and realistic).
 */
function buildProjectWithWorktrees(n) {
  const parent = makeTmp('ae-wt-nudge-project-');
  const originDir = path.join(parent, 'origin.git');
  const projectDir = path.join(parent, 'repo');
  execFileSync('git', ['init', '-q', '--bare', '-b', 'main', originDir]);
  execFileSync('git', ['clone', '-q', originDir, projectDir]);
  git(projectDir, ['config', 'user.email', 'spec@example.com']);
  git(projectDir, ['config', 'user.name', 'spec']);
  fs.writeFileSync(path.join(projectDir, 'README.md'), 'init\n');
  git(projectDir, ['add', 'README.md']);
  git(projectDir, ['commit', '-q', '-m', 'init']);
  git(projectDir, ['push', '-q', '-u', 'origin', 'main']);

  const worktreePaths = [];
  for (let i = 0; i < n; i++) {
    const wtPath = path.join(projectDir, '.claude', 'worktrees', `wt${i}`);
    git(projectDir, ['worktree', 'add', wtPath, '-b', `wt-branch-${i}`]);
    worktreePaths.push(wtPath);
  }
  return { parent, projectDir, worktreePaths };
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
if (!fs.existsSync(DS_CLEANUP)) {
  console.error(`FAIL: bin/ds-cleanup-worktrees not found at ${DS_CLEANUP}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// (W1) normal PATH, repo-dir.sh present, 6 non-root worktrees -> nudge present
// ---------------------------------------------------------------------------
console.log('\n[W1] dev-checkout layout, normal PATH, 6 non-root worktrees (>= threshold 5)');
let w1Fixture;
{
  w1Fixture = buildProjectWithWorktrees(6);
  const fakeHome = seedFakeHome(REPO_ROOT);

  const { code, systemMessage } = runHook(SCRIPT, w1Fixture.projectDir, fakeHome, null);
  assert(code === 0, 'W1: hook exits 0');
  assert(systemMessage.includes('6 non-root git worktrees in this project'),
    `W1: systemMessage contains the 6-worktree nudge (got: ${JSON.stringify(systemMessage)})`);
  assert(systemMessage.includes('/ds-cleanup-worktrees'),
    `W1: systemMessage points at /ds-cleanup-worktrees (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
}

// ---------------------------------------------------------------------------
// (W2) PATH stripped of ~/.local/bin, repo-dir.sh present: nudge still present
// ---------------------------------------------------------------------------
console.log('\n[W2] dev-checkout layout, PATH stripped of ~/.local/bin, 6 non-root worktrees');
{
  const { projectDir, parent } = buildProjectWithWorktrees(6);
  const fakeHome = seedFakeHome(REPO_ROOT);

  const { code, systemMessage } = runHook(SCRIPT, projectDir, fakeHome, strippedPath());
  assert(code === 0, 'W2: hook exits 0');
  assert(systemMessage.includes('6 non-root git worktrees in this project'),
    `W2: systemMessage still contains the nudge with ~/.local/bin stripped from PATH (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(parent);
}

// ---------------------------------------------------------------------------
// (W3) DEPLOYED layout: scripts/lib/repo-dir.sh absent + PATH stripped ->
// inline fallback must still resolve AE_REPO_DIR and surface the nudge.
// ---------------------------------------------------------------------------
console.log('\n[W3] DEPLOYED hooks-snapshot layout (no scripts/lib/repo-dir.sh), PATH stripped, 6 non-root worktrees');
{
  const { projectDir, parent } = buildProjectWithWorktrees(6);
  const fakeHome = seedFakeHome(REPO_ROOT);

  const fakeSnapshot = makeTmp('ae-wt-nudge-snapshot-');
  fs.cpSync(path.join(REPO_ROOT, 'hooks'), path.join(fakeSnapshot, 'hooks'), { recursive: true });
  fs.cpSync(path.join(REPO_ROOT, 'bin'), path.join(fakeSnapshot, 'bin'), { recursive: true });
  const snapshotScript = path.join(fakeSnapshot, 'hooks', 'session-start-wrap.sh');
  assert(fs.existsSync(snapshotScript), 'W3: fake snapshot script exists');
  assert(!fs.existsSync(path.join(fakeSnapshot, 'scripts', 'lib', 'repo-dir.sh')),
    'W3: precondition - scripts/lib/repo-dir.sh is absent from the fake deployed snapshot');

  const { code, systemMessage, stderr } = runHook(snapshotScript, projectDir, fakeHome, strippedPath());
  assert(code === 0, `W3: hook exits 0 (stderr: ${stderr})`);
  assert(systemMessage.includes('6 non-root git worktrees in this project'),
    `W3: deployed-layout inline fallback surfaces the nudge (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(fakeSnapshot);
  cleanup(parent);
}

// ---------------------------------------------------------------------------
// (W4) below threshold (2 non-root worktrees): no nudge line appended.
// ---------------------------------------------------------------------------
console.log('\n[W4] 2 non-root worktrees (below the 5-worktree threshold): no nudge line');
{
  const { projectDir, parent } = buildProjectWithWorktrees(2);
  const fakeHome = seedFakeHome(REPO_ROOT);

  const { code, systemMessage } = runHook(SCRIPT, projectDir, fakeHome, null);
  assert(code === 0, 'W4: hook exits 0');
  assert(!systemMessage.includes('non-root git worktrees'),
    `W4: no worktree nudge present below threshold (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(parent);
}

// ---------------------------------------------------------------------------
// (W5) report-only invariant: W1's worktrees are all still on disk after
// the hook ran - SessionStart must never remove anything.
// ---------------------------------------------------------------------------
console.log('\n[W5] report-only invariant: worktrees observed by W1 are still present');
{
  for (const wtPath of w1Fixture.worktreePaths) {
    assert(fs.existsSync(wtPath), `W5: worktree still present: ${wtPath}`);
  }
  cleanup(w1Fixture.parent);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
