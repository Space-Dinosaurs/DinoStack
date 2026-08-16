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
# Upstream deps: bash, git, mktemp. HARD dependency (the script `exit 1`s at
#                startup if missing): bin/tests/lib/precommit-hook-guard.sh
#                (real-hook save/restore, see the sandbox-guard block
#                below). Optional: `timeout` or `gtimeout` (Test 18's hang
#                guard is skipped with a printed SKIP line when neither is
#                available and ${CI} is not "true"; hard-fails at startup
#                under CI when neither is available - see the resolver
#                block below).
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
#                a different checkout; see Test 7 - plus, as of the sandbox
#                guard below, bin/tests/lib/precommit-hook-guard.sh's own
#                save/restore of the real hook as a second, independent
#                layer). An ambient GIT_DIR (or its sibling env vars, or a
#                global core.hooksPath) could otherwise make `git -C <dir>`
#                silently ignore `-C` and operate against a DIFFERENT repo
#                entirely - see Test 0 and Test 13.
#
# Performance: ~3 s wall time (pure git + shell, no network). Do NOT
#              hand-maintain an assertion/scenario count here - two prior
#              rounds each shipped a stale figure the moment a test was
#              added without updating this comment (round 2 wrote "68
#              assertions across 23 fixture scenarios" and immediately
#              undercounted its own round-2 addition; round 3 found that
#              same miss again). The one number that can never drift is
#              printed by this script itself on every run: the final
#              "Results: N passed, N failed." line - read that instead of
#              trusting any count written here.
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
#   - Sandbox guard (Test 0, Test 13): an ambient GIT_DIR (or sibling env
#     vars, or a global core.hooksPath) makes `git -C <dir>` silently
#     IGNORE `-C` and operate against a DIFFERENT repo - Test 13
#     reproduces the escape directly (env-prefix scoped, never leaked into
#     this script's own shell) and confirms resolve_git_hooks_dir fails
#     closed with the guard genuinely in effect; Test 0 pins that the
#     guard's `unset` block actually ran before any fixture.
#   - Orphan cleanup, delta over #640 (live defect, reproduced against
#     origin/main pre-fix - a dangling hook naming a DIFFERENT,
#     already-removed worktree of the SAME repo can never match either of
#     uninstall_precommit_hook's two exact-match candidates, both derived
#     from the CURRENTLY invoking repo_dir): Test 14 (.claude/worktrees/),
#     Test 15 (.agentic/worktrees/), Test 17 (a RELATIVE dangling target,
#     anchored against the hooks dir per POSIX, not the process CWD),
#     Test 20 (.worktrees/, added after Major 1 round 2 found the
#     "fixed two-candidate shape" premise was false), Test 21
#     (evals/.worktrees/, same round). Test 19 covers the deliberate
#     positive-match case where the dangling target reaches one of these
#     candidates through a symlink OUTSIDE the repo (still removed - see
#     _precommit_is_orphaned_worktree_target's own manifest for why).
#   - Distinct DANGLING warning (round 2, Major 2 predecessor bullet folded
#     in here): a dangling hook matching none of the three
#     uninstall_precommit_hook cases now gets a distinct "DANGLING"
#     warning instead of the generic "points elsewhere" message - Test 16.
#   - False-positive guard (a genuinely foreign dangling hook, or one with
#     the RIGHT shape but the WRONG repo_dir, must never be deleted):
#     Test 16 (outside any worktrees root entirely), Test 22 (re-run after
#     Major 1 round 2 widened the candidate list to four - a same-shaped
#     ".worktrees/<name>/hooks/pre-commit" target rooted at a different,
#     unrelated repo must still be left alone).
#   - Hang guard (Test 18): _precommit_is_orphaned_worktree_target must
#     return promptly for a pathological, deeply-nested, non-existent
#     dangling target. As of round 3 this function DOES implement a
#     bounded upward ancestor walk (see Major 2 below and the helper's own
#     manifest for why the round-1/round-2 fixed-strip design was
#     replaced) - this test now pins that the walk's own bound
#     (_PRECOMMIT_MAX_ANCESTOR_DEPTH and its termination guard) keeps it
#     fast even on a pathological input, not that no walk exists at all.
#   - Exact-match guard, both directions (round 3, Minor 1): a candidate
#     comparison that degrades from exact string equality to a prefix
#     match in either direction is wrong. Test 23 covers the FORWARD
#     direction (target is a superstring of a real candidate, e.g.
#     ".worktrees-decoy" vs ".worktrees"); Test 27 covers the REVERSE
#     direction (an ancestor being tested canonicalizes to a STRING PREFIX
#     of a real candidate, e.g. repo_dir itself is a prefix of
#     "repo_dir/.claude/worktrees") - a sibling mutation class Test 23
#     alone does not reach, found missing by a round-3 Skeptic review.
#   - Danglingness-gate ordering and existence (round 3, Major 1 - a live,
#     resolving relative-target hook was silently deleted because `[[ -e
#     "$target" ]]` ran before the relative-target anchoring block,
#     testing existence against this script's own process CWD instead of
#     hooks_dir): Test 24 (relative live target, isolates the reorder fix
#     - reddens under the pre-fix ordering) and Test 25 (absolute live
#     target, isolates the gate's mere EXISTENCE from its ordering -
#     reddens if the `-e` check is deleted outright, which round 3 found
#     was NOT covered by any assertion before Test 25 was added; deleting
#     it left the full suite green).
#   - Bounded upward search / depth-2 evidence (round 3, Major 2 - the
#     round-2 "every candidate resolves at exactly ONE directory level
#     below its container" premise was false:
#     content/references/subagent-protocol.md:333-334's own documented
#     worktree-add command uses a FEATURE_BRANCH value that, under this
#     repo's branch-naming convention, contains a "/" - landing the
#     worktree TWO levels below ".worktrees", not one; AGENTS.md:48's
#     ".agentic/worktrees/<branch-name>" has the identical hazard for any
#     slash-containing branch name): Test 26, both for ".worktrees/" (the
#     literal subagent-protocol.md example shape) and for
#     ".agentic/worktrees/" (the AGENTS.md sibling shape). Reddens against
#     a reverted fixed-single-strip mutation of the container computation.
#   - ".." escape guard (round 4, Minor 1 - round 3's ancestor walk
#     derived ancestors by naively string-stripping the target's raw
#     spelling, which is not ancestor-derivation when ".." segments
#     appear after a container name: a target of
#     "<repo>/.worktrees/../../../../../x/hooks/pre-commit" physically
#     resolves far outside the repo, but the naive walk still reached
#     "<repo>/.worktrees" - a real, canonicalizable candidate - and
#     answered DELETE): Test 28, fixed by
#     _precommit_lexical_normalize'ing the worktree directory once,
#     before the walk begins.
#   - Empty-hooks_dir guard coverage (round 4, Minor 2 - a documented
#     FAILS-CLOSED clause, "hooks_dir is empty and target is relative",
#     had zero assertion coverage; deleting the guard left the round-3
#     suite unchanged): Test 29, constructed so the unguarded
#     concatenation would reconstruct a real candidate path if the guard
#     were absent - a weaker construction would not distinguish
#     guard-present from guard-absent.
#   This test re-creates worktree fixtures for all of the above to prevent
#   regression.

set -uo pipefail

# Sandbox guard, FIRST executable statement: an ambient GIT_DIR (or its
# siblings) makes `git -C <dir>` silently IGNORE `-C` and operate on
# whatever repo the ambient env points at instead - reproduced directly by
# Test 13 below. Every fixture in this file passes an explicit repo_dir to
# resolve_git_hooks_dir/resolve_hook_src/install_precommit_hook/
# uninstall_precommit_hook expecting `-C` to be honoured; an ambient GIT_DIR
# defeats that silently and can make this file's fixtures operate on an
# unrelated repo's real hooks (in the worst case, the actual DinoStack
# checkout's own .git/hooks, if this test happens to run from a session
# that leaked GIT_DIR into its environment). Unset the full family, not
# just GIT_DIR - GIT_WORK_TREE/_COMMON_DIR/_INDEX_FILE/_OBJECT_DIRECTORY/
# _ALTERNATE_OBJECT_DIRECTORIES/_CEILING_DIRECTORIES can each independently
# redirect git's notion of "which repo" or "which objects".
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_CEILING_DIRECTORIES

# A global (or system) `core.hooksPath` is honoured by `--git-path hooks`
# and is NOT covered by the unset list above (it is read from config, not
# env) - point both config scopes at /dev/null so no ambient
# ~/.gitconfig-level hooksPath override can redirect any fixture's
# resolved hooks directory either.
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$REPO_DIR/scripts/lib/precommit.sh"
GUARD_LIB="$REPO_DIR/bin/tests/lib/precommit-hook-guard.sh"

if [[ ! -f "$LIB" ]]; then
  echo "FAIL: $LIB not found" >&2
  exit 1
fi

if [[ ! -f "$GUARD_LIB" ]]; then
  echo "FAIL: $GUARD_LIB not found" >&2
  exit 1
fi

# shellcheck source=bin/tests/lib/precommit-hook-guard.sh
. "$GUARD_LIB"

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

# Test 0: the sandbox guard above actually took effect in THIS shell before
# any fixture runs - asserted directly rather than merely trusted. Uses
# `env` + a literal name list rather than bash's `${!_v}` indirect
# expansion, which is NOT valid syntax under zsh (this suite is required to
# pass under both).
_SANDBOX_GUARD_CLEAN=1
if env | grep -qE '^(GIT_DIR|GIT_WORK_TREE|GIT_COMMON_DIR|GIT_INDEX_FILE|GIT_OBJECT_DIRECTORY|GIT_ALTERNATE_OBJECT_DIRECTORIES|GIT_CEILING_DIRECTORIES)='; then
  _SANDBOX_GUARD_CLEAN=0
fi
if [[ "$_SANDBOX_GUARD_CLEAN" -eq 1 ]]; then
  _pass "Test 0 (sandbox guard): all seven ambient git env vars are unset before any fixture runs"
else
  _fail "Test 0 (sandbox guard regression): at least one ambient git env var is still set"
fi

# Resolve a timeout binary once - required to make any hang-guard assertion
# (Test 18) meaningful. Without a real resolver, a `timeout`-wrapped
# assertion silently returns 127 (command not found) and the comparison
# against a non-124 rc passes having tested nothing. Hard-fail under CI
# rather than silently skip (same pattern as
# bin/tests/test_check_resident_budget.sh's own guard).
_TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
  _TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  _TIMEOUT_BIN="gtimeout"
elif [[ "${CI:-}" == "true" ]]; then
  echo "FAIL: neither timeout nor gtimeout is available under CI - the hang-guard assertion (Test 18) cannot run and must not silently pass" >&2
  exit 1
fi

# Belt-and-suspenders: even with the env sandbox guard above, snapshot and
# guarantee restoration of this REAL checkout's own pre-commit hook, the
# same guard bin/tests/test_uninstall_ds_prefix.sh and friends already rely
# on for scripts that invoke real install/uninstall paths against the live
# repo. This file's own fixtures never pass $REPO_DIR to install/uninstall
# functions, but the guard is cheap and removes any doubt.
precommit_hook_guard_save "$REPO_DIR"

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
  # Restore the real checkout's own hook FIRST (belt-and-suspenders; see
  # the precommit_hook_guard_save call above), then remove the temp
  # fixture root. Order matters only in that both must run unconditionally
  # even if one of this file's assertions failed earlier.
  precommit_hook_guard_restore
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

if [[ ! -L "$UNINSTALL_HOOK_DST" ]] && [[ ! -e "$UNINSTALL_HOOK_DST" ]]; then
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

if [[ ! -L "$LEGACY_HOOK_DST" ]] && [[ ! -e "$LEGACY_HOOK_DST" ]]; then
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

if [[ ! -L "$CANON_HOOK_DST" ]] && [[ ! -e "$CANON_HOOK_DST" ]]; then
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

if [[ ! -L "$MAJOR1_HOOK_DST" ]] && [[ ! -e "$MAJOR1_HOOK_DST" ]]; then
  _pass "Test 12 (Major 1 fixed): legacy hook installed under a non-canonical (symlinked-parent) spelling is removed by uninstall"
else
  _fail "Test 12 (Major 1 regression): legacy hook installed under a non-canonical spelling was left ORPHANED by uninstall - the legacy candidate must match both the raw and the canonical repo_dir spellings. Output: $MAJOR1_OUT"
fi

# ============================================================
# Test 13: sandbox guard - reproduce the ambient-GIT_DIR escape class this
#          file's top-of-script `unset` guard exists to prevent (a dangling
#          target confirmed to reproduce against origin/main pre-fix: an
#          ambient GIT_DIR makes `git -C <dir>` silently IGNORE `-C` and
#          resolve against the ambient repo instead), using an isolated
#          decoy repo under $TMP_ROOT - never the real checkout - then
#          confirms the leak is scoped to a single command (env-prefix, not
#          export) and that resolve_git_hooks_dir fails closed with the
#          guard genuinely in effect.
# ============================================================

SANDBOX_DECOY_REPO="$TMP_ROOT/sandbox-decoy-repo"
mkdir -p "$SANDBOX_DECOY_REPO"
git init -q "$SANDBOX_DECOY_REPO"

SANDBOX_PLAIN_DIR="$TMP_ROOT/sandbox-plain-dir"
mkdir -p "$SANDBOX_PLAIN_DIR"

# Env-PREFIX form (scoped to this one command only, never `export`) - proves
# the vulnerability class without leaking GIT_DIR into this script's shell.
SANDBOX_LEAK_OUT="$(GIT_DIR="$SANDBOX_DECOY_REPO/.git" git -C "$SANDBOX_PLAIN_DIR" rev-parse --git-path hooks 2>&1)"
SANDBOX_LEAK_RC=$?

if [[ $SANDBOX_LEAK_RC -eq 0 ]] && [[ "$SANDBOX_LEAK_OUT" == "$SANDBOX_DECOY_REPO/.git/hooks" ]]; then
  _pass "Test 13 (sandbox guard): reproduces the ambient-GIT_DIR escape class - 'git -C <plain-dir>' silently resolves to a DIFFERENT repo's hooks dir ($SANDBOX_LEAK_OUT) instead of failing, when GIT_DIR is set"
else
  _fail "Test 13 setup: expected the ambient-GIT_DIR escape to reproduce (rc=$SANDBOX_LEAK_RC out=$SANDBOX_LEAK_OUT) - fixture does not demonstrate the vulnerability class this guard defends against"
fi

if [[ -z "${GIT_DIR:-}" ]]; then
  _pass "Test 13 (sandbox guard): GIT_DIR was NOT leaked into this script's own shell by the demonstration above (env-prefix scoping worked)"
else
  _fail "Test 13 (sandbox guard regression): GIT_DIR leaked into this script's own shell: $GIT_DIR"
fi

if ! resolve_git_hooks_dir "$SANDBOX_PLAIN_DIR" >/dev/null 2>&1; then
  _pass "Test 13 (sandbox guard): resolve_git_hooks_dir on a non-repo dir fails closed with no ambient GIT_DIR set (the guard is genuinely in effect for this file's own fixtures)"
else
  _fail "Test 13 (sandbox guard regression): resolve_git_hooks_dir unexpectedly succeeded on a non-repo, non-worktree dir"
fi

# ============================================================
# Test 14: orphan cleanup (delta over #640) - a DANGLING pre-commit symlink
#          whose target names a DIFFERENT, ALREADY-REMOVED worktree of this
#          same repo under "<repo_dir>/.claude/worktrees/<name>" must be
#          recognised and removed by uninstall_precommit_hook, even though
#          neither of #640's two exact-match candidates (both derived from
#          the CURRENTLY invoking repo_dir) can ever match it. Reproduced
#          against origin/main pre-fix: the dangling symlink survives
#          uninstall permanently ("not ours, skipping").
# ============================================================

ORPHAN_MAIN="$TMP_ROOT/orphan-main-repo"
_make_fixture_repo "$ORPHAN_MAIN"
mkdir -p "$ORPHAN_MAIN/.claude/worktrees"

ORPHAN_WT="$ORPHAN_MAIN/.claude/worktrees/agent-orphan-test"
git -C "$ORPHAN_MAIN" worktree add -q "$ORPHAN_WT" -b orphan-wt-test-branch >/dev/null 2>&1

ORPHAN_REAL_HOOKS_DIR="$(git -C "$ORPHAN_MAIN" rev-parse --git-path hooks)"
case "$ORPHAN_REAL_HOOKS_DIR" in
  /*) : ;;
  *) ORPHAN_REAL_HOOKS_DIR="$ORPHAN_MAIN/$ORPHAN_REAL_HOOKS_DIR" ;;
esac
ORPHAN_HOOK_DST="$ORPHAN_REAL_HOOKS_DIR/pre-commit"

# Simulate a hook that was installed FROM the (now-gone) worktree - the
# target names the worktree's own hooks/pre-commit, exactly what
# install_precommit_hook's KNOWN-RESIDUAL fallback produces for this repo's
# own isolation-worktree layout.
mkdir -p "$ORPHAN_REAL_HOOKS_DIR"
ln -s "$ORPHAN_WT/hooks/pre-commit" "$ORPHAN_HOOK_DST"

if [[ -L "$ORPHAN_HOOK_DST" ]] && [[ "$(readlink "$ORPHAN_HOOK_DST")" == "$ORPHAN_WT/hooks/pre-commit" ]]; then
  _pass "Test 14 setup: orphan-candidate hook installed, targeting the worktree's own hooks/pre-commit"
else
  _fail "Test 14 setup: orphan-candidate hook not installed as expected at $ORPHAN_HOOK_DST"
fi

git -C "$ORPHAN_MAIN" worktree remove -f "$ORPHAN_WT" >/dev/null 2>&1

if [[ -L "$ORPHAN_HOOK_DST" ]] && [[ ! -e "$ORPHAN_HOOK_DST" ]]; then
  _pass "Test 14 setup: hook is now a DANGLING symlink after the worktree was removed - reproduces the live defect's starting state"
else
  _fail "Test 14 setup: expected a dangling symlink at $ORPHAN_HOOK_DST after worktree removal"
fi

# Run uninstall from the PRIMARY checkout (ORPHAN_MAIN itself) - not from
# the gone worktree, which no longer exists to run anything from. This is
# the realistic trigger: a later uninstall run (e.g. via .claude/uninstall.sh
# from the primary checkout) is the only remaining opportunity to clean up
# an orphan left behind by a worktree that is already gone.
ORPHAN_OUT="$(uninstall_precommit_hook "$ORPHAN_MAIN" 2>&1)"
ORPHAN_RC=$?

if [[ $ORPHAN_RC -eq 0 ]]; then
  _pass "Test 14 (orphan cleanup): uninstall_precommit_hook exits 0"
else
  _fail "Test 14 (orphan cleanup): uninstall_precommit_hook exited $ORPHAN_RC. Output: $ORPHAN_OUT"
fi

if [[ ! -L "$ORPHAN_HOOK_DST" ]] && [[ ! -e "$ORPHAN_HOOK_DST" ]]; then
  _pass "Test 14 (orphan cleanup, delta over #640): dangling hook naming an already-removed .claude/worktrees/ worktree is REMOVED. Output: $ORPHAN_OUT"
else
  _fail "Test 14 (orphan cleanup regression): dangling hook naming an already-removed worktree still present at $ORPHAN_HOOK_DST - the live defect this delta exists to fix. Output: $ORPHAN_OUT"
fi

# ============================================================
# Test 15: orphan cleanup, the ".agentic/worktrees/" sibling layout.
# ============================================================

ORPHAN2_MAIN="$TMP_ROOT/orphan2-main-repo"
_make_fixture_repo "$ORPHAN2_MAIN"
mkdir -p "$ORPHAN2_MAIN/.agentic/worktrees"

ORPHAN2_WT="$ORPHAN2_MAIN/.agentic/worktrees/some-feature-branch"
git -C "$ORPHAN2_MAIN" worktree add -q "$ORPHAN2_WT" -b some-feature-branch >/dev/null 2>&1

ORPHAN2_REAL_HOOKS_DIR="$(git -C "$ORPHAN2_MAIN" rev-parse --git-path hooks)"
case "$ORPHAN2_REAL_HOOKS_DIR" in
  /*) : ;;
  *) ORPHAN2_REAL_HOOKS_DIR="$ORPHAN2_MAIN/$ORPHAN2_REAL_HOOKS_DIR" ;;
esac
ORPHAN2_HOOK_DST="$ORPHAN2_REAL_HOOKS_DIR/pre-commit"

mkdir -p "$ORPHAN2_REAL_HOOKS_DIR"
ln -s "$ORPHAN2_WT/hooks/pre-commit" "$ORPHAN2_HOOK_DST"

git -C "$ORPHAN2_MAIN" worktree remove -f "$ORPHAN2_WT" >/dev/null 2>&1

ORPHAN2_OUT="$(uninstall_precommit_hook "$ORPHAN2_MAIN" 2>&1)"

if [[ ! -L "$ORPHAN2_HOOK_DST" ]] && [[ ! -e "$ORPHAN2_HOOK_DST" ]]; then
  _pass "Test 15 (orphan cleanup, .agentic/worktrees/): dangling hook naming an already-removed .agentic/worktrees/ worktree is removed. Output: $ORPHAN2_OUT"
else
  _fail "Test 15 (orphan cleanup regression, .agentic/worktrees/): dangling hook still present at $ORPHAN2_HOOK_DST. Output: $ORPHAN2_OUT"
fi

# ============================================================
# Test 16: false-positive guard - a dangling hook pointing OUTSIDE any
#          worktrees root (a genuinely foreign, unrelated project) must be
#          left untouched, and gets the NEW distinct "DANGLING" warning
#          rather than the generic "points elsewhere" message, so a
#          permanently-broken foreign hook stays visible instead of being
#          silently tolerated forever.
# ============================================================

FOREIGN3_MAIN="$TMP_ROOT/foreign3-main-repo"
_make_fixture_repo "$FOREIGN3_MAIN"

FOREIGN3_REAL_HOOKS_DIR="$(git -C "$FOREIGN3_MAIN" rev-parse --git-path hooks)"
case "$FOREIGN3_REAL_HOOKS_DIR" in
  /*) : ;;
  *) FOREIGN3_REAL_HOOKS_DIR="$FOREIGN3_MAIN/$FOREIGN3_REAL_HOOKS_DIR" ;;
esac
FOREIGN3_HOOK_DST="$FOREIGN3_REAL_HOOKS_DIR/pre-commit"

# Points at a path that superficially resembles the orphan shape (ends in
# "/hooks/pre-commit") but is NOT under this repo's .claude/worktrees or
# .agentic/worktrees at all - e.g. some unrelated scratch checkout.
FOREIGN3_UNRELATED_TARGET="$TMP_ROOT/some-other-project/scratch/hooks/pre-commit"
mkdir -p "$FOREIGN3_REAL_HOOKS_DIR"
ln -s "$FOREIGN3_UNRELATED_TARGET" "$FOREIGN3_HOOK_DST"

FOREIGN3_OUT="$(uninstall_precommit_hook "$FOREIGN3_MAIN" 2>&1)"

if [[ -L "$FOREIGN3_HOOK_DST" ]] && [[ "$(readlink "$FOREIGN3_HOOK_DST")" == "$FOREIGN3_UNRELATED_TARGET" ]]; then
  _pass "Test 16 (no over-match): a dangling hook pointing outside any worktrees root is left untouched, not deleted as a false-positive orphan"
else
  _fail "Test 16 (over-match regression): a genuinely foreign dangling hook was removed or altered. Output: $FOREIGN3_OUT"
fi

if echo "$FOREIGN3_OUT" | grep -qi "DANGLING"; then
  _pass "Test 16 (distinct dangling warning): the foreign dangling hook gets the new distinct DANGLING warning, not just the generic 'points elsewhere' message"
else
  _fail "Test 16 regression: expected a distinct DANGLING warning for an unresolvable, non-orphan hook. Output: $FOREIGN3_OUT"
fi

# ============================================================
# Test 17: orphan cleanup also recognises a RELATIVE dangling target,
#          anchored against the hooks dir per POSIX symlink-resolution
#          semantics (relative to the symlink's OWN directory, never the
#          process CWD) - not merely the absolute-target shape every other
#          orphan test above exercises.
# ============================================================

ORPHAN3_MAIN="$TMP_ROOT/orphan3-main-repo"
_make_fixture_repo "$ORPHAN3_MAIN"
mkdir -p "$ORPHAN3_MAIN/.claude/worktrees"

ORPHAN3_WT="$ORPHAN3_MAIN/.claude/worktrees/agent-relative-test"
git -C "$ORPHAN3_MAIN" worktree add -q "$ORPHAN3_WT" -b orphan3-wt-test-branch >/dev/null 2>&1

ORPHAN3_REAL_HOOKS_DIR="$(git -C "$ORPHAN3_MAIN" rev-parse --git-path hooks)"
case "$ORPHAN3_REAL_HOOKS_DIR" in
  /*) : ;;
  *) ORPHAN3_REAL_HOOKS_DIR="$ORPHAN3_MAIN/$ORPHAN3_REAL_HOOKS_DIR" ;;
esac
ORPHAN3_HOOK_DST="$ORPHAN3_REAL_HOOKS_DIR/pre-commit"

# A RELATIVE target from the real hooks dir to the worktree's own
# hooks/pre-commit (computed with python's relpath equivalent via a plain
# `..` walk, since both paths are already known and fixed for this
# fixture).
ORPHAN3_RELATIVE_TARGET="../../.claude/worktrees/agent-relative-test/hooks/pre-commit"
mkdir -p "$ORPHAN3_REAL_HOOKS_DIR"
ln -s "$ORPHAN3_RELATIVE_TARGET" "$ORPHAN3_HOOK_DST"

# Confirm the relative link actually resolves to the real fixture file
# BEFORE worktree removal (i.e. the relative-path arithmetic above is
# correct for this fixture's real directory depth), so a failure below is
# never mistaken for a fixture bug.
if [[ -e "$ORPHAN3_HOOK_DST" ]]; then
  _pass "Test 17 setup: relative-target symlink resolves correctly before worktree removal (fixture arithmetic confirmed)"
else
  _fail "Test 17 setup: relative-target symlink does NOT resolve before worktree removal at $ORPHAN3_HOOK_DST -> $ORPHAN3_RELATIVE_TARGET (fixture bug, not a library bug)"
fi

git -C "$ORPHAN3_MAIN" worktree remove -f "$ORPHAN3_WT" >/dev/null 2>&1

ORPHAN3_OUT="$(uninstall_precommit_hook "$ORPHAN3_MAIN" 2>&1)"

if [[ ! -L "$ORPHAN3_HOOK_DST" ]] && [[ ! -e "$ORPHAN3_HOOK_DST" ]]; then
  _pass "Test 17 (relative-target orphan cleanup): a RELATIVE dangling target naming an already-removed worktree is also removed. Output: $ORPHAN3_OUT"
else
  _fail "Test 17 (relative-target orphan cleanup regression): relative-target dangling hook still present at $ORPHAN3_HOOK_DST. Output: $ORPHAN3_OUT"
fi

# ============================================================
# Test 18: hang guard - _precommit_is_orphaned_worktree_target must return
#          PROMPTLY even for a pathological, deeply-nested, entirely
#          non-existent dangling target. This module deliberately does NOT
#          implement a generic walk-up-the-target's-ancestors algorithm
#          (see the function's own manifest for why) specifically to avoid
#          needing an unbounded-loop termination guard; this test pins that
#          design choice so a future edit that reintroduces a walk-up loop
#          without a termination guard is caught by a hang, not a silent
#          merge.
# ============================================================

if [[ -n "$_TIMEOUT_BIN" ]]; then
  HANG_REPO="$TMP_ROOT/hang-repo"
  _make_fixture_repo "$HANG_REPO"
  mkdir -p "$HANG_REPO/.claude/worktrees"
  PATHOLOGICAL_TARGET="/nope/a/b/c/d/e/f/g/h/i/j/k/l/m/n/o/p/hooks/pre-commit"

  "$_TIMEOUT_BIN" 5 bash -c '. "$1"; _ae_is_ours() { return 1; }; _precommit_is_orphaned_worktree_target "$2" "$3" "$4"' _ "$LIB" "$PATHOLOGICAL_TARGET" "$HANG_REPO" "$HANG_REPO/.git/hooks" >/dev/null 2>&1
  HANG_RC=$?
  # 124 is `timeout`'s own "killed after timeout" exit code - anything else
  # (0 or 1, the function's real true/false result) proves it returned
  # promptly rather than hanging.
  if [[ $HANG_RC -ne 124 ]]; then
    _pass "Test 18 (hang guard): _precommit_is_orphaned_worktree_target returns promptly for a pathological non-existent target (rc=$HANG_RC, not a timeout-124 kill)"
  else
    _fail "Test 18 (hang guard regression): _precommit_is_orphaned_worktree_target HUNG on a pathological target and was killed by timeout after 5s"
  fi
else
  echo "SKIP: Test 18 (hang guard) - neither timeout nor gtimeout available locally (non-CI); the CI guard above hard-fails this scenario when \${CI}=true"
fi

# ============================================================
# Test 19: a dangling target that reaches one of the four enumerated
#          worktrees-container candidates THROUGH a symlink located
#          OUTSIDE <repo_dir> is still recognised and removed - the
#          physical, `cd`-canonicalized container directory is what is
#          compared, not the symlinked spelling of the path that reaches
#          it. Documented as a deliberate positive-match case in the
#          helper's own manifest (distinct from the FAILS-CLOSED
#          enumeration, since it is a removal, not a refusal).
# ============================================================

SYMOUT_MAIN="$TMP_ROOT/symout-main-repo"
_make_fixture_repo "$SYMOUT_MAIN"
mkdir -p "$SYMOUT_MAIN/.claude/worktrees"

SYMOUT_WT="$SYMOUT_MAIN/.claude/worktrees/agent-symout-test"
git -C "$SYMOUT_MAIN" worktree add -q "$SYMOUT_WT" -b symout-wt-test-branch >/dev/null 2>&1

# A symlink OUTSIDE $SYMOUT_MAIN that resolves into the real worktree - the
# dangling target below is spelled THROUGH this external symlink, never
# through $SYMOUT_MAIN's own (canonical) path.
SYMOUT_EXTERNAL_LINK="$TMP_ROOT/symout-external-alias"
ln -s "$SYMOUT_MAIN" "$SYMOUT_EXTERNAL_LINK"

SYMOUT_REAL_HOOKS_DIR="$(git -C "$SYMOUT_MAIN" rev-parse --git-path hooks)"
case "$SYMOUT_REAL_HOOKS_DIR" in
  /*) : ;;
  *) SYMOUT_REAL_HOOKS_DIR="$SYMOUT_MAIN/$SYMOUT_REAL_HOOKS_DIR" ;;
esac
SYMOUT_HOOK_DST="$SYMOUT_REAL_HOOKS_DIR/pre-commit"

mkdir -p "$SYMOUT_REAL_HOOKS_DIR"
ln -s "$SYMOUT_EXTERNAL_LINK/.claude/worktrees/agent-symout-test/hooks/pre-commit" "$SYMOUT_HOOK_DST"

if [[ -L "$SYMOUT_HOOK_DST" ]] && [[ "$(readlink "$SYMOUT_HOOK_DST")" == "$SYMOUT_EXTERNAL_LINK"* ]]; then
  _pass "Test 19 setup: hook installed via a target spelled through an EXTERNAL symlink, not the repo's own canonical path"
else
  _fail "Test 19 setup: hook not installed as expected at $SYMOUT_HOOK_DST"
fi

git -C "$SYMOUT_MAIN" worktree remove -f "$SYMOUT_WT" >/dev/null 2>&1

SYMOUT_OUT="$(uninstall_precommit_hook "$SYMOUT_MAIN" 2>&1)"

if [[ ! -L "$SYMOUT_HOOK_DST" ]] && [[ ! -e "$SYMOUT_HOOK_DST" ]]; then
  _pass "Test 19 (symlink-outside-repo orphan cleanup): a dangling target reaching this repo's own .claude/worktrees THROUGH an external symlink is still removed. Output: $SYMOUT_OUT"
else
  _fail "Test 19 (symlink-outside-repo orphan cleanup regression): hook still present at $SYMOUT_HOOK_DST. Output: $SYMOUT_OUT"
fi

# ============================================================
# Test 20: orphan cleanup, the ".worktrees/" candidate added for Major 1
#          (content/references/subagent-protocol.md:333's manually-managed
#          fan-out path, "${REPO}/.worktrees/${FEATURE_BRANCH}-${unit_slug}").
# ============================================================

DOTWT_MAIN="$TMP_ROOT/dotwt-main-repo"
_make_fixture_repo "$DOTWT_MAIN"
mkdir -p "$DOTWT_MAIN/.worktrees"

DOTWT_WT="$DOTWT_MAIN/.worktrees/feature-x-unit1"
git -C "$DOTWT_MAIN" worktree add -q "$DOTWT_WT" -b feature-x-unit1 >/dev/null 2>&1

DOTWT_REAL_HOOKS_DIR="$(git -C "$DOTWT_MAIN" rev-parse --git-path hooks)"
case "$DOTWT_REAL_HOOKS_DIR" in
  /*) : ;;
  *) DOTWT_REAL_HOOKS_DIR="$DOTWT_MAIN/$DOTWT_REAL_HOOKS_DIR" ;;
esac
DOTWT_HOOK_DST="$DOTWT_REAL_HOOKS_DIR/pre-commit"

mkdir -p "$DOTWT_REAL_HOOKS_DIR"
ln -s "$DOTWT_WT/hooks/pre-commit" "$DOTWT_HOOK_DST"

git -C "$DOTWT_MAIN" worktree remove -f "$DOTWT_WT" >/dev/null 2>&1

DOTWT_OUT="$(uninstall_precommit_hook "$DOTWT_MAIN" 2>&1)"

if [[ ! -L "$DOTWT_HOOK_DST" ]] && [[ ! -e "$DOTWT_HOOK_DST" ]]; then
  _pass "Test 20 (orphan cleanup, .worktrees/ candidate): dangling hook naming an already-removed .worktrees/ worktree is removed. Output: $DOTWT_OUT"
else
  _fail "Test 20 (orphan cleanup regression, .worktrees/): dangling hook still present at $DOTWT_HOOK_DST. Output: $DOTWT_OUT"
fi

# ============================================================
# Test 21: orphan cleanup, the "evals/.worktrees/" candidate added for
#          Major 1 (content/commands/ds-cleanup-worktrees.md's
#          "evals/.worktrees/wt-*" instance).
# ============================================================

EVALSWT_MAIN="$TMP_ROOT/evalswt-main-repo"
_make_fixture_repo "$EVALSWT_MAIN"
mkdir -p "$EVALSWT_MAIN/evals/.worktrees"

EVALSWT_WT="$EVALSWT_MAIN/evals/.worktrees/wt-abc123"
git -C "$EVALSWT_MAIN" worktree add -q "$EVALSWT_WT" -b evalswt-test-branch >/dev/null 2>&1

EVALSWT_REAL_HOOKS_DIR="$(git -C "$EVALSWT_MAIN" rev-parse --git-path hooks)"
case "$EVALSWT_REAL_HOOKS_DIR" in
  /*) : ;;
  *) EVALSWT_REAL_HOOKS_DIR="$EVALSWT_MAIN/$EVALSWT_REAL_HOOKS_DIR" ;;
esac
EVALSWT_HOOK_DST="$EVALSWT_REAL_HOOKS_DIR/pre-commit"

mkdir -p "$EVALSWT_REAL_HOOKS_DIR"
ln -s "$EVALSWT_WT/hooks/pre-commit" "$EVALSWT_HOOK_DST"

git -C "$EVALSWT_MAIN" worktree remove -f "$EVALSWT_WT" >/dev/null 2>&1

EVALSWT_OUT="$(uninstall_precommit_hook "$EVALSWT_MAIN" 2>&1)"

if [[ ! -L "$EVALSWT_HOOK_DST" ]] && [[ ! -e "$EVALSWT_HOOK_DST" ]]; then
  _pass "Test 21 (orphan cleanup, evals/.worktrees/ candidate): dangling hook naming an already-removed evals/.worktrees/ worktree is removed. Output: $EVALSWT_OUT"
else
  _fail "Test 21 (orphan cleanup regression, evals/.worktrees/): dangling hook still present at $EVALSWT_HOOK_DST. Output: $EVALSWT_OUT"
fi

# ============================================================
# Test 22: false-positive guard, re-run for the WIDENED candidate set - a
#          dangling target whose shape matches a candidate (e.g.
#          ".worktrees/<name>/hooks/pre-commit") but under a COMPLETELY
#          DIFFERENT repo's own directory tree must NOT be recognised as
#          this repo's orphan, even though the string shape is identical.
#          The widened candidate list only ever compares against THIS
#          repo_dir's own four candidate paths - never a generic pattern
#          match - so a same-shaped target rooted at a different physical
#          directory must fail closed.
# ============================================================

FOREIGN4_MAIN="$TMP_ROOT/foreign4-main-repo"
_make_fixture_repo "$FOREIGN4_MAIN"

FOREIGN4_OTHER_REPO="$TMP_ROOT/foreign4-other-repo"
mkdir -p "$FOREIGN4_OTHER_REPO/.worktrees/some-other-feature/hooks"

FOREIGN4_REAL_HOOKS_DIR="$(git -C "$FOREIGN4_MAIN" rev-parse --git-path hooks)"
case "$FOREIGN4_REAL_HOOKS_DIR" in
  /*) : ;;
  *) FOREIGN4_REAL_HOOKS_DIR="$FOREIGN4_MAIN/$FOREIGN4_REAL_HOOKS_DIR" ;;
esac
FOREIGN4_HOOK_DST="$FOREIGN4_REAL_HOOKS_DIR/pre-commit"

# Same SHAPE (".worktrees/<name>/hooks/pre-commit") as Test 20, but rooted
# at a totally different, unrelated repo directory - never removed by
# $FOREIGN4_MAIN's own uninstall run.
FOREIGN4_UNRELATED_TARGET="$FOREIGN4_OTHER_REPO/.worktrees/some-other-feature/hooks/pre-commit"
mkdir -p "$FOREIGN4_REAL_HOOKS_DIR"
ln -s "$FOREIGN4_UNRELATED_TARGET" "$FOREIGN4_HOOK_DST"

FOREIGN4_OUT="$(uninstall_precommit_hook "$FOREIGN4_MAIN" 2>&1)"

if [[ -L "$FOREIGN4_HOOK_DST" ]] && [[ "$(readlink "$FOREIGN4_HOOK_DST")" == "$FOREIGN4_UNRELATED_TARGET" ]]; then
  _pass "Test 22 (no over-match, widened candidate set): a same-shaped dangling hook rooted at a DIFFERENT repo's .worktrees/ is left untouched"
else
  _fail "Test 22 (over-match regression, widened candidate set): a same-shaped but foreign dangling hook was removed or altered. Output: $FOREIGN4_OUT"
fi

# ============================================================
# Test 23: exact-match guard - a candidate comparison that degraded from
#          exact string equality to a PREFIX match would still pass every
#          test above (none of them constructs a sibling directory whose
#          name happens to start with a real candidate's own path), so it
#          is asserted directly here: a dangling hook rooted at
#          "<repo_dir>/.worktrees-decoy" (a real, EXISTING sibling
#          directory of "<repo_dir>/.worktrees" that is NOT itself a
#          recognised candidate, and is not a prefix-relationship
#          coincidence - it merely SHARES ".worktrees" as its own string
#          prefix) must be left untouched. A `==` comparison correctly
#          distinguishes these; a `== *` glob comparison would not.
# ============================================================

DECOY_MAIN="$TMP_ROOT/decoy-main-repo"
_make_fixture_repo "$DECOY_MAIN"
# The REAL ".worktrees" candidate must also exist (even though unused) so
# that a prefix-match mutation has something real to match AGAINST - if
# only the decoy directory existed, the real candidate's own `cd` would
# fail and skip the comparison entirely, making this fixture unable to
# distinguish exact-match from prefix-match regardless of which the
# library actually implements.
mkdir -p "$DECOY_MAIN/.worktrees"
mkdir -p "$DECOY_MAIN/.worktrees-decoy"

DECOY_WT="$DECOY_MAIN/.worktrees-decoy/some-unrelated-dir"
git -C "$DECOY_MAIN" worktree add -q "$DECOY_WT" -b decoy-test-branch >/dev/null 2>&1

DECOY_REAL_HOOKS_DIR="$(git -C "$DECOY_MAIN" rev-parse --git-path hooks)"
case "$DECOY_REAL_HOOKS_DIR" in
  /*) : ;;
  *) DECOY_REAL_HOOKS_DIR="$DECOY_MAIN/$DECOY_REAL_HOOKS_DIR" ;;
esac
DECOY_HOOK_DST="$DECOY_REAL_HOOKS_DIR/pre-commit"

mkdir -p "$DECOY_REAL_HOOKS_DIR"
ln -s "$DECOY_WT/hooks/pre-commit" "$DECOY_HOOK_DST"

git -C "$DECOY_MAIN" worktree remove -f "$DECOY_WT" >/dev/null 2>&1

DECOY_OUT="$(uninstall_precommit_hook "$DECOY_MAIN" 2>&1)"

if [[ -L "$DECOY_HOOK_DST" ]]; then
  _pass "Test 23 (exact-match guard): a dangling hook rooted at a sibling '.worktrees-decoy' directory (shares a string PREFIX with the real '.worktrees' candidate, but is not it) is left untouched"
else
  _fail "Test 23 (exact-match guard regression): a dangling hook under a merely-prefix-sharing sibling directory was incorrectly removed - the candidate comparison is matching by prefix, not exact identity. Output: $DECOY_OUT"
fi

# ============================================================
# Test 24: danglingness-gate ordering (round-3 Major 1) - a RELATIVE
#          symlink target naming a LIVE, still-existing worktree (never
#          removed) must be PRESERVED, not deleted. Pre-fix, `[[ -e
#          "$target" ]]` was evaluated BEFORE the relative-target
#          anchoring block, so it tested existence against this test
#          script's own process CWD (never guaranteed to be hooks_dir) -
#          a live, correctly-resolving-from-hooks_dir target looked
#          "dangling" purely because of that mismatch, and was deleted.
#          Matched control: an ABSOLUTE live target (unaffected by the
#          anchoring reorder, since absolute paths skip that block
#          entirely) is verified separately in Test 25 below - together
#          the two isolate "the reorder fix" from "the danglingness gate
#          existing at all", the second of which round 3 also found
#          entirely uncovered (deleting the gate line outright still
#          passed 69/69 pre this test's addition).
# ============================================================

LIVE_MAIN="$TMP_ROOT/live-main-repo"
_make_fixture_repo "$LIVE_MAIN"
mkdir -p "$LIVE_MAIN/.claude/worktrees"

LIVE_WT="$LIVE_MAIN/.claude/worktrees/agent-LIVE"
git -C "$LIVE_MAIN" worktree add -q "$LIVE_WT" -b live-wt-test-branch >/dev/null 2>&1
# Deliberately NEVER removed - this worktree stays alive for the whole test.

LIVE_REAL_HOOKS_DIR="$(git -C "$LIVE_MAIN" rev-parse --git-path hooks)"
case "$LIVE_REAL_HOOKS_DIR" in
  /*) : ;;
  *) LIVE_REAL_HOOKS_DIR="$LIVE_MAIN/$LIVE_REAL_HOOKS_DIR" ;;
esac
LIVE_HOOK_DST="$LIVE_REAL_HOOKS_DIR/pre-commit"

LIVE_RELATIVE_TARGET="../../.claude/worktrees/agent-LIVE/hooks/pre-commit"
mkdir -p "$LIVE_REAL_HOOKS_DIR"
ln -s "$LIVE_RELATIVE_TARGET" "$LIVE_HOOK_DST"

# Fixture-correctness precondition 1: the relative target genuinely
# resolves when anchored against its own directory (hooks_dir) - i.e. it
# is a LIVE hook, not actually dangling.
if [[ -e "$LIVE_HOOK_DST" ]]; then
  _pass "Test 24 setup: relative live-worktree target resolves correctly via its own symlink directory (genuinely live, not dangling)"
else
  _fail "Test 24 setup: relative live-worktree target does NOT resolve at $LIVE_HOOK_DST -> $LIVE_RELATIVE_TARGET (fixture bug, not a library bug)"
fi

# Fixture-correctness precondition 2: this is the exact CWD-mismatch this
# Major exercises - the SAME relative string, tested bare against this
# script's own process CWD (never hooks_dir), reports FALSE. This is not
# a library call - it is establishing that the reproduction's precondition
# genuinely holds in this fixture, independent of any library code.
if [[ ! -e "$LIVE_RELATIVE_TARGET" ]]; then
  _pass "Test 24 setup: the bare relative target string does NOT resolve from this script's own CWD (confirms the CWD-mismatch precondition the round-3 Major depends on)"
else
  _fail "Test 24 setup: the bare relative target unexpectedly resolved from this script's CWD - fixture does not exercise the CWD-mismatch bug (or this script happens to be running from hooks_dir, which would be a coincidence, not a guarantee)"
fi

LIVE_OUT="$(uninstall_precommit_hook "$LIVE_MAIN" 2>&1)"
LIVE_RC=$?

if [[ $LIVE_RC -eq 0 ]]; then
  _pass "Test 24 (danglingness-gate ordering): uninstall_precommit_hook exits 0"
else
  _fail "Test 24 (danglingness-gate ordering): uninstall_precommit_hook exited $LIVE_RC. Output: $LIVE_OUT"
fi

if [[ -L "$LIVE_HOOK_DST" ]] && [[ -e "$LIVE_HOOK_DST" ]] && [[ "$(readlink "$LIVE_HOOK_DST")" == "$LIVE_RELATIVE_TARGET" ]]; then
  _pass "Test 24 (round-3 Major 1 fixed): a RELATIVE target naming a LIVE, still-existing worktree is PRESERVED, not deleted, by uninstall_precommit_hook. Output: $LIVE_OUT"
else
  _fail "Test 24 (round-3 Major 1 regression): a LIVE worktree's relative-target hook was deleted (readlink target after: $(readlink "$LIVE_HOOK_DST" 2>&1 || echo '<gone>')) - the danglingness gate misjudged a live, resolving target as dangling. Output: $LIVE_OUT"
fi

# ============================================================
# Test 25: danglingness-gate existence (round-3 Major 1's Minor sibling) -
#          an ABSOLUTE target naming the SAME live, still-existing
#          worktree must ALSO be preserved. Absolute targets skip the
#          relative-anchoring block entirely, so this case is UNAFFECTED
#          by the reorder fix in Test 24 - it isolates the danglingness
#          gate's own EXISTENCE (as opposed to its ordering): deleting
#          `[[ -e "$target" ]] && return 1` outright, regardless of where
#          it sits, reddens this test but not Test 24 alone (an absolute
#          live target was never subject to the CWD-mismatch bug - only a
#          missing gate would delete it).
# ============================================================

LIVE2_MAIN="$TMP_ROOT/live2-main-repo"
_make_fixture_repo "$LIVE2_MAIN"
mkdir -p "$LIVE2_MAIN/.claude/worktrees"

LIVE2_WT="$LIVE2_MAIN/.claude/worktrees/agent-LIVE2"
git -C "$LIVE2_MAIN" worktree add -q "$LIVE2_WT" -b live2-wt-test-branch >/dev/null 2>&1
# Deliberately never removed.

LIVE2_REAL_HOOKS_DIR="$(git -C "$LIVE2_MAIN" rev-parse --git-path hooks)"
case "$LIVE2_REAL_HOOKS_DIR" in
  /*) : ;;
  *) LIVE2_REAL_HOOKS_DIR="$LIVE2_MAIN/$LIVE2_REAL_HOOKS_DIR" ;;
esac
LIVE2_HOOK_DST="$LIVE2_REAL_HOOKS_DIR/pre-commit"

# Absolute target, naming the live worktree's OWN hooks/pre-commit - the
# same shape install_precommit_hook's KNOWN-RESIDUAL fallback produces,
# but for a worktree that has NOT been removed (still genuinely live).
mkdir -p "$LIVE2_REAL_HOOKS_DIR"
ln -s "$LIVE2_WT/hooks/pre-commit" "$LIVE2_HOOK_DST"

if [[ -e "$LIVE2_HOOK_DST" ]]; then
  _pass "Test 25 setup: absolute live-worktree target resolves correctly (genuinely live, not dangling)"
else
  _fail "Test 25 setup: absolute live-worktree target does NOT resolve at $LIVE2_HOOK_DST (fixture bug, not a library bug)"
fi

LIVE2_OUT="$(uninstall_precommit_hook "$LIVE2_MAIN" 2>&1)"

if [[ -L "$LIVE2_HOOK_DST" ]] && [[ -e "$LIVE2_HOOK_DST" ]]; then
  _pass "Test 25 (danglingness-gate existence): an ABSOLUTE target naming a LIVE, still-existing worktree is PRESERVED, not deleted. Output: $LIVE2_OUT"
else
  _fail "Test 25 (danglingness-gate existence regression): a LIVE worktree's absolute-target hook was deleted - the danglingness gate is missing or broken independent of ordering. Output: $LIVE2_OUT"
fi

# ============================================================
# Test 26: depth-2 evidence (round-3 Major 2) -
#          content/references/subagent-protocol.md:333-334's own
#          documented, copy-pasteable worktree-add command uses a
#          FEATURE_BRANCH value that, per this repo's branch-naming
#          convention (content/rules/conventions.md), takes the form
#          "feature/<name>" / "fix/<name>" / "chore/<name>" - so the
#          resulting worktree lands at
#          ".worktrees/feature/<name>-<unit_slug>", TWO path components
#          below ".worktrees", not one. A fixed single-strip
#          implementation would compute ".worktrees/feature" as the
#          candidate root, matching nothing, and leave a genuine orphan
#          uncleaned (visible only as a DANGLING warning, not silent -
#          Major, not Critical, per the round-3 finding).
# ============================================================

DEPTH2_MAIN="$TMP_ROOT/depth2-main-repo"
_make_fixture_repo "$DEPTH2_MAIN"
mkdir -p "$DEPTH2_MAIN/.worktrees"

DEPTH2_WT="$DEPTH2_MAIN/.worktrees/feature/my-thing-unit1"
git -C "$DEPTH2_MAIN" worktree add -q "$DEPTH2_WT" -b feature/my-thing-unit1 >/dev/null 2>&1

if [[ -d "$DEPTH2_WT/hooks" ]]; then
  _pass "Test 26 setup: depth-2 worktree fixture created at $DEPTH2_WT (two path components below .worktrees, matching subagent-protocol.md's own FEATURE_BRANCH=feature/<name> example)"
else
  _fail "Test 26 setup: depth-2 worktree fixture missing at $DEPTH2_WT (fixture setup bug)"
fi

DEPTH2_REAL_HOOKS_DIR="$(git -C "$DEPTH2_MAIN" rev-parse --git-path hooks)"
case "$DEPTH2_REAL_HOOKS_DIR" in
  /*) : ;;
  *) DEPTH2_REAL_HOOKS_DIR="$DEPTH2_MAIN/$DEPTH2_REAL_HOOKS_DIR" ;;
esac
DEPTH2_HOOK_DST="$DEPTH2_REAL_HOOKS_DIR/pre-commit"

mkdir -p "$DEPTH2_REAL_HOOKS_DIR"
ln -s "$DEPTH2_WT/hooks/pre-commit" "$DEPTH2_HOOK_DST"

git -C "$DEPTH2_MAIN" worktree remove -f "$DEPTH2_WT" >/dev/null 2>&1

DEPTH2_OUT="$(uninstall_precommit_hook "$DEPTH2_MAIN" 2>&1)"

if [[ ! -L "$DEPTH2_HOOK_DST" ]] && [[ ! -e "$DEPTH2_HOOK_DST" ]]; then
  _pass "Test 26 (round-3 Major 2 fixed, depth-2 evidence): a dangling hook naming an already-removed depth-2 '.worktrees/feature/<name>-<unit>' worktree is removed by the bounded upward search. Output: $DEPTH2_OUT"
else
  _fail "Test 26 (round-3 Major 2 regression): depth-2 dangling hook still present at $DEPTH2_HOOK_DST - a fixed single-strip container computation cannot reach '.worktrees' from two levels down. Output: $DEPTH2_OUT"
fi

# Also exercise the equivalent AGENTS.md:48 hazard for .agentic/worktrees -
# a branch name containing a slash (".agentic/worktrees/<branch-name>",
# where <branch-name> is itself "fix/my-thing") lands the worktree at
# depth 2 under .agentic/worktrees the same way.
DEPTH2B_MAIN="$TMP_ROOT/depth2b-main-repo"
_make_fixture_repo "$DEPTH2B_MAIN"
mkdir -p "$DEPTH2B_MAIN/.agentic/worktrees"

DEPTH2B_WT="$DEPTH2B_MAIN/.agentic/worktrees/fix/my-thing"
git -C "$DEPTH2B_MAIN" worktree add -q "$DEPTH2B_WT" -b fix/my-thing >/dev/null 2>&1

DEPTH2B_REAL_HOOKS_DIR="$(git -C "$DEPTH2B_MAIN" rev-parse --git-path hooks)"
case "$DEPTH2B_REAL_HOOKS_DIR" in
  /*) : ;;
  *) DEPTH2B_REAL_HOOKS_DIR="$DEPTH2B_MAIN/$DEPTH2B_REAL_HOOKS_DIR" ;;
esac
DEPTH2B_HOOK_DST="$DEPTH2B_REAL_HOOKS_DIR/pre-commit"

mkdir -p "$DEPTH2B_REAL_HOOKS_DIR"
ln -s "$DEPTH2B_WT/hooks/pre-commit" "$DEPTH2B_HOOK_DST"

git -C "$DEPTH2B_MAIN" worktree remove -f "$DEPTH2B_WT" >/dev/null 2>&1

DEPTH2B_OUT="$(uninstall_precommit_hook "$DEPTH2B_MAIN" 2>&1)"

if [[ ! -L "$DEPTH2B_HOOK_DST" ]] && [[ ! -e "$DEPTH2B_HOOK_DST" ]]; then
  _pass "Test 26 (depth-2 evidence, .agentic/worktrees/<slash-branch>): a dangling hook naming an already-removed depth-2 '.agentic/worktrees/fix/<name>' worktree (AGENTS.md:48's <branch-name> containing a slash) is removed. Output: $DEPTH2B_OUT"
else
  _fail "Test 26 (depth-2 evidence regression, .agentic/worktrees/<slash-branch>): dangling hook still present at $DEPTH2B_HOOK_DST. Output: $DEPTH2B_OUT"
fi

# ============================================================
# Test 27: reverse-prefix guard (round-3 Minor 1) - Test 23 above only
#          covers the FORWARD prefix direction (target is a superstring of
#          a real candidate). The REVERSE direction is a distinct mutation
#          class: `[[ "$canonical_candidate" == "$canonical_target_root"* ]]`
#          would match whenever the ANCESTOR being tested canonicalizes to
#          exactly <repo_dir> itself (or any ancestor of a real candidate),
#          since every real candidate's path literally starts with
#          <repo_dir> as a string prefix. Shipped code uses `==` (exact
#          identity, symmetric), which is correct; this test pins that a
#          reverse-direction prefix match would also be wrong, closing the
#          sibling mutation class Test 23 does not reach.
# ============================================================

REVPFX_MAIN="$TMP_ROOT/revpfx-main-repo"
_make_fixture_repo "$REVPFX_MAIN"
mkdir -p "$REVPFX_MAIN/.claude/worktrees"

# A dangling target whose "container" ancestor, at some depth of the
# bounded upward walk, canonicalizes to <repo_dir> ITSELF - a real,
# existing directory that is a PREFIX of every one of the four real
# candidates' own paths (e.g. "$REVPFX_MAIN/.claude/worktrees" starts with
# "$REVPFX_MAIN"). A reverse-prefix mutation would treat repo_dir itself
# as matching "$REVPFX_MAIN/.claude/worktrees"* purely by string prefix
# and delete a target rooted at the repo's OWN top-level directory - never
# a real worktree-container relationship.
REVPFX_ROGUE_DIR="$REVPFX_MAIN/some-unrelated-subdir"
mkdir -p "$REVPFX_ROGUE_DIR/hooks"

REVPFX_REAL_HOOKS_DIR="$(git -C "$REVPFX_MAIN" rev-parse --git-path hooks)"
case "$REVPFX_REAL_HOOKS_DIR" in
  /*) : ;;
  *) REVPFX_REAL_HOOKS_DIR="$REVPFX_MAIN/$REVPFX_REAL_HOOKS_DIR" ;;
esac
REVPFX_HOOK_DST="$REVPFX_REAL_HOOKS_DIR/pre-commit"

mkdir -p "$REVPFX_REAL_HOOKS_DIR"
ln -s "$REVPFX_ROGUE_DIR/hooks/pre-commit" "$REVPFX_HOOK_DST"

REVPFX_OUT="$(uninstall_precommit_hook "$REVPFX_MAIN" 2>&1)"

if [[ -L "$REVPFX_HOOK_DST" ]]; then
  _pass "Test 27 (reverse-prefix guard): a dangling target rooted at an unrelated top-level subdirectory of repo_dir (which is itself a string PREFIX of every real candidate) is left untouched"
else
  _fail "Test 27 (reverse-prefix guard regression): a dangling target under an unrelated repo-root subdirectory was incorrectly removed - the candidate comparison is matching by reverse prefix, not exact identity. Output: $REVPFX_OUT"
fi

# ============================================================
# Test 28: ".." escape guard (round 4, Minor 1) - a dangling target whose
#          SPELLING contains ".." segments after a real candidate name
#          must be resolved LEXICALLY before the ancestor walk, not
#          walked as a naive string-strip. The exact probe verified live
#          by the round-4 Skeptic:
#          "<repo>/.worktrees/../../../../../x/hooks/pre-commit" - a
#          target that PHYSICALLY resolves far outside the repo (this
#          fixture's own $TMP_ROOT, several levels above), but whose raw
#          string, naively stripped one component at a time, still passes
#          through "<repo>/.worktrees" - a real, canonicalizable
#          candidate - and pre-fix answered DELETE. Round 2's fixed
#          single-strip design answered KEEP for the same input (it never
#          walked far enough to reach ".worktrees" from this depth), so
#          round 3's bounded walk widened this class rather than closing
#          it.
# ============================================================

DOTDOT_MAIN="$TMP_ROOT/dotdot-main-repo"
_make_fixture_repo "$DOTDOT_MAIN"
mkdir -p "$DOTDOT_MAIN/.worktrees"

DOTDOT_REAL_HOOKS_DIR="$(git -C "$DOTDOT_MAIN" rev-parse --git-path hooks)"
case "$DOTDOT_REAL_HOOKS_DIR" in
  /*) : ;;
  *) DOTDOT_REAL_HOOKS_DIR="$DOTDOT_MAIN/$DOTDOT_REAL_HOOKS_DIR" ;;
esac
DOTDOT_HOOK_DST="$DOTDOT_REAL_HOOKS_DIR/pre-commit"

# The exact probe from the round-4 finding, anchored at this fixture's own
# repo - five ".." segments from ".worktrees" walk well above $TMP_ROOT
# itself, landing at some entirely unrelated "/x/hooks/pre-commit".
DOTDOT_ESCAPE_TARGET="$DOTDOT_MAIN/.worktrees/../../../../../x/hooks/pre-commit"
mkdir -p "$DOTDOT_REAL_HOOKS_DIR"
ln -s "$DOTDOT_ESCAPE_TARGET" "$DOTDOT_HOOK_DST"

DOTDOT_OUT="$(uninstall_precommit_hook "$DOTDOT_MAIN" 2>&1)"

if [[ -L "$DOTDOT_HOOK_DST" ]]; then
  _pass "Test 28 (round-4 Minor 1 fixed, ..-escape guard): a dangling target whose spelling contains '..' segments reaching far outside the repo is left untouched (KEEP), not deleted by a naive string-ancestor match. Output: $DOTDOT_OUT"
else
  _fail "Test 28 (round-4 Minor 1 regression, ..-escape guard): a '..'-escaping dangling target was incorrectly removed - the ancestor walk is matching a string-stripped ancestor that is not a genuine ancestor of the resolved path. Output: $DOTDOT_OUT"
fi

# ============================================================
# Test 29: empty-hooks_dir guard coverage (round 4, Minor 2) -
#          _precommit_is_orphaned_worktree_target's own manifest documents
#          "<hooks_dir> is empty and <target> is relative" as a
#          FAILS-CLOSED case, but nothing asserted it: deleting
#          `[[ -z "$hooks_dir" ]] && return 1` left the round-3 suite at
#          79/0 unchanged. Unreachable from any of this file's other
#          fixtures (uninstall_precommit_hook always resolves a real
#          hooks_dir before calling in), so this test calls the internal
#          helper directly with an empty hooks_dir - the only way to
#          exercise this documented invariant at all.
#
#          A weaker construction (an arbitrary relative target under an
#          arbitrary repo_dir) does NOT distinguish "guard present" from
#          "guard absent": with hooks_dir="", the unguarded concatenation
#          `target="$hooks_dir/$target"` still produces SOME absolute-
#          looking string ("/$target"), and an arbitrary such string
#          almost never happens to walk through a real candidate
#          directory regardless of the guard - so deleting the guard
#          would silently pass a naively-constructed test too. This
#          fixture instead constructs the relative target to be exactly
#          repo_dir's OWN path with its leading "/" stripped, followed by
#          a real candidate suffix - so the unguarded concatenation
#          "" + "/" + target reconstructs repo_dir's real, EXISTING
#          ".claude/worktrees" candidate exactly, which the guard's
#          absence would then let match.
# ============================================================

EMPTYHD_REPO="$TMP_ROOT/emptyhd-repo"
mkdir -p "$EMPTYHD_REPO/.claude/worktrees"

EMPTYHD_TARGET_RELATIVE="${EMPTYHD_REPO#/}/.claude/worktrees/some-nonexistent-worktree/hooks/pre-commit"

EMPTYHD_RESULT_RC=1
if _precommit_is_orphaned_worktree_target "$EMPTYHD_TARGET_RELATIVE" "$EMPTYHD_REPO" ""; then
  EMPTYHD_RESULT_RC=0
fi

if [[ $EMPTYHD_RESULT_RC -eq 1 ]]; then
  _pass "Test 29 (round-4 Minor 2 fixed, empty-hooks_dir guard): a relative target with an empty hooks_dir anchor fails closed (returns 1, not ours) even when the unguarded concatenation would reconstruct a real candidate path"
else
  _fail "Test 29 (round-4 Minor 2 regression, empty-hooks_dir guard): a relative target with an empty hooks_dir anchor was NOT rejected - the documented FAILS-CLOSED clause for this case has no effect"
fi

# ---- Results ----

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
