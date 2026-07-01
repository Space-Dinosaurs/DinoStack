#!/usr/bin/env node
/**
 * Unit tests for the hooksTouched() pure predicate in scripts/update.js.
 *
 * Run: node scripts/test/update-hookstouched.test.js
 *
 * Decision table:
 *   (a) hooks/-prefixed path       -> true
 *   (b) non-hooks path             -> false
 *   (c) mixed paths                -> true
 *   (d) empty changedPaths         -> false (first-install proxy / no-op pull)
 *   (e) backslash-normalized path  -> true
 *   (f) leading-slash path         -> true
 *   (g) no-op changedPaths (single non-hooks file) -> false
 */

'use strict';

const path = require('path');
const { hooksTouched } = require(path.join(__dirname, '..', 'update.js'));

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) {
    console.log(`  PASS  ${msg}`);
    passed++;
  } else {
    console.error(`  FAIL  ${msg}`);
    failed++;
  }
}

// ---------------------------------------------------------------------------
// Case (a): hooks/-prefixed path -> true
// ---------------------------------------------------------------------------

console.log('\nCase (a): hooks/-prefixed path -> true');
assert(hooksTouched(['hooks/enforce-background-spawn.py']), 'hooks/enforce-*.py -> true');
assert(hooksTouched(['hooks/stop-context.js']),              'hooks/stop-context.js -> true');
assert(hooksTouched(['hooks/lib/wrap-marker.js']),           'hooks/lib/... -> true');

// ---------------------------------------------------------------------------
// Case (b): non-hooks path -> false
// ---------------------------------------------------------------------------

console.log('\nCase (b): non-hooks path -> false');
assert(!hooksTouched(['README.md']),                     'README.md -> false');
assert(!hooksTouched(['content/agents/engineer.md']),     'content/... -> false');
assert(!hooksTouched(['bin/agentic-update']),             'bin/... -> false');
assert(!hooksTouched(['scripts/hooks-something.js']),     'scripts/hooks-something.js (not under hooks/) -> false');

// ---------------------------------------------------------------------------
// Case (c): mixed paths -> true
// ---------------------------------------------------------------------------

console.log('\nCase (c): mixed paths -> true');
assert(hooksTouched(['README.md', 'hooks/x.sh']),                     'mixed: hooks/ among others -> true');
assert(hooksTouched(['content/agents/engineer.md', 'hooks/y.py', 'bin/z']), 'mixed: multiple non-hooks + one hooks -> true');

// ---------------------------------------------------------------------------
// Case (d): empty changedPaths -> false (first-install proxy)
// ---------------------------------------------------------------------------

console.log('\nCase (d): empty changedPaths -> false');
assert(!hooksTouched([]), 'empty array -> false');

// ---------------------------------------------------------------------------
// Case (e): backslash-normalized path -> true
// ---------------------------------------------------------------------------

console.log('\nCase (e): backslash-normalized path -> true');
assert(hooksTouched(['hooks\\foo.py']), 'backslash path hooks\\foo.py -> true');

// ---------------------------------------------------------------------------
// Case (f): leading-slash path -> true
// ---------------------------------------------------------------------------

console.log('\nCase (f): leading-slash path -> true');
assert(hooksTouched(['/hooks/foo.py']), 'leading-slash /hooks/foo.py -> true');

// ---------------------------------------------------------------------------
// Case (g): no-op changedPaths (single non-hooks file) -> false
// ---------------------------------------------------------------------------

console.log('\nCase (g): no-op changedPaths (single non-hooks file) -> false');
assert(!hooksTouched(['README.md']), 'single non-hooks file, no-op-equivalent -> false');

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

console.log(`\n${passed + failed} test(s): ${passed} passed, ${failed} failed.\n`);
if (failed > 0) process.exit(1);
