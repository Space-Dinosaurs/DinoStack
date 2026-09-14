#!/usr/bin/env node

/**
 * Purpose: Registered top-level Stop hook. Thin wrapper around
 *          hooks/lib/overreach-detector.js's computeOverreach: reads the
 *          REAL Stop payload from stdin ({session_id, transcript_path, cwd,
 *          hook_event_name, stop_hook_active} - there is no `transcript`
 *          array field on the live payload; an earlier version read
 *          payload.transcript, which does not exist, and was silently
 *          inert in production), resolves the configured (or calibrated
 *          default) threshold, and on ratio_trigger appends a
 *          conductor_overreach event to .agentic/events.jsonl and emits an
 *          advisory additionalContext line. Every path exits 0, but this is
 *          NOT the same as "never blocks the stop": the Claude Code harness
 *          surfaces a Stop hook's `additionalContext` as "Stop hook
 *          feedback" and CONTINUES the turn rather than letting it end.
 *          Since `ratio_trigger` is computed cumulatively over the whole
 *          transcript and is monotonic (only a spawn can clear it, and it
 *          clears it permanently for the rest of the session), an unguarded
 *          fire would refire on every subsequent Stop call for the rest of
 *          the session - re-entrant or not.
 *
 *          TWO layers bound that loop, matching the two-layer pattern
 *          hooks/lib/loop_guard.py documents for the sibling Python Stop
 *          hooks (enforce-no-abdication.py, enforce-turn-shape.py), ported
 *          to this hook's own JS runtime and its own (weaker, monotonic
 *          rather than reset-per-turn) trigger shape:
 *            Layer 1: `payload.stop_hook_active === true` - the primary
 *                     re-entrancy guard. Exits 0 immediately, before
 *                     computing overreach or appending the event, on any
 *                     Stop call the harness itself re-invoked after a prior
 *                     Stop hook's output kept the turn open.
 *            Layer 2: a once-per-session sentinel file at
 *                     [resolved root]/.agentic/.conductor-overreach-fired-
 *                     <sanitized session_id> - backstops Claude Code bug
 *                     #54360, under which `stop_hook_active` can fail to
 *                     propagate when a UserPromptSubmit hook interleaves
 *                     system reminders (this repo has such hooks). A
 *                     once-per-session sentinel was chosen over a JS port of
 *                     loop_guard's counter-cap (cap 2, reset-on-genuine-
 *                     user-turn) shape because this trigger, unlike the
 *                     abdication/turn-shape ones, is monotonic within a
 *                     session: it can never go from true back to false
 *                     except via a spawn, which clears it permanently. A
 *                     cap-2 counter would still allow the loop to run twice
 *                     before backstopping; a sentinel bounds it at exactly 1
 *                     and needs no reset logic, since a genuine new user
 *                     turn cannot make the measured condition any less
 *                     true. The sentinel is checked and (on a successful
 *                     write) set BEFORE the event is appended or the
 *                     advisory is emitted, and mirrors loop_guard's
 *                     fail-toward-silence discipline: if the sentinel write
 *                     fails, or no session_id is available to key it on, the
 *                     hook does NOT emit - an advisory or event emitted
 *                     without a persisted loop bound is exactly the
 *                     unbounded case Layer 2 exists to prevent. One
 *                     zero-byte sentinel file accumulates per session
 *                     forever otherwise (no other code path removes one,
 *                     and hooks/lib/state-mark.js's own readdirSync of
 *                     .agentic/ on every turn would see a monotonically
 *                     growing entry list), so a successful write also runs
 *                     a best-effort age-based prune (7-day retention,
 *                     _pruneAgedSentinels) - never a single shared/
 *                     most-recent-session file instead, since two
 *                     concurrent sessions would then overwrite each
 *                     other's marker and each could re-fire indefinitely,
 *                     the exact failure this guard exists to prevent. The
 *                     prune runs only AFTER the current session's own
 *                     write already succeeded, so a prune failure can
 *                     never affect whether the CURRENT advisory fires.
 *                     _markFired also unlinks its own `.tmp.<pid>` staging
 *                     file if writeFileSync succeeds but renameSync fails,
 *                     rather than leaking it.
 *
 * Public API: primarily a CLI entry point, invoked by the Claude Code Stop
 *             hook per .claude/settings.json. Also exports four
 *             underscore-prefixed internals (_sentinelPath, _hasFired,
 *             _markFired, _pruneAgedSentinels) via a test-only
 *             module.exports at end of file, so
 *             hooks/tests/test-conductor-overreach-nudge.js can shim-load
 *             and unit-test _markFired's rename-failure path directly
 *             (mirroring hooks/stop-context.js's identical precedent) -
 *             this file therefore now HAS a requirer, and the exported
 *             names are an internal test seam, not a public contract for
 *             other production modules to depend on.
 *
 * Upstream deps: Node built-ins (fs, path), hooks/lib/stdin-guard.js
 *                (readStdinGuarded), hooks/lib/overreach-detector.js
 *                (computeOverreach, DEFAULT_THRESHOLD - reads and parses
 *                payload.transcript_path itself, bounded by a size
 *                ceiling), hooks/lib/repo-root.js (resolveAgenticCwd -
 *                anchors both reads/writes below to the repo root instead
 *                of the raw payload cwd). Reads
 *                [resolved root]/.agentic/config.json (optional,
 *                conductor_overreach_threshold key; config-reversible) and,
 *                for the Layer 2 sentinel, checks for the existence of
 *                [resolved root]/.agentic/.conductor-overreach-fired-<id>.
 *
 * Downstream consumers: none - terminal hook. Appends to
 *                        [cwd]/.agentic/events.jsonl, read by bin/ds-cost
 *                        and content/references/events-log.md consumers.
 *                        Also writes the Layer 2 sentinel file (see above),
 *                        consumed only by this hook's own future
 *                        invocations within the same session.
 *
 * Failure modes: fail-open on any error - missing/malformed stdin, missing
 *                fields, unreadable/malformed config, an unavailable or
 *                unparseable transcript (computeOverreach returns
 *                available:false with a transcript_note in that case -
 *                treated the same as ratio_trigger:false here, i.e. no
 *                event, no advisory; never a fabricated zero-call
 *                measurement mistaken for a real one), or a write failure
 *                on events.jsonl all result in a silent exit 0. A missing
 *                session_id, or a failed Layer 2 sentinel write, also
 *                results in a silent exit 0 with NO event and NO advisory
 *                (fail toward silence, not toward an unbounded fire - see
 *                the Layer 2 note above). No suppression-mute logic exists
 *                anywhere in this hook by design (a prior design that
 *                grepped the transcript for an injected harness-suppression
 *                phrase and muted the advisory was removed by Skeptic
 *                Critical finding - do not re-derive it, and do not grep
 *                the transcript for injected-prompt phrases). Given a
 *                fresh (non-re-entrant, not-yet-fired-this-session) Stop
 *                call, the advisory fires unconditionally whenever
 *                ratio_trigger is true, regardless of transcript content.
 *
 * Performance: single stdin read + single bounded transcript file read/pass
 *              (see overreach-detector.js) + one best-effort sentinel
 *              existence check/write + one best-effort events.jsonl append.
 *              On a successful sentinel write, also one readdirSync of
 *              .agentic/ plus a statSync (and, for aged entries, an
 *              unlinkSync) per sentinel-prefixed entry found there
 *              (_pruneAgedSentinels) - bounded by however many sentinel
 *              files have accumulated since the last successful prune, not
 *              by transcript size. No subprocess calls.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const { readStdinGuarded } = require('./lib/stdin-guard.js');
const { computeOverreach, DEFAULT_THRESHOLD } = require('./lib/overreach-detector.js');
const { resolveAgenticCwd } = require('./lib/repo-root.js');

/**
 * @param {string} cwd
 * @returns {number}
 */
function _resolveThreshold(cwd) {
  try {
    const configPath = path.join(resolveAgenticCwd(cwd), '.agentic', 'config.json');
    if (!fs.existsSync(configPath)) return DEFAULT_THRESHOLD;
    const raw = fs.readFileSync(configPath, 'utf8');
    const config = JSON.parse(raw);
    const v = config && config.conductor_overreach_threshold;
    if (typeof v === 'number' && v > 0) return v;
    return DEFAULT_THRESHOLD;
  } catch (_) {
    return DEFAULT_THRESHOLD;
  }
}

/**
 * Append a single conductor_overreach event line. Best-effort, atomic
 * single-line append (matches writeSessionTotal's pattern in
 * hooks/stop-context.js). Any error is swallowed.
 *
 * @param {string} cwd
 * @param {string|null} sessionId
 * @param {{conductor_tool_calls:number, live_or_completed_spawns:number,
 *   ratio_trigger:boolean, whitelisted_reads_excluded:number,
 *   transcript_note:string|null}} result
 */
function _appendEvent(cwd, sessionId, result) {
  try {
    const agenticDir = path.join(resolveAgenticCwd(cwd), '.agentic');
    fs.mkdirSync(agenticDir, { recursive: true });
    const eventsPath = path.join(agenticDir, 'events.jsonl');
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      phase: 'stop',
      event: 'conductor_overreach',
      agent: null,
      task_id: null,
      data: {
        source: 'hook',
        session_uuid: sessionId || null,
        conductor_tool_calls: result.conductor_tool_calls,
        live_or_completed_spawns: result.live_or_completed_spawns,
        ratio_trigger: result.ratio_trigger,
        whitelisted_reads_excluded: result.whitelisted_reads_excluded,
        transcript_note: result.transcript_note,
      },
    });
    fs.appendFileSync(eventsPath, line + '\n');
  } catch (_) {
    // Silent failure - consistent with the other events.jsonl writers.
  }
}

/**
 * Layer 2 loop-guard sentinel path: one file per session_id. Sanitizes the
 * id to a filesystem-safe token (session_id is expected to be a UUID, but
 * this does not trust that assumption).
 *
 * @param {string} cwd
 * @param {string} sessionId
 * @returns {string}
 */
const _SENTINEL_PREFIX = '.conductor-overreach-fired-';
const _SENTINEL_RETENTION_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

function _sentinelPath(cwd, sessionId) {
  const safeId = sessionId.replace(/[^a-zA-Z0-9_-]/g, '_');
  return path.join(resolveAgenticCwd(cwd), '.agentic', `${_SENTINEL_PREFIX}${safeId}`);
}

/**
 * Best-effort prune of sentinel files older than _SENTINEL_RETENTION_MS.
 * One zero-byte sentinel accumulates per session forever otherwise (no
 * other code path ever removes one) - hooks/lib/state-mark.js's
 * readdirSync of .agentic/ on every turn would see a monotonically
 * growing entry list. Never a single shared/most-recent-session file
 * instead: two concurrent sessions would overwrite each other's marker
 * and each could then re-fire indefinitely, exactly the failure this
 * guard exists to prevent - one file per session is load-bearing, so
 * this prunes by AGE, not by count or "most recent".
 *
 * Every failure mode here is silent and non-fatal: this function is
 * called only AFTER the current session's own sentinel write has already
 * succeeded, so a prune failure can never affect whether the CURRENT
 * advisory fires - it only means old sentinels accumulate for one more
 * cycle.
 *
 * @param {string} cwd
 */
function _pruneAgedSentinels(cwd) {
  try {
    const agenticDir = path.join(resolveAgenticCwd(cwd), '.agentic');
    const now = Date.now();
    for (const name of fs.readdirSync(agenticDir)) {
      if (!name.startsWith(_SENTINEL_PREFIX)) continue;
      const entryPath = path.join(agenticDir, name);
      try {
        const stat = fs.statSync(entryPath);
        if (now - stat.mtimeMs > _SENTINEL_RETENTION_MS) {
          fs.unlinkSync(entryPath);
        }
      } catch (_) {
        // Per-entry best-effort: a stat/unlink race or permission error on
        // one entry must not abort the sweep of the rest.
      }
    }
  } catch (_) {
    // .agentic/ unreadable, or any other error - silent, non-fatal.
  }
}

/**
 * @param {string} cwd
 * @param {string} sessionId
 * @returns {boolean} true iff the sentinel already exists (this session has
 *   already fired the advisory once). Fails closed to false (not-yet-fired)
 *   on any read error - a stat failure must never itself block the fire,
 *   since _markFired below is the actual loop-bound enforcement point.
 */
function _hasFired(cwd, sessionId) {
  try {
    return fs.existsSync(_sentinelPath(cwd, sessionId));
  } catch (_) {
    return false;
  }
}

/**
 * Persist the Layer 2 sentinel BEFORE the caller emits anything. Atomic
 * per-process tmp-file + rename, matching hooks/lib/loop_guard.py's
 * write_counter discipline. On a successful write, also runs the
 * best-effort age-based prune (_pruneAgedSentinels) so the sentinel
 * population stays bounded. The write outcome (`wrote`) is fully
 * determined by the write/rename try block BEFORE the prune is ever
 * called, and the prune call is itself independently wrapped - so a
 * prune failure structurally CANNOT flip this function's return value,
 * not merely by relying on _pruneAgedSentinels's own internal catch-all.
 *
 * @param {string} cwd
 * @param {string} sessionId
 * @returns {boolean} true on a successful write. The caller MUST treat
 *   false as "do not emit" - see the module docstring's Layer 2 section.
 */
function _markFired(cwd, sessionId) {
  const agenticDir = path.join(resolveAgenticCwd(cwd), '.agentic');
  const sentinelPath = _sentinelPath(cwd, sessionId);
  const tmp = `${sentinelPath}.tmp.${process.pid}`;
  let wrote = false;
  try {
    fs.mkdirSync(agenticDir, { recursive: true });
    fs.writeFileSync(tmp, '');
    try {
      fs.renameSync(tmp, sentinelPath);
    } catch (renameErr) {
      // writeFileSync succeeded but renameSync failed: clean up the
      // orphaned tmp file rather than leaking it, then propagate to the
      // outer catch so this call still reports failure.
      try { fs.unlinkSync(tmp); } catch (_) { /* best-effort */ }
      throw renameErr;
    }
    wrote = true;
  } catch (_) {
    wrote = false;
  }
  if (wrote) {
    // Independently wrapped: even though _pruneAgedSentinels never
    // throws by its own contract, this call site does not rely on that
    // contract to protect `wrote` - `wrote` is already fixed above.
    try {
      _pruneAgedSentinels(cwd);
    } catch (_) { /* best-effort; never affects the write outcome */ }
  }
  return wrote;
}

async function run() {
  try {
    const raw = await readStdinGuarded();
    if (!raw || !raw.trim()) process.exit(0);

    let payload;
    try {
      payload = JSON.parse(raw);
    } catch (_) {
      process.exit(0);
    }

    const cwd = (typeof payload.cwd === 'string' && payload.cwd.trim())
      ? payload.cwd.trim()
      : null;
    if (!cwd) process.exit(0);

    // Re-entrant Stop call: the harness re-invokes Stop after a prior Stop
    // hook's additionalContext kept the turn open. The overreach trigger is
    // computed cumulatively over the whole transcript, so it is invariant
    // across a text-only continuation reply - without this guard the
    // advisory would refire on every re-entry forever. Exit before
    // computing overreach or appending the event: a single event per stop,
    // not one per re-entry.
    if (payload.stop_hook_active === true) process.exit(0);

    const sessionId = (typeof payload.session_id === 'string' && payload.session_id.trim())
      ? payload.session_id.trim()
      : null;

    const transcriptPath = (typeof payload.transcript_path === 'string' && payload.transcript_path.trim())
      ? payload.transcript_path.trim()
      : null;

    const threshold = _resolveThreshold(cwd);
    const result = computeOverreach(transcriptPath, threshold);

    // available:false (unreadable/unparseable/oversized transcript) never
    // fires ratio_trigger by construction (computeOverreach's own
    // contract), so this check alone is sufficient to skip both the
    // unavailable case and the genuine below-threshold case.
    if (!result.ratio_trigger) process.exit(0);

    // Layer 2 backstop (CC bug #54360: stop_hook_active can fail to
    // propagate). Without a session_id there is no key to bound the loop
    // on, so fail toward silence rather than emit unbounded. Likewise, if
    // this session has already fired once, or the sentinel write itself
    // fails, do not emit - see the module docstring's Layer 2 section.
    if (!sessionId) process.exit(0);
    if (_hasFired(cwd, sessionId)) process.exit(0);
    if (!_markFired(cwd, sessionId)) process.exit(0);

    _appendEvent(cwd, sessionId, result);

    const advisory =
      `Advisory: this session made ${result.conductor_tool_calls} investigation-shaped ` +
      'tool calls with zero subagent spawns; if this was diagnosis rather than ' +
      'fact-confirmation, consider whether it should have been delegated.';

    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'Stop',
        additionalContext: advisory,
      },
    }));
    process.exit(0);
  } catch (_) {
    // Fail-open: exit 0 without emitting anything on any unexpected error.
    process.exit(0);
  }
}

run();

// Test shim: this module.exports block executes on EVERY load, including
// direct CLI invocation - run() above is async and unawaited, so control
// reaches here immediately regardless of whether a test replaced the
// `run();` call. That is harmless in production: nothing requires this
// file as a module outside a test (it is invoked as a CLI script, and
// require()'s return value has no observer), so the assignment is inert.
// It exists so hooks/tests/test-conductor-overreach-nudge.js can shim-load
// this file (replacing `run();` with a no-op first) and call these
// internals directly, mirroring hooks/stop-context.js's identical
// precedent - see that file's own trailing comment for the same pattern
// (its comment states the same "only reached when a test replaces run()"
// claim, which is equally inaccurate there for the same async/unawaited
// reason; left unchanged there as out of scope for this fix).
if (typeof module !== 'undefined') {
  module.exports = {
    _sentinelPath,
    _hasFired,
    _markFired,
    _pruneAgedSentinels,
  };
}
