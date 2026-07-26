#!/usr/bin/env node
'use strict';

/**
 * Purpose: Concurrency regression suite for hooks/lib/wrap-marker.js +
 *          bin/agentic-wrap-acquire-lock (U5, DS wrap-lock-liveness). Every other
 *          test file touched by this change (test-wrap-acquire-lock.js,
 *          test-wrap-release-lock.js, test-wrap-lock-verdict.js, test-wrap-daemon.js,
 *          test-wrap-md-partA-parity.js) is single-process: it plants a fixture,
 *          invokes the code once (or once per case), and asserts a result. NONE of
 *          them prove the central safety property under real OS-level concurrency -
 *          that a live lock is never falsely stolen when N processes race for it at
 *          once. This file spawns genuine concurrent child processes (via
 *          child_process.spawn) to pin that property directly.
 *
 * Cases:
 *   A. THE CENTRAL REGRESSION TEST - a 90-minute-old live whole-flow lock (JSON
 *      descriptor role:agent + a legacy 2-line dead-PID body) survives 10 concurrent
 *      `agentic-wrap-acquire-lock` waiters: all 10 time out (exit 2), zero acquire,
 *      zero give-up, the lock and both owner artifacts are untouched byte-for-byte.
 *   B. The daemon-side arm of the same property: clearProvablyStaleWrapLock refuses
 *      to clear the same live 90-minute fixture.
 *   C. The reported 10-tab symptom repro: 10 waiters serialize correctly through a
 *      lock that is released and re-contested repeatedly, each acquiring exactly
 *      once, with a marker-file handshake proving no two ever hold it at once.
 *   D. An empty (mkdir-before-owner-race) lock directory is waited on, never cleared,
 *      by 10 concurrent waiters.
 *   E. Source pin: retired give-up codes/branches are structurally absent from the
 *      binary; exactly one process.exit(0) call site.
 *   F. Prose -> producer -> predicate round trip: the exact command ds-wrap.md tells
 *      the conductor to run is the command that produces the descriptor the
 *      predicate reads, and the doc no longer instructs a hand-rolled mkdir.
 *
 * Run with: node hooks/tests/test-wrap-no-false-giveup.js
 * Auto-discovered by .github/workflows/hooks-tests.yml's `hooks/tests/test-*.js` glob
 * (hooks-js-tests job, 10-minute budget) - do NOT add a quarantine case arm for this
 * file; it is meant to run there.
 *
 * Wall-clock hang guard: each case runs under a ~120s Promise.race timeout (see
 * runCase below). This is a "did this case wedge" safety net ONLY - it is NEVER used
 * as a correctness assertion. Real assertions are exit codes, file contents, and
 * directory listings.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { spawn, execFileSync } = require('child_process');
const lib = require('../lib/wrap-marker.js');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SCRIPT_PATH = path.join(REPO_ROOT, 'bin', 'agentic-wrap-acquire-lock');
const LIB_PATH = path.join(REPO_ROOT, 'hooks', 'lib', 'wrap-marker.js');
const DS_WRAP_MD_PATH = path.join(REPO_ROOT, 'content', 'commands', 'ds-wrap.md');

/** A PID that is essentially guaranteed dead (very high, unlikely to be live). */
const DEAD_PID = 2147480000;
/** Concurrency width for every multi-waiter case, per the brief. */
const N = 10;
/** Per-case wall-clock hang guard (ms). NEVER a correctness assertion - see header. */
const HANG_GUARD_MS = 120000;

let passed = 0;
let failed = 0;
const tmpDirs = [];

function assert(condition, message) {
  if (condition) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message}`);
    failed++;
  }
}

function makeTmp(prefix) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  tmpDirs.push(dir);
  return dir;
}

function sha256(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Run one case async function under a wall-clock hang guard. The guard exists
 * solely so a genuine wedge fails loud and fast instead of consuming the whole
 * hooks-js-tests job budget; it is never used to assert correctness.
 */
async function runCase(label, fn) {
  console.log(`\n[${label}]`);
  let timer;
  const guard = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`hang guard: exceeded ${HANG_GUARD_MS}ms`)), HANG_GUARD_MS);
  });
  try {
    await Promise.race([fn(), guard]);
  } catch (e) {
    failed++;
    console.error(`  FAIL: case did not complete cleanly: ${(e && e.stack) || e}`);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Spawn `agentic-wrap-acquire-lock` as a real OS child process and resolve with
 * its stdout and exit code once it exits. Used for true multi-process concurrency
 * (Cases A, D) - execFileSync would serialize these one at a time.
 */
function spawnAcquireChild(args) {
  return new Promise((resolve) => {
    const child = spawn('node', [SCRIPT_PATH, ...args], { stdio: ['ignore', 'pipe', 'ignore'] });
    let stdout = '';
    child.stdout.on('data', (d) => { stdout += d.toString(); });
    child.on('exit', (code) => resolve({ stdout, exitCode: code === null ? -1 : code }));
    child.on('error', () => resolve({ stdout, exitCode: -1 }));
  });
}

/**
 * Run `node <args>` synchronously, never throwing - returns {stdout, exitCode}.
 * Mirrors the runHelper() convention in test-wrap-acquire-lock.js.
 */
function runNode(args) {
  try {
    const stdout = execFileSync('node', args, { encoding: 'utf8', timeout: 15000 });
    return { stdout: stdout || '', exitCode: 0 };
  } catch (e) {
    return { stdout: e.stdout || '', exitCode: (e.status !== null && e.status !== undefined) ? e.status : -1 };
  }
}

/** Plant the "live whole-flow /ds-wrap, 90 minutes running" fixture shared by Cases A/B. */
function plantLiveNinetyMinuteFixture(dir) {
  const acquiredAt = new Date(Date.now() - 90 * 60 * 1000).toISOString();
  const descriptor = lib.makeLockDescriptor({ role: 'agent', acquiredAt });
  const lockDir = lib.wrapLockPath(dir);
  fs.mkdirSync(lockDir, { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(dir), JSON.stringify(descriptor), 'utf8');
  fs.writeFileSync(lib.wrapLockOwnerPath(dir), String(DEAD_PID) + '\n' + acquiredAt + '\n', 'utf8');
  return lockDir;
}

/**
 * Shared preconditions for Cases A and B. These are NOT hygiene - without them a
 * schema-invalid descriptor would silently degrade to source:'legacy' and the case
 * would pass vacuously via the pid-blind legacy row-6 rule, proving nothing about
 * owner.json at all.
 */
function assertLiveFixturePreconditions(dir, label) {
  const o = lib.readWrapLockOwnerV2(dir);
  assert(o.source === 'json', `${label} precondition: descriptor is schema-valid (got source=${o.source})`);
  const v = lib.wrapLockVerdict(dir);
  assert(v.verdict === 'live', `${label} precondition: verdict is live (got ${v.verdict})`);
  assert(o.role === 'agent', `${label} precondition: role is agent (got ${o.role})`);
}

// ---------------------------------------------------------------------------
// Case A: THE CENTRAL REGRESSION TEST
// ---------------------------------------------------------------------------
async function caseA() {
  const tmp = makeTmp('nfg-caseA-');
  const lockDir = plantLiveNinetyMinuteFixture(tmp);
  assertLiveFixturePreconditions(tmp, 'Case A');

  const ownerJsonShaBefore = sha256(fs.readFileSync(lib.wrapLockOwnerJsonPath(tmp)));
  const ownerShaBefore = sha256(fs.readFileSync(lib.wrapLockOwnerPath(tmp)));

  const results = await Promise.all(
    Array.from({ length: N }, () => spawnAcquireChild([tmp, '--timeout-ms=4000', '--poll-ms=300']))
  );

  const exitCodes = results.map((r) => r.exitCode);
  assert(exitCodes.every((c) => c === 2), `Case A: all ${N} children exit 2 (their own timeout budget) (got: ${JSON.stringify(exitCodes)})`);
  assert(!exitCodes.some((c) => c === 0 || c === 3 || c === 4 || c === 5), `Case A: zero children exit 0/3/4/5 (got: ${JSON.stringify(exitCodes)})`);
  assert(fs.existsSync(lockDir), 'Case A: lock directory still exists after 10 concurrent waiters timed out');

  const ownerJsonShaAfter = sha256(fs.readFileSync(lib.wrapLockOwnerJsonPath(tmp)));
  const ownerShaAfter = sha256(fs.readFileSync(lib.wrapLockOwnerPath(tmp)));
  assert(ownerJsonShaAfter === ownerJsonShaBefore, 'Case A: owner.json byte-identical to what was planted (sha256 match)');
  assert(ownerShaAfter === ownerShaBefore, 'Case A: owner byte-identical to what was planted (sha256 match)');

  assert(results.every((r) => /rm -rf/.test(r.stdout)),
    `Case A: every child printed a line containing "rm -rf" (got stdouts: ${JSON.stringify(results.map((r) => r.stdout))})`);
}

// ---------------------------------------------------------------------------
// Case B: daemon arm of the same property
// ---------------------------------------------------------------------------
async function caseB() {
  const tmp = makeTmp('nfg-caseB-');
  const lockDir = plantLiveNinetyMinuteFixture(tmp);
  assertLiveFixturePreconditions(tmp, 'Case B');

  const cleared = lib.clearProvablyStaleWrapLock(tmp, 1800000);
  assert(cleared === false, `Case B: clearProvablyStaleWrapLock(cwd, 1800000) returns false for a live 90-min lock (got: ${cleared})`);
  assert(fs.existsSync(lockDir), 'Case B: lock dir survives the daemon-side clear attempt');
  assert(fs.existsSync(lib.wrapLockOwnerJsonPath(tmp)), 'Case B: owner.json survives');
  assert(fs.existsSync(lib.wrapLockOwnerPath(tmp)), 'Case B: legacy owner survives');
}

// ---------------------------------------------------------------------------
// Case C: the 10-tab symptom repro (serialized handoff, no double-hold)
// ---------------------------------------------------------------------------

/**
 * Build the source of a small Node wrapper process for one Case C waiter. The
 * wrapper spawns the real acquire-lock binary as its own child; on that child's
 * exit 0 (acquired), it performs the marker-write -> re-read -> `.done` sentinel
 * handshake (ORDERING BARRIER, reviewer Minor 3): the driver must never release
 * on the mere "acquired" signal, only after this handshake's `.done-<id>` file is
 * observable, or a correct implementation would flake with an ENOENT race against
 * the marker write. The marker-count evidence is written OUTSIDE the lock
 * directory (into tmp, not lockDir) so it survives the driver's next release,
 * which rmSync's the whole lock directory including the marker and `.done` file.
 */
function buildCaseCWaiterSource(tmp, waiterId) {
  return `
'use strict';
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const lib = require(${JSON.stringify(LIB_PATH)});
const tmp = ${JSON.stringify(tmp)};
const scriptPath = ${JSON.stringify(SCRIPT_PATH)};
const waiterId = ${JSON.stringify(waiterId)};

const child = spawn('node', [scriptPath, tmp, '--timeout-ms=20000', '--poll-ms=150'], {
  stdio: ['ignore', 'ignore', 'ignore'],
});
child.on('exit', (code) => {
  if (code === 0) {
    try {
      const lockDir = lib.wrapLockPath(tmp);
      const markerName = 'marker-' + waiterId + '-' + process.pid;
      fs.writeFileSync(path.join(lockDir, markerName), 'x', 'utf8');
      const markerEntries = fs.readdirSync(lockDir).filter((n) => n.indexOf('marker-') === 0);
      fs.writeFileSync(path.join(tmp, '.marker-count-' + waiterId), String(markerEntries.length), 'utf8');
      fs.writeFileSync(path.join(lockDir, '.done-' + waiterId), 'x', 'utf8');
    } catch (e) {
      try {
        fs.writeFileSync(path.join(tmp, '.marker-count-' + waiterId), 'ERROR:' + String(e && e.message), 'utf8');
      } catch (_) { /* best-effort diagnostic only */ }
    }
  }
  process.exit(code === null ? -1 : code);
});
child.on('error', () => process.exit(-1));
`;
}

async function caseC() {
  const tmp = makeTmp('nfg-caseC-');
  const lockDir = lib.wrapLockPath(tmp);

  // Initial holder: an artificial "currently held" lock, released ~2s in - the
  // brief's "a lock that gets released ~2s in".
  fs.mkdirSync(lockDir, { recursive: true });
  const initDescriptor = lib.makeLockDescriptor({ role: 'agent' });
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(tmp), JSON.stringify(initDescriptor), 'utf8');
  fs.writeFileSync(lib.wrapLockOwnerPath(tmp), process.pid + '\n' + new Date().toISOString() + '\n', 'utf8');

  const waiterProcs = [];
  const exitPromises = [];
  for (let i = 0; i < N; i++) {
    const waiterId = 'w' + i;
    const proc = spawn('node', ['-e', buildCaseCWaiterSource(tmp, waiterId)], { stdio: ['ignore', 'ignore', 'ignore'] });
    waiterProcs.push(proc);
    exitPromises.push(new Promise((resolve) => {
      proc.on('exit', (code) => resolve(code === null ? -1 : code));
      proc.on('error', () => resolve(-1));
    }));
  }

  try {
    await sleep(2000);
    lib.releaseWrapLock(tmp); // release the artificial initial holder

    // Drive the release loop: release again only after observing a NEW
    // `.done-*` sentinel (the ordering barrier - see buildCaseCWaiterSource doc).
    const seenDone = new Set();
    const driverDeadline = Date.now() + 60000;
    let releasedForChildren = 0;
    while (releasedForChildren < N && Date.now() < driverDeadline) {
      let doneFile = null;
      try {
        const entries = fs.readdirSync(lockDir);
        doneFile = entries.find((n) => n.indexOf('.done-') === 0 && !seenDone.has(n)) || null;
      } catch (_) {
        // lock dir may not exist momentarily between rounds; keep polling.
      }
      if (doneFile) {
        seenDone.add(doneFile);
        releasedForChildren++;
        lib.releaseWrapLock(tmp);
      } else {
        await sleep(50);
      }
    }

    const exitCodes = await Promise.all(exitPromises);
    assert(exitCodes.length === N && exitCodes.every((c) => c === 0),
      `Case C: all ${N} waiters exit 0 exactly once each (got: ${JSON.stringify(exitCodes)})`);
    assert(!exitCodes.some((c) => c === 3), `Case C: zero exit 3 (got: ${JSON.stringify(exitCodes)})`);
    assert(!exitCodes.some((c) => c === 4), `Case C: zero exit 4 (got: ${JSON.stringify(exitCodes)})`);
    assert(releasedForChildren === N, `Case C: driver observed exactly one .done sentinel per waiter (got: ${releasedForChildren})`);
    assert(!fs.existsSync(lockDir), 'Case C: no residual lock directory at the end');

    // No-two-simultaneous-holders: every waiter's own re-read (recorded outside
    // the lock dir so it survives that waiter's own release) must show exactly
    // one marker file.
    for (let i = 0; i < N; i++) {
      const waiterId = 'w' + i;
      const countPath = path.join(tmp, '.marker-count-' + waiterId);
      let recorded = null;
      try { recorded = fs.readFileSync(countPath, 'utf8').trim(); } catch (_) { /* leave as null -> fails below */ }
      assert(recorded === '1', `Case C: waiter ${waiterId} observed exactly one marker file on its own re-read (got: ${JSON.stringify(recorded)})`);
    }
  } finally {
    for (const p of waiterProcs) {
      try { p.kill('SIGKILL'); } catch (_) { /* already exited */ }
    }
  }
}

// ---------------------------------------------------------------------------
// Case D: empty lock directory (mkdir-before-owner race)
// ---------------------------------------------------------------------------
async function caseD() {
  const tmp = makeTmp('nfg-caseD-');
  const lockDir = lib.wrapLockPath(tmp);
  fs.mkdirSync(lockDir, { recursive: true }); // planted empty - no owner, no owner.json
  assert(fs.readdirSync(lockDir).length === 0, 'Case D precondition: planted lock dir is empty');

  const results = await Promise.all(
    Array.from({ length: N }, () => spawnAcquireChild([tmp, '--timeout-ms=3000', '--poll-ms=300']))
  );

  const exitCodes = results.map((r) => r.exitCode);
  assert(exitCodes.every((c) => c === 2), `Case D: all ${N} children exit 2 (got: ${JSON.stringify(exitCodes)})`);
  assert(!exitCodes.some((c) => c === 3), `Case D: zero exit 3 (got: ${JSON.stringify(exitCodes)})`);
  assert(results.every((r) => !/^acquired/m.test(r.stdout)), 'Case D: zero children ever print "acquired"');
  assert(fs.existsSync(lockDir), 'Case D: the lock dir survives (never cleared by a waiter)');
  assert(fs.readdirSync(lockDir).length === 0, 'Case D: the lock dir remains empty (byte-identical to what was planted)');
}

// ---------------------------------------------------------------------------
// Case E: source pin
// ---------------------------------------------------------------------------
async function caseE() {
  const src = fs.readFileSync(SCRIPT_PATH, 'utf8');
  assert(!/stale-needs-manual/.test(src), 'Case E: "stale-needs-manual" absent from the binary source');
  assert(!/process\.exit\(3\)/.test(src), 'Case E: no process.exit(3) occurrence');
  assert(!/process\.exit\(4\)/.test(src), 'Case E: no process.exit(4) occurrence');
  const exit0Matches = src.match(/process\.exit\(0\)/g) || [];
  assert(exit0Matches.length === 1, `Case E: exactly one process.exit(0) occurrence (got: ${exit0Matches.length})`);
  // CONSTRAINT (Minor 1): we deliberately do NOT attempt to prove that single
  // exit(0) is lexically inside the `acquired === true` guard via indentation-
  // sensitive string matching - that heuristic is brittle in both directions (it
  // can fail a correctly-reformatted implementation and pass an incorrectly
  // relocated one). The count above plus Case A's fully behavioral pin (a live
  // lock is never falsely acquired under real concurrency) are the real proof.
}

// ---------------------------------------------------------------------------
// Case F: prose -> producer -> predicate round trip
// ---------------------------------------------------------------------------
async function caseF() {
  const PREFLIGHT_CMD = 'agentic-wrap-acquire-lock "$cwd" --role=agent --no-wait';
  const md = fs.readFileSync(DS_WRAP_MD_PATH, 'utf8');

  // (1) the doc contains the literal preflight command.
  assert(md.includes(PREFLIGHT_CMD), 'Case F (1): content/commands/ds-wrap.md contains the literal preflight command');

  // (2) no hand-rolled mkdir AS AN INSTRUCTION. There is one legitimate historical
  // prose mention (the explanatory sentence noting what the helper replaces) - we
  // match on the IMPERATIVE form (a numbered step whose content IS the mkdir
  // command), not on mere occurrence of the path, and additionally require every
  // occurrence of the path to be embedded in the "old hand-rolled" explanatory
  // context. This passes the current (correct) file and would fail a regression
  // that reintroduced the hand-rolled mkdir as an actual instruction.
  const lines = md.split('\n');
  const handRolledPattern = /mkdir\s+(?:"?\$cwd"?|<cwd>)\/\.agentic\/wrap\/lock\b/;
  const matchingLines = lines.filter((l) => handRolledPattern.test(l));
  const imperativeInstruction = lines.some((l) => /^\s*\d+\.\s+`?mkdir\s+(?:"?\$cwd"?|<cwd>)\/\.agentic\/wrap\/lock\b/.test(l));
  assert(!imperativeInstruction, 'Case F (2): no numbered-step instruction whose content IS the hand-rolled mkdir');
  assert(matchingLines.length >= 1, 'Case F (2) precondition: the legitimate historical mention is present at all');
  assert(matchingLines.every((l) => /old hand-rolled/.test(l)),
    'Case F (2): every occurrence of the hand-rolled mkdir path is embedded in the "old hand-rolled" explanatory context, never standalone');

  // (3) run that SAME command's argv against a fresh temp dir; expect exit 0 and
  // a fully-formed live agent-role descriptor.
  const tmp = makeTmp('nfg-caseF-');
  // Tokenize the literal command (naive whitespace/quote split is sufficient -
  // the command has no nested quoting) and substitute $cwd for the fresh tmp dir.
  const tokens = PREFLIGHT_CMD.match(/"[^"]*"|\S+/g).map((t) => t.replace(/^"|"$/g, ''));
  const restArgs = tokens.slice(1).map((t) => (t === '$cwd' ? tmp : t));

  const first = runNode([SCRIPT_PATH, ...restArgs]);
  assert(first.exitCode === 0, `Case F (3): round-trip command exits 0 on a fresh dir (got: ${first.exitCode})`);

  const postO = lib.readWrapLockOwnerV2(tmp);
  assert(postO.source === 'json', `Case F (3): readWrapLockOwnerV2(tmp).source === 'json' (got: ${postO.source})`);
  const postV = lib.wrapLockVerdict(tmp);
  assert(postV.verdict === 'live', `Case F (3): wrapLockVerdict(tmp).verdict === 'live' (got: ${postV.verdict})`);
  assert(postO.role === 'agent', `Case F (3): role === 'agent' (got: ${postO.role})`);
  assert(postO.pid === null, `Case F (3): pid === null (got: ${postO.pid})`);

  // (4) a second invocation against the now-held dir exits 5 (busy) and does not
  // remove the lock.
  const second = runNode([SCRIPT_PATH, ...restArgs]);
  assert(second.exitCode === 5, `Case F (4): second invocation exits 5 (busy) (got: ${second.exitCode})`);
  assert(fs.existsSync(lib.wrapLockPath(tmp)), 'Case F (4): lock still present after the second (refused) invocation');

  try { lib.releaseWrapLock(tmp); } catch (_) { /* best-effort cleanup */ }
}

// ---------------------------------------------------------------------------
// Driver
// ---------------------------------------------------------------------------
(async () => {
  await runCase('A: THE CENTRAL REGRESSION TEST - 90-min live lock survives 10 concurrent waiters', caseA);
  await runCase('B: daemon arm - clearProvablyStaleWrapLock refuses a live 90-min lock', caseB);
  await runCase('C: 10-tab symptom repro - serialized handoff, no double-hold', caseC);
  await runCase('D: empty lock dir - 10 concurrent waiters never acquire, never clear it', caseD);
  await runCase('E: source pin - retired codes/branches structurally absent', caseE);
  await runCase('F: prose -> producer -> predicate round trip', caseF);

  for (const d of tmpDirs) {
    try { fs.rmSync(d, { recursive: true, force: true }); } catch (_) { /* best-effort cleanup */ }
  }

  console.log(`\n${passed} passed, ${failed} failed.`);
  process.exit(failed > 0 ? 1 : 0);
})();
