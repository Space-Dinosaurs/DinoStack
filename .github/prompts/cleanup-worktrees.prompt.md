---
description: "Clean up stale git worktrees and local branches in the current repository. Covers both worktree removal and local branch"
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

For each isolation worktree, first check whether it is locked - the lock (set by the conductor immediately after spawning the engineer, and by the engineer on entry as a backstop; see `content/references/worktree-lifecycle.md` §Isolation-worktree liveness lock) is the authoritative liveness signal, not working-tree cleanliness:

```bash
git worktree list --porcelain
```

Find the worktree's stanza. If it contains a `locked` line, evaluate Case 1. Otherwise check `git -C <worktree-path> status --porcelain` and evaluate Cases 2-4, in this order (first match wins):

**Case 1 - Locked, directory exists:**

```bash
mtime_epoch() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null; }
age_seconds=$(( $(date +%s) - $(mtime_epoch "<worktree-path>") ))
```

If `age_seconds` <= 86400 (24h): skip, report "live (locked)" - regardless of clean/dirty.

If `age_seconds` > 86400 (>24h):
- AND `git -C <worktree-path> status --porcelain` is clean: report "possibly-orphaned locked worktree (locked >24h, clean)" and remove ONLY after explicit user confirmation:
  ```bash
  git worktree unlock <worktree-path>
  git worktree remove <worktree-path>
  git branch -D <branch-name>
  ```
- AND dirty: report "possibly-orphaned locked but dirty (>24h) - manual review needed" and skip. NEVER auto-remove - a dirty worktree, locked or not, always needs a human to inspect the diff first. Do not offer an automated removal path for this sub-case, even on confirmation.

**Case 2 - Directory does not exist** (command errors with "not a git repository" or similar): the lock (if any) no longer protects anything - there is no working tree left. Unlock first (safe unconditionally here, since nothing is lost), then prune, then delete the branch (unconditional force-D - see the Intent note above for why gating this on `[gone]`/merged status would strand it forever):
```bash
git worktree unlock <worktree-path> 2>/dev/null || true
git worktree prune
git branch -D <branch-name>
```

**Case 3 - Directory exists, dirty:** List the dirty files and skip removal. Report to the user - do not remove without explicit confirmation. Uncommitted work in an agent worktree may be important.

**Case 4 - Directory exists, clean, unlocked:** apply a shallow recency backstop - if the worktree's directory mtime is within the last 30 minutes, skip and report "possibly live (recently active, unlocked)". This backstop covers only the conductor-lock's small residual spawn-to-lock race window and any legacy pre-lock worktree; it does NOT reliably detect a purely-reading engineer (mtime does not move on reads) - the lock (Case 1) is the real protection. Otherwise remove:
```bash
git worktree remove <worktree-path>
git branch -D <branch-name>
```

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

Run the canonical branch prune from `content/references/worktree-lifecycle.md §Branch prune (stale local branches)`. It targets three classes of stale local branch with safe signals only - branches with no upstream and not merged into `origin/main` are left alone and reported to the user for manual review.

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
