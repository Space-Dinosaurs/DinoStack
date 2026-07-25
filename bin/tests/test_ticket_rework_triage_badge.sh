#!/usr/bin/env bash
# Purpose: Prose-invariant regression guard for the ticket-rework badge/lane
#          rule in content/commands/ds-ticket-triage.md. Unlike
#          bin/tests/test_ticket_rework_ledger.sh (which extracts and RUNS
#          executable bash blocks), this file's spec carries no executable
#          block of its own for the ledger read - Phase 0 and the
#          ticket-rework detection step both reuse ds-implement-ticket.md's
#          logic "by reference", explicitly not forking or copying it. There
#          is therefore nothing here to extract and execute; what CAN drift
#          silently is the PROSE that anchors the read downstream of both
#          Phase 0 branches and outside the Phase 1 tracker gate - exactly the
#          failure mode flagged as most likely during this unit's review
#          (anchoring to only the "normalize" breadcrumb would silently drop
#          the badge for every no-args invocation, the default form for a
#          tracker-connected operator). This suite pins that prose, plus the
#          never-parallel lane rule and the manifest upstream-dep addition,
#          the same way test_ticket_rework_ledger.sh's own "Prose invariants"
#          section pins non-executable contract language in its sibling spec.
#
# Public API: ./bin/tests/test_ticket_rework_triage_badge.sh
#             Exits 0 on all pass, 1 on any failure.
#             Auto-wired into CI by the bin/tests/test_*.sh glob in
#             .github/workflows/bin-tests.yml - no orphans entry needed.
#
# Upstream deps: bash, grep. Reads content/commands/ds-ticket-triage.md from
#                the checkout. No jq, no python3, no network - pure text
#                assertions, since there is no runtime block to execute.
#
# Downstream consumers: developer running locally before commit; CI
#                       (.github/workflows/bin-tests.yml).
#
# Failure modes: none beyond a failing assertion - this test makes no writes
#                and no network calls.
#
# Performance: < 1 s wall time (pure grep, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SPEC="$REPO_DIR/content/commands/ds-ticket-triage.md"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

if [[ ! -f "$SPEC" ]]; then
  echo "FAIL: $SPEC not found" >&2
  exit 1
fi

_present() { # _present <label> <pattern>
  if grep -qiE "$2" "$SPEC"; then
    _pass "$1"
  else
    _fail "$1 - spec no longer contains: /$2/"
  fi
}
_absent() { # _absent <label> <pattern>
  if grep -qiE "$2" "$SPEC"; then
    _fail "$1 - spec still contains: /$2/"
  else
    _pass "$1"
  fi
}

echo ""
echo "--- Dual-branch anchoring: the read must cover BOTH Phase 0 branches ---"
# The failure mode this unit is most likely to ship: anchoring the read to
# only the explicit-input branch's breadcrumb would silently skip the badge
# for every no-args invocation (the default, tracker-connected shape).
_present "detection section names the no-args breadcrumb (resolve-assigned)" \
         'phase=resolve-assigned'
_present "detection section names the explicit-input breadcrumb (normalize)" \
         'phase=normalize'
_present "detection section states it runs downstream of BOTH branches" \
         'downstream of BOTH'
_present "detection section has its own terminal breadcrumb" \
         '\[phase: ticket-triage \| phase=rework-detect\]'

echo ""
echo "--- Outside the Phase 1 tracker gate ---"
_present "detection is explicitly NOT gated on TRACKER != none" \
         'NOT gated on .TRACKER != none'
_present "spec explains why: zero tracker/network calls" \
         'zero tracker and zero network calls'
_present "TRACKER=none named as the case detection matters most for" \
         'TRACKER=none.{0,40}(matters most|no tracker comment thread)'

echo ""
echo "--- Reuse by reference, not fork ---"
_present "detection reuses the implement-ticket algorithm by reference" \
         'reuse .{0,20}/ds-implement-ticket. Phase 1.{0,80}by reference'
_present "spec explicitly forbids forking the jq algorithm" \
         'Do not fork or re-derive'

echo ""
echo "--- The badge ---"
_present "the [REWORK xN] badge is documented" \
         '\[REWORK xN\]'
_present "badge placement is the Ticket cell of the per-ticket summary table" \
         'Ticket column: append .\[REWORK xN\].'

echo ""
echo "--- The never-parallel lane rule ---"
_present "rework isolation rule exists" \
         'Rework isolation \(after in-progress removal, before Rule 2\)'
_present "rework tickets are never designated parallel" \
         'never\*\* .parallel.'
_present "rework tickets get their own single-ticket chain" \
         'own single-ticket chain'
_present "rework tickets are not deferred and not excluded from kickoff" \
         'neither deferred nor excluded from kickoff'
_present "Notes cell annotation names the prior PR" \
         'Elevated floor, may draw Tier-3 Skeptic; verify PR'
_absent  "rework tickets are not silently folded into Rule 3 parallel grouping" \
         'rework .{0,40}parallel grouping'

echo ""
echo "--- Phase 4b checklist gains a 6th point ---"
_present "Phase 4b Skeptic brief checks rework isolation as item (6)" \
         '\(6\) Rework isolation'

echo ""
echo "--- Module manifest Upstream deps ---"
# The manifest header is a multi-line HTML comment; grep -E has no cross-line
# match, so flatten the header block (between "<!--" and the FIRST "-->")
# onto one line before asserting.
HEADER_FLAT="$(awk '/<!--/{f=1} f{print} /-->/{if(f)exit}' "$SPEC" | tr '\n' ' ')"
if printf '%s' "$HEADER_FLAT" | grep -qE 'Upstream deps:.*\.agentic/ticket-ledger\.jsonl'; then
  _pass "manifest Upstream deps names the ledger file"
else
  _fail "manifest Upstream deps names the ledger file - header no longer contains .agentic/ticket-ledger.jsonl in the Upstream deps field"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -gt 0 ]] && exit 1
exit 0
