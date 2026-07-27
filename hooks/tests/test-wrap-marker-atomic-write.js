#!/usr/bin/env node
/**
 * Unit tests: hooks/lib/wrap-marker.js - atomicWriteJson pid-suffixed staging
 * (DS-109 follow-up fix; the site the original 7-site audit missed).
 *
 * Covers:
 *   (1) writeMarker's staging file is suffixed with the writing process's own
 *       pid, not the fixed <target>.tmp name.
 *   (2) On a failure between write and rename, the catch path unlinks ONLY
 *       our own pid-suffixed tmp file - a peer's legacy fixed-name `.tmp`
 *       in-flight file, and a peer's pid-suffixed file under a different
 *       pid, both survive untouched.
 *
 * This file exercises the lib directly (require) - no child process, no
 * `claude` CLI, no network.
 *
 * Run with: node hooks/tests/test-wrap-marker-atomic-write.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const lib = require('../lib/wrap-marker.js');

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

function makeProject(prefix) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  const projectDir = path.join(base, 'project');
  const agenticDir = path.join(projectDir, '.agentic');
  fs.mkdirSync(agenticDir, { recursive: true });
  return { base, projectDir, agenticDir };
}

function cleanup(base) {
  try { fs.rmSync(base, { recursive: true, force: true }); } catch (_) {}
}

const SID = '77777777-7777-4777-7777-000000000001';

function baseMarker(sessionId) {
  return {
    schema_version: 3,
    session_id: sessionId,
    staged_at: new Date().toISOString(),
    status: 'pending',
    claimed_by: null,
    claimed_kind: null,
    claimed_at: null,
    attempts: 0,
  };
}

// ---------------------------------------------------------------------------
// (1) tmp filename is pid-suffixed, not the fixed legacy `.tmp` name.
// ---------------------------------------------------------------------------
console.log('\n[1] writeMarker stages at a pid-suffixed tmp name');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wm-atomic-1-');
  delete process.env.AGENTIC_WRAP_DAEMON;

  const markerPath = lib.markerPath(projectDir, SID);
  const expectedOwnTmp = markerPath + '.tmp.' + process.pid;
  const legacyFixedTmp = markerPath + '.tmp';

  let observedTmpPathDuringWrite = null;
  const realWriteFileSync = fs.writeFileSync;
  fs.writeFileSync = function patchedWriteFileSync(target, ...rest) {
    if (typeof target === 'string' && target.indexOf(markerPath + '.tmp') === 0) {
      observedTmpPathDuringWrite = target;
    }
    return realWriteFileSync.apply(fs, [target, ...rest]);
  };
  try {
    assert(lib.writeMarker(projectDir, baseMarker(SID)) === true,
      '[1] writeMarker returns true on success');
  } finally {
    fs.writeFileSync = realWriteFileSync;
  }

  assert(observedTmpPathDuringWrite === expectedOwnTmp,
    `[1] staging path was pid-suffixed (observed: ${observedTmpPathDuringWrite})`);
  assert(observedTmpPathDuringWrite !== legacyFixedTmp,
    '[1] staging path is NOT the fixed legacy <target>.tmp name');
  assert(!fs.existsSync(expectedOwnTmp),
    '[1] tmp file is gone after a successful rename');
  assert(fs.existsSync(markerPath),
    '[1] final marker file exists at the real path');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// (2) DS-109 regression: a failure between write and rename cleans up ONLY
//     our own pid-suffixed tmp - a peer's fixed-name and pid-suffixed
//     in-flight files both survive.
// ---------------------------------------------------------------------------
console.log('\n[2] catch-path cleanup never touches a peer\'s in-flight tmp file');
{
  const { base, projectDir, agenticDir } = makeProject('ae-wm-atomic-2-');
  delete process.env.AGENTIC_WRAP_DAEMON;

  const markerPath = lib.markerPath(projectDir, SID);
  const expectedOwnTmp = markerPath + '.tmp.' + process.pid;
  const legacyFixedNamePeerTmp = markerPath + '.tmp';
  const foreignPid = String(process.pid) + '9'; // guaranteed != our own pid
  const peerPidTmp = markerPath + '.tmp.' + foreignPid;

  fs.mkdirSync(path.dirname(markerPath), { recursive: true });
  fs.writeFileSync(legacyFixedNamePeerTmp, 'PEER_INFLIGHT_LEGACY_NAME');
  fs.writeFileSync(peerPidTmp, 'PEER_INFLIGHT_PID_SUFFIXED');

  const realRenameSync = fs.renameSync;
  let observedOwnTmpExistedMidWrite = false;
  fs.renameSync = function patchedRenameSync(src, dest) {
    if (src === expectedOwnTmp) {
      observedOwnTmpExistedMidWrite = fs.existsSync(expectedOwnTmp);
      throw new Error('simulated crash between write and rename');
    }
    return realRenameSync.apply(fs, arguments);
  };
  let result;
  try {
    result = lib.writeMarker(projectDir, baseMarker(SID));
  } finally {
    fs.renameSync = realRenameSync;
  }

  assert(result === false, '[2] writeMarker returns false on a mid-write failure');
  assert(observedOwnTmpExistedMidWrite,
    '[2] our own tmp.<pid> did exist on disk at the moment rename failed');
  assert(!fs.existsSync(expectedOwnTmp),
    '[2] our own tmp.<pid> is cleaned up by the catch block after a failed rename');
  assert(fs.existsSync(legacyFixedNamePeerTmp) &&
    fs.readFileSync(legacyFixedNamePeerTmp, 'utf8') === 'PEER_INFLIGHT_LEGACY_NAME',
    'DS-109: a peer\'s legacy fixed-name .tmp file survives our unrelated catch-path cleanup, untouched');
  assert(fs.existsSync(peerPidTmp) &&
    fs.readFileSync(peerPidTmp, 'utf8') === 'PEER_INFLIGHT_PID_SUFFIXED',
    'DS-109: a peer\'s pid-suffixed .tmp.<otherpid> file survives our unrelated catch-path cleanup, untouched');

  cleanup(base);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
