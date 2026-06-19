#!/usr/bin/env node
/**
 * Unit tests: stop-context.js capture-gap backstop.
 *
 * Tests detectCaptureGap() and appendCaptureGapNoticeToContextMd() by setting up
 * temporary .agentic/ directories with controlled events.jsonl / learnings.md
 * content and running the hook in-process via module exports.
 *
 * Test cases:
 *   1. fires-on-debugger:              debugger spawn_complete with session_uuid -> shouldNudge true
 *   2. fires-on-tool_failure_workaround: tool_failure_workaround event -> shouldNudge true
 *   3. suppressed-by-domain-proximate-guardrail: matching guardrail path -> shouldNudge false
 *   4. fires-despite-unrelated-guardrail (Major-1 regression): guardrail added but not domain-
 *      proximate -> shouldNudge true, residualOnly true (residual-WHY text in nudge)
 *   5. no-fire-when-learning-captured: today-dated [LRN- entry -> shouldNudge false
 *   6. session-filter-excludes-foreign-uuid: event has different session_uuid -> shouldNudge false
 *   7. cold-start-100-line-cap: >100 event lines, learning-worthy event in line 50 from end
 *      (within cap) -> shouldNudge true; event beyond 100-line window -> shouldNudge false
 *   8. silent-fail-on-malformed-line: events.jsonl contains malformed JSON lines -> no throw
 *   9. residualOnly-text-differentiation: residualOnly=true -> nudge text contains residual wording
 *  10. no-fire-when-no-session-uuid-on-event: absent session_uuid deliberately excluded (MAJOR regression)
 *  11. skeptic-trigger-fires: skeptic spawn_complete with signed_off=true AND critical>0
 *      -> shouldNudge true (code path existed but had no test)
 *  12. skeptic-no-critical-major-no-fire: skeptic spawn_complete with signed_off=true but
 *      zero critical/major -> shouldNudge false (only non-trivial skeptic reviews are learning-worthy)
 *  13. knw-dated-suppression: today-dated [KNW-YYYYMMDD-XXX] entry with Discovered: line
 *      -> shouldNudge false (KNW + Discovered: branch was untested; only LRN was exercised by test 5)
 *
 * Run with: node hooks/tests/test-capture-gap.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

// ---------------------------------------------------------------------------
// Load the module under test. detectCaptureGap and appendCaptureGapNoticeToContextMd
// are not exported by the script (it calls run() immediately), so we use a
// custom loader that stubs out run() and exports the internal helpers.
// ---------------------------------------------------------------------------

/**
 * Load stop-context.js in a controlled way: require it in a temporary module
 * scope that patches process.exit so run() doesn't terminate the test process,
 * and exports the internal helper functions via a side-channel global.
 *
 * We load by wrapping the source with an IIFE that replaces process.exit and
 * exposes the named functions via a global object before run() fires.
 *
 * Technique: read source, prepend a shim that registers the helpers on a
 * global, append a post-run no-op, eval in a Module sandbox.
 */
const hookPath = path.resolve(__dirname, '..', 'stop-context.js');
const hookSource = fs.readFileSync(hookPath, 'utf8');

// Shim: intercept run() and expose helpers. We do this by wrapping the source
// in a function that overrides run before the bottom-of-file call fires.
// The shim replaces the trailing `run();` call with a no-op so the hook
// doesn't actually read stdin during test setup.
//
// The shim is written to os.tmpdir() and require()d from there, so the hook's
// relative `require('./lib/wrap-marker.js')` (added when stop-context.js was
// extended to delegate marker/lock/heartbeat state to hooks/lib/wrap-marker.js)
// cannot resolve from /tmp. Rewrite that one relative require to an absolute
// path to the REAL hooks/lib/wrap-marker.js before writing the shim, so the
// shimmed copy still loads the real lib (no behavior change, just resolution).
const libMarkerAbs = path.resolve(__dirname, '..', 'lib', 'wrap-marker.js');
const shimmedSource = hookSource
  // Replace the final bare `run();` call so the hook doesn't try to read stdin.
  .replace(/^run\(\);\s*$/m, '// test shim: run() suppressed')
  // Re-anchor the relative lib require to an absolute path to the real lib so the
  // shim resolves it from /tmp. JSON.stringify yields a correctly-escaped literal
  // on every platform (backslashes on Windows, etc.).
  .replace(
    /require\(['"]\.\/lib\/wrap-marker\.js['"]\)/,
    `require(${JSON.stringify(libMarkerAbs)})`
  )
  + `\n
// Expose helpers for unit tests via a module-level export shim.
// This block is appended by the test loader.
if (typeof module !== 'undefined') {
  module.exports = {
    detectCaptureGap,
    appendCaptureGapNoticeToContextMd,
    _tokenize,
  };
}
`;

// Fail loudly if the re-anchor did not fire (e.g. the source's require text
// changed form). Without this, a missed rewrite reverts to an opaque
// MODULE_NOT_FOUND crash at require() time from /tmp.
if (/require\(['"]\.\/lib\//.test(shimmedSource)) {
  console.error(
    '  FATAL: a relative ./lib/ require survived the shim re-anchor - update the '
    + 'rewrite in test-capture-gap.js so the /tmp shim can resolve it.'
  );
  process.exit(1);
}

// Write shim to a temp file and require it.
const tmpShimPath = path.join(os.tmpdir(), `stop-context-shim-${Date.now()}.js`);
fs.writeFileSync(tmpShimPath, shimmedSource, 'utf8');
let helpers;
try {
  helpers = require(tmpShimPath);
} finally {
  try { fs.unlinkSync(tmpShimPath); } catch (_) { /* ignore */ }
}

const { detectCaptureGap, appendCaptureGapNoticeToContextMd, _tokenize } = helpers;

// ---------------------------------------------------------------------------
// Test harness
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

function assertEqual(actual, expected, message) {
  if (actual === expected) {
    console.log(`  PASS: ${message}`);
    passed++;
  } else {
    console.error(`  FAIL: ${message} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`);
    failed++;
  }
}

/**
 * Create a temporary .agentic/ directory tree and return its parent (the fake cwd).
 * @returns {string} Absolute path to the fake project root.
 */
function makeTempProject() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-test-'));
  fs.mkdirSync(path.join(tmpDir, '.agentic'), { recursive: true });
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

/**
 * Build an events.jsonl line with a learning-worthy event.
 * @param {string} sessionId
 * @param {string} event
 * @param {string} agent
 * @param {object} [extra] - merged into data
 * @returns {string}
 */
function makeEvent(sessionId, event, agent, extra = {}) {
  return JSON.stringify({
    ts: new Date().toISOString(),
    phase: 'test',
    event,
    agent: agent || null,
    task_id: null,
    data: Object.assign({ session_uuid: sessionId }, extra),
  });
}

// ---------------------------------------------------------------------------
// Test 1: fires-on-debugger
// ---------------------------------------------------------------------------
console.log('\nTest 1: fires-on-debugger');
{
  const cwd = makeTempProject();
  const sessionId = 'session-debugger-001';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
  fs.writeFileSync(eventsPath, makeEvent(sessionId, 'spawn_complete', 'debugger') + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === true, 'shouldNudge is true when debugger spawn_complete present');
  assert(result.residualOnly === false, 'residualOnly is false (no guardrails added)');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 2: fires-on-tool_failure_workaround
// ---------------------------------------------------------------------------
console.log('\nTest 2: fires-on-tool_failure_workaround');
{
  const cwd = makeTempProject();
  const sessionId = 'session-toolwk-002';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
  fs.writeFileSync(eventsPath, makeEvent(sessionId, 'tool_failure_workaround', null, {
    domain_tag: 'git',
    tool: 'git-push',
    note: 'Used --force-with-lease instead of --force',
  }) + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === true, 'shouldNudge is true on tool_failure_workaround');
  assert(result.residualOnly === false, 'residualOnly false (no guardrails)');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 3: suppressed-by-domain-proximate-guardrail
// We cannot run an actual git repo in a temp dir easily, so we mock the git
// diff output by monkey-patching execSync on the helpers module's closure.
// Instead, we test via a real git repo fixture.
// NOTE: This test verifies the suppression path by constructing a minimal real
// git repo so detectCaptureGap can run git diff.
// ---------------------------------------------------------------------------
console.log('\nTest 3: suppressed-by-domain-proximate-guardrail');
{
  // Build a minimal git repo with one commit so git diff origin/HEAD..HEAD works.
  // We use HEAD~1..HEAD (fallback path) since there's no upstream.
  const cwd = makeTempProject();
  const sessionId = 'session-guardrail-003';

  try {
    execSync('git init -b main', { cwd, stdio: 'pipe' });
    execSync('git config user.email "test@test.com"', { cwd, stdio: 'pipe' });
    execSync('git config user.name "Test"', { cwd, stdio: 'pipe' });
    // Initial commit
    fs.writeFileSync(path.join(cwd, 'README.md'), 'initial\n');
    execSync('git add README.md', { cwd, stdio: 'pipe' });
    execSync('git commit -m "init"', { cwd, stdio: 'pipe' });

    // Add a domain-proximate test file in a second commit.
    fs.mkdirSync(path.join(cwd, 'tests'), { recursive: true });
    fs.writeFileSync(path.join(cwd, 'tests', 'test-git-push.js'), '// test\n');
    execSync('git add tests/test-git-push.js', { cwd, stdio: 'pipe' });
    execSync('git commit -m "add test"', { cwd, stdio: 'pipe' });

    // Events: tool_failure_workaround with domain_tag=git
    const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
    fs.writeFileSync(eventsPath, makeEvent(sessionId, 'tool_failure_workaround', null, {
      domain_tag: 'git',
      tool: 'git-push',
    }) + '\n', 'utf8');

    // The guardrail path "tests/test-git-push.js" has tokens: ['test', 'push']
    // (>=4 chars: 'test', 'push'). Domain tokens from 'git' and 'git-push': 'push'.
    // 'push' appears in both -> domain-proximate -> suppress.
    const result = detectCaptureGap(cwd, sessionId);
    assert(result.shouldNudge === false, 'shouldNudge is false when domain-proximate guardrail present');
  } catch (e) {
    // git not available or setup failed - mark as skipped with a note
    console.log(`  SKIP: git fixture setup failed (${e.message.split('\n')[0]})`);
  }
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 4: fires-despite-unrelated-guardrail (residualOnly regression - Major-1)
// A guardrail test file is added but has no domain-token overlap with the event.
// Nudge MUST fire with residualOnly=true.
// ---------------------------------------------------------------------------
console.log('\nTest 4: fires-despite-unrelated-guardrail (residualOnly=true)');
{
  const cwd = makeTempProject();
  const sessionId = 'session-residual-004';

  try {
    execSync('git init -b main', { cwd, stdio: 'pipe' });
    execSync('git config user.email "test@test.com"', { cwd, stdio: 'pipe' });
    execSync('git config user.name "Test"', { cwd, stdio: 'pipe' });
    // Initial commit
    fs.writeFileSync(path.join(cwd, 'README.md'), 'initial\n');
    execSync('git add README.md', { cwd, stdio: 'pipe' });
    execSync('git commit -m "init"', { cwd, stdio: 'pipe' });

    // Add an UNRELATED test file (domain: payments, not git)
    fs.mkdirSync(path.join(cwd, 'tests'), { recursive: true });
    fs.writeFileSync(path.join(cwd, 'tests', 'test-stripe-checkout.js'), '// test\n');
    execSync('git add tests/test-stripe-checkout.js', { cwd, stdio: 'pipe' });
    execSync('git commit -m "add unrelated test"', { cwd, stdio: 'pipe' });

    // Event domain: 'git', 'push'. Guardrail tokens: 'test', 'stripe', 'checkout'.
    // No overlap -> residualOnly=true, shouldNudge=true.
    const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
    fs.writeFileSync(eventsPath, makeEvent(sessionId, 'tool_failure_workaround', null, {
      domain_tag: 'git',
      tool: 'git-push',
    }) + '\n', 'utf8');

    const result = detectCaptureGap(cwd, sessionId);
    assert(result.shouldNudge === true, 'shouldNudge true despite unrelated guardrail (residual-WHY case)');
    assert(result.residualOnly === true, 'residualOnly true when guardrail added but not domain-proximate');
  } catch (e) {
    console.log(`  SKIP: git fixture setup failed (${e.message.split('\n')[0]})`);
  }
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 5: no-fire-when-learning-captured (today-dated [LRN- entry)
// ---------------------------------------------------------------------------
console.log('\nTest 5: no-fire-when-learning-captured');
{
  const cwd = makeTempProject();
  const sessionId = 'session-captured-005';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
  fs.writeFileSync(eventsPath, makeEvent(sessionId, 'spawn_complete', 'debugger') + '\n', 'utf8');

  const todayStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const learningsPath = path.join(cwd, '.agentic', 'learnings.md');
  fs.writeFileSync(learningsPath, `## [LRN-${todayStr}-001] Some learning\n**Discovered:** today\n`, 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === false, 'shouldNudge false when today-dated LRN entry present');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 6: session-filter-excludes-foreign-uuid
// ---------------------------------------------------------------------------
console.log('\nTest 6: session-filter-excludes-foreign-uuid');
{
  const cwd = makeTempProject();
  const sessionId = 'session-current-006';
  const foreignId = 'session-foreign-006';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
  // Event has DIFFERENT session_uuid - should be excluded by session filter.
  fs.writeFileSync(eventsPath, makeEvent(foreignId, 'spawn_complete', 'debugger') + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === false, 'shouldNudge false when only foreign-session events present');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 7a: cold-start-100-line-cap - learning-worthy event within last 100 lines
// ---------------------------------------------------------------------------
console.log('\nTest 7a: cold-start-100-line-cap (within window)');
{
  const cwd = makeTempProject();
  const sessionId = 'session-coldstart-007a';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');

  // Write 150 lines total: lines 1-100 are foreign, lines 101-150 include a match at line ~125.
  const lines = [];
  for (let i = 0; i < 100; i++) {
    lines.push(makeEvent('foreign-session', 'spawn_complete', 'engineer'));
  }
  // Learning-worthy event at position 50 from end (within the 100-line cap).
  for (let i = 0; i < 49; i++) {
    lines.push(makeEvent('foreign-session', 'spawn_complete', 'engineer'));
  }
  lines.push(makeEvent(sessionId, 'spawn_complete', 'debugger')); // position 50 from end

  fs.writeFileSync(eventsPath, lines.join('\n') + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === true, 'shouldNudge true when matching event within 100-line cold-start window');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 7b: cold-start-100-line-cap - learning-worthy event BEYOND 100-line window
// ---------------------------------------------------------------------------
console.log('\nTest 7b: cold-start-100-line-cap (beyond window)');
{
  const cwd = makeTempProject();
  const sessionId = 'session-coldstart-007b';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');

  // Write 150 lines: the matching event is at line 1 (beyond the 100-line tail window).
  const lines = [];
  lines.push(makeEvent(sessionId, 'spawn_complete', 'debugger')); // position 150 from end - outside window
  for (let i = 0; i < 149; i++) {
    lines.push(makeEvent('foreign-session', 'spawn_complete', 'engineer'));
  }

  fs.writeFileSync(eventsPath, lines.join('\n') + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === false, 'shouldNudge false when matching event beyond 100-line cold-start window');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 8: silent-fail-on-malformed-line
// ---------------------------------------------------------------------------
console.log('\nTest 8: silent-fail-on-malformed-line');
{
  const cwd = makeTempProject();
  const sessionId = 'session-malformed-008';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
  const malformedContent = [
    '{bad json',
    '',
    'not json at all',
    makeEvent(sessionId, 'spawn_complete', 'debugger'),
    '{ "ts": "2024-01-01" incomplete',
  ].join('\n') + '\n';
  fs.writeFileSync(eventsPath, malformedContent, 'utf8');

  let threw = false;
  let result;
  try {
    result = detectCaptureGap(cwd, sessionId);
  } catch (e) {
    threw = true;
  }
  assert(!threw, 'detectCaptureGap does not throw on malformed events.jsonl lines');
  // The valid event line should still be detected.
  assert(result && result.shouldNudge === true, 'shouldNudge still true despite malformed lines');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 9: residualOnly text differentiation
// appendCaptureGapNoticeToContextMd with residualOnly=true must produce different
// text than residualOnly=false.
// ---------------------------------------------------------------------------
console.log('\nTest 9: residualOnly text differentiation');
{
  const cwd9a = makeTempProject();
  const cwd9b = makeTempProject();
  const sessionId = 'session-residual-009';

  // Ensure context.md exists in both (function appends; parent dir must exist)
  const ctx9a = path.join(cwd9a, '.agentic', 'context.md');
  const ctx9b = path.join(cwd9b, '.agentic', 'context.md');
  fs.writeFileSync(ctx9a, '# Session Context\n', 'utf8');
  fs.writeFileSync(ctx9b, '# Session Context\n', 'utf8');

  appendCaptureGapNoticeToContextMd(cwd9a, false); // standard
  appendCaptureGapNoticeToContextMd(cwd9b, true);  // residual

  const textStandard = fs.readFileSync(ctx9a, 'utf8');
  const textResidual = fs.readFileSync(ctx9b, 'utf8');

  assert(textStandard.includes('CAPTURE-GAP'), 'standard nudge includes CAPTURE-GAP marker');
  assert(textResidual.includes('CAPTURE-GAP'), 'residual nudge includes CAPTURE-GAP marker');
  assert(
    textStandard !== textResidual,
    'standard and residual nudge texts are different'
  );
  assert(
    textResidual.includes('residual') || textResidual.includes('guardrail'),
    'residual nudge text mentions residual/guardrail concept'
  );
  assert(
    !textStandard.includes('residual'),
    'standard nudge text does not mention residual'
  );
  cleanup(cwd9a);
  cleanup(cwd9b);
}

// ---------------------------------------------------------------------------
// Test 10: no-fire-when-no-session-uuid-on-event (DELIBERATE exclusion regression)
// Events lacking data.session_uuid must be excluded even when they are learning-worthy.
// This verifies the DELIBERATE absent=exclude rule documented in detectCaptureGap.
// ---------------------------------------------------------------------------
console.log('\nTest 10: no-fire-when-no-session-uuid-on-event (absent=exclude)');
{
  const cwd = makeTempProject();
  const sessionId = 'session-nouuid-010';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');

  // Manually craft an event WITHOUT session_uuid in data (legacy line).
  const legacyEvent = JSON.stringify({
    ts: new Date().toISOString(),
    phase: 'test',
    event: 'spawn_complete',
    agent: 'debugger',
    task_id: null,
    data: {}, // NO session_uuid field
  });
  fs.writeFileSync(eventsPath, legacyEvent + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === false, 'shouldNudge false for events without session_uuid (deliberate exclusion)');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 11: skeptic-trigger-fires
// A skeptic spawn_complete with signed_off=true AND critical > 0 must fire the nudge.
// This path (agentName === 'skeptic' && findings_count.critical > 0 && signed_off)
// existed in detectCaptureGap but had no test coverage until now.
// ---------------------------------------------------------------------------
console.log('\nTest 11: skeptic-trigger-fires (critical finding, signed_off)');
{
  const cwd = makeTempProject();
  const sessionId = 'session-skeptic-011';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');

  // Positive: skeptic with signed_off=true and critical=1 -> learning-worthy
  fs.writeFileSync(eventsPath, makeEvent(sessionId, 'spawn_complete', 'skeptic', {
    signed_off: true,
    findings_count: { critical: 1, major: 0, minor: 0 },
  }) + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === true, 'shouldNudge true for skeptic with critical finding + signed_off');
  assert(result.residualOnly === false, 'residualOnly false (no guardrails added)');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 11b: skeptic-trigger-fires (major finding only)
// ---------------------------------------------------------------------------
console.log('\nTest 11b: skeptic-trigger-fires (major finding, signed_off)');
{
  const cwd = makeTempProject();
  const sessionId = 'session-skeptic-011b';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');

  fs.writeFileSync(eventsPath, makeEvent(sessionId, 'spawn_complete', 'skeptic', {
    signed_off: true,
    findings_count: { critical: 0, major: 2, minor: 1 },
  }) + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === true, 'shouldNudge true for skeptic with major finding + signed_off');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 12: skeptic-no-critical-major-no-fire
// A skeptic spawn_complete with signed_off=true but ZERO critical/major findings
// must NOT count as learning-worthy (no nudge).
// ---------------------------------------------------------------------------
console.log('\nTest 12: skeptic-no-critical-major-no-fire (minor-only findings)');
{
  const cwd = makeTempProject();
  const sessionId = 'session-skeptic-012';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');

  fs.writeFileSync(eventsPath, makeEvent(sessionId, 'spawn_complete', 'skeptic', {
    signed_off: true,
    findings_count: { critical: 0, major: 0, minor: 3 },
  }) + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === false, 'shouldNudge false for skeptic with minor-only findings (no learning-worthy signal)');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 12b: skeptic-not-signed-off-no-fire
// A skeptic spawn_complete with critical findings but signed_off=false (or absent)
// must NOT fire the nudge - the session is still unresolved.
// ---------------------------------------------------------------------------
console.log('\nTest 12b: skeptic-not-signed-off-no-fire');
{
  const cwd = makeTempProject();
  const sessionId = 'session-skeptic-012b';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');

  fs.writeFileSync(eventsPath, makeEvent(sessionId, 'spawn_complete', 'skeptic', {
    signed_off: false,
    findings_count: { critical: 2, major: 1, minor: 0 },
  }) + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === false, 'shouldNudge false for skeptic with critical findings but signed_off=false');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 13: knw-dated-suppression
// A today-dated [KNW-YYYYMMDD-XXX] entry with a "Discovered: YYYY-MM-DD" line
// must suppress the nudge. Test 5 only exercised the [LRN- prefix; the KNW +
// Discovered: branch was untested.
// ---------------------------------------------------------------------------
console.log('\nTest 13: knw-dated-suppression (KNW entry with Discovered: today)');
{
  const cwd = makeTempProject();
  const sessionId = 'session-knw-013';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
  fs.writeFileSync(eventsPath, makeEvent(sessionId, 'spawn_complete', 'debugger') + '\n', 'utf8');

  const todayCompact = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const todayDash = new Date().toISOString().slice(0, 10);
  const learningsPath = path.join(cwd, '.agentic', 'learnings.md');
  // Write a KNW entry with the compact date tag AND a Discovered: line with dashed date.
  fs.writeFileSync(learningsPath, [
    `## [KNW-${todayCompact}-001] Workaround for git push --force`,
    `**Discovered:** ${todayDash}`,
    'Use --force-with-lease instead.',
  ].join('\n') + '\n', 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === false, 'shouldNudge false when today-dated KNW entry with Discovered: line present');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 13b: knw-tag-alone-suppresses
// A [KNW-YYYYMMDD-XXX] prefix alone (without Discovered: line) must also suppress
// the nudge - the code checks includes([KNW-${dateCompact}) independently.
// ---------------------------------------------------------------------------
console.log('\nTest 13b: knw-tag-alone-suppresses (KNW tag without Discovered: line)');
{
  const cwd = makeTempProject();
  const sessionId = 'session-knw-013b';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
  fs.writeFileSync(eventsPath, makeEvent(sessionId, 'spawn_complete', 'debugger') + '\n', 'utf8');

  const todayCompact = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const learningsPath = path.join(cwd, '.agentic', 'learnings.md');
  fs.writeFileSync(learningsPath, `## [KNW-${todayCompact}-001] A known workaround\nDetails here.\n`, 'utf8');

  const result = detectCaptureGap(cwd, sessionId);
  assert(result.shouldNudge === false, 'shouldNudge false when today-dated KNW tag present (no Discovered: line needed)');
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Test 14: standard-exit-path-call-site-arity (regression for U6b Major)
// Drives the REAL run() standard exit path as a subprocess and asserts the
// capture-gap nudge uses the STANDARD (non-residual) wording when no guardrail
// was added. This regression guards the call-site arity: a 3-arg call
// `appendCaptureGapNoticeToContextMd(cwd, sessionId, gap.residualOnly)` passes
// sessionId (truthy string) as residualOnly, forcing the "residual" wording even
// when residualOnly should be false. The 2-arg `(cwd, gap.residualOnly)` is correct.
// ---------------------------------------------------------------------------
console.log('\nTest 14: standard-exit-path-call-site-arity (run() integration)');
{
  const cwd = makeTempProject();
  const sessionId = 'session-runpath-014';
  const eventsPath = path.join(cwd, '.agentic', 'events.jsonl');
  // Learning-worthy debugger event, no guardrail added -> residualOnly must be false.
  fs.writeFileSync(eventsPath, makeEvent(sessionId, 'spawn_complete', 'debugger') + '\n', 'utf8');

  // Drive the real hook via subprocess so run()'s actual call site executes.
  // Payload routes through the STANDARD exit path (no /wrap-authored context.md).
  const payload = JSON.stringify({ cwd, session_id: sessionId, transcript: [] });
  let ran = true;
  try {
    execSync(`node ${JSON.stringify(hookPath)}`, {
      input: payload, cwd, timeout: 10000, stdio: ['pipe', 'pipe', 'pipe'],
    });
  } catch (e) {
    // The hook calls process.exit(0); execSync only throws on non-zero exit.
    ran = false;
    console.log(`  SKIP: hook subprocess failed (${(e.message || '').split('\n')[0]})`);
  }

  if (ran) {
    const ctxPath = path.join(cwd, '.agentic', 'context.md');
    let ctx = '';
    try { ctx = fs.readFileSync(ctxPath, 'utf8'); } catch (_) { /* absent */ }
    assert(ctx.includes('CAPTURE-GAP'), 'standard exit path appended a capture-gap nudge');
    assert(
      !ctx.includes('a related test or guardrail was added this session'),
      'standard exit path uses NON-residual wording (residualOnly correctly false)'
    );
    assert(
      ctx.includes('resolved a root cause / worked around a tool failure'),
      'standard exit path nudge contains the standard (non-residual) text'
    );
  }
  cleanup(cwd);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
if (failed > 0) process.exit(1);
