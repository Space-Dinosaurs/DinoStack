#!/usr/bin/env node
/**
 * Regression tests: stop-context.js 6-tier getIdentity resolution
 * (project > profile > global, confirmed pass before provisional pass)
 * plus profile-config-dir containment (realpath/symlink rejection) and
 * the pending-buffer config_dir tag (cross-tenant flush partition).
 *
 * Sub-tests (mirror the Python J-suite in bin/tests/test_agentic_identity.py):
 *   J1  profile-confirmed beats global-confirmed
 *   J2  project-confirmed beats profile-confirmed
 *   J3  provisional profile does NOT beat confirmed global
 *   J4  provisional profile used when nothing confirmed (pending buffer)
 *       + pending record carries config_dir (Fix-2 regression)
 *   J5  env precedence AGENTIC_CONFIG_DIR > CLAUDE_CONFIG_DIR > CODEX_HOME
 *       > PI_CODING_AGENT_DIR,
 *       plus CODEX_HOME-alone fallback
 *   FALLTHROUGH unsafe higher-precedence profile dir is rejected before
 *       selection so a safe lower-precedence profile can win
 *   J6  outside-$HOME env dir rejected -> global identity used
 *   J7  n/a (--profile-dir is CLI-only; no hook surface) - intentionally skipped
 *   J8  no env vars -> 4-tier back-compat (global identity used)
 *   ENOENT nonexistent highest-precedence env dir STOPS the scan (no
 *       fall-through to a lower-precedence existing profile), matching
 *       Python _profile_config_dir (Path.resolve() needs no existence)
 *   SYM symlink inside $HOME pointing outside must NOT be followed
 *       (Fix-1 regression proof; fails on the pre-fix lexical check)
 *   INVALID canonical-handle validation before session-log path construction
 *   FINAL global/project/profile final-target symlink and non-regular rejection
 *   READ invalid UTF-8 and unreadable identity files fail closed
 *   SNAPSHOT normal deployed layout includes the executable identity helper
 *   TELEMETRY hostile output targets, unpredictable pending publication, and
 *       concurrent descriptor-safe append
 *
 * The hook script path can be overridden via AE_TEST_HOOK_PATH so the SYM
 * case can be executed against a historical copy of stop-context.js to prove
 * the regression (see PR #442 review).
 *
 * Run with: node hooks/tests/test-stop-context-identity.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');

// ---------------------------------------------------------------------------
// Shared helpers (modeled on test-stop-context-session-log.js)
// ---------------------------------------------------------------------------

const hookScript = process.env.AE_TEST_HOOK_PATH
  ? path.resolve(process.env.AE_TEST_HOOK_PATH)
  : path.resolve(__dirname, '..', 'stop-context.js');
if (!fs.existsSync(hookScript)) {
  console.error(`FAIL: hook not found at ${hookScript}`);
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

const PROFILE_ENV_VARS = [
  'AGENTIC_CONFIG_DIR',
  'CLAUDE_CONFIG_DIR',
  'CODEX_HOME',
  'PI_CODING_AGENT_DIR',
];

/**
 * Build a child env: copy parent env, DELETE all profile config-dir vars so
 * the parent shell can never leak a profile into a scenario, then apply the
 * scenario's own vars.
 */
function buildEnv(fakeHome, extraVars) {
  const env = { ...process.env, HOME: fakeHome };
  for (const v of PROFILE_ENV_VARS) delete env[v];
  return Object.assign(env, extraVars || {});
}

function runHook(projectDir, fakeHome, sessionId, extraVars) {
  return runHookAt(hookScript, projectDir, fakeHome, sessionId, extraVars);
}

function runHookAt(script, projectDir, fakeHome, sessionId, extraVars) {
  const payload = JSON.stringify({
    cwd: projectDir,
    session_id: sessionId,
    transcript: [],
  });
  execFileSync(process.execPath, [script], {
    input: payload,
    encoding: 'utf8',
    env: buildEnv(fakeHome, extraVars),
    timeout: 10000,
    stdio: ['pipe', 'pipe', 'ignore'],
  });
}

// realpathSync: macOS mkdtemp returns /var/... which is a symlink to
// /private/var - the hook realpaths $HOME, so the fixture must too.
function makeTmp(prefix) {
  const tmpDir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  const fakeHome = path.join(tmpDir, 'home');
  const projectDir = path.join(tmpDir, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  const globalIdentityDir = path.join(fakeHome, '.agentic');
  fs.mkdirSync(fakeHome, { recursive: true });
  fs.mkdirSync(projectDir, { recursive: true });
  fs.mkdirSync(agenticDir, { recursive: true });
  fs.mkdirSync(globalIdentityDir, { recursive: true });
  return { tmpDir, fakeHome, projectDir, agenticDir, globalIdentityDir };
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
}

function writeIdentity(dir, devId, provisional) {
  fs.mkdirSync(dir, { recursive: true });
  let content = `developer_id: ${devId}\ncreated_at: 2026-01-01T00:00:00Z\n`;
  if (provisional) content += 'provisional: true\n';
  fs.writeFileSync(path.join(dir, 'identity.yml'), content, { mode: 0o600 });
}

function sessionLogFor(baseDir, devId) {
  return path.join(baseDir, '.agentic', 'session-log', `${devId}.jsonl`);
}

function pendingFiles(fakeHome) {
  const dir = path.join(fakeHome, '.agentic', 'session-log', '.pending');
  try {
    return fs.readdirSync(dir).filter((f) => f.endsWith('.json'))
      .map((f) => path.join(dir, f));
  } catch (_) {
    return [];
  }
}

function writeRawIdentity(target, content) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content, { mode: 0o600 });
}

// ---------------------------------------------------------------------------
// J1: profile-confirmed beats global-confirmed
// ---------------------------------------------------------------------------
console.log('\n[J1] profile-confirmed beats global-confirmed');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp('ae-id-j1-');
  const profDir = path.join(fakeHome, '.claude-tenant');
  writeIdentity(globalIdentityDir, 'global-dev', false);
  writeIdentity(profDir, 'profile-dev', false);

  runHook(projectDir, fakeHome, 'j1-uuid', { AGENTIC_CONFIG_DIR: profDir });

  assert(fs.existsSync(sessionLogFor(projectDir, 'profile-dev')),
    'per-project session log written for profile-dev');
  assert(fs.existsSync(sessionLogFor(fakeHome, 'profile-dev')),
    'global mirror written for profile-dev');
  assert(!fs.existsSync(sessionLogFor(projectDir, 'global-dev')),
    'no session log for global-dev (profile won)');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// J2: project-confirmed beats profile-confirmed
// ---------------------------------------------------------------------------
console.log('\n[J2] project-confirmed beats profile-confirmed');
{
  const { tmpDir, fakeHome, projectDir, agenticDir } = makeTmp('ae-id-j2-');
  const profDir = path.join(fakeHome, '.claude-tenant');
  writeIdentity(agenticDir, 'project-dev', false);
  writeIdentity(profDir, 'profile-dev', false);

  runHook(projectDir, fakeHome, 'j2-uuid', { AGENTIC_CONFIG_DIR: profDir });

  assert(fs.existsSync(sessionLogFor(projectDir, 'project-dev')),
    'session log written for project-dev (most specific scope wins)');
  assert(!fs.existsSync(sessionLogFor(projectDir, 'profile-dev')),
    'no session log for profile-dev');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// J3: provisional profile does NOT beat confirmed global
// ---------------------------------------------------------------------------
console.log('\n[J3] provisional profile does NOT suppress confirmed global');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp('ae-id-j3-');
  const profDir = path.join(fakeHome, '.claude-tenant');
  writeIdentity(globalIdentityDir, 'global-dev', false);
  writeIdentity(profDir, 'profile-dev', true); // provisional

  runHook(projectDir, fakeHome, 'j3-uuid', { AGENTIC_CONFIG_DIR: profDir });

  assert(fs.existsSync(sessionLogFor(projectDir, 'global-dev')),
    'confirmed global identity used (direct write)');
  assert(!fs.existsSync(sessionLogFor(projectDir, 'profile-dev')),
    'provisional profile identity NOT used for direct write');
  assert(pendingFiles(fakeHome).length === 0,
    'no pending buffer record (confirmed identity available)');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// J4: provisional profile when nothing confirmed -> pending buffer
//     + pending record carries config_dir (Fix-2 regression)
// ---------------------------------------------------------------------------
console.log('\n[J4] provisional profile only -> pending buffer with config_dir tag');
{
  const { tmpDir, fakeHome, projectDir } = makeTmp('ae-id-j4-');
  const profDir = path.join(fakeHome, '.claude-tenant');
  writeIdentity(profDir, 'profile-dev', true); // provisional, nothing else exists

  runHook(projectDir, fakeHome, 'j4-uuid', { AGENTIC_CONFIG_DIR: profDir });

  const pend = pendingFiles(fakeHome);
  assert(pend.length === 1, `exactly one pending record written (got ${pend.length})`);
  assert(!fs.existsSync(sessionLogFor(projectDir, 'profile-dev')),
    'provisional identity gets no direct session-log write');
  if (pend.length === 1) {
    const rec = JSON.parse(fs.readFileSync(pend[0], 'utf8'));
    assert(rec.session_uuid === 'j4-uuid', 'pending record session_uuid matches');
    assert(rec.config_dir === profDir,
      `pending record tagged with config_dir === active profile dir (got: ${rec.config_dir})`);
    assert(rec.identity_scope === 'profile',
      `pending record tagged with winning identity_scope=profile (got: ${rec.identity_scope})`);
    assert(rec.schema_version === 1, 'schema_version stays 1 (additive field)');
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// WINNING SCOPE: active profile must not retag a global provisional winner.
// ---------------------------------------------------------------------------
console.log('\n[WINNING] global provisional winner keeps global scope tag');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp('ae-id-winning-');
  const profDir = path.join(fakeHome, '.claude-tenant');
  fs.mkdirSync(profDir);
  writeIdentity(globalIdentityDir, 'global-winner', true);

  runHook(projectDir, fakeHome, 'winning-global', { AGENTIC_CONFIG_DIR: profDir });

  const pend = pendingFiles(fakeHome);
  assert(pend.length === 1, 'global provisional winner produced one pending record');
  if (pend.length === 1) {
    const rec = JSON.parse(fs.readFileSync(pend[0], 'utf8'));
    assert(rec.identity_scope === 'global',
      `pending record tagged with winning identity_scope=global (got: ${rec.identity_scope})`);
    assert(!Object.prototype.hasOwnProperty.call(rec, 'config_dir'),
      'global-scope record has no active-profile config_dir routing tag');
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// J5: env precedence AGENTIC > CLAUDE > CODEX > PI; Pi alone works
// ---------------------------------------------------------------------------
console.log('\n[J5] profile env precedence includes PI_CODING_AGENT_DIR');
{
  const { tmpDir, fakeHome, projectDir } = makeTmp('ae-id-j5-');
  const dirA = path.join(fakeHome, '.prof-a');
  const dirB = path.join(fakeHome, '.prof-b');
  const dirC = path.join(fakeHome, '.prof-c');
  const dirD = path.join(fakeHome, '.prof-d');
  writeIdentity(dirA, 'a-dev', false);
  writeIdentity(dirB, 'b-dev', false);
  writeIdentity(dirC, 'c-dev', false);
  writeIdentity(dirD, 'd-dev', false);

  // All four set -> AGENTIC wins.
  runHook(projectDir, fakeHome, 'j5-uuid-1', {
    AGENTIC_CONFIG_DIR: dirA, CLAUDE_CONFIG_DIR: dirB, CODEX_HOME: dirC,
    PI_CODING_AGENT_DIR: dirD,
  });
  assert(fs.existsSync(sessionLogFor(projectDir, 'a-dev')),
    'AGENTIC_CONFIG_DIR wins when all three set');

  // CLAUDE + CODEX -> CLAUDE wins.
  runHook(projectDir, fakeHome, 'j5-uuid-2', {
    CLAUDE_CONFIG_DIR: dirB, CODEX_HOME: dirC,
  });
  assert(fs.existsSync(sessionLogFor(projectDir, 'b-dev')),
    'CLAUDE_CONFIG_DIR wins over CODEX_HOME');

  // CODEX alone -> used.
  runHook(projectDir, fakeHome, 'j5-uuid-3', { CODEX_HOME: dirC });
  assert(fs.existsSync(sessionLogFor(projectDir, 'c-dev')),
    'CODEX_HOME alone selects the profile');

  // Pi's documented native binding is the final supported fallback.
  runHook(projectDir, fakeHome, 'j5-uuid-4', { PI_CODING_AGENT_DIR: dirD });
  assert(fs.existsSync(sessionLogFor(projectDir, 'd-dev')),
    'PI_CODING_AGENT_DIR alone selects the profile');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// FALLTHROUGH: reject an unsafe high candidate before selecting the profile.
// ---------------------------------------------------------------------------
console.log('\n[FALLTHROUGH] unsafe AGENTIC_CONFIG_DIR yields to safe CLAUDE_CONFIG_DIR');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } =
    makeTmp('ae-id-fallthrough-');
  const badTarget = path.join(fakeHome, 'bad-profile-target');
  const badProfile = path.join(fakeHome, 'bad-profile');
  const realProfile = path.join(fakeHome, 'real-profile');
  fs.mkdirSync(badTarget);
  fs.symlinkSync(badTarget, badProfile);
  writeIdentity(realProfile, 'lower-confirmed', false);
  writeIdentity(globalIdentityDir, 'global-prov', true);

  runHook(projectDir, fakeHome, 'fallthrough-uuid', {
    AGENTIC_CONFIG_DIR: badProfile,
    CLAUDE_CONFIG_DIR: realProfile,
  });

  assert(fs.existsSync(sessionLogFor(projectDir, 'lower-confirmed')),
    'safe lower-precedence profile receives direct telemetry');
  assert(!fs.existsSync(sessionLogFor(projectDir, 'global-prov')),
    'global provisional identity does not win over safe lower profile');
  assert(pendingFiles(fakeHome).length === 0,
    'no pending global-scope record is created');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// J6: env dir outside $HOME rejected -> falls back to global
// ---------------------------------------------------------------------------
console.log('\n[J6] outside-$HOME env dir rejected');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp('ae-id-j6-');
  const outsideDir = path.join(tmpDir, 'outside-home'); // sibling of fakeHome
  writeIdentity(globalIdentityDir, 'global-dev', false);
  writeIdentity(outsideDir, 'intruder-dev', false);

  runHook(projectDir, fakeHome, 'j6-uuid', { AGENTIC_CONFIG_DIR: outsideDir });

  assert(fs.existsSync(sessionLogFor(projectDir, 'global-dev')),
    'global identity used when env dir is outside $HOME');
  assert(!fs.existsSync(sessionLogFor(projectDir, 'intruder-dev')),
    'outside-$HOME identity NOT used');
  cleanup(tmpDir);
}

// J7: --profile-dir override is CLI-only (bin/ds-identity); the hook has
// no flag surface -> intentionally no hook-level test (mirrors Python J7 note).
console.log('\n[J7] skipped: --profile-dir is CLI-only, no hook surface');

// ---------------------------------------------------------------------------
// J8: no env vars -> 4-tier back-compat (global identity used)
// ---------------------------------------------------------------------------
console.log('\n[J8] no config-dir env -> 4-tier back-compat');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp('ae-id-j8-');
  writeIdentity(globalIdentityDir, 'global-dev', false);

  runHook(projectDir, fakeHome, 'j8-uuid'); // no extra vars; builder deletes all three

  assert(fs.existsSync(sessionLogFor(projectDir, 'global-dev')),
    'global identity resolved with no profile env set');
  assert(fs.existsSync(sessionLogFor(fakeHome, 'global-dev')),
    'global mirror written with no profile env set');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// ENOENT: nonexistent highest-precedence env dir stops the scan (M2)
// Mirrors Python: _profile_config_dir accepts a not-yet-created dir (it
// holds no identity.yml) and never falls through to a lower-precedence var.
// Pre-fix, realpathSync ENOENT `continue`d to CLAUDE_CONFIG_DIR and the two
// mirrors disagreed on the active profile.
// ---------------------------------------------------------------------------
console.log('\n[ENOENT] nonexistent highest-precedence env dir stops the scan');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp('ae-id-enoent-');
  const ghostDir = path.join(fakeHome, '.agentic-ghost'); // intentionally never created
  const claudeDir = path.join(fakeHome, '.claude-real');
  writeIdentity(claudeDir, 'claude-dev', false);
  writeIdentity(globalIdentityDir, 'global-dev', false);

  runHook(projectDir, fakeHome, 'enoent-uuid', {
    AGENTIC_CONFIG_DIR: ghostDir, CLAUDE_CONFIG_DIR: claudeDir,
  });

  assert(!fs.existsSync(sessionLogFor(projectDir, 'claude-dev')),
    'lower-precedence CLAUDE_CONFIG_DIR identity NOT used (no fall-through)');
  assert(fs.existsSync(sessionLogFor(projectDir, 'global-dev')),
    'global identity used (ghost profile dir holds no identity.yml)');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// SYM: symlink inside $HOME pointing outside must NOT be followed (Fix 1)
// ---------------------------------------------------------------------------
console.log('\n[SYM] symlink escape rejected (realpath containment)');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp('ae-id-sym-');
  const outsideReal = path.join(tmpDir, 'outside-real');
  writeIdentity(outsideReal, 'escape-dev', false);
  writeIdentity(globalIdentityDir, 'global-dev', false);
  // Symlink lives under fake HOME, target is outside it.
  const linkPath = path.join(fakeHome, '.claude-escape');
  fs.symlinkSync(outsideReal, linkPath);

  runHook(projectDir, fakeHome, 'sym-uuid', { AGENTIC_CONFIG_DIR: linkPath });

  assert(!fs.existsSync(sessionLogFor(projectDir, 'escape-dev')),
    'identity behind escaping symlink NOT used');
  assert(fs.existsSync(sessionLogFor(projectDir, 'global-dev')),
    'falls back to global identity when profile symlink escapes $HOME');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// TILDE: a ~-prefixed config-dir env value is expanded to $HOME, matching
// Python's os.path.expanduser (regression for the cross-language divergence
// where Node did path.resolve('~/...') -> <cwd>/~/... and read a different
// identity.yml than the Python CLI for the same env var).
// ---------------------------------------------------------------------------
console.log('\n[TILDE] ~-prefixed AGENTIC_CONFIG_DIR expands to $HOME');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp('ae-id-tilde-');
  // Real profile dir under $HOME; env references it via the ~ shorthand.
  const profDir = path.join(fakeHome, '.claude-tenant');
  writeIdentity(profDir, 'tilde-dev', false);
  writeIdentity(globalIdentityDir, 'global-dev', false);

  runHook(projectDir, fakeHome, 'tilde-uuid', { AGENTIC_CONFIG_DIR: '~/.claude-tenant' });

  assert(fs.existsSync(sessionLogFor(projectDir, 'tilde-dev')),
    '~-prefixed env expands to $HOME/.claude-tenant (profile identity used)');
  assert(!fs.existsSync(sessionLogFor(projectDir, 'global-dev')),
    'did NOT fall back to global (tilde resolved, not treated as <cwd>/~/...)');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// INVALID: parsed handles must never escape either session-log directory.
// ---------------------------------------------------------------------------
console.log('\n[INVALID] invalid parsed handles fail closed');
for (const [index, invalidHandle] of [
  '../../traversal-escape',
  '/absolute/escape',
  'InvalidUpper',
].entries()) {
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp(`ae-id-invalid-${index}-`);
  writeRawIdentity(
    path.join(globalIdentityDir, 'identity.yml'),
    `developer_id: ${invalidHandle}\ncreated_at: 2026-01-01T00:00:00Z\n`,
  );

  runHook(projectDir, fakeHome, `invalid-${index}`);

  assert(!fs.existsSync(path.join(projectDir, '.agentic', 'session-log', 'absolute', 'escape.jsonl')),
    `${invalidHandle} did not create a nested absolute-spelling project log`);
  assert(!fs.existsSync(path.join(fakeHome, '.agentic', 'session-log', 'absolute', 'escape.jsonl')),
    `${invalidHandle} did not create a nested absolute-spelling global log`);
  assert(!fs.existsSync(path.join(projectDir, 'traversal-escape.jsonl')),
    `${invalidHandle} did not escape project session-log`);
  assert(!fs.existsSync(path.join(fakeHome, '.agentic', 'traversal-escape.jsonl')),
    `${invalidHandle} did not escape global session-log`);
  assert(pendingFiles(fakeHome).length === 1,
    `${invalidHandle} was treated as absent/corrupt and buffered`);
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// FINAL TARGETS: every scope rejects symlinked and non-regular identity.yml.
// ---------------------------------------------------------------------------
console.log('\n[FINAL] identity final targets reject symlinks and directories');
for (const scope of ['global', 'project', 'profile']) {
  for (const kind of ['symlink', 'directory']) {
    const { tmpDir, fakeHome, projectDir, agenticDir, globalIdentityDir } =
      makeTmp(`ae-id-final-${scope}-${kind}-`);
    const profileDir = path.join(fakeHome, '.claude-tenant');
    const identityDir = scope === 'global'
      ? globalIdentityDir
      : scope === 'project'
        ? agenticDir
        : profileDir;
    const target = path.join(identityDir, 'identity.yml');
    fs.mkdirSync(identityDir, { recursive: true });
    if (kind === 'symlink') {
      const real = path.join(tmpDir, `${scope}-real.yml`);
      writeRawIdentity(real, `developer_id: ${scope}-symlink-dev\n`);
      fs.symlinkSync(real, target);
    } else {
      fs.mkdirSync(target);
    }

    const extra = scope === 'profile' ? { AGENTIC_CONFIG_DIR: profileDir } : undefined;
    runHook(projectDir, fakeHome, `final-${scope}-${kind}`, extra);

    assert(!fs.existsSync(sessionLogFor(projectDir, `${scope}-symlink-dev`)),
      `${scope} ${kind} final target was not parsed`);
    assert(pendingFiles(fakeHome).length === 1,
      `${scope} ${kind} final target was treated as absent/corrupt`);
    cleanup(tmpDir);
  }
}

// ---------------------------------------------------------------------------
// ENCODING/PERMISSIONS: malformed reads stay bounded and never attribute.
// ---------------------------------------------------------------------------
console.log('\n[READ] invalid UTF-8 and unreadable identity files fail closed');
for (const kind of ['invalid-utf8', 'unreadable']) {
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp(`ae-id-read-${kind}-`);
  const target = path.join(globalIdentityDir, 'identity.yml');
  if (kind === 'invalid-utf8') {
    fs.writeFileSync(target, Buffer.from([
      ...Buffer.from('developer_id: utf8-dev\n', 'utf8'),
      0xff,
      0x0a,
    ]));
  } else {
    writeRawIdentity(target, 'developer_id: unreadable-dev\n');
    fs.chmodSync(target, 0);
  }

  runHook(projectDir, fakeHome, `read-${kind}`);

  if (kind === 'unreadable') fs.chmodSync(target, 0o600);
  assert(!fs.existsSync(sessionLogFor(projectDir, `${kind === 'invalid-utf8' ? 'utf8' : 'unreadable'}-dev`)),
    `${kind} identity was not attributed`);
  assert(pendingFiles(fakeHome).length === 1,
    `${kind} identity produced a bounded absent/corrupt result`);
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// BOUNDED SPECIAL FILES: FIFO/socket reads never block the Stop hook.
// ---------------------------------------------------------------------------
console.log('\n[SPECIAL] FIFO and Unix socket identity reads are bounded');
for (const kind of ['fifo', 'socket']) {
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp(`ae-id-special-${kind}-`);
  const target = path.join(globalIdentityDir, 'identity.yml');
  if (kind === 'fifo') {
    execFileSync('mkfifo', [target]);
  } else {
    execFileSync('python3', [
      '-c',
      'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.close()',
      'identity.yml',
    ], { cwd: globalIdentityDir });
  }
  const payload = JSON.stringify({
    cwd: projectDir,
    session_id: `special-${kind}`,
    transcript: [],
  });
  const started = Date.now();
  const result = spawnSync(process.execPath, [hookScript], {
    input: payload,
    encoding: 'utf8',
    env: buildEnv(fakeHome),
    timeout: 2000,
    stdio: ['pipe', 'pipe', 'ignore'],
  });
  const elapsed = Date.now() - started;
  assert(!result.error, `${kind} identity returned without timeout (${result.error || 'ok'})`);
  assert(result.status === 0, `${kind} identity hook exit is 0 (got ${result.status})`);
  assert(elapsed < 1500, `${kind} identity read completed in ${elapsed}ms`);
  const specialStat = fs.lstatSync(target);
  assert(kind === 'fifo' ? specialStat.isFIFO() : specialStat.isSocket(),
    `${kind} identity target remained unchanged`);
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// PARENT CONTAINMENT: global/project .agentic symlinks are never traversed.
// ---------------------------------------------------------------------------
console.log('\n[PARENT] symlinked global/project .agentic parents fail closed');
for (const scope of ['global', 'project']) {
  const { tmpDir, fakeHome, projectDir, agenticDir, globalIdentityDir } =
    makeTmp(`ae-id-parent-${scope}-`);
  const existingAgentic = scope === 'global' ? globalIdentityDir : agenticDir;
  fs.rmSync(existingAgentic, { recursive: true });
  const outside = path.join(tmpDir, `outside-${scope}`);
  writeIdentity(outside, `outside-${scope}`, false);
  fs.symlinkSync(outside, existingAgentic);

  runHook(projectDir, fakeHome, `parent-${scope}`);

  assert(!fs.existsSync(sessionLogFor(projectDir, `outside-${scope}`)),
    `${scope} identity behind symlinked .agentic parent was not used`);
  if (scope === 'global') {
    assert(pendingFiles(fakeHome).length === 0,
      'global symlinked .agentic parent also blocked the pending write');
    assert(!fs.existsSync(path.join(outside, 'session-log')),
      'global symlinked .agentic parent was not traversed for telemetry');
  } else {
    assert(pendingFiles(fakeHome).length === 1,
      'project symlinked parent was treated as absent/corrupt');
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// LINK COUNT: multiply-linked final identity targets are rejected.
// ---------------------------------------------------------------------------
console.log('\n[NLINK] multiply-linked identity target fails closed');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp('ae-id-nlink-');
  const outside = path.join(tmpDir, 'identity-source.yml');
  writeRawIdentity(outside, 'developer_id: hardlink-dev\n');
  fs.linkSync(outside, path.join(globalIdentityDir, 'identity.yml'));

  runHook(projectDir, fakeHome, 'nlink-global');

  assert(!fs.existsSync(sessionLogFor(projectDir, 'hardlink-dev')),
    'multiply-linked identity was not attributed');
  assert(pendingFiles(fakeHome).length === 1,
    'multiply-linked identity was treated as absent/corrupt');
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// MODE: group/world-writable identity files are attacker-controlled.
// ---------------------------------------------------------------------------
console.log('\n[MODE] group/world-writable identities fail closed');
for (const mode of [0o620, 0o602, 0o666]) {
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } =
    makeTmp(`ae-id-mode-${mode.toString(8)}-`);
  writeIdentity(globalIdentityDir, 'unsafe-mode-dev', false);
  fs.chmodSync(path.join(globalIdentityDir, 'identity.yml'), mode);

  runHook(projectDir, fakeHome, `mode-${mode.toString(8)}`);

  assert(!fs.existsSync(sessionLogFor(projectDir, 'unsafe-mode-dev')),
    `mode ${mode.toString(8)} identity was not attributed`);
  assert(pendingFiles(fakeHome).length === 1,
    `mode ${mode.toString(8)} identity was treated as absent/corrupt`);
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// DEPLOYED SNAPSHOT: normal snapshot layout carries the helper beside hooks.
// ---------------------------------------------------------------------------
console.log('\n[SNAPSHOT] deployed Stop hook resolves its bundled identity helper');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } =
    makeTmp('ae-id-deployed-snapshot-');
  execFileSync('git', ['init', '-q'], { cwd: projectDir });
  writeIdentity(globalIdentityDir, 'snapshot-dev', false);
  const repoDir = path.resolve(__dirname, '..', '..');
  const snapshotDir = execFileSync('bash', [
    '-c',
    'source "$1"; sync_hooks_snapshot "$2" >/dev/null; printf "%s" "$AE_HOOKS_SNAPSHOT_DIR"',
    'bash',
    path.join(repoDir, 'scripts', 'lib', 'hooks-snapshot.sh'),
    repoDir,
  ], {
    encoding: 'utf8',
    env: buildEnv(fakeHome),
  });
  const deployedHook = path.join(snapshotDir, 'hooks', 'stop-context.js');
  const deployedHelper = path.join(snapshotDir, 'bin', 'ds-identity');
  assert(fs.existsSync(deployedHelper), 'snapshot contains bin/ds-identity');
  assert((fs.statSync(deployedHelper).mode & 0o111) !== 0,
    'snapshot identity helper is executable');
  runHookAt(deployedHook, projectDir, fakeHome, 'snapshot-direct');
  const projectRows = fs.readFileSync(
    sessionLogFor(projectDir, 'snapshot-dev'), 'utf8').trim().split('\n');
  const globalRows = fs.readFileSync(
    sessionLogFor(fakeHome, 'snapshot-dev'), 'utf8').trim().split('\n');
  assert(projectRows.length === 1 && globalRows.length === 1,
    'deployed snapshot writes both direct telemetry logs');
  assert(pendingFiles(fakeHome).length === 0,
    'deployed snapshot does not fall back to pending telemetry');
  for (const adapter of ['.claude', '.codex', '.gemini', '.kimi']) {
    const installer = fs.readFileSync(path.join(repoDir, adapter, 'install.sh'), 'utf8');
    assert(installer.includes('sync_hooks_snapshot'),
      `${adapter} installer uses the shared helper-bearing snapshot`);
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// TELEMETRY TARGETS: final output files are descriptor-validated and bounded.
// ---------------------------------------------------------------------------
console.log('\n[TELEMETRY] hostile global log targets fail closed without mutation');
for (const kind of ['symlink', 'hardlink', 'fifo', 'socket', 'mode-620', 'mode-602', 'mode-666', 'oversized']) {
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } =
    makeTmp(`ae-telemetry-${kind}-`);
  execFileSync('git', ['init', '-q'], { cwd: projectDir });
  writeIdentity(globalIdentityDir, 'safe-dev', false);
  const logDir = path.join(fakeHome, '.agentic', 'session-log');
  fs.mkdirSync(logDir, { recursive: true });
  const target = path.join(logDir, 'safe-dev.jsonl');
  const outside = path.join(tmpDir, 'outside-sentinel');
  fs.writeFileSync(outside, 'KEEP\n');
  if (kind === 'symlink') {
    fs.symlinkSync(outside, target);
  } else if (kind === 'hardlink') {
    fs.linkSync(outside, target);
  } else if (kind === 'fifo') {
    execFileSync('mkfifo', [target]);
  } else if (kind === 'socket') {
    execFileSync('python3', [
      '-c',
      'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.close()',
      'safe-dev.jsonl',
    ], { cwd: logDir });
  } else if (kind.startsWith('mode-')) {
    fs.writeFileSync(target, 'KEEP\n');
    fs.chmodSync(target, parseInt(kind.slice(5), 8));
  } else {
    fs.writeFileSync(target, 'KEEP\n');
    fs.truncateSync(target, 16 * 1024 * 1024 + 1);
  }

  const started = Date.now();
  runHook(projectDir, fakeHome, `hostile-${kind}`);
  const elapsed = Date.now() - started;
  assert(elapsed < 5000, `${kind} telemetry target returned in ${elapsed}ms`);
  const targetStat = fs.lstatSync(target);
  if (kind === 'symlink' || kind === 'hardlink') {
    assert(fs.readFileSync(outside, 'utf8') === 'KEEP\n',
      `${kind} telemetry target did not modify its external sentinel`);
  } else if (kind === 'fifo' || kind === 'socket') {
    assert(kind === 'fifo' ? targetStat.isFIFO() : targetStat.isSocket(),
      `${kind} telemetry target remained the same special-file type`);
  } else if (kind.startsWith('mode-')) {
    assert(fs.readFileSync(target, 'utf8') === 'KEEP\n',
      `${kind} telemetry target bytes stayed unchanged`);
  } else {
    assert(targetStat.size === 16 * 1024 * 1024 + 1,
      'oversized telemetry target stayed unchanged');
  }
  assert(fs.existsSync(sessionLogFor(projectDir, 'safe-dev')),
    `${kind} global refusal did not suppress the safe project log`);
  cleanup(tmpDir);
}

console.log('\n[TELEMETRY] wrong-owner log target fails closed when fixture is permitted');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } =
    makeTmp('ae-telemetry-owner-');
  execFileSync('git', ['init', '-q'], { cwd: projectDir });
  writeIdentity(globalIdentityDir, 'safe-dev', false);
  const target = sessionLogFor(fakeHome, 'safe-dev');
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, 'KEEP\n');
  let changedOwner = false;
  try {
    fs.chownSync(target, process.getuid() === 0 ? 1 : 0, process.getgid());
    changedOwner = fs.statSync(target).uid !== process.getuid();
  } catch (_) {
    // Non-root CI cannot construct a wrong-owner regular file.
  }
  if (changedOwner) {
    runHook(projectDir, fakeHome, 'wrong-owner');
    assert(fs.readFileSync(target, 'utf8') === 'KEEP\n',
      'wrong-owner telemetry target stayed unchanged');
  } else {
    const helperSource = fs.readFileSync(
      path.resolve(__dirname, '..', '..', 'bin', 'ds-identity'), 'utf8');
    assert(helperSource.includes('target_stat.st_uid == os.geteuid()'),
      'wrong-owner fixture unavailable; deployed helper still enforces current-owner predicate');
  }
  cleanup(tmpDir);
}

console.log('\n[TELEMETRY] predictable pending temp substitution is inert');
{
  const { tmpDir, fakeHome, projectDir } = makeTmp('ae-telemetry-temp-');
  const pendingDir = path.join(fakeHome, '.agentic', 'session-log', '.pending');
  fs.mkdirSync(pendingDir, { recursive: true });
  const predictable = path.join(pendingDir, 'predictable.json.tmp');
  fs.writeFileSync(predictable, 'KEEP\n');
  runHook(projectDir, fakeHome, 'predictable');
  assert(fs.readFileSync(predictable, 'utf8') === 'KEEP\n',
    'legacy predictable temporary name was not opened or replaced');
  assert(fs.existsSync(path.join(pendingDir, 'predictable.json')),
    'pending record was published through an unpredictable exclusive sibling');
  cleanup(tmpDir);
}

console.log('\n[TELEMETRY] repeated Stop turns replace same-session cumulative totals');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } =
    makeTmp('ae-telemetry-repeat-');
  execFileSync('git', ['init', '-q'], { cwd: projectDir });
  writeIdentity(globalIdentityDir, 'repeat-dev', true);
  const eventsPath = path.join(projectDir, '.agentic', 'events.jsonl');
  const event = (index) => JSON.stringify({
    ts: new Date(Date.UTC(2026, 6, 28) + index * 1000).toISOString(),
    phase: 'test',
    event: 'spawn_complete',
    agent: 'engineer',
    data: {
      session_uuid: 'repeat-session',
      wall_seconds: 1,
      tokens: { input: 1, output: 1, cache_creation: 0, cache_read: 0 },
    },
  });
  fs.writeFileSync(eventsPath, event(0) + '\n');
  runHook(projectDir, fakeHome, 'repeat-session');
  let pending = JSON.parse(fs.readFileSync(
    path.join(fakeHome, '.agentic', 'session-log', '.pending', 'repeat-session.json'),
    'utf8'));
  assert(pending.data.spawn_count === 1, 'first Stop turn stored one cumulative spawn');

  fs.writeFileSync(eventsPath, Array.from({ length: 99 }, (_, index) => event(index)).join('\n') + '\n');
  runHook(projectDir, fakeHome, 'repeat-session');
  pending = JSON.parse(fs.readFileSync(
    path.join(fakeHome, '.agentic', 'session-log', '.pending', 'repeat-session.json'),
    'utf8'));
  assert(pending.data.spawn_count === 99,
    'second Stop turn atomically replaced the same session with latest cumulative totals');
  assert(pendingFiles(fakeHome).length === 1,
    'repeated turns retain exactly one pending record for the session');
  cleanup(tmpDir);
}

console.log('\n[TELEMETRY] concurrent same-session writers preserve the later timestamp');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } =
    makeTmp('ae-telemetry-same-session-');
  execFileSync('git', ['init', '-q'], { cwd: projectDir });
  writeIdentity(globalIdentityDir, 'repeat-dev', true);
  const helper = path.resolve(__dirname, '..', '..', 'bin', 'ds-identity');
  const pendingDir = path.join(fakeHome, '.agentic', 'session-log', '.pending');
  fs.mkdirSync(pendingDir, { recursive: true });
  const payload = (spawnCount) => JSON.stringify({
    identity: {
      developer_id: 'repeat-dev',
      provisional: true,
      identity_scope: 'global',
    },
    session_uuid: 'same-session',
    branch: 'main',
    data: {
      wall_seconds: spawnCount,
      tokens: { input: spawnCount, output: 0, cache_creation: 0, cache_read: 0 },
      spawn_count: spawnCount,
      by_agent: {},
    },
  });
  const low = path.join(tmpDir, 'low.json');
  const high = path.join(tmpDir, 'high.json');
  fs.writeFileSync(low, payload(1));
  fs.writeFileSync(high, payload(99));
  const ready = path.join(tmpDir, 'ready');
  const release = path.join(tmpDir, 'release');
  const result = spawnSync('bash', [
    '-c',
    [
      'python3 -c \'import fcntl,os,sys,time; fd=os.open(sys.argv[1], os.O_RDONLY);',
      'fcntl.flock(fd, fcntl.LOCK_EX); open(sys.argv[2],"w").close();',
      'exec("while not os.path.exists(sys.argv[3]): time.sleep(0.002)"); os.close(fd)\'',
      '"$1" "$2" "$3" & locker=$!;',
      'while [ ! -f "$2" ]; do sleep 0.002; done;',
      '"$4" write-hook --cwd "$5" <"$6" & low=$!;',
      'sleep 0.05;',
      '"$4" write-hook --cwd "$5" <"$7" & high=$!;',
      'touch "$3"; wait "$locker"; wait "$low"; a=$?; wait "$high"; b=$?;',
      'test "$a" -eq 0 -a "$b" -eq 0',
    ].join(' '),
    'bash',
    pendingDir,
    ready,
    release,
    helper,
    projectDir,
    low,
    high,
  ], { env: buildEnv(fakeHome), encoding: 'utf8', timeout: 10000 });
  assert(!result.error && result.status === 0,
    `concurrent same-session helper calls completed (${result.stderr.trim()})`);
  const pending = JSON.parse(fs.readFileSync(
    path.join(pendingDir, 'same-session.json'), 'utf8'));
  assert(pending.data.spawn_count === 99,
    'later same-session timestamp wins regardless of lock acquisition order');
  cleanup(tmpDir);
}

console.log('\n[TELEMETRY] concurrent helper appends remain complete JSONL records');
{
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } =
    makeTmp('ae-telemetry-concurrent-');
  execFileSync('git', ['init', '-q'], { cwd: projectDir });
  writeIdentity(globalIdentityDir, 'safe-dev', false);
  const helper = path.resolve(__dirname, '..', '..', 'bin', 'ds-identity');
  const telemetryData = {
    wall_seconds: 0,
    tokens: { input: 0, output: 0, cache_creation: 0, cache_read: 0 },
    spawn_count: 0,
    by_agent: {},
  };
  const payloadA = path.join(tmpDir, 'a.json');
  const payloadB = path.join(tmpDir, 'b.json');
  fs.writeFileSync(payloadA, JSON.stringify({
    identity: { developer_id: 'safe-dev', provisional: false, identity_scope: 'global' },
    session_uuid: 'parallel-a',
    branch: 'main',
    data: telemetryData,
  }));
  fs.writeFileSync(payloadB, JSON.stringify({
    identity: { developer_id: 'safe-dev', provisional: false, identity_scope: 'global' },
    session_uuid: 'parallel-b',
    branch: 'main',
    data: telemetryData,
  }));
  const concurrent = spawnSync('bash', [
    '-c',
    '"$1" write-hook --cwd "$2" <"$3" & p1=$!; "$1" write-hook --cwd "$2" <"$4" & p2=$!; wait "$p1"; r1=$?; wait "$p2"; r2=$?; test "$r1" -eq 0 -a "$r2" -eq 0',
    'bash',
    helper,
    projectDir,
    payloadA,
    payloadB,
  ], { env: buildEnv(fakeHome), encoding: 'utf8', timeout: 10000 });
  assert(!concurrent.error && concurrent.status === 0,
    `two concurrent helper calls completed successfully (${concurrent.stdout.trim()} ${concurrent.stderr.trim()})`);
  for (const base of [projectDir, fakeHome]) {
    const rows = fs.readFileSync(sessionLogFor(base, 'safe-dev'), 'utf8')
      .trim().split('\n').map((line) => JSON.parse(line));
    const ids = rows.map((row) => row.session_uuid).sort();
    assert(JSON.stringify(ids) === JSON.stringify(['parallel-a', 'parallel-b']),
      `${base === projectDir ? 'project' : 'global'} concurrent log has two complete records (${ids.join(',')})`);
  }
  cleanup(tmpDir);
}

console.log('\n[CEILING] full Stop hook run stays bounded by the production write-hook ceiling when BOTH project and global logs are permanently contended');
{
  // DS-158 round 3 Minor 6: the other TELEMETRY/J-suite concurrency tests
  // in this file invoke `bin/ds-identity write-hook` DIRECTLY (bypassing
  // stop-context.js entirely) with a harness timeout (10000ms) more
  // permissive than production's spawnSync ceiling - they cannot fail on a
  // regression to that ceiling. This test runs the REAL Stop hook
  // end-to-end against a permanently-held flock on BOTH the project and
  // global session logs (not just global - locking only global leaves the
  // project append uncontended and never exercises Major 1's shared-vs-
  // doubled budget distinction, since only a target that ALSO genuinely
  // contends can absorb a share of the budget) and measures the full run's
  // wall clock from the JS side (not via in-script `date` arithmetic,
  // which is non-portable across BSD/GNU `date`), asserting it stays
  // bounded by the production ceiling plus a small margin - not the
  // harness's own generous outer timeout. A regression to round 2's
  // per-append budget (or an unshared JS ceiling) would let this run
  // consume roughly double the shared budget before the JS-side spawnSync
  // ceiling force-kills it.
  const { tmpDir, fakeHome, projectDir, globalIdentityDir } = makeTmp('ae-id-ceiling-');
  writeIdentity(globalIdentityDir, 'ceiling-dev', false);
  execFileSync('git', ['init', '-q'], { cwd: projectDir });

  const globalLog = sessionLogFor(fakeHome, 'ceiling-dev');
  const projectLog = sessionLogFor(projectDir, 'ceiling-dev');
  fs.mkdirSync(path.dirname(globalLog), { recursive: true });
  fs.mkdirSync(path.dirname(projectLog), { recursive: true });
  fs.writeFileSync(globalLog, '');
  fs.writeFileSync(projectLog, '');

  const ready = path.join(tmpDir, 'ready');
  const release = path.join(tmpDir, 'release');
  const payloadFile = path.join(tmpDir, 'payload.json');
  fs.writeFileSync(payloadFile, JSON.stringify({
    cwd: projectDir,
    session_id: 'ceiling-uuid',
    transcript: [],
  }));

  const script = [
    // Locks BOTH targets from a single process before signaling ready, so
    // the hook's project AND global appends are simultaneously contended
    // for the entire run.
    'python3 -c \'import fcntl,os,sys,time;',
    'fd1=os.open(sys.argv[1], os.O_RDONLY); fcntl.flock(fd1, fcntl.LOCK_EX);',
    'fd2=os.open(sys.argv[2], os.O_RDONLY); fcntl.flock(fd2, fcntl.LOCK_EX);',
    'open(sys.argv[3],"w").close();',
    'exec("while not os.path.exists(sys.argv[4]): time.sleep(0.002)");',
    'os.close(fd1); os.close(fd2)\'',
    '"$1" "$2" "$3" "$4" & locker=$!;',
    'while [ ! -f "$3" ]; do sleep 0.002; done;',
    '"$5" "$6" < "$7" >/dev/null 2>&1; hookrc=$?;',
    'touch "$4"; wait "$locker";',
    'exit "$hookrc"',
  ].join(' ');

  const started = Date.now();
  const result = spawnSync('bash', [
    '-c', script, 'bash', projectLog, globalLog, ready, release,
    process.execPath, hookScript, payloadFile,
  ], { env: buildEnv(fakeHome), encoding: 'utf8', timeout: 10000 });
  const elapsedMs = Date.now() - started;

  assert(!result.error && result.status === 0,
    `Stop hook exits 0 even when both logs are permanently contended (status=${result.status}, error=${result.error && result.error.message})`);
  // Measured: fixed (shared-deadline) code lands at ~5330-5370ms across
  // repeated local runs; reverting to a separate 5s budget per append (the
  // exact Major 1 regression) lands at ~6180-6200ms, because the JS-side
  // spawnSync ceiling (unmutated, still 6000ms) force-kills the child
  // before Python's own doubled budget would otherwise let it run to
  // ~10s. 5800ms sits between the two with margin on both sides.
  assert(elapsedMs < 5800,
    `Stop hook run stays bounded by the production write-hook ceiling `
    + `(~5300-5400ms observed for a shared budget; a reversion to a `
    + `separate per-append budget lands at ~6200ms - the JS-side spawnSync `
    + `ceiling still caps it below the theoretical ~10s), got ${elapsedMs}ms`);
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
