#!/usr/bin/env bash
# Purpose: Regression test for scripts/lib/precommit.sh's install_precommit_hook
#          and uninstall_precommit_hook. Ensures both resolve the REAL git
#          hooks directory (via `git rev-parse --git-path hooks`) instead of
#          the hardcoded "$REPO_DIR/.git/hooks", which breaks when REPO_DIR is
#          a git worktree - there ".git" is a FILE (a gitdir pointer), not a
#          directory, so a plain `ln -s`/`rm` against
#          "$REPO_DIR/.git/hooks/..." fails or silently no-ops (DS-58, both
#          the install side and the symmetric uninstall side). Also covers
#          the follow-up fix: the symlink SOURCE must be the common repo's
#          own "hooks/pre-commit", not the worktree's - a worktree's working
#          tree is ephemeral, and pointing the shared hook at a path inside
#          it leaves a dangling symlink once that worktree is removed (git
#          silently treats a dangling hook symlink as "no hook", not an
#          error - the commit-time regression that motivated this addendum).
#
# Public API: ./bin/tests/test_precommit_worktree.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, mktemp.
#
# Downstream consumers: developer running locally before commit; can be
#                       wired into CI (.github/workflows/bin-tests.yml).
#
# Failure modes: any assertion failure prints the failing assertion and exits 1.
#                All fixtures live under a temporary directory; the real repo
#                and its .git/hooks are never touched (verified by this test
#                itself via a before/after checksum AND a before/after
#                `readlink` of the real hook's own symlink target - the
#                checksum alone is insufficient because `shasum` follows a
#                symlink and hashes its resolved content, so it cannot
#                detect a re-point at a byte-identical hooks/pre-commit in
#                a different checkout; see Test 7).
#
# Performance: < 2 s wall time (pure git + shell, no network).
#
# Regression coverage:
#   - DS-58 (install side): `ln -s "$REPO_DIR/hooks/pre-commit"
#     "$REPO_DIR/.git/hooks/pre-commit"` fails with "Not a directory" when
#     REPO_DIR is a git worktree (.git is a file there, not a directory).
#     install_precommit_hook resolves the real hooks dir via
#     `git -C "$REPO_DIR" rev-parse --git-path hooks`, which follows the
#     worktree's gitdir pointer back to the common repo's hooks dir.
#   - DS-58 (uninstall side, symmetric Minor): the same hardcoded
#     "$REPO_DIR/.git/hooks/pre-commit" made uninstall.sh stat an
#     unresolvable path from a worktree, report "nothing to do", and leave
#     the hook installed. uninstall_precommit_hook shares the same
#     resolve_git_hooks_dir resolution and removes the AE-owned hook from
#     the real (shared, main-repo) hooks dir; a foreign hook is preserved.
#   - post-DS-58 dangling-symlink regression (worktree-hijack): the hooks
#     DIRECTORY resolution (DS-58) was correct, but install_precommit_hook
#     still symlinked "<repo_dir>/hooks/pre-commit" as the TARGET - inside
#     the worktree itself. Once that worktree was removed, the shared
#     .git/hooks/pre-commit symlink dangled and git silently ran no hook at
#     all (no error - commits just stopped being checked). Fixed via
#     resolve_hook_src, which points the symlink at the COMMON repo's own
#     hooks/pre-commit when repo_dir is a linked worktree. Test 6 below
#     creates a REAL linked worktree, installs from it, removes it, and
#     asserts the main checkout's hook still resolves AND executes -
#     confirmed to fail against the pre-fix source (see git history/PR for
#     the baseline failure output this test was written to catch).
#   - Major 1 (dangling-at-install for bare/separate-gitdir/submodule
#     worktrees): Test 8 exercises a bare repo + `git worktree add`, where
#     dirname(--git-common-dir) has no hooks/pre-commit of its own.
#     resolve_hook_src falls back to the worktree's own hooks/pre-commit
#     rather than emitting a target dangling from install time. Test 8 ALSO
#     asserts the KNOWN, undisclosed-no-longer residual: this fallback
#     target is still inside the worktree, so removing the worktree leaves
#     the hook dangling anyway (see the library's Failure-modes "KNOWN
#     RESIDUAL" bullet) - not a regression, not fixed by this PR, disclosed
#     rather than silently left unverified.
#   - Major 2 (uninstall orphaning a legacy-targeted hook): Test 9 (canonical
#     fixture path only - see Test 12 for the non-canonical variant).
#   - Minor 1 (install_precommit_hook's `[[ ! -f "$hook_src" ]]` guard was
#     reachable but had zero coverage): Test 10 - an ordinary repo with no
#     hooks/pre-commit file at all, the only shape that exercises
#     resolve_hook_src's unchecked fallback branches.
#   - Minor 3 (legacy_hook_src used the raw, non-canonicalized repo_dir):
#     Test 11 - install with a trailing-slash spelling, uninstall with the
#     canonical spelling of the same directory.
#   - Major 1 (round 3: legacy candidate regressed against a symlinked-
#     parent, non-canonical repo_dir spelling - the cross-version boundary
#     where pre-this-PR code always used the raw spelling but the legacy
#     candidate had become canonical-only): Test 12.
#   This test re-creates worktree fixtures for all of the above to prevent
#   regression.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$REPO_DIR/scripts/lib/precommit.sh"

if [[ ! -f "$LIB" ]]; then
  echo "FAIL: $LIB not found" >&2
  exit 1
fi

# Checksum the REAL checkout's actual hook before running anything, so Test 7
# (below) can assert this test file never touched it. All fixtures in this
# file operate on isolated temp repos under $TMP_ROOT - never on $REPO_DIR.
# Resolved via `git rev-parse --git-path hooks` (not a hardcoded
# "$REPO_DIR/.git/hooks") so this also works correctly when the test itself
# is being run from a linked worktree, where ".git" is a file, not a dir.
REAL_HOOKS_DIR_FOR_CHECKSUM="$(git -C "$REPO_DIR" rev-parse --git-path hooks 2>/dev/null)"
case "$REAL_HOOKS_DIR_FOR_CHECKSUM" in
  /*) : ;;
  "") : ;;
  *) REAL_HOOKS_DIR_FOR_CHECKSUM="$REPO_DIR/$REAL_HOOKS_DIR_FOR_CHECKSUM" ;;
esac
REAL_HOOK_PATH_FOR_CHECKSUM="$REAL_HOOKS_DIR_FOR_CHECKSUM/pre-commit"
REAL_HOOK_CHECKSUM_BEFORE=""
if [[ -n "$REAL_HOOKS_DIR_FOR_CHECKSUM" ]] && [[ -e "$REAL_HOOK_PATH_FOR_CHECKSUM" ]]; then
  REAL_HOOK_CHECKSUM_BEFORE="$(shasum -a 256 "$REAL_HOOK_PATH_FOR_CHECKSUM" 2>/dev/null | awk '{print $1}')"
fi
# `shasum` FOLLOWS a symlink and hashes its resolved content, so a checksum
# alone cannot detect a re-point of the real hook symlink at a
# byte-identical hooks/pre-commit in a DIFFERENT checkout - precisely this
# PR's bug shape (a dangling/mis-targeted symlink that still happens to
# resolve to identical bytes today). Capture the symlink's own TARGET via
# `readlink` as well, so Test 7 below can assert the link itself, not just
# its resolved content, is unchanged.
REAL_HOOK_TARGET_BEFORE=""
if [[ -L "$REAL_HOOK_PATH_FOR_CHECKSUM" ]]; then
  REAL_HOOK_TARGET_BEFORE="$(readlink "$REAL_HOOK_PATH_FOR_CHECKSUM")"
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
# Resolve to the physical path (macOS /tmp -> /private/tmp symlink) so that
# string-equality comparisons against paths git resolves via
# `rev-parse --path-format=absolute` (which follows symlinks) agree with the
# path this script builds by string concatenation - otherwise the two are
# semantically the same location but never string-equal.
TMP_ROOT="$(cd "$TMP_ROOT" && pwd -P)"
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

# The symlink TARGET must be the common (main) repo's own hooks/pre-commit,
# NOT the worktree's - the worktree's working tree is ephemeral and a
# target inside it dangles once the worktree is removed (the bug this test
# file's Test 6 exercises end-to-end).
if [[ -L "$WT_HOOK_DST" ]] && [[ "$(readlink "$WT_HOOK_DST")" == "$WT_MAIN/hooks/pre-commit" ]]; then
  _pass "worktree case: pre-commit symlink installed at real hooks dir, targeting the MAIN repo's hooks/pre-commit ($WT_HOOK_DST)"
else
  _fail "worktree case: pre-commit symlink not found/correct (expected target $WT_MAIN/hooks/pre-commit) at $WT_HOOK_DST. Output: $OUT"
fi

# A second install run from the same worktree must be a no-op (the resolved
# source already matches) rather than rewriting the symlink.
OUT2="$(install_precommit_hook "$WT_BRANCH" 2>&1)"
if echo "$OUT2" | grep -qi "already linked"; then
  _pass "worktree case: re-running install_precommit_hook from the worktree is a no-op"
else
  _fail "worktree case: expected 'already linked' no-op on re-install. Output: $OUT2"
fi

# ============================================================
# Test 3: uninstall from a worktree removes the AE-owned hook (DS-58,
#         symmetric uninstall-side regression)
# ============================================================

UNINSTALL_WT_MAIN="$TMP_ROOT/uninstall-wt-main-repo"
_make_fixture_repo "$UNINSTALL_WT_MAIN"

UNINSTALL_WT_BRANCH="$TMP_ROOT/uninstall-wt-branch"
git -C "$UNINSTALL_WT_MAIN" worktree add -q "$UNINSTALL_WT_BRANCH" -b uninstall-wt-test-branch >/dev/null 2>&1

# Install first (from the worktree), so there is something to uninstall.
install_precommit_hook "$UNINSTALL_WT_BRANCH" >/dev/null 2>&1

UNINSTALL_REAL_HOOKS_DIR="$(git -C "$UNINSTALL_WT_BRANCH" rev-parse --git-path hooks)"
case "$UNINSTALL_REAL_HOOKS_DIR" in
  /*) : ;;
  *) UNINSTALL_REAL_HOOKS_DIR="$UNINSTALL_WT_BRANCH/$UNINSTALL_REAL_HOOKS_DIR" ;;
esac
UNINSTALL_HOOK_DST="$UNINSTALL_REAL_HOOKS_DIR/pre-commit"

if [[ -L "$UNINSTALL_HOOK_DST" ]] && [[ "$(readlink "$UNINSTALL_HOOK_DST")" == "$UNINSTALL_WT_MAIN/hooks/pre-commit" ]]; then
  _pass "uninstall setup: pre-commit hook installed at real hooks dir before uninstall test, targeting the MAIN repo"
else
  _fail "uninstall setup: pre-commit hook not installed at $UNINSTALL_HOOK_DST as expected"
fi

OUT="$(uninstall_precommit_hook "$UNINSTALL_WT_BRANCH" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "uninstall-from-worktree case: uninstall_precommit_hook exits 0"
else
  _fail "uninstall-from-worktree case: uninstall_precommit_hook exited $RC. Output: $OUT"
fi

if [[ ! -e "$UNINSTALL_HOOK_DST" ]]; then
  _pass "uninstall-from-worktree case (DS-58 fixed): AE-owned pre-commit hook actually removed"
else
  _fail "uninstall-from-worktree case (DS-58 regression): pre-commit hook still present at $UNINSTALL_HOOK_DST. Output: $OUT"
fi

if echo "$OUT" | grep -qi "nothing to do"; then
  _fail "uninstall-from-worktree case: reported 'nothing to do' despite an AE-owned hook being present (DS-58 regression). Output: $OUT"
else
  _pass "uninstall-from-worktree case: did not falsely report 'nothing to do'"
fi

# ============================================================
# Test 4: uninstall from a worktree preserves a foreign (non-AE) hook
# ============================================================

FOREIGN_WT_MAIN="$TMP_ROOT/foreign-wt-main-repo"
_make_fixture_repo "$FOREIGN_WT_MAIN"

FOREIGN_WT_BRANCH="$TMP_ROOT/foreign-wt-branch"
git -C "$FOREIGN_WT_MAIN" worktree add -q "$FOREIGN_WT_BRANCH" -b foreign-wt-test-branch >/dev/null 2>&1

FOREIGN_REAL_HOOKS_DIR="$(git -C "$FOREIGN_WT_BRANCH" rev-parse --git-path hooks)"
case "$FOREIGN_REAL_HOOKS_DIR" in
  /*) : ;;
  *) FOREIGN_REAL_HOOKS_DIR="$FOREIGN_WT_BRANCH/$FOREIGN_REAL_HOOKS_DIR" ;;
esac
FOREIGN_HOOK_DST="$FOREIGN_REAL_HOOKS_DIR/pre-commit"

# Simulate a foreign (non-AE) pre-commit hook already present at the real
# hooks dir - a real file, not a symlink into this checkout.
mkdir -p "$FOREIGN_REAL_HOOKS_DIR"
printf '#!/usr/bin/env bash\necho a foreign, non-AE pre-commit hook\n' > "$FOREIGN_HOOK_DST"
chmod +x "$FOREIGN_HOOK_DST"

OUT="$(uninstall_precommit_hook "$FOREIGN_WT_BRANCH" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "foreign-hook case: uninstall_precommit_hook exits 0"
else
  _fail "foreign-hook case: uninstall_precommit_hook exited $RC. Output: $OUT"
fi

if [[ -e "$FOREIGN_HOOK_DST" ]] && [[ ! -L "$FOREIGN_HOOK_DST" ]]; then
  _pass "foreign-hook case: foreign pre-commit hook preserved (not removed)"
else
  _fail "foreign-hook case: foreign pre-commit hook was removed or altered. Output: $OUT"
fi

# ============================================================
# Test 5: hooks-dir resolution failure is non-fatal
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

OUT="$(uninstall_precommit_hook "$NOT_A_REPO" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "non-repo case: uninstall_precommit_hook returns 0 (non-fatal) when git-path resolution fails"
else
  _fail "non-repo case: uninstall_precommit_hook exited $RC instead of 0. Output: $OUT"
fi

if echo "$OUT" | grep -qi "skipping pre-commit hook removal"; then
  _pass "non-repo case: uninstall prints a non-fatal skip warning"
else
  _fail "non-repo case: uninstall expected a non-fatal skip warning. Output: $OUT"
fi

# ============================================================
# Test 6: post-DS-58 worktree-hijack regression - a REAL linked worktree is
#         created, install_precommit_hook runs from it, the worktree is then
#         REMOVED, and the main checkout's shared hook must still resolve
#         AND execute. A plain `test -e` on a dangling symlink is FALSE (it
#         does not follow to a missing target), so this alone is enough to
#         catch the bug - but this test goes further and actually invokes
#         the hook to prove it runs, not just that the path resolves.
# ============================================================

HIJACK_MAIN="$TMP_ROOT/hijack-main-repo"
_make_fixture_repo "$HIJACK_MAIN"

HIJACK_WT="$TMP_ROOT/hijack-wt-branch"
git -C "$HIJACK_MAIN" worktree add -q "$HIJACK_WT" -b hijack-wt-test-branch >/dev/null 2>&1

install_precommit_hook "$HIJACK_WT" >/dev/null 2>&1

MAIN_HOOK_DST="$HIJACK_MAIN/.git/hooks/pre-commit"

if [[ -L "$MAIN_HOOK_DST" ]]; then
  _pass "Test 6 setup: main repo's .git/hooks/pre-commit is a symlink after install-from-worktree"
else
  _fail "Test 6 setup: main repo's .git/hooks/pre-commit is not a symlink at $MAIN_HOOK_DST"
fi

# Remove the worktree - this is the moment the pre-fix bug fires: if the
# symlink target was inside $HIJACK_WT, it now dangles.
git -C "$HIJACK_MAIN" worktree remove -f "$HIJACK_WT" >/dev/null 2>&1

if [[ -e "$MAIN_HOOK_DST" ]]; then
  _pass "Test 6: main repo's pre-commit symlink still resolves (test -e true) after the worktree was removed"
else
  _fail "Test 6 (worktree-hijack regression): main repo's pre-commit symlink is DANGLING after worktree removal - test -e is false at $MAIN_HOOK_DST"
fi

if [[ -x "$MAIN_HOOK_DST" ]]; then
  _pass "Test 6: main repo's pre-commit symlink still resolves to an executable (test -x true)"
else
  _fail "Test 6 (worktree-hijack regression): main repo's pre-commit symlink does not resolve to an executable at $MAIN_HOOK_DST"
fi

HOOK_RUN_OUTPUT="$("$MAIN_HOOK_DST" 2>&1)"
HOOK_RUN_RC=$?
if [[ $HOOK_RUN_RC -eq 0 ]] && [[ "$HOOK_RUN_OUTPUT" == "fixture pre-commit" ]]; then
  _pass "Test 6: main repo's pre-commit hook actually EXECUTES after the worktree was removed (output: $HOOK_RUN_OUTPUT)"
else
  _fail "Test 6 (worktree-hijack regression): main repo's pre-commit hook failed to execute after worktree removal. rc=$HOOK_RUN_RC output=$HOOK_RUN_OUTPUT"
fi

# ============================================================
# Test 7: real checkout's actual .git/hooks/pre-commit is never touched by
#         this test file. All fixtures above use isolated temp repos; this
#         asserts that invariant directly rather than trusting it.
#
#         Verified via TWO independent before/after checks, not one:
#         a `shasum` of the resolved content, AND a `readlink` of the
#         symlink's own target. `shasum` follows a symlink and hashes what
#         it resolves to, so it alone is BLIND to a re-point of the link at
#         a different, byte-identical hooks/pre-commit (e.g. another
#         checkout's copy of the same file) - exactly this PR's bug shape.
#         The `readlink` check catches that a `shasum`-only test would miss.
# ============================================================

REAL_HOOK_TARGET_AFTER=""
if [[ -L "$REAL_HOOK_PATH_FOR_CHECKSUM" ]]; then
  REAL_HOOK_TARGET_AFTER="$(readlink "$REAL_HOOK_PATH_FOR_CHECKSUM")"
fi
if [[ "$REAL_HOOK_TARGET_AFTER" == "$REAL_HOOK_TARGET_BEFORE" ]]; then
  _pass "Test 7: real checkout's .git/hooks/pre-commit symlink target unchanged by this test run (${REAL_HOOK_TARGET_AFTER:-<not a symlink>})"
else
  _fail "Test 7: real checkout's .git/hooks/pre-commit symlink target CHANGED - before=$REAL_HOOK_TARGET_BEFORE after=$REAL_HOOK_TARGET_AFTER"
fi

if [[ -n "$REAL_HOOKS_DIR_FOR_CHECKSUM" ]] && [[ -e "$REAL_HOOK_PATH_FOR_CHECKSUM" ]]; then
  REAL_HOOK_CHECKSUM_AFTER="$(shasum -a 256 "$REAL_HOOK_PATH_FOR_CHECKSUM" 2>/dev/null | awk '{print $1}')"
  if [[ "$REAL_HOOK_CHECKSUM_AFTER" == "$REAL_HOOK_CHECKSUM_BEFORE" ]]; then
    _pass "Test 7: real checkout's .git/hooks/pre-commit checksum unchanged by this test run ($REAL_HOOK_CHECKSUM_AFTER)"
  else
    _fail "Test 7: real checkout's .git/hooks/pre-commit checksum CHANGED - before=$REAL_HOOK_CHECKSUM_BEFORE after=$REAL_HOOK_CHECKSUM_AFTER"
  fi
else
  if [[ -z "$REAL_HOOK_CHECKSUM_BEFORE" ]]; then
    _pass "Test 7: real checkout's .git/hooks/pre-commit did not exist before or after this test run"
  else
    _fail "Test 7: real checkout's .git/hooks/pre-commit existed before this run (checksum $REAL_HOOK_CHECKSUM_BEFORE) but is missing after"
  fi
fi

# ============================================================
# Test 8: bare repo + `git worktree add` - Major-1 regression (dangling
#         symlink at install time). dirname(--git-common-dir) for this
#         layout is the bare repo's PARENT directory, which has no
#         "hooks/pre-commit" of its own - resolve_hook_src must detect that
#         the candidate file does not exist and fall back to the worktree's
#         own "hooks/pre-commit" (which DOES exist, checked out from the
#         same tracked history) rather than emit a target that is dangling
#         from the moment it is installed.
# ============================================================

BARE_SRC_REPO="$TMP_ROOT/bare-src-repo"
_make_fixture_repo "$BARE_SRC_REPO"

BARE_REPO="$TMP_ROOT/bare-repo.git"
git clone -q --bare "$BARE_SRC_REPO" "$BARE_REPO" >/dev/null 2>&1

BARE_WT="$TMP_ROOT/bare-wt-branch"
git -C "$BARE_REPO" worktree add -q "$BARE_WT" -b bare-wt-test-branch >/dev/null 2>&1

if [[ -f "$BARE_WT/hooks/pre-commit" ]]; then
  _pass "Test 8 setup: bare-repo worktree fixture has a real hooks/pre-commit checked out"
else
  _fail "Test 8 setup: bare-repo worktree fixture missing hooks/pre-commit at $BARE_WT/hooks/pre-commit (fixture setup bug)"
fi

BARE_COMMON_DIR="$(git -C "$BARE_WT" rev-parse --path-format=absolute --git-common-dir)"
BARE_COMMON_DIR_PARENT="$(dirname "$BARE_COMMON_DIR")"
if [[ ! -f "$BARE_COMMON_DIR_PARENT/hooks/pre-commit" ]]; then
  _pass "Test 8 setup: dirname(--git-common-dir) ($BARE_COMMON_DIR_PARENT) has no hooks/pre-commit of its own - this is the layout Major 1 exercises"
else
  _fail "Test 8 setup: unexpectedly found hooks/pre-commit under dirname(--git-common-dir) - fixture does not exercise the bug"
fi

BARE_HOOK_SRC="$(resolve_hook_src "$BARE_WT")"

if [[ -f "$BARE_HOOK_SRC" ]]; then
  _pass "Test 8 (Major 1): resolve_hook_src for a bare-repo worktree returns a source file that actually EXISTS ($BARE_HOOK_SRC)"
else
  _fail "Test 8 (Major 1 regression): resolve_hook_src for a bare-repo worktree returned a NONEXISTENT source: $BARE_HOOK_SRC - this is the dangling-at-install bug"
fi

if [[ "$BARE_HOOK_SRC" == "$BARE_WT/hooks/pre-commit" ]]; then
  _pass "Test 8: bare-repo worktree falls back to the worktree's own hooks/pre-commit (the only one that exists in this layout)"
else
  _fail "Test 8: bare-repo worktree resolved to an unexpected source: $BARE_HOOK_SRC"
fi

BARE_OUT="$(install_precommit_hook "$BARE_WT" 2>&1)"
BARE_RC=$?

if [[ $BARE_RC -eq 0 ]]; then
  _pass "Test 8: install_precommit_hook exits 0 for a bare-repo worktree"
else
  _fail "Test 8: install_precommit_hook exited $BARE_RC for a bare-repo worktree. Output: $BARE_OUT"
fi

BARE_HOOK_DST="$BARE_REPO/hooks/pre-commit"
if [[ -e "$BARE_HOOK_DST" ]] && [[ -x "$BARE_HOOK_DST" ]]; then
  _pass "Test 8 (Major 1): installed hook resolves and is executable, not dangling ($BARE_HOOK_DST)"
else
  _fail "Test 8 (Major 1 regression): installed hook is dangling or missing at $BARE_HOOK_DST. Output: $BARE_OUT"
fi

BARE_HOOK_RUN_OUTPUT="$("$BARE_HOOK_DST" 2>&1)"
BARE_HOOK_RUN_RC=$?
if [[ $BARE_HOOK_RUN_RC -eq 0 ]] && [[ "$BARE_HOOK_RUN_OUTPUT" == "fixture pre-commit" ]]; then
  _pass "Test 8 (Major 1): installed hook actually EXECUTES for a bare-repo worktree (output: $BARE_HOOK_RUN_OUTPUT)"
else
  _fail "Test 8 (Major 1 regression): installed hook failed to execute for a bare-repo worktree. rc=$BARE_HOOK_RUN_RC output=$BARE_HOOK_RUN_OUTPUT"
fi

# Test 8 (Minor 2, known-residual disclosure): unlike Test 6's ordinary
# linked worktree, this bare-repo layout has no better source than the
# worktree's OWN hooks/pre-commit (see the manifest's "KNOWN RESIDUAL"
# Failure-modes bullet) - resolve_hook_src cannot point at anything outside
# the worktree here because nothing outside it exists. Removing the
# worktree therefore leaves the installed symlink DANGLING. This is NOT a
# regression (identical on origin/main) and NOT something this PR fixes -
# asserting the known-bad outcome directly documents the residual instead
# of leaving it silently unverified (Test 6, by contrast, asserts the
# GOOD outcome because an ordinary linked worktree DOES have a better
# source: the main checkout's own hooks/pre-commit).
git -C "$BARE_REPO" worktree remove -f "$BARE_WT" >/dev/null 2>&1

if [[ -L "$BARE_HOOK_DST" ]] && [[ ! -e "$BARE_HOOK_DST" ]]; then
  _pass "Test 8 (Minor 2, known residual documented): bare-repo worktree hook is DANGLING after worktree removal, as disclosed in the manifest's Failure modes section (not a regression, no better source exists)"
else
  _fail "Test 8 (Minor 2 regression): expected the KNOWN residual (a DANGLING symlink, i.e. -L true and -e false) but got -L=$([[ -L "$BARE_HOOK_DST" ]] && echo true || echo false) -e=$([[ -e "$BARE_HOOK_DST" ]] && echo true || echo false) at $BARE_HOOK_DST - either the residual was silently fixed (update the manifest disclosure), the fixture broke, or the symlink was never created (plain absence, not dangling)"
fi

# ============================================================
# Test 9: Major-2 regression - uninstall recognises a hook installed by the
#         legacy (pre-this-PR) unconditional "<repo_dir>/hooks/pre-commit"
#         target, AND a foreign hook pointing at neither target is still
#         left alone (the widened check must not over-match).
# ============================================================

LEGACY_WT_MAIN="$TMP_ROOT/legacy-wt-main-repo"
_make_fixture_repo "$LEGACY_WT_MAIN"

LEGACY_WT_BRANCH="$TMP_ROOT/legacy-wt-branch"
git -C "$LEGACY_WT_MAIN" worktree add -q "$LEGACY_WT_BRANCH" -b legacy-wt-test-branch >/dev/null 2>&1

LEGACY_REAL_HOOKS_DIR="$(git -C "$LEGACY_WT_BRANCH" rev-parse --git-path hooks)"
case "$LEGACY_REAL_HOOKS_DIR" in
  /*) : ;;
  *) LEGACY_REAL_HOOKS_DIR="$LEGACY_WT_BRANCH/$LEGACY_REAL_HOOKS_DIR" ;;
esac
LEGACY_HOOK_DST="$LEGACY_REAL_HOOKS_DIR/pre-commit"

# Simulate a hook installed by the OLD (pre-this-PR) code: unconditionally
# targeting "<repo_dir>/hooks/pre-commit" inside the worktree itself, not
# the new worktree-aware resolved target.
mkdir -p "$LEGACY_REAL_HOOKS_DIR"
ln -s "$LEGACY_WT_BRANCH/hooks/pre-commit" "$LEGACY_HOOK_DST"

LEGACY_OUT="$(uninstall_precommit_hook "$LEGACY_WT_BRANCH" 2>&1)"
LEGACY_RC=$?

if [[ $LEGACY_RC -eq 0 ]]; then
  _pass "Test 9 (Major 2): uninstall_precommit_hook exits 0 for a legacy-targeted hook"
else
  _fail "Test 9 (Major 2): uninstall_precommit_hook exited $LEGACY_RC. Output: $LEGACY_OUT"
fi

if [[ ! -e "$LEGACY_HOOK_DST" ]]; then
  _pass "Test 9 (Major 2): legacy-targeted (pre-this-PR) hook is removed by uninstall"
else
  _fail "Test 9 (Major 2 regression): legacy-targeted hook still present at $LEGACY_HOOK_DST after uninstall - orphaned, will dangle once the worktree is removed. Output: $LEGACY_OUT"
fi

# Foreign-hook guard: a symlink pointing at neither the resolved target nor
# the legacy target must still be left alone by the widened check.
FOREIGN2_WT_MAIN="$TMP_ROOT/foreign2-wt-main-repo"
_make_fixture_repo "$FOREIGN2_WT_MAIN"

FOREIGN2_WT_BRANCH="$TMP_ROOT/foreign2-wt-branch"
git -C "$FOREIGN2_WT_MAIN" worktree add -q "$FOREIGN2_WT_BRANCH" -b foreign2-wt-test-branch >/dev/null 2>&1

FOREIGN2_REAL_HOOKS_DIR="$(git -C "$FOREIGN2_WT_BRANCH" rev-parse --git-path hooks)"
case "$FOREIGN2_REAL_HOOKS_DIR" in
  /*) : ;;
  *) FOREIGN2_REAL_HOOKS_DIR="$FOREIGN2_WT_BRANCH/$FOREIGN2_REAL_HOOKS_DIR" ;;
esac
FOREIGN2_HOOK_DST="$FOREIGN2_REAL_HOOKS_DIR/pre-commit"

# Points at a completely unrelated path - neither the resolved worktree
# target nor "<repo_dir>/hooks/pre-commit" for THIS repo_dir.
FOREIGN2_UNRELATED_TARGET="$TMP_ROOT/some-other-project/hooks/pre-commit"
mkdir -p "$FOREIGN2_REAL_HOOKS_DIR"
ln -s "$FOREIGN2_UNRELATED_TARGET" "$FOREIGN2_HOOK_DST"

FOREIGN2_OUT="$(uninstall_precommit_hook "$FOREIGN2_WT_BRANCH" 2>&1)"

if [[ -L "$FOREIGN2_HOOK_DST" ]] && [[ "$(readlink "$FOREIGN2_HOOK_DST")" == "$FOREIGN2_UNRELATED_TARGET" ]]; then
  _pass "Test 9 (Major 2, no over-match): a symlink pointing at neither the resolved nor legacy target is left untouched"
else
  _fail "Test 9 (Major 2 regression, over-match): the widened uninstall check removed or altered a genuinely foreign hook. Output: $FOREIGN2_OUT"
fi

# ============================================================
# Test 10: Minor 1 - install_precommit_hook's own defense-in-depth guard
#          ("resolved pre-commit hook source does not exist" - the guard
#          that follows resolve_hook_src's call in install_precommit_hook)
#          is independently exercised, not merely reachable in theory.
#          resolve_hook_src's FALLBACK branches are unchecked (see the
#          manifest's corrected Public-API wording for resolve_hook_src),
#          so an ordinary (non-worktree) git repo with NO hooks/pre-commit
#          file at all is the only way to make resolve_hook_src return a
#          source path that genuinely does not exist, and this guard is
#          the only thing standing between that and installing a dangling
#          symlink.
# ============================================================

NO_HOOK_REPO="$TMP_ROOT/no-hook-repo"
mkdir -p "$NO_HOOK_REPO"
git init -q "$NO_HOOK_REPO"
git -C "$NO_HOOK_REPO" config user.email test@test.com
git -C "$NO_HOOK_REPO" config user.name test

if [[ ! -f "$NO_HOOK_REPO/hooks/pre-commit" ]]; then
  _pass "Test 10 setup: no-hook-repo fixture genuinely has no hooks/pre-commit file"
else
  _fail "Test 10 setup: unexpectedly found hooks/pre-commit (fixture setup bug)"
fi

NO_HOOK_SRC="$(resolve_hook_src "$NO_HOOK_REPO")"
if [[ "$NO_HOOK_SRC" == "$NO_HOOK_REPO/hooks/pre-commit" ]] && [[ ! -f "$NO_HOOK_SRC" ]]; then
  _pass "Test 10: resolve_hook_src returns the unchecked fallback path, and it genuinely does not exist (confirms the install-side guard is reachable, not dead code)"
else
  _fail "Test 10: resolve_hook_src returned an unexpected source for the no-hook fixture: $NO_HOOK_SRC"
fi

NO_HOOK_OUT="$(install_precommit_hook "$NO_HOOK_REPO" 2>&1)"
NO_HOOK_RC=$?

if [[ $NO_HOOK_RC -eq 0 ]]; then
  _pass "Test 10 (Minor 1): install_precommit_hook exits 0 when the resolved source does not exist"
else
  _fail "Test 10 (Minor 1): install_precommit_hook exited $NO_HOOK_RC instead of 0. Output: $NO_HOOK_OUT"
fi

if echo "$NO_HOOK_OUT" | grep -qi "resolved pre-commit hook source does not exist"; then
  _pass "Test 10 (Minor 1): prints the defense-in-depth skip message"
else
  _fail "Test 10 (Minor 1 regression): expected the defense-in-depth skip message. Output: $NO_HOOK_OUT"
fi

NO_HOOK_REAL_HOOKS_DIR="$(git -C "$NO_HOOK_REPO" rev-parse --git-path hooks)"
case "$NO_HOOK_REAL_HOOKS_DIR" in
  /*) : ;;
  *) NO_HOOK_REAL_HOOKS_DIR="$NO_HOOK_REPO/$NO_HOOK_REAL_HOOKS_DIR" ;;
esac
NO_HOOK_DST="$NO_HOOK_REAL_HOOKS_DIR/pre-commit"

if [[ ! -L "$NO_HOOK_DST" ]] && [[ ! -e "$NO_HOOK_DST" ]]; then
  _pass "Test 10 (Minor 1): no dangling symlink was created at $NO_HOOK_DST despite a missing source"
else
  _fail "Test 10 (Minor 1 regression): a symlink/file was created at $NO_HOOK_DST despite the resolved source not existing (-L=$([[ -L "$NO_HOOK_DST" ]] && echo true || echo false) -e=$([[ -e "$NO_HOOK_DST" ]] && echo true || echo false)). Output: $NO_HOOK_OUT"
fi

# ============================================================
# Test 11: Minor 3 - resolve_hook_src's fallback and
#          uninstall_precommit_hook's legacy_hook_src must agree on a
#          canonical spelling of repo_dir, not the raw caller-supplied
#          string. Installs from a bare-repo + worktree fixture (Test 8's
#          layout, where the fallback IS the installed target) using a
#          repo_dir spelled with a trailing slash, then uninstalls using
#          the canonical (no-trailing-slash) spelling of the SAME
#          directory. Pre-fix, the installed symlink target embeds the
#          trailing-slash spelling while uninstall recomputes both
#          candidates from the canonical spelling - neither matches, and
#          the hook is orphaned ("not ours, skipping"). Post-fix, both
#          calls canonicalize repo_dir first, so they agree regardless of
#          which spelling either caller used.
# ============================================================

CANON_SRC_REPO="$TMP_ROOT/canon-src-repo"
_make_fixture_repo "$CANON_SRC_REPO"

CANON_BARE_REPO="$TMP_ROOT/canon-bare-repo.git"
git clone -q --bare "$CANON_SRC_REPO" "$CANON_BARE_REPO" >/dev/null 2>&1

CANON_WT="$TMP_ROOT/canon-wt-branch"
git -C "$CANON_BARE_REPO" worktree add -q "$CANON_WT" -b canon-wt-test-branch >/dev/null 2>&1

# Install using a NON-canonical (trailing-slash) spelling of the worktree.
CANON_INSTALL_OUT="$(install_precommit_hook "$CANON_WT/" 2>&1)"
CANON_INSTALL_RC=$?

if [[ $CANON_INSTALL_RC -eq 0 ]]; then
  _pass "Test 11 (Minor 3) setup: install_precommit_hook exits 0 for the trailing-slash spelling"
else
  _fail "Test 11 (Minor 3) setup: install_precommit_hook exited $CANON_INSTALL_RC. Output: $CANON_INSTALL_OUT"
fi

CANON_HOOK_DST="$CANON_BARE_REPO/hooks/pre-commit"
if [[ -e "$CANON_HOOK_DST" ]]; then
  _pass "Test 11 (Minor 3) setup: hook installed at $CANON_HOOK_DST via the trailing-slash spelling"
else
  _fail "Test 11 (Minor 3) setup: expected a hook at $CANON_HOOK_DST after install. Output: $CANON_INSTALL_OUT"
fi

# Uninstall using the CANONICAL (no trailing slash) spelling of the SAME
# directory - this is the cross-spelling mismatch Minor 3 exercises.
CANON_UNINSTALL_OUT="$(uninstall_precommit_hook "$CANON_WT" 2>&1)"
CANON_UNINSTALL_RC=$?

if [[ $CANON_UNINSTALL_RC -eq 0 ]]; then
  _pass "Test 11 (Minor 3): uninstall_precommit_hook exits 0 across the spelling mismatch"
else
  _fail "Test 11 (Minor 3): uninstall_precommit_hook exited $CANON_UNINSTALL_RC. Output: $CANON_UNINSTALL_OUT"
fi

if [[ ! -e "$CANON_HOOK_DST" ]]; then
  _pass "Test 11 (Minor 3 fixed): hook installed via a trailing-slash repo_dir is correctly removed by uninstall using the canonical spelling"
else
  _fail "Test 11 (Minor 3 regression): hook installed via a trailing-slash repo_dir was left ORPHANED by uninstall using the canonical spelling - legacy_hook_src is not canonicalized consistently with the installed target. Output: $CANON_UNINSTALL_OUT"
fi

# ============================================================
# Test 12: Major 1 - uninstall's legacy candidate must match a hook
#          installed under a NON-CANONICAL repo_dir spelling (reached
#          through a symlinked PARENT directory), not just the canonical
#          spelling. Pre-this-fix, legacy_hook_src was built AFTER repo_dir
#          had already been overwritten with its canonicalized form, so
#          the raw spelling was lost entirely by the time the legacy
#          candidate string was assembled - a legacy hook installed under
#          the raw spelling (exactly what pre-this-PR, non-canonicalizing
#          code would have done) then matched neither the resolved target
#          nor the legacy candidate, and was orphaned.
# ============================================================

MAJOR1_REAL_PARENT="$TMP_ROOT/major1-real-parent"
mkdir -p "$MAJOR1_REAL_PARENT"
MAJOR1_REPO="$MAJOR1_REAL_PARENT/repo"
_make_fixture_repo "$MAJOR1_REPO"

MAJOR1_SYMLINK_PARENT="$TMP_ROOT/major1-symlinked-parent"
ln -s "$MAJOR1_REAL_PARENT" "$MAJOR1_SYMLINK_PARENT"

# Non-canonical spelling of the SAME repo, reached through the symlinked
# parent directory.
MAJOR1_RAW_REPO_DIR="$MAJOR1_SYMLINK_PARENT/repo"

if [[ "$MAJOR1_RAW_REPO_DIR" != "$MAJOR1_REPO" ]]; then
  _pass "Test 12 setup: raw (symlinked-parent) and canonical repo_dir spellings genuinely differ as strings"
else
  _fail "Test 12 setup: raw and canonical spellings are string-identical - fixture does not exercise the bug"
fi

MAJOR1_HOOKS_DIR="$MAJOR1_REPO/.git/hooks"
mkdir -p "$MAJOR1_HOOKS_DIR"
MAJOR1_HOOK_DST="$MAJOR1_HOOKS_DIR/pre-commit"

# Simulate a hook installed by legacy (pre-this-PR, non-canonicalizing)
# code: the symlink target is built directly from the RAW spelling passed
# in, with no canonicalization step at all.
ln -s "$MAJOR1_RAW_REPO_DIR/hooks/pre-commit" "$MAJOR1_HOOK_DST"

MAJOR1_OUT="$(uninstall_precommit_hook "$MAJOR1_RAW_REPO_DIR" 2>&1)"
MAJOR1_RC=$?

if [[ $MAJOR1_RC -eq 0 ]]; then
  _pass "Test 12 (Major 1): uninstall_precommit_hook exits 0 for a legacy hook installed under a non-canonical spelling"
else
  _fail "Test 12 (Major 1): uninstall_precommit_hook exited $MAJOR1_RC. Output: $MAJOR1_OUT"
fi

if [[ ! -e "$MAJOR1_HOOK_DST" ]]; then
  _pass "Test 12 (Major 1 fixed): legacy hook installed under a non-canonical (symlinked-parent) spelling is removed by uninstall"
else
  _fail "Test 12 (Major 1 regression): legacy hook installed under a non-canonical spelling was left ORPHANED by uninstall - the legacy candidate must match both the raw and the canonical repo_dir spellings. Output: $MAJOR1_OUT"
fi

# ---- Results ----

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
