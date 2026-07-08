#!/usr/bin/env node

/**
 * Purpose: Regression tests for the Node activation guard hooks/lib/activation.js
 * (isActive). Covers every activation layer, the fail-ACTIVE contract, and the
 * <10ms timing assertion from the plan (Unit 10, risk R3).
 *
 * Public API: node hooks/tests/test_activation_guard.js
 *   Exits 0 on all pass, 1 on any failure. Hermetic: tempfile sandboxes and a
 *   fake HOME so the real ~/.agentic is never touched.
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const guard = require('../lib/activation.js');

let fails = 0;
function check(label, cond) {
  if (cond) {
    console.log(`  ok: ${label}`);
  } else {
    console.error(`  FAIL: ${label}`);
    fails += 1;
  }
}

function mkTmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'actguard-'));
}

// Layer 6: dormant (no marker).
const d = mkTmp();
check('no .agentic -> dormant', guard.isActive(d) === false);

// Layer 4: auto-detect.
fs.mkdirSync(path.join(d, '.agentic'), { recursive: true });
check('auto-detect .agentic dir -> active', guard.isActive(d) === true);

// Layer 3: tombstone overrides auto-detect.
fs.writeFileSync(path.join(d, '.agentic', 'dormant'), '');
check('tombstone overrides auto-detect -> dormant', guard.isActive(d) === false);

// Layer 1: explicit active file overrides tombstone.
fs.writeFileSync(path.join(d, '.agentic', 'active'), '');
check('active file overrides tombstone -> active', guard.isActive(d) === true);

// Layer 2: session file overrides tombstone.
const d2 = mkTmp();
fs.mkdirSync(path.join(d2, '.agentic'), { recursive: true });
fs.writeFileSync(path.join(d2, '.agentic', 'dormant'), '');
fs.writeFileSync(path.join(d2, '.agentic', 'active.session'), '');
check('active.session overrides tombstone -> active', guard.isActive(d2) === true);

// Layer 5: allowlist via fake HOME.
const d3 = mkTmp(); // no .agentic
const fakeHome = mkTmp();
fs.mkdirSync(path.join(fakeHome, '.agentic'), { recursive: true });
fs.writeFileSync(
  path.join(fakeHome, '.agentic', 'activation.list'),
  fs.realpathSync(d3) + '\n'
);
const oldHome = process.env.HOME;
process.env.HOME = fakeHome;
try {
  // os.homedir() reads HOME on POSIX; re-require in a child would be cleaner but
  // homedir() honors the env var here.
  check('allowlisted cwd -> active', guard.isActive(d3) === true);
  const d4 = mkTmp();
  check('non-listed cwd -> dormant', guard.isActive(d4) === false);
} finally {
  if (oldHome !== undefined) process.env.HOME = oldHome;
  else delete process.env.HOME;
}

// Fail-ACTIVE: indeterminate cwd.
check('null cwd -> fail-ACTIVE', guard.isActive(null) === true);
check('blank cwd -> fail-ACTIVE', guard.isActive('   ') === true);
check('non-string cwd -> fail-ACTIVE', guard.isActive(12345) === true);

// Timing: <10ms on the hot (dormant) path.
const dt = mkTmp();
const n = 200;
const start = process.hrtime.bigint();
for (let i = 0; i < n; i += 1) guard.isActive(dt);
const perCallMs = Number(process.hrtime.bigint() - start) / 1e6 / n;
check(`dormant path <10ms/call (measured ${perCallMs.toFixed(3)}ms)`, perCallMs < 10.0);

if (fails) {
  console.error(`\n${fails} FAILED`);
  process.exit(1);
}
console.log('\nALL PASS');
process.exit(0);
