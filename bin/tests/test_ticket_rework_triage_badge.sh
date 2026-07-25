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
_present "rework isolation rule exists, anchored after Rule 2 (Critical fix)" \
         'Rework isolation \(after Rule 2, before Rule 3\)'
_present "rework tickets are never designated parallel" \
         'never\*\* .parallel.'
_present "rework tickets get their own single-ticket chain" \
         'own single-ticket chain'
_present "rework tickets are not deferred and not excluded from kickoff" \
         'neither deferred nor excluded from kickoff'
_present "Notes cell annotation names the prior PR" \
         'Elevated floor, may draw Tier-3 Skeptic; verify PR'
_present "Rule 2 explicitly consumes DAG-connected rework tickets (Critical fix)" \
         'including any member separately flagged .entry\.IS_REWORK: true'
_present "Rule 2 explains why isolation would sever the in-set edge" \
         'silently severing that edge'
_present "Rule 3 excludes rework tickets from its own remainder" \
         'zero internal DAG edges AND .entry\.IS_REWORK: false'
_present "Notes-cell rule documents the blocked-by + rework combined format" \
         'blocked by A; rework x2 - Elevated floor'
_present "Rule 4 message distinguishes rework-induced lanes from dependency chains (Minor 1)" \
         'dependency chain\(s\) plus'
_present "Rule 4 message names num_rework_lanes distinctly from num_dep_chains" \
         'num_rework_lanes.*rework-isolated ticket'

echo ""
echo "--- In-progress + rework interaction (Minor 2) ---"
_present "in-progress rework ticket gets a combined badge" \
         '\[IN PROGRESS\] \[REWORK xN\]'
_present "spec states this is the only place that signal appears" \
         'ONLY place an in-progress rework ticket'

echo ""
echo "--- No-args fallthrough no longer reads as bypassing the new section (Minor 3) ---"
_present "no-args >=2 branch names Ticket-rework detection before Phase 1+" \
         'proceed into Ticket-rework detection and Phase 1\+'

echo ""
echo "--- Phase 4b checklist gains a 6th point ---"
_present "Phase 4b Skeptic brief checks rework annotation as item (6)" \
         '\(6\) Rework annotation'

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
echo "--- Module manifest Performance field (Minor 5) ---"
if printf '%s' "$HEADER_FLAT" | grep -qE 'Performance:.*ticket-ledger\.jsonl'; then
  _pass "manifest Performance field names the per-entry ledger read cost"
else
  _fail "manifest Performance field does not mention the per-entry ticket-ledger.jsonl read cost"
fi

echo ""
echo "--- Positional check (Minor 4): heading must sit after BOTH breadcrumbs, before Phase 1 ---"
# All 19 assertions above are string presence/absence - none of them pin the
# *position* of the '## Ticket-rework detection' heading. Someone could move
# the heading back inside the explicit-input branch (leaving all the prose
# above intact) and every string check would still pass. This is the exact
# defect class flagged during review: a move that string-matching cannot see.
LINE_RESOLVE="$(grep -n 'phase=resolve-assigned' "$SPEC" | head -1 | cut -d: -f1)"
LINE_NORMALIZE="$(grep -n 'phase=normalize' "$SPEC" | head -1 | cut -d: -f1)"
LINE_HEADING="$(grep -n '^## Ticket-rework detection' "$SPEC" | head -1 | cut -d: -f1)"
LINE_PHASE1="$(grep -n '^## Phase 1: Metadata fetch' "$SPEC" | head -1 | cut -d: -f1)"

if [[ -z "$LINE_RESOLVE" || -z "$LINE_NORMALIZE" || -z "$LINE_HEADING" || -z "$LINE_PHASE1" ]]; then
  _fail "positional check: one or more anchor lines missing (resolve=$LINE_RESOLVE normalize=$LINE_NORMALIZE heading=$LINE_HEADING phase1=$LINE_PHASE1)"
else
  if (( LINE_HEADING > LINE_RESOLVE && LINE_HEADING > LINE_NORMALIZE )); then
    _pass "Ticket-rework detection heading (line $LINE_HEADING) sits AFTER both Phase 0 breadcrumbs (resolve=$LINE_RESOLVE, normalize=$LINE_NORMALIZE)"
  else
    _fail "Ticket-rework detection heading (line $LINE_HEADING) does NOT sit after both breadcrumbs (resolve=$LINE_RESOLVE, normalize=$LINE_NORMALIZE) - it may have been moved back inside a Phase 0 branch"
  fi

  if (( LINE_HEADING < LINE_PHASE1 )); then
    _pass "Ticket-rework detection heading (line $LINE_HEADING) sits BEFORE Phase 1 (line $LINE_PHASE1)"
  else
    _fail "Ticket-rework detection heading (line $LINE_HEADING) does NOT sit before Phase 1 (line $LINE_PHASE1)"
  fi
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -gt 0 ]] && exit 1
exit 0
