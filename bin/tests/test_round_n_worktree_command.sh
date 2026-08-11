#!/usr/bin/env bash
# Purpose: executable regression spec for the DS-157 "Round-N rework
#          mechanic" `worktree_setup.create_commands` branch-already-exists
#          form (content/commands/ds-implement-ticket.md §Elevated-path
#          engineer-contract extensions; canonical prose also referenced
#          from content/references/worktree-lifecycle.md §Round-N rework
#          mechanic). A round-1 Skeptic review found the ORIGINAL prose form
#          (`git worktree add $WORKTREE_PATH $BRANCH_NAME --track
#          origin/$BRANCH_NAME`) was a git syntax error (exit 129) that also
#          never provided the stale-local-ref defense it was written for -
#          this spec proves the corrected `-B` form actually works, in a
#          disposable scratch git repo under a temp directory (never touches
#          the real DinoStack checkout, worktree, or branch state).
#
# Public API: none (standalone script; `bash bin/tests/test_round_n_worktree_command.sh`).
#
# Upstream deps: none (self-contained scratch-repo fixture). Prose-wiring
#                check greps content/commands/ds-implement-ticket.md,
#                resolved relative to this script's repo root.
#
# Downstream consumers: CI (bin-sh-tests); DS-157 round-2 Skeptic review
#                       (outcome_rubric row 1 and row 7).
#
# Failure modes: exits non-zero if (a) the corrected `-B` command does not
#                exit 0 against a LAGGING local branch ref, (b) the
#                resulting worktree HEAD does not match origin's tip exactly,
#                (c) the already-checked-out fatal does not reproduce (exit
#                128) when a second worktree add targets a branch already
#                checked out elsewhere, (d) the `git worktree list
#                --porcelain` reuse guard fails to identify the existing
#                worktree path, or (e) content/commands/ds-implement-ticket.md
#                still contains the pre-fix `--track origin/$BRANCH_NAME`
#                positional form (the exact reverted-defect regression
#                guard). Cleans up its scratch repos on exit via a trap
#                regardless of outcome.
#
# Performance: sub-second; a handful of `git worktree add`/`remove` calls in
#              throwaway bare-clone repos.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMPL_DOC="$REPO_ROOT/content/commands/ds-implement-ticket.md"
SCRATCH="$(mktemp -d)"

cleanup() {
  rm -rf "$SCRATCH" 2>/dev/null || true
}
trap cleanup EXIT

# --- Prose-wiring / reverted-defect regression guard -----------------------
# The exact pre-fix syntax-error form must never reappear, and the corrected
# form must be present.
check_prose_wiring() {
  local doc="$1"
  local ok=0

  if [ ! -f "$doc" ]; then
    echo "PROSE-WIRING VIOLATION: $doc not found" >&2
    return 1
  fi

  if grep -q -- 'worktree add \$WORKTREE_PATH \$BRANCH_NAME --track origin/\$BRANCH_NAME' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc re-introduced the syntax-error --track positional form in the actual create_commands value" >&2
    ok=1
  fi
  if ! grep -q -- 'worktree add \$WORKTREE_PATH -B \$BRANCH_NAME origin/\$BRANCH_NAME' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not contain the corrected -B worktree-add form" >&2
    ok=1
  fi
  if ! grep -q 'already checked out at' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not document the already-checked-out guard" >&2
    ok=1
  fi

  return "$ok"
}

# --- Scratch repo setup -----------------------------------------------------
# Bare-clone origin + one working checkout ("repo"), matching the real
# $REPO / origin topology. A branch is pushed, then advanced by a SECOND
# push from a throwaway worktree while "repo"'s own local tracking ref for
# that branch stays behind - reproducing the lagging-local-ref precondition
# the -B form exists to defend against.
setup_repo() {
  git init -q --bare "$SCRATCH/origin.git"
  git clone -q "$SCRATCH/origin.git" "$SCRATCH/repo"
  git -C "$SCRATCH/repo" config user.email spec@example.com
  git -C "$SCRATCH/repo" config user.name spec
  git -C "$SCRATCH/repo" commit -q --allow-empty -m init
  git -C "$SCRATCH/repo" branch -M main
  git -C "$SCRATCH/repo" push -q origin main

  # Create feat/test via a throwaway worktree, push, remove - "repo" itself
  # never checks out feat/test directly (mirrors the conductor's shared
  # checkout staying on a different branch than the ticket branch).
  git -C "$SCRATCH/repo" worktree add -q -b feat/test "$SCRATCH/tmpwt" origin/main
  git -C "$SCRATCH/tmpwt" commit -q --allow-empty -m c1
  git -C "$SCRATCH/tmpwt" push -q origin feat/test
  git -C "$SCRATCH/repo" worktree remove --force "$SCRATCH/tmpwt"

  # Advance origin/feat/test AGAIN from a second throwaway worktree, so
  # "repo"'s local feat/test ref (created above, pointing at c1) now LAGS
  # the true origin tip (c2) - the precondition under test.
  git -C "$SCRATCH/repo" worktree add -q -b feat/test-scratch "$SCRATCH/tmpwt2" origin/feat/test
  git -C "$SCRATCH/tmpwt2" commit -q --allow-empty -m c2
  git -C "$SCRATCH/tmpwt2" push -q origin feat/test-scratch:feat/test
  git -C "$SCRATCH/repo" worktree remove --force "$SCRATCH/tmpwt2"
}

echo "== Prose-wiring check: $IMPL_DOC uses the corrected -B form, not the syntax-error --track positional =="
check_prose_wiring "$IMPL_DOC"
r0=$?
echo "prose-wiring exit=$r0"

echo "== Scenario 1: lagging local ref - corrected -B form must exit 0 and land on the ORIGIN tip =="
setup_repo
REPO="$SCRATCH/repo"
WT1="$SCRATCH/wt-roundn"
git -C "$REPO" fetch origin >/dev/null 2>&1
git -C "$REPO" worktree add "$WT1" -B feat/test origin/feat/test >/dev/null 2>&1
r1=$?
head_sha="$(git -C "$WT1" rev-parse HEAD 2>/dev/null)"
origin_tip="$(git -C "$REPO" rev-parse origin/feat/test 2>/dev/null)"
echo "scenario1 exit=$r1 head=$head_sha origin_tip=$origin_tip"

echo "== Scenario 2: already-checked-out fatal reproduces on a second worktree add for the same branch =="
WT2="$SCRATCH/wt-roundn-second"
git -C "$REPO" worktree add "$WT2" -B feat/test origin/feat/test >/tmp/round_n_spec_err.$$ 2>&1
r2=$?
already_checked_out="$(grep -c 'already checked out at' /tmp/round_n_spec_err.$$ 2>/dev/null || true)"
rm -f "/tmp/round_n_spec_err.$$" 2>/dev/null || true
echo "scenario2 exit=$r2 already_checked_out_matches=$already_checked_out"

echo "== Scenario 3: porcelain reuse guard identifies the existing worktree path for feat/test =="
guard_hit="$(git -C "$REPO" worktree list --porcelain | grep -c '^branch refs/heads/feat/test$')"
echo "scenario3 guard_hit=$guard_hit"

echo "Results: prose-wiring=$r0 scenario1_exit=$r1 head_matches_origin=$([ "$head_sha" = "$origin_tip" ] && echo yes || echo no) scenario2_exit=$r2 already_checked_out_matches=$already_checked_out guard_hit=$guard_hit"

if [ "$r0" = "0" ] \
  && [ "$r1" = "0" ] \
  && [ -n "$head_sha" ] \
  && [ "$head_sha" = "$origin_tip" ] \
  && [ "$r2" != "0" ] \
  && [ "${already_checked_out:-0}" -ge 1 ] \
  && [ "${guard_hit:-0}" -ge 1 ]; then
  echo "PASS: prose-wiring clean, -B form lands on origin tip despite a lagging local ref, already-checked-out fatal reproduces, and the porcelain reuse guard identifies it"
  exit 0
fi

echo "FAIL: one or more assertions did not hold - see results line above"
exit 1
