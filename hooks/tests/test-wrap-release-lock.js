#!/usr/bin/env node
'use strict';

/** Regression tests for signed and compatibility lock release CLI paths. */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const lib = require('../lib/wrap-marker.js');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SCRIPT_PATH = path.join(REPO_ROOT, 'bin', 'agentic-wrap-release-lock');
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

function run(script, args) {
  return execFileSync(script, args, { encoding: 'utf8' });
}

console.log('\n[1] correct token releases verified lock');
{
  const project = temp('wrap-release-ok-');
  const token = lib.acquireWrapLockToken(project, 'release-test');
  const output = run(SCRIPT_PATH, [project, `--token=${token}`]);
  assert(output.includes('released'), 'release reports released');
  assert(!fs.existsSync(lib.wrapLockPath(project)), 'verified lock is absent');
}

console.log('\n[2] absent lock remains idempotent with a token-shaped capability');
{
  const project = temp('wrap-release-absent-');
  const output = run(SCRIPT_PATH, [project, `--token=${'0'.repeat(64)}`]);
  assert(output.includes('no lock present'), 'absent lock reports no lock present');
}

console.log('\n[3] wrong tokens never release');
{
  const project = temp('wrap-release-wrong-');
  const token = lib.acquireWrapLockToken(project, 'release-test');
  const wrong = run(SCRIPT_PATH, [project, `--token=${'0'.repeat(64)}`]);
  assert(wrong.includes('WARNING'), 'wrong token is diagnosed');
  assert(fs.existsSync(lib.wrapLockPath(project)), 'wrong-token attempt retains lock');
  assert(lib.releaseWrapLockToken(project, token), 'correct token still releases afterward');
}

console.log('\n[4] replacement inode is refused');
{
  const project = temp('wrap-release-replace-');
  const token = lib.acquireWrapLockToken(project, 'release-test');
  const lock = lib.wrapLockPath(project);
  const saved = lock + '.saved';
  fs.renameSync(lock, saved);
  fs.mkdirSync(lock);
  fs.copyFileSync(path.join(saved, 'owner'), path.join(lock, 'owner'));
  const output = run(SCRIPT_PATH, [project, `--token=${token}`]);
  assert(output.includes('WARNING'), 'replacement inode reports warning');
  assert(fs.existsSync(lock) && fs.existsSync(saved), 'replacement and original are retained');
}

console.log('\n[5] symlinked executable resolves repository implementation');
{
  const binDir = temp('wrap-release-bin-');
  const project = temp('wrap-release-project-');
  const linked = path.join(binDir, 'agentic-wrap-release-lock');
  fs.symlinkSync(SCRIPT_PATH, linked);
  const token = lib.acquireWrapLockToken(project, 'release-test');
  const output = run(linked, [project, `--token=${token}`]);
  assert(output.includes('released'), 'symlinked executable releases with token');
}

console.log('\n[6] tokenless compatibility release keeps current main callers working');
{
  const project = temp('wrap-release-compat-');
  const acquireScript = path.join(REPO_ROOT, 'bin', 'agentic-wrap-acquire-lock');
  const acquired = run(acquireScript, [project, '--timeout-ms=1000', '--poll-ms=20']);
  assert(acquired.includes('acquired'), 'current acquire CLI obtains the lock');
  const output = run(SCRIPT_PATH, [project]);
  assert(output.includes('released'), 'tokenless compatibility release reports released');
  assert(!fs.existsSync(lib.wrapLockPath(project)),
    'tokenless compatibility release leaves no lock residue');
}

for (const dir of tmpDirs) fs.rmSync(dir, { recursive: true, force: true });
console.log(`\n${passed} passed, ${failed} failed.`);
process.exit(failed > 0 ? 1 : 0);
