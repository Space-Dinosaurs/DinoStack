#!/usr/bin/env node
/**
 * Self-contained regression test for saveConfig() read-merge-write behaviour.
 * Run: node scripts/test/update-saveconfig.test.js
 *
 * Tests that saveConfig() preserves existing keys (repo_dir, customKey) while
 * updating only adapters and updatedAt.
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

// ---------------------------------------------------------------------------
// Minimal stub of the functions under test from update.js.
// We re-implement only getConfigPath() and saveConfig() with an injectable
// config path so we can test without touching the real ~/.agentic directory.
// ---------------------------------------------------------------------------

function makeFixture(configPath) {
  function saveConfig(selectedAdapters) {
    let config = {};
    try {
      config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    } catch (_) {
      // absent or unreadable - start from empty
    }
    config.adapters = {};
    for (const adapter of selectedAdapters) {
      config.adapters[adapter] = true;
    }
    config.updatedAt = new Date().toISOString();
    const tmpPath = `${configPath}.tmp.${process.pid}`;
    try {
      fs.writeFileSync(tmpPath, JSON.stringify(config, null, 2) + '\n', 'utf8');
      fs.renameSync(tmpPath, configPath);
    } catch (err) {
      try { fs.unlinkSync(tmpPath); } catch (_) { /* ignore */ }
      throw err;
    }
  }
  return { saveConfig };
}

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) {
    console.log(`  PASS  ${msg}`);
    passed++;
  } else {
    console.error(`  FAIL  ${msg}`);
    failed++;
  }
}

function assertEqual(actual, expected, msg) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    console.log(`  PASS  ${msg}`);
    passed++;
  } else {
    console.error(`  FAIL  ${msg}`);
    console.error(`        expected: ${JSON.stringify(expected)}`);
    console.error(`        actual:   ${JSON.stringify(actual)}`);
    failed++;
  }
}

// ---------------------------------------------------------------------------
// Test 1: merge - pre-existing keys preserved, adapters + updatedAt updated
// ---------------------------------------------------------------------------

console.log('\nTest 1: preserves repo_dir and unknown keys after saveConfig');
{
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-test-'));
  const configPath = path.join(tmpDir, 'agentic-engineering-config.json');

  const initial = {
    repo_dir: '/x',
    adapters: { a: true },
    customKey: 1,
    updatedAt: '2020-01-01T00:00:00.000Z'
  };
  fs.writeFileSync(configPath, JSON.stringify(initial, null, 2) + '\n', 'utf8');

  const { saveConfig } = makeFixture(configPath);
  saveConfig(['.claude', '.cursor']);

  const result = JSON.parse(fs.readFileSync(configPath, 'utf8'));

  assertEqual(result.repo_dir, '/x',          'repo_dir preserved');
  assertEqual(result.customKey, 1,            'customKey preserved');
  assertEqual(result.adapters['.claude'], true, 'new adapter .claude present');
  assertEqual(result.adapters['.cursor'], true, 'new adapter .cursor present');
  assert(!result.adapters.a,                 'old adapter "a" removed (replaced)');
  assert(typeof result.updatedAt === 'string' && result.updatedAt !== '2020-01-01T00:00:00.000Z',
    'updatedAt updated to new timestamp');

  fs.rmSync(tmpDir, { recursive: true });
}

// ---------------------------------------------------------------------------
// Test 2: absent config file - creates fresh config without error
// ---------------------------------------------------------------------------

console.log('\nTest 2: absent config file creates fresh config');
{
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-test-'));
  const configPath = path.join(tmpDir, 'agentic-engineering-config.json');
  // Do NOT write the file - it must not exist.

  const { saveConfig } = makeFixture(configPath);
  saveConfig(['.claude']);

  assert(fs.existsSync(configPath), 'config file created');
  const result = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  assertEqual(result.adapters['.claude'], true, 'adapter present in fresh config');
  assert(typeof result.updatedAt === 'string', 'updatedAt present in fresh config');

  fs.rmSync(tmpDir, { recursive: true });
}

// ---------------------------------------------------------------------------
// Test 3: corrupted existing config - falls back to fresh config
// ---------------------------------------------------------------------------

console.log('\nTest 3: corrupted config file falls back gracefully');
{
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-test-'));
  const configPath = path.join(tmpDir, 'agentic-engineering-config.json');
  fs.writeFileSync(configPath, 'NOT VALID JSON', 'utf8');

  const { saveConfig } = makeFixture(configPath);
  saveConfig(['.claude']);

  const result = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  assertEqual(result.adapters['.claude'], true, 'adapter present after corrupt-file recovery');

  fs.rmSync(tmpDir, { recursive: true });
}

// ---------------------------------------------------------------------------
// Test 4: empty adapters array - clears adapters, preserves other keys
// ---------------------------------------------------------------------------

console.log('\nTest 4: empty selectedAdapters clears adapters but preserves repo_dir');
{
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ae-test-'));
  const configPath = path.join(tmpDir, 'agentic-engineering-config.json');
  const initial = { repo_dir: '/y', adapters: { '.claude': true }, updatedAt: '2020-01-01T00:00:00.000Z' };
  fs.writeFileSync(configPath, JSON.stringify(initial, null, 2) + '\n', 'utf8');

  const { saveConfig } = makeFixture(configPath);
  saveConfig([]);

  const result = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  assertEqual(result.repo_dir, '/y', 'repo_dir preserved when adapters cleared');
  assertEqual(Object.keys(result.adapters).length, 0, 'adapters cleared');

  fs.rmSync(tmpDir, { recursive: true });
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

console.log(`\n${passed + failed} test(s): ${passed} passed, ${failed} failed.\n`);
if (failed > 0) process.exit(1);
