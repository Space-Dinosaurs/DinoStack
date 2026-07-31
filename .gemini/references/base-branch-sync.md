<!--
Purpose: Full reference for the post-merge local base-branch sync procedure -
         the `agentic-base-sync` CLI contract, the underlying
         `ae_base_branch_sync` bash function, the divergence diagnostic
         format, recovery guidance, and the two call sites that invoke it.

Public API: Read-only reference document. Cross-referenced from:
            content/commands/ds-implement-ticket.md Phase 12 (unconditional
            post-phase sync call),
            content/rules/conventions.md Conductor preflight step 6
            (session-start sync call).

Upstream deps: bin/agentic-base-sync, scripts/lib/base-branch-sync.sh.

Downstream consumers: /ds-implement-ticket Phase 12; the conductor session-
                      start preflight in content/rules/conventions.md.

Failure modes: Prose + bash reference; does not auto-execute. A stale copy of
               this doc would misdescribe the exit-code/status contract -
               keep in sync with scripts/lib/base-branch-sync.sh, which is
               the executable source of truth.
-->

# Base-branch sync

## Purpose

Merging a PR to `BASE_BRANCH` leaves the conductor's (or any session's) local `BASE_BRANCH` ref exactly where it was - nothing in the methodology ever fast-forwards it automatically. Without an explicit sync step, the local checkout drifts one commit further behind per merge until a later `git pull --ff-only` refuses outright and the tree jams. `agentic-base-sync` is the one canonical, testable procedure that closes this gap: it fast-forwards the local `<base-branch>` ref to match `origin/<base-branch>`, and nothing else.

## CLI contract

```
usage: agentic-base-sync <repo> <base-branch>

Fast-forwards the LOCAL <base-branch> ref in <repo> to match origin/<base-branch>.
Never merges, rebases, force-pushes, or autostashes.

Exit codes are NORMALIZED by this wrapper - git's own native exit codes (1 for a
`pull --ff-only` dirty-overwrite refusal; 128 for a true `pull --ff-only` divergence,
for `fetch origin base:base` refusing a non-fast-forward write, AND for that same
fetch refusing to write a ref checked out in another worktree - three distinct
conditions on one native code) are never passed through. The wrapper's contract:

  0  synced - status=ff-pulled (HEAD was on <base-branch>) or status=ff-updated-ref
     (HEAD was elsewhere). Covers a real fast-forward and an already-up-to-date no-op.
     On success, if the local branch is ALSO ahead of origin by N unpushed commits
     (behind=0, ahead=N - the precursor state to the handoff's jam), an additional
     informational `NOTE:` line is printed on stdout; this does NOT change the exit
     code or the breadcrumb status.
  1  diverged - local <base-branch> has commits not present on origin/<base-branch>,
     CONFIRMED via `rev-list --left-right --count` after a fresh plain re-fetch of
     origin/<base-branch> (never inferred from git's raw exit code or from a shared
     fall-through). Local ref and working tree are left untouched. Diagnostic +
     recovery guidance printed.
  2  skipped-dirty - HEAD was on <base-branch> and git's own merge-overwrite check
     (matched locale-independently via `LC_ALL=C`) refused the pull because a dirty
     path would be clobbered. Local ref and working tree untouched. A dirty tree
     whose modified/untracked files are untouched by the incoming commits SYNCS
     SUCCESSFULLY (exit 0) - only an actual overwrite conflict lands here.
  3  usage / repo-resolution / argument error - includes an empty or missing
     `<repo>` or `<base-branch>` argument, validated BEFORE any git call, printed
     to stderr, mirrors `agentic-resolve-worktree`.
  4  inconclusive - sync could not be verified or completed this run, and is NOT
     itself evidence of divergence. Three distinct sub-causes, each printed with
     its own distinct breadcrumb status (never collapsed into one):
       status=fetch-failed         - origin unreachable (network/auth). Verify-fetch's
                                      own stderr is printed, not the original
                                      ref-write attempt's stderr.
       status=refused-unknown      - HEAD was ON <base-branch>, the refusal was
                                      neither a dirty-overwrite nor a confirmed
                                      divergence (ahead==0, or divergence could not
                                      be computed because origin/<base-branch> is
                                      absent post-fetch, e.g. a --single-branch
                                      clone). git's own refusal text is printed
                                      verbatim. NEVER emitted as ref-locked-elsewhere
                                      (that status is structurally impossible on
                                      this branch - <base-branch> is checked out in
                                      THIS repo, not "another worktree").
       status=ref-locked-elsewhere - HEAD was ELSEWHERE, the ref-write fetch refused,
                                      and divergence was confirmed absent (ahead==0
                                      with a valid, non-empty count). This is the
                                      ONLY status emitted from the HEAD-elsewhere
                                      path's non-divergent refusal, and the ONLY
                                      status that can name "another worktree" as
                                      cause, because it is the only path where that
                                      cause is reachable. When the HEAD-elsewhere
                                      path's post-refusal counts come back EMPTY
                                      (origin/<base-branch> absent post-fetch), it
                                      also reports status=refused-unknown instead -
                                      "checked out elsewhere" cannot be concluded
                                      without a valid count to confirm ahead==0.

Stdout (always, on any exit): exactly one breadcrumb line, plus zero or more
`WARNING:`/`NOTE:` lines preceding it:
  [phase: base-sync | status=ff-pulled | branch=<base>]
  [phase: base-sync | status=ff-updated-ref | branch=<base> | head=<current-head-branch>]
  [phase: base-sync | status=skipped-dirty | branch=<base>]
  [phase: base-sync | status=diverged | branch=<base>]
  [phase: base-sync | status=refused-unknown | branch=<base>]
  [phase: base-sync | status=ref-locked-elsewhere | branch=<base>]
  [phase: base-sync | status=fetch-failed | branch=<base>]
```

**Structural rule.** `refused-unknown` and `ref-locked-elsewhere` are never both reachable from the same branch of the classification. `ref-locked-elsewhere` ("base checked out in another worktree") can only be true when `<base-branch>` is checked out in a worktree OTHER than `<repo>` - a condition that cannot exist when `<repo>` itself has `<base-branch>` checked out (the HEAD-on-base path). Symmetrically, `refused-unknown`'s catch-all "unrecognized refusal while base IS checked out here" reasoning cannot fire on the HEAD-elsewhere path, since base is never checked out in `<repo>` there. Each path computes and returns its own terminal status; there is no shared post-refusal code path between them.

**Exercising `refused-unknown` in a test or by hand.** Because `refused-unknown` requires a `pull --ff-only` refusal that is neither a dirty-overwrite conflict nor a real divergence, the easiest reliable way to construct it in a scratch clone is to create `.git/index.lock` in the clone before invoking the tool (HEAD on base) - this produces `error: ... Unable to create '.../index.lock': File exists.`, which does not match the dirty-overwrite grep and is not a divergence, landing on `status=refused-unknown` with exit 4. Removing the lock and re-running syncs normally (`status=ff-pulled`, exit 0).

## Base-branch sync procedure

`bin/agentic-base-sync <repo> <base-branch>` is a thin CLI wrapper (argc/repo-dir/git-repo-ness validation, exit 3 on any such error, mirroring `bin/agentic-resolve-worktree`'s error style) around `ae_base_branch_sync`, defined in `scripts/lib/base-branch-sync.sh`:

```bash
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
```

`bin/agentic-base-sync` sources this function from `scripts/lib/base-branch-sync.sh`, performs the argc check (exactly 2 args) plus repo-dir/git-repo-ness validation the same way `agentic-resolve-worktree` does (all exit 3 on failure, mirroring that tool's error style), calls `ae_base_branch_sync "$1" "$2"` (which independently re-validates non-empty `$1`/`$2` as its own defense-in-depth precondition), and does `exit $?`. The library function `return`s, never `exit`s; only the CLI wrapper `exit`s.

## Divergence diagnostic format

`status=diverged` only:

```
WARNING: local <base> has diverged from origin/<base> (behind/ahead: <N>/<M>) - fast-forward sync refused.
Local-only commits on <base>:
<git log origin/<base>..<base> --oneline output>
Recovery: push or cherry-pick the local-only commits above onto a branch cut from origin/<base>; do not rebase or merge the shared <base> tree.
[phase: base-sync | status=diverged | branch=<base>]
```

Ahead-only, exit-0 success paths additionally print an informational (non-failing) note when the local branch has unpushed commits:

```
NOTE: local <base> is <N> commit(s) ahead of origin/<base> with nothing to pull - these are unpushed local-only commits. Push them soon: this is the exact precursor state the handoff's jammed-tree scenario started from.
```

## Recovery

The tool never rewrites the shared `<base-branch>` tree on divergence. On `status=diverged`, the operator or conductor must manually:

1. Inspect the local-only commits printed in the diagnostic (`git log origin/<base>..<base> --oneline`).
2. Push them to a personal branch cut from `origin/<base>`: `git branch recovery/<base>-<date> <base>`, then `git push -u origin recovery/<base>-<date>`. Or cherry-pick them onto a fresh branch.
3. Never `git rebase` or `git merge` the shared `<base>` tree to resolve this - both would rewrite or entangle history other sessions rely on.

## Call sites

- **`content/commands/ds-implement-ticket.md` Phase 12 (unconditional tail).** Runs once at the end of every Phase 12, independent of `auto_merge_on_ci_green` and independent of whether this ticket's own PR merged - it also catches a *different* PR (this ticket's or any other) that merged asynchronously since the session started. Invoked via the repo-relative path `$REPO_DIR/bin/agentic-base-sync`, so it works without a PATH re-install. Only fires inside a `/ds-implement-ticket` invocation.
- **`content/rules/conventions.md` Conductor preflight, step 6.** Fires once at session start, immediately after `BASE_BRANCH` is resolved non-interactively (declaration, local `develop`, or local `development` matched). Invoked via PATH (`agentic-base-sync`), guarded by `command -v`. This is the mechanism that catches a PR merged by a human, by another session, or via `gh pr merge` outside `/ds-implement-ticket` entirely - call site 1 cannot catch a merge that happens between `/ds-implement-ticket` invocations or in a different tool entirely. Skipped silently when `BASE_BRANCH` still requires the interactive prompt.

Neither call site alone is sufficient - Phase 12's call gives immediate in-session confirmation for merges that happen during a `/ds-implement-ticket` run; the preflight call catches everything else.
