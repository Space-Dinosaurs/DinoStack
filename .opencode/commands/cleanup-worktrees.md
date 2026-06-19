---
description: /cleanup-worktrees
agent: build
---
# /cleanup-worktrees

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Clean up stale git worktrees and local branches in the current repository. Covers both worktree removal and local branch prune - see `content/references/worktree-lifecycle.md` §Branch prune for the canonical branch-prune command block.

Use proactively after finishing a task, when a PR is merged, when worktrees are accumulating, or any time you want to confirm the repo is in a clean state. Also invoke when the user says "prune worktrees", "clean up branches", "tidy the repo", or "remove stale worktrees". Works in any git repo.

## Execution model

Run all steps directly in the conductor session via Bash - do NOT spawn background agents. Worktree cleanup is sequential and fast.

---

## Step 1: Fetch and prune metadata

```bash
git fetch origin 2>/dev/null || true
git worktree prune
```

`git fetch origin` is non-fatal - repos without a remote (local test repos, offline environments) will fail here and that is fine. Always continue. `git worktree prune` removes entries pointing to directories that no longer exist on disk.

---

## Step 2: List active worktrees

```bash
git worktree list
```

The **first entry** is always the main worktree - the repo root directory. Skip it unconditionally regardless of what branch it is on.

Categorize each remaining entry by its branch name:

- **Isolation worktrees** - branch matches `worktree-agent-*`. Temporary agent sandboxes. Go to Step 3.
- **Feature worktrees** - branch matches `feature/*`, `fix/*`, or `chore/*`. Long-lived task branches. Go to Step 4.
- **Anything else** - report it to the user and skip removal.

---

## Step 3: Remove isolation worktrees

For each isolation worktree, check its status before touching it:

```bash
git -C <worktree-path> status --porcelain
```

There are three cases:

**Directory does not exist** (command errors with "not a git repository" or similar): The directory was already removed before this command ran. Run `git worktree prune` to clean the stale metadata, then delete the branch.

**Directory exists, clean (no output):** Remove the worktree and delete the branch:

```bash
git worktree remove <worktree-path>
git branch -D <branch-name>
```

**Directory exists, dirty (output present):** List the dirty files and skip removal. Report to the user - do not remove without explicit confirmation. Uncommitted work in an agent worktree may be important.

---

## Step 4: Remove feature worktrees with merged PRs

For each feature worktree, check whether its PR has been merged:

```bash
gh pr list --state all --head <branch-name> --json number,state,title
```

**If state is `MERGED`:** remove the worktree and delete the branch:

```bash
git worktree remove <worktree-path>
git branch -D <branch-name>
```

**If state is `OPEN` or `CLOSED` (not merged):** skip removal. Report the branch name, PR number, and state to the user so they can decide.

**If no PR exists:** skip removal. Report the branch as having no PR and needing manual review.

**If `gh` is not available:** skip the PR check for all feature worktrees. Report each feature worktree as "needs manual review - gh CLI not available". Do not block or error.

---

## Step 5: Prune stale local branches

Run the full branch prune from `content/references/worktree-lifecycle.md` §Branch prune. It covers three classes:

1. Branches whose remote upstream is gone (squash-merged and remote-deleted via `--delete-branch`) - keyed on the `[gone]` upstream marker.
2. Branches fully merged into `origin/main`.
3. Orphaned `worktree-agent-*` branches not checked out in any active worktree.

```bash
git fetch origin --prune

git for-each-ref --format '%(refname:short) %(upstream:track)' refs/heads \
  | awk '$2=="[gone]"{print $1}' | xargs -r -n1 git branch -D

git branch --merged origin/main | grep -vE '^[*+]|(^| )main$' | xargs -r -n1 git branch -d

for b in $(git for-each-ref --format='%(refname:short)' 'refs/heads/worktree-agent-*'); do
  git branch -D "$b" 2>/dev/null || true
done
```

Branches with no upstream and not merged into `origin/main` are left alone - their work cannot be proven merged. Report them to the user for manual review.

---

## Step 6: Final state report

```bash
git worktree prune
git worktree list
```

Report a summary:
- What was removed (worktree path + branch name for each)
- What was skipped (branch name + reason: dirty, PR open, no PR, unknown type)
- Final worktree count

---

## Notes

- **Safety first:** never remove a worktree with uncommitted changes without explicit user confirmation. The status check in Step 3 is not optional.
- Never remove a feature worktree whose PR is still OPEN. Only MERGED PRs are safe to clean up automatically.
- The main worktree (first entry in `git worktree list`) is always skipped.
- Works on the repository in the current working directory - not project-specific.
- If `gh` is not available, flag feature worktrees for manual review and continue.
