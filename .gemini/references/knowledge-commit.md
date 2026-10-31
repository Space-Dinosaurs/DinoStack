<!--
Purpose: Full procedure for Phase 11e of `/ds-implement-ticket` - the
         checkout-free knowledge commit that ships this session's
         knowledge files onto the PR branch - moved verbatim out of
         content/commands/ds-implement-ticket.md so a run that never
         reaches it does not carry it. Covers the purpose, design
         constraints, candidate set and per-file gating, event field
         semantics, the step 0 shard rollup `@harness` block, the
         `ds-ticket-finish knowledge` call, and the CI and delivery-refresh
         notes.

Public API: Read-only reference document, addressed by its retained
            `## Phase 11e: Knowledge commit onto the PR branch
            (soft-fail)` heading. The phase heading, its Trigger line,
            and the Trivial-skip paragraph stay inline in
            content/commands/ds-implement-ticket.md, followed by a
            one-line `**Procedure:**` pointer to this file.
            The knowledge-commit block itself lives in bin/ds-ticket-finish
            (`knowledge` step), where
            bin/tests/test_phase11e_knowledge_commit_shell.py extracts it.

Upstream deps: none (prose reference only; no code, no runtime execution).
               Assumes content/references/delivery-record.md and
               content/references/capture-classification.md, and the
               Phase 8, Phase 9, and Phase 12 sections of
               content/commands/ds-implement-ticket.md, are in context.

Downstream consumers: content/commands/ds-implement-ticket.md (Phase 11e
                      pointer line; Phase 12 re-derives the
                      knowledge-commit condition this phase creates).
                      /ds-wrap Part G is the backstop when this phase
                      skips or fails.

Failure modes: Prose reference; does not auto-execute. A conductor that
               skips the pointer ships no knowledge commit on the PR;
               the content stays in the local checkout until /ds-wrap
               Part G commits it.

Performance: n/a (static reference document).
-->

## Phase 11e: Knowledge commit onto the PR branch (soft-fail)

**Purpose.** A ticket session that produced durable knowledge - root `MEMORY.md`, `decisions.md`, `.agentic/learnings.md`, `AGENTS.md`, `.agentic/tracking.md` - currently leaves it in the operator's local checkout only, where it never rides the PR. The isolation worktree that carried this ticket's code is removed at Phase 8, well before Phase 9 opens the PR, and `wrap-ticket` does not write those files until Phase 11b - so the write can never happen "inside the worktree." Phase 11e moves the **commit** instead of the write: it builds a commit from a temporary index plus `git commit-tree`, then pushes the resulting SHA straight to `refs/heads/$BRANCH_NAME`. No checkout, no worktree, and HEAD is never touched.

**Reads from disk, never from an agent return value.** The candidate files are read off the filesystem at the moment this phase runs. This is deliberate: the deleted predecessor of this phase read only `wrap-ticket`'s return JSON, so every `learnings-agent` write was invisible to it and it produced zero commits over its entire lifetime.

**`auto_merge_on_ci_green` is re-read from config here, not inherited.** Phase 11e runs as a separate Bash invocation from the preflight that set `$AUTO_MERGE_ON_CI_GREEN`; no shell state crosses that boundary, so the value is re-derived from `.agentic/config.json`.

**Checkout-free and worktree-free.** Phase 8's telemetry commit needs a HEAD-branch guard because it commits inside a checkout that could be on the wrong branch. Phase 11e has no analogue and needs none: it never checks anything out and never moves HEAD, so there is no branch state to guard.

**The real index is never touched - including by `update-index`.** Every index operation in the block below targets `$KC_IDX`, a temporary index file under the git dir. `git update-index --refresh` rewrites whichever index it is pointed at, so refreshing the real `$REPO/.git/index` would trade the conductor-checkout-untouched guarantee for the correctness guarantee below. Refreshing the temp index gives both.

**Push safety.** The push is an ordinary fast-forward push to the branch ref - not a force push. If a concurrent session advanced the branch between the `read-tree` and the push, the push is **rejected**, not applied over the top; the rejection is reported and the knowledge is simply not shipped on this PR.

A successful push leaves the operator's LOCAL `$BRANCH_NAME` one commit behind `origin/$BRANCH_NAME` - Phase 8 committed telemetry on that branch inside the checkout, and Phase 11e never moves the local ref. This is harmless and needs no reconciliation: a later push from that stale local branch is rejected non-fast-forward rather than silently overwriting the knowledge commit, and the branch is deleted at merge.

**DCO.** `git commit-tree` takes no `-s`, so the `Signed-off-by:` trailer is written literally into the commit message. This is the one sanctioned exception to the repo rule "build commits with porcelain `git commit -s`, never `git commit-tree`" - the exception exists because Phase 11e must commit without a checkout, and it inherits that plumbing command's pre-commit-hook bypass along with it.

**Portability.** The block is written for both bash and zsh. zsh does not word-split unquoted expansions, so no list is ever built by splitting a variable; `awk` receives `$BRANCH_NAME` via `-v` rather than `ENVIRON[...]` (the variable is conductor-substituted, not exported, so `ENVIRON` resolves empty under both shells); and no variable is named `path` or `status`, both of which collide with zsh specials.

**Absolute soft-fail for knowledge capture.** Nothing in Phase 11e fails the ticket; unresolved delivery publication still blocks merge/new queue under the canonical procedure. The block contains zero `exit` statements by contract; every failure branch prints a warning and continues.

**Candidate set**, in this fixed order: `MEMORY.md`, `decisions.md`, `.agentic/learnings.md`, `AGENTS.md`, `.agentic/tracking.md`. **There is no path-prefix floor.** A categorical refusal to touch anything under `.agentic/*` is precisely the defect that made this phase's deleted predecessor ship zero commits - `.agentic/learnings.md` is a first-class candidate here.

**`knowledge_commit_exclude` gate.** Read from `.agentic/config.json` (array of strings, default `[]`). Each entry is matched by EXACT STRING against the candidate-set entry exactly as listed above (e.g. `.agentic/learnings.md`, not `learnings.md`); an entry that does not match any of the five strings exactly is a silent no-op. This gate runs FIRST inside the file-existence check (after it, not before - an excluded file that does not exist on disk must never produce a fabricated skip record) and skips THAT FILE ONLY, printing a VISIBLE diagnostic. DinoStack's own repo sets this locally (gitignored `.agentic/config.json`, never committed) to `["AGENTS.md"]` to preserve the 2026-08-11 operator decision that session learnings never write to AGENTS.md here.

**Per-file gating.** Each check skips THAT FILE ONLY and never aborts the sweep:
- File absent from disk -> skip silently.
- File's entry in the candidate set above is present in `knowledge_commit_exclude` -> skip THIS FILE ONLY, printing the VISIBLE diagnostic above. **Never redirect this to `/dev/null`.**
- `ds-migrate verify-commit-path <f> --project-root $REPO` exits 1 -> a negation in the live `.gitignore` appears to target `<f>`, but git still reports it ignored (a DEFEATED negation - the point-of-use, exact-path counterpart to `bin/ds-migrate check`/`apply`'s manifest-wide, probe-based sweep, which must synthesize candidate probe paths for the 4 directory-form negations and can miss an unguessed spelling; see `_compute_negations_defeated`'s docstring for that residual). Print a VISIBLE `ERROR:` diagnostic naming `<f>` and skip - this is a loud failure, distinct from the ordinary gitignore skip below. **Never redirect this to `/dev/null`.**
- `git check-ignore -q -- <f>` succeeds -> skip, and print a VISIBLE diagnostic quoting the matched rule from `git check-ignore -v -- <f>`. **Never redirect this to `/dev/null`.** This gate is load-bearing for correctness, not merely for diagnostics: `git add` refuses an ignored path without `-f`, so the gate is what keeps the staging step from failing on a path that was never committable. In DinoStack itself four of the five candidates are gitignored with no negation attempted at all, and the fifth (`AGENTS.md`) is excluded via `knowledge_commit_exclude` instead since it must stay tracked and un-ignored in every repo including this one - which makes this bullet (not the DEFEATED-negation bullet above, which only fires when a negation was attempted and failed) a deliberate and **audible** no-op in this repo for the four gitignored files; consumer projects track all five and get the commit.
- `git cat-file -e origin/$BRANCH_NAME:<f>` fails (the path is absent from the tip) -> the file **survives gating**; it is new content. This probe must run BEFORE the diff, because a path absent from the tip is equally absent from the temp index and `diff-index` would report no difference for it.
- Path present at the tip -> refresh the temp index for that path, then `git diff-index --quiet`. Identical -> skip. Different -> stage.

**The index refresh is mandatory and load-bearing.** `git diff-index --quiet` trusts stat data over content for entries outside git's racily-clean window, so a byte-identical file that was rewritten with a newer mtime is misclassified as changed (measured at roughly 30% of runs before the condition was forced). Refreshing the temp index for that path first is what makes the comparison content-accurate.

**Idempotency.** A second run over unchanged state stages nothing and, if it somehow stages something whose resulting tree equals the branch tip's tree, short-circuits on the tree comparison. Neither path produces an empty commit.

**Event field semantics.** The `knowledge_commit` event carries `site: "phase-11e"`, `files_staged` (everything staged before the commit attempt), and `files_committed` (files that were **actually committed and pushed** - populated on the success path and only there, so it is empty on every non-success status). `files_skipped_ignored` (array of the candidate-set entries exactly as listed above - e.g. `.agentic/learnings.md`, not `learnings.md` - skipped by the gitignore gate, the `knowledge_commit_exclude` config toggle, or the per-file revert-risk gate - the field name predates all three additional cases and is kept for schema stability; it does not distinguish which skip reason applies for a given file - the printed diagnostic line is the only place that distinction is visible). The per-file revert-risk gate runs unconditionally, regardless of `auto_merge_on_ci_green`: a file it excludes is never staged and therefore never contributes to the separate `deleted_lines` aggregate field, which continues to reflect only whatever ended up staged. `deleted_lines` is `-1` when the revert guard could not be evaluated (fail-closed). `status: "no-branch"` is deliberately distinct from `"no-changes"`: the ref-absence warning is printed to stdout, which is not durable, so without a separate status `events.jsonl` could not distinguish "there was no PR branch to commit onto" from "nothing changed".

### Phase 11e step 0: shard rollup (soft-fail, runs BEFORE the candidate-file sweep)

**Why here.** Subagents record learnings in flight into the per-session shard store via `bin/ds-learning-shard append` (see `content/references/learnings-capture-instruction.md`). Nothing else drains that store on the ticket path. Rolling up **before** the candidate-file sweep below is the whole point: entries folded into `.agentic/learnings.md` now are read off disk by the same sweep and ride the same commit onto the PR branch. Rolling up after it would ship nothing until some later session.

**The CLI performs zero classification.** `rollup` emits raw entries as a JSON array on stdout and exits 0 on every path, soft-fails included. The conductor classifies each emitted entry through the existing guardrail-first table in `content/references/capture-classification.md` - the same gate every mandatory trigger already uses - and forwards only the `Capture: MUST` items to `learnings-agent`, emitting the `Capture: MUST/SKIP` declaration for each exactly as at any other trigger. There is no second classification path; `SKIP` items are dropped, not written.

**Session key.** `--session-key` is optional. Pass `$SESSION_KEY` when the conductor has one (the value it supplied in this ticket's spawn briefs); when it is unset or empty, omit the flag and roll up every shard for this repo.

**Absolute soft-fail.** A rollup failure, an unparseable array, or an absent `ds-learning-shard` binary is a warning and nothing more: the sweep, the commit, the push, the PR, and Phase 12 all proceed unchanged. `|| true` is mandatory on the invocation; no `exit` is permitted here either.

```bash
# @harness:phase11e-shard-rollup
# Drain this session's in-flight learning shards BEFORE the candidate-file sweep
# below, so anything folded into .agentic/learnings.md rides the same commit.
# Soft-fail: zero `exit` statements; a failure here changes nothing downstream.
if command -v ds-learning-shard >/dev/null 2>&1; then
  if [ -n "${SESSION_KEY:-}" ]; then
    KC_ROLLUP=$(ds-learning-shard rollup --repo "$REPO" --session-key "$SESSION_KEY" || true)
  else
    KC_ROLLUP=$(ds-learning-shard rollup --repo "$REPO" || true)
  fi
  echo "[phase: knowledge-commit | step=shard-rollup]"
  echo "$KC_ROLLUP"
else
  echo "[phase: knowledge-commit | step=shard-rollup | status=unavailable] ds-learning-shard not on PATH - skipping rollup."
fi
```

The conductor then classifies each entry in that array per `content/references/capture-classification.md` and forwards the `Capture: MUST` ones to `learnings-agent` before running the sweep below. If the array is empty, there is nothing to classify and the sweep runs unchanged.

The sweep, commit, and push run as `ds-ticket-finish knowledge`; its `@harness:phase11e-knowledge-commit` region in `bin/ds-ticket-finish` is the block this section describes:

```bash
"$REPO_DIR/bin/ds-ticket-finish" knowledge --repo "$REPO" --branch "$BRANCH_NAME" --ticket "$TICKET_ID" --gh-repo "$GH_REPO"
```

`GIT_INDEX_FILE="$KC_IDX" git ...` is a **per-command assignment, not an export**, in both bash and zsh - the value is scoped to that one invocation and cannot reach `$REPO/.git/index`. Do not convert it to an `export ... ; unset ...` pair, and do not remove it from the `update-index` call.

**CI interaction.** With `auto_merge_on_ci_green: false` (the default) there is no interaction to reason about: the PR stays open, CI re-runs against the new tip, and the human merges when it is green. With `auto_merge_on_ci_green: true`, Phase 12 re-derives the knowledge-commit condition from `gh` and queues GitHub's own auto-merge, which completes only once the checks are green.

**Delivery refresh (binding).** After this block, collect/publish the new remote-head record per `content/references/delivery-record.md`, retaining original review/QA evidence SHAs with pending coverage until assessed. Leave any suspended queue off until applicable checks are resolved and a guarded request succeeds.

**CI after the late push.** Phase 10a does not re-fire. Final delivery collection observes current CI before any merge/new queue; unresolved results remain owned. GitHub's required checks govern an accepted queue. There is no background monitor for later failures; report the current state rather than promise a future merge. `knowledge_commit_on_pr: false` still disables this phase.

**Per-unit attribution is out of reach and is not attempted.** Fan-out unit branches are merged and `git branch -d`'d at the Phase 5/6 boundary, before Phase 6 fires; `findings_log` entries carry no unit tag; and neither `wrap-ticket` nor `learning-extractor` accepts a unit identifier. What Phase 11e delivers is therefore per-**ticket** attribution. The minimal change that would make per-unit attribution possible - propagate the orchestration planner's per-unit slug into each per-unit Skeptic `findings_log` entry as a `unit` field, and add a `unit` key to `learning-extractor`'s LRN schema - is recorded here as a separate ticket's scope, not built as part of this phase.
