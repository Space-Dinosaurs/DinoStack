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
#          The install side also always sources the hook BODY from the
#          PRIMARY checkout, never from the invoking repo_dir directly
#          (DS-152). The shared hooks dir (resolved by resolve_git_hooks_dir)
#          is common to every worktree of a repo, so a symlink written while
#          running from an ephemeral/scratch worktree (e.g. a Skeptic
#          QA-regression scratch dir) would otherwise repoint the ONE shared
#          hook at a soon-to-be-deleted path, dangling it for the primary
#          checkout and every other worktree the moment that scratch
#          worktree is removed. hooks/pre-commit's own adapter-build section
#          early-exits in any worktree context (see its
#          `git rev-parse --git-common-dir` != `--git-dir` check), so the
#          static-analysis prefix that actually runs when invoked via a
#          worktree's own copy is identical to the primary checkout's copy
#          at the same commit - sourcing from the primary checkout changes
#          WHICH FILE is symlinked, never what the hook does when triggered
#          from a worktree commit.
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
#   resolve_primary_checkout <repo_dir>
#     Echoes the durable primary checkout for <repo_dir>: <repo_dir> itself
#     when it is not a linked worktree (`--git-dir` == `--git-common-dir`),
#     otherwise the parent of the shared ".git" directory that
#     `--git-common-dir` points at (i.e. the main worktree, not whichever
#     linked worktree repo_dir happens to be). Returns non-zero and echoes
#     nothing on resolution failure.
#
#   install_precommit_hook <repo_dir>
#     Resolves the real hooks dir via resolve_git_hooks_dir, mkdir -p's it
#     if needed, and symlinks the PRIMARY checkout's hooks/pre-commit
#     (via resolve_primary_checkout; falls back to repo_dir's own
#     hooks/pre-commit if primary-checkout resolution fails) into it.
#     Honours the caller's $AE_DRY_RUN ("true"/"false") and reuses the
#     caller's _ae_is_ours function (must already be defined in the sourcing
#     script) to detect and re-point stale symlinks from another
#     methodology checkout. Warns loudly (without aborting) whenever the
#     existing hook target is found dangling, and whenever a re-point is
#     refused because the existing symlink is not "ours". If hooks-dir
#     resolution fails for any reason, prints a non-fatal warning and
#     returns 0 - never aborts the caller.
#
#   uninstall_precommit_hook <repo_dir>
#     Resolves the real hooks dir via resolve_git_hooks_dir and removes the
#     pre-commit symlink there iff it is a symlink pointing exactly at the
#     primary checkout's "hooks/pre-commit" (the same ownership check the
#     original per-adapter uninstall blocks used - never deletes a foreign
#     hook, a real file, or a symlink pointing elsewhere). If hooks-dir
#     resolution fails for any reason, prints a non-fatal warning and
#     returns 0 - never aborts the caller.
#
# Upstream dependencies:
#   git (rev-parse --git-path/--git-dir/--git-common-dir), the primary
#   checkout's hooks/pre-commit source file, the caller's $AE_DRY_RUN
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
#   - `resolve_primary_checkout` fails (rev-parse error, or a common-dir
#     that does not end in "/.git"): install_precommit_hook falls back to
#     repo_dir's own hooks/pre-commit, matching the pre-DS-152 behaviour
#     rather than aborting.
#   - Resolved hooks dir does not yet exist (fresh worktree/repo): created
#     via mkdir -p before the symlink is written (install only).
#   - Safe to source under set -euo pipefail; no top-level side effects
#     beyond the function definitions.
#
# Performance: up to three `git rev-parse` calls per install invocation
#   (hooks dir, git-dir, git-common-dir); one for uninstall.
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
# resolve_primary_checkout <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
resolve_primary_checkout() {
  local repo_dir="$1"
  local common_dir git_dir canonical_repo_dir

  if ! common_dir="$(git -C "$repo_dir" rev-parse --git-common-dir 2>/dev/null)" || [[ -z "$common_dir" ]]; then
    return 1
  fi
  if ! git_dir="$(git -C "$repo_dir" rev-parse --git-dir 2>/dev/null)" || [[ -z "$git_dir" ]]; then
    return 1
  fi

  # Both `--git-common-dir` and `--git-dir` can be checkout-relative in a
  # normal (non-worktree) repo; normalise to absolute either way, matching
  # resolve_git_hooks_dir's own normalisation above.
  case "$common_dir" in
    /*) : ;;
    *) common_dir="$repo_dir/$common_dir" ;;
  esac
  case "$git_dir" in
    /*) : ;;
    *) git_dir="$repo_dir/$git_dir" ;;
  esac

  if [[ "$common_dir" == "$git_dir" ]]; then
    # repo_dir is not a linked worktree (or is itself the primary checkout)
    # - it is authoritative for its own hook source. Canonicalise via
    # `pwd -P` (resolving any symlink components, e.g. macOS's
    # /tmp -> /private/tmp or /var/folders -> /private/var/folders) so this
    # branch's output is comparable, byte-for-byte, with the linked-worktree
    # branch below - which is unavoidably canonicalised because that is what
    # `git rev-parse --git-common-dir` returns for a worktree. Without this,
    # installing once from a worktree (canonical form) and again directly
    # from the primary checkout (raw form) would compute two DIFFERENT
    # hook_src strings for the same real directory, and the "already linked"
    # equality check below would spuriously treat the hook as stale forever.
    if canonical_repo_dir="$(cd "$repo_dir" 2>/dev/null && pwd -P)" && [[ -n "$canonical_repo_dir" ]]; then
      echo "$canonical_repo_dir"
    else
      echo "$repo_dir"
    fi
    return 0
  fi

  # repo_dir is a linked worktree; the primary checkout is the parent of the
  # shared ".git" directory that the common dir points at - i.e. the main
  # worktree, not whichever linked worktree repo_dir happens to be.
  case "$common_dir" in
    */.git) echo "${common_dir%/.git}" ;;
    *) return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# install_precommit_hook <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
install_precommit_hook() {
  local repo_dir="$1"

  local primary_checkout
  if ! primary_checkout="$(resolve_primary_checkout "$repo_dir")"; then
    # Resolution failed - fall back to repo_dir's own hooks/pre-commit
    # rather than aborting (pre-DS-152 behaviour).
    primary_checkout="$repo_dir"
  fi
  local hook_src="$primary_checkout/hooks/pre-commit"

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

    if [[ ! -e "$hook_dst" ]]; then
      echo "  ! existing pre-commit hook symlink is dangling (target missing): $current_target"
    fi

    if [[ "$current_target" == "$hook_src" ]]; then
      echo "  = pre-commit hook already linked"
    elif _ae_is_ours "$hook_dst"; then
      # Stale symlink pointing to another methodology checkout (including a
      # now-deleted ephemeral worktree) - re-point at the durable primary
      # checkout, never at repo_dir directly.
      if [[ "$AE_DRY_RUN" == "true" ]]; then
        echo "  ~ pre-commit hook (would re-point to primary checkout)"
      else
        ln -sfn "$hook_src" "$hook_dst"
        echo "  ~ pre-commit hook (re-pointed to primary checkout)"
      fi
    else
      if [[ "$AE_DRY_RUN" == "true" ]]; then
        echo "  ! pre-commit hook (would skip: symlink points outside methodology checkout: $current_target)"
      else
        echo "  ! pre-commit hook points elsewhere: $current_target - skipping (repair manually if this is a dangling methodology hook)"
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

  local primary_checkout
  if ! primary_checkout="$(resolve_primary_checkout "$repo_dir")"; then
    primary_checkout="$repo_dir"
  fi
  local hook_src="$primary_checkout/hooks/pre-commit"

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
