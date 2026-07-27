#!/usr/bin/env node

/**
 * Purpose: Single source of truth for the two loop/batch orchestration
 *          state-file writes previously duplicated inline in
 *          hooks/stop-context.js (writeLoopState/writeBatchState). Splits the
 *          write into two distinct cadences so a per-turn hook (Stop, which
 *          the Claude Code docs classify as firing once per turn, NOT once
 *          per session) never marks a live loop/batch as interrupted merely
 *          because a turn ended: refreshLiveness() is the per-turn liveness
 *          touch, markInterrupted() is the terminal (once-per-session) mark.
 *
 * Public API (CommonJS):
 *   refreshLiveness(cwd, sessionId, onOutcome?) - per-turn cadence. For each
 *     candidate file that is status:"active" AND owned by sessionId (POSITIVE
 *     match required: session_id must be a non-empty string EQUAL to
 *     sessionId - absent/null/empty/differing all SKIP), refreshes the
 *     file's liveness timestamp only (loop-state: last_updated; batch-state:
 *     updated_at). Never changes `status`.
 *   markInterrupted(cwd, sessionId, onOutcome?) - terminal (session-exit)
 *     cadence. For each candidate file that is status:"active" and NOT
 *     positively owned by a DIFFERING session (absent/null/empty session_id
 *     on disk PROCEEDS - mirrors the pre-existing writeBatchState polarity),
 *     sets status:"interrupted", interrupted_at, interrupt_reason:"unknown".
 *     Deliberately does NOT touch loop-state's `last_updated` (see Failure
 *     modes) - batch-state's `updated_at` IS touched here, matching its
 *     pre-existing writer behavior.
 *   candidatePaths(cwd) - returns the array of relative paths this module owns
 *     for the given cwd, RESOLVED at call time from CANDIDATE_FILES plus the
 *     per-ticket keyed loop-state siblings actually present on disk. It is the
 *     exact list both refreshLiveness and markInterrupted iterate over (all
 *     three call _resolveCandidates), so it is load-bearing and cannot
 *     silently drift from what the module reads/writes. Two properties matter:
 *     (a) the two LEGACY rows ('.agentic/loop-state.json' and
 *     '.agentic/batch-state.json') are ALWAYS present, even when .agentic/ is
 *     absent or unreadable - legacy detection can never be lost to a
 *     directory-read failure; (b) each keyed row ('.agentic/loop-state-<K>.json',
 *     matching /^loop-state-.+\.json$/) INHERITS tsField, healthTarget and
 *     touchTimestampOnTerminal VERBATIM from the legacy loop-state row, so a
 *     keyed file has no semantics of its own and cannot drift from the legacy
 *     file's. This replaced the former static `_candidatePaths` export, which
 *     a per-ticket keyed file would have made false on a correctness path
 *     (a read set larger than the exported list); `module.exports
 *     ._candidatePaths` is deliberately undefined.
 *
 * The ownership-predicate asymmetry is BETWEEN THE TWO CADENCE FUNCTIONS,
 * not between the two files - both files share identical polarity within
 * each function. This is intentional, not an oversight: refreshLiveness
 * asserts "a live session is actively working this loop" - a false positive
 * on an unowned/legacy file (no session_id) would make that assertion
 * falsely and could hide an abandoned loop from every staleness reader
 * forever, so it requires a POSITIVE session_id match on every candidate.
 * markInterrupted only ever asserts "this file is not active" - a redundant
 * true statement at worst when applied to an unowned file - so it proceeds
 * on absent/null/empty session_id and aborts only on a positive differing
 * match, again on every candidate. Because the asymmetry lives at the
 * function level (stated once each in _refreshCandidateLiveness and
 * _markCandidateInterrupted below) rather than being re-derived per file,
 * collapsing the former four near-identical per-file helpers into one
 * pair driven by CANDIDATE_FILES does not obscure it - if anything it makes
 * the asymmetry easier to audit, since each polarity now has exactly one
 * implementation instead of two copies that could silently drift apart.
 *
 * Upstream deps: Node built-ins only (fs, path). No npm dependencies. Reads
 *                and writes [cwd]/.agentic/batch-state.json, the legacy
 *                [cwd]/.agentic/loop-state.json, and every per-ticket keyed
 *                sibling [cwd]/.agentic/loop-state-<LOOP_KEY>.json. Additionally
 *                performs one fs.readdirSync of [cwd]/.agentic (fail-open to []
 *                so the two legacy rows survive a missing or unreadable
 *                directory) to discover the keyed siblings.
 *
 * Downstream consumers: hooks/stop-context.js (both functions, dispatched by
 *                        the --cadence=turn|session CLI flag),
 *                        hooks/session-end-wrap.js (markInterrupted only, on
 *                        a terminal SessionEnd reason).
 *
 * Failure modes: Both functions perform their own cwd path-traversal
 *                rejection (path.resolve(cwd) !== cwd -> no-op for every
 *                candidate) since neither caller performs this check
 *                independently. Each candidate file is processed inside its
 *                OWN try/catch so a failure (parse error, fs error) on one
 *                file never skips the other (fail-open PER PATH, not just
 *                per call). Every write is atomic-for-a-single-writer (pid-
 *                suffixed tmp + rename, `<file>.tmp.<pid>`) with a catch-block
 *                fs.unlinkSync(tmp) cleanup scoped to ONLY the pid-suffixed
 *                name this call itself created, so a crash mid-write or an
 *                early parse-error catch never leaves an orphan .tmp file AND
 *                never deletes a concurrent process's in-flight staging file.
 *                "Atomic" here is true single-writer (rename is atomic on the
 *                same filesystem); with two concurrent sessions writing the
 *                same candidate file, the two renames still race for last-
 *                write-wins on the destination, but neither process can ever
 *                observe or clobber the other's tmp - only the fixed-name
 *                variant (pre-fix) had that defect. markInterrupted
 *                deliberately never writes loop-state's
 *                `last_updated` - Contract A's resume-staleness gate reads
 *                only `last_updated` with no `status` exemption, so writing
 *                it on the terminal mark would make a freshly-interrupted
 *                loop look "recently live" to a resuming session for the
 *                full 10-minute staleness window. `interrupted_at` already
 *                timestamps the terminal event; that is sufficient
 *                (CANDIDATE_FILES.touchTimestampOnTerminal is false for
 *                loop-state, true for batch-state - the single place this
 *                distinction is encoded). The `onOutcome` callback is
 *                optional: when omitted, no health recording happens (this
 *                lib holds no health state itself); when provided it is
 *                called with the literal target labels 'writeLoopState' and
 *                'writeBatchState' (unchanged from the pre-existing
 *                stop-context.js recordHealth call sites, now sourced from
 *                CANDIDATE_FILES[].healthTarget) on both success and failure -
 *                `onOutcome(target, success, errMsg)`.
 *
 * Performance: standard - one fs.readdirSync of [cwd]/.agentic per call, then
 *              one fs.existsSync + one fs.readFileSync + one
 *              fs.writeFileSync/fs.renameSync per active/owned candidate;
 *              no subprocess, no network. Keyed loop-state candidates are
 *              ordered newest-mtime-first and CAPPED AT 100 processed, so a
 *              checkout that has accumulated more than 100 keyed files does
 *              bounded work per hook invocation. The cap is safe by
 *              construction: the file a live session owns is rewritten at
 *              every phase transition, so it is always among the newest.
 */

'use strict';

const fs = require('fs');
const path = require('path');

// Single source of truth for which state files this module owns and how each
// cadence treats them. Both refreshLiveness and markInterrupted iterate this
// table directly (see below) - it is not a parallel list kept in sync by
// hand. Fields:
//   file                     - relative filename under [cwd]/.agentic/.
//   keyedPrefix              - non-null when this row also has per-ticket
//                               keyed siblings ([cwd]/.agentic/<keyedPrefix><K>.json).
//                               _resolveCandidates emits one extra row per
//                               matching file on disk, inheriting every other
//                               field from this row verbatim. null = this file
//                               has no keyed form.
//   tsField                  - the liveness-timestamp field name for this
//                               file (the two files deliberately use
//                               different names for the same semantic).
//   healthTarget             - the literal onOutcome() label for this file
//                               (pinned - see module manifest Failure modes).
//   touchTimestampOnTerminal - whether markInterrupted also writes tsField.
//                              false for loop-state.json (Contract A's
//                              resume-staleness gate reads last_updated with
//                              no status exemption - see Failure modes);
//                              true for batch-state.json (matches the
//                              pre-existing writeBatchState behavior, which
//                              always set updated_at alongside interrupted_at).
const CANDIDATE_FILES = [
  {
    file: 'loop-state.json',
    keyedPrefix: 'loop-state-',
    tsField: 'last_updated',
    healthTarget: 'writeLoopState',
    touchTimestampOnTerminal: false,
  },
  {
    file: 'batch-state.json',
    keyedPrefix: null,
    tsField: 'updated_at',
    healthTarget: 'writeBatchState',
    touchTimestampOnTerminal: true,
  },
];

// Maximum number of per-ticket keyed candidates processed per call, ordered
// newest-mtime-first. Safe by construction - a live session rewrites its own
// keyed file at every phase transition, so it is always among the newest.
const KEYED_CANDIDATE_CAP = 100;

// Matches a per-ticket keyed loop-state sibling. `.+` (not `.*`) so the
// degenerate `loop-state-.json` (empty key) is never treated as a candidate;
// the conductor-side derivation floors the key to a non-empty string, so such
// a file can only arrive by hand.
const KEYED_FILE_RE = /^loop-state-.+\.json$/;

/**
 * Resolve the full candidate row set for a cwd: every static row unchanged,
 * plus one inherited row per per-ticket keyed loop-state file present on disk.
 *
 * Binding expansion rules (all four are load-bearing):
 *   1. Every static row is emitted unchanged, and THE TWO LEGACY ROWS ARE
 *      ALWAYS PRESENT - even when [cwd]/.agentic is absent or unreadable. The
 *      readdir failing must never cost us legacy detection.
 *   2. For a row with a non-null keyedPrefix, emit one row per matching entry,
 *      INHERITING tsField / healthTarget / touchTimestampOnTerminal VERBATIM
 *      from the parent static row. No metadata is ever authored for a keyed
 *      file - that is what makes the extension safe, since a keyed file cannot
 *      drift from the legacy file's semantics if it has no semantics of its own.
 *   3. Keyed matches are ordered newest-mtime-first and capped at
 *      KEYED_CANDIDATE_CAP processed.
 *   4. `.tmp` staging files and any non-`.json` entry are excluded.
 *
 * @param {string} cwd
 * @returns {Array<{file: string, tsField: string, healthTarget: string, touchTimestampOnTerminal: boolean}>}
 */
function _resolveCandidates(cwd) {
  const agenticDir = path.join(cwd, '.agentic');

  let entries = [];
  try {
    entries = fs.readdirSync(agenticDir);
  } catch (_e) {
    entries = []; // rule 1: fail open - the static rows below still stand
  }

  const resolved = [];
  for (const staticRow of CANDIDATE_FILES) {
    resolved.push(staticRow); // rule 1
    if (!staticRow.keyedPrefix) continue;

    // rule 4: only `<prefix><key>.json`; `.tmp` and non-.json never match.
    const keyed = entries
      .filter((name) => name !== staticRow.file && KEYED_FILE_RE.test(name))
      .map((name) => {
        let mtimeMs = 0;
        try {
          mtimeMs = fs.statSync(path.join(agenticDir, name)).mtimeMs;
        } catch (_e) { /* raced away between readdir and stat - sorts oldest */ }
        return { name, mtimeMs };
      })
      // rule 3: newest-mtime-first, then capped.
      .sort((a, b) => b.mtimeMs - a.mtimeMs)
      .slice(0, KEYED_CANDIDATE_CAP);

    for (const { name } of keyed) {
      // rule 2: inherit every field but `file` verbatim from the parent row.
      resolved.push(Object.assign({}, staticRow, { file: name }));
    }
  }
  return resolved;
}

/**
 * The relative paths this module owns for a given cwd. Resolved at call time
 * from the same _resolveCandidates() both cadence functions iterate, so it
 * cannot silently drift from what the module actually reads/writes.
 *
 * @param {string} cwd
 * @returns {string[]}
 */
function candidatePaths(cwd) {
  return _resolveCandidates(cwd).map((c) => `.agentic/${c.file}`);
}

/**
 * Refresh one candidate file's liveness timestamp (tsField) when the file is
 * active AND positively owned by sessionId. Never touches `status`.
 * POSITIVE-match ownership predicate: session_id must be a non-empty string
 * EQUAL to sessionId - absent/null/empty/differing all skip silently.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {{file: string, tsField: string, healthTarget: string}} candidate
 * @param {(target: string, success: boolean, errMsg: string|null) => void} [onOutcome]
 */
function _refreshCandidateLiveness(cwd, sessionId, candidate, onOutcome) {
  const filePath = path.join(cwd, '.agentic', candidate.file);
  let tmpPath;
  try {
    if (!fs.existsSync(filePath)) return;
    const state = JSON.parse(fs.readFileSync(filePath, 'utf-8'));

    const ownedByThisSession = typeof state.session_id === 'string'
      && state.session_id.length > 0
      && state.session_id === sessionId;
    if (!ownedByThisSession) return;

    if (state.status !== 'active') return;

    state[candidate.tsField] = new Date().toISOString();
    tmpPath = filePath + '.tmp.' + process.pid;
    fs.writeFileSync(tmpPath, JSON.stringify(state, null, 2));
    fs.renameSync(tmpPath, filePath);
    if (onOutcome) onOutcome(candidate.healthTarget, true, null);
  } catch (err) {
    if (onOutcome) onOutcome(candidate.healthTarget, false, err && err.message);
    // Only unlink OUR OWN pid-suffixed tmp - never a shared/fixed name another
    // concurrent process could own (see module manifest Failure modes).
    if (tmpPath) {
      try { fs.unlinkSync(tmpPath); } catch (_e) { /* tmp absent or never created */ }
    }
  }
}

/**
 * Per-turn liveness cadence: refresh every candidate file (independently -
 * fail-open per path). Rejects cwd values with traversal components.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {(target: string, success: boolean, errMsg: string|null) => void} [onOutcome]
 */
function refreshLiveness(cwd, sessionId, onOutcome) {
  const resolvedCwd = path.resolve(cwd);
  if (resolvedCwd !== cwd) return; // traversal component - skip silently

  for (const candidate of _resolveCandidates(cwd)) {
    _refreshCandidateLiveness(cwd, sessionId, candidate, onOutcome);
  }
}

/**
 * Mark one candidate file interrupted when active and NOT positively owned
 * by a DIFFERING session. Absent/null/empty session_id on disk PROCEEDS
 * (mirrors the pre-existing writeBatchState polarity). Conditionally also
 * writes tsField per candidate.touchTimestampOnTerminal (see module manifest
 * for why loop-state.json is excluded).
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {{file: string, tsField: string, healthTarget: string, touchTimestampOnTerminal: boolean}} candidate
 * @param {(target: string, success: boolean, errMsg: string|null) => void} [onOutcome]
 */
function _markCandidateInterrupted(cwd, sessionId, candidate, onOutcome) {
  const filePath = path.join(cwd, '.agentic', candidate.file);
  let tmpPath;
  try {
    if (!fs.existsSync(filePath)) return;
    const state = JSON.parse(fs.readFileSync(filePath, 'utf-8'));

    const ownedByAnotherSession = typeof state.session_id === 'string'
      && state.session_id.length > 0
      && state.session_id !== sessionId;
    if (ownedByAnotherSession) return;

    if (state.status !== 'active') return;

    const nowIso = new Date().toISOString();
    state.status = 'interrupted';
    state.interrupted_at = nowIso;
    state.interrupt_reason = 'unknown'; // cannot distinguish rate_limit vs crash at hook time
    if (candidate.touchTimestampOnTerminal) {
      state[candidate.tsField] = nowIso;
    }
    // else: tsField is deliberately NOT written here - see module manifest.

    tmpPath = filePath + '.tmp.' + process.pid;
    fs.writeFileSync(tmpPath, JSON.stringify(state, null, 2));
    fs.renameSync(tmpPath, filePath);
    if (onOutcome) onOutcome(candidate.healthTarget, true, null);
  } catch (err) {
    if (onOutcome) onOutcome(candidate.healthTarget, false, err && err.message);
    // Only unlink OUR OWN pid-suffixed tmp - never a shared/fixed name another
    // concurrent process could own (see module manifest Failure modes).
    if (tmpPath) {
      try { fs.unlinkSync(tmpPath); } catch (_e) { /* tmp absent or never created */ }
    }
  }
}

/**
 * Terminal (session-exit) cadence: mark every candidate file interrupted
 * (independently - fail-open per path). Rejects cwd values with traversal
 * components.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {(target: string, success: boolean, errMsg: string|null) => void} [onOutcome]
 */
function markInterrupted(cwd, sessionId, onOutcome) {
  const resolvedCwd = path.resolve(cwd);
  if (resolvedCwd !== cwd) return; // traversal component - skip silently

  for (const candidate of _resolveCandidates(cwd)) {
    _markCandidateInterrupted(cwd, sessionId, candidate, onOutcome);
  }
}

module.exports = { refreshLiveness, markInterrupted, candidatePaths };
