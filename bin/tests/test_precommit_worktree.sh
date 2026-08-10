#!/usr/bin/env bash
# DS-152 round 2 (Major 1 sandbox hazard) - this MUST be the first
# executable statement in the file, before REPO_DIR or anything else is
# resolved. If GIT_DIR (in particular) is set in the invoking environment,
# git IGNORES `-C <dir>` entirely for every `git -C <dir> rev-parse ...`
# call - both in this suite's own fixture setup and in the
# scripts/lib/precommit.sh functions under test - and resolves against the
# AMBIENT GIT_DIR instead of the intended fixture repo. Demonstrated: a
# caller exporting GIT_DIR before invoking this script caused
# install_precommit_hook to write a pre-commit symlink into the REAL
# repo's ambient hooks dir (not a fixture), with 12/27 assertions then
# failing on top of that corruption. Clearing these before any other line
# runs defeats that class of leak outright.
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_CEILING_DIRECTORIES
# DS-152 round 3 (Minor - hostile global git config): a global
# `core.hooksPath` collapses every fixture's hooks dir onto one directory
# (`git rev-parse --git-path hooks` honours it, and it is not one of the
# GIT_* env vars unset above). GIT_CONFIG_GLOBAL/GIT_CONFIG_SYSTEM point git
# at /dev/null instead of the operator's real global/system config for
# every git invocation in this process, neutralising the vector - same
# pattern already used by bin/tests/test_agentic_tracker.py and
# bin/tests/lib/git_fixture.py.
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null
# Purpose: Regression test for scripts/lib/precommit.sh's install_precommit_hook
#          and uninstall_precommit_hook. Ensures both resolve the REAL git
#          hooks directory (via `git rev-parse --git-path hooks`) instead of
#          the hardcoded "$REPO_DIR/.git/hooks", which breaks when REPO_DIR is
#          a git worktree - there ".git" is a FILE (a gitdir pointer), not a
#          directory, so a plain `ln -s`/`rm` against
#          "$REPO_DIR/.git/hooks/..." fails or silently no-ops (DS-58, both
#          the install side and the symmetric uninstall side). Also covers
#          DS-152: install_precommit_hook must source the hook BODY from the
#          durable PRIMARY checkout, never from whichever worktree repo_dir
#          happens to be, so an ephemeral/scratch worktree's removal can
#          never dangle the ONE shared hook every worktree of a repo uses.
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
#   This test re-creates worktree fixtures for both sides to prevent
#   regression.
#   - DS-152: install_precommit_hook always symlinks the shared hooks dir
#     at the PRIMARY checkout's hooks/pre-commit, even when invoked with an
#     ephemeral worktree as repo_dir - so removing that worktree afterward
#     can never dangle the shared hook. Tests 2 and 3 below assert against
#     the primary checkout's hook_src (not repo_dir's) to reflect this: DS-58
#     only ever needed the DESTINATION (the real, shared hooks dir) resolved
#     correctly and a working, non-"Not a directory" symlink installed -
#     which worktree's own copy of hooks/pre-commit happened to be the
#     SOURCE was an incidental implementation detail of DS-58, not part of
#     what it was fixing. Test 6 covers the DS-152 scratch-worktree-removal
#     scenario directly.
#   - DS-152 round 2 (Skeptic findings):
#     Major 1 (sandbox hazard): the leading `unset GIT_DIR ...` line above,
#     plus Test 0 below asserting those vars are actually empty, plus
#     wrapping the whole suite in bin/tests/lib/precommit-hook-guard.sh's
#     save/restore (defense in depth - restores the REAL repo's hook if
#     anything still slips through). Verified by re-running this suite with
#     GIT_DIR exported before invocation; see the fix commit message for the
#     transcript.
#     Major 2 (missing hook_src is now reachable): Test 8 asserts
#     install_precommit_hook refuses to create a dangling symlink when the
#     primary checkout's own hooks/pre-commit does not exist, and warns
#     loudly rather than silently succeeding.
#     Minor (silent primary-checkout fallback): Test 9 asserts a loud
#     warning fires when resolve_primary_checkout fails and
#     install_precommit_hook falls back to repo_dir directly.
#     Minor (uninstall ownership too narrow for legacy targets): Test 10
#     asserts uninstall_precommit_hook still removes a hook that was
#     installed by pre-DS-152 code pointing at a worktree's own
#     hooks/pre-commit rather than the primary checkout's.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$REPO_DIR/scripts/lib/precommit.sh"
GUARD="$REPO_DIR/bin/tests/lib/precommit-hook-guard.sh"

if [[ ! -f "$LIB" ]]; then
  echo "FAIL: $LIB not found" >&2
  exit 1
fi
if [[ ! -f "$GUARD" ]]; then
  echo "FAIL: $GUARD not found" >&2
  exit 1
fi

# shellcheck source=scripts/lib/precommit.sh
. "$LIB"
# shellcheck source=bin/tests/lib/precommit-hook-guard.sh
. "$GUARD"

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

# ------------------------------------------------------------------
# DS-152 round 2 (Major 1): save the REAL repo's pre-commit hook slot
# before ANY fixture is created and restore it unconditionally on exit -
# defense in depth alongside the leading `unset GIT_DIR ...` above. Even if
# some future change to this suite (or an ambient git env var this file did
# not anticipate) causes a library call to resolve against REPO_DIR instead
# of a fixture, the real hook is protected and restored. This is the same
# guard used by the four suites that invoke a REAL install.sh/uninstall.sh
# against this live checkout (bin/tests/test_uninstall_ds_prefix.sh,
# bin/tests/test_hooks_snapshot_migration.sh,
# bin/tests/test_local_bin_ds_prefix_install.sh,
# .claude/tests/install-converge.test.sh) - do not hand-roll a second,
# weaker guard beside it.
# ------------------------------------------------------------------
precommit_hook_guard_save "$REPO_DIR"

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  [[ -n "${TMP_ROOT:-}" && -d "$TMP_ROOT" ]] && rm -rf "$TMP_ROOT"
  precommit_hook_guard_restore
}
trap _cleanup EXIT

# ============================================================
# Test 0: DS-152 round 2 (Major 1) - the leaked-git-env-var sandbox hazard
#         is actually neutralised, not merely documented.
# ============================================================

if [[ -z "${GIT_DIR:-}" && -z "${GIT_WORK_TREE:-}" && -z "${GIT_COMMON_DIR:-}" \
      && -z "${GIT_INDEX_FILE:-}" && -z "${GIT_OBJECT_DIRECTORY:-}" \
      && -z "${GIT_ALTERNATE_OBJECT_DIRECTORIES:-}" && -z "${GIT_CEILING_DIRECTORIES:-}" ]]; then
  _pass "sandbox isolation: no leaked GIT_* environment overrides are set"
else
  _fail "sandbox isolation: a GIT_* environment override survived the leading unset (GIT_DIR=${GIT_DIR:-<unset>})"
fi

# ------------------------------------------------------------------
# Sandbox-isolation guarantee: every fixture below lives under a fresh
# `mktemp -d` directory (TMP_ROOT), never under $REPO_DIR (this real
# checkout's own .git/hooks are never touched, by construction - fixture
# repos are `git init`-ed from scratch and are their own independent
# repositories with their own independent .git dirs). Assert TMP_ROOT is
# genuinely outside REPO_DIR before creating any fixture, so a future
# change to the mktemp call cannot silently reintroduce the "fakes $HOME
# but not git --git-path hooks, escapes its sandbox" hazard recorded for
# this class of test. This is a PATH check only - it does not by itself
# guard against a leaked GIT_DIR (which ignores -C entirely regardless of
# path); that hazard is handled by the unset + guard above.
# ------------------------------------------------------------------
case "$TMP_ROOT" in
  "$REPO_DIR"/*|"$REPO_DIR")
    echo "FAIL: TMP_ROOT ($TMP_ROOT) is inside REPO_DIR ($REPO_DIR) - refusing to run, this would risk touching the real repo's .git/hooks" >&2
    exit 1
    ;;
esac
_pass "sandbox isolation: TMP_ROOT ($TMP_ROOT) is outside REPO_DIR ($REPO_DIR)"

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
# -ef (same-inode) rather than a literal string match: the primary-checkout
# resolution canonicalises repo_dir (`pwd -P`), so on a host where TMPDIR
# itself is a symlink (e.g. macOS /var/folders -> /private/var/folders) the
# resolved hook_src legitimately differs, byte-for-byte, from the literal
# $NORMAL_REPO string while still pointing at the exact same file.
if [[ -L "$NORMAL_HOOK_DST" ]] && [[ "$NORMAL_HOOK_DST" -ef "$NORMAL_REPO/hooks/pre-commit" ]]; then
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

# DS-152: source is the PRIMARY checkout (WT_MAIN), not the invoking
# worktree (WT_BRANCH) - see the file header note above. -ef (same-inode)
# rather than a literal string match, for the same TMPDIR-symlink reason as
# Test 1's NORMAL_HOOK_DST assertion.
if [[ -L "$WT_HOOK_DST" ]] && [[ "$WT_HOOK_DST" -ef "$WT_MAIN/hooks/pre-commit" ]]; then
  _pass "worktree case: pre-commit symlink installed at real hooks dir, sourced from primary checkout ($WT_HOOK_DST)"
else
  _fail "worktree case: pre-commit symlink not found/correct at $WT_HOOK_DST. Output: $OUT"
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

# DS-152: source is the PRIMARY checkout (UNINSTALL_WT_MAIN), not the
# invoking worktree (UNINSTALL_WT_BRANCH) - see the file header note above.
# -ef (same-inode) for the same TMPDIR-symlink reason as Test 1/2 above.
if [[ -L "$UNINSTALL_HOOK_DST" ]] && [[ "$UNINSTALL_HOOK_DST" -ef "$UNINSTALL_WT_MAIN/hooks/pre-commit" ]]; then
  _pass "uninstall setup: pre-commit hook installed at real hooks dir before uninstall test"
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

# `! -e` alone follows symlinks and would false-pass on a dangling
# leftover symlink (target gone, link itself still present) - assert
# `! -L` too so a botched removal that leaves a dangling symlink is caught.
if [[ ! -e "$UNINSTALL_HOOK_DST" ]] && [[ ! -L "$UNINSTALL_HOOK_DST" ]]; then
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
# Test 6: DS-152 - installing FROM an ephemeral scratch worktree must not
#         dangle the shared hook once that worktree is removed. This is the
#         direct regression test for the bug: running install.sh with
#         repo_dir pointed at a soon-to-be-deleted worktree (e.g. a Skeptic
#         QA-regression scratch dir) must symlink the shared hook at the
#         durable PRIMARY checkout's hooks/pre-commit, not at the scratch
#         worktree's own copy.
# ============================================================

SCRATCH_MAIN="$TMP_ROOT/scratch-main-repo"
_make_fixture_repo "$SCRATCH_MAIN"

SCRATCH_WT="$TMP_ROOT/scratch-wt"
git -C "$SCRATCH_MAIN" worktree add -q "$SCRATCH_WT" -b scratch-wt-test-branch >/dev/null 2>&1

# Install run directly from the scratch worktree - simulates an install.sh
# invocation whose repo_dir happens to be the ephemeral worktree, with no
# prior install having run from the primary checkout first.
OUT="$(install_precommit_hook "$SCRATCH_WT" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "scratch-worktree case: install_precommit_hook exits 0"
else
  _fail "scratch-worktree case: install_precommit_hook exited $RC. Output: $OUT"
fi

SCRATCH_REAL_HOOKS_DIR="$(git -C "$SCRATCH_WT" rev-parse --git-path hooks)"
case "$SCRATCH_REAL_HOOKS_DIR" in
  /*) : ;;
  *) SCRATCH_REAL_HOOKS_DIR="$SCRATCH_WT/$SCRATCH_REAL_HOOKS_DIR" ;;
esac
SCRATCH_HOOK_DST="$SCRATCH_REAL_HOOKS_DIR/pre-commit"

# -ef (same-inode) rather than a literal string match, for the same
# TMPDIR-symlink reason as Test 1/2/3 above.
if [[ -L "$SCRATCH_HOOK_DST" ]] && [[ "$SCRATCH_HOOK_DST" -ef "$SCRATCH_MAIN/hooks/pre-commit" ]]; then
  _pass "scratch-worktree case (DS-152): shared hook sourced from the primary checkout, not the scratch worktree"
else
  _fail "scratch-worktree case (DS-152 regression): shared hook not sourced from primary checkout ($SCRATCH_MAIN/hooks/pre-commit); got $(readlink "$SCRATCH_HOOK_DST" 2>&1). Output: $OUT"
fi

# Now delete the scratch worktree entirely, exactly as the Skeptic
# QA-regression protocol would after a scratch session ends.
git -C "$SCRATCH_MAIN" worktree remove --force "$SCRATCH_WT" >/dev/null 2>&1

if [[ -e "$SCRATCH_HOOK_DST" ]]; then
  _pass "scratch-worktree case (DS-152): shared hook still resolves after the scratch worktree is removed (not dangling)"
else
  _fail "scratch-worktree case (DS-152 regression): shared hook is DANGLING after scratch worktree removal - readlink: $(readlink "$SCRATCH_HOOK_DST" 2>&1)"
fi

# Re-running install from the (now-durable, still-present) primary checkout
# must report the hook as already correctly linked - no re-point needed.
OUT="$(install_precommit_hook "$SCRATCH_MAIN" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]] && echo "$OUT" | grep -qi "already linked"; then
  _pass "scratch-worktree case (DS-152): re-running install from the primary checkout reports the hook already linked"
else
  _fail "scratch-worktree case (DS-152 regression): re-running install from the primary checkout did not report already-linked. Output: $OUT"
fi

# ============================================================
# Test 7: DS-152 - a dangling hook target is warned about loudly
# ============================================================

DANGLE_MAIN="$TMP_ROOT/dangle-main-repo"
_make_fixture_repo "$DANGLE_MAIN"

DANGLE_REAL_HOOKS_DIR="$(git -C "$DANGLE_MAIN" rev-parse --git-path hooks)"
case "$DANGLE_REAL_HOOKS_DIR" in
  /*) : ;;
  *) DANGLE_REAL_HOOKS_DIR="$DANGLE_MAIN/$DANGLE_REAL_HOOKS_DIR" ;;
esac
DANGLE_HOOK_DST="$DANGLE_REAL_HOOKS_DIR/pre-commit"

# Hand-craft a dangling symlink whose target string contains a DinoStack
# path component (so a real _ae_is_ours reclaims it) but the target itself
# is gone - simulating the exact post-cleanup state the bug report
# describes. The module-level _ae_is_ours stub (see top of file) always
# returns "not ours" by design for the other tests above; temporarily
# override it here to match the real per-adapter predicate's actual
# broken-symlink-reclaim behaviour (see .claude/install.sh _ae_is_ours),
# then restore the stub so later tests are unaffected.
mkdir -p "$DANGLE_REAL_HOOKS_DIR"
ln -s "$TMP_ROOT/gone-DinoStack/hooks/pre-commit" "$DANGLE_HOOK_DST"

_ae_is_ours() {
  local dst="$1"
  [[ -L "$dst" ]] || return 1
  local current_target
  current_target="$(readlink "$dst")"
  [[ "$current_target" == */DinoStack/* || "$current_target" == *-DinoStack/* ]] && return 0
  return 1
}

OUT="$(install_precommit_hook "$DANGLE_MAIN" 2>&1)"
RC=$?

_ae_is_ours() {
  return 1
}

if [[ $RC -eq 0 ]]; then
  _pass "dangling-hook case: install_precommit_hook exits 0"
else
  _fail "dangling-hook case: install_precommit_hook exited $RC. Output: $OUT"
fi

if echo "$OUT" | grep -qi "dangling"; then
  _pass "dangling-hook case (DS-152): dangling target is warned about loudly"
else
  _fail "dangling-hook case (DS-152 regression): no loud warning about the dangling hook target. Output: $OUT"
fi

if [[ -L "$DANGLE_HOOK_DST" ]] && [[ "$DANGLE_HOOK_DST" -ef "$DANGLE_MAIN/hooks/pre-commit" ]]; then
  _pass "dangling-hook case (DS-152): dangling hook repaired to point at the primary checkout"
else
  _fail "dangling-hook case (DS-152 regression): dangling hook not repaired. Output: $OUT"
fi

# ============================================================
# Test 8: DS-152 round 2 (Major 2) - install must refuse to create a NEW
#         dangling symlink when the primary checkout's own hooks/pre-commit
#         does not exist (a pruned/moved primary checkout, or one checked
#         out to a commit without hooks/pre-commit). Pre-DS-152 this state
#         was unreachable, because the source was always the invoking
#         checkout itself, which necessarily existed.
# ============================================================

MISSING_SRC_MAIN="$TMP_ROOT/missing-src-main-repo"
_make_fixture_repo "$MISSING_SRC_MAIN"
# Remove the primary checkout's own hooks/pre-commit AFTER the fixture repo
# is committed (so it is still a valid git repo, just missing this one
# tracked-but-now-deleted-on-disk file) - simulates a primary checkout that
# was moved/pruned or checked out to a commit predating hooks/pre-commit.
rm -f "$MISSING_SRC_MAIN/hooks/pre-commit"

MISSING_SRC_HOOKS_DIR="$(git -C "$MISSING_SRC_MAIN" rev-parse --git-path hooks)"
case "$MISSING_SRC_HOOKS_DIR" in
  /*) : ;;
  *) MISSING_SRC_HOOKS_DIR="$MISSING_SRC_MAIN/$MISSING_SRC_HOOKS_DIR" ;;
esac
MISSING_SRC_HOOK_DST="$MISSING_SRC_HOOKS_DIR/pre-commit"

OUT="$(install_precommit_hook "$MISSING_SRC_MAIN" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "missing-source case: install_precommit_hook exits 0 (non-fatal)"
else
  _fail "missing-source case: install_precommit_hook exited $RC. Output: $OUT"
fi

if echo "$OUT" | grep -qi "hook source is missing"; then
  _pass "missing-source case (DS-152 round 2, Major 2): loud warning printed for a missing hook_src"
else
  _fail "missing-source case (DS-152 round 2 regression, Major 2): no loud warning for a missing hook_src. Output: $OUT"
fi

# `! -e` alone follows symlinks and would false-pass if a dangling symlink
# were created instead of no symlink at all - assert `! -L` too.
if [[ ! -e "$MISSING_SRC_HOOK_DST" ]] && [[ ! -L "$MISSING_SRC_HOOK_DST" ]]; then
  _pass "missing-source case (DS-152 round 2, Major 2): no NEW dangling symlink was created"
else
  _fail "missing-source case (DS-152 round 2 regression, Major 2): a dangling symlink was created at $MISSING_SRC_HOOK_DST despite a missing source"
fi

# Symmetric sub-case: a re-point (via _ae_is_ours) onto a missing source
# must also refuse, leaving the existing (foreign-checkout) symlink intact.
MISSING_SRC_REPOINT_MAIN="$TMP_ROOT/missing-src-repoint-main-repo"
_make_fixture_repo "$MISSING_SRC_REPOINT_MAIN"
rm -f "$MISSING_SRC_REPOINT_MAIN/hooks/pre-commit"

MISSING_SRC_REPOINT_HOOKS_DIR="$(git -C "$MISSING_SRC_REPOINT_MAIN" rev-parse --git-path hooks)"
case "$MISSING_SRC_REPOINT_HOOKS_DIR" in
  /*) : ;;
  *) MISSING_SRC_REPOINT_HOOKS_DIR="$MISSING_SRC_REPOINT_MAIN/$MISSING_SRC_REPOINT_HOOKS_DIR" ;;
esac
MISSING_SRC_REPOINT_HOOK_DST="$MISSING_SRC_REPOINT_HOOKS_DIR/pre-commit"

mkdir -p "$MISSING_SRC_REPOINT_HOOKS_DIR"
ln -s "$TMP_ROOT/gone-DinoStack/hooks/pre-commit" "$MISSING_SRC_REPOINT_HOOK_DST"

_ae_is_ours() {
  local dst="$1"
  [[ -L "$dst" ]] || return 1
  local current_target
  current_target="$(readlink "$dst")"
  [[ "$current_target" == */DinoStack/* || "$current_target" == *-DinoStack/* ]] && return 0
  return 1
}

OUT="$(install_precommit_hook "$MISSING_SRC_REPOINT_MAIN" 2>&1)"
RC=$?

_ae_is_ours() {
  return 1
}

if echo "$OUT" | grep -qi "hook source is missing"; then
  _pass "missing-source re-point case (DS-152 round 2, Major 2): loud warning printed instead of re-pointing onto a missing source"
else
  _fail "missing-source re-point case (DS-152 round 2 regression, Major 2): no loud warning for a missing hook_src during a re-point. Output: $OUT"
fi

if [[ -L "$MISSING_SRC_REPOINT_HOOK_DST" ]] && [[ "$(readlink "$MISSING_SRC_REPOINT_HOOK_DST")" == "$TMP_ROOT/gone-DinoStack/hooks/pre-commit" ]]; then
  _pass "missing-source re-point case (DS-152 round 2, Major 2): existing symlink left untouched rather than re-pointed onto a missing source"
else
  _fail "missing-source re-point case (DS-152 round 2 regression, Major 2): existing symlink was altered despite the intended re-point target missing"
fi

# ============================================================
# Test 9: DS-152 round 2 (Minor) - a silent fallback to repo_dir when
#         resolve_primary_checkout fails must warn loudly, not just be
#         documented in a comment.
# ============================================================

# A STANDALONE --separate-git-dir checkout (no worktrees added from it) is
# NOT the failure case: --git-dir == --git-common-dir there (both point at
# the relocated gitdir), so resolve_primary_checkout correctly takes its
# "not a linked worktree" branch and repo_dir is authoritative - no
# fallback needed. The measured failure (per Skeptic round 2) requires a
# LINKED WORKTREE of a --separate-git-dir primary: --git-common-dir then
# resolves to the relocated gitdir path, which does not end in a literal
# "/.git" path component the way a normal-worktree's common-dir always
# does, so resolve_primary_checkout's suffix-strip fails (rc=1).
SEPARATE_GITDIR_ROOT="$TMP_ROOT/separate-gitdir-root"
SEPARATE_GITDIR_ACTUAL="$TMP_ROOT/separate-gitdir-actual-dotgit"
mkdir -p "$SEPARATE_GITDIR_ROOT/hooks"
git init -q --separate-git-dir="$SEPARATE_GITDIR_ACTUAL" "$SEPARATE_GITDIR_ROOT"
git -C "$SEPARATE_GITDIR_ROOT" config user.email test@test.com
git -C "$SEPARATE_GITDIR_ROOT" config user.name test
printf '#!/usr/bin/env bash\necho fixture pre-commit\n' > "$SEPARATE_GITDIR_ROOT/hooks/pre-commit"
chmod +x "$SEPARATE_GITDIR_ROOT/hooks/pre-commit"
git -C "$SEPARATE_GITDIR_ROOT" add hooks/pre-commit
git -C "$SEPARATE_GITDIR_ROOT" commit -q -m "fixture: add pre-commit hook"

SEPARATE_GITDIR_WT="$TMP_ROOT/separate-gitdir-wt"
git -C "$SEPARATE_GITDIR_ROOT" worktree add -q "$SEPARATE_GITDIR_WT" -b separate-gitdir-wt-branch >/dev/null 2>&1

OUT="$(install_precommit_hook "$SEPARATE_GITDIR_WT" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "separate-git-dir case: install_precommit_hook exits 0 (non-fatal)"
else
  _fail "separate-git-dir case: install_precommit_hook exited $RC. Output: $OUT"
fi

if echo "$OUT" | grep -qi "could not resolve the primary checkout"; then
  _pass "separate-git-dir case (DS-152 round 2, Minor): loud warning printed for the silent primary-checkout fallback"
else
  _fail "separate-git-dir case (DS-152 round 2 regression, Minor): resolve_primary_checkout fell back to repo_dir with no warning. Output: $OUT"
fi

# ============================================================
# Test 9b: DS-152 round 3 (bare-repo coverage gap) - a linked worktree of a
#          BARE primary repo hits the same resolve_primary_checkout failure
#          mode as Test 9's --separate-git-dir case (a common-dir that does
#          not end in a literal "/.git" path component), but via a
#          different git construct. The header's failure-modes block claims
#          this was "measured for --separate-git-dir AND bare linked
#          worktrees" - this test makes that claim true instead of aspirational.
# ============================================================

BARE_SOURCE="$TMP_ROOT/bare-source-repo"
_make_fixture_repo "$BARE_SOURCE"

BARE_MAIN="$TMP_ROOT/bare-main-repo.git"
git clone -q --bare "$BARE_SOURCE" "$BARE_MAIN" >/dev/null 2>&1

BARE_WT="$TMP_ROOT/bare-wt"
git -C "$BARE_MAIN" worktree add -q "$BARE_WT" -b bare-wt-test-branch >/dev/null 2>&1

OUT="$(install_precommit_hook "$BARE_WT" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "bare-repo case: install_precommit_hook exits 0 (non-fatal)"
else
  _fail "bare-repo case: install_precommit_hook exited $RC. Output: $OUT"
fi

if echo "$OUT" | grep -qi "could not resolve the primary checkout"; then
  _pass "bare-repo case (DS-152 round 3, bare-repo coverage gap): loud warning printed for the silent primary-checkout fallback"
else
  _fail "bare-repo case (DS-152 round 3 regression, bare-repo coverage gap): resolve_primary_checkout fell back to repo_dir with no warning. Output: $OUT"
fi

# Falls back to repo_dir's own hooks/pre-commit (BARE_WT's own copy, which
# `git worktree add` checks out from the bare repo's committed tree) and
# still installs successfully rather than aborting.
BARE_HOOKS_DIR="$(git -C "$BARE_WT" rev-parse --git-path hooks)"
case "$BARE_HOOKS_DIR" in
  /*) : ;;
  *) BARE_HOOKS_DIR="$BARE_WT/$BARE_HOOKS_DIR" ;;
esac
BARE_HOOK_DST="$BARE_HOOKS_DIR/pre-commit"

if [[ -L "$BARE_HOOK_DST" ]] && [[ "$BARE_HOOK_DST" -ef "$BARE_WT/hooks/pre-commit" ]]; then
  _pass "bare-repo case (DS-152 round 3, bare-repo coverage gap): falls back to repo_dir's own hooks/pre-commit and installs"
else
  _fail "bare-repo case (DS-152 round 3 regression, bare-repo coverage gap): fallback install did not land at repo_dir's own hooks/pre-commit. Output: $OUT"
fi

# ============================================================
# Test 10: DS-152 round 2 (Minor) - uninstall must still remove a hook that
#          was installed by PRE-DS-152 code pointing at a worktree's own
#          hooks/pre-commit, not the primary checkout's.
# ============================================================

LEGACY_MAIN="$TMP_ROOT/legacy-main-repo"
_make_fixture_repo "$LEGACY_MAIN"

LEGACY_WT="$TMP_ROOT/legacy-wt"
git -C "$LEGACY_MAIN" worktree add -q "$LEGACY_WT" -b legacy-wt-test-branch >/dev/null 2>&1

LEGACY_HOOKS_DIR="$(git -C "$LEGACY_WT" rev-parse --git-path hooks)"
case "$LEGACY_HOOKS_DIR" in
  /*) : ;;
  *) LEGACY_HOOKS_DIR="$LEGACY_WT/$LEGACY_HOOKS_DIR" ;;
esac
LEGACY_HOOK_DST="$LEGACY_HOOKS_DIR/pre-commit"

# Hand-craft the PRE-DS-152 install shape: the shared hook symlinked
# directly at the WORKTREE's own hooks/pre-commit (what
# `hook_src="$repo_dir/hooks/pre-commit"` would have written), not the
# primary checkout's.
mkdir -p "$LEGACY_HOOKS_DIR"
ln -s "$LEGACY_WT/hooks/pre-commit" "$LEGACY_HOOK_DST"

OUT="$(uninstall_precommit_hook "$LEGACY_WT" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "legacy-target uninstall case: uninstall_precommit_hook exits 0"
else
  _fail "legacy-target uninstall case: uninstall_precommit_hook exited $RC. Output: $OUT"
fi

# `! -e` alone follows symlinks and would false-pass on a dangling
# leftover symlink - assert `! -L` too.
if [[ ! -e "$LEGACY_HOOK_DST" ]] && [[ ! -L "$LEGACY_HOOK_DST" ]]; then
  _pass "legacy-target uninstall case (DS-152 round 2, Minor): pre-DS-152 worktree-targeted hook actually removed"
else
  _fail "legacy-target uninstall case (DS-152 round 2 regression, Minor): pre-DS-152 hook still present at $LEGACY_HOOK_DST, current target: $(readlink "$LEGACY_HOOK_DST" 2>&1). Output: $OUT"
fi

if echo "$OUT" | grep -qi "not ours"; then
  _fail "legacy-target uninstall case (DS-152 round 2 regression, Minor): reported 'not ours' despite the target being a legacy sibling worktree hook. Output: $OUT"
else
  _pass "legacy-target uninstall case (DS-152 round 2, Minor): did not falsely report 'not ours'"
fi

# ============================================================
# Test 11: DS-152 round 3 (Major) - _pc_git_common_dir_abs must canonicalise,
#          not just concatenate. Test 10 above only exercises the WORKTREE
#          invocation of uninstall (both the calling repo_dir AND the legacy
#          target are worktrees), which - even pre-fix - takes git's own
#          already-canonical --git-common-dir output on both sides and so
#          cannot redden this bug. The measured failure requires the
#          PRIMARY-checkout invocation: repo_common_dir is computed from the
#          non-worktree branch (pre-fix: raw string concatenation of
#          repo_dir + ".git", NOT canonicalised) while target_common_dir (a
#          worktree) is computed from git's own canonical
#          --git-common-dir output - these differ whenever TMPDIR/HOME has a
#          symlinked component (e.g. macOS's
#          /var/folders -> /private/var/folders), and
#          _pc_is_legacy_sibling_hook silently returns false, leaving the
#          hook in place. This test targets that exact invocation shape.
# ============================================================

PRIMARY_INVOKE_MAIN="$TMP_ROOT/primary-invoke-main-repo"
_make_fixture_repo "$PRIMARY_INVOKE_MAIN"

PRIMARY_INVOKE_WT="$TMP_ROOT/primary-invoke-wt"
git -C "$PRIMARY_INVOKE_MAIN" worktree add -q "$PRIMARY_INVOKE_WT" -b primary-invoke-wt-test-branch >/dev/null 2>&1

# The shared hooks dir is common to both the primary checkout and its
# worktree - resolve it from either side.
PRIMARY_INVOKE_HOOKS_DIR="$(git -C "$PRIMARY_INVOKE_MAIN" rev-parse --git-path hooks)"
case "$PRIMARY_INVOKE_HOOKS_DIR" in
  /*) : ;;
  *) PRIMARY_INVOKE_HOOKS_DIR="$PRIMARY_INVOKE_MAIN/$PRIMARY_INVOKE_HOOKS_DIR" ;;
esac
PRIMARY_INVOKE_HOOK_DST="$PRIMARY_INVOKE_HOOKS_DIR/pre-commit"

# Hand-craft the PRE-DS-152 install shape at the shared hooks dir: symlinked
# at the WORKTREE's own hooks/pre-commit, exactly as Test 10 does, but this
# time the removal call below targets the PRIMARY checkout, not the
# worktree.
mkdir -p "$PRIMARY_INVOKE_HOOKS_DIR"
ln -s "$PRIMARY_INVOKE_WT/hooks/pre-commit" "$PRIMARY_INVOKE_HOOK_DST"

OUT="$(uninstall_precommit_hook "$PRIMARY_INVOKE_MAIN" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "primary-checkout-invocation legacy-target case (DS-152 round 3, Major): uninstall_precommit_hook exits 0"
else
  _fail "primary-checkout-invocation legacy-target case (DS-152 round 3, Major): uninstall_precommit_hook exited $RC. Output: $OUT"
fi

# `! -e` alone follows symlinks and would false-pass on a dangling leftover
# symlink - assert `! -L` too.
if [[ ! -e "$PRIMARY_INVOKE_HOOK_DST" ]] && [[ ! -L "$PRIMARY_INVOKE_HOOK_DST" ]]; then
  _pass "primary-checkout-invocation legacy-target case (DS-152 round 3, Major): legacy sibling hook removed when uninstall is invoked from the PRIMARY checkout"
else
  _fail "primary-checkout-invocation legacy-target case (DS-152 round 3 regression, Major): legacy sibling hook still present at $PRIMARY_INVOKE_HOOK_DST when uninstall was invoked from the primary checkout (this is the _pc_git_common_dir_abs canonicalisation bug), current target: $(readlink "$PRIMARY_INVOKE_HOOK_DST" 2>&1). Output: $OUT"
fi

# ============================================================
# Test 12: DS-152 round 3 (dangling-legacy-target-can-never-be-cleaned) - a
#          legacy hook whose target worktree has ALREADY BEEN DELETED must
#          still be removable, provided it lies under the repo's own known
#          worktree roots (.claude/worktrees/ or .agentic/worktrees/).
# ============================================================

DANGLE_LEGACY_MAIN="$TMP_ROOT/dangle-legacy-main-repo"
_make_fixture_repo "$DANGLE_LEGACY_MAIN"

DANGLE_LEGACY_HOOKS_DIR="$(git -C "$DANGLE_LEGACY_MAIN" rev-parse --git-path hooks)"
case "$DANGLE_LEGACY_HOOKS_DIR" in
  /*) : ;;
  *) DANGLE_LEGACY_HOOKS_DIR="$DANGLE_LEGACY_MAIN/$DANGLE_LEGACY_HOOKS_DIR" ;;
esac
DANGLE_LEGACY_HOOK_DST="$DANGLE_LEGACY_HOOKS_DIR/pre-commit"

# DS-152 round 4 (Major, was relocated here in round 3): the dangling
# target's path is built from the RAW $DANGLE_LEGACY_MAIN string (as
# `.claude/install.sh`'s pre-fix `REPO_DIR="$(cd ... && pwd)"` - logical
# pwd, NOT `pwd -P` - would actually have spelled it for any checkout
# reached through a symlinked component), NOT a pre-canonicalised form. This
# is the shape the defect lives in: on a symlinked TMPDIR/HOME (e.g. macOS's
# /var/folders -> /private/var/folders) this raw spelling differs, on disk,
# from `primary_checkout`'s canonical form even though both name the exact
# same real directory. A fixture built from the canonical form (round 3's
# shape) cannot exercise this - see _pc_canonicalize_missing_dir below for
# the fix that makes comparing these two spellings actually work.
DANGLE_LEGACY_TARGET_DIR="$DANGLE_LEGACY_MAIN/.claude/worktrees/agent-deleted-example"
mkdir -p "$DANGLE_LEGACY_HOOKS_DIR"
ln -s "$DANGLE_LEGACY_TARGET_DIR/hooks/pre-commit" "$DANGLE_LEGACY_HOOK_DST"

# Verify the fixture actually models "already deleted" - the target
# directory must NOT exist.
if [[ ! -d "$DANGLE_LEGACY_TARGET_DIR" ]]; then
  _pass "dangling-legacy-target fixture: target worktree directory does not exist (fixture models an already-deleted worktree)"
else
  _fail "dangling-legacy-target fixture: target worktree directory unexpectedly exists (fixture setup bug)"
fi

OUT="$(uninstall_precommit_hook "$DANGLE_LEGACY_MAIN" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "dangling-legacy-target case (DS-152 round 3): uninstall_precommit_hook exits 0"
else
  _fail "dangling-legacy-target case (DS-152 round 3): uninstall_precommit_hook exited $RC. Output: $OUT"
fi

# `! -e` alone follows symlinks and would false-pass on the exact dangling
# case this test exists to check - assert `! -L` too.
if [[ ! -e "$DANGLE_LEGACY_HOOK_DST" ]] && [[ ! -L "$DANGLE_LEGACY_HOOK_DST" ]]; then
  _pass "dangling-legacy-target case (DS-152 round 3): dangling legacy hook under a known worktree root actually removed"
else
  _fail "dangling-legacy-target case (DS-152 round 3 regression): dangling legacy hook still present at $DANGLE_LEGACY_HOOK_DST, current target: $(readlink "$DANGLE_LEGACY_HOOK_DST" 2>&1). Output: $OUT"
fi

# ------------------------------------------------------------------
# Test 12b: the SAME dangling-target shape, but OUTSIDE the repo's known
#           worktree roots, must NOT be removed - the path constraint exists
#           precisely to avoid widening into a foreign dangling hook that
#           merely happens to be unreachable.
# ------------------------------------------------------------------

DANGLE_FOREIGN_MAIN="$TMP_ROOT/dangle-foreign-main-repo"
_make_fixture_repo "$DANGLE_FOREIGN_MAIN"

DANGLE_FOREIGN_HOOKS_DIR="$(git -C "$DANGLE_FOREIGN_MAIN" rev-parse --git-path hooks)"
case "$DANGLE_FOREIGN_HOOKS_DIR" in
  /*) : ;;
  *) DANGLE_FOREIGN_HOOKS_DIR="$DANGLE_FOREIGN_MAIN/$DANGLE_FOREIGN_HOOKS_DIR" ;;
esac
DANGLE_FOREIGN_HOOK_DST="$DANGLE_FOREIGN_HOOKS_DIR/pre-commit"

# Target lies outside both known worktree roots - some unrelated, already
# deleted directory that happens to end in /hooks/pre-commit.
DANGLE_FOREIGN_TARGET_DIR="$TMP_ROOT/some-unrelated-deleted-checkout"
mkdir -p "$DANGLE_FOREIGN_HOOKS_DIR"
ln -s "$DANGLE_FOREIGN_TARGET_DIR/hooks/pre-commit" "$DANGLE_FOREIGN_HOOK_DST"

OUT="$(uninstall_precommit_hook "$DANGLE_FOREIGN_MAIN" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "dangling-foreign-target case (DS-152 round 3): uninstall_precommit_hook exits 0"
else
  _fail "dangling-foreign-target case (DS-152 round 3): uninstall_precommit_hook exited $RC. Output: $OUT"
fi

if [[ -L "$DANGLE_FOREIGN_HOOK_DST" ]] && [[ "$(readlink "$DANGLE_FOREIGN_HOOK_DST")" == "$DANGLE_FOREIGN_TARGET_DIR/hooks/pre-commit" ]]; then
  _pass "dangling-foreign-target case (DS-152 round 3): dangling hook outside known worktree roots left untouched, not widened into"
else
  _fail "dangling-foreign-target case (DS-152 round 3 regression): dangling hook outside known worktree roots was removed - the path constraint failed to scope the fix. Output: $OUT"
fi

# ============================================================
# Test 13: DS-152 round 5 (Critical) - a dangling legacy hook whose RAW
#          (readlink) target is a RELATIVE path, whose first path component
#          does not exist, must not hang uninstall_precommit_hook.
#          `${existing%/*}` is a no-op on a slash-free string, so pre-fix
#          code (d2af1489) walked "toolbox" -> "toolbox" -> ... forever,
#          growing `tail` unbounded. Wrapped in `timeout` so a regression
#          here fails a single assertion instead of hanging the whole
#          suite (and CI) - a hung test is its own incident.
# ============================================================

HANG_MAIN="$TMP_ROOT/hang-main-repo"
_make_fixture_repo "$HANG_MAIN"

HANG_HOOKS_DIR="$(git -C "$HANG_MAIN" rev-parse --git-path hooks)"
case "$HANG_HOOKS_DIR" in
  /*) : ;;
  *) HANG_HOOKS_DIR="$HANG_MAIN/$HANG_HOOKS_DIR" ;;
esac
HANG_HOOK_DST="$HANG_HOOKS_DIR/pre-commit"

# A relative symlink target whose first component ("toolbox") does not
# exist anywhere resolvable - the exact shape that hung pre-fix code, and
# the exact shape a real relative pre-DS-152 hook target could take
# (`.husky/hooks/pre-commit`, `toolbox/hooks/pre-commit`, etc).
mkdir -p "$HANG_HOOKS_DIR"
ln -s "toolbox/hooks/pre-commit" "$HANG_HOOK_DST"

HANG_OUT_FILE="$TMP_ROOT/hang-out.txt"
timeout 8 bash -c "
  set -uo pipefail
  . '$LIB'
  _ae_is_ours() { return 1; }
  AE_DRY_RUN=false
  uninstall_precommit_hook '$HANG_MAIN'
" > "$HANG_OUT_FILE" 2>&1
HANG_RC=$?

if [[ $HANG_RC -ne 124 ]]; then
  _pass "hang regression case (DS-152 round 5, Critical): uninstall_precommit_hook did not hang (rc=$HANG_RC, not 124/timeout)"
else
  _fail "hang regression case (DS-152 round 5 regression, Critical): uninstall_precommit_hook HUNG - killed by timeout (rc=124). Output: $(cat "$HANG_OUT_FILE" 2>&1)"
fi

if [[ $HANG_RC -eq 0 ]]; then
  _pass "hang regression case (DS-152 round 5, Critical): uninstall_precommit_hook exits 0 (non-fatal - a relative target anchored against the hooks dir cannot be verified as a legacy sibling without an existing directory, so it is correctly left alone)"
else
  _fail "hang regression case (DS-152 round 5, Critical): uninstall_precommit_hook exited $HANG_RC (expected 0, non-fatal). Output: $(cat "$HANG_OUT_FILE" 2>&1)"
fi

if grep -qi "not ours" "$HANG_OUT_FILE"; then
  _pass "hang regression case (DS-152 round 5, Critical): correctly reported as not ours rather than silently removed"
else
  _fail "hang regression case (DS-152 round 5 regression, Critical): did not report the expected 'not ours' outcome. Output: $(cat "$HANG_OUT_FILE" 2>&1)"
fi

# ------------------------------------------------------------------
# Test 13b: DS-152 round 5 (Critical, safety-net unit) - the termination
#           guard inside _pc_canonicalize_missing_dir itself must hold
#           even when called directly with an unanchored, slash-free,
#           non-existent path - i.e. independent of
#           _pc_is_legacy_sibling_hook's own anchoring fix. This is the
#           safety net the round-5 fix explicitly adds on top of the
#           root-cause anchor.
# ------------------------------------------------------------------

HANG_UNIT_OUT_FILE="$TMP_ROOT/hang-unit-out.txt"
timeout 8 bash -c "
  set -uo pipefail
  . '$LIB'
  _pc_canonicalize_missing_dir 'toolbox'
" > "$HANG_UNIT_OUT_FILE" 2>&1
HANG_UNIT_RC=$?

if [[ $HANG_UNIT_RC -ne 124 ]]; then
  _pass "hang regression unit case (DS-152 round 5, Critical): _pc_canonicalize_missing_dir('toolbox') did not hang (rc=$HANG_UNIT_RC, not 124/timeout)"
else
  _fail "hang regression unit case (DS-152 round 5 regression, Critical): _pc_canonicalize_missing_dir('toolbox') HUNG - killed by timeout (rc=124)."
fi

# ------------------------------------------------------------------
# Test 13c: DS-152 round 5 (Critical, anchor correctness) - isolates the
#           anchoring fix from the termination guard: this fixture's
#           dangling... no, EXISTING target resolves correctly ONLY when
#           the relative readlink target is anchored against the
#           symlink's own directory (hooks_dir), never against the
#           process CWD. Without the anchor, `-d target_repo_dir` is
#           checked against a path relative to the test runner's CWD (this
#           repo checkout) rather than the real sibling worktree, so the
#           hook is wrongly left in place - it would NOT hang (the
#           termination guard alone prevents that), so Test 13/13b cannot
#           distinguish "anchored correctly" from "merely didn't hang".
#           This test can.
# ------------------------------------------------------------------

ANCHOR_MAIN="$TMP_ROOT/anchor-main-repo"
_make_fixture_repo "$ANCHOR_MAIN"

ANCHOR_WT="$TMP_ROOT/anchor-wt"
git -C "$ANCHOR_MAIN" worktree add -q "$ANCHOR_WT" -b anchor-wt-test-branch >/dev/null 2>&1

ANCHOR_HOOKS_DIR="$(git -C "$ANCHOR_MAIN" rev-parse --git-path hooks)"
case "$ANCHOR_HOOKS_DIR" in
  /*) : ;;
  *) ANCHOR_HOOKS_DIR="$ANCHOR_MAIN/$ANCHOR_HOOKS_DIR" ;;
esac
ANCHOR_HOOK_DST="$ANCHOR_HOOKS_DIR/pre-commit"

# The RELATIVE path from the symlink's own directory (ANCHOR_HOOKS_DIR) to
# the real sibling worktree's hooks/pre-commit - exactly the raw text a
# relative pre-DS-152 install would have written via `ln -s`.
ANCHOR_REL_TARGET="$(python3 -c "import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" "$ANCHOR_WT/hooks/pre-commit" "$ANCHOR_HOOKS_DIR")"

mkdir -p "$ANCHOR_HOOKS_DIR"
ln -s "$ANCHOR_REL_TARGET" "$ANCHOR_HOOK_DST"

OUT="$(uninstall_precommit_hook "$ANCHOR_MAIN" 2>&1)"
RC=$?

if [[ $RC -eq 0 ]]; then
  _pass "anchor-correctness case (DS-152 round 5, Critical): uninstall_precommit_hook exits 0"
else
  _fail "anchor-correctness case (DS-152 round 5, Critical): uninstall_precommit_hook exited $RC. Output: $OUT"
fi

# `! -e` alone follows symlinks and would false-pass on a dangling
# leftover symlink - assert `! -L` too.
if [[ ! -e "$ANCHOR_HOOK_DST" ]] && [[ ! -L "$ANCHOR_HOOK_DST" ]]; then
  _pass "anchor-correctness case (DS-152 round 5, Critical): relative legacy target correctly resolved against the symlink's own directory and removed"
else
  _fail "anchor-correctness case (DS-152 round 5 regression, Critical): relative legacy target was NOT removed - it was resolved against the wrong base directory (CWD instead of the symlink's own directory: $ANCHOR_HOOKS_DIR). Output: $OUT"
fi

# ---- Results ----

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
