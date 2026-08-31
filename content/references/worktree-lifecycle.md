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
         not here - see the Round-N rework mechanic section itself), the
         Ad-hoc (non-`/ds-implement-ticket`) worktree cleanup obligation
         (the process-discipline trigger for cleaning up an isolation
         worktree spawned outside the ticket flow, where Phase 8's own
         automatic cleanup never fires - closing the single largest
         confirmed source of orphaned worktrees observed in this repo),
         and The unproven class, and archiving it (the opt-in
         `--archive-unproven` mechanism that extends the identical
         verified-git-bundle-then-delete precedent a 2026-08-11 manual
         one-off operator sweep already established for branches
         (DS-153; bin/ds-branch-prune itself does not call `git bundle`)
         from branches to worktrees, for the `SKIP_UNPROVEN` class that
         every other gate cannot resolve), the Implicit Trivial batching
         section (the canonical single-source mechanism for opening one
         draft PR at the first push of a Trivial-tier tweak and
         continuing it by detaching the engineer's OWN harness isolation
         worktree onto the batch's fetched remote tip - no second/nested
         worktree - so the write/read isolation hooks admit every edit
         trivially, across subsequent related tweaks, referenced by a
         pointer from content/sections/04-risk-classification.md §Trivial
         signals), and the SKIP_UNREFERENCED_COMMIT section (the
         disposition EVERY such detached harness worktree resolves to
         today if it crashes before its push - `head_reachable` is dead
         code in bin/ds-cleanup-worktrees, so no leftover, pushed or not,
         currently auto-sweeps; see that section for the manual
         triage/recovery procedure), and the Dev-server process lifetime
         ownership section (the canonical rule that any dev server booted
         by an agent is run-scoped only and will not survive the agent's
         run on this harness - referenced by the qa-gate boot pattern and
         the engineer/qa-engineer runtime smoke-test caveats).

Public API: Read-only reference document. Cross-referenced from:
            content/sections/11-worktree-lifecycle.md (inline pointers replacing
            each bash block),
            content/sections/12-protocol-details.md (Worktree lifecycle Protocol
            Details entry),
            content/sections/02-delegation.md §Standing authorizations,
            content/references/conductor-operating-rules.md:20,
            content/rules/conventions.md §Git Workflow (rework-vs-superseding
            bullet points here for the round-N mechanic; also the
            Implicit Trivial batching exception in the live-testing
            paragraph, "Commit each fix immediately during testing"),
            content/sections/04-risk-classification.md §Trivial signals
            (pointer to the Implicit Trivial batching section),
            content/references/qa-gate.md (dev-server boot pattern pointer
            to §Dev-server process lifetime ownership),
            content/agents/qa-engineer.md (dev-server start caveat pointer
            to §Dev-server process lifetime ownership),
            content/agents/engineer.md (runtime smoke-test caveat pointer
            to §Dev-server process lifetime ownership).

Upstream deps: content/sections/11-worktree-lifecycle.md (parent section; read
               that section first for the two-class summary, isolation mandate,
               and session-start prune rule).

Downstream consumers: conductor preflight (session-start prune script and
                      branch prune block); conductor cleanup flows (isolation
                      and feature worktree removal commands);
                      /ds-cleanup-worktrees command (and its executable
                      predicate implementation, bin/ds-cleanup-worktrees);
                      /ds-implement-ticket lifecycle cleanup (Phase 8's
                      single-attempt, refusal-only cleanup block - no
                      unlock, no force); every /ds-implement-ticket fix-pass
                      spawn site that re-seeds an engineer worktree against an
                      already-open PR's branch (Phase 6/6b Skeptic and QA fix
                      passes, Phase 7 quality-gate fix passes) via the Round-N
                      rework mechanic; every ad-hoc isolation-worktree spawn
                      outside `/ds-implement-ticket` (the Ad-hoc worktree
                      cleanup obligation section); bin/ds-base-sync's
                      --count-only advisory note and hooks/session-start-wrap.sh's
                      SessionStart worktree-count nudge (both backstops for
                      this obligation, never a substitute for it);
                      content/references/qa-gate.md (dev-server boot pattern);
                      content/agents/qa-engineer.md (dev-server start caveat);
                      content/agents/engineer.md (runtime smoke-test caveat) -
                      all three cross-referencing the Dev-server process
                      lifetime ownership section.

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
               bin/ds-branch-prune, and bin/ds-cleanup-worktrees backstops.
               A crashed Implicit Trivial batching continuation leaves its
               own harness isolation worktree detached (possibly with an
               unpushed commit) - a DIFFERENT case from the above: none of
               the session-start prune, bin/ds-branch-prune, or the
               automatic reap resolve it - `head_reachable` (the fact the
               reap's ELIGIBLE path for a detached HEAD depends on) is
               dead code in bin/ds-cleanup-worktrees, hardcoded to
               "not_checked" at every construction site, so every such
               leftover resolves SKIP_UNREFERENCED_COMMIT regardless of
               push status and is left in place; only the manual procedure
               in §SKIP_UNREFERENCED_COMMIT resolves it.

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

This is the self-scoped inline pattern; it does not need the general disposition model in `bin/tests/worktree_model.py` (`disposition_for` / `disposition_for_orphan_branch`) because it only ever operates on the branch the current session just pushed in the same phase. `content/commands/ds-implement-ticket.md` Phase 8 carries the hardened, canonical form of this block: single attempt, no force, surfacing stderr and appending a persisted skip record (`.agentic/worktree-cleanup-skips.jsonl`) to a refusal rather than discarding it - the illustrative snippet above omits that hardening for brevity.

If the worktree is still locked by a running agent, `git worktree remove` will
refuse until the agent finishes. That is expected and safe - it is the
correct, permanent outcome for a refusal, NEVER a signal to unlock or
force-remove (`git worktree unlock` may be used ONLY on a worktree whose
directory is already gone - see §Guardrail below, unchanged by any cleanup
block in this document). The refusal is recorded (Phase 8's ledger above) so
it stays visible in a later session; the session-start prune script and
`bin/ds-cleanup-worktrees` below remain the backstop that eventually reclaims it
once the lock is genuinely released.

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
| Engineer worktree silently started from main (branching logic not applied / DS-123) | mis-populated create_commands or harness fallback quirk | Do NOT push the SHA directly - main-based, could silently revert intervening branch commits. Never resolve this by checking out `origin/$BRANCH_NAME` in the primary checkout ($REPO) - fetch, then `git -C $REPO worktree add <scratch-path> origin/$BRANCH_NAME` to create a dedicated scratch worktree, cherry-pick $ENGINEER_SHA there; if the cherry-pick conflicts, re-delegate to a correctly-seeded engineer rather than resolving it conductor-side (no conductor-exempt path exists for shippable-tree conflict resolution - conventions.md's shippable/exempt classifier and `enforce-shippable-edit.py` both deny it); push resulting SHA by-SHA; remove the scratch worktree afterward. |
| DCO fails on pushed commit | commit without -s, or cherry-pick trailer mismatch | Amend BEFORE push: `git commit --amend -s --no-edit`, push new SHA. Never amend a commit already on the shared remote tip - re-derive and re-push. |
| Strict checks: base moved since last green run | orthogonal, governed by near-merge rebase policy | Unchanged: `gh pr update-branch --rebase` before merge. NOT eliminated by this mechanic. |

Deliberately unchanged by this mechanic: Skeptic review rigor (a fresh Skeptic invocation still reviews the same open PR's branch on round N - see `content/references/skeptic-protocol.md`), the CI check set, strict required-checks + near-merge rebase policy, the force-push prohibition, and DCO. Superseding (a wholesale approach replacement) still closes + rebases per `content/rules/conventions.md` §Git Workflow - this mechanic applies to rework only. DS-123 (the harness worktree-fallback quirk) remains open and unresolved by this mechanic; the recovery procedure above is mitigation, not a fix.

## Implicit Trivial batching: open the PR at first push

A Trivial-classified change (`content/sections/04-risk-classification.md` §Trivial
signals) commits and pushes immediately, from a fresh, disposable,
worktree-isolated Trivial-path engineer spawn (per the delegation
kernel's existing spawn contract - the Trivial tier's real contract is
plain prose per `content/commands/ds-implement-ticket.md:1545`; the tier
carries no `worktree_setup` field; the Elevated-only contract at
`:1543`/`:1615`/`:1621` is not used here). The **first** tweak to a surface
opens a **draft** PR immediately. Every continuation is seeded via a
detached-HEAD checkout of the batch's fetched remote tip. CI runs on every
push; nothing is deferred or skipped.

### Pre-spawn continuation judgment

Before spawning, the conductor decides continuation vs. new work from
conversational context - the same judgment class as the precedence rules
below. Ambiguity fails closed to not-a-continuation (mint a fresh
branch/PR rather than risk colliding with an unrelated batch).

### Seeding mechanics

**Continuation** (an existing batch): the Trivial engineer is briefed in
plain prose (per `:1545`'s form) to run, directly inside its own
harness-provided isolation worktree - no nested worktree, no separate
directory.

**Cleanliness precheck, mandatory, immediately before the detach:**
`:1545`'s own porcelain precheck was written for a `checkout -B`
force-moving a shared branch ref and is inapplicable to that case - but
this in-place `git checkout --detach` re-invalidates that reasoning for a
different reason: any untracked file already present in the worktree (a
stray build artifact, this repo's own known absolutized-symlink artifact
class) rides along onto the detached HEAD unnoticed and can land in the
tweak commit. Require `git status --porcelain` to print EMPTY output
immediately before running the detach:

```bash
[ -z "$(git status --porcelain)" ] || { echo "BLOCKED: worktree not clean before detach"; exit 1; }
git fetch origin && git checkout --detach origin/chore/tweak-<key>
```

Nonempty output is a hard stop - report `BLOCKED`, do not proceed with
the detach. A freshly-spawned isolation worktree is clean by
construction, so this check costs nothing on the normal path; it exists
only to catch the abnormal one.

[verified-by-execution, own worktree, git 2.55.0]: `git checkout --detach
origin/main` succeeds; `git symbolic-ref -q HEAD` afterward exits nonzero
(genuinely detached); the engineer's own harness branch ref
(`worktree-agent-<id>`) survives the detach untouched, confirmed via
`git show-ref` before and after. Every edit the engineer makes afterward
lands inside its own `caller_root` by construction, since there is no
second directory - the write/read isolation hooks
(`hooks/enforce-worktree-write.py`, `hooks/enforce-worktree-read.py`)
admit it trivially, with no placement decision, no exemption, and no
kill-switch to reason about.

The engineer edits, commits detached (`git commit -s`), then **pushes by
explicit refspec**:

```bash
git push origin "HEAD:refs/heads/chore/tweak-<key>"
```

[verified-by-execution, own worktree, git 2.55.0]: committed on the
detached HEAD, pushed by this exact refspec form to a scratch branch,
confirmed landed via `git ls-remote`, then deleted the scratch ref -
clean round trip. **Binding constraint - braced variables always, and
the explicit refspec is mandatory:** a detached worktree's bare
branch-name push does NOT behave as a uniform silent no-op; it does one
of two things, neither of them the intended push. With NO local branch
named `chore/tweak-<key>` present (the normal case - a detached checkout
never creates one), the bare form FAILS LOUDLY:
`git push -u origin chore/tweak-<key>` exits nonzero with
`error: src refspec chore/tweak-<key> does not match any` - safe, but
wastes the turn. With a STALE local branch of that name already present
(unusual but possible on a reused worktree), the bare form instead pushes
THAT local ref - silently landing the WRONG commit on `origin`, the
genuinely dangerous case. The explicit `HEAD:refs/heads/chore/tweak-<key>`
refspec form is mandatory in **both** cases - it names the exact commit
being pushed regardless of what local branches happen to exist. Do not
simplify this to a bare branch-name form, and **do not substitute
`AGENTS.md:53`'s literal** (`git push -u origin <branch-name>`) here -
that sequence's worker-pushes-then-conductor-acts SEQUENCE carries over
(matching the `:2575`/`:2585-2595` in-worktree push precedent, which uses
this same explicit-refspec form for the same underlying reason), its push
FORM does not.

**Re-attach immediately after the push succeeds, mandatory:**

```bash
git checkout worktree-agent-<id>
```

**Why this exists - never simplify it away:** §Isolation worktree cleanup
commands above resolves the worktree to remove via
`resolve_branch_worktree "$REPO_DIR" "$BRANCH_NAME"`
(`scripts/lib/worktree.sh`), whose own module docstring states verbatim
"Intentionally does not match detached-HEAD worktrees or remote-tracking
refs" (`:24`). Left detached, that resolver returns an empty path for
THIS worktree on every subsequent lookup, and the cleanup block's
`[ -n "$WORKTREE_PATH" ]` guards both the status check and the removal -
so cleanup silently no-ops forever, not just once. Re-attaching to the
engineer's own harness branch (`worktree-agent-<id>` - confirmed above to
survive the detach) restores the resolver's visibility and makes the
worktree an ordinary, cleanable branch-based entry again before the
engineer returns.

The engineer returns the already-landed SHA as confirmation once the
re-attach completes - there is no separate removal step, since there was
never a second worktree to remove; the harness's own isolation-worktree
cleanup (§Isolation worktree cleanup commands above, "once the branch has
been pushed") handles the engineer's worktree exactly as it would for any
other Trivial spawn, now that it is branch-resolvable again. **The
conductor pushes nothing on this path** - its role is to open the draft
PR (minting) or note the landed push (continuation); push-by-SHA from the
primary checkout is reserved for the §Round-N rework mechanic's recovery
procedure above, never used routinely here.

**New work (minting):** an ordinary base-seeded Trivial spawn - the
engineer pushes `HEAD:refs/heads/chore/tweak-<key>` from its own harness
worktree; the conductor then opens the draft PR against the already-pushed
branch, a direct instance of the standard worker-pushes-then-conductor-acts
sequence. On return, the file-overlap scope test
(`git diff --name-only HEAD~1 HEAD` in the engineer's worktree) runs as
**verification only, never the batching decision** - the pre-spawn
continuation judgment above is what decides whether to batch. Unexpected
overlap with another open batch's files recovers via the §Round-N rework
mechanic's scratch-worktree cherry-pick recovery row above (the
main-based-engineer-worktree row of that table); a conflict during that
recovery is re-delegated to a fresh engineer, never resolved
conductor-side.

### Crash paths (stated honestly - one worktree, not two)

Because there is no nested worktree, a crashed continuation spawn leaves
behind exactly ONE artifact: its own ordinary harness isolation worktree,
detached, possibly holding an unpushed commit - not two admin entries,
and no orphaned-nested-entry case to reason about separately. It is
reaped (or not) by the same harness/session-start machinery that governs
any other crashed spawn.

[verified-by-read]: `classify_entry` (`bin/tests/worktree_model.py:443-447`)
is path-prefix-only and never reads `entry.branch` - a detached harness
worktree at `.claude/worktrees/agent-<id>` classifies ISOLATION exactly
like a branched one. `disposition_for`'s detached-HEAD branch
(`bin/tests/worktree_model.py:756-762`) is `ELIGIBLE` only when
`facts.head_reachable == "reachable"`, else `SKIP_UNREFERENCED_COMMIT`.
`bin/ds-cleanup-worktrees:2692` hardcodes `head_reachable="not_checked"`
at every construction site, and `_compute_origin_reachable`'s own
docstring (`bin/ds-cleanup-worktrees:1801-1821`) calls the field
"unrelated, dead code" at `:1816` - distinct from the separate, live
`origin_reachable` field DS-196 added, which does not feed this branch at
all (`worktree_model.py:478-487`).
Since `"not_checked" != "reachable"`, the `ELIGIBLE` arm can never fire
today: **every detached harness worktree, whether its push already
landed or not, resolves `SKIP_UNREFERENCED_COMMIT`** and is left for
manual handling - refused by design, the same work-preserving discipline
as `SKIP_UNPROVEN` below, but a distinct disposition.

**Operator triage, since the tool does not distinguish the two cases for
you:** check whether the commit already reached `origin` -
`git -C <path> branch -r --contains "$(git -C <path> rev-parse HEAD)"`.
Nonempty output means nothing is at risk - the work is already on
`origin`, and the plain-`git worktree remove` procedure in
§SKIP_UNREFERENCED_COMMIT below (with its dirty-refusal handling) is
sufficient to reclaim the leftover. Empty output means the commit exists
nowhere but this worktree - follow that section's full
inspect-recover-or-discard procedure. See §SKIP_UNREFERENCED_COMMIT below
for both.

**A possible future enhancement, deliberately not done here:** wiring
`head_reachable` up to a real check (mirroring `_compute_origin_reachable`'s
existing pattern) would let a crash-after-push leftover auto-sweep
instead of needing the manual triage above. Out of scope for this
change - the honest-docs fix (stating the true, current behavior) is
minimal-diff; wiring up dead code to change tool behavior is a separate,
larger change with its own review. This paragraph is a per-change scope
note from the docs revision that added it, not a standing cross-unit repo
decision - deferring `head_reachable`-wiring to its own separately-scoped
unit remains the right sequencing call, but no repo-level decision
mandates that split.

**A registered-but-out-of-tree worktree (`OUT_OF_TREE`).** A worktree THIS
repo's own git registered, but which lives physically outside
`repo_root`'s directory tree, is not `UNMANAGED` - `classify_entry`
bifurcates on `host == repo_root` (`bin/tests/worktree_model.py:414-424`):
when equal (the sole real call site's shape), it classifies `OUT_OF_TREE`
and is evidence-gated exactly like ISOLATION/CONDUCTOR_CREATED, subject to
THREE removal paths, not one: (1) ancestor-of-base merge evidence; (2)
`origin_reachable` (DS-196) for a branched entry - independent of
`head_reachable` staying dead, rolled back to the pre-DS-196 evidence
order by `--no-origin-reachable-evidence` for an operator who wants the
more conservative behavior; and (3) `--archive-unproven`, which archives
and removes ANY entry (of any class, including `OUT_OF_TREE`) whose
disposition resolves `SKIP_NOT_PUSHED` or `SKIP_AMBIGUOUS_NO_PR` -
needing no merge evidence at all, since both dispositions mean "the
branch content itself is the only unresolved question" (see
`_ARCHIVABLE_UNPROVEN_DISPOSITIONS`'s own docstring). None of these three
paths are new code; `OUT_OF_TREE` is simply newly subject to all of them,
same as ISOLATION/CONDUCTOR_CREATED always have been. When `host !=
repo_root` (a hypothetical caller relativizing against a different root
than the containment boundary - the genuine cross-repo case), the entry
stays `UNMANAGED`, unchanged - the cross-repo non-collision guarantee this
module documents.

**A linked worktree used as the sweep target is not supported.** `--repo
<path>` (and `--multi-repo` scan discovery, since `_is_git_dir` accepts a
`.git` FILE - exactly a linked worktree's marker) resolves `host` and
`repo_root` via `git rev-parse --show-toplevel`, which returns a LINKED
worktree's OWN directory when run from inside one, not its parent repo's
root. Without a guard, that would make `host == repo_root == <the linked
worktree's own path>`, and every SIBLING worktree of the parent repo would
resolve `OUT_OF_TREE` and become evidence-gated for removal - a
blast-radius expansion onto a repo the operator never named, and one that
also defeats `RepoTarget` dedup for that repo. `_host_is_linked_worktree`
(`bin/ds-cleanup-worktrees`) distinguishes a main worktree from a linked
one via `git rev-parse --git-dir` versus `--git-common-dir` (identical
for the main worktree, different for a linked one) and, when the target
IS a linked worktree, withholds `OUT_OF_TREE` for that run - the
not-under-host branch stays `UNMANAGED` exactly as it did before
`OUT_OF_TREE` existed. Point `--repo` at a repo's main worktree, never at
one of its own linked worktrees.

**Orphaned unregistered directories - decision.** No sweep/report
mechanism was built to find EXISTING orphaned, unregistered worktree
directories on disk (no git object/ref/admin entry survives to verify
"nothing unrecoverable" against). The only mechanism added is
source-hardening: `_salvage_and_remove` now attempts an active repair
(an `rmtree` retry) when `git worktree remove` reports success but leaves
the directory present on disk, guarded by a defensive floor that refuses
to `rmtree` a path resolving to or containing `repo_root`. A residual
TOCTOU risk between git's `rc==0` and the `rmtree` call is accepted as
disclosed debt, not closed - see this module's own `_salvage_and_remove`
docstring for the full disclosure. Disposition of any pre-existing
orphan of unknown provenance is left to the operator.

### Discovery: draft-only, with a bounded backstop

Primary: `gh pr list --state open --json headRefName,number,files,isDraft`
filtered to `chore/tweak-*` AND `isDraft: true` - a non-draft open tweak
PR is mid-ship, never a continuation target.

Backstop (covers a create-failure where the push landed but no PR exists
yet): a branch qualifies only when ALL of: (a) `gh pr list --state all`
shows no PR of any state for it (a branch whose PR was explicitly closed
is never a backstop candidate); (b) the tip's author matches the
session's resolved identity; (c) the tip is within the shared recency
window. Read empty stdout, never exit status.

### Concurrency: two routes, two matched fixes

- **Route (i), two sessions minting for the same file:** the
  session-scoped `<key>` token (`<file-basename-slug>-<session-token>`,
  minted only at new-branch time) means the two branches can never
  converge - cost is two draft PRs, a cheap visible failure.
- **Route (ii), two sessions continuing the SAME batch:** an
  origin-visible claim comment. Before continuing, read the PR's comments
  (`gh pr view <n> --json comments`); take the **latest** comment matching
  the `tweak-claim:` pattern, using that comment's own `createdAt` (never
  `updatedAt`, which moves on unrelated PR activity) as the freshness
  signal against the shared recency window. A live foreign claim
  (different token, within the window) -> fail closed to minting a new
  branch. Free or stale -> post
  `gh pr comment <n> --body "tweak-claim:<session-token>"` and continue.
  **Release at ship:** post a `tweak-release:` comment - a **distinct
  pattern from `tweak-claim:`**, never `tweak-claim:released` - so an
  interrupted ship's release comment can never parse as a fresh foreign
  claim (or simply rely on the merge itself removing the PR from the
  open/draft discovery set).

### Draft-PR rationale and the un-draft corollary

The PR opens `--draft`. [verified-by-execution, live probe PR #815, this
repo, 2026-08-25]: both `gh pr merge --squash` and
`gh pr merge --squash --admin` on a draft PR exit 1 with
`GraphQL: Pull Request is still a draft (mergePullRequest)`; draft
enforcement is at the GraphQL mutation layer, upstream of `--admin`'s
bypass scope - so the standing auto-merge-on-CI-green instruction cannot
merge a tweak batch prematurely, and a non-draft open tweak PR would
falsely signal "ready for review" to a human reviewer. **Binding
corollary:** `gh pr ready <number>` MUST precede any merge attempt -
`--admin` never implicitly un-drafts a PR; a merge failing with
`GraphQL: Pull Request is still a draft` means "forgot to un-draft," not a
mystery to investigate.

### Ship-with-teardown

`gh pr ready <number>`, then `gh pr merge --squash --delete-branch`
(`--admin` where required). Post the `tweak-release:` comment (or rely on
the PR leaving the discovery set). **Teardown:** `--delete-branch` deletes
the branch the visibility worktree (if any - see below) has checked out,
so ship re-points or removes it:
`git -C <visibility-worktree> fetch origin && git -C <visibility-worktree> checkout $BASE_BRANCH && git -C <visibility-worktree> pull --ff-only`,
or remove it per §Feature worktree cleanup commands above.

### Operator visibility (recommendation, not machinery)

Optionally, `git worktree add` the `chore/tweak-<key>` branch under
`.agentic/worktrees/` (a feature worktree - path-prefix-classified
CONDUCTOR_CREATED, per `classify_entry` - cleaned up after its PR merges
per §Feature worktree cleanup commands above), which a dev server can
point at,
fast-forwarded after each push - or simpler, pull the branch into the
main checkout between tweaks. **Created only after the PR is confirmed
`OPEN`** (`gh pr view <branch> --json state -q '.state'` returning the
literal `OPEN`) - the pushed-no-PR window is reap-`ELIGIBLE`, so creating
it earlier risks the reap removing it out from under the operator.
`AE_WORKTREE_REAP_DISABLE=1` is available to suppress the reap while a
visibility worktree is in active use. Dev-server hot-reload against an
externally fast-forwarded checkout is a flagged environment assumption.
The visibility worktree (a branch checkout) never collides with
continuation engineers, which are always detached.

### Pillar 4 degradation path

All mechanics are `gh` invocations against a GitHub-backed remote.
**`gh` unavailable, unauthenticated, or a non-GitHub forge -> batching is
inert**: every Trivial change follows today's unbatched pipeline (commit,
push, PR, merge, pull, per change). **Narrower case: `gh` present but
under-scoped for PR comments** (a restricted token) - discovery and the
draft-PR mechanism still function (read + create/edit), but route (ii)'s
claiming falls back to fail-closed-to-new-branch when a comment-post
fails on permissions - degrading toward the already-accepted "extra
branch" cost, never toward blocking or a silent unclaimed continuation.

### Precedence rules

1. Explicit ship-language anywhere -> ships this turn.
2. Explicit urgent/escape-hatch language -> that request skips batching
   entirely.
3. Any Trivial-shaped request never triggers a ship.
4. A non-Trivial request alongside or after an open batch -> **marks the
   batch ready and merges asynchronously** while the non-Trivial spawn
   starts immediately (within seconds, not after the async merge
   completes). Disclosed costs: (i) an ordering gap - the non-Trivial
   branch will not contain the tweaks unless it rebases or they merge
   first; (ii) a base-move hazard - the tweak PR merging mid-flight moves
   the non-Trivial PR's base, requiring `gh pr update-branch --rebase`
   and a full required-checks re-run under strict checks (force-push is
   denied; the default merge-update form fails DCO). This is a disclosed
   cost, not a gate: a pre-spawn file-disjointness gate would need the
   non-Trivial unit's file set before it is spawned - the same
   pre-spawn-guess shape this design rejects elsewhere.
5. A pure question is never a trigger. A compound request ("why...? make
   it 1px") is evaluated on its change-request half only.

### Ship triggers

(a) explicit ship-language; (b) a new non-Trivial request (rule 4, async);
(c) an explicit end-of-session signal; (d) abrupt session end - **NOT**
shipped; the draft PR persists and is surfaced by rediscovery next
session (see §Session-start prune script below).

### Announcement wording (binding)

- Tweak-1 PR-open success: `Opened a draft PR for <what/file> (not ready
  to merge) - say "ship it" to mark it ready, or I'll do it when we move
  to unrelated work or you wrap the session.`
- Tweak-1 PR-open failure: `Committed and pushed <what/file>, but
  couldn't open the PR (<short reason>) - I'll retry automatically; say
  "ship it" to retry now.`
- Reuse (tweak 2+): **silent** - no announcement.
- Rediscovery (see §Session-start prune script below): `Picked up an open
  draft PR from a prior session: <title> (#<number>). Say "ship it" to
  mark it ready and merge, say "not now" and I won't ask again about this
  one, or it folds into the next related change.` An explicit decline
  writes `dismissed pr:<number>` to the tracker.

### Scope

Trivial tier only. The urgent-language escape hatch (precedence rule 2)
exits batching entirely. Theme/token/config/CI files are already excluded
from the Trivial tier by the classifier (§Trivial signals in
`content/sections/04-risk-classification.md`) and therefore never reach
this mechanism.

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
# Worktree reap (DS-196): this is the conductor's own preflight action, invoking
# bin/ds-cleanup-worktrees's full evidence-gated disposition (origin-reachability,
# activity liveness, dirty/locked/age/protected-content gates - see "The unproven
# class" and bin/ds-cleanup-worktrees's own docstring for the full predicate)
# against the CURRENT repo, backgrounded so this preflight never blocks on
# worktree count. `git rev-parse --show-toplevel` resolves the repo root explicitly
# rather than using $(pwd) - `.agentic/` is root-anchored in .gitignore, so a non-root
# cwd would otherwise create a stray, non-ignored `.agentic/` directory. Note: when this
# preflight itself runs from inside a worktree (rather than the main checkout),
# `--show-toplevel` returns THAT WORKTREE's own root, not the main checkout's - this is
# expected and acceptable, since the reap then scopes to that worktree's own repo view;
# the main-checkout session-start invocation is the normal case. The log is APPENDED
# (never truncated) with a per-run header line (UTC timestamp + pid) so DIFFERENT
# concurrent sessions interleave identifiably in `.agentic/worktree-reap.log` rather
# than clobbering the only record of a mutating removal pass. Corrected claim
# (round-2 Minor 6): `$$` in a backgrounded subshell expands to the PARENT shell's
# own pid, not a fresh subshell pid (verified in both bash and zsh) - a same-session
# 30-minute-idle re-fire (see below) shares this pid across every run and is
# distinguished by its timestamp alone, not by pid; pid only distinguishes a
# genuinely different session's own shell process. Suppress entirely with
# `AE_WORKTREE_REAP_DISABLE=1`; PATH-absence degrades to a warning, same discipline
# as the branch-prune guard below:
if [ -z "${AE_WORKTREE_REAP_DISABLE:-}" ]; then
  if command -v ds-cleanup-worktrees >/dev/null 2>&1; then
    REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || REPO_ROOT=""
    if [ -n "$REPO_ROOT" ]; then
      mkdir -p "$REPO_ROOT/.agentic" 2>/dev/null || true
      ( echo "=== reap $(date -u +%Y-%m-%dT%H:%M:%SZ) pid $$ ===" >> "$REPO_ROOT/.agentic/worktree-reap.log"
        ds-cleanup-worktrees --repo "$REPO_ROOT" \
          >> "$REPO_ROOT/.agentic/worktree-reap.log" 2>&1 || true ) >>"$REPO_ROOT/.agentic/worktree-reap.log" 2>&1 &
    fi
    # else: --show-toplevel failed (not a git repo) - skip silently, nothing to reap.
  else
    echo "WARNING: ds-cleanup-worktrees not found on PATH - re-run your harness's DinoStack install script (<repo>/.claude/install.sh for Claude Code, the equivalent script under your adapter directory otherwise) to wire bin/ onto PATH. Session-start worktree reap skipped this session." >&2
  fi
fi
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

**Residual, named not fixed (round-2 Minor 4): undisclosed reap/branch-prune concurrency.** The reap above is backgrounded (`&`, with the subshell's own file descriptors also redirected to the log so a harness pipe is never held open for the reap's duration) while `ds-branch-prune` immediately following it in the same script runs synchronously - the two race for the remainder of this preflight. Git ref/index lock contention (`.git/index.lock`, a stale `.git/refs/...` lock) can make either transiently fail; both already soft-fail by design (the reap's subprocess appends its own errors to the log via `|| true`, and `ds-branch-prune` is PATH-guarded and non-blocking on any exit per the comment above), so contention cannot corrupt state, only silently skip a removal or a prune for that one run - recoverable on the next invocation. A subtler case: the reap can remove a worktree mid-pass while `ds-branch-prune`'s subsumption predicate is still evaluating branches, changing which branches it is willing to delete out from under it (a branch whose only checked-out worktree existed at the START of the branch-prune run may be gone by the time it reaches that branch). There is no data-loss path either way - removal on both sides is always evidence-gated, and `ds-branch-prune`'s own ledger records every deletion - but this is the one accepted trade-off in this change that was not previously disclosed anywhere in this document.

**Tweak-PR rediscovery.** Runs in the same preflight, modeled on the
skill-candidate sweep's `open`/`dismissed` idiom
(`content/rules/conventions.md` §Session Context and Memory,
skill-candidate sweep) - co-located here rather than restated there
because both are worktree/branch lifecycle facts, not session-context
facts: `gh pr list --state open --json headRefName,number,title,isDraft`
filtered to `chore/tweak-*`, plus the bounded backstop (see §Implicit
Trivial batching: open the PR at first push above), diffed against the
session-scoped, gitignored tracker `.agentic/.tweak-pr-surfaced`
(`<session_id> pr:<number>` - announced this session;
`<session_id> branch:<name>` - create-failure backstop record;
`dismissed pr:<number>` - permanent cross-session suppression on an
explicit operator decline). Lookup order: `dismissed` -> permanently
suppressed; else a current-session line -> suppressed this session; else
announce once (the Rediscovery wording in §Implicit Trivial batching
above) and append. Entries whose PR is no longer open are pruned each
preflight, keeping the tracker bounded. **Pagination is explicitly
waived here**, unlike the meta-divergence and skill-candidate sweeps: the
donor set (`gh pr list --state open`, filtered to one narrow branch
prefix) is inherently small and remote-bounded, not a locally-growing log
file, so there is no vicious-loop risk to defend against.

## Ad-hoc (non-`/ds-implement-ticket`) worktree cleanup obligation

`/ds-implement-ticket` Phase 8's own cleanup block (§Isolation worktree cleanup commands above) only fires on that command's own success path - after a push succeeds on the ticket flow. Any ad-hoc isolation-worktree spawn made OUTSIDE that flow (a Worker per `AGENTS.md` §Workflow, a scratch investigation spawn, a one-off fix not run through `/ds-implement-ticket`) has no equivalent automatic trigger and is the single largest confirmed source of orphaned worktrees in practice - measured against this repo's own history, branches like `worktree-agent-<id>` (default-named, never renamed) and abandoned rework rounds (`ds-round8`..`ds-round12`, `work-round7`, `fix-gigi-round5` - legacy remnants that predate the round-N rework mechanic below and would not recur under it) accounted for the majority of accumulated non-root worktrees.

**Obligation:** whenever the conductor spawns an ad-hoc isolation-worktree Worker outside `/ds-implement-ticket`, it is responsible for cleaning up that worktree itself once the branch is pushed, the work is abandoned, or the session concludes - by running the same self-scoped pattern in §Isolation worktree cleanup commands above, immediately, rather than assuming any later automatic pass will catch it. This is a standing authorization (§Standing authorizations above already covers the removal itself); the obligation here is the TRIGGER - do it at the natural completion point of the ad-hoc spawn, not "eventually."

**Round-N rework coverage.** The Round-N rework mechanic above already establishes that rework rounds reuse the SAME branch and worktree rather than creating a fresh `-rN` sibling each round - this is what makes `-rN` proliferation a legacy failure mode rather than a live one. When a round is genuinely SUPERSEDED (a wholesale approach replacement per `content/rules/conventions.md` §Git Workflow's rework-vs-superseding test, not a same-approach fix), the superseded round's worktree is now abandoned and must be cleaned up at that moment - the close+rebase step that supersedes it is exactly the natural completion point this obligation attaches to, not a "later" pass.

**Backstop, not a substitute:** the session-start prune script, `bin/ds-branch-prune`, and `bin/ds-cleanup-worktrees` (invoked directly, via `/ds-cleanup-worktrees`, surfaced by the `ds-base-sync` advisory note and the SessionStart worktree-count nudge, or - as of DS-196 - invoked by the conductor's session-start preflight (backgrounded, per §Session-start prune script, so it never blocks), a fourth trigger path - see their own docs) all remain in place specifically because this obligation is process discipline, not a structural guarantee - a crashed session, an interrupted spawn, or a conductor that simply forgets still needs a backstop that eventually reclaims the worktree without relying on the obligation having been honored.

Implicit Trivial batching (§Implicit Trivial batching: open the PR at
first push above) needs no special case here: each continuation spawn is
an ordinary Trivial engineer running in its own harness isolation
worktree, so the standard "once the branch is pushed" trigger above
already covers it - there is no second worktree to separately account
for. A crash before push instead leaves the `SKIP_UNREFERENCED_COMMIT`
residual documented below.

## The unproven class, and archiving it (`--archive-unproven`)

Even with every prior gate passing (clean, unlocked, past the age floor, not self, not protected-content), `bin/ds-cleanup-worktrees` still refuses to remove a worktree whose branch carries real, unmerged commits that were never pushed anywhere and have no matching PR - `disposition_for` correctly reports `SKIP_UNPROVEN` rather than guessing. Measured against this repo's own live checkout, this is the dominant remaining blocker once the `.agentic/`-content correction landed: `skipped-protected-content` dropped to 0, but `removed` stayed 0, because most of the remaining worktrees carry exactly this class of branch (default-named `worktree-agent-<id>` branches and legacy `ds-round8`..`ds-round12` rework branches - see §Ad-hoc worktree cleanup obligation above for how they accumulated). Left alone by this predicate, `SKIP_UNPROVEN` worktrees do not resolve on their own. **This is now qualified, not absolute (DS-196):** a `SKIP_UNPROVEN` branch that has since been pushed to `origin` and reached a resolved (non-open) PR state can resolve via the separate `origin_reachable` evidence source (see the session-start reap above), which is LENIENT-only and evaluated after `pr_state` - `SKIP_UNPROVEN` itself, produced by the STRICT branch-deletion path, is untouched by this; only the worktree-removal path gains the new resolution route. A branch that is genuinely unpushed, with no PR, still never resolves.

**`SKIP_RECENT_ACTIVITY` masking note:** the new file-activity liveness gate (`--activity-window-hours`, default 3.0) is checked immediately after the age floor and before the dirty/locked checks, so a worktree that is BOTH recently active AND dirty or locked reports only `SKIP_RECENT_ACTIVITY` in a plain run - the dirty/locked facts are still true but not the reported reason. This is the same masking class as the pre-existing `SKIP_TOO_YOUNG` age-floor gate; `--explain` surfaces the full evidence for a given entry regardless of which single-reason bucket it lands in.

This repo already solved the identical problem for BRANCHES: a 2026-08-11 manual one-off operator sweep (DS-153) archived 75 branches its own four-layer subsumption predicate could not prove into one verified `git bundle` (`.agentic/branch-archive/`) before deleting them, rather than leaving them unresolved forever - `bin/ds-branch-prune` itself does not call `git bundle`. `bin/ds-cleanup-worktrees --archive-unproven` extends that exact pattern to WORKTREES - OPT-IN, never the default:

1. For each `SKIP_UNPROVEN` entry, `git bundle create .agentic/worktree-archive/<branch>-<timestamp>.bundle <branch>` captures the FULL branch - every commit unique to it, not just its tip. When the resolved base branch's objects can be excluded without producing an empty bundle, DS-191's compaction is applied: objects already reachable from the resolved base are excluded (`--not <base>`), producing a small bundle plus a recorded prerequisite commit, rather than a full copy of history already present on the base. Compaction is skipped (a full-history bundle is produced instead, and a NOTE is printed to stderr) for any of: the base ref cannot be verified locally (e.g. a bad explicit `--base`); the branch shares no history with it; an explicit `--base` verifies and shares history with the branch but does not resolve to the same commit this tool's own auto-resolution would have picked (see item 5 below); a concurrent `git fetch` advanced the base ref past the branch tip between the pre-create measurement and the actual bundle creation (a TOCTOU race - retried once without compaction rather than left stuck); or the rev-list commit count could not be parsed - a full-disk operator relying on this flag to reclaim disk should verify the base ref resolves before relying on compact bundles.
2. The bundle is VERIFIED with `git bundle verify` BEFORE any removal - a create failure, a missing/empty bundle, or a failed verification leaves the entry `SKIP_UNPROVEN`, worktree untouched, same discipline as the telemetry-salvage guard: a failed archive must never become a silent deletion of the only copy of unproven work.
3. Only then is the worktree removed - and ONLY the worktree. `bin/ds-cleanup-worktrees` never deletes the branch itself; the archived branch's own local ref remains `bin/ds-branch-prune`'s responsibility to resolve, same as every other branch in this repo.
4. The exact restore command is printed, braced per this repo's own documented zsh refspec gotcha: `git fetch <bundle> "refs/heads/${BRANCH}:refs/heads/${BRANCH}"`. For a compact bundle, the printed line also carries a parenthetical: restoring it requires the commit `git bundle` actually recorded as the bundle's prerequisite - the boundary/fork-point commit between the branch and the excluded base at archive time, which is NOT necessarily the base ref's own tip (measured: base at tip `8afc5cf` recorded a prerequisite of `b3e48266`) - to still be present in this repo's object store. `git bundle verify` at archive time only proves that commit exists locally right now, not permanently - a later force-push/rewrite-and-gc of the base branch could still invalidate an already-archived compact bundle. A full-history bundle (no exclusion applied) has no such dependency and is self-contained.
5. **An explicit `--base` is never compacted against unless it resolves to the same commit auto-resolution would have picked (round-N, DS-191 MAJOR-2 fix).** `resolve_base_branch` returns an explicit `--base` unvalidated - nothing constrains it to a durable ref, so compacting against an arbitrary caller-supplied ref (e.g. a feature branch later deleted and gc'd) would create a bundle whose sole prerequisite can vanish, making the archive permanently unrestorable. When `--base` is supplied explicitly and does not resolve to the same commit the tool's own auto-resolution tiers would have picked, compaction is skipped (full-history bundle, with a `NOTE:` explaining why) even though the base ref itself verifies and shares history with the branch.

`.agentic/worktree-archive/` is gitignored (the existing `/.agentic/*` umbrella already covers it - no new carve-out) and grows unbounded, exactly like `.agentic/branch-archive/` before it - pruning it is the operator's own responsibility, not something either tool does automatically. Without `--archive-unproven`, `SKIP_UNPROVEN` entries are reported and never touched - this is unchanged default behavior. See `bin/ds-cleanup-worktrees`'s own module docstring ("Archiving unproven branches") for the full mechanism.

Not every non-`ELIGIBLE` branch-evidence outcome lands in `SKIP_UNPROVEN`, and `--archive-unproven` only ever considers entries that do. A worktree whose `gh pr list` query genuinely FAILED for that one branch (rate limit, auth hiccup, network blip - `gh` itself remains available) resolves to its own `SKIP_PR_QUERY_ERROR` outcome instead, on every run mode, not only under `--archive-unproven` - a query failure is a distinct fact from "no PR exists" and treating it as absence would let a worktree behind a live OPEN PR be silently archived (or, on the lenient MERGED-is-sufficient worktree-removal path, removed outright with no flags at all). See `bin/ds-cleanup-worktrees`'s own module docstring, Removal predicate gate 9, for the full mechanism.

## `SKIP_UNREFERENCED_COMMIT`: a distinct detached-HEAD-commit class

The route into this disposition (§Implicit Trivial batching: open the PR
at first push above) is a detached HARNESS ENGINEER WORKTREE that crashed
before its push - no nested worktree, just the engineer's own
`.claude/worktrees/agent-<id>` left with `git symbolic-ref -q HEAD`
failing and possibly an uncommitted-nowhere-else commit sitting on top.
That leftover is a distinct disposition from `SKIP_UNPROVEN` above - it
is not a checked-out branch with unproven ancestry, it is a **detached
HEAD**. `disposition_for` reports it as `SKIP_UNREFERENCED_COMMIT`,
refused by the same work-preserving discipline as `SKIP_UNPROVEN`. **As
of today this is the outcome for EVERY such leftover, not only an
unpushed one** - `head_reachable`, the fact that would let a leftover
whose commit already reached `origin` resolve `ELIGIBLE` instead, is dead
code in `bin/ds-cleanup-worktrees` (see §Crash paths above); nothing
currently distinguishes "sole copy of the work" from "already safely on
origin" for you. Auto-deleting an entry in this disposition is never
acceptable either way, since the tool itself cannot yet tell which case
it is.

**Manual recovery/discard procedure:**

0. **Triage first - check whether the work is already safe:**
   `git -C <path> branch -r --contains "$(git -C <path> rev-parse HEAD)"`.
   Nonempty output means the commit already reached `origin` on some ref -
   nothing is at risk, and step 3 (plain `worktree remove`) alone is
   sufficient; skip step 2. Empty output means this worktree is the sole
   copy - continue through steps 1-3 in full.
1. Inspect the committed tip: `git -C <path> log -1`.
2. Recover the work either by pushing it to its intended destination from
   inside the worktree - `git -C <path> push origin "HEAD:refs/heads/<intended-branch>"`
   (braced variables, explicit refspec - the same binding constraint as
   the routine push in §Implicit Trivial batching above) - or by
   cherry-picking the commit onto wherever it belongs.
3. **Discard via plain `git worktree remove <path>` FIRST** - never reach
   for `--force` as the first move. A refusal naming "modified or
   untracked files" means there is uncommitted work that step 1's
   `log -1` inspection structurally cannot show (a detached HEAD's
   committed tip says nothing about the working tree on top of it). On
   that refusal, inspect `git -C <path> status --porcelain` and
   `git -C <path> diff` before deciding what to do with the uncommitted
   content, and only then run `git worktree remove --force <path>`.

**Note - this is the harness's own isolation worktree, unlike the
now-deleted nested-worktree design, so the §Guardrail: never
force-override the harness lock rule above applies directly here, not as
an unrelated aside.** If `git worktree remove` instead refuses citing the
lock (a still-running or not-yet-reaped agent), that is a DIFFERENT
refusal from the uncommitted-content one in step 3 - do not unlock or
force-remove it; follow §Isolation worktree cleanup commands above
("that is expected and safe... NEVER a signal to unlock or
force-remove") and let the session-start prune's locked-but-dir-missing
reclaim path or the automatic reap resolve it once the lock is genuinely
released. Only a refusal naming uncommitted content (not a lock) is what
step 3's `--force` addresses.

### Advisory: sharing node_modules across worktrees (pnpm)

For JS/Web-UI projects using a worktree-per-feature workflow, per-worktree `node_modules` is the dominant raw-disk driver - roughly 2G per worktree is typical, and that cost multiplies by every open worktree. npm and yarn both install a full independent copy of `node_modules` per worktree, so disk usage scales linearly with worktree count.

pnpm avoids this by installing from a single machine-wide content-addressable store and linking (hard links) each worktree's `node_modules` from it, so N worktrees cost roughly one full copy plus cheap links rather than N full copies.

Migrating an existing project to pnpm (`pnpm import` from an existing lockfile, or simply switching the install command) is a per-project decision and is out of DinoStack's scope to automate - this is advisory only, not an enforced or default behavior. Nothing in the worktree cleanup or prune tooling assumes or requires pnpm.

## Cross-repo mode: `--multi-repo` and `--report`

`bin/ds-cleanup-worktrees --multi-repo` extends every gate and mechanism documented above (self/age/dirty/locked/protected-content, `SKIP_UNPROVEN`, `--archive-unproven`) to sweep several repos in one call, sequentially, each resolving its OWN base independently (`--base` combined with `--multi-repo` is a usage error - a single global base would silently leak one repo's base into every other repo's evaluation). `--multi-repo --report` (with or without `--count-only`) is the read-only, ranked cross-repo visibility companion - "which project is worst" - and is the recommended first step before a multi-repo sweep; see `content/commands/ds-cleanup-worktrees.md` for the full flag reference and the two cost tiers. The standalone `bin/ds-reap-all` subprocess-per-repo sweep wrapper has been retired - this in-process mode is the sole cross-repo mechanism.

## Guardrail: never force-override the harness lock

No cleanup or prune path in this document may call `git worktree remove -f -f` (double force, which overrides a lock). `git worktree unlock` may be used ONLY on a worktree whose directory is already gone - at that point its agent cannot still be running, so there is nothing left to protect (this is exactly what the isolation-cleanup and session-start-prune steps do to reclaim a stale locked admin entry). Never unlock, or double-force-remove, a worktree whose directory still exists: the harness's lock (set on every isolation worktree while its agent runs) is load-bearing cross-session protection - it is the reason a concurrent session's cleanup cannot delete another session's live worktree, and overriding it reintroduces exactly the mid-task-deletion risk. No path in this document currently does this; the note is a guardrail against future regression.

## Dev-server process lifetime ownership

Any dev server booted by an agent - qa-engineer's boot pattern, engineer's runtime smoke test, or any ad-hoc verification - is run-scoped only and will not survive the agent's run on this harness. The operator's own shell is the only durable owner of a dev server's lifetime, unless a future mechanism explicitly states otherwise. Treat "restarted and verified" from an agent as true only for the duration of that agent's own run, never as a claim about server availability afterward.

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
  Note: `git fetch --prune` removes stale remote-tracking refs, and origin-
  reachability evidence (see the session-start reap below) depends on those
  refs surviving locally - as `fetch.prune` runs, coverage for this evidence
  source shrinks toward pre-DS-196 behavior (fail-closed, no data loss), not
  silently wrong; this is a consequence of an already-standing authorization,
  not a hypothetical.
- Running the automatic, backgrounded session-start worktree reap
  (`bin/ds-cleanup-worktrees`, invoked from the session-start prune block
  above) against worktrees other than the current session's own -
  suppressible via `AE_WORKTREE_REAP_DISABLE=1`. This authorization also
  covers its 30-minute-idle preflight re-run (per `content/sections/11-worktree-lifecycle.md`):
  every gate re-evaluates fresh git/filesystem state on each invocation, so
  a re-fire cannot remove anything a fresh run would not independently judge
  safe at that moment - a worktree that became active in the interim is
  re-protected by the activity gate. **Residual, named not fixed:** a live
  session's own or a second live session's clean, pushed, idle-past-window
  worktree (including the current session's own non-cwd feature worktree,
  reapable via the 30-minute-idle re-fire since `SKIP_SELF` only protects the
  cwd worktree) can be reaped out from under it - the harness lock covers
  only RUNNING agents. No commits are ever lost (removal is worktree-only,
  evidence-gated); the activity window is the deliberate defense; no
  cross-session-branch-skip gate is added, since the tool has no visibility
  into other sessions' branches beyond the locked flag.

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

DinoStack's mandatory-isolation rule (every `engineer`/`qa-engineer`/`release-orchestrator` spawn runs in its own worktree) depends on a Claude Code fix that lets an isolated subagent read and edit files inside its OWN worktree. On builds predating that fix, an isolated engineer self-denies on its own files and deadlocks - it cannot edit the very tree it was spawned to change. On such a build, `hooks/enforce-worktree-isolation-spawn.py` compounds this into a TOTAL deadlock: it denies a non-isolated spawn of the three mandated roles, and isolation itself deadlocks per the paragraph above, leaving no permitted action. The escape hatch is that hook's kill-switch, `AE_WORKTREE_ISOLATION_GUARD_DISABLE=1` (set in the environment that launches Claude Code, then restart) - not a substitute for the Claude Code fix, only a way to fall back to the pre-spawn stash fallback below while the operator is stuck on a pre-fix build. Treat the fix as a hard floor for the delegation model. Keep the aggressive per-session worktree prune above regardless of Claude Code's own 30-day orphan sweep: the sweep cleans Claude Code's isolation worktrees on a monthly cadence and is a backstop, not a replacement; stale worktrees accumulate between sweeps.

## Project-override policy

Worktree lifecycle rules - classification (`classify_entry`) and disposition (`disposition_for` / `disposition_for_orphan_branch`, all in `bin/tests/worktree_model.py`) - are methodology-owned and NOT overridable by a project `AGENTS.md`. A project may add non-conflicting project-specific conventions (e.g. pruning its own generated artifacts) but may NOT redefine which path prefixes mean ISOLATION/CONDUCTOR_CREATED, change the disposition gate order, or otherwise contradict the classification or trigger rules in this document.

This is a deliberate absence from the small set of items a project MAY declare - e.g. `BASE_BRANCH:` per `content/rules/conventions.md` §Git Workflow. Unlike the base branch, worktree lifecycle touches cross-session safety: the harness's own lock-while-running behavior, branch-rename mapping across sessions, and another session's live work. A per-project override could not safely account for any of those, so none is offered and no declaration form is defined for it.

## Pre-spawn stash fallback

Pre-spawn safety net (fallback, not a substitute for isolation): before any non-isolated spawn that the conductor cannot avoid, the conductor stashes its scaffolding to keep it out of the subagent's working tree. On Claude Code, a non-isolated spawn of `engineer`/`qa-engineer`/`release-orchestrator` is mechanically DENIED by `hooks/enforce-worktree-isolation-spawn.py`, so for those three roles this fallback is reachable only via that hook's kill-switch for the two documented emergency cases below. For any other role (e.g. `investigator`, `architect`), a non-isolated spawn is still permitted on Claude Code - and on any other adapter, which has no such hook at all and relies on the prose rule alone (Claude Code's legacy `Task` tool name is also unenforced by this hook - see that hook's own Trigger docstring note) - the fallback below applies directly:

```bash
git stash push --include-untracked --keep-index --message 'conductor-scaffolding-pre-spawn'
# ... spawn returns ...
git stash pop
```

This is a fallback only. Worktree isolation is the primary mechanism; the stash dance exists for the rare case where isolation is genuinely not possible (e.g. the Trivial carve-out interleaving with an unexpected concurrent spawn).

On Claude Code specifically, the kill-switch is `AE_WORKTREE_ISOLATION_GUARD_DISABLE=1` (set before launching Claude Code, then restart), reachable only for the two documented emergency cases where the hook itself would otherwise deadlock the session (§Version floor above; a build where the harness genuinely does not honor the worktree-isolation spawn parameter at all). Do not reach for the kill-switch merely because a spawn is inconvenient to isolate - it disables the enforcement mechanism for the whole session, not just the one spawn, and its use should be rare and short-lived (unset it, or restart without it, as soon as the emergency case is past).
