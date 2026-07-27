#!/usr/bin/env node
/**
 * Phase 11b lock-release scoping guard: prevent the release sentence in
 * content/commands/ds-implement-ticket.md Phase 11b from silently reverting
 * to an UNSCOPED "releases the lock unconditionally on every exit path"
 * claim - whether via the exact original phrasing or a wording-variant
 * rewrite (e.g. "always release", "release ... regardless", "on all ...
 * paths", "in every case", "whether or not it was acquired").
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
 * MECHANISM HISTORY (why this is a golden-text pin, not a pattern-match pin)
 * ---------------------------------------------------------------------
 * v1 (regex-only, added alongside #496): scanned for the literal phrase
 * "unconditionally on every ... ." and never asserted the scoped sentence
 * was the ONLY release directive in Phase 11b - an additive contradicting
 * sentence appended after it passed cleanly.
 *
 * v2 (whole-section regex, round 1): scanned the whole Phase 11b section for
 * release+universal-quantifier co-occurrence with a raw character-count
 * proximity window (`CONTEXT_PAD = 80`) to decide whether a nearby "in that
 * branch" qualifier excused the match. Round 2 adversarial review defeated
 * this twice:
 *   (a) Proximity blind zone - the sanctioned sentence's own qualifier sits
 *       ~103 chars from the release/quantifier tokens, so anything inserted
 *       within that ±80-char radius (e.g. right after "outcome in that
 *       branch") was silently excused as "close enough to the qualifier"
 *       even though it was a NEW, unscoped claim.
 *   (b) Synonym gap - the QUANT token list omitted "every"/"any"/bare
 *       "all"/"without exception"/"whether or not", so the pre-#496 phrase
 *       minus one adverb ("releases the lock on every exit path") passed
 *       9/9 with exit 0.
 *
 * v3 (this version) replaces open-ended pattern-matching as the PRIMARY
 * defense with an exact golden-text pin on the sanctioned paragraph itself:
 * any edit to that paragraph - reword, insertion, deletion, widening - fails
 * the test outright, because the correct posture for a safety-critical
 * invariant guarding a cross-session data-destruction bug is "changes here
 * must be deliberate", not "try to enumerate every bad edit". The semantic
 * scan from v2 is retained as defense-in-depth for a NEW contradicting
 * directive added elsewhere in Phase 11b (which wouldn't touch the golden
 * paragraph), with both v2 defects fixed: proximity is now bound to the
 * SAME SENTENCE as the match (not a raw character radius), and a second
 * pattern independently catches "release ... whether or not ... acquired"
 * phrasing that quantifies over acquisition status rather than exit paths.
 *
 * IMPORTANT SCOPE NOTE: this is a prose pin. It verifies THAT THE SCOPING
 * PARAGRAPH IS UNCHANGED (golden pin) and THAT NO CONTRADICTING DIRECTIVE
 * HAS BEEN ADDED ELSEWHERE (semantic net). It cannot catch a conductor that
 * reads the correct prose and still misapplies it - only that the doc
 * itself has not regressed.
 *
 * Run with: node hooks/tests/test-phase11b-release-scoping.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const TARGET = path.join(REPO_ROOT, 'content', 'commands', 'ds-implement-ticket.md');
const PR_496 = 'PR #496';

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
// single space, then trim) so unrelated line-wrap/reflow edits do not break
// these assertions. Assertions below match against this normalized text, not
// raw line-anchored text.
function normalize(text) {
  return text.replace(/\s+/g, ' ').trim();
}

// ---------------------------------------------------------------------------
// The canonical, exact text of the Phase 11b lock-release directive, as
// landed by PR #496 and re-confirmed by this fix pass. Normalized (single-
// spaced) form - compare against the normalized extracted paragraph, not the
// raw file bytes, so that pure line-wrap reflow does not trip this pin.
//
// If you are here because this assertion just failed on a LEGITIMATE reword:
// this paragraph is pinned because a prior version of it caused a real
// cross-session lock-deletion bug (see PR #496 above and the WHY THIS TEST
// EXISTS section). Before updating the constant below, confirm your reword
// still (1) explicitly scopes the release action to ONLY the "If the lock is
// acquired" branch, and (2) explicitly states that the two skip-conditions
// paths and the lock-held-by-another-session path must NOT call the release
// helper. If both hold, update GOLDEN_LOCK_RELEASE_TEXT below to match the
// new wording in the SAME commit as the doc change.
// ---------------------------------------------------------------------------
const GOLDEN_LOCK_RELEASE_TEXT = normalize(
  'Lock release: this applies ONLY within the "If the lock is acquired" ' +
  'branch above - the conductor runs `agentic-wrap-release-lock` ' +
  '(PATH-wired helper) unconditionally on every `wrap-ticket` outcome in ' +
  'that branch (success, non-JSON return, timeout, soft-fail) before ' +
  'advancing to Phase 12. The two skip-conditions paths and the ' +
  'lock-held-by-another-session path never acquired the lock in this ' +
  'session and must NOT call the release helper.'
);

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
// (1) PRIMARY - golden-text pin on the "Lock release:" paragraph.
//
// Locate the paragraph (a blank-line-delimited block in the RAW, unnormalized
// section text) that begins with "Lock release:", normalize it the same way
// as the golden constant, and require EXACT equality. Any edit to this
// paragraph - reword, insertion, deletion, widening, an in-sentence
// qualifier tweak - fails here, by design: this is the correct posture for a
// safety-critical invariant guarding a cross-session data-destruction bug.
// ---------------------------------------------------------------------------
console.log('\n[1] golden-text pin: "Lock release:" paragraph is byte-for-byte (whitespace-normalized) unchanged');
{
  const paragraphs = sectionRaw
    .split(/\n\s*\n+/)
    .map((p) => p.trim())
    .filter(Boolean);
  const goldenParagraphRaw = paragraphs.find((p) => /^Lock release:/i.test(p));

  assert(goldenParagraphRaw !== undefined, 'a paragraph starting with "Lock release:" exists in Phase 11b');

  if (goldenParagraphRaw === undefined) {
    console.error(
      '  The "Lock release:" directive paragraph is missing entirely from Phase 11b.\n' +
      `  This paragraph is pinned because a prior version of it caused a real cross-\n` +
      `  session lock-deletion bug (${PR_496}: pre-fix prose released the wrap lock\n` +
      '  "unconditionally on every exit path" while a lock genuinely held by another\n' +
      '  session was never acquired in this one - the release succeeded anyway and\n' +
      '  deleted the other session\'s lock).\n' +
      '  If this removal is intentional and the section still (1) scopes release to\n' +
      '  ONLY the "If the lock is acquired" branch and (2) states the non-acquiring\n' +
      '  paths must NOT call the release helper, update GOLDEN_LOCK_RELEASE_TEXT in\n' +
      '  this test file to match the new wording in the same commit.'
    );
  } else {
    const actualNormalized = normalize(goldenParagraphRaw);
    const matches = actualNormalized === GOLDEN_LOCK_RELEASE_TEXT;
    assert(
      matches,
      matches
        ? 'the "Lock release:" paragraph text matches the pinned canonical wording exactly'
        : 'the "Lock release:" paragraph text has changed from the pinned canonical wording'
    );
    if (!matches) {
      console.error(
        '  The Phase 11b "Lock release:" directive changed.\n' +
        `  This paragraph is pinned because a prior version of it caused a real cross-\n` +
        `  session lock-deletion bug (${PR_496}: pre-fix prose released the wrap lock\n` +
        '  "unconditionally on every exit path" while a lock genuinely held by another\n' +
        '  session was never acquired in this one - the release succeeded anyway and\n' +
        '  deleted the other session\'s lock).\n' +
        '  If this change is intentional AND the reworded paragraph still (1) scopes\n' +
        '  release to ONLY the "If the lock is acquired" branch and (2) explicitly\n' +
        '  states that the two skip-conditions paths and the lock-held-by-another-\n' +
        '  session path must NOT call the release helper, then the fix is to update\n' +
        '  GOLDEN_LOCK_RELEASE_TEXT in this test file to match, in the same commit.\n' +
        '  --- expected (normalized) ---\n' +
        `  ${GOLDEN_LOCK_RELEASE_TEXT}\n` +
        '  --- actual (normalized) ---\n' +
        `  ${actualNormalized}\n`
      );
    }
  }
}

// ---------------------------------------------------------------------------
// (2) POSITIVE (sanity, section-scoped) - the lock-held-by-another-session
// path still carries its own no-release directive. Not covered by the golden
// pin above (that pin covers only the "Lock release:" paragraph).
// ---------------------------------------------------------------------------
console.log('\n[2] lock-held-by-another-session path carries its own no-release directive');
{
  assert(
    /Do NOT release the lock \(this session never acquired it\)/i.test(section),
    'lock-held-by-another-session path states "Do NOT release the lock (this session never acquired it)"'
  );
}

// ---------------------------------------------------------------------------
// (3) NEGATIVE (defense-in-depth, semantic net) - no NEW release directive
// ELSEWHERE in Phase 11b (outside the golden paragraph) claims universality
// over exit paths/cases, or claims release happens regardless of whether the
// lock was ever acquired. The golden pin above catches an edit TO the
// sanctioned paragraph; this net catches an ADDITIVE contradicting directive
// placed anywhere else in the section (the exact shape of the pre-#496 and
// round-1 defects: two disagreeing locations).
//
// Detection strategy: group the section into UNITS - a unit is one bullet
// list item (one physical line, since this doc's bullets never wrap onto a
// continuation line) or one single-line paragraph/heading. A blank-line-
// delimited block that itself spans multiple physical lines (a bullet list,
// or a heading immediately followed by its bullets on the next lines with no
// blank line between) is split one-unit-per-line; a block that is already a
// single physical line (the common case - most paragraphs and bullets in
// this section) is one unit as-is. Each unit is then split into SENTENCE-
// level spans for match LOCALIZATION (a Pattern A/B co-occurrence must fall
// within one sentence - a raw character-count radius is exactly what round 2
// defeated), while the scope-qualifier EXEMPTION check below is evaluated
// across the WHOLE UNIT, not just the matched sentence - because this doc's
// legitimate scoping language sometimes precedes the matched sentence within
// the same bullet (e.g. "- **If the lock is acquired:** ... below. The
// conductor releases the lock on every exit path ... Phase 12." is ONE
// bullet/unit where the scoping lead-in and the release claim are two
// different sentences of the same list item).
//
//   Pattern A: a release word ("release"/"releases"/"released"/"releasing")
//   co-occurring, IN THE SAME SENTENCE, with a universal-quantifier word
//   ("unconditionally"/"always"/"regardless"/"on all"/"in every case"/
//   "every"/"any"/bare "all"/"without exception"/"no matter") AND an
//   exit-path/case noun ("exit path(s)"/"case(s)"). NOUN is deliberately
//   restricted to "exit path(s)" (not bare "path(s)") and "case(s)" - a bare
//   "path(s)" noun also matches unrelated prose like "the PATH for all
//   invocation paths" (a round-2 Minor false-FAIL), which has nothing to do
//   with lock-release semantics.
//
//   Pattern B: a release word co-occurring, IN THE SAME SENTENCE, with a
//   phrase indicating release happens regardless of acquisition status
//   ("whether (or not)"/"regardless of whether"/"no matter whether") near
//   "acquir*". This catches a wording variant that ignores exit-path/case
//   nouns entirely (e.g. "release the lock whether or not it was
//   acquired"), which Pattern A alone would miss.
//
// A Pattern-A match is excluded only when an explicit scoping qualifier -
// "in that branch" / "within that branch" (the golden paragraph's own
// wording) or "if the lock is acquired" (this doc's other legitimate
// scoping lead-in, used by the summary bullet at "If the lock is acquired:")
// - appears anywhere in the SAME UNIT as the match (bullet-wide or
// paragraph-wide, not a raw character window; see the doc-comment above).
// Pattern B is never excused by either qualifier - neither fixes a directive
// that ignores acquisition status.
//
// The golden paragraph itself is excluded from this scan (see step 3a) so
// it does not self-trip Pattern A on its own legitimate "in that branch"
// scoping - that paragraph's correctness is the golden pin's job, not this
// net's.
// ---------------------------------------------------------------------------
console.log('\n[3] no unscoped or wording-variant unconditional-release claim elsewhere in Phase 11b');
{
  // (3a) Group the raw (unnormalized) section into units, excluding the
  // golden "Lock release:" paragraph.
  function getUnits(raw) {
    const blocks = raw.split(/\n\s*\n+/).map((b) => b.trim()).filter(Boolean);
    const units = [];
    for (const block of blocks) {
      if (/^Lock release:/i.test(block)) continue; // golden paragraph: excluded
      const lines = block.split('\n').map((l) => l.trim()).filter(Boolean);
      if (lines.length <= 1) {
        units.push(block);
      } else {
        for (const line of lines) units.push(line);
      }
    }
    return units;
  }

  // Split a unit into sentence-level spans. A period is treated as a
  // sentence boundary only when followed by whitespace and then an
  // uppercase letter, a quote, a backtick, an opening paren, or a list-item
  // dash - this avoids splitting mid-abbreviation (e.g. "etc.)" is NOT
  // followed by whitespace, so it is correctly NOT treated as a boundary)
  // while still splitting normal multi-sentence prose.
  function splitSentences(text) {
    const spans = [];
    let last = 0;
    const re = /\.(\s+)(?=[A-Z"'`(-])/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      spans.push(text.slice(last, m.index + 1));
      last = m.index + 1 + m[1].length;
      re.lastIndex = last;
    }
    spans.push(text.slice(last));
    return spans.map((s) => s.trim()).filter(Boolean);
  }

  const RELEASE = '(?:releas\\w*)';
  const QUANT = '(?:unconditionally|always|regardless(?:\\s+of)?|on\\s+all|in\\s+every\\s+case|every|any|all|without\\s+exception|no\\s+matter)';
  const NOUN = '(?:exit\\s+paths?|cases?)';
  const SCOPE_QUALIFIER = /\b(?:in|within)\s+that\s+branch\b|if\s+the\s+lock\s+is\s+acquired/i;

  // WINDOW is a BOUNDED lazy span (not `[^]*?` unbounded), which keeps
  // matching linear even on a pathological adversarial unit (e.g. a single
  // multi-hundred-KB "sentence" with no periods to split on, repeating the
  // word "release" thousands of times with no quantifier ever following -
  // an unbounded lazy span there is O(n^2): every "release" occurrence
  // re-scans to the end of the string before giving up). 300 chars is
  // generous headroom over any real single sentence in this section that
  // legitimately needs to co-occur across RELEASE/QUANT/NOUN.
  const WINDOW = '[^]{0,300}?';

  const forwardA = new RegExp(`\\b${RELEASE}\\b${WINDOW}\\b${QUANT}\\b${WINDOW}\\b${NOUN}\\b`, 'i');
  const backwardA = new RegExp(`\\b${QUANT}\\b${WINDOW}\\b${NOUN}\\b${WINDOW}\\b${RELEASE}\\b`, 'i');

  const QUANT2 = '(?:whether(?:\\s+or\\s+not)?|regardless\\s+of\\s+whether|no\\s+matter\\s+whether)';
  const ACQUIRE = '(?:acquir\\w*)';
  const forwardB = new RegExp(`\\b${RELEASE}\\b${WINDOW}\\b${QUANT2}\\b${WINDOW}\\b${ACQUIRE}\\b`, 'i');
  const backwardB = new RegExp(`\\b${ACQUIRE}\\b${WINDOW}\\b${QUANT2}\\b${WINDOW}\\b${RELEASE}\\b`, 'i');

  const units = getUnits(sectionRaw);
  const hits = [];
  for (const unitRaw of units) {
    const unitNormalized = normalize(unitRaw);
    const unitHasQualifier = SCOPE_QUALIFIER.test(unitNormalized);
    for (const sentence of splitSentences(unitNormalized)) {
      const aHit = forwardA.test(sentence) || backwardA.test(sentence);
      if (aHit && !unitHasQualifier) {
        hits.push(sentence);
        continue;
      }
      const bHit = forwardB.test(sentence) || backwardB.test(sentence);
      if (bHit) {
        hits.push(sentence);
      }
    }
  }

  assert(
    hits.length === 0,
    hits.length === 0
      ? 'no release directive outside the golden paragraph co-occurs (in one sentence) with an unscoped universal quantifier over exit paths/cases, or with an acquisition-status-independent release claim'
      : `found ${hits.length} unscoped/wording-variant release directive(s) elsewhere in Phase 11b (e.g. "${hits[0].slice(0, 200)}") - a release/lock directive must not claim universality over exit paths or cases (without a same-bullet/paragraph "in that branch"/"within that branch"/"if the lock is acquired" qualifier), nor claim release happens regardless of acquisition status`
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
// "on all outcomes within that branch".
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
