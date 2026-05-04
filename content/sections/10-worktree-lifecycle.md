## Worktree Lifecycle

**Two classes of worktree, two cleanup triggers.**

**Isolation is mandatory for concurrent spawns.** Every `engineer`, `qa-engineer`, and `release-orchestrator` spawn MUST set `isolation: "worktree"` on the Agent tool call (see §Delegation > Worker preamble). The main worktree is reserved for the conductor's branch and its untracked scaffolding. The single exception is the Trivial-path solo `engineer` spawn when no other subagents are running. Everything below assumes isolation is in use for any concurrent or Elevated-path spawn.

**Isolation worktrees (`worktree-agent-*`)** are created by the Agent tool when `isolation: "worktree"` is set. Once the agent returns its output and the conductor has opened a PR (or confirmed no PR is needed), the isolation worktree is redundant - the branch holds the commits. The conductor must remove it immediately:

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

**Feature worktrees (`feature/*`, `fix/*`, `chore/*`)** are removed after the PR is merged:

```bash
gh pr merge <number> --squash --delete-branch
git worktree remove --force <worktree-path>
git branch -D <branch-name>   # if not auto-deleted by --delete-branch
git worktree prune             # clean up any stale metadata
```

**Worktree prune and base-branch resolution run ONCE at session start**, not before every subagent spawn. Cache the resolved base branch in-context for the session. Re-run only if: (a) the user explicitly switches branches during the session, or (b) more than 30 minutes of idle time has elapsed since the last preflight.

```bash
# Run at session start (conductor preflight):
git fetch origin
git worktree prune
# Resolve base branch (develop > development > create develop from main/master):
# Cache result as BASE_BRANCH in-context
# Delete any worktree-agent-* branches not currently checked out in a worktree:
git branch | grep 'worktree-agent-' | sed 's/^[* ]*//' | while read b; do
  git worktree list | grep -qF "[$b]" || git branch -D "$b"
done
```

**Subagents do not have hooks.** Hooks fire only in the main session. Isolation worktrees with no changes are auto-cleaned by the Agent tool. Isolation worktrees with changes persist until the conductor explicitly removes them.
