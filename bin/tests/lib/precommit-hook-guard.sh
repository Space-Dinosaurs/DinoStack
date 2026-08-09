# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Shared save/restore guard for bin/tests/*.sh scripts that run a
#          REAL adapter uninstall.sh (or install.sh) against the live repo
#          checkout - REPO_DIR unfaked - while only $HOME is sandboxed.
#          scripts/lib/precommit.sh resolves the git hooks directory via
#          `git -C <repo_dir> rev-parse --git-path hooks`, which is entirely
#          independent of $HOME. A test that fakes only $HOME still lets
#          uninstall_precommit_hook delete this checkout's REAL
#          <repo>/.git/hooks/pre-commit symlink (or, from inside a linked
#          worktree, the common repo's hooks dir) - the deletion is never
#          restored on its own. This guard snapshots the real hook before
#          the run and restores it unconditionally afterward via the
#          caller's own EXIT trap.
#
# Public API:
#   precommit_hook_guard_save <repo_dir>
#     Resolves the real git hooks dir for <repo_dir> and snapshots
#     <hooks_dir>/pre-commit: whether it exists, its symlink target (if a
#     symlink), or a byte-for-byte backup copy (if a regular file). Sets
#     the module-global _PCG_* state consumed by
#     precommit_hook_guard_restore. Safe to call when no hook exists, and
#     safe to call when hooks-dir resolution fails (not a git repo) - both
#     are treated as "nothing to protect".
#
#   precommit_hook_guard_restore
#     Restores whatever precommit_hook_guard_save observed: re-creates the
#     symlink, restores the backed-up regular file, or removes whatever is
#     there now if nothing existed before the save. Idempotent - safe to
#     call even if the hook was never mutated, and safe to call more than
#     once (a second call is a no-op once state has been consumed). Removes
#     its own temp backup file. Never aborts under `set -uo pipefail` - all
#     conditionals use `[[ ]]` with explicit defaults.
#
# Upstream dependencies: git, mktemp, cp, readlink, ln. Depends on the
#   caller having already sourced this file before calling either function.
#
# Downstream consumers: bin/tests/test_uninstall_ds_prefix.sh,
#   bin/tests/test_hooks_snapshot_migration.sh (both invoke a real
#   .claude/uninstall.sh against the live checkout with only $HOME faked);
#   .claude/tests/install-converge.test.sh and
#   .cursor/tests/install-converge.test.sh (both invoke a real
#   .claude/install.sh or .cursor/install.sh / .opencode/install.sh against
#   the live checkout with only $HOME faked); bin/tests/test_local_bin_ds_prefix_install.sh
#   (Test 2 invokes a real .claude/install.sh against the live checkout with
#   only $HOME faked).
#
# Failure modes: if `git rev-parse --git-path hooks` fails to resolve (not
#   a git repo, git missing), save/restore are no-ops - there is nothing to
#   protect in that case, consistent with scripts/lib/precommit.sh's own
#   non-fatal failure mode.
#
# Performance: one `git rev-parse` + at most one `cp` per save call.
# ---------------------------------------------------------------------------

_PCG_HOOK_PATH=""
_PCG_EXISTED=0
_PCG_SYMLINK_TARGET=""
_PCG_BACKUP_FILE=""

# ---------------------------------------------------------------------------
# precommit_hook_guard_save <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
precommit_hook_guard_save() {
  local repo_dir="$1"
  local hooks_dir

  _PCG_HOOK_PATH=""
  _PCG_EXISTED=0
  _PCG_SYMLINK_TARGET=""
  _PCG_BACKUP_FILE=""

  if ! hooks_dir="$(git -C "$repo_dir" rev-parse --git-path hooks 2>/dev/null)" || [[ -z "$hooks_dir" ]]; then
    return 0
  fi

  # Same normalisation as scripts/lib/precommit.sh's resolve_git_hooks_dir:
  # --git-path is relative in a normal checkout, absolute from a worktree.
  case "$hooks_dir" in
    /*) : ;;
    *) hooks_dir="$repo_dir/$hooks_dir" ;;
  esac

  _PCG_HOOK_PATH="$hooks_dir/pre-commit"

  if [[ -L "$_PCG_HOOK_PATH" ]]; then
    _PCG_EXISTED=1
    _PCG_SYMLINK_TARGET="$(readlink "$_PCG_HOOK_PATH")"
  elif [[ -e "$_PCG_HOOK_PATH" ]]; then
    _PCG_EXISTED=1
    _PCG_BACKUP_FILE="$(mktemp)"
    cp -p "$_PCG_HOOK_PATH" "$_PCG_BACKUP_FILE"
  fi
}

# ---------------------------------------------------------------------------
# precommit_hook_guard_restore
#   See "Public API" above.
# ---------------------------------------------------------------------------
precommit_hook_guard_restore() {
  if [[ -z "$_PCG_HOOK_PATH" ]]; then
    return 0
  fi

  if [[ "$_PCG_EXISTED" -eq 1 ]]; then
    if [[ -n "$_PCG_SYMLINK_TARGET" ]]; then
      ln -sfn "$_PCG_SYMLINK_TARGET" "$_PCG_HOOK_PATH"
    elif [[ -n "$_PCG_BACKUP_FILE" && -f "$_PCG_BACKUP_FILE" ]]; then
      cp -p "$_PCG_BACKUP_FILE" "$_PCG_HOOK_PATH"
    fi
  else
    if [[ -e "$_PCG_HOOK_PATH" || -L "$_PCG_HOOK_PATH" ]]; then
      rm -f "$_PCG_HOOK_PATH"
    fi
  fi

  if [[ -n "$_PCG_BACKUP_FILE" && -f "$_PCG_BACKUP_FILE" ]]; then
    rm -f "$_PCG_BACKUP_FILE"
  fi
  _PCG_BACKUP_FILE=""
  _PCG_HOOK_PATH=""
}
