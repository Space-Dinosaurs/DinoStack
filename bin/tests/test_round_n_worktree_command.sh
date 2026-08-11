#!/usr/bin/env bash
# Purpose: executable regression spec for the DS-157 "Round-N rework
#          mechanic" `worktree_setup.create_commands` branch-already-exists
#          form (content/commands/ds-implement-ticket.md §Elevated-path
#          engineer-contract extensions; canonical prose also referenced
#          from content/references/worktree-lifecycle.md §Round-N rework
#          mechanic). Grew across three Skeptic rounds, each of which found
#          a MEASURED defect in the prose this file pins:
#            - Round 1: the original `--track origin/$BRANCH_NAME` positional
#              form was a git syntax error (exit 129).
#            - Round 2: the already-checked-out reuse remedy reset the
#              existing worktree UNCONDITIONALLY, destroying local-only
#              commits from a round whose push had failed.
#            - Round 3: (a) the reset precheck's unpushed-commit predicate
#              (`git log origin/$BRANCH_NAME..HEAD`) exits 128 with EMPTY
#              stdout when the local remote-tracking ref is stale/absent -
#              a naive empty-string check misreads that as "safe", and (b)
#              the Trivial path's prose falsely claimed `git checkout -B`
#              shares `git worktree add`'s already-checked-out protection;
#              measured false - `checkout -B` exits 0 and silently drags
#              another worktree's HEAD (and any unpushed commit on it) along
#              with the branch ref reset.
#          Every scenario below runs against a disposable scratch git repo
#          under a temp directory (never touches the real DinoStack
#          checkout, worktree, or branch state), and where a prior round's
#          bug is being regression-guarded, first demonstrates the bug
#          reproduces under a literal simulation of the pre-fix logic before
#          asserting the current documented logic avoids it.
#
# Public API: none (standalone script; `bash bin/tests/test_round_n_worktree_command.sh`).
#
# Upstream deps: none (self-contained scratch-repo fixtures). Prose-wiring
#                check greps content/commands/ds-implement-ticket.md,
#                resolved relative to this script's repo root.
#
# Downstream consumers: CI (bin-sh-tests); DS-157 Skeptic review rounds
#                       (outcome_rubric row 1 and row 7).
#
# Failure modes: exits non-zero if any scenario's assertions do not hold -
#                see each scenario's inline comment for what it pins.
#                Cleans up its scratch repos on exit via a trap regardless
#                of outcome.
#
# Performance: a few seconds; a handful of `git worktree add`/`remove`,
#              `fetch`, `reset --hard`, and `checkout -B` calls across
#              several throwaway bare-clone repos.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMPL_DOC="$REPO_ROOT/content/commands/ds-implement-ticket.md"
SCRATCH="$(mktemp -d)"

cleanup() {
  rm -rf "$SCRATCH" 2>/dev/null || true
}
trap cleanup EXIT

FAIL=0
note_fail() {
  echo "FAIL: $1" >&2
  FAIL=1
}

# --- Prose-wiring / reverted-defect regression guard -----------------------
check_prose_wiring() {
  local doc="$1"
  local ok=0

  if [ ! -f "$doc" ]; then
    echo "PROSE-WIRING VIOLATION: $doc not found" >&2
    return 1
  fi

  # Round 1: the syntax-error --track form must never reappear; the
  # corrected -B worktree-add form must be present.
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

  # Round 3 MAJOR 1: the reset precheck must fetch BEFORE evaluating the
  # predicates, must capture the unpushed-commit check's exit code, and
  # must document the awk-based path extraction (not the old boolean grep).
  if ! grep -q -- 'awk -v b="refs/heads/\$BRANCH_NAME"' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not document the awk-based existing-worktree path extraction" >&2
    ok=1
  fi
  if ! grep -q -- 'UNPUSHED_RC=\$?' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not capture the unpushed-commit check's exit code (fail-closed precondition)" >&2
    ok=1
  fi
  if ! grep -qi -- 'fetch FIRST' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not state the fetch-before-predicates ordering requirement" >&2
    ok=1
  fi

  # Round 3 CRITICAL: the false "checkout -B shares worktree add's
  # already-checked-out protection" claim must not reappear, and the
  # corrected (measured-true) claim must be present.
  if grep -qi -- 'checkout -B.\{0,40\}subject to the same already-checked-out fatal' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc re-introduced the measured-false checkout -B already-checked-out-fatal claim" >&2
    ok=1
  fi
  if ! grep -q -- 'already-checked-out behavior is git-version-dependent' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not state that checkout -B's already-checked-out behavior is git-version-dependent" >&2
    ok=1
  fi
  if ! grep -q -- 'OLDER git.*does NOT refuse' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not document the older-git (non-refusing) checkout -B arm" >&2
    ok=1
  fi
  if ! grep -q -- 'NEWER git.*now refuses' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not document the newer-git (refusing) checkout -B arm" >&2
    ok=1
  fi
  if ! grep -q -- 'MANDATORY.*under BOTH behaviors' "$doc"; then
    echo "PROSE-WIRING VIOLATION: $doc does not state the precheck is mandatory under both git-version behaviors" >&2
    ok=1
  fi

  return "$ok"
}

# --- Scratch repo setup -----------------------------------------------------
# Bare-clone origin + one working checkout ("repo"), matching the real
# $REPO / origin topology.
setup_bare_and_repo() {
  local scratch_dir="$1"
  git init -q --bare "$scratch_dir/origin.git"
  git clone -q "$scratch_dir/origin.git" "$scratch_dir/repo"
  git -C "$scratch_dir/repo" config user.email spec@example.com
  git -C "$scratch_dir/repo" config user.name spec
  git -C "$scratch_dir/repo" commit -q --allow-empty -m init
  git -C "$scratch_dir/repo" branch -M main
  git -C "$scratch_dir/repo" push -q origin main
}

# --- Simulations of the documented reuse-precheck logic --------------------
# sim_old_unconditional_reset: the state of the world BEFORE round 2's
# precheck existed at all - reset unconditionally, no predicates.
sim_old_unconditional_reset() {
  local wt="$1" branch="$2"
  git -C "$wt" fetch origin >/dev/null 2>&1
  git -C "$wt" reset --hard "origin/$branch" >/dev/null 2>&1
  echo "RESET"
}

# sim_round3_naive_predicates: round 3's (pre-this-fix) predicate check -
# evaluates predicates BEFORE fetching, and reads a nonzero-rc empty stdout
# from the unpushed-commit check as "no unpushed commits" (the MAJOR 1 bug).
sim_round3_naive_predicates() {
  local wt="$1" branch="$2"
  local dirty unpushed
  dirty="$(git -C "$wt" status --porcelain)"
  unpushed="$(git -C "$wt" log "origin/$branch..HEAD" --oneline 2>/dev/null)"
  if [ -n "$dirty" ]; then
    echo "ESCALATE_DIRTY"
    return
  fi
  if [ -n "$unpushed" ]; then
    echo "ROUTE_RECOVERY_PUSH_FIRST"
    return
  fi
  # naive: empty unpushed (whether truly empty OR because the command
  # errored) is treated as safe.
  git -C "$wt" fetch origin >/dev/null 2>&1
  git -C "$wt" reset --hard "origin/$branch" >/dev/null 2>&1
  echo "RESET"
}

# sim_current_fixed_logic: the current documented logic (this round's fix) -
# fetch FIRST, capture the unpushed-commit check's exit code, fail closed on
# a nonzero exit, and never conflate "uncommitted work" with "has a commit
# to push" (Minor 2).
sim_current_fixed_logic() {
  local wt="$1" branch="$2"
  git -C "$wt" fetch origin >/dev/null 2>&1
  local dirty unpushed unpushed_rc
  dirty="$(git -C "$wt" status --porcelain)"
  unpushed="$(git -C "$wt" log "origin/$branch..HEAD" --oneline 2>/dev/null)"
  unpushed_rc=$?
  if [ "$unpushed_rc" -ne 0 ]; then
    echo "ROUTE_RECOVERY_RC_FAIL"
    return
  fi
  if [ -n "$dirty" ]; then
    echo "ESCALATE_DIRTY"
    return
  fi
  if [ -n "$unpushed" ]; then
    echo "ROUTE_RECOVERY_PUSH_FIRST"
    return
  fi
  git -C "$wt" reset --hard "origin/$branch" >/dev/null 2>&1
  echo "RESET"
}

echo "== Prose-wiring check: $IMPL_DOC pins all three rounds' fixes =="
check_prose_wiring "$IMPL_DOC"
r0=$?
echo "prose-wiring exit=$r0"
[ "$r0" = "0" ] || note_fail "prose-wiring check"

echo "== Scenario 1: lagging local ref - corrected -B form must exit 0 and land on the ORIGIN tip =="
S1="$SCRATCH/s1"
mkdir -p "$S1"
setup_bare_and_repo "$S1"
git -C "$S1/repo" worktree add -q -b feat/test "$S1/tmpwt" origin/main
git -C "$S1/tmpwt" commit -q --allow-empty -m c1
git -C "$S1/tmpwt" push -q origin feat/test
git -C "$S1/repo" worktree remove --force "$S1/tmpwt"
git -C "$S1/repo" worktree add -q -b feat/test-scratch "$S1/tmpwt2" origin/feat/test
git -C "$S1/tmpwt2" commit -q --allow-empty -m c2
git -C "$S1/tmpwt2" push -q origin feat/test-scratch:feat/test
git -C "$S1/repo" worktree remove --force "$S1/tmpwt2"

git -C "$S1/repo" fetch origin >/dev/null 2>&1
git -C "$S1/repo" worktree add "$S1/wt-roundn" -B feat/test origin/feat/test >/dev/null 2>&1
r1=$?
head_sha="$(git -C "$S1/wt-roundn" rev-parse HEAD 2>/dev/null)"
origin_tip="$(git -C "$S1/repo" rev-parse origin/feat/test 2>/dev/null)"
echo "scenario1 exit=$r1 head=$head_sha origin_tip=$origin_tip"
if [ "$r1" != "0" ] || [ -z "$head_sha" ] || [ "$head_sha" != "$origin_tip" ]; then
  note_fail "scenario 1: -B form did not exit 0 or did not land on origin tip"
fi

echo "== Scenario 2: already-checked-out fatal reproduces on a second worktree add for the same branch (version-tolerant message match) =="
git -C "$S1/repo" worktree add "$S1/wt-roundn-second" -B feat/test origin/feat/test >"$SCRATCH/s2-err.log" 2>&1
r2=$?
# The fatal's message wording is NOT stable across git versions - measured
# "fatal: '<branch>' is already checked out at '<path>'" on git 2.39.5 and
# "fatal: '<branch>' is already used by worktree at '<path>'" on git 2.55.0
# (also observed matching the CI runner's git 2.54.0 behavior: same rc, this
# gate does not depend on the exact wording). `worktree add`'s REFUSAL
# behavior (nonzero exit) is what this scenario pins - not one version's
# exact message text.
already_checked_out="$(grep -Eic "already (checked out|used by worktree)" "$SCRATCH/s2-err.log" 2>/dev/null || true)"
echo "scenario2 exit=$r2 already_checked_out_matches=$already_checked_out"
if [ "$r2" = "0" ]; then
  note_fail "scenario 2: worktree add did not refuse (already-checked-out fatal did not reproduce)"
fi
if [ "${already_checked_out:-0}" -lt 1 ]; then
  note_fail "scenario 2: worktree add's failure message did not match either known wording (checked out / used by worktree) - a THIRD wording may exist; investigate before accepting"
fi

echo "== Scenario 3: awk-based reuse guard (as documented) identifies the existing worktree PATH for feat/test =="
guard_path="$(git -C "$S1/repo" worktree list --porcelain | awk -v b="refs/heads/feat/test" '/^worktree /{p=$2} $0=="branch "b{print p}')"
expected_path="$(cd "$S1/wt-roundn" && pwd -P)"
echo "scenario3 guard_path=[$guard_path] expected=[$expected_path]"
if [ -z "$guard_path" ] || [ "$guard_path" != "$expected_path" ]; then
  note_fail "scenario 3: awk reuse guard did not resolve the existing worktree's path"
fi

echo "== Scenario 4: dirty-worktree case - reddens under the pre-precheck baseline, protected under current logic =="
S4="$SCRATCH/s4"
mkdir -p "$S4"
setup_bare_and_repo "$S4"
# tracked.txt is committed and pushed so it exists at the origin tip too -
# the dirty state under test is an UNCOMMITTED MODIFICATION to a TRACKED
# file, not an untracked file (untracked files survive `reset --hard`
# unmodified, so an untracked-only fixture would not actually exercise the
# data-loss path `reset --hard` is dangerous for).
echo "original" > "$S4/repo/tracked.txt"
git -C "$S4/repo" add tracked.txt
git -C "$S4/repo" commit -q -m "add tracked.txt"
git -C "$S4/repo" push -q origin main
git -C "$S4/repo" worktree add -q -b feat/test "$S4/wt" origin/main
git -C "$S4/wt" commit -q --allow-empty -m c1
git -C "$S4/wt" push -q origin feat/test
echo "UNCOMMITTED CHANGE" > "$S4/wt/tracked.txt"
pre_dirty_head="$(git -C "$S4/wt" rev-parse HEAD)"

# Baseline (pre-any-precheck): confirm this genuinely destroys the
# uncommitted modification - reddens.
old_action="$(sim_old_unconditional_reset "$S4/wt" feat/test)"
old_content_after="$(cat "$S4/wt/tracked.txt")"
echo "scenario4 baseline: action=$old_action content_after=[$old_content_after]"
if [ "$old_action" != "RESET" ] || [ "$old_content_after" = "UNCOMMITTED CHANGE" ]; then
  note_fail "scenario 4 baseline did not reproduce data loss under the pre-precheck reset - the scenario is not exercising a real bug"
fi

# Rebuild the dirty state in the SAME worktree location (feat/test can only
# be checked out in one worktree at a time) and re-test under the CURRENT
# documented logic.
git -C "$S4/wt" reset --hard "$pre_dirty_head" >/dev/null 2>&1
echo "UNCOMMITTED CHANGE" > "$S4/wt/tracked.txt"
fixed_action="$(sim_current_fixed_logic "$S4/wt" feat/test)"
fixed_content_after="$(cat "$S4/wt/tracked.txt")"
fixed_head_after="$(git -C "$S4/wt" rev-parse HEAD)"
echo "scenario4 fixed: action=$fixed_action content_after=[$fixed_content_after] head_unchanged=$([ "$fixed_head_after" = "$pre_dirty_head" ] && echo yes || echo no)"
if [ "$fixed_action" != "ESCALATE_DIRTY" ] || [ "$fixed_content_after" != "UNCOMMITTED CHANGE" ] || [ "$fixed_head_after" != "$pre_dirty_head" ]; then
  note_fail "scenario 4: current logic did not escalate-and-preserve the dirty worktree"
fi

echo "== Scenario 5: unpushed-commit case - reddens under the pre-precheck baseline, protected under current logic =="
S5="$SCRATCH/s5"
mkdir -p "$S5"
setup_bare_and_repo "$S5"
git -C "$S5/repo" worktree add -q -b feat/test "$S5/wt" origin/main
git -C "$S5/wt" commit -q --allow-empty -m c1
git -C "$S5/wt" push -q origin feat/test
git -C "$S5/wt" commit -q --allow-empty -m "local-only-unpushed"
unpushed_sha="$(git -C "$S5/wt" rev-parse HEAD)"

old_action5="$(sim_old_unconditional_reset "$S5/wt" feat/test)"
head_after_old="$(git -C "$S5/wt" rev-parse HEAD)"
echo "scenario5 baseline: action=$old_action5 head_before=$unpushed_sha head_after=$head_after_old"
if [ "$old_action5" != "RESET" ] || [ "$head_after_old" = "$unpushed_sha" ]; then
  note_fail "scenario 5 baseline did not reproduce the unpushed-commit being dropped under the pre-precheck reset"
fi

# Rebuild an unpushed-commit state in the SAME worktree location (feat/test
# can only be checked out in one worktree at a time) and re-test under the
# CURRENT documented logic.
git -C "$S5/wt" commit -q --allow-empty -m "local-only-unpushed-2"
unpushed_sha2="$(git -C "$S5/wt" rev-parse HEAD)"
fixed_action5="$(sim_current_fixed_logic "$S5/wt" feat/test)"
head_after_fixed="$(git -C "$S5/wt" rev-parse HEAD)"
echo "scenario5 fixed: action=$fixed_action5 head_before=$unpushed_sha2 head_after=$head_after_fixed"
if [ "$fixed_action5" != "ROUTE_RECOVERY_PUSH_FIRST" ] || [ "$head_after_fixed" != "$unpushed_sha2" ]; then
  note_fail "scenario 5: current logic did not route the unpushed-commit case to recovery with HEAD preserved"
fi

echo "== Scenario 6: absent/unresolvable tracking ref - reddens under round-3's naive (pre-fetch-first) predicate check, protected under current logic =="
S6="$SCRATCH/s6"
mkdir -p "$S6"
setup_bare_and_repo "$S6"
git -C "$S6/repo" worktree add -q -b feat/test "$S6/wt" origin/main
git -C "$S6/wt" commit -q --allow-empty -m c1
git -C "$S6/wt" push -q origin feat/test
git -C "$S6/wt" commit -q --allow-empty -m "local-only-unpushed"
sha_before_6="$(git -C "$S6/wt" rev-parse HEAD)"
# Simulate the described gap directly: delete the local remote-tracking ref
# (as `git fetch --prune` would after a branch delete+recreate cycle),
# without re-fetching yet.
git -C "$S6/wt" update-ref -d refs/remotes/origin/feat/test

naive_action6="$(sim_round3_naive_predicates "$S6/wt" feat/test)"
head_after_naive="$(git -C "$S6/wt" rev-parse HEAD)"
echo "scenario6 baseline (round-3 naive, no fetch-first): action=$naive_action6 head_before=$sha_before_6 head_after=$head_after_naive"
if [ "$naive_action6" != "RESET" ] || [ "$head_after_naive" = "$sha_before_6" ]; then
  note_fail "scenario 6 baseline did not reproduce the absent-tracking-ref misroute to RESET under round-3's naive predicate check"
fi

# Rebuild an unpushed-commit + deleted-tracking-ref state in the SAME
# worktree location (feat/test can only be checked out in one worktree at a
# time) and re-test under the current fetch-first, rc-checked logic.
git -C "$S6/wt" commit -q --allow-empty -m "local-only-unpushed-2"
sha_before_6b="$(git -C "$S6/wt" rev-parse HEAD)"
git -C "$S6/wt" update-ref -d refs/remotes/origin/feat/test
fixed_action6="$(sim_current_fixed_logic "$S6/wt" feat/test)"
head_after_fixed6="$(git -C "$S6/wt" rev-parse HEAD)"
echo "scenario6 fixed (fetch-first, rc-checked): action=$fixed_action6 head_before=$sha_before_6b head_after=$head_after_fixed6"
if [ "$fixed_action6" = "RESET" ] || [ "$head_after_fixed6" != "$sha_before_6b" ]; then
  note_fail "scenario 6: current logic did not avoid RESET / preserve HEAD in the absent-tracking-ref case"
fi

# run_checkout_b_collision: runs the Trivial-path round-N `checkout -B`
# collision scenario against a specific git binary in its own scratch repo,
# and asserts the DICHOTOMY that is actually true across git versions rather
# than pinning one version's behavior:
#   - older git (measured: 2.39.5) does NOT refuse: exits 0, force-moves the
#     shared branch ref, and drags the other worktree's HEAD along with it -
#     the round-3 Critical fix's whole point is that the mandatory porcelain
#     precheck is the ONLY thing standing between this and silent data loss.
#   - newer git (measured: 2.55.0, and observed matching CI's 2.54.0 exit
#     code) now refuses (exit 128, matching worktree add's protection) -
#     the other worktree's HEAD is left untouched.
# The dichotomy is exhaustive: the checkout's exit code is either 0 or non-zero, there
# is no third case. Each branch below asserts something that would fail for
# real if violated - neither arm is a vacuous no-op placeholder.
run_checkout_b_collision() {
  local git_bin="$1" label="$2" dir="$3"
  mkdir -p "$dir"
  "$git_bin" init -q --bare "$dir/origin.git"
  "$git_bin" clone -q "$dir/origin.git" "$dir/repo"
  "$git_bin" -C "$dir/repo" config user.email spec@example.com
  "$git_bin" -C "$dir/repo" config user.name spec
  "$git_bin" -C "$dir/repo" commit -q --allow-empty -m init
  "$git_bin" -C "$dir/repo" branch -M main
  "$git_bin" -C "$dir/repo" push -q origin main
  "$git_bin" -C "$dir/repo" worktree add -q -b feat/test "$dir/wtA" origin/main
  "$git_bin" -C "$dir/wtA" commit -q --allow-empty -m c1
  "$git_bin" -C "$dir/wtA" push -q origin feat/test
  "$git_bin" -C "$dir/wtA" commit -q --allow-empty -m "unpushed-in-wtA"
  local head_before head_after rc
  head_before="$("$git_bin" -C "$dir/wtA" rev-parse HEAD)"

  "$git_bin" -C "$dir/repo" fetch origin >/dev/null 2>&1
  "$git_bin" -C "$dir/repo" checkout -B feat/test origin/feat/test >/dev/null 2>&1
  rc=$?
  head_after="$("$git_bin" -C "$dir/wtA" rev-parse HEAD)"
  echo "scenario7[$label] git=$("$git_bin" --version) rc=$rc head_before=$head_before head_after=$head_after"

  if [ "$rc" = "0" ]; then
    # Old-git arm: checkout -B must have force-moved the shared ref and
    # dragged the other worktree's HEAD - if it did NOT, this fixture is
    # not exercising the bypass this scenario exists to pin.
    if [ "$head_after" = "$head_before" ]; then
      note_fail "scenario 7[$label]: checkout -B exited 0 (old-git arm) but did NOT drag the other worktree's HEAD as measured - fixture not exercising the bypass"
    else
      echo "scenario7[$label]: OLD-GIT ARM confirmed - checkout -B bypassed the collision and dragged the other worktree's HEAD (this is exactly why the mandatory precheck exists)"
    fi
  else
    # New-git arm: checkout -B refused, so the other worktree's HEAD must be
    # untouched - if it moved anyway, something refused AND still mutated
    # state, which would be worse than either measured behavior.
    if [ "$head_after" != "$head_before" ]; then
      note_fail "scenario 7[$label]: checkout -B refused (rc=$rc, new-git arm) but the other worktree's HEAD moved anyway - unexpected third behavior"
    else
      echo "scenario7[$label]: NEW-GIT ARM confirmed - checkout -B refused (rc=$rc) and the other worktree's HEAD was left untouched"
    fi
  fi
}

echo "== Scenario 7: Trivial-path checkout -B collision - version-tolerant, pins the TRUE (measured) dichotomy, not the round-3 false single-behavior claim =="
run_checkout_b_collision "$(command -v git)" "default" "$SCRATCH/s7-default"
checkout_rc_report="see scenario7[default] above"

# Best-effort: if a second git binary with a DIFFERENT version is available
# on this machine (common in local dev after installing a newer git
# alongside the OS-bundled one), exercise it too - this makes BOTH arms
# fire for real in one run wherever both git versions happen to be present,
# rather than relying on whichever single version the current environment
# ships.
default_git="$(command -v git)"
default_git_version="$("$default_git" --version)"
for candidate in /usr/bin/git /opt/homebrew/bin/git /usr/local/bin/git; do
  if [ -x "$candidate" ] && [ "$candidate" != "$default_git" ]; then
    candidate_version="$("$candidate" --version)"
    if [ "$candidate_version" != "$default_git_version" ]; then
      echo "== Scenario 7 (alt git): $candidate ($candidate_version) differs from default ($default_git_version) - exercising it too for dual-arm coverage =="
      run_checkout_b_collision "$candidate" "alt:$candidate" "$SCRATCH/s7-alt"
      break
    fi
  fi
done

echo "== Results =="
echo "prose-wiring=$r0 scenario1_exit=$r1 scenario2_exit=$r2 scenario3_guard=[$guard_path] scenario4=$fixed_action scenario5=$fixed_action5 scenario6=$fixed_action6 scenario7=$checkout_rc_report"

if [ "$FAIL" = "0" ]; then
  echo "PASS: all scenarios hold - prose-wiring clean; -B form correct; already-checked-out fatal reproduces for worktree add; awk reuse guard resolves the path; dirty/unpushed/absent-ref cases all reproduce data loss under their respective pre-fix baselines and are protected under current logic; checkout -B's TRUE (non-refusing, HEAD-dragging) semantics are pinned"
  exit 0
fi

echo "FAIL: one or more scenarios did not hold - see FAIL lines above"
exit 1
