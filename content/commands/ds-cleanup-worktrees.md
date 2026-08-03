# /ds-cleanup-worktrees

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

## Step 2: List and classify active worktrees

```bash
git worktree list
```

The **first entry** is always the main worktree - the repo root directory. Skip it unconditionally regardless of what branch it is on.

Classify every remaining entry by **path relative to the repo root, never by branch name** - this is what `classify_entry()` in `bin/tests/worktree_model.py` does, and it is the single normative definition of the four classes below (DS-118 defect 1: a `feature/*`/`fix/*`/`chore/*`-named branch can and does live inside a `.claude/worktrees/` isolation directory once renamed post-creation, which a branch-name-only heuristic cannot disambiguate). Where this prose and `classify_entry` disagree, `classify_entry` wins.

- **Isolation worktrees** - path starts with `.claude/worktrees/` -> `WorktreeClass.ISOLATION`. Temporary agent sandboxes. Go to Step 3.
- **Feature (conductor-created) worktrees** - path starts with `.agentic/worktrees/` -> `WorktreeClass.CONDUCTOR_CREATED`. Long-lived task branches. Go to Step 4.
- **Anything else** - `WorktreeClass.UNMANAGED` (a bare-repo entry, a path outside this repo's own host, or a path under neither admin directory, e.g. `evals/.worktrees/wt-*`). Report it to the user and skip removal.

---

## Step 3: Remove isolation worktrees

For each ISOLATION-classified entry, apply `disposition_for()`'s gate order - locked, dirty, then merge-evidence-independent-of-push (`bin/tests/worktree_model.py`; where this prose and `disposition_for` disagree, `disposition_for` wins). (Note: if a worktree is still locked - its agent actively running, per Claude Code's own lock-while-running behavior - the `git worktree remove` and `git branch -D` below are refused by git automatically; this is expected, not an error to route around - `SKIP_LOCKED`.)

Resolve its path from the branch name and check its status before touching it:

```bash
source "${REPO_DIR:-.}/scripts/lib/worktree.sh" 2>/dev/null || true
WORKTREE_PATH=$(resolve_branch_worktree "$REPO_DIR" "$b" 2>/dev/null || true)
git -C "$WORKTREE_PATH" status --porcelain 2>/dev/null
```

where `$b` is the branch name from `git worktree list` for the current isolation worktree.

**Directory does not exist** (command errors with "not a git repository" or similar): The directory was already removed before this command ran. If the entry is still locked, a bare `git worktree prune` will NOT clear it - unlock first, then prune, then delete the branch:

```bash
git worktree unlock "$WORKTREE_PATH" 2>/dev/null || true
git worktree prune
git branch -D "$b"
```

**Directory exists, dirty (output present)** (`SKIP_DIRTY`): List the dirty files and skip removal. Report to the user - do not remove without explicit confirmation. Uncommitted work in an agent worktree may be important.

**Directory exists, clean (no output):** resolve merge evidence in `disposition_for`'s order - `merge_evidence` (ancestry) first, then `pr_state`, then `ls_remote_status` last, since push status alone is never sufficient proof of merge:

```bash
HEAD_SHA=$(git -C "$WORKTREE_PATH" rev-parse HEAD)
git merge-base --is-ancestor "$HEAD_SHA" origin/main 2>/dev/null && MERGE_EVIDENCE=merged || MERGE_EVIDENCE=unmerged
```

- `MERGE_EVIDENCE=merged` (`ELIGIBLE`): remove the worktree and delete the branch:

```bash
git worktree remove "$WORKTREE_PATH"
git branch -D "$b"
```

- `MERGE_EVIDENCE=unmerged`: fall back to PR state, if `gh` is available - `gh pr view "$b" --json state -q .state`. `OPEN` skips (`SKIP_PR_OPEN`, report to the user); `MERGED` is `ELIGIBLE` (remove as above - covers a squash-merge ancestry missed). `CLOSED`/no PR/`gh` unavailable falls through to push status: `git ls-remote --exit-code --heads origin "$b"` - absent -> `SKIP_NOT_PUSHED`, command error -> `SKIP_LS_REMOTE_ERROR`, present -> `SKIP_AMBIGUOUS_NO_PR`. Every skip outcome here reports the branch to the user for manual review - never delete on an inconclusive read.

---

## Step 4: Remove feature (conductor-created) worktrees with merged PRs

For each CONDUCTOR_CREATED-classified entry, apply `disposition_for()`'s gate order - locked, **dirty (this check was previously missing here - closing that gap)**, then merge-evidence-independent-of-push:

**Locked** (`SKIP_LOCKED`): as in Step 3.

**Dirty** (`SKIP_DIRTY`):

```bash
git -C <worktree-path> status --porcelain
```

Any output: skip removal, list the dirty files, and report to the user.

**Clean only - merge evidence.** Check whether the branch's PR has been merged:

```bash
gh pr list --state all --head <branch-name> --json number,state,title
```

**If state is `MERGED`:** remove the worktree and delete the branch:

```bash
git worktree remove <worktree-path>
git branch -D <branch-name>
```

**If state is `OPEN` or `CLOSED` (not merged):** skip removal (`SKIP_PR_OPEN` / inconclusive). Report the branch name, PR number, and state to the user so they can decide.

**If no PR exists:** fall back to ancestry (`git merge-base --is-ancestor <head> origin/main`). Merged -> `ELIGIBLE`, remove as above. Still unmerged -> `SKIP_AMBIGUOUS_NO_PR`. Report the branch as needing manual review.

**If `gh` is not available:** skip the PR check for all feature worktrees; fall back to the ancestry check alone. Report each feature worktree still unmerged as "needs manual review - gh CLI not available". Do not block or error.

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
