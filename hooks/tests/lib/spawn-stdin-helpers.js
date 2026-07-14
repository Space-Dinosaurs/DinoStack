#!/usr/bin/env node
/**
 * Test-only helpers for driving a child process's stdin with precise timing
 * control. Shared by hooks/tests/test-stdin-guard.js and sibling integration
 * test files (test-stop-context-stdin-guard.js and friends, wired in sibling
 * units of docs/planning/cursor-stop-hook-plan.md) so the spawn/write/timing
 * boilerplate is not duplicated across every hardened-hook test file.
 * Dependency-free: child_process + timers only.
 *
 * Run with: not a standalone test - required by other test files.
 */

'use strict';

const { spawn } = require('child_process');

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Spawn cmd with an open stdin pipe that never receives data and is never
 * closed. Resolves on the child's natural exit, or after maxWaitMs (the
 * child is force-killed and timedOut is set true).
 *
 * @param {{cmd: string, args?: string[], cwd?: string, env?: object, maxWaitMs?: number}} opts
 * @returns {Promise<{code: number|null, elapsedMs: number, stdout: string, stderr: string, timedOut: boolean}>}
 */
function spawnSilentStdin(opts) {
  const cmd = opts.cmd;
  const args = opts.args || [];
  const cwd = opts.cwd;
  const env = opts.env || process.env;
  const maxWaitMs = typeof opts.maxWaitMs === 'number' ? opts.maxWaitMs : 5000;

  return new Promise((resolve) => {
    const start = Date.now();
    const child = spawn(cmd, args, { cwd, env, stdio: ['pipe', 'pipe', 'pipe'] });

    let stdout = '';
    let stderr = '';
    let settled = false;
    let timer = null;

    child.stdout.on('data', (c) => { stdout += c; });
    child.stderr.on('data', (c) => { stderr += c; });

    function finish(code, timedOut) {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      resolve({ code, elapsedMs: Date.now() - start, stdout, stderr, timedOut });
    }

    child.on('exit', (code) => finish(code, false));
    child.on('error', () => finish(null, false));

    timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch (_) { /* ignore */ }
      finish(null, true);
    }, maxWaitMs);

    // stdin is deliberately left open: never written to, never end()'d.
  });
}

/**
 * Spawn cmd and write each chunk to its stdin with gapMs between writes,
 * then hold the pipe open for holdOpenMs before closing it.
 *
 * @param {{cmd: string, args?: string[], cwd?: string, env?: object, chunks: string[], gapMs?: number, holdOpenMs?: number}} opts
 * @returns {Promise<{code: number|null, elapsedMs: number, stdout: string, stderr: string}>}
 */
function spawnDelayedChunks(opts) {
  const cmd = opts.cmd;
  const args = opts.args || [];
  const cwd = opts.cwd;
  const env = opts.env || process.env;
  const chunks = opts.chunks || [];
  const gapMs = typeof opts.gapMs === 'number' ? opts.gapMs : 0;
  const holdOpenMs = typeof opts.holdOpenMs === 'number' ? opts.holdOpenMs : 0;

  return new Promise((resolve) => {
    const start = Date.now();
    const child = spawn(cmd, args, { cwd, env, stdio: ['pipe', 'pipe', 'pipe'] });

    let stdout = '';
    let stderr = '';
    let settled = false;

    child.stdout.on('data', (c) => { stdout += c; });
    child.stderr.on('data', (c) => { stderr += c; });

    function finish(code) {
      if (settled) return;
      settled = true;
      resolve({ code, elapsedMs: Date.now() - start, stdout, stderr });
    }

    child.on('exit', (code) => finish(code));
    child.on('error', () => finish(null));

    (async () => {
      for (const chunk of chunks) {
        try {
          child.stdin.write(chunk);
        } catch (_) {
          // the child may have already exited (e.g. resolved early via
          // early-completion-by-parse) - further writes are moot.
        }
        if (gapMs > 0) await sleep(gapMs);
      }
      if (holdOpenMs > 0) await sleep(holdOpenMs);
      try { child.stdin.end(); } catch (_) { /* child may already be gone */ }
    })();
  });
}

module.exports = {
  spawnSilentStdin,
  spawnDelayedChunks,
};
