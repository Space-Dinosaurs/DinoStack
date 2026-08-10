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
# NOTE: bin/ds-doctor's check_git_precommit resolves its expected
#   pre-commit symlink SOURCE via _resolve_hook_src (a Python function -
#   search `def _resolve_hook_src`; line numbers shift), which shells out
#   to `bash -c 'source "$1"; resolve_hook_src "$2"'` against THIS file,
#   with a git-scrubbed subprocess environment, rather than reimplementing
#   this function's git-dir-vs-git-common-dir resolution logic in Python a
#   second time (PR #653 / #640 follow-up). Consequently this function's
#   NAME, its ARGUMENT SHAPE (exactly one positional <repo_dir>), and its
#   STDOUT CONTRACT (exactly one path on stdout, all diagnostics to
#   stderr - the existing `>&2` warning in the worktree-fallback branch
#   below is load-bearing, not decorative) form a cross-language API.
#   Renaming this function, adding a required parameter, or writing
#   anything else to stdout silently breaks bin/ds-doctor's pre-commit
#   check - each of those three was independently verified by mutation to
#   redden the parity suite below. The parity test also greps for the
#   literal `^resolve_hook_src[[:space:]]*\(\)` definition form, so
#   restyling this function to `function resolve_hook_src {` hard-fails
#   CI even though the bash semantics are unchanged.
#
#   bin/ds-doctor deliberately does NOT mirror this function's own
#   fallback-to-hardcode behavior: on any resolution failure,
#   _resolve_hook_src returns None, and check_git_precommit WARNs and
#   skips the symlink write entirely rather than substituting
#   "<repo_dir>/hooks/pre-commit" - which is the WRONG target by
#   construction for a linked-worktree repo_dir, the exact Major #653
#   exists to close, and unattended `ds-doctor --fix` (via `ds-update`)
#   has no operator present to catch a bad guess. This bash-side function
#   keeps its own historical fallback (see resolve_hook_src's Public API
#   doc above) - the two callers intentionally diverge on failure
#   handling, not by oversight.
#
#   Agreement between the two implementations is pinned by
#   bin/tests/test_ds_doctor_precommit_source_parity.sh across three
#   topologies (ordinary checkout, linked worktree - pinned to the
#   PRIMARY checkout's own hooks/pre-commit specifically, not merely
#   mutual agreement, since a double regression could still agree with
#   itself - and a checkout missing hooks/pre-commit entirely); failure
#   handling is pinned separately by
#   bin/tests/test_ds_doctor_precommit_fallback_safety.sh. Both tests `cp`
#   THIS real file into isolated fixtures and hard-fail (never skip) if it
#   stops defining resolve_hook_src, so a rename or removal cannot pass
#   silently. If this function's name, argument shape, or stdout contract
#   changes, both test files need re-verification alongside bin/ds-doctor
#   itself.
#
# Downstream consumers:
#   .claude/install.sh, .cursor/install.sh, .opencode/install.sh,
#   .claude/uninstall.sh, .cursor/uninstall.sh, .opencode/uninstall.sh
#   (the only adapters that install/uninstall a pre-commit hook); bin/ds-doctor
#   (shells out to resolve_hook_src via _resolve_hook_src - see the NOTE
#   above - as a cross-language API, not a source-level import).
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
# resolve_git_hooks_dir, two in resolve_hook_src). uninstall_precommit_hook
# additionally, ONLY on the path where an existing symlink matched neither
# exact-match candidate (live or dangling - see
# _precommit_is_orphaned_worktree_target's own manifest on why this is not
# dangling-gated at the call site): one call into
# _precommit_is_orphaned_worktree_target, which performs a BOUNDED upward
# ancestor walk capped at _PRECOMMIT_MAX_ANCESTOR_DEPTH (8) iterations,
# each iteration spawning up to one `cd` subshell for the ancestor itself
# plus up to four more (one per enumerated worktrees-container candidate,
# short-circuiting on the first match within the iteration) - worst case
# 8 * 5 = 40 `cd` subshells for a target that matches no candidate at any
# depth up to the cap; typically far fewer, since a real match or a
# non-existent ancestor short-circuits early. No `basename` calls (removed
# along with the basename-shape pre-check; see the helper's own manifest).
# A live/resolving hook that matches an exact-match candidate, or a clean
# uninstall, never reaches this path at all.
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
#   <target> - the readlink() of a pre-commit symlink that matched neither
#   of uninstall_precommit_hook's two exact-match candidates - is BOTH
#   confirmed DANGLING (by this function itself, internally - the CALLER
#   does NOT pre-filter on danglingness; this function is invoked for any
#   non-exact-match symlink, live or dangling, and must safely say "no" for
#   a live one) AND a hook that WOULD have been installed by this module's
#   own install_precommit_hook for some OTHER, now-removed worktree of the
#   SAME repo (<repo_dir>, already canonicalized by the caller):
#   uninstall_precommit_hook's two existing exact-match candidates
#   (hook_src, legacy_hook_src_*) are both derived from the CURRENTLY
#   INVOKING repo_dir and so can never match a target naming a *different*,
#   already-deleted worktree - this helper is the third, narrower candidate
#   that closes exactly that gap.
#
#   "Ours" is decided against a small, ENUMERATED list of candidate
#   worktree-container directories under <repo_dir> - NOT a generic
#   pattern match, and NOT a claim that this is every location worktrees
#   could ever be created. Each candidate is a real, documented location
#   this repo's own tooling is known to create worktrees under:
#     - "<repo_dir>/.claude/worktrees"  (the live Claude Code harness's
#       own isolation-worktree auto-lock directory)
#     - "<repo_dir>/.agentic/worktrees" (AGENTS.md's documented
#       isolation/feature worktree path)
#     - "<repo_dir>/.worktrees"         (content/references/subagent-protocol.md:333's
#       manually-managed fan-out path,
#       "${REPO}/.worktrees/${FEATURE_BRANCH}-${unit_slug}")
#     - "<repo_dir>/evals/.worktrees"   (content/commands/ds-cleanup-worktrees.md:38's
#       "evals/.worktrees/wt-*" instance)
#   This list is a known INCOMPLETE enumeration, not a closed set derived
#   from any single source of truth - if methodology or harness tooling
#   ever documents creating worktrees under a fifth location, that
#   location must be added here explicitly; nothing in this function
#   discovers new locations on its own. A dangling target naming a
#   worktree under an undocumented fifth location fails closed (left
#   dangling, not deleted) until this list is updated - the same outcome
#   as on origin/main today, not a regression.
#
#   The worktree's own directory is NOT always exactly one path component
#   below its container. This was assumed in an earlier revision (a fixed
#   two-strip: strip "/hooks/pre-commit", then strip one more trailing
#   component) and found false by a round-3 Skeptic review:
#   content/references/subagent-protocol.md:333-334's own documented,
#   copy-pasteable command creates a worktree at
#   "${REPO}/.worktrees/${FEATURE_BRANCH}-${unit_slug}", and this repo's
#   branch-naming convention (content/rules/conventions.md) makes
#   FEATURE_BRANCH a "feature/<name>" / "fix/<name>" / "chore/<name>"
#   value - so the resulting worktree lands at
#   ".worktrees/feature/<name>-<unit_slug>", TWO components below
#   ".worktrees", not one. AGENTS.md:48's ".agentic/worktrees/<branch-name>"
#   phrasing has the identical hazard for any branch name containing a
#   slash. A fixed strip count is therefore wrong by construction for any
#   candidate whose worktree-naming convention can itself contain a "/".
#
#   Handled by a BOUNDED upward search instead of a fixed strip count:
#   starting from the worktree's own directory (target minus
#   "/hooks/pre-commit"), walk up one path component at a time, testing
#   each ancestor against the four enumerated candidates, until a match is
#   found, the walk reaches _PRECOMMIT_MAX_ANCESTOR_DEPTH ancestors (8 -
#   comfortably deeper than any real worktree-naming convention observed
#   in this repo; a deeper mismatch fails closed, not a hang), or a strip
#   stops changing the string (the same slash-free-root termination guard
#   round 1 required for the walk-up design it rejected THEN - now
#   required and present, since this IS that walk, deliberately reintroduced
#   with the guard round 1 said it would need). This differs from the
#   generic "canonicalize the target's longest existing ancestor" algorithm
#   round 1 rejected: that walk stops at the first ancestor that EXISTS on
#   disk and asks no further question; this walk instead tests EVERY
#   ancestor up to the depth bound against the enumerated candidate list
#   and only accepts an EXACT match - a non-existent, non-matching
#   ancestor is simply skipped (via `continue`, not `return`), not treated
#   as a resolution failure. String manipulation on the (possibly
#   non-canonical, non-existent) target is used ONLY to compute each
#   candidate ancestor string before any filesystem call; the actual
#   containment decision at each step is always made by comparing two
#   REAL, `cd`-canonicalized, existing directories (one of <repo_dir>'s
#   four enumerated candidates, and the current ancestor, when that
#   ancestor exists on disk) - so a symlinked path component anywhere in
#   either side is resolved correctly by `cd`, never by fragile string
#   comparison. There is deliberately no basename-shape pre-check (e.g.
#   "does the parent directory's own name look like .claude or .agentic?")
#   - that check does not generalise across the four candidates above
#   (".worktrees" and "evals/.worktrees" do not share the
#   ".claude/agentic + worktrees" two-segment shape) and was removed; the
#   real, `cd`-canonicalized comparison against the enumerated list is
#   both necessary and sufficient on its own.
#
#   A RELATIVE target (readlink() can return either form) is anchored
#   against <hooks_dir> per POSIX symlink-resolution semantics (relative
#   to the symlink's OWN directory, never the process's CWD) BEFORE
#   anything else - including the danglingness gate itself, not merely the
#   shape test - never resolved against $PWD. Ordering matters here: this
#   function is called by uninstall_precommit_hook for ANY symlink that
#   did not match either exact-match candidate, whether or not it is
#   actually dangling, so a danglingness test evaluated before anchoring
#   would judge a relative target's existence against the wrong base and
#   could misclassify a LIVE, still-resolving hook as dangling.
#
#   NOT covered by the FAILS-CLOSED enumeration below, disclosed
#   separately because it is a positive-match (deletion) case, not a
#   failure: a dangling target whose path reaches one of the four
#   enumerated candidates THROUGH a symlink located OUTSIDE <repo_dir> (a
#   symlinked path component anywhere before the container segment) still
#   matches and IS deleted - `cd`-canonicalization resolves that symlink
#   on both sides of the comparison before it happens, so the real,
#   physical container directory is what is actually compared, not the
#   symlinked spelling. This is deliberate, not an oversight: the object
#   being deleted is always identified by comparing REAL directories (the
#   repo's own enumerated container, physically, against the target's own
#   container, physically) - a symlink hop on the way there changes the
#   SPELLING of the path, never the physical directory the comparison
#   ultimately identifies as "ours". Test 19 in
#   bin/tests/test_precommit_worktree.sh exercises this directly.
#
#   FAILS CLOSED (returns 1, "not ours - leave it dangling") whenever the
#   real containment cannot be positively confirmed: <target> is not
#   dangling, does not end in "/hooks/pre-commit", <hooks_dir> is empty and
#   <target> is relative, no ancestor up to _PRECOMMIT_MAX_ANCESTOR_DEPTH
#   (8) levels above the worktree's own directory exists on disk and
#   matches one of the four enumerated candidates, or the walk hits a
#   slash-free non-existent component before finding a match. The asymmetry
#   is deliberate: the failure direction here is DELETION, and a false
#   negative (an orphan that stays dangling one more run) is far cheaper
#   than a false positive (deleting a hook this function merely guessed
#   was ours).
# ---------------------------------------------------------------------------
_precommit_is_orphaned_worktree_target() {
  local target="$1"
  local repo_dir="$2"
  local hooks_dir="$3"

  # POSIX: a relative symlink target resolves against the symlink's OWN
  # directory, not the caller's CWD. Anchor it against hooks_dir FIRST -
  # fail closed if that anchor is unavailable - so that every subsequent
  # test (starting with the danglingness gate immediately below) is
  # evaluated against the correct base. This anchoring step MUST run
  # before the danglingness gate, not after it: testing `-e` on a raw
  # relative target against the wrong base (the caller's ambient CWD,
  # which is never guaranteed to be hooks_dir) can report a LIVE,
  # still-resolving target as nonexistent purely because of process CWD,
  # not because the target is actually dangling - a round-3 Major found
  # exactly this shipped in reversed order, silently deleting a live
  # worktree's still-in-use hook. See Test 24 in
  # bin/tests/test_precommit_worktree.sh for the regression coverage this
  # ordering requires (deleting the gate below entirely, or restoring the
  # old order, both redden Test 24).
  case "$target" in
    /*) : ;;
    *)
      [[ -z "$hooks_dir" ]] && return 1
      target="$hooks_dir/$target"
      ;;
  esac

  # Only a DANGLING target is ever eligible - a target that still resolves
  # is adjudicated by the caller's exact-match checks, never by this guess.
  # MUST run after the anchoring block above (see the comment there).
  [[ -e "$target" ]] && return 1

  case "$target" in
    */hooks/pre-commit) : ;;
    *) return 1 ;;
  esac

  local worktree_dir="${target%/hooks/pre-commit}"
  [[ "$worktree_dir" == "$target" || -z "$worktree_dir" ]] && return 1

  # BOUNDED upward search: the worktree's own directory is not always
  # exactly one path component below its container (see this function's
  # own manifest for why - subagent-protocol.md's documented worktree
  # path can itself contain a "/" via a "feature/<name>" branch). Walk up
  # one component at a time, testing EVERY ancestor against the four
  # enumerated candidates, capped at _PRECOMMIT_MAX_ANCESTOR_DEPTH
  # iterations with an explicit termination guard against a slash-free
  # non-existent component (where `${x%/*}` is a no-op) - both bounds are
  # required together; either alone is insufficient (the depth cap alone
  # would still spin needlessly on a pathological input that never
  # changes, and the termination guard alone provides no upper bound on a
  # deeply-nested but always-changing string).
  local -r _PRECOMMIT_MAX_ANCESTOR_DEPTH=8
  local ancestor="$worktree_dir" prev_ancestor="" depth=0
  local candidate canonical_candidate canonical_ancestor
  while [[ $depth -lt $_PRECOMMIT_MAX_ANCESTOR_DEPTH ]]; do
    prev_ancestor="$ancestor"
    ancestor="${ancestor%/*}"
    if [[ "$ancestor" == "$prev_ancestor" || -z "$ancestor" ]]; then
      break
    fi
    depth=$((depth + 1))

    # A non-existent or non-canonicalizable ancestor is simply skipped
    # (not a resolution failure) - the worktree segments below it are
    # gone, but a candidate container further up may still be real.
    [[ -d "$ancestor" ]] || continue
    canonical_ancestor="$(cd "$ancestor" 2>/dev/null && pwd -P)" || continue
    [[ -z "$canonical_ancestor" ]] && continue

    for candidate in \
      "$repo_dir/.claude/worktrees" \
      "$repo_dir/.agentic/worktrees" \
      "$repo_dir/.worktrees" \
      "$repo_dir/evals/.worktrees"
    do
      canonical_candidate="$(cd "$candidate" 2>/dev/null && pwd -P)" || continue
      [[ -z "$canonical_candidate" ]] && continue
      if [[ "$canonical_ancestor" == "$canonical_candidate" ]]; then
        return 0
      fi
    done
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
