#!/usr/bin/env node
/**
 * Regression tests: hooks/session-start-wrap.sh - the worktree-accumulation
 * nudge (5th systemMessage contributor, ds-cleanup-worktrees --dry-run) and
 * the DS-189 Unit B machine-wide worst-project nudge (6th contributor).
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
 *   W6 - machine-wide nudge (DS-189 Unit B): populated config, current
 *        repo IS the machine-wide worst -> cwd_toplevel dedup means no
 *        machine-wide line (single-repo nudge still fires independently).
 *   W7 - populated config, a DIFFERENT repo is worst and over threshold,
 *        no truncation -> machine-wide line present, "Worst project for
 *        stale worktrees machine-wide" wording, correct path/count.
 *   W7b - truncated=true in the multi-repo JSON -> subset wording
 *        ("Largest stale-worktree count among the first 20 scanned
 *        repos"), never the superlative wording.
 *   W8 - config file absent -> no machine-wide line; single-repo behavior
 *        unchanged.
 *   W9 - DS_CLEANUP_BIN unresolved (no bin/ds-cleanup-worktrees at the
 *        resolved AE_REPO_DIR, PATH stripped of ~/.local/bin) -> fully
 *        silent, no worktree line of any kind.
 *   W10 - resolved binary, non-git cwd -> silent (no worktree line).
 *   W11 - resolved binary, git cwd, genuine subprocess failure (mock exits
 *        1) -> visible "worktree-count check failed unexpectedly
 *        (ds-cleanup-worktrees exited 1)" line.
 *   W12 - empty-config exit-2 path (mock exits 2 with empty stdout on
 *        --multi-repo) -> machine-wide silent AND the composed
 *        systemMessage still contains another seeded contributor line
 *        (deferred-work nudge) AND stdout parses as valid JSON.
 *   W13 - timeout path: mocks a hang so the real `timeout`/`gtimeout`
 *        wrapper fires (rc=124) -> silent + survival, like W12. Loudly
 *        SKIPped (not silently green) when no timeout/gtimeout binary is
 *        present on the test machine.
 *   W13b - no-timeout-binary degrade path: with `timeout`/`gtimeout`
 *        hidden from PATH, a HEALTHY multi-repo run still produces the
 *        machine-wide line - proves the else-branch (bounded by
 *        --max-repos alone) is live.
 *   W14 - python3 unavailable (for the machine-wide inner JSON parse, via
 *        a PATH with git but no python3, and a non-git cwd so the
 *        single-repo gate is silently skipped independent of python3) ->
 *        silent, hook survives, valid JSON payload.
 *   W15 - payload `source` is `compact`, 6 worktrees, a different machine-wide
 *        worst repo, a seeded deferred item -> neither worktree line, the
 *        deferred-work line survives, valid JSON. The same fixture with
 *        `startup` shows both worktree lines.
 *   W16 - `startup`, `resume`, `clear` -> the worktree nudge is present.
 *   W17 - jq stubbed to fail, `compact` -> the grep fallback reads `source`
 *        and the nudge is skipped.
 *   W18 - jq stubbed to fail, `startup`, and an earlier `"event_source":
 *        "compact"` key -> the nudge is present.
 *   W19 - SessionStart worktree sweep kill switch: AE_WORKTREE_REAP_DISABLE=1
 *        launches nothing; the same fixture without it launches the sweep
 *        with --min-age-hours 24. Every other case runs with the kill switch
 *        set, so no sweep starts against its fixture.
 *   W20-W31 - the machine-wide sweep (block (i2)) over other repos that
 *        have a log in the fake HOME's ~/.agentic/worktree-reap/:
 *   W20 - a stale other repo B is swept with --min-age-hours 24; the
 *        current repo A is not.
 *   W21 - a log written within 6 h is skipped.
 *   W22 - a non-git cwd still sweeps the other repos.
 *   W23 - a log root that is missing, not a git repo, or not a main
 *        checkout is skipped.
 *   W24 - a repo with no non-root worktree registers itself (a log whose
 *        line 1 is a register header).
 *   W25 - every stale repo is claimed before the first sweep exits.
 *   W26 - AE_WORKTREE_REAP_DISABLE set: the current repo's opt-out marker
 *        is written and nothing is launched.
 *   W27 - B's marker makes A skip B; a later session in B without the
 *        variable clears it, and A then sweeps B.
 *   W28 - B's .claude/settings.json or settings.local.json sets the
 *        variable, so B is skipped.
 *   W29 - an existing claim for the current 6 h bucket blocks the sweep,
 *        and two concurrent hook runs sweep B exactly once.
 *   W30 - unparsable settings in B, so B is skipped.
 *   W31 - non-git cwd with the variable set: nothing launched, no marker.
 *
 * Run with: node hooks/tests/test-session-start-wrap-worktree-nudge.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFileSync, spawnSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SCRIPT = path.resolve(__dirname, '..', 'session-start-wrap.sh');
const DS_CLEANUP = path.resolve(REPO_ROOT, 'bin', 'ds-cleanup-worktrees');

let passed = 0;
let failed = 0;
let skipped = 0;

function assert(condition, message) {
  if (condition) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message}`);
    failed++;
  }
}

function skip(message) {
  console.log(`  SKIP: ${message}`);
  skipped++;
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

/**
 * Writes $fakeHome/.agentic/agentic-engineering-config.json (repo_dir
 * resolution) and, when `cleanupConfig` is given, $fakeHome/.agentic/
 * cleanup-worktrees.json (the DS-189 Unit B machine-wide config gate).
 */
function seedFakeHome(repoDir, cleanupConfig) {
  const fakeHome = makeTmp('ae-wt-nudge-home-');
  fs.mkdirSync(path.join(fakeHome, '.agentic'), { recursive: true });
  fs.writeFileSync(
    path.join(fakeHome, '.agentic', 'agentic-engineering-config.json'),
    JSON.stringify({ repo_dir: repoDir }),
    'utf8',
  );
  if (cleanupConfig !== undefined) {
    fs.writeFileSync(
      path.join(fakeHome, '.agentic', 'cleanup-worktrees.json'),
      JSON.stringify(cleanupConfig),
      'utf8',
    );
  }
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

/**
 * Lean repo builder for multi-repo fixtures (W6-W8, W13/W13b): a plain
 * `git init` (no origin/remote/commit needed - `--count-only`'s fast tier
 * never calls `gh` or `git ls-remote`) with `n` non-root worktrees added
 * directly off the unborn HEAD.
 */
function buildBareRepoWithWorktrees(n, prefix) {
  const dir = makeTmp(prefix || 'ae-wt-nudge-bare-');
  execFileSync('git', ['init', '-q', dir]);
  for (let i = 0; i < n; i++) {
    execFileSync('git', ['-C', dir, 'worktree', 'add', `wt${i}`, '-b', `b${i}`], { cwd: dir });
  }
  return dir;
}

function strippedPath() {
  return process.env.PATH
    .split(path.delimiter)
    .filter((p) => !p.includes('.local/bin'))
    .join(path.delimiter);
}

/**
 * Builds a curated PATH containing ONLY `/usr/bin:/bin` (present on every
 * macOS test machine: real git + real python3, but NO timeout/gtimeout -
 * those ship only via Homebrew coreutils under /opt/homebrew/bin or
 * /usr/local/bin). Used for W13b to prove the no-coreutils-timeout degrade
 * branch is live without disturbing git/python3 availability.
 */
function pathWithoutTimeout() {
  return '/usr/bin:/bin';
}

/**
 * Builds a PATH that SHADOWS `python3` with a stub that always exits 127
 * (simulating "command not found"), prepended before the real PATH - every
 * other tool (grep, sed, dirname, git, bash, ...) still resolves normally
 * via the real PATH entries that follow. A dir-removal approach (stripping
 * whichever directories carry `python3`) was tried first and rejected: on
 * this machine python3, git, grep, sed, dirname, and head are ALL
 * co-located in the same PATH directories (/usr/bin, /opt/homebrew/bin),
 * so excluding "the python3 directory" also breaks the coreutils
 * session-start-wrap.sh itself depends on before it ever reaches the
 * worktree-nudge block, producing an unrelated early failure.
 */
function pathWithoutPython3() {
  const dir = makeTmp('ae-wt-nudge-nopy-');
  const stubPath = path.join(dir, 'python3');
  fs.writeFileSync(stubPath, '#!/bin/sh\necho "python3: command not found" >&2\nexit 127\n', 'utf8');
  fs.chmodSync(stubPath, 0o755);
  return { path: `${dir}:${process.env.PATH}`, dir };
}

/**
 * Same shadowing method as pathWithoutPython3, for `jq`: the stub exits
 * non-zero, so the hook's grep/sed fallback is what extracts the payload
 * fields.
 */
function pathWithFailingJq() {
  const dir = makeTmp('ae-wt-nudge-nojq-');
  const stubPath = path.join(dir, 'jq');
  fs.writeFileSync(stubPath, '#!/bin/sh\nexit 1\n', 'utf8');
  fs.chmodSync(stubPath, 0o755);
  return { path: `${dir}:${process.env.PATH}`, dir };
}

/**
 * Run the SessionStart hook (given script path) with a given projectDir as
 * cwd, a fake HOME, and an optional PATH override. AGENTIC_QUIET is
 * explicitly unset so the composed systemMessage is populated.
 */
function runHook(scriptPath, projectDir, fakeHome, pathOverride, extraEnv, source, extraPayload) {
  const fields = Object.assign({ cwd: projectDir }, extraPayload || {});
  if (source !== undefined) {
    fields.source = source;
  }
  const payload = JSON.stringify(fields);
  const env = Object.assign({}, process.env, {
    HOME: fakeHome,
    AGENTIC_WRAP_DAEMON: '1', // never spawn the real daemon from a test
    AE_WORKTREE_REAP_DISABLE: '1', // nor the worktree sweep, unless a case unsets it
  }, extraEnv || {});
  for (const key of Object.keys(env)) {
    if (env[key] === undefined) delete env[key];
  }
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
  let parsedOk = false;
  try {
    const parsed = JSON.parse(res.stdout || '{}');
    systemMessage = parsed.systemMessage || '';
    parsedOk = true;
  } catch (_) {
    // leave empty; assertions below will fail visibly on bad JSON
  }
  return { code: res.status, stdout: res.stdout || '', stderr: res.stderr || '', systemMessage, parsedOk };
}

/**
 * Writes a mock `ds-cleanup-worktrees` at $repoDir/bin/ds-cleanup-worktrees
 * as a Python script (invoked via `python3 "$DS_CLEANUP_BIN" ...`, so it
 * only needs to be a valid python3 program, not independently executable -
 * chmod +x is still set to satisfy the hook's own `[[ -x ... ]]` resolution
 * check). `body` is the full Python source. `repoDir` is `git init`ed FIRST
 * - `scripts/lib/repo-dir.sh`'s `resolve_repo_dir` validates the resolved
 * `repo_dir` IS a git repo and silently substitutes `$HOME/DinoStack`
 * otherwise (measured: a non-git mock dir makes AE_REPO_DIR resolution fall
 * straight through to the absent `$HOME/DinoStack`, which then makes
 * DS_CLEANUP_BIN unresolvable and the whole nudge silently skip - not what
 * these mock-binary tests are exercising).
 */
function writeMockCleanupBin(repoDir, body) {
  execFileSync('git', ['init', '-q', repoDir]);
  const binDir = path.join(repoDir, 'bin');
  fs.mkdirSync(binDir, { recursive: true });
  const binPath = path.join(binDir, 'ds-cleanup-worktrees');
  fs.writeFileSync(binPath, body, 'utf8');
  fs.chmodSync(binPath, 0o755);
  return binPath;
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
{
  const w1Fixture = buildProjectWithWorktrees(6);
  const fakeHome = seedFakeHome(REPO_ROOT);

  const { code, systemMessage } = runHook(SCRIPT, w1Fixture.projectDir, fakeHome, null);
  assert(code === 0, 'W1: hook exits 0');
  assert(systemMessage.includes('6 non-root git worktrees in this project'),
    `W1: systemMessage contains the 6-worktree nudge (got: ${JSON.stringify(systemMessage)})`);
  assert(systemMessage.includes('/ds-cleanup-worktrees'),
    `W1: systemMessage points at /ds-cleanup-worktrees (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(w1Fixture.parent);
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
// (W6) machine-wide nudge: cwd itself is the worst -> cwd_toplevel dedup,
// no machine-wide line (single-repo nudge still fires independently).
// ---------------------------------------------------------------------------
console.log('\n[W6] machine-wide config populated, cwd IS the worst repo -> dedup, no machine-wide line');
{
  const repoA = buildBareRepoWithWorktrees(6, 'ae-wt-nudge-w6a-'); // worst
  const repoB = buildBareRepoWithWorktrees(1, 'ae-wt-nudge-w6b-'); // decoy
  const fakeHome = seedFakeHome(REPO_ROOT, { repos: [repoA, repoB] });

  const { code, systemMessage } = runHook(SCRIPT, repoA, fakeHome, null);
  assert(code === 0, 'W6: hook exits 0');
  assert(systemMessage.includes('6 non-root git worktrees in this project'),
    `W6: single-repo nudge still fires for cwd's own count (got: ${JSON.stringify(systemMessage)})`);
  assert(!systemMessage.includes('Worst project for stale worktrees machine-wide'),
    `W6: no machine-wide line when cwd IS the worst repo (got: ${JSON.stringify(systemMessage)})`);
  assert(!systemMessage.includes('Largest stale-worktree count among the first 20'),
    `W6: no truncated-subset machine-wide line either (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(repoA);
  cleanup(repoB);
}

// ---------------------------------------------------------------------------
// (W7) machine-wide nudge: a DIFFERENT repo is worst and over threshold,
// no truncation -> line present, superlative wording, correct path/count.
// ---------------------------------------------------------------------------
console.log('\n[W7] machine-wide config populated, a different repo is worst (no truncation) -> superlative line');
{
  const cwdRepo = buildBareRepoWithWorktrees(1, 'ae-wt-nudge-w7cwd-'); // below threshold
  const worstRepo = buildBareRepoWithWorktrees(7, 'ae-wt-nudge-w7worst-'); // worst, over threshold
  const fakeHome = seedFakeHome(REPO_ROOT, { repos: [cwdRepo, worstRepo] });

  const { code, systemMessage } = runHook(SCRIPT, cwdRepo, fakeHome, null);
  assert(code === 0, 'W7: hook exits 0');
  assert(!systemMessage.includes('non-root git worktrees in this project'),
    `W7: cwd's own single-repo nudge stays silent (1 < threshold 5) (got: ${JSON.stringify(systemMessage)})`);
  assert(systemMessage.includes('Worst project for stale worktrees machine-wide'),
    `W7: machine-wide superlative wording present (got: ${JSON.stringify(systemMessage)})`);
  assert(systemMessage.includes(worstRepo),
    `W7: machine-wide line names the correct worst repo path (got: ${JSON.stringify(systemMessage)})`);
  assert(systemMessage.includes('(7 non-root worktrees)'),
    `W7: machine-wide line carries the correct count (got: ${JSON.stringify(systemMessage)})`);
  assert(!systemMessage.includes('Largest stale-worktree count among the first 20'),
    `W7: never the truncated-subset wording when truncated is false (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(cwdRepo);
  cleanup(worstRepo);
}

// ---------------------------------------------------------------------------
// (W7b) truncated=true -> subset wording, never the superlative wording.
// ---------------------------------------------------------------------------
console.log('\n[W7b] machine-wide config with 21 repos (> --max-repos 20) -> truncated subset wording');
{
  const worstRepo = buildBareRepoWithWorktrees(6, 'ae-wt-nudge-w7b-worst-'); // index 0, kept
  const decoys = [];
  for (let i = 0; i < 20; i++) {
    decoys.push(buildBareRepoWithWorktrees(0, 'ae-wt-nudge-w7b-decoy-'));
  }
  const cwdRepo = buildBareRepoWithWorktrees(0, 'ae-wt-nudge-w7b-cwd-'); // not in config at all
  const fakeHome = seedFakeHome(REPO_ROOT, { repos: [worstRepo, ...decoys] }); // 21 total > 20 max

  const { code, systemMessage } = runHook(SCRIPT, cwdRepo, fakeHome, null);
  assert(code === 0, 'W7b: hook exits 0');
  assert(systemMessage.includes('Largest stale-worktree count among the first 20 scanned repos'),
    `W7b: truncated-subset wording present (got: ${JSON.stringify(systemMessage)})`);
  assert(!systemMessage.includes('Worst project for stale worktrees machine-wide'),
    `W7b: never the superlative wording when truncated (got: ${JSON.stringify(systemMessage)})`);
  assert(systemMessage.includes(worstRepo),
    `W7b: names the correct (index-0, kept-in-truncation) worst repo (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(worstRepo);
  for (const d of decoys) cleanup(d);
  cleanup(cwdRepo);
}

// ---------------------------------------------------------------------------
// (W8) config file absent -> no machine-wide line; single-repo unchanged.
// ---------------------------------------------------------------------------
console.log('\n[W8] machine-wide config absent -> no machine-wide line, single-repo nudge unchanged');
{
  const { projectDir, parent } = buildProjectWithWorktrees(6);
  const fakeHome = seedFakeHome(REPO_ROOT); // no cleanupConfig arg -> file never written

  const { code, systemMessage } = runHook(SCRIPT, projectDir, fakeHome, null);
  assert(code === 0, 'W8: hook exits 0');
  assert(systemMessage.includes('6 non-root git worktrees in this project'),
    `W8: single-repo nudge still fires (got: ${JSON.stringify(systemMessage)})`);
  assert(!systemMessage.includes('machine-wide'),
    `W8: no machine-wide line when config is absent (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(parent);
}

// ---------------------------------------------------------------------------
// (W9) DS_CLEANUP_BIN unresolved -> fully silent, no worktree line at all.
// ---------------------------------------------------------------------------
console.log('\n[W9] DS_CLEANUP_BIN unresolved (no bin/ds-cleanup-worktrees, PATH stripped) -> silent');
{
  const { projectDir, parent } = buildProjectWithWorktrees(6);
  const emptyRepoDir = makeTmp('ae-wt-nudge-empty-repodir-'); // no bin/ subdir at all
  const fakeHome = seedFakeHome(emptyRepoDir, { repos: [projectDir] });

  const { code, systemMessage } = runHook(SCRIPT, projectDir, fakeHome, strippedPath());
  assert(code === 0, 'W9: hook exits 0');
  assert(!systemMessage.includes('non-root git worktrees'),
    `W9: no single-repo nudge (got: ${JSON.stringify(systemMessage)})`);
  assert(!systemMessage.includes('worktree-count check failed'),
    `W9: no visible failure line either - unresolved binary is silent (got: ${JSON.stringify(systemMessage)})`);
  assert(!systemMessage.toLowerCase().includes('machine-wide'),
    `W9: no machine-wide line (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(emptyRepoDir);
  cleanup(parent);
}

// ---------------------------------------------------------------------------
// (W10) resolved binary, non-git cwd -> silent.
// ---------------------------------------------------------------------------
console.log('\n[W10] resolved binary, non-git cwd -> silent');
{
  const nonGitDir = makeTmp('ae-wt-nudge-nongit-');
  const fakeHome = seedFakeHome(REPO_ROOT);

  const { code, systemMessage } = runHook(SCRIPT, nonGitDir, fakeHome, null);
  assert(code === 0, 'W10: hook exits 0');
  assert(!systemMessage.includes('non-root git worktrees'),
    `W10: no single-repo nudge for a non-git cwd (got: ${JSON.stringify(systemMessage)})`);
  assert(!systemMessage.includes('worktree-count check failed'),
    `W10: no visible failure line - non-git cwd is silent, not an error (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(nonGitDir);
}

// ---------------------------------------------------------------------------
// (W11) resolved binary, git cwd, genuine subprocess failure -> VISIBLE
// exit-code-naming line.
// ---------------------------------------------------------------------------
console.log('\n[W11] resolved binary, git cwd, mock exits 1 -> visible "worktree-count check failed" line');
{
  const { projectDir, parent } = buildProjectWithWorktrees(0);
  const mockRepoDir = makeTmp('ae-wt-nudge-mockbin-');
  writeMockCleanupBin(mockRepoDir, 'import sys\nsys.exit(1)\n');
  const fakeHome = seedFakeHome(mockRepoDir);

  const { code, systemMessage } = runHook(SCRIPT, projectDir, fakeHome, strippedPath());
  assert(code === 0, 'W11: hook exits 0 (fail-open even on a genuine subprocess failure)');
  assert(systemMessage.includes('worktree-count check failed unexpectedly (ds-cleanup-worktrees exited 1)'),
    `W11: visible exit-code-naming line present (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(mockRepoDir);
  cleanup(parent);
}

// ---------------------------------------------------------------------------
// (W12) empty-config exit-2 path (mock exits 2 with empty stdout on
// --multi-repo) -> machine-wide silent, but another seeded contributor
// (deferred-work) survives, and stdout is still valid JSON.
// ---------------------------------------------------------------------------
console.log('\n[W12] mock --multi-repo call exits 2 with empty stdout (empty-config path) -> machine-wide silent, other contributors survive');
{
  const { projectDir, parent } = buildProjectWithWorktrees(0); // below threshold single-repo
  const mockRepoDir = makeTmp('ae-wt-nudge-mockbin-w12-');
  writeMockCleanupBin(mockRepoDir, `import sys
if "--multi-repo" in sys.argv:
    sys.exit(2)
print("ds-cleanup-worktrees: mode=count-only entries=1")
sys.exit(0)
`);
  // Also carry the REAL bin/ds-defer (plus its sibling bin/_lib.py, which
  // ds-defer imports at runtime and expects to find alongside itself)
  // alongside the mock ds-cleanup-worktrees, so the deferred-work nudge (an
  // independent contributor) can actually resolve and fire from the same
  // AE_REPO_DIR.
  fs.cpSync(path.join(REPO_ROOT, 'bin', 'ds-defer'), path.join(mockRepoDir, 'bin', 'ds-defer'));
  fs.chmodSync(path.join(mockRepoDir, 'bin', 'ds-defer'), 0o755);
  fs.cpSync(path.join(REPO_ROOT, 'bin', '_lib.py'), path.join(mockRepoDir, 'bin', '_lib.py'));
  const fakeHome = seedFakeHome(mockRepoDir, { repos: [] }); // file present -> gate opens

  // Seed a deferred-work entry so the defer_msg contributor is present and
  // its survival can be asserted alongside machine-wide silence.
  const agenticDir = path.join(projectDir, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  fs.writeFileSync(
    path.join(agenticDir, 'deferred-work.jsonl'),
    `${JSON.stringify({ id: 'w12-defer-1', status: 'open', text: 'w12 seeded deferred item' })}\n`,
    'utf8',
  );

  const { code, systemMessage, parsedOk } = runHook(SCRIPT, projectDir, fakeHome, strippedPath());
  assert(code === 0, 'W12: hook exits 0');
  assert(parsedOk, 'W12: stdout parses as valid JSON');
  assert(!systemMessage.toLowerCase().includes('machine-wide'),
    `W12: no machine-wide line on the empty-config exit-2 path (got: ${JSON.stringify(systemMessage)})`);
  assert(systemMessage.includes('deferred-work item(s) pending'),
    `W12: another seeded contributor (deferred-work) survives (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(mockRepoDir);
  cleanup(parent);
}

// ---------------------------------------------------------------------------
// (W13) timeout path: a mock that hangs, forcing the real timeout/gtimeout
// wrapper to fire (rc=124) -> silent + survival. Loudly SKIPped when no
// timeout/gtimeout binary exists on the test machine.
// ---------------------------------------------------------------------------
console.log('\n[W13] mock --multi-repo call hangs -> real timeout wrapper fires (rc=124) -> silent + survival');
{
  const hasTimeoutBin = spawnSync('bash', ['-c', 'command -v timeout || command -v gtimeout'], { encoding: 'utf8' }).stdout.trim();
  if (!hasTimeoutBin) {
    skip('W13: no timeout/gtimeout binary on this test machine - cannot exercise the real wrapper');
  } else {
    const { projectDir, parent } = buildProjectWithWorktrees(0);
    const mockRepoDir = makeTmp('ae-wt-nudge-mockbin-w13-');
    writeMockCleanupBin(mockRepoDir, `import sys, time
if "--multi-repo" in sys.argv:
    time.sleep(30)
    sys.exit(0)
print("ds-cleanup-worktrees: mode=count-only entries=1")
sys.exit(0)
`);
    const fakeHome = seedFakeHome(mockRepoDir, { repos: [] });

    const start = Date.now();
    const { code, systemMessage, parsedOk } = runHook(SCRIPT, projectDir, fakeHome, strippedPath());
    const elapsedMs = Date.now() - start;
    assert(code === 0, 'W13: hook exits 0');
    assert(parsedOk, 'W13: stdout parses as valid JSON');
    assert(!systemMessage.toLowerCase().includes('machine-wide'),
      `W13: no machine-wide line when the call times out (got: ${JSON.stringify(systemMessage)})`);
    assert(elapsedMs < 15000,
      `W13: hook returns promptly, bounded by the 5s timeout wrapper (elapsed: ${elapsedMs}ms)`);

    cleanup(fakeHome);
    cleanup(mockRepoDir);
    cleanup(parent);
  }
}

// ---------------------------------------------------------------------------
// (W13b) no-timeout-binary degrade path: with timeout/gtimeout hidden from
// PATH, a HEALTHY multi-repo run still produces the machine-wide line.
// ---------------------------------------------------------------------------
console.log('\n[W13b] timeout/gtimeout hidden from PATH, healthy run -> machine-wide line still produced (else-branch is live)');
{
  const cwdRepo = buildBareRepoWithWorktrees(1, 'ae-wt-nudge-w13b-cwd-');
  const worstRepo = buildBareRepoWithWorktrees(8, 'ae-wt-nudge-w13b-worst-');
  const fakeHome = seedFakeHome(REPO_ROOT, { repos: [cwdRepo, worstRepo] });

  const { code, systemMessage } = runHook(SCRIPT, cwdRepo, fakeHome, pathWithoutTimeout());
  assert(code === 0, `W13b: hook exits 0`);
  assert(systemMessage.includes('Worst project for stale worktrees machine-wide'),
    `W13b: machine-wide line present without timeout/gtimeout on PATH (got: ${JSON.stringify(systemMessage)})`);
  assert(systemMessage.includes(worstRepo),
    `W13b: correct worst repo path (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(cwdRepo);
  cleanup(worstRepo);
}

// ---------------------------------------------------------------------------
// (W14) python3 unavailable (for the machine-wide inner parse) -> silent,
// hook survives, valid JSON payload. Uses a non-git cwd so the single-repo
// gate is silently skipped independent of python3 availability.
// ---------------------------------------------------------------------------
console.log('\n[W14] python3 unresolvable on PATH, non-git cwd, config populated -> silent, hook survives, valid JSON');
{
  const nonGitDir = makeTmp('ae-wt-nudge-w14-nongit-');
  const decoyRepo = buildBareRepoWithWorktrees(6, 'ae-wt-nudge-w14-decoy-');
  const fakeHome = seedFakeHome(REPO_ROOT, { repos: [decoyRepo] });
  const { path: noPyPath, dir: noPyDir } = pathWithoutPython3();

  const { code, systemMessage, parsedOk } = runHook(SCRIPT, nonGitDir, fakeHome, noPyPath);
  assert(code === 0, 'W14: hook exits 0');
  assert(parsedOk, 'W14: stdout parses as valid JSON');
  assert(!systemMessage.toLowerCase().includes('machine-wide'),
    `W14: no machine-wide line when python3 is unresolvable (got: ${JSON.stringify(systemMessage)})`);
  assert(!systemMessage.includes('worktree-count check failed'),
    `W14: no visible single-repo failure line either - non-git cwd short-circuits that gate (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(nonGitDir);
  cleanup(decoyRepo);
  cleanup(noPyDir);
}

// ---------------------------------------------------------------------------
// (W15) source=compact -> both worktree nudges skipped, other contributors
// unchanged. The startup run on the same fixture proves both lines would fire.
// ---------------------------------------------------------------------------
console.log('\n[W15] source=compact, 6 worktrees, different machine-wide worst, seeded deferred item -> no worktree lines, defer line kept');
{
  const cwdRepo = buildBareRepoWithWorktrees(6, 'ae-wt-nudge-w15-cwd-');
  const worstRepo = buildBareRepoWithWorktrees(8, 'ae-wt-nudge-w15-worst-');
  const fakeHome = seedFakeHome(REPO_ROOT, { repos: [cwdRepo, worstRepo] });
  const agenticDir = path.join(cwdRepo, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  fs.writeFileSync(
    path.join(agenticDir, 'deferred-work.jsonl'),
    `${JSON.stringify({ id: 'w15-defer-1', status: 'open', text: 'w15 seeded deferred item' })}\n`,
    'utf8',
  );

  const control = runHook(SCRIPT, cwdRepo, fakeHome, null, null, 'startup');
  assert(control.systemMessage.includes('6 non-root git worktrees in this project')
    && control.systemMessage.includes('Worst project for stale worktrees machine-wide')
    && control.systemMessage.includes('deferred-work item(s) pending'),
    `W15: control - with source=startup the fixture shows both worktree lines and the defer line (got: ${JSON.stringify(control.systemMessage)})`);

  const { code, systemMessage, parsedOk } = runHook(SCRIPT, cwdRepo, fakeHome, null, null, 'compact');
  assert(code === 0, 'W15: hook exits 0');
  assert(parsedOk, 'W15: stdout parses as valid JSON');
  assert(!systemMessage.includes('non-root git worktrees in this project'),
    `W15: no single-repo worktree line on compact (got: ${JSON.stringify(systemMessage)})`);
  assert(!systemMessage.toLowerCase().includes('machine-wide'),
    `W15: no machine-wide line on compact (got: ${JSON.stringify(systemMessage)})`);
  assert(systemMessage.includes('deferred-work item(s) pending'),
    `W15: deferred-work line still present on compact (got: ${JSON.stringify(systemMessage)})`);

  cleanup(fakeHome);
  cleanup(cwdRepo);
  cleanup(worstRepo);
}

// ---------------------------------------------------------------------------
// (W16) every non-compact source keeps the nudge.
// ---------------------------------------------------------------------------
console.log('\n[W16] source=startup/resume/clear -> worktree nudge present');
{
  const cwdRepo = buildBareRepoWithWorktrees(6, 'ae-wt-nudge-w16-');
  const fakeHome = seedFakeHome(REPO_ROOT);
  for (const source of ['startup', 'resume', 'clear']) {
    const { code, systemMessage } = runHook(SCRIPT, cwdRepo, fakeHome, null, null, source);
    assert(code === 0, `W16: hook exits 0 (source=${source})`);
    assert(systemMessage.includes('6 non-root git worktrees in this project'),
      `W16: nudge present for source=${source} (got: ${JSON.stringify(systemMessage)})`);
  }
  cleanup(fakeHome);
  cleanup(cwdRepo);
}

// ---------------------------------------------------------------------------
// (W17) jq fails -> the grep fallback still reads source=compact.
// ---------------------------------------------------------------------------
console.log('\n[W17] jq stubbed to fail, source=compact -> nudge skipped via the grep fallback');
{
  const cwdRepo = buildBareRepoWithWorktrees(6, 'ae-wt-nudge-w17-');
  const fakeHome = seedFakeHome(REPO_ROOT);
  const { path: noJqPath, dir: noJqDir } = pathWithFailingJq();
  const { code, systemMessage, parsedOk } = runHook(SCRIPT, cwdRepo, fakeHome, noJqPath, null, 'compact');
  assert(code === 0, 'W17: hook exits 0');
  assert(parsedOk, 'W17: stdout parses as valid JSON');
  assert(!systemMessage.includes('non-root git worktrees in this project'),
    `W17: nudge skipped on compact with jq failing (got: ${JSON.stringify(systemMessage)})`);
  cleanup(fakeHome);
  cleanup(cwdRepo);
  cleanup(noJqDir);
}

// ---------------------------------------------------------------------------
// (W18) jq fails, source=startup, and an earlier key ending in "source"
// holds "compact" -> the fallback must anchor on the exact "source" key.
// ---------------------------------------------------------------------------
console.log('\n[W18] jq stubbed to fail, source=startup, decoy "event_source": "compact" before it -> nudge present');
{
  const cwdRepo = buildBareRepoWithWorktrees(6, 'ae-wt-nudge-w18-');
  const fakeHome = seedFakeHome(REPO_ROOT);
  const { path: noJqPath, dir: noJqDir } = pathWithFailingJq();
  const { code, systemMessage, parsedOk } = runHook(SCRIPT, cwdRepo, fakeHome, noJqPath, null, 'startup',
    { event_source: 'compact' });
  assert(code === 0, 'W18: hook exits 0');
  assert(parsedOk, 'W18: stdout parses as valid JSON');
  assert(systemMessage.includes('6 non-root git worktrees in this project'),
    `W18: nudge present - the event_source decoy is not read as source (got: ${JSON.stringify(systemMessage)})`);
  cleanup(fakeHome);
  cleanup(cwdRepo);
  cleanup(noJqDir);
}

// ---------------------------------------------------------------------------
// (W19) AE_WORKTREE_REAP_DISABLE=1 launches no SessionStart worktree sweep;
// the same fixture without it launches one, so the absence is the switch.
// ---------------------------------------------------------------------------
console.log('\n[W19] AE_WORKTREE_REAP_DISABLE=1 -> no sweep launched; unset -> sweep launched with --min-age-hours 24');
{
  const { projectDir, parent } = buildProjectWithWorktrees(1);
  const mockRepoDir = makeTmp('ae-wt-nudge-w19-mock-');
  const launchLog = path.join(mockRepoDir, 'launches.txt');
  writeMockCleanupBin(mockRepoDir, `import sys
if '--count-only' in sys.argv:
    print('ds-cleanup-worktrees: mode=count-only entries=2')
    sys.exit(0)
with open(${JSON.stringify(launchLog)}, 'a') as handle:
    handle.write(' '.join(sys.argv[1:]) + '\\n')
`);
  const fakeHome = seedFakeHome(mockRepoDir);
  const sleepMs = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

  const disabled = runHook(SCRIPT, projectDir, fakeHome, null, { AE_WORKTREE_REAP_DISABLE: '1' });
  assert(disabled.code === 0, 'W19: hook exits 0 with the kill switch set');
  sleepMs(1500);
  assert(!fs.existsSync(launchLog), 'W19: kill switch set -> the sweep was never launched');
  const reapDirW19 = path.join(fakeHome, '.agentic', 'worktree-reap');
  const logsW19 = fs.existsSync(reapDirW19) ? fs.readdirSync(reapDirW19).filter((f) => f.endsWith('.log')) : [];
  assert(logsW19.length === 0,
    `W19: kill switch set -> no sweep log was created (got: ${JSON.stringify(logsW19)})`);

  const enabled = runHook(SCRIPT, projectDir, fakeHome, null, { AE_WORKTREE_REAP_DISABLE: undefined });
  assert(enabled.code === 0, 'W19: hook exits 0 with the kill switch unset');
  // Poll the content, not existence: the mock's open() creates the file
  // before its write is flushed, so an existence check can read "".
  const expectedLaunch = `--repo ${projectDir} --min-age-hours 24`;
  let launched = '';
  for (let i = 0; i < 300 && !launched.includes(expectedLaunch); i++) {
    sleepMs(100);
    launched = fs.existsSync(launchLog) ? fs.readFileSync(launchLog, 'utf8') : '';
  }
  assert(launched.includes(expectedLaunch),
    `W19: kill switch unset -> sweep launched against the main checkout (got: ${JSON.stringify(launched)})`);

  cleanup(fakeHome);
  cleanup(mockRepoDir);
  cleanup(parent);
}

// ---------------------------------------------------------------------------
// Machine-wide sweep fixtures (W20-W31). Each case gets its own fake HOME,
// a mock ds-cleanup-worktrees that records every sweep it is asked to run,
// and plain `git init` repos. The mock reports one worktree entry, so the
// current repo never has a non-root worktree and block (i) stays idle.
// ---------------------------------------------------------------------------
function pauseMs(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function waitFor(predicate, ms) {
  const deadline = Date.now() + (ms || 20000);
  while (Date.now() < deadline) {
    if (predicate()) return true;
    pauseMs(100);
  }
  return predicate();
}

function reapStem(fakeHome, root) {
  const id = crypto.createHash('sha1').update(root).digest('hex').slice(0, 8);
  return path.join(fakeHome, '.agentic', 'worktree-reap', `${path.basename(root)}-${id}`);
}

function sweepFixture() {
  const mockRepoDir = makeTmp('ae-wt-sweep-mock-');
  const launchLog = path.join(mockRepoDir, 'launches.txt');
  writeMockCleanupBin(mockRepoDir, `import os, sys, time
if '--count-only' in sys.argv:
    print('ds-cleanup-worktrees: mode=count-only entries=1')
    sys.exit(0)
with open(${JSON.stringify(launchLog)}, 'a') as handle:
    handle.write(' '.join(sys.argv[1:]) + '\\n')
time.sleep(float(os.environ.get('SWEEP_STUB_SLEEP', '0')))
print('STUB_SWEEP_RAN')
`);
  const fakeHome = seedFakeHome(mockRepoDir);
  const reapDir = path.join(fakeHome, '.agentic', 'worktree-reap');
  fs.mkdirSync(reapDir, { recursive: true });
  return { mockRepoDir, launchLog, fakeHome, reapDir };
}

function makeMainRepo(prefix) {
  const dir = makeTmp(prefix);
  execFileSync('git', ['init', '-q', dir]);
  return dir;
}

/** A log for `root` whose line 1 is a reap header, last written `hoursAgo` hours ago. */
function registerLog(fx, root, hoursAgo) {
  const stem = reapStem(fx.fakeHome, root);
  const log = `${stem}.log`;
  fs.writeFileSync(log, `=== reap 2026-01-01T00:00:00Z pid 1 root ${root} ===\n`);
  const t = Date.now() / 1000 - hoursAgo * 3600;
  fs.utimesSync(log, t, t);
  return { stem, log };
}

function runSweepHook(fx, cwd, extraEnv) {
  return runHook(SCRIPT, cwd, fx.fakeHome, null,
    Object.assign({ AE_WORKTREE_REAP_DISABLE: undefined }, extraEnv || {}));
}

function launches(fx) {
  return fs.existsSync(fx.launchLog)
    ? fs.readFileSync(fx.launchLog, 'utf8').split('\n').filter(Boolean)
    : [];
}

function launchCount(fx, root) {
  return launches(fx).filter((l) => l === `--repo ${root} --min-age-hours 24`).length;
}

function reapHeaders(log, root) {
  if (!fs.existsSync(log)) return 0;
  return fs.readFileSync(log, 'utf8').split('\n')
    .filter((l) => l.startsWith('=== reap ') && l.endsWith(` root ${root} ===`)).length;
}

function claimsFor(fx, stem) {
  const prefix = `${path.basename(stem)}.claim.`;
  return fs.readdirSync(fx.reapDir).filter((f) => f.startsWith(prefix));
}

function filesMatching(fx, re) {
  return fs.existsSync(fx.reapDir) ? fs.readdirSync(fx.reapDir).filter((f) => re.test(f)) : [];
}

// ---------------------------------------------------------------------------
// (W20) a stale other repo is swept; the current repo is not.
// ---------------------------------------------------------------------------
console.log('\n[W20] stale logs for repos A and B, session in repo A -> B swept with --min-age-hours 24, A not');
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w20a-');
  const repoB = makeMainRepo('ae-wt-sweep-w20b-');
  registerLog(fx, repoA, 7);
  const b = registerLog(fx, repoB, 7);
  const { code } = runSweepHook(fx, repoA);
  assert(code === 0, 'W20: hook exits 0');
  assert(waitFor(() => launchCount(fx, repoB) === 1 && fs.readFileSync(b.log, 'utf8').includes('STUB_SWEEP_RAN')),
    `W20: B swept once, output in B's log (got: ${JSON.stringify(launches(fx))})`);
  assert(reapHeaders(b.log, repoB) === 2, 'W20: a reap header was appended to B\'s log before the sweep');
  assert(launchCount(fx, repoA) === 0 && claimsFor(fx, reapStem(fx.fakeHome, repoA)).length === 0,
    `W20: the current repo A, though stale, is neither claimed nor swept by block (i2) (got: ${JSON.stringify(launches(fx))})`);
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoB);
}

// ---------------------------------------------------------------------------
// (W21) a log written within 6 h is skipped.
// ---------------------------------------------------------------------------
console.log('\n[W21] B\'s log is 1 h old, C\'s is 7 h old -> only C swept');
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w21a-');
  const repoB = makeMainRepo('ae-wt-sweep-w21b-');
  const repoC = makeMainRepo('ae-wt-sweep-w21c-');
  const b = registerLog(fx, repoB, 1);
  registerLog(fx, repoC, 7);
  runSweepHook(fx, repoA);
  assert(waitFor(() => launchCount(fx, repoC) === 1), 'W21: control C swept');
  assert(launchCount(fx, repoB) === 0 && claimsFor(fx, b.stem).length === 0,
    `W21: fresh B neither claimed nor swept (got: ${JSON.stringify(launches(fx))})`);
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoB); cleanup(repoC);
}

// ---------------------------------------------------------------------------
// (W22) a non-git cwd still sweeps the other repos.
// ---------------------------------------------------------------------------
console.log('\n[W22] non-git cwd -> stale B still swept');
{
  const fx = sweepFixture();
  const plainDir = makeTmp('ae-wt-sweep-w22-plain-');
  const repoB = makeMainRepo('ae-wt-sweep-w22b-');
  registerLog(fx, repoB, 7);
  const { code } = runSweepHook(fx, plainDir);
  assert(code === 0, 'W22: hook exits 0');
  assert(waitFor(() => launchCount(fx, repoB) === 1),
    `W22: B swept from a non-git cwd (got: ${JSON.stringify(launches(fx))})`);
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(plainDir); cleanup(repoB);
}

// ---------------------------------------------------------------------------
// (W23) a root that is gone, not a repo, or not a main checkout is skipped.
// ---------------------------------------------------------------------------
console.log('\n[W23] log roots that are missing, non-git, a subdirectory, or a linked worktree -> skipped');
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w23a-');
  const repoC = makeMainRepo('ae-wt-sweep-w23c-');
  const scratch = makeTmp('ae-wt-sweep-w23-');
  const nonGit = path.join(scratch, 'plain');
  fs.mkdirSync(nonGit);
  const subdir = path.join(repoC, 'sub');
  fs.mkdirSync(subdir);
  const withWorktree = buildBareRepoWithWorktrees(1, 'ae-wt-sweep-w23w-');
  const roots = [path.join(scratch, 'gone'), nonGit, subdir, path.join(withWorktree, 'wt0')];
  const bad = roots.map((root) => Object.assign({ root }, registerLog(fx, root, 7)));
  registerLog(fx, repoC, 7);
  runSweepHook(fx, repoA);
  assert(waitFor(() => launchCount(fx, repoC) === 1), 'W23: control C swept');
  for (const entry of bad) {
    assert(launchCount(fx, entry.root) === 0 && claimsFor(fx, entry.stem).length === 0,
      `W23: ${entry.root} neither claimed nor swept (got: ${JSON.stringify(launches(fx))})`);
  }
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoC); cleanup(scratch);
  cleanup(withWorktree);
}

// ---------------------------------------------------------------------------
// (W24) a zero-worktree repo registers itself, and is then sweepable.
// ---------------------------------------------------------------------------
console.log('\n[W24] session in A with no non-root worktree and no log -> register header; a later session in D sweeps A');
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w24a-');
  const repoD = makeMainRepo('ae-wt-sweep-w24d-');
  const aLog = `${reapStem(fx.fakeHome, repoA)}.log`;
  runSweepHook(fx, repoA);
  assert(waitFor(() => fs.existsSync(aLog) && fs.readFileSync(aLog, 'utf8').length > 0), 'W24: A\'s log was created');
  const firstLine = fs.existsSync(aLog) ? fs.readFileSync(aLog, 'utf8').split('\n')[0] : '';
  assert(/^=== register \S+ pid \d+ root /.test(firstLine) && firstLine.endsWith(` root ${repoA} ===`),
    `W24: line 1 is a register header naming A (got: ${JSON.stringify(firstLine)})`);
  const t = Date.now() / 1000 - 7 * 3600;
  fs.utimesSync(aLog, t, t);
  runSweepHook(fx, repoD);
  assert(waitFor(() => launchCount(fx, repoA) === 1),
    `W24: the registered A is swept from D (got: ${JSON.stringify(launches(fx))})`);
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoD);
}

// ---------------------------------------------------------------------------
// (W25) every stale repo is claimed before the first sweep exits.
// ---------------------------------------------------------------------------
console.log('\n[W25] stale B and C, a 4 s sweep stub -> both claimed while the first sweep still runs');
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w25a-');
  const repoB = makeMainRepo('ae-wt-sweep-w25b-');
  const repoC = makeMainRepo('ae-wt-sweep-w25c-');
  const b = registerLog(fx, repoB, 7);
  const c = registerLog(fx, repoC, 7);
  runSweepHook(fx, repoA, { SWEEP_STUB_SLEEP: '4' });
  assert(waitFor(() => launches(fx).length >= 1), 'W25: the first sweep started');
  assert(launches(fx).length === 1, `W25: only one sweep has started so far (got: ${JSON.stringify(launches(fx))})`);
  assert(claimsFor(fx, b.stem).length === 1 && claimsFor(fx, c.stem).length === 1,
    'W25: B and C both claimed before the first sweep exits');
  assert(reapHeaders(b.log, repoB) === 2 && reapHeaders(c.log, repoC) === 2,
    'W25: B and C both got a reap header before the first sweep exits');
  assert(waitFor(() => launchCount(fx, repoB) === 1 && launchCount(fx, repoC) === 1, 15000),
    `W25: both swept in turn (got: ${JSON.stringify(launches(fx))})`);
  waitFor(() => fs.readFileSync(b.log, 'utf8').includes('STUB_SWEEP_RAN')
    && fs.readFileSync(c.log, 'utf8').includes('STUB_SWEEP_RAN'), 10000);
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoB); cleanup(repoC);
}

// ---------------------------------------------------------------------------
// (W26) the variable set: marker written, nothing launched.
// ---------------------------------------------------------------------------
console.log('\n[W26] AE_WORKTREE_REAP_DISABLE=1 in A -> A\'s marker written, stale B not swept');
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w26a-');
  const repoB = makeMainRepo('ae-wt-sweep-w26b-');
  registerLog(fx, repoB, 7);
  const aStem = reapStem(fx.fakeHome, repoA);
  runSweepHook(fx, repoA, { AE_WORKTREE_REAP_DISABLE: '1' });
  assert(waitFor(() => fs.existsSync(`${aStem}.reap-disabled`)), 'W26: A\'s opt-out marker written');
  pauseMs(1500);
  assert(launches(fx).length === 0, `W26: nothing launched (got: ${JSON.stringify(launches(fx))})`);
  assert(filesMatching(fx, /\.claim\./).length === 0, 'W26: nothing claimed');
  assert(!fs.existsSync(`${aStem}.log`), 'W26: A was not registered');
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoB);
}

// ---------------------------------------------------------------------------
// (W27) B's marker makes A skip B; B's next session without it clears it.
// ---------------------------------------------------------------------------
console.log('\n[W27] B opted out by marker -> A skips B; B\'s next plain session clears the marker -> A sweeps B');
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w27a-');
  const repoB = makeMainRepo('ae-wt-sweep-w27b-');
  const repoC = makeMainRepo('ae-wt-sweep-w27c-');
  const b = registerLog(fx, repoB, 7);
  registerLog(fx, repoC, 7);
  runSweepHook(fx, repoB, { AE_WORKTREE_REAP_DISABLE: '1' });
  assert(waitFor(() => fs.existsSync(`${b.stem}.reap-disabled`)),
    'W27: B\'s session with the variable set wrote B\'s marker');
  runSweepHook(fx, repoA);
  assert(waitFor(() => launchCount(fx, repoC) === 1), 'W27: control C swept');
  assert(launchCount(fx, repoB) === 0 && claimsFor(fx, b.stem).length === 0,
    `W27: B skipped while its marker exists (got: ${JSON.stringify(launches(fx))})`);
  runSweepHook(fx, repoB);
  assert(waitFor(() => !fs.existsSync(`${b.stem}.reap-disabled`)),
    'W27: B\'s next session without the variable cleared the marker');
  runSweepHook(fx, repoA);
  assert(waitFor(() => launchCount(fx, repoB) === 1),
    `W27: A sweeps B once the marker is gone (got: ${JSON.stringify(launches(fx))})`);
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoB); cleanup(repoC);
}

// ---------------------------------------------------------------------------
// (W28) B's project settings set the variable -> skipped.
// ---------------------------------------------------------------------------
console.log('\n[W28] AE_WORKTREE_REAP_DISABLE in B\'s settings.json or settings.local.json env -> B skipped');
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w28a-');
  const repoC = makeMainRepo('ae-wt-sweep-w28c-');
  const optedOut = ['settings.json', 'settings.local.json'].map((name) => {
    const root = makeMainRepo('ae-wt-sweep-w28b-');
    fs.mkdirSync(path.join(root, '.claude'));
    fs.writeFileSync(path.join(root, '.claude', name), JSON.stringify({ env: { AE_WORKTREE_REAP_DISABLE: '1' } }));
    return Object.assign({ name, root }, registerLog(fx, root, 7));
  });
  registerLog(fx, repoC, 7);
  runSweepHook(fx, repoA);
  assert(waitFor(() => launchCount(fx, repoC) === 1), 'W28: control C swept');
  for (const entry of optedOut) {
    assert(launchCount(fx, entry.root) === 0 && claimsFor(fx, entry.stem).length === 0,
      `W28: B with the variable in .claude/${entry.name} skipped (got: ${JSON.stringify(launches(fx))})`);
    cleanup(entry.root);
  }
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoC);
}

// ---------------------------------------------------------------------------
// (W29) the per-bucket claim: an existing claim blocks the sweep, and two
// concurrent hook runs sweep B exactly once.
// ---------------------------------------------------------------------------
console.log('\n[W29] existing claim for this 6 h bucket -> B skipped; two concurrent sessions -> B swept exactly once');
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w29a-');
  const repoB = makeMainRepo('ae-wt-sweep-w29b-');
  const repoC = makeMainRepo('ae-wt-sweep-w29c-');
  const b = registerLog(fx, repoB, 7);
  registerLog(fx, repoC, 7);
  // Both the current bucket and the next, so a bucket boundary mid-test
  // cannot let B through.
  const bucket = Math.floor(Date.now() / 1000 / 21600);
  fs.writeFileSync(`${b.stem}.claim.${bucket}`, '');
  fs.writeFileSync(`${b.stem}.claim.${bucket + 1}`, '');
  runSweepHook(fx, repoA);
  assert(waitFor(() => launchCount(fx, repoC) === 1), 'W29: control C swept');
  assert(launchCount(fx, repoB) === 0 && reapHeaders(b.log, repoB) === 1,
    `W29: B already claimed this bucket -> not swept (got: ${JSON.stringify(launches(fx))})`);
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoB); cleanup(repoC);
}
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w29a2-');
  const repoD = makeMainRepo('ae-wt-sweep-w29d2-');
  const repoB = makeMainRepo('ae-wt-sweep-w29b2-');
  const b = registerLog(fx, repoB, 7);
  const env = Object.assign({}, process.env, { HOME: fx.fakeHome, AGENTIC_WRAP_DAEMON: '1' });
  delete env.AE_WORKTREE_REAP_DISABLE;
  delete env.AGENTIC_QUIET;
  const res = spawnSync('bash', ['-c',
    'printf %s "$1" | bash "$3" >/dev/null & printf %s "$2" | bash "$3" >/dev/null & wait',
    'w29', JSON.stringify({ cwd: repoA }), JSON.stringify({ cwd: repoD }), SCRIPT],
  { encoding: 'utf8', timeout: 30000, env });
  assert(res.status === 0, 'W29: both concurrent hook runs returned');
  assert(waitFor(() => launchCount(fx, repoB) >= 1), 'W29: B swept by one of the concurrent sessions');
  pauseMs(2000);
  assert(launchCount(fx, repoB) === 1, `W29: B swept exactly once (got: ${JSON.stringify(launches(fx))})`);
  assert(reapHeaders(b.log, repoB) === 2 && claimsFor(fx, b.stem).length === 1,
    'W29: exactly one reap header appended and one claim file for B');
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoD); cleanup(repoB);
}

// ---------------------------------------------------------------------------
// (W30) unparsable settings in B -> skipped.
// ---------------------------------------------------------------------------
console.log('\n[W30] B\'s .claude/settings.json does not parse -> B skipped');
{
  const fx = sweepFixture();
  const repoA = makeMainRepo('ae-wt-sweep-w30a-');
  const repoB = makeMainRepo('ae-wt-sweep-w30b-');
  const repoC = makeMainRepo('ae-wt-sweep-w30c-');
  fs.mkdirSync(path.join(repoB, '.claude'));
  fs.writeFileSync(path.join(repoB, '.claude', 'settings.json'), '{not json');
  const b = registerLog(fx, repoB, 7);
  registerLog(fx, repoC, 7);
  runSweepHook(fx, repoA);
  assert(waitFor(() => launchCount(fx, repoC) === 1), 'W30: control C swept');
  assert(launchCount(fx, repoB) === 0 && claimsFor(fx, b.stem).length === 0,
    `W30: B with unparsable settings skipped (got: ${JSON.stringify(launches(fx))})`);
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(repoA); cleanup(repoB); cleanup(repoC);
}

// ---------------------------------------------------------------------------
// (W31) non-git cwd with the variable set: nothing launched, no marker.
// ---------------------------------------------------------------------------
console.log('\n[W31] non-git cwd with AE_WORKTREE_REAP_DISABLE=1 -> nothing launched, no marker');
{
  const fx = sweepFixture();
  const plainDir = makeTmp('ae-wt-sweep-w31-plain-');
  const repoB = makeMainRepo('ae-wt-sweep-w31b-');
  registerLog(fx, repoB, 7);
  const { code } = runSweepHook(fx, plainDir, { AE_WORKTREE_REAP_DISABLE: '1' });
  assert(code === 0, 'W31: hook exits 0');
  pauseMs(1500);
  assert(launches(fx).length === 0, `W31: nothing launched (got: ${JSON.stringify(launches(fx))})`);
  assert(filesMatching(fx, /\.reap-disabled$/).length === 0, 'W31: no marker written');
  cleanup(fx.fakeHome); cleanup(fx.mockRepoDir); cleanup(plainDir); cleanup(repoB);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed, ${skipped} skipped.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
