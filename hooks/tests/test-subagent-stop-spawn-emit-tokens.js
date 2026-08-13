#!/usr/bin/env node
/**
 * Unit tests: subagent-stop-spawn-emit.js token resolution (post-DS-160
 * addition; see hooks/lib/config-dir.js and bin/ds-parse-subagent-usage for
 * the sibling Python-side fix of the same root cause).
 *
 * Test cases:
 *   1. transcript-found-tokens-summed:  a real transcript with two assistant
 *                                        turns under the SAME config dir the
 *                                        hook resolves -> data.tokens summed
 *                                        correctly, no tokens_note.
 *   2. transcript-not-found-descriptive-note: no transcript on disk (and no
 *                                        agent_id on the payload) -> exit 0,
 *                                        no crash, data.tokens_note is a
 *                                        descriptive string, and NO
 *                                        data.tokens key at all (never a
 *                                        zero-filled stand-in).
 *   3. transcript-oversized-skipped:    a transcript at/above
 *                                        MAX_TRANSCRIPT_BYTES (20 MiB) ->
 *                                        data.tokens_note ===
 *                                        "skipped (transcript too large)",
 *                                        no data.tokens key (never a
 *                                        partial sum of what was read).
 *   4. claude-config-dir-honored:       CLAUDE_CONFIG_DIR points at a
 *                                        redirected dir holding the real
 *                                        transcript; a DECOY transcript with
 *                                        different token counts sits under
 *                                        the default ~/.claude location
 *                                        (HOME patched via env) - the
 *                                        resolved tokens must match the
 *                                        CLAUDE_CONFIG_DIR-scoped transcript,
 *                                        not the decoy. Direct regression
 *                                        gate for the hardcoded-~/.claude bug.
 *   5. transcript-empty-file-never-zero-filled: a 0-byte transcript exists
 *                                        on disk -> data.tokens_note ===
 *                                        "unavailable (transcript
 *                                        unreadable)", no data.tokens key.
 *                                        Round-2 regression: prior to the
 *                                        fix this returned a zero-filled
 *                                        tokens object with NO note, the
 *                                        exact fabrication this module's
 *                                        header claims never happens.
 *   6. transcript-malformed-never-zero-filled: a transcript that exists and
 *                                        is wholly non-JSONL garbage ->
 *                                        same "unavailable (transcript
 *                                        unreadable)" note, no data.tokens
 *                                        key. Same round-2 regression as
 *                                        Test 5, different cause.
 *   7. transcript-exact-boundary-skipped: a transcript of EXACTLY
 *                                        MAX_TRANSCRIPT_BYTES (20 MiB, not
 *                                        20 MiB + padding like Test 3) ->
 *                                        still skipped ("skipped
 *                                        (transcript too large)"), pinning
 *                                        the "at or above" boundary
 *                                        (`>=`, not `>`) at the exact edge
 *                                        Test 3's padded fixture cannot
 *                                        exercise.
 *
 * Round-3 additions (never-fabricate + documented-blemish regressions):
 *   8. transcript-whitespace-only-never-zero-filled: a transcript that is
 *                                        all blank/whitespace lines (not
 *                                        0 bytes) -> same "unavailable
 *                                        (transcript unreadable)" outcome
 *                                        as an empty file.
 *   9. transcript-no-assistant-records-never-zero-filled: a transcript with
 *                                        only non-assistant (`type:"user"`)
 *                                        records -> same "unavailable
 *                                        (transcript unreadable)" outcome.
 *  10. transcript-usage-empty-object-never-zero-filled: every assistant
 *                                        record carries `usage: {}` -> no
 *                                        `data.tokens` key and a note,
 *                                        never a fabricated {0,0,0,0}
 *                                        (round-3 regression: previously
 *                                        counted as "parsed" on `usage`
 *                                        object presence alone).
 *  11. transcript-usage-nonnumeric-never-zero-filled: every usage field is
 *                                        a non-numeric string -> same
 *                                        outcome as Test 10 (round-3
 *                                        regression: previously coerced via
 *                                        `Number(x) || 0` and counted as
 *                                        "parsed").
 *  12. transcript-usage-negative-not-summed: a negative usage field is
 *                                        never summed and does not, by
 *                                        itself, count a record as parsed;
 *                                        a genuinely usable positive field
 *                                        in the SAME record is still summed
 *                                        and still counts.
 *  13. transcript-partial-valid-plus-malformed-summed-undisclosed:
 *                                        documents (does not fix) the
 *                                        accepted round-3 blemish - a
 *                                        transcript mixing one valid line
 *                                        with one malformed/truncated line
 *                                        emits a partial `data.tokens` sum
 *                                        with NO disclosure note.
 *  14. transcript-just-under-boundary-summed-not-skipped: a transcript at
 *                                        exactly MAX_TRANSCRIPT_BYTES - 1
 *                                        byte is summed normally, not
 *                                        skipped - pins the opposite edge
 *                                        of Test 7's `>=` boundary.
 *
 * Run with: node hooks/tests/test-subagent-stop-spawn-emit-tokens.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const hookPath = path.resolve(__dirname, '..', 'subagent-stop-spawn-emit.js');

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

function makeTmpDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function cleanup(dir) {
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

function assistantTurn(inputTokens, outputTokens, cacheCreation, cacheRead) {
  return JSON.stringify({
    type: 'assistant',
    timestamp: new Date().toISOString(),
    message: {
      model: 'claude-test',
      usage: {
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        cache_creation_input_tokens: cacheCreation,
        cache_read_input_tokens: cacheRead,
      },
    },
  });
}

// Round-3 helper: an assistant turn with an ARBITRARY usage object (rather
// than the four canonical numeric fields assistantTurn() always fills in),
// for exercising usage-empty-object / usage-nonnumeric / usage-negative
// states.
function assistantTurnWithUsage(usage) {
  return JSON.stringify({
    type: 'assistant',
    timestamp: new Date().toISOString(),
    message: {
      model: 'claude-test',
      usage,
    },
  });
}

// A non-assistant record (e.g. a user turn) - never contributes to the
// token sum and never counts as "parsed".
function userTurn() {
  return JSON.stringify({
    type: 'user',
    timestamp: new Date().toISOString(),
    message: { content: 'hello' },
  });
}

function runHook(payload, cwd, envOverrides) {
  const env = Object.assign({}, process.env, envOverrides || {});
  const res = spawnSync('node', [hookPath], {
    input: JSON.stringify(payload), cwd, timeout: 10000, encoding: 'utf8', env,
  });
  return { stdout: res.stdout || '', status: res.status };
}

function readEvents(projectCwd) {
  const eventsPath = path.join(projectCwd, '.agentic', 'events.jsonl');
  if (!fs.existsSync(eventsPath)) return [];
  return fs.readFileSync(eventsPath, 'utf8')
    .split('\n').filter(Boolean)
    .map(line => { try { return JSON.parse(line); } catch (_) { return null; } })
    .filter(Boolean);
}

// projectHashFromCwd mirrors the hook's own scheme: every '/' -> '-'.
function projectHash(cwd) {
  return cwd.replace(/\//g, '-');
}

function plantTranscript(configDir, projectCwd, sessionId, agentId, lines) {
  const dir = path.join(configDir, 'projects', projectHash(projectCwd), sessionId, 'subagents');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `agent-${agentId}.jsonl`), lines.join('\n') + '\n', 'utf8');
}

function stopPayload(cwd, sessionId, agentId, overrides) {
  return Object.assign({
    cwd,
    session_id: sessionId,
    agent_id: agentId,
    hook_event_name: 'SubagentStop',
  }, overrides || {});
}

// ---------------------------------------------------------------------------
console.log('\nTest 1: transcript-found-tokens-summed');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-001';
  const agentId = 'agent-tok-001';
  plantTranscript(configDir, projectCwd, sessionId, agentId, [
    assistantTurn(100, 50, 10, 5),
    assistantTurn(200, 80, 20, 15),
  ]);

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(!!data.tokens, `data.tokens present (got: ${JSON.stringify(data.tokens)})`);
    if (data.tokens) {
      assert(data.tokens.input === 300, `input summed to 300 (got: ${data.tokens.input})`);
      assert(data.tokens.output === 130, `output summed to 130 (got: ${data.tokens.output})`);
      assert(data.tokens.cache_creation === 30, `cache_creation summed to 30 (got: ${data.tokens.cache_creation})`);
      assert(data.tokens.cache_read === 20, `cache_read summed to 20 (got: ${data.tokens.cache_read})`);
    }
    assert(data.tokens_note === undefined, `no tokens_note on success (got: ${JSON.stringify(data.tokens_note)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 2: transcript-not-found-descriptive-note');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  // No transcript planted anywhere; no agent_id on the payload either -
  // resolveTranscriptPath cannot construct a primary path without one.
  const { status } = runHook(
    stopPayload(projectCwd, 'sess-tok-002', null),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0 (no crash)');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete still emitted');
  if (complete) {
    const data = complete.data || {};
    assert(typeof data.tokens_note === 'string' && data.tokens_note.length > 0,
      `tokens_note is a descriptive string (got: ${JSON.stringify(data.tokens_note)})`);
    assert(data.tokens === undefined,
      `no zero-filled tokens object when unresolved (got: ${JSON.stringify(data.tokens)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 3: transcript-oversized-skipped');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-003';
  const agentId = 'agent-tok-003';
  const dir = path.join(configDir, 'projects', projectHash(projectCwd), sessionId, 'subagents');
  fs.mkdirSync(dir, { recursive: true });
  const transcriptPath = path.join(dir, `agent-${agentId}.jsonl`);
  // Write a transcript at/above 20 MiB, padded with valid assistant-turn
  // lines so a naive "sum whatever we read" implementation WOULD produce a
  // non-zero partial sum if the size cap were not enforced.
  const line = assistantTurn(1000, 1000, 0, 0) + '\n';
  const bytesNeeded = 20 * 1024 * 1024 + 4096;
  const fd = fs.openSync(transcriptPath, 'w');
  let written = 0;
  while (written < bytesNeeded) {
    fs.writeSync(fd, line);
    written += line.length;
  }
  fs.closeSync(fd);
  const sizeBefore = fs.statSync(transcriptPath).size;
  assert(sizeBefore >= 20 * 1024 * 1024, `fixture transcript exceeds MAX_TRANSCRIPT_BYTES (got ${sizeBefore} bytes)`);

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(data.tokens_note === 'skipped (transcript too large)',
      `tokens_note === "skipped (transcript too large)" (got: ${JSON.stringify(data.tokens_note)})`);
    assert(data.tokens === undefined,
      `no partial-summed tokens for an oversized transcript (got: ${JSON.stringify(data.tokens)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 4: claude-config-dir-honored');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const redirectedConfigDir = makeTmpDir('ae-tok-redirected-');
  const decoyHome = makeTmpDir('ae-tok-decoyhome-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-004';
  const agentId = 'agent-tok-004';

  // Real transcript under the redirected CLAUDE_CONFIG_DIR.
  plantTranscript(redirectedConfigDir, projectCwd, sessionId, agentId, [
    assistantTurn(7, 3, 0, 0),
  ]);
  // Decoy transcript with DIFFERENT token counts under the default
  // ~/.claude location (HOME patched to decoyHome) - if the hook ignored
  // CLAUDE_CONFIG_DIR and fell back to HOME, it would read this instead.
  plantTranscript(path.join(decoyHome, '.claude'), projectCwd, sessionId, agentId, [
    assistantTurn(999, 999, 999, 999),
  ]);

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: redirectedConfigDir, AGENTIC_CONFIG_DIR: '', HOME: decoyHome }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(!!data.tokens, `data.tokens present (got: ${JSON.stringify(data.tokens)})`);
    if (data.tokens) {
      assert(data.tokens.input === 7,
        `tokens read from CLAUDE_CONFIG_DIR-scoped transcript, not the HOME decoy (got input=${data.tokens.input})`);
      assert(data.tokens.output === 3,
        `tokens read from CLAUDE_CONFIG_DIR-scoped transcript, not the HOME decoy (got output=${data.tokens.output})`);
    }
  }
  cleanup(projectCwd);
  cleanup(redirectedConfigDir);
  cleanup(decoyHome);
}

// ---------------------------------------------------------------------------
console.log('\nTest 5: transcript-empty-file-never-zero-filled');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-005';
  const agentId = 'agent-tok-005';
  const dir = path.join(configDir, 'projects', projectHash(projectCwd), sessionId, 'subagents');
  fs.mkdirSync(dir, { recursive: true });
  // 0-byte transcript: exists on disk, but has nothing to parse.
  fs.writeFileSync(path.join(dir, `agent-${agentId}.jsonl`), '', 'utf8');

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(data.tokens_note === 'unavailable (transcript unreadable)',
      `tokens_note === "unavailable (transcript unreadable)" (got: ${JSON.stringify(data.tokens_note)})`);
    assert(data.tokens === undefined,
      `no zero-filled tokens object for an empty transcript (got: ${JSON.stringify(data.tokens)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 6: transcript-malformed-never-zero-filled');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-006';
  const agentId = 'agent-tok-006';
  const dir = path.join(configDir, 'projects', projectHash(projectCwd), sessionId, 'subagents');
  fs.mkdirSync(dir, { recursive: true });
  // Wholly malformed: not JSON at all, on every line.
  fs.writeFileSync(
    path.join(dir, `agent-${agentId}.jsonl`),
    'this is not json\nneither is this }{\n\x00\x01garbage\n',
    'utf8'
  );

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(data.tokens_note === 'unavailable (transcript unreadable)',
      `tokens_note === "unavailable (transcript unreadable)" (got: ${JSON.stringify(data.tokens_note)})`);
    assert(data.tokens === undefined,
      `no zero-filled tokens object for a malformed transcript (got: ${JSON.stringify(data.tokens)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 7: transcript-exact-boundary-skipped');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-007';
  const agentId = 'agent-tok-007';
  const dir = path.join(configDir, 'projects', projectHash(projectCwd), sessionId, 'subagents');
  fs.mkdirSync(dir, { recursive: true });
  const transcriptPath = path.join(dir, `agent-${agentId}.jsonl`);
  // Exactly MAX_TRANSCRIPT_BYTES (20 MiB), no more, no less - pins the
  // "at or above" boundary (>=) that Test 3's padded fixture cannot.
  const MAX_TRANSCRIPT_BYTES = 20 * 1024 * 1024;
  const fd = fs.openSync(transcriptPath, 'w');
  fs.ftruncateSync(fd, MAX_TRANSCRIPT_BYTES);
  fs.closeSync(fd);
  const sizeBefore = fs.statSync(transcriptPath).size;
  assert(sizeBefore === MAX_TRANSCRIPT_BYTES, `fixture transcript is exactly MAX_TRANSCRIPT_BYTES (got ${sizeBefore} bytes)`);

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(data.tokens_note === 'skipped (transcript too large)',
      `tokens_note === "skipped (transcript too large)" at the exact boundary (got: ${JSON.stringify(data.tokens_note)})`);
    assert(data.tokens === undefined,
      `no tokens for a transcript at exactly the size boundary (got: ${JSON.stringify(data.tokens)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 8: transcript-whitespace-only-never-zero-filled');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-008';
  const agentId = 'agent-tok-008';
  const dir = path.join(configDir, 'projects', projectHash(projectCwd), sessionId, 'subagents');
  fs.mkdirSync(dir, { recursive: true });
  // Whitespace-only: not 0 bytes, but nothing but blank lines - same
  // "nothing usable parsed" outcome as an empty file.
  fs.writeFileSync(path.join(dir, `agent-${agentId}.jsonl`), '   \n\t\n   \n', 'utf8');

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(data.tokens_note === 'unavailable (transcript unreadable)',
      `tokens_note === "unavailable (transcript unreadable)" (got: ${JSON.stringify(data.tokens_note)})`);
    assert(data.tokens === undefined,
      `no zero-filled tokens object for a whitespace-only transcript (got: ${JSON.stringify(data.tokens)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 9: transcript-no-assistant-records-never-zero-filled');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-009';
  const agentId = 'agent-tok-009';
  plantTranscript(configDir, projectCwd, sessionId, agentId, [userTurn(), userTurn()]);

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(data.tokens_note === 'unavailable (transcript unreadable)',
      `tokens_note === "unavailable (transcript unreadable)" (got: ${JSON.stringify(data.tokens_note)})`);
    assert(data.tokens === undefined,
      `no zero-filled tokens object with zero assistant records (got: ${JSON.stringify(data.tokens)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 10: transcript-usage-empty-object-never-zero-filled (round-3 regression)');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-010';
  const agentId = 'agent-tok-010';
  // Every assistant record carries `usage: {}` - a `usage` OBJECT is
  // present but contributes no usable numeric field. Pre-round-3 this
  // counted as "parsed" (parsedCount incremented on `usage` presence alone)
  // and silently emitted tokens:{0,0,0,0} with NO note.
  plantTranscript(configDir, projectCwd, sessionId, agentId, [
    assistantTurnWithUsage({}),
    assistantTurnWithUsage({}),
  ]);

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(data.tokens_note === 'unavailable (transcript unreadable)',
      `tokens_note === "unavailable (transcript unreadable)" (got: ${JSON.stringify(data.tokens_note)})`);
    assert(data.tokens === undefined,
      `no fabricated {0,0,0,0} tokens for usage:{} records (got: ${JSON.stringify(data.tokens)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 11: transcript-usage-nonnumeric-never-zero-filled (round-3 regression)');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-011';
  const agentId = 'agent-tok-011';
  // Every usage field is a non-numeric string. Pre-round-3,
  // `Number(usage.input_tokens) || 0` silently coerced this to 0 and still
  // counted the record as "parsed" (usage object was present).
  plantTranscript(configDir, projectCwd, sessionId, agentId, [
    assistantTurnWithUsage({
      input_tokens: 'not-a-number',
      output_tokens: 'also-not',
      cache_creation_input_tokens: 'nope',
      cache_read_input_tokens: 'nope',
    }),
  ]);

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(data.tokens_note === 'unavailable (transcript unreadable)',
      `tokens_note === "unavailable (transcript unreadable)" (got: ${JSON.stringify(data.tokens_note)})`);
    assert(data.tokens === undefined,
      `no fabricated tokens for non-numeric usage values (got: ${JSON.stringify(data.tokens)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 12: transcript-usage-negative-not-summed (round-3 regression)');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-012';
  const agentId = 'agent-tok-012';
  // A negative usage value must never be summed (a negative token count is
  // not a real measurement) but a genuinely usable positive field in the
  // SAME record must still be summed and still count the record as parsed.
  plantTranscript(configDir, projectCwd, sessionId, agentId, [
    assistantTurnWithUsage({
      input_tokens: -100,
      output_tokens: 5,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 0,
    }),
  ]);

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(!!data.tokens, `data.tokens present (got: ${JSON.stringify(data.tokens)})`);
    if (data.tokens) {
      assert(data.tokens.input === 0,
        `negative input_tokens NOT summed (got: ${data.tokens.input})`);
      assert(data.tokens.output === 5,
        `positive output_tokens in the same record still summed (got: ${data.tokens.output})`);
    }
    assert(data.tokens_note === undefined,
      `no tokens_note when a usable positive field was found (got: ${JSON.stringify(data.tokens_note)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 13: transcript-partial-valid-plus-malformed-summed-undisclosed');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-013';
  const agentId = 'agent-tok-013';
  const dir = path.join(configDir, 'projects', projectHash(projectCwd), sessionId, 'subagents');
  fs.mkdirSync(dir, { recursive: true });
  // One valid assistant turn plus one truncated/malformed line (simulating
  // a transcript captured mid-write). Documented blemish (round-3, see
  // module header "Known, documented blemish"): the malformed line is
  // silently skipped and the partial sum is reported with NO note
  // disclosing that some lines failed to parse - this test pins that
  // documented (not fixed) behavior so a future change to it is deliberate.
  const lines = [assistantTurn(10, 5, 0, 0), '{"type":"assistant","message":{"usage":{"in'];
  fs.writeFileSync(path.join(dir, `agent-${agentId}.jsonl`), lines.join('\n') + '\n', 'utf8');

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(!!data.tokens, `data.tokens present (got: ${JSON.stringify(data.tokens)})`);
    if (data.tokens) {
      assert(data.tokens.input === 10, `partial sum from the valid line only (got: ${data.tokens.input})`);
      assert(data.tokens.output === 5, `partial sum from the valid line only (got: ${data.tokens.output})`);
    }
    assert(data.tokens_note === undefined,
      `documented blemish: no disclosure note for a partial sum (got: ${JSON.stringify(data.tokens_note)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log('\nTest 14: transcript-just-under-boundary-summed-not-skipped');
{
  const projectCwd = makeTmpDir('ae-tok-proj-');
  const configDir = makeTmpDir('ae-tok-cfg-');
  fs.mkdirSync(path.join(projectCwd, '.agentic'), { recursive: true });
  const sessionId = 'sess-tok-014';
  const agentId = 'agent-tok-014';
  const dir = path.join(configDir, 'projects', projectHash(projectCwd), sessionId, 'subagents');
  fs.mkdirSync(dir, { recursive: true });
  const transcriptPath = path.join(dir, `agent-${agentId}.jsonl`);
  // Exactly MAX_TRANSCRIPT_BYTES - 1 byte, so the `>=` boundary must NOT
  // trip - pins the opposite edge from Test 7.
  const MAX_TRANSCRIPT_BYTES = 20 * 1024 * 1024;
  const turnLine = assistantTurn(3, 2, 0, 0) + '\n';
  const padTarget = MAX_TRANSCRIPT_BYTES - 1 - turnLine.length;
  const padding = 'x'.repeat(Math.max(0, padTarget));
  const fd = fs.openSync(transcriptPath, 'w');
  fs.writeSync(fd, turnLine);
  fs.writeSync(fd, padding);
  fs.closeSync(fd);
  const sizeBefore = fs.statSync(transcriptPath).size;
  assert(sizeBefore === MAX_TRANSCRIPT_BYTES - 1,
    `fixture transcript is exactly MAX_TRANSCRIPT_BYTES - 1 (got ${sizeBefore} bytes)`);

  const { status } = runHook(
    stopPayload(projectCwd, sessionId, agentId),
    projectCwd,
    { CLAUDE_CONFIG_DIR: configDir, AGENTIC_CONFIG_DIR: '' }
  );
  assert(status === 0, 'hook exits 0');
  const events = readEvents(projectCwd);
  const complete = events.find(e => e.event === 'spawn_complete');
  assert(!!complete, 'spawn_complete emitted');
  if (complete) {
    const data = complete.data || {};
    assert(!!data.tokens, `data.tokens present, not skipped, one byte under the boundary (got: ${JSON.stringify(data.tokens)})`);
    if (data.tokens) {
      assert(data.tokens.input === 3, `tokens summed just under the size boundary (got: ${data.tokens.input})`);
    }
    assert(data.tokens_note === undefined,
      `no tokens_note when just under the size boundary (got: ${JSON.stringify(data.tokens_note)})`);
  }
  cleanup(projectCwd);
  cleanup(configDir);
}

// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
