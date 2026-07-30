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

echo
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
