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
 *   _candidatePaths - exported array of the two relative paths this module
 *     owns, exactly ['.agentic/loop-state.json', '.agentic/batch-state.json'].
 *
 * The ownership-predicate asymmetry between the two functions is
 * intentional, not an oversight: refreshLiveness asserts "a live session is
 * actively working this loop" - a false positive on an unowned/legacy file
 * (no session_id) would make that assertion falsely and could hide an
 * abandoned loop from every staleness reader forever. markInterrupted only
 * ever asserts "this file is not active" - a redundant true statement at
 * worst when applied to an unowned file - so it proceeds on absent/null/empty
 * session_id and aborts only on a positive differing match.
 *
 * Upstream deps: Node built-ins only (fs, path). No npm dependencies. Reads
 *                and writes [cwd]/.agentic/loop-state.json and
 *                [cwd]/.agentic/batch-state.json.
 *
 * Downstream consumers: hooks/stop-context.js (both functions, dispatched by
 *                        the --cadence=turn|session CLI flag),
 *                        hooks/session-end-wrap.js (markInterrupted only, on
 *                        a terminal SessionEnd reason).
 *
 * Failure modes: Both functions perform their own cwd path-traversal
 *                rejection (path.resolve(cwd) !== cwd -> no-op for both
 *                candidates) since neither caller performs this check
 *                independently. Each candidate file is processed inside its
 *                OWN try/catch so a failure (parse error, fs error) on one
 *                file never skips the other (fail-open PER PATH, not just
 *                per call). Every write is atomic (tmp + rename) with a
 *                catch-block fs.unlinkSync(tmp) cleanup so a crash mid-write
 *                or an early parse-error catch never leaves an orphan .tmp
 *                file. markInterrupted deliberately never writes loop-state's
 *                `last_updated` - Contract A's resume-staleness gate reads
 *                only `last_updated` with no `status` exemption, so writing
 *                it on the terminal mark would make a freshly-interrupted
 *                loop look "recently live" to a resuming session for the
 *                full 10-minute staleness window. `interrupted_at` already
 *                timestamps the terminal event; that is sufficient. The
 *                `onOutcome` callback is optional: when omitted, no health
 *                recording happens (this lib holds no health state itself);
 *                when provided it is called with the literal target labels
 *                'writeLoopState' and 'writeBatchState' (unchanged from the
 *                pre-existing stop-context.js recordHealth call sites) on
 *                both success and failure - `onOutcome(target, success,
 *                errMsg)`.
 *
 * Performance: standard - one fs.existsSync + one fs.readFileSync + one
 *              fs.writeFileSync/fs.renameSync per active/owned candidate;
 *              no subprocess, no network.
 */

'use strict';

const fs = require('fs');
const path = require('path');

// Candidate set is exactly these two relative paths. This module owns no
// other state file.
const _candidatePaths = ['.agentic/loop-state.json', '.agentic/batch-state.json'];

/**
 * Refresh loop-state.json's `last_updated` liveness timestamp when the file
 * is active AND positively owned by sessionId. Never touches `status`.
 * POSITIVE-match ownership predicate: session_id must be a non-empty string
 * EQUAL to sessionId - absent/null/empty/differing all skip silently.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {(target: string, success: boolean, errMsg: string|null) => void} [onOutcome]
 */
function _refreshLoopStateLiveness(cwd, sessionId, onOutcome) {
  const loopStatePath = path.join(cwd, '.agentic', 'loop-state.json');
  let tmpPath;
  try {
    if (!fs.existsSync(loopStatePath)) return;
    const loopState = JSON.parse(fs.readFileSync(loopStatePath, 'utf-8'));

    const ownedByThisSession = typeof loopState.session_id === 'string'
      && loopState.session_id.length > 0
      && loopState.session_id === sessionId;
    if (!ownedByThisSession) return;

    if (loopState.status !== 'active') return;

    loopState.last_updated = new Date().toISOString();
    tmpPath = loopStatePath + '.tmp';
    fs.writeFileSync(tmpPath, JSON.stringify(loopState, null, 2));
    fs.renameSync(tmpPath, loopStatePath);
    if (onOutcome) onOutcome('writeLoopState', true, null);
  } catch (err) {
    if (onOutcome) onOutcome('writeLoopState', false, err && err.message);
    try { fs.unlinkSync(loopStatePath + '.tmp'); } catch (_e) { /* tmp absent or never created */ }
  }
}

/**
 * Refresh batch-state.json's `updated_at` liveness timestamp when the file
 * is active AND positively owned by sessionId. Never touches `status`.
 * Same POSITIVE-match ownership predicate as _refreshLoopStateLiveness.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {(target: string, success: boolean, errMsg: string|null) => void} [onOutcome]
 */
function _refreshBatchStateLiveness(cwd, sessionId, onOutcome) {
  const batchStatePath = path.join(cwd, '.agentic', 'batch-state.json');
  let tmpPath;
  try {
    if (!fs.existsSync(batchStatePath)) return;
    const batchState = JSON.parse(fs.readFileSync(batchStatePath, 'utf-8'));

    const ownedByThisSession = typeof batchState.session_id === 'string'
      && batchState.session_id.length > 0
      && batchState.session_id === sessionId;
    if (!ownedByThisSession) return;

    if (batchState.status !== 'active') return;

    batchState.updated_at = new Date().toISOString();
    tmpPath = batchStatePath + '.tmp';
    fs.writeFileSync(tmpPath, JSON.stringify(batchState, null, 2));
    fs.renameSync(tmpPath, batchStatePath);
    if (onOutcome) onOutcome('writeBatchState', true, null);
  } catch (err) {
    if (onOutcome) onOutcome('writeBatchState', false, err && err.message);
    try { fs.unlinkSync(batchStatePath + '.tmp'); } catch (_e) { /* tmp absent or never created */ }
  }
}

/**
 * Per-turn liveness cadence: refresh both candidate files (independently -
 * fail-open per path). Rejects cwd values with traversal components.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {(target: string, success: boolean, errMsg: string|null) => void} [onOutcome]
 */
function refreshLiveness(cwd, sessionId, onOutcome) {
  const resolvedCwd = path.resolve(cwd);
  if (resolvedCwd !== cwd) return; // traversal component - skip silently

  _refreshLoopStateLiveness(cwd, sessionId, onOutcome);
  _refreshBatchStateLiveness(cwd, sessionId, onOutcome);
}

/**
 * Mark loop-state.json interrupted when active and NOT positively owned by a
 * DIFFERING session. Absent/null/empty session_id on disk PROCEEDS (mirrors
 * the pre-existing writeBatchState polarity). Deliberately never writes
 * `last_updated` - see module manifest Failure modes.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {(target: string, success: boolean, errMsg: string|null) => void} [onOutcome]
 */
function _markLoopStateInterrupted(cwd, sessionId, onOutcome) {
  const loopStatePath = path.join(cwd, '.agentic', 'loop-state.json');
  let tmpPath;
  try {
    if (!fs.existsSync(loopStatePath)) return;
    const loopState = JSON.parse(fs.readFileSync(loopStatePath, 'utf-8'));

    const ownedByAnotherSession = typeof loopState.session_id === 'string'
      && loopState.session_id.length > 0
      && loopState.session_id !== sessionId;
    if (ownedByAnotherSession) return;

    if (loopState.status !== 'active') return;

    loopState.status = 'interrupted';
    loopState.interrupted_at = new Date().toISOString();
    loopState.interrupt_reason = 'unknown'; // cannot distinguish rate_limit vs crash at hook time
    // last_updated is deliberately NOT written here - see module manifest.
    tmpPath = loopStatePath + '.tmp';
    fs.writeFileSync(tmpPath, JSON.stringify(loopState, null, 2));
    fs.renameSync(tmpPath, loopStatePath);
    if (onOutcome) onOutcome('writeLoopState', true, null);
  } catch (err) {
    if (onOutcome) onOutcome('writeLoopState', false, err && err.message);
    try { fs.unlinkSync(loopStatePath + '.tmp'); } catch (_e) { /* tmp absent or never created */ }
  }
}

/**
 * Mark batch-state.json interrupted when active and NOT positively owned by
 * a DIFFERING session. Same ownership predicate and field set as the
 * pre-existing writeBatchState (status, interrupted_at, interrupt_reason,
 * updated_at all set).
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {(target: string, success: boolean, errMsg: string|null) => void} [onOutcome]
 */
function _markBatchStateInterrupted(cwd, sessionId, onOutcome) {
  const batchStatePath = path.join(cwd, '.agentic', 'batch-state.json');
  let tmpPath;
  try {
    if (!fs.existsSync(batchStatePath)) return;
    const batchState = JSON.parse(fs.readFileSync(batchStatePath, 'utf-8'));

    const ownedByAnotherSession = typeof batchState.session_id === 'string'
      && batchState.session_id.length > 0
      && batchState.session_id !== sessionId;
    if (ownedByAnotherSession) return;

    if (batchState.status !== 'active') return;

    const nowIso = new Date().toISOString();
    batchState.status = 'interrupted';
    batchState.interrupted_at = nowIso;
    batchState.interrupt_reason = 'unknown';
    batchState.updated_at = nowIso;

    tmpPath = batchStatePath + '.tmp';
    fs.writeFileSync(tmpPath, JSON.stringify(batchState, null, 2));
    fs.renameSync(tmpPath, batchStatePath);
    if (onOutcome) onOutcome('writeBatchState', true, null);
  } catch (err) {
    if (onOutcome) onOutcome('writeBatchState', false, err && err.message);
    try { fs.unlinkSync(batchStatePath + '.tmp'); } catch (_e) { /* tmp absent or never created */ }
  }
}

/**
 * Terminal (session-exit) cadence: mark both candidate files interrupted
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

  _markLoopStateInterrupted(cwd, sessionId, onOutcome);
  _markBatchStateInterrupted(cwd, sessionId, onOutcome);
}

module.exports = { refreshLiveness, markInterrupted, _candidatePaths };
