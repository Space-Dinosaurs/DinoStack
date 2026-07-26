#!/usr/bin/env bash
# Purpose: Prose-invariant regression guard for the In-flight code detection
#          section in content/commands/ds-ticket-triage.md (Unit 3 of the
#          triage-inflight-awareness plan). Like its sibling
#          test_ticket_rework_triage_badge.sh, this spec carries no
#          executable block for the detection logic itself - the only
#          runnable fragment is the `gh pr list` invocation example, which
#          this suite extracts and inspects (fence-scoped) rather than runs
#          (no network calls in CI). Everything else is prose that anchors
#          the read downstream of BOTH Phase 0 branches, before Phase 1, and
#          that documents the match predicate, precedence rule, and
#          degradation table a Worker or reader must get right. Three gates
#          (A, B, C) close the plan's central unguarded safety claim: that
#          the pre-existing rework/badge/lane invariants (Rules 1-4,
#          `num_chains` accounting, the consume-and-remainder invariant)
#          stay byte-identical while the four `in_progress: true` sites
#          (one definition, three consumers) gain or correctly withhold an
#          In-flight cross-reference.
#
# Public API: ./bin/tests/test_ticket_triage_inflight.sh
#             Exits 0 on all pass, 1 on any failure.
#             Auto-wired into CI by the bin/tests/test_*.sh glob in
#             .github/workflows/bin-tests.yml:62 - no orphans entry needed
#             (re-confirmed against that line at authoring time).
#
# Upstream deps: bash, grep, sed, awk. Reads content/commands/ds-ticket-triage.md
#                from the checkout. No jq, no python3, no network, no gh call -
#                pure text assertions and fence extraction, mirroring
#                test_ticket_rework_triage_badge.sh's approach.
#
# Downstream consumers: developer running locally before commit; CI
#                       (.github/workflows/bin-tests.yml).
#
# Failure modes: none beyond a failing assertion - this test makes no writes
#                and no network calls.
#
# Performance: < 1 s wall time (pure grep/sed/awk, no network).

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

_present() { # _present <label> <pattern> - whole-file presence
  if grep -qE "$2" "$SPEC"; then
    _pass "$1"
  else
    _fail "$1 - spec no longer contains: /$2/"
  fi
}
_absent() { # _absent <label> <pattern> - whole-file absence
  if grep -qE "$2" "$SPEC"; then
    _fail "$1 - spec still contains: /$2/"
  else
    _pass "$1"
  fi
}

# Section body, extracted once. Several assertions below are scoped to THIS
# range rather than the whole file, because some of their tokens (e.g.
# "phase=resolve-assigned", "phase=normalize") also appear in the earlier
# Ticket-rework detection section - a whole-file _present would pass
# trivially regardless of whether the NEW section says anything at all.
INFLIGHT_START="$(grep -n '^## In-flight code detection' "$SPEC" | head -1 | cut -d: -f1)"
INFLIGHT_END="$(grep -n '^## Phase 1: Metadata fetch' "$SPEC" | head -1 | cut -d: -f1)"
if [[ -z "$INFLIGHT_START" || -z "$INFLIGHT_END" ]]; then
  echo "FAIL: could not locate the In-flight code detection section boundaries" >&2
  exit 1
fi
SECTION_BODY="$(sed -n "${INFLIGHT_START},${INFLIGHT_END}p" "$SPEC")"

_present_section() { # _present_section <label> <pattern>
  if printf '%s' "$SECTION_BODY" | grep -qE "$2"; then
    _pass "$1"
  else
    _fail "$1 - In-flight section no longer contains: /$2/"
  fi
}
_absent_section() { # _absent_section <label> <pattern>
  if printf '%s' "$SECTION_BODY" | grep -qE "$2"; then
    _fail "$1 - In-flight section still contains: /$2/"
  else
    _pass "$1"
  fi
}

echo ""
echo "--- AC-1: positional - heading after BOTH Phase 0 breadcrumbs and the rework breadcrumb, before Phase 1 ---"
LINE_RESOLVE="$(grep -n 'phase=resolve-assigned' "$SPEC" | head -1 | cut -d: -f1)"
LINE_NORMALIZE="$(grep -n 'phase=normalize' "$SPEC" | head -1 | cut -d: -f1)"
LINE_REWORK_BREADCRUMB="$(grep -n '\[phase: ticket-triage \| phase=rework-detect\]' "$SPEC" | head -1 | cut -d: -f1)"
LINE_INFLIGHT="$INFLIGHT_START"
LINE_PHASE1="$INFLIGHT_END"

if [[ -z "$LINE_RESOLVE" || -z "$LINE_NORMALIZE" || -z "$LINE_REWORK_BREADCRUMB" || -z "$LINE_INFLIGHT" || -z "$LINE_PHASE1" ]]; then
  _fail "AC-1 positional: one or more anchor lines missing (resolve=$LINE_RESOLVE normalize=$LINE_NORMALIZE rework=$LINE_REWORK_BREADCRUMB inflight=$LINE_INFLIGHT phase1=$LINE_PHASE1)"
else
  if (( LINE_INFLIGHT > LINE_RESOLVE && LINE_INFLIGHT > LINE_NORMALIZE && LINE_INFLIGHT > LINE_REWORK_BREADCRUMB )); then
    _pass "AC-1: In-flight heading (line $LINE_INFLIGHT) sits after both Phase 0 breadcrumbs and the rework breadcrumb"
  else
    _fail "AC-1: In-flight heading (line $LINE_INFLIGHT) does NOT sit after both Phase 0 breadcrumbs and the rework breadcrumb (resolve=$LINE_RESOLVE, normalize=$LINE_NORMALIZE, rework=$LINE_REWORK_BREADCRUMB)"
  fi
  if (( LINE_INFLIGHT < LINE_PHASE1 )); then
    _pass "AC-1: In-flight heading (line $LINE_INFLIGHT) sits before Phase 1 (line $LINE_PHASE1)"
  else
    _fail "AC-1: In-flight heading (line $LINE_INFLIGHT) does NOT sit before Phase 1 (line $LINE_PHASE1)"
  fi
fi

echo ""
echo "--- AC-2: NOT run on Phase 0a path, reason given, limitation named ---"
_present_section "AC-2: states NOT executed on Phase 0a path, with reason" \
         'NOT executed on the .{0,10}/ds-implement-ticket. Phase 0a integration path: Phase 0a feeds its OWN already-normalized .entries\[\]. directly into triage Phase 1'
_present_section "AC-2: names the resulting limitation for /ds-implement-ticket A, B, C" \
         '/ds-implement-ticket A, B, C.{0,120}receives \*\*no\*\* in-flight code detection'

echo ""
echo "--- AC-3: dual-branch anchoring names both breadcrumbs and 'downstream of BOTH' ---"
_present_section "AC-3: section names the no-args breadcrumb (resolve-assigned)" \
         'phase=resolve-assigned'
_present_section "AC-3: section names the explicit-input breadcrumb (normalize)" \
         'phase=normalize'
_present_section "AC-3: section states it runs downstream of BOTH branches" \
         'downstream of BOTH'

echo ""
echo "--- AC-4: assignment rule - sets in_progress, no new category, four consumers ---"
_present_section "AC-4: sets entry.in_progress = true on a match" \
         'entry\.in_progress = true'
_present_section "AC-4: states this creates no new category" \
         'no new category'
_present_section "AC-4: enumerates all four inherited consumers (item 4 present)" \
         '\(4\) .triage_result\.in_progress_excluded\[\].'

echo ""
echo "--- AC-5: one call per run; no git branch -r / --repo INSIDE the section's code fences ---"
_present_section "AC-5: asserts one network call per run, O(1)" \
         'one network call per run, O\(1\)'
FENCE="$(printf '%s\n' "$SECTION_BODY" | awk '/^```/{f=!f; next} f')"
if [ -z "$FENCE" ]; then
  _fail "AC-5: in-flight invocation fence extracted empty - heading mismatch or missing code fence"
else
  if printf '%s\n' "$FENCE" | grep -q 'gh pr list --state open'; then
    _pass "AC-5: invocation fence contains the 'gh pr list --state open' call"
  else
    _fail "AC-5: invocation fence does not contain the 'gh pr list --state open' call"
  fi
  if printf '%s\n' "$FENCE" | grep -qE 'git branch -r|--repo'; then
    _fail "AC-5: fence contains 'git branch -r' or '--repo' (both deliberately removed)"
  else
    _pass "AC-5: fence contains no 'git branch -r' or '--repo' - prose may still name both legitimately"
  fi
fi

echo ""
echo "--- AC-6: match predicate documents the non-alphanumeric trailing AND leading guard ---"
_present_section "AC-6: match predicate documents both guards" \
         'following character is \*\*non-alphanumeric or absent\*\*.*preceding character is \*\*non-alphanumeric or absent\*\*'

echo ""
echo "--- AC-7: no .agentic/ read mentioned inside the section's own line range ---"
_absent_section "AC-7: section makes no .agentic/ reference" \
         '\.agentic/'

echo ""
echo "--- AC-10: evidence cap of 3 with (+N more) ---"
_present_section "AC-10: evidence cap of 3 entries with (+N more) documented" \
         'at most 3 entries per ticket.*\(\+N more\)'

echo ""
echo "--- AC-17: precedence rule - orthogonal flags, dual-PR Notes format ---"
_present_section "AC-17: precedence rule states IN_FLIGHT and IS_REWORK are orthogonal" \
         'IN_FLIGHT.*IS_REWORK.*are \*\*orthogonal\*\*'
_present "AC-17: dual-PR Notes format documented" \
         'in flight: open PR #<n>; prior attempt PR #<m> - verify both once back from in-progress'

echo ""
echo "--- AC-9: manifest Upstream deps names gh pr list; Performance names one-call-per-run ---"
# The manifest header is a multi-line HTML comment; grep -E has no cross-line
# match, so flatten the header block (between "<!--" and the FIRST "-->")
# onto one line before asserting - same technique as
# test_ticket_rework_triage_badge.sh.
HEADER_FLAT="$(awk '/<!--/{f=1} f{print} /-->/{if(f)exit}' "$SPEC" | tr '\n' ' ')"
if printf '%s' "$HEADER_FLAT" | grep -qE 'Upstream deps:.*gh CLI \(pr list'; then
  _pass "AC-9: manifest Upstream deps names the gh CLI pr list call"
else
  _fail "AC-9: manifest Upstream deps does not name the gh CLI pr list call"
fi
if printf '%s' "$HEADER_FLAT" | grep -qE 'Performance:.*one .gh pr list. call per triage run, not'; then
  _pass "AC-9: manifest Performance field names one-call-per-run"
else
  _fail "AC-9: manifest Performance field does not name one-call-per-run"
fi

echo ""
echo "--- AC-11: Phase 4b brief item (7) In-flight provenance ---"
_present "AC-11: Phase 4b brief contains item (7) In-flight provenance" \
         '\(7\) In-flight provenance'

echo ""
echo "--- AC-14: Soft-fail discipline names the gh call as neither tracker nor MCP ---"
_present "AC-14: Soft-fail discipline carries the gh-call extension" \
         'gh pr list. call \(neither a tracker call nor an MCP call\)'

echo ""
echo "--- AC-15: null/empty ticket_id skips detection ---"
_present_section "AC-15: precondition skips null/empty ticket_id, mirroring the rework guard" \
         'Detection is skipped for any entry whose .ticket_id. is null or empty'

echo ""
echo "--- AC-16: Phase 4b skip condition includes the no-IN_FLIGHT-exclusions clause ---"
_present "AC-16: Phase 4b skip condition names no IN_FLIGHT-sourced exclusions" \
         'zero lanes AND zero chains AND no IN_FLIGHT-sourced exclusions'

echo ""
echo "--- AC-19: Output carries the zero-lane honesty line verbatim ---"
_present "AC-19: zero-lane-with-in-flight-exclusions output line present" \
         'All candidate tickets are already in flight \(open PRs: <keys>\)\. No lanes to recommend\. Recommended next action: review those PRs before starting new work - or re-invoke with an explicit ticket id to override\.'

echo ""
echo "--- AC-20: Composition and non-goals carries the .agentic/-read non-goal ---"
_present "AC-20: non-goals list forbids any .agentic/ state read for in-flight detection" \
         'Perform any \.agentic/ state read for in-flight detection'

echo ""
echo "--- AC-21: both Phase 0 itinerary sites name the in-flight section ---"
_present "AC-21: no-args >=2 branch names In-flight code detection before Phase 1+" \
         'proceed into Ticket-rework detection, In-flight code detection, and Phase 1\+ exactly as for an explicit list input'
_present "AC-21: Edge-cases no-args >=2 row names In-flight code detection before Phase 1+" \
         'proceed into Ticket-rework detection, In-flight code detection, and Phase 1\+ as for an explicit list'

echo ""
echo "=== Gates A, B, C (verbatim from the plan - do not re-derive) ==="

# GATE A: the DEFINITION site of `in_progress: true` must point at the new section.
#
# ANCHOR-DRIVEN, NOT TOKEN-DRIVEN - and this is the third repair of this gate, so
# the reasoning matters. Grepping the bare `in_progress: true` token yields FOUR
# hits but only ONE is a definition site. The other three are CONSUMERS by this
# plan's own AC-4 taxonomy: the story-size preflight, Phase 3 removal, and the
# Edge-cases row. Step 2b says consumers are NOT annotated, so a token grep
# demanded In-flight pointers inside consumers - unresolvable against the
# plan's own text.
#
# The token set is not the site set. Gates B and C already iterate anchors; A
# does too. To add a definition site later, add its anchor to DEF_ANCHORS - do
# not reintroduce a token grep.
DEF_ANCHORS='\*\*In-progress detection:\*\*'
# PROCESS SUBSTITUTION, NOT A PIPE. In zsh the LAST stage of a pipeline runs in
# the CURRENT shell (bash forks a subshell for it), so `printf ... | while ...;
# done` plus `exit 1` inside the loop kills the entire script under zsh instead
# of just failing the gate - verified. Process substitution keeps the loop
# in-shell under BOTH, so MISSES can be incremented directly and no `exit` is
# needed. Same `< <(...)` form as the drift loop in the Verification command;
# do not "simplify" either back to a pipe.
while IFS= read -r A; do
  [ -n "$A" ] || continue
  LN=$(grep -nE "$A" "$SPEC" | head -1 | cut -d: -f1)
  if [ -z "$LN" ]; then
    _fail "Gate A: definition-site anchor vanished: /$A/"
    continue
  fi
  LO=$(( LN > 8 ? LN - 8 : 1 )); HI=$(( LN + 8 ))
  if sed -n "${LO},${HI}p" "$SPEC" | grep -qE 'IN_FLIGHT|In-flight code detection'; then
    _pass "Gate A: definition site /$A/ (line $LN) cross-references the In-flight section"
  else
    _fail "Gate A: definition site /$A/ (line $LN) has no In-flight cross-reference within +/-8 lines"
  fi
done < <(printf '%s\n' "$DEF_ANCHORS")

# GATE B: the four pre-existing `in_progress: true` sites must all SURVIVE, and the three
# CONSUMER sites must remain UN-annotated. Gate A proves the definition site gained a
# pointer; nothing in Gate A stops a Worker from deleting a consumer, or from "helpfully"
# annotating one against Step 2b. B closes both directions and is what AC-8's second and
# third limbs actually rest on.
#
# LINE-SCOPED EXCLUSION, NOT WINDOW-SCOPED. The story-size consumer sits ~2-4 lines below
# the definition site, so a +/-8 window around it necessarily overlaps the definition site,
# which by Gate A's own requirement DOES carry an In-flight pointer - a window-scoped
# `_absent` would therefore fail a fully correct spec. Each consumer's OWN line is the
# only sound scope. Do not widen it.
CONSUMER_ANCHORS='that is not `terminal: true` or `in_progress: true`
\*\*In-progress removal \(after Rule 1\):\*\*
\| Ticket with `IS_REWORK: true` AND `in_progress: true` \|'
while IFS= read -r A; do
  [ -n "$A" ] || continue
  HITS=$(grep -cE "$A" "$SPEC")
  if [ "$HITS" -ne 1 ]; then
    _fail "Gate B: consumer anchor /$A/ matched $HITS times (expected exactly 1) - site deleted or duplicated"
    continue
  fi
  if grep -E "$A" "$SPEC" | grep -qE 'IN_FLIGHT|In-flight code detection'; then
    _fail "Gate B: consumer site /$A/ was annotated with an In-flight pointer - Step 2b annotates definition sites ONLY"
  else
    _pass "Gate B: consumer site /$A/ present exactly once and correctly un-annotated"
  fi
done < <(printf '%s\n' "$CONSUMER_ANCHORS")

# GATE C: the three distribution-rule sentences this plan promises stay BYTE-IDENTICAL must
# still be present verbatim. This is the gate the Core-design section cites when it claims
# Rules 1-4, `num_chains` accounting, and the consume-and-remainder invariant are
# gate-enforced; without it that claim is unbacked prose.
#
# SCOPE HONESTLY (see AC-18): three `grep -qE` presence tests catch ALTERATION and DELETION
# of these sentences. They do NOT catch text APPENDED after them. That is adequate here
# only because this change touches no Rule text at all - if a future unit edits Rule
# prose, this gate is not sufficient and must be replaced with a hash or a range diff.
RULE_ANCHORS='\*\*Rule 3 - Parallel grouping \(sees only the remainder: tickets with zero internal DAG edges AND `entry\.IS_REWORK: false`\):\*\*
`num_chains` \(the total Rule 4 uses for cap accounting\) = `num_dep_chains \+ num_rework_lanes`
each rule consumes the tickets it assigns; later rules see only the remainder'
while IFS= read -r A; do
  [ -n "$A" ] || continue
  if grep -qE "$A" "$SPEC"; then
    _pass "Gate C: rule sentence present unaltered: /$A/"
  else
    _fail "Gate C: rule sentence altered or deleted - this unit must not touch Rule text: /$A/"
  fi
done < <(printf '%s\n' "$RULE_ANCHORS")

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -gt 0 ]] && exit 1
exit 0
