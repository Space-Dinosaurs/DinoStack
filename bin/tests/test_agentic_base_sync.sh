#!/usr/bin/env bash
# Purpose: Regression/behavior test for bin/agentic-base-sync and its backing
#          library scripts/lib/base-branch-sync.sh (ae_base_branch_sync).
#          Constructs scratch bare-origin + local-clone repo pairs per case
#          and asserts exit code, breadcrumb status, and - critically - that
#          the local ref position and working-tree state are byte-identical
#          to pre-call state on every non-zero-exit path.
#
# Public API: ./bin/tests/test_agentic_base_sync.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, mktemp, awk, python3, bin/ds-reap-worktrees (case
#                18 exercises bin/agentic-base-sync's worktree-reaper
#                advisory note, which shells out to `python3
#                bin/ds-reap-worktrees --count-only` - both are load-bearing
#                for that case, not merely for the tool under test).
#
# Downstream consumers: bin-tests CI job (glob-picked-up test_*.sh).
#
# Failure modes: any assertion failure prints the failing assertion and exits
#                1 at end of run (all cases still execute so a run reports
#                every failure, not just the first). All fixtures live under
#                a temporary directory; the real repo is never touched.
#
# Performance: ~12.7 s wall time (pure git + shell, no network) - measured via
#              `time bash bin/tests/test_agentic_base_sync.sh`; this figure
#              was already stale (previously cited as "< 10 s") before this
#              ticket, and case 18's `python3` subprocess is a small
#              additional contributor, not the whole gap.
#
# Regression coverage: see plan-base-branch-sync.md cases 1-14 (11 and 14
#                       revised per round-3 Skeptic correction - see inline
#                       comments on those cases below for why).
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TOOL="$REPO_DIR/bin/agentic-base-sync"

if [[ ! -x "$TOOL" ]]; then
  echo "FAIL: $TOOL not found or not executable" >&2
  exit 1
fi

PASS=0
FAIL=0

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

_pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

_assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    _pass "$desc"
  else
    _fail "$desc (expected [$expected], got [$actual])"
  fi
}

_assert_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    _pass "$desc"
  else
    _fail "$desc (did not find [$needle] in output)"
  fi
}

_assert_not_contains() {
  local desc="$1" haystack="$2" needle="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    _pass "$desc"
  else
    _fail "$desc (unexpectedly found [$needle] in output)"
  fi
}

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  [[ -n "${TMP_ROOT:-}" && -d "$TMP_ROOT" ]] && rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

_gitcfg() {
  git -C "$1" config user.email test@test.com
  git -C "$1" config user.name test
}

# _make_origin_and_clone <case-dir>
#   Creates a bare origin at <case-dir>/origin.git with one commit on branch
#   "base", HEAD set to "base", and clones it to <case-dir>/repo (checked out
#   on "base"). Also leaves a pushable seed clone at <case-dir>/seed for
#   advancing origin further.
_make_origin_and_clone() {
  local case_dir="$1"
  mkdir -p "$case_dir"
  git init -q --bare "$case_dir/origin.git"
  git -C "$case_dir/origin.git" symbolic-ref HEAD refs/heads/base

  git init -q "$case_dir/seed"
  _gitcfg "$case_dir/seed"
  git -C "$case_dir/seed" checkout -q -b base
  echo "init" > "$case_dir/seed/file.txt"
  echo "init" > "$case_dir/seed/other.txt"
  git -C "$case_dir/seed" add file.txt other.txt
  git -C "$case_dir/seed" commit -q -m "initial commit"
  git -C "$case_dir/seed" remote add origin "$case_dir/origin.git"
  git -C "$case_dir/seed" push -q -u origin base

  git clone -q "$case_dir/origin.git" "$case_dir/repo"
  _gitcfg "$case_dir/repo"
}

# _seed_advance <case-dir> <msg>
#   Adds a commit on origin's "base" branch via the seed clone, pushes it.
_seed_advance() {
  local case_dir="$1" msg="$2"
  echo "$msg" >> "$case_dir/seed/file.txt"
  git -C "$case_dir/seed" add file.txt
  git -C "$case_dir/seed" commit -q -m "$msg"
  git -C "$case_dir/seed" push -q origin base
}

# _snapshot <repo>
#   Prints "<base-sha-or-none> <working-tree-hash>" for pre/post-call
#   byte-identity comparison on non-zero-exit paths. Deliberately EXCLUDES
#   `git status --branch` ahead/behind info: a `pull --ff-only`/`fetch`
#   attempt updates the local origin/<base> remote-tracking ref as a side
#   effect even when the merge/ref-write itself is refused, which would
#   change the branch-tracking header without the tool having touched the
#   local <base> ref or the working tree - a false positive for this check.
_snapshot() {
  local repo="$1"
  local sha wt_hash
  sha="$(git -C "$repo" rev-parse --verify -q refs/heads/base 2>/dev/null || echo none)"
  wt_hash="$( { git -C "$repo" status --porcelain=v1 --untracked-files=all 2>/dev/null; \
                git -C "$repo" diff 2>/dev/null; \
                git -C "$repo" diff --cached 2>/dev/null; } | shasum | awk '{print $1}')"
  echo "$sha $wt_hash"
}

echo "=== Case 1: HEAD on base, clean, origin ahead -> ff-pulled ==="
{
  C="$TMP_ROOT/case1"
  _make_origin_and_clone "$C"
  _seed_advance "$C" "advance1"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  ORIGIN_SHA="$(git -C "$C/repo" rev-parse origin/base)"
  LOCAL_SHA="$(git -C "$C/repo" rev-parse base)"
  _assert_eq "case1: exit 0" "0" "$RC"
  _assert_contains "case1: breadcrumb ff-pulled" "$OUT" "status=ff-pulled"
  _assert_eq "case1: local ref == origin ref" "$ORIGIN_SHA" "$LOCAL_SHA"
}

echo "=== Case 2: HEAD on base, dirty tracked file NOT touched by incoming commit -> ff-pulled ==="
{
  C="$TMP_ROOT/case2"
  _make_origin_and_clone "$C"
  # Dirty-modify an already-tracked file (other.txt) that the incoming remote
  # commit does NOT touch (_seed_advance only ever appends to file.txt).
  echo "dirty edit" >> "$C/repo/other.txt"
  _seed_advance "$C" "advance2"
  DIRTY_BEFORE="$(cat "$C/repo/other.txt")"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  DIRTY_AFTER="$(cat "$C/repo/other.txt")"
  _assert_eq "case2: exit 0" "0" "$RC"
  _assert_contains "case2: breadcrumb ff-pulled" "$OUT" "status=ff-pulled"
  _assert_eq "case2: dirty tracked edit preserved" "$DIRTY_BEFORE" "$DIRTY_AFTER"
}

echo "=== Case 3: HEAD on base, only an untracked file present -> ff-pulled ==="
{
  C="$TMP_ROOT/case3"
  _make_origin_and_clone "$C"
  echo "untracked content" > "$C/repo/untracked.txt"
  _seed_advance "$C" "advance3"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  _assert_eq "case3: exit 0" "0" "$RC"
  _assert_contains "case3: breadcrumb ff-pulled" "$OUT" "status=ff-pulled"
  if [[ -f "$C/repo/untracked.txt" ]] && [[ "$(cat "$C/repo/untracked.txt")" == "untracked content" ]]; then
    _pass "case3: untracked file preserved"
  else
    _fail "case3: untracked file missing or altered"
  fi
}

echo "=== Case 4: HEAD on base, incoming commit WOULD overwrite the dirty tracked path -> skipped-dirty ==="
{
  C="$TMP_ROOT/case4"
  _make_origin_and_clone "$C"
  # Dirty-modify file.txt (the file the seed advance below also touches).
  echo "conflicting local edit" >> "$C/repo/file.txt"
  _seed_advance "$C" "advance4-conflict"
  SNAP_BEFORE="$(_snapshot "$C/repo")"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  SNAP_AFTER="$(_snapshot "$C/repo")"
  _assert_eq "case4: exit 2" "2" "$RC"
  _assert_contains "case4: breadcrumb skipped-dirty" "$OUT" "status=skipped-dirty"
  _assert_eq "case4: local ref + working tree byte-identical pre/post" "$SNAP_BEFORE" "$SNAP_AFTER"
}

echo "=== Case 5: HEAD on base, local has a divergent commit -> diverged ==="
{
  C="$TMP_ROOT/case5"
  _make_origin_and_clone "$C"
  # Genuine two-way divergence: commit locally on "other.txt" FIRST (both
  # local and origin fork from the same initial commit), THEN advance origin
  # independently via the seed clone on "file.txt". A local-only commit with
  # origin left unchanged is NOT divergence - "pull --ff-only" treats that as
  # a trivial no-op success (that is what case 13 tests). True divergence
  # requires both sides to have moved past the common ancestor.
  echo "local-only" >> "$C/repo/other.txt"
  git -C "$C/repo" add other.txt
  git -C "$C/repo" commit -q -m "local divergent commit"
  _seed_advance "$C" "advance5-origin-side"
  SNAP_BEFORE="$(_snapshot "$C/repo")"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  SNAP_AFTER="$(_snapshot "$C/repo")"
  _assert_eq "case5: exit 1" "1" "$RC"
  _assert_contains "case5: breadcrumb diverged" "$OUT" "status=diverged"
  _assert_contains "case5: WARNING present" "$OUT" "WARNING"
  _assert_contains "case5: Recovery line present" "$OUT" "Recovery:"
  _assert_contains "case5: local-only commit oneline shown" "$OUT" "local divergent commit"
  _assert_eq "case5: local ref + working tree byte-identical pre/post" "$SNAP_BEFORE" "$SNAP_AFTER"
}

echo "=== Case 6: HEAD elsewhere (fan-out sim), origin ahead, base not checked out anywhere -> ff-updated-ref ==="
{
  C="$TMP_ROOT/case6"
  _make_origin_and_clone "$C"
  git -C "$C/repo" checkout -q -b feature
  _seed_advance "$C" "advance6"
  HEAD_BEFORE="$(git -C "$C/repo" rev-parse --abbrev-ref HEAD)"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  HEAD_AFTER="$(git -C "$C/repo" rev-parse --abbrev-ref HEAD)"
  ORIGIN_SHA="$(git -C "$C/repo" rev-parse origin/base)"
  LOCAL_BASE_SHA="$(git -C "$C/repo" rev-parse base)"
  _assert_eq "case6: exit 0" "0" "$RC"
  _assert_contains "case6: breadcrumb ff-updated-ref" "$OUT" "status=ff-updated-ref"
  _assert_eq "case6: base ref == origin ref" "$ORIGIN_SHA" "$LOCAL_BASE_SHA"
  _assert_eq "case6: working-tree HEAD unchanged" "$HEAD_BEFORE" "$HEAD_AFTER"
}

echo "=== Case 7 (revised, round-4 correction): HEAD elsewhere, GENUINE two-sided divergence -> diverged ==="
# Original setup advanced only local "base" (via a throwaway worktree) and
# left origin unchanged: behind=0, ahead=1 - that is the AHEAD-ONLY benign
# state (see case 7b below), not divergence. `fetch origin base:base`
# refuses the non-fast-forward write either way, but the tool's OWN rule
# (stated in the comment above the HEAD-elsewhere branch in
# scripts/lib/base-branch-sync.sh) is that `diverged` requires BOTH
# behind>0 AND ahead>0. This case now advances BOTH sides independently
# from the same common ancestor so the divergence is real.
{
  C="$TMP_ROOT/case7"
  _make_origin_and_clone "$C"
  git -C "$C/repo" checkout -q -b feature
  # Advance local "base" (not checked out in $repo) via a throwaway worktree,
  # forking from the common-ancestor initial commit, then remove that
  # worktree so base is unchecked-out-anywhere again.
  git -C "$C/repo" worktree add -q "$C/wt-tmp" base
  echo "local-only-elsewhere" >> "$C/wt-tmp/other.txt"
  git -C "$C/wt-tmp" add other.txt
  git -C "$C/wt-tmp" commit -q -m "local divergent commit on base (elsewhere)"
  git -C "$C/repo" worktree remove "$C/wt-tmp"
  # Independently advance origin's base from the SAME common ancestor (via
  # the seed clone, which never saw the local commit above).
  _seed_advance "$C" "advance7-origin-side"
  SNAP_BEFORE="$(_snapshot "$C/repo")"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  SNAP_AFTER="$(_snapshot "$C/repo")"
  _assert_eq "case7: exit 1" "1" "$RC"
  _assert_contains "case7: breadcrumb diverged" "$OUT" "status=diverged"
  _assert_contains "case7: local-only commit oneline shown" "$OUT" "local divergent commit"
  _assert_eq "case7: local base ref byte-identical pre/post" "$SNAP_BEFORE" "$SNAP_AFTER"
}

echo "=== Case 7b (round-4 addition): HEAD elsewhere, AHEAD-ONLY (behind=0) -> NOT diverged, ff-updated-ref + NOTE ==="
# The benign counterpart to case 7: only local base advances, origin never
# moves. `fetch origin base:base` still refuses (the write would move base
# BACKWARD relative to local), but this is the exact same "unpushed local
# commits" precursor state the HEAD-on-base ahead-only path (case 13)
# reports as a benign success - misreporting it as `diverged` here would
# tell the operator to cherry-pick onto a fresh branch when the correct
# action is a plain `git push` (round-4 Skeptic finding).
{
  C="$TMP_ROOT/case7b"
  _make_origin_and_clone "$C"
  git -C "$C/repo" checkout -q -b feature
  git -C "$C/repo" worktree add -q "$C/wt-tmp" base
  echo "local-only-ahead" >> "$C/wt-tmp/other.txt"
  git -C "$C/wt-tmp" add other.txt
  git -C "$C/wt-tmp" commit -q -m "local ahead-only commit on base (elsewhere)"
  git -C "$C/repo" worktree remove "$C/wt-tmp"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  _assert_eq "case7b: exit 0" "0" "$RC"
  _assert_contains "case7b: breadcrumb ff-updated-ref" "$OUT" "status=ff-updated-ref"
  _assert_not_contains "case7b: NOT diverged" "$OUT" "status=diverged"
  _assert_contains "case7b: NOTE line present" "$OUT" "NOTE:"
  _assert_contains "case7b: NOTE names 1 unpushed commit" "$OUT" "1 commit(s) ahead"
}

echo "=== Case 8: base ref checked out in ANOTHER worktree, no actual divergence -> ref-locked-elsewhere ==="
{
  C="$TMP_ROOT/case8"
  _make_origin_and_clone "$C"
  git -C "$C/repo" checkout -q -b feature
  git -C "$C/repo" worktree add -q "$C/wt-locked" base
  _seed_advance "$C" "advance8"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  _assert_eq "case8: exit 4" "4" "$RC"
  _assert_contains "case8: breadcrumb ref-locked-elsewhere" "$OUT" "status=ref-locked-elsewhere"
  git -C "$C/repo" worktree remove "$C/wt-locked" 2>/dev/null || true
}

echo "=== Case 9: origin unreachable -> fetch-failed ==="
{
  C="$TMP_ROOT/case9"
  _make_origin_and_clone "$C"
  git -C "$C/repo" remote set-url origin "$TMP_ROOT/case9/does-not-exist.git"
  SNAP_BEFORE="$(_snapshot "$C/repo")"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  SNAP_AFTER="$(_snapshot "$C/repo")"
  _assert_eq "case9: exit 4" "4" "$RC"
  _assert_contains "case9: breadcrumb fetch-failed" "$OUT" "status=fetch-failed"
  _assert_not_contains "case9: not misclassified as diverged" "$OUT" "status=diverged"
  _assert_eq "case9: local ref byte-identical pre/post" "$SNAP_BEFORE" "$SNAP_AFTER"
  # Finding N7: the printed diagnostic is the verify-fetch's own stderr. On
  # this fixture both the pull attempt and the plain verify-fetch hit the
  # same unreachable remote and therefore emit textually-identical git error
  # text, so this assertion cannot byte-distinguish "verify_err" from "err"
  # by output alone - that is confirmed instead by reading
  # scripts/lib/base-branch-sync.sh (the fetch-failed branch prints
  # $verify_err, never $err). Here we assert only that SOME git-authored
  # unreachable-remote diagnostic made it to stdout.
  _assert_contains "case9: git error text present in diagnostic" "$OUT" "does-not-exist"
}

echo "=== Case 10: detached HEAD, origin ahead -> ff-updated-ref (same path as case 6) ==="
{
  C="$TMP_ROOT/case10"
  _make_origin_and_clone "$C"
  SHA="$(git -C "$C/repo" rev-parse base)"
  git -C "$C/repo" checkout -q --detach "$SHA"
  _seed_advance "$C" "advance10"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  ORIGIN_SHA="$(git -C "$C/repo" rev-parse origin/base)"
  LOCAL_BASE_SHA="$(git -C "$C/repo" rev-parse base)"
  _assert_eq "case10: exit 0" "0" "$RC"
  _assert_contains "case10: breadcrumb ff-updated-ref" "$OUT" "status=ff-updated-ref"
  _assert_eq "case10: base ref == origin ref" "$ORIGIN_SHA" "$LOCAL_BASE_SHA"
}

echo "=== Case 11 (revised, round-3 correction): HEAD on base, .git/index.lock present -> refused-unknown ==="
# Original plan draft specified an untracked-file overwrite refusal here, but
# that is unreachable: an untracked-file overwrite refusal matches the
# "would be overwritten by merge" grep and returns skipped-dirty/exit 2
# BEFORE this branch's refused-unknown tail is ever reached (verified by
# execution in round 3). index.lock reliably reaches refused-unknown instead:
# "Unable to create '.../index.lock'" does not match the dirty-overwrite grep
# and is not a confirmed divergence.
{
  C="$TMP_ROOT/case11"
  _make_origin_and_clone "$C"
  _seed_advance "$C" "advance11"
  touch "$C/repo/.git/index.lock"
  SNAP_BEFORE="$(_snapshot "$C/repo")"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  SNAP_AFTER="$(_snapshot "$C/repo")"
  _assert_eq "case11: exit 4" "4" "$RC"
  _assert_contains "case11: breadcrumb refused-unknown" "$OUT" "status=refused-unknown"
  _assert_not_contains "case11: NOT ref-locked-elsewhere" "$OUT" "status=ref-locked-elsewhere"
  _assert_contains "case11: git error text printed verbatim" "$OUT" "index.lock"
  _assert_eq "case11: local ref + working tree byte-identical pre/post" "$SNAP_BEFORE" "$SNAP_AFTER"
  rm -f "$C/repo/.git/index.lock"
  OUT2="$("$TOOL" "$C/repo" base)"; RC2=$?
  _assert_eq "case11 (lock removed): exit 0" "0" "$RC2"
  _assert_contains "case11 (lock removed): breadcrumb ff-pulled" "$OUT2" "status=ff-pulled"
}

echo "=== Case 12: empty <base-branch> and empty <repo> arguments -> exit 3, no sync performed ==="
{
  C="$TMP_ROOT/case12"
  _make_origin_and_clone "$C"
  SNAP_BEFORE="$(_snapshot "$C/repo")"
  ERR="$("$TOOL" "$C/repo" "" 2>&1 1>/dev/null)"; RC=$?
  SNAP_AFTER="$(_snapshot "$C/repo")"
  _assert_eq "case12: empty base -> exit 3" "3" "$RC"
  _assert_contains "case12: empty base -> usage message on stderr" "$ERR" "usage: ds-base-sync"
  _assert_eq "case12: empty base -> local ref byte-identical pre/post (no git call made)" "$SNAP_BEFORE" "$SNAP_AFTER"

  ERR2="$("$TOOL" "" base 2>&1 1>/dev/null)"; RC2=$?
  _assert_eq "case12: empty repo -> exit 3" "3" "$RC2"
  _assert_contains "case12: empty repo -> error message on stderr" "$ERR2" "ds-base-sync"
}

echo "=== Case 13: HEAD on base, pull succeeds trivially with local already ahead, origin unchanged -> ff-pulled + NOTE ==="
{
  C="$TMP_ROOT/case13"
  _make_origin_and_clone "$C"
  echo "unpushed" >> "$C/repo/file.txt"
  git -C "$C/repo" add file.txt
  git -C "$C/repo" commit -q -m "unpushed local commit"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  _assert_eq "case13: exit 0" "0" "$RC"
  _assert_contains "case13: breadcrumb ff-pulled" "$OUT" "status=ff-pulled"
  _assert_contains "case13: NOTE line present" "$OUT" "NOTE:"
  _assert_contains "case13: NOTE names 1 unpushed commit" "$OUT" "1 commit(s) ahead"
}

echo "=== Case 14 (revised, round-3 correction): origin/<base> absent post-fetch -> refused-unknown, both branches ==="
# Original plan draft's setup (--single-branch clone, or deleting
# origin/<base>) does not make "pull --ff-only origin <base>" fail at all -
# it falls back to FETCH_HEAD and exits 0, so refused-unknown is never
# reached that way (verified by execution in round 3). This revision
# combines a --single-branch clone (so origin/<base> never gets a
# remote-tracking ref) with a genuine refusal cause on each branch, so the
# empty-counts refused-unknown tail is actually exercised - and explicitly
# NOT defaulted into ref-locked-elsewhere via an empty ahead value.
{
  C="$TMP_ROOT/case14"
  mkdir -p "$C"
  git init -q --bare "$C/origin.git"
  git -C "$C/origin.git" symbolic-ref HEAD refs/heads/other

  git init -q "$C/seed"
  _gitcfg "$C/seed"
  git -C "$C/seed" checkout -q -b other
  echo "other-init" > "$C/seed/other.txt"
  git -C "$C/seed" add other.txt
  git -C "$C/seed" commit -q -m "other init"
  git -C "$C/seed" remote add origin "$C/origin.git"
  git -C "$C/seed" push -q -u origin other

  git -C "$C/seed" checkout -q -b base
  echo "base-init" > "$C/seed/base.txt"
  git -C "$C/seed" add base.txt
  git -C "$C/seed" commit -q -m "base init"
  git -C "$C/seed" push -q origin base

  # --single-branch clone of "other" only: origin/base never gets a
  # remote-tracking ref, since the configured refspec covers only "other".
  git clone -q --single-branch --branch other "$C/origin.git" "$C/repo"
  _gitcfg "$C/repo"

  # --- HEAD-on-base variant: create local "base" (unrelated to origin/base
  # history since this clone never fetched it), check it out, lock the index
  # so pull --ff-only's merge phase refuses for an unrecognized reason.
  git -C "$C/repo" checkout -q -b base
  echo "local-base" > "$C/repo/localbase.txt"
  git -C "$C/repo" add localbase.txt
  git -C "$C/repo" commit -q -m "local base init"
  touch "$C/repo/.git/index.lock"
  OUT="$("$TOOL" "$C/repo" base)"; RC=$?
  rm -f "$C/repo/.git/index.lock"
  _assert_eq "case14 (HEAD-on-base): exit 4" "4" "$RC"
  _assert_contains "case14 (HEAD-on-base): breadcrumb refused-unknown" "$OUT" "status=refused-unknown"
  _assert_not_contains "case14 (HEAD-on-base): NOT ref-locked-elsewhere" "$OUT" "status=ref-locked-elsewhere"

  # --- HEAD-elsewhere variant: HEAD stays on "other"; local "base" branch
  # exists (unrelated history to origin's base, so the ref-write fetch is a
  # non-fast-forward refusal) but is NOT checked out anywhere.
  git -C "$C/repo" checkout -q other
  # base already exists (from the HEAD-on-base variant above) pointing at
  # unrelated local history; it is simply no longer checked out anywhere,
  # which is exactly what the HEAD-elsewhere non-fast-forward refusal needs.
  OUT2="$("$TOOL" "$C/repo" base)"; RC2=$?
  _assert_eq "case14 (HEAD-elsewhere): exit 4" "4" "$RC2"
  _assert_contains "case14 (HEAD-elsewhere): breadcrumb refused-unknown" "$OUT2" "status=refused-unknown"
  _assert_not_contains "case14 (HEAD-elsewhere): NOT ref-locked-elsewhere" "$OUT2" "status=ref-locked-elsewhere"
}

echo "=== Case 15 (round-4 CRITICAL regression): invoked via a PATH symlink still resolves scripts/lib/base-branch-sync.sh ==="
# .claude/install.sh's ae_install_bins() installs this tool on PATH as a
# SYMLINK: ~/.local/bin/agentic-base-sync -> $REPO_DIR/bin/agentic-base-sync.
# content/rules/conventions.md call site 2 invokes it BY NAME
# (`agentic-base-sync "$REPO" "$BASE_BRANCH"`), which resolves through that
# symlink. Before the round-4 fix, SCRIPT_DIR was computed from
# `dirname "${BASH_SOURCE[0]}"` WITHOUT resolving the symlink chain first -
# when invoked via the symlink, BASH_SOURCE[0] is the symlink's own path
# (e.g. a temp bin dir here, ~/.local/bin in production), so LIB_DIR
# resolved to a nonexistent sibling of THAT directory, not of the real
# script's directory, and the tool exited 3 with "base-branch-sync.sh not
# found" before ever calling git - silently defeating call site 2 (the
# reference doc's own words: "the mechanism that catches a PR merged by a
# human, by another session, or via `gh pr merge` outside
# /ds-implement-ticket entirely") on every real install.
{
  C="$TMP_ROOT/case15"
  _make_origin_and_clone "$C"
  _seed_advance "$C" "advance15"
  SYMLINK_DIR="$TMP_ROOT/case15-symlink-bin"
  mkdir -p "$SYMLINK_DIR"
  ln -s "$TOOL" "$SYMLINK_DIR/agentic-base-sync"
  # Capture stdout+stderr combined (2>&1): the pre-fix "base-branch-sync.sh
  # not found" error is printed to STDERR (bin/agentic-base-sync:66), so a
  # stdout-only capture can never observe it - that assertion would pass
  # vacuously both before and after the fix. The breadcrumb/status
  # assertions below still hold against the combined stream since the
  # success path never writes to stderr.
  OUT="$("$SYMLINK_DIR/agentic-base-sync" "$C/repo" base 2>&1)"; RC=$?
  ORIGIN_SHA="$(git -C "$C/repo" rev-parse origin/base)"
  LOCAL_SHA="$(git -C "$C/repo" rev-parse base)"
  _assert_eq "case15: symlink invocation exit 0 (not 3)" "0" "$RC"
  _assert_contains "case15: symlink invocation breadcrumb ff-pulled" "$OUT" "status=ff-pulled"
  _assert_not_contains "case15: symlink invocation did NOT fail to find base-branch-sync.sh" "$OUT" "base-branch-sync.sh not found"
  _assert_eq "case15: symlink invocation local ref == origin ref" "$ORIGIN_SHA" "$LOCAL_SHA"
}

echo "=== Case 16 (DS-54): hooks-snapshot staleness advisory note is printed after a sync, and never affects the exit code ==="
# Uses an isolated FAKE_HOME with repo_dir pointed at REPO_DIR (the real
# checkout, which actually ships hooks/lib/hooks-staleness-core.sh - the
# scratch <repo> fixtures used by the other cases do not) so the note fires
# deterministically regardless of this machine's real ~/.agentic state.
# Read-only: hooks-staleness-core.sh never writes; nothing under REPO_DIR
# itself is ever touched.
{
  C="$TMP_ROOT/case16"
  _make_origin_and_clone "$C"
  _seed_advance "$C" "advance16"

  FAKE_HOME="$TMP_ROOT/case16-home"
  mkdir -p "$FAKE_HOME/.agentic"
  cat > "$FAKE_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$REPO_DIR"
}
EOF
  # No snapshot has ever been synced under FAKE_HOME for REPO_DIR -> never_migrated.
  OUT="$(HOME="$FAKE_HOME" "$TOOL" "$C/repo" base 2>&1)"; RC=$?
  _assert_eq "case16: exit 0 (advisory note does not affect exit code)" "0" "$RC"
  _assert_contains "case16: breadcrumb ff-pulled" "$OUT" "status=ff-pulled"
  _assert_contains "case16: advisory note present" "$OUT" "ds-base-sync: dinostack: hooks are not yet snapshotted"
}

echo "=== Case 17 (DS-54): advisory note ABSENT when the operator's hooks snapshot is already current ==="
{
  C="$TMP_ROOT/case17"
  _make_origin_and_clone "$C"
  _seed_advance "$C" "advance17"

  FAKE_HOME="$TMP_ROOT/case17-home"
  mkdir -p "$FAKE_HOME/.agentic"
  cat > "$FAKE_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$REPO_DIR"
}
EOF
  # Sync the snapshot under FAKE_HOME for REPO_DIR first (mirrors what
  # install.sh does), so hooks-staleness-core.sh classifies "current"
  # (silent - no note).
  (
    HOME="$FAKE_HOME"
    export HOME
    # shellcheck source=/dev/null
    source "$REPO_DIR/scripts/lib/hooks-snapshot.sh"
    sync_hooks_snapshot "$REPO_DIR" >/dev/null
  )
  OUT="$(HOME="$FAKE_HOME" "$TOOL" "$C/repo" base 2>&1)"; RC=$?
  _assert_eq "case17: exit 0" "0" "$RC"
  _assert_not_contains "case17: advisory note ABSENT (snapshot already current)" "$OUT" "ds-base-sync:"
}

echo "=== Case 18 (round-6): worktree-reaper --count-only advisory note ACTUALLY EMITS when the synced repo has a non-root worktree ==="
# Case 17 above passes vacuously for the worktree-advisory leg specifically:
# its fixture repo has zero non-root worktrees, so _ds_reap_nonroot is
# always 0 and the note branch is never exercised - nothing in the
# existing suite actually drives a nonzero non-root count through
# bin/ds-reap-worktrees --count-only and asserts the note text. This case
# closes that gap by adding one extra worktree to $C/repo before syncing.
{
  C="$TMP_ROOT/case18"
  _make_origin_and_clone "$C"
  _seed_advance "$C" "advance18"
  git -C "$C/repo" worktree add -q "$C/repo/wt-extra" -b worktree-case18-extra >/dev/null

  # ds-base-sync resolves REPO_DIR via `pwd -P` (symlink-resolved), so the
  # path in its printed note can differ from the literal $C/repo (e.g. a
  # /var -> /private/var symlink on macOS) - match against the SAME
  # resolved path, not the literal one.
  RESOLVED_REPO="$(cd "$C/repo" && pwd -P)"

  OUT="$("$TOOL" "$C/repo" base 2>&1)"; RC=$?
  _assert_eq "case18: exit 0" "0" "$RC"
  _assert_contains "case18: breadcrumb ff-pulled" "$OUT" "status=ff-pulled"
  _assert_contains "case18: worktree-reaper advisory note present with correct non-root count" "$OUT" \
    "ds-base-sync: 1 non-root git worktree(s) in $RESOLVED_REPO - consider \`/ds-cleanup-worktrees\`"

  git -C "$C/repo" worktree remove "$C/repo/wt-extra" 2>/dev/null || true
}

echo "=== Locale robustness note (Finding N2 / LC_ALL=C) ==="
echo "Not independently reproducible as a test case on this git build: Apple"
echo "Git 2.39.5 ships no locale catalogs, so a translated-message failure"
echo "cannot be constructed here. LC_ALL=C is present in the implementation"
echo "(see scripts/lib/base-branch-sync.sh) and is verified by code"
echo "inspection, not by a locale-switching test - same treatment as case 4/11."

echo ""
echo "=== Deliberate-failure harness self-check ==="
# Verify the harness itself catches a real miss: assert something false and
# confirm the FAIL counter incremented by EXACTLY 1, then correct it back.
# Snapshotting FAIL before the probe (rather than just checking "FAIL >= 1"
# afterward) matters: if an earlier case had already failed for real, a
# ">= 1" check would pass regardless of whether THIS probe's failure was
# actually counted - it would only validate the counter when everything
# else was already green.
FAIL_BEFORE_PROBE="$FAIL"
_assert_eq "harness self-check (expected to fail)" "yes" "no"
FAIL_DELTA=$((FAIL - FAIL_BEFORE_PROBE))
if [[ "$FAIL_DELTA" -eq 1 ]]; then
  echo "PASS: harness self-check - a deliberately false assertion incremented FAIL by exactly 1"
  PASS=$((PASS + 1))
  FAIL=$((FAIL - 1))
else
  echo "FAIL: harness self-check - deliberately false assertion changed FAIL by $FAIL_DELTA (expected 1); the FAIL counter is broken" >&2
  FAIL=$((FAIL + 1))
fi

echo ""
echo "======================================"
echo "Results: $PASS passed, $FAIL failed"
echo "======================================"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
