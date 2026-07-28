#!/usr/bin/env bash
# Purpose: Pin the three scope axes named by the "Skeptic absence-or-critical
#          findings require conductor verification before action" rule in
#          content/sections/02-delegation.md, so a future compression back to
#          a single axis (the exact drift observed mid-ticket on DS-114, where
#          "case variants and paraphrases" silently vanished with no gate
#          objecting) fails loudly instead of passing every existing check.
#
#          Each axis closes a distinct motivating failure and is asserted
#          INDIVIDUALLY, with its own failure message naming which axis is
#          missing and why it exists - a single combined assertion would tell
#          a future reader only that "something" broke, not which axis to
#          restore:
#            - "the pattern"    - covers a token-scoped or case-sensitive grep
#                                 that misses a semantic variant of the term
#                                 being searched for.
#            - "the file set"   - covers a search confined to one file (or too
#                                 few files) that misses a restatement of the
#                                 same rule living elsewhere in the tree.
#            - "any closed list" - covers an enumerated vocabulary certified
#                                 complete when a legitimate value is missing
#                                 from it; no amount of widening the pattern or
#                                 the file set answers a completeness question
#                                 about a closed list.
#
#          A second gate confirms the pre-existing freshness half of the same
#          rule (the reason the rule exists in the first place - stale git
#          state producing a false absence claim) has not been silently
#          dropped alongside a future edit to the scope-axis clause.
#
# Public API: none (executable test). Run with:
#             bash bin/tests/test_absence_claim_scope_axes.sh
#
# Upstream deps: bash 3.2+, grep. Read-only - asserts against the tracked
#                canonical source file, writes nothing.
#
# Downstream consumers: the `bin-sh-tests` CI job (.github/workflows/bin-tests.yml,
#                        `files=(bin/tests/test_*.sh)`), which glob-discovers
#                        this file - no separate CI wiring needed.
#
# Failure modes: this file runs `set -uo pipefail` WITHOUT -e (matching its
#                sibling bin/tests/test_loop_state_site_coverage.sh), so the
#                exit code is derived from the FAIL counter, never from the
#                last command's status. Every verdict below routes through
#                _pass/_fail so a real miss cannot silently report "0 failed".
#
# Performance: < 1 s wall time (a handful of `grep -c` passes, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR" || exit 1

FILE=content/sections/02-delegation.md

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

echo "--- absence-claim scope axes (content/sections/02-delegation.md) ---"

# Axis 1: the pattern (token/case narrowness).
if grep -qF 'broaden the pattern' "$FILE"; then
  _pass "axis 'the pattern' present"
else
  _fail "AXIS MISSING: 'the pattern' not found in $FILE - this axis covers a token-scoped or case-sensitive grep that misses a semantic variant of the term being searched for. Restore it; do not compress the remedy clause back to a single axis."
fi

# Axis 2: the file set (search confined to too few files).
if grep -qF 'the file set' "$FILE"; then
  _pass "axis 'the file set' present"
else
  _fail "AXIS MISSING: 'the file set' not found in $FILE - this axis covers a search confined to one file (or too few files) that misses a restatement of the same rule living elsewhere in the tree. Restore it; do not compress the remedy clause back to a single axis."
fi

# Axis 3: any closed list (enumeration completeness).
if grep -qF 'any closed list' "$FILE"; then
  _pass "axis 'any closed list' present"
else
  _fail "AXIS MISSING: 'any closed list' not found in $FILE - this axis covers an enumerated vocabulary certified complete when a legitimate value is missing from it; no amount of widening the pattern or the file set answers a completeness question about a closed list. Restore it; do not compress the remedy clause back to a single axis."
fi

# Freshness half: confirm the pre-existing rule this clause extends is still
# present, byte-for-byte on its closing sentence, and was not dropped or
# rewritten alongside a future edit to the scope-axis clause.
if grep -qF 'is not a substitute for verifying falsifiable claims before acting on them.' "$FILE"; then
  _pass "freshness half present (closing sentence intact)"
else
  _fail "FRESHNESS HALF MISSING: the closing sentence of the pre-existing freshness rule ('...is not a substitute for verifying falsifiable claims before acting on them.') was not found in $FILE. That half addresses stale git state producing a false absence claim and must survive any edit to the adjacent scope-axis clause."
fi

echo
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
