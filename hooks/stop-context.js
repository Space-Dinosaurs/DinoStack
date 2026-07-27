#!/usr/bin/env node

/**
 * Purpose: Reads the Claude Code Stop hook JSON payload from stdin - which
 *          fires once per TURN, not once per session - and writes session
 *          context to disk so the next session's Workers have lightweight
 *          context about what was happening. Also refreshes or terminally
 *          marks any active loop-state.json/batch-state.json via
 *          hooks/lib/state-mark.js, dispatched by a --cadence=turn|session CLI
 *          flag: --cadence=turn (this hook's install.sh-wired default) only
 *          refreshes a liveness timestamp on every turn; the terminal
 *          interrupted-mark now lives on hooks/session-end-wrap.js
 *          (SessionEnd, once per session). --cadence=session (or an
 *          absent/unrecognized flag) preserves this file's pre-existing
 *          behavior for callers, such as Pi's session_shutdown, that invoke
 *          this script directly without the flag. Writes
 *          per-developer session telemetry via a three-branch identity gate:
 *          confirmed identity -> per-project log + global mirror; provisional
 *          identity or no identity -> pending buffer (~/.agentic/session-log/.pending/);
 *          no identity also appends a one-time nudge to this session's shard.
 *          Runs a capture-gap backstop that detects learning-worthy sessions with
 *          no captured learnings and appends a nudge to the shard. ALWAYS creates
 *          [cwd]/.agentic/events.jsonl on every TURN (zero-aggregate
 *          fallback) so the telemetry substrate is present even in ad-hoc sessions
 *          that produce no conductor spawn_complete events.
 *
 * Public API: run() — invoked immediately at module load via run() call at
 *             bottom of file. Not imported; executed as a CLI script by the
 *             Claude Code Stop hook. Internal helpers:
 *             scanSessionAggregate(eventsPath, sessionId[, cachedRaw]),
 *             writeSessionTotal(cwd, sessionId[, cachedRaw]), computeSessionTotals(cwd, sessionId[, cachedRaw]),
 *             getIdentity(cwd), writeSessionLog(cwd, identity, sessionId[, cachedRaw]),
 *             writeSessionLogGlobal(identity, sessionId, data),
 *             writePendingBuffer(cwd, sessionId[, cachedRaw]),
 *             appendIdentityNudgeToContextMd(repoRoot, sessionId),
 *             appendCaptureGapNoticeToContextMd(cwd, residualOnly, sessionId),
 *             writeContextShardAndRollup(cwd, sessionId, shardBody) — replaces the
 *             former lock-gated writeContextMdOrSpill/appendSpilloverRecord/
 *             wrapLockHeld trio (see SHARD MODEL below),
 *             stageWrapPending(cwd, sessionId, scan) (thin alias to wrap-marker
 *             lib stagePending),
 *             recordHealth(target, success, errMsg) — synchronous in-memory
 *             accumulator for per-write-path success/failure counts; never throws,
 *             flushHealth(cwd) — atomic read-merge-write of
 *             [cwd]/.agentic/.telemetry-health.json; never throws; called once
 *             before each process.exit(0). The marker reads/transitions
 *             (readLastWrap, liveMarkerForSession - which replaces the former
 *             liveMarkerExists - stagePending, touchHeartbeat, etc.) now live in
 *             hooks/lib/wrap-marker.js, the single source of truth.
 *
 * Upstream deps: Node built-ins only (fs, path, os, child_process) plus five
 *                local CommonJS modules: hooks/lib/wrap-marker.js (the deferred-/ds-wrap
 *                marker single source of truth - lock gate, per-session staging,
 *                heartbeat), hooks/lib/capture-gap.js (the shared capture-gap
 *                detector - detectCaptureGap, GUARDRAIL_PATTERNS, _tokenize,
 *                extracted so the in-session PostToolUse nudge reuses it),
 *                hooks/lib/skill-candidate-detector.js (Stop-hook write path
 *                runSkillCandidateScan; required lazily inside the skill-candidate
 *                detection path, gated by the skill_candidate_detection toggle),
 *                hooks/lib/stdin-guard.js (readStdinGuarded - the shared
 *                bounded-stdin reader used in place of a blocking
 *                fs.readFileSync(0) so this hook cannot hang a harness's
 *                shutdown path when the spawning process never closes stdin),
 *                and hooks/lib/state-mark.js (refreshLiveness/markInterrupted -
 *                the single source of truth for the loop-state.json/
 *                batch-state.json writes, shared with hooks/session-end-wrap.js
 *                and dispatched here by the --cadence CLI flag),
 *                and hooks/lib/context-rollup.js (the per-session shard + derived
 *                rollup single source of truth - writeShard, appendToShard,
 *                regenerateRollup; see SHARD MODEL below).
 *                No npm dependencies. Reads from stdin (fd 0).
 *                Reads/writes
 *                [cwd]/.agentic/context.d/<session_id>.md (this session's shard -
 *                the ONLY context file this hook writes directly),
 *                [cwd]/.agentic/context.md (DERIVED rollup, regenerated from
 *                _wrap.md + the shard set; never hand-composed here),
 *                [cwd]/.agentic/loop-state.json (legacy) AND every per-ticket
 *                keyed sibling [cwd]/.agentic/loop-state-<LOOP_KEY>.json - this
 *                hook derives no key and enumerates no path itself; the
 *                candidate set is resolved by hooks/lib/state-mark.js
 *                (candidatePaths(cwd)), which always includes the legacy path
 *                and selects by session_id,
 *                [cwd]/.agentic/batch-state.json,
 *                [cwd]/.agentic/session-log/<developer_id>.jsonl,
 *                ~/.agentic/session-log/<developer_id>.jsonl (global mirror),
 *                ~/.agentic/session-log/.pending/<session_uuid>.json (pending buffer),
 *                ~/.agentic/identity.yml (read-only, global),
 *                [cwd]/.agentic/identity.yml (read-only, project-local; takes precedence
 *                over global when confirmed, per 4-tier resolution in getIdentity(cwd)),
 *                [cwd]/.agentic/config.json (read-only, deferred_wrap_daemon +
 *                skill_candidate_detection toggles),
 *                [cwd]/.agentic/events.jsonl (read-only for capture-gap backstop and
 *                skill-candidate scan),
 *                [cwd]/.agentic/learnings.md (read-only for capture-gap backstop and
 *                skill-candidate scan),
 *                [cwd]/.agentic/.capture-gap-last-sweep (pagination cursor; atomic
 *                tmp+rename on write),
 *                [cwd]/.agentic/.skill-candidate-tally.json (atomic tmp+rename),
 *                [cwd]/.agentic/.skill-candidate-cursor (ISO8601 high-water mark),
 *                [cwd]/.agentic/skill-candidates.md (appended when a domain first
 *                crosses the candidate threshold).
 *                [cwd]/.agentic/.telemetry-health.json (atomic tmp+rename;
 *                accumulated health outcomes flushed once per exit by flushHealth).
 *                Via wrap-marker.js it also touches [cwd]/.agentic/wrap/heartbeats/<session_id>
 *                (per-turn liveness mtime) and may stage
 *                [cwd]/.agentic/wrap/pending-<session_id>.json (per-session marker).
 *
 * Downstream consumers: Claude Code Stop hook (configured in
 *                        ~/.claude/settings.json or project .claude/settings.json).
 *                        Output files are read by Worker agents at session start.
 *                        bin/agentic-cost team reads .agentic/session-log/ for
 *                        team-level aggregation.
 *                        bin/agentic-cost operator reads ~/.agentic/session-log/*.jsonl
 *                        for global operator rollup. The .pending/ subdir is NOT
 *                        globbed by agentic-cost (operator or team) - it is consumed
 *                        only by agentic-identity confirm/init via flushPendingBuffer.
 *
 * Failure modes: All failures are silent (process.exit(0)). Stdin acquisition
 *                (step 1 of run()) is bounded via hooks/lib/stdin-guard.js's
 *                readStdinGuarded(), which never rejects and resolves via one
 *                of three paths - parse-success, EOF, or timeout - all feeding
 *                the same downstream write paths below, so a spawning process
 *                that never closes stdin cannot hang this hook's exit. Twelve
 *                independent write paths (plus the health-flush observability
 *                layer described below): (1) context.md write is best-effort; any fs error
 *                is swallowed and the file may not be written. (2) loop-state.json
 *                write is also best-effort; any fs error is swallowed independently
 *                of path (1). On the --cadence=turn dispatch (this hook's
 *                install.sh-wired default) this is a liveness-only refresh
 *                (last_updated) gated on a POSITIVE session_id match - it
 *                never sets status:"interrupted" (see hooks/lib/state-mark.js).
 *                On --cadence=session (or an absent/unrecognized flag) it is
 *                the terminal interrupted-mark, preserved for callers that
 *                invoke this script directly without the flag. (3) events.jsonl write is best-effort; writeSessionTotal
 *                now ALWAYS creates events.jsonl (zero-aggregate fallback when no
 *                qualifying events exist) after ensuring .agentic/ dir exists via
 *                mkdirSync({recursive:true}). Any fs error is swallowed independently
 *                of paths (1) and (2). The append failure model is identical to
 *                context.md - the next session can re-derive totals from per-spawn
 *                events if needed.
 *                (4) the same --cadence dispatch also writes
 *                .agentic/batch-state.json (hooks/lib/state-mark.js
 *                refreshLiveness/markInterrupted); on --cadence=turn this
 *                updates only `updated_at` (POSITIVE session_id match
 *                required); on --cadence=session (or an absent/unrecognized
 *                flag) this is the terminal interrupted-status write - aborts
 *                silently on a positively-differing session_id, on missing
 *                file, or on parse error. Best-effort silent-fail; failure of
 *                this path does not block writeSessionTotal.
 *                (5) writeSessionLog appends to .agentic/session-log/<dev>.jsonl;
 *                any fs error is swallowed independently of all other paths.
 *                (6) appendIdentityNudgeToContextMd appends to THIS SESSION'S
 *                shard; any fs error is swallowed independently. It is no longer
 *                deferred behind the wrap lock - the target is session-private,
 *                so there is nothing to serialize against, and deferring behind
 *                a lock let an ORPHANED lock suppress the one-time notice
 *                indefinitely.
 *                (7) writeSessionLogGlobal appends to ~/.agentic/session-log/<dev>.jsonl;
 *                any fs error is swallowed independently of the per-project write
 *                (path 5) - a global failure never affects the per-project write.
 *                (8) writePendingBuffer writes atomically (tmp+rename) to
 *                ~/.agentic/session-log/.pending/<uuid>.json; enforces cap-100
 *                (drops oldest by ts with one stderr notice); any fs error swallowed
 *                independently of all other paths.
 *                (9) appendCaptureGapNoticeToContextMd appends to THIS SESSION'S
 *                shard; any fs error is swallowed independently. The
 *                .capture-gap-last-sweep cursor update is also best-effort and
 *                never blocks exit.
 *                (10) RETIRED - appendSpilloverRecord no longer exists. Spillover
 *                was a consequence of the lock-gated skip in path 1; under the
 *                shard model no write is ever skipped, so nothing is deferred.
 *                `/ds-wrap` Part A still DRAINS a pre-existing
 *                .agentic/wrap/deferred-activity.jsonl - the drain is unchanged;
 *                only the producer is gone.
 *                (11) wrapMarker.touchHeartbeat writes/utimes
 *                .agentic/wrap/heartbeats/<session_id> once per turn (per-session
 *                liveness mtime). UNGATED from deferred_wrap_daemon (DS-106):
 *                that toggle defaults to false, so previously NO heartbeat was
 *                written for ANY session and the lock-liveness signal that
 *                wrapLockAbandoned's Arm A depends on could never exist. Still a
 *                no-op under the AGENTIC_WRAP_DAEMON loop-guard; any fs error
 *                swallowed independently of all other paths.
 *                Marker staging (stageWrapPending -> wrap-marker lib) shares this
 *                fail-open discipline and is never counted as blocking exit.
 *                (12) runSkillCandidateScan writes .agentic/.skill-candidate-tally.json,
 *                .agentic/.skill-candidate-cursor, and .agentic/skill-candidates.md
 *                (when a domain first crosses the candidate threshold). Gated by
 *                skill_candidate_detection in config.json (default true when absent
 *                or unreadable). Any error is absorbed by runSkillCandidateScan's
 *                own top-level try/catch; the path is additionally wrapped here in
 *                an independent try/catch so a crash inside the detector can never
 *                affect paths (1)-(11) or block session exit.
 *                Health-flush observability layer: recordHealth(target, success,
 *                errMsg) is called at success and catch sites for each of the
 *                twelve paths (excludes: marker unlink, JSON-line-skip catches,
 *                git-subprocess catches, and the one-time
 *                sentinel wx writes at ~1271/1367 where EEXIST is the expected
 *                normal path - not a failure). flushHealth(cwd) atomically
 *                merges accumulated counts into .agentic/.telemetry-health.json;
 *                called once before each process.exit(0). Both functions are
 *                wrapped in outer try/catch and never throw. The health flush is
 *                the observability layer for existing paths, not a new data-loss
 *                path itself.
 *                All twelve paths are independent - a failure in one does not
 *                affect the others. The 10-minute implicit-interrupt heuristic
 *                handles missed loop-state writes. cwd values with path
 *                traversal components are rejected for the loop-state and
 *                batch-state writes (defence in depth).
 *
 *                SHARD MODEL (DS-106/DS-107) - THE CONTEXT.MD WRITE IS NO LONGER
 *                LOCK-GATED, AND THAT IS THE FIX. This hook previously consulted
 *                wrapLockHeld(cwd) before writing context.md and SKIPPED the
 *                write when a /ds-wrap held .agentic/wrap/lock. Three defects
 *                compounded there: (D1) a role:'agent' lock carries pid:null, so
 *                its verdict is 'live' forever and nothing on the default config
 *                could clear it - one was measured held 10.3 h by a dead pid;
 *                (D2) both Stop-hook writers CHECKED the lock and NEITHER
 *                acquired it, so it provided zero mutual exclusion between the
 *                writers it appeared to protect; (D3) the capture-gap append
 *                ignored the lock entirely and wrote through it. Measured result:
 *                49 context.md writes across 6 sessions silently discarded over
 *                ~12 hours, from the file every session reads FIRST.
 *                Now: each writer writes .agentic/context.d/<session_id>.md (a
 *                SESSION-PRIVATE target, so concurrent writers cannot collide),
 *                then regenerates .agentic/context.md as a PURE FUNCTION of
 *                (_wrap.md, shard set). Because the rollup is derivable, a lost
 *                update SELF-HEALS next turn instead of losing data - which is
 *                what licenses writing it without a lock, and what lets the
 *                stuck-lock banner reach the operator through the very lock it
 *                reports. Do not reintroduce a lock check on that write path.
 *                stageWrapPending
 *                (delegated to wrap-marker lib stagePending) stages a per-session
 *                .agentic/wrap/pending-<session_id>.json marker (schema_version 3,
 *                atomic tmp+rename, NORMATIVE schema in content/commands/ds-wrap.md)
 *                so the next session or the daemon can complete enrichment for an
 *                un-wrapped session; staging is suppressed when the current
 *                session_id equals .agentic/wrap/last-wrap (this session already
 *                wrapped), when this session's marker is already ready / pending /
 *                in_progress (MAJOR-3), when the session had no substantive
 *                activity, or under the AGENTIC_WRAP_DAEMON loop-guard. Staging is
 *                fail-open and never blocks exit.
 *
 * Performance: ~5-20 ms typical; one git status subprocess call (5 s timeout)
 *              plus one git diff subprocess call for the capture-gap backstop
 *              (5 s timeout, soft-fail). Synchronous I/O throughout; runs as a
 *              short-lived CLI process. events.jsonl is read ONCE at the top of
 *              run() and the raw string is threaded to all consumers
 *              (scanSessionAggregate, computeSessionTotals, writeSessionTotal,
 *              writeSessionLog, writePendingBuffer, detectCaptureGap) so no
 *              consumer re-reads the file. On large projects (5-10 MB events
 *              files) this eliminates 3-4 redundant full-file reads per exit.
 */

/**
 * Claude Code Stop Hook — Session Context Writer
 *
 * Reads the Stop hook JSON payload from stdin and writes this session's activity
 * shard, then regenerates the derived [cwd]/.agentic/context.md rollup, so that
 * the next session's Workers have lightweight context about what was happening.
 *
 * Design goals:
 *  - Silent failure: any error exits 0, nothing written to stderr
 *  - No external dependencies: only Node built-ins
 *  - Fast: no LLM call, pure text extraction
 *  - /ds-wrap coexistence, partitioned at the `## Session Activity` sentinel:
 *    `.agentic/_wrap.md` owns everything up to the sentinel (including
 *    `## Recent Focus` and its 10-slot rolling label window, whose algorithm is
 *    unchanged); this hook owns everything from the sentinel onward and
 *    regenerates it wholesale from the shard set. The old strip-and-append
 *    "replace mode, most recent session only" semantic is RETIRED - on an
 *    N-session rollup it destroyed N-1 sessions' activity.
 *
 * Output paths: [cwd]/.agentic/context.d/<session_id>.md (written directly) and
 *   [cwd]/.agentic/context.md (derived; recomposed, never appended to)
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');

// Single source of truth for the deferred-/ds-wrap marker state machine, lock,
// heartbeat, and sentinel. The local helpers that previously lived in this file
// (wrapLockHeld, readLastWrap, liveMarkerExists, stageWrapPending) are now
// delegated to this lib so stop-context.js, the SessionEnd hook, and the daemon
// share one atomic, fail-open implementation.
const wrapMarker = require('./lib/wrap-marker.js');

// Single source of truth for the per-session SHARD + derived ROLLUP model
// (hooks/lib/context-rollup.js). EVERY context.md writer in this file now goes
// through it: each writes its own .agentic/context.d/<session_id>.md and then
// regenerates .agentic/context.md as a pure function of (_wrap.md, shard set).
// This is what retires the lock-gated whole-file write - see the LOCK-FREE note
// on writeContextShardAndRollup below.
const contextRollup = require('./lib/context-rollup.js');

// Shared capture-gap detector extracted to hooks/lib/capture-gap.js so the
// Stop-hook backstop below and the in-session PostToolUse(Task) nudge
// (hooks/post-tool-use-capture-nudge.js) share one implementation. Only
// detectCaptureGap is used here; GUARDRAIL_PATTERNS and _tokenize remain
// exported by the lib for test-capture-gap.js. appendCaptureGapNoticeToContextMd
// (the sole writer of the .capture-gap-last-sweep cursor) stays in this file.
const { detectCaptureGap } = require('./lib/capture-gap.js');

// Shared bounded-stdin reader (hooks/lib/stdin-guard.js) so this hook cannot
// hang a harness's shutdown path when the spawning process never closes
// stdin (round-1 Skeptic Finding 1 / plan-Skeptic M1 on
// docs/planning/cursor-stop-hook-plan.md).
const { readStdinGuarded } = require('./lib/stdin-guard.js');

// Single source of truth for the loop-state.json / batch-state.json
// liveness-vs-terminal-interrupt writes (hooks/lib/state-mark.js). This hook
// fires once per TURN (per the Claude Code Stop-hook docs), not once per
// session, so its default dispatch is refreshLiveness (--cadence=turn);
// markInterrupted (--cadence=session) is reserved for the terminal cadence
// and is also the fallback when --cadence is absent/unrecognized, preserving
// this file's historical behavior for callers (e.g. Pi's session_shutdown)
// that invoke this script without the flag.
const stateMark = require('./lib/state-mark.js');

// ---------------------------------------------------------------------------
// Telemetry-health counter (in-memory accumulate + single flush per exit)
// ---------------------------------------------------------------------------
// Module-level accumulator: keyed by target label, holds per-path outcome state.
// Populated by recordHealth(); flushed to disk once by flushHealth(cwd).
const healthOutcomes = {};

/**
 * Record a success or failure for a named write-path target.
 * Pure synchronous in-memory mutation — never throws (outer try/catch).
 *
 * @param {string} target   - Stable label for the write path (e.g. 'writeLoopState').
 * @param {boolean} success - True on the success branch; false in the catch.
 * @param {string|null} errMsg - Error message on failure; null on success.
 */
function recordHealth(target, success, errMsg) {
  try {
    if (!healthOutcomes[target]) {
      healthOutcomes[target] = {
        failures: 0,
        last_success: null,
        last_error: null,
        last_error_ts: null,
      };
    }
    const now = new Date().toISOString();
    if (success) {
      healthOutcomes[target].last_success = now;
    } else {
      healthOutcomes[target].failures += 1;
      healthOutcomes[target].last_error = errMsg || null;
      healthOutcomes[target].last_error_ts = now;
    }
  } catch (_) {
    // Never throw from the health layer.
  }
}

/**
 * Flush accumulated health outcomes to [cwd]/.agentic/.telemetry-health.json.
 * Single atomic read-merge-write: reads existing file (parse-fail or absent ->
 * start fresh), merges accumulated outcomes (cumulative failures, latest
 * timestamps), sets updated_at, writes to a .tmp file then renames.
 *
 * Schema note: `failures` is cumulative and approximate — concurrent same-repo
 * sessions may both read a stale count before either flushes, causing undercounts.
 * No lock by design — health flush must never block session exit.
 *
 * Never throws — entire body is wrapped in an outer try/catch.
 *
 * @param {string} cwd - Verified project root directory.
 */
function flushHealth(cwd) {
  // Declare both paths before the outer try so the catch-block cleanup can
  // reference them (avoids referencing try-scoped vars from catch).
  let healthPath;
  let tmp;
  try {
    if (!cwd) return;
    const resolvedCwd = path.resolve(cwd);
    if (resolvedCwd !== cwd) return; // traversal component - skip silently
    healthPath = path.join(cwd, '.agentic', '.telemetry-health.json');
    tmp = healthPath + '.tmp.' + process.pid;

    // Read existing file (absent or parse-fail -> start fresh).
    let existing = { updated_at: null, targets: {} };
    try {
      const raw = fs.readFileSync(healthPath, 'utf8');
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed.targets === 'object') {
        existing = parsed;
      }
    } catch (_) {
      // Absent or unreadable -> start fresh.
    }

    // Merge accumulated outcomes into the existing state.
    for (const [target, outcome] of Object.entries(healthOutcomes)) {
      if (!existing.targets[target]) {
        existing.targets[target] = {
          failures: 0,
          last_success: null,
          last_error: null,
          last_error_ts: null,
        };
      }
      const stored = existing.targets[target];
      stored.failures = (stored.failures || 0) + outcome.failures;
      if (outcome.last_success) {
        stored.last_success = outcome.last_success;
      }
      if (outcome.last_error_ts) {
        stored.last_error = outcome.last_error;
        stored.last_error_ts = outcome.last_error_ts;
      }
    }
    existing.updated_at = new Date().toISOString();

    // Atomic write: tmp + rename.
    fs.writeFileSync(tmp, JSON.stringify(existing, null, 2), 'utf8');
    fs.renameSync(tmp, healthPath);
  } catch (_) {
    // Silent failure - health flush must never block session exit.
    if (tmp) {
      try { fs.unlinkSync(tmp); } catch (_e) { /* tmp absent or never created */ }
    }
  }
}

/**
 * Read the `deferred_wrap_daemon` toggle from [cwd]/.agentic/config.json.
 * Fail-open: absent file, unreadable file, parse error, or absent key all
 * resolve to false. This is an OUTER config gate; the in-lib daemonGuardActive()
 * inner guard inside touchHeartbeat is PRESERVED (they serve different purposes).
 * Sister implementation: hooks/session-end-wrap.js deferredDaemonEnabled (keep in sync).
 *
 * @param {string} cwd - Project root directory.
 * @returns {boolean}
 */
function deferredDaemonEnabled(cwd) {
  try {
    const configPath = path.join(cwd, '.agentic', 'config.json');
    const raw = fs.readFileSync(configPath, 'utf8');
    const config = JSON.parse(raw);
    return config && config.deferred_wrap_daemon === true;
  } catch (_) {
    return false;
  }
}

/**
 * Read the `skill_candidate_detection` toggle from [cwd]/.agentic/config.json.
 * Fail-open: absent file, unreadable file, parse error, or absent key all
 * resolve to TRUE (default-on per the spec: detection is enabled unless
 * explicitly set to false). When the key is explicitly false, returns false.
 *
 * @param {string} cwd - Project root directory.
 * @returns {boolean}
 */
function skillCandidateDetectionEnabled(cwd) {
  try {
    const configPath = path.join(cwd, '.agentic', 'config.json');
    const raw = fs.readFileSync(configPath, 'utf8');
    const config = JSON.parse(raw);
    // Only disable when the key is explicitly set to false (boolean).
    if (config && config.skill_candidate_detection === false) {
      return false;
    }
    return true;
  } catch (_) {
    // Absent file, unreadable, or parse error -> default true.
    return true;
  }
}

/**
 * Scan events.jsonl and return aggregate totals for the current session.
 * Returns null if the file is absent, empty, or unreadable.
 *
 * Counting rules:
 *   - spawn_complete events contribute wall_seconds + tokens + spawn count.
 *   - conductor_direct events are NO LONGER counted (deprecated; hook-emitted
 *     spawn_start events replace them for ad-hoc session tracking).
 *   - spawn_start events with data.source === 'hook' contribute spawn count
 *     (wall_seconds 0, no tokens) ONLY when the session has zero spawn_complete
 *     events (ad-hoc session double-count guard). In /ds-implement-ticket sessions
 *     that carry conductor spawn_complete events the hook spawn_starts are
 *     skipped to avoid inflating counts with unverified duplicates. The resulting
 *     mild undercount of advisory spawn counts in mixed sessions is accepted
 *     (per plan deferred default: per-spawn reconciliation is impossible without
 *     a harness-provided correlation id).
 *
 * The returned by_agent map uses the rich token structure (4 bands) needed by
 * writeSessionTotal. writeSessionLog re-shapes it to its own output format.
 *
 * @param {string} eventsPath - Absolute path to events.jsonl.
 * @param {string|null} sessionId - Current session uuid (null = include all).
 * @param {string|null} [cachedRaw] - Pre-read file contents from run()'s single
 *   read. When provided (non-undefined), the file is NOT re-read; null means the
 *   file was absent or unreadable at read time and this function returns null
 *   immediately. When omitted (undefined), falls back to reading eventsPath
 *   directly for back-compat with callers that do not thread the cache.
 * @returns {{wall_seconds: number, tokens: object, spawn_count: number,
 *            by_agent: object}|null}
 */
function scanSessionAggregate(eventsPath, sessionId, cachedRaw) {
  let raw;
  if (cachedRaw !== undefined) {
    // Caller threaded the cached read: null means absent/unreadable.
    if (cachedRaw === null) return null;
    raw = cachedRaw;
  } else {
    // Back-compat: no cache provided, read the file directly.
    if (!fs.existsSync(eventsPath)) return null;
    try { raw = fs.readFileSync(eventsPath, 'utf8'); } catch (_) { return null; }
  }
  if (!raw.trim()) return null;

  const lines = raw.split('\n');
  let totalWall = 0;
  let spawnCount = 0;
  const totalTokens = { input: 0, output: 0, cache_creation: 0, cache_read: 0 };
  const byAgent = {};

  // First pass: count spawn_complete events to determine session type.
  // If any spawn_complete exists this is a ticketed/mixed session; hook
  // spawn_starts will be skipped in the second pass (double-count guard).
  let hasSpawnComplete = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try { obj = JSON.parse(trimmed); } catch (_) { continue; }
    if (obj && obj.event === 'spawn_complete') {
      const data = (obj && obj.data) || {};
      if (sessionId && data.session_uuid && data.session_uuid !== sessionId) continue;
      hasSpawnComplete = true;
      break;
    }
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try { obj = JSON.parse(trimmed); } catch (_) { continue; }
    const ev = obj && obj.event;
    const data = (obj && obj.data) || {};

    // Determine whether this line is a hook-emitted spawn_start.
    const isHookSpawn = ev === 'spawn_start' && data.source === 'hook';

    // Count: spawn_complete always; hook spawn_start only in ad-hoc sessions
    // (no spawn_complete in this session). conductor_direct is no longer counted.
    if (ev !== 'spawn_complete' && !isHookSpawn) continue;
    if (isHookSpawn && hasSpawnComplete) continue; // double-count guard

    // Filter to current session when session_uuid is present on the
    // event payload. Events without session_uuid are included
    // unconditionally (tolerant of pre-instrumentation events).
    if (sessionId && data.session_uuid && data.session_uuid !== sessionId) {
      continue;
    }
    const wall = Number(data.wall_seconds) || 0;
    totalWall += wall;
    const tokens = data.tokens || {};
    for (const k of ['input', 'output', 'cache_creation', 'cache_read']) {
      totalTokens[k] += Number(tokens[k]) || 0;
    }
    // Count the spawn (both spawn_complete and hook spawn_start count as spawns).
    spawnCount += 1;
    const agentName = obj.agent || 'unknown';
    if (!byAgent[agentName]) {
      byAgent[agentName] = {
        spawns: 0, wall_seconds: 0,
        tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
      };
    }
    byAgent[agentName].spawns += 1;
    byAgent[agentName].wall_seconds += wall;
    if (ev === 'spawn_complete') {
      for (const k of ['input', 'output', 'cache_creation', 'cache_read']) {
        byAgent[agentName].tokens[k] += Number(tokens[k]) || 0;
      }
    }
    // Hook spawn_starts carry no token data (harness ceiling) - tokens stay 0.
  }

  return {
    wall_seconds: Number(totalWall.toFixed(3)),
    tokens: totalTokens,
    spawn_count: spawnCount,
    by_agent: byAgent,
  };
}

/**
 * Append a single session_total event to .agentic/events.jsonl summing
 * spawn_complete + conductor_direct events for the current session.
 * Best-effort: any fs / parse failure is swallowed silently.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid from the Stop payload.
 * @param {string|null} [cachedRaw] - Pre-read events.jsonl contents from run()'s
 *   single read. When provided (non-undefined), no additional file read occurs.
 *   null means file was absent/unreadable; undefined triggers back-compat read.
 */
function writeSessionTotal(cwd, sessionId, cachedRaw) {
  try {
    const agenticDir = path.join(cwd, '.agentic');
    const eventsPath = path.join(agenticDir, 'events.jsonl');
    // Ensure .agentic/ exists so the append below always works, even in
    // ad-hoc sessions where no other hook has created the directory yet.
    fs.mkdirSync(agenticDir, { recursive: true });
    // Bootstrap: when no qualifying events exist, write a zero-aggregate
    // session_total so events.jsonl is ALWAYS created on every TURN.
    const agg = scanSessionAggregate(eventsPath, sessionId, cachedRaw) || {
      wall_seconds: 0,
      tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
      spawn_count: 0,
      by_agent: {},
    };

    const totalLine = JSON.stringify({
      ts: new Date().toISOString(),
      phase: 'session_end',
      event: 'session_total',
      agent: null,
      task_id: null,
      data: {
        wall_seconds: agg.wall_seconds,
        tokens: agg.tokens,
        spawn_count: agg.spawn_count,
        by_agent: agg.by_agent,
        session_uuid: sessionId || null,
      },
    });
    fs.appendFileSync(eventsPath, totalLine + '\n');
    recordHealth('writeSessionTotal', true, null);
  } catch (_) {
    recordHealth('writeSessionTotal', false, _ && _.message);
    // Silent failure - consistent with context.md / loop-state.json paths.
  }
}

/**
 * Remove the learnings-agent session marker if it belongs to the current session.
 * Silent failure: any error is swallowed.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid from the Stop payload.
 */
function removeLearningsAgentSession(cwd, sessionId) {
  // Reject cwd values with traversal components before any path join.
  const resolvedCwd = path.resolve(cwd);
  if (resolvedCwd !== cwd) {
    return;
  }

  try {
    const markerPath = path.join(cwd, '.agentic', 'learnings-agent.session');
    if (!fs.existsSync(markerPath)) return;
    const raw = fs.readFileSync(markerPath, 'utf8');
    const marker = JSON.parse(raw);
    if (typeof marker.session_id === 'string' && marker.session_id === sessionId) {
      fs.unlinkSync(markerPath);
    }
  } catch (_) {
    // Silent failure
  }
}

/**
 * Parse a YAML identity file at filePath. Returns {developer_id, provisional} or null.
 * Silent on ENOENT or any parse error.
 *
 * @param {string} filePath - Absolute path to the identity.yml file.
 * @returns {{developer_id: string, provisional: boolean}|null}
 */
function _parseIdentityFile(filePath) {
  try {
    if (!fs.existsSync(filePath)) return null;
    const raw = fs.readFileSync(filePath, 'utf8');
    const m = raw.match(/^developer_id:\s*(\S+)\s*$/m);
    if (!m) return null;
    const pm = raw.match(/^provisional:\s*(true|false)\s*$/m);
    const provisional = pm ? pm[1] === 'true' : false;
    return { developer_id: m[1], provisional };
  } catch (_) {
    return null;
  }
}

/**
 * Resolve effective identity via 4-tier total ordering:
 *   project-confirmed > global-confirmed > project-provisional > global-provisional > null
 *
 * Reads project file (<cwd>/.agentic/identity.yml) and global file
 * (~/.agentic/identity.yml) using two synchronous existsSync+readFileSync calls
 * (~1ms, Node built-ins only, no subprocess).
 *
 * The existing three-branch write-vs-buffer gate (identity && !identity.provisional)
 * remains valid: confirmed at either scope -> direct write; provisional -> pending buffer.
 *
 * @param {string} cwd - The repo working directory (already validated by run()).
 * @returns {{developer_id: string, provisional: boolean}|null}
 */
function getIdentity(cwd) {
  const projectPath = path.join(cwd, '.agentic', 'identity.yml');
  const globalPath = path.join(os.homedir(), '.agentic', 'identity.yml');

  const projId = _parseIdentityFile(projectPath);
  const globId = _parseIdentityFile(globalPath);

  // Pass 1: first confirmed candidate in [project, global] order
  if (projId && !projId.provisional) return projId;
  if (globId && !globId.provisional) return globId;

  // Pass 2: first provisional candidate in [project, global] order
  if (projId) return projId;
  if (globId) return globId;

  return null;
}

/**
 * Append a one-time identity nudge to THIS SESSION'S shard, from which the
 * rollup composer carries it into .agentic/context.md.
 * Silent on any fs error. Idempotent via sentinel at ~/.agentic/.identity-nudged.
 *
 * Formerly a raw append straight into the shared `.agentic/context.md`, gated on
 * `!wrapLockHeld(cwd)`. Both halves are gone: the target is now session-private
 * so there is nothing to serialize against, and deferring the nudge behind a
 * lock is what let an ORPHANED lock suppress it indefinitely.
 *
 * @param {string} repoRoot - Verified project directory.
 * @param {string|null} sessionId - Session uuid from the Stop payload.
 */
function appendIdentityNudgeToContextMd(repoRoot, sessionId) {
  try {
    const nudge = [
      '',
      '---',
      '[agentic-engineering] No developer identity set. Session telemetry is local-only.',
      'To enable team telemetry: agentic-identity init <handle>',
      'Sentinel: ~/.agentic/.identity-nudged (delete to re-nudge)',
    ].join('\n') + '\n';
    const ok = contextRollup.appendToShard(repoRoot, sessionId || NO_SESSION_SHARD, nudge);
    recordHealth('appendIdentityNudgeToContextMd', ok, null);
  } catch (_) {
    recordHealth('appendIdentityNudgeToContextMd', false, _ && _.message);
    // Silent failure
  }
}

/**
 * Compute session totals by scanning events.jsonl, shaped for writeSessionLog.
 * The by_agent map uses a flat tokens_total (sum of 4 bands) for the session-log
 * format, distinct from the 4-band structure used in writeSessionTotal.
 * Returns null on failure.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid.
 * @param {string|null} [cachedRaw] - Pre-read events.jsonl contents from run()'s
 *   single read. When provided (non-undefined), no additional file read occurs.
 *   null means file was absent/unreadable; undefined triggers back-compat read.
 * @returns {{wall_seconds: number, tokens: object, spawn_count: number, by_agent: object}|null}
 */
function computeSessionTotals(cwd, sessionId, cachedRaw) {
  try {
    const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
    const agg = scanSessionAggregate(eventsPath, sessionId, cachedRaw);
    if (!agg) return null;

    // Re-shape by_agent: flatten 4-band tokens to a single tokens_total for the
    // session-log format consumed by agentic-cost team.
    const byAgentFlat = {};
    for (const [name, entry] of Object.entries(agg.by_agent)) {
      const t = entry.tokens || {};
      byAgentFlat[name] = {
        spawns: entry.spawns,
        wall_seconds: entry.wall_seconds,
        tokens_total: (Number(t.input) || 0) + (Number(t.output) || 0)
          + (Number(t.cache_creation) || 0) + (Number(t.cache_read) || 0),
      };
    }

    return {
      wall_seconds: agg.wall_seconds,
      tokens: agg.tokens,
      spawn_count: agg.spawn_count,
      by_agent: byAgentFlat,
    };
  } catch (_) {
    return null;
  }
}

/**
 * Write a session-log line to .agentic/session-log/<developer_id>.jsonl.
 * Creates the directory if needed. Silent failure on any fs error.
 *
 * @param {string} cwd - Verified project directory.
 * @param {{developer_id: string}} identity - Identity from getIdentity().
 * @param {string|null} sessionId - Current session uuid.
 * @param {string|null} [cachedRaw] - Pre-read events.jsonl contents from run()'s
 *   single read. When provided (non-undefined), no additional file read occurs.
 *   null means file was absent/unreadable; undefined triggers back-compat read.
 */
function writeSessionLog(cwd, identity, sessionId, cachedRaw) {
  try {
    // Resolve project slug and branch best-effort
    const projectSlug = path.basename(cwd);
    let branch = '';
    try {
      const { execSync: _exec } = require('child_process');
      branch = _exec('git symbolic-ref --short HEAD', {
        cwd, timeout: 3000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
    } catch (_) {
      // Not a git repo or detached HEAD - leave branch as empty string
    }

    const totals = computeSessionTotals(cwd, sessionId, cachedRaw);
    const data = totals || {
      wall_seconds: 0,
      tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
      spawn_count: 0,
      by_agent: {},
    };

    const logLine = JSON.stringify({
      ts: new Date().toISOString(),
      phase: 'session_end',
      event: 'session_total',
      agent: null,
      task_id: null,
      developer_id: identity.developer_id,
      session_uuid: sessionId || null,
      project_slug: projectSlug,
      branch,
      data,
    });

    const sessionLogDir = path.join(cwd, '.agentic', 'session-log');
    fs.mkdirSync(sessionLogDir, { recursive: true });
    const logFile = path.join(sessionLogDir, `${identity.developer_id}.jsonl`);
    fs.appendFileSync(logFile, logLine + '\n', 'utf8');
    recordHealth('writeSessionLog', true, null);
  } catch (_) {
    recordHealth('writeSessionLog', false, _ && _.message);
    // Silent failure - consistent with all other write paths
  }
}

/**
 * Write the same session-log line that writeSessionLog writes per-project,
 * but to the global operator mirror: ~/.agentic/session-log/<dev>.jsonl.
 * Independent of the per-project write - a failure here never affects it.
 * Creates the directory if needed. Silent failure on any fs error.
 *
 * @param {{developer_id: string, provisional: boolean}} identity - From getIdentity().
 * @param {string|null} sessionId - Current session uuid.
 * @param {{wall_seconds: number, tokens: object, spawn_count: number, by_agent: object}} data - Telemetry.
 */
function writeSessionLogGlobal(identity, sessionId, data) {
  try {
    const globalLogDir = path.join(os.homedir(), '.agentic', 'session-log');
    fs.mkdirSync(globalLogDir, { recursive: true });
    const logLine = JSON.stringify({
      ts: new Date().toISOString(),
      phase: 'session_end',
      event: 'session_total',
      agent: null,
      task_id: null,
      developer_id: identity.developer_id,
      session_uuid: sessionId || null,
      project_slug: data.project_slug || null,
      branch: data.branch || '',
      data: {
        wall_seconds: data.wall_seconds,
        tokens: data.tokens,
        spawn_count: data.spawn_count,
        by_agent: data.by_agent,
      },
    });
    const logFile = path.join(globalLogDir, `${identity.developer_id}.jsonl`);
    fs.appendFileSync(logFile, logLine + '\n', 'utf8');
    recordHealth('writeSessionLogGlobal', true, null);
  } catch (_) {
    recordHealth('writeSessionLogGlobal', false, _ && _.message);
    // Silent failure - independent of per-project write
  }
}

/**
 * Generate a UUID v4 using crypto.randomUUID when available (Node 14.17+),
 * falling back to a Math.random-based implementation for older runtimes.
 *
 * @returns {string} UUID v4 string.
 */
function generateUuid() {
  try {
    const crypto = require('crypto');
    if (typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
  } catch (_) { /* no crypto module */ }
  // Fallback: RFC 4122 v4 via Math.random
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Write unattributed session telemetry to the pending buffer.
 * Used when identity is null (no identity) or provisional (not yet confirmed).
 * Writes atomically via tmp+rename to ~/.agentic/session-log/.pending/<uuid>.json.
 * Enforces a cap of 100 pending files: when at or above cap, deletes the single
 * oldest file by `ts` field and emits one stderr notice before writing.
 * No developer_id field in the pending record - it is unattributed until flush.
 * Silent failure on any fs error.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid (uuid v4 generated if null).
 * @param {string|null} [cachedRaw] - Pre-read events.jsonl contents from run()'s
 *   single read. When provided (non-undefined), no additional file read occurs.
 *   null means file was absent/unreadable; undefined triggers back-compat read.
 */
function writePendingBuffer(cwd, sessionId, cachedRaw) {
  let pendingTmpFile = null;
  try {
    const pendingDir = path.join(os.homedir(), '.agentic', 'session-log', '.pending');
    fs.mkdirSync(pendingDir, { recursive: true });

    // Enforce cap-100: count existing pending files
    let existingFiles = [];
    try {
      existingFiles = fs.readdirSync(pendingDir).filter((f) => f.endsWith('.json'));
    } catch (_) { /* silent */ }

    if (existingFiles.length >= 100) {
      // Parse ts from each file, find oldest, delete it
      let oldestTs = null;
      let oldestFile = null;
      for (const fname of existingFiles) {
        try {
          const raw = fs.readFileSync(path.join(pendingDir, fname), 'utf8');
          const obj = JSON.parse(raw);
          const ts = obj.ts || '';
          if (oldestTs === null || ts < oldestTs) {
            oldestTs = ts;
            oldestFile = fname;
          }
        } catch (_) { /* skip unreadable files */ }
      }
      if (oldestFile) {
        try { fs.unlinkSync(path.join(pendingDir, oldestFile)); } catch (_) { /* silent */ }
        process.stderr.write('agentic-engineering: pending buffer at cap (100); oldest session dropped\n');
      }
    }

    // Compute telemetry
    const totals = computeSessionTotals(cwd, sessionId, cachedRaw);
    const data = totals || {
      wall_seconds: 0,
      tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
      spawn_count: 0,
      by_agent: {},
    };

    // Resolve metadata
    const projectSlug = path.basename(cwd);
    const repoRoot = cwd;
    let branch = '';
    try {
      branch = execSync('git symbolic-ref --short HEAD', {
        cwd, timeout: 3000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
    } catch (_) { /* detached HEAD or non-git dir */ }

    const sessionUuid = sessionId || generateUuid();
    const record = {
      schema_version: 1,
      session_uuid: sessionUuid,
      ts: new Date().toISOString(),
      project_slug: projectSlug,
      repo_root: repoRoot,
      branch,
      data: {
        wall_seconds: data.wall_seconds,
        tokens: data.tokens,
        spawn_count: data.spawn_count,
        by_agent: data.by_agent,
      },
    };

    // Atomic write: tmp + rename
    const outFile = path.join(pendingDir, `${sessionUuid}.json`);
    pendingTmpFile = outFile + '.tmp';
    fs.writeFileSync(pendingTmpFile, JSON.stringify(record, null, 2), 'utf8');
    fs.renameSync(pendingTmpFile, outFile);
    recordHealth('writePendingBuffer', true, null);
  } catch (_) {
    recordHealth('writePendingBuffer', false, _ && _.message);
    // Silent failure - consistent with all other write paths
    if (pendingTmpFile) {
      try { fs.unlinkSync(pendingTmpFile); } catch (_e) { /* tmp absent or never created */ }
    }
  }
}

/**
 * Deterministic fallback shard key for a payload that carries no `session_id`.
 * Such a writer has no identity to key on, so it shares ONE slot rather than
 * losing its turn entirely - strictly better than the whole-file clobber that
 * preceded this design, and it can never collide with a real session uuid.
 */
const NO_SESSION_SHARD = 'no-session-id';

/**
 * Write this turn's activity into THIS SESSION'S shard, then regenerate the
 * derived `.agentic/context.md` rollup.
 *
 * DELIBERATELY LOCK-FREE, and that is the fix - do not reintroduce a lock check
 * here. The function this replaces consulted `wrapLockHeld(cwd)` twice and, when
 * the lock was held, SKIPPED the write and spilled a record instead. Three
 * defects lived in that design:
 *
 *   D1 - an abandoned lock was immortal (a role:'agent' descriptor carries
 *        pid:null, so its verdict was 'live' forever and nothing on the default
 *        config could clear it). Measured: held 10.3 hours by a dead pid.
 *   D2 - the lock provided ZERO mutual exclusion between the writers it appeared
 *        to protect: both Stop-hook writers CHECKED it and NEITHER acquired it,
 *        so two concurrent hooks both saw it free and both whole-file-wrote.
 *   D3 - a third writer (the capture-gap append) ignored the lock entirely.
 *
 * Net effect, measured live: 49 context.md writes across 6 sessions silently
 * discarded over ~12 hours, while `.agentic/context.md` is the file every
 * session reads as its FIRST action - so all six started from stale context and
 * none of them knew.
 *
 * Both halves of the replacement are needed. The shard is SESSION-PRIVATE, so
 * concurrent writers cannot collide (D2/D3). The rollup is a PURE FUNCTION of
 * the shard set, so a lost update self-heals on the next turn rather than losing
 * data - which is what makes writing it without a lock safe, and what lets the
 * stuck-lock banner reach the operator through the very lock it reports (D1).
 *
 * Silent-fail on any fs error, consistent with every other write path here.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Session uuid from the Stop payload.
 * @param {string} shardBody - This session's activity block.
 */
function writeContextShardAndRollup(cwd, sessionId, shardBody) {
  try {
    const key = sessionId || NO_SESSION_SHARD;
    const wrote = contextRollup.writeShard(cwd, key, shardBody);
    recordHealth('writeContextShard', wrote, null);
    const res = contextRollup.regenerateRollup(cwd);
    recordHealth('writeContextMd', res.written, null);
  } catch (_) {
    recordHealth('writeContextMd', false, _ && _.message);
    // Silent failure
  }
}

/**
 * Stage a per-session .agentic/wrap/pending-<session_id>.json enrichment marker
 * (schema_version 3) so the next session in this project (or the daemon) can
 * complete enrichment for a session that exited un-wrapped. The full staging
 * predicate, the MAJOR-3 ready/pending/in_progress suppression, the .last-wrap
 * suppression, the substantive-activity gate, the atomic tmp+rename write, and
 * the loop-guard NO-OP all live in hooks/lib/wrap-marker.js (single source of
 * truth). NORMATIVE marker schema lives in content/commands/ds-wrap.md.
 *
 * @param {string} cwd - Verified project directory.
 * @param {string|null} sessionId - Current session uuid from the Stop payload.
 * @param {{uncommittedCount: number, pathsReferencedCount: number,
 *          recentFocusCount: number}} scan - Already-computed activity counts.
 */
function stageWrapPending(cwd, sessionId, scan) {
  wrapMarker.stagePending(cwd, sessionId, scan);
}

// ---------------------------------------------------------------------------
// Capture-gap backstop helpers
// ---------------------------------------------------------------------------
// detectCaptureGap, GUARDRAIL_PATTERNS, and _tokenize now live in
// hooks/lib/capture-gap.js (required at the top of this file) so the in-session
// PostToolUse(Task) nudge shares the detector. appendCaptureGapNoticeToContextMd
// below - the sole writer of the .capture-gap-last-sweep cursor - stays here.

/**
 * Append a capture-gap nudge to THIS SESSION'S shard, from which the rollup
 * composer carries it into .agentic/context.md. Sentinel-gated per session via
 * .agentic/.capture-gap-last-sweep (ISO8601 UTC; absent = cold start). The
 * cursor is updated atomically (tmp+rename) after a successful append so the same
 * session does not nag twice. Silent failure on any fs error.
 *
 * THIS WRITER IS D3. It was a raw `fs.appendFileSync` straight into the shared
 * `.agentic/context.md` with NO lock check at all - so while the wrap lock was
 * suppressing every other writer, this one wrote THROUGH it. (The live orphaned
 * checkout's context.md ended with a CAPTURE-GAP block for exactly that reason.)
 * Retargeting it at a session-private shard makes the ungated append harmless
 * rather than adding a fourth gate that the next writer would forget.
 *
 * When residualOnly === true the nudge text emphasises that a guardrail was added
 * but is not domain-proximate, so only the residual WHY / dead-end reasoning needs
 * capturing. When residualOnly === false the standard nudge fires.
 *
 * @param {string} cwd - Verified project root.
 * @param {boolean} residualOnly - True when a guardrail was added but none were
 *   domain-proximate with the learning-worthy event.
 * @param {string|null} sessionId - Session uuid from the Stop payload.
 */
function appendCaptureGapNoticeToContextMd(cwd, residualOnly, sessionId) {
  try {
    const cursorPath = path.join(cwd, '.agentic', '.capture-gap-last-sweep');

    let nudgeText;
    if (residualOnly) {
      nudgeText = [
        '',
        '---',
        'CAPTURE-GAP: a related test or guardrail was added this session, but it is not',
        'domain-proximate to the learning-worthy event (root cause / tool workaround).',
        'Capture only the residual WHY and any dead-ends the test does not encode:',
        'spawn learnings-agent or add an LRN/KNW entry to .agentic/learnings.md.',
        '(If the guardrail fully captures it, ignore this.)',
      ].join('\n') + '\n';
    } else {
      nudgeText = [
        '',
        '---',
        'CAPTURE-GAP: this session resolved a root cause / worked around a tool failure',
        'but recorded no learning. If there is a non-obvious WHY beyond what a test or',
        'the diff already shows, capture it: spawn learnings-agent or add an LRN/KNW',
        'entry to .agentic/learnings.md. (If the test you added fully captures it, ignore this.)',
      ].join('\n') + '\n';
    }

    const ok = contextRollup.appendToShard(cwd, sessionId || NO_SESSION_SHARD, nudgeText);
    recordHealth('appendCaptureGapNoticeToContextMd-context', ok, null);

    // Update pagination cursor atomically so the same session doesn't fire twice.
    // Note: the inner catch uses _cursorErr to avoid shadowing the outer _ at the
    // outer catch below. recordHealth for the cursor write goes in this catch, not
    // in the _e cleanup catch (which handles tmp cleanup only).
    const tmpCursor = cursorPath + '.tmp.' + process.pid;
    try {
      const nowIso = new Date().toISOString();
      fs.writeFileSync(tmpCursor, nowIso, 'utf8');
      fs.renameSync(tmpCursor, cursorPath);
      recordHealth('appendCaptureGapNoticeToContextMd-cursor', true, null);
    } catch (_cursorErr) {
      recordHealth('appendCaptureGapNoticeToContextMd-cursor', false, _cursorErr && _cursorErr.message);
      /* silent - cursor update failure is non-fatal */
      // Only unlink OUR OWN pid-suffixed tmp - never a shared/fixed name
      // another concurrent session could own.
      try { fs.unlinkSync(tmpCursor); } catch (_e) { /* tmp absent or never created */ }
    }
  } catch (_) {
    recordHealth('appendCaptureGapNoticeToContextMd-context', false, _ && _.message);
    // Silent failure - consistent with all other context.md append paths.
  }
}

async function run() {
  // --- 1. Read stdin ---
  const raw = await readStdinGuarded();
  if (!raw.trim()) process.exit(0);

  // --- 2. Parse JSON ---
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (_) {
    process.exit(0);
  }

  // --- 3. Extract fields (all optional — guard every access) ---
  const cwd = (typeof payload.cwd === 'string' && payload.cwd.trim()) ? payload.cwd.trim() : null;
  if (!cwd) process.exit(0);

  const sessionId = (typeof payload.session_id === 'string' && payload.session_id.trim())
    ? payload.session_id.trim()
    : null;

  // --- 3a. Dispatch cadence: --cadence=turn -> refreshLiveness (per-turn
  // liveness only, never marks interrupted); --cadence=session or
  // absent/unrecognized -> markInterrupted (today's behavior, preserved as
  // the fallback for callers such as Pi's session_shutdown that invoke this
  // script without the flag). See hooks/lib/state-mark.js for both.
  const cadenceArg = process.argv.find((a) => a.startsWith('--cadence='));
  const cadence = cadenceArg ? cadenceArg.slice('--cadence='.length) : 'session';
  const stateMarkFn = cadence === 'turn' ? stateMark.refreshLiveness : stateMark.markInterrupted;

  // --- 3b-pre. Single events.jsonl read for the entire run() ---
  // All consumers (writeSessionTotal, computeSessionTotals, writeSessionLog,
  // writePendingBuffer, detectCaptureGap) receive this string instead of
  // re-reading the file. null = file absent or unreadable (consumers treat it
  // identically to a missing file). This eliminates 3-4 redundant full reads
  // per session exit on large events files (#267).
  const eventsPath = cwd ? path.join(cwd, '.agentic', 'events.jsonl') : null;
  let cachedEventsRaw = null;
  if (eventsPath) {
    try {
      if (fs.existsSync(eventsPath)) cachedEventsRaw = fs.readFileSync(eventsPath, 'utf8');
    } catch (_) { /* silent - stays null, consumers treat null as absent */ }
  }

  // --- 3b. Touch this session's heartbeat (per-turn liveness signal) ---
  // Two consumers, only one of which is daemon-scoped:
  //   (1) the daemon defers claiming a `ready` marker whose session still emits
  //       turns (pure wastefulness defense);
  //   (2) wrapLockAbandoned's Arm A uses it as THE liveness signal for a
  //       role:'agent' lock, which carries pid:null and therefore has no process
  //       to check.
  // UNGATED from `deferredDaemonEnabled(cwd)` deliberately (DS-106). That gate
  // returns true only when `deferred_wrap_daemon === true`, and the default is
  // false - so on a default install NO heartbeat was ever written for ANY
  // session, and any heartbeat-based liveness check would have been permanently
  // inert. (The live orphaned checkout's heartbeats/ directory was empty by
  // CONSTRUCTION, not because sessions had stopped.) The inner guard inside
  // touchHeartbeat is preserved - it serves a different purpose (the daemon
  // loop-guard). Local fs only (no git/network); fail-open; never blocks exit.
  // OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
  if (sessionId) wrapMarker.touchHeartbeat(cwd, sessionId);

  const transcript = Array.isArray(payload.transcript) ? payload.transcript : [];

  // --- 4. Output paths ---
  // Both live under the project's .agentic/ directory. Claude Code treats any
  // .claude/ directory (project-local OR global) as a sensitive file location,
  // so writing there still triggers the permission prompt even when allow rules
  // are set; .agentic/ is the same convention loop-state.json already uses and
  // is not subject to that check. The paths themselves are derived inside
  // hooks/lib/context-rollup.js (shardPath / rollupPath) so exactly one module
  // knows the layout.

  // --- 5. Extract recent user messages (last 3, truncated to ~150 chars) ---
  const userMessages = [];
  for (const msg of transcript) {
    if (!msg || msg.role !== 'user') continue;
    let text = '';
    if (typeof msg.content === 'string') {
      text = msg.content.trim();
    } else if (Array.isArray(msg.content)) {
      // Concatenate all text blocks
      for (const block of msg.content) {
        if (block && block.type === 'text' && typeof block.text === 'string') {
          text += block.text;
        }
      }
      text = text.trim();
    }
    if (text) userMessages.push(text);
  }
  const recentUserMessages = userMessages.slice(-3);

  // --- 6. Extract files touched from tool calls in transcript ---
  // Note: "Paths Referenced" in the output includes both file accesses (Read/Edit/Write/MultiEdit)
  // and search directories (Glob/Grep `path` arguments). Both categories appear in the same section.
  const filePaths = new Set();
  const fileToolNames = new Set(['Read', 'Edit', 'Write', 'MultiEdit']);

  for (const msg of transcript) {
    if (!msg) continue;
    const blocks = Array.isArray(msg.content) ? msg.content : [];
    for (const block of blocks) {
      if (!block || block.type !== 'tool_use') continue;
      const name = block.name || '';
      const input = block.input || {};

      if (fileToolNames.has(name)) {
        // Read, Edit, Write, MultiEdit all use file_path
        if (typeof input.file_path === 'string' && input.file_path.trim()) {
          filePaths.add(input.file_path.trim());
        }
      } else if (name === 'Glob' || name === 'Grep') {
        // Glob and Grep use path (directory or file to search in)
        if (typeof input.path === 'string' && input.path.trim()) {
          filePaths.add(input.path.trim());
        }
      } else if (name === 'Bash' || name === 'bash') {
        // Try to extract file paths from Bash commands via simple heuristic:
        // look for arguments that look like absolute paths
        const cmd = typeof input.command === 'string' ? input.command : '';
        const matches = cmd.match(/(?:^|\s)(\/[^\s"'\\;|&<>]+)/g);
        if (matches) {
          for (const m of matches) {
            const p = m.trim();
            // Only include paths that look like files (have an extension or are in known dirs)
            if (p.includes('.') || p.startsWith('/Users/') || p.startsWith('/home/')) {
              // Skip paths that are clearly flags or short tokens
              if (p.length > 4 && !p.startsWith('/.')) {
                // Require at least /Users/name/dir/file depth (4+ slashes) to avoid
                // capturing bare directories like /Users/alice or /home/bob
                if ((p.match(/\//g) || []).length >= 4) {
                  filePaths.add(p);
                }
              }
            }
          }
        }
      }
    }
  }

  // --- 7. Extract unique tools used from transcript tool_use blocks ---
  const toolsUsedSet = new Set();
  for (const msg of transcript) {
    if (!msg) continue;
    const blocks = Array.isArray(msg.content) ? msg.content : [];
    for (const block of blocks) {
      if (block && block.type === 'tool_use' && typeof block.name === 'string' && block.name.trim()) {
        toolsUsedSet.add(block.name.trim());
      }
    }
  }
  const uniqueTools = [...toolsUsedSet].sort();

  // --- 7b. Detect uncommitted changes via git status --porcelain ---
  const uncommittedFiles = [];
  try {
    const gitStatus = execSync('git status --porcelain', { cwd, timeout: 5000, encoding: 'utf8' });
    for (const line of gitStatus.split('\n')) {
      if (!line.trim()) continue;
      const statusCode = line.slice(0, 2).trim();
      const filePath = line.slice(3).trim();
      // Only include tracked modified/added/deleted/renamed files; skip untracked (??)
      if (statusCode && !statusCode.includes('?') && filePath) {
        uncommittedFiles.push({ statusCode, filePath });
      }
    }
  } catch (_) {
    // Silent failure if git isn't available or cwd isn't a repo
  }
  const uncommittedFilesLimited = uncommittedFiles.slice(0, 30);

  // --- 8. Format content ---
  const dateStr = new Date().toISOString().slice(0, 10);

  const recentFocusLines = recentUserMessages.length > 0
    ? recentUserMessages.map(m => {
        const truncated = m.length > 150 ? m.slice(0, 147) + '...' : m;
        // Indent continuation lines to keep the list readable
        return '- ' + truncated.replace(/\n/g, ' ');
      }).join('\n')
    : '(no user messages captured)';

  const pathsReferencedLines = filePaths.size > 0
    ? [...filePaths].sort().map(p => '- ' + p).join('\n')
    : '(none detected)';

  const toolsLine = uniqueTools.length > 0
    ? uniqueTools.join(', ')
    : '(none recorded)';

  const uncommittedChangesLines = uncommittedFilesLimited.length > 0
    ? uncommittedFilesLimited.map(({ statusCode, filePath }) => `- ${statusCode} ${filePath}`).join('\n')
    : '(working tree clean)';

  // --- 8b. Deferred-wrap marker-staging inputs ---
  // OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
  // NO SPILLOVER RECORD IS PRODUCED ANY MORE. Spillover existed solely because a
  // held wrap lock SKIPPED the context.md write; under the shard model the write
  // is never skipped, so there is nothing to defer. `/ds-wrap` Part A still
  // DRAINS a pre-existing `.agentic/wrap/deferred-activity.jsonl` (the 49
  // preserved records from the live incident drain normally) - the drain step is
  // deliberately unchanged; only the producer is retired.
  const spilloverScan = {
    uncommittedCount: uncommittedFiles.length,
    pathsReferencedCount: filePaths.size,
    recentFocusCount: recentUserMessages.length,
  };

  // THIS SESSION'S SHARD BODY. The composer wraps it in a `### Session <id>`
  // heading inside the derived activity region, so it carries no file header and
  // - critically - NO `## Recent Focus` heading. That heading names CURATED
  // content owned by `_wrap.md` and its 10-slot rolling label window; a derived,
  // idempotently regenerated file cannot own it without destroying either the
  // curation or the idempotence that licenses lock-freedom.
  const shardBody = `*Auto-updated by Stop hook — ${dateStr}.*

#### Recent Messages
${recentFocusLines}

#### Paths Referenced
${pathsReferencedLines}

#### Uncommitted Changes
${uncommittedChangesLines}

#### Tools Used
${toolsLine}
`;

  // --- 9. Section RETIRED: the /ds-wrap strip-and-append coexistence path ---
  // DELETED, not converted. It read the existing context.md, found the FIRST
  // `## Session Activity` sentinel, sliced everything after it away, and appended
  // exactly ONE fresh block - "replace mode, most recent session only, not
  // accumulated". On a rollup carrying N sessions that destroys N-1 of them,
  // which is a variant of the very data-loss bug this change fixes.
  //
  // Nothing replaces it, because the composer now regenerates the ENTIRE
  // post-sentinel region from the shard set on every write. "All but one block"
  // is therefore not a state any writer in this file can produce. The single
  // write path below serves both the /ds-wrap-authored and the fresh-file cases,
  // which also collapses the ~110 lines of exit-path logic that used to be
  // duplicated between the two branches.

  // --- 10. Write this session's shard + regenerate the rollup ---
  // LOCK-FREE by design; see writeContextShardAndRollup's doc block for why the
  // lock gate this replaces provided no mutual exclusion and could suppress
  // every write indefinitely.
  writeContextShardAndRollup(cwd, sessionId, shardBody);

  // --- 11. Refresh liveness or mark loop-state/batch-state interrupted ---
  // Dispatched by --cadence per hooks/lib/state-mark.js. There is now exactly
  // ONE exit path (section 9's duplicate was deleted), so this simply runs.
  stateMarkFn(cwd, sessionId, recordHealth);

  // --- 12. Append session_total event to .agentic/events.jsonl if present ---
  // Independent best-effort write; any failure swallowed.
  writeSessionTotal(cwd, sessionId, cachedEventsRaw);

  // --- 13. Three-branch identity gate: session log, global mirror, or pending buffer ---
  // Independent best-effort write; any failure swallowed. Never blocks exit.
  try {
    const identity = getIdentity(cwd);
    if (identity && !identity.provisional) {
      // Confirmed identity: per-project write + global mirror
      writeSessionLog(cwd, identity, sessionId, cachedEventsRaw);
      // Build shared metadata for global mirror
      const totals = computeSessionTotals(cwd, sessionId, cachedEventsRaw);
      const globalData = Object.assign(
        {
          wall_seconds: 0,
          tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
          spawn_count: 0,
          by_agent: {},
        },
        totals,
        { project_slug: path.basename(cwd), branch: '' }
      );
      try {
        globalData.branch = execSync('git symbolic-ref --short HEAD', {
          cwd, timeout: 3000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
        }).trim();
      } catch (_) { /* detached HEAD or non-git dir */ }
      writeSessionLogGlobal(identity, sessionId, globalData);
    } else {
      // Provisional or no identity: pending buffer
      writePendingBuffer(cwd, sessionId, cachedEventsRaw);
      // The `!wrapLockHeld(cwd)` gate that used to guard this nudge is REMOVED.
      // Its target is now a session-private shard, so there is nothing to
      // serialize against - and because the sentinel is consumed atomically with
      // the nudge, deferring behind a lock meant an ORPHANED lock could suppress
      // this one-time notice for as long as the orphan lived.
      if (!identity) {
        // No identity at all: also nudge once
        const sentinelPath = path.join(os.homedir(), '.agentic', '.identity-nudged');
        try {
          fs.mkdirSync(path.join(os.homedir(), '.agentic'), { recursive: true });
          // NOTE: this wx write is intentionally NOT instrumented by recordHealth -
          // EEXIST is the expected normal path (sentinel already written), not a failure.
          fs.writeFileSync(sentinelPath, '', { flag: 'wx' });
          // Sentinel did not exist - nudge once
          appendIdentityNudgeToContextMd(cwd, sessionId);
        } catch (_nudgeErr) {
          // EEXIST: sentinel already written, skip nudge
        }
      }
    }
  } catch (_) {
    // Silent failure
  }

  // --- 14. Remove learnings-agent session marker if owned by this session ---
  removeLearningsAgentSession(cwd, sessionId);

  // --- 15. Capture-gap backstop (path 9 - independent of all other paths) ---
  // Detects learning-worthy sessions with no captured learnings and appends a
  // nudge to THIS SESSION'S shard. Silent failure; never blocks exit.
  try {
    const gap = detectCaptureGap(cwd, sessionId, cachedEventsRaw);
    if (gap.shouldNudge) {
      appendCaptureGapNoticeToContextMd(cwd, gap.residualOnly, sessionId);
    }
  } catch (_) { /* silent */ }

  // --- 15b. Re-compose the rollup so THIS turn's notices actually surface ---
  // The identity nudge (13) and capture-gap nudge (15) append to the shard AFTER
  // section 10 already composed the rollup, so without this second pass a notice
  // would not reach .agentic/context.md until the NEXT turn - and never at all if
  // the session ends here, because both notices consume a one-time sentinel as
  // they fire. The rollup is a pure function of its inputs, so a redundant
  // regeneration over an unchanged shard set is byte-identical and free.
  try {
    contextRollup.regenerateRollup(cwd);
  } catch (_) { /* silent - section 10's rollup stands */ }

  // --- 16b. Skill-candidate detection (path 12 - independent soft-fail) ---
  // Gated on skill_candidate_detection toggle (default true when absent or
  // unreadable). runSkillCandidateScan has its own top-level try/catch; this
  // outer try/catch is an additional layer so no error can reach this exit path
  // and block session exit. Lazy-require so the module is only loaded when the
  // toggle is on.
  try {
    if (skillCandidateDetectionEnabled(cwd)) {
      const { runSkillCandidateScan } = require('./lib/skill-candidate-detector.js');
      runSkillCandidateScan(cwd, sessionId).catch(() => { /* soft-fail: async errors swallowed */ });
    }
  } catch (_) { /* soft-fail: require or sync setup errors swallowed */ }

  // --- 16. Stage the wrap-pending marker (deferred-wrap safety-net) ---
  // Runs after the context.md decision, on this exit path. Gated on
  // deferredDaemonEnabled so the flag-off default never accumulates markers.
  // Fail-open; never blocks exit. Staged only when no live marker exists, this
  // session has not already wrapped (.last-wrap), and the session had substantive
  // activity.
  // OpenCode intentionally omits this lock-gate / heartbeat / staging logic (Claude-only feature; no parity obligation)
  if (deferredDaemonEnabled(cwd)) stageWrapPending(cwd, sessionId, spilloverScan);

  flushHealth(cwd);
  process.exit(0);
}

run().catch(() => { try { process.exit(0); } catch (_) {} });

// Test shim: appended at module load so test files can import internals without
// executing run(). stop-context.js has no production module.exports; this shim
// is only reached when the test replaces `run();` before requiring.
if (typeof module !== 'undefined') {
  module.exports = { recordHealth, flushHealth, healthOutcomes, appendCaptureGapNoticeToContextMd };
}
