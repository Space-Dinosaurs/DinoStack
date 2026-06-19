#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/settings-migrate.py - install/uninstall migration.
 *
 * Cases:
 *   SM1  - mika + plugin survival: entries containing '*-mika.py' or plugin
 *          paths survive BOTH install AND uninstall.
 *   SM2  - FALSE-POSITIVE REGRESSION (mandated by U6 Skeptic): user hooks
 *          'node /Users/jane/.claude/hooks/my-stop-context.js' and
 *          'bash /Users/jane/.claude/hooks/my-session-start-wrap.sh' are NOT
 *          pruned on install or uninstall - they are user-owned hooks whose
 *          filenames merely contain a legacy basename as a suffix, not a
 *          path-segment-anchored match. This guards the data-loss bug fixed
 *          by the path-segment-anchored predicate.
 *   SM3  - genuine agentic entries are pruned:
 *          (a) old absolute 'stop-context.js' path (path contains
 *              'agentic-engineering/hooks/stop-context.js')
 *          (b) the RISK echo command (contains the signature substring)
 *          (c) a stale 'session-start-version-check.sh' standalone entry
 *   SM4  - install registers exactly one dispatcher entry per event:
 *          UserPromptSubmit, Stop, SessionStart, SessionEnd under '*' matcher;
 *          PreToolUse under derived matchers from pretooluse.d/ leaves.
 *   SM5  - a .bak-* backup file is written on install.
 *   SM6  - second install is idempotent (byte-identical result, no duplicate entries).
 *   SM7  - uninstall removes all agentic dispatcher entries across all 5 events.
 *
 * All fixtures are temp files under the OS temp dir. The real ~/.claude/settings.json
 * is NEVER touched.
 *
 * Run with: node hooks/tests/test-settings-migrate.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const MIGRATE_PY = path.resolve(__dirname, '..', 'lib', 'settings-migrate.py');
const REPO_DIR = path.resolve(__dirname, '..', '..');

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

// Guard: migration script must exist
if (!fs.existsSync(MIGRATE_PY)) {
  console.error(`FAIL: settings-migrate.py not found at ${MIGRATE_PY}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Run the migration CLI. Returns { status, stdout, stderr }. */
function runMigrate(mode, settingsPath) {
  const result = spawnSync(
    'python3',
    [MIGRATE_PY, mode, REPO_DIR, settingsPath],
    { encoding: 'utf8', timeout: 15000 }
  );
  return { status: result.status, stdout: result.stdout || '', stderr: result.stderr || '' };
}

/** Write a temp settings.json with the given object. Returns its path. */
function writeTempSettings(obj) {
  const tmp = path.join(os.tmpdir(), `ae-migrate-test-${Date.now()}-${Math.random().toString(36).slice(2)}.json`);
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2) + '\n', 'utf8');
  return tmp;
}

/** Read and parse a settings.json. */
function readSettings(settingsPath) {
  return JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
}

/** Collect all hook command strings across all events and matcher blocks. */
function allCommands(settings) {
  const cmds = [];
  const hooks = settings.hooks || {};
  for (const blocks of Object.values(hooks)) {
    if (!Array.isArray(blocks)) continue;
    for (const block of blocks) {
      if (!block || !Array.isArray(block.hooks)) continue;
      for (const entry of block.hooks) {
        if (entry && typeof entry.command === 'string') cmds.push(entry.command);
      }
    }
  }
  return cmds;
}

/** Return true if any command in settings contains the given substring. */
function hasCommand(settings, substring) {
  return allCommands(settings).some(cmd => cmd.includes(substring));
}

// ---------------------------------------------------------------------------
// Test SM1: mika + plugin entries survive install and uninstall
// ---------------------------------------------------------------------------
console.log('\nTest SM1: mika + plugin entries survive install and uninstall');
{
  const mikaCmd = 'python3 /Users/jane/.claude/hooks/my-mika.py';
  const pluginCmd = 'node /Users/jane/.claude/plugins/my-plugin.js';
  const initial = {
    hooks: {
      UserPromptSubmit: [
        { matcher: '*', hooks: [{ type: 'command', command: mikaCmd, timeout: 10 }] },
        { matcher: '*', hooks: [{ type: 'command', command: pluginCmd, timeout: 10 }] },
      ],
    },
  };
  const tmp = writeTempSettings(initial);
  try {
    // Install
    const installResult = runMigrate('install', tmp);
    assertEqual(installResult.status, 0, 'SM1: install exits 0');
    const afterInstall = readSettings(tmp);
    assert(hasCommand(afterInstall, mikaCmd), 'SM1: mika command survives install');
    assert(hasCommand(afterInstall, pluginCmd), 'SM1: plugin command survives install');

    // Uninstall
    const uninstallResult = runMigrate('uninstall', tmp);
    assertEqual(uninstallResult.status, 0, 'SM1: uninstall exits 0');
    const afterUninstall = readSettings(tmp);
    assert(hasCommand(afterUninstall, mikaCmd), 'SM1: mika command survives uninstall');
    assert(hasCommand(afterUninstall, pluginCmd), 'SM1: plugin command survives uninstall');
  } finally {
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
    // Clean up any backup files
    const dir = path.dirname(tmp);
    const base = path.basename(tmp);
    try {
      for (const f of fs.readdirSync(dir)) {
        if (f.startsWith(base + '.bak-')) {
          try { fs.unlinkSync(path.join(dir, f)); } catch (_) { /* ignore */ }
        }
      }
    } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Test SM2: FALSE-POSITIVE REGRESSION
//   User hooks 'node .../my-stop-context.js' and 'bash .../my-session-start-wrap.sh'
//   are NOT pruned on install or uninstall.
//   The basename 'stop-context.js' appears in 'my-stop-context.js' as a SUFFIX
//   (preceded by 'my-'), NOT as a path-segment-anchored match. The predicate
//   requires the basename to be preceded by '/' (or start-of-string), so the
//   user hook must survive.
// ---------------------------------------------------------------------------
console.log('\nTest SM2: FALSE-POSITIVE REGRESSION - user hooks with legacy-basename suffix survive');
{
  const userStopCmd = 'node /Users/jane/.claude/hooks/my-stop-context.js';
  const userSessionCmd = 'bash /Users/jane/.claude/hooks/my-session-start-wrap.sh';
  const initial = {
    hooks: {
      Stop: [
        { matcher: '*', hooks: [{ type: 'command', command: userStopCmd, timeout: 10 }] },
      ],
      SessionStart: [
        { matcher: '*', hooks: [{ type: 'command', command: userSessionCmd, timeout: 10 }] },
      ],
    },
  };
  const tmp = writeTempSettings(initial);
  try {
    // Install: user hooks must survive even though their names contain legacy basenames
    const installResult = runMigrate('install', tmp);
    assertEqual(installResult.status, 0, 'SM2: install exits 0');
    const afterInstall = readSettings(tmp);
    assert(
      hasCommand(afterInstall, userStopCmd),
      'SM2: user my-stop-context.js survives install (basename suffix is not a path-segment match)'
    );
    assert(
      hasCommand(afterInstall, userSessionCmd),
      'SM2: user my-session-start-wrap.sh survives install (basename suffix not matched)'
    );

    // Uninstall: user hooks must still survive
    const uninstallResult = runMigrate('uninstall', tmp);
    assertEqual(uninstallResult.status, 0, 'SM2: uninstall exits 0');
    const afterUninstall = readSettings(tmp);
    assert(
      hasCommand(afterUninstall, userStopCmd),
      'SM2: user my-stop-context.js survives uninstall (false-positive regression guard)'
    );
    assert(
      hasCommand(afterUninstall, userSessionCmd),
      'SM2: user my-session-start-wrap.sh survives uninstall (false-positive regression guard)'
    );
  } finally {
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
    const dir = path.dirname(tmp);
    const base = path.basename(tmp);
    try {
      for (const f of fs.readdirSync(dir)) {
        if (f.startsWith(base + '.bak-')) {
          try { fs.unlinkSync(path.join(dir, f)); } catch (_) { /* ignore */ }
        }
      }
    } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Test SM3: genuine agentic entries are pruned
// ---------------------------------------------------------------------------
console.log('\nTest SM3: genuine agentic entries are pruned');
{
  const oldAbsoluteCmd = 'node /Users/dev/repos/agentic-engineering/hooks/stop-context.js';
  const riskEchoCmd = 'echo "BEFORE ANY ACTION: classify risk first" >> /tmp/risk.log';
  const staleVersionCheckCmd = 'bash /Users/dev/repos/agentic-engineering/hooks/session-start-version-check.sh';
  const initial = {
    hooks: {
      Stop: [
        { matcher: '*', hooks: [{ type: 'command', command: oldAbsoluteCmd, timeout: 10 }] },
      ],
      UserPromptSubmit: [
        { matcher: '*', hooks: [{ type: 'command', command: riskEchoCmd, timeout: 10 }] },
      ],
      SessionStart: [
        { matcher: '*', hooks: [{ type: 'command', command: staleVersionCheckCmd, timeout: 10 }] },
      ],
    },
  };
  const tmp = writeTempSettings(initial);
  try {
    const result = runMigrate('uninstall', tmp);
    assertEqual(result.status, 0, 'SM3: uninstall exits 0');
    const afterUninstall = readSettings(tmp);
    assert(!hasCommand(afterUninstall, oldAbsoluteCmd),
      'SM3: old absolute stop-context.js path is pruned');
    assert(!hasCommand(afterUninstall, riskEchoCmd),
      'SM3: risk-echo signature command is pruned');
    assert(!hasCommand(afterUninstall, staleVersionCheckCmd),
      'SM3: stale session-start-version-check.sh is pruned');
  } finally {
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Test SM4: install registers exactly one dispatcher entry per event
// ---------------------------------------------------------------------------
console.log('\nTest SM4: install registers exactly one dispatcher entry per event');
{
  const tmp = writeTempSettings({});
  try {
    const result = runMigrate('install', tmp);
    assertEqual(result.status, 0, 'SM4: install exits 0');
    const settings = readSettings(tmp);
    const hooks = settings.hooks || {};

    // UserPromptSubmit, Stop, SessionStart, SessionEnd: exactly one entry each
    for (const event of ['UserPromptSubmit', 'Stop', 'SessionStart', 'SessionEnd']) {
      const blocks = hooks[event] || [];
      const dispatcherCmds = [];
      for (const block of blocks) {
        if (!Array.isArray(block.hooks)) continue;
        for (const entry of block.hooks) {
          if (entry && typeof entry.command === 'string' && entry.command.includes('dino-dispatch.py')) {
            dispatcherCmds.push(entry.command);
          }
        }
      }
      assertEqual(dispatcherCmds.length, 1, `SM4: exactly one dispatcher entry for ${event}`);
      assert(
        dispatcherCmds[0] && dispatcherCmds[0].includes(` ${event}`),
        `SM4: dispatcher entry for ${event} references event name`
      );
    }

    // PreToolUse: at least one dispatcher entry (one per derived matcher)
    const ptuBlocks = hooks['PreToolUse'] || [];
    const ptuDispatcherCmds = [];
    for (const block of ptuBlocks) {
      if (!Array.isArray(block.hooks)) continue;
      for (const entry of block.hooks) {
        if (entry && typeof entry.command === 'string' && entry.command.includes('dino-dispatch.py')) {
          ptuDispatcherCmds.push(entry.command);
        }
      }
    }
    assert(ptuDispatcherCmds.length >= 1, 'SM4: at least one PreToolUse dispatcher entry registered');
    assert(
      ptuDispatcherCmds.every(cmd => cmd.includes('PreToolUse')),
      'SM4: all PreToolUse dispatcher entries reference PreToolUse'
    );
  } finally {
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
    const dir = path.dirname(tmp);
    const base = path.basename(tmp);
    try {
      for (const f of fs.readdirSync(dir)) {
        if (f.startsWith(base + '.bak-')) {
          try { fs.unlinkSync(path.join(dir, f)); } catch (_) { /* ignore */ }
        }
      }
    } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Test SM5: a .bak-* backup file is written on install
// ---------------------------------------------------------------------------
console.log('\nTest SM5: .bak-* backup file written on install');
{
  const tmp = writeTempSettings({ hooks: {} });
  const dir = path.dirname(tmp);
  const base = path.basename(tmp);
  try {
    const result = runMigrate('install', tmp);
    assertEqual(result.status, 0, 'SM5: install exits 0');
    // Find a backup file matching <tmp>.bak-*
    const files = fs.readdirSync(dir);
    const bakFiles = files.filter(f => f.startsWith(base + '.bak-'));
    assert(bakFiles.length >= 1, 'SM5: at least one .bak-* backup file written on install');
  } finally {
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
    try {
      for (const f of fs.readdirSync(dir)) {
        if (f.startsWith(base + '.bak-')) {
          try { fs.unlinkSync(path.join(dir, f)); } catch (_) { /* ignore */ }
        }
      }
    } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Test SM6: second install is idempotent (byte-identical result)
// ---------------------------------------------------------------------------
console.log('\nTest SM6: second install is idempotent (byte-identical result)');
{
  const tmp = writeTempSettings({});
  const dir = path.dirname(tmp);
  const base = path.basename(tmp);
  try {
    const r1 = runMigrate('install', tmp);
    assertEqual(r1.status, 0, 'SM6: first install exits 0');
    const afterFirst = fs.readFileSync(tmp, 'utf8');

    const r2 = runMigrate('install', tmp);
    assertEqual(r2.status, 0, 'SM6: second install exits 0');
    const afterSecond = fs.readFileSync(tmp, 'utf8');

    assertEqual(afterFirst, afterSecond, 'SM6: second install is byte-identical to first (idempotent)');

    // Also verify no duplicate dispatcher entries after second install
    const settings = readSettings(tmp);
    const hooks = settings.hooks || {};
    for (const event of ['UserPromptSubmit', 'Stop', 'SessionStart', 'SessionEnd']) {
      const blocks = hooks[event] || [];
      let count = 0;
      for (const block of blocks) {
        if (!Array.isArray(block.hooks)) continue;
        for (const entry of block.hooks) {
          if (entry && typeof entry.command === 'string' && entry.command.includes('dino-dispatch.py')) {
            count++;
          }
        }
      }
      assertEqual(count, 1, `SM6: still exactly one dispatcher entry for ${event} after second install`);
    }
  } finally {
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
    try {
      for (const f of fs.readdirSync(dir)) {
        if (f.startsWith(base + '.bak-')) {
          try { fs.unlinkSync(path.join(dir, f)); } catch (_) { /* ignore */ }
        }
      }
    } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Test SM7: uninstall removes all agentic dispatcher entries across all 5 events
// ---------------------------------------------------------------------------
console.log('\nTest SM7: uninstall removes all agentic dispatcher entries across all 5 events');
{
  const tmp = writeTempSettings({});
  const dir = path.dirname(tmp);
  const base = path.basename(tmp);
  try {
    // First install to populate entries
    const installResult = runMigrate('install', tmp);
    assertEqual(installResult.status, 0, 'SM7: install exits 0');

    // Verify entries are present after install
    const afterInstall = readSettings(tmp);
    assert(hasCommand(afterInstall, 'dino-dispatch.py'), 'SM7: dispatcher entries present after install');

    // Now uninstall
    const uninstallResult = runMigrate('uninstall', tmp);
    assertEqual(uninstallResult.status, 0, 'SM7: uninstall exits 0');

    const afterUninstall = readSettings(tmp);
    assert(!hasCommand(afterUninstall, 'dino-dispatch.py'),
      'SM7: all dino-dispatch.py entries removed by uninstall');

    // Verify no hooks key remains if it was empty before
    const hooksAfter = afterUninstall.hooks || {};
    const remainingEvents = Object.keys(hooksAfter);
    // All 5 events should be absent (were empty before install, now cleaned)
    for (const event of ['UserPromptSubmit', 'Stop', 'SessionStart', 'SessionEnd', 'PreToolUse']) {
      assert(!(event in hooksAfter), `SM7: ${event} key removed from hooks after uninstall`);
    }
  } finally {
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
    try {
      for (const f of fs.readdirSync(dir)) {
        if (f.startsWith(base + '.bak-')) {
          try { fs.unlinkSync(path.join(dir, f)); } catch (_) { /* ignore */ }
        }
      }
    } catch (_) { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n--- Results: ${passed} passed, ${failed} failed ---`);
if (failed > 0) process.exit(1);
