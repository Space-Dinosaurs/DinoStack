#!/usr/bin/env node
/**
 * DS-62 Skeptic round-1 regression guard: pins the four spec-prose fixes made
 * to content/commands/wrap.md, content/commands/wrap-deferred.md, and
 * content/commands/ticket-status-sync.md after the first Skeptic pass on
 * commit c1982b9 (approve-with-minors, 4 findings).
 *
 * WHY THIS TEST EXISTS
 * --------------------
 * These are pure spec-prose findings with no runtime harness that exercises
 * command markdown - the "harness" is the human/LLM operator reading and
 * following the text. A grep-based structural guard is the cheapest thing
 * that can still catch a future edit silently reintroducing the same defect:
 *
 *   (1) wrap-deferred.md's "Omitted versus /wrap" table must enumerate
 *       Part F (the daemon has no Bash tool and spawns nothing, so it can
 *       never run Part F's tracker reconciliation).
 *   (2) wrap.md Part F's bounded git log call must use the CORRECT git
 *       option order: `-E --grep="..."` (regex flag before the grep
 *       predicate). The malformed form `--grep -E "..."` parses `-E` as
 *       the value of `--grep` and silently breaks the extended-regex flag.
 *   (3) Both the ticket-status-sync.md tracker-wide sweep and wrap.md's
 *       Part F must gate the evidence comment on the transition actually
 *       having succeeded - otherwise a persistently soft-failing transition
 *       re-posts the same evidence comment on every run.
 *
 * Run with: node hooks/tests/test-wrap-partF-skeptic-r1.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const WRAP_MD = path.join(REPO_ROOT, 'content', 'commands', 'wrap.md');
const WRAP_DEFERRED_MD = path.join(REPO_ROOT, 'content', 'commands', 'wrap-deferred.md');
const TICKET_STATUS_SYNC_MD = path.join(REPO_ROOT, 'content', 'commands', 'ticket-status-sync.md');

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

function readFile(p) {
  try { return fs.readFileSync(p, 'utf8'); } catch (_) { return null; }
}

console.log('\n[pre] required files exist');
const wrapText = readFile(WRAP_MD);
const wrapDeferredText = readFile(WRAP_DEFERRED_MD);
const ticketStatusSyncText = readFile(TICKET_STATUS_SYNC_MD);
assert(wrapText !== null, `wrap.md exists: ${path.relative(REPO_ROOT, WRAP_MD)}`);
assert(wrapDeferredText !== null, `wrap-deferred.md exists: ${path.relative(REPO_ROOT, WRAP_DEFERRED_MD)}`);
assert(ticketStatusSyncText !== null, `ticket-status-sync.md exists: ${path.relative(REPO_ROOT, TICKET_STATUS_SYNC_MD)}`);

if (wrapText === null || wrapDeferredText === null || ticketStatusSyncText === null) {
  console.log(`\n${passed} passed, ${failed} failed.`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// (1) wrap-deferred.md omission table enumerates Part F
// ---------------------------------------------------------------------------
console.log('\n[1] wrap-deferred.md omission table has a Part F row');
{
  const deferredTableRow = /\|\s*Part F.*\|\s*omitted.*Bash.*spawns nothing.*\|/i;
  assert(deferredTableRow.test(wrapDeferredText),
    'wrap-deferred.md "Omitted versus /wrap" table contains a Part F row citing no-Bash/spawns-nothing');
}

// ---------------------------------------------------------------------------
// (2) wrap.md Part F git log syntax is well-formed (regex flag before --grep)
// ---------------------------------------------------------------------------
console.log('\n[2] wrap.md Part F git log --grep syntax is well-formed');
{
  const malformed = /--grep\s+-E\s/;
  assert(!malformed.test(wrapText),
    'wrap.md does NOT contain the malformed form (--grep followed by a bare -E argument)');

  const wellFormed = /git log <BASE_BRANCH> -E --grep="<TICKET_PREFIX>-\[0-9\]\+"/;
  assert(wellFormed.test(wrapText),
    'wrap.md contains the corrected form: git log <BASE_BRANCH> -E --grep="<TICKET_PREFIX>-[0-9]+"');
}

// ---------------------------------------------------------------------------
// (3) Evidence comment gated on transition success (both sites)
// ---------------------------------------------------------------------------
console.log('\n[3] evidence comment gated on transition success, not posted unconditionally');
{
  assert(!ticketStatusSyncText.includes('independently of the transition'),
    'ticket-status-sync.md no longer describes the comment as posted independently of the transition');
  assert(/only when the transition succeeded/i.test(ticketStatusSyncText),
    'ticket-status-sync.md Tier 1 step 7 gates the evidence comment on transition success');

  assert(/Post the evidence comment .* only when the Writeback Helper reports the transition applied/i.test(wrapText),
    'wrap.md Part F gates the evidence comment on the Writeback Helper reporting the transition applied');
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed.`);
if (failed > 0) {
  process.exit(1);
}
process.exit(0);
