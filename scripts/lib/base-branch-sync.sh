# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Module manifest
# Purpose: Fast-forward the LOCAL <base-branch> ref in a repo to match
#          origin/<base-branch>. Never merges, rebases, force-pushes, or
#          autostashes. Classifies why a fast-forward did NOT happen into
#          distinct, per-originating-branch terminal statuses (see below).
#
# Public API:
#   ae_base_branch_sync <repo> <base>
#     Prints a breadcrumb line (and, on some paths, WARNING/NOTE diagnostic
#     lines) to stdout. Returns (never exits):
#       0  synced          - status=ff-pulled or status=ff-updated-ref
#       1  diverged         - status=diverged
#       2  skipped-dirty     - status=skipped-dirty
#       3  usage/arg error   - empty <repo> or <base> (defense-in-depth; the
#                              CLI wrapper is expected to have already caught
#                              this, but this function re-validates its own
#                              preconditions independently)
#       4  inconclusive      - status=fetch-failed, status=refused-unknown,
#                              or status=ref-locked-elsewhere
#
# Upstream deps: bash, git, awk.
#
# Downstream consumers: bin/agentic-base-sync.
#
# Failure modes:
#   - Two fully separate per-branch terminal classifications (HEAD-on-base vs
#     HEAD-elsewhere) with NO shared post-refusal code path. This is a
#     structural fix: `ref-locked-elsewhere` ("base checked out in another
#     worktree") is only reachable when HEAD is NOT on base - it is
#     impossible for that to be the cause of a refusal when base IS checked
#     out in this repo. Symmetrically, `refused-unknown` is only reachable
#     when HEAD IS on base.
#   - Dirty-overwrite refusal text is matched via `LC_ALL=C` to avoid a
#     translated git locale silently defeating the grep.
#   - Divergence is always CONFIRMED via a fresh, plain `git fetch origin
#     <base>` + `rev-list --left-right --count`, never inferred from git's
#     raw (and overloaded) native exit code.
#   - An empty `rev-list --left-right --count` result (e.g. a --single-branch
#     clone with no origin/<base>) is reported verbatim as refused-unknown /
#     ref-locked-elsewhere, never defaulted into a false ahead=0 conclusion.
#
# Performance: 2-4 git invocations on the success path; up to 3 on a refusal
#              path (the ff/fetch attempt, the plain verify-fetch, and the
#              rev-list).
# ---------------------------------------------------------------------------

ae_base_branch_sync() {
  local repo="$1" base="$2"
  local head err verify_err counts behind ahead

  [ -n "$repo" ] || { echo "usage: agentic-base-sync <repo> <base-branch>" >&2; return 3; }
  [ -n "$base" ] || { echo "usage: agentic-base-sync <repo> <base-branch>" >&2; return 3; }

  head=$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null)
  # Detached HEAD: rev-parse --abbrev-ref HEAD returns the literal string "HEAD",
  # which never equals $base, so it correctly falls into the HEAD-elsewhere branch
  # below without special-casing.

  if [ "$head" = "$base" ]; then
    # ---- HEAD-on-base branch. Terminal statuses reachable from here: ff-pulled,
    # skipped-dirty, diverged, fetch-failed, refused-unknown. NEVER ref-locked-
    # elsewhere - base is checked out in $repo itself, so "checked out in another
    # worktree" cannot be the cause of any refusal on this branch.
    err=$(LC_ALL=C git -C "$repo" pull --ff-only origin "$base" 2>&1)
    if [ $? -eq 0 ]; then
      counts=$(git -C "$repo" rev-list --left-right --count "origin/${base}...${base}" 2>/dev/null)
      ahead=$(printf '%s' "$counts" | awk '{print $2}')
      if [ -n "$ahead" ] && [ "$ahead" -gt 0 ] 2>/dev/null; then
        echo "NOTE: local $base is $ahead commit(s) ahead of origin/$base with nothing to pull - these are unpushed local-only commits. Push them soon: this is the exact precursor state the handoff's jammed-tree scenario started from (0-behind/2-ahead became 10-behind/2-ahead over time)."
      fi
      echo "[phase: base-sync | status=ff-pulled | branch=$base]"
      return 0
    fi
    # LC_ALL=C makes this match locale-independent (git's own po/ catalogs mean an
    # unpinned locale can translate this text and silently defeat a plain grep).
    # Both the tracked- and untracked-file overwrite variants contain this
    # substring in English.
    if printf '%s' "$err" | grep -qi 'would be overwritten by merge'; then
      echo "WARNING: base-branch-sync skipped on $base - local uncommitted changes would be overwritten by the incoming fast-forward. Commit or discard them, then re-sync."
      echo "[phase: base-sync | status=skipped-dirty | branch=$base]"
      return 2
    fi
    # Refused for a reason that is neither a dirty-overwrite conflict nor (yet)
    # confirmed to be a divergence. Verify against a fresh, PLAIN re-fetch (never
    # a local-ref write, so it cannot itself trigger a "checked out" refusal).
    verify_err=$(git -C "$repo" fetch origin "$base" 2>&1)
    if [ $? -ne 0 ]; then
      echo "WARNING: base-branch-sync could not reach origin to verify $base (network or auth failure). Local $base left untouched. git error:"
      echo "$verify_err"
      echo "[phase: base-sync | status=fetch-failed | branch=$base]"
      return 4
    fi
    counts=$(git -C "$repo" rev-list --left-right --count "origin/${base}...${base}" 2>/dev/null)
    if [ -z "$counts" ]; then
      # origin/<base> absent even after a successful fetch (e.g. a --single-branch
      # clone whose refspec does not cover base) - cannot classify. Do not default
      # ahead/behind into a status; report the git error verbatim.
      echo "WARNING: base-branch-sync could not determine divergence for $base - origin/$base not found after fetch (possible --single-branch clone). Last git error:"
      echo "$err"
      echo "[phase: base-sync | status=refused-unknown | branch=$base]"
      return 4
    fi
    behind=$(printf '%s' "$counts" | awk '{print $1}')
    ahead=$(printf '%s' "$counts" | awk '{print $2}')
    if [ "$ahead" -gt 0 ]; then
      echo "WARNING: local $base has diverged from origin/$base (behind/ahead: ${behind}/${ahead}) - fast-forward sync refused."
      echo "Local-only commits on $base:"
      git -C "$repo" log "origin/${base}..${base}" --oneline 2>/dev/null
      echo "Recovery: push or cherry-pick the local-only commits above onto a branch cut from origin/$base; do not rebase or merge the shared $base tree."
      echo "[phase: base-sync | status=diverged | branch=$base]"
      return 1
    fi
    # ahead == 0, counts are valid, and base IS checked out here - the refusal has
    # no known cause on this branch. Report the unrecognized git error verbatim
    # rather than guessing a reassuring status.
    echo "WARNING: base-branch-sync could not fast-forward $base for an unrecognized reason (not a dirty-overwrite conflict, not a confirmed divergence). git error:"
    echo "$err"
    echo "[phase: base-sync | status=refused-unknown | branch=$base]"
    return 4
  fi

  # ---- HEAD-elsewhere branch (fan-out's $FEATURE_BRANCH, any other branch, or
  # detached HEAD). Terminal statuses reachable from here: ff-updated-ref,
  # diverged, fetch-failed, refused-unknown, ref-locked-elsewhere. NEVER
  # skipped-dirty or ref-locked-elsewhere-when-counts-are-empty - this branch
  # never touches the working tree, and when the post-refusal rev-list counts
  # come back empty (origin/<base> absent, e.g. a --single-branch clone) the
  # cause cannot be attributed to "checked out in another worktree" so it is
  # reported as refused-unknown instead; ref-locked-elsewhere is reserved for
  # the one case this branch CAN disambiguate: valid, non-empty counts with
  # ahead==0, where "checked out elsewhere" is the only remaining explanation.
  err=$(git -C "$repo" fetch origin "${base}:${base}" 2>&1)
  if [ $? -eq 0 ]; then
    counts=$(git -C "$repo" rev-list --left-right --count "origin/${base}...${base}" 2>/dev/null)
    ahead=$(printf '%s' "$counts" | awk '{print $2}')
    if [ -n "$ahead" ] && [ "$ahead" -gt 0 ] 2>/dev/null; then
      echo "NOTE: local $base is $ahead commit(s) ahead of origin/$base with nothing to pull - these are unpushed local-only commits. Push them soon: this is the exact precursor state the handoff's jammed-tree scenario started from."
    fi
    echo "[phase: base-sync | status=ff-updated-ref | branch=$base | head=$head]"
    return 0
  fi
  # Refused: either real divergence, or base checked out in ANOTHER worktree -
  # the only place either cause is disambiguated is right here, on this branch.
  verify_err=$(git -C "$repo" fetch origin "$base" 2>&1)
  if [ $? -ne 0 ]; then
    echo "WARNING: base-branch-sync could not reach origin to verify $base (network or auth failure). Local $base left untouched. git error:"
    echo "$verify_err"
    echo "[phase: base-sync | status=fetch-failed | branch=$base]"
    return 4
  fi
  counts=$(git -C "$repo" rev-list --left-right --count "origin/${base}...${base}" 2>/dev/null)
  if [ -z "$counts" ]; then
    echo "WARNING: base-branch-sync could not determine divergence for $base - origin/$base not found after fetch (possible --single-branch clone). Last git error:"
    echo "$err"
    echo "[phase: base-sync | status=refused-unknown | branch=$base]"
    return 4
  fi
  behind=$(printf '%s' "$counts" | awk '{print $1}')
  ahead=$(printf '%s' "$counts" | awk '{print $2}')
  if [ "$ahead" -gt 0 ]; then
    echo "WARNING: local $base has diverged from origin/$base (behind/ahead: ${behind}/${ahead}) - fast-forward sync refused."
    echo "Local-only commits on $base:"
    git -C "$repo" log "origin/${base}..${base}" --oneline 2>/dev/null
    echo "Recovery: push or cherry-pick the local-only commits above onto a branch cut from origin/$base; do not rebase or merge the shared $base tree."
    echo "[phase: base-sync | status=diverged | branch=$base]"
    return 1
  fi
  # ahead == 0, counts valid, and this IS the only branch where "checked out in
  # another worktree" is a reachable cause (base is not checked out in $repo).
  echo "[phase: base-sync | status=ref-locked-elsewhere | branch=$base]"
  return 4
}
