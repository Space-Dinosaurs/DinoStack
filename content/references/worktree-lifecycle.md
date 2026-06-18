<!--
Purpose: Full reference for worktree lifecycle command blocks extracted from
         METHODOLOGY.md §Worktree Lifecycle. Contains the isolation worktree
         cleanup commands, feature worktree cleanup commands, and the
         session-start prune script.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/11-worktree-lifecycle.md (inline pointers replacing
            each bash block),
            content/sections/12-protocol-details.md (Worktree lifecycle Protocol
            Details entry).

Upstream deps: content/sections/11-worktree-lifecycle.md (parent section; read
               that section first for the two-class summary, isolation mandate,
               and session-start prune rule).

Downstream consumers: conductor preflight (session-start prune script);
                      conductor cleanup flows (isolation and feature worktree
                      removal commands); /implement-ticket lifecycle cleanup.

Failure modes: Prose + bash blocks; does not auto-execute. Using force-remove
               without the status check first risks losing uncommitted work.
               The --delete-branch flag on gh pr merge may not auto-delete in
               all gh CLI versions; the explicit git branch -D is the fallback.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Worktree Lifecycle. Read that section first for the two-class summary, isolation mandate, and session-start prune rule.

# Worktree Lifecycle - Full Reference

## Isolation worktree cleanup commands

Once the agent returns its output and the conductor has opened a PR (or confirmed no PR is needed), the isolation worktree is redundant - the branch holds the commits. The conductor must remove it immediately:

```bash
# Verify no uncommitted changes before removing:
git -C <worktree-path> status --porcelain
# If clean (no output), remove:
git worktree remove <worktree-path>
# If the above fails (modified tracked files exist), inspect them first,
# then force-remove only after confirming nothing important is uncommitted:
# git worktree remove --force <worktree-path>
# Do NOT delete the branch - it backs the open PR.
# Exception: if no PR was opened (task cancelled/no PR needed), also delete the branch:
# git branch -D <branch-name>
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
