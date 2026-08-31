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
 * Run with: node hooks/tests/test-memory-shard.js
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

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

/** Runs the real CLI via execFileSync-equivalent (spawn-like, capturing
 * exit code) against `dir`. */
function runCli(args, opts = {}) {
  const res = require('child_process').spawnSync('node', [CLI_PATH, ...args], {
    encoding: 'utf8',
    ...opts,
  });
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

  let threw = null;
  try {
    lib.regenerateCommand({ shardDir, memoryPath, check: false, allowRemoval: false });
  } catch (err) {
    threw = err;
  }
  assert(threw !== null, 'regenerate REFUSES (throws) when the current file lost an entry line');
  assert(/REFUSING/.test(threw.message), 'refusal message says REFUSING');
  const afterAttempt = fs.readFileSync(memoryPath, 'utf8');
  assert(afterAttempt === beforeAttempt, 'nothing was written to MEMORY.md on refusal');

  // CLI-level: nonzero exit
  const cli = runCli(['regenerate', '--dir', dir]);
  assert(cli.status !== 0, 'CLI regenerate exits nonzero on entry-loss refusal');

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
  assert(/REORDER/.test(threw.message), 'refusal message names the reordering');
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

function main() {
  try {
    case1();
    caseNoPreamble();
    case2();
    case3();
    case4();
    case5();
    case6();
  } finally {
    cleanup();
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
