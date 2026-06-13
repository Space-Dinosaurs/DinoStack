#!/usr/bin/env node
/**
 * Smoke tests: hooks/wrap-daemon.js - the per-project deferred-`/wrap` daemon (U3).
 *
 * Covers architect-plan verification-gate cases:
 *   (7)  singleton: a second launch no-ops on a LIVE pid file; reclaims a stale +
 *        dead pid file.
 *   (8)  idle self-exit (no ready markers, short idle window -> daemon exits).
 *   (9)  FIFO over ready markers by staged_at (oldest drained first).
 *   (10) acquireWrapLock auto-clears a STALE lock + defers on a FRESH one (lib).
 *   (11/toggle) the daemon acts only when launched; it is launched only when the
 *        toggle is true (asserted at the lib/hook level; here we assert that a
 *        directly-run daemon with NO ready markers does nothing destructive).
 *   (CRITICAL-A) the daemon NEVER claims a `pending` marker (only listReadyMarkers).
 *   (14) heartbeat-fresh -> defer (a fresh heartbeat keeps the marker ready,
 *        unclaimed).
 *   (15) auth pre-flight non-zero -> wrap-daemon-auth-failed written + NO attempt
 *        (marker untouched).
 *   (16) timeout-and-kill -> the hung child is killed and the marker is reset
 *        (attempts incremented), not left in_progress.
 *
 * Hermetic: a MOCK `claude` (a stub node script placed FIRST on PATH) replaces the
 * real CLI - the daemon never invokes the real Claude. The mock's behavior is
 * driven by env vars (MOCK_CLAUDE_AUTH / MOCK_CLAUDE_WRAP / MOCK_CLAUDE_HANG_MS)
 * that the daemon forwards into the child env. Project dirs live under the OS
 * tmpdir, realpath'd so the daemon's own `path.resolve(root) === root` guard
 * accepts them. No network.
 *
 * Run with: node hooks/tests/test-wrap-daemon.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync, spawn } = require('child_process');

const daemonScript = path.resolve(__dirname, '..', 'wrap-daemon.js');
const lib = require('../lib/wrap-marker.js');
if (!fs.existsSync(daemonScript)) {
  console.error(`FAIL: daemon not found at ${daemonScript}`);
  process.exit(1);
}

let passed = 0;
let failed = 0;

function assert(condition, message) {
  if (condition) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message}`);
    failed++;
  }
}

// ---------------------------------------------------------------------------
// Mock `claude` on PATH
// ---------------------------------------------------------------------------
// One mock dir is shared by all tests. The mock branches on argv:
//   - `auth status`  -> exit 0 unless MOCK_CLAUDE_AUTH=fail (then exit 1).
//   - `--resume ...`  (the /wrap-deferred drain) -> behavior from MOCK_CLAUDE_WRAP:
//        "ok"   (default) -> exit 0
//        "fail"           -> exit 7
//        "hang"           -> sleep MOCK_CLAUDE_HANG_MS (default 60000) then exit 0
//   The mock also appends one line per invocation to MOCK_CLAUDE_LOG (if set) so a
//   test can count how many times the drain was attempted.
let MOCK_DIR = null;
function installMockClaude() {
  MOCK_DIR = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ae-mock-bin-')));
  const mockPath = path.join(MOCK_DIR, 'claude');
  const body = [
    '#!/usr/bin/env node',
    "'use strict';",
    'const fs = require("fs");',
    'const args = process.argv.slice(2);',
    'const log = process.env.MOCK_CLAUDE_LOG;',
    'if (log) { try { fs.appendFileSync(log, args.join(" ") + "\\n"); } catch (_) {} }',
    '// SEC-C1: record the git-config hardening env vars the daemon set on this child',
    '// so a test can assert global/system git config is neutralized. One JSON line',
    '// per invocation, keyed by the first arg so auth vs drain are distinguishable.',
    'const envLog = process.env.MOCK_CLAUDE_ENV_LOG;',
    'if (envLog) {',
    '  try {',
    '    fs.appendFileSync(envLog, JSON.stringify({',
    '      kind: args[0],',
    '      GIT_CONFIG_GLOBAL: process.env.GIT_CONFIG_GLOBAL,',
    '      GIT_CONFIG_SYSTEM: process.env.GIT_CONFIG_SYSTEM,',
    '      GIT_CONFIG_NOSYSTEM: process.env.GIT_CONFIG_NOSYSTEM,',
    '    }) + "\\n");',
    '  } catch (_) {}',
    '}',
    'if (args[0] === "auth" && args[1] === "status") {',
    '  process.exit(process.env.MOCK_CLAUDE_AUTH === "fail" ? 1 : 0);',
    '}',
    '// Otherwise treat as a --resume drain.',
    'const mode = process.env.MOCK_CLAUDE_WRAP || "ok";',
    'if (mode === "fail") { process.exit(7); }',
    'if (mode === "hang") {',
    '  const ms = parseInt(process.env.MOCK_CLAUDE_HANG_MS || "60000", 10);',
    '  setTimeout(() => process.exit(0), ms);',
    '  return;',
    '}',
    'process.exit(0);',
    '',
  ].join('\n');
  fs.writeFileSync(mockPath, body, 'utf8');
  fs.chmodSync(mockPath, 0o755);
}
function mockPathEnv() {
  return MOCK_DIR + path.delimiter + process.env.PATH;
}
installMockClaude();

// ---------------------------------------------------------------------------
// Project + marker helpers
// ---------------------------------------------------------------------------
function makeProject(prefix) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  const projectDir = path.join(base, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  const heartbeatDir = path.join(agenticDir, '.heartbeats');
  fs.mkdirSync(heartbeatDir, { recursive: true });
  return { base, projectDir, agenticDir, heartbeatDir };
}
function cleanup(base) { try { fs.rmSync(base, { recursive: true, force: true }); } catch (_) {} }

function markerPath(agenticDir, sessionId) {
  return path.join(agenticDir, 'wrap-pending-' + sessionId + '.json');
}
function writeMarkerRaw(agenticDir, sessionId, overrides) {
  const marker = Object.assign({
    schema_version: 3, session_id: sessionId, staged_at: new Date().toISOString(),
    status: 'pending', claimed_by: null, claimed_kind: null, claimed_at: null,
    attempts: 0, project_root: path.dirname(agenticDir), last_error: null,
  }, overrides || {});
  fs.writeFileSync(markerPath(agenticDir, sessionId), JSON.stringify(marker, null, 2), 'utf8');
  return marker;
}
function readMarker(agenticDir, sessionId) {
  const p = markerPath(agenticDir, sessionId);
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return null; }
}
function writeConfig(agenticDir, obj) {
  fs.writeFileSync(path.join(agenticDir, 'config.json'), JSON.stringify(obj, null, 2), 'utf8');
}
function agoIso(seconds) { return new Date(Date.now() - seconds * 1000).toISOString(); }

// Plausible-UUID session ids (the daemon rejects non-UUID ids before --resume).
const SID = {
  a: 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa',
  b: 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb',
  c: 'cccccccc-cccc-4ccc-cccc-cccccccccccc',
};

/**
 * Run the daemon to completion (it self-exits on idle) and capture stdout. A
 * hard watchdog kills it if it overruns. Returns { code, stdout }.
 *
 * @param {string} projectDir
 * @param {object} env - extra env (mock control vars).
 * @param {number} watchdogMs - hard kill bound for the spawned daemon.
 */
function runDaemonToExit(projectDir, env, watchdogMs) {
  const res = spawnSync(process.execPath, [daemonScript, projectDir], {
    cwd: projectDir,
    encoding: 'utf8',
    timeout: watchdogMs || 30000,
    killSignal: 'SIGKILL',
    env: Object.assign({}, process.env, { PATH: mockPathEnv() }, env || {},
      // The guard must never leak in from a parent run.
      { AGENTIC_WRAP_DAEMON: undefined }),
  });
  return { code: res.status, stdout: res.stdout || '', signal: res.signal };
}

// Fast idle config so the daemon self-exits quickly once the queue is empty.
// idle_minutes is multiplied by 60*1000; 0.02 min = 1200 ms. The poll is a fixed
// 5 s, so a no-marker daemon exits after ~1 poll (~5 s + a bit).
const FAST_IDLE = { deferred_wrap_idle_minutes: 0.02 };

// ---------------------------------------------------------------------------
// (15) auth pre-flight non-zero -> auth-failed written, NO marker touched
// ---------------------------------------------------------------------------
console.log('\n[15] auth pre-flight non-zero -> wrap-daemon-auth-failed written, marker untouched');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-auth-');
  writeConfig(agenticDir, FAST_IDLE);
  // A ready marker the daemon WOULD drain if auth passed.
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready' });
  const logPath = path.join(base, 'mock.log');

  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'fail', MOCK_CLAUDE_LOG: logPath,
  }, 30000);

  assert(code === 0, 'daemon exits 0 after auth failure');
  assert(fs.existsSync(path.join(agenticDir, 'wrap-daemon-auth-failed')),
    'wrap-daemon-auth-failed notice written on non-zero auth');
  const m = readMarker(agenticDir, SID.a);
  assert(m && m.status === 'ready', 'ready marker left untouched (still ready) on auth failure');
  assert(m && m.attempts === 0, 'marker attempts NOT incremented on auth failure');
  // The mock log should contain `auth status` but NEVER a `--resume` drain.
  const logTxt = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : '';
  assert(/auth status/.test(logTxt), 'mock claude ran `auth status`');
  assert(!/--resume/.test(logTxt), 'mock claude was NEVER asked to drain (no --resume) on auth failure');
  assert(!fs.existsSync(lib.daemonPidPath(projectDir)), 'pid singleton released on exit');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (9) FIFO over ready markers by staged_at (oldest first) + clean drain -> done
// ---------------------------------------------------------------------------
console.log('\n[9] FIFO drain by staged_at: oldest ready marker wrapped first, then -> done');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-fifo-');
  writeConfig(agenticDir, FAST_IDLE);
  const logPath = path.join(base, 'mock.log');
  // b is OLDER than a; the FIFO head must be b.
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(60) });
  writeMarkerRaw(agenticDir, SID.b, { status: 'ready', staged_at: agoIso(600) });

  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok', MOCK_CLAUDE_LOG: logPath,
  }, 40000);

  assert(code === 0, 'daemon exits 0 after draining the queue');
  // Both markers should end as `done` (unlinked) after a clean drain.
  assert(!fs.existsSync(markerPath(agenticDir, SID.a)), 'marker a unlinked (done) after clean drain');
  assert(!fs.existsSync(markerPath(agenticDir, SID.b)), 'marker b unlinked (done) after clean drain');

  // FIFO: the FIRST --resume in the mock log must target b (the older marker).
  const drains = (fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : '')
    .split('\n').filter((l) => l.includes('--resume'));
  assert(drains.length >= 1, 'at least one --resume drain occurred');
  assert(drains[0].includes(SID.b),
    `FIFO: oldest marker (b) drained first (first drain was: ${drains[0]})`);
  assert(drains.some((l) => l.includes(SID.a)), 'newer marker (a) also drained');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (CRITICAL-A) the daemon NEVER claims a `pending` marker
// ---------------------------------------------------------------------------
console.log('\n[CRITICAL-A] daemon never drains a pending marker (only ready)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-pend-');
  writeConfig(agenticDir, FAST_IDLE);
  const logPath = path.join(base, 'mock.log');
  // ONLY a pending marker exists - the daemon must never touch it.
  writeMarkerRaw(agenticDir, SID.a, { status: 'pending', staged_at: agoIso(600) });

  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok', MOCK_CLAUDE_LOG: logPath,
  }, 30000);

  assert(code === 0, 'daemon exits 0 with only a pending marker present');
  const m = readMarker(agenticDir, SID.a);
  assert(m && m.status === 'pending', 'pending marker stays pending (never claimed)');
  assert(m && m.attempts === 0, 'pending marker attempts not incremented');
  const logTxt = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : '';
  assert(!/--resume/.test(logTxt), 'daemon issued NO --resume drain for a pending marker (CRITICAL-A)');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (14) heartbeat-fresh -> defer (marker stays ready, unclaimed)
// ---------------------------------------------------------------------------
console.log('\n[14] heartbeat-fresh -> defer: a live session keeps its ready marker unclaimed');
{
  const { base, projectDir, agenticDir, heartbeatDir } = makeProject('ae-wd-hb-');
  // Large heartbeat window so the marker is always deferred. NOTE: a 'deferred'
  // tick counts as ACTIVITY in the daemon (it keeps waiting on a still-live
  // session rather than self-exiting out from under it), so the daemon does NOT
  // idle-exit here by design - the watchdog kills it. The correctness claim is
  // that across the whole run the marker is NEVER claimed/drained.
  writeConfig(agenticDir, { deferred_wrap_idle_minutes: 0.02, deferred_wrap_heartbeat_seconds: 3600 });
  const logPath = path.join(base, 'mock.log');
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600) });
  // FRESH heartbeat -> within the 3600 s window -> defer.
  fs.writeFileSync(path.join(heartbeatDir, SID.a), '', 'utf8');

  // Short watchdog: let the daemon run a couple of poll ticks (>5 s) deferring,
  // then SIGKILL it. We assert on the marker state, not on a clean exit.
  const { signal } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok', MOCK_CLAUDE_LOG: logPath,
  }, 8000);

  assert(signal === 'SIGKILL',
    'daemon keeps deferring on a fresh heartbeat (does not self-exit; killed by watchdog)');
  const m = readMarker(agenticDir, SID.a);
  assert(m && m.status === 'ready', 'heartbeat-fresh marker stays ready (deferred, not claimed)');
  assert(m && m.attempts === 0, 'deferred marker attempts not incremented');
  const logTxt = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : '';
  assert(!/--resume/.test(logTxt), 'no --resume drain while the session heartbeat is fresh');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (16) timeout-and-kill -> hung child killed, marker reset (attempts++)
// ---------------------------------------------------------------------------
console.log('\n[16] timeout-and-kill: a hung /wrap-deferred is killed and the marker is reset (attempts++)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-to-');
  // timeout_minutes 0.02 min = 1200 ms; the mock hangs 60 s -> the daemon must kill it.
  writeConfig(agenticDir, { deferred_wrap_idle_minutes: 0.02, deferred_wrap_timeout_minutes: 0.02 });
  const logPath = path.join(base, 'mock.log');
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600) });

  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'hang', MOCK_CLAUDE_HANG_MS: '60000',
    MOCK_CLAUDE_LOG: logPath,
  }, 40000);

  assert(code === 0, 'daemon exits 0 even after a timeout-and-kill');
  const m = readMarker(agenticDir, SID.a);
  // After one timeout (attempts < cap), the marker is reset to ready for a future run.
  assert(m && m.status === 'ready',
    'timed-out marker reset to ready (not stranded in_progress)');
  assert(m && m.attempts >= 1, 'timed-out marker attempts incremented (>=1)');
  assert(m && m.claimed_by === null && m.claimed_kind === null,
    'timed-out marker claim fields cleared on reset');
  assert(m && /timeout/.test(String(m.last_error || '')),
    'timed-out marker records last_error=timeout');
  assert(!fs.existsSync(lib.daemonPidPath(projectDir)), 'pid singleton released after timeout run');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (8) idle self-exit (no ready markers at all)
// ---------------------------------------------------------------------------
console.log('\n[8] idle self-exit: a daemon with no ready markers exits on the idle window');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-idle-');
  writeConfig(agenticDir, FAST_IDLE);
  // No markers at all.
  const start = Date.now();
  const { code, stdout } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);
  const elapsed = Date.now() - start;

  assert(code === 0, 'idle daemon exits 0');
  assert(elapsed < 30000, `idle daemon self-exited before the watchdog (took ${elapsed} ms)`);
  assert(/self-exiting/.test(stdout), 'idle daemon logged a self-exit');
  assert(!fs.existsSync(lib.daemonPidPath(projectDir)), 'pid singleton released on idle exit');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (7) singleton: live pid file -> second launch no-ops; stale+dead pid -> reclaim
// ---------------------------------------------------------------------------
console.log('\n[7] singleton: a LIVE pid file blocks a second launch; a stale+dead pid is reclaimed');
{
  // (7a) LIVE pid -> second daemon must no-op (not drain the ready marker).
  const { base, projectDir, agenticDir } = makeProject('ae-wd-singleton-');
  writeConfig(agenticDir, FAST_IDLE);
  const logPath = path.join(base, 'mock.log');
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600) });
  // A pid file owned by THIS test process (alive), freshly timestamped.
  fs.writeFileSync(lib.daemonPidPath(projectDir),
    String(process.pid) + '\n' + new Date().toISOString() + '\n', 'utf8');

  const r1 = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok', MOCK_CLAUDE_LOG: logPath,
  }, 20000);
  assert(r1.code === 0, 'second daemon exits 0 when a live daemon owns the singleton');
  // The incumbent pid file (ours) must survive - the second daemon did not steal it.
  const pidBody = fs.readFileSync(lib.daemonPidPath(projectDir), 'utf8');
  assert(pidBody.startsWith(String(process.pid)),
    'live incumbent pid file preserved (second launch did not overwrite)');
  // The ready marker must be UNTOUCHED (the second daemon never drained).
  assert(readMarker(agenticDir, SID.a).status === 'ready',
    'ready marker untouched - second daemon did not drain (singleton respected)');
  const logTxt = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : '';
  assert(!/--resume/.test(logTxt), 'no drain attempted by the blocked second daemon');
  // Clean up our hand-written pid file so it is not mistaken for a live daemon later.
  try { fs.unlinkSync(lib.daemonPidPath(projectDir)); } catch (_) {}
  cleanup(base);

  // (7b) STALE + DEAD pid -> a new daemon reclaims it and runs to idle-exit.
  const p2 = makeProject('ae-wd-singleton2-');
  writeConfig(p2.agenticDir, FAST_IDLE);
  // A dead PID with a stale (old) timestamp -> reclaimable.
  fs.writeFileSync(lib.daemonPidPath(p2.projectDir),
    '2147480000\n' + new Date(Date.now() - 40 * 60 * 1000).toISOString() + '\n', 'utf8');

  const r2 = runDaemonToExit(p2.projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);
  assert(r2.code === 0, 'new daemon exits 0 after reclaiming a stale+dead pid file');
  assert(/self-exiting/.test(r2.stdout),
    'new daemon acquired the singleton (reached the drain loop and self-exited)');
  assert(!fs.existsSync(lib.daemonPidPath(p2.projectDir)),
    'reclaimed pid singleton released on exit');
  cleanup(p2.base);
}

// ---------------------------------------------------------------------------
// (10) acquireWrapLock auto-clears a STALE lock; defers on a FRESH one (lib)
// ---------------------------------------------------------------------------
console.log('\n[10] acquireWrapLock: auto-clears a stale lock, defers on a fresh one');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-lock-');
  const lockDir = path.join(agenticDir, 'wrap.lock');
  const STALE_MS = 30 * 60 * 1000;

  // (a) No lock -> acquire succeeds.
  assert(lib.acquireWrapLock(projectDir, 'owner-1', STALE_MS) === true,
    'acquireWrapLock succeeds when no lock is held');
  assert(fs.existsSync(lockDir), 'lock directory created on acquire');

  // (b) FRESH lock held by someone else -> a new acquire defers (false).
  assert(lib.acquireWrapLock(projectDir, 'owner-2', STALE_MS) === false,
    'acquireWrapLock defers (false) on a FRESH held lock');
  lib.releaseWrapLock(projectDir);
  assert(!fs.existsSync(lockDir), 'releaseWrapLock removes the lock directory');

  // (c) STALE lock -> auto-cleared + re-acquired.
  fs.mkdirSync(lockDir, { recursive: true });
  const old = new Date(Date.now() - 40 * 60 * 1000);
  fs.utimesSync(lockDir, old, old); // backdate mtime so it reads as stale
  assert(lib.wrapLockStale(projectDir, STALE_MS) === true, 'a backdated lock reads as stale');
  assert(lib.acquireWrapLock(projectDir, 'owner-3', STALE_MS) === true,
    'acquireWrapLock auto-clears a STALE lock and re-acquires');
  lib.releaseWrapLock(projectDir);

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (11/toggle) daemon does nothing destructive when there is nothing ready
// ---------------------------------------------------------------------------
console.log('\n[11] toggle/launch boundary: an idle daemon makes no marker transitions');
{
  // This complements the hook-level toggle test (session-end / session-start only
  // launch the daemon when deferred_wrap_daemon is true). Here we assert the
  // daemon itself, when launched with only a done/gave_up marker present, performs
  // no destructive transition - it has nothing to drain.
  const { base, projectDir, agenticDir } = makeProject('ae-wd-toggle-');
  writeConfig(agenticDir, FAST_IDLE);
  const logPath = path.join(base, 'mock.log');
  writeMarkerRaw(agenticDir, SID.a, { status: 'done' });
  writeMarkerRaw(agenticDir, SID.b, { status: 'gave_up', last_error: 'prev' });

  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok', MOCK_CLAUDE_LOG: logPath,
  }, 30000);

  assert(code === 0, 'daemon exits 0 with only terminal markers present');
  assert(readMarker(agenticDir, SID.b).status === 'gave_up',
    'gave_up marker left as-is (not re-attempted)');
  const logTxt = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : '';
  assert(!/--resume/.test(logTxt), 'no drain attempted for done/gave_up markers');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (SEC-C1) the drain spawn passes --disallowedTools "Bash", which REMOVES Bash from
// the headless model's context (the actual security boundary under
// bypassPermissions, where --allowedTools only suppresses prompts and does NOT
// constrain the tool set). This is what closes the repo-local .git/config RCE class.
// Every spawned child env also neutralizes global/system git config (defense-in-depth).
// ---------------------------------------------------------------------------
console.log('\n[SEC-C1] drain spawn passes --disallowedTools Bash (Bash removed from model context); child env neutralizes global/system git config');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-disallowtools-');
  writeConfig(agenticDir, FAST_IDLE);
  const logPath = path.join(base, 'mock.log');
  const envLogPath = path.join(base, 'mock-env.log');
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600) });

  runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok',
    MOCK_CLAUDE_LOG: logPath, MOCK_CLAUDE_ENV_LOG: envLogPath,
  }, 40000);

  // The mock records the full argv per invocation; the --resume drain line carries
  // the exact flags (incl. --disallowedTools / --allowedTools) the daemon passed.
  const drainLine = (fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : '')
    .split('\n').find((l) => l.includes('--resume')) || '';
  assert(drainLine.length > 0, 'a --resume drain was logged (argv is observable)');
  // Tokenize the recorded argv so flag/value pairs can be asserted positionally.
  const drainArgv = drainLine.trim().split(/\s+/);

  // CRITICAL (the load-bearing assertion): --disallowedTools "Bash" is present on the
  // drain spawn, so Bash is REMOVED from the headless model's context. This is the
  // only fix for the repo-local .git/config exec class (fsmonitor / diff.external /
  // pager / alias / ext::) - under bypassPermissions, --allowedTools alone cannot
  // close it because unlisted tools (Bash) remain in context and auto-approve.
  const disallowIdx = drainArgv.indexOf('--disallowedTools');
  assert(disallowIdx >= 0, '--disallowedTools flag is present on the /wrap-deferred drain spawn (SEC-C1)');
  assert(drainArgv[disallowIdx + 1] === 'Bash',
    `--disallowedTools value is exactly "Bash" so Bash is removed from model context (got: ${drainArgv[disallowIdx + 1]}) (SEC-C1)`);
  // The value carries no git verb or other tool - Bash removal is the whole boundary.
  assert(!/\bgit\b/.test(drainArgv[disallowIdx + 1] || ''),
    '--disallowedTools value is the bare tool name (no git verb) (SEC-C1)');

  // --allowedTools is still EXACTLY the file tools (kept; harmless prompt-suppression
  // under bypassPermissions). It is NOT the boundary, but its value must not drift.
  const allowIdx = drainArgv.indexOf('--allowedTools');
  const allowToolsVal = allowIdx >= 0 ? (drainArgv[allowIdx + 1] || '') : '';
  assert(allowToolsVal === 'Read,Edit,Write,Glob,Grep',
    `--allowedTools is exactly the file tools (got: ${allowToolsVal})`);
  // And each file tool is individually present (belt-and-suspenders on the exact match).
  for (const tool of ['Read', 'Edit', 'Write', 'Glob', 'Grep']) {
    assert(allowToolsVal.split(',').includes(tool), `allowlist still grants ${tool}`);
  }

  // Defense-in-depth: every spawned child env neutralizes global/system git config.
  const envLines = (fs.existsSync(envLogPath) ? fs.readFileSync(envLogPath, 'utf8') : '')
    .split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch (_) { return null; } })
    .filter(Boolean);
  assert(envLines.length >= 1, 'at least one child recorded its git-config env');
  for (const e of envLines) {
    assert(e.GIT_CONFIG_GLOBAL === '/dev/null',
      `child (${e.kind}) env sets GIT_CONFIG_GLOBAL=/dev/null`);
    assert(e.GIT_CONFIG_SYSTEM === '/dev/null',
      `child (${e.kind}) env sets GIT_CONFIG_SYSTEM=/dev/null`);
    assert(e.GIT_CONFIG_NOSYSTEM === '1',
      `child (${e.kind}) env sets GIT_CONFIG_NOSYSTEM=1`);
  }
  // Both the auth pre-flight child and the drain child must be hardened.
  assert(envLines.some((e) => e.kind === 'auth'),
    'auth pre-flight child env was recorded (hardened)');
  assert(envLines.some((e) => e.kind === '--resume'),
    'drain child env was recorded (hardened)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (SEC-M2) oversized config.json is skipped (defaults used, daemon still runs)
// ---------------------------------------------------------------------------
console.log('\n[SEC-M2] oversized config.json is skipped (size cap, defaults, fail-open)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-cfgcap-');
  // A config that sets FAST_IDLE but is padded past the 64 KB cap. Because the daemon
  // skips it (size cap) it falls back to DEFAULTS - including the 15-min idle window -
  // so a fast self-exit would NOT happen. We assert the daemon ignores the oversized
  // file by confirming it does NOT pick up the fast-idle override (it runs until the
  // watchdog kills it rather than self-exiting in ~1 poll).
  const padded = Object.assign({}, FAST_IDLE, { _pad: 'x'.repeat(70 * 1024) });
  fs.writeFileSync(path.join(agenticDir, 'config.json'), JSON.stringify(padded), 'utf8');
  // No ready markers -> with DEFAULTS (15-min idle) the daemon will NOT self-exit
  // within the short watchdog; with the (ignored) fast-idle it WOULD. The watchdog
  // SIGKILL proves the oversized config was skipped and defaults applied.
  const { signal, stdout } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 8000);

  assert(signal === 'SIGKILL',
    'daemon ignored the oversized config (used default 15-min idle; killed by watchdog, did not fast self-exit)');
  assert(!/self-exiting/.test(stdout),
    'daemon did NOT log a fast self-exit (oversized fast-idle override was skipped)');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// Final cleanup of the shared mock bin dir
// ---------------------------------------------------------------------------
cleanup(MOCK_DIR);

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
