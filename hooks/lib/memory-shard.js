'use strict';

/**
 * Purpose: Compiler/splitter for the memory-shard convention (DS-221 Unit 1):
 *          splits a `MEMORY.md`-shaped file into one git-tracked shard file
 *          per top-level entry (plus a `_preamble.md` structural artifact),
 *          and recompiles those shards back into the original file
 *          byte-for-byte. This is a PURE-LOGIC + FILE-IO library consumed by
 *          `bin/ds-memory-shard` (the CLI). It does not know about any
 *          specific project's `MEMORY.md` - it operates on whatever
 *          `memoryPath`/`shardDir` it is given. See
 *          `content/references/memory-shard-convention.md` for the full
 *          convention this file implements; that doc is the source of
 *          truth for WHY each guard exists, this file only implements them.
 *          Adapted from an unreviewed, unmerged reference implementation at
 *          authentic8/scripts/regenerate-memory.mjs - re-derived and
 *          re-tested here, not ported verbatim (see module history).
 *
 * Public API: splitEntries, compile, compileFromRecords, parseShardFile,
 *   buildFrontmatter, deriveSlug, deriveDescription, deriveDateForFilename,
 *   fillSequenceRun, assignSequencesForUnresolved, extractLines,
 *   findLostLines, findPermutedLines, readPreamble, readEntryRecords,
 *   compileFromDir, writeFileAtomic, splitCommand, regenerateCommand,
 *   PREAMBLE_FILENAME, SEQUENCE_GAP, BULK_ORPHAN_THRESHOLD.
 *
 * Upstream deps: Node built-ins only (fs, path, crypto). Zero npm
 *   dependencies, matching bin/ds-wrap-acquire-lock /
 *   bin/ds-wrap-release-lock's house style - this must run standalone from
 *   a bare `node` in any consumer project, which has no guaranteed
 *   node_modules of its own.
 *
 * Downstream consumers: bin/ds-memory-shard (CLI). NOTHING in
 *   content/commands or content/agents calls this yet - DS-221 Unit 1 ships
 *   the compiler only, with `memory_shard_mode` defaulting `false`. Writer
 *   wiring (/ds-wrap Part E, wrap-ticket, /ds-memory-update) is later units'
 *   scope.
 *
 * Failure modes: `regenerateCommand` REFUSES and writes nothing whenever the
 *   current `memoryPath` contains any physical line absent from the freshly
 *   compiled output (entry-loss guard, multiset comparison - see
 *   findLostLines), or when zero lines are lost but their relative order
 *   would change (reordering guard - see findPermutedLines). Both refusals
 *   are overridden by `allowRemoval: true`. `splitCommand` refuses to
 *   re-split an existing non-empty shard directory without `force: true`,
 *   and refuses to delete more than BULK_ORPHAN_THRESHOLD orphaned shard
 *   files without `allowRemoval: true` even under `force`. `splitCommand`
 *   stages its full reconciled output and round-trip-verifies it BEFORE
 *   touching any real shard file, and re-verifies again after committing;
 *   a post-commit verification failure throws a distinct loud error rather
 *   than silently reporting success. Every real-file write in this module
 *   (writeFileAtomic, and the shard/preamble writes inside splitCommand) is
 *   stage-then-rename, never a direct write - a crash mid-write cannot
 *   truncate the target.
 *
 * Performance: standard. Single-directory reads and small-file compiles;
 *   no indexing, no network, no subprocess.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

/** Reserved shard filename holding the compiled file's verbatim preamble
 * (everything before the first top-level "- " entry line). Written by
 * `split`, read by `regenerate` - not a fact shard, carries no frontmatter. */
const PREAMBLE_FILENAME = '_preamble.md';

/** Gap between consecutive `sequence` values assigned at split time. Leaves
 * 999 unused integers between any two originally-adjacent entries so a
 * later insertion never requires renumbering the rest of the corpus - see
 * content/references/memory-shard-convention.md "Sort key". */
const SEQUENCE_GAP = 1000;

/** Above this many orphaned shard files, `split` refuses to delete them
 * without an explicit `allowRemoval`, even under `force`. Ordinary
 * reconciliation (one hand-edited entry) removes 0-1 orphans and stays
 * automatic; a larger number signals drift wider than a single edit and is
 * worth a human's attention before it happens silently. */
const BULK_ORPHAN_THRESHOLD = 3;

/**
 * Fills `count` strictly-increasing `sequence` values in the open interval
 * `(leftBound, rightBound)` - `rightBound === null` means unbounded above.
 * Prefers full SEQUENCE_GAP-wide spacing anchored just below `rightBound`
 * when there is room; falls back to even bisection of the available span;
 * throws only when even bisection cannot produce `count` distinct integers
 * in the interval (an exhausted local gap).
 */
function fillSequenceRun(leftBound, rightBound, count) {
  if (rightBound == null) {
    return Array.from({ length: count }, (_, k) => leftBound + (k + 1) * SEQUENCE_GAP);
  }
  const span = rightBound - leftBound;
  if (span > count * SEQUENCE_GAP) {
    return Array.from({ length: count }, (_, k) => rightBound - (count - k) * SEQUENCE_GAP);
  }
  const step = Math.floor(span / (count + 1));
  if (step < 1) {
    throw new Error(
      `fillSequenceRun: sequence gap between neighboring shards (${leftBound} and ${rightBound}) is ` +
        `exhausted - cannot fit ${count} new/edited ${count === 1 ? 'entry' : 'entries'} between them. ` +
        'Manually widen the gap (edit the neighboring shards\' `sequence` frontmatter fields), then re-run split --force.',
    );
  }
  return Array.from({ length: count }, (_, k) => leftBound + (k + 1) * step);
}

/**
 * Mutates `resolved` in place, assigning `.sequence` to every entry NOT
 * already matched to an existing unchanged shard (`.reused === false`).
 * Walks the list once, grouping consecutive unresolved runs between their
 * nearest resolved neighbors (or the array boundary) and calling
 * `fillSequenceRun` once per run - this is what guarantees an unchanged
 * entry's `sequence` is genuinely untouched on a re-split.
 */
function assignSequencesForUnresolved(resolved) {
  let i = 0;
  while (i < resolved.length) {
    if (resolved[i].reused) {
      i++;
      continue;
    }
    let j = i;
    while (j < resolved.length && !resolved[j].reused) j++;
    const leftBound = i > 0 ? resolved[i - 1].sequence : 0;
    const rightBound = j < resolved.length ? resolved[j].sequence : null;
    const values = fillSequenceRun(leftBound, rightBound, j - i);
    for (let k = 0; k < values.length; k++) {
      resolved[i + k].sequence = values[k];
    }
    i = j;
  }
}

/**
 * Splits `fullText` at every line starting "- " into a preamble plus an
 * ordered array of entry-body strings. Each body carries its own trailing
 * separator baked in (whatever blank lines immediately followed it in the
 * source, up to but not including the next entry) - see the convention
 * doc's "Compile" rule: the compiler never inserts a separator itself.
 */
function splitEntries(fullText) {
  const lines = fullText.split('\n');
  const firstEntryIdx = lines.findIndex((l) => l.startsWith('- '));
  if (firstEntryIdx === -1) {
    throw new Error('splitEntries: no line starting with "- " found - cannot locate the first entry boundary');
  }
  // BUG FIX (Skeptic Minor): when firstEntryIdx === 0 (the file starts at
  // column 0 with "- ", i.e. genuinely no preamble at all), preambleLines
  // is [] and an UNCONDITIONAL "+ '\n'" would fabricate a spurious leading
  // blank line that was never in the original file, breaking
  // byte-identity. Only append the separator when there IS a preamble.
  const preambleLines = lines.slice(0, firstEntryIdx);
  const preamble = preambleLines.length > 0 ? preambleLines.join('\n') + '\n' : '';

  const cutPoints = [];
  for (let i = firstEntryIdx; i < lines.length; i++) {
    if (lines[i].startsWith('- ')) cutPoints.push(i);
  }

  const entries = [];
  for (let k = 0; k < cutPoints.length; k++) {
    const start = cutPoints[k];
    const end = k + 1 < cutPoints.length ? cutPoints[k + 1] : lines.length;
    const entryLines = lines.slice(start, end);
    const isLast = k === cutPoints.length - 1;
    const body = entryLines.join('\n') + (isLast ? '' : '\n');
    entries.push(body);
  }

  return { preamble, entries };
}

/** Concatenates shard bodies in the given order with NO separator inserted
 * - separation, where it exists, is already inside each body. Order is the
 * caller's job (see compileFromRecords). */
function compile(preamble, orderedBodies) {
  return preamble + orderedBodies.join('');
}

/** Sorts records by `sequence` (never by array/enumeration order) and
 * compiles against `preamble`. Refuses on a duplicate `sequence` value. */
function compileFromRecords(records, preamble) {
  if (typeof preamble !== 'string') {
    throw new Error('compileFromRecords: preamble is required (pass the contents of _preamble.md)');
  }
  const seen = new Map();
  for (const r of records) {
    if (seen.has(r.sequence)) {
      throw new Error(
        `compileFromRecords: duplicate sequence ${r.sequence} (files "${seen.get(r.sequence)}" and "${r.file}")`,
      );
    }
    seen.set(r.sequence, r.file);
  }
  const sorted = [...records].sort((a, b) => a.sequence - b.sequence);
  return compile(preamble, sorted.map((r) => r.body));
}

/** Parses a shard file's frontmatter. Extracts `sequence` and
 * `metadata.type` (required, validated) plus `body` (everything after the
 * closing `---`). NOT used for `_preamble.md`, which has no frontmatter. */
function parseShardFile(text, fileLabel) {
  const m = text.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!m) {
    throw new Error(`parseShardFile: ${fileLabel}: no "---"-delimited frontmatter block found`);
  }
  const [, frontmatter, body] = m;
  const seqMatch = frontmatter.match(/^sequence:\s*(-?\d+)\s*$/m);
  if (!seqMatch) {
    throw new Error(`parseShardFile: ${fileLabel}: missing or non-integer "sequence" field in frontmatter`);
  }
  const typeMatch = frontmatter.match(/^\s*type:\s*(\S.*)$/m);
  if (!typeMatch) {
    throw new Error(`parseShardFile: ${fileLabel}: missing "metadata.type" field in frontmatter`);
  }
  return { sequence: Number(seqMatch[1]), type: typeMatch[1].trim(), body };
}

/** Builds the frontmatter block per content/references/memory-shard-convention.md.
 * `description` is JSON-escaped into a YAML double-quoted scalar (a valid
 * subset for the characters JSON.stringify ever emits), so this needs no
 * YAML library dependency. */
function buildFrontmatter({ name, description, type, sequence }) {
  const lines = [
    '---',
    `name: ${name}`,
    `description: ${JSON.stringify(description)}`,
    'metadata:',
    `  type: ${type}`,
    `sequence: ${sequence}`,
    'supersedes: []',
    'superseded_by: null',
    '---',
    '',
  ];
  return lines.join('\n');
}

/** Mechanical (no semantic judgment) slug derivation: the first
 * ticket-shaped reference anywhere in the entry (a generic `PREFIX-123`
 * pattern - never a project-specific ticket prefix, per the universality
 * constraint), else "session", lowercased, plus an 8-hex-char content hash
 * of the whole entry body. Deliberately CONTENT-derived, never
 * position-derived, so inserting or renumbering entries never renames a
 * file. The ticket segment is a scanning aid only, not an attribution
 * claim - an entry that merely mentions the ticket in passing still gets
 * that segment. */
function deriveSlug(entryBody) {
  const ticketMatch = entryBody.match(/\b([A-Z]{2,10}-\d+)\b/);
  const base = ticketMatch ? ticketMatch[1].toLowerCase() : 'session';
  const hash = crypto.createHash('sha256').update(entryBody, 'utf8').digest('hex').slice(0, 8);
  return `${base}-${hash}`;
}

/** Mechanical (no semantic judgment) one-line description: the entry's own
 * opening line, bullet marker and markdown bold/code markers stripped,
 * truncated. A text transform of the entry's own words, not a
 * hand-authored summary. */
function deriveDescription(entryBody) {
  const firstLine = entryBody.split('\n')[0] || '';
  let text = firstLine.replace(/^- /, '').replace(/\*\*/g, '').replace(/`/g, '').trim();
  const MAX = 180;
  if (text.length > MAX) text = `${text.slice(0, MAX - 1).trimEnd()}…`;
  return text;
}

/** Extracts a "YYYY-MM-DD" date for the filename's human-scanning date
 * segment (NOT the sort key - see "Sort key" in the convention doc).
 * Looks for the pattern anywhere in the entry's first line; falls back to
 * "0000-00-00" (never throws) when none is found, since the convention is
 * deliberately format-agnostic across projects whose MEMORY.md entries may
 * not all open with a bold date the way this repo's own historically has. */
function deriveDateForFilename(entryBody) {
  const firstLine = entryBody.split('\n')[0] || '';
  const m = firstLine.match(/(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : '0000-00-00';
}

/** Every physical line in `text`, in order - the unit the entry-loss guard
 * operates on. Covers the WHOLE file (preamble, heading, entry first
 * lines, continuation lines, blank separators), not just "- "-prefixed
 * lines, since splitEntries explicitly supports multi-line entries and the
 * preamble sits directly on the designed header-edit path. */
function extractLines(text) {
  return text.split('\n');
}

/** Lines present in `currentText` but absent from `compiledText`, computed
 * as MULTISET containment (never set membership, never substring
 * containment) so a duplicate blank/separator line is matched correctly
 * and a line that legitimately appears fewer times in the compiled output
 * is still flagged lost. A COUNT check would pass when one line's content
 * is swapped for another while the count stays constant; this does not,
 * and a substring check would silently treat reordered/partial content as
 * present, which this also does not. */
function findLostLines(currentText, compiledText) {
  const compiledCounts = new Map();
  for (const l of extractLines(compiledText)) {
    compiledCounts.set(l, (compiledCounts.get(l) || 0) + 1);
  }
  const lost = [];
  for (const l of extractLines(currentText)) {
    const remaining = compiledCounts.get(l) || 0;
    if (remaining > 0) {
      compiledCounts.set(l, remaining - 1);
    } else {
      lost.push(l);
    }
  }
  return lost;
}

/**
 * True when `compiledText` contains every line of `currentText` (by
 * multiset - i.e. findLostLines returns []) but in a DIFFERENT relative
 * order. findLostLines' multiset containment is deliberately order-blind,
 * so a pure reordering (e.g. a hand-edited shard `sequence` that moves an
 * entry past a neighbor, as opposed to a legitimate insertion into a gap)
 * loses zero lines and would sail through that guard silently - this is a
 * SEPARATE check, meant to run only after findLostLines has already
 * confirmed nothing was lost.
 *
 * Implementation: greedily matches each line of `currentText`, in order,
 * to the EARLIEST occurrence of that same line in `compiledText` that sits
 * STRICTLY AFTER the previously-matched index - a per-line cursor into
 * that line's own ascending occurrence-index list, not a shift()-based
 * queue (a shift() would take the earliest globally-unconsumed occurrence,
 * which can sit BEFORE the current position for a repeated line and
 * falsely read as going backward). If no occurrence exists strictly after
 * the previous match, the relative order changed.
 */
function findPermutedLines(currentText, compiledText) {
  const indexQueues = new Map();
  extractLines(compiledText).forEach((l, idx) => {
    if (!indexQueues.has(l)) indexQueues.set(l, []);
    indexQueues.get(l).push(idx);
  });

  const cursor = new Map();
  let lastIndex = -1;
  for (const l of extractLines(currentText)) {
    const arr = indexQueues.get(l);
    if (!arr || arr.length === 0) {
      // Should be unreachable if findLostLines was already checked empty -
      // fail safe (treat as permuted) rather than crash.
      return true;
    }
    let i = cursor.get(l) || 0;
    while (i < arr.length && arr[i] <= lastIndex) i++;
    if (i >= arr.length) return true;
    lastIndex = arr[i];
    cursor.set(l, i + 1);
  }
  return false;
}

/** Reads `_preamble.md` from `dir`. Fails loud (never returns a default) if
 * missing - `regenerate` cannot run before `split` has produced one. */
function readPreamble(dir) {
  const p = path.join(dir, PREAMBLE_FILENAME);
  try {
    return fs.readFileSync(p, 'utf8');
  } catch (err) {
    if (err && err.code === 'ENOENT') {
      throw new Error(
        `readPreamble: ${p} not found - a shard directory must contain "${PREAMBLE_FILENAME}" ` +
          '(written by `split`) before `regenerate` can run',
      );
    }
    throw err;
  }
}

/** Reads every fact shard in `dir` (everything except `_preamble.md` and
 * dotfiles), parsing frontmatter and validating required fields. Refuses
 * loudly on any file that is neither a dotfile nor ends ".md". Returns
 * records in WHATEVER order `readdirSync` returns them - sorting is
 * compileFromRecords' job, never this function's. */
function readEntryRecords(dir) {
  const names = fs.readdirSync(dir);
  const records = [];
  for (const name of names) {
    if (name === PREAMBLE_FILENAME) continue;
    if (name.startsWith('.')) continue; // OS/editor artifacts, not shard content
    if (!name.endsWith('.md')) {
      throw new Error(
        `readEntryRecords: unexpected non-".md" file in shard dir: "${name}" - refusing rather than ` +
          'silently ignoring it (a hand-added file with the wrong extension would otherwise compile away with no warning)',
      );
    }
    const text = fs.readFileSync(path.join(dir, name), 'utf8');
    const { sequence, type, body } = parseShardFile(text, name);
    records.push({ file: name, sequence, type, body, text });
  }
  return records;
}

function compileFromDir(dir) {
  const preamble = readPreamble(dir);
  const records = readEntryRecords(dir);
  return compileFromRecords(records, preamble);
}

/** Writes `content` to `targetPath` via stage-then-rename, never a direct
 * write - a crash or full disk mid-write leaves either the old
 * `targetPath` intact or the new one fully written, never a truncated
 * hybrid. Staged as a SIBLING of `targetPath` (never a fixed temp dir) so
 * an EXDEV rename failure across filesystems can never happen here. */
function writeFileAtomic(targetPath, content) {
  // Skeptic Minor fix (round 2 correction: the round-1 comment overstated
  // this by conflating "cannot avoid an orphan tmp file at all" with
  // "cannot avoid an orphan at the consumer's repo ROOT" - the staging
  // location IS choosable; this function deliberately keeps it as a
  // sibling of `targetPath` anyway, the same discipline splitCommand's own
  // staging dir uses, so a crash mid-rename can never leave a truncated
  // hybrid of old and new content). `targetPath` is typically a project's
  // MEMORY.md at the repo root, which is git-tracked (not ignored) - so a
  // sibling `.tmp-<pid>-<ts>` file is itself outside any ignore rule. A
  // SIGKILL between writeFileSync and renameSync still leaves the tmp file
  // regardless of where it is staged - that crash-proofing gap is real and
  // inherent to any tmp+rename scheme, sibling-staged or not - but a
  // rename failure that DOES throw synchronously (permissions, disk full,
  // EXDEV) is now cleaned up rather than leaving an orphaned tmp file as a
  // side effect of the failure.
  const tmpPath = `${targetPath}.tmp-${process.pid}-${Date.now()}`;
  fs.writeFileSync(tmpPath, content, 'utf8');
  try {
    fs.renameSync(tmpPath, targetPath);
  } catch (err) {
    try {
      fs.rmSync(tmpPath, { force: true });
    } catch (_) {
      /* best-effort cleanup; surface the original rename error below */
    }
    throw err;
  }
}

function firstDifferenceOffset(a, b) {
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i++) {
    if (a[i] !== b[i]) return i;
  }
  return len;
}

function describeLostLines(lost) {
  const MAX_SHOWN = 10;
  const preview = lost.slice(0, MAX_SHOWN).map((l) => {
    const t = l.length > 100 ? `${l.slice(0, 99)}…` : l;
    return `  ${t}`;
  });
  const more = lost.length > MAX_SHOWN ? `\n  ...and ${lost.length - MAX_SHOWN} more` : '';
  return (
    `${lost.length} ${lost.length === 1 ? 'line' : 'lines'} present in the current file would be LOST ` +
    `by this regenerate:\n${preview.join('\n')}${more}`
  );
}

/** Names the SAFE remedy for the common case (a hand-appended entry not
 * yet captured into a shard: `split --force` is safe there, since
 * appending only ADDS a shard, never removes one), and warns against the
 * one case where that same command is actively harmful: if any lost line
 * looks like preamble/header content (not an entry bullet), `split
 * --force` would re-derive the preamble from the CURRENT memoryPath - which
 * still has the OLD header at that point - and silently revert a
 * `_preamble.md` edit made ahead of a `regenerate`. */
function suggestRemedyForLoss(lost) {
  const looksLikePreambleOrHeader = lost.some((l) => l.trim() !== '' && !l.startsWith('- '));
  if (looksLikePreambleOrHeader) {
    return (
      'Some of the lost lines are NOT entry bullets (they look like preamble/header content). If you just ' +
      'edited `_preamble.md` by hand, do NOT run `split --force` here - it re-derives the preamble from the ' +
      'CURRENT file and would silently REVERT your edit. Re-run `regenerate --allow-removal` instead to ' +
      'commit the new header (only after confirming no ENTRY content is among the lost lines above).\n' +
      'If instead the file has a hand-appended entry not yet captured into a shard, `split --force` remains ' +
      'safe for that case (it only ADDS a shard, it does not remove any).'
    );
  }
  return (
    'This usually means the file has a hand-appended entry not yet captured into a shard - re-run ' +
    '`split --force` to pick it up (safe: appending only adds a shard, it does not remove any), then ' +
    '`regenerate` again.'
  );
}

/**
 * Splits `memoryPath` into `shardDir`, reconciling against any existing
 * shard set. See the module manifest above for the full failure-mode
 * contract (re-split refusal, bulk-orphan-deletion gate, stage-then-verify
 * commit). Returns a summary object; throws on every refusal path.
 */
function splitCommand({ shardDir, memoryPath, force, allowRemoval }) {
  const original = fs.readFileSync(memoryPath, 'utf8');
  const { preamble, entries } = splitEntries(original);

  let shardDirExists = false;
  try {
    fs.accessSync(shardDir);
    shardDirExists = true;
  } catch {
    shardDirExists = false;
  }
  const oldRecords = shardDirExists ? readEntryRecords(shardDir) : [];

  if (oldRecords.length > 0 && !force) {
    throw new Error(
      `split: ${shardDir} already contains ${oldRecords.length} shard file(s); refusing to re-split ` +
        'without --force. Pass --force to reconcile the shard set with the current file (unchanged ' +
        'entries keep their existing filename/sequence, new/edited entries get fresh ones, and shards ' +
        'for entries that no longer exist are removed).',
    );
  }

  // Match each current entry to an existing shard by CONTENT (never by
  // position) - a queue per body text so N old shards sharing the same
  // body text are matched one-to-one, in order, never double-borrowed.
  const oldByBody = new Map();
  for (const r of oldRecords) {
    if (!oldByBody.has(r.body)) oldByBody.set(r.body, []);
    oldByBody.get(r.body).push(r);
  }

  const resolved = entries.map((body) => {
    const q = oldByBody.get(body);
    if (q && q.length > 0) {
      const reused = q.shift();
      return { body, reused: true, filename: reused.file, sequence: reused.sequence, text: reused.text };
    }
    return { body, reused: false, filename: null, sequence: null, text: null };
  });

  assignSequencesForUnresolved(resolved);

  for (const r of resolved) {
    if (!r.reused) {
      const date = deriveDateForFilename(r.body);
      const slug = deriveSlug(r.body);
      const description = deriveDescription(r.body);
      r.filename = `${date}-${slug}.md`;
      r.text = buildFrontmatter({ name: slug, description, type: 'project', sequence: r.sequence }) + r.body;
    }
  }

  const seenNames = new Set();
  for (const r of resolved) {
    if (seenNames.has(r.filename)) {
      throw new Error(
        `split: duplicate shard filename generated: ${r.filename} - two entries hashed to the same ` +
          'content-derived slug; astronomically unlikely for real data and signals a bug or a byte-identical duplicate entry',
      );
    }
    seenNames.add(r.filename);
  }

  const desiredFilenames = new Set(resolved.map((r) => r.filename));
  const orphanFiles = oldRecords.filter((r) => !desiredFilenames.has(r.file)).map((r) => r.file);

  if (orphanFiles.length > BULK_ORPHAN_THRESHOLD && !allowRemoval) {
    throw new Error(
      `split: REFUSING - reconciling would remove ${orphanFiles.length} shard file(s), more than the ` +
        `${BULK_ORPHAN_THRESHOLD}-file threshold for automatic removal:\n` +
        orphanFiles.map((f) => `  ${f}`).join('\n') +
        '\n\nThis usually means the shard directory and the compiled file have drifted further than a ' +
        'single hand-edit - confirm this is intended, then re-run split --force --allow-removal.\n' +
        `${shardDir} was NOT modified.`,
    );
  }

  // Stage the FULL reconciled state, verify, THEN commit. Staging is a
  // SIBLING of shardDir (never a fixed base path) so a shardDir on a
  // different filesystem never hits an EXDEV mid-commit rename.
  const stagingDir = path.join(
    path.dirname(shardDir),
    `${path.basename(shardDir)}-staging-${process.pid}-${Date.now()}`,
  );
  fs.mkdirSync(stagingDir, { recursive: true });

  fs.writeFileSync(path.join(stagingDir, PREAMBLE_FILENAME), preamble, 'utf8');
  for (const r of resolved) {
    fs.writeFileSync(path.join(stagingDir, r.filename), r.text, 'utf8');
  }

  const stagedCompiled = compileFromDir(stagingDir);
  if (stagedCompiled !== original) {
    const firstDiff = firstDifferenceOffset(stagedCompiled, original);
    throw new Error(
      'split: round-trip verification FAILED before any real shard file was touched - the reconciled ' +
        `shard set does not reproduce ${memoryPath} byte-for-byte. First divergence at byte offset ${firstDiff}. ` +
        `Compiled length=${stagedCompiled.length}, original length=${original.length}. ` +
        `Refusing to touch ${shardDir}. Staging directory left in place for inspection: ${stagingDir}`,
    );
  }

  fs.mkdirSync(shardDir, { recursive: true });
  for (const r of resolved) {
    fs.renameSync(path.join(stagingDir, r.filename), path.join(shardDir, r.filename));
  }
  fs.renameSync(path.join(stagingDir, PREAMBLE_FILENAME), path.join(shardDir, PREAMBLE_FILENAME));
  for (const orphan of orphanFiles) {
    fs.rmSync(path.join(shardDir, orphan), { force: true });
  }

  // Post-commit verification: read back the REAL shardDir, not the
  // (about-to-be-deleted) staging directory. Should be unreachable if the
  // pre-commit check passed; a failure here means the commit step itself
  // is buggy and needs a loud, distinct error rather than a false success.
  const committedCompiled = compileFromDir(shardDir);
  if (committedCompiled !== original) {
    throw new Error(
      `split: POST-COMMIT verification FAILED - ${shardDir} does not reproduce ${memoryPath} byte-for-byte ` +
        'after committing, even though the pre-commit staging check passed. This indicates a bug in the ' +
        'commit step itself. Manual inspection required; do not trust this shard directory.',
    );
  }

  fs.rmSync(stagingDir, { recursive: true, force: true });

  const reusedCount = resolved.filter((r) => r.reused).length;
  const newCount = resolved.length - reusedCount;
  return {
    entryCount: resolved.length,
    reusedCount,
    newCount,
    orphansRemoved: orphanFiles.length,
    orphanFiles,
  };
}

/**
 * Recompiles `memoryPath` from `shardDir`. THROWS (never returns having
 * silently done nothing) on every refusal path. Returns
 * `{ wrote: boolean, matched?: boolean }` on success so callers can
 * distinguish a write from a matched --check no-op.
 */
function regenerateCommand({ shardDir, memoryPath, check, allowRemoval }) {
  const compiled = compileFromDir(shardDir);

  // Skeptic Minor fix (near-Major per reviewer): a bare `catch {}` here
  // swallowed EVERY read error, not just "file absent". A non-ENOENT
  // failure (permissions, an I/O error, memoryPath being a directory)
  // would silently disable BOTH the entry-loss and reordering guards
  // (current stays null, so neither guard's `current != null` branch ever
  // runs) and then proceed to write - the opposite of this function's
  // whole safety contract. Only ENOENT ("absent memoryPath - nothing to
  // lose, nothing to check against") is legitimately swallowed; anything
  // else propagates.
  let current = null;
  try {
    current = fs.readFileSync(memoryPath, 'utf8');
  } catch (err) {
    if (!err || err.code !== 'ENOENT') {
      throw err;
    }
  }

  if (current != null && !allowRemoval) {
    const lost = findLostLines(current, compiled);
    if (lost.length > 0) {
      throw new Error(
        `regenerate: REFUSING - ${describeLostLines(lost)}\n\n` +
          `${suggestRemedyForLoss(lost)}\n` +
          'If this removal is deliberate (a pruning PR, or a preamble/header edit), re-run with --allow-removal.\n' +
          `${memoryPath} was NOT modified.`,
      );
    }
    if (findPermutedLines(current, compiled)) {
      throw new Error(
        'regenerate: REFUSING - the compiled output would REORDER existing lines relative to the current ' +
          `${memoryPath} (no content is lost, but the relative order changed). This usually means a shard's ` +
          '`sequence` value was hand-edited in a way that moves it past a neighbor, rather than merely ' +
          'inserting a NEW entry into a gap - re-run `split --force` to regenerate the shard set from the ' +
          'current file\'s own order (if the current file is correct and the shard edit is the mistake). If the ' +
          'new order is genuinely intended, re-run with --allow-removal.\n' +
          `${memoryPath} was NOT modified.`,
      );
    }
  }

  if (check) {
    if (current === compiled) {
      return { wrote: false, matched: true };
    }
    const firstDiff = current == null ? 0 : firstDifferenceOffset(compiled, current);
    throw new Error(
      `regenerate --check: ${memoryPath} does NOT match the compiled output of ${shardDir} ` +
        `(first divergence at byte offset ${firstDiff}). Run without --check to overwrite.`,
    );
  }

  writeFileAtomic(memoryPath, compiled);
  return { wrote: true };
}

module.exports = {
  PREAMBLE_FILENAME,
  SEQUENCE_GAP,
  BULK_ORPHAN_THRESHOLD,
  fillSequenceRun,
  assignSequencesForUnresolved,
  splitEntries,
  compile,
  compileFromRecords,
  parseShardFile,
  buildFrontmatter,
  deriveSlug,
  deriveDescription,
  deriveDateForFilename,
  extractLines,
  findLostLines,
  findPermutedLines,
  readPreamble,
  readEntryRecords,
  compileFromDir,
  writeFileAtomic,
  splitCommand,
  regenerateCommand,
};
