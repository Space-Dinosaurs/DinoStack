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
#     worktree AND that file actually exists there. This matters because
#     the hooks DIRECTORY (resolved by resolve_git_hooks_dir, per DS-58) is
#     shared across every worktree of a repo, but a worktree's own working
#     tree is ephemeral - pointing the shared hook at a path inside it
#     leaves a dangling symlink (which git silently treats as "no hook",
#     not an error) once that worktree is removed. Detects "linked
#     worktree" by comparing `git rev-parse --path-format=absolute
#     --git-dir` against `--git-common-dir`: equal means an ordinary (or
#     bare main) checkout, different means a linked worktree, in which case
#     the candidate target becomes "$(dirname <git-common-dir>)/hooks/pre-commit".
#     dirname(<git-common-dir>) is the common repo's own working tree ONLY
#     for an ordinary linked worktree - it is NOT for a bare repo +
#     `git worktree add`, `git init --separate-git-dir` + worktree, or a
#     submodule + worktree, where it resolves to some other directory with
#     no "hooks/pre-commit" of its own. The candidate is therefore gated on
#     the FILE existing (`[[ -f ]]`), not merely the directory - on any
#     resolution failure (not a git repo, git missing, common-dir has no
#     parent, candidate file does not exist, etc) falls back to
#     "<repo_dir>/hooks/pre-commit" - but that fallback itself is NOT
#     existence-gated (it is echoed unconditionally on every fallback
#     branch), so resolve_hook_src CAN still return a path that does not
#     exist, e.g. an ordinary (non-worktree) repo_dir with no
#     hooks/pre-commit file at all. Only the worktree-linked candidate is
#     existence-checked. install_precommit_hook's own `[[ -f "$hook_src" ]]`
#     guard is therefore load-bearing, not redundant belt-and-braces - do
#     not remove it on the assumption this function already guarantees an
#     existing source.
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
#     is a symlink pointing exactly at that resolved target OR at the
#     legacy unconditional "<repo_dir>/hooks/pre-commit" target that
#     pre-this-PR code (or this code from an ordinary, non-worktree
#     repo_dir) would have installed (the same ownership check the
#     original per-adapter uninstall blocks used, widened by exactly one
#     additional exact-match candidate - never deletes a foreign hook, a
#     real file, or a symlink pointing anywhere else). If hooks-dir
#     resolution fails for any reason, prints a non-fatal warning and
#     returns 0 - never aborts the caller.
#
# Upstream dependencies:
#   git (rev-parse --git-path / --git-dir / --git-common-dir), the COMMON
#   repo's hooks/pre-commit source file (the caller's own
#   $REPO_DIR/hooks/pre-commit for an ordinary checkout, but a different
#   worktree's ancestor repo when $REPO_DIR is a linked worktree - see
#   resolve_hook_src above), the caller's $AE_DRY_RUN variable (install
#   only), the caller's _ae_is_ours function (install only; duplicated
#   per-adapter helper).
#
# NOTE: bin/ds-doctor:783 independently hardcodes the same
#   "<repo_dir>/hooks/pre-commit is the expected symlink target" invariant
#   (`expected_src = doc.repo_dir / "hooks" / "pre-commit"`) with no shared
#   source between the two - harmless today only because ds-doctor's own
#   repo_dir/.git/hooks hardcode already fails first from a worktree, so
#   the two never actually disagree in a live run. If resolve_hook_src's
#   resolution logic changes again, check bin/ds-doctor for drift too.
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
#   - KNOWN RESIDUAL (not a regression - identical on origin/main): a bare
#     repo + `git worktree add`, `git init --separate-git-dir` + worktree,
#     and a submodule + worktree all fall back to the worktree's OWN
#     "hooks/pre-commit" (resolve_hook_src has no better source in these
#     three layouts - `git worktree list --porcelain` returns the gitdir,
#     not a working tree, in all three). That fallback target is still
#     INSIDE the worktree, so the installed symlink dangles the moment that
#     worktree is removed, same failure mode this module exists to prevent,
#     just not reachable from an ordinary linked worktree. Test 8 in
#     bin/tests/test_precommit_worktree.sh asserts this known-dangling
#     outcome directly rather than leaving it undocumented.
#   - Safe to source under set -euo pipefail; no top-level side effects
#     beyond the function definitions.
#
# Performance: up to three `git rev-parse` calls per invocation (one in
# resolve_git_hooks_dir, two in resolve_hook_src).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _precommit_canonical_repo_dir <repo_dir>
#   Internal helper (not part of the public API). Echoes the physical,
#   symlink-resolved, trailing-slash-free form of <repo_dir> via
#   `(cd <repo_dir> && pwd -P)`, or <repo_dir> unchanged if that cd fails
#   (non-existent dir - callers already tolerate an unresolvable repo_dir
#   downstream). resolve_hook_src's worktree-linked candidate is already
#   canonical (derived from `git rev-parse --path-format=absolute
#   --git-common-dir`), but its FALLBACK path and
#   uninstall_precommit_hook's legacy_hook_src are both built by string
#   concatenation on the raw repo_dir argument - two callers passing
#   different (but equivalent) spellings of the same directory (a trailing
#   slash, or a path through a symlinked parent) would otherwise produce
#   two different fallback/legacy strings for the same real hook, breaking
#   the exact-match comparisons in install/uninstall. Canonicalizing once,
#   consistently, closes that gap.
# ---------------------------------------------------------------------------
_precommit_canonical_repo_dir() {
  local d="$1"
  (cd "$d" 2>/dev/null && pwd -P) || echo "$d"
}

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
  repo_dir="$(_precommit_canonical_repo_dir "$repo_dir")"
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

  # Linked worktree: git-dir and git-common-dir diverge. In an ordinary
  # linked worktree, the common repo's own working tree is the parent of
  # the common .git dir. That assumption does NOT hold for a bare repo +
  # `git worktree add`, `git init --separate-git-dir` + worktree, or a
  # submodule + worktree - in all three, dirname(common_dir) is some other
  # directory (the bare repo's parent, the separate-gitdir's parent, or
  # `.git/modules/...`) that has no "hooks/pre-commit" of its own. Gate on
  # the SOURCE FILE actually existing there, not merely on the directory
  # existing (the directory always exists in those unsupported layouts,
  # which is what let this fall through undetected before) - if it does
  # not, degrade to the pre-fix fallback rather than emit a target that is
  # dangling from the moment it is installed.
  local common_worktree candidate
  common_worktree="$(dirname "$common_dir")"
  candidate="$common_worktree/hooks/pre-commit"
  if [[ -z "$common_worktree" || ! -f "$candidate" ]]; then
    echo "  ! could not resolve a real hooks/pre-commit under the common worktree ($common_worktree) - falling back to $fallback (non-fatal, but this hook WILL stop working once this worktree is removed - see Failure modes above)" >&2
    echo "$fallback"
    return 0
  fi

  echo "$candidate"
}

# ---------------------------------------------------------------------------
# install_precommit_hook <repo_dir>
#   See "Public API" above.
# ---------------------------------------------------------------------------
install_precommit_hook() {
  local repo_dir="$1"
  repo_dir="$(_precommit_canonical_repo_dir "$repo_dir")"
  local hook_src
  hook_src="$(resolve_hook_src "$repo_dir")"

  local hooks_dir
  if ! hooks_dir="$(resolve_git_hooks_dir "$repo_dir")"; then
    echo "  ! could not resolve git hooks directory - skipping pre-commit hook install (non-fatal)"
    return 0
  fi

  # This guard is LOAD-BEARING, not redundant belt-and-braces: only
  # resolve_hook_src's worktree-linked candidate is existence-gated - its
  # fallback ("$repo_dir/hooks/pre-commit") is echoed unconditionally on
  # every fallback branch and can itself be a path that does not exist
  # (e.g. an ordinary repo_dir with no hooks/pre-commit file at all).
  # Never create a link whose source is missing regardless of how it got
  # here - a dangling symlink is silently treated by git as "no hook",
  # exactly the failure mode this module exists to prevent.
  if [[ ! -f "$hook_src" ]]; then
    echo "  ! resolved pre-commit hook source does not exist: $hook_src - skipping pre-commit hook install (non-fatal)"
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
  repo_dir="$(_precommit_canonical_repo_dir "$repo_dir")"
  local hook_src
  hook_src="$(resolve_hook_src "$repo_dir")"

  # Legacy target: the pre-DS-58-worktree-fix (and pre-this-PR) symlink
  # target, "<repo_dir>/hooks/pre-commit" unconditionally, with no
  # worktree-awareness. install_precommit_hook heals a link pointing here
  # via _ae_is_ours, but uninstall previously had no equivalent - a hook
  # installed by the old code (or by this new code from an ordinary,
  # non-worktree repo_dir, where hook_src already equals this value) was
  # left orphaned by an uninstall that only recognised the new resolved
  # target. Accepting this SECOND exact target widens what uninstall will
  # remove to exactly: "the current resolved target" OR "the legacy
  # unconditional <repo_dir>/hooks/pre-commit target" - both still require
  # an EXACT match (per the existing `[[ "$current_target" == ... ]]`
  # ownership check), so a foreign hook pointing anywhere else, including a
  # different methodology checkout's hooks/pre-commit, is still left
  # untouched. It does NOT match a link pointing at some other project's
  # own hooks/pre-commit that happens to share a basename but not a path.
  local legacy_hook_src="$repo_dir/hooks/pre-commit"

  local hooks_dir
  if ! hooks_dir="$(resolve_git_hooks_dir "$repo_dir")"; then
    echo "  ! could not resolve git hooks directory - skipping pre-commit hook removal (non-fatal)"
    return 0
  fi

  local hook_dst="$hooks_dir/pre-commit"

  if [[ -L "$hook_dst" ]]; then
    local current_target
    current_target="$(readlink "$hook_dst")"
    if [[ "$current_target" == "$hook_src" || "$current_target" == "$legacy_hook_src" ]]; then
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
