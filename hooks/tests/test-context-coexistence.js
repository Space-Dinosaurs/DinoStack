#!/usr/bin/env node
'use strict';

/** Golden tests for the pure context coexistence serializer. */

const assert = require('assert/strict');
const coexist = require('../lib/context-coexistence.js');

assert.equal(coexist.WRAP_HEADER_PREFIX, '# Session Context\n*Written by /wrap');
assert.equal(coexist.ACTIVITY_SENTINEL, '\n\n---\n\n## Session Activity\n');

const base = '# Session Context\n*Written by /wrap on 2026-07-14.*\n\n## Recent Focus\n- preserved';
const old = base + coexist.ACTIVITY_SENTINEL + 'old activity\n';
const fresh = coexist.mergeAutomatedContext(old, 'fallback\n', 'fresh activity\n');
assert.equal(fresh, base + coexist.ACTIVITY_SENTINEL + 'fresh activity\n');
assert.equal(fresh.split(coexist.ACTIVITY_SENTINEL).length - 1, 1);
assert.equal(coexist.mergeAutomatedContext('other\n', 'fallback\n', 'activity\n'), 'fallback\n');
assert.equal(
  coexist.mergeAutomatedContext(base, 'fallback\n', coexist.ACTIVITY_SENTINEL + 'fresh activity\n'),
  base + coexist.ACTIVITY_SENTINEL + 'fresh activity\n'
);
assert.throws(() => coexist.mergeAutomatedContext(null, 'x', 'y'), TypeError);

console.log('context coexistence golden: 7 passed, 0 failed');
