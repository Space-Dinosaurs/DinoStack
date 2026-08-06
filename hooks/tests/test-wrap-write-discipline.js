#!/usr/bin/env node
/**
 * Regression test for DS-128 (atomic write discipline at /ds-wrap write sites).
 *
 * WHAT THIS PINS
 * ---------------
 * (1) All 17 /ds-wrap write-site citations of "Atomic write discipline" carry
 *     their own unique literal marker (`<!-- aw-site: <id> -->`), and each
 *     marker occurs EXACTLY ONCE across the two files that use it (14 in
 *     content/commands/ds-wrap.md, 3 in content/references/wrap-context-format.md).
 * (2) Two ownership corrections from DS-128 Units 1/1b stay corrected:
 *     - ds-wrap.md documents the wrap-ticket writer carve-out and no longer
 *       claims /ds-wrap itself owns root MEMORY.md / decisions.md / learnings.md
 *       content across a whole session.
 *     - content/rules/conventions.md's MEMORY.md routing bullet says /ds-wrap
 *       writes a "(stub seed only)", not an unqualified ongoing writer, and
 *       still cites the conventions-detail.md exception.
 *
 * WHY IDENTITY, NOT PROXIMITY
 * ---------------------------
 * Three earlier designs tried to verify "citation X is near marker Y" using a
 * window/anchor/offset/midpoint/indexOf-distance check, and each failed
 * differently against the real shapes in these files: a fixed +/-400-char
 * radius overlapped 12 of 17 sites; a midpoint partition was shorter than an
 * anchor's own clause and failed correct work; a forward-half partition broke
 * because 9 of 17 anchors are TRAILING `Result:`/`Return:` labels, so the
 * natural citation position falls inside the PREVIOUS site's window. Proximity
 * is not a reliable signal in this document shape. The mechanism DS-128 Unit 2
 * actually shipped is IDENTITY: every site emits its own unique literal
 * marker, and this test asserts on exact-substring OCCURRENCE COUNTS only -
 * never distance, never a window. Do not reintroduce a proximity check here;
 * it will silently mis-attribute citations exactly as its predecessors did.
 *
 * A prior revision of this test also under-specified the ownership NEGATIVE
 * assertions (missing backticks made one of them vacuously true). The
 * byte-exact strings below are copied from the live pre-fix commits, backticks
 * included, so the assertion cannot pass without actually checking the text.
 *
 * Run with: node hooks/tests/test-wrap-write-discipline.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const WRAP_MD = path.join(REPO_ROOT, 'content', 'commands', 'ds-wrap.md');
const REFERENCE = path.join(REPO_ROOT, 'content', 'references', 'wrap-context-format.md');
const CONVENTIONS_MD = path.join(REPO_ROOT, 'content', 'rules', 'conventions.md');

// The 14 marker ids that must occur exactly once each in ds-wrap.md.
const WRAP_MD_IDS = [
  'claude-md-root',
  'memory-md-seed',
  'claude-md-track',
  'stub-creation',
  'settings-json',
  'gitignore',
  'memory-pending',
  'memory-md-fresh',
  'memory-md-merge',
  'agents-md-pending',
  'agents-md-write',
  'original-md',
  'rolling-snapshot',
  'compressed-overwrite',
];

// The 3 marker ids that must occur exactly once each in wrap-context-format.md.
const REFERENCE_IDS = [
  'wrap-md-fresh',
  'wrap-md-nonauthored',
  'wrap-md-merge',
];

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

/** True occurrence count (not line count) of a literal substring. */
function occurrences(content, substring) {
  if (!content) return 0;
  return content.split(substring).length - 1;
}

function markerFor(id) {
  return `Atomic write discipline <!-- aw-site: ${id} -->`;
}

// ---------------------------------------------------------------------------
// Pre-flight: required files exist
// ---------------------------------------------------------------------------
console.log('\n[pre] required files exist');
const wrapText = readFile(WRAP_MD);
const refText = readFile(REFERENCE);
const conventionsText = readFile(CONVENTIONS_MD);
assert(wrapText !== null, `ds-wrap.md exists: ${path.relative(REPO_ROOT, WRAP_MD)}`);
assert(refText !== null, `wrap-context-format.md exists: ${path.relative(REPO_ROOT, REFERENCE)}`);
assert(conventionsText !== null, `conventions.md exists: ${path.relative(REPO_ROOT, CONVENTIONS_MD)}`);

if (wrapText === null || refText === null || conventionsText === null) {
  console.log(`\n${passed} passed, ${failed} failed.`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// (1) 17 marker-identity assertions: each id's marker occurs exactly once in
//     its owning file.
// ---------------------------------------------------------------------------
console.log('\n[1] each of the 14 ds-wrap.md aw-site markers occurs exactly once');
for (const id of WRAP_MD_IDS) {
  const marker = markerFor(id);
  const count = occurrences(wrapText, marker);
  assert(count === 1, `ds-wrap.md marker "${id}" occurs exactly once (found ${count})`);
}

console.log('\n[1] each of the 3 wrap-context-format.md aw-site markers occurs exactly once');
for (const id of REFERENCE_IDS) {
  const marker = markerFor(id);
  const count = occurrences(refText, marker);
  assert(count === 1, `wrap-context-format.md marker "${id}" occurs exactly once (found ${count})`);
}

// Sanity: the 17 ids are pairwise distinct (hand-verified, cheap to re-check).
console.log('\n[1] the 17 marker ids are pairwise distinct');
{
  const allIds = [...WRAP_MD_IDS, ...REFERENCE_IDS];
  const distinct = new Set(allIds);
  assert(distinct.size === allIds.length,
    `17 marker ids are pairwise distinct (${distinct.size} unique of ${allIds.length} total)`);
}

// ---------------------------------------------------------------------------
// (2) Ownership corrections stayed corrected
// ---------------------------------------------------------------------------
console.log('\n[2] ds-wrap.md documents the wrap-ticket writer carve-out (DS-128 Unit 1)');
{
  assert(wrapText.includes('wrap-ticket writer carve-out'),
    'ds-wrap.md references the "wrap-ticket writer carve-out"');

  const preFixWholeSession =
    'targets AGENTS.md, MEMORY.md, and `.agentic/_wrap.md` across an entire session';
  assert(!wrapText.includes(preFixWholeSession),
    'ds-wrap.md does NOT contain the pre-fix "targets AGENTS.md, MEMORY.md, and `.agentic/_wrap.md` across an entire session" claim');

  const preFixInlineWrites =
    'already writes root `MEMORY.md`, `decisions.md`, and `.agentic/learnings.md` inline';
  assert(!wrapText.includes(preFixInlineWrites),
    'ds-wrap.md does NOT contain the pre-fix "already writes root `MEMORY.md`, `decisions.md`, and `.agentic/learnings.md` inline" claim');
}

console.log('\n[2] conventions.md MEMORY.md routing bullet reflects stub-seed-only ownership (DS-128 Unit 1b)');
{
  const postFixBullet =
    'written by `/ds-wrap` (stub seed only), wrap-ticket, `/ds-memory-update`.';
  assert(conventionsText.includes(postFixBullet),
    'conventions.md contains the post-fix "written by `/ds-wrap` (stub seed only), wrap-ticket, `/ds-memory-update`." bullet');

  const preFixBullet =
    'written by `/ds-wrap`, wrap-ticket, `/ds-memory-update`.';
  assert(!conventionsText.includes(preFixBullet),
    'conventions.md does NOT contain the pre-fix "written by `/ds-wrap`, wrap-ticket, `/ds-memory-update`." bullet');

  assert(conventionsText.includes('(exception: see conventions-detail.md)'),
    'conventions.md still cites the "(exception: see conventions-detail.md)" cross-reference');
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
