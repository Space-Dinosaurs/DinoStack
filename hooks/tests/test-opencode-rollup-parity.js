#!/usr/bin/env node
'use strict';

/**
 * Parity gate between hooks/lib/context-rollup.js (the Node source of truth) and
 * .opencode/plugins/session-context.ts (its hand-authored port).
 *
 * WHY THIS EXISTS. The plugin cannot `require` the lib: it is a standalone Bun
 * plugin loaded from ~/.config/opencode/plugins/ where the repo's hooks/ tree is
 * unreachable, so the shard/rollup logic is duplicated by necessity. Nothing
 * mechanical guarded that duplication - `check-adapter-sync` compares GENERATED
 * content and cannot see this file at all, because it is hand-authored and no
 * build script emits it.
 *
 * The failure that motivated it: the first version of the port omitted
 * `stripDerivedBlocks` entirely and seeded `_wrap.md` with the migration prefix
 * VERBATIM. Pre-sentinel capture-gap and identity-nudge notices then persisted
 * permanently into the curated file - "immortal derived cruft, unclearable
 * because `_wrap.md` is only merge-written by Part A". Reachable in any mixed
 * Claude+OpenCode repo, and a pre-sentinel CAPTURE-GAP block is exactly the
 * shape the live incident's wedged `context.md` had.
 *
 * SCOPE, stated honestly. This is a STRUCTURAL gate, not a behavioural one: it
 * asserts the port carries the same load-bearing constants and has not dropped a
 * required procedure or safety return. It cannot execute the plugin's
 * closure-scoped functions (that needs an OpenCode runtime), so it does NOT
 * prove behavioural equivalence. It is the cheapest check that would have caught
 * the actual regression, and it fails loudly when either side gains a constant
 * the other lacks.
 *
 * Run with: node hooks/tests/test-opencode-rollup-parity.js
 * Argument-free invocation runs everything (auto-discovered by the
 * hooks/tests/test-*.js glob in .github/workflows/hooks-tests.yml).
 */

const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..', '..');
const JS_PATH = path.join(REPO, 'hooks', 'lib', 'context-rollup.js');
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

const js = fs.readFileSync(JS_PATH, 'utf8');
const ts = fs.readFileSync(TS_PATH, 'utf8');

/** Extract the string literals of a `const NAME = [...]` array declaration. */
function arrayLiterals(src, name) {
  const m = src.match(new RegExp('const ' + name + '\\s*(?::[^=]*)?=\\s*\\[([\\s\\S]*?)\\];'));
  if (!m) return null;
  return (m[1].match(/(['"])(?:\\.|(?!\1).)*\1/g) || [])
    .map((s) => s.slice(1, -1))
    .sort();
}

// ---------------------------------------------------------------------------
// Load-bearing constants must be byte-identical
// ---------------------------------------------------------------------------
console.log('\n--- constants ---');
{
  const jsSentinel = js.match(/const ACTIVITY_SENTINEL = '([^']*)'/);
  const tsSentinel = ts.match(/const ACTIVITY_SENTINEL = '([^']*)'/);
  assert(!!jsSentinel && !!tsSentinel && jsSentinel[1] === tsSentinel[1],
    'ACTIVITY_SENTINEL is byte-identical in both files');

  const jsMarker = js.match(/const DERIVED_MARKER = '([^']*)'/);
  const tsMarker = ts.match(/const DERIVED_MARKER = '([^']*)'/);
  assert(!!jsMarker && !!tsMarker && jsMarker[1] === tsMarker[1],
    'DERIVED_MARKER is byte-identical in both files (placement AND value are load-bearing)');

  const jsRetention = js.match(/const SHARD_RETENTION = (\d+)/);
  const tsRetention = ts.match(/const SHARD_RETENTION = (\d+)/);
  assert(!!jsRetention && !!tsRetention && jsRetention[1] === tsRetention[1],
    'SHARD_RETENTION matches (a divergence changes WHICH shard is dropped)');
}
{
  for (const name of ['ACTIVITY_REGION_SIGNATURES', 'DERIVED_NOTICE_SIGNATURES']) {
    const a = arrayLiterals(js, name);
    const b = arrayLiterals(ts, name);
    assert(a !== null, `${name} is declared in context-rollup.js`);
    assert(b !== null, `${name} is declared in session-context.ts`);
    if (a && b) {
      const missingInTs = a.filter((x) => !b.includes(x));
      const missingInJs = b.filter((x) => !a.includes(x));
      assert(missingInTs.length === 0,
        `${name}: no entry missing from the TS port (missing: ${JSON.stringify(missingInTs)})`);
      assert(missingInJs.length === 0,
        `${name}: no entry missing from the JS lib (missing: ${JSON.stringify(missingInJs)})`);
    }
  }
}

// ---------------------------------------------------------------------------
// Required procedures must be PRESENT and CALLED in the port
// ---------------------------------------------------------------------------
console.log('\n--- required procedures ---');
{
  // Declared AND invoked - a dead helper would satisfy a presence-only check.
  const required = [
    ['stripDerivedBlocks', /function stripDerivedBlocks\(/, /stripDerivedBlocks\(prefix\)/],
    ['findActivityRegionIndex', /function findActivityRegionIndex\(/, /findActivityRegionIndex\(/],
  ];
  for (const [name, declRe, callRe] of required) {
    assert(declRe.test(ts), `${name} is declared in the TS port`);
    assert(callRe.test(ts), `${name} is actually CALLED in the TS port (not dead code)`);
  }
  assert(/stripDerivedBlocks\(prefix\)/.test(js),
    'the JS lib seeds via stripDerivedBlocks too (both sides strip, or neither claim does)');
}

// ---------------------------------------------------------------------------
// The migration seed must NOT be verbatim in either implementation
// ---------------------------------------------------------------------------
console.log('\n--- migration seed is stripped, never verbatim ---');
{
  assert(!/Bun\.write\(curatedPath, prefix/.test(ts),
    'the TS port does NOT seed _wrap.md with a VERBATIM prefix (that made derived cruft immortal)');
  assert(!/atomicWrite\(cp, prefix/.test(js),
    'the JS lib does NOT seed _wrap.md with a VERBATIM prefix');
}

// ---------------------------------------------------------------------------
// ABORT-BEFORE-OVERWRITE must exist on both sides
// ---------------------------------------------------------------------------
console.log('\n--- abort-before-overwrite ---');
{
  // TS: both the seed catch and the preservation catch must RETURN, not fall
  // through to the wholesale rollup overwrite.
  const seedCatch = ts.match(/Migration seed failed[\s\S]{0,400}?\n\s*return;/);
  assert(!!seedCatch,
    'TS: a failed migration seed RETURNS instead of falling through to the overwrite');
  const fpCatch = ts.match(/Foreign preservation failed[\s\S]{0,400}?\n\s*return;/);
  assert(!!fpCatch,
    'TS: a failed foreign preservation RETURNS instead of falling through to the overwrite');
  assert(!/catch \(_\) \{ \/\* best-effort \*\/ \}[\s\S]{0,120}regenerateRollup\(cwd\); \/\/ recompose/.test(ts),
    'TS: the seed failure path no longer swallows-and-recurses (that spun forever)');

  assert(/if \(migration\.failed\) return result;/.test(js),
    'JS: a failed migration aborts regenerateRollup before the overwrite');
  assert(/if \(!preserveForeign\(cwd, foreign\)\) return result;/.test(js),
    'JS: a failed foreign preservation aborts regenerateRollup before the overwrite');
}

// ---------------------------------------------------------------------------
// The retired strip-and-append must not come back on either side
// ---------------------------------------------------------------------------
console.log('\n--- retired semantics stay retired ---');
{
  assert(!/indexOf\(ACTIVITY_SENTINEL\)/.test(ts),
    'TS: no single-sentinel indexOf slice (the strip-and-append that destroyed N-1 sessions)');
  assert(/lastIndexOf\(ACTIVITY_SENTINEL\)/.test(ts),
    'TS: the region boundary is found from the LAST sentinel, matching the JS lib');
  assert(/lastIndexOf\(ACTIVITY_SENTINEL\)/.test(js),
    'JS: the region boundary is found from the LAST sentinel');
}

console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
