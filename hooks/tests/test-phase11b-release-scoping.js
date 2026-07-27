#!/usr/bin/env node
/**
 * Phase 11b lock-release scoping guard: prevent the release sentence in
 * content/commands/ds-implement-ticket.md Phase 11b from silently reverting
 * to an UNSCOPED "releases the lock unconditionally on every exit path"
 * claim.
 *
 * WHY THIS TEST EXISTS
 * --------------------
 * PR #496 fixed a live lock-deletion bug: pre-#496 prose said the conductor
 * releases the wrap lock "unconditionally on every exit path", while 25
 * lines earlier saying not to release a lock this session never acquired.
 * Post-#495 that became reachable: the interactive pre-flight publishes
 * `pid: null`, and `releaseWrapLock`'s tokenless refusal requires a LIVE
 * NON-NULL pid - so the release SUCCEEDS and deletes another live session's
 * lock. The fix (#496) is prose-only: the release sentence is now scoped to
 * the "If the lock is acquired" branch. There was no test pinning that
 * scoping, so a future edit could restore the unscoped phrasing and reopen
 * the bug with fully green CI. This test is that pin.
 *
 * IMPORTANT SCOPE NOTE: this is a grep-based prose pin. It verifies THAT THE
 * SCOPING SENTENCE EXISTS in the doc, not that any conductor session actually
 * honors it at runtime. It cannot catch a conductor that reads the correct
 * prose and still misapplies it - only that the doc itself has not regressed
 * to the unscoped claim.
 *
 * Run with: node hooks/tests/test-phase11b-release-scoping.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const TARGET = path.join(REPO_ROOT, 'content', 'commands', 'ds-implement-ticket.md');

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

// Normalize whitespace (collapse runs of whitespace, including newlines, to a
// single space) so unrelated line-wrap/reflow edits do not break these
// assertions. Assertions below match against this normalized text, not raw
// line-anchored text.
function normalize(text) {
  return text.replace(/\s+/g, ' ');
}

// ---------------------------------------------------------------------------
// Pre-flight: required file exists
// ---------------------------------------------------------------------------
console.log('\n[pre] required file exists');
const rawText = readFile(TARGET);
assert(rawText !== null, `target exists: ${path.relative(REPO_ROOT, TARGET)}`);

if (rawText === null) {
  console.log(`\n${passed} passed, ${failed} failed.`);
  process.exit(1);
}

const text = normalize(rawText);

// ---------------------------------------------------------------------------
// (1) POSITIVE - the release sentence exists and is explicitly scoped to the
// "If the lock is acquired" branch, and explicitly excludes the non-acquiring
// paths from calling the release helper.
// ---------------------------------------------------------------------------
console.log('\n[1] release sentence is scoped to the acquired branch');
{
  assert(
    /Lock release:\s*this applies ONLY within the\s*"If the lock is acquired"\s*branch above/i.test(text),
    'release sentence explicitly limits itself to the "If the lock is acquired" branch'
  );

  assert(
    /never acquired the lock in this session and must NOT call the release helper/i.test(text),
    'release sentence explicitly states non-acquiring paths must NOT call the release helper'
  );
}

// ---------------------------------------------------------------------------
// (2) POSITIVE - the lock-held-by-another-session path still carries its own
// no-release directive.
// ---------------------------------------------------------------------------
console.log('\n[2] lock-held-by-another-session path carries its own no-release directive');
{
  assert(
    /Do NOT release the lock \(this session never acquired it\)/i.test(text),
    'lock-held-by-another-session path states "Do NOT release the lock (this session never acquired it)"'
  );
}

// ---------------------------------------------------------------------------
// (3) NEGATIVE - no UNSCOPED unconditional-release claim. An occurrence of
// "unconditionally on every" is only legitimate when it is qualified by the
// acquired-branch scoping (i.e. it sits inside a sentence containing "in
// that branch" or is itself preceded by the ONLY-within-acquired-branch
// qualifier). The pre-#496 defect read "the conductor releases the wrap
// lock unconditionally on every exit path" with no such qualifier anywhere
// nearby - this assertion must fail on that phrasing and pass on the
// current, correctly-scoped phrasing.
// ---------------------------------------------------------------------------
console.log('\n[3] no unscoped unconditional-release claim');
{
  const unconditionalMatches = [...text.matchAll(/unconditionally on every[^.]*\./gi)];
  assert(
    unconditionalMatches.length > 0,
    'sanity: at least one "unconditionally on every ..." sentence is present (the legitimate scoped one)'
  );

  const unscoped = unconditionalMatches.filter((m) => {
    const sentence = m[0];
    // Legitimate current phrasing: "... unconditionally on every `wrap-ticket`
    // outcome in that branch ..." - qualified by "in that branch".
    return !/in that branch/i.test(sentence);
  });

  assert(
    unscoped.length === 0,
    'every "unconditionally on every ..." sentence is qualified by "in that branch" (no unscoped claim survives)'
  );
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
