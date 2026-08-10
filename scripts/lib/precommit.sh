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
#     repo_dir) would have installed - checked against BOTH the RAW
#     repo_dir spelling as passed to this function and its canonicalized
#     (symlink-resolved) form, since the two can differ when repo_dir is
#     reached through a symlinked parent, and the legacy target may have
#     been installed under either spelling depending on which code wrote
#     it (the same ownership check the original per-adapter uninstall
#     blocks used, widened by exactly two additional exact-match
#     candidates - never deletes a foreign hook, a real file, or a symlink
#     pointing anywhere else). If hooks-dir resolution fails for any
#     reason, prints a non-fatal warning and returns 0 - never aborts the
#     caller.
#
#     A THIRD case is also recognised, orthogonal to the two exact-match
#     candidates above: a DANGLING symlink whose target names a DIFFERENT,
#     already-removed worktree of this same repo (neither exact-match
#     candidate is derived from a gone worktree's path, so this case can
#     never be caught by them - see _precommit_is_orphaned_worktree_target).
#     This is what "uninstall" means for that stale entry: no live worktree
#     remains to uninstall FROM, so the only actionable owner is whichever
#     current repo_dir's uninstall run happens to notice the dangling link.
#     A dangling hook that does NOT match any of the three cases gets a
#     distinct "DANGLING" warning (see below) instead of the generic
#     "points elsewhere" message, so a permanently-broken hook stays
#     visible on every run rather than being silently tolerated forever.
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
#
#   KNOWN EDGE CASE (guarded): an empty <repo_dir> ("") is rejected before
#   the `cd` - `cd ""` succeeds in both bash and zsh and silently retargets
#   to the caller's CURRENT directory, which would make this function
#   fail-open (returning the invoker's cwd, not an error indicator) for a
#   function whose whole job is deriving where symlinks get written/read.
#   Not reachable from any of the six current consumers (all set REPO_DIR
#   unconditionally before calling in), but the raw `cd "$d"` behavior
#   without this guard would silently swap a caller bug (empty repo_dir)
#   for a directory-confusion bug instead of surfacing it - echoes the
#   empty string back unchanged so callers see the same "unresolved"
#   signal they'd get from any other invalid repo_dir.
# ---------------------------------------------------------------------------
_precommit_canonical_repo_dir() {
  local d="$1"
  if [[ -z "$d" ]]; then
    echo "$d"
    return 0
  fi
  (cd "$d" 2>/dev/null && pwd -P) || echo "$d"
}

# ---------------------------------------------------------------------------
# _precommit_is_orphaned_worktree_target <target> <repo_dir> <hooks_dir>
#   Internal helper (not part of the public API). Returns 0 (true) iff
#   <target> - the readlink() of a DANGLING pre-commit symlink, i.e. it has
#   already been confirmed `[[ ! -e "$target" ]]` by the caller - is a
#   hook that WOULD have been installed by this module's own
#   install_precommit_hook for some OTHER, now-removed worktree of the
#   SAME repo (<repo_dir>, already canonicalized by the caller): a dangling
#   target ending in "/hooks/pre-commit" whose containing "worktrees"
#   directory sits directly under "<repo_dir>/.claude/worktrees" or
#   "<repo_dir>/.agentic/worktrees" - the two locations this repo's own
#   tooling creates isolation/feature worktrees under (see
#   content/references/worktree-lifecycle.md). uninstall_precommit_hook's
#   two existing exact-match candidates (hook_src, legacy_hook_src_*) are
#   both derived from the CURRENTLY INVOKING repo_dir and so can never
#   match a target naming a *different*, already-deleted worktree - this
#   helper is the third, narrower candidate that closes exactly that gap.
#
#   Deliberately does NOT use a generic walk-up-the-target's-ancestors
#   algorithm (canonicalize the target's longest existing ancestor and
#   re-append the missing tail) - that approach was considered and
#   rejected for two reasons: (1) it requires an explicit termination
#   guard against a slash-free non-existent path component (a bare
#   `${x%/*}` is a no-op there, so an unguarded loop hangs and grows
#   memory unboundedly - a hazard that does NOT exist on origin/main today
#   and this helper must not introduce), and (2) it is unnecessary here:
#   this repo's worktree layout is a FIXED, two-candidate shape
#   ("<repo_dir>/.claude/worktrees/<name>/hooks/pre-commit" or the
#   ".agentic/" sibling), so the anchor to canonicalize is already known
#   up front - "<repo_dir>/.claude/worktrees" or "<repo_dir>/.agentic/worktrees"
#   - and can be canonicalized directly with a single `cd + pwd -P per
#   candidate (bounded, no loop) rather than discovered by walking. String
#   manipulation on the (possibly non-canonical, non-existent) target is
#   used ONLY to test its coarse SHAPE - does it plausibly look like
#   ".../.claude/worktrees/<name>/hooks/pre-commit"? - before any
#   filesystem call; the actual containment decision is always made by
#   comparing two REAL, `cd`-canonicalized, existing directories
#   (<repo_dir>'s own ".claude/worktrees" or ".agentic/worktrees", and the
#   target's own "worktrees" segment, when that segment still exists on
#   disk) - so a symlinked path component anywhere in either side is
#   resolved correctly by `cd`, never by fragile string comparison.
#
#   A RELATIVE target (readlink() can return either form) is anchored
#   against <hooks_dir> per POSIX symlink-resolution semantics (relative
#   to the symlink's OWN directory, never the process's CWD) before the
#   shape test - never resolved against $PWD.
#
#   FAILS CLOSED (returns 1, "not ours - leave it dangling") whenever the
#   real containment cannot be positively confirmed: <target> is not
#   dangling, does not end in "/hooks/pre-commit", <hooks_dir> is empty and
#   <target> is relative, the target's own "worktrees" segment no longer
#   exists on disk (nothing left to canonicalize and compare), or neither
#   "<repo_dir>/.claude/worktrees" nor "<repo_dir>/.agentic/worktrees"
#   exists. The asymmetry is deliberate: the failure direction here is
#   DELETION, and a false negative (an orphan that stays dangling one more
#   run) is far cheaper than a false positive (deleting a hook this
#   function merely guessed was ours).
# ---------------------------------------------------------------------------
_precommit_is_orphaned_worktree_target() {
  local target="$1"
  local repo_dir="$2"
  local hooks_dir="$3"

  # Only a DANGLING target is ever eligible - a target that still resolves
  # is adjudicated by the caller's exact-match checks, never by this guess.
  [[ -e "$target" ]] && return 1

  case "$target" in
    /*) : ;;
    *)
      # POSIX: a relative symlink target resolves against the symlink's
      # OWN directory, not the caller's CWD. Anchor it against hooks_dir;
      # fail closed if that anchor is unavailable.
      [[ -z "$hooks_dir" ]] && return 1
      target="$hooks_dir/$target"
      ;;
  esac

  case "$target" in
    */hooks/pre-commit) : ;;
    *) return 1 ;;
  esac

  local worktree_dir="${target%/hooks/pre-commit}"
  [[ "$worktree_dir" == "$target" || -z "$worktree_dir" ]] && return 1

  local worktrees_root="${worktree_dir%/*}"
  [[ "$worktrees_root" == "$worktree_dir" || -z "$worktrees_root" ]] && return 1

  case "$(basename "$worktrees_root")" in
    worktrees) : ;;
    *) return 1 ;;
  esac
  case "$(basename "${worktrees_root%/*}")" in
    .claude | .agentic) : ;;
    *) return 1 ;;
  esac

  # The target's own "worktrees" ancestor must still exist on disk to be
  # canonicalized at all - if the whole container is gone too, there is
  # nothing real left to compare against; fail closed.
  [[ -d "$worktrees_root" ]] || return 1
  local canonical_target_root
  canonical_target_root="$(cd "$worktrees_root" 2>/dev/null && pwd -P)" || return 1
  [[ -z "$canonical_target_root" ]] && return 1

  local candidate canonical_candidate
  for candidate in "$repo_dir/.claude/worktrees" "$repo_dir/.agentic/worktrees"; do
    canonical_candidate="$(cd "$candidate" 2>/dev/null && pwd -P)" || continue
    [[ -z "$canonical_candidate" ]] && continue
    if [[ "$canonical_target_root" == "$canonical_candidate" ]]; then
      return 0
    fi
  done

  return 1
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
  local raw_repo_dir="$1"
  local repo_dir
  repo_dir="$(_precommit_canonical_repo_dir "$raw_repo_dir")"
  local hook_src
  hook_src="$(resolve_hook_src "$repo_dir")"

  # Legacy target: the pre-DS-58-worktree-fix (and pre-this-PR) symlink
  # target, "<repo_dir>/hooks/pre-commit" unconditionally, with no
  # worktree-awareness and no canonicalization. install_precommit_hook
  # heals a link pointing here via _ae_is_ours, but uninstall previously
  # had no equivalent - a hook installed by the old code (or by this new
  # code from an ordinary, non-worktree repo_dir, where hook_src already
  # equals this value) was left orphaned by an uninstall that only
  # recognised the new resolved target. Two exact-match candidates are
  # built here, not one: the RAW spelling of repo_dir as originally passed
  # in (pre-this-PR code, and pre-canonicalization callers, built the
  # symlink target from this uncanonicalized string) and the CANONICAL
  # spelling (this PR's install path always symlinks against the
  # canonicalized form). When repo_dir is reached through a symlinked
  # parent, those two strings differ, and a hook installed under the raw
  # spelling would otherwise silently escape both the resolved-target
  # check and a canonical-only legacy check - re-orphaning it across the
  # cross-version boundary this widening exists to close. Accepting these
  # candidates widens what uninstall will remove to exactly: "the current
  # resolved target" OR "the legacy target built from the raw repo_dir
  # spelling" OR "the legacy target built from the canonical repo_dir
  # spelling" - all three still require an EXACT match (per the existing
  # `[[ "$current_target" == ... ]]` ownership check), so a foreign hook
  # pointing anywhere else, including a different methodology checkout's
  # hooks/pre-commit, is still left untouched. It does NOT match a link
  # pointing at some other project's own hooks/pre-commit that happens to
  # share a basename but not a path.
  local legacy_hook_src_raw="$raw_repo_dir/hooks/pre-commit"
  local legacy_hook_src_canonical="$repo_dir/hooks/pre-commit"

  local hooks_dir
  if ! hooks_dir="$(resolve_git_hooks_dir "$repo_dir")"; then
    echo "  ! could not resolve git hooks directory - skipping pre-commit hook removal (non-fatal)"
    return 0
  fi

  local hook_dst="$hooks_dir/pre-commit"

  if [[ -L "$hook_dst" ]]; then
    local current_target
    current_target="$(readlink "$hook_dst")"
    if [[ "$current_target" == "$hook_src" || "$current_target" == "$legacy_hook_src_raw" || "$current_target" == "$legacy_hook_src_canonical" ]]; then
      rm "$hook_dst"
      echo "  - pre-commit hook removed"
    elif _precommit_is_orphaned_worktree_target "$current_target" "$repo_dir" "$hooks_dir"; then
      rm "$hook_dst"
      echo "  - pre-commit hook removed (orphaned symlink from an already-removed worktree: $current_target)"
    elif [[ ! -e "$hook_dst" ]]; then
      echo "  ! pre-commit hook is DANGLING (points at a missing target, not ours to remove): $current_target - this hook is currently broken and silently NOT running" >&2
    else
      echo "  = pre-commit hook points elsewhere: $current_target - not ours, skipping"
    fi
  elif [[ -e "$hook_dst" ]]; then
    echo "  = pre-commit hook is a real file - not removing"
  else
    echo "  = pre-commit hook not found - nothing to do"
  fi
}
