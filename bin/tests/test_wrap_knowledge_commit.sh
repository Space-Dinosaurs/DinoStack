#!/usr/bin/env bash
# Purpose: Pin the ds-wrap-knowledge-commit refactor (DS-108-adjacent, the
#          "commit knowledge files from /ds-wrap instead of a never-firing
#          Phase 11c bridge" change): /ds-wrap gains a Part G that commits
#          root MEMORY.md, decisions.md, and .agentic/learnings.md verbatim
#          to a fresh chore/knowledge-<date>-<hex> branch; the dead
#          knowledge-file-commit block in /ds-implement-ticket's former
#          Phase 11c is deleted (it never fired - zero chore(knowledge):
#          commits in repo history - and could not see learnings-agent /
#          learning-extractor writes); the independent Review-rigor
#          PR-body-evidence step is promoted to its own top-level Phase 11d.
#
#          Each assertion below is something a grep can honestly prove -
#          presence/absence of an identifier or literal string - not a
#          restatement of the prose. An assertion that only checks presence
#          without first asserting an expected count is a known vacuous-pass
#          risk on this repo (see MEMORY.md KNW-20260727-004/006); every
#          count-bearing check below asserts the count BEFORE the content
#          check that depends on it.
#
# Public API: none (executable test). Run with:
#             bash bin/tests/test_wrap_knowledge_commit.sh
#
# Upstream deps: bash 3.2+, grep. Read-only - asserts against the tracked
#                canonical source files, writes nothing.
#
# Downstream consumers: the `bin-sh-tests` CI job (.github/workflows/bin-tests.yml,
#                        `files=(bin/tests/test_*.sh)`), which glob-discovers
#                        this file - no separate CI wiring needed.
#
# Failure modes: this file runs `set -uo pipefail` WITHOUT -e (matching its
#                siblings bin/tests/test_absence_claim_scope_axes.sh and
#                bin/tests/test_loop_state_site_coverage.sh), so the exit
#                code is derived from the FAIL counter, never from the last
#                command's status. Every verdict routes through _pass/_fail
#                so a real miss cannot silently report "0 failed".
#
# Performance: < 1 s wall time (a handful of grep passes, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR" || exit 1

IMPLEMENT_TICKET=content/commands/ds-implement-ticket.md
WRAP=content/commands/ds-wrap.md

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

echo "--- ds-wrap knowledge-commit refactor ---"

# 1. The dead Phase 11c bridging variables must be fully gone from
#    ds-implement-ticket.md - they had no consumer outside the deleted range.
COUNT_MEMORY_MD_PATH=$(grep -c 'MEMORY_MD_PATH' "$IMPLEMENT_TICKET" || true)
if [ "$COUNT_MEMORY_MD_PATH" -eq 0 ]; then
  _pass "MEMORY_MD_PATH absent from $IMPLEMENT_TICKET (count=0)"
else
  _fail "MEMORY_MD_PATH still appears $COUNT_MEMORY_MD_PATH time(s) in $IMPLEMENT_TICKET - the dead Phase 11c bridging variable was not fully deleted."
fi

COUNT_APPEND_HELPER=$(grep -c '_ae_append_entries' "$IMPLEMENT_TICKET" || true)
if [ "$COUNT_APPEND_HELPER" -eq 0 ]; then
  _pass "_ae_append_entries absent from $IMPLEMENT_TICKET (count=0)"
else
  _fail "_ae_append_entries still appears $COUNT_APPEND_HELPER time(s) in $IMPLEMENT_TICKET - the dead knowledge-commit append helper was not fully deleted."
fi

# 2. Part G must exist in ds-wrap.md, in the zero-substance skip enumeration,
#    and in the relay-confirmation block.
COUNT_PART_G_HEADING=$(grep -c '^\*\*Part G - Knowledge-file commit\.\*\*' "$WRAP" || true)
if [ "$COUNT_PART_G_HEADING" -eq 1 ]; then
  _pass "Part G heading present exactly once in $WRAP"
else
  _fail "Part G heading found $COUNT_PART_G_HEADING time(s) in $WRAP (expected exactly 1) - Unit A's Part G section is missing or duplicated."
fi

if grep -qF 'Skip Part G (no session activity means no knowledge-file changes to commit)' "$WRAP"; then
  _pass "zero-substance enumeration lists 'Skip Part G'"
else
  _fail "zero-substance skip enumeration in $WRAP does not mention Part G - a zero-substance session would leave Part G's skip condition undocumented (spec item 11)."
fi

if grep -qF 'the Part G outcome (files committed and the pushed branch name' "$WRAP"; then
  _pass "relay-confirmation block reports the Part G outcome"
else
  _fail "relay-confirmation block in $WRAP does not report the Part G outcome - spec item 12 requires the confirmation to include it."
fi

# 3. The Review-rigor step must exist under its NEW phase label and must no
#    longer say "Phase 11c" anywhere in ds-implement-ticket.md (reusing 11c
#    would falsify ticket-rework.md's Trivial-path claim - see spec item 16).
if grep -qF '## Phase 11d: Review-rigor PR-body evidence (soft-fail)' "$IMPLEMENT_TICKET"; then
  _pass "Review-rigor promoted to its own '## Phase 11d' heading"
else
  _fail "'## Phase 11d: Review-rigor PR-body evidence (soft-fail)' not found in $IMPLEMENT_TICKET - the promoted top-level heading is missing or mislabeled."
fi

COUNT_11C=$(grep -c '11c' "$IMPLEMENT_TICKET" || true)
if [ "$COUNT_11C" -eq 0 ]; then
  _pass "'11c' no longer appears anywhere in $IMPLEMENT_TICKET (count=0)"
else
  _fail "'11c' still appears $COUNT_11C time(s) in $IMPLEMENT_TICKET - a self-reference to the deleted Phase 11c was left behind."
fi

# ticket-rework.md must describe the real mechanism (Phase 11b, genuinely
# skipped on the Trivial path) rather than the deleted Phase 11c.
TICKET_REWORK=content/references/ticket-rework.md
COUNT_REWORK_11C=$(grep -c '11c' "$TICKET_REWORK" || true)
if [ "$COUNT_REWORK_11C" -eq 0 ]; then
  _pass "'11c' no longer appears anywhere in $TICKET_REWORK (count=0)"
else
  _fail "'11c' still appears $COUNT_REWORK_11C time(s) in $TICKET_REWORK - the 'Why not Phase 11c' rationale was not reworded (spec item 18)."
fi

if grep -qF 'Phase 11b (the per-ticket' "$TICKET_REWORK"; then
  _pass "$TICKET_REWORK names Phase 11b as the mechanism genuinely skipped on Trivial"
else
  _fail "$TICKET_REWORK does not name Phase 11b as the Trivial-skipped mechanism - spec item 18's reword is missing."
fi

# 4. agentic-emit knowledge_commit must appear inside Part G.
if grep -qF 'agentic-emit knowledge_commit' "$WRAP"; then
  _pass "'agentic-emit knowledge_commit' present in $WRAP"
else
  _fail "'agentic-emit knowledge_commit' not found in $WRAP - Part G step 10's auditability event is missing."
fi

# 5. The check-ignore gate must be present, and must NOT be suffixed
#    2>/dev/null - the whole point of Unit A step 2's audibility requirement
#    is that this diagnostic is never suppressed.
if grep -qF 'git check-ignore -q -- <f>' "$WRAP"; then
  _pass "check-ignore gate present in $WRAP"
else
  _fail "'git check-ignore -q -- <f>' not found in $WRAP - the per-file gitignore gate is missing."
fi

COUNT_SUPPRESSED_CHECK_IGNORE=$(grep -c 'check-ignore.*2>/dev/null' "$WRAP" || true)
if [ "$COUNT_SUPPRESSED_CHECK_IGNORE" -eq 0 ]; then
  _pass "check-ignore is never suffixed 2>/dev/null in $WRAP (count=0)"
else
  _fail "check-ignore is suffixed 2>/dev/null $COUNT_SUPPRESSED_CHECK_IGNORE time(s) in $WRAP - this would silently suppress the gitignored-file diagnostic Unit A step 2 requires to stay audible."
fi

# 6. Skeptic Major 2 - the numstat deletion-warning step must precede the
#    commit step in Part G's numbered list, not follow it. Compare line
#    numbers directly rather than trusting the step-number labels, since a
#    label can be wrong while the text order is right or vice versa.
LINE_DELETION_WARNING=$(grep -n '^5\. \*\*Deletion warning\.\*\*' "$WRAP" | head -1 | cut -d: -f1)
LINE_COMMIT_STEP=$(grep -n '^6\. Commit with `git -C <worktree> commit -s`' "$WRAP" | head -1 | cut -d: -f1)
if [ -n "$LINE_DELETION_WARNING" ] && [ -n "$LINE_COMMIT_STEP" ] && [ "$LINE_DELETION_WARNING" -lt "$LINE_COMMIT_STEP" ]; then
  _pass "deletion-warning step (line $LINE_DELETION_WARNING) precedes the commit step (line $LINE_COMMIT_STEP) in $WRAP"
else
  _fail "deletion-warning step does not precede the commit step in $WRAP (deletion warning line='$LINE_DELETION_WARNING', commit line='$LINE_COMMIT_STEP') - Major 2 regression."
fi

# 7. Skeptic Major 3 - commit failure must have explicit handling AND be
#    named in step 9's cleanup enumeration.
if grep -qF 'If the commit fails' "$WRAP" && grep -qF 'status: "commit-failed"' "$WRAP"; then
  _pass "Part G defines explicit commit-failure handling with a commit-failed status in $WRAP"
else
  _fail "Part G is missing explicit commit-failure handling or the commit-failed status in $WRAP - Major 3 regression."
fi

if grep -qF 'the step-6 commit-failure soft-fail' "$WRAP"; then
  _pass "step 9's cleanup enumeration names the step-6 commit-failure soft-fail in $WRAP"
else
  _fail "step 9's cleanup enumeration in $WRAP does not name the step-6 commit-failure soft-fail - a leaked ephemeral worktree on commit failure would go undetected (Major 3 regression)."
fi

# 8. Skeptic Major 4 - the no-op path and the event-emission enumeration must
#    agree: the no-op line must NOT say "no event", and it must say the event
#    still fires. Assert the contradictory phrase is gone (count-first, per
#    this file's own vacuous-pass discipline) before asserting the fix text.
COUNT_NO_EVENT_CONTRADICTION=$(grep -c 'no worktree, no branch, no commit, no event' "$WRAP" || true)
if [ "$COUNT_NO_EVENT_CONTRADICTION" -eq 0 ]; then
  _pass "the contradictory 'no worktree, no branch, no commit, no event' phrase is absent from $WRAP (count=0)"
else
  _fail "'no worktree, no branch, no commit, no event' still appears $COUNT_NO_EVENT_CONTRADICTION time(s) in $WRAP - Major 4's no-op/event contradiction was not fixed."
fi

if grep -qF 'no worktree, no branch, no commit - but it still emits' "$WRAP"; then
  _pass "the no-op path in $WRAP now states the event still fires, matching step 10's enumeration"
else
  _fail "$WRAP does not state that the no-op path still emits an event - Major 4 regression."
fi

# skipped-ignored must no longer be a status enum member (unreachable per
# Major 4). It may still be mentioned in prose explaining its removal, and
# files_skipped_ignored remains a valid array field name - so assert the
# specific enum-list substring is gone, not the bare string anywhere.
COUNT_SKIPPED_IGNORED_ENUM=$(grep -c 'no-changes`, `skipped-ignored`' "$WRAP" || true)
if [ "$COUNT_SKIPPED_IGNORED_ENUM" -eq 0 ]; then
  _pass "the unreachable 'skipped-ignored' status enum member is absent from the status enum list in $WRAP (count=0)"
else
  _fail "'skipped-ignored' status still appears in the status enum list $COUNT_SKIPPED_IGNORED_ENUM time(s) in $WRAP - Major 4's unreachable-enum-member fix was not applied."
fi

# 9. Skeptic Major 5 - the dead "4th stacked first-user-turn notice"
#    quotation must be gone from ticket-rework.md.
COUNT_DEAD_QUOTE=$(grep -c 'the 4th stacked first-user-turn notice' "$TICKET_REWORK" || true)
if [ "$COUNT_DEAD_QUOTE" -eq 0 ]; then
  _pass "the dead '4th stacked first-user-turn notice' quotation is absent from $TICKET_REWORK (count=0)"
else
  _fail "'the 4th stacked first-user-turn notice' still appears $COUNT_DEAD_QUOTE time(s) in $TICKET_REWORK - Major 5 regression."
fi

# 10. Skeptic Major 1 - the knowledge-strand tracker key must be
#     content-derived (path + diff hash), not a bare path.
CONVENTIONS=content/rules/conventions.md
if grep -qF '<path>:<hash>' "$CONVENTIONS" && grep -qF 'SHA-256 of `git diff origin/<BASE_BRANCH> -- <path>`' "$CONVENTIONS"; then
  _pass "knowledge-strand tracker key is content-derived (path + diff hash) in $CONVENTIONS"
else
  _fail "knowledge-strand tracker key in $CONVENTIONS is not content-derived - Major 1 regression."
fi

echo
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
