#!/usr/bin/env node
/**
 * Part-A parity guard: prevent silent divergence of the rolling-session-label
 * merge algorithm between content/commands/wrap.md and the shared normative
 * reference content/references/wrap-context-format.md.
 *
 * WHY THIS TEST EXISTS
 * --------------------
 * The deferred-wrap reconcile (U3) kept new-main's whole-flow `wrap.lock` while
 * grafting the daemon Step-0a / data-model / Part-A drain deltas. The repo's
 * pre-existing golden test (test-wrap-context-format-golden.js, U1) structurally
 * REQUIRES that the rolling-session-label merge algorithm live in exactly ONE
 * place - the reference - and that wrap.md CITE it rather than inline a second
 * copy. U3 therefore took the single-source-of-truth shape (Option B in the U3
 * brief): wrap.md Part A is a thin wrapper that defers the algorithm to the
 * reference. That eliminates the two-copy drift surface at the source.
 *
 * This guard pins the RELATIONSHIP that makes the single-source guarantee real,
 * so a future edit that re-inlines the algorithm into wrap.md (re-creating a
 * second, divergence-prone copy) fails here loudly:
 *
 *   (A) The reference OWNS the canonical algorithm block (the normative section
 *       header + the load-bearing rolling-window steps).
 *   (B) wrap.md CITES the reference for Part A and contains NO inline copy of the
 *       algorithm's distinctive steps. If those distinctive phrases ever reappear
 *       in wrap.md, two competing copies exist and this test fails.
 *   (C) wrap.md keeps new-main's WHOLE-FLOW lock and does NOT graft the
 *       lock-narrowing ("Part A is the ONLY part ... wrap.lock"). The lock model
 *       is part of the Part-A contract; a graft that silently narrows it would
 *       change behavior, so it is guarded here too.
 *
 * The golden test pins the reference's algorithm CONTENT against a fixture; this
 * test pins the wrap.md <-> reference STRUCTURE. Together they make divergence of
 * the duplicated algorithm impossible: there is only one copy (this test) and it
 * cannot drift undetected (the golden test).
 *
 * Run with: node hooks/tests/test-wrap-md-partA-parity.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const WRAP_MD = path.join(REPO_ROOT, 'content', 'commands', 'wrap.md');
const REFERENCE = path.join(REPO_ROOT, 'content', 'references', 'wrap-context-format.md');

// The normative section header that owns the merge algorithm in the reference.
const ALGO_SECTION_MARKER = '## context.md rolling-session-label merge algorithm (NORMATIVE)';

// Distinctive algorithm steps. These phrases are unique to the algorithm body and
// must live ONLY in the reference. Their presence in wrap.md means a second copy
// was re-inlined (the divergence surface this guard exists to prevent).
const ALGORITHM_ONLY_PHRASES = [
  'relabel `[Session B]` as `[Session A]`',
  'Five labels present',
  'Wrote fresh context to [path] (no existing file)',
  'Merged context written to [path] (combined sessions)',
  'combine both comma-separated lists, split by comma, trim whitespace',
];

// The lock-narrowing graft that U3 must NOT import (new-main's whole-flow lock is kept).
const LOCK_NARROWING_PHRASE = 'Part A is the ONLY part';

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

function readFile(p) {
  try { return fs.readFileSync(p, 'utf8'); } catch (_) { return null; }
}

// ---------------------------------------------------------------------------
// Pre-flight: required files exist
// ---------------------------------------------------------------------------
console.log('\n[pre] required files exist');
const wrapText = readFile(WRAP_MD);
const refText = readFile(REFERENCE);
assert(wrapText !== null, `wrap.md exists: ${path.relative(REPO_ROOT, WRAP_MD)}`);
assert(refText !== null, `reference exists: ${path.relative(REPO_ROOT, REFERENCE)}`);

if (wrapText === null || refText === null) {
  console.log(`\n${passed} passed, ${failed} failed.`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// (A) The reference OWNS the canonical algorithm block
// ---------------------------------------------------------------------------
console.log('\n[A] reference owns the canonical merge-algorithm block');
{
  assert(refText.includes(ALGO_SECTION_MARKER),
    `reference contains the normative section header ("${ALGO_SECTION_MARKER}")`);
  for (const phrase of ALGORITHM_ONLY_PHRASES) {
    assert(refText.includes(phrase),
      `reference owns the algorithm step: "${phrase.slice(0, 48)}..."`);
  }
}

// ---------------------------------------------------------------------------
// (B) wrap.md CITES the reference and inlines NO copy of the algorithm
// ---------------------------------------------------------------------------
console.log('\n[B] wrap.md Part A cites the reference and inlines no second copy');
{
  assert(wrapText.includes('content/references/wrap-context-format.md'),
    'wrap.md Part A cites content/references/wrap-context-format.md');

  assert(/rolling-session-label merge algorithm/.test(wrapText)
    && /NOT restated here|not restated here/.test(wrapText),
    'wrap.md Part A explicitly states the merge algorithm is NOT restated inline');

  // The single-source guarantee: NONE of the distinctive algorithm steps appear
  // in wrap.md. If one reappears, a divergence-prone second copy was re-inlined.
  for (const phrase of ALGORITHM_ONLY_PHRASES) {
    assert(!wrapText.includes(phrase),
      `wrap.md does NOT inline the algorithm step (single source): "${phrase.slice(0, 48)}..."`);
  }
}

// ---------------------------------------------------------------------------
// (C) wrap.md keeps the whole-flow lock and does NOT graft the lock-narrowing
// ---------------------------------------------------------------------------
console.log('\n[C] wrap.md keeps the whole-flow lock (no lock-narrowing graft)');
{
  assert(!wrapText.includes(LOCK_NARROWING_PHRASE),
    `wrap.md does NOT graft the lock-narrowing ("${LOCK_NARROWING_PHRASE} ... wrap.lock")`);

  // The whole-flow lock contract must still be present: pre-flight acquisition,
  // the mandatory-release block, and the Step 6 release line.
  assert(wrapText.includes('Pre-flight lock acquisition'),
    'wrap.md retains the Pre-flight lock acquisition block (whole-flow lock acquire)');
  assert(wrapText.includes('Lock release is mandatory on every exit path'),
    'wrap.md retains the mandatory lock-release block');
  assert(wrapText.includes('Release the pre-flight lock: `rm -rf <cwd>/.agentic/wrap.lock`'),
    'wrap.md retains the Step 6 pre-flight lock release line');
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
