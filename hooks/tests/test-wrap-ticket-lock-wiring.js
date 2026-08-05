#!/usr/bin/env node
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

console.log(`\n${failed === 0 ? 'ALL PASS' : failed + ' FAILED'}`);
process.exit(failed === 0 ? 0 : 1);
