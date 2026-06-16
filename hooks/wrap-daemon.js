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
 *                Also writes an always-on bounded operator log at
 *                [project_root]/.agentic/wrap-daemon.log (rotation target
 *                .agentic/wrap-daemon.log.1), each rotated at MAX_DAEMON_LOG_BYTES.
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
 *                bypassPermissions; under that mode --allowedTools does NOT
 *                constrain the tool set (it only suppresses approval prompts for the
 *                tools it lists - unlisted tools stay in context and auto-approve),
 *                so the security boundary is --disallowedTools, which REMOVES a tool
 *                from the model's context before the bypass step.
 *                SEC-C1 (CRITICAL, repo-local .git/config RCE): a malicious cloned
 *                repo ships its own repo-local `.git/config`, which git reads on
 *                EVERY invocation with no opt-out flag. Execution hooks in that
 *                config fire on the read-only verbs themselves - `core.fsmonitor`
 *                on `git status`, `diff.external` on a bare `git diff`, plus
 *                `core.pager` / `core.sshCommand` / `alias.*` / `ext::` - reaching
 *                arbitrary code execution on the developer's machine under
 *                bypassPermissions. An argv-safe per-verb git allowlist CANNOT close
 *                this (the danger is git reading the attacker's on-disk config, not
 *                the argv we pass). Mitigation: the headless drain spawn passes
 *                --disallowedTools "Bash" (DEFERRED_WRAP_DISALLOWED_TOOLS), which
 *                removes Bash from the model's context entirely, so it can never
 *                invoke git/shell and the exec vectors never fire - this is enforced
 *                before the bypass-mode auto-approval and is the actual boundary.
 *                --allowedTools (file tools only) is kept but is supplementary under
 *                bypassPermissions (prompt-suppression, not a constraint). Plus
 *                defense-in-depth GIT_CONFIG_GLOBAL=/dev/null,
 *                GIT_CONFIG_SYSTEM=/dev/null, GIT_CONFIG_NOSYSTEM=1 in every spawned
 *                child env (childEnv) so the global/system config tiers are
 *                neutralized regardless. The interactive `/wrap` is OUT OF SCOPE:
 *                it is human-driven under normal (non-bypassed) permissions and
 *                reads git normally. Both config and marker/scan reads are
 *                size-bounded (SEC-M2 / SEC-M3) so a planted multi-GB file or a
 *                directory of tens of thousands of marker files cannot wedge a poll
 *                tick.
 *                LOGGING (bounded, does NOT alter the boundary): the headless child's
 *                stdout/stderr is captured into a per-run 256 KB-capped in-memory
 *                buffer (drain-and-discard past the cap - the stream listener stays
 *                attached so a chatty child cannot wedge on a full OS pipe) and
 *                flushed to wrap-daemon.log on EVERY terminal path (clean/non-zero
 *                exit, signal/timeout kill, child error). Capturing the child's
 *                pipes does NOT change the --disallowedTools "Bash" / childEnv git
 *                hardening boundary - those flags and env are passed verbatim.
 *                SEC (CWE-59/CWE-61, planted-symlink write-through): wrap-daemon.log is
 *                written via an O_NOFOLLOW open (O_WRONLY|O_CREAT|O_APPEND|O_NOFOLLOW,
 *                0o600), so the append REFUSES to follow a symlink - a hostile repo's
 *                tracked symlink at .agentic/wrap-daemon.log (which the .agentic/*
 *                gitignore does NOT cover) cannot redirect attacker-influenced child
 *                output through the link into ~/.bashrc / a git hook / authorized_keys.
 *                A pre-write lstat (does not follow) detects + unlinks a planted link
 *                (self-heal to a fresh regular file), and the O_NOFOLLOW open closes the
 *                residual race (a link raced in after the lstat fails the open with
 *                ELOOP). 0o600 keeps the log owner-only (it may carry session content).
 *                All fail-open: an ELOOP/error silently drops the line, never crashes.
 *
 * Performance: long-running but near-idle. Polls the marker directory on a fixed
 *              interval; each tick is a single readdir + a few stat/read calls.
 *              Heavy work (the `claude` subprocess) is bounded by the configured
 *              per-child timeout (default 10 min). Self-exits when idle (default
 *              15 min) so an unused daemon does not linger. The wrap-daemon.log is
 *              bounded to ~2 MB live + one prior `.log.1` rotation (~4 MB max); on a
 *              persistent rename failure the live log may exceed 2 MB by accumulated
 *              appends until the next successful rotation - the in-memory capture
 *              buffer is hard-capped at 256 KB and never grows unbounded.
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

// SEC-C1 (CRITICAL, repo-local .git/config RCE): the headless `/wrap-deferred`
// child runs under --permission-mode bypassPermissions. Under that mode,
// --allowedTools does NOT constrain the tool set - it only suppresses the approval
// PROMPT for the tools it lists. Any tool NOT listed (including Bash) still remains
// in the model's context and is auto-approved by the bypass mode. So dropping Bash
// from --allowedTools is NOT a security boundary: the model can still call Bash.
//
// The actual boundary is --disallowedTools: a bare tool name passed there REMOVES the
// tool from the model's context, and that removal is enforced BEFORE the bypass-mode
// auto-approval step. We pass `Bash` so the headless run cannot invoke git (or any
// shell command) at all, regardless of bypassPermissions.
//
// Why Bash removal matters here: a malicious cloned repo ships its OWN repo-local
// `.git/config`, which git reads on EVERY invocation with no flag and no way to opt
// out per-command. That config can carry execution hooks that fire on ordinary
// read-only verbs: `core.fsmonitor=<program>` executes on `git status`,
// `diff.external=<program>` executes on a bare `git diff`, and `core.pager` /
// `core.sshCommand` / `alias.*` / `ext::` reach arbitrary execution similarly. None
// of these involve a `-c` flag or shell metacharacters, so an argv-safe, per-verb
// `Bash(git status:*)` allowlist does NOT close them - the danger is git reading the
// attacker's on-disk config, not the argv we pass. Under bypassPermissions in an
// attacker-influenced repo this is arbitrary code execution on the developer's
// machine when the daemon drains that session. The only fix that closes the class is
// to remove the Bash tool from the model's context entirely - which --disallowedTools
// does and --allowedTools does not.
//
// The deferred wrap does not need git: it is best-effort and conversation-driven.
// It writes context.md/memory.md/AGENTS.md via Write/Edit, and derives any git-state
// section of context.md from the resumed CONVERSATION transcript (or omits it). The
// interactive `/wrap` - run by a human under normal permissions, not bypassed - is
// out of scope and still reads git normally.
//
// --allowedTools is still passed: under bypassPermissions it is harmless (it
// auto-approves the file tools without a prompt) and documents the intended surface.
const DEFERRED_WRAP_ALLOWED_TOOLS = ['Read', 'Edit', 'Write', 'Glob', 'Grep'].join(',');
// The tool removed from the headless model's context (THE security boundary, per the
// note above). A bare tool name in --disallowedTools deletes it from context before
// the bypass-mode step, so Bash/git/shell can never run in the deferred drain.
const DEFERRED_WRAP_DISALLOWED_TOOLS = 'Bash';

// SEC-C1 (belt-and-suspenders, defense-in-depth): even though the headless child is
// granted no git tool, harden every spawned child's env so that if git ever runs
// incidentally (e.g. invoked indirectly by some future tool), attacker-controlled
// GLOBAL/SYSTEM git config cannot inject execution. Repo-local `.git/config` is
// already neutralized by granting no Bash/git; this closes the global/system tiers
// regardless. Merge these into the child env alongside AGENTIC_WRAP_DAEMON.
const GIT_HARDENED_ENV = {
  GIT_CONFIG_GLOBAL: '/dev/null',
  GIT_CONFIG_SYSTEM: '/dev/null',
  GIT_CONFIG_NOSYSTEM: '1',
};

/**
 * Build the env for a daemon-spawned `claude` child: the inherited process env,
 * the daemon loop-guard, and the git-config hardening (SEC-C1). Centralized so the
 * auth pre-flight child and the drain child cannot drift apart.
 */
function childEnv() {
  return Object.assign(
    {},
    process.env,
    { AGENTIC_WRAP_DAEMON: '1' },
    GIT_HARDENED_ENV,
  );
}

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

/**
 * Append a pre-formatted line to the daemon-owned .agentic/wrap-daemon.log, with a
 * single-generation size rotation. Fail-open: the WHOLE body is wrapped so it NEVER
 * throws (a logging failure must never crash the daemon or suppress stdout). A no-op
 * until logFilePath is bound (pre-init lines stay stdout-only).
 *
 * SECURITY (CWE-59 / CWE-61, symlink write-through): a hostile cloned repo can ship a
 * TRACKED symlink at .agentic/wrap-daemon.log (the .agentic/* gitignore does NOT cover
 * a tracked path, so it materializes on clone) pointing OUTSIDE .agentic/ - e.g. at
 * ~/.bashrc, a git hook, or ~/.ssh/authorized_keys. A symlink-following append would
 * write attacker-influenced child output THROUGH the link into the victim file (a
 * persistence/exec primitive). Two layers close this: (1) lstatSync (does NOT follow)
 * detects a planted link and unlinkSync removes ONLY the link (not its target) so a
 * fresh regular file is created on open; (2) the write itself uses an O_NOFOLLOW open,
 * so even a link raced in AFTER the lstat fails the open with ELOOP rather than writing
 * through. Both paths fail-open: on ELOOP/any error the line is silently dropped.
 */
function appendToLog(line) {
  if (logFilePath === null) return;
  try {
    // Detect + self-heal a planted symlink, then run the existing size rotation. lstat
    // does NOT follow the link, so an attacker-planted symlink is observed AS a symlink.
    try {
      const st = fs.lstatSync(logFilePath);
      if (st.isSymbolicLink()) {
        // Remove ONLY the link (unlink never follows), so the O_NOFOLLOW open below
        // creates a fresh regular file in its place instead of touching the target.
        fs.unlinkSync(logFilePath);
      } else if (st.size > wrapMarker.MAX_DAEMON_LOG_BYTES) {
        // Single-generation rotation: rename the live log onto .log.1. renameSync
        // REPLACES the destination NAME atomically - it does not open/follow a .log.1
        // symlink - so the rotation target needs no separate O_NOFOLLOW guard. A rename
        // failure is swallowed (fail-open) - the open below still proceeds on the live file.
        try { fs.renameSync(logFilePath, logFilePath + '.1'); } catch (_) { /* ignore */ }
      }
    } catch (_) { /* lstat throws ENOENT when the log is absent yet - just open below */ }
    // O_NOFOLLOW makes the open fail with ELOOP if logFilePath is a symlink (even one
    // raced in after the lstat above), so a write-through the link is impossible. The
    // open is O_WRONLY|O_CREAT|O_APPEND (append semantics, create on first run) with
    // 0o600 perms - the log may carry session content, so least-privilege owner-only.
    const fd = fs.openSync(
      logFilePath,
      fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_APPEND | fs.constants.O_NOFOLLOW,
      0o600,
    );
    // finally guarantees the fd is closed even if writeSync throws (no descriptor leak).
    try { fs.writeSync(fd, line); } finally { fs.closeSync(fd); }
  } catch (_) { /* ignore - logging is best-effort and must never throw (incl. ELOOP) */ }
}

/**
 * Best-effort logger - the daemon's diagnostics go to BOTH stdout (unchanged) and the
 * persistent .agentic/wrap-daemon.log (once bound). Never throws: each sink has its own
 * guard so one failing must not suppress the other.
 */
function log(msg) {
  try {
    process.stdout.write('[wrap-daemon] ' + msg + '\n');
  } catch (_) { /* ignore */ }
  appendToLog('[' + new Date().toISOString() + '] [wrap-daemon] ' + msg + '\n');
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
      env: childEnv(),
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
        // SEC-C1 (THE security boundary): --disallowedTools removes Bash from the
        // model's context BEFORE the bypass-mode step, so the headless run cannot
        // invoke git/shell at all - regardless of bypassPermissions. This is what
        // actually closes the repo-local .git/config RCE class. See the const def.
        '--disallowedTools', DEFERRED_WRAP_DISALLOWED_TOOLS,
        // --allowedTools only suppresses prompts for the listed file tools under
        // bypassPermissions; it does NOT constrain the tool set (see SEC-C1 note).
        '--allowedTools', DEFERRED_WRAP_ALLOWED_TOOLS,
        '--max-turns', String(DEFAULT_MAX_TURNS),
      ], {
        cwd: projectRoot,
        // detached:true puts the child in its own process group so we can signal
        // the WHOLE group (-pid) on timeout - this kills any grandchildren the
        // headless run spawned, not just the immediate child.
        detached: true,
        // Capture the headless child's stdout+stderr (previously discarded) so the
        // /wrap-deferred output lands in .agentic/wrap-daemon.log. The boundary is
        // UNCHANGED: --disallowedTools Bash + childEnv() git hardening still apply.
        stdio: ['ignore', 'pipe', 'pipe'],
        env: childEnv(),
      });
    } catch (err) {
      resolve({ ok: false, error: 'spawn-failed: ' + (err && err.message ? err.message : 'unknown') });
      return;
    }

    // Per-run capture of the child's stdout/stderr, hard-capped at
    // MAX_CHILD_CAPTURE_BYTES. CRITICAL anti-wedge: once the cap is reached we STOP
    // growing `captured` but the listener STAYS attached and keeps consuming (and
    // discarding) further chunks. If we instead removed the listener or paused the
    // stream at the cap, a chatty child would block on a full OS pipe buffer (~64 KB)
    // and wedge the daemon queue - the exact failure the daemon exists to prevent.
    let captured = '';
    let capturedBytes = 0;
    let capTruncated = false;
    const onChunk = (chunk) => {
      if (capturedBytes < wrapMarker.MAX_CHILD_CAPTURE_BYTES) {
        const s = chunk.toString();
        captured += s;
        capturedBytes += Buffer.byteLength(s);
        if (capturedBytes >= wrapMarker.MAX_CHILD_CAPTURE_BYTES) capTruncated = true;
      }
      // else: drain-and-discard (listener stays attached; pipe never fills).
    };
    if (child.stdout) child.stdout.on('data', onChunk);
    if (child.stderr) child.stderr.on('data', onChunk);

    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      flushChildCapture(sessionId, captured, capTruncated, result);
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

/**
 * Flush one headless /wrap-deferred child's captured output to the log as a single
 * delimited block (via log(), so it also appears on stdout). Called on EVERY terminal
 * path - clean exit, non-zero exit, signal/timeout kill, and child error. The
 * spawn-failure early-return has no child object and nothing to flush, so it is the
 * only terminal path that does not call this.
 *
 * @param {string} sessionId - Validated session UUID.
 * @param {string} captured - The (bounded) child stdout+stderr.
 * @param {boolean} capTruncated - Whether the 256 KB cap was hit.
 * @param {{ok:boolean, error:string|null}} result - The drain outcome.
 */
function flushChildCapture(sessionId, captured, capTruncated, result) {
  const status = result && result.ok ? 'ok' : ('FAILED: ' + ((result && result.error) || 'unknown'));
  let block = '----- /wrap-deferred output for ' + sessionId + ' [' + status + '] -----\n';
  block += captured;
  if (captured && !captured.endsWith('\n')) block += '\n';
  if (capTruncated) block += '[output truncated at 256 KB]\n';
  block += '----- end output for ' + sessionId + ' -----';
  log(block);
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
    const startedAt = Date.now();
    const result = await runDeferredWrap(sessionId, cwd, timeoutMs);

    if (result.ok) {
      // (e) Clean exit -> done (unlinks marker + heartbeat in the lib).
      wrapMarker.transitionDone(cwd, sessionId);
      log('session ' + sessionId + ' done (code:0 dur:' + (Date.now() - startedAt) + 'ms)');
    } else {
      // (f) Failure/timeout. The claim already incremented attempts. At the cap,
      // give up; otherwise reset to `ready` so a FUTURE daemon run retries it.
      const attempts = Number.isInteger(claimed.attempts) ? claimed.attempts : 0;
      const lastError = result.error || 'unknown';
      if (attempts >= MAX_ATTEMPTS) {
        // Pass the SAME lastError to both the marker transition and the log line so
        // the log and the marker's last_error agree by construction (do NOT re-derive).
        wrapMarker.transitionGaveUp(cwd, sessionId, lastError);
        log('session ' + sessionId + ' gave_up after ' + attempts + ' attempts (last_error:'
          + lastError + '; dur:' + (Date.now() - startedAt) + 'ms)');
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
          + attempts + '/' + MAX_ATTEMPTS + '; retried on next daemon launch; dur:'
          + (Date.now() - startedAt) + 'ms)');
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
// Bound to the resolved log path once main() has validated project_root (so the path
// derives from a clean absolute existing dir). Null before that -> appendToLog no-ops,
// keeping pre-init lifecycle lines stdout-only.
let logFilePath = null;

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

  // Bind the persistent log path ONLY after project_root passed its validity and
  // existing-directory guards, so the path derives from a clean absolute existing dir.
  // From here on, log()/appendToLog also persist to .agentic/wrap-daemon.log.
  logFilePath = wrapMarker.wrapDaemonLogPath(projectRoot);

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
