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
#   resolve_hook_src <repo_dir>
#     Echoes the symlink TARGET path for the hooks/pre-commit source file -
#     "<repo_dir>/hooks/pre-commit" for an ordinary checkout (byte-for-byte
#     identical to the original DS-58 behavior), but the COMMON repo's
#     "<main worktree>/hooks/pre-commit" when <repo_dir> is a linked
#     worktree. This matters because the hooks DIRECTORY (resolved by
#     resolve_git_hooks_dir, per DS-58) is shared across every worktree of a
#     repo, but a worktree's own working tree is ephemeral - pointing the
#     shared hook at a path inside it leaves a dangling symlink (which git
#     silently treats as "no hook", not an error) once that worktree is
#     removed. Detects "linked worktree" by comparing
#     `git rev-parse --path-format=absolute --git-dir` against
#     `--git-common-dir`: equal means an ordinary (or bare main) checkout,
#     different means a linked worktree, in which case the target becomes
#     "$(dirname <git-common-dir>)/hooks/pre-commit". On any resolution
#     failure (not a git repo, git missing, common-dir has no parent, etc)
#     falls back to "<repo_dir>/hooks/pre-commit" unchanged - never errors.
#
#   install_precommit_hook <repo_dir>
#     Resolves the real hooks dir via resolve_git_hooks_dir and the symlink
#     source via resolve_hook_src, mkdir -p's the hooks dir if needed, and
#     symlinks the resolved source into it. Honours the caller's
#     $AE_DRY_RUN ("true"/"false") and reuses the caller's _ae_is_ours
#     function (must already be defined in the sourcing script) to detect
#     and re-point stale symlinks from another methodology checkout. An
#     existing symlink that already matches the resolved source (including
#     an already-correctly-repointed worktree install) is left untouched
#     (reported as "already linked", not rewritten). If hooks-dir
#     resolution fails for any reason, prints a non-fatal warning and
#     returns 0 - never aborts the caller.
#
#   uninstall_precommit_hook <repo_dir>
#     Resolves the real hooks dir via resolve_git_hooks_dir and the expected
#     symlink target via resolve_hook_src (the same resolution
#     install_precommit_hook used, so a worktree-repointed symlink is
#     recognised as ours), and removes the pre-commit symlink there iff it
#     is a symlink pointing exactly at that resolved target (the same
#     ownership check the original per-adapter uninstall blocks used -
#     never deletes a foreign hook, a real file, or a symlink pointing
#     elsewhere). If hooks-dir resolution fails for any reason, prints a
#     non-fatal warning and returns 0 - never aborts the caller.
#
# Upstream dependencies:
#   git (rev-parse --git-path / --git-dir / --git-common-dir), the caller's
#   $REPO_DIR/hooks/pre-commit source file, the caller's $AE_DRY_RUN
#   variable (install only), the caller's _ae_is_ours function (install
#   only; duplicated per-adapter helper).
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
#   - `git rev-parse --git-dir`/`--git-common-dir` fails, or the common
#     dir's parent can't be determined: resolve_hook_src falls back to
#     "<repo_dir>/hooks/pre-commit" (today's pre-worktree-fix behavior) -
#     never propagates a failure to the caller.
#   - Resolved hooks dir does not yet exist (fresh worktree/repo): created
#     via mkdir -p before the symlink is written (install only).
#   - Safe to source under set -euo pipefail; no top-level side effects
#     beyond the function definitions.
#
# Performance: up to three `git rev-parse` calls per invocation (one in
# resolve_git_hooks_dir, two in resolve_hook_src).
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
# resolve_hook_src <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
resolve_hook_src() {
  local repo_dir="$1"
  local fallback="$repo_dir/hooks/pre-commit"

  local git_dir common_dir
  if ! git_dir="$(git -C "$repo_dir" rev-parse --path-format=absolute --git-dir 2>/dev/null)" || [[ -z "$git_dir" ]]; then
    echo "$fallback"
    return 0
  fi
  if ! common_dir="$(git -C "$repo_dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || [[ -z "$common_dir" ]]; then
    echo "$fallback"
    return 0
  fi

  if [[ "$git_dir" == "$common_dir" ]]; then
    # Ordinary checkout (or the main worktree of a repo that also has
    # linked worktrees) - unchanged from the original DS-58 behavior.
    echo "$fallback"
    return 0
  fi

  # Linked worktree: git-dir and git-common-dir diverge. The common repo's
  # own working tree is the parent of the common .git dir - use ITS
  # hooks/pre-commit as the symlink target so it outlives this worktree.
  local common_worktree
  common_worktree="$(dirname "$common_dir")"
  if [[ -z "$common_worktree" || ! -d "$common_worktree" ]]; then
    echo "$fallback"
    return 0
  fi

  echo "$common_worktree/hooks/pre-commit"
}

# ---------------------------------------------------------------------------
# install_precommit_hook <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
install_precommit_hook() {
  local repo_dir="$1"
  local hook_src
  hook_src="$(resolve_hook_src "$repo_dir")"

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
  local hook_src
  hook_src="$(resolve_hook_src "$repo_dir")"

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
