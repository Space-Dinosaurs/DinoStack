#!/usr/bin/env node
/**
 * Phase 11b lock-release scoping guard: prevent the release sentence in
 * content/commands/ds-implement-ticket.md Phase 11b from silently reverting
 * to an UNSCOPED "releases the lock unconditionally on every exit path"
 * claim - whether via the exact original phrasing or a wording-variant
 * rewrite (e.g. "always release", "release ... regardless", "on all ...
 * paths", "in every case").
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
 * A first version of this pin (added alongside this comment block) only
 * inspected text INSIDE each "unconditionally on every ... ." span and never
 * asserted the scoped sentence was the ONLY release directive in Phase 11b -
 * an additive contradicting sentence appended after it (a two-location
 * disagreement, exactly the pre-#496 defect's shape) passed cleanly. This
 * version scans the whole Phase 11b section for release+universal-quantifier
 * co-occurrences instead of relying on a single fixed phrase or sentence
 * boundaries.
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

// ---------------------------------------------------------------------------
// (0) Locate the Phase 11b section programmatically: from its heading to the
// next "## " heading at the same level (or end of file). All Phase-11b-scoped
// assertions below operate on this extracted section, not the whole ~2900-
// line file - unrelated occurrences of the same words elsewhere in the file
// must not pollute these checks, and a hardcoded line range would silently
// drift as the file grows.
// ---------------------------------------------------------------------------
console.log('\n[0] locate Phase 11b section');
const headingRe = /^## Phase 11b:.*$/m;
const headingMatch = headingRe.exec(rawText);
assert(headingMatch !== null, 'Phase 11b heading located ("## Phase 11b:")');

let sectionRaw = '';
if (headingMatch) {
  const afterHeading = rawText.slice(headingMatch.index + headingMatch[0].length);
  const nextHeadingMatch = /^## /m.exec(afterHeading);
  const sectionEnd = nextHeadingMatch ? nextHeadingMatch.index : afterHeading.length;
  sectionRaw = headingMatch[0] + afterHeading.slice(0, sectionEnd);
}
assert(sectionRaw.length > 0, 'Phase 11b section body is non-empty');

const section = normalize(sectionRaw);

// ---------------------------------------------------------------------------
// (1) POSITIVE - the release sentence exists and is explicitly scoped to the
// "If the lock is acquired" branch, and explicitly excludes the non-acquiring
// paths from calling the release helper.
// ---------------------------------------------------------------------------
console.log('\n[1] release sentence is scoped to the acquired branch');
{
  assert(
    /Lock release:\s*this applies ONLY within the\s*"If the lock is acquired"\s*branch above/i.test(section),
    'release sentence explicitly limits itself to the "If the lock is acquired" branch'
  );

  assert(
    /never acquired the lock in this session and must NOT call the release helper/i.test(section),
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
    /Do NOT release the lock \(this session never acquired it\)/i.test(section),
    'lock-held-by-another-session path states "Do NOT release the lock (this session never acquired it)"'
  );
}

// ---------------------------------------------------------------------------
// (3) NEGATIVE - no UNSCOPED unconditional-release claim, and no
// wording-variant re-regression ("always release", "release ... regardless",
// "on all ... paths", "in every case", etc.) that reopens the same bug
// without ever matching the literal phrase "unconditionally on every".
//
// Detection strategy: scan the Phase 11b section for any co-occurrence of a
// release word ("release"/"releases"/"released"/"releasing") with a
// universal-quantifier word ("unconditionally"/"always"/"regardless"/"on
// all"/"in every case") AND a path/case/exit noun ("path(s)"/"case(s)"/"exit
// path(s)"). The sanctioned sentence deliberately quantifies over
// `wrap-ticket` OUTCOMEs within the acquired branch, not over exit paths or
// cases - so it does not trip this pattern. A match is excluded only when an
// explicit branch-scoping qualifier ("in that branch" / "within that
// branch") appears in the surrounding context, so a legitimate reword that
// still scopes correctly does not false-positive (see finding #2's over-
// tightening warning: the sanctioned sentence itself legitimately contains
// "unconditionally on every `wrap-ticket` outcome ... in that branch").
//
// This uses character-count windows (`[^]{0,N}`), NOT period-bounded spans -
// a period-bounded span (`[^.]*\.`) truncates early on an intra-sentence
// period such as "(success, timeout, etc.)" and produces false FAILs on
// correctly-scoped prose that merely reflows around a parenthetical (finding
// #2 in the review that added this section).
// ---------------------------------------------------------------------------
console.log('\n[3] no unscoped or wording-variant unconditional-release claim');
{
  const RELEASE = '(?:releas\\w*)';
  const QUANT = '(?:unconditionally|always|regardless(?:\\s+of)?|on\\s+all|in\\s+every\\s+case)';
  const NOUN = '(?:exit\\s+paths?|paths?|cases?)';
  const WINDOW = '[^]{0,150}?';
  const SCOPE_QUALIFIER = /\b(?:in|within)\s+that\s+branch\b/i;
  const CONTEXT_PAD = 80; // extra chars around each raw match checked for a nearby scope qualifier

  const forwardRe = new RegExp(`\\b${RELEASE}\\b${WINDOW}\\b${QUANT}\\b${WINDOW}\\b${NOUN}\\b`, 'gi');
  const backwardRe = new RegExp(`\\b${QUANT}\\b${WINDOW}\\b${NOUN}\\b${WINDOW}\\b${RELEASE}\\b`, 'gi');

  function findUnscoped(re) {
    const hits = [];
    let m;
    while ((m = re.exec(section)) !== null) {
      const start = Math.max(0, m.index - CONTEXT_PAD);
      const end = Math.min(section.length, m.index + m[0].length + CONTEXT_PAD);
      const context = section.slice(start, end);
      if (!SCOPE_QUALIFIER.test(context)) {
        hits.push(m[0]);
      }
      // Avoid re-matching from inside the same hit on the next iteration of a
      // global regex when zero-width progress could otherwise loop.
      if (re.lastIndex === m.index) re.lastIndex++;
    }
    return hits;
  }

  const unscopedHits = [...findUnscoped(forwardRe), ...findUnscoped(backwardRe)];

  assert(
    unscopedHits.length === 0,
    unscopedHits.length === 0
      ? 'no release directive in Phase 11b co-occurs with an unscoped universal quantifier over exit paths/cases'
      : `found ${unscopedHits.length} unscoped release directive(s) in Phase 11b (e.g. "${unscopedHits[0].slice(0, 160)}") - a release/lock directive must not claim universality over exit paths or cases without a nearby "in that branch"/"within that branch" qualifier`
  );
}

// ---------------------------------------------------------------------------
// (4) NEGATIVE - exactly one "Lock release:" directive in Phase 11b. A
// second, additive "Lock release:" paragraph (even one that avoids every
// keyword assertion (3) scans for) reopens the same class of bug: two
// directives that can silently disagree about scope, which was the exact
// shape of the pre-#496 defect (two locations, 25 lines apart, disagreeing).
// ---------------------------------------------------------------------------
console.log('\n[4] exactly one "Lock release:" directive in Phase 11b');
{
  const lockReleaseCount = (section.match(/Lock release:/gi) || []).length;
  assert(
    lockReleaseCount === 1,
    `expected exactly one "Lock release:" directive in Phase 11b, found ${lockReleaseCount} - a second "Lock release:" paragraph can silently disagree with the sanctioned one on scope`
  );
}

// ---------------------------------------------------------------------------
// (5) POSITIVE (sanity, section-scoped, synonym-tolerant) - the Phase 11b
// section still contains a release directive that is explicitly scoped to
// "that branch" (the acquired branch). This replaces a whole-file, literal-
// phrase-only sanity check ("unconditionally on every" surviving ANYWHERE in
// the ~2900-line file), which would fail on an equally-scoped reword such as
// "on all outcomes within that branch" (finding #2).
// ---------------------------------------------------------------------------
console.log('\n[5] a scoped release directive still exists in Phase 11b (synonym-tolerant)');
{
  const scopedReleasePresent =
    /releas\w*[^]{0,200}?\b(?:in|within)\s+that\s+branch\b/i.test(section) ||
    /\b(?:in|within)\s+that\s+branch\b[^]{0,200}?releas\w*/i.test(section);
  assert(
    scopedReleasePresent,
    'sanity: Phase 11b contains a release directive explicitly scoped to "that branch" (not merely the literal phrase "unconditionally on every")'
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
