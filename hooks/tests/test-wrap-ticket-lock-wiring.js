#!/usr/bin/env node
/**
 * WHY THIS TEST EXISTS
 * --------------------
 * Wiring guard for the Phase 11b wrap-lock acquire/release contract in
 * content/commands/ds-implement-ticket.md and content/agents/wrap-ticket.md:
 * confirms the bounded-wait acquisition mechanism (DS-127) is present with
 * both attempts, all documented exit-code branches, the findings_log hold
 * instruction, and the PATH-not-found install message - plus confirms
 * wrap-ticket.md's replacement conductor-side-lock-contract prose and
 * harmonized early-exit JSON shape, and that the dead pre-DS-127 `mkdir`
 * shell snippet is gone.
 *
 * Assertion (9) additionally guards acquire/release anchor symmetry: both
 * `agentic-wrap-acquire-lock` calls in Phase 11b are explicitly rooted at
 * `"$REPO"`, and the release call MUST use the same explicit root, never a
 * bare invocation. `agentic-wrap-release-lock` resolves its root from an
 * optional positional argument, falling back to `process.cwd()` when the
 * argument is omitted. A bare release call resolves against the conductor's
 * cwd - if cwd differs from `$REPO`, the release silently no-ops (the
 * helper fails open) and the live, heartbeating `--role=agent` lock leaks
 * for the rest of the session, blocking every later `/ds-wrap` and skipping
 * every later Phase 11b. Without this assertion, a future edit that drops
 * the `"$REPO"` argument from only the release call (while leaving both
 * acquire calls untouched) passes every other assertion in this file.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const IMPL_PATH = path.join(__dirname, '..', '..', 'content', 'commands', 'ds-implement-ticket.md');
const WRAP_TICKET_PATH = path.join(__dirname, '..', '..', 'content', 'agents', 'wrap-ticket.md');

const implText = fs.readFileSync(IMPL_PATH, 'utf8');
const wrapTicketText = fs.readFileSync(WRAP_TICKET_PATH, 'utf8');

let failed = 0;
function assert(cond, msg) {
  if (!cond) { console.error('FAIL: ' + msg); failed++; }
  else { console.log('PASS: ' + msg); }
}

const phase11bMatch = implText.match(/## Phase 11b: Wrap learnings[\s\S]*?(?=\n## Phase 11d)/);
assert(phase11bMatch, 'Phase 11b section found in ds-implement-ticket.md');
const phase11bText = phase11bMatch ? phase11bMatch[0] : '';

// (1) OLD mechanism gone
assert(!implText.includes('(atomic `mkdir`)'),
  'ds-implement-ticket.md no longer describes lock acquisition as "(atomic mkdir)"');

// (2) NEW mechanism present with the exact bound and both invocations
assert(phase11bText.includes('--timeout-ms=45000'),
  'Phase 11b invokes the bounded background retry with --timeout-ms=45000');
assert(phase11bText.includes('--no-wait'),
  'Phase 11b invokes the first attempt with --no-wait');
assert((phase11bText.match(/agentic-wrap-acquire-lock/g) || []).length >= 2,
  'Phase 11b invokes agentic-wrap-acquire-lock at least twice (both attempts)');

// (3) All required exit-code branches present
assert(/\*\*0\*\*\s*-\s*acquired/.test(phase11bText), 'Phase 11b documents exit 0 (acquired)');
assert(/\*\*5\*\*\s*-\s*busy/.test(phase11bText), 'Phase 11b documents exit 5 (busy)');
assert(/\*\*2\*\*\s*-\s*timeout/.test(phase11bText), 'Phase 11b documents exit 2 (timeout)');
assert(/\*\*1\*\*\s*-\s*fatal/.test(phase11bText), 'Phase 11b documents exit 1 (fatal)');
assert(phase11bText.includes('any other exit code'),
  'Phase 11b documents an "any other exit code" fallback branch');

// (4) findings_log hold instruction present
assert(phase11bText.includes('MUST NOT advance to Phase 11d'),
  'Phase 11b explicitly forbids advancing past the background wait before it resolves');
assert(phase11bText.includes('findings_log'),
  'Phase 11b hold instruction references findings_log explicitly');

// (5) PATH-not-found install message ported
assert(phase11bText.includes('not found on PATH'),
  'Phase 11b ports the not-found-on-PATH install-step message');

// (6) wrap-ticket.md: dead shell block gone; no fenced block of ANY tag (or none)
// carries a wrap/lock mkdir pattern, so a re-introduced untagged block is caught.
assert(!wrapTicketText.includes('mkdir .agentic/wrap/lock 2>/dev/null'),
  'wrap-ticket.md no longer contains the dead mkdir shell snippet');
{
  const fenceRe = /```[^\n]*\n([\s\S]*?)```/g;
  let m;
  let foundRogueBlock = false;
  while ((m = fenceRe.exec(wrapTicketText)) !== null) {
    if (/wrap\/lock/.test(m[1]) && /mkdir/.test(m[1])) foundRogueBlock = true;
  }
  assert(!foundRogueBlock,
    'wrap-ticket.md contains no fenced code block (any language tag, or none) with a wrap/lock mkdir pattern');
}

// (7) replacement prose describes the conductor-side contract
assert(wrapTicketText.includes('never spawned unless the conductor already holds'),
  'wrap-ticket.md states the conductor-already-holds-the-lock precondition');

// (8) early-exit JSON shape harmonized
const earlyExitMatch = wrapTicketText.match(/"skipped_reason":\s*"wrap-lock-contention"[\s\S]{0,200}/);
assert(earlyExitMatch && earlyExitMatch[0].includes('cluster_results'),
  'wrap-ticket.md early-exit JSON includes cluster_results');
assert(earlyExitMatch && earlyExitMatch[0].includes('resolved_paths'),
  'wrap-ticket.md early-exit JSON includes resolved_paths');

// (9) acquire/release lock anchor symmetry: both acquire calls and the
// release call must all be rooted at the same explicit "$REPO" argument.
// A bare release call (no root argument) resolves against the conductor's
// cwd instead, which silently no-ops the release and leaks the lock when
// cwd differs from $REPO. See file header for the full failure mode.
{
  const acquireRepoCount = (phase11bText.match(/agentic-wrap-acquire-lock "\$REPO"/g) || []).length;
  assert(acquireRepoCount >= 2,
    'Phase 11b roots both agentic-wrap-acquire-lock calls at an explicit "$REPO" argument');
  assert(phase11bText.includes('agentic-wrap-release-lock "$REPO"'),
    'Phase 11b roots the agentic-wrap-release-lock call at an explicit "$REPO" argument');
  // The paragraph legitimately mentions the bare form once, explanatorily,
  // to describe the failure mode ("a bare `agentic-wrap-release-lock`
  // resolves against the conductor's cwd instead"). Exclude that specific
  // explanatory phrasing and assert no OTHER bare (unrooted) occurrence
  // exists - in particular, not as the actual invoked release call.
  const allBareMatches = phase11bText.match(/`agentic-wrap-release-lock`/g) || [];
  const explanatoryBareMatches = phase11bText.match(/a bare `agentic-wrap-release-lock`/g) || [];
  assert(allBareMatches.length === explanatoryBareMatches.length,
    'Phase 11b does not invoke a bare agentic-wrap-release-lock (no root argument) as the actual release call');
}

console.log(`\n${failed === 0 ? 'ALL PASS' : failed + ' FAILED'}`);
process.exit(failed === 0 ? 0 : 1);
