#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/repo-root.js (resolveAgenticCwdWithDiagnostics /
 * resolveAgenticCwd, and DS-246 resolveMainRepoRoot with a parity check
 * against hooks/lib/git_worktree.py resolve_worktree_primary_root).
 *
 * Consumes the SHARED cross-language fixture
 * hooks/tests/fixtures/repo-root-cases.json - the SAME cases drive
 * hooks/tests/test-repo-root.py, so a JS/Python resolver divergence
 * surfaces as one suite going red against a fixture neither owns.
 *
 * Each case builds a temp directory layout, optionally places a `.git`
 * entry (file or dir), optionally chmods it, optionally symlinks the start
 * path, then asserts resolveAgenticCwdWithDiagnostics(start) against the
 * case's expected {root, drift_levels, found_git_ancestor} (root/start
 * paths in the fixture are relative to the temp root; "" means the temp
 * root itself).
 *
 * Run with: node hooks/tests/test-repo-root.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const repoRoot = require(path.resolve(__dirname, '..', 'lib', 'repo-root.js'));
const FIXTURES = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, 'fixtures', 'repo-root-cases.json'), 'utf8')
);

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

function buildLayout(tmpDir, layout) {
  const dirs = (layout && layout.dirs) || [''];
  for (const d of dirs) {
    fs.mkdirSync(path.join(tmpDir, d), { recursive: true });
  }
  if (layout && layout.git_at !== undefined) {
    const gitPath = path.join(tmpDir, layout.git_at, '.git');
    if (layout.git_kind === 'file') {
      fs.writeFileSync(gitPath, 'gitdir: ../.git/worktrees/x\n');
    } else {
      fs.mkdirSync(gitPath, { recursive: true });
    }
    if (layout.chmod_git) {
      try {
        fs.chmodSync(gitPath, parseInt(layout.chmod_git, 8));
      } catch (_) { /* best-effort; some platforms restrict this to root */ }
    }
  }
  if (layout && layout.symlink) {
    const from = path.join(tmpDir, layout.symlink.from);
    const to = path.join(tmpDir, layout.symlink.to);
    try {
      fs.symlinkSync(to, from, 'dir');
    } catch (e) {
      // Symlink creation can fail without privilege on some CI runners
      // (notably Windows); the case is skipped rather than failed.
      return false;
    }
  }
  return true;
}

function cleanup(tmpDir) {
  try {
    fs.chmodSync(tmpDir, 0o755);
  } catch (_) { /* ignore */ }
  // Restore any chmod-000 .git so recursive removal can traverse it.
  const walk = (dir) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (_) {
      return;
    }
    for (const e of entries) {
      const p = path.join(dir, e.name);
      try {
        fs.chmodSync(p, 0o755);
      } catch (_) { /* ignore */ }
      if (e.isDirectory()) walk(p);
    }
  };
  walk(tmpDir);
  fs.rmSync(tmpDir, { recursive: true, force: true });
}

function runCase(tc) {
  const tmpDir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'repo-root-js-')));
  try {
    const built = buildLayout(tmpDir, tc.layout);
    if (!built) {
      console.log(`  SKIP: ${tc.id} (platform cannot create symlinks)`);
      return;
    }
    const start = path.join(tmpDir, tc.start || '');
    const result = repoRoot.resolveAgenticCwdWithDiagnostics(start);

    const expectedRoot = path.join(tmpDir, tc.expect.root || '');
    assert(
      fs.realpathSync(result.root) === fs.realpathSync(expectedRoot),
      `${tc.id}: root resolves to expected path`
    );
    assert(
      result.driftLevels === tc.expect.drift_levels,
      `${tc.id}: driftLevels === ${tc.expect.drift_levels} (got ${result.driftLevels})`
    );
    assert(
      result.foundGitAncestor === tc.expect.found_git_ancestor,
      `${tc.id}: foundGitAncestor === ${tc.expect.found_git_ancestor} (got ${result.foundGitAncestor})`
    );

    // Convenience wrapper must agree with the diagnostics form's .root.
    const wrapperRoot = repoRoot.resolveAgenticCwd(start);
    assert(
      wrapperRoot === result.root,
      `${tc.id}: resolveAgenticCwd() agrees with resolveAgenticCwdWithDiagnostics().root`
    );
  } finally {
    cleanup(tmpDir);
  }
}

console.log('hooks/lib/repo-root.js tests\n');
for (const tc of FIXTURES.cases) {
  runCase(tc);
}

// ---------------------------------------------------------------------------
// Never-throws smoke checks not expressible via the shared fixture shape.
// ---------------------------------------------------------------------------
assert(
  (() => {
    try {
      repoRoot.resolveAgenticCwd('/definitely/does/not/exist/anywhere');
      return true;
    } catch (_) {
      return false;
    }
  })(),
  'resolveAgenticCwd never throws on a wholly nonexistent path'
);

// ---------------------------------------------------------------------------
// DS-246: resolveMainRepoRoot (JS mirror of git_worktree.py
// resolve_worktree_primary_root), plus a parity check against the Python
// helper for every case whose shape it recognizes.
// ---------------------------------------------------------------------------
const { spawnSync } = require('child_process');

function git(cwd, args) {
  return spawnSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.com', ...args],
    { cwd, encoding: 'utf8' });
}

const pythonOk = spawnSync('python3', ['-c', 'import sys'], { encoding: 'utf8' }).status === 0;
const gitWorktreePy = path.resolve(__dirname, '..', 'lib', 'git_worktree.py');

function pythonPrimary(callerRoot) {
  const code = [
    'import importlib.util, sys',
    `spec = importlib.util.spec_from_file_location("gw", ${JSON.stringify(gitWorktreePy)})`,
    'm = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)',
    'print(m.resolve_worktree_primary_root(sys.argv[1]) or "")',
  ].join('\n');
  const r = spawnSync('python3', ['-c', code, callerRoot], { encoding: 'utf8' });
  return (r.stdout || '').trim() || null;
}

function mainRootCase(id, build, expectMode, expectRootRel, parity = true) {
  const tmp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'repo-main-js-')));
  try {
    const start = build(tmp);
    const got = repoRoot.resolveMainRepoRoot(start);
    assert(got.mode === expectMode, `${id}: mode === ${expectMode} (got ${got.mode})`);
    const expectRoot = path.join(tmp, expectRootRel);
    assert(fs.realpathSync(got.root) === fs.realpathSync(expectRoot),
      `${id}: root === <tmp>/${expectRootRel} (got ${got.root})`);
    if (pythonOk && parity) {
      const callerRoot = repoRoot.resolveAgenticCwd(start);
      const py = pythonPrimary(callerRoot);
      const jsLinked = got.mode === 'linked' ? fs.realpathSync(got.root) : null;
      assert((py ? fs.realpathSync(py) : null) === jsLinked,
        `${id}: parity with git_worktree.resolve_worktree_primary_root (py ${py}, js ${jsLinked})`);
    } else {
      console.log(`  SKIP: ${id} parity (${parity ? 'python3 unavailable' : 'commondir-only shape'})`);
    }
  } finally {
    cleanup(tmp);
  }
}

console.log('\nresolveMainRepoRoot tests\n');

mainRootCase('main-checkout', (tmp) => {
  git(tmp, ['init', '-q']);
  fs.mkdirSync(path.join(tmp, 'sub', 'dir'), { recursive: true });
  return path.join(tmp, 'sub', 'dir');
}, 'main', '');

mainRootCase('real-linked-worktree', (tmp) => {
  const main = path.join(tmp, 'main');
  fs.mkdirSync(main);
  git(main, ['init', '-q']);
  git(main, ['commit', '-q', '--allow-empty', '-m', 'init']);
  git(main, ['worktree', 'add', '-q', path.join(tmp, 'wt'), '-b', 'wt']);
  fs.mkdirSync(path.join(tmp, 'wt', 'deep'), { recursive: true });
  return path.join(tmp, 'wt', 'deep');
}, 'linked', 'main');

mainRootCase('relative-gitdir-no-commondir', (tmp) => {
  fs.mkdirSync(path.join(tmp, 'main', '.git', 'worktrees', 'w'), { recursive: true });
  fs.mkdirSync(path.join(tmp, 'wt'));
  fs.writeFileSync(path.join(tmp, 'wt', '.git'), 'gitdir: ../main/.git/worktrees/w\n');
  return path.join(tmp, 'wt');
}, 'linked', 'main');

mainRootCase('commondir-relative-dotdot', (tmp) => {
  // Admin dir outside any `/.git/worktrees/` path, so only commondir can
  // resolve it (the Python helper, which ignores commondir, returns None).
  fs.mkdirSync(path.join(tmp, 'main', '.git'), { recursive: true });
  fs.mkdirSync(path.join(tmp, 'admin', 'w'), { recursive: true });
  fs.writeFileSync(path.join(tmp, 'admin', 'w', 'commondir'), '../../main/.git\n');
  fs.mkdirSync(path.join(tmp, 'wt'));
  fs.writeFileSync(path.join(tmp, 'wt', '.git'), `gitdir: ${path.join(tmp, 'admin', 'w')}\n`);
  return path.join(tmp, 'wt');
}, 'linked', 'main', false);

mainRootCase('submodule-is-fallback', (tmp) => {
  fs.mkdirSync(path.join(tmp, 'super', '.git', 'modules', 'sub'), { recursive: true });
  fs.mkdirSync(path.join(tmp, 'super', 'sub'));
  fs.writeFileSync(path.join(tmp, 'super', 'sub', '.git'), 'gitdir: ../.git/modules/sub\n');
  return path.join(tmp, 'super', 'sub');
}, 'fallback', 'super/sub');

mainRootCase('non-git-is-fallback', (tmp) => {
  fs.mkdirSync(path.join(tmp, 'plain'));
  return path.join(tmp, 'plain');
}, 'fallback', 'plain');

mainRootCase('candidate-without-git-dir-is-fallback', (tmp) => {
  fs.mkdirSync(path.join(tmp, 'gone', 'x', '.git', 'worktrees', 'w'), { recursive: true });
  fs.mkdirSync(path.join(tmp, 'wt'));
  // Pointer names a primary whose own `.git` is NOT a directory.
  fs.writeFileSync(path.join(tmp, 'wt', '.git'), `gitdir: ${path.join(tmp, 'ghost', '.git', 'worktrees', 'w')}\n`);
  return path.join(tmp, 'wt');
}, 'fallback', 'wt');

assert(
  (() => {
    try {
      return repoRoot.resolveMainRepoRoot('/definitely/does/not/exist/anywhere').mode === 'fallback';
    } catch (_) {
      return false;
    }
  })(),
  'resolveMainRepoRoot never throws and falls back on a wholly nonexistent path'
);

console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
