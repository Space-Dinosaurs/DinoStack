## Worktree Lifecycle

**Isolation is mandatory for every shippable-edit spawn.** Every `engineer`, `qa-engineer`, and `release-orchestrator` spawn MUST set `isolation: "worktree"` on the Agent tool call. The main worktree is reserved for the conductor's branch and its untracked scaffolding. No exception: the Trivial-path solo `engineer` spawn is also `isolation: "worktree"`.

**Subagents do not have hooks.** Hooks fire only in the main session. Isolation worktrees with no changes are auto-cleaned by the Agent tool. Isolation worktrees with changes persist until the conductor explicitly removes them.

Read `content/references/worktree-lifecycle.md` for cleanup command blocks (isolation and feature worktrees) and the session-start prune script.
