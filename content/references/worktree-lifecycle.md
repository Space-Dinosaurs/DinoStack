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
                      cleanup.

Failure modes: Prose + bash blocks; does not auto-execute. Using force-remove
               without the status check first risks losing uncommitted work.
               The --delete-branch flag on gh pr merge may not auto-delete in
               all gh CLI versions; the explicit git branch -D is the fallback.
               The branch prune block never force-deletes unproven work - see
               Safe boundary note in that section.

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
git worktree remove <worktree-path>
git branch -D <branch-name> 2>/dev/null || true   # branch lingers otherwise; safe to delete once worktree is removed
# If the above fails (modified tracked files exist), inspect them first,
# then force-remove only after confirming nothing important is uncommitted:
# git worktree remove --force <worktree-path>
# git branch -D <branch-name>
# Do NOT delete the branch while a PR is open - it backs the open PR.
# Exception: if no PR was opened (task cancelled/no PR needed), delete the branch as shown above.
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
git worktree prune
# Resolve base branch (main > master > develop > development):
# Cache result as BASE_BRANCH in-context
# Delete any worktree-agent-* branches not currently checked out in a worktree:
git branch | grep 'worktree-agent-' | sed 's/^[* ]*//' | while read b; do
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
git branch --merged origin/main | grep -vE '^[*+]|(^| )main$' | xargs -r -n1 git branch -d

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
