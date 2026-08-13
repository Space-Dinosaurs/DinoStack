---
description: "Clean up stale git worktrees and local branches in the current repository. Covers both worktree removal and local branch"
---
# /ds-cleanup-worktrees

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

Clean up stale git worktrees and local branches in the current repository. Covers both worktree removal and local branch prune - see `content/references/worktree-lifecycle.md` §Branch prune for the canonical branch-prune command block.

`bin/ds-reap-worktrees` is an executable, machine-invocable form of Steps 2-4 below - it delegates the LOCKED/DIRTY/branch-evidence decision to `disposition_for` itself (`bin/tests/worktree_model.py`), the same function these steps already cite as normative, so it can no longer diverge from the manual predicate the way a bespoke reimplementation could (a round-2 Skeptic Critical/Major review caught exactly that divergence in an earlier version and required this delegation). It additionally applies three safety floors the manual steps below do not: a self-worktree guard (never reaps the worktree the invoking process is running inside), an age floor (default 24h - a worktree can be unlocked yet still belong to a resumable session), and a gitignored-content guard - a worktree can report CLEAN under plain `git status --porcelain` while holding irreplaceable ignored content, e.g. `.agentic/plan.md`. By OPERATOR DECISION (round 3) this guard is a PROTECTED DENYLIST, not a fail-safe allowlist: `docs/planning/**`, `.env*`, and `*.local` block removal; everything else ignored - including generated adapter output (`.kimi/`, `.codex/`, `.claude/skills/`) - is disposable and does not block (a round-2 fail-safe allowlist shipped first and measured `removed=0` against the live checkout). `.agentic/**` is a special case with INVERTED polarity (round-4 correction): protected by default inside `.agentic/` - EXCEPT a small named disposable set (routine telemetry like `events.jsonl`, `wrap/`, `codex-prompt-generation/`, `hud/`, cache dirs). Round 3's blanket `.agentic/**` protection also measured `removed=0`, because this repo dogfoods its own methodology and every worktree that has ever hosted an agent accumulates routine telemetry; `.agentic/**` was only ever meant to protect AUTHORED work (plans, notes, decisions), not session logs. Before any worktree is actually removed, its `.agentic/events.jsonl` (if present) is salvaged into the primary repo's `.agentic/reaped-telemetry/` first and the copy is verified - a failed salvage blocks removal rather than becoming a silent deletion. `--strict-ignored` restores the round-2 allowlist behavior UNCHANGED (including for `.agentic/`, where it still blocks `events.jsonl` exactly like round 2) for an operator who wants the more conservative (and less effective) polarity instead. See `bin/ds-reap-worktrees`'s own module docstring for the full rationale, disposable-set definitions, and salvage mechanics. This can only make the tool remove FEWER worktrees than the manual steps would, never more. Both `ds-base-sync`'s advisory note and the SessionStart worktree-count nudge invoke it in `--count-only` mode (a raw count, zero network, zero per-entry evaluation - not a removal forecast). Run `ds-reap-worktrees --explain` for a full per-worktree breakdown, or omit `--dry-run` to actually remove.

**The `SKIP_UNPROVEN` class and `--archive-unproven` (round 5).** A worktree can pass every other gate (clean, unlocked, past the age floor, not self, not protected-content) and STILL never resolve, because its branch carries real, unmerged commits that were never pushed anywhere and have no matching PR - `disposition_for` correctly refuses to call that `ELIGIBLE` (the round-4 measurement against this repo's own live checkout found this to be the dominant remaining blocker once the `.agentic/` correction landed: `skipped-protected-content` dropped to 0, but `removed` stayed 0 because most of the remaining worktrees carry exactly this class of branch - default-named `worktree-agent-<id>` branches and legacy `ds-round8`..`ds-round12` rework branches). Left alone, `SKIP_UNPROVEN` worktrees accumulate indefinitely - nothing ever resolves them. `--archive-unproven` (OPT-IN, NEVER the default) extends this repo's own precedent for the identical problem on BRANCHES - `bin/ds-branch-prune` archived 75 unprovable branches into one verified `git bundle` before deleting them (DS-153, `.agentic/branch-archive/`) - to WORKTREES, but only to an explicit whitelist within `SKIP_UNPROVEN`, never the whole bucket (round 6 correction): only `SKIP_NOT_PUSHED` and `SKIP_AMBIGUOUS_NO_PR` qualify - `SKIP_PR_OPEN` (a hard safety override) and `SKIP_LS_REMOTE_ERROR` (a transient failure) are NEVER archived, even with the flag set. Separately, a PER-ENTRY `gh pr list` query failure (auth fine, that one call errored/timed out/rate-limited) is reported as its OWN `SKIP_PR_QUERY_ERROR` outcome - never `SKIP_UNPROVEN` at all - so it is never eligible for `--archive-unproven` in the first place, not merely excluded from the whitelist: a query failure is a distinct fact from "no PR exists" and must never be treated as proof of anything (round-7/8 correction; see `bin/ds-reap-worktrees`'s own module docstring, Removal predicate gate 9). It also refuses to run at all in degraded gh mode (`--no-gh`, or `gh` unavailable/unauthenticated) - without PR evidence it cannot distinguish a genuinely-unprovable branch from one behind an open PR. For every whitelisted entry, it archives the full branch into a verified `git bundle` under `.agentic/worktree-archive/` (never removing anything if the bundle create or verify fails), salvages telemetry (same guard as the plain removal path - a failed salvage also blocks removal), then removes the worktree and prints the exact restore command. It removes the worktree only, never the branch - branch deletion remains `bin/ds-branch-prune`'s job. `.agentic/worktree-archive/` is gitignored (same `/.agentic/*` umbrella as `.agentic/reaped-telemetry/`, no new carve-out) and grows unbounded - pruning it is the operator's own responsibility, exactly like `.agentic/branch-archive/`. See `bin/ds-reap-worktrees`'s own module docstring ("Archiving unproven branches") for the full mechanism.

**Sweeping multiple repos: `bin/ds-reap-all`.** `ds-reap-worktrees` operates on exactly one repo per invocation (`--repo <path>`, default cwd). `ds-reap-all` is a thin wrapper for an operator with several project checkouts: it discovers a set of repos - explicit `--repo <path>` (repeatable), a root-directory scan (positional root args, depth-1 children by default, `--depth` up to 3), or a `~/.agentic/reap-all.json` fallback (`{"roots": [...], "repos": [...]}`) when no CLI args are given at all - then invokes `ds-reap-worktrees` once per repo sequentially, forwarding every pass-through flag (`--dry-run`, `--explain`, `--count-only`, `--no-gh`, `--min-age-hours`, `--strict-ignored`, `--archive-unproven`, `--base`) verbatim. It contains no removal logic of its own; every safety gate described above remains entirely owned by `ds-reap-worktrees` and is reused unmodified. One repo's failure (bad path, timeout, nonzero exit) never halts the sweep - it is reported and the remaining repos are still attempted.

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

For each ISOLATION-classified entry, apply `disposition_for()`'s gate order - locked, dirty, then merge-evidence-independent-of-push (`bin/tests/worktree_model.py`; where this prose and `disposition_for` disagree, `disposition_for` wins). (Note: if a worktree is still locked - its agent actively running, per Claude Code's own lock-while-running behavior - the `git worktree remove` below is refused by git automatically; this is expected, not an error to route around - `SKIP_LOCKED`.)

Resolve its path from the branch name and check its status before touching it:

```bash
source "${REPO_DIR:-.}/scripts/lib/worktree.sh" 2>/dev/null || true
WORKTREE_PATH=$(resolve_branch_worktree "$REPO_DIR" "$b" 2>/dev/null || true)
git -C "$WORKTREE_PATH" status --porcelain 2>/dev/null
```

where `$b` is the branch name from `git worktree list` for the current isolation worktree.

**Directory does not exist** (command errors with "not a git repository" or similar): The directory was already removed before this command ran. If the entry is still locked, a bare `git worktree prune` will NOT clear it - unlock first, then prune. Do **not** delete the branch here: an admin-only worktree entry with a missing directory is not merge evidence, and `git branch -D` at this point would run on zero proof of subsumption - strictly weaker evidence than either MERGED-PR route below. The orphaned branch is left for Step 5's `ds-branch-prune` subsumption predicate to evaluate under its own four-layer proof, ledgered on deletion:

```bash
git worktree unlock "$WORKTREE_PATH" 2>/dev/null || true
git worktree prune
```

**Directory exists, dirty (output present)** (`SKIP_DIRTY`): List the dirty files and skip removal. Report to the user - do not remove without explicit confirmation. Uncommitted work in an agent worktree may be important.

**Directory exists, clean (no output):** resolve merge evidence in `disposition_for`'s order - `merge_evidence` (ancestry) first, then `pr_state`, then `ls_remote_status` last, since push status alone is never sufficient proof of merge:

```bash
HEAD_SHA=$(git -C "$WORKTREE_PATH" rev-parse HEAD)
git merge-base --is-ancestor "$HEAD_SHA" origin/main 2>/dev/null && MERGE_EVIDENCE=merged || MERGE_EVIDENCE=unmerged
```

- `MERGE_EVIDENCE=merged` (`ELIGIBLE`): remove the worktree only - do **not** delete the branch here:

```bash
git worktree remove "$WORKTREE_PATH"
```

Branch deletion is deferred to Step 5's `ds-branch-prune` subsumption predicate: a bare `MERGE_EVIDENCE=merged` read is sufficient to reclaim the worktree (`git worktree remove` does not destroy commits) but is NOT sufficient evidence for `git branch -D` (DS-153 Amendment B1 - see the Notes section below).

- `MERGE_EVIDENCE=unmerged`: fall back to PR state, if `gh` is available - `gh pr view "$b" --json state -q .state`. `OPEN` skips (`SKIP_PR_OPEN`, report to the user); `MERGED` is `ELIGIBLE` (remove the worktree only, as above - covers a squash-merge ancestry missed; do not delete the branch here either). `CLOSED`/no PR/`gh` unavailable falls through to push status: `git ls-remote --exit-code --heads origin "$b"` - absent -> `SKIP_NOT_PUSHED`, command error -> `SKIP_LS_REMOTE_ERROR`, present -> `SKIP_AMBIGUOUS_NO_PR`. Every skip outcome here reports the branch to the user for manual review - never delete on an inconclusive read.

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

**If state is `MERGED`:** remove the worktree only - do **not** delete the branch here:

```bash
git worktree remove <worktree-path>
```

Branch deletion is deferred to Step 5's `ds-branch-prune` subsumption predicate (DS-153 Amendment B1) - see the Notes section below.

**If state is `OPEN` or `CLOSED` (not merged):** skip removal (`SKIP_PR_OPEN` / inconclusive). Report the branch name, PR number, and state to the user so they can decide.

**If no PR exists:** fall back to ancestry (`git merge-base --is-ancestor <head> origin/main`). Merged -> `ELIGIBLE`, remove the worktree only (as above; do not delete the branch here). Still unmerged -> `SKIP_AMBIGUOUS_NO_PR`. Report the branch as needing manual review.

**If `gh` is not available:** skip the PR check for all feature worktrees; fall back to the ancestry check alone. Report each feature worktree still unmerged as "needs manual review - gh CLI not available". Do not block or error.

---

## Step 5: Prune stale local branches

Run the canonical branch prune from `content/references/worktree-lifecycle.md §Branch prune (stale local branches)` - `bin/ds-branch-prune` (DS-153). It deletes a local branch only when a four-layer, first-match-wins subsumption predicate (ancestry, squash-patch equivalence, tip-subsumption, content-on-main) proves that branch's tip content is on `origin/main`; absence of proof is always `SKIP_UNPROVEN`, reported for manual review, never force-deleted. When `gh` is unavailable or errors, the predicate degrades to ancestry and content-on-main evidence only (L1/L4) - a strict subset, never a superset, of what a full run would delete - and the run names the degradation rather than staying silent.

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
- Never remove a feature worktree whose PR is still OPEN. For a live worktree's own removal (Steps 3/4, `disposition_for`), a MERGED PR alone remains sufficient evidence - `git worktree remove` does not destroy commits, so the worst case is already covered by `SKIP_DIRTY`/`SKIP_LOCKED` (DS-153 Amendment B1). This does NOT extend to local branch DELETION: `bin/ds-branch-prune` (Step 5, `disposition_for_orphan_branch`) treats a bare MERGED PR as terminally insufficient (`SKIP_PR_MERGED_UNPROVEN`) and requires the subsumption predicate to prove the tip's content is on `origin/main` before deleting.
- The main worktree (first entry in `git worktree list`) is always skipped.
- Works on the repository in the current working directory - not project-specific.
- If `gh` is not available, flag feature worktrees for manual review and continue.
