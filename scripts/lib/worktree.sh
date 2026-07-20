# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Module manifest
# Purpose: Resolve a local branch name to its checked-out git worktree path.
#
# Public API:
#   resolve_branch_worktree <repo> <branch-name>
#     Prints the absolute worktree path for the given branch, or nothing if
#     the branch is not checked out in any worktree.
#
# Upstream deps: git (worktree list --porcelain), awk.
#
# Downstream consumers: content/references/worktree-lifecycle.md,
#                       content/commands/implement-ticket.md,
#                       content/commands/cleanup-worktrees.md,
#                       bin/agentic-resolve-worktree.
#
# Failure modes:
#   - Prints nothing and exits 0 when no worktree matches the branch.
#   - Does not validate that <repo> is a git repository; callers must ensure
#     this (bin/agentic-resolve-worktree does).
#   - Does not distinguish between "branch not checked out" and "branch does
#     not exist"; both result in empty output.
#   - Intentionally does not match detached-HEAD worktrees or remote-tracking
#     refs.
#
# Performance: standard - one `git worktree list --porcelain` per call.
# ---------------------------------------------------------------------------

resolve_branch_worktree() {
  local repo="$1"
  local branch="$2"
  # Normalize: strip refs/heads/ prefix if present.
  branch="${branch#refs/heads/}"
  git -C "$repo" worktree list --porcelain 2>/dev/null | awk -v b="$branch" '
    /^worktree / { path = substr($0, 10) }
    /^branch refs\/heads\// {
      ref = substr($0, 8)
      name = ref
      sub(/^refs\/heads\//, "", name)
      if (name == b && path != "") {
        print path
        found = 1
        exit 0
      }
    }
    /^$/ { path = "" }
    END { if (!found) exit 0 }
  '
}
