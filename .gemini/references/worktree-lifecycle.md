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
         every other gate cannot resolve).

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
               bin/ds-branch-prune, and bin/ds-cleanup-worktrees backstops.

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
# Automatic worktree reap (DS-196): runs bin/ds-cleanup-worktrees's full evidence-gated
# disposition (origin-reachability, activity liveness, dirty/locked/age/protected-content
# gates - see "The unproven class" and bin/ds-cleanup-worktrees's own docstring for the
# full predicate) against the CURRENT repo, backgrounded so this preflight never blocks
# on worktree count. `git rev-parse --show-toplevel` resolves the repo root explicitly
# rather than using $(pwd) - `.agentic/` is root-anchored in .gitignore, so a non-root
# cwd would otherwise create a stray, non-ignored `.agentic/` directory. Note: when this
# preflight itself runs from inside a worktree (rather than the main checkout),
# `--show-toplevel` returns THAT WORKTREE's own root, not the main checkout's - this is
# expected and acceptable, since the reap then scopes to that worktree's own repo view;
# the main-checkout session-start invocation is the normal case. The log is APPENDED
# (never truncated) with a per-run header line (UTC timestamp + pid) so concurrent
# sessions or a 30-minute-idle re-fire (see below) interleave identifiably in
# `.agentic/worktree-reap.log` rather than clobbering the only record of a mutating
# removal pass. Suppress entirely with `AE_WORKTREE_REAP_DISABLE=1`; PATH-absence
# degrades to a warning, same discipline as the branch-prune guard below:
if [ -z "${AE_WORKTREE_REAP_DISABLE:-}" ]; then
  if command -v ds-cleanup-worktrees >/dev/null 2>&1; then
    REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || REPO_ROOT=""
    if [ -n "$REPO_ROOT" ]; then
      mkdir -p "$REPO_ROOT/.agentic" 2>/dev/null || true
      ( echo "=== reap $(date -u +%Y-%m-%dT%H:%M:%SZ) pid $$ ===" >> "$REPO_ROOT/.agentic/worktree-reap.log"
        ds-cleanup-worktrees --repo "$REPO_ROOT" \
          >> "$REPO_ROOT/.agentic/worktree-reap.log" 2>&1 || true ) &
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

## Ad-hoc (non-`/ds-implement-ticket`) worktree cleanup obligation

`/ds-implement-ticket` Phase 8's own cleanup block (§Isolation worktree cleanup commands above) only fires on that command's own success path - after a push succeeds on the ticket flow. Any ad-hoc isolation-worktree spawn made OUTSIDE that flow (a Worker per `AGENTS.md` §Workflow, a scratch investigation spawn, a one-off fix not run through `/ds-implement-ticket`) has no equivalent automatic trigger and is the single largest confirmed source of orphaned worktrees in practice - measured against this repo's own history, branches like `worktree-agent-<id>` (default-named, never renamed) and abandoned rework rounds (`ds-round8`..`ds-round12`, `work-round7`, `fix-gigi-round5` - legacy remnants that predate the round-N rework mechanic below and would not recur under it) accounted for the majority of accumulated non-root worktrees.

**Obligation:** whenever the conductor spawns an ad-hoc isolation-worktree Worker outside `/ds-implement-ticket`, it is responsible for cleaning up that worktree itself once the branch is pushed, the work is abandoned, or the session concludes - by running the same self-scoped pattern in §Isolation worktree cleanup commands above, immediately, rather than assuming any later automatic pass will catch it. This is a standing authorization (§Standing authorizations above already covers the removal itself); the obligation here is the TRIGGER - do it at the natural completion point of the ad-hoc spawn, not "eventually."

**Round-N rework coverage.** The Round-N rework mechanic above already establishes that rework rounds reuse the SAME branch and worktree rather than creating a fresh `-rN` sibling each round - this is what makes `-rN` proliferation a legacy failure mode rather than a live one. When a round is genuinely SUPERSEDED (a wholesale approach replacement per `content/rules/conventions.md` §Git Workflow's rework-vs-superseding test, not a same-approach fix), the superseded round's worktree is now abandoned and must be cleaned up at that moment - the close+rebase step that supersedes it is exactly the natural completion point this obligation attaches to, not a "later" pass.

**Backstop, not a substitute:** the session-start prune script, `bin/ds-branch-prune`, and `bin/ds-cleanup-worktrees` (invoked directly, via `/ds-cleanup-worktrees`, surfaced by the `ds-base-sync` advisory note and the SessionStart worktree-count nudge, or - as of DS-196 - run automatically and unattended by the backgrounded session-start reap above, a fourth trigger path - see their own docs) all remain in place specifically because this obligation is process discipline, not a structural guarantee - a crashed session, an interrupted spawn, or a conductor that simply forgets still needs a backstop that eventually reclaims the worktree without relying on the obligation having been honored.

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

### Advisory: sharing node_modules across worktrees (pnpm)

For JS/Web-UI projects using a worktree-per-feature workflow, per-worktree `node_modules` is the dominant raw-disk driver - roughly 2G per worktree is typical, and that cost multiplies by every open worktree. npm and yarn both install a full independent copy of `node_modules` per worktree, so disk usage scales linearly with worktree count.

pnpm avoids this by installing from a single machine-wide content-addressable store and linking (hard links) each worktree's `node_modules` from it, so N worktrees cost roughly one full copy plus cheap links rather than N full copies.

Migrating an existing project to pnpm (`pnpm import` from an existing lockfile, or simply switching the install command) is a per-project decision and is out of DinoStack's scope to automate - this is advisory only, not an enforced or default behavior. Nothing in the worktree cleanup or prune tooling assumes or requires pnpm.

## Cross-repo mode: `--multi-repo` and `--report`

`bin/ds-cleanup-worktrees --multi-repo` extends every gate and mechanism documented above (self/age/dirty/locked/protected-content, `SKIP_UNPROVEN`, `--archive-unproven`) to sweep several repos in one call, sequentially, each resolving its OWN base independently (`--base` combined with `--multi-repo` is a usage error - a single global base would silently leak one repo's base into every other repo's evaluation). `--multi-repo --report` (with or without `--count-only`) is the read-only, ranked cross-repo visibility companion - "which project is worst" - and is the recommended first step before a multi-repo sweep; see `content/commands/ds-cleanup-worktrees.md` for the full flag reference and the two cost tiers. The standalone `bin/ds-reap-all` subprocess-per-repo sweep wrapper has been retired - this in-process mode is the sole cross-repo mechanism.

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
