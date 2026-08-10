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
#     still be removed post-upgrade. Also removed when the legacy target's
#     own worktree directory has already been deleted, PROVIDED its path -
#     canonicalised via _pc_canonicalize_missing_dir, so a target spelled
#     through a symlinked TMPDIR/HOME component still matches - lies under
#     the primary checkout's own ".claude/worktrees/" or ".agentic/worktrees/"
#     (see _pc_is_legacy_sibling_hook's dangling-target branch) - the most
#     common pre-fix residue, since a dangling hook is already broken
#     regardless. Never deletes a foreign hook, a real
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
# _pc_canonicalize_dir <dir>
#   Internal helper (not part of the public API). Echoes the canonical
#   (symlink-resolved) absolute form of <dir> via `cd <dir> && pwd -P`.
#   Shared by resolve_primary_checkout and _pc_git_common_dir_abs so every
#   absolute path either of them produces is canonicalised the SAME way - a
#   symlinked TMPDIR/HOME path component (e.g. macOS's
#   /tmp -> /private/tmp or /var/folders -> /private/var/folders) would
#   otherwise leave one call site's output canonical and the other's raw,
#   causing string-equality comparisons downstream to spuriously fail.
#   <dir>="" is rejected up front (returns 1, echoes nothing) rather than
#   passed to `cd` - bash's `cd ""` fails (rc=1, "null directory") but zsh's
#   `cd ""` SUCCEEDS and resolves to the shell's CURRENT working directory,
#   so without this guard the two shells would echo different, silently
#   wrong answers for the same empty input. No current caller passes an
#   empty <dir> today, but NOT because any upstream `git -C ""` call fails -
#   it does not: `git -C "" rev-parse ...` is treated the same as omitting
#   `-C` entirely and succeeds against the process CWD (verified both
#   shells). Concretely: _pc_git_common_dir_abs already returns early on an
#   empty git-common-dir before ever calling this helper (and an empty
#   <dir> passed to IT would still succeed via `git -C ""`'s CWD fallback,
#   so this guard is never reached that way either); resolve_primary_checkout
#   never calls this helper with `repo_dir=""` because its own `-ef`
#   identity check (comparing a real common-dir against a malformed,
#   literal "/.git" git-dir - "" concatenated with the relative ".git" -
#   for repo_dir="") evaluates false for empty input, so it takes the
#   linked-worktree branch instead (which echoes a case-stripped
#   common_dir directly, never calling this helper) rather than the
#   primary-checkout branch that would. Verified: `resolve_primary_checkout
#   ""` returns rc=0 and echoes this checkout's own resolved path, in both
#   shells - not a failure at all. The guard exists so a FUTURE caller
#   cannot be silently bitten by the bash/zsh inter-shell divergence
#   documented above, independent of how today's callers happen to avoid
#   it.
#   On any OTHER canonicalisation failure (a non-empty <dir> that does not
#   exist, a permission error, or a path that is a file, not a directory),
#   falls back to echoing <dir> unchanged and still returns 0 - this
#   fallback is UNREACHABLE by every current caller (each already guards
#   its own non-existence case upstream, per the callers documented at each
#   call site) and exists purely as documented dead-code behaviour, not as
#   a contract any caller relies on. Do not add a caller that depends on
#   distinguishing "canonicalised" from "fell back" via this return value
#   without first re-auditing this comment.
# ---------------------------------------------------------------------------
_pc_canonicalize_dir() {
  local dir="$1"
  if [[ -z "$dir" ]]; then
    return 1
  fi
  local canonical
  if canonical="$(cd "$dir" 2>/dev/null && pwd -P)" && [[ -n "$canonical" ]]; then
    echo "$canonical"
  else
    echo "$dir"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# _pc_canonicalize_missing_dir <path>
#   Internal helper (not part of the public API). Canonicalises <path> even
#   when <path> itself does not exist on disk (e.g. a deleted worktree),
#   which `_pc_canonicalize_dir` cannot do - `cd`/`pwd -P` require the
#   target directory to exist. Walks upward from <path> to find its longest
#   EXISTING ancestor, canonicalises that ancestor (via
#   _pc_canonicalize_dir, resolving any symlinked component such as macOS's
#   /var/folders -> /private/var/folders), then re-appends the missing
#   trailing path components verbatim - they cannot contain a symlink to
#   resolve, because a symlink target must itself exist to be dereferenced.
#   Always returns 0.
#
#   Known, harmless edge behaviours (none of these are bugs - documented so
#   a future change doesn't "fix" them into something that IS a bug):
#     - <path>="/" (or any input whose only existing ancestor is "/") echoes
#       the EMPTY STRING, not "/" - the final `${canonical_existing%/}`
#       strip removes a lone trailing slash unconditionally. Every current
#       caller only ever appends this result as a prefix, so an empty
#       prefix is equivalent to no prefix.
#     - A trailing slash on <path> itself survives verbatim into the
#       output's tail (e.g. "/tmp/gone/" canonicalises to
#       "/private/tmp/gone/", not "/private/tmp/gone") - the walk only
#       strips components from the END via `${existing%/*}`, which does not
#       touch a trailing slash already present.
#     - <path>="" is treated as "/" up front, so it produces the same empty
#       string as the "/" case above.
#
#   Termination guard (DS-152 round 5, Critical): if the walk-up reduces
#   `existing` to a slash-free, still-nonexistent fragment (e.g. a
#   relative <path> like "toolbox/hooks" evaluated in a CWD that has no
#   "toolbox" entry), `${existing%/*}` becomes a no-op on that fragment and
#   the loop would otherwise never terminate, growing `tail` without bound.
#   The `*/*` case guard below detects exactly this and stops climbing,
#   leaving the unresolved fragment as the base for _pc_canonicalize_dir
#   (which fails closed - falls back to echoing it unchanged - rather than
#   hanging). This is a safety net: _pc_is_legacy_sibling_hook anchors its
#   own input to an absolute path before ever reaching here specifically to
#   avoid needing it, but a future caller that does not anchor its input is
#   still protected from a hang rather than merely from a wrong answer.
# ---------------------------------------------------------------------------
_pc_canonicalize_missing_dir() {
  local path="$1"
  local existing="${path:-/}"
  local tail=""
  while [[ ! -d "$existing" && "$existing" != "/" ]]; do
    case "$existing" in
      */*) : ;;
      *) break ;;
    esac
    tail="/${existing##*/}${tail}"
    existing="${existing%/*}"
    [[ -z "$existing" ]] && existing="/"
  done
  local canonical_existing
  canonical_existing="$(_pc_canonicalize_dir "$existing")"
  echo "${canonical_existing%/}${tail}"
}

# ---------------------------------------------------------------------------
# _pc_git_common_dir_abs <dir>
#   Internal helper (not part of the public API). Echoes the CANONICAL
#   absolute `git -C <dir> rev-parse --git-common-dir` for <dir>: the raw
#   result is normalised to absolute exactly like resolve_git_hooks_dir
#   does, then run through _pc_canonicalize_dir. Returns non-zero and
#   echoes nothing if <dir> is not a git checkout (missing, deleted, or
#   never a repo). Shared by resolve_primary_checkout and
#   _pc_is_legacy_sibling_hook so both compare common-dirs computed the
#   SAME way and in the SAME (canonical) form - `git rev-parse
#   --git-common-dir` returns a checkout-RELATIVE path from a primary
#   (non-worktree) checkout but a fully canonical ABSOLUTE path from a
#   linked worktree, so without this canonicalisation step the two forms
#   would raw-string-mismatch on any TMPDIR/HOME with a symlinked
#   component even though they resolve to the identical directory.
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
  _pc_canonicalize_dir "$common_dir"
}

# ---------------------------------------------------------------------------
# _pc_is_legacy_sibling_hook <target> <repo_common_dir> [primary_checkout] [hooks_dir]
#   Internal helper (not part of the public API). A pre-DS-152 install could
#   have symlinked the shared hook at ANY worktree's own
#   "<worktree>/hooks/pre-commit" (repo_dir itself, not necessarily the
#   primary checkout). <target> is the RAW symlink target text (from
#   `readlink`), which may be a RELATIVE path - per POSIX symlink semantics
#   a relative target resolves against the symlink's OWN directory
#   (<hooks_dir>, the directory the pre-commit symlink itself lives in),
#   NOT the calling process's CWD. When <target> is not absolute and
#   [hooks_dir] is given, it is anchored against <hooks_dir> before any
#   further use (DS-152 round 5) - both for correctness (a relative target
#   evaluated against CWD names the wrong directory) and because an
#   unanchored relative target with a slash-free first component could
#   otherwise reach _pc_canonicalize_missing_dir's walk-up in a form that
#   never becomes absolute. Returns 0 (true) iff <target> ends in
#   "/hooks/pre-commit" AND either:
#     - the directory it hangs off of still exists, and THAT directory's own
#       git-common-dir matches <repo_common_dir> - i.e. <target> is some
#       worktree of the exact same repo family repo_dir belongs to,
#       regardless of which worktree wrote it or how its path was
#       originally spelled; or
#     - the directory it hangs off of has already been DELETED (the most
#       common pre-fix residue - a scratch/ephemeral worktree that was
#       cleaned up without ever uninstalling its legacy hook first) AND
#       [primary_checkout] is given AND <target>'s worktree path,
#       CANONICALISED via _pc_canonicalize_missing_dir (its own directory
#       component is gone, so it cannot be canonicalised the normal way -
#       see that helper), lies under "<primary_checkout>/.claude/worktrees/"
#       or "<primary_checkout>/.agentic/worktrees/" - the repo's own known
#       worktree roots, compared in the SAME canonical form primary_checkout
#       is already in. Without this canonicalisation step a target spelled
#       via a symlinked TMPDIR/HOME component (e.g. the raw, non-`pwd -P`
#       form a pre-DS-152 install could have written) would raw-string
#       mismatch against primary_checkout's canonical form even though both
#       name the identical real directory (DS-152 round 4). Ownership cannot
#       be verified via git-common-dir once the directory is gone, so this
#       path constraint stands in for it: the hook is already broken either
#       way (its target cannot be executed), and constraining to the repo's
#       own worktree roots prevents widening into a foreign dangling hook
#       that merely happens to be unreachable.
#   Returns 1 (false) - never aborts - when <target> does not match the
#   suffix, or (for an existing target directory) its common-dir resolves to
#   a different repo, or (for an already-deleted target directory) no
#   primary_checkout was given or the path falls outside both known
#   worktree roots.
# ---------------------------------------------------------------------------
_pc_is_legacy_sibling_hook() {
  local target="$1" repo_common_dir="$2" primary_checkout="${3:-}" hooks_dir="${4:-}"
  case "$target" in
    */hooks/pre-commit) : ;;
    *) return 1 ;;
  esac
  local target_repo_dir="${target%/hooks/pre-commit}"

  # Anchor a relative target against the symlink's own directory (see
  # docstring above) - never against the process CWD.
  case "$target_repo_dir" in
    /*) : ;;
    *)
      if [[ -n "$hooks_dir" ]]; then
        target_repo_dir="$hooks_dir/$target_repo_dir"
      fi
      ;;
  esac

  if [[ ! -d "$target_repo_dir" ]]; then
    if [[ -n "$primary_checkout" ]]; then
      local canonical_target_repo_dir
      canonical_target_repo_dir="$(_pc_canonicalize_missing_dir "$target_repo_dir")"
      case "$canonical_target_repo_dir" in
        "$primary_checkout"/.claude/worktrees/*|"$primary_checkout"/.agentic/worktrees/*)
          return 0
          ;;
      esac
    fi
    return 1
  fi

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
  local common_dir git_dir

  common_dir="$(_pc_git_common_dir_abs "$repo_dir")" || return 1
  if ! git_dir="$(git -C "$repo_dir" rev-parse --git-dir 2>/dev/null)" || [[ -z "$git_dir" ]]; then
    return 1
  fi

  # `--git-dir` can be checkout-relative in a normal (non-worktree) repo;
  # normalise to absolute, matching _pc_git_common_dir_abs's own
  # normalisation of --git-common-dir above. Deliberately NOT run through
  # _pc_canonicalize_dir - it does not need to match common_dir's exact
  # string form, only its identity (see the `-ef` comparison below).
  case "$git_dir" in
    /*) : ;;
    *) git_dir="$repo_dir/$git_dir" ;;
  esac

  # Compare by inode identity (`-ef`), not string equality: common_dir is
  # now always canonicalised (via _pc_git_common_dir_abs) while git_dir may
  # still be a raw, non-canonicalised concatenation on a symlinked
  # TMPDIR/HOME. Both paths exist as real directories whenever repo_dir is a
  # valid checkout, so `-ef` correctly identifies "same directory" without
  # requiring either side's string form to match.
  if [[ "$common_dir" -ef "$git_dir" ]]; then
    # repo_dir is not a linked worktree (or is itself the primary checkout)
    # - it is authoritative for its own hook source. Canonicalise via the
    # shared helper so this branch's output is comparable, byte-for-byte,
    # with the linked-worktree branch below (whose common_dir is already
    # canonical). Without this, installing once from a worktree (canonical
    # form) and again directly from the primary checkout (raw form) would
    # compute two DIFFERENT hook_src strings for the same real directory,
    # and the "already linked" equality check downstream would spuriously
    # treat the hook as stale forever.
    _pc_canonicalize_dir "$repo_dir"
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
        && _pc_is_legacy_sibling_hook "$current_target" "$repo_common_dir" "$primary_checkout" "$hooks_dir"; then
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
