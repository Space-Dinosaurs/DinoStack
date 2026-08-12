<!--
Purpose: Full reference for worktree and branch lifecycle command blocks
         extracted from METHODOLOGY.md §Worktree Lifecycle. Contains the
         isolation worktree cleanup commands, feature worktree cleanup commands,
         the session-start prune script, the Standing authorizations section
         (the enumerated set of routine-hygiene operations pre-authorized for
         every session, satisfying a harness confirm-first carve-out), the
         local-branch prune block, the Round-N rework mechanic (the
         conductor-side SHA-push recovery procedure and failure-mode table for
         landing a same-approach fix commit on an already-open PR's branch;
         the literal `create_commands` branching forms live in
         content/commands/ds-implement-ticket.md's canonical definition site,
         not here - see the Round-N rework mechanic section itself), and the
         Ad-hoc (non-`/ds-implement-ticket`) worktree cleanup obligation
         (the process-discipline trigger for cleaning up an isolation
         worktree spawned outside the ticket flow, where Phase 8's own
         automatic cleanup never fires - closing the single largest
         confirmed source of orphaned worktrees observed in this repo).

Public API: Read-only reference document. Cross-referenced from:
            content/sections/11-worktree-lifecycle.md (inline pointers replacing
            each bash block),
            content/sections/12-protocol-details.md (Worktree lifecycle Protocol
            Details entry),
            content/sections/02-delegation.md §Standing authorizations,
            content/references/conductor-operating-rules.md:20,
            content/rules/conventions.md §Git Workflow (rework-vs-superseding
            bullet points here for the round-N mechanic).

Upstream deps: content/sections/11-worktree-lifecycle.md (parent section; read
               that section first for the two-class summary, isolation mandate,
               and session-start prune rule).

Downstream consumers: conductor preflight (session-start prune script and
                      branch prune block); conductor cleanup flows (isolation
                      and feature worktree removal commands);
                      /ds-cleanup-worktrees command (and its executable
                      predicate implementation, bin/ds-reap-worktrees);
                      /ds-implement-ticket lifecycle cleanup (Phase 8's
                      hardened locked-unlock-retry-then-ledger cleanup
                      block); every /ds-implement-ticket fix-pass spawn site
                      that re-seeds an engineer worktree against an
                      already-open PR's branch (Phase 6/6b Skeptic and QA fix
                      passes, Phase 7 quality-gate fix passes) via the Round-N
                      rework mechanic; every ad-hoc isolation-worktree spawn
                      outside `/ds-implement-ticket` (the Ad-hoc worktree
                      cleanup obligation section); bin/ds-base-sync's
                      dry-run advisory note and hooks/session-start-wrap.sh's
                      SessionStart worktree-count nudge (both backstops for
                      this obligation, never a substitute for it).

Failure modes: Prose + bash blocks; does not auto-execute. Using force-remove
               without the status check first risks losing uncommitted work.
               The --delete-branch flag on gh pr merge may not auto-delete in
               all gh CLI versions; the explicit git branch -D is the fallback.
               The branch prune step (bin/ds-branch-prune, DS-153) proves
               subsumption before deleting - absence of proof is always a
               skip, never a force-delete; see Safe boundary note in that
               section. A locked-but-dir-missing worktree admin entry survives
               a bare `git worktree prune` - the isolation-cleanup and
               session-start-prune paths both unlock before pruning to
               reclaim it. The Ad-hoc worktree cleanup obligation is process
               discipline, not a structural guarantee - a crashed session or
               a forgotten cleanup still relies on the session-start prune,
               bin/ds-branch-prune, and bin/ds-reap-worktrees backstops.

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

This `git branch -D` is likewise exempt from the general disposition model (as the isolation-worktree pattern above is): it runs only as a fallback AFTER `gh pr merge --delete-branch` has already succeeded on this exact branch, so the merge itself - not a bare "a PR merged" signal - is the proof of subsumption.

Same-PR rework rounds (see §Round-N rework mechanic below) mean one persistent branch per ticket instead of `-rN` siblings that each needed their own worktree, so `-rN` proliferation should drop. This is unaffected by the squash-merge-defeats-prune hazard: the branch-gone-from-origin / four-layer subsumption predicate (§Branch prune below) remains the correct predicate for cleanup either way, and prune logic itself is untouched by this change.

## Round-N rework mechanic

When a Skeptic finding, CI failure, or QA failure needs a fix pass against an already-open PR's branch (round N>=2 of the SAME approach - see `content/rules/conventions.md` §Git Workflow for the rework-vs-superseding boundary test), the fix commit lands on the existing branch's remote tip instead of a fresh branch off `$BASE_BRANCH`. Phase 10a's post-PR CI fix loop already does this ("commit and push to the same branch") - this section generalizes that same mechanic to the pre-PR Phase 6/6b/7 fix-pass spawn sites.

**Branching logic (`worktree_setup.create_commands` population rule).** The literal `create_commands` forms (initial spawn / `PLAN_PRESEEDED` / round-N rework), the already-checked-out guard, and the precheck-gated reuse remedy are NOT restated here - `content/commands/ds-implement-ticket.md`'s Phase 5 `worktree_setup` field definition (§Elevated-path engineer-contract extensions) is the sole canonical definition site for all of it. See that site for the full form and guard.

Verified empirically (git 2.39.5, scratch repo with a bare-clone origin, a lagging local `feat/test` ref, and a fresh `worktree add`): the `-B` form exits 0 and the resulting worktree's `HEAD` matches `origin/$BRANCH_NAME`'s tip exactly, even when the local `feat/test` ref pointed at an older commit before the run. The already-checked-out fatal (exit 128, `fatal: '<branch>' is already checked out at '<path>'`) reproduces when a second `worktree add` targets a branch already checked out elsewhere under the same `$REPO`, and `git worktree list --porcelain`'s `branch refs/heads/<name>` line reliably identifies the existing worktree path for the reuse guard.

**Recovery procedure (conductor-side, for when the branching logic above wasn't applied or the DS-123 worktree-fallback quirk fired).**

```bash
# 1. Confirm the engineer produced a commit.
ENGINEER_SHA=$(git -C "$ENGINEER_WORKTREE" rev-parse HEAD)

# 2. Confirm this SHA is NOT already an ancestor of the branch remote tip.
git -C "$REPO" fetch origin
if git -C "$REPO" merge-base --is-ancestor "$ENGINEER_SHA" "origin/$BRANCH_NAME"; then
  echo "SHA already on branch - nothing to push."
  exit 0
fi

# 3. Push the engineer's commit SHA directly onto the existing branch remote tip.
#    By explicit SHA, never local branch name (local ref can lag remote tip).
git -C "$REPO" push origin "$ENGINEER_SHA:refs/heads/$BRANCH_NAME"
```

Failure-mode table:

| Failure | Cause | Recovery |
|---|---|---|
| push rejected, non-fast-forward | origin/$BRANCH_NAME moved since worktree seeded | fetch; then (a) cherry-pick $ENGINEER_SHA onto fresh checkout of origin/$BRANCH_NAME and push NEW SHA by-SHA, or (b) re-spawn fix-pass engineer with current branch tip per the branching logic above. NEVER force-push (blanket-denied for conductor and subagents; chat authorization cannot clear it). |
| Engineer worktree silently started from main (branching logic not applied / DS-123) | mis-populated create_commands or harness fallback quirk | Do NOT push the SHA directly - main-based, could silently revert intervening branch commits. Fetch, checkout origin/$BRANCH_NAME in scratch location, cherry-pick $ENGINEER_SHA; if the cherry-pick conflicts, re-delegate to a correctly-seeded engineer rather than resolving it conductor-side (no conductor-exempt path exists for shippable-tree conflict resolution - conventions.md's shippable/exempt classifier and `enforce-shippable-edit.py` both deny it); push resulting SHA by-SHA. |
| DCO fails on pushed commit | commit without -s, or cherry-pick trailer mismatch | Amend BEFORE push: `git commit --amend -s --no-edit`, push new SHA. Never amend a commit already on the shared remote tip - re-derive and re-push. |
| Strict checks: base moved since last green run | orthogonal, governed by near-merge rebase policy | Unchanged: `gh pr update-branch --rebase` before merge. NOT eliminated by this mechanic. |

Deliberately unchanged by this mechanic: Skeptic review rigor (a fresh Skeptic invocation still reviews the same open PR's branch on round N - see `content/references/skeptic-protocol.md`), the CI check set, strict required-checks + near-merge rebase policy, the force-push prohibition, and DCO. Superseding (a wholesale approach replacement) still closes + rebases per `content/rules/conventions.md` §Git Workflow - this mechanic applies to rework only. DS-123 (the harness worktree-fallback quirk) remains open and unresolved by this mechanic; the recovery procedure above is mitigation, not a fix.

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
# Local branch prune (four-layer subsumption predicate - ancestry, squash-patch
# equivalence, tip-subsumption, content-on-main; see §Branch prune below) runs
# here via bin/ds-branch-prune (DS-153), covering worktree-agent-* branches
# and every other stale local branch in one pass. PATH-guarded, non-blocking
# on any exit - absence must not mean no pruning at all this session:
if command -v ds-branch-prune >/dev/null 2>&1; then
  ds-branch-prune
else
  echo "WARNING: ds-branch-prune not found on PATH - re-run your harness's DinoStack install script (<repo>/.claude/install.sh for Claude Code, the equivalent script under your adapter directory otherwise) to wire bin/ onto PATH. Local branch prune skipped this session." >&2
fi
```

## Ad-hoc (non-`/ds-implement-ticket`) worktree cleanup obligation

`/ds-implement-ticket` Phase 8's own cleanup block (§Isolation worktree cleanup commands above) only fires on that command's own success path - after a push succeeds on the ticket flow. Any `isolation:"worktree"` spawn made OUTSIDE that flow (an ad-hoc Worker per `AGENTS.md` §Workflow, a scratch investigation spawn, a one-off fix not run through `/ds-implement-ticket`) has no equivalent automatic trigger and is the single largest confirmed source of orphaned worktrees in practice - measured against this repo's own history, branches like `worktree-agent-<id>` (default-named, never renamed) and abandoned rework rounds (`ds-round8`..`ds-round12`, `work-round7`, `fix-gigi-round5` - legacy remnants that predate the round-N rework mechanic below and would not recur under it) accounted for the majority of accumulated non-root worktrees.

**Obligation:** whenever the conductor spawns an ad-hoc `isolation:"worktree"` Worker outside `/ds-implement-ticket`, it is responsible for cleaning up that worktree itself once the branch is pushed, the work is abandoned, or the session concludes - by running the same self-scoped pattern in §Isolation worktree cleanup commands above, immediately, rather than assuming any later automatic pass will catch it. This is a standing authorization (§Standing authorizations above already covers the removal itself); the obligation here is the TRIGGER - do it at the natural completion point of the ad-hoc spawn, not "eventually."

**Round-N rework coverage.** The Round-N rework mechanic above already establishes that rework rounds reuse the SAME branch and worktree rather than creating a fresh `-rN` sibling each round - this is what makes `-rN` proliferation a legacy failure mode rather than a live one. When a round is genuinely SUPERSEDED (a wholesale approach replacement per `content/rules/conventions.md` §Git Workflow's rework-vs-superseding test, not a same-approach fix), the superseded round's worktree is now abandoned and must be cleaned up at that moment - the close+rebase step that supersedes it is exactly the natural completion point this obligation attaches to, not a "later" pass.

**Backstop, not a substitute:** the session-start prune script, `bin/ds-branch-prune`, and `bin/ds-reap-worktrees` (invoked directly, via `/ds-cleanup-worktrees`, or surfaced by the `ds-base-sync` advisory note and the SessionStart worktree-count nudge - see their own docs) all remain in place specifically because this obligation is process discipline, not a structural guarantee - a crashed session, an interrupted spawn, or a conductor that simply forgets still needs a backstop that eventually reclaims the worktree without relying on the obligation having been honored.

## Guardrail: never force-override the harness lock

No cleanup or prune path in this document may call `git worktree remove -f -f` (double force, which overrides a lock). `git worktree unlock` may be used ONLY on a worktree whose directory is already gone - at that point its agent cannot still be running, so there is nothing left to protect (this is exactly what the isolation-cleanup and session-start-prune steps do to reclaim a stale locked admin entry). Never unlock, or double-force-remove, a worktree whose directory still exists: the harness's lock (set on every isolation worktree while its agent runs) is load-bearing cross-session protection - it is the reason a concurrent session's cleanup cannot delete another session's live worktree, and overriding it reintroduces exactly the mid-task-deletion risk. No path in this document currently does this; the note is a guardrail against future regression.

## Standing authorizations

These are authorized once, for every session, and are never an operator choice:

- Deleting a local branch that `bin/ds-branch-prune`'s four-layer subsumption
  predicate (§Branch prune below) proves DELETE-eligible - ancestry, squash-
  patch equivalence, tip-subsumption, or content-on-main, first match wins.
  Absence of proof is always a skip; a bare "a PR merged" signal is never
  sufficient on its own (see the predicate's terminal `SKIP_PR_MERGED_UNPROVEN`
  outcome in §Branch prune below).
- Deleting the corresponding remote branch as part of `gh pr merge --delete-branch`.
- Removing an isolation or feature worktree per §Isolation worktree cleanup
  commands / §Feature worktree cleanup commands above.
- Running the session-start worktree prune, branch prune, and `git fetch --prune`.

The boundary is unchanged and is not restated here - see §Guardrail: never
force-override the harness lock above and the Safe boundary paragraph in
§Branch prune below.

These authorizations are methodology-owned and not project-overridable,
consistent with §Project-override policy below, and are the durable-authorization
form which **satisfies** a harness confirm-first carve-out rather than overriding
it - a harness default of "confirm first unless durably authorized" is met on its
own terms by this section, not superseded by it.

Parent clause: `content/sections/02-delegation.md` §Standing authorizations.

## Branch prune (stale local branches)

Run at session start alongside the session-start prune script, via
`bin/ds-branch-prune` (DS-153) - never inline shell. The script proves, for
each local branch, that its tip's content is subsumed by `origin/main` via a
four-layer, first-match-wins predicate (ancestry, squash-patch equivalence,
tip-subsumption, content-on-main); absence of proof is always a skip, never
a force-delete. See the script's own module docstring (`bin/ds-branch-prune`)
and `.agentic/ds-153-plan.md` (DS-153) for the full normative predicate.

Every branch's outcome additionally routes through
`disposition_for_orphan_branch()` (`bin/tests/worktree_model.py`) so this
script and every other branch-deletion caller share one normative
ELIGIBLE/`SKIP_PR_MERGED_UNPROVEN` definition rather than two representations
that can silently disagree - see that module's docstring. A bare
`pr_state == "MERGED"` alone is never sufficient: reaching the PR-state check
means ancestry and content-subsumption were both already inconclusive, so
`disposition_for_orphan_branch` resolves it to the terminal
`SKIP_PR_MERGED_UNPROVEN`, not `ELIGIBLE`.

```bash
if command -v ds-branch-prune >/dev/null 2>&1; then
  ds-branch-prune
else
  echo "WARNING: ds-branch-prune not found on PATH - re-run your harness's DinoStack install script (<repo>/.claude/install.sh for Claude Code, the equivalent script under your adapter directory otherwise) to wire bin/ onto PATH. Local branch prune skipped this session." >&2
fi
```

Pass `--explain` for a per-branch reason list, `--dry-run` to compute and
report without deleting anything, or `--no-gh` to force the degraded mode
(only ancestry and content-on-main evidence, when `gh` is unavailable or
errors - degradation can only delete FEWER branches than a full run, never
more, and the run always names the condition rather than staying silent).

**Safe boundary:** a branch the predicate cannot prove subsumed resolves to
`SKIP_UNPROVEN` - reported, never force-deleted. This includes a branch
whose only evidence is "a PR merged": that proves the PR merged, not that
THIS local tip's content is on `origin/main` - precisely the predicate this
script was built to eliminate (see the plan's Core decision).

**Residual: G0's base-branch guard is name-based, and the session-start
call site above passes no `--base`.** A project declaring a non-develop
`BASE_BRANCH` in `AGENTS.md` (e.g. `integration`, `staging`, `release`) has
that branch deleted via L1 like any other stale branch once it is fully
merged into `origin/main` - after which base-branch resolution can no
longer find it locally. Not data loss (the ref survives on origin, and the
deletion ledger records the tip SHA), but disclosed here because the
develop/development guard is unconditional while a custom `BASE_BRANCH` is
not. Passing the resolved `BASE_BRANCH` explicitly via `--base` at the call
site would close this; deliberately not done here, since `BASE_BRANCH` is
resolved lazily and this script runs unconditionally at session start (see
the `content/rules/conventions.md` Base branch resolution note above).

**Recovery (Amendment B3):** `git branch -D` deletes the branch's own reflog
(`.git/logs/refs/heads/<branch>`) outright, so the default 90-day
`gc.reflogExpire` does NOT govern recovery here - that setting applies to
REACHABLE reflog entries, and a deleted branch's own reflog does not survive
the deletion. What actually governs a deleted branch's now-dangling commit is
`gc.reflogExpireUnreachable` (default 30 days) and `gc.pruneExpire` (default
2 weeks) - and for a branch created inside an isolation worktree since
pruned, the per-worktree `HEAD` reflog may be gone too, leaving no reflog
entry anywhere. The real recovery path is the deletion ledger every
successful `ds-branch-prune` run writes: `<branch> <tip-sha>`, appended to
both stdout and `.agentic/branch-prune-ledger.txt`, so recovery is always
`git branch <name> <sha>` regardless of reflog state.

**Why this supersedes the old `[gone]` signal:** after a history rewrite
(such as the 2026-06-14 pre-OSS filter-repo purge), squash-merged
pre-rewrite branches are not ancestors of the rewritten `main`, so ancestry
alone misses them - the same gap the old `[gone]`-upstream-marker fallback
existed to paper over. `[gone]` is an inferred signal (the remote ref is
gone, not proof of content) and cannot distinguish a branch that predates a
rewrite from one simply deleted without merging. The squash-patch-equivalence
and tip-subsumption layers close this gap with actual proof instead of
inference: they compare the branch's own diff, or its tip's ancestry, against
a known-merged PR's squash commit - independent of both local-`main`
ancestry and upstream-tracking state.

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
