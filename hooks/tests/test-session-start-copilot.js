#!/usr/bin/env node
/**
 * Integration tests: .copilot/hooks/session-start-copilot.sh and its
 * hand-duplicated mirror .github/hooks/session-start-copilot.sh (DS-176,
 * adapter-hooks-agentic-root). Neither script had any test coverage before
 * this unit.
 *
 * Both scripts read the payload's `cwd` field from stdin and, pre-fix,
 * fell back to `pwd` when the payload carried none - the same
 * phantom-.agentic-tree bug class fixed for hooks/**\/bin/** in PR #745.
 * Post-fix, the workspace root is resolved via hooks/lib/repo-root.sh's
 * resolve_agentic_root (walks up to the nearest ACTUAL git repo via
 * `git rev-parse --show-toplevel` - unlike the JS/Py resolvers, a bare
 * `mkdir .git` does NOT satisfy this; fixtures below use `git init`), and
 * the `pwd` fallback is removed entirely: an unresolvable cwd now emits
 * `{}` rather than reading (or worse, phantom-creating) an unrelated
 * .agentic/context.md whichever directory the hook process happens to be
 * running in.
 *
 * Test cases (each run once per entry in HOOK_SCRIPTS):
 *   (a) payload cwd is a DRIFTED subdirectory of a real git repo whose
 *       ROOT holds a real context.md -> the injected additionalContext
 *       reflects the ROOT's context.md, not a (nonexistent) one at the
 *       drifted subdirectory.
 *   (b) payload cwd has no .git ancestor anywhere -> {} (no additionalContext),
 *       even when an unrelated context.md exists at the hook PROCESS's own
 *       cwd (proves there is no `pwd` fallback reading the wrong file).
 *   (c) payload carries no cwd field at all -> {} (guarded no-op), same
 *       proof as (b) for the empty-payload path.
 *   (d) payload cwd resolves to a real repo root with NO context.md yet ->
 *       {} (file legitimately absent, not a resolution failure).
 *
 * Round-2 rework (Major 2): (b) and (c) previously relied on runHook's
 * process cwd defaulting to `process.cwd()` - i.e. this test file's own
 * repo checkout - as the "unrelated context.md" that a restored `pwd`
 * fallback would leak. That is non-deterministic: `.agentic/` is
 * categorically gitignored, so a fresh clone, a worktree, or CI has no
 * `.agentic/context.md` there at all, and the mutation that removes the
 * `pwd`-fallback-removal fix silently passed (`18 passed, 0 failed`)
 * instead of reddening. Fixed: runHook now defaults its process cwd to
 * SENTINEL_CWD, a fixture directory seeded once at module load with a
 * `.agentic/context.md` containing a known sentinel string. If the `pwd`
 * fallback is ever restored, (b)/(c) deterministically observe that
 * sentinel leak into additionalContext, regardless of what the test
 * runner's own working directory happens to contain.
 *
 * Run with: node hooks/tests/test-session-start-copilot.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

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

const HOOK_SCRIPTS = [
  { label: '.copilot', path: path.resolve(__dirname, '..', '..', '.copilot', 'hooks', 'session-start-copilot.sh') },
  { label: '.github', path: path.resolve(__dirname, '..', '..', '.github', 'hooks', 'session-start-copilot.sh') },
];

for (const { label, path: hookScript } of HOOK_SCRIPTS) {
  if (!fs.existsSync(hookScript)) {
    console.error(`FAIL: ${label} hook not found at ${hookScript}`);
    process.exit(1);
  }
}

function makeTmp(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

/**
 * Creates a tmp dir and `git init`s it - the bash resolver shells out to
 * `git rev-parse --show-toplevel`, which (unlike the JS/Py existence-only
 * walk) requires an ACTUAL git repository, not merely a `.git` directory
 * entry. Verified empirically: a bare `mkdir .git` makes
 * `git rev-parse --show-toplevel` fail with "not a git repository".
 */
function makeGitFixture(prefix) {
  const dir = makeTmp(prefix);
  execFileSync('git', ['init', '-q'], { cwd: dir });
  return dir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

// Sentinel string a restored `pwd` fallback would leak into
// additionalContext - deterministic stand-in for "this test's own process
// cwd happens to have a .agentic/context.md", replacing that
// non-deterministic assumption (see Round-2 rework note above).
const SENTINEL_CONTEXT = 'LEAKED-PHANTOM-CONTEXT';
const SENTINEL_CWD = makeTmp('ae-session-start-copilot-sentinel-cwd-');
fs.mkdirSync(path.join(SENTINEL_CWD, '.agentic'), { recursive: true });
fs.writeFileSync(path.join(SENTINEL_CWD, '.agentic', 'context.md'), SENTINEL_CONTEXT, 'utf8');
process.once('exit', () => cleanup(SENTINEL_CWD));

/**
 * Run the hook with a JSON payload on stdin. execFileSync closes stdin
 * after writing `input`, so the hook's stdin-reading python3 subprocess
 * sees EOF and returns promptly - no stdin-guard machinery needed here
 * (these session-start hooks are synchronous, unlike the stop hooks).
 *
 * The hook PROCESS's own cwd (as opposed to the payload's `cwd` field)
 * defaults to SENTINEL_CWD, not process.cwd() - see Round-2 rework note
 * above.
 */
function runHook(hookScript, payload, opts) {
  const cwd = (opts && opts.cwd) || SENTINEL_CWD;
  try {
    const stdout = execFileSync('bash', [hookScript], {
      input: JSON.stringify(payload),
      cwd,
      timeout: 5000,
      encoding: 'utf8',
    });
    return { code: 0, stdout };
  } catch (err) {
    return { code: err.status, stdout: err.stdout ? err.stdout.toString() : '', stderr: err.stderr ? err.stderr.toString() : '' };
  }
}

// ---------------------------------------------------------------------------
// (a) drifted cwd -> additionalContext reflects the REPO ROOT's context.md
//
// Reddening mutation: reverting the resolve_agentic_root sourcing back to
// the pre-fix `CWD="$PAYLOAD_CWD"` / `[[ -z "$CWD" ]] && CWD="$(pwd)"`
// shape makes this test fail for the wrong reason it was written to catch
// - CONTEXT_FILE would point at the drifted subdirectory (which has no
// context.md) instead of the repo root, so additionalContext would never
// appear at all.
// ---------------------------------------------------------------------------

function testDriftedCwdReadsRootContext(hookScript, label) {
  const repoRoot = makeGitFixture('ae-session-start-copilot-a-');
  try {
    const driftedDir = path.join(repoRoot, 'sub', 'nested', 'drift');
    fs.mkdirSync(driftedDir, { recursive: true });
    fs.mkdirSync(path.join(repoRoot, '.agentic'), { recursive: true });
    fs.writeFileSync(path.join(repoRoot, '.agentic', 'context.md'), 'ROOT-CONTEXT-DS176', 'utf8');

    const result = runHook(hookScript, { cwd: driftedDir, session_id: 'drift-a' });

    assert(result.code === 0, `(a ${label}) hook exits 0`);
    let parsed = null;
    try { parsed = JSON.parse(result.stdout); } catch (_) { /* leave null */ }
    assert(parsed !== null, `(a ${label}) stdout parses as JSON (got: ${JSON.stringify(result.stdout)})`);
    const injected = parsed && parsed.hookSpecificOutput && parsed.hookSpecificOutput.additionalContext;
    assert(
      typeof injected === 'string' && injected.includes('ROOT-CONTEXT-DS176'),
      `(a ${label}) additionalContext reflects the REPO ROOT's context.md, not the drifted subdirectory (got: ${JSON.stringify(result.stdout)})`
    );
  } finally {
    cleanup(repoRoot);
  }
}

// ---------------------------------------------------------------------------
// (b) no .git ancestor -> {} even though an unrelated context.md exists at
// the hook's own process cwd. Proves there is no `pwd` fallback: if the
// pre-fix `CWD="$(pwd)"` fallback still fired, this test's own process cwd
// (the repo checkout, which of course has a .agentic/context.md-shaped
// dir) would leak into the output.
// ---------------------------------------------------------------------------

function testNoGitAncestorSkipsLookup(hookScript, label) {
  const noGitDir = makeTmp('ae-session-start-copilot-b-');
  try {
    const result = runHook(hookScript, { cwd: noGitDir, session_id: 'no-git-b' });

    assert(result.code === 0, `(b ${label}) hook exits 0`);
    assert(
      result.stdout.trim() === '{}',
      `(b ${label}) stdout is exactly {} - no .git ancestor, lookup skipped, no pwd fallback (got: ${JSON.stringify(result.stdout)})`
    );
  } finally {
    cleanup(noGitDir);
  }
}

// ---------------------------------------------------------------------------
// (c) no cwd field at all -> {} (guarded no-op)
// ---------------------------------------------------------------------------

function testMissingCwdField(hookScript, label) {
  const result = runHook(hookScript, { session_id: 'no-cwd-c' });

  assert(result.code === 0, `(c ${label}) hook exits 0`);
  assert(
    result.stdout.trim() === '{}',
    `(c ${label}) stdout is exactly {} when the payload has no cwd field (got: ${JSON.stringify(result.stdout)})`
  );
}

// ---------------------------------------------------------------------------
// (d) real repo root, no context.md yet -> {} (legitimately absent file,
// not a resolution failure)
// ---------------------------------------------------------------------------

function testResolvedRootNoContextFile(hookScript, label) {
  const repoRoot = makeGitFixture('ae-session-start-copilot-d-');
  try {
    const result = runHook(hookScript, { cwd: repoRoot, session_id: 'no-context-d' });

    assert(result.code === 0, `(d ${label}) hook exits 0`);
    assert(
      result.stdout.trim() === '{}',
      `(d ${label}) stdout is exactly {} when the resolved root has no context.md yet (got: ${JSON.stringify(result.stdout)})`
    );
  } finally {
    cleanup(repoRoot);
  }
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

function main() {
  for (const { label, path: hookScript } of HOOK_SCRIPTS) {
    console.log(`\n=== ${label} ===`);

    console.log('(a) drifted cwd -> additionalContext reflects the repo root');
    testDriftedCwdReadsRootContext(hookScript, label);

    console.log('(b) no .git ancestor -> {} (no pwd fallback)');
    testNoGitAncestorSkipsLookup(hookScript, label);

    console.log('(c) missing cwd field -> {} (guarded no-op)');
    testMissingCwdField(hookScript, label);

    console.log('(d) resolved root, no context.md yet -> {}');
    testResolvedRootNoContextFile(hookScript, label);
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
