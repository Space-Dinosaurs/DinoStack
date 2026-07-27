#!/usr/bin/env node
'use strict';

/**
 * Unit tests for hooks/lib/context-rollup.js - the per-session SHARD + derived
 * ROLLUP model that replaces whole-file `.agentic/context.md` writes (DS-107).
 *
 * Regression coverage for the live defect: an orphaned `/ds-wrap` lock silently
 * discarded 49 `context.md` writes across 6 sessions over ~12 hours, because the
 * lock was CHECKED by two writers and ACQUIRED by neither (no mutual exclusion),
 * a third writer ignored it entirely, and nothing could ever clear it.
 *
 * Covers:
 *   AC4  - two writers with different session_id both persist
 *   AC5  - a capture-gap append leaves the `_wrap.md`-derived region byte-identical
 *   AC7  - two successive regens over an unchanged shard set are BYTE-IDENTICAL
 *   AC9  - a pre-existing non-derived context.md is preserved as `_foreign.md`
 *   AC12 - the derived marker lives in the ACTIVITY-REGION header, not the file header
 *   AC16 - `---`-segmentation relationship holds and heuristic 2 stays the one that fires
 *   AC17 - `_wrap.md`'s 10 session labels survive repeated rollup regens
 *   AC18 - a wrap-ticket `[Ticket ID]` paragraph in `_wrap.md` survives a regen
 *   AC19 - an `agentic-migrate` audit line (its own shard) survives a regen
 *   AC21 - migrating a `/ds-wrap` file seeds `_wrap.md` with lines 1-2 BYTE-EXACT
 *   AC22 - a pre-sentinel CAPTURE-GAP block does not enter the seeded `_wrap.md`
 *   AC23 - interleaved writers: the final rollup contains BOTH blocks
 *   AC24 - a no-sentinel non-/ds-wrap file is preserved as `_foreign.md`
 *   AC25 - a curated body QUOTING the sentinel migrates without truncation
 *   plus: shard ordering, retention, symlink refusal, fail-open behaviour.
 *
 * Run with: node hooks/tests/test-context-shard-rollup.js
 * Argument-free invocation runs everything (auto-discovered by the
 * hooks/tests/test-*.js glob in .github/workflows/hooks-tests.yml).
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const R = require('../lib/context-rollup.js');

let passed = 0;
let failed = 0;
const tmpDirs = [];

function assert(condition, message) {
  if (condition) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message}`);
    failed++;
  }
}

function makeProject() {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ctx-rollup-')));
  tmpDirs.push(dir);
  fs.mkdirSync(path.join(dir, '.agentic'), { recursive: true });
  return dir;
}

function readRollup(cwd) {
  try { return fs.readFileSync(R.rollupPath(cwd), 'utf8'); } catch (_) { return null; }
}

const SENTINEL = R.ACTIVITY_SENTINEL;

// ---------------------------------------------------------------------------
// AC4 - two writers with different session_id both persist
// ---------------------------------------------------------------------------
console.log('\n--- AC4: disjoint shards, neither lost ---');
{
  const cwd = makeProject();
  R.writeShard(cwd, 'sess-alpha', '- alpha did a thing\n');
  R.writeShard(cwd, 'sess-beta', '- beta did another thing\n');
  R.regenerateRollup(cwd, { banner: null });
  const body = readRollup(cwd);
  assert(body !== null && body.includes('alpha did a thing'), 'AC4: alpha activity present');
  assert(body !== null && body.includes('beta did another thing'), 'AC4: beta activity present');
  assert(fs.existsSync(R.shardPath(cwd, 'sess-alpha')) && fs.existsSync(R.shardPath(cwd, 'sess-beta')),
    'AC4: both shard files exist on disk');
}

// Falsifying mutation for AC4: point both shards at one filename.
{
  const cwd = makeProject();
  const single = path.join(R.shardDirPath(cwd), 'collapsed.md');
  fs.mkdirSync(R.shardDirPath(cwd), { recursive: true });
  fs.writeFileSync(single, '- alpha did a thing\n');
  fs.writeFileSync(single, '- beta did another thing\n'); // second write clobbers
  R.regenerateRollup(cwd, { banner: null });
  const body = readRollup(cwd) || '';
  assert(!body.includes('alpha did a thing'),
    'AC4 mutation: collapsing both writers onto one filename DOES lose the first (gate is live)');
}

// ---------------------------------------------------------------------------
// AC7 - idempotence: two regens over an unchanged shard set are byte-identical
// ---------------------------------------------------------------------------
console.log('\n--- AC7: byte-identical regens ---');
{
  const cwd = makeProject();
  R.writeShard(cwd, 'sess-one', '- one\n');
  R.writeShard(cwd, 'sess-two', '- two\n');
  R.regenerateRollup(cwd, { banner: null });
  const first = readRollup(cwd);
  R.regenerateRollup(cwd, { banner: null });
  const second = readRollup(cwd);
  assert(first !== null && first === second, 'AC7: two successive regens are byte-identical');
  assert(!/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(first || ''),
    'AC7: composer emits no ISO timestamp of its own (idempotence, hence lock-freedom)');
}

// ---------------------------------------------------------------------------
// AC12 - marker placement: activity-region header, NEVER the file header
// ---------------------------------------------------------------------------
console.log('\n--- AC12: derived marker placement ---');
{
  const cwd = makeProject();
  fs.writeFileSync(R.curatedPath(cwd),
    '# Session Context\n*Written by /ds-wrap on 2026-07-26.*\n\n## Recent Focus\n[Session A] curated\n');
  R.writeShard(cwd, 'sess-x', '- x\n');
  R.regenerateRollup(cwd, { banner: null });
  const body = readRollup(cwd) || '';
  const markerIdx = body.indexOf(R.DERIVED_MARKER);
  const sentinelIdx = body.indexOf(SENTINEL);
  assert(markerIdx > 0 && sentinelIdx >= 0 && markerIdx > sentinelIdx,
    'AC12: derived marker sits AFTER the sentinel (activity-region header)');
  const header = body.split('\n').slice(0, 3).join('\n');
  assert(header.indexOf(R.DERIVED_MARKER) === -1,
    'AC12: derived marker is ABSENT from the file header (a header marker survives '
    + "OpenCode's strip-and-append and defeats foreign-preservation)");

  // THE CONSEQUENCE, asserted directly rather than inferred from placement.
  // OpenCode's legacy strip-and-append PRESERVES the file header and REPLACES
  // the activity region. Simulate exactly that against our own marked rollup: a
  // marker living in the file header would survive the foreign write, the
  // composer would conclude "this is mine", skip foreign-preservation, and
  // destroy the foreign block. Checking placement alone does not catch a
  // detector that consults the wrong region; this does.
  const stripped = body.slice(0, body.indexOf(SENTINEL))
    + SENTINEL + '*Auto-appended by session idle plugin - 2026-07-26.*\n\nFOREIGN STRIP-AND-APPEND BLOCK\n';
  assert(stripped.indexOf(R.DERIVED_MARKER) === -1,
    'AC12: a foreign strip-and-append leaves NO derived marker anywhere in the file');
  fs.writeFileSync(R.rollupPath(cwd), stripped);
  R.regenerateRollup(cwd, { banner: null });
  const preserved = (function () {
    try { return fs.readFileSync(R.foreignPath(cwd), 'utf8'); } catch (_) { return ''; }
  })();
  assert(preserved.includes('FOREIGN STRIP-AND-APPEND BLOCK'),
    'AC12: the foreign block IS preserved - marker placement actually defends the '
    + 'unported-adapter path, not just the byte layout');
}

// ---------------------------------------------------------------------------
// AC12 - a rollup carrying 3 session blocks still carries all 3 after a regen
// ---------------------------------------------------------------------------
console.log('\n--- AC12: multi-block accumulation ---');
{
  const cwd = makeProject();
  R.writeShard(cwd, 'sess-1', '- block one\n');
  R.writeShard(cwd, 'sess-2', '- block two\n');
  R.writeShard(cwd, 'sess-3', '- block three\n');
  R.regenerateRollup(cwd, { banner: null });
  R.regenerateRollup(cwd, { banner: null });
  const body = readRollup(cwd) || '';
  const n = (body.match(/^### Session /gm) || []).length;
  assert(n === 3, `AC12: all 3 session blocks survive a full regen (got ${n})`);
}

// ---------------------------------------------------------------------------
// AC17 / AC18 - curated region is never touched by the accumulator
// ---------------------------------------------------------------------------
console.log('\n--- AC17/AC18: curated region untouched ---');
{
  const cwd = makeProject();
  const labels = 'ABCDEFGHIJ'.split('').map((c) => `[Session ${c}] focus ${c}`).join('\n\n');
  const curated = '# Session Context\n*Written by /ds-wrap on 2026-07-26.*\n\n'
    + '## Recent Focus\n' + labels + '\n\n[Ticket DS-106] wrap-ticket paragraph\n';
  fs.writeFileSync(R.curatedPath(cwd), curated);
  R.writeShard(cwd, 'sess-q', '- q\n');
  for (let i = 0; i < 5; i++) R.regenerateRollup(cwd, { banner: null });
  const after = fs.readFileSync(R.curatedPath(cwd), 'utf8');
  assert(after === curated, 'AC17: _wrap.md is byte-unchanged after 5 rollup regens');
  const body = readRollup(cwd) || '';
  const labelCount = (body.match(/\[Session [A-J]\]/g) || []).length;
  assert(labelCount === 10, `AC17: all 10 session labels present in the rollup (got ${labelCount})`);
  assert(body.includes('[Ticket DS-106] wrap-ticket paragraph'),
    'AC18: a wrap-ticket [Ticket ID] paragraph survives the regen');
  const preSentinel = body.slice(0, body.indexOf(SENTINEL));
  const postSentinel = body.slice(body.indexOf(SENTINEL));
  assert(postSentinel.indexOf('## Recent Focus') === -1,
    'AC17: the composer NEVER writes ## Recent Focus (curated content it must not own)');
  assert(preSentinel.includes('## Recent Focus'),
    'AC17: ## Recent Focus stays in the curated pre-sentinel region');
}

// ---------------------------------------------------------------------------
// AC19 - an agentic-migrate audit line (its own shard) survives a regen
// ---------------------------------------------------------------------------
console.log('\n--- AC19: migrate audit line survives ---');
{
  const cwd = makeProject();
  R.appendToShard(cwd, 'notices', '[scaffolding-sync] WARNING: manifest not found, sync skipped.\n');
  R.writeShard(cwd, 'sess-live', '- live turn\n');
  R.regenerateRollup(cwd, { banner: null });
  R.regenerateRollup(cwd, { banner: null });
  const body = readRollup(cwd) || '';
  assert(body.includes('[scaffolding-sync] WARNING: manifest not found'),
    'AC19: the audit line survives a subsequent regen (it lives in its own shard)');
}

// ---------------------------------------------------------------------------
// AC5 - a capture-gap append does not mutate the derived region
// ---------------------------------------------------------------------------
console.log('\n--- AC5: capture-gap append is shard-local ---');
{
  const cwd = makeProject();
  fs.writeFileSync(R.curatedPath(cwd),
    '# Session Context\n*Written by /ds-wrap on 2026-07-26.*\n\n## Recent Focus\n[Session A] curated\n');
  R.writeShard(cwd, 'sess-c', '- turn body\n');
  R.regenerateRollup(cwd, { banner: null });
  const curatedBefore = fs.readFileSync(R.curatedPath(cwd), 'utf8');
  R.appendToShard(cwd, 'sess-c', '\n---\nCAPTURE-GAP: nudge text\n');
  R.regenerateRollup(cwd, { banner: null });
  const curatedAfter = fs.readFileSync(R.curatedPath(cwd), 'utf8');
  assert(curatedBefore === curatedAfter, 'AC5: the curated _wrap.md is byte-identical after a capture-gap append');
  assert((readRollup(cwd) || '').includes('CAPTURE-GAP: nudge text'),
    'AC5: the nudge still reaches the rollup, via the session shard');
}

// ---------------------------------------------------------------------------
// AC9 / AC24 - foreign preservation
// ---------------------------------------------------------------------------
console.log('\n--- AC9/AC24: foreign preservation ---');
{
  // AC9: an UNMARKED activity region (an unported adapter's strip-and-append).
  const cwd = makeProject();
  fs.writeFileSync(R.curatedPath(cwd), '# Session Context\n*Written by /ds-wrap on 2026-07-26.*\n\ncurated\n');
  fs.writeFileSync(R.rollupPath(cwd),
    '# Session Context\n*Written by /ds-wrap on 2026-07-26.*\n\ncurated'
    + SENTINEL + '*Auto-appended by Stop hook - 2026-07-26.*\n\nUNPORTED ADAPTER BLOCK\n');
  R.writeShard(cwd, 'sess-n', '- new\n');
  R.regenerateRollup(cwd, { banner: null });
  const foreign = fs.readFileSync(R.foreignPath(cwd), 'utf8');
  assert(foreign.includes('UNPORTED ADAPTER BLOCK'), 'AC9: an unmarked activity region is preserved as _foreign.md');
  assert((readRollup(cwd) || '').includes('- new'), 'AC9: the rollup is rebuilt after preservation');
}
{
  // AC24: a no-sentinel, non-/ds-wrap whole-file write (what all 5 deferred
  // adapters emit - each a bare writeFileSync with ZERO sentinels).
  const cwd = makeProject();
  fs.writeFileSync(R.curatedPath(cwd), '# Session Context\n*Written by /ds-wrap on 2026-07-26.*\n\ncurated\n');
  fs.writeFileSync(R.rollupPath(cwd),
    '# Session Context\n*Auto-updated by session idle plugin - 2026-07-26.*\n\nADAPTER WHOLE FILE\n');
  R.writeShard(cwd, 'sess-m', '- m\n');
  R.regenerateRollup(cwd, { banner: null });
  const foreign = fs.readFileSync(R.foreignPath(cwd), 'utf8');
  assert(foreign.includes('ADAPTER WHOLE FILE'),
    'AC24: a no-sentinel non-/ds-wrap body is preserved entirely as _foreign.md');
}
{
  // Negative: our OWN marked rollup must never be preserved as foreign, and a
  // repeated regen must not churn _foreign.md every turn.
  const cwd = makeProject();
  R.writeShard(cwd, 'sess-p', '- p\n');
  R.regenerateRollup(cwd, { banner: null });
  R.writeShard(cwd, 'sess-p2', '- p2\n');
  R.regenerateRollup(cwd, { banner: null });
  assert(!fs.existsSync(R.foreignPath(cwd)),
    'no _foreign.md churn: a marked rollup whose shard set changed is NOT treated as foreign');
}
{
  // Negative: our own ZERO-SHARD output (E8: `_wrap.md` verbatim, no sentinel)
  // must not be misread as a foreign whole-file write on the next turn.
  const cwd = makeProject();
  fs.writeFileSync(R.curatedPath(cwd), '# Curated By Conductor\nno wrap header here\n\nbody\n');
  R.regenerateRollup(cwd, { banner: null });
  R.writeShard(cwd, 'sess-e8', '- e8\n');
  R.regenerateRollup(cwd, { banner: null });
  assert(!fs.existsSync(R.foreignPath(cwd)),
    'E8: our own zero-shard rollup is recognised as ours, not preserved as foreign');
}

// ---------------------------------------------------------------------------
// AC21 / AC22 / AC25 - migration
// ---------------------------------------------------------------------------
console.log('\n--- AC21/AC22/AC25: migration ---');
const AC25_FIXTURE = [
  '# Session Context',
  '*Written by /ds-wrap on 2026-07-26.*',
  '*Project: /somewhere*',
  '',
  '## Recent Focus',
  '[Session A] we agreed the sentinel bytes are literally:',
  '',
  '---',
  '',
  '## Session Activity',
  'and that quoted block is curated prose, not a derived region.',
  '',
  'LATER CURATED TEXT that must survive migration.',
  '',
  '---',
  'CAPTURE-GAP: this session resolved a root cause / worked around a tool failure',
  'but recorded no learning. If there is a non-obvious WHY beyond what a test or',
  'the diff already shows, capture it.',
  '',
  '## Watch Out For',
  '- the hardlink hazard',
  '',
  '---',
  '',
  '## Session Activity',
  '*Auto-appended by Stop hook - 2026-07-25. Replaced each session.*',
  '',
  '### Recent Messages',
  '- STALE DERIVED ACTIVITY',
  '',
].join('\n');

{
  const cwd = makeProject();
  fs.writeFileSync(R.rollupPath(cwd), AC25_FIXTURE);

  const firstSentinel = AC25_FIXTURE.indexOf(SENTINEL);
  const realRegion = R.findActivityRegionIndex(AC25_FIXTURE);
  assert(firstSentinel >= 0 && realRegion > firstSentinel,
    `AC25: the quoted sentinel (offset ${firstSentinel}) is NOT the region boundary (offset ${realRegion})`);

  const migrated = R.migrateIfNeeded(cwd);
  assert(migrated === true, 'migration ran once');
  const seed = fs.readFileSync(R.curatedPath(cwd), 'utf8');

  const srcHead = AC25_FIXTURE.split('\n').slice(0, 2).join('\n');
  const seedHead = seed.split('\n').slice(0, 2).join('\n');
  assert(seedHead === srcHead,
    'AC21: lines 1-2 are BYTE-EXACT (anything else and the next /ds-wrap takes the '
    + 'fresh-write/replace branch and destroys the 10-slot window)');

  assert(seed.includes('LATER CURATED TEXT that must survive migration.'),
    'AC25: curated text FOLLOWING a quoted sentinel survives (slicing at the FIRST '
    + 'sentinel would truncate it, and AC21 would still pass)');
  assert(seed.includes('## Watch Out For'), 'AC25: curated content after the CAPTURE-GAP block survives');
  assert(!seed.includes('CAPTURE-GAP'), 'AC22: the pre-sentinel CAPTURE-GAP block is NOT seeded into _wrap.md');
  assert(!seed.includes('STALE DERIVED ACTIVITY'), 'AC22: the derived activity region is NOT seeded into _wrap.md');

  // Idempotence: a second call must be a no-op.
  const before = fs.readFileSync(R.curatedPath(cwd), 'utf8');
  assert(R.migrateIfNeeded(cwd) === false, 'migration is guarded by _wrap.md existence');
  assert(fs.readFileSync(R.curatedPath(cwd), 'utf8') === before, 'migration is idempotent');
}

{
  // Migration of a NON-/ds-wrap file must NOT seed the curated file.
  const cwd = makeProject();
  fs.writeFileSync(R.rollupPath(cwd),
    '# Session Context\n*Auto-updated by Stop hook - 2026-07-26.*\n\nSTOP HOOK BODY\n');
  R.migrateIfNeeded(cwd);
  assert(!fs.existsSync(R.curatedPath(cwd)),
    'migration: a Stop-hook-authored file is NOT curated and never seeds _wrap.md');
  assert(fs.readFileSync(R.foreignPath(cwd), 'utf8').includes('STOP HOOK BODY'),
    'migration: non-curated content is preserved as _foreign.md');
}

{
  // Empty / whitespace-only existing file: no migration, no crash.
  const cwd = makeProject();
  fs.writeFileSync(R.rollupPath(cwd), '   \n\n');
  assert(R.migrateIfNeeded(cwd) === false, 'migration: whitespace-only context.md is a no-op');
  assert(!fs.existsSync(R.curatedPath(cwd)), 'migration: no _wrap.md seeded from an empty file');
}

// ---------------------------------------------------------------------------
// AC23 - interleaved writers (compare-and-retry)
// ---------------------------------------------------------------------------
console.log('\n--- AC23: interleaved writers ---');
{
  // Simulate X shard -> X snapshot -> Y shard -> Y snapshot -> Y rollup -> X
  // rollup. X's regen is entered when only X's shard is visible; the interleave
  // is injected by writing Y's shard from inside X's first snapshot window.
  const cwd = makeProject();
  R.writeShard(cwd, 'sess-X', '- from X\n');

  const realReaddir = fs.readdirSync;
  let injected = false;
  fs.readdirSync = function (p, o) {
    const names = realReaddir.call(fs, p, o);
    if (!injected && String(p) === R.shardDirPath(cwd)) {
      injected = true;
      // Y lands AFTER X snapshotted the shard dir but BEFORE X writes its rollup.
      R.writeShard(cwd, 'sess-Y', '- from Y\n');
    }
    return names;
  };
  try {
    R.regenerateRollup(cwd, { banner: null });
  } finally {
    fs.readdirSync = realReaddir;
  }
  const body = readRollup(cwd) || '';
  assert(body.includes('- from X') && body.includes('- from Y'),
    'AC23: compare-and-retry recovers the block written under the read-then-write window');
}

// ---------------------------------------------------------------------------
// AC16 - agentic-memory segmentation relationship
// ---------------------------------------------------------------------------
console.log('\n--- AC16: agentic-memory segmentation ---');
{
  const cwd = makeProject();
  fs.writeFileSync(R.curatedPath(cwd),
    '# Session Context\n*Written by /ds-wrap on 2026-07-26.*\n\n## Recent Focus\n[Session A] curated\n');
  R.writeShard(cwd, 'sess-s1', '- one\n');
  R.writeShard(cwd, 'sess-s2', '- two\n');
  R.writeShard(cwd, 'sess-s3', '- three\n');
  R.regenerateRollup(cwd, { banner: null });
  const lines = (readRollup(cwd) || '').split('\n');

  // Heuristic 1 (`^##\s+Turn`) must NOT fire, or it hijacks segmentation.
  const turnHeadings = lines.filter((l) => /^##\s+Turn\b/i.test(l)).length;
  assert(turnHeadings === 0,
    'AC16: the rollup emits no `## Turn` heading, so agentic-memory heuristic 1 never fires');

  // Heuristic 2 (`^---+$`) fires, and the segment count is a RELATIONSHIP:
  // segments == 1 + (number of `---` fences), given no empty segments.
  const fences = lines.filter((l) => /^---+$/.test(l)).length;
  assert(fences >= 1, 'AC16: heuristic 2 (`---`) is the one that fires');
  const segments = (function () {
    let n = 0;
    let cur = [];
    for (const l of lines) {
      if (/^---+$/.test(l)) { if (cur.length) { n++; cur = []; } } else { cur.push(l); }
    }
    if (cur.length) n++;
    return n;
  })();
  assert(segments === 1 + fences,
    `AC16: segments (${segments}) == 1 + fences (${fences}) - a relationship, not a magnitude`);
  assert(fences === 3,
    `AC16: 3 session shards produce 3 fences (1 sentinel + 2 inter-block), got ${fences}`);
}

// ---------------------------------------------------------------------------
// Ordering, retention, and hostile input
// ---------------------------------------------------------------------------
console.log('\n--- ordering / retention / hostile input ---');
{
  const cwd = makeProject();
  for (let i = 0; i < 14; i++) {
    R.writeShard(cwd, 'sess-' + String(i).padStart(2, '0'), '- body ' + i + '\n');
    // Force distinct, strictly increasing mtimes so ordering is unambiguous.
    const p = R.shardPath(cwd, 'sess-' + String(i).padStart(2, '0'));
    const t = new Date(Date.now() + i * 1000);
    fs.utimesSync(p, t, t);
  }
  const snap = R.snapshotShards(cwd);
  assert(snap.length === 14, 'snapshotShards sees every shard');
  assert(snap[0].sessionId === 'sess-13', 'shards are ordered mtime DESC (newest first)');
  R.regenerateRollup(cwd, { banner: null });
  const body = readRollup(cwd) || '';
  const n = (body.match(/^### Session /gm) || []).length;
  assert(n === R.SHARD_RETENTION, `retention keeps the ${R.SHARD_RETENTION} most recent shards (got ${n})`);
  assert(body.includes('- body 13') && !body.includes('- body 0\n'),
    'retention drops the OLDEST shards, not the newest');
}
{
  // mtime tie -> the session_id secondary key must make ordering deterministic.
  const cwd = makeProject();
  const t = new Date(1700000000000);
  for (const sid of ['zzz', 'aaa', 'mmm']) {
    R.writeShard(cwd, sid, '- ' + sid + '\n');
    fs.utimesSync(R.shardPath(cwd, sid), t, t);
  }
  const ids = R.snapshotShards(cwd).map((s) => s.sessionId);
  assert(JSON.stringify(ids) === JSON.stringify(['aaa', 'mmm', 'zzz']),
    'mtime ties break on session_id ASC (mandatory: retention drops by order)');
}
{
  const cwd = makeProject();
  assert(R.shardPath(cwd, '../escape') === null, 'traversal session ids are refused');
  assert(R.shardPath(cwd, 'a/b') === null, 'path-separator session ids are refused');
  assert(R.writeShard(cwd, null, 'x') === false, 'a null session id writes no shard');
  assert(R.writeShard(cwd, '', 'x') === false, 'an empty session id writes no shard');
}
{
  // Fail-open: a symlinked shard is skipped, never followed.
  const cwd = makeProject();
  R.writeShard(cwd, 'real', '- real\n');
  fs.mkdirSync(R.shardDirPath(cwd), { recursive: true });
  try {
    fs.symlinkSync('/etc/passwd', path.join(R.shardDirPath(cwd), 'evil.md'));
    const ids = R.snapshotShards(cwd).map((s) => s.sessionId);
    assert(!ids.includes('evil'), 'a symlinked shard is skipped (CWE-59, no-follow)');
  } catch (_) {
    assert(true, 'symlink creation unsupported on this platform - skipped');
  }
}
{
  // Fail-open: nothing throws on a nonexistent project.
  let threw = false;
  try {
    R.regenerateRollup(path.join(os.tmpdir(), 'definitely-not-a-project-' + Date.now()), { banner: null });
    R.snapshotShards('/nonexistent/xyz');
    R.stripDerivedBlocks(null);
    R.findActivityRegionIndex(undefined);
  } catch (_) { threw = true; }
  assert(!threw, 'every entry point is fail-open on absent/invalid input');
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------
for (const d of tmpDirs) {
  try { fs.rmSync(d, { recursive: true, force: true }); } catch (_) { /* best-effort */ }
}

console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
