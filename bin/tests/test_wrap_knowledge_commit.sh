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
CONV_DETAIL=content/references/conventions-detail.md

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

# 4. ds-emit knowledge_commit must appear inside Part G.
if grep -qF 'ds-emit knowledge_commit' "$WRAP"; then
  _pass "'ds-emit knowledge_commit' present in $WRAP"
else
  _fail "'ds-emit knowledge_commit' not found in $WRAP - Part G step 10's auditability event is missing."
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
#     content-derived (path + diff hash), not a bare path. The full
#     derivation was relocated out of content/rules/conventions.md (DS-74
#     resident-budget compression, #532) into content/references/
#     conventions-detail.md §Session-Start Sweeps - assert against its new
#     home, not the summary that replaced it inline.
CONVENTIONS=content/rules/conventions.md
if grep -qF '<path>:<hash>' "$CONV_DETAIL" && grep -qF 'SHA-256 of `git diff origin/<BASE_BRANCH> -- <path>`' "$CONV_DETAIL"; then
  _pass "knowledge-strand tracker key is content-derived (path + diff hash) in $CONV_DETAIL"
else
  _fail "knowledge-strand tracker key in $CONV_DETAIL is not content-derived - Major 1 regression."
fi

# 10b. The resident-set compression must be a genuine relocation, not a
#      silent drop: conventions.md keeps a short pointer to the new home and
#      must NOT still carry the full tracker-key derivation prose inline
#      (that would mean the budget fix double-counted the content instead of
#      moving it).
if grep -qF 'conventions-detail.md` §Session-Start Sweeps' "$CONVENTIONS"; then
  _pass "$CONVENTIONS points to conventions-detail.md §Session-Start Sweeps"
else
  _fail "$CONVENTIONS does not point to conventions-detail.md §Session-Start Sweeps - the knowledge-strand sweep pointer is missing."
fi
if grep -qF 'SHA-256 of `git diff origin/<BASE_BRANCH> -- <path>`' "$CONVENTIONS"; then
  _fail "$CONVENTIONS still carries the full tracker-key derivation prose inline - it was not actually relocated to $CONV_DETAIL, just duplicated."
else
  _pass "$CONVENTIONS no longer duplicates the tracker-key derivation prose (relocated, not copied)"
fi

# 11. Skeptic Major (final round) - the Part E clause in the deletion warning
#     is provably dead (Part E's target set and Part G's candidate set are
#     disjoint) and must be gone. The MEMORY-archive.md clause (DS-130) was a
#     DinoStack-local convention that leaked into the shipped methodology -
#     /ds-init-project never scaffolds a MEMORY-archive.md for consumer
#     projects, so the caveat was unreachable for every consumer and has been
#     retired; the deletion warning now prints unconditionally with no
#     archive-specific carve-out.
COUNT_PART_E_CLAUSE=$(grep -c 'Part E ran earlier\|Part E compressed' "$WRAP" || true)
if [ "$COUNT_PART_E_CLAUSE" -eq 0 ]; then
  _pass "the dead 'Part E ran earlier'/'Part E compressed' clause is absent from $WRAP (count=0)"
else
  _fail "'Part E ran earlier'/'Part E compressed' still appears $COUNT_PART_E_CLAUSE time(s) in $WRAP - the provably-dead Part E clause was not removed."
fi

if grep -qF 'moved verbatim to `MEMORY-archive.md`' "$WRAP"; then
  _fail "the MEMORY-archive.md clause is still present in the deletion warning in $WRAP - it was retired (DS-130) because /ds-init-project never scaffolds MEMORY-archive.md for consumer projects, making the caveat unreachable for every consumer."
else
  _pass "the MEMORY-archive.md clause is absent from the deletion warning in $WRAP (DS-130 retirement holds)"
fi

# 11c. DS-130 - the revert-risk warning itself is Part G's only defense
#      against a stale verbatim copy reverting content another session
#      already merged. It MUST survive the archive-caveat removal above -
#      this pins that survival so the two edits can never be conflated.
if grep -qF 'this commit may revert content another session already merged' "$WRAP"; then
  _pass "the revert-risk warning survives the DS-130 archive-caveat removal in $WRAP"
else
  _fail "the revert-risk warning is missing from $WRAP - Part G's only defense against a stale verbatim copy reverting merged content was lost."
fi

# 11d. DS-130 - the dangling "otherwise print the warning without that
#      caveat" connector must be gone too; it only made sense paired with the
#      archive-specific branch above and would otherwise survive as residue.
COUNT_WITHOUT_CAVEAT=$(grep -c 'without that caveat' "$WRAP" || true)
if [ "$COUNT_WITHOUT_CAVEAT" -eq 0 ]; then
  _pass "the dangling 'without that caveat' connector is absent from $WRAP (count=0)"
else
  _fail "'without that caveat' still appears $COUNT_WITHOUT_CAVEAT time(s) in $WRAP - the DS-130 archive-caveat retirement left this connector residue behind."
fi

# 12. Skeptic Minor 2 (final round) - a file absent from origin/<BASE_BRANCH>
#     must be treated as changed, not silently skipped, in BOTH ds-wrap.md's
#     Part G gating and the conventions.md sweep. `git diff --quiet` exits 0
#     (falsely "unchanged") for a path that was never committed to that ref.
if grep -qF 'git cat-file -e origin/<BASE_BRANCH>:<f>' "$WRAP"; then
  _pass "Part G's per-file gating in $WRAP handles the absent-from-ref case via git cat-file -e"
else
  _fail "Part G's per-file gating in $WRAP does not check git cat-file -e origin/<BASE_BRANCH>:<f> - a brand-new untracked knowledge file would be silently skipped by git diff --quiet's false 'unchanged' report."
fi

if grep -qF 'git cat-file -e origin/<BASE_BRANCH>:<path>' "$CONV_DETAIL"; then
  _pass "the knowledge-strand sweep in $CONV_DETAIL handles the absent-from-ref case via git cat-file -e"
else
  _fail "the knowledge-strand sweep in $CONV_DETAIL does not check git cat-file -e origin/<BASE_BRANCH>:<path> - it shares Part G's absent-from-ref defect and would silently skip a brand-new untracked knowledge file."
fi

# 13. Skeptic Minor 1 (final round) - the status enum must cover a steps-1-3
#     (worktree creation / file copy / git add) setup failure, not only the
#     step-4 missing-git-config "failed" status. Assert the new member is
#     present in BOTH the status enum list and the emit-on-every-path
#     enumeration, and that step 9's cleanup handles it.
if grep -qF '`committed`, `no-changes`, `setup-failed`, `commit-failed`, `push-failed`, `failed`' "$WRAP"; then
  _pass "the status enum list in $WRAP includes 'setup-failed' for a steps-1-3 failure"
else
  _fail "the status enum list in $WRAP does not include 'setup-failed' - a git-worktree-add, cp, or git-add failure has no status member to report (Minor 1 regression)."
fi

if grep -qF 'the setup-failure soft-fail (`status: "setup-failed"`)' "$WRAP"; then
  _pass "the emit-on-every-path enumeration in $WRAP names the setup-failure soft-fail"
else
  _fail "the emit-on-every-path enumeration in $WRAP does not name the setup-failure soft-fail - Minor 1's new status member is not wired into the 'emit on every path' contract."
fi

if grep -qF 'the steps-1-3 setup-failure soft-fail' "$WRAP"; then
  _pass "step 9's cleanup enumeration in $WRAP names the steps-1-3 setup-failure soft-fail"
else
  _fail "step 9's cleanup enumeration in $WRAP does not name the steps-1-3 setup-failure soft-fail - a leaked ephemeral worktree on setup failure would go undetected."
fi

# ---------------------------------------------------------------------------
# Phase 11e (knowledge commit onto the PR branch) and the Part G dedup gate.
#
# The Part G dedup bullet is the ONLY thing stopping Part G from re-committing
# knowledge Phase 11e already shipped, and it encodes three separately
# breakable contracts: a five-condition FAIL-OPEN rule, a load-bearing
# "deliberately LAST in the gating order" position, and a writer/reader
# filename contract on .agentic/knowledge-commit-state.json that spans two
# files. Behavioral coverage of the 11e block lives in
# bin/tests/test_phase11e_knowledge_commit_shell.py; the gate below is prose,
# so it is pinned here the same way every other normative sentence in this
# region is.
# ---------------------------------------------------------------------------

# 16. The new phase is numbered 11e, exactly once. This is the other half of
#     the `grep -c '11c' == 0` invariant above (assertions 3 and 4): that
#     invariant is what forced the 11e numbering in the first place, and
#     without this check a renumbering back onto 11c would break it silently.
COUNT_11E_HEADING=$(grep -c '^## Phase 11e:' "$IMPLEMENT_TICKET" || true)
if [ "$COUNT_11E_HEADING" -eq 1 ]; then
  _pass "the '## Phase 11e:' heading appears exactly once in $IMPLEMENT_TICKET"
else
  _fail "'## Phase 11e:' appears $COUNT_11E_HEADING time(s) in $IMPLEMENT_TICKET (expected exactly 1) - the knowledge-commit phase is missing, duplicated, or was renumbered (which would collide with the '11c' == 0 invariant asserted above)."
fi

# 17. Writer/reader filename contract. The marker file is WRITTEN by the
#     Phase 11e block and READ by Part G's dedup gate; they live in different
#     files, so renaming one side alone is a silent break with no conflict
#     marker. Assert both sides name the same file.
COUNT_STATE_WRITER=$(grep -c 'knowledge-commit-state\.json' "$IMPLEMENT_TICKET" || true)
COUNT_STATE_READER=$(grep -c 'knowledge-commit-state\.json' "$WRAP" || true)
if [ "$COUNT_STATE_WRITER" -ge 1 ] && [ "$COUNT_STATE_READER" -ge 1 ]; then
  _pass "'.agentic/knowledge-commit-state.json' is named on BOTH sides of the writer/reader contract ($IMPLEMENT_TICKET=$COUNT_STATE_WRITER, $WRAP=$COUNT_STATE_READER)"
else
  _fail "the knowledge-commit-state.json writer/reader contract is broken ($IMPLEMENT_TICKET=$COUNT_STATE_WRITER, $WRAP=$COUNT_STATE_READER; both must be >= 1) - Phase 11e writes the marker and Part G's dedup gate reads it, so a rename on one side alone silently disables the gate."
fi

# 18. The dedup gate must be FAIL-OPEN toward committing. A duplicate commit
#     is a reviewable diff; failing open toward SKIPPING silently drops
#     knowledge, which is the exact failure Part G exists to prevent.
if grep -qF 'the gate does NOT fire and Part G proceeds exactly as it does today' "$WRAP"; then
  _pass "the Part G dedup gate declares its fail-open direction in $WRAP"
else
  _fail "$WRAP does not state that any unmet condition leaves the dedup gate UNFIRED - a gate that fails open toward skipping would silently drop knowledge."
fi

# 19. All five gate conditions must be named. Dropping any one of them turns
#     the gate from "provably already shipped" into a guess.
MISSING_COND=""
for cond in 'parses as JSON' '`commit` field is non-empty' 'cat-file -e <commit>^{commit}' 'cat-file -e <commit>:<f>' 'diff --quiet <commit> -- <f>'; do
  grep -qF "$cond" "$WRAP" || MISSING_COND="$MISSING_COND [$cond]"
done
if [ -z "$MISSING_COND" ]; then
  _pass "all five dedup-gate conditions are named in $WRAP"
else
  _fail "the Part G dedup gate is missing condition(s):$MISSING_COND - each dropped condition lets the gate fire on unproven state and skip content that was never shipped."
fi

# 20. `deleted_lines` must be explicitly excluded: this gate is content-based,
#     not risk-based.
if grep -qF '`deleted_lines` is NOT consulted' "$WRAP"; then
  _pass "$WRAP states that deleted_lines is not consulted by the dedup gate"
else
  _fail "$WRAP does not state that deleted_lines is excluded from the dedup gate - a risk-based reading of a content-based gate would skip on the wrong signal."
fi

# 21. ORDERING (load-bearing). The dedup bullet must come AFTER the
#     byte-identity bullet. Hoisted above it, a genuinely UNCHANGED file would
#     report "already captured" instead of "unchanged". Compare line numbers
#     directly rather than trusting prose, same technique as assertion 6.
LINE_IDENTITY_BULLET=$(grep -n '^- File exists and is not gitignored, but is byte-identical to its' "$WRAP" | head -1 | cut -d: -f1)
LINE_DEDUP_BULLET=$(grep -n 'already captured onto a ticket PR branch by' "$WRAP" | head -1 | cut -d: -f1)
if [ -n "$LINE_IDENTITY_BULLET" ] && [ -n "$LINE_DEDUP_BULLET" ] && [ "$LINE_IDENTITY_BULLET" -lt "$LINE_DEDUP_BULLET" ]; then
  _pass "the dedup bullet (line $LINE_DEDUP_BULLET) follows the byte-identity bullet (line $LINE_IDENTITY_BULLET) in $WRAP"
else
  _fail "the Part G dedup bullet is not positioned after the byte-identity bullet in $WRAP (byte-identity line='$LINE_IDENTITY_BULLET', dedup line='$LINE_DEDUP_BULLET') - hoisted above it, a genuinely unchanged file reports 'already captured' rather than 'unchanged'."
fi

# 22. The step-10 payload sentence appended for the SECOND emit site.
if grep -qF 'one of `wrap-part-g` or `phase-11e`' "$WRAP"; then
  _pass "step 10's payload prose in $WRAP declares the two-site \`site\` field"
else
  _fail "$WRAP does not declare the \`site\` field's two values - the knowledge_commit event is now emitted from two sites and events.jsonl could not tell them apart."
fi

if grep -qF 'files ACTUALLY committed' "$WRAP" && grep -qF '`files_staged`' "$WRAP"; then
  _pass "step 10's payload prose in $WRAP defines files_staged and pins files_committed to files ACTUALLY committed"
else
  _fail "$WRAP does not define files_staged and/or does not pin files_committed's meaning - populating files_committed at staging time would make a failed push indistinguishable from a success."
fi

# 23. `no-branch` must be in the Phase 11e status enum. Without it, "there was
#     no PR branch to commit onto" is indistinguishable from "nothing changed"
#     in events.jsonl - the ambiguity that let this phase's deleted predecessor
#     ship zero commits for its entire lifetime unnoticed.
if grep -qF 'no-branch' "$WRAP" && grep -qF 'KC_STATUS="no-branch"' "$IMPLEMENT_TICKET"; then
  _pass "the 'no-branch' status is set in $IMPLEMENT_TICKET and documented in $WRAP's enum sentence"
else
  _fail "the 'no-branch' status is missing from $IMPLEMENT_TICKET's block and/or $WRAP's enum sentence - the ref-absent path would report 'no-changes', which is indistinguishable from 'nothing changed' in events.jsonl."
fi

# 24. The gitignore diagnostic must stay audible in the Phase 11e block too -
#     assertion 5 above already covers $WRAP, but the check-ignore gate now
#     exists in BOTH files and only one of them was protected.
COUNT_SUPPRESSED_CI_IT=$(grep -c 'check-ignore.*2>/dev/null' "$IMPLEMENT_TICKET" || true)
if [ "$COUNT_SUPPRESSED_CI_IT" -eq 0 ]; then
  _pass "check-ignore is never suffixed 2>/dev/null in $IMPLEMENT_TICKET (count=0)"
else
  _fail "check-ignore is suffixed 2>/dev/null $COUNT_SUPPRESSED_CI_IT time(s) in $IMPLEMENT_TICKET - this would suppress the Phase 11e gitignored-file diagnostic, which is load-bearing for correctness (git add refuses an ignored path without -f), not merely diagnostic."
fi

echo
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
