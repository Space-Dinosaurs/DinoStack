#!/usr/bin/env node
/**
 * Unit tests: skill-candidate Layer-2 in-session nudge wired into
 * post-tool-use-capture-nudge.js.
 *
 * The hook is a stdin-driven CLI script (run() reads fd 0 and process.exit(0)s),
 * so each case drives the REAL hook as a subprocess with a controlled payload on
 * stdin and a temporary .agentic/ fixture, then asserts on the hook's stdout.
 *
 * Test cases:
 *   (a) fires-with-candidate:        both toggles on + tally with >=threshold
 *                                     candidate -> SKILL-CANDIDATE-NUDGE emitted.
 *   (b) dedup-suppresses-repeat:     same candidate again in the same session ->
 *                                     NOT re-emitted (.skill-candidates-in-session
 *                                     dedup fires).
 *   (c) nudge-toggle-absent-silent:  skill_candidate_nudge absent (default false)
 *                                     -> no nudge even if candidates exist.
 *   (d) nudge-toggle-false-silent:   skill_candidate_nudge explicitly false ->
 *                                     no nudge.
 *   (e) detection-false-silent:      skill_candidate_detection: false -> no nudge
 *                                     even if nudge toggle is true.
 *   (f) peek-read-only:              hook run does not alter tally mtime. Asserts
 *                                     that peekActiveCandidates() is read-only: the
 *                                     tally file mtime is unchanged after the hook.
 *
 * All tests use temp dirs under os.tmpdir(). NEVER touch real ~/.claude or .agentic/.
 *
 * Run with: node hooks/tests/test-post-tool-use-skill-nudge.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const hookPath = path.resolve(__dirname, '..', 'post-tool-use-capture-nudge.js');

// ---------------------------------------------------------------------------
// Tmp-shim load: suppress run(), re-anchor relative lib requires to absolute
// paths so the /tmp shim resolves them correctly. Mirrors the pattern from
// test-post-tool-use-capture-nudge.js.
// ---------------------------------------------------------------------------
const hookSource = fs.readFileSync(hookPath, 'utf8');
const libCaptureGapAbs = path.resolve(__dirname, '..', 'lib', 'capture-gap.js');
const libSkillDetectorAbs = path.resolve(__dirname, '..', 'lib', 'skill-candidate-detector.js');

let shimmedSource = hookSource
  .replace(/^run\(\);\s*$/m, '// test shim: run() suppressed')
  .replace(
    /require\(['"]\.\/lib\/capture-gap\.js['"]\)/,
    `require(${JSON.stringify(libCaptureGapAbs)})`
  )
  .replace(
    /require\(['"]\.\/lib\/skill-candidate-detector\.js['"]\)/,
    `require(${JSON.stringify(libSkillDetectorAbs)})`
  );

// Fail loud if any relative ./lib/ require survived re-anchoring.
if (/require\(['"]\.\/lib\//.test(shimmedSource)) {
  console.error(
    '  FATAL: a relative ./lib/ require survived the shim re-anchor - update the '
    + 'rewrite in test-post-tool-use-skill-nudge.js so the /tmp shim can resolve it.'
  );
  process.exit(1);
}

const tmpShimPath = path.join(os.tmpdir(), `ptu-skill-shim-${Date.now()}.js`);
fs.writeFileSync(tmpShimPath, shimmedSource, 'utf8');
try {
  require(tmpShimPath); // must load without reading stdin or throwing
} finally {
  try { fs.unlinkSync(tmpShimPath); } catch (_) { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

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

function makeTempProject() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-skill-nudge-test-'));
  fs.mkdirSync(path.join(tmpDir, '.agentic'), { recursive: true });
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

/**
 * Write .agentic/config.json with the given skill toggle values.
 * @param {string} cwd
 * @param {object} overrides - keys to set/override (e.g. { skill_candidate_nudge: true })
 */
function writeConfig(cwd, overrides) {
  const configPath = path.join(cwd, '.agentic', 'config.json');
  const base = {};
  const config = Object.assign(base, overrides);
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2) + '\n', 'utf8');
}

/**
 * Write .agentic/.skill-candidate-tally.json with at least one candidate at or
 * above CANDIDATE_THRESHOLD (3).
 * @param {string} cwd
 * @param {string} domain - candidate domain slug
 * @param {number} count - candidate count (default 3 = at threshold)
 */
function writeTally(cwd, domain, count) {
  count = typeof count === 'number' ? count : 3;
  const tallyPath = path.join(cwd, '.agentic', '.skill-candidate-tally.json');
  const tally = {
    version: 1,
    lastCursorTs: new Date().toISOString(),
    candidates: {
      [domain]: {
        count,
        exampleNote: `example note for ${domain}`,
        firstSeen: '2026-06-01T00:00:00.000Z',
        lastSeen: new Date().toISOString(),
        suggestedArtifact: 'command',
        surfacedAt: null,
        learnDatesApplied: [],
      },
    },
  };
  fs.writeFileSync(tallyPath, JSON.stringify(tally, null, 2) + '\n', 'utf8');
  return tallyPath;
}

/**
 * Drive the real hook as a subprocess with the given payload on stdin.
 * Returns { stdout, status }. spawnSync so a clean exit 0 with empty stdout
 * is captured rather than treated as an error.
 * @param {object} payload
 * @param {string} cwd
 * @returns {{ stdout: string, status: number }}
 */
function runHook(payload, cwd) {
  const input = JSON.stringify(payload);
  const res = spawnSync('node', [hookPath], {
    input, cwd, timeout: 15000, encoding: 'utf8',
  });
  return { stdout: res.stdout || '', status: res.status };
}

/**
 * Build a standard PostToolUse(Task) async_launched payload.
 * @param {string} cwd
 * @param {string} sessionId
 * @param {object} overrides
 * @returns {object}
 */
function taskPayload(cwd, sessionId, overrides) {
  return Object.assign({
    cwd,
    session_id: sessionId,
    tool_name: 'Task',
    tool_response: { status: 'async_launched' },
  }, overrides || {});
}

// ---------------------------------------------------------------------------
// Test (a): fires-with-candidate
// Both toggles on, tally has a domain at count=3 (at threshold).
// Hook must emit SKILL-CANDIDATE-NUDGE with the domain name.
// ---------------------------------------------------------------------------
console.log('\nTest (a): fires-with-candidate');
{
  const cwd = makeTempProject();
  const sessionId = 'skill-nudge-session-a';
  const domain = 'git-workaround';

  writeConfig(cwd, { skill_candidate_detection: true, skill_candidate_nudge: true });
  writeTally(cwd, domain, 3);

  const { stdout, status } = runHook(taskPayload(cwd, sessionId), cwd);
  assert(status === 0, 'hook exits 0');
  let out = null;
  try { out = JSON.parse(stdout); } catch (_) { /* leave null */ }
  assert(out !== null, 'hook emitted parseable JSON');
  assert(
    out && out.hookSpecificOutput && out.hookSpecificOutput.hookEventName === 'PostToolUse',
    'hookEventName is PostToolUse'
  );
  const ctx = out && out.hookSpecificOutput ? out.hookSpecificOutput.additionalContext : '';
  assert(
    ctx.includes('SKILL-CANDIDATE-NUDGE'),
    'additionalContext contains SKILL-CANDIDATE-NUDGE'
  );
  assert(ctx.includes(domain), `additionalContext mentions the domain "${domain}"`);
  assert(ctx.includes('skill-creator'), 'additionalContext references skill-creator skill');
  assert(ctx.includes('/skill-candidates'), 'additionalContext references /skill-candidates command');
  // Dedup tracker was written.
  const trackerPath = path.join(cwd, '.agentic', '.skill-candidates-in-session');
  assert(fs.existsSync(trackerPath), 'dedup tracker written after firing');
  const trackerContent = fs.readFileSync(trackerPath, 'utf8');
  const parsed = JSON.parse(trackerContent.trim());
  assert(
    parsed.session_id === sessionId && parsed.candidate_id === domain,
    'dedup tracker entry has correct session_id and candidate_id'
  );
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (b): dedup-suppresses-repeat
// Same candidate, same session -> no second nudge.
// ---------------------------------------------------------------------------
console.log('\nTest (b): dedup-suppresses-repeat');
{
  const cwd = makeTempProject();
  const sessionId = 'skill-nudge-session-b';
  const domain = 'adapter-build';

  writeConfig(cwd, { skill_candidate_detection: true, skill_candidate_nudge: true });
  writeTally(cwd, domain, 5);

  const first = runHook(taskPayload(cwd, sessionId), cwd);
  assert(first.stdout.includes('SKILL-CANDIDATE-NUDGE'), 'first spawn emits skill nudge');

  const second = runHook(taskPayload(cwd, sessionId), cwd);
  assert(second.status === 0, 'second spawn exits 0');
  assert(second.stdout.trim() === '', 'second spawn (same candidate) emits nothing - dedup');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (c): nudge-toggle-absent-silent
// skill_candidate_nudge key absent from config -> defaults false -> no nudge.
// ---------------------------------------------------------------------------
console.log('\nTest (c): nudge-toggle-absent-silent');
{
  const cwd = makeTempProject();
  const sessionId = 'skill-nudge-session-c';
  const domain = 'some-domain';

  // Config has NO skill_candidate_nudge key (absent = default false).
  writeConfig(cwd, { skill_candidate_detection: true });
  writeTally(cwd, domain, 4);

  const { stdout, status } = runHook(taskPayload(cwd, sessionId), cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no nudge when skill_candidate_nudge absent (default false)');
  assert(
    !fs.existsSync(path.join(cwd, '.agentic', '.skill-candidates-in-session')),
    'no dedup tracker written when nudge is off'
  );
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (d): nudge-toggle-false-silent
// skill_candidate_nudge: false explicitly -> no nudge.
// ---------------------------------------------------------------------------
console.log('\nTest (d): nudge-toggle-false-silent');
{
  const cwd = makeTempProject();
  const sessionId = 'skill-nudge-session-d';
  const domain = 'another-domain';

  writeConfig(cwd, { skill_candidate_detection: true, skill_candidate_nudge: false });
  writeTally(cwd, domain, 3);

  const { stdout, status } = runHook(taskPayload(cwd, sessionId), cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no nudge when skill_candidate_nudge is false');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (e): detection-false-silent
// skill_candidate_detection: false -> master toggle off -> no nudge even if
// skill_candidate_nudge: true.
// ---------------------------------------------------------------------------
console.log('\nTest (e): detection-false-silent');
{
  const cwd = makeTempProject();
  const sessionId = 'skill-nudge-session-e';
  const domain = 'some-domain';

  writeConfig(cwd, { skill_candidate_detection: false, skill_candidate_nudge: true });
  writeTally(cwd, domain, 3);

  const { stdout, status } = runHook(taskPayload(cwd, sessionId), cwd);
  assert(status === 0, 'hook exits 0');
  assert(stdout.trim() === '', 'no nudge when skill_candidate_detection is false');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test (f): peek-read-only
// Both toggles on, tally exists. After the hook fires, the tally mtime must
// be unchanged - peekActiveCandidates() must NEVER write the tally or cursor.
// ---------------------------------------------------------------------------
console.log('\nTest (f): peek-read-only (tally mtime unchanged after hook)');
{
  const cwd = makeTempProject();
  const sessionId = 'skill-nudge-session-f';
  const domain = 'lint-workaround';

  writeConfig(cwd, { skill_candidate_detection: true, skill_candidate_nudge: true });
  const tallyPath = writeTally(cwd, domain, 3);
  const cursorPath = path.join(cwd, '.agentic', '.skill-candidate-cursor');

  // Record mtime BEFORE hook run.
  const tallyMtimeBefore = fs.statSync(tallyPath).mtimeMs;
  // Cursor does not exist yet - we just record absence.
  const cursorExistedBefore = fs.existsSync(cursorPath);

  const { stdout, status } = runHook(taskPayload(cwd, sessionId), cwd);
  assert(status === 0, 'hook exits 0 (peek-read-only case)');
  assert(stdout.includes('SKILL-CANDIDATE-NUDGE'), 'nudge was emitted (confirming tally was readable)');

  const tallyMtimeAfter = fs.statSync(tallyPath).mtimeMs;
  assert(
    tallyMtimeAfter === tallyMtimeBefore,
    'tally mtime unchanged - peekActiveCandidates did not write the tally'
  );

  const cursorExistedAfter = fs.existsSync(cursorPath);
  assert(
    cursorExistedAfter === cursorExistedBefore,
    'cursor file presence unchanged - peekActiveCandidates did not create/write cursor'
  );
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
if (failed > 0) process.exit(1);
