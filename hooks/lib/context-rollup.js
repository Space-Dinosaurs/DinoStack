#!/usr/bin/env node

/**
 * Purpose: Single source of truth for the per-session SHARD + derived ROLLUP
 *          model that replaces whole-file `.agentic/context.md` writes (DS-107).
 *          Every per-turn writer now writes its own `.agentic/context.d/<session_id>.md`
 *          shard and then regenerates `.agentic/context.md` as a PURE FUNCTION of
 *          (`.agentic/_wrap.md`, shard set). Because the rollup is derivable, a
 *          lost update SELF-HEALS on the next turn instead of losing data, which
 *          is what licenses the rollup write being deliberately LOCK-FREE.
 *
 *          The bug this replaces: `.agentic/wrap/lock` was CHECKED by two Stop-hook
 *          writers and ACQUIRED by neither, so it provided zero mutual exclusion
 *          between them (D2); a third writer ignored it entirely (D3); and an
 *          orphaned lock silently suppressed every write for 10.3 hours (D1,
 *          fixed in wrap-marker.js). 49 writes across 6 sessions were discarded.
 *
 * Public API (CommonJS, all exported on module.exports):
 *   Constants:
 *     ACTIVITY_SENTINEL   - '\n\n---\n\n## Session Activity\n' (unchanged, the
 *                           existing boundary between the curated and derived regions)
 *     DERIVED_MARKER      - the marker written in the ACTIVITY-REGION HEADER, never
 *                           in the file header (see MARKER PLACEMENT below)
 *     SHARD_RETENTION     - 10 most recent shards
 *   Paths:
 *     rollupPath(cwd)     -> .agentic/context.md      (derived; never hand-edited)
 *     shardDirPath(cwd)   -> .agentic/context.d/
 *     shardPath(cwd, sid) -> .agentic/context.d/<sid>.md
 *     curatedPath(cwd)    -> .agentic/_wrap.md        (owned by /ds-wrap + conductor)
 *     foreignPath(cwd)    -> .agentic/_foreign.md     (preserved unported-adapter writes)
 *   Shard writes (atomic, session-private):
 *     writeShard(cwd, sessionId, body) -> boolean
 *     appendToShard(cwd, sessionId, text) -> boolean
 *   Composition / regeneration:
 *     snapshotShards(cwd) -> [{sessionId, path, mtimeNs, size}]  (mtime DESC, sid ASC)
 *     composeRollup(cwd, shards, opts) -> string
 *     regenerateRollup(cwd, opts) -> {written, attempts, degraded, migrated, foreign}
 *   Migration / classification helpers (exported for tests):
 *     findActivityRegionIndex(text) -> number
 *     stripDerivedBlocks(text) -> string
 *     migrateIfNeeded(cwd) -> boolean
 *     stuckLockBanner(cwd, opts) -> string|null
 *
 * MARKER PLACEMENT is load-bearing, not cosmetic. The derived marker goes in the
 * ACTIVITY-REGION header line (immediately after the sentinel) and NEVER in the
 * file header. The OpenCode plugin's legacy strip-and-append PRESERVES the file
 * header while replacing the activity region, so a marker in the file header
 * would survive a foreign write, the composer would conclude "this is mine",
 * skip foreign-preservation, and destroy that writer's block.
 *
 * TWO WINDOWS ON ONE FILE is the accepted cost of coexisting with /ds-wrap:
 * `_wrap.md` owns everything up to the sentinel (including `## Recent Focus` and
 * its 10-slot rolling label window, whose algorithm is retained VERBATIM in
 * content/references/wrap-context-format.md); this composer owns everything from
 * the sentinel onward and regenerates it wholesale. The composer MUST NEVER write
 * `## Recent Focus` - that is curated content and a derived, idempotently
 * regenerated file cannot own it without destroying either the curation or the
 * idempotence that licenses lock-freedom.
 *
 * NO TIMESTAMP APPEARS IN COMPOSER-GENERATED TEXT. Two successive regens over an
 * unchanged shard set MUST be byte-identical; embedding a clock read would void
 * that idempotence and with it the argument for writing without a lock. Dates
 * live inside shard bodies, which are inputs written once per turn, not outputs.
 *
 * COMPARE-AND-RETRY on the rollup write closes the interleaving
 *   X shard -> X snapshot -> Y shard -> Y snapshot -> Y rollup -> X rollup
 * whose final rollup would otherwise OMIT Y (no permanent loss - Y's shard
 * survives - but the file every session reads first would be short a session,
 * possibly across the session boundary). Retry fires only when the shard set
 * changed under the write, so an unchanged set still yields byte-identical output.
 *
 * Upstream deps: Node built-ins only (fs, path). Requires ./wrap-marker.js for
 *                the abandoned/stuck-lock banner ONLY (wrap-marker does not
 *                require this module, so there is no cycle). Reads/writes under
 *                [cwd]/.agentic/: context.md, context.d/<sid>.md, _wrap.md,
 *                _foreign.md (+ pid+uuid-suffixed .tmp staging files).
 *
 * Downstream consumers: hooks/stop-context.js (all four of its former context.md
 *                       writer sites), .opencode/plugins/session-context.ts (an
 *                       independent TypeScript port - that file is hand-authored
 *                       and regenerated by no build script), bin/agentic-migrate
 *                       (writes a notices shard).
 *
 * Failure modes: every exported function is FAIL-OPEN and never throws to a hook.
 *                A shard write failure loses one turn of one session's activity
 *                and self-heals next turn. A rollup write failure leaves the
 *                previous rollup in place; the next turn regenerates it from the
 *                same shard set. Three failed compare-and-retry attempts emit a
 *                bounded-degradation banner rather than looping.
 *
 * Performance: synchronous fs only; one readdir plus one stat per shard per
 *              regen (retention-capped), no git, no network, no subprocess.
 */

'use strict';

const fs = require('fs');
const path = require('path');

let wrapMarker = null;
try {
  wrapMarker = require('./wrap-marker.js');
} catch (_) {
  wrapMarker = null; // banner degrades to absent; never fatal
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Unchanged from the legacy writers - the existing curated/derived boundary. */
const ACTIVITY_SENTINEL = '\n\n---\n\n## Session Activity\n';

/** Written in the ACTIVITY-REGION header, never the file header. */
const DERIVED_MARKER = '<!-- agentic:derived-activity-region v1 -->';

/** Matches the 1-to-10 rolling label window `_wrap.md` already uses. */
const SHARD_RETENTION = 10;

const SHARD_DIR_NAME = 'context.d';
const SHARD_SUFFIX = '.md';

/** Max compare-and-retry attempts before emitting the degradation banner. */
const MAX_ROLLUP_ATTEMPTS = 3;

/**
 * Signatures that identify the line(s) immediately following a sentinel as a
 * DERIVED ACTIVITY REGION rather than curated prose that merely quotes the
 * sentinel bytes. This distinction is what lets a `/ds-wrap` body containing a
 * verbatim `\n\n---\n\n## Session Activity\n` (a session wrapping while working
 * on this very ticket writes exactly that) migrate WITHOUT truncation.
 */
const ACTIVITY_REGION_SIGNATURES = [
  DERIVED_MARKER,
  '<!-- agentic:derived-activity-region', // any future marker version
  '*Derived from .agentic/context.d/',
  '*Auto-appended by Stop hook',
  '*Auto-appended by session idle plugin',
  '*Auto-appended by /ds-wrap finalization',
  '*Auto-updated by session idle plugin',
  '### Recent Messages',
];

/** Leading text of the machine-derived one-time notices stripped on migration. */
const DERIVED_NOTICE_SIGNATURES = [
  'CAPTURE-GAP:',
  '[agentic-engineering] No developer identity set.',
  'WRAP-LOCK-STUCK:',
  '[scaffolding-sync] WARNING:',
];

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

function agenticDir(cwd) {
  return path.join(cwd, '.agentic');
}

function rollupPath(cwd) {
  return path.join(agenticDir(cwd), 'context.md');
}

function shardDirPath(cwd) {
  return path.join(agenticDir(cwd), SHARD_DIR_NAME);
}

function curatedPath(cwd) {
  return path.join(agenticDir(cwd), '_wrap.md');
}

function foreignPath(cwd) {
  return path.join(agenticDir(cwd), '_foreign.md');
}

/**
 * Sanitize a session id for use as a shard filename. Same discipline as
 * wrap-marker's safeSessionId (the proven `pending-<session_id>.json` pattern
 * this design extends): reject path separators and traversal so a hostile id
 * can never escape .agentic/context.d/.
 */
function safeSessionId(sessionId) {
  if (typeof sessionId !== 'string') return null;
  const trimmed = sessionId.trim();
  if (!trimmed) return null;
  if (trimmed.includes('/') || trimmed.includes('\\') || trimmed.includes('..')) return null;
  return trimmed;
}

function shardPath(cwd, sessionId) {
  const sid = safeSessionId(sessionId);
  if (!sid) return null;
  return path.join(shardDirPath(cwd), sid + SHARD_SUFFIX);
}

/**
 * Suffixed temp path: pid + a random component, so two concurrent processes
 * never share a staging file. Deliberately NOT the fixed `<path>.tmp` pattern
 * used elsewhere in hooks/ (tracked separately as DS-109) - this unit adds no
 * new instances of that hazard.
 */
function tmpPathFor(target) {
  return target + '.tmp.' + process.pid + '.' + Math.random().toString(36).slice(2, 10);
}

/** Atomic write via suffixed tmp + rename. Fail-open: returns false. */
function atomicWrite(target, body) {
  const tmp = tmpPathFor(target);
  try {
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(tmp, body, 'utf8');
    fs.renameSync(tmp, target);
    return true;
  } catch (_) {
    try { fs.unlinkSync(tmp); } catch (_e) { /* tmp absent or never created */ }
    return false;
  }
}

function readIfPresent(p) {
  try {
    return fs.readFileSync(p, 'utf8');
  } catch (_) {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Shard writes (session-private; no lock needed, no cross-session collision)
// ---------------------------------------------------------------------------

/**
 * Write this session's shard, replacing its previous contents. The target is
 * SESSION-PRIVATE (keyed by session_id in the filename), and the harness
 * serializes turns within a session, so two writers can never collide here -
 * the identical invariant that makes `pending-<session_id>.json` safe.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {string} body
 * @returns {boolean}
 */
function writeShard(cwd, sessionId, body) {
  const p = shardPath(cwd, sessionId);
  if (!p) return false;
  return atomicWrite(p, typeof body === 'string' ? body : String(body == null ? '' : body));
}

/**
 * Append to this session's shard, creating it if absent. Used by the one-time
 * notice writers (identity nudge, capture-gap, scaffolding warnings) that
 * previously appended straight into the shared rollup - the D3 defect. Appending
 * to a session-private file is harmless regardless of lock state, which is why
 * their `!wrapLockHeld(cwd)` gates are dropped rather than kept.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {string} text
 * @returns {boolean}
 */
function appendToShard(cwd, sessionId, text) {
  const p = shardPath(cwd, sessionId);
  if (!p) return false;
  try {
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.appendFileSync(p, typeof text === 'string' ? text : String(text == null ? '' : text), 'utf8');
    return true;
  } catch (_) {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Shard set snapshot
// ---------------------------------------------------------------------------

/**
 * List the shard set with the metadata the compare-and-retry loop needs.
 *
 * Ordering is `(mtime_ns DESC, session_id ASC)`. The secondary key is MANDATORY,
 * not cosmetic: mtime granularity is undefined on 1-second-resolution and
 * network filesystems, and because retention keeps only the N most recent, a tie
 * changes BOTH the presentation order AND which shard is dropped. Without the
 * tiebreak two regens over an identical shard set could differ, voiding AC7.
 *
 * Fail-open: [] on any error.
 *
 * @param {string} cwd
 * @returns {Array<{sessionId: string, path: string, mtimeNs: string, size: number}>}
 */
function snapshotShards(cwd) {
  const dir = shardDirPath(cwd);
  let names;
  try {
    names = fs.readdirSync(dir);
  } catch (_) {
    return [];
  }
  const out = [];
  for (const name of names) {
    if (!name.endsWith(SHARD_SUFFIX)) continue;
    const sessionId = name.slice(0, -SHARD_SUFFIX.length);
    if (!safeSessionId(sessionId)) continue;
    const p = path.join(dir, name);
    try {
      // bigint:true is REQUIRED for mtimeNs - the default Stats object exposes
      // only float mtimeMs, whose precision is not enough to order two shard
      // writes inside the same millisecond.
      const st = fs.lstatSync(p, { bigint: true }); // no-follow: a symlinked shard is not ours
      if (st.isSymbolicLink() || !st.isFile()) continue;
      out.push({
        sessionId,
        path: p,
        // Zero-padded so plain string comparison equals numeric comparison.
        mtimeNs: String(st.mtimeNs).padStart(24, '0'),
        size: Number(st.size),
      });
    } catch (_) { /* shard vanished mid-scan; skip */ }
  }
  // (mtime_ns DESC, session_id ASC). The secondary key is MANDATORY - see the
  // function doc: a tie changes BOTH order and which shard retention drops.
  out.sort((a, b) => {
    if (a.mtimeNs !== b.mtimeNs) return a.mtimeNs < b.mtimeNs ? 1 : -1;
    return a.sessionId < b.sessionId ? -1 : (a.sessionId > b.sessionId ? 1 : 0);
  });
  return out;
}

/** Stable fingerprint of a shard snapshot, for the compare-and-retry equality test. */
function snapshotKey(shards) {
  return shards.map((s) => s.sessionId + ' ' + s.mtimeNs + ' ' + s.size).join('');
}

// ---------------------------------------------------------------------------
// Region classification
// ---------------------------------------------------------------------------

/** True when the text immediately following a sentinel looks like an activity region. */
function looksLikeActivityRegion(after) {
  const head = after.slice(0, 400);
  for (const sig of ACTIVITY_REGION_SIGNATURES) {
    if (head.indexOf(sig) !== -1) return true;
  }
  return false;
}

/**
 * Index of the ACTIVITY REGION's opening sentinel, or -1 when the text carries
 * no activity region at all.
 *
 * Scans for the LAST sentinel occurrence whose following content matches an
 * activity-region signature. LAST, not first, because the activity region is
 * ALWAYS the file tail: a curated body that QUOTES the sentinel would otherwise
 * be sliced in half - migration would seed a truncated `_wrap.md` and park the
 * curated remainder in a last-writer-wins `_foreign.md`, and in steady state the
 * composer would misdetect the remainder as foreign and REWRITE `_foreign.md`
 * every single turn, destroying a genuine unported-adapter write within one turn.
 *
 * The signature test is what makes the quoted-sentinel case safe even when the
 * quote is the LAST sentinel in the file (a curated body that quotes the
 * sentinel and has no real activity region yet): such a quote matches no
 * signature, so the function reports -1 and the whole body is treated as curated.
 *
 * @param {string} text
 * @returns {number}
 */
function findActivityRegionIndex(text) {
  if (typeof text !== 'string' || !text) return -1;
  let idx = text.lastIndexOf(ACTIVITY_SENTINEL);
  while (idx >= 0) {
    if (looksLikeActivityRegion(text.slice(idx + ACTIVITY_SENTINEL.length))) return idx;
    idx = idx > 0 ? text.lastIndexOf(ACTIVITY_SENTINEL, idx - 1) : -1;
  }
  return -1;
}

/** The second line of a body, or '' when there is none. */
function secondLine(text) {
  if (typeof text !== 'string') return '';
  const nl = text.indexOf('\n');
  if (nl < 0) return '';
  const rest = text.slice(nl + 1);
  const nl2 = rest.indexOf('\n');
  return nl2 < 0 ? rest : rest.slice(0, nl2);
}

/** True when a body carries the pinned `/ds-wrap` header contract on line 2. */
function isWrapAuthored(text) {
  return secondLine(text).startsWith('*Written by /ds-wrap');
}

/**
 * Remove machine-DERIVED content from a body that is about to be seeded into the
 * curated `_wrap.md`.
 *
 * Two classes are removed:
 *   1. Any ACTIVITY REGION found in the body - MARKED OR UNMARKED. Unmarked is
 *      exactly what every legacy writer and every unported adapter produces, so
 *      a marked-only strip would let stale activity content seed permanently
 *      into the curated file. That cruft would be IMMORTAL: `_wrap.md` is only
 *      ever merge-written by /ds-wrap Part A, and the strip-and-append path that
 *      used to clear it is deleted by this change.
 *   2. The one-time derived NOTICES (capture-gap, identity nudge, stuck-lock
 *      banner, scaffolding warning), which are observably present PRE-sentinel
 *      in real files - the sentinel is a HEADING boundary, not an OWNERSHIP
 *      boundary. Stripped blocks are DROPPED, not re-emitted: both notice
 *      families are sentinel-gated one-time nudges whose sentinels are already
 *      consumed, so re-emitting would double-nudge.
 *
 * Content that merely QUOTES a sentinel is preserved verbatim - see
 * findActivityRegionIndex.
 *
 * @param {string} text
 * @returns {string}
 */
function stripDerivedBlocks(text) {
  if (typeof text !== 'string' || !text) return '';
  let out = text;

  // 1. Activity regions, innermost-last: repeatedly cut the last signature-
  //    matched region until none remain.
  for (;;) {
    const i = findActivityRegionIndex(out);
    if (i < 0) break;
    out = out.slice(0, i);
  }

  // 2. Derived one-time notices. Each is written as `\n---\n<TEXT...>` and runs
  //    to the next `---` fence, the next top-level heading, or end of body.
  const lines = out.split('\n');
  const kept = [];
  for (let i = 0; i < lines.length; i++) {
    const isFence = lines[i].trim() === '---';
    if (!isFence) { kept.push(lines[i]); continue; }
    // Look ahead past blank lines for a derived-notice signature.
    let j = i + 1;
    while (j < lines.length && !lines[j].trim()) j++;
    const isNotice = j < lines.length
      && DERIVED_NOTICE_SIGNATURES.some((sig) => lines[j].startsWith(sig));
    if (!isNotice) { kept.push(lines[i]); continue; }
    // Skip the fence and the notice body.
    let k = j;
    while (k < lines.length && lines[k].trim() !== '---' && !lines[k].startsWith('## ')) k++;
    i = k - 1;
  }
  out = kept.join('\n');

  return out.replace(/\s+$/, '');
}

// ---------------------------------------------------------------------------
// Stuck-lock banner (bounded-degradation guarantee)
// ---------------------------------------------------------------------------

/**
 * Return the WRAP-LOCK-STUCK banner text, or null when there is nothing to say.
 *
 * The guarantee this implements: the banner rides the ROLLUP write, which is
 * structurally lock-independent, so it CANNOT be suppressed by the very lock it
 * is reporting. The observed failure - writes discarded AND nothing said, for 12
 * hours - is no longer a reachable state. Deliberately NOT gated on
 * `deferred_wrap_daemon`; gating it there would restore silence on the default
 * config, i.e. the original bug.
 *
 * Fires when the lock is abandoned, OR whenever it has simply been held longer
 * than STUCK_NOTICE_MS regardless of verdict - a genuinely long /ds-wrap is
 * worth surfacing too, and saying so costs one line.
 *
 * @param {string} cwd
 * @param {{abandonMs?: number, legacyAbandonMs?: number, stuckNoticeMs?: number}} [opts]
 * @returns {string|null}
 */
function stuckLockBanner(cwd, opts) {
  if (!wrapMarker) return null;
  try {
    const o = opts || {};
    const stuckMs = (typeof o.stuckNoticeMs === 'number' && o.stuckNoticeMs >= 0)
      ? o.stuckNoticeMs
      : wrapMarker.STUCK_NOTICE_MS;

    const v = wrapMarker.wrapLockVerdict(cwd);
    if (v.verdict === 'free') return null;

    const abandoned = wrapMarker.wrapLockAbandoned(cwd, o);
    const ageMs = (typeof v.ageMs === 'number') ? v.ageMs : null;
    const oldEnough = ageMs !== null && ageMs > stuckMs;
    if (!abandoned && !oldEnough) return null;

    const ageLabel = ageMs === null ? 'unknown' : Math.round(ageMs / 60000) + 'm';
    const state = abandoned ? 'ABANDONED' : 'held';
    return [
      '',
      '---',
      'WRAP-LOCK-STUCK: .agentic/wrap/lock has been ' + state + ' for ' + ageLabel
        + ' (role=' + (v.role || v.source || 'unknown') + ').',
      abandoned
        ? 'It carries no live holder. The next `agentic-wrap-acquire-lock` run clears it'
        : 'If no /ds-wrap is actually running, the next acquire will clear it once abandoned',
      'automatically; `agentic-wrap-release-lock` releases it now. This notice cannot be',
      'suppressed by the lock - context.md writes are lock-free and are NOT being lost.',
    ].join('\n') + '\n';
  } catch (_) {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Migration (runs once, before the first rollup write in a project)
// ---------------------------------------------------------------------------

/** Append to `_foreign.md`, creating it if absent. Fail-open. */
function preserveForeign(cwd, body) {
  if (typeof body !== 'string' || !body.trim()) return false;
  const p = foreignPath(cwd);
  const prior = readIfPresent(p);
  const sep = prior && prior.trim() ? prior.replace(/\s+$/, '') + '\n\n---\n\n' : '';
  return atomicWrite(p, sep + body.replace(/\s+$/, '') + '\n');
}

/**
 * One-time migration of a pre-existing `.agentic/context.md` into the new
 * two-file model. Idempotent, guarded by `_wrap.md`'s existence, and runs
 * strictly BEFORE the first rollup write in a project.
 *
 * WHY SEEDING IS MANDATORY. wrap-context-format.md's merge algorithm step 2 is
 * "if the file does not exist, write the new draft content directly". Without a
 * seeded `_wrap.md` the next /ds-wrap takes that branch and the 10-slot rolling
 * label window is GONE. Step 3 then overwrites any file whose SECOND LINE does
 * not begin `*Written by /ds-wrap`, so the seed must keep lines 1-2 BYTE-EXACT -
 * anything else re-creates the loss through a different door.
 *
 * Non-curated content is never seeded into `_wrap.md`; it is preserved as
 * `_foreign.md` instead. A Stop-hook-authored or adapter-authored file is not
 * curated narrative and must not become the curated seed.
 *
 * This procedure GOVERNS wherever it and the steady-state composer rules both
 * reach a shape.
 *
 * @param {string} cwd
 * @returns {boolean} true when a migration was performed
 */
function migrateIfNeeded(cwd) {
  try {
    const cp = curatedPath(cwd);
    if (fs.existsSync(cp)) return false; // already migrated

    const existing = readIfPresent(rollupPath(cwd));
    // Absent, empty, or whitespace-only: nothing to migrate. The rollup will be
    // header + activity region.
    if (existing === null || !existing.trim()) return false;
    // Already OUR OWN derived output. This project has no curated file (a
    // project that never ran /ds-wrap, or one whose `_wrap.md` was deleted) -
    // there is nothing curated to rescue, and treating a derived rollup as
    // pre-migration content would append it to `_foreign.md` on EVERY turn.
    if (existing.indexOf(DERIVED_MARKER) !== -1) return false;

    const i = findActivityRegionIndex(existing);
    const prefix = i >= 0 ? existing.slice(0, i) : existing;
    const suffix = i >= 0 ? existing.slice(i) : '';

    if (isWrapAuthored(prefix)) {
      // Curated -> seed `_wrap.md`, VERBATIM apart from stripDerivedBlocks.
      atomicWrite(cp, stripDerivedBlocks(prefix) + '\n');
    } else {
      // Stop-hook / adapter authored. NOT curated - preserve, never seed.
      preserveForeign(cwd, prefix);
    }

    // An unmarked trailing region is an unported writer's block; preserve it.
    if (suffix && suffix.indexOf(DERIVED_MARKER) === -1) {
      preserveForeign(cwd, suffix);
    }
    return true;
  } catch (_) {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Composition
// ---------------------------------------------------------------------------

const DERIVED_HEADER_LINE = '*Derived rollup - regenerated from .agentic/context.d/ on every turn. Not committed to git.*';

/**
 * Build the full rollup body from `_wrap.md` plus the shard set. PURE with
 * respect to the filesystem inputs it is handed: no clock read, no randomness,
 * no ordering that depends on readdir order.
 *
 * @param {string} cwd
 * @param {Array} shards - from snapshotShards (already ordered + unbounded)
 * @param {{banner?: string|null, degraded?: boolean}} [opts]
 * @returns {string}
 */
function composeRollup(cwd, shards, opts) {
  const o = opts || {};
  const curated = readIfPresent(curatedPath(cwd));

  let head;
  if (curated !== null && curated.trim()) {
    head = curated.replace(/\s+$/, '');
  } else {
    head = [
      '# Session Context',
      DERIVED_HEADER_LINE,
      '*Project: ' + cwd + '*',
    ].join('\n');
  }

  const kept = shards.slice(0, SHARD_RETENTION);
  const parts = [head];

  if (o.banner) parts.push(o.banner.replace(/\s+$/, ''));

  if (kept.length > 0) {
    const blocks = [];
    for (const s of kept) {
      const body = readIfPresent(s.path);
      if (body === null || !body.trim()) continue;
      blocks.push('### Session ' + s.sessionId + '\n\n' + body.replace(/\s+$/, ''));
    }
    if (blocks.length > 0) {
      // The DERIVED MARKER lives HERE - in the activity-region header, one line
      // after the sentinel - and never in the file header. See MARKER PLACEMENT.
      const regionHeader = ACTIVITY_SENTINEL
        + DERIVED_MARKER + '\n'
        + '*Derived from .agentic/context.d/ - ' + blocks.length
        + ' session shard(s). Do not edit; regenerated every turn.*'
        + (o.degraded ? '\n*NOTE: shard set changed under three consecutive regens; this rollup may lag by one turn.*' : '')
        + '\n';
      parts[parts.length - 1] = parts[parts.length - 1].replace(/\s+$/, '');
      // Session blocks are `---`-separated so `bin/agentic-memory turns`
      // segments the rollup ONE SEGMENT PER SESSION. That tool's heuristic 2
      // (`^---+$`) is load-bearing here and must stay the one that fires - the
      // composer therefore never emits a `## Turn`-prefixed heading, which
      // would hijack segmentation via its heuristic 1.
      return parts.join('\n') + regionHeader + '\n' + blocks.join('\n\n---\n\n') + '\n';
    }
  }

  // No shard content: `_wrap.md` (or the derived header) verbatim, NO sentinel.
  return parts.join('\n') + '\n';
}

// ---------------------------------------------------------------------------
// Regeneration
// ---------------------------------------------------------------------------

/**
 * Decide whether the CURRENT rollup on disk carries content this composer did
 * not write, and must therefore be preserved as `_foreign.md` before rebuild.
 *
 * Returns the text to preserve, or null.
 *
 * NOTE - a deliberate, documented departure from the plan's row E6 ("marker
 * present but region does not match shard-derived output -> treat as foreign").
 * That rule is unimplementable as written: it contradicts row E2 ("marker
 * present, shard set changed -> regenerate"), because a legitimately-stale
 * marked region is byte-indistinguishable from a partially-edited one. Applying
 * E6 literally would rewrite `_foreign.md` on EVERY turn in which any shard
 * changed - the exact per-turn `_foreign.md` churn that rev 5 fixed elsewhere.
 * MARKER PRESENCE therefore governs: marked => ours, unmarked => preserve.
 */
function foreignContentToPreserve(cwd, existing, curatedHead) {
  if (existing === null || !existing.trim()) return null;
  if (existing.indexOf(DERIVED_MARKER) !== -1) return null; // ours

  // Our own zero-shard output is `_wrap.md` (or the derived header) verbatim and
  // carries no marker. Recognising it exactly prevents a self-inflicted
  // false-positive that would preserve our own file as "foreign" every turn.
  if (existing.replace(/\s+$/, '') === curatedHead.replace(/\s+$/, '')) return null;

  const i = findActivityRegionIndex(existing);
  if (i >= 0) return existing.slice(i);           // unmarked activity region

  // No activity region at all. A pure /ds-wrap file is curated, not foreign -
  // the composer simply appends a fresh marked region below it.
  if (isWrapAuthored(existing)) return null;

  // Anything else is a whole-file write by an unported adapter (each is a bare
  // writeFileSync emitting ZERO sentinels). Preserve the entire body.
  return existing;
}

/**
 * Regenerate `.agentic/context.md` from `_wrap.md` + the shard set.
 *
 * DELIBERATELY LOCK-FREE. The rollup is a pure function of its inputs, so a lost
 * update self-heals on the next turn rather than losing data - which is what
 * makes the lock unnecessary here and what makes the stuck-lock banner
 * unsuppressible. Do not add a lock check to this function; doing so restores
 * D1/D2/D3 in one edit.
 *
 * Fail-open in every branch; never throws to a hook.
 *
 * @param {string} cwd
 * @param {{banner?: string|null, skipBanner?: boolean, abandonMs?: number,
 *          legacyAbandonMs?: number, stuckNoticeMs?: number}} [opts]
 * @returns {{written: boolean, attempts: number, degraded: boolean,
 *            migrated: boolean, foreign: boolean}}
 */
function regenerateRollup(cwd, opts) {
  const result = { written: false, attempts: 0, degraded: false, migrated: false, foreign: false };
  try {
    const o = opts || {};
    if (typeof cwd !== 'string' || !cwd) return result;

    result.migrated = migrateIfNeeded(cwd);

    const target = rollupPath(cwd);
    const existing = readIfPresent(target);

    // Compose the zero-shard head once, purely to recognise our own E8 output.
    const curatedHead = composeRollup(cwd, [], {});
    const foreign = foreignContentToPreserve(cwd, existing, curatedHead);
    if (foreign !== null) {
      preserveForeign(cwd, foreign);
      result.foreign = true;
    }

    const banner = Object.prototype.hasOwnProperty.call(o, 'banner')
      ? o.banner
      : (o.skipBanner ? null : stuckLockBanner(cwd, o));

    // Never write an empty rollup: with no shards AND no `_wrap.md` there is
    // nothing to say, and writing a bare header would only churn the file.
    let shards = snapshotShards(cwd);
    if (shards.length === 0 && readIfPresent(curatedPath(cwd)) === null && !banner) {
      return result;
    }

    // Compare-and-retry. Without it the interleaving
    //   X shard -> X snapshot -> Y shard -> Y snapshot -> Y rollup -> X rollup
    // ends with a rollup that OMITS Y. Idempotence is preserved because the
    // retry fires ONLY on a shard-set change; an unchanged set never loops.
    for (let attempt = 1; attempt <= MAX_ROLLUP_ATTEMPTS; attempt++) {
      result.attempts = attempt;
      const before = snapshotKey(shards);
      const degraded = attempt === MAX_ROLLUP_ATTEMPTS && attempt > 1;
      const body = composeRollup(cwd, shards, { banner, degraded });
      result.written = atomicWrite(target, body);
      const after = snapshotShards(cwd);
      if (snapshotKey(after) === before) {
        result.degraded = degraded;
        return result;
      }
      shards = after;
    }
    // Three attempts, shard set still moving: the last write stands and carries
    // the bounded-degradation note. Bounded, announced, never a silent discard.
    result.degraded = true;
    return result;
  } catch (_) {
    return result;
  }
}

module.exports = {
  // constants
  ACTIVITY_SENTINEL,
  DERIVED_MARKER,
  SHARD_RETENTION,
  MAX_ROLLUP_ATTEMPTS,
  // paths
  rollupPath,
  shardDirPath,
  shardPath,
  curatedPath,
  foreignPath,
  // shard writes
  writeShard,
  appendToShard,
  // snapshot / compose / regen
  snapshotShards,
  composeRollup,
  regenerateRollup,
  // classification / migration (exported for tests)
  findActivityRegionIndex,
  stripDerivedBlocks,
  migrateIfNeeded,
  foreignContentToPreserve,
  isWrapAuthored,
  stuckLockBanner,
};
