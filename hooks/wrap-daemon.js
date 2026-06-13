#!/usr/bin/env node

/**
 * Purpose: Per-project background daemon that finalizes forgotten session wraps.
 *          It drains the deferred-`/wrap` `ready` marker queue (FIFO by staged_at)
 *          by headlessly resuming each cleanly-ended Claude session and running the
 *          NON-interactive `/wrap-deferred` command IN THE MAIN PROJECT DIR (no
 *          worktree, no copy-back, no merge). It is the SOLE consumer of `ready`
 *          markers and the highest-blast-radius unit of the feature: it spawns
 *          `claude` subprocesses, owns a PID-file singleton, reclaims markers a
 *          dead daemon abandoned in `in_progress` (MAJOR-C), deletes stale
 *          `pending` markers (MINOR-1, delete-only), and bounds every child with a
 *          timeout-and-kill of the whole process group. It NEVER promotes a
 *          `pending` marker to `ready` (that is SessionEnd's sole job - CRITICAL-A),
 *          so it can never resume a live/idle session.
 *
 * Public API: none (CLI script). Invoked as `node hooks/wrap-daemon.js <project_root>`
 *             by the SessionEnd / SessionStart hooks (detached) or manually. Not
 *             imported by any module.
 *
 * Upstream deps: Node built-ins only (fs, path, child_process) plus the local
 *                CommonJS module hooks/lib/wrap-marker.js (the deferred-`/wrap`
 *                marker single source of truth - all marker reads/transitions, the
 *                pid-path helper, the reclaim/janitor, the heartbeat read, the
 *                auth-failed path). Reads [project_root]/.agentic/config.json for
 *                tuning params (all optional, defaulted). Spawns the `claude` CLI
 *                (`claude auth status` for the pre-flight; `claude --resume <id> -p
 *                "/wrap-deferred" ...` for each drain) with AGENTIC_WRAP_DAEMON=1 in
 *                the child env so the child's own hooks no-op (loop-guard).
 *                Writes/owns [project_root]/.agentic/wrap-daemon.pid (O_EXCL
 *                singleton) and may write [project_root]/.agentic/wrap-daemon-auth-failed.
 *
 * Downstream consumers: none (terminal process). Its side effects - the canonical
 *                       context.md / memory.md / AGENTS.md writes - are performed by
 *                       the `/wrap-deferred` command it spawns, not by the daemon
 *                       itself; the daemon only drives the marker state machine.
 *
 * Failure modes: Defensive and fail-open at the marker layer - a daemon bug must
 *                never corrupt markers (every marker transition goes through the
 *                lib's atomic, fail-open functions). The daemon ALWAYS releases its
 *                PID singleton on every exit path including SIGTERM/SIGINT. It
 *                exits 0 immediately under the AGENTIC_WRAP_DAEMON loop-guard (a
 *                daemon must never spawn from inside a daemon-driven headless run),
 *                on an invalid/traversing project_root, when a live daemon already
 *                owns the pid file, and when `claude auth status` returns non-zero
 *                (writing the one-time auth-failed notice and touching NO marker's
 *                attempts). Each child is bounded by a timeout-and-kill of its whole
 *                process group; a hung headless run cannot wedge the queue. A claim
 *                already increments attempts in the lib, so on a child failure the
 *                daemon resets the marker back to `ready` for retry until attempts
 *                reaches the cap (3), at which point it is moved to `gave_up`. The
 *                daemon self-exits after an idle window with no `ready` markers.
 *                SECURITY: the session id is validated as a plausible UUID before it
 *                is ever passed as a `--resume` argument (no shell-arg injection);
 *                args are passed as an argv array (no shell), so there is no shell
 *                metacharacter surface. The headless child runs under
 *                bypassPermissions, so its --allowedTools list IS the security
 *                boundary: it is an EXPLICIT per-verb read-only git allowlist
 *                (SEC-M1, DEFERRED_WRAP_ALLOWED_TOOLS) - never `Bash(git *)` - so
 *                `git -c <config>=...` / `ext::` config-injection forms cannot
 *                match. Both config and marker/scan reads are size-bounded
 *                (SEC-M2 / SEC-M3) so a planted multi-GB file or a directory of
 *                tens of thousands of marker files cannot wedge a poll tick.
 *
 * Performance: long-running but near-idle. Polls the marker directory on a fixed
 *              interval; each tick is a single readdir + a few stat/read calls.
 *              Heavy work (the `claude` subprocess) is bounded by the configured
 *              per-child timeout (default 10 min). Self-exits when idle (default
 *              15 min) so an unused daemon does not linger.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const wrapMarker = require('./lib/wrap-marker.js');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_ATTEMPTS = 3;
// How stale the EXISTING pid-file timestamp must be before a new daemon will even
// consider reclaiming it (the owner must ALSO be a dead PID). 30 min mirrors the
// in_progress reclaim window and is intentionally generous - a live daemon
// refreshes nothing, so this only bites a genuinely abandoned pid file.
const PID_STALE_MS = 30 * 60 * 1000;
// Poll interval for the drain loop (ms). Small enough to feel responsive, large
// enough that a near-idle daemon costs almost nothing.
const POLL_INTERVAL_MS = 5 * 1000;
// A plausible Claude session id is a v4-ish UUID. We validate against this before
// passing it to `claude --resume` so a corrupt/hostile marker filename can never
// inject an argument. (The lib also sanitizes path separators; this is the
// argv-safety layer.)
const UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
// Bound the headless wrap so a single hung run cannot starve the queue forever.
const DEFAULT_MAX_TURNS = 40;

// SEC-M1: the headless `/wrap-deferred` child runs under --permission-mode
// bypassPermissions, so its --allowedTools list IS the security boundary. The old
// `Bash(git *)` glob was too broad: it admitted `git -c core.pager='!sh' log`,
// `git -c alias.x='!sh' x`, and `ext::`/remote-helper forms that reach arbitrary
// execution with prompts bypassed. We replace it with an EXPLICIT per-verb allowlist
// of ONLY the read-only git surveys `/wrap-deferred` needs to build context.md's
// git-state section (it writes context.md/memory.md/AGENTS.md via Write/Edit, NOT
// via git - so NO mutating git verb is listed):
//   git status      - uncommitted/working-tree survey (`git status --porcelain`)
//   git stash list  - stashed-work survey
//   git log         - recent commits produced this session
//   git diff        - inspect uncommitted/staged change detail when summarizing
//   git rev-parse   - resolve HEAD / branch / repo-root for the git-state section
//   git branch      - current-branch name for the git-state section
// The `Bash(git <verb>:*)` scoped form fixes the verb and wildcards only its args;
// because `-c <config>=...` precedes the subcommand, `git -c ... status` does NOT
// match `Bash(git status:*)` - the dangerous `-c`/`ext::` config-injection surface
// is closed. Keep this list MINIMAL: add a verb only when /wrap-deferred provably
// needs it, and never add a write/mutating verb.
const DEFERRED_WRAP_GIT_VERBS = [
  'git status',
  'git stash list',
  'git log',
  'git diff',
  'git rev-parse',
  'git branch',
];
const DEFERRED_WRAP_ALLOWED_TOOLS = [
  'Read', 'Edit', 'Write', 'Glob', 'Grep',
  ...DEFERRED_WRAP_GIT_VERBS.map((verb) => 'Bash(' + verb + ':*)'),
].join(',');

// ---------------------------------------------------------------------------
// Config (defensive; absent file/keys -> defaults)
// ---------------------------------------------------------------------------

const CONFIG_DEFAULTS = {
  deferred_wrap_idle_minutes: 15,
  deferred_wrap_heartbeat_seconds: 120,
  deferred_wrap_timeout_minutes: 10,
  deferred_wrap_inprogress_reclaim_minutes: 30,
  deferred_wrap_pending_ttl_days: 7,
};

// SEC-M2 (DoS, unbounded JSON read): config.json is a tiny tuning file. A hostile
// repo could plant a multi-GB file that we re-read every startup; cap the size and
// fall back to defaults (fail-open) on anything larger. 64 KB is generous for a
// handful of numeric keys.
const MAX_CONFIG_BYTES = 64 * 1024;

/**
 * Read tuning params from [cwd]/.agentic/config.json. Every key is optional and
 * falls back to its default; a missing file, parse error, or non-numeric value all
 * resolve to the default. Returns a fully-populated config object.
 */
function readConfig(cwd) {
  const out = Object.assign({}, CONFIG_DEFAULTS);
  let parsed = null;
  try {
    const cfgPath = path.join(cwd, '.agentic', 'config.json');
    // SEC-M2: stat-then-read - skip an over-cap (or non-regular) file before we
    // load its bytes, so a planted multi-GB config cannot wedge startup.
    const st = fs.statSync(cfgPath);
    if (!st.isFile() || st.size > MAX_CONFIG_BYTES) {
      return out; // too large / not a regular file -> defaults (fail-open)
    }
    const raw = fs.readFileSync(cfgPath, 'utf8');
    parsed = JSON.parse(raw);
  } catch (_) {
    parsed = null;
  }
  if (parsed && typeof parsed === 'object') {
    for (const key of Object.keys(CONFIG_DEFAULTS)) {
      const v = parsed[key];
      if (typeof v === 'number' && Number.isFinite(v) && v > 0) {
        out[key] = v;
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// PID-file singleton
// ---------------------------------------------------------------------------

/** Best-effort logger - the daemon's diagnostics go to stdout; never throws. */
function log(msg) {
  try {
    process.stdout.write('[wrap-daemon] ' + msg + '\n');
  } catch (_) { /* ignore */ }
}

/**
 * Read a pid file into { pid, ts } (the file body is `PID\n<ISO8601>`). Returns
 * null on any error or malformed content.
 */
function readPidFile(pidPath) {
  try {
    const raw = fs.readFileSync(pidPath, 'utf8');
    const lines = raw.split('\n');
    const pid = Number((lines[0] || '').trim());
    const ts = (lines[1] || '').trim();
    if (!Number.isInteger(pid) || pid <= 0) return null;
    return { pid, ts };
  } catch (_) {
    return null;
  }
}

/** True when the given PID is dead (ESRCH). EPERM/alive/indeterminate -> false. */
function pidIsDead(pid) {
  const n = Number(pid);
  if (!Number.isInteger(n) || n <= 0) return false;
  try {
    process.kill(n, 0);
    return false; // alive
  } catch (err) {
    if (err && err.code === 'ESRCH') return true;
    return false; // EPERM (alive, not ours) or anything else -> treat as alive
  }
}

/** Parse an ISO8601 timestamp to ms; null on bad input. */
function tsMs(iso) {
  if (typeof iso !== 'string' || !iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
}

/**
 * Acquire the singleton pid file via O_EXCL ('wx'). On EEXIST, inspect the
 * incumbent: if its timestamp is older than PID_STALE_MS AND its PID is dead,
 * unlink it (the EXACT pid-file path only) and retry ONCE. Otherwise another
 * daemon owns it -> return false (caller exits 0). Returns true on acquisition.
 *
 * SECURITY: the unlink targets only the resolved pid-file path returned by the lib
 * (no traversal, no glob).
 */
function acquireSingleton(pidPath) {
  const body = String(process.pid) + '\n' + new Date().toISOString() + '\n';
  const tryCreate = () => {
    try {
      fs.mkdirSync(path.dirname(pidPath), { recursive: true });
      fs.writeFileSync(pidPath, body, { flag: 'wx' }); // O_EXCL
      return true;
    } catch (err) {
      if (err && err.code === 'EEXIST') return false;
      // Any other fs error -> cannot acquire safely.
      return false;
    }
  };

  if (tryCreate()) return true;

  // Collision: reclaim only a genuinely stale + dead incumbent.
  const incumbent = readPidFile(pidPath);
  if (!incumbent) {
    // Unreadable/malformed pid file. Treat as stale only if old by mtime, to avoid
    // stealing from a daemon that just created it. Conservative: if we cannot read
    // it AND it is old, reclaim; else yield.
    let oldByMtime = false;
    try {
      const st = fs.statSync(pidPath);
      oldByMtime = (Date.now() - st.mtimeMs) > PID_STALE_MS;
    } catch (_) {
      oldByMtime = false;
    }
    if (!oldByMtime) return false;
    try { fs.unlinkSync(pidPath); } catch (_) {}
    return tryCreate();
  }

  const incumbentTs = tsMs(incumbent.ts);
  const stale = incumbentTs !== null && (Date.now() - incumbentTs) > PID_STALE_MS;
  if (stale && pidIsDead(incumbent.pid)) {
    try { fs.unlinkSync(pidPath); } catch (_) {}
    return tryCreate();
  }
  // A live (or not-yet-stale) daemon owns the singleton.
  return false;
}

// ---------------------------------------------------------------------------
// Auth pre-flight
// ---------------------------------------------------------------------------

/**
 * Run `claude auth status` synchronously. Returns true when exit code is 0
 * (authed), false otherwise (non-zero exit OR spawn failure). Bounded by a short
 * timeout so a hung auth check cannot wedge startup.
 */
function authOk() {
  try {
    const res = spawnSync('claude', ['auth', 'status'], {
      stdio: 'ignore',
      timeout: 30 * 1000,
      env: Object.assign({}, process.env, { AGENTIC_WRAP_DAEMON: '1' }),
    });
    // spawnSync sets .error on ENOENT/timeout; non-zero status -> not authed.
    if (res.error) return false;
    return res.status === 0;
  } catch (_) {
    return false;
  }
}

/**
 * Write the one-time auth-failed notice (create-if-absent, idempotent). Touches NO
 * marker's attempts. Fail-open.
 */
function writeAuthFailed(cwd) {
  try {
    const p = wrapMarker.authFailedPath(cwd);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const body = 'claude auth status returned non-zero at ' + new Date().toISOString()
      + '\nDeferred-wrap daemon could not authenticate; run `claude auth login`.\n';
    // create-if-absent so we do not spam; refresh is unnecessary (surfaced next
    // SessionStart). 'wx' swallows EEXIST below.
    fs.writeFileSync(p, body, { flag: 'wx' });
  } catch (_) {
    // EEXIST (already present) or any fs error - swallow; fail-open.
  }
}

// ---------------------------------------------------------------------------
// Child drain (spawn /wrap-deferred with timeout-and-kill of the process group)
// ---------------------------------------------------------------------------

/**
 * Headlessly run `/wrap-deferred` for one session via `claude --resume`, bounded by
 * a timeout-and-kill of the whole child process group. Returns a promise resolving
 * to { ok: boolean, error: string|null } - ok=true ONLY on a clean exit-0.
 *
 * SECURITY: sessionId is pre-validated as a UUID by the caller; args are an argv
 * array (no shell), so there is no metacharacter/injection surface.
 *
 * @param {string} sessionId - Validated session UUID.
 * @param {string} projectRoot - The MAIN project dir (child cwd).
 * @param {number} timeoutMs - Hard wall-clock bound for the child.
 */
function runDeferredWrap(sessionId, projectRoot, timeoutMs) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn('claude', [
        '--resume', sessionId,
        '-p', '/wrap-deferred',
        '--permission-mode', 'bypassPermissions',
        '--allowedTools', DEFERRED_WRAP_ALLOWED_TOOLS,
        '--max-turns', String(DEFAULT_MAX_TURNS),
      ], {
        cwd: projectRoot,
        // detached:true puts the child in its own process group so we can signal
        // the WHOLE group (-pid) on timeout - this kills any grandchildren the
        // headless run spawned, not just the immediate child.
        detached: true,
        stdio: 'ignore',
        env: Object.assign({}, process.env, { AGENTIC_WRAP_DAEMON: '1' }),
      });
    } catch (err) {
      resolve({ ok: false, error: 'spawn-failed: ' + (err && err.message ? err.message : 'unknown') });
      return;
    }

    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };

    // Timeout-and-kill: SIGKILL the entire process group. Negative pid targets the
    // group. Fall back to killing just the child if the group kill throws.
    const timer = setTimeout(() => {
      killGroup(child);
      finish({ ok: false, error: 'timeout' });
    }, timeoutMs);

    child.on('error', (err) => {
      finish({ ok: false, error: 'child-error: ' + (err && err.message ? err.message : 'unknown') });
    });

    child.on('exit', (code, signal) => {
      if (code === 0) {
        finish({ ok: true, error: null });
      } else {
        const why = signal ? ('signal:' + signal) : ('exit:' + code);
        finish({ ok: false, error: why });
      }
    });
  });
}

/** Kill a detached child's whole process group (SIGKILL), best-effort. */
function killGroup(child) {
  if (!child || typeof child.pid !== 'number') return;
  try {
    // Negative pid -> signal the process group (requires detached:true).
    process.kill(-child.pid, 'SIGKILL');
  } catch (_) {
    // Group kill failed (e.g. child already gone or no group) - try the child PID.
    try { child.kill('SIGKILL'); } catch (_) {}
  }
}

// ---------------------------------------------------------------------------
// Drain loop
// ---------------------------------------------------------------------------

/**
 * Process exactly ONE ready marker per call (the FIFO head that is claimable, not
 * heartbeat-fresh, and not already attempted in THIS daemon run). Returns:
 *   'processed' - a marker was claimed and a child ran (regardless of outcome)
 *   'deferred'  - the head marker is heartbeat-fresh (session still live); skip
 *   'idle'      - no ready markers eligible this run (none, or all already
 *                 attempted / lost the race)
 *
 * Retry model (matches the architect contract's "recovered on next startup"):
 * a session is drained at most ONCE per daemon run. On a child failure the marker
 * is reset to `ready` (attempts already bumped by the lib's claim) but the session
 * is recorded in `attemptedThisRun` so it is NOT hot-retried within this same
 * process - the next daemon launch (a SessionEnd / SessionStart fires one) picks it
 * up with natural spacing. This prevents the failure mode where a transient error
 * burns the whole 3-attempt budget in a few seconds of tight looping. The cap
 * (`gave_up` at attempts >= 3) is therefore reached across runs, not within one.
 *
 * @param {string} cwd - The validated project root.
 * @param {object} cfg - Resolved config (minutes/seconds-based tuning).
 * @param {Set<string>} attemptedThisRun - Session ids already drained this run.
 */
async function drainOnce(cwd, cfg, attemptedThisRun) {
  const ready = wrapMarker.listReadyMarkers(cwd); // already FIFO by staged_at asc
  if (!ready.length) return 'idle';

  const heartbeatMs = cfg.deferred_wrap_heartbeat_seconds * 1000;
  const reclaimMs = cfg.deferred_wrap_inprogress_reclaim_minutes * 60 * 1000;
  const timeoutMs = cfg.deferred_wrap_timeout_minutes * 60 * 1000;
  const ownerToken = String(process.pid);

  let sawDeferral = false;
  for (const entry of ready) {
    const sessionId = entry.sessionId;

    // SECURITY: never pass a non-UUID session id to `claude --resume`.
    if (!UUID_RE.test(sessionId)) {
      log('skipping marker with non-UUID session id: ' + JSON.stringify(sessionId));
      continue;
    }

    // Skip sessions already attempted this run (a failed-and-reset marker is left
    // `ready` for a FUTURE daemon launch, not hot-retried here).
    if (attemptedThisRun.has(sessionId)) {
      continue;
    }

    // (a) Defer if the session still emits turns (heartbeat fresh).
    if (wrapMarker.heartbeatFresh(cwd, sessionId, heartbeatMs)) {
      sawDeferral = true;
      continue;
    }

    // (b) Claim (ready -> in_progress; attempts++ happens in the lib).
    const claimed = wrapMarker.claimMarker(cwd, sessionId, ownerToken, 'daemon', reclaimMs);
    if (!claimed) {
      // Lost the race / no longer ready - move on.
      continue;
    }

    // From here on this session has been attempted this run, regardless of outcome.
    attemptedThisRun.add(sessionId);

    // (c)+(d) Run /wrap-deferred in the MAIN project dir, bounded by timeout-kill.
    log('draining session ' + sessionId + ' (attempt ' + claimed.attempts + ')');
    const result = await runDeferredWrap(sessionId, cwd, timeoutMs);

    if (result.ok) {
      // (e) Clean exit -> done (unlinks marker + heartbeat in the lib).
      wrapMarker.transitionDone(cwd, sessionId);
      log('session ' + sessionId + ' wrapped -> done');
    } else {
      // (f) Failure/timeout. The claim already incremented attempts. At the cap,
      // give up; otherwise reset to `ready` so a FUTURE daemon run retries it.
      const attempts = Number.isInteger(claimed.attempts) ? claimed.attempts : 0;
      const lastError = result.error || 'unknown';
      if (attempts >= MAX_ATTEMPTS) {
        wrapMarker.transitionGaveUp(cwd, sessionId, lastError);
        log('session ' + sessionId + ' gave_up after ' + attempts + ' attempts (' + lastError + ')');
      } else {
        // Reset in_progress -> ready, preserving the bumped attempts and recording
        // last_error. Use the claimed marker object verbatim and only flip the
        // fields we own. writeMarker is atomic + fail-open in the lib.
        const retry = Object.assign({}, claimed, {
          status: 'ready',
          claimed_by: null,
          claimed_kind: null,
          claimed_at: null,
          last_error: lastError,
        });
        wrapMarker.writeMarker(cwd, retry);
        log('session ' + sessionId + ' failed (' + lastError + '); reset to ready (attempt '
          + attempts + '/' + MAX_ATTEMPTS + '; retried on next daemon launch)');
      }
    }
    return 'processed';
  }

  // We walked the whole ready list without claiming anything: either every head
  // was heartbeat-fresh (deferred), already attempted this run, or lost the race.
  return sawDeferral ? 'deferred' : 'idle';
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

let pidPathForCleanup = null;
let cleanedUp = false;

/** Release the pid singleton (unlink the EXACT path). Idempotent. */
function releaseSingleton() {
  if (cleanedUp) return;
  cleanedUp = true;
  if (pidPathForCleanup) {
    try { fs.unlinkSync(pidPathForCleanup); } catch (_) {}
  }
}

/** Install signal + exit handlers so the pid file is ALWAYS released. */
function installCleanup() {
  process.on('exit', releaseSingleton);
  for (const sig of ['SIGTERM', 'SIGINT', 'SIGHUP']) {
    process.on(sig, () => {
      releaseSingleton();
      // CORR-Minor-2: exit 0 DELIBERATELY. This is a fire-and-forget background
      // daemon, not an interactive process whose caller inspects a 128+signal code;
      // the only contract that matters on a signal is that the pid singleton is
      // released (done above) and the process leaves. A uniform exit 0 keeps every
      // exit path of this daemon consistent (see the module manifest). Comment and
      // code agree: this is NOT a 128+signal re-raise.
      process.exit(0);
    });
  }
}

async function main() {
  // --- 1. Resolve + guard project_root ---
  const rawRoot = process.argv[2];
  if (typeof rawRoot !== 'string' || !rawRoot.trim()) {
    log('missing project_root argument; exiting');
    process.exit(0);
  }
  const projectRoot = rawRoot.trim();
  // Traversal/validity guard: mirror stop-context.js - a clean absolute path must
  // resolve to itself. Anything else (relative, traversing) is rejected.
  if (path.resolve(projectRoot) !== projectRoot) {
    log('project_root is not a clean absolute path; exiting');
    process.exit(0);
  }
  // Must be an existing directory.
  try {
    if (!fs.statSync(projectRoot).isDirectory()) {
      log('project_root is not a directory; exiting');
      process.exit(0);
    }
  } catch (_) {
    log('project_root does not exist; exiting');
    process.exit(0);
  }

  // --- 2. Loop-guard: a daemon must NEVER spawn from inside a daemon run ---
  if (wrapMarker.daemonGuardActive()) {
    process.exit(0);
  }

  const cfg = readConfig(projectRoot);

  // --- 3. Singleton via O_EXCL pid file ---
  const pidPath = wrapMarker.daemonPidPath(projectRoot);
  if (!pidPath) {
    log('could not resolve pid path; exiting');
    process.exit(0);
  }
  if (!acquireSingleton(pidPath)) {
    // Another live daemon owns the singleton (or we could not safely acquire).
    process.exit(0);
  }
  pidPathForCleanup = pidPath;
  installCleanup();

  // --- 4. Reclaim markers a dead daemon abandoned in in_progress (MAJOR-C) ---
  const reclaimMs = cfg.deferred_wrap_inprogress_reclaim_minutes * 60 * 1000;
  const reclaim = wrapMarker.reclaimAbandonedInProgress(projectRoot, reclaimMs);
  if (reclaim && (reclaim.reclaimed.length || reclaim.gaveUp.length)) {
    log('reclaim: reset-to-ready=' + JSON.stringify(reclaim.reclaimed)
      + ' gave-up=' + JSON.stringify(reclaim.gaveUp));
  }

  // --- 5. Janitor: delete stale pending markers (MINOR-1, delete-only) ---
  const ttlMs = cfg.deferred_wrap_pending_ttl_days * 24 * 60 * 60 * 1000;
  const janitor = wrapMarker.cleanStalePending(projectRoot, ttlMs);
  if (janitor && janitor.deleted.length) {
    log('janitor: deleted stale pending=' + JSON.stringify(janitor.deleted));
  }

  // --- 6. Auth pre-flight ---
  if (!authOk()) {
    writeAuthFailed(projectRoot);
    log('claude auth status non-zero; wrote auth-failed notice and exiting (no marker touched)');
    // releaseSingleton fires via the exit handler.
    process.exit(0);
  }

  // --- 7. Drain loop (FIFO), with idle self-exit ---
  const idleMs = cfg.deferred_wrap_idle_minutes * 60 * 1000;
  let lastActivity = Date.now();
  // Sessions drained (success or failure) during THIS run. A failed-and-reset
  // marker stays `ready` for a future daemon launch but is not hot-retried here.
  const attemptedThisRun = new Set();

  // Loop until idle-timeout with nothing to do. A 'deferred' tick (heartbeat-fresh
  // head) counts as activity so we keep waiting on a still-live session rather than
  // self-exiting out from under it.
  for (;;) {
    let outcome;
    try {
      outcome = await drainOnce(projectRoot, cfg, attemptedThisRun);
    } catch (err) {
      // Defensive: a drain error must not crash the daemon mid-queue.
      log('drain error (continuing): ' + (err && err.message ? err.message : 'unknown'));
      outcome = 'idle';
    }

    if (outcome === 'processed' || outcome === 'deferred') {
      lastActivity = Date.now();
    } else if (Date.now() - lastActivity >= idleMs) {
      log('idle for ' + cfg.deferred_wrap_idle_minutes + ' min; self-exiting');
      break;
    }

    await sleep(POLL_INTERVAL_MS);
  }

  // releaseSingleton fires via the 'exit' handler; call explicitly for clarity.
  releaseSingleton();
  process.exit(0);
}

/** Promise-based sleep. */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Top-level fail-safe: any unexpected throw must still release the singleton.
main().catch((err) => {
  try { log('fatal: ' + (err && err.message ? err.message : 'unknown')); } catch (_) {}
  releaseSingleton();
  process.exit(0);
});
