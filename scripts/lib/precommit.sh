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
#          WHICH FILE is symlinked, not what the hook does when triggered
#          from a worktree commit, PROVIDED the primary checkout's own
#          hooks/pre-commit exists. install_precommit_hook verifies this
#          before writing or re-pointing any symlink (DS-152 round 2) and
#          refuses - loudly, non-fatally - to create a NEW dangling symlink
#          if the primary checkout's copy is itself missing (a pruned
#          worktree, or a primary checkout checked out to a commit that
#          predates hooks/pre-commit).
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
#     (via resolve_primary_checkout; on primary-checkout resolution failure,
#     warns loudly and falls back to repo_dir's own hooks/pre-commit) into
#     it. Honours the caller's $AE_DRY_RUN ("true"/"false") and reuses the
#     caller's _ae_is_ours function (must already be defined in the sourcing
#     script) to detect and re-point stale symlinks from another
#     methodology checkout. Verifies the resolved hook_src actually exists
#     before EVER writing or re-pointing a symlink to it - a fresh install
#     or a re-point onto a missing source warns loudly and skips (non-fatal)
#     rather than creating a new dangling symlink. Also warns loudly
#     (without aborting) whenever the PRE-EXISTING hook target is found
#     dangling, and whenever a re-point is refused because the existing
#     symlink is not "ours". If hooks-dir resolution fails for any reason,
#     prints a non-fatal warning and returns 0 - never aborts the caller.
#
#   uninstall_precommit_hook <repo_dir>
#     Resolves the real hooks dir via resolve_git_hooks_dir and removes the
#     pre-commit symlink there iff it is a symlink pointing exactly at the
#     primary checkout's "hooks/pre-commit" OR at a "legacy" pre-DS-152
#     target: some OTHER worktree's own hooks/pre-commit that still shares
#     repo_dir's git-common-dir (see _pc_is_legacy_sibling_hook) - the same
#     ownership check the original per-adapter uninstall blocks used,
#     extended so a hook installed by pre-DS-152 code from a worktree can
#     still be removed post-upgrade. Never deletes a foreign hook, a real
#     file, or a symlink pointing at an unrelated repo. If hooks-dir
#     resolution fails for any reason, prints a non-fatal warning and
#     returns 0 - never aborts the caller. On primary-checkout resolution
#     failure, warns loudly and falls back to repo_dir's own hooks/pre-commit
#     for the ownership comparison.
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
#   - `resolve_primary_checkout` fails (rev-parse error, a common-dir that
#     does not end in "/.git" - measured for --separate-git-dir and bare
#     linked worktrees): both install_precommit_hook and
#     uninstall_precommit_hook print a loud, non-fatal warning and fall
#     back to repo_dir's own hooks/pre-commit, matching the pre-DS-152
#     behaviour rather than aborting.
#   - The resolved hook_src does not exist (a pruned/moved primary
#     checkout, or one checked out to a commit without hooks/pre-commit):
#     install_precommit_hook warns loudly and skips the write (non-fatal) -
#     it never creates a NEW dangling symlink. A PRE-EXISTING dangling
#     symlink is separately detected and warned about every install run.
#   - Resolved hooks dir does not yet exist (fresh worktree/repo): created
#     via mkdir -p before the symlink is written (install only).
#   - Safe to source under set -euo pipefail; no top-level side effects
#     beyond the function definitions.
#
# Performance: up to three `git rev-parse` calls per install invocation
#   (hooks dir, git-dir, git-common-dir); up to two for uninstall (hooks
#   dir, plus one more when a legacy-target ownership check is needed).
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
# _pc_git_common_dir_abs <dir>
#   Internal helper (not part of the public API). Echoes the absolute
#   `git -C <dir> rev-parse --git-common-dir` for <dir>, normalising a
#   checkout-relative result to absolute exactly like resolve_git_hooks_dir
#   does. Returns non-zero and echoes nothing if <dir> is not a git checkout
#   (missing, deleted, or never a repo). Shared by resolve_primary_checkout
#   and _pc_is_legacy_sibling_hook so both compare common-dirs computed the
#   SAME way - avoids the raw-string mismatches a symlinked TMPDIR/HOME
#   component would otherwise cause between the two call sites.
# ---------------------------------------------------------------------------
_pc_git_common_dir_abs() {
  local dir="$1"
  local common_dir
  if ! common_dir="$(git -C "$dir" rev-parse --git-common-dir 2>/dev/null)" || [[ -z "$common_dir" ]]; then
    return 1
  fi
  case "$common_dir" in
    /*) : ;;
    *) common_dir="$dir/$common_dir" ;;
  esac
  echo "$common_dir"
}

# ---------------------------------------------------------------------------
# _pc_is_legacy_sibling_hook <target> <repo_common_dir>
#   Internal helper (not part of the public API). A pre-DS-152 install could
#   have symlinked the shared hook at ANY worktree's own
#   "<worktree>/hooks/pre-commit" (repo_dir itself, not necessarily the
#   primary checkout). Returns 0 (true) iff <target> ends in
#   "/hooks/pre-commit", the directory it hangs off of still exists, and
#   THAT directory's own git-common-dir matches <repo_common_dir> - i.e.
#   <target> is some worktree of the exact same repo family repo_dir
#   belongs to, regardless of which worktree wrote it or how its path was
#   originally spelled. Returns 1 (false) - never aborts - when <target>
#   does not match the suffix, the directory no longer exists (cannot be
#   verified), or its common-dir resolves to a different repo.
# ---------------------------------------------------------------------------
_pc_is_legacy_sibling_hook() {
  local target="$1" repo_common_dir="$2"
  case "$target" in
    */hooks/pre-commit) : ;;
    *) return 1 ;;
  esac
  local target_repo_dir="${target%/hooks/pre-commit}"
  [[ -d "$target_repo_dir" ]] || return 1
  local target_common_dir
  target_common_dir="$(_pc_git_common_dir_abs "$target_repo_dir")" || return 1
  [[ "$target_common_dir" == "$repo_common_dir" ]]
}

# ---------------------------------------------------------------------------
# resolve_primary_checkout <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
resolve_primary_checkout() {
  local repo_dir="$1"
  local common_dir git_dir canonical_repo_dir

  common_dir="$(_pc_git_common_dir_abs "$repo_dir")" || return 1
  if ! git_dir="$(git -C "$repo_dir" rev-parse --git-dir 2>/dev/null)" || [[ -z "$git_dir" ]]; then
    return 1
  fi

  # `--git-dir` can be checkout-relative in a normal (non-worktree) repo;
  # normalise to absolute, matching _pc_git_common_dir_abs's own
  # normalisation of --git-common-dir above.
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
    # Resolution failed (e.g. a --separate-git-dir or bare linked worktree)
    # - warn loudly and fall back to repo_dir's own hooks/pre-commit rather
    # than aborting (pre-DS-152 behaviour).
    echo "  ! could not resolve the primary checkout for $repo_dir - falling back to its own hooks/pre-commit"
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
      # checkout, never at repo_dir directly. Never write a NEW symlink at a
      # source that does not exist - that would trade one dangling target
      # for another.
      if [[ ! -e "$hook_src" ]]; then
        echo "  ! cannot re-point pre-commit hook - primary checkout's hook source is missing: $hook_src (leaving existing symlink untouched, non-fatal)"
      elif [[ "$AE_DRY_RUN" == "true" ]]; then
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
    # Never symlink to a source that does not exist - a fresh install must
    # not create a new dangling hook (DS-152 round 2).
    if [[ ! -e "$hook_src" ]]; then
      echo "  ! cannot install pre-commit hook - primary checkout's hook source is missing: $hook_src (non-fatal, skipping)"
    elif [[ "$AE_DRY_RUN" == "true" ]]; then
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
    echo "  ! could not resolve the primary checkout for $repo_dir - falling back to its own hooks/pre-commit"
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
      # Not a match against the primary checkout's own hook_src - check
      # whether it is a "legacy" pre-DS-152 target: some other worktree of
      # the exact same repo family, which older install_precommit_hook code
      # would have symlinked directly.
      local repo_common_dir
      if repo_common_dir="$(_pc_git_common_dir_abs "$repo_dir" 2>/dev/null)" \
        && _pc_is_legacy_sibling_hook "$current_target" "$repo_common_dir"; then
        rm "$hook_dst"
        echo "  - pre-commit hook removed (legacy pre-DS-152 target: $current_target)"
      else
        echo "  = pre-commit hook points elsewhere: $current_target - not ours, skipping"
      fi
    fi
  elif [[ -e "$hook_dst" ]]; then
    echo "  = pre-commit hook is a real file - not removing"
  else
    echo "  = pre-commit hook not found - nothing to do"
  fi
}
