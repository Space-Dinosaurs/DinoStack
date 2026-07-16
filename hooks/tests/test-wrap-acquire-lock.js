#!/usr/bin/env node
'use strict';

/** Regression tests for the tokenized agentic-wrap-acquire-lock CLI. */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const lib = require('../lib/wrap-marker.js');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SCRIPT_PATH = path.join(REPO_ROOT, 'bin', 'agentic-wrap-acquire-lock');
const tmpDirs = [];
let passed = 0;
let failed = 0;

function assert(value, message) {
  if (value) { console.log(`  PASS: ${message}`); passed++; }
  else { console.error(`  FAIL: ${message}`); failed++; }
}

function temp(prefix) {
  const value = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  tmpDirs.push(value);
  return value;
}

function run(args, options = {}) {
  try {
    return { code: 0, out: execFileSync(SCRIPT_PATH, args, { encoding: 'utf8', ...options }) };
  } catch (error) {
    return { code: error.status, out: error.stdout || '' };
  }
}

function tokenFrom(output) {
  const match = output.match(/\btoken=([0-9a-f]{64})\b/);
  return match ? match[1] : null;
}

console.log('\n[1] free acquisition returns an opaque release token');
{
  const project = temp('wrap-acquire-free-');
  const result = run([project, '--timeout-ms=1000', '--poll-ms=20']);
  const token = tokenFrom(result.out);
  assert(result.code === 0, `free acquisition exits 0 (got ${result.code})`);
  assert(typeof token === 'string', 'free acquisition prints a 64-hex token');
  assert(lib.releaseWrapLockToken(project, token) === true, 'returned token releases the lock');
}

console.log('\n[2] live owner blocks, then waiter acquires after token release');
{
  const project = temp('wrap-acquire-wait-');
  const wrapper = `
    const { spawn } = require('child_process');
    const lib = require(${JSON.stringify(path.join(REPO_ROOT, 'hooks', 'lib', 'wrap-marker.js'))});
    const project = ${JSON.stringify(project)};
    const token = lib.acquireWrapLockToken(project, 'test-holder');
    if (!token) process.exit(9);
    const child = spawn(${JSON.stringify(SCRIPT_PATH)}, [project, '--timeout-ms=5000', '--poll-ms=50'], {
      stdio: ['ignore', 'pipe', 'inherit'],
    });
    let output = '';
    child.stdout.on('data', (chunk) => { output += chunk.toString(); });
    setTimeout(() => { lib.releaseWrapLockToken(project, token); }, 250);
    child.on('exit', (code) => { process.stdout.write(output); process.exit(code || 0); });
  `;
  let output = '';
  let exitCode = 0;
  try {
    output = execFileSync(process.execPath, ['-e', wrapper], { encoding: 'utf8', timeout: 8000 });
  } catch (error) {
    output = error.stdout || '';
    exitCode = error.status;
  }
  const acquiredToken = tokenFrom(output);
  assert(exitCode === 0, `waiter exits 0 after release (got ${exitCode})`);
  assert(output.includes('waiting'), 'waiter reports progress while held');
  assert(typeof acquiredToken === 'string', 'waiter returns its own token');
  lib.releaseWrapLockToken(project, acquiredToken);
}

console.log('\n[3] live owner times out without mutation');
{
  const project = temp('wrap-acquire-timeout-');
  const heldToken = lib.acquireWrapLockToken(project, 'test-holder');
  assert(lib.clearProvablyStaleWrapLockTokenized(project, 0) === false,
    'signed stale clear refuses a live owner');
  const result = run([project, '--timeout-ms=180', '--poll-ms=30'], { timeout: 3000 });
  assert(result.code === 2, `timeout exits 2 (got ${result.code})`);
  assert(result.out.includes('timeout'), 'timeout status is printed');
  assert(fs.existsSync(lib.wrapLockPath(project)), 'live lock remains present');
  lib.releaseWrapLockToken(project, heldToken);
}

console.log('\n[4] malformed legacy owner is retained and classified unreadable');
{
  const project = temp('wrap-acquire-malformed-');
  fs.mkdirSync(lib.wrapLockPath(project), { recursive: true });
  fs.writeFileSync(lib.wrapLockOwnerPath(project), '123\nold-format\n');
  const result = run([project, '--timeout-ms=1000', '--poll-ms=20']);
  assert(result.code === 3, `malformed owner exits 3 (got ${result.code})`);
  assert(result.out.includes('unreadable-owner'), 'malformed owner is reported');
  assert(fs.existsSync(lib.wrapLockPath(project)), 'malformed lock is retained');
}

console.log('\n[5] valid dead owner is reclaimed automatically');
{
  const project = temp('wrap-acquire-dead-');
  const childScript = `
    const lib = require(${JSON.stringify(path.join(REPO_ROOT, 'hooks', 'lib', 'wrap-marker.js'))});
    const token = lib.acquireWrapLockToken(${JSON.stringify(project)}, 'dead-child');
    if (!token) process.exit(2);
    process.stdout.write(token);
  `;
  execFileSync(process.execPath, ['-e', childScript], { encoding: 'utf8' });
  const result = run([project, '--timeout-ms=1000', '--poll-ms=20']);
  const token = tokenFrom(result.out);
  assert(result.code === 0, `dead-owner reclaim exits 0 (got ${result.code})`);
  assert(typeof token === 'string', 'dead-owner reclaim returns a fresh token');
  lib.releaseWrapLockToken(project, token);
}

console.log('\n[6] daemon stale clear uses acquisition-internal reclaim');
{
  const project = temp('wrap-clear-dead-');
  const childScript = `
    const lib = require(${JSON.stringify(path.join(REPO_ROOT, 'hooks', 'lib', 'wrap-marker.js'))});
    const token = lib.acquireWrapLockToken(${JSON.stringify(project)}, 'dead-clear-child');
    if (!token) process.exit(2);
  `;
  execFileSync(process.execPath, ['-e', childScript], { encoding: 'utf8' });
  assert(lib.clearProvablyStaleWrapLockTokenized(project, 0) === true,
    'signed stale clear reclaims through acquire and releases its token');
  assert(!fs.existsSync(lib.wrapLockPath(project)), 'stale clear leaves no replacement lock');
}

console.log('\n[7] symlinked executable resolves repository helper');
{
  const binDir = temp('wrap-acquire-bin-');
  const project = temp('wrap-acquire-project-');
  const linked = path.join(binDir, 'agentic-wrap-acquire-lock');
  fs.symlinkSync(SCRIPT_PATH, linked);
  const result = (() => {
    try { return { code: 0, out: execFileSync(linked, [project, '--timeout-ms=1000'], { encoding: 'utf8' }) }; }
    catch (error) { return { code: error.status, out: error.stdout || '' }; }
  })();
  const token = tokenFrom(result.out);
  assert(result.code === 0, `symlinked executable exits 0 (got ${result.code})`);
  assert(typeof token === 'string', 'symlinked executable returns a token');
  lib.releaseWrapLockToken(project, token);
}

console.log('\n[8] compatibility boundary preserves boolean acquire and tokenless release');
{
  const project = temp('wrap-acquire-compat-');
  assert(lib.acquireWrapLock(project, 'legacy-daemon-owner', 1000) === true,
    'legacy acquire returns strict boolean true for current daemon consumers');
  assert(lib.acquireWrapLock(project, 'legacy-contender', 1000) === false,
    'legacy contention returns strict boolean false');
  assert(lib.releaseWrapLock(project) === true,
    'legacy tokenless release removes the compatibility lock');
  assert(!fs.existsSync(lib.wrapLockPath(project)),
    'compatibility release leaves no lock residue');
}

console.log('\n[9] attacker-controlled PATH cannot substitute the Python helper');
{
  const project = temp('wrap-acquire-trusted-python-project-');
  const fakeBin = temp('wrap-acquire-fake-python-bin-');
  const invoked = path.join(fakeBin, 'fake-python-invoked');
  const fakePython = path.join(fakeBin, 'python3');
  fs.writeFileSync(
    fakePython,
    '#!/bin/sh\n'
      + `touch ${JSON.stringify(invoked)}\n`
      + `printf '${JSON.stringify({ status: 'acquired', token: 'b'.repeat(64) })}\\n'\n`,
    { mode: 0o700 },
  );
  const originalPath = process.env.PATH;
  process.env.PATH = fakeBin + path.delimiter + (originalPath || '');
  let token;
  try {
    token = lib.acquireWrapLockToken(project, 'trusted-python-test');
  } finally {
    process.env.PATH = originalPath;
  }
  assert(typeof token === 'string' && token !== 'b'.repeat(64),
    'signed acquisition ignores the forged helper response');
  assert(!fs.existsSync(invoked), 'fake python3 earlier in PATH is never executed');
  assert(fs.existsSync(lib.wrapLockPath(project)), 'trusted helper created the real signed lock');
  lib.releaseWrapLockToken(project, token);
}

for (const dir of tmpDirs) fs.rmSync(dir, { recursive: true, force: true });
console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
