#!/usr/bin/env node

/**
 * Purpose: Interactive updater for agentic-engineering. Presents a TUI
 *          multi-select menu of adapters, runs git pull --ff-only
 *          origin main, and executes each selected adapter's install.sh.
 *
 * Public API: main() — CLI entry point. Called directly when the file is
 *             executed as a script.
 *
 * Upstream deps: Node built-ins (fs, path, child_process, readline). No
 *                external packages.
 *
 * Downstream consumers: update.sh (shell shim that delegates here).
 *
 * Failure modes: Exits with non-zero code on fatal errors (missing repo,
 *                git not on PATH, pull failure). Safe to retry; idempotent
 *                adapter installs and config writes.
 *
 * Performance: Standard. TUI is synchronous; git and install script
 *              operations block until completion.
 *
 * Usage: node scripts/update.js <repo_dir>
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { spawn, spawnSync } = require('child_process');
const readline = require('readline');

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

function getConfigPath() {
  const home = process.env.HOME || process.env.USERPROFILE || '.';
  const configDir = path.join(home, '.agentic');
  try {
    fs.mkdirSync(configDir, { recursive: true });
  } catch (_) {
    // ignore
  }
  return path.join(configDir, 'agentic-engineering-config.json');
}

function loadConfig() {
  const configPath = getConfigPath();
  try {
    const data = fs.readFileSync(configPath, 'utf8');
    return JSON.parse(data);
  } catch (_) {
    return null;
  }
}

function saveConfig(selectedAdapters) {
  const configPath = getConfigPath();
  const config = {
    adapters: {},
    updatedAt: new Date().toISOString()
  };
  for (const adapter of selectedAdapters) {
    config.adapters[adapter] = true;
  }
  try {
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2) + '\n', 'utf8');
  } catch (err) {
    console.error(`Warning: failed to write config: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// Adapter discovery
// ---------------------------------------------------------------------------

const SKIP_DIRS = new Set([
  '.', '..', '.git', '.github', '.vscode', '.idea',
  '.cache', '.venv', '.mypy_cache', '.pytest_cache', '.ruff_cache'
]);

function discoverAdapters(repoDir) {
  const adapters = [];
  try {
    const entries = fs.readdirSync(repoDir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const name = entry.name;
      if (!name.startsWith('.')) continue;
      if (SKIP_DIRS.has(name)) continue;
      const installPath = path.join(repoDir, name, 'install.sh');
      if (fs.existsSync(installPath)) {
        adapters.push(name);
      }
    }
  } catch (err) {
    console.error(`Error discovering adapters: ${err.message}`);
    process.exit(1);
  }
  // Case-insensitive alphabetical sort
  adapters.sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
  return adapters;
}

// ---------------------------------------------------------------------------
// Display names
// ---------------------------------------------------------------------------

const DISPLAY_NAMES = {
  claude:   'Claude',
  codex:    'Codex',
  cursor:   'Cursor',
  gemini:   'Gemini',
  opencode: 'OpenCode',
  kimi:     'Kimi',
  omp:      'Pi',
};

function displayName(raw) {
  const stripped = raw.replace(/^\./, '');
  if (DISPLAY_NAMES[stripped]) return DISPLAY_NAMES[stripped];
  return stripped.charAt(0).toUpperCase() + stripped.slice(1).toLowerCase();
}

// ---------------------------------------------------------------------------
// Git helpers
// ---------------------------------------------------------------------------

function git(worktree, ...args) {
  try {
    const result = spawnSync('git', ['-C', worktree, ...args], {
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe']
    });
    if (result.status !== 0) {
      return {
        success: false,
        stdout: '',
        stderr: result.stderr ? result.stderr.toString() : ''
      };
    }
    return { success: true, stdout: (result.stdout || '').trim() };
  } catch (err) {
    return { success: false, stdout: '', stderr: err.message };
  }
}

function getCurrentBranch(repoDir) {
  const result = git(repoDir, 'rev-parse', '--abbrev-ref', 'HEAD');
  return result.success ? result.stdout : 'unknown';
}

function isWorkingTreeDirty(repoDir) {
  const result = git(repoDir, 'status', '--porcelain');
  return result.success && result.stdout.length > 0;
}

function getDirtyFiles(repoDir) {
  const result = git(repoDir, 'status', '--porcelain');
  if (!result.success) return { staged: [], unstaged: [], untracked: [] };
  const lines = result.stdout.split('\n').filter(l => l.trim());
  const staged = [];
  const unstaged = [];
  const untracked = [];
  for (const line of lines) {
    const status = line.slice(0, 2);
    let file = line.slice(3);
    // Porcelain v1 renames/copies are formatted as "old -> new". Capture only
    // the new path so warning output does not show the entire arrow form.
    if (status[0] === 'R' || status[0] === 'C') {
      const match = file.match(/^(.+?) -> (.+)$/);
      if (match) file = match[2];
    }
    if (status.includes('?')) {
      untracked.push(file);
    } else if (status[0] !== ' ' && status[0] !== '?') {
      staged.push(file);
    } else if (status[1] !== ' ') {
      unstaged.push(file);
    }
  }
  return { staged, unstaged, untracked };
}

// ---------------------------------------------------------------------------
// Terminal / TUI helpers
// ---------------------------------------------------------------------------

function enterAltScreen() {
  process.stdout.write('\x1b[?1049h');
}

function exitAltScreen() {
  process.stdout.write('\x1b[?1049l');
}

function hideCursor() {
  process.stdout.write('\x1b[?25l');
}

function showCursor() {
  process.stdout.write('\x1b[?25h');
}

function clearScreen() {
  process.stdout.write('\x1b[2J\x1b[H');
}

function moveCursor(row, col) {
  process.stdout.write(`\x1b[${row};${col}H`);
}

function setRawMode(enable) {
  if (process.stdin.isTTY) {
    process.stdin.setRawMode(enable);
  }
}

// ---------------------------------------------------------------------------
// TUI State
// ---------------------------------------------------------------------------

// Adapters that are always-on and cannot be deselected from the TUI.
// Mirrors the prior update.sh contract of unconditionally running .claude/install.sh.
const LOCKED_ADAPTERS = new Set(['.claude']);

function runTUI(adapters, preselected) {
  return new Promise((resolve, reject) => {
    // Locked adapters are always selected, regardless of preselected/config state.
    const selected = new Set(preselected.filter(a => adapters.includes(a)));
    for (const adapter of adapters) {
      if (LOCKED_ADAPTERS.has(adapter)) selected.add(adapter);
    }
    let cursor = 0;
    let done = false;

    function draw() {
      clearScreen();
      moveCursor(1, 1);
      console.log('  Update agentic-engineering\n');

      for (let i = 0; i < adapters.length; i++) {
        const adapter = adapters[i];
        const locked = LOCKED_ADAPTERS.has(adapter);
        const mark = selected.has(adapter) ? 'x' : ' ';
        const pointer = i === cursor ? '> ' : '  ';
        const suffix = locked ? ' (locked)' : '';
        console.log(`${pointer}[${mark}] ${displayName(adapter)}${suffix}`);
      }

      console.log('\n  ↑/↓ navigate · space toggle · enter confirm · q abort');
    }

    function cleanup() {
      if (done) return;
      done = true;
      setRawMode(false);
      showCursor();
      exitAltScreen();
      process.stdin.pause();
      process.stdin.removeListener('keypress', onKeypress);
      process.removeListener('SIGINT', sigintHandler);
    }

    function abort() {
      cleanup();
      reject(new Error('aborted'));
    }

    function confirm() {
      // Ensure locked adapters are always present in the resolved set.
      for (const adapter of adapters) {
        if (LOCKED_ADAPTERS.has(adapter)) selected.add(adapter);
      }
      cleanup();
      resolve(Array.from(selected));
    }

    function onKeypress(str, key) {
      if (done) return;

      if (key.name === 'up') {
        if (cursor > 0) cursor--;
        draw();
      } else if (key.name === 'down') {
        if (cursor < adapters.length - 1) cursor++;
        draw();
      } else if (key.name === 'space') {
        const adapter = adapters[cursor];
        if (LOCKED_ADAPTERS.has(adapter)) {
          // Locked rows are non-toggleable.
          return;
        }
        if (selected.has(adapter)) {
          selected.delete(adapter);
        } else {
          selected.add(adapter);
        }
        draw();
      } else if (key.name === 'return') {
        confirm();
      } else if (key.name === 'q') {
        abort();
      } else if (key.name === 'c' && key.ctrl) {
        abort();
      }
    }

    const sigintHandler = () => abort();

    // Setup
    readline.emitKeypressEvents(process.stdin);
    enterAltScreen();
    hideCursor();
    setRawMode(true);
    draw();

    process.stdin.on('keypress', onKeypress);
    process.stdin.resume();

    // Handle SIGINT gracefully
    process.on('SIGINT', sigintHandler);
  });
}

// ---------------------------------------------------------------------------
// Prompt helpers
// ---------------------------------------------------------------------------

function promptYesNo(question, defaultYes = false) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout
    });
    const defaultStr = defaultYes ? 'Y/n' : 'y/N';
    rl.question(`${question} [${defaultStr}] `, (answer) => {
      rl.close();
      const trimmed = answer.trim().toLowerCase();
      if (!trimmed) {
        resolve(defaultYes);
        return;
      }
      resolve(trimmed === 'y' || trimmed === 'yes');
    });
  });
}

// ---------------------------------------------------------------------------
// Install script execution
// ---------------------------------------------------------------------------

async function runInstallScript(repoDir, adapter) {
  const scriptPath = path.join(repoDir, adapter, 'install.sh');
  const display = displayName(adapter);

  console.log('');
  console.log(`>>> bash ${scriptPath}`);

  return new Promise((resolve) => {
    const child = spawn('bash', [scriptPath], {
      cwd: repoDir,
      stdio: 'inherit'
    });

    child.on('close', (code) => {
      if (code !== 0) {
        console.error(`\nerror: install script failed: ${scriptPath} (exit ${code}).`);
        resolve({ success: false, adapter, display, code });
      } else {
        resolve({ success: true, adapter, display });
      }
    });

    child.on('error', (err) => {
      console.error(`\nerror: failed to spawn install script: ${scriptPath} (${err.message}).`);
      resolve({ success: false, adapter, display, code: -1 });
    });
  });
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const args = process.argv.slice(2);
  const repoDir = args[0];

  // --help flag (handle before TTY check so it works in non-TTY)
  if (args.includes('-h') || args.includes('--help')) {
    console.log('Usage: update.sh [--help]');
    console.log('       node scripts/update.js <repo_dir> [--help]');
    console.log('');
    console.log('Interactive updater for the agentic-engineering repo. Opens a multi-select');
    console.log("menu of adapters, confirms the plan, then runs");
    console.log("'git pull --ff-only origin main' and each chosen install.sh.");
    console.log('');
    console.log('Options:');
    console.log('  -h, --help    Print this help and exit.');
    process.exit(0);
  }

  if (!repoDir) {
    console.error('error: repo directory argument required.');
    console.error('Usage: node scripts/update.js <repo_dir>');
    process.exit(1);
  }

  // Preflight: TTY check
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    console.error('error: update.sh requires a terminal (TTY) — run it directly from a shell, not piped.');
    process.exit(1);
  }

  const resolvedRepoDir = path.resolve(repoDir);

  // Preflight: git check
  // Note: spawnSync does not throw on ENOENT; it returns result.error instead.
  const gitProbe = spawnSync('git', ['--version'], { stdio: 'ignore' });
  if (gitProbe.error || gitProbe.status !== 0) {
    console.error("error: 'git' not found on PATH.");
    process.exit(1);
  }

  // Preflight: repo check
  const claudeInstall = path.join(resolvedRepoDir, '.claude', 'install.sh');
  if (!fs.existsSync(claudeInstall)) {
    console.error(`error: ${resolvedRepoDir} does not look like an agentic-engineering checkout`);
    console.error(`       (expected ${claudeInstall}).`);
    process.exit(1);
  }

  // Preflight: git repo check
  const gitCheck = git(resolvedRepoDir, 'rev-parse', '--is-inside-work-tree');
  if (!gitCheck.success || gitCheck.stdout !== 'true') {
    console.error(`error: ${resolvedRepoDir} is not a git working tree.`);
    process.exit(1);
  }

  // Discover adapters
  const adapters = discoverAdapters(resolvedRepoDir);
  if (adapters.length === 0) {
    console.error('error: no adapters found.');
    process.exit(1);
  }

  // Load config for pre-selection
  const config = loadConfig();
  let preselected = [];
  if (config && config.adapters) {
    preselected = Object.keys(config.adapters).filter(a => config.adapters[a]);
  }

  // Hard-block: non-main branch
  // Pulling origin main onto a non-main branch creates a confusing merge
  // situation. The old script blocked this; keep the hard-block.
  const currentBranch = getCurrentBranch(resolvedRepoDir);
  if (currentBranch !== 'main') {
    console.error(`error: update.sh must be run from the 'main' branch (currently on '${currentBranch}').`);
    process.exit(1);
  }

  // Warning: dirty tree
  if (isWorkingTreeDirty(resolvedRepoDir)) {
    const dirty = getDirtyFiles(resolvedRepoDir);
    console.warn('\nwarning: local changes present — git pull needs a clean working tree.');
    console.warn('         git pull --ff-only will fail with these changes uncommitted.');
    if (dirty.staged.length > 0) {
      console.warn('  Staged for commit:');
      dirty.staged.forEach(f => console.warn(`    ${f}`));
    }
    if (dirty.unstaged.length > 0) {
      console.warn('  Modified (not staged):');
      dirty.unstaged.forEach(f => console.warn(`    ${f}`));
    }
    if (dirty.untracked.length > 0) {
      console.warn('  Untracked:');
      dirty.untracked.forEach(f => console.warn(`    ${f}`));
    }
    console.warn('');
    const proceed = await promptYesNo('Proceed anyway?', false);
    if (!proceed) {
      console.log('aborted.');
      process.exit(0);
    }
  }

  // Run TUI
  let selected;
  try {
    selected = await runTUI(adapters, preselected);
  } catch (err) {
    if (err.message === 'aborted') {
      console.log('aborted.');
      process.exit(130);
    }
    throw err;
  }

  // Defense in depth: locked adapters are always included regardless of TUI state.
  for (const adapter of adapters) {
    if (LOCKED_ADAPTERS.has(adapter) && !selected.includes(adapter)) {
      selected.push(adapter);
    }
  }

  if (selected.length === 0) {
    console.log('\nNo adapters selected. Nothing to do.');
    process.exit(0);
  }

  // Confirmation
  console.log('\nWill run:');
  console.log('  git fetch origin');
  console.log('  git pull --ff-only origin main');
  for (const adapter of selected) {
    console.log(`  bash ${adapter}/install.sh`);
  }
  console.log('');
  console.log(`Adapters to refresh: ${selected.map(displayName).join(', ')}`);
  console.log('');

  const proceed = await promptYesNo('Proceed?', true);
  if (!proceed) {
    console.log('aborted.');
    process.exit(0);
  }

  // Git operations
  console.log('\n>>> git fetch origin');
  const fetchResult = git(resolvedRepoDir, 'fetch', 'origin');
  if (!fetchResult.success) {
    console.error(`error: 'git fetch origin' failed.`);
    console.error(fetchResult.stderr);
    process.exit(1);
  }

  const oldHead = git(resolvedRepoDir, 'rev-parse', 'HEAD').stdout;

  console.log('\n>>> git pull --ff-only origin main');
  const pullResult = git(resolvedRepoDir, 'pull', '--ff-only', 'origin', 'main');
  if (!pullResult.success) {
    console.error(`error: 'git pull --ff-only origin main' failed.`);
    console.error(pullResult.stderr);
    console.error('       resolve the non-fast-forward (or other) condition and retry.');
    process.exit(1);
  }

  const newHead = git(resolvedRepoDir, 'rev-parse', 'HEAD').stdout;
  let commitsPulled = 0;
  if (oldHead !== newHead) {
    const countResult = git(resolvedRepoDir, 'rev-list', '--count', `${oldHead}..${newHead}`);
    commitsPulled = countResult.success ? parseInt(countResult.stdout, 10) : 0;
  }

  // Run install scripts (fail-fast: stop on first failure)
  const successes = [];

  for (const adapter of selected) {
    const result = await runInstallScript(resolvedRepoDir, adapter);
    if (result.success) {
      successes.push(result.display);
    } else {
      console.error(`\nerror: ${result.display}/install.sh failed (exit ${result.code}).`);
      console.error('       Fix the failure and re-run ./update.sh.');
      process.exit(result.code || 1);
    }
  }

  // Save config
  saveConfig(selected);

  // Summary
  console.log('');
  if (commitsPulled === 0) {
    console.log(`Already up to date. Refreshed ${successes.length} adapter(s): ${successes.join(' ')}.`);
  } else {
    console.log(`Updated: pulled ${commitsPulled} commit(s); refreshed ${successes.length} adapter(s): ${successes.join(' ')}.`);
  }

  // Warn about generated changes
  if (isWorkingTreeDirty(resolvedRepoDir)) {
    const dirty = getDirtyFiles(resolvedRepoDir);
    console.warn('\nwarning: adapter install scripts generated changes in the working tree.');
    if (dirty.staged.length > 0) {
      console.warn('  Staged for commit:');
      dirty.staged.forEach(f => console.warn(`    ${f}`));
    }
    if (dirty.unstaged.length > 0) {
      console.warn('  Modified (not staged):');
      dirty.unstaged.forEach(f => console.warn(`    ${f}`));
    }
    if (dirty.untracked.length > 0) {
      console.warn('  Untracked:');
      dirty.untracked.forEach(f => console.warn(`    ${f}`));
    }
    console.warn('\n  These are likely build artifacts from the adapter install scripts.');
    console.warn('  If they should be tracked, run: git add <files> && git commit');
    console.warn('  If they are generated files that should not be tracked, add them to .gitignore.');
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
