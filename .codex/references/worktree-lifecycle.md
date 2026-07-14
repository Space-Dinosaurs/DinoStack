<!--
Purpose: Full reference for worktree and branch lifecycle command blocks
         extracted from METHODOLOGY.md §Worktree Lifecycle. Contains the
         isolation worktree cleanup commands, feature worktree cleanup commands,
         the session-start prune script, and the local-branch prune block.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/11-worktree-lifecycle.md (inline pointers replacing
            each bash block),
            content/sections/12-protocol-details.md (Worktree lifecycle Protocol
            Details entry).

Upstream deps: content/sections/11-worktree-lifecycle.md (parent section; read
               that section first for the two-class summary, isolation mandate,
               and session-start prune rule).

Downstream consumers: conductor preflight (session-start prune script and
                      branch prune block); conductor cleanup flows (isolation
                      and feature worktree removal commands);
                      /cleanup-worktrees command; /implement-ticket lifecycle
                      cleanup; the Isolation-worktree liveness lock section
                      (conductor-side and engineer-side lock contracts).

Failure modes: Prose + bash blocks; does not auto-execute. Using force-remove
               without the status check first risks losing uncommitted work.
               The --delete-branch flag on gh pr merge may not auto-delete in
               all gh CLI versions; the explicit git branch -D is the fallback.
               The branch prune block never force-deletes unproven work - see
               Safe boundary note in that section. A locked-but-dir-missing
               worktree entry survives git worktree prune until explicitly
               unlocked first - both cleanup paths above now do this.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Worktree Lifecycle. Read that section first for the two-class summary, isolation mandate, and session-start prune rule.

# Worktree and Branch Lifecycle - Full Reference

## Isolation worktree cleanup commands

Once the agent returns its output and the conductor has opened a PR (or confirmed no PR is needed), the isolation worktree is redundant - the branch holds the commits. The conductor must remove it immediately:

```bash
# Verify no uncommitted changes before removing:
git -C <worktree-path> status --porcelain
# If clean (no output), remove the worktree and its branch:
git worktree unlock <worktree-path> 2>/dev/null || true   # NEW: release the liveness lock (see §Isolation-worktree liveness lock) before removing
git worktree remove <worktree-path>
git branch -D <branch-name> 2>/dev/null || true   # branch lingers otherwise; safe to delete once worktree is removed
# Safe even with a PR open: the PR is backed by the branch on origin, not this local ref.
# Only the redundant local branch is removed; the pushed commits and the PR are unaffected.
# (If you might still push follow-up commits to the PR from this checkout, keep the branch until the PR merges.)
# If the above fails (modified tracked files exist), inspect them first,
# then force-remove only after confirming nothing important is uncommitted:
# git worktree remove --force <worktree-path>
# git branch -D <branch-name>
```

## Isolation-worktree liveness lock

`worktree-agent-*` isolation worktrees are `git status`-clean for their entire pre-commit lifetime (engineers commit once, at the end). Cleanliness alone can never distinguish a live engineer from an abandoned one. The fix is a git-native `git worktree lock`: a locked worktree refuses non-force AND single-`-f`-force `git worktree remove` (`fatal: cannot remove a locked working tree ... use 'remove -f -f' to override or unlock first`), its checked-out branch refuses `git branch -D`, and `git worktree prune` leaves it untouched - verified on git 2.39.5.

**Primary mechanism - conductor-side lock, set immediately after spawn.**

```bash
# BEFORE issuing the Agent spawn call(s) with isolation: "worktree":
PRE_WT_SNAPSHOT="$(mktemp)"
git worktree list --porcelain | awk '/^worktree /{print $2}' > "$PRE_WT_SNAPSHOT"

# Issue the spawn call(s) now. Isolation spawns run in the background by default, so
# control returns to the conductor immediately - do NOT wait for the subagent to return
# before running the sweep below; run it in the same turn.

# IMMEDIATELY after the spawn call(s) return control:
git worktree list --porcelain | awk '
  FNR==NR { seen[$0]=1; next }
  /^worktree / { path=$2; is_new=!(path in seen) }
  /^branch refs\/heads\/worktree-agent-/ { if (is_new) print path }
' "$PRE_WT_SNAPSHOT" - | while read -r wt; do
  git worktree lock "$wt" --reason "conductor-locked: engineer active, spawned $(date -u +%FT%TZ)" 2>/dev/null || true
done
rm -f "$PRE_WT_SNAPSHOT"
```

This exact `FNR==NR` temp-file transport is required - **never** pass a multi-line snapshot value via `awk -v`, which fails hard on BSD awk (macOS default `/usr/bin/awk`): `awk: newline in string ... at source line 1`, exit 2, zero output, with the failure silent to the conductor (stderr only; the downstream `while read` loop simply iterates zero times).

**Residual race, stated precisely.** "Minimized, not eliminated" is accurate only where the sweep above actually runs (i.e., it must be this BSD-safe form). Given that, a small window remains between the harness creating the worktree (part of the Agent tool call) and this sweep executing - not prevented, minimized to a single tool-call round-trip. If the sweep somehow does not run at all (conductor skips the step, or an environment lacks `awk`/`mktemp`), the engineer-side lock-on-entry below is the SOLE protection for that spawn, carrying its own window (the engineer's first-Bash-call timing) - a degraded-but-not-silent fallback, not equivalent coverage.

**Defense-in-depth - engineer-side lock on entry.**

```bash
if git rev-parse --show-toplevel 2>/dev/null | grep -q '/worktree-agent-'; then
  git worktree lock "$(git rev-parse --show-toplevel)" --reason "engineer-locked: pid=$$ since=$(date -u +%FT%TZ)" 2>/dev/null || true
fi
```

Detection is by the worktree's own directory path, not `git branch --show-current` - the path stays stable even after the engineer renames its own branch per its `worktree_setup` contract, and it does not silently no-op on detached HEAD the way a branch-name check would. This is a backstop only. A forgetful or crashed engineer that never reaches this line is still covered by the conductor-side lock. Locking twice is harmless - the second call errors "already locked" and is swallowed.

**Owner cleanup (unlock-before-remove/prune).** The conductor (never the engineer) unlocks and removes a worktree once its work has landed in a PR:

```bash
git worktree unlock <worktree-path> 2>/dev/null || true
git worktree remove <worktree-path>
```

**Stale-ceiling scope (honest statement).** The 24-hour stale-then-confirm ceiling in `/cleanup-worktrees` Step 3 Case 1 covers ONLY a locked worktree whose directory still exists and is clean - a crashed engineer the harness never removed. It does NOT cover: a DIRTY crashed worktree (never auto-removed by design, regardless of age - uncommitted work always needs a human look); or a worktree whose directory was removed out from under git while still locked (Case 2 - no time ceiling needed there; unlock-then-prune is safe immediately since there is no working tree left to protect).

**Portable mtime.**

```bash
mtime_epoch() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null; }
```

## Feature worktree cleanup commands

Feature worktrees (`feature/*`, `fix/*`, `chore/*`) are removed after the PR is merged:

```bash
gh pr merge <number> --squash --delete-branch
git worktree remove --force <worktree-path>
git branch -D <branch-name>   # if not auto-deleted by --delete-branch
git worktree prune             # clean up any stale metadata
```

## Session-start prune script

Run at session start (conductor preflight) - ONCE per session, not before every subagent spawn:

```bash
# Run at session start (conductor preflight):
git fetch origin
# Unlock any locked entry whose directory is already gone, so prune can actually clear
# the stale admin metadata - a lock never protects a worktree that no longer exists:
git worktree list --porcelain | awk '
  /^worktree /{p=$2; locked=0}
  /^locked/{locked=1}
  /^$/{if (p && locked) print p; p=""}
' | while read -r p; do
  [ -d "$p" ] || git worktree unlock "$p" 2>/dev/null || true
done
git worktree prune
# Base branch (BASE_BRANCH) is NOT resolved here - it is resolved lazily on first shippable need; see content/rules/conventions.md, "Base branch resolution".
# Delete any worktree-agent-* branches not currently checked out in a worktree.
# NOTE: `git branch` prefixes a branch checked out in ANOTHER linked worktree with `+`
# (not just `*` for the current one) - the sed must strip both, or the guard below
# silently misparses the name and the liveness check/delete operate on a malformed string:
git branch | grep 'worktree-agent-' | sed 's/^[*+ ]*//' | while read b; do
  git worktree list | grep -qF "[$b]" || git branch -D "$b"
done
```

## Branch prune (stale local branches)

Run at session start alongside the session-start prune script. Targets three classes of stale local branch with safe signals only - never force-deletes work that cannot be proven merged:

```bash
# Prune stale LOCAL branches. Safe signals only; never force-delete unproven work.
git fetch origin --prune                       # drop stale remote-tracking refs

# 1. Branches whose upstream is gone (merged + remote deleted via squash + --delete-branch):
git for-each-ref --format '%(refname:short) %(upstream:track)' refs/heads \
  | awk '$2=="[gone]"{print $1}' | xargs -r -n1 git branch -D

# 2. Branches fully merged into origin/main:
git branch --merged origin/main | grep -vE '^[*+]|(^| )(main|master)$' | xargs -r -n1 git branch -d

# 3. worktree-agent-* branches whose worktree no longer exists:
#    (a branch checked out in a live worktree is protected by git and will be skipped)
for b in $(git for-each-ref --format='%(refname:short)' 'refs/heads/worktree-agent-*'); do
  git branch -D "$b" 2>/dev/null || true
done
```

**Safe boundary:** any branch that has no upstream AND is not merged into `origin/main` is left alone. Its work cannot be proven merged and force-deleting it would risk loss. Report such branches for manual review rather than deleting them automatically.

**Why `[gone]` is the reliable signal:** after a history rewrite (such as the 2026-06-14 pre-OSS filter-repo purge) squash-merged pre-rewrite branches are not ancestors of the rewritten `main`, so ancestry checks alone miss them. The `[gone]` upstream marker - set when `git fetch --prune` drops the deleted remote ref - is the reliable "was merged and remote-cleaned" signal, which is why step 1 keys on `[gone]` rather than ancestry alone. Deletions performed by this block are recoverable via `git reflog` for the duration of the reflog retention window (default 90 days).

## Version floor: isolated-worktree own-file edits (load-bearing)

DinoStack's mandatory-isolation rule (every `engineer`/`qa-engineer`/`release-orchestrator` spawn runs in its own worktree) depends on a Claude Code fix that lets an isolated subagent read and edit files inside its OWN worktree. On builds predating that fix, an isolated engineer self-denies on its own files and deadlocks - it cannot edit the very tree it was spawned to change. Treat the fix as a hard floor for the delegation model. Keep the aggressive per-session worktree prune above regardless of Claude Code's own 30-day orphan sweep: the sweep cleans Claude Code's isolation worktrees on a monthly cadence and is a backstop, not a replacement; stale worktrees accumulate between sweeps.

## Pre-spawn stash fallback

Pre-spawn safety net (fallback, not a substitute for isolation): before any non-isolated spawn that the conductor cannot avoid, the conductor stashes its scaffolding to keep it out of the subagent's working tree:

```bash
git stash push --include-untracked --keep-index --message 'conductor-scaffolding-pre-spawn'
# ... spawn returns ...
git stash pop
```

This is a fallback only. Worktree isolation is the primary mechanism; the stash dance exists for the rare case where isolation is genuinely not possible (e.g. the Trivial carve-out interleaving with an unexpected concurrent spawn).
