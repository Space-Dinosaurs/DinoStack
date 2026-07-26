#!/usr/bin/env node
'use strict';

/**
 * Unit tests for the wrapLockVerdict predicate and its supporting primitives
 * (readWrapLockOwnerV2, makeLockDescriptor) in hooks/lib/wrap-marker.js (U1).
 *
 * Covers:
 *   - Every predicate row (1-14) of the wrapLockVerdict decision table, as named
 *     cases.
 *   - The schema-rejection matrix: a JSON descriptor that parses but fails
 *     validation must never be trusted as source:'json'.
 *   - readGuardedFile boundaries (G1-G6): symlink/directory guards and the
 *     strict `>` (not `>=`) size cap, exercised indirectly via readWrapLockOwner
 *     and readWrapLockOwnerV2 (readGuardedFile itself is not exported).
 *   - Time-independence: the full fixture matrix run twice with Date.now()
 *     stubbed to 0 and to Number.MAX_SAFE_INTEGER must produce byte-identical
 *     decision fields (verdict/source/role/pid/ts - ageMs is excluded since it
 *     is deliberately clock-dependent, computed only after the verdict decision).
 *   - Fuzz: 5000 random owner bodies; every result must be a member of the
 *     four-value verdict enum and nothing may throw.
 *   - makeLockDescriptor round trip: a descriptor it produces always validates
 *     as source:'json'; it throws on an out-of-enum role or a non-positive-
 *     integer pid.
 *
 * Run with: node hooks/tests/test-wrap-lock-verdict.js
 * Argument-free invocation runs everything (auto-discovered by the
 * hooks/tests/test-*.js glob in .github/workflows/hooks-tests.yml).
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const lib = require('../lib/wrap-marker.js');

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

/** Create the lock dir (mkdir -p) for a fresh project dir; returns the lock path. */
function plantLockDir(projectDir) {
  const lockDir = lib.wrapLockPath(projectDir);
  fs.mkdirSync(lockDir, { recursive: true });
  return lockDir;
}

/** Write the legacy 2-line (or 1-line) owner body verbatim. */
function writeLegacyOwner(projectDir, body) {
  fs.writeFileSync(lib.wrapLockOwnerPath(projectDir), body, 'utf8');
}

/** Write raw (possibly invalid) bytes to lock/owner.json. */
function writeOwnerJsonRaw(projectDir, raw) {
  fs.writeFileSync(lib.wrapLockOwnerJsonPath(projectDir), raw, 'utf8');
}

/** A PID that is essentially guaranteed dead (very high, unlikely to be live). */
const DEAD_PID = 2147480000;

function isoAgo(seconds) {
  return new Date(Date.now() - seconds * 1000).toISOString();
}

function isoYearsAgo(years) {
  return new Date(Date.now() - years * 365.25 * 24 * 3600 * 1000).toISOString();
}

/** Build a valid-shape descriptor object (before JSON.stringify), with overrides. */
function baseDescriptor(overrides) {
  const d = {
    schema_version: 1,
    role: 'daemon',
    pid: 12345,
    host: os.hostname(),
    acquired_at: new Date().toISOString(),
    token: null,
  };
  return Object.assign(d, overrides || {});
}

/** Build a base descriptor with the given keys deleted entirely (absence tests). */
function baseDescriptorMissing(keys) {
  const d = baseDescriptor({});
  for (const k of keys) delete d[k];
  return d;
}

// ---------------------------------------------------------------------------
// Part A: wrapLockVerdict decision-table rows (1-14)
// ---------------------------------------------------------------------------
console.log('\n[Part A] wrapLockVerdict decision-table rows');

// Row 1: safeCwd(cwd) === null -> unknown (a non-absolute / non-normalized path).
{
  const v = lib.wrapLockVerdict('relative/not-absolute-path');
  assert(v.verdict === 'unknown', `row 1: safeCwd rejection -> unknown (got: ${v.verdict})`);
}

// Row 2: lstat(lock) throws (absent) -> free.
{
  const tmp = makeTmp('wlv-row2-');
  const v = lib.wrapLockVerdict(tmp);
  assert(v.verdict === 'free', `row 2: absent lock -> free (got: ${v.verdict})`);
}

// Row 3: lstat(lock).isSymbolicLink() -> unknown.
{
  const tmp = makeTmp('wlv-row3-');
  const target = makeTmp('wlv-row3-target-');
  const lockPath = lib.wrapLockPath(tmp);
  fs.mkdirSync(path.dirname(lockPath), { recursive: true });
  fs.symlinkSync(target, lockPath);
  const v = lib.wrapLockVerdict(tmp);
  assert(v.verdict === 'unknown', `row 3: symlink at lock path -> unknown (got: ${v.verdict})`);
}

// Row 4: !lstat(lock).isDirectory() -> unknown (a plain file at the lock path).
{
  const tmp = makeTmp('wlv-row4-');
  const lockPath = lib.wrapLockPath(tmp);
  fs.mkdirSync(path.dirname(lockPath), { recursive: true });
  fs.writeFileSync(lockPath, 'not a directory', 'utf8');
  const v = lib.wrapLockVerdict(tmp);
  assert(v.verdict === 'unknown', `row 4: plain file at lock path -> unknown (got: ${v.verdict})`);
}

// Row 5: source === null -> unknown (real lock dir, no owner file, no owner.json).
{
  const tmp = makeTmp('wlv-row5-');
  plantLockDir(tmp);
  const v = lib.wrapLockVerdict(tmp);
  assert(v.verdict === 'unknown', `row 5: no owner artifacts at all -> unknown (got: ${v.verdict})`);
  assert(v.source === null, `row 5: source is null (got: ${v.source})`);
}

// Row 6: legacy, pid!==null, ts!==null, tsMs(ts)!==null -> live, PID-BLIND.
// Uses a DEAD pid + a 31-minute-old (long past any staleness window) timestamp to
// prove liveness is never consulted for a 2-line interactive body.
{
  const tmp = makeTmp('wlv-row6-');
  plantLockDir(tmp);
  writeLegacyOwner(tmp, String(DEAD_PID) + '\n' + isoAgo(31 * 60) + '\n');
  const v = lib.wrapLockVerdict(tmp);
  assert(v.verdict === 'live', `row 6: 2-line dead-pid + 31-min ts -> live, pid-blind (got: ${v.verdict})`);
  assert(v.source === 'legacy', `row 6: source is legacy (got: ${v.source})`);
}

// Row 7: legacy, pid!==null, ts===null (1-line daemon body) -> pidIsDead(pid) ? dead : live.
{
  // (a) dead pid, 1-line body -> dead.
  const tmpDead = makeTmp('wlv-row7-dead-');
  plantLockDir(tmpDead);
  writeLegacyOwner(tmpDead, String(DEAD_PID));
  const vDead = lib.wrapLockVerdict(tmpDead);
  assert(vDead.verdict === 'dead', `row 7a: 1-line dead-pid body -> dead (got: ${vDead.verdict})`);

  // (b) alive pid (this test process), 1-line body -> live.
  const tmpAlive = makeTmp('wlv-row7-alive-');
  plantLockDir(tmpAlive);
  writeLegacyOwner(tmpAlive, String(process.pid));
  const vAlive = lib.wrapLockVerdict(tmpAlive);
  assert(vAlive.verdict === 'live', `row 7b: 1-line alive-pid body -> live (got: ${vAlive.verdict})`);
}

// Row 8: legacy, pid===null, ts!==null, tsMs(ts)!==null -> live.
{
  const tmp = makeTmp('wlv-row8-');
  plantLockDir(tmp);
  writeLegacyOwner(tmp, '\n' + isoAgo(60) + '\n'); // empty pid line, valid ts line
  const v = lib.wrapLockVerdict(tmp);
  assert(v.verdict === 'live', `row 8: no-pid + valid ts -> live (got: ${v.verdict})`);
}

// Row 9: legacy, ts non-null with tsMs(ts) === null (garbled) -> unknown.
{
  // (a) pid present, garbled ts.
  const tmpPid = makeTmp('wlv-row9-pid-');
  plantLockDir(tmpPid);
  writeLegacyOwner(tmpPid, '4711\nnot-a-date\n');
  const vPid = lib.wrapLockVerdict(tmpPid);
  assert(vPid.verdict === 'unknown', `row 9a: "4711\\nnot-a-date" -> unknown (got: ${vPid.verdict})`);

  // (b) no pid, garbled ts.
  const tmpNoPid = makeTmp('wlv-row9-nopid-');
  plantLockDir(tmpNoPid);
  writeLegacyOwner(tmpNoPid, '\nnot-a-date\n');
  const vNoPid = lib.wrapLockVerdict(tmpNoPid);
  assert(vNoPid.verdict === 'unknown', `row 9b: "\\nnot-a-date" (no pid) -> unknown (got: ${vNoPid.verdict})`);
}

// Row 10: json, role==='agent' -> live, UNCONDITIONALLY, even with a ten-year-old
// acquired_at. There is deliberately no TTL and no expiry for an agent-role lock.
{
  const tmp = makeTmp('wlv-row10-');
  plantLockDir(tmp);
  const d = lib.makeLockDescriptor({ role: 'agent', pid: null, acquiredAt: isoYearsAgo(10) });
  writeOwnerJsonRaw(tmp, JSON.stringify(d));
  const v = lib.wrapLockVerdict(tmp);
  assert(v.verdict === 'live', `row 10: role:'agent' with a ten-year-old acquired_at -> live (got: ${v.verdict})`);
  assert(v.source === 'json', `row 10: source is json (got: ${v.source})`);
}

// Row 11: json, role in {daemon,commit}, host !== os.hostname() -> unknown.
{
  for (const role of ['daemon', 'commit']) {
    const tmp = makeTmp('wlv-row11-' + role + '-');
    plantLockDir(tmp);
    const d = lib.makeLockDescriptor({ role, pid: process.pid });
    d.host = 'some-other-host-' + role;
    writeOwnerJsonRaw(tmp, JSON.stringify(d));
    const v = lib.wrapLockVerdict(tmp);
    assert(v.verdict === 'unknown', `row 11 (${role}): host mismatch -> unknown (got: ${v.verdict})`);
  }
}

// Row 12: json, role in {daemon,commit}, host matches, pid === null -> unknown.
{
  for (const role of ['daemon', 'commit']) {
    const tmp = makeTmp('wlv-row12-' + role + '-');
    plantLockDir(tmp);
    const d = lib.makeLockDescriptor({ role, pid: null });
    writeOwnerJsonRaw(tmp, JSON.stringify(d));
    const v = lib.wrapLockVerdict(tmp);
    assert(v.verdict === 'unknown', `row 12 (${role}): host matches, pid null -> unknown (got: ${v.verdict})`);
  }
}

// Row 13: json, role in {daemon,commit}, host matches, pidIsDead(pid) -> dead.
{
  for (const role of ['daemon', 'commit']) {
    const tmp = makeTmp('wlv-row13-' + role + '-');
    plantLockDir(tmp);
    const d = lib.makeLockDescriptor({ role, pid: DEAD_PID });
    writeOwnerJsonRaw(tmp, JSON.stringify(d));
    const v = lib.wrapLockVerdict(tmp);
    assert(v.verdict === 'dead', `row 13 (${role}): host matches, dead pid -> dead (got: ${v.verdict})`);
  }
}

// Row 14: otherwise (json, process role, host match, live pid) -> live.
{
  for (const role of ['daemon', 'commit']) {
    const tmp = makeTmp('wlv-row14-' + role + '-');
    plantLockDir(tmp);
    const d = lib.makeLockDescriptor({ role, pid: process.pid });
    writeOwnerJsonRaw(tmp, JSON.stringify(d));
    const v = lib.wrapLockVerdict(tmp);
    assert(v.verdict === 'live', `row 14 (${role}): host matches, live pid -> live (got: ${v.verdict})`);
  }
}

// ---------------------------------------------------------------------------
// Part B: schema-rejection matrix - each must fall back to legacy or unknown,
// NEVER 'json'. No legacy owner file is planted alongside, so the expected
// fallback here is source:null -> wrapLockVerdict 'unknown'.
// ---------------------------------------------------------------------------
console.log('\n[Part B] schema-rejection matrix (readWrapLockOwnerV2 must never trust these as json)');

function expectSchemaRejected(label, rawContent) {
  const tmp = makeTmp('wlv-schema-');
  plantLockDir(tmp);
  writeOwnerJsonRaw(tmp, rawContent);
  const o = lib.readWrapLockOwnerV2(tmp);
  assert(o.source !== 'json', `schema-rejection [${label}]: readWrapLockOwnerV2 source is NOT 'json' (got: ${o.source})`);
  const v = lib.wrapLockVerdict(tmp);
  assert(v.verdict === 'unknown', `schema-rejection [${label}]: wrapLockVerdict is 'unknown' (no legacy fallback present) (got: ${v.verdict})`);
}

expectSchemaRejected('schema_version:2', JSON.stringify(baseDescriptor({ schema_version: 2 })));
expectSchemaRejected('role:"bogus"', JSON.stringify(baseDescriptor({ role: 'bogus' })));
expectSchemaRejected('acquired_at:"garbage"', JSON.stringify(baseDescriptor({ acquired_at: 'garbage' })));
expectSchemaRejected('acquired_at absent', JSON.stringify(baseDescriptorMissing(['acquired_at'])));
expectSchemaRejected('host absent', JSON.stringify(baseDescriptorMissing(['host'])));
expectSchemaRejected('host:""', JSON.stringify(baseDescriptor({ host: '' })));
expectSchemaRejected('token:""', JSON.stringify(baseDescriptor({ token: '' })));
expectSchemaRejected('pid:-1', JSON.stringify(baseDescriptor({ pid: -1 })));
expectSchemaRejected('non-JSON bytes', 'this is not json at all {{{');
expectSchemaRejected('JSON array', JSON.stringify([1, 2, 3]));

// ---------------------------------------------------------------------------
// Part C: readGuardedFile boundaries (G1-G6), exercised indirectly via
// readWrapLockOwner (legacy path) and readWrapLockOwnerV2 (JSON path).
// ---------------------------------------------------------------------------
console.log('\n[Part C] readGuardedFile boundaries (G1-G6)');

// G1: lock/owner is a symlink -> {pid:null, ts:null}.
{
  const tmp = makeTmp('wlv-g1-');
  const target = makeTmp('wlv-g1-target-');
  fs.writeFileSync(path.join(target, 'evil-owner'), '99999\n' + new Date().toISOString(), 'utf8');
  plantLockDir(tmp);
  fs.symlinkSync(path.join(target, 'evil-owner'), lib.wrapLockOwnerPath(tmp));
  const o = lib.readWrapLockOwner(tmp);
  assert(o.pid === null && o.ts === null, `G1: lock/owner symlink -> {pid:null,ts:null} (got: ${JSON.stringify(o)})`);
}

// G2: lock/owner is a directory -> {pid:null, ts:null}.
{
  const tmp = makeTmp('wlv-g2-');
  plantLockDir(tmp);
  fs.mkdirSync(lib.wrapLockOwnerPath(tmp), { recursive: true });
  const o = lib.readWrapLockOwner(tmp);
  assert(o.pid === null && o.ts === null, `G2: lock/owner directory -> {pid:null,ts:null} (got: ${JSON.stringify(o)})`);
}

// G3: lock/owner exactly 4096 bytes with a valid pid on line 0 -> READ (pins
// strict `>` rather than `>=`).
{
  const tmp = makeTmp('wlv-g3-');
  plantLockDir(tmp);
  const head = '12345\n';
  const filler = 'a'.repeat(4096 - head.length);
  const content = head + filler;
  assert(Buffer.byteLength(content, 'utf8') === 4096, `G3 precondition: fixture is exactly 4096 bytes (got: ${Buffer.byteLength(content, 'utf8')})`);
  writeLegacyOwner(tmp, content);
  const o = lib.readWrapLockOwner(tmp);
  assert(o.pid === 12345, `G3: exactly-4096-byte owner file IS read (pid extracted) (got pid: ${o.pid})`);
}

// G4: 4097 bytes -> rejected.
{
  const tmp = makeTmp('wlv-g4-');
  plantLockDir(tmp);
  const head = '12345\n';
  const filler = 'a'.repeat(4097 - head.length);
  const content = head + filler;
  assert(Buffer.byteLength(content, 'utf8') === 4097, `G4 precondition: fixture is exactly 4097 bytes (got: ${Buffer.byteLength(content, 'utf8')})`);
  writeLegacyOwner(tmp, content);
  const o = lib.readWrapLockOwner(tmp);
  assert(o.pid === null && o.ts === null, `G4: 4097-byte owner file is REJECTED (got: ${JSON.stringify(o)})`);
}

// G5: lock/owner.json a symlink or directory -> source !== 'json'.
{
  // (a) symlink
  const tmpSym = makeTmp('wlv-g5-sym-');
  const target = makeTmp('wlv-g5-target-');
  const validJson = JSON.stringify(baseDescriptor({}));
  fs.writeFileSync(path.join(target, 'evil-owner.json'), validJson, 'utf8');
  plantLockDir(tmpSym);
  fs.symlinkSync(path.join(target, 'evil-owner.json'), lib.wrapLockOwnerJsonPath(tmpSym));
  const oSym = lib.readWrapLockOwnerV2(tmpSym);
  assert(oSym.source !== 'json', `G5a: lock/owner.json symlink -> source is not 'json' (got: ${oSym.source})`);

  // (b) directory
  const tmpDir = makeTmp('wlv-g5-dir-');
  plantLockDir(tmpDir);
  fs.mkdirSync(lib.wrapLockOwnerJsonPath(tmpDir), { recursive: true });
  const oDir = lib.readWrapLockOwnerV2(tmpDir);
  assert(oDir.source !== 'json', `G5b: lock/owner.json directory -> source is not 'json' (got: ${oDir.source})`);
}

// G6: lock/owner.json 4097 bytes of otherwise-valid JSON -> source !== 'json'.
{
  const tmp = makeTmp('wlv-g6-');
  plantLockDir(tmp);
  const base = baseDescriptor({ pad: '' });
  const baseLen = Buffer.byteLength(JSON.stringify(base), 'utf8');
  const deficit = 4097 - baseLen;
  assert(deficit >= 0, 'G6 precondition: base descriptor fits under 4097 bytes with room to pad');
  base.pad = 'a'.repeat(deficit);
  const content = JSON.stringify(base);
  assert(Buffer.byteLength(content, 'utf8') === 4097, `G6 precondition: fixture is exactly 4097 bytes (got: ${Buffer.byteLength(content, 'utf8')})`);
  writeOwnerJsonRaw(tmp, content);
  const o = lib.readWrapLockOwnerV2(tmp);
  assert(o.source !== 'json', `G6: 4097-byte owner.json (otherwise valid) is REJECTED (got: ${o.source})`);
}

// ---------------------------------------------------------------------------
// Part D: time-independence - run the entire fixture matrix twice with
// Date.now() stubbed to 0 and to Number.MAX_SAFE_INTEGER; require byte-
// identical decision fields (verdict/source/role/pid/ts). ageMs is EXCLUDED
// from the comparison - it is deliberately clock-dependent (computed only
// after the verdict is already decided, purely for log messages) and is
// EXPECTED to differ between the two clock stubs. This mechanically proves
// the no-arithmetic-comparison rule: if any branch compared against
// Date.now(), the decision fields (not just ageMs) would flip between the
// two extreme clock values.
// ---------------------------------------------------------------------------
console.log('\n[Part D] time-independence (Date.now() stubbed to 0 and to MAX_SAFE_INTEGER)');

function buildTimeIndependenceFixtures() {
  const fixtures = [];

  // free
  fixtures.push(makeTmp('wlv-ti-free-'));

  // legacy 2-line (pid-blind live)
  {
    const d = makeTmp('wlv-ti-legacy2-');
    plantLockDir(d);
    writeLegacyOwner(d, String(DEAD_PID) + '\n' + isoAgo(31 * 60) + '\n');
    fixtures.push(d);
  }

  // legacy 1-line dead
  {
    const d = makeTmp('wlv-ti-legacy1dead-');
    plantLockDir(d);
    writeLegacyOwner(d, String(DEAD_PID));
    fixtures.push(d);
  }

  // legacy 1-line alive
  {
    const d = makeTmp('wlv-ti-legacy1alive-');
    plantLockDir(d);
    writeLegacyOwner(d, String(process.pid));
    fixtures.push(d);
  }

  // legacy garbled ts
  {
    const d = makeTmp('wlv-ti-garbled-');
    plantLockDir(d);
    writeLegacyOwner(d, '4711\nnot-a-date\n');
    fixtures.push(d);
  }

  // json role:agent, ten-year-old acquired_at
  {
    const d = makeTmp('wlv-ti-agent-');
    plantLockDir(d);
    const desc = lib.makeLockDescriptor({ role: 'agent', pid: null, acquiredAt: isoYearsAgo(10) });
    writeOwnerJsonRaw(d, JSON.stringify(desc));
    fixtures.push(d);
  }

  // json role:daemon, dead pid
  {
    const d = makeTmp('wlv-ti-daemondead-');
    plantLockDir(d);
    const desc = lib.makeLockDescriptor({ role: 'daemon', pid: DEAD_PID });
    writeOwnerJsonRaw(d, JSON.stringify(desc));
    fixtures.push(d);
  }

  // json role:commit, alive pid
  {
    const d = makeTmp('wlv-ti-commitalive-');
    plantLockDir(d);
    const desc = lib.makeLockDescriptor({ role: 'commit', pid: process.pid });
    writeOwnerJsonRaw(d, JSON.stringify(desc));
    fixtures.push(d);
  }

  // unknown: symlink at lock path
  {
    const d = makeTmp('wlv-ti-symlink-');
    const target = makeTmp('wlv-ti-symlink-target-');
    const lockPath = lib.wrapLockPath(d);
    fs.mkdirSync(path.dirname(lockPath), { recursive: true });
    fs.symlinkSync(target, lockPath);
    fixtures.push(d);
  }

  return fixtures;
}

{
  const fixtures = buildTimeIndependenceFixtures();
  const originalNow = Date.now;

  Date.now = () => 0;
  const resultsAtZero = fixtures.map((dir) => lib.wrapLockVerdict(dir));

  Date.now = () => Number.MAX_SAFE_INTEGER;
  const resultsAtMax = fixtures.map((dir) => lib.wrapLockVerdict(dir));

  Date.now = originalNow;

  const stripAgeMs = (r) => ({ verdict: r.verdict, source: r.source, role: r.role, pid: r.pid, ts: r.ts });
  let allMatch = true;
  for (let i = 0; i < fixtures.length; i++) {
    const a = JSON.stringify(stripAgeMs(resultsAtZero[i]));
    const b = JSON.stringify(stripAgeMs(resultsAtMax[i]));
    if (a !== b) {
      allMatch = false;
      console.error(`  MISMATCH at fixture ${i} (${fixtures[i]}): Date.now()=0 -> ${a} vs Date.now()=MAX -> ${b}`);
    }
  }
  assert(allMatch, `time-independence: all ${fixtures.length} fixtures produce byte-identical decision fields regardless of Date.now() stub`);
}

// ---------------------------------------------------------------------------
// Part E: fuzz - 5000 randomly generated owner bodies (random bytes, line
// counts, JSON fragments). Every result must be a member of the four-value
// enum and nothing may throw.
// ---------------------------------------------------------------------------
console.log('\n[Part E] fuzz (5000 random owner bodies)');

const VALID_VERDICTS = new Set(['free', 'live', 'dead', 'unknown']);

function randomBytes(maxLen) {
  const len = Math.floor(Math.random() * maxLen);
  const chars = [];
  for (let i = 0; i < len; i++) {
    // Mix of printable ASCII, newlines, and the occasional null/control byte.
    const roll = Math.random();
    if (roll < 0.1) {
      chars.push('\n');
    } else if (roll < 0.15) {
      chars.push(String.fromCharCode(Math.floor(Math.random() * 32))); // control bytes
    } else {
      chars.push(String.fromCharCode(32 + Math.floor(Math.random() * 95))); // printable ASCII
    }
  }
  return chars.join('');
}

function randomJsonFragment() {
  const variants = [
    () => JSON.stringify(baseDescriptor({})),
    () => JSON.stringify(baseDescriptor({ role: 'agent', pid: null })),
    () => JSON.stringify(baseDescriptor({ pid: Math.floor(Math.random() * 100000) - 50000 })),
    () => JSON.stringify(baseDescriptor({ schema_version: Math.floor(Math.random() * 5) })),
    () => JSON.stringify({ random: Math.random(), nested: { a: [1, 2, 3] } }),
    () => JSON.stringify([1, 2, 3]),
    () => '{"unterminated": ',
    () => 'null',
    () => 'true',
    () => '42',
  ];
  return variants[Math.floor(Math.random() * variants.length)]();
}

{
  let fuzzThrew = false;
  let fuzzAllValid = true;
  const FUZZ_COUNT = 5000;
  for (let i = 0; i < FUZZ_COUNT; i++) {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wlv-fuzz-'));
    tmpDirs.push(tmp);
    try {
      const hasLock = Math.random() < 0.9;
      if (hasLock) {
        plantLockDir(tmp);
        const which = Math.random();
        if (which < 0.5) {
          // legacy owner file: random bytes
          writeLegacyOwner(tmp, randomBytes(300));
        } else if (which < 0.9) {
          // owner.json: random JSON-ish fragment
          writeOwnerJsonRaw(tmp, randomJsonFragment());
        } else {
          // both present simultaneously
          writeLegacyOwner(tmp, randomBytes(150));
          writeOwnerJsonRaw(tmp, randomJsonFragment());
        }
      }
      // else: lock dir absent entirely (free case) on ~10% of iterations.

      const v = lib.wrapLockVerdict(tmp);
      if (!VALID_VERDICTS.has(v.verdict)) {
        fuzzAllValid = false;
        console.error(`  fuzz iteration ${i}: invalid verdict "${v.verdict}"`);
      }
    } catch (e) {
      fuzzThrew = true;
      console.error(`  fuzz iteration ${i} THREW: ${e && e.message}`);
    }
  }
  assert(!fuzzThrew, `fuzz: wrapLockVerdict never threw across ${FUZZ_COUNT} random fixtures`);
  assert(fuzzAllValid, `fuzz: every result was a member of {free,live,dead,unknown} across ${FUZZ_COUNT} random fixtures`);
}

// ---------------------------------------------------------------------------
// Part F: makeLockDescriptor round trip.
// ---------------------------------------------------------------------------
console.log('\n[Part F] makeLockDescriptor round trip');

{
  for (const role of ['agent', 'daemon', 'commit']) {
    const tmp = makeTmp('wlv-roundtrip-' + role + '-');
    plantLockDir(tmp);
    const d = lib.makeLockDescriptor({ role, pid: role === 'agent' ? null : process.pid, token: 'tok-' + role });
    writeOwnerJsonRaw(tmp, JSON.stringify(d));
    const o = lib.readWrapLockOwnerV2(tmp);
    assert(o.source === 'json', `round trip (${role}): a produced descriptor always validates as source:'json' (got: ${o.source})`);
    assert(o.token === 'tok-' + role, `round trip (${role}): token round-trips correctly (got: ${o.token})`);
  }
}

{
  let threwOnRole = false;
  try {
    lib.makeLockDescriptor({ role: 'not-a-real-role' });
  } catch (e) {
    threwOnRole = (e instanceof TypeError);
  }
  assert(threwOnRole, 'makeLockDescriptor throws a TypeError on an out-of-enum role');
}

{
  let threwOnPidNegative = false;
  try {
    lib.makeLockDescriptor({ role: 'daemon', pid: -5 });
  } catch (e) {
    threwOnPidNegative = (e instanceof TypeError);
  }
  assert(threwOnPidNegative, 'makeLockDescriptor throws a TypeError on a negative pid');
}

{
  let threwOnPidZero = false;
  try {
    lib.makeLockDescriptor({ role: 'daemon', pid: 0 });
  } catch (e) {
    threwOnPidZero = (e instanceof TypeError);
  }
  assert(threwOnPidZero, 'makeLockDescriptor throws a TypeError on pid:0 (non-positive)');
}

{
  let threwOnPidFloat = false;
  try {
    lib.makeLockDescriptor({ role: 'daemon', pid: 1.5 });
  } catch (e) {
    threwOnPidFloat = (e instanceof TypeError);
  }
  assert(threwOnPidFloat, 'makeLockDescriptor throws a TypeError on a non-integer pid');
}

{
  let threwOnEmptyToken = false;
  try {
    lib.makeLockDescriptor({ role: 'daemon', pid: process.pid, token: '' });
  } catch (e) {
    threwOnEmptyToken = (e instanceof TypeError);
  }
  assert(threwOnEmptyToken, 'makeLockDescriptor throws a TypeError on an empty-string token');
}

{
  let threwOnNumericToken = false;
  try {
    lib.makeLockDescriptor({ role: 'daemon', pid: process.pid, token: 123 });
  } catch (e) {
    threwOnNumericToken = (e instanceof TypeError);
  }
  assert(threwOnNumericToken, 'makeLockDescriptor throws a TypeError on a non-string (numeric) token');
}

{
  let d = null;
  let threw = false;
  try {
    d = lib.makeLockDescriptor({ role: 'daemon', pid: process.pid, token: null });
  } catch (e) {
    threw = true;
  }
  assert(!threw && d && d.token === null, 'makeLockDescriptor accepts token:null');
}

{
  const uuid = '123e4567-e89b-12d3-a456-426614174000';
  let d = null;
  let threw = false;
  try {
    d = lib.makeLockDescriptor({ role: 'daemon', pid: process.pid, token: uuid });
  } catch (e) {
    threw = true;
  }
  assert(!threw && d && d.token === uuid, 'makeLockDescriptor accepts a valid uuid token');
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------
for (const d of tmpDirs) {
  try { fs.rmSync(d, { recursive: true, force: true }); } catch (_) { /* best-effort */ }
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
