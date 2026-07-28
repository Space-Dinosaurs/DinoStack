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
_present_section "Minor regression (fix pass 2): consumer (4) carries the same Rule-1 carve-out as consumers (1) and (3)" \
         'never also in .in_progress_excluded\[\].'

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
echo "--- AC-17: precedence rule - independent sources, IS_REWORK orthogonal, no fixed 'both true' string ---"
_present_section "AC-17: precedence rule states IN_FLIGHT and IN_PROGRESS_TRACKER are independent" \
         'entry\.IN_FLIGHT.*entry\.IN_PROGRESS_TRACKER.*are \*\*independent\*\*'
_present_section "AC-17: precedence rule states IS_REWORK is orthogonal to both" \
         'entry\.IS_REWORK. is \*\*orthogonal\*\* to both'

echo ""
echo "--- Major 1 regression: Notes-cell composition is compositional, not three fixed strings ---"
# The Skeptic's diagnosis: the suite must pin STATE COVERAGE, not just sentence presence.
# These assertions would have failed against the pre-fix spec, where the Notes cell was a
# fixed three-way branch that printed "not the tracker column" even when the tracker column
# genuinely had moved (the tracker+PR overlap case - the common real-world workflow).
_present_section "Major-1 regression: composition rule defines the tracker-column qualifier's own omission condition" \
         'Omit this qualifier whenever .entry\.IN_PROGRESS_TRACKER. is also true'
_present_section "Major-1 regression: in-flight clause template documented" \
         'in flight: open PR #<n>'
_present_section "Major-1 regression: rework-with-in-flight clause template documented" \
         'prior attempt PR #<m> - verify both once back from in-progress'
_present_section "Major-1 regression: rework-only (no in-flight) clause template documented" \
         'verify PR #<m> once back from in-progress'
_present_section "Major-1 regression: tracker-column qualifier template documented" \
         'detected from an open PR, not the tracker column'
# State-coverage: all six reachable (tracker-moved x PR-open x rework) combinations have a
# worked example row in the In-progress tickets table.
for ROW_ANCHOR in \
  '\| Z \[IN PROGRESS\] \|' \
  '\| W \[IN PROGRESS\] \[REWORK x1\] \|' \
  '\| DS-12 \[IN PROGRESS\] \|' \
  '\| DS-34 \[IN PROGRESS\] \|' \
  '\| DS-40 \[IN PROGRESS\] \[REWORK x1\] \|' \
  '\| DS-41 \[IN PROGRESS\] \[REWORK x1\] \|'
do
  _present "Major-1 regression: worked-example row present: /$ROW_ANCHOR/" "$ROW_ANCHOR"
done
# THE failure mode itself: the tracker+PR overlap example (DS-34) must NOT carry the false
# "not the tracker column" claim - this is the literal defect the Skeptic found.
DS34_ROW="$(grep -E '^\| DS-34 \[IN PROGRESS\] \|' "$SPEC")"
if [ -z "$DS34_ROW" ]; then
  _fail "Major-1 regression: DS-34 example row not found - cannot verify the false-claim fix"
elif printf '%s' "$DS34_ROW" | grep -q 'not the tracker column'; then
  _fail "Major-1 regression: DS-34 (tracker+PR overlap) row still claims 'not the tracker column' - this is the exact false claim the fix removes"
elif printf '%s' "$DS34_ROW" | grep -q 'in flight: open PR'; then
  _pass "Major-1 regression: DS-34 (tracker+PR overlap) row names the PR WITHOUT the false tracker-column claim"
else
  _fail "Major-1 regression: DS-34 row does not name an in-flight PR at all"
fi
# Sanity: DS-12 (PR-only, tracker did NOT move) DOES carry the qualifier - proves the
# qualifier-omission logic is conditional, not simply deleted.
DS12_ROW="$(grep -E '^\| DS-12 \[IN PROGRESS\] \|' "$SPEC")"
if printf '%s' "$DS12_ROW" | grep -q 'not the tracker column'; then
  _pass "Major-1 regression: DS-12 (PR-only, tracker did not move) row correctly carries the qualifier"
else
  _fail "Major-1 regression: DS-12 row is missing the tracker-column qualifier it should carry"
fi

echo ""
echo "--- Fix-pass-2 regression: the WRITER of entry.IN_PROGRESS_TRACKER, not just mentions of it ---"
# Fix pass 1 added three assertions that merely MENTION IN_PROGRESS_TRACKER; none pinned the
# statement that actually SETS it. Deleting the writer (Phase 1's In-progress detection
# sentence) leaves the flag permanently false for every ticket - clause 4's trigger
# ("entry.IN_PROGRESS_TRACKER is false") then fires unconditionally, reintroducing Major 1's
# false claim across all six cells, with zero presence-only assertion noticing. This is the
# DS-96 failure class: a field read by a gate with no writer, failing open.
_present "Fix-pass-2 regression: the WRITER statement for entry.IN_PROGRESS_TRACKER exists" \
         'marked `in_progress: true` and `entry\.IN_PROGRESS_TRACKER = true`'

echo ""
echo "--- Fix-pass-2 regression: clause 4's trigger condition, both polarities, pinned verbatim ---"
# Pinning only the omit-sentence (as fix pass 1 did) leaves the TRIGGER unguarded: flipping
# "IN_PROGRESS_TRACKER is false" to "is true" instructs the conductor to print the false claim
# in exactly the overlap case, while the omit-sentence a few words later still says the
# opposite - self-contradictory, and invisible to a presence-only check on the omit sentence.
_present_section "Fix-pass-2 regression: clause 4 trigger requires IN_FLIGHT true AND IN_PROGRESS_TRACKER false (both polarities pinned)" \
         '`entry\.IN_FLIGHT` is true AND `entry\.IN_PROGRESS_TRACKER` is false'

echo ""
echo "--- Fix-pass-2 regression: DS-40 and DS-41 get the same positive/negative content checks as DS-12/DS-34 ---"
# DS-40 (PR+rework, tracker did NOT move) MUST carry the qualifier.
DS40_ROW="$(grep -E '^\| DS-40 \[IN PROGRESS\] \[REWORK x1\] \|' "$SPEC")"
if [ -z "$DS40_ROW" ]; then
  _fail "Fix-pass-2 regression: DS-40 example row not found"
elif printf '%s' "$DS40_ROW" | grep -q 'not the tracker column'; then
  _pass "Fix-pass-2 regression: DS-40 (PR+rework, tracker did not move) row correctly carries the qualifier"
else
  _fail "Fix-pass-2 regression: DS-40 row is missing the tracker-column qualifier it should carry"
fi
# DS-41 (tracker+PR+rework overlap) must NOT carry the qualifier - the column DID move.
DS41_ROW="$(grep -E '^\| DS-41 \[IN PROGRESS\] \[REWORK x1\] \|' "$SPEC")"
if [ -z "$DS41_ROW" ]; then
  _fail "Fix-pass-2 regression: DS-41 example row not found"
elif printf '%s' "$DS41_ROW" | grep -q 'not the tracker column'; then
  _fail "Fix-pass-2 regression: DS-41 (tracker+PR+rework overlap) row still claims 'not the tracker column' - the column DID move"
elif printf '%s' "$DS41_ROW" | grep -q 'prior attempt PR'; then
  _pass "Fix-pass-2 regression: DS-41 (tracker+PR+rework overlap) row names both PRs WITHOUT the false tracker-column claim"
else
  _fail "Fix-pass-2 regression: DS-41 row does not carry the dual-PR rework clause"
fi

echo ""
echo "--- Fix-pass-2 regression: Z and W (no PR evidence) never render an in-flight clause ---"
# Extends the same content-check discipline to the two tracker-only cells - a corruption that
# added a bogus in-flight clause to a tracker-only ticket would have been invisible to the
# presence-only row-existence loop above.
Z_ROW="$(grep -E '^\| Z \[IN PROGRESS\] \|' "$SPEC")"
if printf '%s' "$Z_ROW" | grep -qE 'in flight:|not the tracker column'; then
  _fail "Fix-pass-2 regression: Z (tracker-only, no PR) row wrongly carries an in-flight clause or qualifier"
else
  _pass "Fix-pass-2 regression: Z (tracker-only, no PR) row carries no in-flight clause"
fi
W_ROW="$(grep -E '^\| W \[IN PROGRESS\] \[REWORK x1\] \|' "$SPEC")"
if printf '%s' "$W_ROW" | grep -qE 'in flight:|not the tracker column'; then
  _fail "Fix-pass-2 regression: W (tracker+rework, no PR) row wrongly carries an in-flight clause or qualifier"
elif printf '%s' "$W_ROW" | grep -q 'verify PR #501 once back from in-progress'; then
  _pass "Fix-pass-2 regression: W (tracker+rework, no PR) row carries the rework-only clause and no in-flight clause"
else
  _fail "Fix-pass-2 regression: W row is missing its rework-only clause"
fi

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
echo "--- Major 2 regression: IN_FLIGHT on a Rule-1-deferred ticket has a defined, non-universal disposition ---"
# Pre-fix, item (7) was universally quantified over EVERY entry.IN_FLIGHT: true ticket,
# including ones Rule 1 defers before they ever reach a Notes-bearing table - an
# unsatisfiable obligation for a correctly-produced artifact. These assertions pin the
# scoping fix, not just sentence presence.
_present "Major-2 regression: item (7) scopes the Notes-cell obligation to the In-progress table" \
         'reaching the In-progress tickets table \(Notes-bearing\) with .entry\.IN_FLIGHT: true.'
_present "Major-2 regression: item (7) defines the disjoint Rule-1-deferred disposition" \
         'ticket Rule 1 deferred \(no Notes cell in that table\) that also carries .entry\.IN_FLIGHT: true.'
_present "Major-2 regression: Interaction-with-Rule-1-deferral note exists" \
         '\*\*Interaction with Rule 1 deferral \(binding\)\.\*\*'
_present "Major-2 regression: Deferred tickets Reason-cell IN_FLIGHT extension documented" \
         'Reason cell IN_FLIGHT extension'
_present "Major-2 regression: Deferred tickets worked example (terminal + in-flight) present" \
         '\| V \| terminal \(Done\); in flight: open PR #440 \|'
_present "Major-2 regression: Edge cases row for Rule-1-deferred + in-flight ticket" \
         'Ticket deferred by Rule 1 .terminal / external blocker / fetch-failed / cycle. that also has an open PR'
_present "Major-2 regression: that Edge-cases row states it is NOT an IN_FLIGHT-sourced exclusion" \
         'Does NOT count as an IN_FLIGHT-sourced kickoff exclusion'

echo ""
echo "--- DS-105 (1): Interaction-with-Rule-1-deferral note - load-bearing sentence, not just the title ---"
# Presence-only pinning (Major-2 regression above) only anchors the BOLD TITLE. Gutting the
# entire note body to "Handled elsewhere." left the 72-assertion suite green (measured). Pin
# the sentence that actually establishes Rule 1's precedence over the In-progress-removal step.
_present "DS-105 (1): note states Rule 1's deferral takes precedence over In-progress removal" \
         "Rule 1's deferral takes precedence: such a ticket is removed by Rule 1 before the In-progress-removal step ever runs"

echo ""
echo "--- DS-105 (2): Deferred tickets Reason-cell extension - instruction body, not just title + example row ---"
# Presence-only pinning (Major-2 regression above) only anchors the HTML comment's title and the
# worked \`| V |\` row. Gutting the instruction body between them left the suite green (measured).
# The comment spans multiple lines, so flatten it the same way the manifest header block is
# flattened above (AC-9) before asserting.
DEFERRED_COMMENT="$(awk '/<!-- Reason cell IN_FLIGHT extension/{f=1} f{print} /-->/{if(f)exit}' "$SPEC" | tr '\n' ' ' | tr -s ' ')"
if [ -z "$DEFERRED_COMMENT" ]; then
  _fail "DS-105 (2): Deferred tickets Reason-cell comment block extracted empty - heading mismatch or comment removed"
else
  if printf '%s' "$DEFERRED_COMMENT" | grep -qE 'append "; in flight: open PR #<n>" \(with the "\(\+N more\)" cap, same rendering as the in-flight clause in the Notes-cell composition rule\) to the Reason cell'; then
    _pass "DS-105 (2): comment body specifies the exact Reason-cell append format and cap re-use"
  else
    _fail "DS-105 (2): comment body no longer specifies the Reason-cell append format and cap re-use"
  fi
  if printf '%s' "$DEFERRED_COMMENT" | grep -qE 'This does NOT count as an IN_FLIGHT-sourced kickoff exclusion \(Phase 4b skip condition / Output item 7 below\) - the ticket was already deferred for its own Rule 1 reason'; then
    _pass "DS-105 (2): comment body links the non-exclusion rule to Phase 4b skip condition / Output item 7"
  else
    _fail "DS-105 (2): comment body no longer links the non-exclusion rule to Phase 4b skip condition / Output item 7"
  fi
fi

echo ""
echo "--- DS-105 (3): Notes-cell composition clause 2 - (+N more) cap linkage, previously unpinned ---"
# No prior assertion anywhere in this suite pinned the sentence tying \`(+N more)\` to
# \`entry.IN_FLIGHT_EVIDENCE[]\` exceeding the Evidence cap (measured: deleting the phrase left
# the suite green). Scoped to the In-flight section since this is where clause 2 is defined.
_present_section "DS-105 (3): in-flight clause ties (+N more) to entry.IN_FLIGHT_EVIDENCE[] exceeding the Evidence cap" \
         'followed by . \(\+N more\). when .entry\.IN_FLIGHT_EVIDENCE\[\]. exceeds the Evidence cap below'

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
_present "Major-2 regression: skip condition explicitly excludes Rule-1-deferred+in-flight tickets from the count" \
         'a Rule-1-deferred ticket that also carries .entry\.IN_FLIGHT. does NOT count here'

echo ""
echo "--- DS-105 (4): skip condition uses a structural predicate, matching Output item 7's phrasing style ---"
# The pre-fix wording ("no ticket reaches the In-progress tickets table because of
# entry.IN_FLIGHT") was loose for the both-sources case: a ticket with IN_PROGRESS_TRACKER
# also true would reach the table via the tracker column regardless of IN_FLIGHT. Output item
# 7 (below) already answers the analogous question with a structural predicate over table
# state rather than causal ("because of") language; this brings the skip condition into the
# same style. Positive: new structural predicate present. Negative: the old loose causal
# phrasing is gone.
_present "DS-105 (4): skip condition states the structural predicate (IN_PROGRESS_TRACKER true OR IN_FLIGHT false)" \
         'every entry in .## In-progress tickets. carries .entry\.IN_PROGRESS_TRACKER: true. or .entry\.IN_FLIGHT: false.'
_absent "DS-105 (4): skip condition no longer uses the loose causal 'because of entry.IN_FLIGHT' phrasing" \
         'reaches the In-progress tickets table because of .entry\.IN_FLIGHT.'

echo ""
echo "--- AC-19: Output carries the zero-lane honesty line verbatim ---"
_present "AC-19: zero-lane-with-in-flight-exclusions output line present" \
         'All candidate tickets are already in flight \(open PRs: <keys>\)\. No lanes to recommend\. Recommended next action: review those PRs before starting new work - or re-invoke with an explicit ticket id to override\.'

echo ""
echo "--- Minor 1 regression: the zero-lane honesty line requires ALL exclusions to be in-flight, not just >=1 ---"
# Pre-fix (original), the print condition was "zero lanes AND >=1 in-flight exclusion" - a mix
# of (2 terminal-deferred + 1 in-flight) also has zero lanes and would have wrongly triggered
# "All candidate tickets are already in flight". Fix pass 1's remedy introduced a SECOND
# defect (Skeptic fix-pass-2 Minor): its main clause and parenthetical were non-equivalent for
# a terminal-plus-open-PR ticket. Fix pass 2 replaces both with a single unambiguous,
# table-structure definition that reuses the skip condition's own "IN_FLIGHT-sourced
# exclusion" term instead of inventing a second gloss.
_present "Minor-1 regression: condition is stated as a single unambiguous, table-structure definition" \
         'equivalently: .## Deferred tickets. is empty AND every entry in .## In-progress tickets. carries .entry\.IN_FLIGHT: true.'
_present "Minor-1 regression: fallback correctly routes the terminal-plus-open-PR edge case away from the false claim" \
         'a terminal-plus-open-PR ticket lands in .## Deferred tickets., so its presence alone routes here, not to the special print'

echo ""
echo "--- Minor 2 regression: Disclaimer enumerates all three false-positive paths, not just one ---"
# Pre-fix, the Disclaimer claimed the stale-open-PR case was "the ONE remaining
# false-positive path" - contradicted by the plan's own Known limitations, which name two
# more (title-match false positives; DS-4.1 matching key DS-4).
_present_section "Minor-2 regression: disclaimer names the title-match false positive" \
         'title match on unrelated wording'
_present_section "Minor-2 regression: disclaimer names the dotted-key over-match false positive" \
         'dotted-key over-match'
_absent_section "Minor-2 regression: disclaimer no longer asserts a false 'one remaining' absolute" \
         'is the one remaining false-positive path'

echo ""
echo "--- Minor 3 regression: --limit 100 truncation follows the file's own truncate-plus-warning convention ---"
_present_section "Minor-3 regression: truncation notice documented" \
         '\*\*Truncation notice\.\*\*'
_present_section "Minor-3 regression: truncation notice specifies the emitted text" \
         'In-flight evidence truncated at 100 open PRs'

echo ""
echo "--- Minor 4 regression: degradation notice line specifies its emission point ---"
_absent_section "Minor-4 regression: degradation row no longer promises an unspecified 'one notice line'" \
         'call fails \| total no-op; no flags set; one notice line'
_present_section "Minor-4 regression: degradation row specifies the notice text and emission point" \
         'In-flight code detection skipped: <reason>. once, immediately after the failed/skipped call, before Phase 1 begins'

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
