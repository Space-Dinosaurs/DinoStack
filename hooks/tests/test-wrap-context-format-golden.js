#!/usr/bin/env node
/**
 * Content-pin + structural test for the MINOR-E format extraction
 * (architect-plan verification-gate case 21).
 *
 * WHY THIS IS NOT AN EXECUTABLE BYTE-IDENTITY TEST
 * ------------------------------------------------
 * Case 21 in the architect plan asks for a "golden-file Part A byte-identity"
 * test proving that interactive `/wrap` Part A produces byte-identical context.md
 * output before and after the merge algorithm was extracted into
 * `content/references/wrap-context-format.md`. That algorithm is PROSE - a set of
 * model-executed instructions ("relabel [Session B] as [Session A]", "union both
 * lists", ...), not runnable code. There is no function to call and no
 * deterministic program output to diff, so a true output-byte-identity test is not
 * runnable in a hermetic Node harness. Running the actual `/wrap` would require a
 * live model and is neither hermetic nor deterministic.
 *
 * WHAT IS FEASIBLE (and what this test does)
 * ------------------------------------------
 *   (A) CONTENT PIN: snapshot the reference's normative merge-algorithm section
 *       against a committed golden fixture. Any future drift to the extracted
 *       algorithm (the single normative home both `/wrap` and `/wrap-deferred`
 *       cite) is caught here. If the change is intentional, the golden is
 *       regenerated in the same commit - the test then documents the change.
 *   (B) STRUCTURAL EXTRACTION: assert that `content/commands/wrap.md` Part A CITES
 *       the reference and contains NO inline copy of the merge algorithm. This is
 *       what makes the extraction real: the algorithm must live in exactly ONE
 *       place. A regression that re-inlines the algorithm into wrap.md (re-creating
 *       the drift surface MINOR-E removed) fails here.
 *
 * To regenerate the golden after an INTENTIONAL change to the reference algorithm:
 *   node -e 'const fs=require("fs");const r=fs.readFileSync("content/references/wrap-context-format.md","utf8");const i=r.indexOf("## context.md rolling-session-label merge algorithm (NORMATIVE)");fs.writeFileSync("hooks/tests/fixtures/wrap-context-merge-algorithm.golden.md",r.slice(i),"utf8")'
 * (run from the repo root).
 *
 * Run with: node hooks/tests/test-wrap-context-format-golden.js
 */

'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const REFERENCE = path.join(REPO_ROOT, 'content', 'references', 'wrap-context-format.md');
const WRAP_MD = path.join(REPO_ROOT, 'content', 'commands', 'wrap.md');
const GOLDEN = path.join(__dirname, 'fixtures', 'wrap-context-merge-algorithm.golden.md');

// The deterministic section boundary: the merge-algorithm section runs from this
// header to EOF (it is the last section of the reference).
const SECTION_MARKER = '## context.md rolling-session-label merge algorithm (NORMATIVE)';

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

/** Extract the normative merge-algorithm section (marker -> EOF) from the reference. */
function extractAlgorithmSection(refText) {
  if (typeof refText !== 'string') return null;
  const idx = refText.indexOf(SECTION_MARKER);
  if (idx < 0) return null;
  return refText.slice(idx);
}

// ---------------------------------------------------------------------------
// Pre-flight: required files exist
// ---------------------------------------------------------------------------
console.log('\n[pre] required files exist');
const refText = readFile(REFERENCE);
const wrapText = readFile(WRAP_MD);
const goldenText = readFile(GOLDEN);
assert(refText !== null, `reference exists: ${path.relative(REPO_ROOT, REFERENCE)}`);
assert(wrapText !== null, `wrap.md exists: ${path.relative(REPO_ROOT, WRAP_MD)}`);
assert(goldenText !== null, `golden fixture exists: ${path.relative(REPO_ROOT, GOLDEN)}`);

if (refText === null || wrapText === null || goldenText === null) {
  console.log(`\n${passed} passed, ${failed} failed.`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// (A) CONTENT PIN: the live algorithm section matches the committed golden
// ---------------------------------------------------------------------------
console.log('\n[21-A] content pin: reference merge-algorithm section == committed golden (drift guard)');
{
  const section = extractAlgorithmSection(refText);
  assert(section !== null,
    `the normative section marker is present in the reference ("${SECTION_MARKER}")`);

  if (section !== null) {
    assert(section === goldenText,
      'live merge-algorithm section is byte-identical to the golden fixture (no undocumented drift)');

    const liveHash = crypto.createHash('sha256').update(section, 'utf8').digest('hex');
    const goldHash = crypto.createHash('sha256').update(goldenText, 'utf8').digest('hex');
    assert(liveHash === goldHash,
      `sha256 of the live section matches the golden (${goldHash.slice(0, 12)}...)`);

    // Sanity: the golden actually contains the load-bearing rolling-window steps
    // (so an empty/placeholder golden cannot pass the equality check vacuously).
    assert(/Five labels present/.test(goldenText) && /relabel `\[Session B\]` as `\[Session A\]`/.test(goldenText),
      'golden contains the 5-label rolling-window step (fixture is the real algorithm, not a stub)');
    assert(/Duplicate-claim dedup/.test(goldenText),
      'golden contains the duplicate-claim dedup (idempotency) rule');
  }
}

// ---------------------------------------------------------------------------
// (B) STRUCTURAL EXTRACTION: wrap.md cites the reference + does NOT re-inline it
// ---------------------------------------------------------------------------
console.log('\n[21-B] structural: wrap.md Part A CITES the reference and inlines NO merge algorithm');
{
  // (1) wrap.md cites the shared reference at least once.
  assert(wrapText.includes('wrap-context-format.md'),
    'wrap.md cites content/references/wrap-context-format.md');

  // (2) The Part A wrapper explicitly defers the algorithm to the reference and
  //     states the algorithm itself is not restated here.
  assert(/rolling-session-label merge algorithm/.test(wrapText)
    && /not restated here|NOT restated here/.test(wrapText),
    'wrap.md Part A explicitly states the merge algorithm is NOT restated inline');

  // (3) The distinctive algorithm STEPS must NOT appear inline in wrap.md. These
  //     phrases are unique to the extracted algorithm body; their presence in
  //     wrap.md would mean the algorithm was re-inlined (the drift surface MINOR-E
  //     removed). They MUST live only in the reference.
  const inlineOnlyPhrases = [
    'relabel `[Session B]` as `[Session A]`',
    'Five labels present',
    'Wrote fresh context to [path] (no existing file)',
    'Merged context written to [path] (combined sessions)',
  ];
  for (const phrase of inlineOnlyPhrases) {
    assert(!wrapText.includes(phrase),
      `wrap.md does NOT inline the algorithm step: "${phrase.slice(0, 48)}..."`);
    assert(refText.includes(phrase),
      `the reference DOES own the algorithm step: "${phrase.slice(0, 48)}..."`);
  }
}

// ---------------------------------------------------------------------------
// (C) Reference declares its consumers (the extraction's contract surface)
// ---------------------------------------------------------------------------
console.log('\n[21-C] the reference declares both consumers (wrap + wrap-deferred)');
{
  assert(/Consumers:/.test(refText), 'reference opens with a Consumers declaration');
  assert(/wrap\.md/.test(refText) && /wrap-deferred\.md/.test(refText),
    'reference names both /wrap and /wrap-deferred as consumers');
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
