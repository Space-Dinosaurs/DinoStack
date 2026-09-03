#!/usr/bin/env bash
# Purpose: Pins the `## North Star alignment` section into BOTH Phase 9
#          `gh pr create` body branches in content/commands/ds-implement-ticket.md
#          (Case A - behavior-visible with QA evidence; Case B - all else), and
#          pins vision-alignment-check.yml to re-run on `edited`.
#
#          WHY THIS TEST EXISTS: `check-vision-alignment` is a REQUIRED check on
#          main and reads the PR body for a `## North Star alignment` section.
#          `gh pr create --body-file` bypasses .github/PULL_REQUEST_TEMPLATE.md
#          entirely (the template only populates web-UI PRs), so before this
#          section existed in the Phase 9 heredocs every conductor-composed PR
#          touching a methodology-shaping path opened with a red required check
#          by construction. A one-sided edit is the specific hazard: Case B is
#          the branch EVERY Trivial ticket takes, so dropping the section from
#          Case B alone would still look correct on any behavior-visible ticket
#          while reddening every Trivial one. The per-branch extraction below is
#          therefore load-bearing - a whole-file grep for the heading stays green
#          when only one branch loses it, since the binding prose note and the
#          other branch both still match.
#
#          The `edited` trigger is pinned alongside because the two defects
#          compound: without it, a body edit that adds the section never re-runs
#          the check, leaving the red permanent until an unrelated push.
#
#          Pillar 8 obligation. *Named catch:* a Phase 9 edit that drops the
#          section from one of the two PR-body branches - measured pre-fix as
#          0/4 assertions passing against origin/main, and as exactly 1/4
#          failing under a Case-B-only removal that leaves a whole-file grep
#          count of 2 and would keep a naive guard green.
#          *Retirement condition:* this suite retires when
#          "check-vision-alignment" leaves the required-checks list of the main
#          ruleset (14778332) - once the check cannot block a merge, a
#          one-sided drop costs a red X rather than a wedged PR, and the
#          producing-step pin stops earning its bytes.
#
# Public API: ./bin/tests/test_pr_body_north_star.sh
#             Exits 0 on all pass, 1 on any failure, 2 on a bad repo root.
#             Auto-wired into CI by the bin/tests/test_*.sh glob in
#             .github/workflows/bin-tests.yml - no orphans entry needed.
#
# Upstream deps: bash, grep, sed, awk, tr, cut, head, python3. awk and tr arrive
#                via the extraction pipeline lifted out of the workflow and
#                eval'd here, not from this file's own text; cut and head are
#                used by the pipeline/ordering line-number lookups. Reads
#                content/commands/ds-implement-ticket.md,
#                .github/workflows/vision-alignment-check.yml, and
#                .github/PULL_REQUEST_TEMPLATE.md from the checkout.
#                Honors GATE_REPO to override the root.
#
# Downstream consumers: developer running locally before commit; CI
#                       (.github/workflows/bin-tests.yml, bin-sh-tests job).
#
# Failure modes: python3 missing -> hard _fail (never a silently-skipped
#                assertion, which is indistinguishable from a passing one).
#                Read-only: no writes anywhere.
#
# Performance: < 1 s wall time (two file reads, no network).

set -uo pipefail

REPO_DIR="${GATE_REPO:-$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd)}"
cd "$REPO_DIR" 2>/dev/null || { echo "FATAL: cannot cd to '$REPO_DIR'" >&2; exit 2; }
DIT="$REPO_DIR/content/commands/ds-implement-ticket.md"
WF="$REPO_DIR/.github/workflows/vision-alignment-check.yml"
if [ ! -f "$DIT" ] || [ ! -f "$WF" ]; then
  echo "FATAL: '$REPO_DIR' is not a DinoStack repo root (expected content/commands/ds-implement-ticket.md and .github/workflows/vision-alignment-check.yml). Set GATE_REPO." >&2
  exit 2
fi

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

SECTION_HEADING='## North Star alignment'

# --- Per-branch extraction ----------------------------------------------------
# Split the Phase 9 `if`/`else` on its Case A and Case B marker comments, which
# the spec's own prose names, and assert the heading independently inside each
# half. A whole-file grep cannot distinguish a one-sided drop.
if ! command -v python3 >/dev/null 2>&1; then
  _fail "python3 not found on PATH - the per-branch extraction cannot run (a silently-skipped regression guard is indistinguishable from a passing one)"
else
  CASE_A_MARKER='# Case A: behavior-visible unit'
  CASE_B_MARKER='# Case B: all else'

  extract_branch() {
    # $1 = start marker, $2 = end marker ("" means to end of the PRBODY heredoc
    # that follows the start marker). Prints the branch text.
    python3 - "$DIT" "$1" "$2" <<'PY'
import sys
path, start_marker, end_marker = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path, encoding="utf-8").read()
start = text.find(start_marker)
if start == -1:
    sys.exit(3)
if end_marker:
    end = text.find(end_marker, start)
    if end == -1:
        sys.exit(4)
else:
    # End at the close of the first PRBODY heredoc after the marker.
    end = text.find("\nPRBODY\n", start)
    if end == -1:
        sys.exit(4)
sys.stdout.write(text[start:end])
PY
  }

  CASE_A="$(extract_branch "$CASE_A_MARKER" "$CASE_B_MARKER")"
  RC_A=$?
  CASE_B="$(extract_branch "$CASE_B_MARKER" "")"
  RC_B=$?

  if [ "$RC_A" -ne 0 ] || [ -z "$CASE_A" ]; then
    _fail "Case A branch not locatable in $DIT (anchor '$CASE_A_MARKER' .. '$CASE_B_MARKER', rc=$RC_A)"
  else
    printf '%s' "$CASE_A" | grep -qF "$SECTION_HEADING" \
      && _pass "Case A PR body heredoc contains '$SECTION_HEADING'" \
      || _fail "Case A PR body heredoc lacks '$SECTION_HEADING' - every behavior-visible ticket's PR would open with a red required check-vision-alignment"
  fi

  if [ "$RC_B" -ne 0 ] || [ -z "$CASE_B" ]; then
    _fail "Case B branch not locatable in $DIT (anchor '$CASE_B_MARKER' .. PRBODY, rc=$RC_B)"
  else
    printf '%s' "$CASE_B" | grep -qF "$SECTION_HEADING" \
      && _pass "Case B PR body heredoc contains '$SECTION_HEADING'" \
      || _fail "Case B PR body heredoc lacks '$SECTION_HEADING' - Case B is the branch EVERY Trivial ticket takes, so this reddens check-vision-alignment on every Trivial ticket"
  fi
fi

# --- Workflow: re-runs on a body-only edit ------------------------------------
# Assert MEMBERSHIP of each trigger, not the array's byte form: a reorder or a
# whitespace change is not a regression, and pinning the literal string would
# fail on one while missing a genuine drop that happened to preserve the shape.
WF_TYPES="$(sed -n 's/^[[:space:]]*types:[[:space:]]*\[\(.*\)\][[:space:]]*$/\1/p' "$WF" | head -1)"
if [ -z "$WF_TYPES" ]; then
  _fail "vision-alignment-check.yml has no 'types: [...]' array - the trigger list is unreadable"
else
  for t in opened edited synchronize reopened; do
    if printf '%s' "$WF_TYPES" | tr ',' '\n' | sed 's/[[:space:]]//g' | grep -qx "$t"; then
      _pass "vision-alignment-check.yml triggers on '$t'"
    elif [ "$t" = "edited" ]; then
      _fail "vision-alignment-check.yml does not trigger on 'edited' - adding the section by a body edit would never re-run the check, making the red permanent until an unrelated push"
    else
      _fail "vision-alignment-check.yml does not trigger on '$t'"
    fi
  done
fi

# --- Workflow: the error message no longer contradicts its required status -----
grep -qF 'advisory check, not a merge blocker' "$WF" \
  && _fail "vision-alignment-check.yml calls itself 'an advisory check, not a merge blocker' - check-vision-alignment IS a required context on main, so this teaches an operator to ignore a blocking red" \
  || _pass "vision-alignment-check.yml does not claim to be advisory (it is a required context on main)"

# --- Empirical: run the workflow's OWN extraction pipeline over three bodies ---
# Extracted from the shipped workflow rather than retyped, so a drift in the
# real awk/sed drifts this test with it. The unfilled case is the one that
# matters: presence alone is not an answer, and a bare presence test would call
# a body still carrying "[pillar]" verbatim a pass.
PIPE_START="$(grep -n 'SECTION="\$(printf' "$WF" | head -1 | cut -d: -f1)"
PIPE_END="$(grep -n "tr -d '\[:space:\]')\"" "$WF" | head -1 | cut -d: -f1)"
if [ -z "$PIPE_START" ] || [ -z "$PIPE_END" ] || [ "$PIPE_START" -gt "$PIPE_END" ]; then
  _fail "cannot locate the SECTION/STRIPPED pipeline in $WF (start '$PIPE_START', end '$PIPE_END')"
else
  PIPELINE="$(sed -n "${PIPE_START},${PIPE_END}p" "$WF" | sed 's/^ *//')"

  run_pipeline() {  # $1 = body text; echoes the STRIPPED result
    BODY="$1"
    eval "$PIPELINE"
    printf '%s' "$STRIPPED"
  }

  # The three fixtures below carry a resolved tracker reference line (DS-226)
  # positioned as the shipped template emits it: ABOVE the section heading, and so
  # OUTSIDE the region the check captures. That is realism - it keeps these bodies
  # shaped like real ones - and nothing more; none of the three would behave
  # differently without it. The hole itself (a tracker line INSIDE the captured
  # region, whose ticket ID alone is a non-empty "answer" that passes an unfilled
  # section) is pinned by BODY_UNFILLED_TRACKER_INSIDE, and the placement that
  # avoids it is pinned by the template-ordering block further down.
  BODY_ABSENT="$(printf '## Summary\n- x\n\nDS-226\n\n## Test plan\n- [ ] y\n')"
  BODY_UNFILLED="$(printf '## Summary\n- x\n\nDS-226\n\n## North Star alignment\n\n- Pillar(s) advanced (see docs/overview/vision.md): [pillar]\n- Trade-off or pillar this could regress, if any: [trade-off, or "none identified"]\n\n## Test plan\n- [ ] y\n')"
  BODY_FILLED="$(printf '## Summary\n- x\n\nDS-226\n\n## North Star alignment\n\n- Pillar(s) advanced (see docs/overview/vision.md): Pillar 7\n- Trade-off or pillar this could regress, if any: Pillar 8 - one more pin\n\n## Test plan\n- [ ] y\n')"

  # The hole the fixtures above now cover, pinned directly: a body with the
  # tracker line INSIDE the section (i.e. the section not placed last) must still
  # be rejected when unfilled. If this ever passes, the template was reordered.
  BODY_UNFILLED_TRACKER_INSIDE="$(printf '## Summary\n- x\n\n## North Star alignment\n\n- Pillar(s) advanced (see docs/overview/vision.md): [pillar]\n- Trade-off or pillar this could regress, if any: [trade-off, or "none identified"]\n\nDS-226\n\n## Test plan\n- [ ] y\n')"

  [ -z "$(run_pipeline "$BODY_ABSENT")" ] \
    && _pass "pipeline: a body with NO section fails the check (exit 1 path)" \
    || _fail "pipeline: a body with no section was accepted"

  [ -z "$(run_pipeline "$BODY_UNFILLED")" ] \
    && _pass "pipeline: a body with UNFILLED [pillar]/[trade-off] placeholders fails the check" \
    || _fail "pipeline: an UNFILLED section passed - the check is vacuous, green on a body that answers nothing (was unmissably red pre-fix)"

  [ -n "$(run_pipeline "$BODY_FILLED")" ] \
    && _pass "pipeline: a FILLED section passes the check" \
    || _fail "pipeline: a filled section was rejected - the check would block every compliant PR"

  # The two N/A shapes the Phase 9 fill rule makes binding must both pass. The
  # bare-line shape is what a consumer repo with no docs/overview/vision.md
  # emits; rejecting it would make the section unsatisfiable off this repo.
  BODY_NA_BARE="$(printf '## Summary\n- x\n\n## North Star alignment\n\nN/A - no docs/overview/vision.md in this repository\n\n## Test plan\n- [ ] y\n')"
  BODY_NA_BULLET="$(printf '## Summary\n- x\n\n## North Star alignment\n\n- Pillar(s) advanced (see docs/overview/vision.md): N/A - typo only\n- Trade-off or pillar this could regress, if any: none identified\n\n## Test plan\n- [ ] y\n')"

  [ -n "$(run_pipeline "$BODY_NA_BARE")" ] \
    && _pass "pipeline: the bare-line N/A shape (repo with no vision.md) passes" \
    || _fail "pipeline: the bare-line N/A shape was rejected - the section would be unsatisfiable in a repo with no docs/overview/vision.md"

  [ -n "$(run_pipeline "$BODY_NA_BULLET")" ] \
    && _pass "pipeline: the per-bullet N/A shape passes" \
    || _fail "pipeline: the per-bullet N/A shape was rejected"

  [ -n "$(run_pipeline "$BODY_UNFILLED_TRACKER_INSIDE")" ] \
    && _pass "pipeline: an unfilled section with the tracker line INSIDE it is (correctly) accepted - which is exactly why the template must keep the section last" \
    || _fail "pipeline: unexpected - the tracker-inside shape was rejected, so the ordering constraint below may no longer be load-bearing"

  # The shipped template's own section, lifted VERBATIM from the file rather than
  # retyped, so a reworded comment drifts this fixture with it. Its instruction
  # block is a MULTI-LINE HTML comment: a line-based s/<!--.*-->//g leaves it whole
  # and the surviving comment text becomes the "answer", passing an entirely
  # unfilled web-UI template. This is the fixture that pins the range-aware strip.
  TPL="$REPO_DIR/.github/PULL_REQUEST_TEMPLATE.md"
  if [ ! -f "$TPL" ]; then
    _fail "cannot read $TPL - the multi-line-comment fixture cannot be built from the shipped template"
  else
    TPL_SECTION="$(sed -n '/^## North Star alignment$/,/^## Review rigor$/p' "$TPL")"
    if ! printf '%s' "$TPL_SECTION" | grep -q '<!--'; then
      _fail "the template's '## North Star alignment' section no longer contains an HTML comment - this fixture is asserting nothing; re-derive it"
    else
      BODY_TEMPLATE_COMMENT="$(printf '## Summary\n- x\n\n%s\n' "$TPL_SECTION")"
      [ -z "$(run_pipeline "$BODY_TEMPLATE_COMMENT")" ] \
        && _pass "pipeline: the shipped template's UNFILLED section (multi-line HTML comment) fails the check" \
        || _fail "pipeline: the shipped template's unfilled section PASSED - its multi-line comment survived the strip and became the answer, so an untouched web-UI template satisfies a required check"
    fi
  fi

  # Ordering guard on the two comment strips: single-line comments must be closed
  # BEFORE the range delete. A bare '/<!--/,/-->/d' does not end a range on the
  # line it starts (sed resumes from the next line), so a trailing inline comment
  # would swallow the rest of the section and reject a legitimately filled body.
  BODY_FILLED_INLINE_COMMENT="$(printf '## Summary\n- x\n\nDS-226\n\n## North Star alignment\n\n- Pillar(s) advanced (see docs/overview/vision.md): Pillar 7 <!-- inline note -->\n- Trade-off or pillar this could regress, if any: none identified\n\n## Test plan\n- [ ] y\n')"
  [ -n "$(run_pipeline "$BODY_FILLED_INLINE_COMMENT")" ] \
    && _pass "pipeline: a FILLED answer carrying a trailing inline comment still passes" \
    || _fail "pipeline: a filled answer with an inline comment was rejected - the range delete swallowed it, so the two comment strips are in the wrong order"
fi

# --- Template ordering: the section sits LAST, directly above '## Test plan' ---
# Load-bearing, not cosmetic: the check captures from the section heading to the
# next '## ', so ANY content between them counts as an answer. With the tracker
# reference block inside that window, its ticket ID alone passes an unfilled
# section and the check goes vacuous - green on a body that answers nothing.
if ! command -v python3 >/dev/null 2>&1; then
  _fail "python3 not found on PATH - the template-ordering check cannot run (a silently-skipped regression guard is indistinguishable from a passing one)"
else
for marker in '# Case A: behavior-visible unit' '# Case B: all else'; do
  if [ "$marker" = '# Case A: behavior-visible unit' ]; then
    END_MARKER='# Case B: all else'
  else
    END_MARKER=''
  fi
  BRANCH="$(extract_branch "$marker" "$END_MARKER")"
  NS_LINE="$(printf '%s\n' "$BRANCH" | grep -n '^## North Star alignment$' | head -1 | cut -d: -f1)"
  TP_LINE="$(printf '%s\n' "$BRANCH" | grep -n '^## Test plan$' | head -1 | cut -d: -f1)"
  TR_LINE="$(printf '%s\n' "$BRANCH" | grep -n '^\[TRACKER_REFERENCE_BLOCK\]$' | head -1 | cut -d: -f1)"
  LABEL="${marker#\# }"
  if [ -z "$NS_LINE" ] || [ -z "$TP_LINE" ] || [ -z "$TR_LINE" ]; then
    _fail "$LABEL: cannot locate all three of the section heading, Test plan, and tracker block (ns='$NS_LINE' tp='$TP_LINE' tr='$TR_LINE')"
  elif [ "$TR_LINE" -lt "$NS_LINE" ] && [ "$NS_LINE" -lt "$TP_LINE" ]; then
    _pass "$LABEL: tracker block precedes the section, which sits directly above '## Test plan'"
  else
    _fail "$LABEL: template reordered - the tracker block must precede '## North Star alignment', which must precede '## Test plan' (got tracker=$TR_LINE section=$NS_LINE testplan=$TP_LINE). Any content captured between the section heading and the next '## ' passes an unfilled section."
  fi
done
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -gt 0 ] && exit 1
exit 0
