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
                      /ds-cleanup-worktrees command; /ds-implement-ticket lifecycle
                      cleanup.

Failure modes: Prose + bash blocks; does not auto-execute. Using force-remove
               without the status check first risks losing uncommitted work.
               The --delete-branch flag on gh pr merge may not auto-delete in
               all gh CLI versions; the explicit git branch -D is the fallback.
               The branch prune block never force-deletes unproven work - see
               Safe boundary note in that section. A locked-but-dir-missing
               worktree admin entry survives a bare `git worktree prune` - the
               isolation-cleanup and session-start-prune paths both unlock
               before pruning to reclaim it.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Worktree Lifecycle. Read that section first for the two-class summary, isolation mandate, and session-start prune rule.

# Worktree and Branch Lifecycle - Full Reference

## Isolation worktree cleanup commands

Isolation worktrees are removed inline after the branch has been pushed to
origin. Once commits are on origin, the PR/branch is backed by the remote ref,
so the local worktree is redundant. Cleaning up at push time avoids the
branch-rename mapping problem that makes "after PR open" cleanup unreliable.

```bash
# Resolve worktree path from branch name (works even if the branch was renamed).
# Requires scripts/lib/worktree.sh to be sourced.
source "${REPO_DIR}/scripts/lib/worktree.sh"
WORKTREE_PATH=$(resolve_branch_worktree "$REPO_DIR" "$BRANCH_NAME")

# Verify no uncommitted changes in the isolated worktree:
[ -n "$WORKTREE_PATH" ] && git -C "$WORKTREE_PATH" status --porcelain

# If clean, remove the isolated worktree and its local branch:
[ -n "$WORKTREE_PATH" ] && git -C "$REPO_DIR" worktree remove "$WORKTREE_PATH"
git -C "$REPO_DIR" branch -D "$BRANCH_NAME" 2>/dev/null || true
```

This is the self-scoped inline pattern; it does not need the general disposition model in `bin/tests/worktree_model.py` (`disposition_for` / `disposition_for_orphan_branch`) because it only ever operates on the branch the current session just pushed in the same phase.

If the worktree is still locked by a running agent, `git worktree remove` will
refuse until the agent finishes. That is expected and safe; the session-start
prune script below remains a backstop.

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
# the stale admin metadata - a locked-but-dir-missing entry is NOT cleared by a bare
# `git worktree prune`:
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
  git worktree list | grep -qF "[$b]" && continue
  # Gate the delete via disposition_for_orphan_branch's evidence order
  # (bin/tests/worktree_model.py) rather than deleting unconditionally -
  # `merge_evidence` (ancestry) first, then `pr_state`, then
  # `ls_remote_status` last, mirroring §Branch prune bullets 1/2 below.
  if git merge-base --is-ancestor "$b" origin/main 2>/dev/null; then
    git branch -D "$b"
  elif command -v gh >/dev/null 2>&1 && [ "$(gh pr view "$b" --json state -q .state 2>/dev/null)" = "MERGED" ]; then
    git branch -D "$b"
  else
    echo "SKIP (unproven merge): $b - needs manual review" >&2
  fi
done
```

## Guardrail: never force-override the harness lock

No cleanup or prune path in this document may call `git worktree remove -f -f` (double force, which overrides a lock). `git worktree unlock` may be used ONLY on a worktree whose directory is already gone - at that point its agent cannot still be running, so there is nothing left to protect (this is exactly what the isolation-cleanup and session-start-prune steps do to reclaim a stale locked admin entry). Never unlock, or double-force-remove, a worktree whose directory still exists: the harness's lock (set on every isolation worktree while its agent runs) is load-bearing cross-session protection - it is the reason a concurrent session's cleanup cannot delete another session's live worktree, and overriding it reintroduces exactly the mid-task-deletion risk. No path in this document currently does this; the note is a guardrail against future regression.

## Branch prune (stale local branches)

Run at session start alongside the session-start prune script. Targets three classes of stale local branch with safe signals only - never force-deletes work that cannot be proven merged.

Bullets 1/2's existing selection filters below are pre-model guards, confirmed sound and left unchanged by this ticket - each is already equivalent to the `merge_evidence`/`ls_remote_status` signal `disposition_for_orphan_branch()` (`bin/tests/worktree_model.py`) would compute from the same underlying facts, so no command change was needed to bring them into agreement with the model.

**Bullet 3 targets the identical `worktree-agent-*`-with-no-live-worktree population as the session-start prune script above, at the same session-start phase - it now runs the same merge-evidence gate, not a separate unconditional delete.** An earlier revision of this ticket left bullet 3 ungated on the claim that "no genuine merge-evidence source exists for a bare branch name here" - that claim was false the moment the session-start prune script above gained exactly that source (ancestry, then PR state); shipping the gate in one script and not the other produced zero behavior change (bullet 3 unconditionally deleted whatever the gate above had just skipped) plus new stderr noise. Both scripts now apply the identical check, so a branch either survives both or is deleted by whichever runs first - never gated by one and swept unconditionally by the other.

```bash
# Prune stale LOCAL branches. Safe signals only; never force-delete unproven work.
git fetch origin --prune                       # drop stale remote-tracking refs

# 1. Branches whose upstream is gone (merged + remote deleted via squash + --delete-branch):
#    - equivalent to disposition_for_orphan_branch's ls_remote_status="not_pushed"-adjacent
#      signal (the remote ref is gone because it WAS pushed and then merged+deleted).
git for-each-ref --format '%(refname:short) %(upstream:track)' refs/heads \
  | awk '$2=="[gone]"{print $1}' | xargs -r -n1 git branch -D

# 2. Branches fully merged into origin/main, excluding main/master themselves:
#    - equivalent to disposition_for_orphan_branch's merge_evidence="merged" resolution,
#      with the main/master exclusion mirroring DEFAULT_BASE_BRANCHES / SKIP_BASE_BRANCH.
git branch --merged origin/main | grep -vE '^[*+]|(^| )(main|master)$' | xargs -r -n1 git branch -d

# 3. worktree-agent-* branches whose worktree no longer exists - same merge-evidence
#    gate as the session-start prune script above (ancestry, then PR state):
#    (a branch checked out in a live worktree is protected by git and will be skipped)
for b in $(git for-each-ref --format='%(refname:short)' 'refs/heads/worktree-agent-*'); do
  if git merge-base --is-ancestor "$b" origin/main 2>/dev/null; then
    git branch -D "$b" 2>/dev/null || true
  elif command -v gh >/dev/null 2>&1 && [ "$(gh pr view "$b" --json state -q .state 2>/dev/null)" = "MERGED" ]; then
    git branch -D "$b" 2>/dev/null || true
  else
    echo "SKIP (unproven merge): $b - needs manual review" >&2
  fi
done
```

**Safe boundary:** any branch that has no upstream AND is not merged into `origin/main` is left alone. Its work cannot be proven merged and force-deleting it would risk loss. Report such branches for manual review rather than deleting them automatically.

**Why `[gone]` is the reliable signal:** after a history rewrite (such as the 2026-06-14 pre-OSS filter-repo purge) squash-merged pre-rewrite branches are not ancestors of the rewritten `main`, so ancestry checks alone miss them. The `[gone]` upstream marker - set when `git fetch --prune` drops the deleted remote ref - is the reliable "was merged and remote-cleaned" signal, which is why step 1 keys on `[gone]` rather than ancestry alone. Deletions performed by this block are recoverable via `git reflog` for the duration of the reflog retention window (default 90 days).

## Version floor: isolated-worktree own-file edits (load-bearing)

DinoStack's mandatory-isolation rule (every `engineer`/`qa-engineer`/`release-orchestrator` spawn runs in its own worktree) depends on a Claude Code fix that lets an isolated subagent read and edit files inside its OWN worktree. On builds predating that fix, an isolated engineer self-denies on its own files and deadlocks - it cannot edit the very tree it was spawned to change. Treat the fix as a hard floor for the delegation model. Keep the aggressive per-session worktree prune above regardless of Claude Code's own 30-day orphan sweep: the sweep cleans Claude Code's isolation worktrees on a monthly cadence and is a backstop, not a replacement; stale worktrees accumulate between sweeps.

## Project-override policy

Worktree lifecycle rules - classification (`classify_entry`) and disposition (`disposition_for` / `disposition_for_orphan_branch`, all in `bin/tests/worktree_model.py`) - are methodology-owned and NOT overridable by a project `AGENTS.md`. A project may add non-conflicting project-specific conventions (e.g. pruning its own generated artifacts) but may NOT redefine which path prefixes mean ISOLATION/CONDUCTOR_CREATED, change the disposition gate order, or otherwise contradict the classification or trigger rules in this document.

This is a deliberate absence from the small set of items a project MAY declare - e.g. `BASE_BRANCH:` per `content/rules/conventions.md` §Git Workflow. Unlike the base branch, worktree lifecycle touches cross-session safety: the harness's own lock-while-running behavior, branch-rename mapping across sessions, and another session's live work. A per-project override could not safely account for any of those, so none is offered and no declaration form is defined for it.

## Pre-spawn stash fallback

Pre-spawn safety net (fallback, not a substitute for isolation): before any non-isolated spawn that the conductor cannot avoid, the conductor stashes its scaffolding to keep it out of the subagent's working tree:

```bash
git stash push --include-untracked --keep-index --message 'conductor-scaffolding-pre-spawn'
# ... spawn returns ...
git stash pop
```

This is a fallback only. Worktree isolation is the primary mechanism; the stash dance exists for the rare case where isolation is genuinely not possible (e.g. the Trivial carve-out interleaving with an unexpected concurrent spawn).
