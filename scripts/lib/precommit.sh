# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Shared pre-commit hook installer sourced by every adapter
#          installer that wires the methodology's git pre-commit hook.
#          Resolves the REAL git hooks directory instead of hardcoding
#          "$REPO_DIR/.git/hooks" - the hardcoded form breaks when REPO_DIR
#          is a git worktree, where ".git" is a file (a gitdir pointer) and
#          not a directory (DS-58).
#
# Public API:
#   install_precommit_hook <repo_dir>
#     Resolves the real hooks dir via `git -C <repo_dir> rev-parse
#     --git-path hooks` (this correctly follows a worktree's gitdir pointer
#     back to the common repo's hooks dir), mkdir -p's it if needed, and
#     symlinks hooks/pre-commit into it. Honours the caller's $AE_DRY_RUN
#     ("true"/"false") and reuses the caller's _ae_is_ours function (must
#     already be defined in the sourcing script) to detect and re-point
#     stale symlinks from another methodology checkout. If hooks-dir
#     resolution fails for any reason, prints a non-fatal warning and
#     returns 0 - never aborts the caller.
#
# Upstream dependencies:
#   git (rev-parse --git-path), the caller's $REPO_DIR/hooks/pre-commit
#   source file, the caller's $AE_DRY_RUN variable, the caller's
#   _ae_is_ours function (duplicated per-adapter helper).
#
# Downstream consumers:
#   .claude/install.sh, .cursor/install.sh, .opencode/install.sh
#   (the only adapters that install a pre-commit hook).
#
# Failure modes:
#   - `git rev-parse --git-path hooks` fails (not a git repo, git missing):
#     prints a non-fatal warning, returns 0, install.sh continues.
#   - Resolved hooks dir does not yet exist (fresh worktree/repo): created
#     via mkdir -p before the symlink is written.
#   - Safe to source under set -euo pipefail; no top-level side effects
#     beyond the function definition.
#
# Performance: one `git rev-parse` call per invocation.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# install_precommit_hook <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
install_precommit_hook() {
  local repo_dir="$1"
  local hook_src="$repo_dir/hooks/pre-commit"

  local hooks_dir
  if ! hooks_dir="$(git -C "$repo_dir" rev-parse --git-path hooks 2>/dev/null)" || [[ -z "$hooks_dir" ]]; then
    echo "  ! could not resolve git hooks directory - skipping pre-commit hook install (non-fatal)"
    return 0
  fi
  # `--git-path` returns a path relative to repo_dir in a normal checkout,
  # but an absolute path (via the worktree's common-dir) inside a worktree.
  # Normalise to absolute either way.
  case "$hooks_dir" in
    /*) : ;;
    *) hooks_dir="$repo_dir/$hooks_dir" ;;
  esac

  mkdir -p "$hooks_dir"
  local hook_dst="$hooks_dir/pre-commit"

  if [[ -L "$hook_dst" ]]; then
    local current_target
    current_target="$(readlink "$hook_dst")"
    if [[ "$current_target" == "$hook_src" ]]; then
      echo "  = pre-commit hook already linked"
    elif _ae_is_ours "$hook_dst"; then
      # Stale symlink pointing to another methodology checkout - re-point it.
      if [[ "$AE_DRY_RUN" == "true" ]]; then
        echo "  ~ pre-commit hook (would re-point to repo_dir)"
      else
        ln -sfn "$hook_src" "$hook_dst"
        echo "  ~ pre-commit hook (re-pointed to repo_dir)"
      fi
    else
      if [[ "$AE_DRY_RUN" == "true" ]]; then
        echo "  ! pre-commit hook (would skip: symlink points outside methodology checkout: $current_target)"
      else
        echo "  ! pre-commit hook points elsewhere: $current_target - skipping"
      fi
    fi
  elif [[ -e "$hook_dst" ]]; then
    echo "  ! pre-commit hook is a real file (not a symlink) - skipping to preserve existing hook"
  else
    if [[ "$AE_DRY_RUN" == "true" ]]; then
      echo "  + pre-commit hook (would create)"
    else
      ln -s "$hook_src" "$hook_dst"
      echo "  + pre-commit hook installed"
    fi
  fi
}
