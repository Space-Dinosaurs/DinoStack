#!/usr/bin/env node

/**
 * Purpose: Claude Code SessionEnd hook for the daemon-driven deferred-`/wrap`
 *          feature. On a genuine terminal session end it performs the SOLE
 *          pending->ready marker transition (finalizeReady) and removes the
 *          session heartbeat, then - when the project opts in via the
 *          `deferred_wrap_daemon` config toggle - launches the wrap daemon
 *          detached so a forgotten session is enriched in the background. It is
 *          the load-bearing stop on the daemon's own headless `/wrap-deferred`
 *          run: under the AGENTIC_WRAP_DAEMON loop-guard it exits immediately
 *          without finalizing or launching, so the daemon can never re-wrap
 *          itself forever. There is NO stale-sweep here (CRITICAL-A).
 *
 * Public API: none (CLI script). Invoked by the Claude Code SessionEnd hook with
 *             the hook JSON payload on stdin (fd 0):
 *             { session_id, transcript_path, cwd, hook_event_name:"SessionEnd",
 *               reason }. Not imported by any module.
 *
 * Upstream deps: Node built-ins only (fs, path, child_process) plus the local
 *                CommonJS module hooks/lib/wrap-marker.js (the deferred-`/wrap`
 *                marker single source of truth). Reads stdin (fd 0) and
 *                [cwd]/.agentic/config.json (deferred_wrap_daemon toggle).
 *                Spawns `node <repo>/hooks/wrap-daemon.js <cwd>` detached when
 *                the toggle is true (the daemon file is built in U3 and may not
 *                exist yet - the detached spawn fails silently until it lands).
 *
 * Downstream consumers: Claude Code SessionEnd hook (wired by .claude/install.sh
 *                       in U4). No code imports this file.
 *
 * Failure modes: Fully fail-open. The entire body is wrapped in try/catch and the
 *                process ALWAYS exits 0 - a hook error must never block or delay
 *                session shutdown. Defensive stdin parse (malformed/empty payload
 *                -> exit 0). Under the AGENTIC_WRAP_DAEMON=1 loop-guard the hook
 *                exits 0 immediately: no finalize, no heartbeat removal, no daemon
 *                launch. finalizeReady runs ONLY on a terminal reason
 *                {clear, logout, prompt_input_exit, bypass_permissions_disabled,
 *                other}; reason `resume` does NOT finalize (the session may
 *                continue) and the marker stays `pending` (recovered by manual
 *                `/wrap`, never auto-wrapped - the deliberate CRITICAL-A trade).
 *                The daemon launch is best-effort detached + unref'd; if the
 *                daemon file is absent or the spawn errors, it is swallowed.
 *
 * Performance: standard. A few synchronous fs reads (marker + config) and one
 *              detached child spawn that the parent never waits on; the hook
 *              returns essentially immediately and adds no measurable shutdown
 *              latency.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const wrapMarker = require('./lib/wrap-marker.js');

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

function run() {
  // --- 1. Read + parse stdin (defensive; fail-open) ---
  let raw = '';
  try {
    raw = fs.readFileSync(0, 'utf8');
  } catch (_) {
    return; // no stdin -> exit 0
  }
  if (!raw.trim()) return;

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (_) {
    return; // malformed payload -> exit 0
  }
  if (!payload || typeof payload !== 'object') return;

  // --- 2. Loop-guard: bail IMMEDIATELY under AGENTIC_WRAP_DAEMON=1 ---
  // This is the load-bearing stop on the daemon's own headless `/wrap-deferred`
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

  // --- 4. Finalize on a terminal reason ONLY ---
  // finalizeReady is the SOLE pending->ready transition (no sweep, no daemon, no
  // SessionStart - CRITICAL-A). It carries no branch/sha and no-ops in the lib on
  // any non-pending marker. `resume` is non-terminal: the marker stays `pending`
  // and is recovered only by a manual `/wrap` (never auto-wrapped). Both
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
try {
  run();
} catch (_) {
  // Swallow everything - a SessionEnd hook must never throw.
}
process.exit(0);
