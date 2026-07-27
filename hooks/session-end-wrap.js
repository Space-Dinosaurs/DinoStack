#!/usr/bin/env node

/**
 * Purpose: Claude Code SessionEnd hook for the daemon-driven deferred-`/ds-wrap`
 *          feature. On a genuine terminal session end it performs the SOLE
 *          pending->ready marker transition (finalizeReady) and removes the
 *          session heartbeat, then - when the project opts in via the
 *          `deferred_wrap_daemon` config toggle - launches the wrap daemon
 *          detached so a forgotten session is enriched in the background. It is
 *          the load-bearing stop on the daemon's own headless `/ds-wrap-deferred`
 *          run: under the AGENTIC_WRAP_DAEMON loop-guard it exits immediately
 *          without finalizing or launching, so the daemon can never re-wrap
 *          itself forever. There is NO stale-sweep here (CRITICAL-A). On a
 *          terminal reason it ALSO marks any active loop-state.json/
 *          batch-state.json interrupted via hooks/lib/state-mark.js
 *          markInterrupted - this hook fires once per SESSION (unlike the
 *          Stop hook, which fires once per turn), making it the correct home
 *          for the terminal interrupted-mark.
 *
 * Public API: none (CLI script). Invoked by the Claude Code SessionEnd hook with
 *             the hook JSON payload on stdin (fd 0):
 *             { session_id, transcript_path, cwd, hook_event_name:"SessionEnd",
 *               reason }. Not imported by any module.
 *
 * Upstream deps: Node built-ins only (fs, path, child_process) plus three local
 *                CommonJS modules: hooks/lib/wrap-marker.js (the deferred-`/ds-wrap`
 *                marker single source of truth), hooks/lib/stdin-guard.js
 *                (readStdinGuarded, bounded stdin reader), and
 *                hooks/lib/state-mark.js (markInterrupted - shared with
 *                hooks/stop-context.js's --cadence=session dispatch). Reads
 *                stdin (fd 0) via the bounded reader and
 *                [cwd]/.agentic/config.json (deferred_wrap_daemon toggle).
 *                Writes [cwd]/.agentic/loop-state.json (legacy), every
 *                per-ticket keyed sibling
 *                [cwd]/.agentic/loop-state-<LOOP_KEY>.json, and
 *                [cwd]/.agentic/batch-state.json (via state-mark.js, on a
 *                terminal reason only - this hook derives no key and
 *                enumerates no path itself; state-mark.js's candidatePaths(cwd)
 *                resolves the set, always including the legacy path, and
 *                markInterrupted's per-file ownership predicate decides which
 *                are marked). Spawns
 *                `node <repo>/hooks/wrap-daemon.js <cwd>` detached when the
 *                toggle is true (the daemon file is built in U3 and may not
 *                exist yet - the detached spawn fails silently until it lands).
 *
 * Downstream consumers: Claude Code SessionEnd hook (wired by .claude/install.sh
 *                       in U4). No code imports this file.
 *
 * Failure modes: Fully fail-open. Stdin is read via lib/stdin-guard.js's
 *                readStdinGuarded(), which never rejects and resolves '' if the
 *                spawning harness never closes stdin (the exact app-close failure
 *                class this hook exists to survive), bounding worst-case latency
 *                instead of blocking indefinitely on a synchronous read. run() is
 *                async (it awaits the stdin read); the call site chains
 *                `.catch(() => {})` (equivalent to the previous synchronous
 *                try/catch) followed by `.finally(() => process.exit(0))` so the
 *                process ALWAYS exits 0, but only once run() has settled - a
 *                trailing synchronous process.exit(0) would otherwise fire before
 *                the awaited read completes and silently skip finalizeReady /
 *                removeHeartbeat / launchDaemonDetached / markInterrupted. A hook
 *                error must never block or delay session shutdown. Defensive
 *                stdin parse (malformed/empty payload -> exit 0). Under the
 *                AGENTIC_WRAP_DAEMON=1 loop-guard the hook
 *                exits 0 immediately: no finalize, no heartbeat removal, no daemon
 *                launch, no markInterrupted. finalizeReady runs ONLY on a
 *                terminal reason
 *                {clear, logout, prompt_input_exit, bypass_permissions_disabled,
 *                other}; reason `resume` does NOT finalize (the session may
 *                continue) and the marker stays `pending` (recovered by manual
 *                `/ds-wrap`, never auto-wrapped - the deliberate CRITICAL-A trade).
 *                The daemon launch is best-effort detached + unref'd; if the
 *                daemon file is absent or the spawn errors, it is swallowed.
 *                markInterrupted runs on the SAME terminal-reason set as
 *                finalizeReady (gated on sessionId being present) but is NOT
 *                gated on deferred_wrap_daemon (that toggle defaults false;
 *                gating markInterrupted on it would make the terminal mark a
 *                no-op on the common case) and runs in its own try/catch so a
 *                failure there can never block finalizeReady, heartbeat
 *                removal, or the daemon launch. It deliberately does NOT write
 *                loop-state's `last_updated` field - see
 *                hooks/lib/state-mark.js for why.
 *
 * Performance: standard. A few synchronous fs reads (marker + config + the two
 *              state files) and one detached child spawn that the parent never
 *              waits on; the hook returns essentially immediately and adds no
 *              measurable shutdown latency.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const wrapMarker = require('./lib/wrap-marker.js');
const { readStdinGuarded } = require('./lib/stdin-guard.js');
const stateMark = require('./lib/state-mark.js');

// Terminal SessionEnd reasons that warrant finalizing a pending marker to
// `ready`. `resume` is deliberately EXCLUDED: a resumed session may continue, so
// promoting it could let the daemon resume a live session (CRITICAL-A). Any
// reason not in this set (including an absent/unknown reason) is treated as
// non-terminal and does NOT finalize.
const TERMINAL_REASONS = new Set([
  'clear',
  'logout',
  'prompt_input_exit',
  'bypass_permissions_disabled',
  'other',
]);

/**
 * Read the `deferred_wrap_daemon` toggle from [cwd]/.agentic/config.json.
 * Fail-open: absent file, unreadable file, parse error, or absent key all
 * resolve to false (do NOT launch the daemon).
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
 * Launch the wrap daemon detached and fully fd-redirected so the hook never
 * blocks (the Node analogue of the version-check-core.sh
 * `nohup ... </dev/null >/dev/null 2>&1 & disown` pattern). The daemon path is
 * resolved relative to THIS hook file (sibling wrap-daemon.js). The daemon file
 * is built in U3 and may not exist yet - the spawn then errors and is swallowed
 * (fail-open). Never throws.
 */
function launchDaemonDetached(cwd) {
  try {
    const daemonPath = path.join(__dirname, 'wrap-daemon.js');
    const child = spawn(process.execPath, [daemonPath, cwd], {
      detached: true,
      stdio: 'ignore',
      // The daemon must run in the main project dir (no worktree).
      cwd,
    });
    // Swallow async spawn errors (e.g. daemon file absent until U3) - fail-open.
    child.on('error', () => {});
    child.unref();
  } catch (_) {
    // Synchronous spawn failure - swallow; fail-open.
  }
}

async function run() {
  // --- 1. Read + parse stdin (defensive; fail-open) ---
  const raw = await readStdinGuarded();
  if (!raw.trim()) return;

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (_) {
    return; // malformed payload -> exit 0
  }
  if (!payload || typeof payload !== 'object') return;

  // --- 2. Loop-guard: bail IMMEDIATELY under AGENTIC_WRAP_DAEMON=1 ---
  // This is the load-bearing stop on the daemon's own headless `/ds-wrap-deferred`
  // SessionEnd: do NOT finalize, do NOT remove the heartbeat, do NOT launch the
  // daemon. Without this the daemon would re-wrap forever.
  if (wrapMarker.daemonGuardActive()) return;

  // --- 3. Extract fields (all optional - guard every access) ---
  const cwd = (typeof payload.cwd === 'string' && payload.cwd.trim())
    ? payload.cwd.trim()
    : null;
  if (!cwd) return;

  const sessionId = (typeof payload.session_id === 'string' && payload.session_id.trim())
    ? payload.session_id.trim()
    : null;

  const reason = (typeof payload.reason === 'string') ? payload.reason.trim() : '';

  // --- 3b. Mark loop-state.json/batch-state.json interrupted on a terminal
  // reason ONLY. This is the terminal cadence for the loop/batch orchestration
  // state: this hook fires once per SESSION (not once per turn like the Stop
  // hook), so it is the correct place for the interrupted-mark to live. Gated
  // on sessionId being present (mirrors the finalize gate below) but
  // deliberately NOT gated on deferredDaemonEnabled - that toggle defaults
  // false, so gating this write on it would ship a no-op on the common case.
  // Own try/catch so a failure here can never block finalizeReady, heartbeat
  // removal, or the daemon launch below.
  if (sessionId && TERMINAL_REASONS.has(reason)) {
    try {
      stateMark.markInterrupted(cwd, sessionId);
    } catch (_) {
      // Fail-open - never block session shutdown.
    }
  }

  // --- 4. Finalize on a terminal reason ONLY ---
  // finalizeReady is the SOLE pending->ready transition (no sweep, no daemon, no
  // SessionStart - CRITICAL-A). It carries no branch/sha and no-ops in the lib on
  // any non-pending marker. `resume` is non-terminal: the marker stays `pending`
  // and is recovered only by a manual `/ds-wrap` (never auto-wrapped). Both
  // finalizeReady and removeHeartbeat require a session id.
  // Gated on deferredDaemonEnabled so the flag-off default never accumulates markers.
  if (sessionId && TERMINAL_REASONS.has(reason) && deferredDaemonEnabled(cwd)) {
    wrapMarker.finalizeReady(cwd, sessionId);
    wrapMarker.removeHeartbeat(cwd, sessionId);
  }

  // --- 5. Launch the daemon detached, gated on the opt-in toggle ---
  // Independent of the finalize decision: even when this session was `resume`
  // (no finalize), launching lets the daemon drain any OTHER session's already
  // `ready` marker. Absent/false toggle -> never launch.
  if (deferredDaemonEnabled(cwd)) {
    launchDaemonDetached(cwd);
  }
}

// --- Fail-open wrapper: ALWAYS exit 0, never block session shutdown ---
// .catch(() => {}) swallows everything (a SessionEnd hook must never throw);
// .finally(() => process.exit(0)) ensures the process exits only after run()
// settles, so finalizeReady / removeHeartbeat / launchDaemonDetached always get
// a chance to run before shutdown.
run().catch(() => {}).finally(() => process.exit(0));
