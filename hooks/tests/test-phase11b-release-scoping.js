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
 * v3 (round 2 fix) replaces open-ended pattern-matching as the PRIMARY
 * defense with an exact golden-text pin on the sanctioned "Lock release:"
 * paragraph itself: any edit to that paragraph - reword, insertion,
 * deletion, widening - fails the test outright, because the correct posture
 * for a safety-critical invariant guarding a cross-session data-destruction
 * bug is "changes here must be deliberate", not "try to enumerate every bad
 * edit". The semantic scan from v2 is retained as defense-in-depth for a NEW
 * contradicting directive added elsewhere in Phase 11b (which wouldn't touch
 * the golden paragraph), with both v2 defects fixed: proximity is now bound
 * to the SAME SENTENCE as the match (not a raw character radius), and a
 * second pattern independently catches "release ... whether or not ...
 * acquired" phrasing that quantifies over acquisition status rather than
 * exit paths.
 *
 * v4 (round 3 fix) closes a gap v3 left open: v3's golden pin covers only
 * the "Lock release:" paragraph, and v3's semantic net exempts a whole UNIT
 * (bullet) from Pattern A once any qualifier phrase appears anywhere in that
 * unit - including the "**If the lock is acquired:**" bullet's own leading
 * text. That meant a sentence appended INSIDE that bullet extending release
 * to the non-acquiring paths (e.g. "...including the two skip-conditions
 * paths and the lock-held-by-another-session path") passed cleanly: the
 * golden pin never saw it (wrong paragraph) and the net excused it (unit-wide
 * qualifier). v4 adds two independent defenses: (1) a second golden-text pin
 * on the "**If the lock is acquired:**" bullet itself, so any edit to it -
 * including an appended sentence - fails outright; (2) Pattern C in the
 * semantic net, which fires when a release word co-occurs with a phrase
 * NAMING a non-acquiring path, and which (unlike Pattern A) is NEVER excused
 * by the unit-wide scope qualifier - only by an in-sentence negation
 * ("do NOT release", "never release") that marks the sentence as prohibitive
 * rather than directive.
 *
 * v5 (round 4 fix) hardens Pattern C's negation exemption and its PATH_NAME
 * lexicon, both defeated by adversarial review:
 *   (a) Pattern C's negation exemption was a raw "negation word within 30
 *       chars before the release word" radius. A DOUBLE-NEGATIVE directive
 *       ("Do not skip the release on the lock held by another session
 *       path.", "Never withhold release on the skip-conditions paths.")
 *       sits inside that radius while asserting the OPPOSITE of a
 *       prohibition - it instructs release TO happen. Fixed by
 *       `isGenuinelyNegated()`, which additionally requires that no
 *       inversion word (skip/omit/withhold/forgo/forego/neglect) sits
 *       between the negation trigger and the release word.
 *   (b) The same raw radius false-FAILed on legitimate prohibitive prose
 *       whose negation is genuinely more than 30 chars from "release" (an
 *       intervening adverbial aside: "Do NOT, under any circumstances
 *       whatsoever, release the lock...") or that uses a standalone
 *       circumstantial negator with no "not"/"never" at all ("...must
 *       under no circumstances invoke the release helper."). Fixed (in v5)
 *       by stripping short comma-delimited adverbial asides ANYWHERE in the
 *       sentence before matching, and by widening the negation-trigger
 *       lexicon to include standalone circumstantial negators. v5's aside
 *       strip was unanchored - see v6 below for the regression this caused
 *       and its fix.
 *   (c) PATH_NAME was a verbatim transcription of five phrases and missed
 *       plausible spelling variants: the doc's own heading spells one path
 *       with a SPACE ("skip conditions") while the pattern required a
 *       hyphen or nothing, and a hyphenated form of another path
 *       ("lock-held-by-another-session") did not match a pattern requiring
 *       literal spaces. Fixed by widening separators to `[-\s]+` throughout,
 *       plus adding "without having acquir*"/"hadn't acquir*"/"was not
 *       acquir*" as additional non-acquisition phrasings.
 *
 * v6 (round 5 fix) fixes a REGRESSION introduced by v5(b)'s aside-stripping
 * and finishes v4's reflow tolerance:
 *   (a) v5's `stripAsides()` removed a short comma-delimited aside from
 *       ANYWHERE in the sentence, not just from immediately after the
 *       negation trigger. That let an aside following an UNRELATED EARLIER
 *       CLAUSE get stripped, shortening the trigger-to-release distance and
 *       wrongly exempting a genuine unscoped release directive conjoined to
 *       the negated clause by "and"/"so" (e.g. "The conductor must not
 *       block Phase 12, however long wrap-ticket runs, and releases the
 *       lock on the skip-conditions paths." - the "however long ..." aside
 *       sits after "block Phase 12", not after "must not", but stripping it
 *       pulled "releases" inside the 30-char post-strip gap of "must not",
 *       which negates "block", not "releases"). Fixed by anchoring the
 *       aside consumption directly to the negation trigger: the optional
 *       aside is now matched as part of the SAME regex immediately after
 *       the trigger token (`TRIGGER_ADJACENT_ASIDE`), so an aside anywhere
 *       else in the sentence is left untouched and cannot bridge two
 *       unrelated clauses. `stripAsides()` as a free-floating string
 *       rewrite is removed entirely.
 *   (b) Step (3)'s `getUnits()` still split any multi-physical-line block
 *       one unit per line, even after v4 taught step (1b)'s golden pin to
 *       tolerate a pure reflow of the "**If the lock is acquired:**" bullet
 *       onto continuation lines. A harmless reflow (zero wording change)
 *       therefore still passed (1b) but failed (3): the qualifier phrase
 *       "If the lock is acquired" (on the bullet's first physical line) and
 *       the release clause (pushed onto a continuation line by the wrap)
 *       ended up in two different single-line "units", so the unit-wide
 *       scope-qualifier exemption no longer covered the release clause.
 *       Fixed by making `getUnits()` merge a bullet or heading start line
 *       with any following continuation lines into one unit - mirroring
 *       `extractBulletWithContinuation()` in step (1b) - so a reflow with no
 *       wording change stays exempt, while a substantive edit (an appended
 *       sentence, a contradicting continuation, a reorder, or a wording
 *       change) is still caught by the golden pin and/or the semantic net.
 *
 * IMPORTANT SCOPE NOTE: this is a prose pin. It verifies THAT THE SCOPING
 * PARAGRAPH AND BULLET ARE UNCHANGED (golden pins) and THAT NO CONTRADICTING
 * DIRECTIVE HAS BEEN ADDED ELSEWHERE (semantic net, Patterns A/B/C). It
 * cannot catch a conductor that reads the correct prose and still misapplies
 * it - only that the doc itself has not regressed.
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
// The canonical, exact text of the "**If the lock is acquired:**" bullet
// (immediately above the "Lock release:" paragraph). Round-3 adversarial
// review found this bullet is a live gap: a sentence can be appended INSIDE
// this bullet that extends release to the non-acquiring paths, and it slips
// past every existing assertion -
//   - the golden pin above only covers the "Lock release:" paragraph, so an
//     edit confined to THIS bullet leaves it untouched;
//   - the semantic net's scope-qualifier exemption (see step (3) below) is
//     evaluated UNIT-WIDE (bullet-wide), and this bullet's own leading
//     "**If the lock is acquired:**" text satisfies the "if the lock is
//     acquired" qualifier for the ENTIRE bullet - so a Pattern-A-shaped
//     sentence added later in the same bullet is excused regardless of what
//     it actually claims;
//   - a wording variant that quantifies over acquisition status instead of
//     exit paths (Pattern B's shape) does not require the "exit path"/"case"
//     noun at all, so it can dodge Pattern A's noun restriction too.
// Golden-pinning this bullet closes the gap the same way the paragraph pin
// closes it for "Lock release:": any edit to this bullet - reword,
// insertion, deletion, widening - fails here, by design.
//
// If you are here because this assertion just failed on a LEGITIMATE reword:
// before updating the constant below, confirm your reword still (1) confines
// this bullet's release action to the "If the lock is acquired" branch only,
// and (2) does not add any sentence extending release to the two
// skip-conditions paths or the lock-held-by-another-session path. If both
// hold, update GOLDEN_ACQUIRED_BULLET_TEXT to match the new wording in the
// SAME commit as the doc change.
// ---------------------------------------------------------------------------
const GOLDEN_ACQUIRED_BULLET_TEXT = normalize(
  '- **If the lock is acquired:** spawn `wrap-ticket` with the inputs ' +
  'below. The conductor releases the lock on every exit path (success, ' +
  'timeout, soft-fail) before proceeding to Phase 12.'
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
      '  No paragraph in Phase 11b starts with the exact prefix "Lock release:".\n' +
      '  This detector matches on a literal leading prefix, so it CANNOT distinguish\n' +
      '  three different causes: the paragraph is (a) missing entirely, (b) present\n' +
      '  but re-prefixed (e.g. bolded as "**Lock release:**", bulleted as "- Lock\n' +
      '  release:", or reworded as "Wrap-lock release:"), or (c) merged into another\n' +
      '  paragraph. Check the Phase 11b section by hand to determine which.\n' +
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
// (1b) PRIMARY - golden-text pin on the "**If the lock is acquired:**"
// bullet.
//
// Located by pattern (a line starting with "- **If the lock is acquired:**")
// within the extracted RAW section, not by hardcoded line number - the file
// grows and a fixed offset would silently drift. This doc's bullets do not
// currently wrap onto a continuation line, but a pure REFLOW of this bullet
// (line-wrapping the same text onto continuation lines with no wording
// change) is harmless and should not trip this pin - only a substantive edit
// should. `extractBulletWithContinuation` therefore consumes any
// continuation lines that follow the bullet's start line, stopping at the
// first blank line, the next `- ` list item, or a heading - since
// `normalize()` collapses whitespace/newlines to single spaces anyway, this
// widens what counts as "the bullet" without weakening the golden pin's
// strictness against a substantive edit (any wording change still fails the
// exact-equality check below).
// ---------------------------------------------------------------------------
console.log('\n[1b] golden-text pin: "**If the lock is acquired:**" bullet is byte-for-byte (whitespace-normalized) unchanged');
{
  function extractBulletWithContinuation(raw, startLineRe) {
    const lines = raw.split('\n');
    let startIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      if (startLineRe.test(lines[i])) { startIdx = i; break; }
    }
    if (startIdx === -1) return null;
    const collected = [lines[startIdx]];
    for (let i = startIdx + 1; i < lines.length; i++) {
      const trimmed = lines[i].trim();
      if (trimmed === '') break; // blank line ends the bullet
      if (/^-\s/.test(trimmed)) break; // next list item starts
      if (/^#{1,6}\s/.test(trimmed)) break; // heading starts
      collected.push(lines[i]);
    }
    return collected.join(' ');
  }

  const acquiredBulletStartRe = /^- \*\*If the lock is acquired:\*\*/;
  const acquiredBulletText = extractBulletWithContinuation(sectionRaw, acquiredBulletStartRe);

  assert(acquiredBulletText !== null, 'the "**If the lock is acquired:**" bullet exists in Phase 11b');

  if (acquiredBulletText === null) {
    console.error(
      '  The "**If the lock is acquired:**" bullet is missing, renamed, or re-prefixed\n' +
      '  in Phase 11b.\n' +
      `  This bullet is pinned because round-3 adversarial review (${PR_496} follow-up)\n` +
      '  found that a sentence appended INSIDE this bullet can silently extend release\n' +
      '  to the non-acquiring paths (the two skip-conditions paths and the\n' +
      '  lock-held-by-another-session path) without tripping the "Lock release:"\n' +
      '  paragraph pin or the semantic net, because this bullet\'s own leading text\n' +
      '  satisfies the net\'s scope-qualifier exemption for the WHOLE bullet.\n' +
      '  If this removal is intentional and the section still (1) confines this\n' +
      '  bullet\'s release action to the "If the lock is acquired" branch only and\n' +
      '  (2) adds no sentence extending release to the non-acquiring paths, update\n' +
      '  GOLDEN_ACQUIRED_BULLET_TEXT in this test file to match the new wording in\n' +
      '  the same commit.'
    );
  } else {
    const actualAcquiredNormalized = normalize(acquiredBulletText);
    const acquiredMatches = actualAcquiredNormalized === GOLDEN_ACQUIRED_BULLET_TEXT;
    assert(
      acquiredMatches,
      acquiredMatches
        ? 'the "**If the lock is acquired:**" bullet text matches the pinned canonical wording exactly'
        : 'the "**If the lock is acquired:**" bullet text has changed from the pinned canonical wording'
    );
    if (!acquiredMatches) {
      console.error(
        '  The Phase 11b "**If the lock is acquired:**" bullet changed.\n' +
        `  This bullet is pinned because round-3 adversarial review (${PR_496} follow-up)\n` +
        '  found that a sentence appended INSIDE this bullet can silently extend release\n' +
        '  to the non-acquiring paths (the two skip-conditions paths and the\n' +
        '  lock-held-by-another-session path) without tripping the "Lock release:"\n' +
        '  paragraph pin or the semantic net, because this bullet\'s own leading text\n' +
        '  satisfies the net\'s scope-qualifier exemption for the WHOLE bullet.\n' +
        '  If this change is intentional AND the reworded bullet still (1) confines\n' +
        '  release to ONLY the "If the lock is acquired" branch and (2) adds no\n' +
        '  sentence extending release to the two skip-conditions paths or the\n' +
        '  lock-held-by-another-session path, then the fix is to update\n' +
        '  GOLDEN_ACQUIRED_BULLET_TEXT in this test file to match, in the same commit.\n' +
        '  --- expected (normalized) ---\n' +
        `  ${GOLDEN_ACQUIRED_BULLET_TEXT}\n` +
        '  --- actual (normalized) ---\n' +
        `  ${actualAcquiredNormalized}\n`
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
// list item or one paragraph/heading, INCLUDING any continuation lines that
// wrap it (mirroring `extractBulletWithContinuation()` in step (1b), so a
// pure reflow with no wording change is exempt here the same way it is
// exempt there). A blank-line-delimited block that spans multiple physical
// lines (a bullet list, or a heading immediately followed by its bullets on
// the next lines with no blank line between) is split at each new bullet/
// heading start line; any line that is neither a bullet nor a heading start
// is treated as a CONTINUATION of the preceding unit and merged into it. A
// block that is already a single physical line (the common case - most
// paragraphs and bullets in this section) is one unit as-is. Each unit is
// then split into SENTENCE-
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
  // golden "Lock release:" paragraph. A unit is one bullet/heading start
  // line plus any continuation lines that follow it (lines that are
  // themselves neither a new bullet nor a heading), so a pure line-wrap
  // reflow of a bullet does not split its qualifier phrase and its release
  // clause into two different units - matching
  // `extractBulletWithContinuation()` in step (1b).
  function getUnits(raw) {
    const blocks = raw.split(/\n\s*\n+/).map((b) => b.trim()).filter(Boolean);
    const units = [];
    for (const block of blocks) {
      if (/^Lock release:/i.test(block)) continue; // golden paragraph: excluded
      const lines = block.split('\n').map((l) => l.trim()).filter(Boolean);
      if (lines.length <= 1) {
        if (lines.length === 1) units.push(block);
        continue;
      }
      let current = null;
      for (const line of lines) {
        const isBullet = /^-\s/.test(line);
        const isHeading = /^#{1,6}\s/.test(line);
        if (isBullet || isHeading || current === null) {
          if (current !== null) units.push(current);
          current = line;
        } else {
          current += ' ' + line; // continuation line: merge into current unit
        }
      }
      if (current !== null) units.push(current);
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

  // Pattern C: a release word co-occurring, IN THE SAME SENTENCE, with a
  // phrase that NAMES one of the non-acquiring paths (the two
  // skip-conditions paths, the lock-held-by-another-session path). This
  // catches a sentence that extends a release directive to those paths by
  // naming them directly, rather than by a universal quantifier (Pattern A)
  // or an acquisition-status phrase (Pattern B) - the exact shape of the
  // round-3 exploit sentence appended inside the "**If the lock is
  // acquired:**" bullet ("...including the two skip-conditions paths and the
  // lock-held-by-another-session path"). Pattern C is NEVER excused by
  // SCOPE_QUALIFIER - naming a non-acquiring path in a release directive is
  // wrong regardless of surrounding scope words ("if the lock is acquired"
  // does not un-name a path the same sentence also names as released).
  //
  // The one legitimate exception is NEGATED/PROHIBITIVE phrasing - a
  // sentence that says release must NOT happen for a named non-acquiring
  // path (e.g. "Do NOT release the lock (this session never acquired it)."
  // - the lock-held-by-another-session bullet's own correct directive, or
  // "...must NOT call the release helper." in the golden "Lock release:"
  // paragraph, already excluded from `units` by getUnits()). This exemption
  // is implemented by `isGenuinelyNegated()` (round-4 hardening; see its
  // doc comment below), NOT a raw negation-within-N-chars radius - round 4
  // found the raw radius was defeated in both directions: a double-negative
  // directive ("Do not skip the release...") sits inside any plausible
  // radius while asserting the OPPOSITE of a prohibition, and legitimate
  // prohibitive prose can legitimately separate the negation from "release"
  // by more than any fixed radius (an intervening adverbial aside, or a
  // standalone circumstantial negator with no "not"/"never" at all).
  // PATH_NAME separators are widened to `[-\s]+` (one-or-more hyphen/space)
  // rather than a fixed literal spelling, because the doc's own heading uses
  // a SPACE ("skip conditions") while the exploit-sentence catalog uses a
  // HYPHEN ("lock-held-by-another-session") - a pattern anchored to only one
  // spelling missed the other. Two additional phrasings are added for
  // "released even though this session never acquired the lock": "without
  // having acquir*", "hadn't acquir*", "was not acquir*".
  const PATH_NAME = '(?:skip[-\\s]?conditions?|held[-\\s]+by[-\\s]+another[-\\s]+session|never\\s+acquir\\w*|did\\s+not\\s+acquir\\w*|did\\s+not\\s+create|without\\s+having\\s+acquir\\w*|hadn\'?t\\s+acquir\\w*|was\\s+not\\s+acquir\\w*)';
  const forwardC = new RegExp(`\\b${RELEASE}\\b${WINDOW}\\b${PATH_NAME}\\b`, 'i');
  const backwardC = new RegExp(`\\b${PATH_NAME}\\b${WINDOW}\\b${RELEASE}\\b`, 'i');

  // NEGATED_RELEASE exemption, round-4 hardening.
  //
  // A raw "negation-trigger within N chars of the release word" radius (the
  // pre-round-4 shape) is defeated in BOTH directions by real prose:
  //   (i)  a DOUBLE NEGATIVE directive - "Do not skip the release", "Never
  //        withhold release", "Do not omit the release" - sits well inside
  //        any plausible radius while asserting the exact opposite of what
  //        the exemption assumes: these sentences instruct release TO
  //        happen, they do not prohibit it. INVERSION_WORD closes this: if
  //        one of skip/omit/withhold/forgo/forego/neglect appears between
  //        the negation trigger and the release word, that trigger does NOT
  //        count as a genuine negation of release.
  //   (ii) legitimate prohibitive prose can separate the negation trigger
  //        from "release" by more than any fixed radius via an intervening
  //        adverbial aside ("Do NOT, under any circumstances whatsoever,
  //        release the lock") or via a standalone circumstantial negator
  //        with no "not"/"never" at all ("...must under no circumstances
  //        invoke the release helper"). Fix: (a) allow an adverbial aside to
  //        be optionally consumed IMMEDIATELY AFTER the negation trigger
  //        (see `TRIGGER_ADJACENT_ASIDE` below), so the negation and the
  //        verb it governs read as the same clause instead of
  //        radius-separated; (b) widen the trigger set to include standalone
  //        circumstantial negators ("under no circumstances", "in no case",
  //        "on no account", "in no event") that do not require a
  //        co-occurring "not"/"never".
  //
  // v6 correction: an earlier version of fix (ii)(a) stripped a short
  // comma-delimited aside from ANYWHERE in the sentence before matching, not
  // just from immediately after the trigger. That was a regression: it let
  // an aside following an UNRELATED EARLIER CLAUSE be removed, shortening
  // the apparent trigger-to-release distance and wrongly exempting a
  // genuine unscoped release directive conjoined to the negated clause by
  // "and"/"so" (e.g. "The conductor must not block Phase 12, however long
  // wrap-ticket runs, and releases the lock on the skip-conditions paths." -
  // "not" negates "block", not "releases", but stripping the unrelated
  // "however long..." aside pulled "releases" inside the post-strip 30-char
  // gap of "must not"). Fixed by folding the optional aside into the SAME
  // regex as the trigger, immediately after it (`TRIGGER_ADJACENT_ASIDE`),
  // so only an aside directly adjacent to the trigger can be consumed - an
  // aside anywhere else in the sentence is left untouched and cannot bridge
  // two unrelated clauses. The residual 30-char gap after the (optional)
  // aside still bounds the search to a single local clause; it is anchored
  // to the trigger's own immediate continuation, not a free-floating radius
  // that can be shortened by unrelated text elsewhere in the sentence.
  const INVERSION_WORD = /\b(?:skip|omit|withhold|forgo|forego|neglect)\b/i;
  const NEGATION_TRIGGER =
    '(?:(?:do|does|did|must|shall|will|should)\\s+not|never|' +
    'under\\s+no\\s+circumstances|in\\s+no\\s+case|on\\s+no\\s+account|in\\s+no\\s+event)';
  // Optionally consumes a short comma-delimited adverbial aside, but ONLY
  // when it starts immediately (after optional whitespace) at the negation
  // trigger - never a free-floating strip elsewhere in the sentence.
  const TRIGGER_ADJACENT_ASIDE = '(?:,\\s*[^,]{1,60}?,\\s*)?';
  const negatedReleaseRe = new RegExp(
    `\\b${NEGATION_TRIGGER}\\b${TRIGGER_ADJACENT_ASIDE}([^]{0,30}?)\\b${RELEASE}\\b`,
    'gi'
  );

  function isGenuinelyNegated(sentence) {
    negatedReleaseRe.lastIndex = 0;
    let m;
    while ((m = negatedReleaseRe.exec(sentence)) !== null) {
      const gap = m[1];
      if (!INVERSION_WORD.test(gap)) return true;
      if (negatedReleaseRe.lastIndex === m.index) negatedReleaseRe.lastIndex++;
    }
    return false;
  }

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
        continue;
      }
      const cHit = forwardC.test(sentence) || backwardC.test(sentence);
      if (cHit && !isGenuinelyNegated(sentence)) {
        hits.push(sentence);
      }
    }
  }

  assert(
    hits.length === 0,
    hits.length === 0
      ? 'no release directive outside the golden paragraph co-occurs (in one sentence) with an unscoped universal quantifier over exit paths/cases, an acquisition-status-independent release claim, or a non-negated reference to a non-acquiring path'
      : `found ${hits.length} unscoped/wording-variant release directive(s) elsewhere in Phase 11b (e.g. "${hits[0].slice(0, 200)}") - a release/lock directive must not claim universality over exit paths or cases (without a same-bullet/paragraph "in that branch"/"within that branch"/"if the lock is acquired" qualifier), must not claim release happens regardless of acquisition status, and must not (in non-negated phrasing) extend release to a named non-acquiring path (skip-conditions paths, lock-held-by-another-session path)`
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
