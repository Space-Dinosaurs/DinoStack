#!/usr/bin/env node
/**
 * Unit tests for the needsRebuild() pure predicate in scripts/update.js.
 *
 * Run: node scripts/test/update-needsrebuild.test.js
 *
 * Decision table:
 *   (a) oldHead empty/null    -> always rebuild (first-install safety case)
 *   (b) old === new           -> skip (already up to date)
 *   (c) content/ path changed -> rebuild
 *   (d) bin/ path changed     -> rebuild
 *   (e) README.md / docs/ only -> skip (doc-only change)
 *   (f) adapter build.sh changed -> rebuild
 *   (g) hooks/ changed        -> rebuild
 */

'use strict';

const path = require('path');
const { needsRebuild } = require(path.join(__dirname, '..', 'update.js'));

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

// ---------------------------------------------------------------------------
// Case (a): oldHead empty -> always rebuild
// ---------------------------------------------------------------------------

console.log('\nCase (a): null/empty oldHead -> full rebuild');
assert(needsRebuild('', 'abc123', []),            'empty string oldHead -> rebuild');
assert(needsRebuild(null, 'abc123', []),           'null oldHead -> rebuild');
assert(needsRebuild(undefined, 'abc123', []),      'undefined oldHead -> rebuild');
assert(needsRebuild('', '', []),                   'both empty oldHead -> rebuild (safety)');

// ---------------------------------------------------------------------------
// Case (b): old === new -> skip
// ---------------------------------------------------------------------------

console.log('\nCase (b): old === new -> skip');
assert(!needsRebuild('abc123', 'abc123', []),                         'identical SHAs -> skip');
assert(!needsRebuild('abc123', 'abc123', ['README.md']),              'identical SHAs, changed paths ignored -> skip');
assert(!needsRebuild('abc123', 'abc123', ['content/agents/foo.md']), 'identical SHAs, trigger path ignored -> skip');

// ---------------------------------------------------------------------------
// Case (c): content/ path changed -> rebuild
// ---------------------------------------------------------------------------

console.log('\nCase (c): content/ changed -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['content/agents/engineer.md']), 'content/agents/... -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['content/commands/brief.md']),  'content/commands/... -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['content/foo.txt']),             'content/foo.txt -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['README.md', 'content/x.md']), 'mixed: content/ among others -> rebuild');

// ---------------------------------------------------------------------------
// Case (d): bin/ path changed -> rebuild
// ---------------------------------------------------------------------------

console.log('\nCase (d): bin/ changed -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['bin/agentic-doctor']),          'bin/agentic-doctor -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['bin/agentic-cost']),            'bin/agentic-cost -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['README.md', 'bin/new-tool']),   'mixed: bin/ among others -> rebuild');

// ---------------------------------------------------------------------------
// Case (e): README.md / docs/ only -> skip
// ---------------------------------------------------------------------------

console.log('\nCase (e): doc-only changes -> skip');
assert(!needsRebuild('aaa', 'bbb', ['README.md']),                         'README.md only -> skip');
assert(!needsRebuild('aaa', 'bbb', ['docs/overview/vision.md']),           'docs/overview/... -> skip');
assert(!needsRebuild('aaa', 'bbb', ['CHANGELOG.md', 'docs/changelog.html']), 'changelog files -> skip');
assert(!needsRebuild('aaa', 'bbb', ['.gitignore', 'docs/technical/x.md']), 'gitignore + docs -> skip');

// ---------------------------------------------------------------------------
// Case (f): adapter build.sh (*/build.sh) -> rebuild
// ---------------------------------------------------------------------------

console.log('\nCase (f): adapter build.sh -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['.cursor/build.sh']),  '.cursor/build.sh -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['.claude/build.sh']), '.claude/build.sh -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['.codex/build.sh']),  '.codex/build.sh -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['scripts/build-all.sh']),         'scripts/build-all.sh -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['scripts/build-methodology.sh']), 'scripts/build-methodology.sh -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['scripts/build-slides.sh']),      'scripts/build-slides.sh -> rebuild');

// ---------------------------------------------------------------------------
// Case (g): hooks/ changed -> rebuild
// ---------------------------------------------------------------------------

console.log('\nCase (g): hooks/ changed -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['hooks/enforce-background-spawn.py']), 'hooks/enforce-*.py -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['hooks/stop-context.js']),             'hooks/stop-context.js -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['README.md', 'hooks/x.sh']),          'mixed: hooks/ among others -> rebuild');

// ---------------------------------------------------------------------------
// .claude/install.sh specifically -> rebuild
// ---------------------------------------------------------------------------

console.log('\nExtra: .claude/install.sh -> rebuild');
assert(needsRebuild('aaa', 'bbb', ['.claude/install.sh']), '.claude/install.sh -> rebuild');

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

console.log(`\n${passed + failed} test(s): ${passed} passed, ${failed} failed.\n`);
if (failed > 0) process.exit(1);
