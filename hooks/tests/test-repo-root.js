#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/repo-root.js (resolveAgenticCwdWithDiagnostics /
 * resolveAgenticCwd).
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

console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
