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
 *   J5  env precedence AGENTIC_CONFIG_DIR > CLAUDE_CONFIG_DIR > CODEX_HOME,
 *       plus CODEX_HOME-alone fallback
 *   J6  outside-$HOME env dir rejected -> global identity used
 *   J7  n/a (--profile-dir is CLI-only; no hook surface) - intentionally skipped
 *   J8  no env vars -> 4-tier back-compat (global identity used)
 *   ENOENT nonexistent highest-precedence env dir STOPS the scan (no
 *       fall-through to a lower-precedence existing profile), matching
 *       Python _profile_config_dir (Path.resolve() needs no existence)
 *   SYM symlink inside $HOME pointing outside must NOT be followed
 *       (Fix-1 regression proof; fails on the pre-fix lexical check)
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
const { execSync } = require('child_process');

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

const PROFILE_ENV_VARS = ['AGENTIC_CONFIG_DIR', 'CLAUDE_CONFIG_DIR', 'CODEX_HOME'];

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
  const payload = JSON.stringify({
    cwd: projectDir,
    session_id: sessionId,
    transcript: [],
  });
  execSync(`node "${hookScript}"`, {
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
    assert(rec.schema_version === 1, 'schema_version stays 1 (additive field)');
  }
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// J5: env precedence AGENTIC > CLAUDE > CODEX; CODEX_HOME alone works
// ---------------------------------------------------------------------------
console.log('\n[J5] env precedence AGENTIC_CONFIG_DIR > CLAUDE_CONFIG_DIR > CODEX_HOME');
{
  const { tmpDir, fakeHome, projectDir } = makeTmp('ae-id-j5-');
  const dirA = path.join(fakeHome, '.prof-a');
  const dirB = path.join(fakeHome, '.prof-b');
  const dirC = path.join(fakeHome, '.prof-c');
  writeIdentity(dirA, 'a-dev', false);
  writeIdentity(dirB, 'b-dev', false);
  writeIdentity(dirC, 'c-dev', false);

  // All three set -> AGENTIC wins.
  runHook(projectDir, fakeHome, 'j5-uuid-1', {
    AGENTIC_CONFIG_DIR: dirA, CLAUDE_CONFIG_DIR: dirB, CODEX_HOME: dirC,
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

// J7: --profile-dir override is CLI-only (bin/agentic-identity); the hook has
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
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
