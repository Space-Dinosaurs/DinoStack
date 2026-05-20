## Worktree Lifecycle

**Two classes of worktree, two cleanup triggers.**

**Isolation is mandatory for every shippable-edit spawn.** Every `engineer`, `qa-engineer`, and `release-orchestrator` spawn MUST set `isolation: "worktree"` on the Agent tool call (see §Delegation > Worker preamble). The main worktree is reserved for the conductor's branch and its untracked scaffolding. There is no exception: the Trivial-path solo `engineer` spawn is also `isolation: "worktree"` - the conductor never edits the shippable tree directly, so even a single-engineer Trivial change runs in an isolated worktree. Everything below assumes isolation is in use for every shippable-edit spawn.

**Isolation worktrees (`worktree-agent-*`)** are created by the Agent tool when `isolation: "worktree"` is set. Once the agent returns its output and the conductor has opened a PR (or confirmed no PR is needed), the isolation worktree is redundant - the branch holds the commits. The conductor must remove it immediately. See `content/references/worktree-lifecycle.md` §Isolation worktree cleanup commands for the command block.

**Feature worktrees (`feature/*`, `fix/*`, `chore/*`)** are removed after the PR is merged. See `content/references/worktree-lifecycle.md` §Feature worktree cleanup commands for the command block.

**Worktree prune and base-branch resolution run ONCE at session start**, not before every subagent spawn. Cache the resolved base branch in-context for the session. Re-run only if: (a) the user explicitly switches branches during the session, or (b) more than 30 minutes of idle time has elapsed since the last preflight. See `content/references/worktree-lifecycle.md` §Session-start prune script for the command block.

**Subagents do not have hooks.** Hooks fire only in the main session. Isolation worktrees with no changes are auto-cleaned by the Agent tool. Isolation worktrees with changes persist until the conductor explicitly removes them.
