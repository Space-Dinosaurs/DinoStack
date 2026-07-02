#!/usr/bin/env bash
# Purpose: Regression test for scripts/lib/precommit.sh's install_precommit_hook.
#          Ensures the pre-commit hook installer resolves the REAL git hooks
#          directory (via `git rev-parse --git-path hooks`) instead of the
#          hardcoded "$REPO_DIR/.git/hooks", which breaks when REPO_DIR is a
#          git worktree - there ".git" is a FILE (a gitdir pointer), not a
#          directory, so a plain `ln -s ... "$REPO_DIR/.git/hooks/..."` fails
#          with "Not a directory" (DS-58).
#
# Public API: ./bin/tests/test_precommit_worktree.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, mktemp.
#
# Downstream consumers: developer running locally before commit; can be
#                       wired into CI.
#
# Failure modes: any assertion failure prints the failing assertion and exits 1.
#                All fixtures live under a temporary directory; the real repo
#                and its .git/hooks are never touched.
#
# Performance: < 2 s wall time (pure git + shell, no network).
#
# Regression coverage:
#   - DS-58: `ln -s "$REPO_DIR/hooks/pre-commit" "$REPO_DIR/.git/hooks/pre-commit"`
#     fails with "Not a directory" when REPO_DIR is a git worktree (.git is a
#     file there, not a directory). install_precommit_hook resolves the real
#     hooks dir via `git -C "$REPO_DIR" rev-parse --git-path hooks`, which
#     follows the worktree's gitdir pointer back to the common repo's hooks
#     dir. This test re-creates a worktree fixture to prevent regression.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$REPO_DIR/scripts/lib/precommit.sh"

if [[ ! -f "$LIB" ]]; then
  echo "FAIL: $LIB not found" >&2
  exit 1
fi

# shellcheck source=scripts/lib/precommit.sh
. "$LIB"

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

# Stub matching the real per-adapter _ae_is_ours contract closely enough for
# this test: nothing pre-existing points at another methodology checkout, so
# it always reports "not ours" (never re-points a stale symlink).
_ae_is_ours() {
  return 1
}

AE_DRY_RUN=false

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  [[ -n "${TMP_ROOT:-}" && -d "$TMP_ROOT" ]] && rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

# _make_fixture_repo <dir>
#   git-inits <dir>, commits a tracked hooks/pre-commit file.
_make_fixture_repo() {
  local dir="$1"
  mkdir -p "$dir/hooks"
  git init -q "$dir"
  git -C "$dir" config user.email test@test.com
  git -C "$dir" config user.name test
  printf '#!/usr/bin/env bash\necho fixture pre-commit\n' > "$dir/hooks/pre-commit"
  chmod +x "$dir/hooks/pre-commit"
  git -C "$dir" add hooks/pre-commit
  git -C "$dir" commit -q -m "fixture: add pre-commit hook"
}

# ============================================================
# Test 1: normal checkout (.git is a directory) - baseline still works
# ============================================================

NORMAL_REPO="$TMP_ROOT/normal-repo"
_make_fixture_repo "$NORMAL_REPO"

if [[ -d "$NORMAL_REPO/.git" ]]; then
  _pass "normal-repo fixture: .git is a directory"
else
  _fail "normal-repo fixture: .git is not a directory (fixture setup bug)"
fi

OUT="$(install_precommit_hook "$NORMAL_REPO" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "normal case: install_precommit_hook exits 0"
else
  _fail "normal case: install_precommit_hook exited $RC. Output: $OUT"
fi

if echo "$OUT" | grep -qi "not a directory"; then
  _fail "normal case: unexpected 'Not a directory' error. Output: $OUT"
else
  _pass "normal case: no 'Not a directory' error"
fi

NORMAL_HOOK_DST="$NORMAL_REPO/.git/hooks/pre-commit"
if [[ -L "$NORMAL_HOOK_DST" ]] && [[ "$(readlink "$NORMAL_HOOK_DST")" == "$NORMAL_REPO/hooks/pre-commit" ]]; then
  _pass "normal case: pre-commit symlink installed at $NORMAL_HOOK_DST"
else
  _fail "normal case: pre-commit symlink not found/correct at $NORMAL_HOOK_DST. Output: $OUT"
fi

# ============================================================
# Test 2: worktree checkout (.git is a FILE) - DS-58 regression
# ============================================================

WT_MAIN="$TMP_ROOT/wt-main-repo"
_make_fixture_repo "$WT_MAIN"

WT_BRANCH="$TMP_ROOT/wt-branch"
git -C "$WT_MAIN" worktree add -q "$WT_BRANCH" -b wt-test-branch >/dev/null 2>&1

if [[ -f "$WT_BRANCH/.git" ]] && [[ ! -d "$WT_BRANCH/.git" ]]; then
  _pass "worktree fixture: .git is a file (gitdir pointer), not a directory"
else
  _fail "worktree fixture: .git is not a file as expected (fixture setup bug)"
fi

OUT="$(install_precommit_hook "$WT_BRANCH" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "worktree case: install_precommit_hook exits 0"
else
  _fail "worktree case: install_precommit_hook exited $RC. Output: $OUT"
fi

if echo "$OUT" | grep -qi "not a directory"; then
  _fail "worktree case (DS-58 regression): 'Not a directory' error resurfaced. Output: $OUT"
else
  _pass "worktree case: no 'Not a directory' error (DS-58 fixed)"
fi

# The real hooks dir for a worktree is the MAIN repo's .git/hooks, shared
# across all of that repo's worktrees.
REAL_HOOKS_DIR="$(git -C "$WT_BRANCH" rev-parse --git-path hooks)"
case "$REAL_HOOKS_DIR" in
  /*) : ;;
  *) REAL_HOOKS_DIR="$WT_BRANCH/$REAL_HOOKS_DIR" ;;
esac
WT_HOOK_DST="$REAL_HOOKS_DIR/pre-commit"

if [[ "$REAL_HOOKS_DIR" -ef "$WT_MAIN/.git/hooks" ]]; then
  _pass "worktree case: real hooks dir resolves to the main repo's .git/hooks"
else
  _fail "worktree case: real hooks dir resolved to unexpected path: $REAL_HOOKS_DIR"
fi

if [[ -L "$WT_HOOK_DST" ]] && [[ "$(readlink "$WT_HOOK_DST")" == "$WT_BRANCH/hooks/pre-commit" ]]; then
  _pass "worktree case: pre-commit symlink installed at real hooks dir ($WT_HOOK_DST)"
else
  _fail "worktree case: pre-commit symlink not found/correct at $WT_HOOK_DST. Output: $OUT"
fi

# ============================================================
# Test 3: hooks-dir resolution failure is non-fatal
# ============================================================

NOT_A_REPO="$TMP_ROOT/not-a-repo"
mkdir -p "$NOT_A_REPO/hooks"
printf '#!/usr/bin/env bash\necho fixture pre-commit\n' > "$NOT_A_REPO/hooks/pre-commit"

OUT="$(install_precommit_hook "$NOT_A_REPO" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "non-repo case: install_precommit_hook returns 0 (non-fatal) when git-path resolution fails"
else
  _fail "non-repo case: install_precommit_hook exited $RC instead of 0. Output: $OUT"
fi

if echo "$OUT" | grep -qi "skipping pre-commit hook install"; then
  _pass "non-repo case: prints a non-fatal skip warning"
else
  _fail "non-repo case: expected a non-fatal skip warning. Output: $OUT"
fi

# ---- Results ----

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
