#!/usr/bin/env node
/**
 * Unit tests: stop-context.js appendCaptureGapNoticeToContextMd's pagination
 * cursor write (.agentic/.capture-gap-last-sweep), via the shim-load pattern
 * used by test-stop-context-health.js.
 *
 * DS-109: the cursor's staging file used to be a single fixed
 * `<cursorPath>.tmp` name shared by every writer, with an unconditional
 * catch-path `fs.unlinkSync(cursorPath + '.tmp')` cleanup that could delete
 * a concurrent peer's still-in-flight staging file. Post-fix, the tmp name
 * is pid-suffixed (`<cursorPath>.tmp.<pid>`) and the catch-path cleanup is
 * scoped to only the exact tmp path this call created.
 *
 * Test cases:
 *   (a) normal write succeeds: cursor file is written, no own-style tmp
 *       remains afterward.
 *   (b) a peer's in-flight staging file - at the legacy fixed name, or at a
 *       different pid's suffixed name - survives our own successful write
 *       untouched.
 *   (c) a peer's in-flight staging file survives our own FAILED write
 *       (simulated by monkeypatching fs.renameSync to throw once, after our
 *       own tmp.<pid> has actually landed on disk) - proves the catch-path
 *       cleanup is scoped to our own name only, not the shared/legacy name.
 *
 * Run with: node hooks/tests/test-stop-context-capture-gap-cursor.js
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

// ---------------------------------------------------------------------------
// Shim-load stop-context.js (same technique as test-stop-context-health.js)
// ---------------------------------------------------------------------------

const hookPath = path.resolve(__dirname, '..', 'stop-context.js');
const hookSource = fs.readFileSync(hookPath, 'utf8');

const { reanchorHookRequires } = require('./lib/hook-shim.js');

let shimmedSource;
try {
  shimmedSource = reanchorHookRequires(
    hookSource.replace(/^run\(\).*;\s*$/m, '// test shim: run() suppressed'),
    path.resolve(__dirname, '..', 'lib')
  );
} catch (shimErr) {
  console.error('  FATAL: ' + shimErr.message);
  process.exit(1);
}

const tmpShimPath = path.join(os.tmpdir(), `stop-ctx-cgc-shim-${Date.now()}.js`);
fs.writeFileSync(tmpShimPath, shimmedSource, 'utf8');
let helpers;
try {
  helpers = require(tmpShimPath);
} finally {
  try { fs.unlinkSync(tmpShimPath); } catch (_) { /* ignore */ }
}

const { appendCaptureGapNoticeToContextMd } = helpers;
if (typeof appendCaptureGapNoticeToContextMd !== 'function') {
  console.error('  FATAL: appendCaptureGapNoticeToContextMd not exported by the shim - update the module.exports shim.');
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Harness
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

function makeTmpProject() {
  // realpathSync: DS-171's resolveAgenticCwd() realpath-pins its input
  // (macOS os.tmpdir() is /var/... -> symlinked to /private/var/...), so a
  // test computing an expected path from the RAW (non-realpath'd) tmpDir
  // would build a different string than what stop-context.js's cursor
  // writer actually uses internally, even though both name the same file.
  const tmpDir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ae-stop-cgc-')));
  fs.mkdirSync(path.join(tmpDir, '.agentic'), { recursive: true });
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) { /* ignore */ }
}

const isOwnStyleTmp = (f) => /\.capture-gap-last-sweep\.tmp\.\d+$/.test(f);

// ---------------------------------------------------------------------------
// (a) normal write succeeds, no own-style tmp left behind
// ---------------------------------------------------------------------------
console.log('\n[a] normal write succeeds; no orphan tmp.<pid> remains');
{
  const tmpDir = makeTmpProject();
  const agenticDir = path.join(tmpDir, '.agentic');
  const cursorPath = path.join(agenticDir, '.capture-gap-last-sweep');

  appendCaptureGapNoticeToContextMd(tmpDir, false, 'sess-a');

  assert(fs.existsSync(cursorPath), 'cursor file written');
  const leftover = fs.readdirSync(agenticDir).filter(isOwnStyleTmp);
  assert(leftover.length === 0, `no orphan tmp.<pid> remains (found: ${leftover.join(', ') || 'none'})`);
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (b) DS-109: a peer's in-flight staging file survives our own SUCCESSFUL
//     write, whether at the legacy fixed name or a different pid's name.
// ---------------------------------------------------------------------------
console.log('\n[b] DS-109: peer in-flight tmp survives our own successful write');
{
  const tmpDir = makeTmpProject();
  const agenticDir = path.join(tmpDir, '.agentic');
  const cursorPath = path.join(agenticDir, '.capture-gap-last-sweep');

  const legacyFixedNamePeerTmp = cursorPath + '.tmp';
  const foreignPid = String(process.pid) + '9'; // guaranteed not our own pid
  const peerTmp = cursorPath + '.tmp.' + foreignPid;
  fs.writeFileSync(legacyFixedNamePeerTmp, 'PEER_INFLIGHT_DATA_LEGACY_NAME');
  fs.writeFileSync(peerTmp, 'PEER_INFLIGHT_DATA_PID_SUFFIXED');

  appendCaptureGapNoticeToContextMd(tmpDir, false, 'sess-a');

  assert(fs.existsSync(cursorPath), 'cursor file still written correctly despite peer tmp files present');
  assert(
    fs.existsSync(legacyFixedNamePeerTmp) && fs.readFileSync(legacyFixedNamePeerTmp, 'utf8') === 'PEER_INFLIGHT_DATA_LEGACY_NAME',
    'peer\'s legacy fixed-name .tmp file survives untouched'
  );
  assert(
    fs.existsSync(peerTmp) && fs.readFileSync(peerTmp, 'utf8') === 'PEER_INFLIGHT_DATA_PID_SUFFIXED',
    'peer\'s pid-suffixed .tmp.<otherpid> file survives untouched'
  );
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// (c) DS-109: a peer's in-flight staging file survives our own FAILED write
//     (forced rename failure), and our own tmp.<pid> is cleaned up by the
//     catch block - proving cleanup is scoped to our own name only.
// ---------------------------------------------------------------------------
console.log('\n[c] DS-109: peer in-flight tmp survives our own failed write; own tmp still cleaned up');
{
  const tmpDir = makeTmpProject();
  const agenticDir = path.join(tmpDir, '.agentic');
  const cursorPath = path.join(agenticDir, '.capture-gap-last-sweep');
  const expectedOwnTmp = cursorPath + '.tmp.' + process.pid;

  const legacyFixedNamePeerTmp = cursorPath + '.tmp';
  fs.writeFileSync(legacyFixedNamePeerTmp, 'PEER_INFLIGHT_DATA_LEGACY_NAME');

  const realRenameSync = fs.renameSync;
  let observedOwnTmpExistedMidWrite = false;
  fs.renameSync = function patchedRenameSync(src, dest) {
    if (src === expectedOwnTmp) {
      observedOwnTmpExistedMidWrite = fs.existsSync(expectedOwnTmp);
      throw new Error('simulated crash between write and rename');
    }
    return realRenameSync.apply(fs, arguments);
  };
  try {
    appendCaptureGapNoticeToContextMd(tmpDir, false, 'sess-a');
  } finally {
    fs.renameSync = realRenameSync;
  }

  assert(observedOwnTmpExistedMidWrite, 'our own tmp.<pid> did exist on disk at the moment rename failed');
  assert(!fs.existsSync(expectedOwnTmp), 'our own tmp.<pid> is cleaned up by the catch block after a failed rename');
  assert(
    fs.existsSync(legacyFixedNamePeerTmp) && fs.readFileSync(legacyFixedNamePeerTmp, 'utf8') === 'PEER_INFLIGHT_DATA_LEGACY_NAME',
    'DS-109: peer\'s legacy fixed-name .tmp file survives our unrelated failed-write cleanup, untouched'
  );
  cleanup(tmpDir);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
