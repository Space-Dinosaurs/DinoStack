#!/usr/bin/env node
'use strict';

/**
 * Behavioral test: .opencode/plugins/session-context.ts's resolveAgenticRoot
 * (DS-176, adapter-hooks-agentic-root) and its two call sites (session.idle,
 * command.executed), which anchor every `.agentic/` write at the nearest
 * `.git` ancestor of `directory || process.cwd()` instead of trusting that
 * value verbatim, and SKIP the write entirely (never fall back to the
 * unresolved start dir) when no `.git` ancestor is found.
 *
 * WHY THIS TEST EXTRACTS RATHER THAN SPAWNS. This is a standalone Bun
 * plugin (Bun.file, Bun.write, the `$` shell tag) loaded from
 * ~/.config/opencode/plugins/ - there is no OpenCode runtime in CI to
 * execute it against, and `bun` itself is not installed in this repo's CI
 * (see .github/workflows/hooks-tests.yml - no bun setup step), so a real
 * end-to-end spawn is not an option here, unlike the Cursor/Copilot JS
 * hooks. hooks/tests/test-opencode-rollup-parity.js established the
 * accepted precedent for this file: a STRUCTURAL regex-based check that
 * fails loudly on drift.
 *
 * This test goes one step further where it can: resolveAgenticRoot itself
 * uses ONLY Node built-ins (fs.existsSync, fs.realpathSync, path) - no
 * Bun-specific API - so its source is extracted verbatim from the .ts file,
 * has its known TS type annotations stripped (targeted string replacement,
 * not a general TS-to-JS transpile - adequate because this test controls
 * exactly which annotations it expects: the function signature's parameter
 * type + return type, and the one `let real: string;` local declaration -
 * and asserts all were found), and is `new Function`-evaluated in-process.
 * This gives REAL behavioral
 * coverage of the resolver logic itself (not just a regex match), while
 * the two call-site checks below (skip-on-no-git-ancestor wiring) remain
 * structural, same as the rest of this file's sibling parity test.
 *
 * If this extraction ever breaks (e.g. the function gains a third TS
 * annotation, or starts using a Bun-only API), the STRIP assertion below
 * fails loudly rather than silently testing nothing - see the
 * "extraction succeeded" assertion.
 *
 * Run with: node hooks/tests/test-opencode-agentic-root.js
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const REPO = path.resolve(__dirname, '..', '..');
const TS_PATH = path.join(REPO, '.opencode', 'plugins', 'session-context.ts');

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

const ts = fs.readFileSync(TS_PATH, 'utf8');

// ---------------------------------------------------------------------------
// Extract resolveAgenticRoot's source (balanced-brace scan from the
// function keyword) and strip its two TS type annotations.
// ---------------------------------------------------------------------------

// NOTE: `signature` must END in the function body's OPENING brace. A naive
// `src.indexOf('{', start)` search for that opening brace is unsafe here
// because resolveAgenticRoot's TS return-type annotation
// (`: { root: string; foundGitAncestor: boolean }`) contains its OWN
// balanced brace pair BEFORE the body even starts - the first `{` after
// `start` belongs to the return type, not the function body. Using the
// known signature's own length to locate the body-opening brace sidesteps
// that entirely.
function extractFunctionSource(src, signature) {
  const start = src.indexOf(signature);
  if (start === -1) return null;
  const braceOpen = start + signature.length - 1;
  if (src[braceOpen] !== '{') return null;
  let depth = 0;
  for (let i = braceOpen; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  return null;
}

const TS_SIGNATURE = 'function resolveAgenticRoot(startDir: string): { root: string; foundGitAncestor: boolean } {';
const JS_SIGNATURE = 'function resolveAgenticRoot(startDir) {';
const TS_LOCAL = 'let real: string;';
const JS_LOCAL = 'let real;';

let fnSource = extractFunctionSource(ts, TS_SIGNATURE);
let stripped = false;
if (fnSource && fnSource.startsWith(TS_SIGNATURE) && fnSource.includes(TS_LOCAL)) {
  fnSource = JS_SIGNATURE + fnSource.slice(TS_SIGNATURE.length);
  fnSource = fnSource.replace(TS_LOCAL, JS_LOCAL);
  stripped = true;
}

assert(
  !!fnSource && stripped,
  'extraction succeeded: resolveAgenticRoot found in session-context.ts with its expected TS signature and local, both stripped cleanly'
);

const maxDepthMatch = ts.match(/const AGENTIC_ROOT_MAX_DEPTH = (\d+);/);
assert(!!maxDepthMatch, 'AGENTIC_ROOT_MAX_DEPTH constant found');
assert(
  !!maxDepthMatch && maxDepthMatch[1] === '64',
  `AGENTIC_ROOT_MAX_DEPTH is 64, matching hooks/lib/repo-root.js's MAX_DEPTH (got: ${maxDepthMatch && maxDepthMatch[1]})`
);

// ---------------------------------------------------------------------------
// Behavioral: evaluate the extracted function against real fixture trees.
// ---------------------------------------------------------------------------

if (fnSource && stripped && maxDepthMatch) {
  // eslint-disable-next-line no-new-func
  const resolveAgenticRoot = new Function(
    'existsSync', 'realpathSync', 'path', 'AGENTIC_ROOT_MAX_DEPTH',
    `${fnSource}\nreturn resolveAgenticRoot;`
  )(fs.existsSync, fs.realpathSync, path, Number(maxDepthMatch[1]));

  function makeTmp(prefix) {
    return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  }
  function cleanup(dir) {
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
  }

  // (a) start dir IS the repo root -> foundGitAncestor true, root unchanged.
  {
    const repoRoot = makeTmp('ae-opencode-agentic-root-a-');
    fs.mkdirSync(path.join(repoRoot, '.git'));
    try {
      const { root, foundGitAncestor } = resolveAgenticRoot(repoRoot);
      assert(foundGitAncestor === true, '(a) foundGitAncestor is true when start dir has a .git entry');
      assert(root === fs.realpathSync(repoRoot), '(a) root is the realpath of the start dir itself');
    } finally {
      cleanup(repoRoot);
    }
  }

  // (b) drifted subdirectory -> walks up to the repo root, not the drifted dir.
  {
    const repoRoot = makeTmp('ae-opencode-agentic-root-b-');
    fs.mkdirSync(path.join(repoRoot, '.git'));
    const driftedDir = path.join(repoRoot, 'sub', 'nested', 'drift');
    fs.mkdirSync(driftedDir, { recursive: true });
    try {
      const { root, foundGitAncestor } = resolveAgenticRoot(driftedDir);
      assert(foundGitAncestor === true, '(b) foundGitAncestor is true for a drifted subdirectory of a real repo');
      assert(
        root === fs.realpathSync(repoRoot),
        `(b) root walks up to the REPO ROOT, not the drifted subdirectory (got: ${root})`
      );
    } finally {
      cleanup(repoRoot);
    }
  }

  // (c) no .git ancestor anywhere -> foundGitAncestor false.
  {
    const noGitDir = makeTmp('ae-opencode-agentic-root-c-');
    try {
      const { foundGitAncestor } = resolveAgenticRoot(noGitDir);
      assert(foundGitAncestor === false, '(c) foundGitAncestor is false when no .git ancestor exists');
    } finally {
      cleanup(noGitDir);
    }
  }

  // (d) linked-worktree .git is a FILE, not a directory - existence-only
  // check must still find it (a .isDirectory() test would fail here).
  {
    const repoRoot = makeTmp('ae-opencode-agentic-root-d-');
    fs.writeFileSync(path.join(repoRoot, '.git'), 'gitdir: ../.git/worktrees/x\n', 'utf8');
    try {
      const { foundGitAncestor } = resolveAgenticRoot(repoRoot);
      assert(
        foundGitAncestor === true,
        '(d) a FILE .git entry (linked worktree) is recognized - existence-only, not isDirectory()'
      );
    } finally {
      cleanup(repoRoot);
    }
  }
} else {
  console.error('  SKIP: behavioral cases skipped - extraction failed (see the "extraction succeeded" assertion above)');
}

// ---------------------------------------------------------------------------
// Structural: both event-handler call sites must check foundGitAncestor and
// SKIP (return early) rather than falling back to the unresolved start dir.
//
// Reddening mutation: reverting either `const { root: cwd, foundGitAncestor }
// = resolveAgenticRoot(startDir); if (!foundGitAncestor) { ...; return; }`
// block back to the pre-fix `const cwd = directory || process.cwd();` makes
// these assertions fail - the call site would no longer anchor the write or
// skip on resolution failure.
// ---------------------------------------------------------------------------

console.log('\n--- call-site wiring ---');
{
  assert(
    !/const cwd = directory \|\| process\.cwd\(\);/.test(ts),
    'the pre-fix unresolved `directory || process.cwd()` assignment to cwd is gone'
  );

  const idleSite = ts.match(/if \(type === "session\.idle"\) \{[\s\S]{0,600}?resolveAgenticRoot\(startDir\)[\s\S]{0,300}?if \(!foundGitAncestor\) \{[\s\S]{0,200}?return;/);
  assert(!!idleSite, 'session.idle handler resolves via resolveAgenticRoot and skips (return) when foundGitAncestor is false');

  const wrapSite = ts.match(/if \(type === "command\.executed"\) \{[\s\S]{0,1200}?resolveAgenticRoot\(startDir\)[\s\S]{0,300}?if \(!foundGitAncestor\) \{[\s\S]{0,200}?return;/);
  assert(!!wrapSite, 'command.executed (/ds-wrap) handler resolves via resolveAgenticRoot and skips (return) when foundGitAncestor is false');
}

console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
