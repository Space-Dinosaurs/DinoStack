#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/config-dir.js resolveClaudeConfigDir() - tilde
 * expansion and absolutization (round-2 fix for a Node/Python divergence
 * on a `~`-prefixed CLAUDE_CONFIG_DIR value; see bin/tests/test_lib.py's
 * sibling coverage of bin/_lib.py's resolve_claude_config_dir()).
 *
 * Test cases:
 *   1. tilde-prefixed-value-expanded: CLAUDE_CONFIG_DIR="~/.claude-alt"
 *      resolves to a path under os.homedir(), not a literal "~/..." string
 *      that can never exist on disk.
 *   2. bare-tilde-expanded: CLAUDE_CONFIG_DIR="~" alone resolves to
 *      os.homedir() exactly.
 *   3. relative-value-absolutized: a relative (non-`~`) CLAUDE_CONFIG_DIR
 *      value resolves to an absolute path via path.resolve().
 *   4. absolute-value-passthrough: an already-absolute value with no `~`
 *      resolves unchanged (spot-checks the happy path is not broken by
 *      the new expansion step).
 *
 * Run with: node hooks/tests/test-config-dir.js
 */

'use strict';

const os = require('os');
const path = require('path');

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

// Isolate module state across test cases (env-var driven, no module-level
// caching in config-dir.js, but re-require via a fresh cache key keeps
// this test independent of that fact).
function resolveWithEnv(envOverrides) {
  const prevEnv = {};
  const keys = ['AGENTIC_CONFIG_DIR', 'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'PI_CODING_AGENT_DIR'];
  for (const k of keys) prevEnv[k] = process.env[k];
  for (const k of keys) delete process.env[k];
  Object.assign(process.env, envOverrides);
  delete require.cache[require.resolve('../lib/config-dir.js')];
  const { resolveClaudeConfigDir } = require('../lib/config-dir.js');
  const result = resolveClaudeConfigDir();
  for (const k of keys) {
    if (prevEnv[k] === undefined) delete process.env[k];
    else process.env[k] = prevEnv[k];
  }
  delete require.cache[require.resolve('../lib/config-dir.js')];
  return result;
}

// ---------------------------------------------------------------------------
console.log('\nTest 1: tilde-prefixed-value-expanded');
{
  const result = resolveWithEnv({ CLAUDE_CONFIG_DIR: '~/.claude-alt' });
  const expected = path.join(os.homedir(), '.claude-alt');
  assert(result === expected, `~/.claude-alt expands to ${expected} (got: ${result})`);
  assert(!result.startsWith('~'), `result is never a literal unexpanded ~ path (got: ${result})`);
}

// ---------------------------------------------------------------------------
console.log('\nTest 2: bare-tilde-expanded');
{
  const result = resolveWithEnv({ CLAUDE_CONFIG_DIR: '~' });
  assert(result === os.homedir(), `bare ~ resolves to os.homedir() (got: ${result}, expected: ${os.homedir()})`);
}

// ---------------------------------------------------------------------------
console.log('\nTest 3: relative-value-absolutized');
{
  const result = resolveWithEnv({ CLAUDE_CONFIG_DIR: 'relative-config-dir' });
  assert(path.isAbsolute(result), `relative value absolutizes (got: ${result})`);
  assert(result === path.resolve('relative-config-dir'),
    `matches path.resolve() of the raw value (got: ${result})`);
}

// ---------------------------------------------------------------------------
console.log('\nTest 4: absolute-value-passthrough');
{
  const abs = path.join(os.tmpdir(), 'ae-config-dir-passthrough');
  const result = resolveWithEnv({ CLAUDE_CONFIG_DIR: abs });
  assert(result === abs, `already-absolute value passes through unchanged (got: ${result}, expected: ${abs})`);
}

// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
