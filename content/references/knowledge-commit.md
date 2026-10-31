<!--
Purpose: Full procedure for Phase 11e of `/ds-implement-ticket` - the
         checkout-free knowledge commit that ships this session's
         knowledge files onto the PR branch - moved verbatim out of
         content/commands/ds-implement-ticket.md so a run that never
         reaches it does not carry it. Covers the purpose, design
         constraints, candidate set and per-file gating, event field
         semantics, the step 0 shard rollup, both `@harness` shell
         blocks, and the CI and delivery-refresh notes.

Public API: Read-only reference document, addressed by its retained
            `## Phase 11e: Knowledge commit onto the PR branch
            (soft-fail)` heading. The phase heading, its Trigger line,
            and the Trivial-skip paragraph stay inline in
            content/commands/ds-implement-ticket.md, followed by a
            one-line `**Procedure:**` pointer to this file.
            bin/tests/test_phase11e_knowledge_commit_shell.py extracts the
            `phase11e-knowledge-commit` harness block from this file.

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

```bash
# @harness:phase11e-knowledge-commit
# Phase 11e: commit this session's knowledge files onto the PR branch.
# Checkout-free and worktree-free: builds the commit with a temporary index plus
# commit-tree and pushes the SHA straight to the branch ref, so HEAD is never
# touched and the Phase-8-removed isolation worktree is not needed.
#
# PORTABILITY (bash + zsh): zsh does not word-split unquoted expansions. Never
# write `git add -- $KC_SURVIVORS`; never build a list with `echo $VAR | tr`;
# never use awk ENVIRON[...] (BRANCH_NAME is substituted, not exported, so
# ENVIRON resolves empty under BOTH shells) - pass it with -v. Never name a
# variable `path` or `status` (zsh collisions). ALWAYS brace an expansion that
# is followed by a literal `:` - zsh applies history-style modifiers to an
# UNBRACED `$VAR:...` even inside double quotes, so "$KC_SHA:refs/heads/..."
# silently becomes the `:r` (remove-extension) form of the SHA followed by
# "efs/heads/...", and the push fails with a bogus "src refspec ... does not
# match any". Measured, not theoretical.
#
# DIAGNOSTIC / FAIL-CLOSED: no `2>/dev/null` on check-ignore, read-tree,
# update-index, add, push, diff-index, or ls-tree. Any guard failure or
# unparseable guard result counts as RISK PRESENT, never as risk absent.
#
# INDEX: every index operation targets $KC_IDX. The real $REPO/.git/index is
# never read for staging and never written - including by update-index.
#
# Soft-fail throughout - zero `exit` statements by contract.
KC_STATUS="no-changes"
KC_LIST=""          # comma-joined staged paths, for the commit subject
KC_JSON_STAGED=""   # files_staged (staging time)
KC_JSON_FILES=""    # files_committed (push success ONLY)
KC_JSON_IGN=""      # files_skipped_ignored
KC_SHA=""
KC_DELETED=0
KC_REVERT_RISK="no"
KC_N=0
KC_REVERT_SKIP_COUNT=0
KC_REVERT_SKIP_DELETED=0
KC_RESET_FAILED="no"  # set "yes" if a per-file temp-index reset (after a
                      # revert-risk skip) cannot be verified safe; see the
                      # fail-closed check before write-tree below.

KC_ENABLED=$(python3 -c "
import json
try:
  cfg = json.load(open('$REPO/.agentic/config.json'))
  print('true' if cfg.get('knowledge_commit_on_pr', True) else 'false')
except Exception: print('true')
" 2>/dev/null || echo 'true')

# Re-read here, NOT inherited: Phase 11e is a separate Bash invocation.
KC_AUTOMERGE=$(python3 -c "
import json
try:
  cfg = json.load(open('$REPO/.agentic/config.json'))
  print('true' if cfg.get('auto_merge_on_ci_green', False) else 'false')
except Exception: print('false')
" 2>/dev/null || echo 'false')

# A single multi-line string, never a bash array - see the Portability comment
# above (zsh does not word-split unquoted expansions, so no list is ever built
# by splitting a variable).
KC_EXCLUDE_LIST=$(python3 -c "
import json
try:
  cfg = json.load(open('$REPO/.agentic/config.json'))
  exc = cfg.get('knowledge_commit_exclude', [])
  if isinstance(exc, list):
    print('\n'.join(str(x) for x in exc))
except Exception: pass
" 2>/dev/null || true)

if [ "$KC_ENABLED" != "true" ]; then
  KC_STATUS="disabled"
  echo "[phase: knowledge-commit | status=disabled | knowledge_commit_on_pr=false]"
else
  # Fetch failure and ref-absence are SEPARATE conditions: a transient network
  # failure must not be reported as "branch not found" when the ref exists
  # locally and the push would have worked.
  KC_FETCH_ERR=$(git -C "$REPO" fetch origin "$BRANCH_NAME" 2>&1 >/dev/null)
  if [ $? -ne 0 ]; then
    echo "WARNING: [phase: knowledge-commit] git fetch origin $BRANCH_NAME failed: $KC_FETCH_ERR - continuing against the local remote-tracking ref, which may be stale."
  fi

  if ! git -C "$REPO" rev-parse --verify -q "origin/$BRANCH_NAME" >/dev/null 2>&1; then
    # DISTINCT from "no-changes": the WARNING below goes to stdout, which is not
    # durable. Left at the "no-changes" initializer, events.jsonl could not tell
    # "there was no PR branch to commit onto" from "nothing changed" - and that
    # exact ambiguity is what let this phase's deleted predecessor ship zero
    # commits for its entire lifetime without anyone noticing.
    KC_STATUS="no-branch"
    echo "WARNING: [phase: knowledge-commit] origin/$BRANCH_NAME does not resolve - no PR branch to commit onto; /ds-wrap Part G remains the fallback."
  else
    KC_GITDIR=$(git -C "$REPO" rev-parse --absolute-git-dir)
    KC_IDX="$KC_GITDIR/knowledge-commit-index-$$"
    KC_READ_ERR=$(GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" read-tree "origin/$BRANCH_NAME" 2>&1 >/dev/null)
    if [ $? -ne 0 ]; then
      echo "WARNING: [phase: knowledge-commit] read-tree origin/$BRANCH_NAME failed: $KC_READ_ERR"
      KC_STATUS="commit-failed"
    else
      # Single LITERAL-list loop: gate and stage in one pass (zsh-safe).
      for KC_F in MEMORY.md decisions.md .agentic/learnings.md AGENTS.md .agentic/tracking.md; do
        if [ -f "$REPO/$KC_F" ]; then
          if [ -n "$KC_EXCLUDE_LIST" ] && printf '%s\n' "$KC_EXCLUDE_LIST" | grep -Fxq "$KC_F"; then
            echo "[phase: knowledge-commit] $KC_F is excluded via knowledge_commit_exclude - not committed."
            if [ -z "$KC_JSON_IGN" ]; then KC_JSON_IGN="\"$KC_F\""; else KC_JSON_IGN="$KC_JSON_IGN,\"$KC_F\""; fi
            continue
          fi
          # Point-of-use defeated-negation check, BEFORE the ordinary
          # check-ignore gate below. Exit 1 means a negation in the live
          # .gitignore appears to target $KC_F but git still reports it
          # ignored - a DEFEATED negation, distinct from a legitimate
          # categorical exclusion with no negation attempted at all (e.g.
          # DinoStack's own repo, which the ordinary gate below already
          # handles as an intentional, audible skip). See
          # bin/ds-migrate's cmd_verify_commit_path docstring. Never
          # redirect this check's own stdout/stderr to /dev/null.
          KC_DEFEAT_OUT=$(ds-migrate verify-commit-path "$KC_F" --project-root "$REPO" 2>&1)
          KC_DEFEAT_RC=$?
          if [ "$KC_DEFEAT_RC" -eq 1 ]; then
            echo "ERROR: [phase: knowledge-commit] $KC_F has a negation in .gitignore that appears to target it, but git still reports it ignored (DEFEATED NEGATION) - not committed. Fix .gitignore by hand, then re-run \`ds-migrate apply\`. Detail: $KC_DEFEAT_OUT"
            if [ -z "$KC_JSON_IGN" ]; then KC_JSON_IGN="\"$KC_F\""; else KC_JSON_IGN="$KC_JSON_IGN,\"$KC_F\""; fi
          elif git -C "$REPO" check-ignore -q -- "$KC_F"; then
            KC_RULE=$(git -C "$REPO" check-ignore -v -- "$KC_F")
            echo "[phase: knowledge-commit] $KC_F is gitignored (rule: $KC_RULE) - not committed."
            if [ -z "$KC_JSON_IGN" ]; then KC_JSON_IGN="\"$KC_F\""; else KC_JSON_IGN="$KC_JSON_IGN,\"$KC_F\""; fi
          else
            KC_SKIP_THIS="no"
            if git -C "$REPO" cat-file -e "origin/${BRANCH_NAME}:${KC_F}" 2>/dev/null; then
              # Refresh the TEMP index for this path before comparing. Without
              # this, diff-index trusts stat data over content and a
              # byte-identical file with a newer mtime is misclassified as
              # changed. A non-zero exit here means "needs update" and is
              # expected; stderr is left visible on purpose.
              GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" update-index -q --refresh -- "$KC_F" >/dev/null || true
              if GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" diff-index --quiet "origin/$BRANCH_NAME" -- "$KC_F"; then
                KC_SKIP_THIS="yes"
              fi
            fi
            if [ "$KC_SKIP_THIS" = "no" ]; then
              # Per-file revert guard, run BEFORE staging (C1: unstaging an
              # already-read-tree'd full-tip index with `git rm --cached`
              # DELETES the path from the eventual commit rather than
              # reverting it - so this check must never run after `git add`).
              # Runs UNCONDITIONALLY, regardless of auto_merge_on_ci_green:
              # under the shipped default (false) a candidate whose copy
              # deletes lines relative to the branch tip is still skipped -
              # the risk this guards against (an engineer's newer file on the
              # branch getting silently overwritten by the conductor's stale
              # local copy) is present on every green PR, not only the
              # auto-merge path. This is ADDITIVE to the aggregate diff-index
              # guard below (the "--- Revert guard: ONE diff-index run
              # against the TEMP index ---" comment block), NOT a replacement
              # for it (C2): the aggregate guard's own two fail-closed
              # branches (an unevaluable diff-index, or a non-numeric awk
              # result) cover a batch-level failure this per-file,
              # working-tree-only check cannot see. The aggregate guard's own
              # skip-on-revert-risk branch (its `KC_STATUS="revert-risk-skipped"`
              # assignment, gated on `[ "$KC_REVERT_RISK" = "yes" ] && [
              # "$KC_AUTOMERGE" = "true" ]`) remains gated on
              # auto_merge_on_ci_green, since a green-but-not-auto-merging PR
              # still gets human review before merge - the per-file gate
              # above is the one that had no reviewer standing between a
              # stale write and a merge. (Cited by anchor text, not line
              # number - a line-number citation here has gone stale twice
              # already across separate rounds.)
              # GIT_INDEX_FILE is set here for consistency with this block's
              # own invariant ("The real $REPO/.git/index is never read for
              # staging and never written"). It is REQUIRED in general: a
              # bare `git diff HEAD -- <path>`, a plain `git status`, or an
              # argument-less `git diff` DOES rewrite $REPO/.git/index via
              # diff.autoRefreshIndex whenever the real index's entry for a
              # path is content-identical to the working file but stat-dirty
              # (measured, git 2.55.0) - this is exactly the kind of write
              # the block's invariant forbids, and dropping GIT_INDEX_FILE
              # anywhere else in this block reproduces it (see
              # test_real_index_is_never_read_or_written). For THIS
              # particular call the hazard is provably unreachable rather
              # than merely unobserved: this line only runs once $KC_SKIP_THIS
              # is "no", which the check above it already established by
              # finding that $KC_F's WORKING-TREE content differs from
              # origin/$BRANCH_NAME's blob at this path (or that the path is
              # absent from the tip). diff.autoRefreshIndex only rewrites an
              # entry when refresh CONFIRMS the working file is unchanged
              # relative to what is being diffed against - which this call's
              # own precondition rules out for the treeish it actually uses
              # (origin/$BRANCH_NAME, never HEAD or any tree that matches the
              # real index at this path). Confirmed empirically across five
              # independent fixture shapes, including one built specifically
              # to force the raciness (DS-170 round 3;
              # test_per_file_numstat_leaves_real_index_untouched_under_forced_raciness).
              # Keeping the assignment costs nothing and holds the line
              # uniform with every other index operation in this block.
              KC_F_NUMSTAT_ERR=$(GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" diff --numstat "origin/$BRANCH_NAME" -- "$KC_F" 2>&1 >"$KC_IDX.f-numstat")
              if [ $? -ne 0 ]; then
                echo "WARNING: [phase: knowledge-commit] diff --numstat failed for $KC_F: $KC_F_NUMSTAT_ERR - treating this file as REVERT RISK PRESENT (fail-closed)."
                KC_F_DELETED=-1
              else
                KC_F_DELETED=$(awk -v idx=2 '{s += $(idx)} END {print s+0}' "$KC_IDX.f-numstat")
              fi
              # No `''|*[!0-9]*` arm mirroring the aggregate block's guard is
              # needed for CORRECTNESS: $((0+"")) and $((0+abc)) both yield 0
              # under bash 3.2 and zsh, and any garbage value still fails
              # closed through the `!= "0"` test below (verified). Accepted
              # residual: a garbage per-file result folded into
              # KC_REVERT_SKIP_DELETED can make the deleted_lines telemetry
              # read 0 while the file is still correctly skipped.
              if [ "$KC_F_DELETED" != "0" ]; then
                echo "WARNING: [phase: knowledge-commit] $KC_F has $KC_F_DELETED deleted line(s) vs origin/$BRANCH_NAME - skipping THIS FILE ONLY (revert risk: this candidate's copy would delete content the branch tip already has)."
                if [ -z "$KC_JSON_IGN" ]; then KC_JSON_IGN="\"$KC_F\""; else KC_JSON_IGN="$KC_JSON_IGN,\"$KC_F\""; fi
                KC_SKIP_THIS="yes"
                # Undo the stat-refresh above: `git update-index -q --refresh`
                # silently restages a genuinely-differing path's WORKING-TREE
                # content into the temp index (measured, not documented -
                # `-q` makes it "continue anyway" rather than merely suppress
                # the "needs update" message), so by this point $KC_IDX may
                # already carry this file's local content even though it is
                # about to be skipped. Reset the temp index entry back to the
                # origin tip's exact blob/mode so a file skipped here is
                # PROVABLY untouched in $KC_IDX, not staged-then-never-added.
                #
                # DIAGNOSTIC / FAIL-CLOSED, same contract as the rest of this
                # block: no `2>/dev/null` on ls-tree, and a failed
                # update-index reset is never swallowed with `|| true`. If
                # either step cannot be verified to have restored the tip's
                # exact blob, $KC_IDX may still carry this file's stale
                # working-tree content even though it is reported as
                # SKIPPED - the round-1 Critical recurring silently. Treat
                # that as RISK PRESENT for the WHOLE run: KC_RESET_FAILED
                # forces the write-tree/commit-tree/push sequence below to be
                # skipped entirely, so a corrupted temp index is discarded
                # (by the unconditional `rm -f "$KC_IDX"` at the end of this
                # block) rather than ever written or pushed.
                KC_TIP_ENTRY=$(git -C "$REPO" ls-tree "origin/$BRANCH_NAME" -- "$KC_F")
                KC_LSTREE_RC=$?
                if [ "$KC_LSTREE_RC" -ne 0 ] || [ -z "$KC_TIP_ENTRY" ]; then
                  echo "WARNING: [phase: knowledge-commit] ls-tree origin/$BRANCH_NAME -- $KC_F failed while resetting the temp index after a revert-risk skip - the temp index entry for $KC_F cannot be verified safe. Abandoning this knowledge-commit run rather than risk shipping stale content (fail-closed)."
                  KC_RESET_FAILED="yes"
                else
                  KC_TIP_MODE=$(printf '%s' "$KC_TIP_ENTRY" | awk -v idx=1 '{print $(idx)}')
                  KC_TIP_SHA=$(printf '%s' "$KC_TIP_ENTRY" | awk -v idx=3 '{print $(idx)}')
                  KC_CACHEINFO_ERR=$(GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" update-index --add --cacheinfo "$KC_TIP_MODE,$KC_TIP_SHA,$KC_F" 2>&1 >/dev/null)
                  if [ $? -ne 0 ]; then
                    echo "WARNING: [phase: knowledge-commit] update-index --add --cacheinfo failed while resetting $KC_F's temp index entry after a revert-risk skip: $KC_CACHEINFO_ERR - the temp index entry for $KC_F cannot be verified safe. Abandoning this knowledge-commit run rather than risk shipping stale content (fail-closed)."
                    KC_RESET_FAILED="yes"
                  fi
                fi
                # Track the all-candidates-skipped case so a KC_N == 0 run
                # still reports revert-risk-skipped with the
                # correct deleted_lines rather than falling through to
                # no-changes/deleted_lines:0. The -1 fail-closed sentinel
                # dominates the running total, as it does in the aggregate
                # block below.
                KC_REVERT_SKIP_COUNT=$((KC_REVERT_SKIP_COUNT + 1))
                if [ "$KC_F_DELETED" = "-1" ] || [ "$KC_REVERT_SKIP_DELETED" = "-1" ]; then
                  KC_REVERT_SKIP_DELETED=-1
                else
                  KC_REVERT_SKIP_DELETED=$((KC_REVERT_SKIP_DELETED + KC_F_DELETED))
                fi
              fi
            fi
            if [ "$KC_SKIP_THIS" = "no" ]; then
              KC_ADD_ERR=$(GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" add -- "$KC_F" 2>&1 >/dev/null)
              if [ $? -ne 0 ]; then
                echo "WARNING: [phase: knowledge-commit] git add $KC_F failed: $KC_ADD_ERR - this file is not included."
              else
                KC_N=$((KC_N + 1))
                if [ -z "$KC_LIST" ]; then KC_LIST="$KC_F"; else KC_LIST="$KC_LIST,$KC_F"; fi
                if [ -z "$KC_JSON_STAGED" ]; then KC_JSON_STAGED="\"$KC_F\""; else KC_JSON_STAGED="$KC_JSON_STAGED,\"$KC_F\""; fi
              fi
            fi
          fi
        fi
      done
      # Two-tier: ship new shards with MEMORY.md.
      case ",$KC_LIST," in *,MEMORY.md,*)
        KC_NEW=$(ds-memory-capture new-shards --dir "$REPO" --ref "origin/${BRANCH_NAME}" || true)
        while IFS= read -r KC_S; do
          [ -n "$KC_S" ] || continue
          KC_ADD_ERR=$(GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" add -- "$KC_S" 2>&1 >/dev/null)
          if [ $? -ne 0 ]; then echo "WARNING: [phase: knowledge-commit] git add $KC_S failed: $KC_ADD_ERR"; continue; fi
          KC_N=$((KC_N + 1)); KC_LIST="$KC_LIST,$KC_S"; KC_JSON_STAGED="$KC_JSON_STAGED,\"$KC_S\""
        done <<< "$KC_NEW"
      esac

      if [ "$KC_RESET_FAILED" = "yes" ]; then
        # Checked BEFORE the KC_N == 0 branch below, deliberately: KC_N == 0
        # and KC_RESET_FAILED == "yes" can both be true at once (every
        # candidate carried revert risk AND at least one of those per-file
        # resets could not be verified restored) - the fail-closed integrity
        # concern here is strictly worse than "nothing was staged" and must
        # dominate regardless of KC_N, or that combination would report
        # revert-risk-skipped and hide that $KC_IDX may still carry stale
        # content that was never verified safe (telemetry-only either way,
        # since KC_N == 0 means nothing gets written/pushed in this run, but
        # the reported status must still name the more severe condition).
        #
        # Fail-closed per the per-file reset block above: at least one
        # revert-risk-skipped file's temp-index entry could not be verified
        # restored to the tip's exact blob, so $KC_IDX may still carry stale
        # working-tree content for it. Abandon the WHOLE commit rather than
        # write-tree/commit-tree/push a temp index that cannot be trusted.
        echo "WARNING: [phase: knowledge-commit] a per-file temp-index reset could not be verified safe earlier in this run - abandoning the knowledge commit entirely rather than risk shipping stale content from a corrupted temp index (fail-closed)."
        KC_STATUS="commit-failed"
      elif [ "$KC_N" -eq 0 ]; then
        if [ "$KC_REVERT_SKIP_COUNT" -gt 0 ]; then
          echo "WARNING: [phase: knowledge-commit] no candidate could be staged - $KC_REVERT_SKIP_COUNT file(s) carried revert risk (deleted_lines=$KC_REVERT_SKIP_DELETED) - skipping. Run /ds-wrap so Part G ships this content on a reviewable branch."
          KC_STATUS="revert-risk-skipped"
          KC_DELETED=$KC_REVERT_SKIP_DELETED
        else
          echo "[phase: knowledge-commit | status=no-changes | branch=$BRANCH_NAME]"
        fi
      else
        # --- Revert guard: ONE diff-index run against the TEMP index. Stdout to
        #     a file (reused for the per-file warning), stderr to a variable.
        #     FAILS CLOSED. This is the aggregate, batch-level backstop; the
        #     per-file, pre-staging guard above now runs unconditionally for
        #     every candidate, so this aggregate check typically has nothing
        #     left to catch for content reasons - it remains the ONLY path
        #     that fires when the guard itself cannot be evaluated (an
        #     unevaluable diff-index, or a non-numeric awk result), which the
        #     per-file check structurally cannot see. Its own skip-on-risk
        #     branch below stays gated on auto_merge_on_ci_green: under the
        #     default (false), a green PR still gets a human reading the diff
        #     before merge, so an unevaluable-guard WARNING here is
        #     sufficient - the human is the backstop this branch's own skip
        #     is for under auto-merge, where no human reads the diff. ---
        KC_NUMSTAT_ERR=$(GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" diff-index --cached --numstat "origin/$BRANCH_NAME" 2>&1 >"$KC_IDX.numstat")
        if [ $? -ne 0 ]; then
          echo "WARNING: [phase: knowledge-commit] diff-index failed: $KC_NUMSTAT_ERR - treating as REVERT RISK PRESENT (fail-closed; the guard cannot be verified)."
          KC_REVERT_RISK="yes"
          KC_DELETED=-1
        else
          # awk emits 0 (not empty) for an empty input file under bash, zsh, and
          # sh, so the '' arm below is reachable only if awk itself fails to run
          # or the numstat file is unreadable. Keep it for exactly that case.
          KC_DELETED=$(awk -v idx=2 '{s += $(idx)} END {print s+0}' "$KC_IDX.numstat")
          case "$KC_DELETED" in
            ''|*[!0-9]*)
              echo "WARNING: [phase: knowledge-commit] deleted-line count is empty or non-numeric ('$KC_DELETED') - awk did not run or its output is unusable; treating as REVERT RISK PRESENT (fail-closed)."
              KC_REVERT_RISK="yes"
              KC_DELETED=-1
              ;;
            0) : ;;
            *)
              KC_REVERT_RISK="yes"
              awk -v kc_branch="$BRANCH_NAME" -v idx2=2 -v idx3=3 '$(idx2) > 0 {printf "WARNING: [phase: knowledge-commit] %s has %s deleted line(s) vs origin/%s - this commit may revert content another session already merged. Review the PR diff before merging.\n", $(idx3), $(idx2), kc_branch}' "$KC_IDX.numstat"
              ;;
          esac
        fi

        KC_NAME=$(git -C "$REPO" config user.name 2>/dev/null || true)
        KC_EMAIL=$(git -C "$REPO" config user.email 2>/dev/null || true)

        if [ "$KC_REVERT_RISK" = "yes" ] && [ "$KC_AUTOMERGE" = "true" ]; then
          echo "WARNING: [phase: knowledge-commit] auto_merge_on_ci_green is true and this commit carries revert risk (deleted_lines=$KC_DELETED) - skipping. No human would read the PR diff before merge. Run /ds-wrap so Part G ships this content on a reviewable branch."
          KC_STATUS="revert-risk-skipped"
        elif [ -z "$KC_NAME" ] || [ -z "$KC_EMAIL" ]; then
          echo "WARNING: [phase: knowledge-commit] git user.name/user.email not configured - skipping knowledge commit to avoid a malformed DCO trailer."
          KC_STATUS="failed"
        else
          KC_TREE=$(GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" write-tree 2>/dev/null || true)
          KC_BASE_TREE=$(git -C "$REPO" rev-parse "origin/$BRANCH_NAME^{tree}" 2>/dev/null || true)
          if [ -z "$KC_TREE" ]; then
            echo "WARNING: [phase: knowledge-commit] write-tree failed - skipping knowledge commit."
            KC_STATUS="commit-failed"
          elif [ "$KC_TREE" = "$KC_BASE_TREE" ]; then
            echo "[phase: knowledge-commit | status=no-changes | tree-identical]"
          else
            KC_MSG=$(printf 'chore(knowledge): capture %s from ticket session\n\nSigned-off-by: %s <%s>' "$KC_LIST" "$KC_NAME" "$KC_EMAIL")
            KC_SHA=$(git -C "$REPO" commit-tree "$KC_TREE" -p "origin/$BRANCH_NAME" -m "$KC_MSG" 2>/dev/null || true)
            if [ -z "$KC_SHA" ]; then
              echo "WARNING: [phase: knowledge-commit] commit-tree failed - skipping knowledge commit."
              KC_STATUS="commit-failed"
            else
              KC_QUEUE=$(gh pr view "$BRANCH_NAME" --repo "$GH_REPO" --json autoMergeRequest 2>/dev/null)
              KC_CAN_PUSH=false
              if printf '%s' "$KC_QUEUE" | jq -e 'has("autoMergeRequest")' >/dev/null 2>&1; then
                if [ "$(printf '%s' "$KC_QUEUE" | jq -r '.autoMergeRequest == null')" = "true" ] || gh pr merge "$BRANCH_NAME" --repo "$GH_REPO" --disable-auto; then
                  KC_CAN_PUSH=true
                fi
              fi
              KC_PUSH_OK=false
              if [ "$KC_CAN_PUSH" = "true" ]; then
                KC_PUSH_ERR=$(git -C "$REPO" push origin "${KC_SHA}:refs/heads/${BRANCH_NAME}" 2>&1 >/dev/null) && KC_PUSH_OK=true
              else
                KC_PUSH_ERR="queue observation/suspension failed; head unchanged"
              fi
              if [ "$KC_PUSH_OK" = "true" ]; then
                KC_STATUS="committed"
                # files_committed is populated HERE and ONLY here.
                KC_JSON_FILES="$KC_JSON_STAGED"
                mkdir -p "$REPO/.agentic" 2>/dev/null || true
                printf '{"branch":"%s","commit":"%s","files":[%s],"deleted_lines":%s,"ts":"%s"}\n' \
                  "$BRANCH_NAME" "$KC_SHA" "$KC_JSON_FILES" "$KC_DELETED" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                  > "$REPO/.agentic/knowledge-commit-state.json.tmp" 2>/dev/null &&
                  mv "$REPO/.agentic/knowledge-commit-state.json.tmp" "$REPO/.agentic/knowledge-commit-state.json" 2>/dev/null || true
                echo "[phase: knowledge-commit | status=committed | branch=$BRANCH_NAME | commit=$KC_SHA | files=$KC_LIST]"
                echo "NOTE: [phase: knowledge-commit] CI is re-running against this new tip. Phase 10a cannot re-fire, so a red result on this commit needs manual attention."
              else
                echo "WARNING: [phase: knowledge-commit] push to $BRANCH_NAME rejected: $KC_PUSH_ERR - knowledge not shipped on this PR; /ds-wrap Part G remains the fallback."
                KC_STATUS="push-failed"
              fi
            fi
          fi
        fi
      fi
    fi
    rm -f "$KC_IDX" "$KC_IDX.numstat" "$KC_IDX.f-numstat" 2>/dev/null || true
  fi
fi

ds-emit knowledge_commit - "${TICKET_ID:--}" "{\"site\":\"phase-11e\",\"status\":\"$KC_STATUS\",\"files_staged\":[$KC_JSON_STAGED],\"files_committed\":[$KC_JSON_FILES],\"files_skipped_ignored\":[$KC_JSON_IGN],\"branch\":\"$BRANCH_NAME\",\"commit\":\"$KC_SHA\",\"deleted_lines\":$KC_DELETED}" 2>/dev/null || true
```

`GIT_INDEX_FILE="$KC_IDX" git ...` is a **per-command assignment, not an export**, in both bash and zsh - the value is scoped to that one invocation and cannot reach `$REPO/.git/index`. Do not convert it to an `export ... ; unset ...` pair, and do not remove it from the `update-index` call.

**CI interaction.** With `auto_merge_on_ci_green: false` (the default) there is no interaction to reason about: the PR stays open, CI re-runs against the new tip, and the human merges when it is green. With `auto_merge_on_ci_green: true`, Phase 12 re-derives the knowledge-commit condition from `gh` and queues GitHub's own auto-merge, which completes only once the checks are green.

**Delivery refresh (binding).** After this block, collect/publish the new remote-head record per `content/references/delivery-record.md`, retaining original review/QA evidence SHAs with pending coverage until assessed. Leave any suspended queue off until applicable checks are resolved and a guarded request succeeds.

**CI after the late push.** Phase 10a does not re-fire. Final delivery collection observes current CI before any merge/new queue; unresolved results remain owned. GitHub's required checks govern an accepted queue. There is no background monitor for later failures; report the current state rather than promise a future merge. `knowledge_commit_on_pr: false` still disables this phase.

**Per-unit attribution is out of reach and is not attempted.** Fan-out unit branches are merged and `git branch -d`'d at the Phase 5/6 boundary, before Phase 6 fires; `findings_log` entries carry no unit tag; and neither `wrap-ticket` nor `learning-extractor` accepts a unit identifier. What Phase 11e delivers is therefore per-**ticket** attribution. The minimal change that would make per-unit attribution possible - propagate the orchestration planner's per-unit slug into each per-unit Skeptic `findings_log` entry as a `unit` field, and add a `unit` key to `learning-extractor`'s LRN schema - is recorded here as a separate ticket's scope, not built as part of this phase.
