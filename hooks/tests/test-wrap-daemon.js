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
 * Daemon-logging cases (.agentic/wrap/daemon.log):
 *   (LOG-1) success capture: the log holds the done outcome line + the child's
 *           captured stdout (WRAP_OK_MARKER) inside the delimited block.
 *   (LOG-2) gave_up + stderr capture + log/marker agreement: the log carries
 *           gave_up + last_error:exit:7 + the captured stderr, and the marker's
 *           last_error equals exit:7 (agree by construction).
 *   (LOG-3) ANTI-WEDGE cap: a 512 KB stdout flood is bounded at ~256 KB with the
 *           truncation notice, AND the child exits NORMALLY (no timeout/kill) -
 *           proving drain-and-discard keeps the listener attached so the child
 *           never wedges on a full OS pipe.
 *   (LOG-3b) MULTI-BYTE cap: a >256 KB flood of the 3-byte char '€' crosses the cap
 *           with a multi-byte chunk, exercising the code-point-boundary truncation
 *           loop; asserts no U+FFFD is introduced at the truncation point.
 *   (LOG-4) rotation: a >2 MB log rotates to .log.1; the live log becomes smaller.
 *   (LOG-5) SEC-C1 boundary intact after the stdio capture change: --disallowedTools
 *           Bash, --allowedTools file-tools, and the per-child GIT_CONFIG_* env are
 *           all unchanged.
 *   (LOG-6) SEC-symlink (CWE-59): a planted tracked symlink at wrap-daemon.log pointing
 *           at a victim OUTSIDE .agentic/ is NEVER written through (O_NOFOLLOW), the
 *           victim content is unchanged, and the log self-heals to a regular file
 *           (lstat-detect + unlink) - the daemon stays fail-open (exits normally).
 *
 * Hermetic: a MOCK `claude` (a stub node script placed FIRST on PATH) replaces the
 * real CLI - the daemon never invokes the real Claude. The mock's behavior is
 * driven by env vars (MOCK_CLAUDE_AUTH / MOCK_CLAUDE_WRAP / MOCK_CLAUDE_HANG_MS /
 * MOCK_CLAUDE_FLOOD_KB / MOCK_CLAUDE_FLOOD_CHAR) that the daemon forwards into the
 * child env. The drain mock
 * emits WRAP_OK_MARKER on stdout (success) or WRAP_ERR_MARKER on stderr (failure) so
 * tests can assert output capture. Project dirs live under the OS tmpdir, realpath'd
 * so the daemon's own `path.resolve(root) === root` guard accepts them. No network.
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
    'if (mode === "hang") {',
    '  const ms = parseInt(process.env.MOCK_CLAUDE_HANG_MS || "60000", 10);',
    '  setTimeout(() => process.exit(0), ms);',
    '  return;',
    '}',
    '// Multibyte boundary mode: write a known UTF-8 string whose multi-byte code points',
    '// are SPLIT across two raw writes at a mid-sequence byte boundary, so the daemon',
    '// receives the first half of a multi-byte char in one chunk and the rest in the',
    '// next. A naive chunk.toString() would emit U+FFFD for the straddled byte; a',
    '// StringDecoder buffers it. The sentinel is wrapped in MB_START/MB_END markers.',
    'if (mode === "multibyte") {',
    '  // "MB_START\\u00e9\\u20ac\\ud83d\\ude80MB_END\\n" - e-acute (2B), euro (3B), rocket (4B).',
    '  const sentinel = "MB_START\\u00e9\\u20ac\\ud83d\\ude80MB_END\\n";',
    '  const buf = Buffer.from(sentinel, "utf8");',
    '  // Find a split index that lands INSIDE a multi-byte sequence (a continuation byte,',
    '  // 0b10xxxxxx) so the first write ends mid-codepoint.',
    '  let split = -1;',
    '  for (let k = 1; k < buf.length; k++) { if ((buf[k] & 0xc0) === 0x80) { split = k; break; } }',
    '  if (split < 0) split = Math.floor(buf.length / 2);',
    '  const a = buf.subarray(0, split);',
    '  const b = buf.subarray(split);',
    '  // Write the first half, then the second half on the next tick so they arrive as',
    '  // SEPARATE data chunks on the daemon side (straddling the boundary).',
    '  process.stdout.write(a, () => {',
    '    setTimeout(() => { process.stdout.write(b, () => process.exit(0)); }, 20);',
    '  });',
    '  return;',
    '}',
    '// Optional flood: write N KB to stdout (used to prove the daemon\'s capture cap',
    '// and drain-and-discard keep a chatty child from wedging on a full OS pipe).',
    '// CRITICAL: write asynchronously and RESPECT BACKPRESSURE (wait for drain when',
    '// the OS pipe buffer fills) so the FULL flood is actually delivered to the daemon',
    '// before we exit - a synchronous write loop + immediate process.exit() would',
    '// discard everything past the first ~64 KB pipe buffer and never exercise the cap.',
    'const floodKb = parseInt(process.env.MOCK_CLAUDE_FLOOD_KB || "0", 10);',
    'function finish() {',
    '  if (mode === "fail") {',
    '    // On failure, emit a known marker on STDERR so a test can assert stderr capture.',
    '    try { process.stderr.write("WRAP_ERR_MARKER\\n"); } catch (_) {}',
    '    process.exit(7);',
    '  }',
    '  // Success: emit a known marker on STDOUT so a test can assert stdout capture.',
    '  try { process.stdout.write("WRAP_OK_MARKER\\n", () => process.exit(0)); }',
    '  catch (_) { process.exit(0); }',
    '}',
    'if (floodKb > 0) {',
    '  // MOCK_CLAUDE_FLOOD_CHAR (optional): the repeating unit of the flood. Unset ->',
    '  // exact original ASCII "x" so the LOG-3 test is byte-for-byte unchanged; set ->',
    '  // a multi-byte char (e.g. the 3-byte euro sign) to exercise the code-point',
    '  // truncation branch in appendDecoded. Each KB-unit emits 1024 of this char, so a',
    '  // 3-byte char makes each unit 3072 bytes (size MOCK_CLAUDE_FLOOD_KB accordingly).',
    '  const floodChar = process.env.MOCK_CLAUDE_FLOOD_CHAR || "x";',
    '  const chunk = floodChar.repeat(1024);',
    '  let i = 0;',
    '  function pump() {',
    '    while (i < floodKb) {',
    '      i++;',
    '      // write() returns false when the kernel pipe buffer is full -> stop and',
    '      // resume on drain (the daemon consuming the pipe is what unblocks us).',
    '      if (!process.stdout.write(chunk)) { process.stdout.once("drain", pump); return; }',
    '    }',
    '    finish();',
    '  }',
    '  pump();',
    '} else {',
    '  finish();',
    '}',
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
  // Create .agentic/wrap/heartbeats/ (new layout).
  fs.mkdirSync(path.join(agenticDir, 'wrap', 'heartbeats'), { recursive: true });
  const heartbeatDir = path.join(agenticDir, 'wrap', 'heartbeats');
  return { base, projectDir, agenticDir, heartbeatDir };
}
function cleanup(base) { try { fs.rmSync(base, { recursive: true, force: true }); } catch (_) {} }

function writeMarkerRaw(agenticDir, sessionId, overrides) {
  const projectDir = path.dirname(agenticDir);
  const marker = Object.assign({
    schema_version: 3, session_id: sessionId, staged_at: new Date().toISOString(),
    status: 'pending', claimed_by: null, claimed_kind: null, claimed_at: null,
    attempts: 0, project_root: projectDir, last_error: null,
  }, overrides || {});
  const p = lib.markerPath(projectDir, sessionId);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(marker, null, 2), 'utf8');
  return marker;
}
function readMarker(agenticDir, sessionId) {
  const p = lib.markerPath(path.dirname(agenticDir), sessionId);
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return null; }
}
function writeConfig(agenticDir, obj) {
  fs.writeFileSync(path.join(agenticDir, 'config.json'), JSON.stringify(obj, null, 2), 'utf8');
}
function agoIso(seconds) { return new Date(Date.now() - seconds * 1000).toISOString(); }

// The always-on daemon log + its single-generation rotation target.
function daemonLogPath(agenticDir) { return lib.wrapDaemonLogPath(path.dirname(agenticDir)); }
function readDaemonLog(agenticDir) {
  const p = daemonLogPath(agenticDir);
  return fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : '';
}

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
  assert(fs.existsSync(lib.authFailedPath(projectDir)),
    'wrap/daemon-auth-failed notice written on non-zero auth');
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
  // Both markers should be retained as `done` tombstones with a parseable wrapped_at.
  const mA = readMarker(agenticDir, SID.a);
  const mB = readMarker(agenticDir, SID.b);
  assert(mA !== null && mA.status === 'done', 'marker a retained as done tombstone after clean drain');
  assert(Number.isFinite(Date.parse(mA && mA.wrapped_at)), 'marker a done tombstone has parseable wrapped_at');
  assert(mB !== null && mB.status === 'done', 'marker b retained as done tombstone after clean drain');
  assert(Number.isFinite(Date.parse(mB && mB.wrapped_at)), 'marker b done tombstone has parseable wrapped_at');

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
  const lockDir = lib.wrapLockPath(projectDir);
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
// (LOG-1) success capture: clean drain writes the daemon log with the done line
// AND the child's captured stdout (WRAP_OK_MARKER) inside the delimited block.
// ---------------------------------------------------------------------------
console.log('\n[LOG-1] success capture: wrap-daemon.log contains the done line + child stdout (WRAP_OK_MARKER)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-log-ok-');
  writeConfig(agenticDir, FAST_IDLE);
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600) });

  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok',
  }, 40000);

  assert(code === 0, 'daemon exits 0 after a clean drain');
  assert(fs.existsSync(daemonLogPath(agenticDir)), '.agentic/wrap/daemon.log exists after a run');
  const logTxt = readDaemonLog(agenticDir);
  assert(new RegExp(SID.a + ' done').test(logTxt),
    'log records the per-run outcome line (session <id> done)');
  // The captured child stdout must be inside the delimited block for this session.
  const block = (logTxt.split('----- /wrap-deferred output for ' + SID.a)[1] || '')
    .split('----- end output for ' + SID.a)[0] || '';
  assert(/WRAP_OK_MARKER/.test(block),
    'child stdout (WRAP_OK_MARKER) captured inside the delimited /wrap-deferred block');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOG-2) gave_up + stderr capture + log/marker agreement: a marker pre-seeded at
// attempts:2 fails (exit 7, stderr WRAP_ERR_MARKER) -> the daemon transitions it to
// gave_up. The log carries `gave_up` + `last_error:exit:7` + the captured stderr,
// AND readMarker(...).last_error === 'exit:7' (log and marker agree by construction).
// ---------------------------------------------------------------------------
console.log('\n[LOG-2] gave_up + stderr capture + log/marker last_error agreement');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-log-giveup-');
  writeConfig(agenticDir, FAST_IDLE);
  // attempts:2 so the claim bumps it to 3 (the cap) -> gave_up on this failure.
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600), attempts: 2 });

  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'fail',
  }, 40000);

  assert(code === 0, 'daemon exits 0 after a failing drain reaches the cap');
  const m = readMarker(agenticDir, SID.a);
  assert(m && m.status === 'gave_up', 'marker transitioned to gave_up at the attempts cap');
  // Log/marker agreement: the marker last_error is exactly exit:7 ...
  assert(m && m.last_error === 'exit:7',
    `marker last_error is exit:7 (got: ${m && m.last_error})`);
  const logTxt = readDaemonLog(agenticDir);
  // ... and the log line carries the SAME last_error and a gave_up outcome.
  assert(/gave_up/.test(logTxt), 'log records the gave_up outcome line');
  assert(/last_error:exit:7/.test(logTxt),
    'log gave_up line carries last_error:exit:7 (agrees with the marker)');
  // The child stderr is captured inside the delimited block.
  const block = (logTxt.split('----- /wrap-deferred output for ' + SID.a)[1] || '')
    .split('----- end output for ' + SID.a)[0] || '';
  assert(/WRAP_ERR_MARKER/.test(block), 'child stderr (WRAP_ERR_MARKER) captured in the block');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOG-3) ANTI-WEDGE cap (highest-risk): a child floods 512 KB to stdout (>256 KB cap
// AND >>OS pipe buffer ~64 KB). Assert (a) the captured block is bounded at ~256 KB +
// the truncation notice, AND (b) the daemon observed a NORMAL child exit (the `done`
// outcome line) - proving the stream listener stayed attached (drain-and-discard) and
// the child did NOT wedge on a full pipe. (b) is the point of this test.
// ---------------------------------------------------------------------------
console.log('\n[LOG-3] anti-wedge cap: 512 KB flood is bounded at ~256 KB AND the child exits normally (no pipe wedge)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-log-flood-');
  // Generous per-child timeout so a wedge would manifest as a timeout/kill (NOT a
  // normal exit). 0.5 min = 30 s; the flood child should finish in well under that
  // IF the daemon keeps draining the pipe. If it wedged, it would be killed at 30 s.
  writeConfig(agenticDir, { deferred_wrap_idle_minutes: 0.02, deferred_wrap_timeout_minutes: 0.5 });
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600) });

  const start = Date.now();
  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok', MOCK_CLAUDE_FLOOD_KB: '512',
  }, 45000);
  const elapsed = Date.now() - start;

  assert(code === 0, 'daemon exits 0 after the flood drain');
  const m = readMarker(agenticDir, SID.a);
  // (b) THE point: the child reached the normal `done` outcome (clean exit:0). A wedge
  // would have stranded/reset the marker via the timeout path instead of leaving a tombstone.
  assert(m !== null && m.status === 'done', 'flood marker retained as done tombstone - child exited NORMALLY, no pipe wedge');
  assert(Number.isFinite(Date.parse(m && m.wrapped_at)), 'flood done tombstone has parseable wrapped_at');
  const logTxt = readDaemonLog(agenticDir);
  assert(new RegExp(SID.a + ' done').test(logTxt),
    'log shows the normal done outcome (child exited cleanly under the flood; listener stayed attached)');
  assert(!/timeout|signal:SIGKILL/.test(logTxt.split(SID.a + ' done')[0] || logTxt),
    'no timeout/kill recorded for the flood drain (proves drain-and-discard, not a wedge)');
  // It also finished well under the 30 s per-child timeout (a wedge would hit ~30 s).
  assert(elapsed < 25000, `flood drain finished promptly (no wedge); took ${elapsed} ms`);
  // (a) The captured block is bounded at ~256 KB + delimiters and carries the notice.
  const block = (logTxt.split('----- /wrap-deferred output for ' + SID.a)[1] || '')
    .split('----- end output for ' + SID.a)[0] || '';
  assert(/\[output truncated at 256 KB\]/.test(block),
    'captured block carries the [output truncated at 256 KB] notice');
  // Bounded: the captured payload is EXACTLY <= 256 KB (byte-accurate cap, truncated
  // on a code-point boundary), NOT the full 512 KB flood. The 2048-byte slack covers
  // only the surrounding delimiter/notice lines ("----- /wrap-deferred output for
  // <sid>", "[output truncated at 256 KB]", "----- end output for <sid>", newlines;
  // ~150-250 bytes) plus margin - far tighter than the old 300 KB bound, which masked
  // an up-to-~321 KB overshoot. The captured payload itself never exceeds 256 KB.
  assert(Buffer.byteLength(block) <= 256 * 1024 + 2048,
    `captured block bounded at 256 KB + delimiters (cap enforced), not the full 512 KB flood (got ${Buffer.byteLength(block)} bytes)`);
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOG-3b) MULTI-BYTE cap: a child floods >256 KB of the 3-byte char '€' (U+20AC) so
// the cap is crossed by a MULTI-BYTE chunk, exercising the code-point-boundary
// truncation `for...of` loop in appendDecoded (which LOG-3's ASCII flood never hits).
// Assert the no-U+FFFD invariant holds AT the truncation point: a multi-byte sequence
// is dropped WHOLE rather than split, so no '�' replacement char is introduced.
//
// Determinism: MAX = 256*1024 = 262144 bytes; 262144 / 3 = 87381.33, so the boundary
// char cannot fit the 1 remaining byte and is dropped WHOLE -> captured = 262143 bytes,
// never split, no U+FFFD. The boundary outcome is the same every run (the cap is a
// fixed byte count and '€' is a fixed 3 bytes), independent of how the OS chunks the
// pipe - the decoder reassembles complete code points and the truncation loop only ever
// takes whole code points. So the captured size is stable across runs.
//
// Sizing: each MOCK_CLAUDE_FLOOD_KB unit emits 1024 chars = 3072 bytes for '€', so 512
// KB-units = ~1.5 MB of bytes, comfortably exceeding the 256 KB cap.
// ---------------------------------------------------------------------------
console.log("\n[LOG-3b] multi-byte flood: cap truncates on a code-point boundary, no U+FFFD");
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-log-mbflood-');
  writeConfig(agenticDir, { deferred_wrap_idle_minutes: 0.02, deferred_wrap_timeout_minutes: 0.5 });
  writeMarkerRaw(agenticDir, SID.b, { status: 'ready', staged_at: agoIso(600) });

  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok',
    MOCK_CLAUDE_FLOOD_KB: '512', MOCK_CLAUDE_FLOOD_CHAR: '€',
  }, 45000);

  assert(code === 0, 'daemon exits 0 after the multi-byte flood drain');
  const m = readMarker(agenticDir, SID.b);
  assert(m !== null && m.status === 'done', 'multi-byte flood marker retained as done tombstone - child exited NORMALLY, no pipe wedge');
  const logTxt = readDaemonLog(agenticDir);
  const block = (logTxt.split('----- /wrap-deferred output for ' + SID.b)[1] || '')
    .split('----- end output for ' + SID.b)[0] || '';
  // (c) the cap path was actually hit (so we know the truncation branch ran).
  assert(/\[output truncated at 256 KB\]/.test(block),
    'captured block carries the [output truncated at 256 KB] notice (cap path hit)');
  // (a) NO U+FFFD replacement char introduced at the truncation point: the boundary
  // multi-byte sequence was dropped whole, not split mid-codepoint.
  assert(!block.includes('�'),
    'no U+FFFD replacement char at the truncation boundary (multi-byte char dropped whole, not split)');
  // (b) the captured payload is bounded at the cap (same bound LOG-3 uses).
  assert(Buffer.byteLength(block) <= 256 * 1024 + 2048,
    `multi-byte captured block bounded at 256 KB + delimiters (got ${Buffer.byteLength(block)} bytes)`);
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOG-4) rotation: a pre-seeded >2 MB wrap-daemon.log is rotated to .log.1 on the
// next log() call, and the live wrap-daemon.log becomes the smaller current file.
// ---------------------------------------------------------------------------
console.log('\n[LOG-4] rotation: a >2 MB wrap-daemon.log rotates to .log.1, live log becomes smaller');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-log-rot-');
  writeConfig(agenticDir, FAST_IDLE);
  // Pre-seed the live log just over the 2 MB cap so the very first log() rotates it.
  const bigLog = daemonLogPath(agenticDir);
  fs.writeFileSync(bigLog, 'y'.repeat(2 * 1024 * 1024 + 16), 'utf8');
  const seededSize = fs.statSync(bigLog).size;
  // No markers -> the daemon idle-self-exits, but it logs at least once (self-exit),
  // which triggers the rotation check.
  const { code } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);

  assert(code === 0, 'daemon exits 0');
  const rotated = bigLog + '.1';
  assert(fs.existsSync(rotated), '.agentic/wrap/daemon.log.1 exists after rotation');
  assert(fs.existsSync(bigLog), '.agentic/wrap/daemon.log (live) still exists after rotation');
  const liveSize = fs.statSync(bigLog).size;
  assert(liveSize < seededSize,
    `live log is the smaller current file after rotation (live ${liveSize} < seeded ${seededSize})`);
  assert(fs.statSync(rotated).size === seededSize,
    'rotation target .log.1 holds the prior (large) contents');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOG-5/SEC-C1) the security boundary is UNCHANGED after the stdio capture change:
// the drain spawn still passes --disallowedTools Bash + --allowedTools file-tools, and
// every spawned child env still neutralizes global/system git config.
// ---------------------------------------------------------------------------
console.log('\n[LOG-5/SEC-C1] boundary intact after stdio capture: --disallowedTools Bash + GIT_CONFIG_* still present');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-log-sec-');
  writeConfig(agenticDir, FAST_IDLE);
  const logPath = path.join(base, 'mock.log');
  const envLogPath = path.join(base, 'mock-env.log');
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600) });

  runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok',
    MOCK_CLAUDE_LOG: logPath, MOCK_CLAUDE_ENV_LOG: envLogPath,
  }, 40000);

  const drainLine = (fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : '')
    .split('\n').find((l) => l.includes('--resume')) || '';
  const drainArgv = drainLine.trim().split(/\s+/);
  const disallowIdx = drainArgv.indexOf('--disallowedTools');
  assert(disallowIdx >= 0 && drainArgv[disallowIdx + 1] === 'Bash',
    '--disallowedTools Bash still present on the drain spawn after stdio capture (SEC-C1)');
  const allowIdx = drainArgv.indexOf('--allowedTools');
  assert(allowIdx >= 0 && drainArgv[allowIdx + 1] === 'Read,Edit,Write,Glob,Grep',
    '--allowedTools file-tools unchanged after stdio capture (SEC-C1)');
  const envLines = (fs.existsSync(envLogPath) ? fs.readFileSync(envLogPath, 'utf8') : '')
    .split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch (_) { return null; } })
    .filter(Boolean);
  const drainEnv = envLines.find((e) => e.kind === '--resume');
  assert(drainEnv && drainEnv.GIT_CONFIG_GLOBAL === '/dev/null'
    && drainEnv.GIT_CONFIG_SYSTEM === '/dev/null' && drainEnv.GIT_CONFIG_NOSYSTEM === '1',
    'drain child env still neutralizes global/system git config after stdio capture (SEC-C1)');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOG-6/SEC-symlink) CWE-59 planted-symlink write-through is closed: a hostile repo
// pre-plants a tracked symlink at .agentic/wrap/daemon.log pointing at a victim file
// OUTSIDE .agentic/. The O_NOFOLLOW write + lstat self-heal must (a) NEVER write
// through the link into the victim, (b) replace the link with a fresh REGULAR log
// holding the daemon's own lines, and (c) keep the daemon fail-open (exits normally).
// ---------------------------------------------------------------------------
console.log('\n[LOG-6/SEC-symlink] planted symlink at wrap/daemon.log: victim untouched, log self-heals to a regular file (CWE-59)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-log-symlink-');
  writeConfig(agenticDir, FAST_IDLE);
  // A victim sentinel OUTSIDE .agentic/ (in the test's own tmp base) with known content.
  const victim = path.join(base, 'victim.txt');
  const VICTIM_CONTENT = 'DO-NOT-OVERWRITE-' + 'x'.repeat(64);
  fs.writeFileSync(victim, VICTIM_CONTENT, 'utf8');
  // Pre-plant the hostile symlink where the daemon will append its log.
  const logPath = daemonLogPath(agenticDir);
  fs.symlinkSync(victim, logPath);
  assert(fs.lstatSync(logPath).isSymbolicLink(), 'precondition: wrap-daemon.log is a planted symlink');

  // No ready markers -> the daemon idle-self-exits, but it still log()s lifecycle lines
  // (startup/self-exit), which exercises appendToLog against the planted link.
  const { code, signal } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);

  // (c) fail-open: the daemon exited normally, it did NOT crash on the planted link.
  assert(code === 0 && !signal, `daemon exits 0 / not killed despite the planted symlink (code=${code} signal=${signal})`);
  // (a) the victim was NEVER written through the link - content byte-identical, and no
  // daemon log line leaked into it.
  const victimAfter = fs.readFileSync(victim, 'utf8');
  assert(victimAfter === VICTIM_CONTENT, 'victim file content UNCHANGED (never written through the symlink)');
  assert(!/\[wrap-daemon\]/.test(victimAfter), 'no [wrap-daemon] line leaked into the victim via the link');
  // (b) the log self-healed: wrap-daemon.log is now a REGULAR file (link removed) holding
  // the daemon's own lines.
  const st = fs.lstatSync(logPath);
  assert(st.isFile() && !st.isSymbolicLink(), 'wrap-daemon.log self-healed to a REGULAR file (symlink removed)');
  assert(/\[wrap-daemon\]/.test(readDaemonLog(agenticDir)), 'self-healed regular log holds the daemon lines');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// Lock-clear helpers (Part F: LOCK-1..7)
// ---------------------------------------------------------------------------
// Plant a wrap/lock DIRECTORY with an optional owner file body.
function plantLockDir(projectDir, ownerBody) {
  const lockDir = lib.wrapLockPath(projectDir);
  fs.mkdirSync(lockDir, { recursive: true });
  if (ownerBody !== null && ownerBody !== undefined) {
    fs.writeFileSync(path.join(lockDir, 'owner'), ownerBody, 'utf8');
  }
  return lockDir;
}
// A PID that is essentially guaranteed dead (very high, unlikely to be live).
const DEAD_PID = '2147480000';

// ---------------------------------------------------------------------------
// (LOCK-1) dead-PID owner -> the daemon clears the stale wrap.lock before drain.
// ---------------------------------------------------------------------------
console.log('\n[LOCK-1] dead-PID owner: daemon clears stale wrap/lock before drain');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-lock1-');
  writeConfig(agenticDir, FAST_IDLE);
  // wrap/lock dir + owner = a known-dead PID (2-line body, PID + recent ISO).
  const lockDir = plantLockDir(projectDir, DEAD_PID + '\n' + new Date().toISOString() + '\n');
  assert(fs.existsSync(lockDir), 'precondition: stale wrap/lock dir planted');

  const { code, stdout } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);

  assert(code === 0, 'daemon exits 0');
  assert(!fs.existsSync(lockDir), 'stale wrap/lock dir was cleared (dead owner PID)');
  assert(/cleared provably-stale wrap[./]lock/.test(stdout)
    || /cleared provably-stale wrap[./]lock/.test(readDaemonLog(agenticDir)),
    'daemon logged "cleared provably-stale wrap/lock"');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOCK-2) no-PID owner + old timestamp -> cleared.
// ---------------------------------------------------------------------------
console.log('\n[LOCK-2] no-PID owner + old timestamp: daemon clears stale wrap/lock');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-lock2-');
  writeConfig(agenticDir, FAST_IDLE);
  // owner body = "\n<35-min-ago ISO>" -> line0 empty (no PID), line1 = old ts.
  // Default reclaim window is 30 min, so 35 min is provably stale.
  const lockDir = plantLockDir(projectDir, '\n' + agoIso(35 * 60) + '\n');

  const { code } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);

  assert(code === 0, 'daemon exits 0');
  assert(!fs.existsSync(lockDir), 'stale wrap/lock dir cleared (no PID + owner ts older than staleMs)');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOCK-3) symlink at wrap.lock is NOT followed: victim untouched, link removed.
// ---------------------------------------------------------------------------
console.log('\n[LOCK-3] symlink at wrap/lock: not followed, victim untouched, link removed (CWE-59)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-lock3-');
  writeConfig(agenticDir, FAST_IDLE);
  // A sentinel dir+file OUTSIDE .agentic/ that the symlink points at.
  const sentinelDir = path.join(base, 'sentinel-dir');
  fs.mkdirSync(sentinelDir, { recursive: true });
  const sentinelFile = path.join(sentinelDir, 'keep.txt');
  const SENTINEL_CONTENT = 'DO-NOT-DELETE-' + 'z'.repeat(48);
  fs.writeFileSync(sentinelFile, SENTINEL_CONTENT, 'utf8');
  // Plant wrap/lock as a SYMLINK to the sentinel dir.
  const lockPath = lib.wrapLockPath(projectDir);
  fs.mkdirSync(path.dirname(lockPath), { recursive: true });
  fs.symlinkSync(sentinelDir, lockPath);
  assert(fs.lstatSync(lockPath).isSymbolicLink(), 'precondition: wrap/lock is a planted symlink');

  const { code, signal } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);

  assert(code === 0 && !signal, `daemon exits 0 / not killed (code=${code} signal=${signal})`);
  // Sentinel must be byte-identical and still present (never followed/deleted through link).
  assert(fs.existsSync(sentinelFile), 'sentinel file still present (symlink target never removed)');
  assert(fs.readFileSync(sentinelFile, 'utf8') === SENTINEL_CONTENT,
    'sentinel content byte-identical (symlink not followed)');
  // The link itself is gone (unlinked as a hostile artifact).
  let linkGone = false;
  try { fs.lstatSync(lockPath); } catch (_) { linkGone = true; }
  assert(linkGone, 'planted wrap/lock symlink removed (link only, target untouched)');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOCK-4) live-PID owner + recent ts -> lock KEPT (must NEVER clear a live lock).
// ---------------------------------------------------------------------------
console.log('\n[LOCK-4] live-PID owner + recent ts: lock KEPT (never clears a live lock)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-lock4-');
  writeConfig(agenticDir, FAST_IDLE);
  // owner = THIS test process PID (alive) + recent ts.
  const lockDir = plantLockDir(projectDir, String(process.pid) + '\n' + new Date().toISOString() + '\n');

  const { code } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);

  assert(code === 0, 'daemon exits 0');
  assert(fs.existsSync(lockDir), 'live lock KEPT (alive owner PID is authoritative)');
  const ownerAfter = fs.readFileSync(path.join(lockDir, 'owner'), 'utf8');
  assert(ownerAfter.startsWith(String(process.pid)), 'owner file unchanged (lock untouched)');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOCK-5) no-owner race -> lock KEPT (no usable signal -> keep, covers the
// interactive /wrap mkdir-before-owner window).
// ---------------------------------------------------------------------------
console.log('\n[LOCK-5] no-owner race: lock KEPT (no signal -> keep)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-lock5-');
  writeConfig(agenticDir, FAST_IDLE);
  // mkdir wrap/lock with NO owner file at all.
  const lockDir = plantLockDir(projectDir, null);

  const { code } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);

  assert(code === 0, 'daemon exits 0');
  assert(fs.existsSync(lockDir), 'no-owner lock KEPT (no usable signal -> keep, mkdir-before-owner race)');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOCK-6) alive-PID + OLD ts -> KEEP (the live-lock corruption guard: an alive
// PID is authoritative; timestamp age does NOT override liveness).
// ---------------------------------------------------------------------------
console.log('\n[LOCK-6] alive-PID + OLD ts: KEEP (alive PID authoritative; age does not override)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-lock6-');
  writeConfig(agenticDir, FAST_IDLE);
  // owner = alive PID (this process) + a 35-min-old ts (older than the 30-min window).
  const lockDir = plantLockDir(projectDir, String(process.pid) + '\n' + agoIso(35 * 60) + '\n');

  const { code } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);

  assert(code === 0, 'daemon exits 0');
  assert(fs.existsSync(lockDir),
    'lock KEPT despite OLD ts (alive PID is authoritative; age does not drive the clear)');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOCK-7) dead-PID + RECENT ts -> CLEAR (liveness, not age, drives the clear).
// ---------------------------------------------------------------------------
console.log('\n[LOCK-7] dead-PID + RECENT ts: CLEAR (liveness, not age, drives the clear)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-lock7-');
  writeConfig(agenticDir, FAST_IDLE);
  // owner = dead PID + a FRESH ts (within the window). The PID liveness, not the
  // timestamp, must drive the clear.
  const lockDir = plantLockDir(projectDir, DEAD_PID + '\n' + new Date().toISOString() + '\n');

  const { code } = runDaemonToExit(projectDir, { MOCK_CLAUDE_AUTH: 'ok' }, 30000);

  assert(code === 0, 'daemon exits 0');
  assert(!fs.existsSync(lockDir), 'lock CLEARED on a dead PID even with a recent ts (liveness drives)');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOCK-8) readWrapLockOwner parent-symlink guard: when wrap.lock itself is a
// symlink to an attacker-controlled directory that contains a real (non-symlink)
// owner file, readWrapLockOwner must return {pid:null,ts:null} WITHOUT reading the
// attacker's owner. The leaf lstat guard alone is insufficient here because the
// attacker's owner is a regular file (isSymbolicLink()===false at the leaf level).
// ---------------------------------------------------------------------------
console.log('\n[LOCK-8] readWrapLockOwner parent-symlink guard: does not read owner through a parent wrap/lock symlink (CWE-59 defense-in-depth)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-lock8-');

  // Plant an "attacker" directory OUTSIDE .agentic/ containing a real owner file
  // with recognizable PID + far-future ISO timestamp.
  const attackerDir = path.join(base, 'attacker-dir');
  fs.mkdirSync(attackerDir, { recursive: true });
  const ATTACKER_PID = '4242';
  const ATTACKER_TS = '2099-01-01T00:00:00.000Z';
  fs.writeFileSync(path.join(attackerDir, 'owner'),
    ATTACKER_PID + '\n' + ATTACKER_TS + '\n', 'utf8');

  // Plant .agentic/wrap/lock as a SYMLINK to the attacker directory.
  const lockPath = lib.wrapLockPath(projectDir);
  fs.mkdirSync(path.dirname(lockPath), { recursive: true });
  fs.symlinkSync(attackerDir, lockPath);
  assert(fs.lstatSync(lockPath).isSymbolicLink(),
    'LOCK-8 precondition: wrap/lock is a symlink to the attacker dir');

  // readWrapLockOwner must NOT resolve through the parent link and read the
  // attacker's owner file; it must return {pid:null,ts:null}.
  const result = lib.readWrapLockOwner(projectDir);
  assert(result.pid === null && result.ts === null,
    'LOCK-8: readWrapLockOwner returns {pid:null,ts:null} when wrap/lock is a parent symlink (did NOT read attacker owner through the link)');

  // The attacker dir and its owner file must be completely untouched.
  assert(fs.existsSync(path.join(attackerDir, 'owner')),
    'LOCK-8: attacker dir/owner file is untouched (never followed into)');
  const attackerOwnerContent = fs.readFileSync(path.join(attackerDir, 'owner'), 'utf8');
  assert(attackerOwnerContent.startsWith(ATTACKER_PID),
    'LOCK-8: attacker owner file content is unchanged (no side effects)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (LOCK-M1) daemon owns the wrap lock: a live lock WITH a ready marker present
// causes the daemon to skip the drain (return 'idle') and self-exit cleanly
// (code 0, no watchdog SIGKILL); after release the daemon drains normally and
// leaves no wrap/lock dir behind.
// ---------------------------------------------------------------------------
console.log('\n[LOCK-M1] daemon owns wrap lock: live lock + ready marker -> idle self-exit; release -> drain; no lock residue');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-lockm1-');
  writeConfig(agenticDir, FAST_IDLE);
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600) });
  const logPath = path.join(base, 'mock.log');

  // (i) Hold the lock from the test process, then run the daemon.
  // The daemon must detect the held lock, NOT drain, NOT SIGKILL-spin.
  const STALE_MS = 30 * 60 * 1000;
  const lockAcquiredByTest = lib.acquireWrapLock(projectDir, String(process.pid), STALE_MS);
  assert(lockAcquiredByTest === true, 'LOCK-M1 precondition: test process acquired the wrap lock');

  const r1 = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok', MOCK_CLAUDE_LOG: logPath,
  }, 30000);
  assert(r1.code === 0, 'LOCK-M1(i): daemon exits 0 (not killed by watchdog) when a live lock is held');
  assert(r1.signal !== 'SIGKILL', 'LOCK-M1(i): daemon was NOT SIGKILLed (idle self-exit, not spin)');

  // Marker must still be ready (daemon did not drain).
  const mAfterBlock = readMarker(agenticDir, SID.a);
  assert(mAfterBlock && mAfterBlock.status === 'ready',
    'LOCK-M1(i): ready marker stays ready when lock is held (daemon skipped drain)');
  assert(!fs.existsSync(logPath) || !/--resume/.test(fs.readFileSync(logPath, 'utf8')),
    'LOCK-M1(i): no --resume drain issued when the lock was held');

  // (ii) Release the lock - daemon should now drain normally.
  lib.releaseWrapLock(projectDir);
  // Reset the mock log so we can assert a new drain.
  try { fs.unlinkSync(logPath); } catch (_) {}

  const r2 = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok', MOCK_CLAUDE_LOG: logPath,
  }, 40000);
  assert(r2.code === 0, 'LOCK-M1(ii): daemon exits 0 after lock is released');
  const mAfterDrain = readMarker(agenticDir, SID.a);
  assert(mAfterDrain && mAfterDrain.status === 'done',
    'LOCK-M1(ii): marker transitioned to done tombstone after lock was released');
  assert(Number.isFinite(Date.parse(mAfterDrain && mAfterDrain.wrapped_at)),
    'LOCK-M1(ii): done tombstone has parseable wrapped_at');
  const drains = (fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : '')
    .split('\n').filter((l) => l.includes('--resume'));
  assert(drains.length >= 1, 'LOCK-M1(ii): at least one --resume drain occurred after lock release');

  // (iii) No wrap/lock dir persists after the daemon acquired and released it.
  assert(!fs.existsSync(lib.wrapLockPath(projectDir)),
    'LOCK-M1(iii): no wrap/lock dir persists after the daemon ran (daemon released what it acquired)');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (CAP-multibyte) a multi-byte UTF-8 string straddling a chunk/backpressure
// boundary is captured byte-exact (no U+FFFD) thanks to the StringDecoder.
// ---------------------------------------------------------------------------
console.log('\n[CAP-multibyte] multi-byte UTF-8 straddling a chunk boundary captured byte-exact (no U+FFFD)');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-multibyte-');
  writeConfig(agenticDir, FAST_IDLE);
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600) });

  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'multibyte',
  }, 40000);

  assert(code === 0, 'daemon exits 0 after a multibyte drain');
  const logTxt = readDaemonLog(agenticDir);
  const block = (logTxt.split('----- /wrap-deferred output for ' + SID.a)[1] || '')
    .split('----- end output for ' + SID.a)[0] || '';
  // The exact sentinel the mock emitted (e-acute 2B, euro 3B, rocket 4B), reassembled.
  const expected = 'MB_STARTé€🚀MB_END';
  assert(block.includes(expected),
    'captured block contains the exact multi-byte sentinel reassembled across the chunk boundary');
  assert(!block.includes('�'),
    'captured block contains NO U+FFFD replacement char (StringDecoder reassembled the straddled bytes)');
  cleanup(base);
}

// ---------------------------------------------------------------------------
// (WRITE-short) a long log line is present byte-complete in wrap-daemon.log after a
// run (exercises the appendToLog partial-write loop on the captured-output block).
// ---------------------------------------------------------------------------
console.log('\n[WRITE-short] a long captured line is present byte-complete in wrap-daemon.log');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wd-write-');
  writeConfig(agenticDir, FAST_IDLE);
  writeMarkerRaw(agenticDir, SID.a, { status: 'ready', staged_at: agoIso(600) });
  // Flood ~200 KB (under the 256 KB capture cap) so a single large block line is
  // written to the log; the partial-write loop must emit it whole.
  const { code } = runDaemonToExit(projectDir, {
    MOCK_CLAUDE_AUTH: 'ok', MOCK_CLAUDE_WRAP: 'ok', MOCK_CLAUDE_FLOOD_KB: '200',
  }, 45000);

  assert(code === 0, 'daemon exits 0 after the large-output drain');
  const logTxt = readDaemonLog(agenticDir);
  const block = (logTxt.split('----- /wrap-deferred output for ' + SID.a)[1] || '')
    .split('----- end output for ' + SID.a)[0] || '';
  // Not truncated (200 KB < 256 KB cap), so the full ~200 KB of 'x' is byte-complete.
  assert(!/\[output truncated at 256 KB\]/.test(block),
    'precondition: 200 KB output is under the 256 KB cap (not truncated)');
  const xCount = (block.match(/x/g) || []).length;
  assert(xCount >= 200 * 1024,
    `the full ~200 KB flood is byte-complete in the log (got ${xCount} x bytes; partial-write loop wrote it whole)`);
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
