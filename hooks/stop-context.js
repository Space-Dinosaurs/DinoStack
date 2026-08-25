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
 *          identity or no identity -> pending buffer (~/.agentic/session-log/.pending/).
 *          Provisional records carry identity_scope from the winning identity;
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
 *             getIdentity(cwd),
 *             writeTelemetrySafely(cwd, identity, sessionId[, cachedRaw]),
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
 * Upstream deps: Node built-ins (fs, path, os, child_process), the bounded
 *                descriptor-safe bin/ds-identity resolve-hook/write-hook
 *                helper, hooks/lib/repo-root.js (resolveAgenticCwd /
 *                resolveAgenticCwdWithDiagnostics - anchors every .agentic/
 *                write to the repo root instead of the raw payload cwd;
 *                writeSessionTotal's session_total event also emits
 *                agentic_root_drift_levels/agentic_root_found_git from its
 *                diagnostics form), plus six
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
 *                <config-dir>/identity.yml (read-only, profile scope; config dir
 *                env-detected via AGENTIC_CONFIG_DIR/CLAUDE_CONFIG_DIR/
 *                CODEX_HOME/PI_CODING_AGENT_DIR),
 *                [cwd]/.agentic/identity.yml (read-only, project-local; takes precedence
 *                over profile and global when confirmed, per 6-tier resolution in
 *                getIdentity(cwd)),
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
 *                        bin/ds-cost team reads .agentic/session-log/ for
 *                        team-level aggregation.
 *                        bin/ds-cost operator reads ~/.agentic/session-log/*.jsonl
 *                        for global operator rollup. The .pending/ subdir is NOT
 *                        globbed by ds-cost (operator or team) - it is consumed
 *                        only by ds-identity confirm/init via flushPendingBuffer.
 *
 * Failure modes: All failures are silent (process.exit(0)). Stdin acquisition
 *                (step 1 of run()) is bounded via hooks/lib/stdin-guard.js's
 *                readStdinGuarded(), which never rejects and resolves via one
 *                of three paths - parse-success, EOF, or timeout - all feeding
 *                the same downstream write paths below, so a spawning process
 *                that never closes stdin cannot hang this hook's exit.
 *                Identity reads run through the bounded descriptor-relative
 *                Python helper because Node lacks openat-style component
 *                traversal. Invalid handles/UTF-8, symlinks, special files,
 *                multiply-linked files, wrong-owner files, and oversized files
 *                are absent/corrupt. Profile config candidates use the same
 *                component validation before selection; unsafe candidates are
 *                skipped so a safe lower-precedence env candidate can qualify.
 *                A root-owned top-level platform alias
 *                (for example macOS /var -> /private/var) is normalized before
 *                the nofollow walk; later components are never resolved. Twelve
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
 *                (5) writeTelemetrySafely asks the bundled helper to append to
 *                .agentic/session-log/<dev>.jsonl through validated directory
 *                and file descriptors; refusal is swallowed independently.
 *                (6) appendIdentityNudgeToContextMd appends to THIS SESSION'S
 *                shard; any fs error is swallowed independently. It is no longer
 *                deferred behind the wrap lock - the target is session-private,
 *                so there is nothing to serialize against, and deferring behind
 *                a lock let an ORPHANED lock suppress the one-time notice
 *                indefinitely.
 *                (7) the same helper independently appends to
 *                ~/.agentic/session-log/<dev>.jsonl through a bounded, owned,
 *                singly-linked regular-file descriptor; a global refusal never
 *                affects path 5.
 *                (8) for provisional or absent identity, the same helper
 *                publishes ~/.agentic/session-log/.pending/<uuid>.json through
 *                an exclusive unpredictable sibling and no-clobber link;
 *                validates cap-100 candidates before pruning. Any refusal is
 *                swallowed independently of all other paths.
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
 * Performance: ~150-400 ms typical including bounded identity-helper process
 *              launches; one git status subprocess call (5 s timeout)
 *              plus one git diff subprocess call for the capture-gap backstop
 *              (5 s timeout, soft-fail). Synchronous I/O throughout; runs as a
 *              short-lived CLI process. events.jsonl is read ONCE at the top of
 *              run() and the raw string is threaded to all consumers
 *              (scanSessionAggregate, computeSessionTotals, writeSessionTotal,
 *              writeTelemetrySafely, detectCaptureGap) so no
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
 *  - No npm dependencies: Node built-ins plus the bundled Python identity helper
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
const { execSync, spawnSync } = require('child_process');

// Anchors .agentic/ writes to the repo root instead of the raw payload cwd
// (see hooks/lib/repo-root.js manifest for full rationale).
const { resolveAgenticCwd, resolveAgenticCwdWithDiagnostics } = require('./lib/repo-root.js');

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
 * Record an INDETERMINATE outcome for a named write-path target - the
 * write may or may not have landed, and this call deliberately does not
 * touch `failures`, `last_success`, or `last_error` (DS-158 round 3
 * Major 2). A write whose outcome cannot be confirmed must never be
 * reported as a confirmed failure: the operator-facing telemetry-health
 * surface (bin/ds-status) would then assert something untrue about data
 * that may actually be on disk. Used when the write-hook subprocess is
 * killed by its own timeout ceiling before it can checkpoint that
 * specific target's result.
 *
 * @param {string} target - Stable label for the write path.
 * @param {string|null} note - Human-readable reason it is unknown.
 */
function recordHealthUnknown(target, note) {
  try {
    if (!healthOutcomes[target]) {
      healthOutcomes[target] = {
        failures: 0,
        last_success: null,
        last_error: null,
        last_error_ts: null,
      };
    }
    healthOutcomes[target].last_unknown =
      note || 'write outcome indeterminate (helper killed before reporting)';
    healthOutcomes[target].last_unknown_ts = new Date().toISOString();
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
    healthPath = path.join(resolveAgenticCwd(cwd), '.agentic', '.telemetry-health.json');
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
      // DS-158 round 3 Major 2: an indeterminate outcome is tracked
      // separately from confirmed failure - it never increments `failures`.
      if (outcome.last_unknown_ts) {
        stored.last_unknown = outcome.last_unknown;
        stored.last_unknown_ts = outcome.last_unknown_ts;
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
    const configPath = path.join(resolveAgenticCwd(cwd), '.agentic', 'config.json');
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
    const configPath = path.join(resolveAgenticCwd(cwd), '.agentic', 'config.json');
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
 *   - conductor-emitted spawn_complete events (data.source !== 'hook') always
 *     contribute wall_seconds + tokens + spawn count. Their presence in a
 *     session (data.source !== 'hook') is what defines a "ticketed" session
 *     for the double-count guard below - NOT the mere presence of ANY
 *     spawn_complete (see DS-160 fix note).
 *   - conductor_direct events are NO LONGER counted (deprecated; hook-emitted
 *     spawn_start events replace them for ad-hoc session tracking).
 *   - DS-160 double-count guard: when the session has at least one
 *     conductor-emitted spawn_complete (a ticketed session), ALL hook-emitted
 *     telemetry (both spawn_start AND spawn_complete, data.source === 'hook')
 *     is excluded entirely - the conductor's own richer spawn_complete is
 *     authoritative and the hook variant would otherwise double-count the
 *     same spawn. (Prior to DS-160 this guard only existed for spawn_start
 *     because spawn_complete had no hook-emitted variant; once
 *     hooks/subagent-stop-spawn-emit.js started emitting hook spawn_complete
 *     too, the guard had to be extended to cover it as well - a hook
 *     spawn_complete for a spawn the conductor already reported would
 *     otherwise be counted a second time.) This still leaves a mild
 *     UNDERCOUNT in genuinely mixed sessions: a hook-only ad-hoc spawn that
 *     co-occurs in the same session as a conductor-ticketed spawn is
 *     excluded entirely, not reconciled against the conductor's spawn - the
 *     same accepted tradeoff as the pre-DS-160 guard (per-spawn
 *     reconciliation across the conductor/hook boundary is not attempted;
 *     per plan deferred default, since a harness-provided cross-source
 *     correlation id does not exist).
 *   - In a pure ad-hoc session (zero conductor-emitted spawn_complete), hook
 *     spawn_start events are the authoritative "this spawn happened" signal
 *     and are DEDUPED by data.spawn_id so each real spawn counts exactly
 *     once: a spawn_start with no matching spawn_complete yet (SubagentStop
 *     still pending, or permanently lost) still counts once with
 *     wall_seconds 0 - it is NOT silently dropped. A PAIRED spawn_complete
 *     (data.paired_spawn_id referencing a spawn_start already counted via
 *     the dedup above) enriches that same spawn's record with a real
 *     wall_seconds and, when present, data.tokens - it does NOT add a
 *     second spawn.
 *   - DS-160 round-2 fix: an UNPAIRED hook spawn_complete (paired_spawn_id:
 *     null) does NOT contribute a spawn count of its own. Earlier this
 *     function counted it as a distinct spawn on the theory that its
 *     spawn_start had "rotated out of the [hook's 2MB tail] scan window" -
 *     but this consumer reads the WHOLE file (no tail bound), so exactly the
 *     case the hook's tail-window comment describes is the case where the
 *     spawn_start IS still visible here and would be double-counted (once
 *     via the spawn_start dedup, once via the unpaired-complete branch).
 *     Pairing can also fail for reasons that have nothing to do with a
 *     rotated-out spawn_start (a null session_id on the SubagentStop side,
 *     or a same-session concurrency race - see hooks/subagent-stop-spawn-emit.js
 *     Failure modes) - in every one of those cases the spawn's spawn_start is
 *     either already counted here or was never written at all, and there is
 *     no reliable way to distinguish "genuinely spawn_start-less" from
 *     "spawn_start present but pairing failed" from this side. Given
 *     pre-tool-use-spawn-emit.js fires unconditionally on every real spawn
 *     (fail-open, but deterministic on the happy path), the spawn_start-less
 *     case is treated as rare enough that undercounting it is the safer
 *     failure mode than double-counting the common case. Unpaired
 *     spawn_complete events are therefore treated as completion METADATA
 *     only (available for forensic inspection directly in events.jsonl) and
 *     contribute nothing to spawn_count/wall_seconds/by_agent here.
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

  function recordSpawn(agentName, wall, tokens) {
    totalWall += wall;
    if (tokens) {
      for (const k of ['input', 'output', 'cache_creation', 'cache_read']) {
        totalTokens[k] += Number(tokens[k]) || 0;
      }
    }
    spawnCount += 1;
    const name = agentName || 'unknown';
    if (!byAgent[name]) {
      byAgent[name] = {
        spawns: 0, wall_seconds: 0,
        tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
      };
    }
    byAgent[name].spawns += 1;
    byAgent[name].wall_seconds += wall;
    if (tokens) {
      for (const k of ['input', 'output', 'cache_creation', 'cache_read']) {
        byAgent[name].tokens[k] += Number(tokens[k]) || 0;
      }
    }
  }

  // Parse once, filtering to the current session (events without a
  // session_uuid are tolerated/included for back-compat with
  // pre-instrumentation lines).
  const parsed = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try { obj = JSON.parse(trimmed); } catch (_) { continue; }
    if (!obj) continue;
    const data = obj.data || {};
    if (sessionId && data.session_uuid && data.session_uuid !== sessionId) continue;
    parsed.push(obj);
  }

  // Session-type determination: ONLY a conductor-emitted (non-hook)
  // spawn_complete marks this a "ticketed" session. A hook-emitted
  // spawn_complete does NOT, by itself, imply the conductor also reported
  // this spawn (see DS-160 fix note above).
  const hasConductorSpawnComplete = parsed.some(
    obj => obj.event === 'spawn_complete' && (obj.data || {}).source !== 'hook'
  );

  if (hasConductorSpawnComplete) {
    // Ticketed/mixed session: count ONLY conductor-emitted spawn_complete
    // events. ALL hook-emitted telemetry (spawn_start and spawn_complete)
    // is excluded - double-count guard.
    for (const obj of parsed) {
      if (obj.event !== 'spawn_complete') continue;
      const data = obj.data || {};
      if (data.source === 'hook') continue;
      recordSpawn(obj.agent, Number(data.wall_seconds) || 0, data.tokens || {});
    }
  } else {
    // Pure ad-hoc session: dedup hook-emitted spawn_start/spawn_complete by
    // spawn_id so each real spawn counts exactly once, and a spawn whose
    // SubagentStop was lost (spawn_start with no paired spawn_complete)
    // still counts rather than being silently dropped. Legacy spawn_start
    // events written before DS-160 (no data.spawn_id) get a synthetic
    // per-event key so they still count individually - back-compat, no
    // dedup possible without a correlation id.
    let legacySyntheticCounter = 0;
    const bySpawnId = new Map();
    // First pass: every hook spawn_start is the counted spawn. Built first
    // so the enrichment pass below can always tell whether a spawn_complete's
    // paired_spawn_id resolves to an already-counted spawn.
    for (const obj of parsed) {
      const data = obj.data || {};
      if (obj.event !== 'spawn_start' || data.source !== 'hook') continue;
      const key = data.spawn_id || `__legacy_${legacySyntheticCounter++}__`;
      if (!bySpawnId.has(key)) {
        bySpawnId.set(key, { agent: obj.agent, wall: 0, tokens: null });
      }
    }
    // Second pass: a spawn_complete NEVER creates a new spawn count. When its
    // paired_spawn_id resolves to a spawn already counted above, it enriches
    // that spawn's wall_seconds AND tokens (completion metadata - tokens as
    // of the post-DS-160 token-resolution addition to
    // hooks/subagent-stop-spawn-emit.js; see that file's header for how
    // data.tokens is resolved, and why it is ABSENT rather than zero-filled
    // when unresolvable, which is exactly why `data.tokens || null` below
    // never manufactures a false zero-token enrichment). Any other
    // spawn_complete - unpaired (paired_spawn_id: null) OR paired to a
    // spawn_id not present in this session's spawn_starts - is dropped from
    // the aggregate entirely (see the DS-160 round-2 fix note in the doc
    // comment above for why: this consumer reads the whole file, so a
    // "missing" spawn_start here is not a scan-window artifact, and treating
    // it as a new spawn risks double-counting far more often than it
    // recovers a genuinely spawn_start-less spawn).
    for (const obj of parsed) {
      const data = obj.data || {};
      if (obj.event !== 'spawn_complete' || data.source !== 'hook') continue;
      if (!data.paired_spawn_id) continue;
      const existing = bySpawnId.get(data.paired_spawn_id);
      if (!existing) continue;
      // A capped/suspect wall_seconds (see hooks/subagent-stop-spawn-emit.js)
      // is emitted as null, not a fabricated ceiling value; Number(null)||0
      // naturally contributes 0 here rather than injecting a false duration.
      existing.wall = Number(data.wall_seconds) || 0;
      existing.agent = obj.agent || existing.agent;
      // data.tokens is present ONLY when the hook resolved a real
      // transcript; absent (not zero-filled) otherwise - `|| null` here
      // preserves that distinction rather than coercing an absent value
      // into a false zero-token enrichment.
      if (data.tokens) existing.tokens = data.tokens;
    }
    for (const rec of bySpawnId.values()) {
      recordSpawn(rec.agent, rec.wall, rec.tokens);
    }
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
 * spawn_complete events for the current session (conductor_direct is a
 * retired event name and is no longer counted - see :555 above).
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
    const rootDiag = resolveAgenticCwdWithDiagnostics(cwd);
    const agenticDir = path.join(rootDiag.root, '.agentic');
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
        agentic_root_drift_levels: rootDiag.driftLevels,
        agentic_root_found_git: rootDiag.foundGitAncestor,
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
    const markerPath = path.join(resolveAgenticCwd(cwd), '.agentic', 'learnings-agent.session');
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

const IDENTITY_SCOPE_FIELD = 'identity_scope';
const HANDLE_RE = /^[a-z0-9._-]{1,64}$/;

/**
 * Resolve effective identity via 6-tier total ordering:
 *   project-confirmed > profile-confirmed > global-confirmed >
 *   project-provisional > profile-provisional > global-provisional > null
 *
 * Delegates identity file traversal to the Python CLI's descriptor-relative
 * resolver because Node does not expose openat-style component traversal.
 * The helper is repo-relative, shell-free, time-bounded, and output-bounded.
 *
 * The existing three-branch write-vs-buffer gate (identity && !identity.provisional)
 * remains valid: confirmed at any scope -> direct write; provisional -> pending buffer.
 *
 * @param {string} cwd - The repo working directory (already validated by run()).
 * @returns {{developer_id: string, provisional: boolean}|null}
 */
function getIdentity(cwd) {
  try {
    const helper = path.resolve(__dirname, '..', 'bin', 'ds-identity');
    const result = spawnSync(helper, ['resolve-hook', '--cwd', cwd], {
      encoding: 'utf8',
      timeout: 2000,
      maxBuffer: 64 * 1024,
      stdio: ['ignore', 'pipe', 'ignore'],
      env: process.env,
    });
    if (result.error || result.status !== 0 || typeof result.stdout !== 'string') {
      return null;
    }
    const identity = JSON.parse(result.stdout);
    if (!identity || typeof identity !== 'object' || Array.isArray(identity)) return null;
    if (!HANDLE_RE.test(identity.developer_id || '')) return null;
    if (!['global', 'profile', 'project'].includes(identity[IDENTITY_SCOPE_FIELD])) {
      return null;
    }
    if (identity.provisional !== true && identity.provisional !== false) return null;
    if (
      identity[IDENTITY_SCOPE_FIELD] === 'profile'
      && typeof identity.config_dir !== 'string'
    ) return null;
    return identity;
  } catch (_) {
    return null;
  }
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
      '[dinostack] No developer identity set. Session telemetry is local-only.',
      'To enable team telemetry: ds-identity init <handle>',
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
    const eventsPath = path.join(resolveAgenticCwd(cwd), '.agentic', 'events.jsonl');
    const agg = scanSessionAggregate(eventsPath, sessionId, cachedRaw);
    if (!agg) return null;

    // Re-shape by_agent: flatten 4-band tokens to a single tokens_total for the
    // session-log format consumed by ds-cost team.
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
 * Generate a UUID v4 using crypto.randomUUID when available (Node 14.17+),
 * falling back to a crypto.randomBytes-derived v4 construction for older
 * runtimes. Both paths draw from a cryptographically secure random source -
 * never Math.random, which is not suitable for identifier generation.
 *
 * @returns {string} UUID v4 string.
 */
function generateUuid() {
  const crypto = require('crypto');
  if (typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // Fallback: RFC 4122 v4 via crypto.randomBytes
  const bytes = crypto.randomBytes(16);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10
  const hex = bytes.toString('hex');
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20, 32),
  ].join('-');
}

// DS-158 round 3 Major 1: the JS-side spawnSync ceiling below must be
// provably derived from bin/ds-identity's SESSION_LOG_LOCK_BUDGET_SECONDS,
// not merely commented as such. SESSION_LOG_LOCK_BUDGET_MS mirrors that
// Python constant (5.0s) and is now, as of round 3, the SHARED lock-retry
// budget for the helper's WHOLE invocation - cmd_write_hook computes one
// deadline and passes it to both the project and global appends, so a
// permanently-contended lock on either target costs this budget once, not
// twice (round 2's bug). HELPER_STARTUP_HEADROOM_MS covers process
// startup/imports, the `git symbolic-ref` probe above, and the
// read/render/write work outside the lock itself.
// bin/tests/test_agentic_identity.py::test_hook_ceiling_matches_python_budget
// parses this file and bin/ds-identity and fails the moment either value
// changes without the other - this is enforced by that test, not by this
// comment.
const SESSION_LOG_LOCK_BUDGET_MS = 5000;
const HELPER_STARTUP_HEADROOM_MS = 1000;
const WRITE_HOOK_SPAWN_CEILING_MS = SESSION_LOG_LOCK_BUDGET_MS + HELPER_STARTUP_HEADROOM_MS;

/**
 * Best-effort read of the write-hook helper's partial-progress checkpoint
 * (DS-158 round 3 Major 2). Returns `{}` on any absence/parse failure -
 * the checkpoint is a diagnostic aid, never a correctness dependency.
 *
 * @param {string} statusFile - Path passed to the helper via --status-file.
 * @returns {object}
 */
function readWriteHookCheckpoint(statusFile) {
  try {
    const raw = fs.readFileSync(statusFile, 'utf8');
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch (_) {
    return {};
  }
}

/**
 * Persist one telemetry record through the descriptor-safe Python helper.
 * Identity resolution is compared again in the helper before any write, so an
 * identity swap between resolution and persistence fails closed. The helper
 * independently reports project/global/pending outcomes for health telemetry.
 *
 * DS-158 round 2: this call is deliberately single-shot, not wrapped in its
 * own retry. The Python helper already retries its flock acquisition with
 * backoff across its own bounded wall-clock budget (see the spawnSync
 * `timeout` comment below); a caller-side retry here would re-spawn the
 * whole subprocess and could double the worst-case Stop-hook latency for no
 * added chance of success, since a second attempt would race the same
 * contention the first one just spent its full budget failing to clear.
 * On a project/global write failure, status is surfaced through
 * recordHealth() -> flushHealth() (unconditional, not debug-gated) rather
 * than retried here.
 *
 * DS-158 round 3 Major 2: on a spawnSync error/timeout (no parseable
 * stdout), this now consults the helper's --status-file checkpoint before
 * concluding total failure. A target present in the checkpoint gets its
 * confirmed outcome recorded normally; a target absent from it (never
 * attempted, or killed mid-attempt) is recorded as indeterminate via
 * recordHealthUnknown, never as a confirmed failure.
 */
function writeTelemetrySafely(cwd, identity, sessionId, cachedRaw) {
  const confirmed = Boolean(identity && !identity.provisional);
  const effectiveSessionId = sessionId || generateUuid();
  const statusFile = path.join(
    os.tmpdir(),
    `ds-identity-write-hook-${process.pid}-${effectiveSessionId}.json`,
  );
  try {
    const totals = computeSessionTotals(cwd, sessionId, cachedRaw);
    const data = totals || {
      wall_seconds: 0,
      tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
      spawn_count: 0,
      by_agent: {},
    };
    let branch = '';
    try {
      branch = execSync('git symbolic-ref --short HEAD', {
        cwd, timeout: 3000, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
    } catch (_) { /* detached HEAD or non-git dir */ }

    const helper = path.resolve(__dirname, '..', 'bin', 'ds-identity');
    const request = JSON.stringify({
      identity,
      session_uuid: effectiveSessionId,
      branch,
      data,
    });
    const result = spawnSync(
      helper,
      ['write-hook', '--cwd', cwd, '--status-file', statusFile],
      {
        encoding: 'utf8',
        // DS-158 round 2/3: bin/ds-identity's session-log append(s) retry
        // their flock with backoff across a SESSION_LOG_LOCK_BUDGET_SECONDS
        // (5.0s) wall-clock budget, capped at
        // SESSION_LOG_LOCK_PER_ATTEMPT_CAP_SECONDS (1.0s) per attempt.
        // As of round 3, that budget is SHARED across the whole helper
        // invocation (both the project and global append below draw from
        // one deadline computed once in cmd_write_hook), so this ceiling
        // is WRITE_HOOK_SPAWN_CEILING_MS = SESSION_LOG_LOCK_BUDGET_MS +
        // HELPER_STARTUP_HEADROOM_MS, not a multiple of the budget - see
        // those constants' definitions above this function for the
        // cross-file consistency test. A genuinely contended write must
        // exhaust its own retry budget and report a graceful failure back
        // to recordHealth(), not get SIGKILLed here first; if it IS
        // SIGKILLed (e.g. real budget/headroom drift), the --status-file
        // checkpoint below still lets us report per-target outcomes
        // honestly instead of asserting uniform failure.
        timeout: WRITE_HOOK_SPAWN_CEILING_MS,
        maxBuffer: 64 * 1024,
        stdio: ['pipe', 'pipe', 'ignore'],
        input: request,
        env: process.env,
      },
    );
    if (result.error || result.status !== 0 || typeof result.stdout !== 'string') {
      throw result.error || new Error('safe telemetry helper failed');
    }
    const status = JSON.parse(result.stdout);
    if (!status || typeof status !== 'object' || Array.isArray(status)) {
      throw new Error('safe telemetry helper returned invalid status');
    }
    if (confirmed) {
      recordHealth('writeSessionLog', status.project === true, status.project === true ? null : 'safe helper refused project log');
      recordHealth('writeSessionLogGlobal', status.global === true, status.global === true ? null : 'safe helper refused global log');
    } else {
      recordHealth('writePendingBuffer', status.pending === true, status.pending === true ? null : 'safe helper refused pending record');
    }
  } catch (_) {
    // DS-158 round 3 Major 2: no parseable stdout - consult the helper's
    // partial-progress checkpoint before asserting uniform failure. A
    // target present in the checkpoint has a confirmed outcome; a target
    // absent from it (never attempted, or interrupted mid-attempt) is
    // reported as indeterminate, not as a confirmed failure.
    const checkpoint = readWriteHookCheckpoint(statusFile);
    const errMsg = _ && _.message;
    if (confirmed) {
      if (typeof checkpoint.project === 'boolean') {
        recordHealth('writeSessionLog', checkpoint.project, checkpoint.project ? null : 'safe helper refused project log');
      } else {
        recordHealthUnknown('writeSessionLog', errMsg);
      }
      if (typeof checkpoint.global === 'boolean') {
        recordHealth('writeSessionLogGlobal', checkpoint.global, checkpoint.global ? null : 'safe helper refused global log');
      } else {
        recordHealthUnknown('writeSessionLogGlobal', errMsg);
      }
    } else if (typeof checkpoint.pending === 'boolean') {
      recordHealth('writePendingBuffer', checkpoint.pending, checkpoint.pending ? null : 'safe helper refused pending record');
    } else {
      recordHealthUnknown('writePendingBuffer', errMsg);
    }
  } finally {
    try { fs.unlinkSync(statusFile); } catch (_e) { /* absent or never created */ }
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
    const cursorPath = path.join(resolveAgenticCwd(cwd), '.agentic', '.capture-gap-last-sweep');

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
  const eventsPath = cwd ? path.join(resolveAgenticCwd(cwd), '.agentic', 'events.jsonl') : null;
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
      // Confirmed identity: descriptor-safe project log + global mirror.
      writeTelemetrySafely(cwd, identity, sessionId, cachedEventsRaw);
    } else {
      // Provisional or no identity: descriptor-safe pending buffer.
      writeTelemetrySafely(cwd, identity, sessionId, cachedEventsRaw);
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
  module.exports = {
    recordHealth,
    recordHealthUnknown,
    flushHealth,
    healthOutcomes,
    appendCaptureGapNoticeToContextMd,
    readWriteHookCheckpoint,
  };
}
