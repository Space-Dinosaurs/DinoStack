# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Shared pre-commit hook install/uninstall logic sourced by every
#          adapter installer/uninstaller that wires the methodology's git
#          pre-commit hook. Resolves the REAL git hooks directory instead of
#          hardcoding "$REPO_DIR/.git/hooks" - the hardcoded form breaks when
#          REPO_DIR is a git worktree, where ".git" is a file (a gitdir
#          pointer) and not a directory (DS-58, both the install side and
#          the symmetric uninstall side).
#
# Public API:
#   resolve_git_hooks_dir <repo_dir>
#     Echoes the absolute real git hooks dir for <repo_dir> via
#     `git -C <repo_dir> rev-parse --git-path hooks` (this correctly follows
#     a worktree's gitdir pointer back to the common repo's hooks dir),
#     normalising a checkout-relative result to absolute. Returns non-zero
#     and echoes nothing on resolution failure (not a git repo, git
#     missing, etc).
#
#   install_precommit_hook <repo_dir>
#     Resolves the real hooks dir via resolve_git_hooks_dir, mkdir -p's it
#     if needed, and symlinks hooks/pre-commit into it. Honours the
#     caller's $AE_DRY_RUN ("true"/"false") and reuses the caller's
#     _ae_is_ours function (must already be defined in the sourcing script)
#     to detect and re-point stale symlinks from another methodology
#     checkout. If hooks-dir resolution fails for any reason, prints a
#     non-fatal warning and returns 0 - never aborts the caller.
#
#   uninstall_precommit_hook <repo_dir>
#     Resolves the real hooks dir via resolve_git_hooks_dir and removes the
#     pre-commit symlink there iff it is a symlink pointing exactly at
#     "<repo_dir>/hooks/pre-commit" (the same ownership check the original
#     per-adapter uninstall blocks used - never deletes a foreign hook, a
#     real file, or a symlink pointing elsewhere). If hooks-dir resolution
#     fails for any reason, prints a non-fatal warning and returns 0 -
#     never aborts the caller.
#
# Upstream dependencies:
#   git (rev-parse --git-path), the caller's $REPO_DIR/hooks/pre-commit
#   source file, the caller's $AE_DRY_RUN variable (install only), the
#   caller's _ae_is_ours function (install only; duplicated per-adapter
#   helper).
#
# Downstream consumers:
#   .claude/install.sh, .cursor/install.sh, .opencode/install.sh,
#   .claude/uninstall.sh, .cursor/uninstall.sh, .opencode/uninstall.sh
#   (the only adapters that install/uninstall a pre-commit hook).
#
# Failure modes:
#   - `git rev-parse --git-path hooks` fails (not a git repo, git missing):
#     resolve_git_hooks_dir returns 1; both install_precommit_hook and
#     uninstall_precommit_hook print a non-fatal warning and return 0.
#   - Resolved hooks dir does not yet exist (fresh worktree/repo): created
#     via mkdir -p before the symlink is written (install only).
#   - Safe to source under set -euo pipefail; no top-level side effects
#     beyond the function definitions.
#
# Performance: one `git rev-parse` call per invocation.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# resolve_git_hooks_dir <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
resolve_git_hooks_dir() {
  local repo_dir="$1"
  local hooks_dir

  if ! hooks_dir="$(git -C "$repo_dir" rev-parse --git-path hooks 2>/dev/null)" || [[ -z "$hooks_dir" ]]; then
    return 1
  fi

  # `--git-path` returns a path relative to repo_dir in a normal checkout,
  # but an absolute path (via the worktree's common-dir) inside a worktree.
  # Normalise to absolute either way.
  case "$hooks_dir" in
    /*) : ;;
    *) hooks_dir="$repo_dir/$hooks_dir" ;;
  esac

  echo "$hooks_dir"
}

# ---------------------------------------------------------------------------
# install_precommit_hook <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
install_precommit_hook() {
  local repo_dir="$1"
  local hook_src="$repo_dir/hooks/pre-commit"

  local hooks_dir
  if ! hooks_dir="$(resolve_git_hooks_dir "$repo_dir")"; then
    echo "  ! could not resolve git hooks directory - skipping pre-commit hook install (non-fatal)"
    return 0
  fi

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

# ---------------------------------------------------------------------------
# uninstall_precommit_hook <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
uninstall_precommit_hook() {
  local repo_dir="$1"
  local hook_src="$repo_dir/hooks/pre-commit"

  local hooks_dir
  if ! hooks_dir="$(resolve_git_hooks_dir "$repo_dir")"; then
    echo "  ! could not resolve git hooks directory - skipping pre-commit hook removal (non-fatal)"
    return 0
  fi

  local hook_dst="$hooks_dir/pre-commit"

  if [[ -L "$hook_dst" ]]; then
    local current_target
    current_target="$(readlink "$hook_dst")"
    if [[ "$current_target" == "$hook_src" ]]; then
      rm "$hook_dst"
      echo "  - pre-commit hook removed"
    else
      echo "  = pre-commit hook points elsewhere: $current_target - not ours, skipping"
    fi
  elif [[ -e "$hook_dst" ]]; then
    echo "  = pre-commit hook is a real file - not removing"
  else
    echo "  = pre-commit hook not found - nothing to do"
  fi
}
