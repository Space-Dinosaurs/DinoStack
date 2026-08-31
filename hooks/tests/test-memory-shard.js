#!/usr/bin/env node
'use strict';

/**
 * Unit + integration tests for hooks/lib/memory-shard.js and its CLI wrapper
 * bin/ds-memory-shard (DS-221 Unit 1). Operates ONLY on the checked-in
 * synthetic fixture hooks/tests/fixtures/memory-shard-sample.md - never on
 * this repo's own root MEMORY.md, which is untracked by design (DS-129),
 * absent from a fresh clone, and absent from a worktree-isolated engineer's
 * checkout.
 *
 * Each required case below is paired with a NAMED mutation that is actually
 * RUN (never merely described) against a throwaway in-memory copy of the
 * library, confirming the mutant fails the same assertion the real code
 * passes. Mutation tests load the mutated source from a temp file via an
 * ABSOLUTE path (never overwriting the real hooks/lib/memory-shard.js on
 * disk), so a crash mid-test can never leave the shipped module mutated.
 *
 * Cases:
 *   1. Round-trip byte-identity            (+ mutation: drop trailing-blank
 *                                             -line capture)
 *   2. Entry-loss refusal                  (+ mutation: substring
 *                                             containment instead of
 *                                             multiset)
 *   3. Reorder refusal                     (+ mutation: remove the
 *                                             permutation detector)
 *   4. Gap-spacing collision               (+ mutation: off-by-one midpoint
 *                                             arithmetic)
 *   5. Gitignore carve-out                 (+ mutation: delete only the
 *                                             bare directory negation,
 *                                             keeping `**` - measured to be
 *                                             the load-bearing line under
 *                                             this repo's `.agentic/*`
 *                                             one-level-glob umbrella; see
 *                                             the in-test comment)
 *   6. Concurrency demonstration           (+ mutation: two clones each
 *                                             rewrite the same compiled
 *                                             region instead of adding a
 *                                             shard)
 *
 * Additional coverage (Skeptic round 3): the six briefed cases above were
 * exhaustively audited case-by-case for the "would this assertion still
 * pass against a completely broken implementation" question - the CLI
 * status-code check in case 2 failed that audit (fixed above) and every
 * other assertion in cases 1-6 was confirmed to discriminate correctly.
 * The gaps that audit surfaced (a whole untested binary, six undocumented
 * manifest guarantees, one unregression-tested prior fix) are covered by
 * the additional cases below, each with its own independently-run mutation:
 *   - CLI success path (caseCliSuccessPath) - the CLI actually writes
 *     shard files to disk, not just "exits 0"; mutation: a stub that
 *     fakes success without calling splitCommand.
 *   - CLI arg-parsing (caseCliArgParsing) - unknown flag, split --check,
 *     regenerate --force, unknown subcommand, --dir with no operand -
 *     each rejection independently mutation-verified via a temp-staged
 *     CLI copy (runMutatedCli) that reproduces the real bin/../hooks/lib
 *     relative layout.
 *   - writeFileAtomic's stage-then-rename guarantee (caseWriteFileAtomicIsReallyAtomic)
 *     - verified via an fs.renameSync spy, not by trusting the docstring.
 *   - Six previously-untested manifest guarantees, each with its own
 *     mutation: re-split refusal, bulk-orphan threshold, duplicate-sequence
 *     refusal, non-".md" refusal, pre-commit round-trip verification, and
 *     post-commit verification (the latter two via a corruption-injecting
 *     mutation that creates a LEGITIMATE trigger for each guard, then a
 *     second mutation that also disables the guard).
 *   - A regression pin for the round-2 ENOENT-narrowing fix
 *     (caseEnoentNarrowingRegression).
 *
 * Run with: node hooks/tests/test-memory-shard.js
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const LIB_PATH = path.join(REPO_ROOT, 'hooks', 'lib', 'memory-shard.js');
const CLI_PATH = path.join(REPO_ROOT, 'bin', 'ds-memory-shard');
const FIXTURE_PATH = path.join(__dirname, 'fixtures', 'memory-shard-sample.md');
const SCAFFOLD_YML_PATH = path.join(REPO_ROOT, 'content', 'project-scaffolding.yml');

let passed = 0;
let failed = 0;
const tmpDirs = [];

function assert(condition, message) {
  if (condition) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.log(`  FAIL: ${message}`);
    failed++;
  }
}

function mkTmpDir(prefix) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  tmpDirs.push(d);
  return d;
}

function cleanup() {
  for (const d of tmpDirs) {
    try {
      fs.rmSync(d, { recursive: true, force: true });
    } catch (_) {
      /* best-effort */
    }
  }
}

/** Loads hooks/lib/memory-shard.js with `transform` applied to its source,
 * from a TEMP FILE at an absolute path - never touches the real file on
 * disk. Asserts the transform actually changed something (a no-op
 * transform would silently "pass" every mutation test without reddening
 * anything). */
function loadMutatedLib(transform, label) {
  const original = fs.readFileSync(LIB_PATH, 'utf8');
  const mutated = transform(original);
  if (mutated === original) {
    throw new Error(`loadMutatedLib(${label}): transform was a no-op - mutation did not change the source`);
  }
  const dir = mkTmpDir('memory-shard-mutant-');
  const mutantPath = path.join(dir, 'memory-shard.mutant.js');
  fs.writeFileSync(mutantPath, mutated, 'utf8');
  delete require.cache[mutantPath];
  return require(mutantPath);
}

/** Mirrors bin/tests/test_cleanup_worktrees.py's init_repo_with_origin:
 * a bare `origin` plus a repo with one commit on `main`, pushed. Used by
 * cases 5 and 6, which depend on real git state (gitignore behavior,
 * independent clone pushes). This fixture family is history-shallow by
 * construction (one commit before any divergence) - stated explicitly
 * since case 6 depends on the fork point being exactly this. */
function initRepoWithOrigin(base, name) {
  const origin = path.join(base, `${name}-origin.git`);
  execFileSync('git', ['init', '-q', '--bare', '-b', 'main', origin]);
  const repo = path.join(base, name);
  fs.mkdirSync(repo);
  execFileSync('git', ['init', '-q', '-b', 'main'], { cwd: repo });
  execFileSync('git', ['config', 'user.email', 'spec@example.com'], { cwd: repo });
  execFileSync('git', ['config', 'user.name', 'spec'], { cwd: repo });
  fs.writeFileSync(path.join(repo, 'README.md'), 'init\n');
  execFileSync('git', ['add', 'README.md'], { cwd: repo });
  execFileSync('git', ['commit', '-q', '-m', 'init'], { cwd: repo });
  execFileSync('git', ['remote', 'add', 'origin', origin], { cwd: repo });
  execFileSync('git', ['push', '-q', '-u', 'origin', 'main'], { cwd: repo });
  return { repo, origin };
}

/** Runs the real CLI via spawnSync (capturing exit code, stdout, stderr). */
function runCli(args, opts = {}) {
  const res = spawnSync('node', [CLI_PATH, ...args], {
    encoding: 'utf8',
    ...opts,
  });
  return { status: res.status, stdout: res.stdout, stderr: res.stderr };
}

/** Runs a MUTATED copy of bin/ds-memory-shard, from a temp file that
 * reproduces the real `bin/../hooks/lib/memory-shard.js` relative layout
 * (the CLI resolves its lib import via `__dirname`-relative require, so a
 * mutant staged in an arbitrary directory would fail to load the real lib
 * at all) - never touches the real bin/ds-memory-shard on disk. Asserts
 * the transform actually changed something, same discipline as
 * loadMutatedLib. */
function runMutatedCli(transform, label, args, opts = {}) {
  const original = fs.readFileSync(CLI_PATH, 'utf8');
  const mutated = transform(original);
  if (mutated === original) {
    throw new Error(`runMutatedCli(${label}): transform was a no-op - mutation did not change the source`);
  }
  const root = mkTmpDir('memory-shard-cli-mutant-');
  const binDir = path.join(root, 'bin');
  const libDir = path.join(root, 'hooks', 'lib');
  fs.mkdirSync(binDir, { recursive: true });
  fs.mkdirSync(libDir, { recursive: true });
  fs.copyFileSync(LIB_PATH, path.join(libDir, 'memory-shard.js'));
  const mutantCliPath = path.join(binDir, 'ds-memory-shard.mutant.js');
  fs.writeFileSync(mutantCliPath, mutated, 'utf8');
  const res = spawnSync('node', [mutantCliPath, ...args], { encoding: 'utf8', ...opts });
  return { status: res.status, stdout: res.stdout, stderr: res.stderr };
}

function setupSplitFixture() {
  const dir = mkTmpDir('memory-shard-case-');
  const memoryPath = path.join(dir, 'MEMORY.md');
  fs.copyFileSync(FIXTURE_PATH, memoryPath);
  const shardDir = path.join(dir, '.agentic', 'memory-shards');
  fs.mkdirSync(path.dirname(shardDir), { recursive: true });
  return { dir, memoryPath, shardDir };
}

// ---------------------------------------------------------------------------
// Case 1: Round-trip byte-identity
// ---------------------------------------------------------------------------
function case1() {
  console.log('\n[1] Round-trip byte-identity');
  const lib = require(LIB_PATH);
  const { dir, memoryPath, shardDir } = setupSplitFixture();
  const original = fs.readFileSync(memoryPath, 'utf8');

  lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });
  fs.rmSync(memoryPath);
  const result = lib.regenerateCommand({ shardDir, memoryPath, check: false, allowRemoval: false });
  assert(result.wrote === true, 'regenerate wrote MEMORY.md from the fresh shard set');
  const regenerated = fs.readFileSync(memoryPath, 'utf8');
  assert(regenerated === original, 'regenerated file is byte-identical to the original fixture');

  console.log('  Mutation: drop trailing-blank-line capture from the shard body');
  const mutatedLib = loadMutatedLib((src) => {
    const marker = 'const entryLines = lines.slice(start, end);';
    if (!src.includes(marker)) throw new Error('marker not found in source - mutation site moved');
    return src.replace(
      marker,
      marker + "\n  while (entryLines.length > 1 && entryLines[entryLines.length - 1] === '') entryLines.pop();",
    );
  }, 'drop-trailing-blank-lines');
  const { entries } = mutatedLib.splitEntries(original);
  const compiledMutant = mutatedLib.compile(mutatedLib.splitEntries(original).preamble, entries);
  assert(
    compiledMutant !== original,
    'REDDENED: mutant that drops trailing blank lines fails byte-identity (multi-blank-line entry loses whitespace)',
  );
}

// ---------------------------------------------------------------------------
// Regression: preamble-less file (Skeptic Minor fix)
// ---------------------------------------------------------------------------
function caseNoPreamble() {
  console.log('\n[1b] Regression: preamble-less file (splitEntries firstEntryIdx === 0)');
  const lib = require(LIB_PATH);
  const dir = mkTmpDir('memory-shard-no-preamble-');
  const memoryPath = path.join(dir, 'MEMORY.md');
  const noPreambleFixture = path.join(__dirname, 'fixtures', 'memory-shard-sample-no-preamble.md');
  fs.copyFileSync(noPreambleFixture, memoryPath);
  const shardDir = path.join(dir, '.agentic', 'memory-shards');
  fs.mkdirSync(path.dirname(shardDir), { recursive: true });
  const original = fs.readFileSync(memoryPath, 'utf8');

  const { preamble } = lib.splitEntries(original);
  assert(
    preamble === '',
    'splitEntries does NOT fabricate a spurious leading blank line when the file starts at column 0 with "- "',
  );

  lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });
  fs.rmSync(memoryPath);
  lib.regenerateCommand({ shardDir, memoryPath, check: false, allowRemoval: false });
  const regenerated = fs.readFileSync(memoryPath, 'utf8');
  assert(regenerated === original, 'preamble-less file round-trips byte-identical (no fabricated leading newline)');
}

// ---------------------------------------------------------------------------
// Case 2: Entry-loss refusal
// ---------------------------------------------------------------------------
function case2() {
  console.log('\n[2] Entry-loss refusal');
  const lib = require(LIB_PATH);
  const { dir, memoryPath, shardDir } = setupSplitFixture();
  lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });

  // Simulate a shard set that has drifted behind the current MEMORY.md: an
  // entry's shard file is deleted (e.g. an accidental removal, or the
  // inverse of the documented "hand-appended entry not yet captured into a
  // shard" scenario), while MEMORY.md itself - a COPY of the fixture,
  // untouched - still has that entry's line. Compiling the reduced shard
  // set would therefore DROP a line the current file still has, which is
  // exactly the entry-loss guard's trigger condition (see
  // hooks/lib/memory-shard.js regenerateCommand's failure-mode contract).
  const records = lib.readEntryRecords(shardDir);
  const seventhRecord = records.find((r) => r.body.includes('Seventh entry'));
  assert(seventhRecord !== undefined, 'setup: found the shard corresponding to "Seventh entry" in the fixture copy');
  fs.rmSync(path.join(shardDir, seventhRecord.file));
  const beforeAttempt = fs.readFileSync(memoryPath, 'utf8');

  // BUG FIX (Skeptic round-2 Major 1): the assertion here used to be
  // `threw !== null` plus `/REFUSING/.test(threw.message)` - both guards'
  // refusal messages contain the word "REFUSING", so this could not tell
  // apart "the entry-loss guard fired" from "some OTHER guard fired for a
  // different reason". Measured: mutating ONLY the entry-loss guard to
  // `if (false && lost.length > 0)` still passed both assertions, because
  // findPermutedLines' own fail-safe (`if (!arr || arr.length === 0)
  // return true` for a line that no longer exists anywhere in the
  // compiled output) throws the REORDER refusal instead - which also says
  // "REFUSING". The fix asserts on a LOSS-SPECIFIC marker
  // (`describeLostLines`'s own "would be LOST" text), the same
  // discipline case 3 already uses for `/REORDER/`.
  let threw = null;
  try {
    lib.regenerateCommand({ shardDir, memoryPath, check: false, allowRemoval: false });
  } catch (err) {
    threw = err;
  }
  assert(threw !== null, 'regenerate REFUSES (throws) when the current file lost an entry line');
  if (threw !== null) {
    assert(/would be LOST/.test(threw.message), 'refusal message names the LOSS specifically (not just any refusal)');
  }
  const afterAttempt = fs.readFileSync(memoryPath, 'utf8');
  assert(afterAttempt === beforeAttempt, 'nothing was written to MEMORY.md on refusal');

  // Skeptic round-3 Major fix: `cli.status !== 0` was vacuous - it passes
  // for ANY nonzero exit, including a completely broken binary (measured:
  // repointing the CLI's lib require at a nonexistent module makes EVERY
  // invocation exit 1 with a load error, and this assertion alone stayed
  // green). Assert the EXACT exit code (1, the documented refusal code -
  // never 2, the usage-error code a broken require also happens to avoid
  // but a malformed-args path would hit) AND the loss-specific stderr
  // marker, so a broken binary that exits 1 for an unrelated reason is
  // caught by the second assertion.
  const cli = runCli(['regenerate', '--dir', dir]);
  assert(cli.status === 1, 'CLI regenerate exits EXACTLY 1 (the documented refusal code) on entry-loss refusal');
  assert(/would be LOST/.test(cli.stderr), 'CLI stderr names the LOSS specifically (not just any nonzero exit)');

  console.log('  Mutation: repoint the CLI\'s lib require at a nonexistent module (completely broken binary)');
  const brokenCli = runMutatedCli(
    (src) => {
      const marker = "lib = require(path.join(__dirname, '..', 'hooks', 'lib', 'memory-shard.js'));";
      if (!src.includes(marker)) throw new Error('lib-require marker not found - mutation site moved');
      return src.replace(marker, "lib = require(path.join(__dirname, '..', 'hooks', 'lib', 'DOES-NOT-EXIST.js'));");
    },
    'broken-lib-require',
    ['regenerate', '--dir', dir],
  );
  assert(brokenCli.status === 1, 'setup: the completely-broken binary also exits 1 (same code as a real refusal - this is exactly why exit-code-alone cannot discriminate)');
  assert(
    !/would be LOST/.test(brokenCli.stderr || ''),
    'REDDENED: the broken binary\'s stderr does NOT contain the loss-specific marker (it is a module-load error, not a refusal) - proving the marker, not the exit code, is what the fixed assertion actually verifies',
  );

  // Skeptic round-2 Major 1 (independent-guard verification): mutate ONLY
  // the entry-loss guard, leaving the reordering guard fully intact, and
  // confirm the loss-specific assertion above is what actually catches
  // it - not merely "some refusal happened". With the loss guard
  // disabled, regenerateCommand still throws (the reordering guard's own
  // fail-safe catches the now-vanished line), so a bare "did it throw"
  // check stays green; the loss-specific marker must NOT appear in that
  // thrown message, proving the marker - not the mutation - is what
  // discriminates which guard actually fired.
  console.log('  Mutation: disable ONLY the entry-loss guard (reordering guard stays active)');
  const lossGuardOnlyLib = loadMutatedLib((src) => {
    const marker = 'if (lost.length > 0) {';
    if (!src.includes(marker)) throw new Error('entry-loss guard marker not found - mutation site moved');
    return src.replace(marker, 'if (false && lost.length > 0) { // MUTANT: entry-loss guard disabled');
  }, 'disable-entry-loss-guard-only');
  let lossGuardMutantThrew = null;
  try {
    lossGuardOnlyLib.regenerateCommand({ shardDir, memoryPath, check: false, allowRemoval: false });
  } catch (err) {
    lossGuardMutantThrew = err;
  }
  assert(
    lossGuardMutantThrew !== null,
    'with the entry-loss guard disabled, regenerate STILL throws (via the reordering guard\'s own fail-safe on the vanished line) - so a bare "did it throw" check cannot discriminate',
  );
  if (lossGuardMutantThrew !== null) {
    assert(
      !/would be LOST/.test(lossGuardMutantThrew.message),
      'REDDENED: with the entry-loss guard disabled, the thrown message does NOT contain the loss-specific marker - proving the marker (not "any refusal") is what actually verifies this guard',
    );
  }

  console.log('  Mutation: replace the multiset check with substring containment');
  const mutatedLib = loadMutatedLib((src) => {
    const marker = 'function findLostLines(currentText, compiledText) {';
    if (!src.includes(marker)) throw new Error('marker not found - mutation site moved');
    const idx = src.indexOf(marker);
    const closeIdx = src.indexOf('\n}\n', idx);
    if (closeIdx === -1) throw new Error('could not locate end of findLostLines');
    const replacement =
      'function findLostLines(currentText, compiledText) {\n' +
      '  // MUTANT: substring containment instead of multiset comparison.\n' +
      '  const lost = [];\n' +
      '  for (const l of extractLines(currentText)) {\n' +
      "    if (l === '' || compiledText.includes(l)) continue;\n" +
      '    lost.push(l);\n' +
      '  }\n' +
      '  return lost;\n' +
      '}\n';
    return src.slice(0, idx) + replacement + src.slice(closeIdx + 3);
  }, 'substring-containment');

  // Reordered/partial content case: a line that exists ELSEWHERE in the
  // compiled text (so substring containment finds it) but is genuinely a
  // DIFFERENT occurrence than the one that was lost - construct a
  // currentText with a duplicated line where one copy is removed from the
  // compiled side. Substring/set-membership containment cannot tell the
  // two apart; multiset counting can.
  const compiledForMutant = mutatedLib.compileFromDir(shardDir);
  const dup = 'DUPLICATE_MARKER_LINE';
  const currentWithTwoCopies = compiledForMutant.replace('\n', `\n${dup}\n${dup}\n`);
  const compiledWithOneCopyLost = compiledForMutant.replace('\n', `\n${dup}\n`);
  const mutantLost = mutatedLib.findLostLines(currentWithTwoCopies, compiledWithOneCopyLost);
  assert(
    mutantLost.length === 0,
    'REDDENED: substring-containment mutant fails to detect a lost duplicate-line occurrence (real multiset check would flag it)',
  );
  const realLost = lib.findLostLines(currentWithTwoCopies, compiledWithOneCopyLost);
  assert(
    realLost.includes(dup),
    'control: the REAL multiset-based findLostLines correctly flags the lost duplicate occurrence',
  );
}

// ---------------------------------------------------------------------------
// Case 3: Reorder refusal
// ---------------------------------------------------------------------------
function case3() {
  console.log('\n[3] Reorder refusal');
  const lib = require(LIB_PATH);
  const { dir, memoryPath, shardDir } = setupSplitFixture();
  lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });

  const records = lib.readEntryRecords(shardDir);
  const sorted = [...records].sort((a, b) => a.sequence - b.sequence);
  assert(sorted.length >= 2, 'setup: at least two shards exist to swap');
  const a = sorted[0];
  const b = sorted[1];

  // Swap two ADJACENT shards' sequence values - zero content loss, pure
  // reorder.
  const aText = fs.readFileSync(path.join(shardDir, a.file), 'utf8');
  const bText = fs.readFileSync(path.join(shardDir, b.file), 'utf8');
  const aSwapped = aText.replace(`sequence: ${a.sequence}`, `sequence: ${b.sequence}`);
  const bSwapped = bText.replace(`sequence: ${b.sequence}`, `sequence: ${a.sequence}`);
  fs.writeFileSync(path.join(shardDir, a.file), aSwapped);
  fs.writeFileSync(path.join(shardDir, b.file), bSwapped);

  const beforeAttempt = fs.readFileSync(memoryPath, 'utf8');
  let threw = null;
  try {
    lib.regenerateCommand({ shardDir, memoryPath, check: false, allowRemoval: false });
  } catch (err) {
    threw = err;
  }
  assert(threw !== null, 'regenerate REFUSES when two shards\' sequences are swapped (zero loss, pure reorder)');
  // Skeptic Minor fix: `threw.message` used to be dereferenced unguarded
  // right after the `threw !== null` assertion - a FAILED assertion here
  // (threw === null) would then throw a TypeError reading `.message` off
  // null, aborting the whole run and SILENTLY SKIPPING every later case.
  // Guard the dereference so a genuine failure here is reported as a
  // normal FAIL line, not a silent skip of the rest of the suite.
  if (threw !== null) {
    assert(/REORDER/.test(threw.message), 'refusal message names the reordering');
  }
  const afterAttempt = fs.readFileSync(memoryPath, 'utf8');
  assert(afterAttempt === beforeAttempt, 'nothing was written to MEMORY.md on reorder refusal');

  console.log('  Mutation: remove the permutation detector entirely');
  const mutatedLib = loadMutatedLib((src) => {
    const marker = 'if (findPermutedLines(current, compiled)) {';
    if (!src.includes(marker)) throw new Error('marker not found - mutation site moved');
    // Neutralize the call so it never fires (findPermutedLines never
    // consulted by regenerateCommand).
    return src.replace(marker, 'if (false && findPermutedLines(current, compiled)) {');
  }, 'remove-permutation-detector');

  let mutantThrew = null;
  try {
    mutatedLib.regenerateCommand({ shardDir, memoryPath, check: false, allowRemoval: false });
  } catch (err) {
    mutantThrew = err;
  }
  assert(
    mutantThrew === null,
    'REDDENED: mutant with the permutation detector disabled no longer refuses the swapped-sequence case (silently writes)',
  );
}

// ---------------------------------------------------------------------------
// Case 4: Gap-spacing collision
// ---------------------------------------------------------------------------
function case4() {
  console.log('\n[4] Gap-spacing collision');
  const lib = require(LIB_PATH);
  const { dir, memoryPath, shardDir } = setupSplitFixture();
  lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });

  const records = lib.readEntryRecords(shardDir);
  const sorted = [...records].sort((a, b) => a.sequence - b.sequence);
  const left = sorted[0].sequence;
  const right = sorted[1].sequence;

  // Insert TWO new shards into the SAME gap between adjacent originals.
  const values = lib.fillSequenceRun(left, right, 2);
  assert(values.length === 2, 'fillSequenceRun produced two values');
  assert(values[0] !== values[1], 'the two new sequence values are DISTINCT, not colliding');
  assert(
    values.every((v) => v > left && v < right),
    'both new values fall strictly inside the gap',
  );

  console.log('  Mutation: off-by-one midpoint arithmetic so both get the same integer');
  const mutatedLib = loadMutatedLib((src) => {
    // Only the bisection branch's VALUE GENERATION is mutated (never the
    // `step < 1` exhaustion guard, which must still see the correctly
    // computed step so it does not spuriously fire) - every requested slot
    // collapses to the same fixed midpoint instead of advancing by `step`
    // per k, an off-by-one bug in the array-building formula.
    const marker = 'return Array.from({ length: count }, (_, k) => leftBound + (k + 1) * step);';
    if (!src.includes(marker)) throw new Error('marker not found - mutation site moved');
    return src.replace(
      marker,
      'return Array.from({ length: count }, () => leftBound + step); // MUTANT: drops the (k + 1) factor, collapsing every value to the same integer',
    );
  }, 'off-by-one-midpoint');

  // Force the small-span (bisection) branch to fire by using a tight gap
  // that still satisfies span <= count*SEQUENCE_GAP. Measured: the "real"
  // assertions above (left=1000, right=2000, count=2 - two originally-
  // adjacent split-time shards) ALSO land in this same bisection branch
  // (span=1000 is not > count*SEQUENCE_GAP=2000), so this mutation and the
  // real-code assertions already exercise the identical branch.
  const tightLeft = 0;
  const tightRight = 3; // span=3, count=2 -> falls to bisection branch (3 <= 2*1000)
  const mutantValues = mutatedLib.fillSequenceRun(tightLeft, tightRight, 2);
  assert(
    mutantValues[0] === mutantValues[1],
    'REDDENED: mutant produces a SEQUENCE COLLISION (both new shards get the same integer)',
  );

  // Skeptic Minor fix: the wide-gap branch (span > count*SEQUENCE_GAP,
  // taken when new shards are being inserted into a gap wide enough to
  // give each a full SEQUENCE_GAP-sized slot) had ZERO test coverage
  // above - neither the real assertions nor the bisection mutation touch
  // it. Exercised directly here, with its own dedicated mutation.
  console.log('  Wide-gap branch (span > count*SEQUENCE_GAP): real values plus its own off-by-one mutation');
  const wideLeft = 0;
  const wideRight = 10000; // span=10000, count=2 -> wide branch (10000 > 2*1000)
  const wideValues = lib.fillSequenceRun(wideLeft, wideRight, 2);
  assert(wideValues.length === 2, 'wide-gap branch: fillSequenceRun produced two values');
  assert(wideValues[0] !== wideValues[1], 'wide-gap branch: the two values are DISTINCT');
  assert(
    wideValues.every((v) => v > wideLeft && v < wideRight),
    'wide-gap branch: both values fall strictly inside the gap',
  );

  const wideMutatedLib = loadMutatedLib((src) => {
    // Drops the "(count - k)" factor from the wide-gap branch's formula,
    // collapsing every requested slot to the same fixed offset from
    // rightBound regardless of k - the wide-branch analogue of the
    // bisection mutation above.
    const marker = 'return Array.from({ length: count }, (_, k) => rightBound - (count - k) * SEQUENCE_GAP);';
    if (!src.includes(marker)) throw new Error('wide-gap marker not found - mutation site moved');
    return src.replace(
      marker,
      'return Array.from({ length: count }, () => rightBound - SEQUENCE_GAP); // MUTANT: drops the (count - k) factor, collapsing every value to the same integer',
    );
  }, 'wide-gap-off-by-one');
  const wideMutantValues = wideMutatedLib.fillSequenceRun(wideLeft, wideRight, 2);
  assert(
    wideMutantValues[0] === wideMutantValues[1],
    'REDDENED: wide-gap mutant produces a SEQUENCE COLLISION (both new shards get the same integer)',
  );
}

// ---------------------------------------------------------------------------
// Case 5: Gitignore carve-out
// ---------------------------------------------------------------------------
function extractGitignorePatterns() {
  const text = fs.readFileSync(SCAFFOLD_YML_PATH, 'utf8');
  const patterns = [];
  const lines = text.split('\n');
  let inGitignore = false;
  for (const line of lines) {
    if (/^gitignore:\s*$/.test(line)) {
      inGitignore = true;
      continue;
    }
    if (inGitignore) {
      if (/^\S/.test(line)) break; // dedented out of the gitignore: list
      const m = line.match(/^\s*-\s*pattern:\s*"([^"]*)"/);
      if (m) patterns.push(m[1]);
    }
  }
  return patterns;
}

function case5() {
  console.log('\n[5] Gitignore carve-out');
  const patterns = extractGitignorePatterns();
  assert(
    patterns.includes('!.agentic/memory-shards/'),
    'content/project-scaffolding.yml declares !.agentic/memory-shards/ negation',
  );
  assert(
    patterns.includes('!.agentic/memory-shards/**'),
    'content/project-scaffolding.yml declares !.agentic/memory-shards/** negation',
  );

  const base = mkTmpDir('memory-shard-gitignore-');
  const repo = path.join(base, 'repo');
  fs.mkdirSync(repo);
  execFileSync('git', ['init', '-q', '-b', 'main'], { cwd: repo });
  const gitignoreBody = patterns.join('\n') + '\n';
  fs.writeFileSync(path.join(repo, '.gitignore'), gitignoreBody);

  const shardFileRel = path.join('.agentic', 'memory-shards', '2026-01-01-example.md');
  fs.mkdirSync(path.dirname(path.join(repo, shardFileRel)), { recursive: true });
  fs.writeFileSync(path.join(repo, shardFileRel), 'placeholder\n');

  const checkIgnore = require('child_process').spawnSync('git', ['check-ignore', '-q', shardFileRel], {
    cwd: repo,
  });
  assert(
    checkIgnore.status === 1,
    'git check-ignore -q exits 1 (NOT ignored) for a shard path under the real scaffolding gitignore',
  );

  // Measured against this repo's actual umbrella shape (`.agentic/*`, a
  // one-level GLOB - not the bare/recursive `.agentic/` form the
  // AGENTS.md git lessons warn cannot be pierced at all): deleting ONLY
  // the `**` line and keeping the bare directory negation does NOT flip
  // the exit code on git 2.55.0 - `.agentic/*` matching the directory
  // ENTRY itself, once negated by `!.agentic/memory-shards/`, stops
  // excluding everything under it with no further pattern needed (the
  // same redundancy MEMORY.md's `!.agentic/session-log/**` note already
  // documents for this repo's identical two-line convention). Verified
  // directly before writing this assertion - do not restore the
  // brief's originally-suggested "delete only **" mutation without
  // re-measuring, since it is not load-bearing under this umbrella shape.
  // The genuinely load-bearing line is the BARE DIRECTORY negation -
  // deleting THAT one (keeping `**`) is what actually reddens, since
  // `.agentic/*` still excludes the directory ENTRY itself and nothing
  // negates that entry-level exclusion for git to recurse past.
  console.log('  Mutation: delete ONLY the bare directory negation, keep the ** negation');
  const mutatedPatterns = patterns.filter((p) => p !== '!.agentic/memory-shards/');
  fs.writeFileSync(path.join(repo, '.gitignore'), mutatedPatterns.join('\n') + '\n');
  const checkIgnoreMutant = require('child_process').spawnSync('git', ['check-ignore', '-q', shardFileRel], {
    cwd: repo,
  });
  assert(
    checkIgnoreMutant.status === 0,
    'REDDENED: with only the bare directory negation removed, git check-ignore -q exits 0 (IS ignored again) - the carve-out is broken',
  );

  // Restore the real gitignore for good measure (throwaway repo, but keep
  // the test's post-condition honest).
  fs.writeFileSync(path.join(repo, '.gitignore'), gitignoreBody);
}

// ---------------------------------------------------------------------------
// Case 6: Concurrency demonstration
// ---------------------------------------------------------------------------
function case6() {
  console.log('\n[6] Concurrency demonstration (the actual claim)');
  const base = mkTmpDir('memory-shard-concurrency-');
  const { origin } = initRepoWithOrigin(base, 'concurrency-repo');

  // Seed origin/main with an initial MEMORY.md + split shard set, pushed.
  const seedDir = path.join(base, 'seed');
  execFileSync('git', ['clone', '-q', origin, seedDir]);
  execFileSync('git', ['config', 'user.email', 'spec@example.com'], { cwd: seedDir });
  execFileSync('git', ['config', 'user.name', 'spec'], { cwd: seedDir });
  fs.copyFileSync(FIXTURE_PATH, path.join(seedDir, 'MEMORY.md'));
  const lib = require(LIB_PATH);
  lib.splitCommand({
    shardDir: path.join(seedDir, '.agentic', 'memory-shards'),
    memoryPath: path.join(seedDir, 'MEMORY.md'),
    force: false,
    allowRemoval: false,
  });
  execFileSync('git', ['add', '-f', 'MEMORY.md', '.agentic/memory-shards'], { cwd: seedDir });
  execFileSync('git', ['commit', '-q', '-m', 'seed shard corpus'], { cwd: seedDir });
  execFileSync('git', ['push', '-q', 'origin', 'main'], { cwd: seedDir });

  // Two independent clones (A, B), each adding ONE new shard.
  const cloneA = path.join(base, 'clone-a');
  const cloneB = path.join(base, 'clone-b');
  execFileSync('git', ['clone', '-q', origin, cloneA]);
  execFileSync('git', ['clone', '-q', origin, cloneB]);
  for (const c of [cloneA, cloneB]) {
    execFileSync('git', ['config', 'user.email', 'spec@example.com'], { cwd: c });
    execFileSync('git', ['config', 'user.name', 'spec'], { cwd: c });
  }

  function addShard(clonePath, name, sequence, factText) {
    const shardDir = path.join(clonePath, '.agentic', 'memory-shards');
    const filename = `2026-02-01-${name}.md`;
    const body = `- **2026-02-01: ${factText}**\n`;
    const text = lib.buildFrontmatter({ name, description: factText, type: 'project', sequence }) + body;
    fs.writeFileSync(path.join(shardDir, filename), text, 'utf8');
    return filename;
  }

  // Pick sequences that fall in the same gap on each side, independently -
  // this is the whole point: two worktrees adding two uniquely-named files
  // at DIFFERENT paths can never conflict in git, regardless of how their
  // sequence values relate.
  const shardFileA = addShard(cloneA, 'fact-from-clone-a', 999000, 'Fact added by clone A.');
  execFileSync('git', ['add', '-f', `.agentic/memory-shards/${shardFileA}`], { cwd: cloneA });
  execFileSync('git', ['commit', '-q', '-m', 'clone A adds a fact'], { cwd: cloneA });
  execFileSync('git', ['push', '-q', 'origin', 'main'], { cwd: cloneA });

  const shardFileB = addShard(cloneB, 'fact-from-clone-b', 999500, 'Fact added by clone B.');
  execFileSync('git', ['add', '-f', `.agentic/memory-shards/${shardFileB}`], { cwd: cloneB });
  execFileSync('git', ['commit', '-q', '-m', 'clone B adds a fact'], { cwd: cloneB });

  // B pushes SECOND, after A - must pull/rebase or merge to reconcile,
  // but the merge itself must be CLEAN (two adds at different paths).
  let pushBFailed = false;
  try {
    execFileSync('git', ['push', '-q', 'origin', 'main'], { cwd: cloneB });
  } catch (_) {
    pushBFailed = true;
  }
  if (pushBFailed) {
    execFileSync('git', ['-c', 'pull.rebase=false', 'pull', '-q', '--no-edit', 'origin', 'main'], { cwd: cloneB });
    execFileSync('git', ['push', '-q', 'origin', 'main'], { cwd: cloneB });
  }

  // Fresh clone C, pull both facts, run regenerate --check.
  const cloneC = path.join(base, 'clone-c');
  execFileSync('git', ['clone', '-q', origin, cloneC]);
  const compiled = lib.compileFromDir(path.join(cloneC, '.agentic', 'memory-shards'));
  assert(compiled.includes('Fact added by clone A.'), 'clone A\'s independently-added fact is present after the merge');
  assert(compiled.includes('Fact added by clone B.'), 'clone B\'s independently-added fact is present after the merge');

  let checkResult = null;
  let checkErr = null;
  try {
    checkResult = lib.regenerateCommand({
      shardDir: path.join(cloneC, '.agentic', 'memory-shards'),
      memoryPath: path.join(cloneC, 'MEMORY.md'),
      check: true,
      allowRemoval: false,
    });
  } catch (err) {
    checkErr = err;
  }
  // A clean merge landed two ADDED shards that MEMORY.md itself was never
  // regenerated to include yet - `regenerate --check` against the stale
  // MEMORY.md is therefore EXPECTED to report a mismatch (not a refusal:
  // both new lines are pure additions, never a loss/reorder). The load-
  // bearing assertion is that this path is reachable AT ALL (no merge
  // conflict blocked it) and that both facts are visible to compileFromDir.
  assert(
    checkErr !== null && /does NOT match/.test(checkErr.message),
    'regenerate --check reports the (additive) mismatch cleanly - no merge conflict ever blocked reaching this point',
  );

  console.log(
    '  Mutation: A and B each do a full-file prose rewrite of the same compiled region instead of adding a shard',
  );
  const cloneA2 = path.join(base, 'clone-a2');
  const cloneB2 = path.join(base, 'clone-b2');
  execFileSync('git', ['clone', '-q', origin, cloneA2]);
  execFileSync('git', ['clone', '-q', origin, cloneB2]);
  for (const c of [cloneA2, cloneB2]) {
    execFileSync('git', ['config', 'user.email', 'spec@example.com'], { cwd: c });
    execFileSync('git', ['config', 'user.name', 'spec'], { cwd: c });
  }
  // Both rewrite the SAME first shard file's body (the pre-shard failure
  // mode this design fixes: two concurrent full-file MEMORY.md rewrites).
  const records = lib.readEntryRecords(path.join(cloneA2, '.agentic', 'memory-shards'));
  const targetFile = [...records].sort((a, b) => a.sequence - b.sequence)[0].file;
  const targetPathA = path.join(cloneA2, '.agentic', 'memory-shards', targetFile);
  const targetPathB = path.join(cloneB2, '.agentic', 'memory-shards', targetFile);
  const origBody = fs.readFileSync(targetPathA, 'utf8');
  fs.writeFileSync(targetPathA, origBody.replace(/- \*\*.*$/m, '- **REWRITTEN BY CLONE A - conflicting edit**'));
  fs.writeFileSync(targetPathB, origBody.replace(/- \*\*.*$/m, '- **REWRITTEN BY CLONE B - conflicting edit**'));
  execFileSync('git', ['add', '-f', `.agentic/memory-shards/${targetFile}`], { cwd: cloneA2 });
  execFileSync('git', ['commit', '-q', '-m', 'clone A rewrites the shard'], { cwd: cloneA2 });
  execFileSync('git', ['push', '-q', 'origin', 'main'], { cwd: cloneA2 });

  execFileSync('git', ['add', '-f', `.agentic/memory-shards/${targetFile}`], { cwd: cloneB2 });
  execFileSync('git', ['commit', '-q', '-m', 'clone B rewrites the shard'], { cwd: cloneB2 });
  let mutantPushFailed = false;
  try {
    execFileSync('git', ['push', '-q', 'origin', 'main'], { cwd: cloneB2 });
  } catch (_) {
    mutantPushFailed = true;
  }
  assert(mutantPushFailed, 'setup: clone B\'s push of a same-file rewrite is rejected (non-fast-forward), as expected');

  // BUG FIX (Skeptic Major 2): the prior version was
  // `(err.stderr || err.stdout || '').toString().includes('CONFLICT') ||
  // err.status !== 0` - the `||` short-circuited on truthy stderr (git
  // prints CONFLICT to STDOUT, not stderr) and the trailing
  // `|| err.status !== 0` then made the assertion pass on ANY nonzero
  // exit for ANY reason, not specifically a merge conflict. Measured:
  // status=1, stdout has CONFLICT=true, stderr has CONFLICT=false. Both
  // streams must be joined and searched together, and the assertion must
  // rest on the CONFLICT marker alone - never on exit status as a proxy.
  let mergeConflicted = false;
  try {
    execFileSync('git', ['-c', 'pull.rebase=false', 'pull', '-q', '--no-edit', 'origin', 'main'], { cwd: cloneB2 });
  } catch (err) {
    const combined = [err.stdout, err.stderr]
      .map((s) => (s ? s.toString() : ''))
      .join('');
    mergeConflicted = combined.includes('CONFLICT');
  }
  assert(
    mergeConflicted,
    'REDDENED: two clones rewriting the SAME compiled region (same shard file) produce a real git merge CONFLICT, ' +
      'reproducing the exact defect the per-fact shard design fixes',
  );
}

// ---------------------------------------------------------------------------
// CLI coverage (Skeptic round-3 Major): a real success path plus every
// arg-parsing rejection this binary implements, each independently verified
// by mutation. Before this, the ONLY assertion executing bin/ds-memory-shard
// at all was the (fixed, above) entry-loss refusal check - unknown-flag
// rejection (round 1), inapplicable-flag rejection (round 2), and the
// --dir-missing-operand rejection (round 3) all shipped completely untested.
// ---------------------------------------------------------------------------
function caseCliSuccessPath() {
  console.log('\n[CLI-1] Success path: CLI split actually writes shards, CLI regenerate --check round-trips');
  const { dir, memoryPath, shardDir } = setupSplitFixture();

  const splitRes = runCli(['split', '--dir', dir]);
  assert(splitRes.status === 0, 'CLI split exits 0 on a fresh MEMORY.md');
  const shardFiles = fs.existsSync(shardDir) ? fs.readdirSync(shardDir) : [];
  assert(shardFiles.includes('_preamble.md'), 'CLI split actually wrote _preamble.md to disk (not just claimed success)');
  const entryShardCount = shardFiles.filter((f) => f !== '_preamble.md').length;
  assert(entryShardCount === 15, `CLI split actually wrote all 15 entry shards to disk (found ${entryShardCount})`);

  const regenCheckRes = runCli(['regenerate', '--dir', dir, '--check']);
  assert(regenCheckRes.status === 0, 'CLI regenerate --check exits 0 - the CLI-created shard set round-trips against MEMORY.md');

  console.log('  Mutation: stub the CLI\'s split branch to report success without calling splitCommand at all');
  const { dir: dir2 } = setupSplitFixture();
  const shardDir2 = path.join(dir2, '.agentic', 'memory-shards');
  const stubbed = runMutatedCli(
    (src) => {
      const marker = "if (cmd === 'split') {\n      const result = lib.splitCommand({ shardDir, memoryPath, force, allowRemoval });";
      if (!src.includes(marker)) throw new Error('split-branch marker not found - mutation site moved');
      return src.replace(
        marker,
        "if (cmd === 'split') {\n      process.stdout.write('split: FAKED SUCCESS\\n'); process.exit(0); return;\n      const result = lib.splitCommand({ shardDir, memoryPath, force, allowRemoval });",
      );
    },
    'stub-split-fake-success',
    ['split', '--dir', dir2],
  );
  assert(stubbed.status === 0, 'setup: the stubbed binary also exits 0 (same code as real success - this is why exit-code-alone cannot discriminate)');
  const shardFiles2 = fs.existsSync(shardDir2) ? fs.readdirSync(shardDir2) : [];
  assert(
    shardFiles2.length === 0,
    'REDDENED: the stubbed binary exits 0 but wrote ZERO shard files to disk - proving the file-count assertion above (not exit code) is what verifies a real success',
  );
}

function caseCliArgParsing() {
  console.log('\n[CLI-2] Arg-parsing rejections, each independently mutation-verified');

  // --- unknown flag -------------------------------------------------------
  const { dir: dirA } = setupSplitFixture();
  const unknownFlagRes = runCli(['split', '--dir', dirA, '--forse']);
  assert(unknownFlagRes.status === 2, 'unknown flag (--forse) exits 2');
  assert(/unrecognized argument/.test(unknownFlagRes.stderr), 'unknown-flag stderr names it as unrecognized');
  const shardDirA = path.join(dirA, '.agentic', 'memory-shards');
  assert(!fs.existsSync(shardDirA), 'unknown flag did NOT perform a real split (no shard dir created)');

  console.log('  Mutation: disable the unknown-flag guard');
  const unknownFlagMutant = runMutatedCli(
    (src) => {
      const marker = "if (unknown.length > 0) {";
      if (!src.includes(marker)) throw new Error('unknown-flag guard marker not found - mutation site moved');
      return src.replace(marker, "if (false && unknown.length > 0) {");
    },
    'disable-unknown-flag-guard',
    ['split', '--dir', dirA, '--forse'],
  );
  assert(
    unknownFlagMutant.status === 0,
    'REDDENED: with the guard disabled, "split --forse" now silently exits 0 (ran a non-forced split instead of rejecting the typo)',
  );

  // --- inapplicable flag: split --check -----------------------------------
  const { dir: dirB } = setupSplitFixture();
  const splitCheckRes = runCli(['split', '--dir', dirB, '--check']);
  assert(splitCheckRes.status === 2, '"split --check" (recognized but inapplicable flag) exits 2');
  assert(/--check does not apply to split/.test(splitCheckRes.stderr), 'stderr names --check as inapplicable to split');
  const shardDirB = path.join(dirB, '.agentic', 'memory-shards');
  assert(!fs.existsSync(shardDirB), '"split --check" did NOT perform a real write');

  console.log('  Mutation: disable the split/--check inapplicable-flag guard');
  const splitCheckMutant = runMutatedCli(
    (src) => {
      const marker = "if (cmd === 'split' && check) {";
      if (!src.includes(marker)) throw new Error('split/--check guard marker not found - mutation site moved');
      return src.replace(marker, "if (false && cmd === 'split' && check) {");
    },
    'disable-split-check-guard',
    ['split', '--dir', dirB, '--check'],
  );
  assert(splitCheckMutant.status === 0, 'setup: with the guard disabled, "split --check" now exits 0');
  const shardDirB2 = path.join(dirB, '.agentic', 'memory-shards');
  assert(
    fs.existsSync(shardDirB2),
    'REDDENED: with the guard disabled, "split --check" silently performed a REAL WRITE (shard dir now exists) - exactly the bug the guard exists to prevent',
  );

  // --- inapplicable flag: regenerate --force ------------------------------
  const { dir: dirC, memoryPath: memoryPathC, shardDir: shardDirC } = setupSplitFixture();
  const lib = require(LIB_PATH);
  lib.splitCommand({ shardDir: shardDirC, memoryPath: memoryPathC, force: false, allowRemoval: false });
  const regenForceRes = runCli(['regenerate', '--dir', dirC, '--force']);
  assert(regenForceRes.status === 2, '"regenerate --force" (recognized but inapplicable flag) exits 2');
  assert(/--force does not apply to regenerate/.test(regenForceRes.stderr), 'stderr names --force as inapplicable to regenerate');

  console.log('  Mutation: disable the regenerate/--force inapplicable-flag guard');
  const regenForceMutant = runMutatedCli(
    (src) => {
      const marker = "if (cmd === 'regenerate' && force) {";
      if (!src.includes(marker)) throw new Error('regenerate/--force guard marker not found - mutation site moved');
      return src.replace(marker, "if (false && cmd === 'regenerate' && force) {");
    },
    'disable-regenerate-force-guard',
    ['regenerate', '--dir', dirC, '--force'],
  );
  assert(
    regenForceMutant.status === 0,
    'REDDENED: with the guard disabled, "regenerate --force" now silently exits 0 instead of rejecting the inapplicable flag',
  );

  // --- unknown subcommand --------------------------------------------------
  const { dir: dirD } = setupSplitFixture();
  const unknownCmdRes = runCli(['bogus-subcommand', '--dir', dirD]);
  assert(unknownCmdRes.status === 2, 'an unknown subcommand exits 2');

  console.log('  Mutation: disable the unknown-subcommand guard');
  const unknownCmdMutant = runMutatedCli(
    (src) => {
      const marker = "if (cmd !== 'split' && cmd !== 'regenerate') {";
      if (!src.includes(marker)) throw new Error('unknown-subcommand guard marker not found - mutation site moved');
      return src.replace(marker, "if (false && cmd !== 'split' && cmd !== 'regenerate') {");
    },
    'disable-unknown-subcommand-guard',
    ['bogus-subcommand', '--dir', dirD],
  );
  // With the guard disabled, cmd falls through to the try block where
  // `cmd === 'split'` is false and `cmd === 'regenerate'` is also false, so
  // it drops into the regenerate branch's lib.regenerateCommand() call
  // (the final `else` in this binary's shape) - REGARDLESS of the exact
  // downstream behavior, the point is it no longer exits 2 for an unknown
  // subcommand.
  assert(
    unknownCmdMutant.status !== 2,
    'REDDENED: with the guard disabled, an unknown subcommand no longer exits 2 (usage rejection lost)',
  );

  // --- --dir with a missing operand ----------------------------------------
  // A real MEMORY.md must exist in the fallback cwd, or splitCommand fails
  // on its own initial read before ever reaching the write path the guard
  // is meant to prevent - that would make the mutation assertion below
  // vacuous for an unrelated reason (ENOENT, not "guard absent").
  const dirlessRoot = mkTmpDir('memory-shard-dirless-cwd-');
  fs.copyFileSync(FIXTURE_PATH, path.join(dirlessRoot, 'MEMORY.md'));
  const dirMissingRes = spawnSync('node', [CLI_PATH, 'split', '--dir'], { encoding: 'utf8', cwd: dirlessRoot });
  assert(dirMissingRes.status === 2, '"split --dir" with no operand exits 2');
  assert(/requires a path operand/.test(dirMissingRes.stderr || ''), 'stderr names the missing --dir operand');
  assert(!fs.existsSync(path.join(dirlessRoot, '.agentic')), '"split --dir" with no operand did NOT write into cwd');

  console.log('  Mutation: disable the --dir-missing-operand guard');
  const dirMissingMutant = runMutatedCli(
    (src) => {
      const marker = 'if (dirMissingOperand) {';
      if (!src.includes(marker)) throw new Error('--dir-missing-operand guard marker not found - mutation site moved');
      return src.replace(marker, 'if (false && dirMissingOperand) {');
    },
    'disable-dir-missing-operand-guard',
    ['split', '--dir'],
    { cwd: dirlessRoot },
  );
  assert(
    dirMissingMutant.status === 0 && fs.existsSync(path.join(dirlessRoot, '.agentic', 'memory-shards')),
    'REDDENED: with the guard disabled, "split --dir" (no operand) silently falls back to cwd and performs a REAL WRITE there',
  );
}

// ---------------------------------------------------------------------------
// writeFileAtomic: proves the "stage-then-rename, never a direct write"
// manifest guarantee via an fs.renameSync spy, rather than trusting the
// docstring's own claim.
// ---------------------------------------------------------------------------
function caseWriteFileAtomicIsReallyAtomic() {
  console.log('\n[writeFileAtomic] "stage-then-rename, never a direct write" guarantee');
  const lib = require(LIB_PATH);
  const dir = mkTmpDir('memory-shard-atomic-');
  const target = path.join(dir, 'MEMORY.md');

  const realRename = fs.renameSync;
  const calls = [];
  fs.renameSync = (...args) => {
    calls.push(args);
    return realRename(...args);
  };
  try {
    lib.writeFileAtomic(target, 'hello world\n');
  } finally {
    fs.renameSync = realRename;
  }
  assert(calls.length === 1, 'writeFileAtomic calls fs.renameSync EXACTLY once (stage-then-rename)');
  if (calls.length === 1) {
    assert(calls[0][1] === target, 'the rename call\'s destination is the real target path');
    assert(calls[0][0] !== target && calls[0][0].startsWith(target), 'the rename call\'s source is a sibling tmp path distinct from the target');
  }
  assert(fs.readFileSync(target, 'utf8') === 'hello world\n', 'final content is correct after the real atomic write');

  console.log('  Mutation: replace writeFileAtomic with a direct fs.writeFileSync (no stage-then-rename)');
  const mutatedLib = loadMutatedLib((src) => {
    const marker = "function writeFileAtomic(targetPath, content) {";
    if (!src.includes(marker)) throw new Error('writeFileAtomic marker not found - mutation site moved');
    const idx = src.indexOf(marker);
    const closeIdx = src.indexOf('\n}\n', idx);
    if (closeIdx === -1) throw new Error('could not locate end of writeFileAtomic');
    const replacement =
      'function writeFileAtomic(targetPath, content) {\n' +
      '  // MUTANT: direct write, no staging, no rename.\n' +
      "  fs.writeFileSync(targetPath, content, 'utf8');\n" +
      '}\n';
    return src.slice(0, idx) + replacement + src.slice(closeIdx + 3);
  }, 'direct-write-not-atomic');

  const target2 = path.join(dir, 'MEMORY2.md');
  const calls2 = [];
  const realRename2 = fs.renameSync;
  fs.renameSync = (...args) => {
    calls2.push(args);
    return realRename2(...args);
  };
  try {
    mutatedLib.writeFileAtomic(target2, 'hello2\n');
  } finally {
    fs.renameSync = realRename2;
  }
  assert(
    calls2.length === 0,
    'REDDENED: the direct-write mutant never calls fs.renameSync at all (no stage-then-rename, violating the manifest\'s "never a direct write" guarantee)',
  );
}

// ---------------------------------------------------------------------------
// Manifest-guarantee coverage (Skeptic round-3 Minor): six documented
// refusals/verifications with previously zero test coverage, each with an
// independently-run reddening mutation.
// ---------------------------------------------------------------------------
function caseResplitRefusal() {
  console.log('\n[Manifest] Re-split refusal (already-populated shard dir without --force)');
  const lib = require(LIB_PATH);
  const { memoryPath, shardDir } = setupSplitFixture();
  lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });

  let threw = null;
  try {
    lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });
  } catch (err) {
    threw = err;
  }
  assert(threw !== null, 'a second split without --force REFUSES (throws)');
  if (threw !== null) {
    assert(/already contains/.test(threw.message), 'refusal message names the already-populated shard dir');
  }

  console.log('  Mutation: disable the re-split refusal guard');
  const mutatedLib = loadMutatedLib((src) => {
    const marker = 'if (oldRecords.length > 0 && !force) {';
    if (!src.includes(marker)) throw new Error('re-split guard marker not found - mutation site moved');
    return src.replace(marker, 'if (false && oldRecords.length > 0 && !force) {');
  }, 'disable-resplit-guard');
  let mutantThrew = null;
  try {
    mutatedLib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });
  } catch (err) {
    mutantThrew = err;
  }
  assert(
    mutantThrew === null,
    'REDDENED: with the guard disabled, a second split without --force no longer refuses (silently reconciles)',
  );
}

function caseBulkOrphanThreshold() {
  console.log('\n[Manifest] Bulk-orphan deletion threshold (>3 orphans without --allow-removal)');
  const lib = require(LIB_PATH);
  const { memoryPath, shardDir } = setupSplitFixture();
  lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });

  // Remove 5 of the fixture's 15 entries from MEMORY.md (more than
  // BULK_ORPHAN_THRESHOLD=3), simulating a large hand-edit - their
  // corresponding shards become orphans on the next split.
  const lines = fs.readFileSync(memoryPath, 'utf8').split('\n');
  let removed = 0;
  const kept = [];
  for (const line of lines) {
    if (removed < 5 && /^- \*\*2026-01-1[0-4]:/.test(line)) {
      removed++;
      continue;
    }
    kept.push(line);
  }
  assert(removed === 5, `setup: removed exactly 5 entries from MEMORY.md (removed ${removed})`);
  fs.writeFileSync(memoryPath, kept.join('\n'));

  let threw = null;
  try {
    lib.splitCommand({ shardDir, memoryPath, force: true, allowRemoval: false });
  } catch (err) {
    threw = err;
  }
  assert(threw !== null, 'split --force (no --allow-removal) REFUSES when reconciliation would remove >3 orphans');
  if (threw !== null) {
    assert(/REFUSING/.test(threw.message) && /threshold/.test(threw.message), 'refusal message names the bulk-orphan threshold');
  }
  assert(fs.readdirSync(shardDir).length === 16, 'nothing was deleted from shardDir on refusal (still 15 entries + preamble)');

  console.log('  Mutation: disable the bulk-orphan threshold guard');
  const mutatedLib = loadMutatedLib((src) => {
    const marker = 'if (orphanFiles.length > BULK_ORPHAN_THRESHOLD && !allowRemoval) {';
    if (!src.includes(marker)) throw new Error('bulk-orphan guard marker not found - mutation site moved');
    return src.replace(marker, 'if (false && orphanFiles.length > BULK_ORPHAN_THRESHOLD && !allowRemoval) {');
  }, 'disable-bulk-orphan-guard');
  let mutantThrew = null;
  try {
    mutatedLib.splitCommand({ shardDir, memoryPath, force: true, allowRemoval: false });
  } catch (err) {
    mutantThrew = err;
  }
  assert(
    mutantThrew === null && fs.readdirSync(shardDir).length === 11,
    'REDDENED: with the guard disabled, split --force silently deletes all 5 orphans without --allow-removal (shard count drops from 16 to 11)',
  );
}

function caseDuplicateSequenceRefusal() {
  console.log('\n[Manifest] Duplicate-sequence refusal in compileFromRecords');
  const lib = require(LIB_PATH);
  const { memoryPath, shardDir } = setupSplitFixture();
  lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });

  const records = lib.readEntryRecords(shardDir);
  const sorted = [...records].sort((a, b) => a.sequence - b.sequence);
  const a = sorted[0];
  const b = sorted[1];
  // Force b's sequence to collide with a's (a genuine duplicate, not merely
  // a swap - this is a different scenario from case 3's reorder refusal).
  const bText = fs.readFileSync(path.join(shardDir, b.file), 'utf8');
  fs.writeFileSync(path.join(shardDir, b.file), bText.replace(`sequence: ${b.sequence}`, `sequence: ${a.sequence}`));

  let threw = null;
  try {
    lib.compileFromDir(shardDir);
  } catch (err) {
    threw = err;
  }
  assert(threw !== null, 'compileFromDir REFUSES (throws) when two shards share the same sequence value');
  if (threw !== null) {
    assert(/duplicate sequence/.test(threw.message), 'refusal message names the duplicate sequence');
  }

  console.log('  Mutation: disable the duplicate-sequence guard');
  const mutatedLib = loadMutatedLib((src) => {
    const marker = 'if (seen.has(r.sequence)) {';
    if (!src.includes(marker)) throw new Error('duplicate-sequence guard marker not found - mutation site moved');
    return src.replace(marker, 'if (false && seen.has(r.sequence)) {');
  }, 'disable-duplicate-sequence-guard');
  let mutantThrew = null;
  try {
    mutatedLib.compileFromDir(shardDir);
  } catch (err) {
    mutantThrew = err;
  }
  assert(
    mutantThrew === null,
    'REDDENED: with the guard disabled, compileFromDir no longer refuses a duplicate sequence (silently compiles in array order)',
  );
}

function caseNonMdRefusal() {
  console.log('\n[Manifest] Non-".md" file refusal in readEntryRecords');
  const lib = require(LIB_PATH);
  const { memoryPath, shardDir } = setupSplitFixture();
  lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });
  // Deliberately VALID frontmatter content (parseShardFile would accept it
  // cleanly) at a NON-".md" filename - isolates the extension check itself.
  // Content that failed to parse as a shard (e.g. "not a shard\n") would
  // still throw with the extension guard disabled, just from
  // parseShardFile's OWN frontmatter validation instead - a cascading
  // failure that would make the mutation assertion below pass for the
  // wrong reason.
  const strayText = lib.buildFrontmatter({
    name: 'stray-notes',
    description: 'Not a real shard, wrong extension.',
    type: 'project',
    sequence: 999999,
  }) + '- **2026-01-01: Stray entry.** Should never be read.\n';
  fs.writeFileSync(path.join(shardDir, 'stray-notes.txt'), strayText);

  let threw = null;
  try {
    lib.readEntryRecords(shardDir);
  } catch (err) {
    threw = err;
  }
  assert(threw !== null, 'readEntryRecords REFUSES (throws) on a stray non-".md" file in the shard dir');
  if (threw !== null) {
    assert(/stray-notes\.txt/.test(threw.message), 'refusal message names the offending filename');
  }

  console.log('  Mutation: disable the non-".md" guard');
  const mutatedLib = loadMutatedLib((src) => {
    const marker = "if (!name.endsWith('.md')) {";
    if (!src.includes(marker)) throw new Error('non-.md guard marker not found - mutation site moved');
    return src.replace(marker, "if (false && !name.endsWith('.md')) {");
  }, 'disable-non-md-guard');
  let mutantThrew = null;
  try {
    mutatedLib.readEntryRecords(shardDir);
  } catch (err) {
    mutantThrew = err;
  }
  assert(
    mutantThrew === null,
    'REDDENED: with the guard disabled, readEntryRecords silently ignores the stray non-".md" file instead of refusing (content is deliberately valid frontmatter, isolating the extension check)',
  );
}

function casePrecommitVerification() {
  console.log('\n[Manifest] Pre-commit round-trip verification (refuses BEFORE any real file is touched)');
  const { memoryPath, shardDir } = setupSplitFixture();

  // Inject a mutation that corrupts ONE staged shard file immediately after
  // staging (simulating a hypothetical bug in the staging-write step) -
  // this makes stagedCompiled genuinely diverge from `original`, a
  // legitimate trigger for the pre-commit guard rather than a synthetic one.
  const corruptedLib = loadMutatedLib((src) => {
    const marker = [
      "  for (const r of resolved) {",
      "    fs.writeFileSync(path.join(stagingDir, r.filename), r.text, 'utf8');",
      "  }",
      "",
      "  const stagedCompiled = compileFromDir(stagingDir);",
    ].join('\n');
    if (!src.includes(marker)) throw new Error('staging-write marker not found - mutation site moved');
    return src.replace(
      marker,
      [
        "  for (const r of resolved) {",
        "    fs.writeFileSync(path.join(stagingDir, r.filename), r.text, 'utf8');",
        "  }",
        "  fs.appendFileSync(path.join(stagingDir, resolved[0].filename), 'PRECOMMIT_CORRUPTION\\n');",
        "",
        "  const stagedCompiled = compileFromDir(stagingDir);",
      ].join('\n'),
    );
  }, 'corrupt-staged-shard');

  let threw = null;
  try {
    corruptedLib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });
  } catch (err) {
    threw = err;
  }
  assert(threw !== null, 'a corrupted staged shard REFUSES (throws) before any real file is touched');
  if (threw !== null) {
    assert(/round-trip verification FAILED before any real shard file was touched/.test(threw.message), 'refusal message is the PRE-COMMIT variant specifically');
  }
  assert(!fs.existsSync(shardDir), 'nothing was committed to the real shardDir on pre-commit refusal (it does not even exist)');

  console.log('  Mutation: ALSO disable the pre-commit guard (on top of the same corruption)');
  const corruptedAndDisabledLib = loadMutatedLib((src) => {
    const stageMarker = [
      "  for (const r of resolved) {",
      "    fs.writeFileSync(path.join(stagingDir, r.filename), r.text, 'utf8');",
      "  }",
      "",
      "  const stagedCompiled = compileFromDir(stagingDir);",
    ].join('\n');
    if (!src.includes(stageMarker)) throw new Error('staging-write marker not found - mutation site moved');
    let mutated = src.replace(
      stageMarker,
      [
        "  for (const r of resolved) {",
        "    fs.writeFileSync(path.join(stagingDir, r.filename), r.text, 'utf8');",
        "  }",
        "  fs.appendFileSync(path.join(stagingDir, resolved[0].filename), 'PRECOMMIT_CORRUPTION\\n');",
        "",
        "  const stagedCompiled = compileFromDir(stagingDir);",
      ].join('\n'),
    );
    const guardMarker = 'if (stagedCompiled !== original) {';
    if (!mutated.includes(guardMarker)) throw new Error('pre-commit guard marker not found - mutation site moved');
    mutated = mutated.replace(guardMarker, 'if (false && stagedCompiled !== original) {');
    return mutated;
  }, 'corrupt-staged-shard-and-disable-precommit-guard');

  // NOTE: the post-commit guard is still intact in this mutant, and it will
  // independently catch the SAME corruption (defense in depth) - so this
  // specific mutant demonstrates the pre-commit guard's OWN distinct value
  // (refusing before shardDir is ever created), while the two assertions
  // below still prove real observable loss: shardDir gets created and
  // populated with the corrupted content before the post-commit guard
  // ever runs, which never happens with both guards intact.
  let mutantThrew = null;
  try {
    corruptedAndDisabledLib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });
  } catch (err) {
    mutantThrew = err;
  }
  assert(
    mutantThrew !== null && /POST-COMMIT verification FAILED/.test(mutantThrew.message),
    'REDDENED: with ONLY the pre-commit guard disabled, the SAME corruption is instead caught by the post-commit guard - proving the pre-commit guard specifically is what prevented shardDir from ever being touched',
  );
  assert(
    fs.existsSync(shardDir),
    'REDDENED: with the pre-commit guard disabled, the corrupted content WAS actually committed to shardDir before the post-commit guard caught it (the exact "before any real file is touched" guarantee is what was lost)',
  );
}

function casePostcommitVerification() {
  console.log('\n[Manifest] Post-commit verification (catches a bug in the commit step itself)');
  const { memoryPath, shardDir } = setupSplitFixture();

  // Inject a mutation that corrupts a REAL committed shard file AFTER the
  // rename-into-shardDir step but BEFORE the post-commit compile check -
  // this never touches staging, so it isolates the post-commit guard
  // specifically (the pre-commit guard cannot see this corruption at all).
  const corruptedLib = loadMutatedLib((src) => {
    const marker = [
      "  for (const orphan of orphanFiles) {",
      "    fs.rmSync(path.join(shardDir, orphan), { force: true });",
      "  }",
      "",
    ].join('\n');
    if (!src.includes(marker)) throw new Error('post-commit marker not found - mutation site moved');
    return src.replace(
      marker,
      marker + "  fs.appendFileSync(path.join(shardDir, resolved[0].filename), 'POSTCOMMIT_CORRUPTION\\n');\n\n",
    );
  }, 'corrupt-committed-shard');

  let threw = null;
  try {
    corruptedLib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });
  } catch (err) {
    threw = err;
  }
  assert(threw !== null, 'a post-commit corruption REFUSES (throws) after committing');
  if (threw !== null) {
    assert(/POST-COMMIT verification FAILED/.test(threw.message), 'refusal message is the POST-COMMIT variant specifically');
  }
  assert(
    fs.existsSync(shardDir) && fs.readdirSync(shardDir).some((f) => fs.readFileSync(path.join(shardDir, f), 'utf8').includes('POSTCOMMIT_CORRUPTION')),
    'the corrupted content WAS committed (matches the documented "should be unreachable if pre-commit passed, but if it happens the real files are already written" contract)',
  );

  console.log('  Mutation: ALSO disable the post-commit guard (on top of the same corruption)');
  const { memoryPath: memoryPath2, shardDir: shardDir2 } = setupSplitFixture();
  const corruptedAndDisabledLib = loadMutatedLib((src) => {
    const commitMarker = [
      "  for (const orphan of orphanFiles) {",
      "    fs.rmSync(path.join(shardDir, orphan), { force: true });",
      "  }",
      "",
    ].join('\n');
    if (!src.includes(commitMarker)) throw new Error('post-commit marker not found - mutation site moved');
    let mutated = src.replace(
      commitMarker,
      commitMarker + "  fs.appendFileSync(path.join(shardDir, resolved[0].filename), 'POSTCOMMIT_CORRUPTION\\n');\n\n",
    );
    const guardMarker = 'if (committedCompiled !== original) {';
    if (!mutated.includes(guardMarker)) throw new Error('post-commit guard marker not found - mutation site moved');
    mutated = mutated.replace(guardMarker, 'if (false && committedCompiled !== original) {');
    return mutated;
  }, 'corrupt-committed-shard-and-disable-postcommit-guard');

  let mutantThrew = null;
  try {
    corruptedAndDisabledLib.splitCommand({ shardDir: shardDir2, memoryPath: memoryPath2, force: false, allowRemoval: false });
  } catch (err) {
    mutantThrew = err;
  }
  assert(
    mutantThrew === null,
    'REDDENED: with the post-commit guard disabled, the corrupted split now reports SUCCESS with no error at all',
  );
  assert(
    fs.existsSync(shardDir2) && fs.readdirSync(shardDir2).some((f) => fs.readFileSync(path.join(shardDir2, f), 'utf8').includes('POSTCOMMIT_CORRUPTION')),
    'REDDENED: the corrupted content survives undetected in the committed shardDir',
  );
}

function caseEnoentNarrowingRegression() {
  console.log('\n[Manifest] regenerateCommand read-error narrowing (ENOENT only, round-2 fix regression pin)');
  const lib = require(LIB_PATH);
  const { memoryPath, shardDir } = setupSplitFixture();
  lib.splitCommand({ shardDir, memoryPath, force: false, allowRemoval: false });

  // Make memoryPath unreadable (EACCES, not ENOENT) - a non-absent-file
  // read failure that must propagate, never be silently swallowed.
  fs.chmodSync(memoryPath, 0o000);
  let threw = null;
  try {
    lib.regenerateCommand({ shardDir, memoryPath, check: false, allowRemoval: false });
  } catch (err) {
    threw = err;
  } finally {
    fs.chmodSync(memoryPath, 0o644);
  }
  assert(threw !== null, 'a non-ENOENT read failure (EACCES) on memoryPath PROPAGATES rather than being swallowed');
  if (threw !== null) {
    assert(threw.code === 'EACCES', 'the propagated error is the real EACCES, not a fabricated one');
  }

  console.log('  Mutation: revert to a bare catch {} (round-1 regression shape)');
  const mutatedLib = loadMutatedLib((src) => {
    const marker = [
      "  let current = null;",
      "  try {",
      "    current = fs.readFileSync(memoryPath, 'utf8');",
      "  } catch (err) {",
      "    if (!err || err.code !== 'ENOENT') {",
      "      throw err;",
      "    }",
      "  }",
    ].join('\n');
    if (!src.includes(marker)) throw new Error('ENOENT-narrowing marker not found - mutation site moved');
    return src.replace(
      marker,
      [
        "  let current = null;",
        "  try {",
        "    current = fs.readFileSync(memoryPath, 'utf8');",
        "  } catch {",
        "    // MUTANT: bare swallow (round-1 regression shape)",
        "  }",
      ].join('\n'),
    );
  }, 'bare-catch-regression');

  fs.chmodSync(memoryPath, 0o000);
  let mutantThrew = null;
  let mutantResult = null;
  try {
    mutantResult = mutatedLib.regenerateCommand({ shardDir, memoryPath, check: false, allowRemoval: false });
  } catch (err) {
    mutantThrew = err;
  } finally {
    fs.chmodSync(memoryPath, 0o644);
  }
  assert(
    mutantThrew === null && mutantResult && mutantResult.wrote === true,
    'REDDENED: with the bare catch restored, the EACCES read failure is silently swallowed and regenerateCommand proceeds to a successful write',
  );
}

function main() {
  try {
    case1();
    caseNoPreamble();
    case2();
    case3();
    case4();
    case5();
    case6();
    caseCliSuccessPath();
    caseCliArgParsing();
    caseWriteFileAtomicIsReallyAtomic();
    caseResplitRefusal();
    caseBulkOrphanThreshold();
    caseDuplicateSequenceRefusal();
    caseNonMdRefusal();
    casePrecommitVerification();
    casePostcommitVerification();
    caseEnoentNarrowingRegression();
  } finally {
    cleanup();
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
