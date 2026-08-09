<!--
Purpose: Full reference for the two conditional QA phases of
         `/ds-implement-ticket` and their loop-state bookkeeping - Phase 6b
         (the QA Gate: trigger conditions, the `qa_skip` enum, the QA loop
         contract's per-iteration Step 1-5 sequence and loop-state schema,
         screenshot evidence capture, and the QA regressions curator) and
         Phase 8.5 (QA evidence: committing PASS screenshots to the
         `qa-evidence` orphan branch and building click-through evidence
         URLs for the PR body). `content/references/qa-gate.md` documents
         the GENERAL QA-gate procedure (trigger rationale, the concurrent
         vs. sequential QA spec, INCONCLUSIVE classification, per-ticket
         in-flow discipline); this file is THIS COMMAND's loop-state
         bookkeeping around that procedure - the two are complementary, not
         duplicative.

Public API: Read-only reference document, addressed by its two retained
            headings `## Phase 6b: QA Gate (conditional)` and `## Phase
            8.5: QA evidence (conditional)`. Cross-referenced from
            content/commands/ds-implement-ticket.md at both extraction
            sites (pointer paragraphs).

Upstream deps: none (prose reference only; no code, no runtime execution).
               Assumes the reader already has `content/references/qa-gate.md`
               (the general QA-gate procedure), the "Batch-mode escalation
               routing (mark-blocked-and-continue)" subsection (Phase 6 in
               content/commands/ds-implement-ticket.md), and
               `content/references/qa-regression-obligation.md` in context -
               all three are named, not repeated, here.

Downstream consumers: content/commands/ds-implement-ticket.md (both
                      extraction site pointers: Phase 6b and Phase 8.5).
                      The kernel Phase 6b section retains the `site: W3`
                      tracker-writeback structured tag and its firing
                      condition in place (see the Phase 6b heading in
                      content/commands/ds-implement-ticket.md); this file's
                      "Loop entry" subsection points back to that kernel
                      location rather than duplicating the tag, so the tag
                      has exactly one source of truth.

Failure modes: Prose reference; does not auto-execute. A stale copy would
               misdescribe the QA loop's termination conditions, the
               `QA_STATUS` verdict contract, or the qa-evidence branch's
               push/retry mechanics - keep in sync with the live Phase 6b
               and Phase 8.5 call sites whenever either changes.

Performance: n/a (static reference document).
-->

## Phase 6b: QA Gate (conditional)

**Dry-run skip (open-goal only).** If `batch-state.json.open_goal.active == true` AND `batch-state.json.open_goal.dry_run == true`: skip Phase 6b entirely - no qa-engineer spawn, no dev-server boot. Proceed directly to Phase 12. Never fires for ordinary invocations (no `open_goal.dry_run` field to read).

**Phase 6b only runs if Phase 6 exits cleanly (Skeptic sign-off granted, `termination_reason: clean`).** If Phase 6 exits via `cap_reached`, `convergence_failure`, or `blocked` escalation, Phase 6b is skipped entirely. Running QA on a Skeptic-rejected implementation is wasteful - the Phase 6 escalation subsumes Phase 6b for that session.

**Cap independence:** Phase 6 and Phase 6b caps are independent - exhausting the Phase 6 Skeptic cap (3 fix passes) does not consume Phase 6b QA cap budget, and vice versa. Each phase gets its own 3-fix-pass budget evaluated separately.

**Trigger:** Phase 6b QA fires for Elevated units IFF all of the following hold:
1. The unit's `qa_criteria` block (from the Brief, or from the architect plan if no Brief) is present.
2. `qa_criteria.qa_skip == null`.
3. `qa_criteria.scenarios[]` is non-empty.
4. Phase 6 `termination_reason == clean`.

The Trivial path never enters Phase 6b (Trivial units bypass the entire Skeptic/QA loop per METHODOLOGY.md §Risk Classification).

**Invalid `qa_skip` enum normalization (at Phase 6b entry).** If `qa_criteria.qa_skip` is non-null and not in the 5-valid-enum set (`pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only`), normalize to null and emit the operator warning verbatim:

```
WARNING: qa_skip value '<X>' is not a valid enum (one of: pure-backend-library, config-only, type-only-refactor, dep-bump-no-runtime-change, docs-only). Treating as null; QA will fire.
```

After normalization, re-evaluate the trigger conditions (with `qa_skip` now null, QA fires if scenarios are present).

**qa.md is supplemental, not gating.** Whether `.agentic/qa.md` (or legacy `.claude/qa.md`) exists, has a `## QA triggers` section, or matches the diff is NOT part of the trigger decision. qa-engineer auto-detects qa.md trigger matches at spawn time and pulls supplemental project knowledge (dev server config, project quirks, matched trigger patterns) into its context, but the gate decision is owned by the architect's `qa_criteria`. qa.md triggers can SUPPLEMENT but CANNOT override `qa_skip != null`.

**Phase 6b is per-ticket and in-flow.** Phase 6b runs inside this ticket's loop, before Phase 7. The conductor MUST NOT defer Phase 6b to a final batch-end QA sweep across multiple tickets. If runtime QA cannot run for this ticket at the moment of its Phase 6b - dev server fails to boot, env file missing, preview deploy is blocked, no working URL - that is a blocker for THIS ticket, surfaced as `qa_blocked` with the operator's three options (provide the missing input, accept INCONCLUSIVE with `qa_unverified=true`, or abandon the ticket). See `content/references/qa-gate.md` §"Per-ticket, in-flow" for the anti-pattern and `content/references/qa-gate.md` §"INCONCLUSIVE classification" for the no-static-only-auto-pass rule.

**Conductor preflight before any qa-engineer spawn.** Before spawning qa-engineer for this unit, verify the project env file exists at the path the dev server will load (resolved from qa.md `env_file:` + `env_pull_command:` fields, or from project config such as a `package.json` `env:pull:<app>` script). If the env file is missing, do NOT spawn qa-engineer - surface the verbatim message defined in `content/references/qa-gate.md` §"Conductor preflight before any qa-engineer spawn" with the resolved `<env_pull_command>` and wait for the operator. Spawning qa-engineer just to discover the env is missing wastes a worker turn.

**Multi-PR / multi-ticket parallel-by-worktree.** When more than one PR or unit is awaiting QA, default to spawning one qa-engineer per worktree in parallel (single message, background, each on a unique port `PORT=$((3000 + N))`). See `content/references/qa-gate.md` §"Multi-PR / multi-ticket parallel-by-worktree".

- **If trigger conditions hold (QA fires) - UI-visible changes (concurrent path):** when the unit's diff is UI-visible, `qa-engineer` was already spawned IN PARALLEL with the Skeptic during Phase 6 (single message, both background). If QA passed concurrently, Phase 6b is already satisfied - skip to Phase 7. If QA failed concurrently or was deferred, proceed with the QA loop contract below. See `content/references/qa-gate.md` §"QA gate flow (UI-visible - concurrent)" for the full concurrent QA spec.
- **If trigger conditions hold (QA fires) - non-UI changes (sequential path):** proceed with the QA loop contract below.
- **If trigger conditions do not hold (QA skipped):** record the skip rationale (`qa_skip` value or "Trivial path") in the conductor's status update and proceed directly to Phase 7. Also set `QA_STATUS="skipped:<rationale>"` using that same rationale (in-context variable consumed by the Phase 9 ticket-rework ledger write). Writing the rationale rather than leaving it empty is what lets the rework notice distinguish "QA was deliberately skipped, here is why" from "QA status unavailable".

For full QA gate rules, see `METHODOLOGY.md §QA Gate`.

**QA loop contract:**

Before the loop starts, initialize loop state and write it to `.agentic/loop-state-$LOOP_KEY.json` (overwriting the Phase 6 state). **Use atomic write (tmp+rename).** Reset `last_phase=qa`, `last_phase_action=spawned`. Same write-trigger pattern as Phase 6 applies here: write at every phase transition (QA spawn, QA return, Engineer spawn, Engineer return). On clean exit set `status=complete`; on stalled exit set `status=stalled`.

```
LOOP_STATE initialized:
  phase: qa
  iteration: 1
  max_iterations: 3
  qa_failures_log: []
  last_engineer_summary: null
  termination_reason: null
```

Write as JSON to `.agentic/loop-state-$LOOP_KEY.json` (same stability contract as Phase 6 - see above).

Emit the inline breadcrumb:

```
[loop: qa | iteration 1/3 | open failures: -]
```

**Loop entry (repeat until termination):**

**Tracker writeback (W3)** fires on iteration 1 only, at this Step 1's first `qa-engineer` spawn. See `content/commands/ds-implement-ticket.md` §"Phase 6b: QA Gate (conditional)" for the fire condition and the `[phase: tracker-writeback | site: W3 | ...]` structured tag emitted there - kept in the kernel command file rather than duplicated here so the tag has one source of truth.

**Step 1.** Spawn `qa-engineer` with ticket context, the diff, the unit's `qa_criteria` block (required input - the authoritative test plan), the `ticket_id` (for knowledge attribution), and the resolved qa.md config as supplemental context (`.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback). The Agent tool call MUST set `isolation: "worktree"` (mandatory per METHODOLOGY.md §Delegation > Worker preamble). On iteration 2+, prepend the "Prior QA failures" section to the brief:

**Telemetry emit (V1):** Bracket the QA `Agent` tool call with `ds-emit spawn_start qa-engineer <task_id> ...` before and `ds-emit spawn_complete qa-engineer <task_id> ...` after. Same pattern as Phase 6 emits.

```
## Prior QA failures

The following failures were identified and fix attempts were made in earlier iterations. For each:
- If the acceptance criterion now passes: mark it CLOSED with a one-line confirmation.
- If the criterion still fails: re-raise it using [PREV: <id>] prefix in the failure description.
- Do not re-raise failures that are confirmed fixed.

[paste qa_failures_log entries with status=open or status=addressed]
```

**Step 2.** Receive QA output. Update `qa_failures_log`:
- Each failure gets a short slug `id`, `description`, `first_raised: <iteration>`, `status: open`.
- If a failure carries `[PREV: <id>]`, set `re_raised: true` on the matching `qa_failures_log` entry.
- Overwrite `.agentic/loop-state-$LOOP_KEY.json` with the updated LOOP_STATE.
- Run the QA knowledge capture procedure (`content/references/qa-gate.md` §"QA knowledge capture (canonical procedure)") against this iteration's qa-engineer return, regardless of verdict, before proceeding to Step 3.

**Step 3. Termination check:**
- If PASS (all acceptance criteria met): auto-close all `qa_failures_log` entries. Set `termination_reason: clean`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Set `QA_RAN_AND_PASSED="true"` (in-context variable used by Phase 9 QA Evidence section) and `QA_STATUS="PASS"` (in-context variable used by the Phase 9 ticket-rework ledger write). **Parse QA screenshot evidence (see below).** Exit loop cleanly. Proceed to Phase 7.

**`QA_STATUS` on every other terminal QA outcome.** Whenever Phase 6b reaches a terminal verdict for this ticket by any route, set `QA_STATUS` to that verdict - one of `PASS`/`FAIL`/`PARTIAL`/`BLOCKED`/`INCONCLUSIVE`. In particular, when the operator accepts INCONCLUSIVE with `qa_unverified=true` on the `qa_blocked` path and the ticket continues to Phase 9, set `QA_STATUS="INCONCLUSIVE"`. A known verdict must never be discarded to null: the ledger's contract reserves null for the case where *neither* a result *nor* a rationale can be resolved, and "the operator looked at this and accepted that QA could not verify it" is a result. Recording it as `n/a` would tell a later rework attempt that QA status was simply unavailable, hiding an accepted-unverified ticket - the exact class of silent downgrade this field exists to surface.
- If `iteration == max_iterations` AND still failing: set `termination_reason: cap_reached`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection in Phase 6. Escalate to human with the `qa_failures_log`. Phase 7 does NOT run.
- If same failure recurs unchanged after a claimed fix (`re_raised: true`): set `termination_reason: convergence_failure`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection in Phase 6. Escalate to human with convergence note.

**QA screenshot evidence capture (PASS exit only).** On clean PASS exit, parse the `qa-screenshots-json` fenced block from the qa-engineer return text:

```
Look for a fenced block whose info string is exactly `qa-screenshots-json`, regardless of whether
the fence character is backticks (```) or tildes (~~~). Either of the following forms is valid:

  ```qa-screenshots-json
  [{"path": "...", "description": "...", "criterion_id": "...", "result": "..."}]
  ```

  ~~~qa-screenshots-json
  [{"path": "...", "description": "...", "criterion_id": "...", "result": "..."}]
  ~~~

Match by the info string `qa-screenshots-json`; do not require a specific fence character.
```

Parse the JSON array into `QA_SCREENSHOT_PATHS` (array of `{path, description, criterion_id, result}` objects). Retain only entries where `result == "PASS"` on overall PASS. If the block is absent, malformed, or the JSON fails to parse, set `QA_SCREENSHOT_PATHS=()` and continue without error. This is an in-context variable only - do NOT write `QA_SCREENSHOT_PATHS` to `.agentic/loop-state-$LOOP_KEY.json` or any other state file.

**Step 4. Engineer fix pass.** Spawn `engineer` with the QA failure description, prior fix summary, and instruction to fix only the failing acceptance criteria. The fix engineer spawn brief MUST cite `content/references/qa-regression-obligation.md` - the engineer adds a regression test that targets the failing scenario (id, description) or, if a regression test is genuinely infeasible, appends a documented exception entry to `.agentic/qa-regressions.md` using the canonical schema in that reference. A missing test with no explanation and no curated-index entry is a Major Skeptic finding on the QA-fix iteration. **Iter N (N >= 2) surgical-edit directive.** When `iteration >= 2`, the brief MUST include the iter N-1 Engineer output VERBATIM as input - not a summary, not a paraphrase. Paste the prior return summary in full (or the prior diff plus committed-file excerpts when the prior output was code). Then include this instruction verbatim: *"APPLY SURGICAL EDITS to the iter N-1 output above. Do NOT regenerate from scratch. Do NOT change anything not directly tied to a QA failure listed below. Each edit you make must trace to a specific failure id."* Same rationale as Phase 6: a fresh subagent without prior-iteration context regenerates from scratch and diverges from the scoped change; anchoring on the prior output verbatim is the only reliable way to scope a fresh subagent to surgical fixes. Bracket the **Agent call** with `ds-emit spawn_start engineer <task_id> ...` and `ds-emit spawn_complete engineer <task_id> ...` per the Phase 6 emit pattern. Apply the same BLOCKED/NEEDS_CONTEXT handling as Phase 6:
- If `Status: BLOCKED`: set `termination_reason: blocked`. Before escalating, apply the "Batch-mode escalation routing (mark-blocked-and-continue)" subsection in Phase 6. **Tracker writeback (W5):** if `TRACKER != none`, invoke the Tracker Writeback Helper with `target_state: $TRACKER_STATE_BLOCKED`, `forward_only_guard: true`. Fire-and-forget. `[phase: tracker-writeback | site: W5 | target: $TRACKER_STATE_BLOCKED]` Escalate immediately. Do NOT increment `iteration`.
- If `Status: NEEDS_CONTEXT`: re-supply context and re-spawn without incrementing `iteration`. If context cannot be supplied, escalate to human.

**Step 5.** Receive Engineer output. If neither BLOCKED nor NEEDS_CONTEXT (whether `Status: DONE` or `Status: DONE_WITH_CONCERNS`): update `qa_failures_log` entries the Engineer claims to have fixed to `status: addressed`. Update `last_engineer_summary`. Increment `iteration`. Overwrite `.agentic/loop-state-$LOOP_KEY.json`. Update inline breadcrumb. Go to Step 1.

### QA regressions curator (Phase 6b clean exit)

At Phase 6b clean exit, if any iteration of this Phase 6b loop involved a QA FAIL (i.e., `qa_failures_log` was non-empty at any point before the final PASS), spawn a qa-regressions-curator subagent. **Note:** `qa-regressions-curator` does not yet exist as a named agent; use `general-purpose` agent type (Tier 1, fire-and-forget) until the named agent is formally added. Mirrors the Phase 6 findings curator pattern (see "Findings curator (loop exit)" above).

**Brief:**
- Input: the qa-engineer's last FAIL report containing the `## Regression draft (for .agentic/qa-regressions.md)` block (verbatim), any fix-engineer documented-exception block from the QA-fix iteration, the `ticket_id`, and the curated index path (`.agentic/qa-regressions.md`).
- The curator computes the dedupe key `(surface, claim)` from each draft entry: lowercase the `Surface` and `What broke` values, collapse whitespace runs to a single space, strip leading/trailing whitespace, concatenate with a `|` separator.
- Dedupe rule: if a matching `(surface, claim)` key already exists in `.agentic/qa-regressions.md`, skip the write for that entry.
- The curator is the sole writer of `.agentic/qa-regressions.md` (append-only by discipline; the curator is fire-and-forget so the conductor never writes the file).
- Schema reference: `content/references/qa-regression-obligation.md` §`.agentic/qa-regressions.md` schema (canonical).

Fires exactly once per ticket per `/ds-implement-ticket` invocation. Skipped entirely if Phase 6b never recorded a FAIL (clean PASS on iteration 1 with no failures).

## Phase 8.5: QA evidence (conditional)

**Skip conditions (all must be false for phase to run):**
- QA was skipped (`qa_skip != null`) or the ticket is Trivial
- `QA_SCREENSHOT_PATHS` is empty (`()`)
- `gh` or `jq` is unavailable (`which gh jq` fails)

When any skip condition is true, set `QA_EVIDENCE_URLS=()` and proceed directly to Phase 9.

**Goal:** commit PASS screenshots to a long-lived orphan `qa-evidence` branch on GitHub under the deterministic path `<TICKET_SLUG>/<BRANCH_SLUG>/<filename>`, build click-through evidence URLs, and emit them into the PR body. The branch is never merged to main; it is a parallel evidence store.

**Slug derivation:**
- `TICKET_SLUG`: `$TICKET_ID` lowercased, non-alphanum replaced with hyphens (e.g. `eng-123`)
- `BRANCH_SLUG`: `$BRANCH_NAME` with leading `feature/`, `fix/`, `chore/` stripped; remaining slashes replaced with hyphens

**Copy screenshots to a stable temp directory:**

```bash
SCREENSHOTS_SRC="/tmp/qa-evidence-$$"
mkdir -p "$SCREENSHOTS_SRC"
# Copy each path from QA_SCREENSHOT_PATHS into $SCREENSHOTS_SRC
# (QA_SCREENSHOT_PATHS is a bash array; entries are JSON objects from Phase 6b parse)
for entry in "${QA_SCREENSHOT_PATHS[@]}"; do
  SRC_PATH=$(echo "$entry" | jq -r '.path')
  cp "$SRC_PATH" "$SCREENSHOTS_SRC/" 2>/dev/null || true
done
# If nothing copied, treat as skip
[ "$(ls -A "$SCREENSHOTS_SRC")" ] || { QA_EVIDENCE_URLS=(); rm -rf "$SCREENSHOTS_SRC"; proceed to Phase 9; }
```

**Check whether `qa-evidence` branch already exists on remote:**

```bash
REMOTE_EXISTS=$(git -C "$REPO" ls-remote --heads origin qa-evidence | wc -l)
```

**First-create path (branch does not exist on remote):**

Create a scratch clone in `/tmp` to bootstrap the orphan branch. `$SCREENSHOTS_SRC` lives in `/tmp` (outside the clone) so `reset --hard` never destroys the source.

```bash
TEMP_CLONE="/tmp/qa-evidence-clone-$$"
git clone --depth=1 "$REPO" "$TEMP_CLONE"
git -C "$TEMP_CLONE" checkout --orphan qa-evidence
git -C "$TEMP_CLONE" rm -rf . 2>/dev/null || true
mkdir -p "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
cp -r "$SCREENSHOTS_SRC"/. "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
git -C "$TEMP_CLONE" add .
git -C "$TEMP_CLONE" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"

# RACE RECOVERY LOOP: handles concurrent first-creators racing on the orphan root
PUSH_SUCCEEDED_FIRST_CREATE=false
for i in 1 2 3; do
  if git -C "$TEMP_CLONE" push origin qa-evidence; then
    PUSH_SUCCEEDED_FIRST_CREATE=true
    break
  fi
  # push rejected - a concurrent creator won; adopt the landed history
  git -C "$TEMP_CLONE" fetch origin qa-evidence
  git -C "$TEMP_CLONE" reset --hard origin/qa-evidence   # adopts remote history; wipes worktree
  mkdir -p "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"      # recreate dest dir destroyed by reset
  cp -r "$SCREENSHOTS_SRC"/. "$TEMP_CLONE/$TICKET_SLUG/$BRANCH_SLUG/"
  git -C "$TEMP_CLONE" add .
  git -C "$TEMP_CLONE" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"
done

rm -rf "$TEMP_CLONE"
```

After temp-clone push succeeds, fetch the updated remote-tracking ref into the main repo:

```bash
git -C "$REPO" fetch origin qa-evidence
```

**Steady-state path (branch already exists on remote):**

Add a detached-HEAD worktree pointing at `origin/qa-evidence`, copy files, and push using the `HEAD:qa-evidence` refspec (mandatory because the worktree is on a detached HEAD - `push origin qa-evidence` would be a no-op in this state).

```bash
WORKTREE_PATH="$REPO/.agentic/worktrees/qa-evidence-$$"
git -C "$REPO" fetch origin qa-evidence
git -C "$REPO" worktree add "$WORKTREE_PATH" origin/qa-evidence   # detached HEAD

mkdir -p "$WORKTREE_PATH/$TICKET_SLUG/$BRANCH_SLUG/"
cp -r "$SCREENSHOTS_SRC"/. "$WORKTREE_PATH/$TICKET_SLUG/$BRANCH_SLUG/"
git -C "$WORKTREE_PATH" add .
git -C "$WORKTREE_PATH" commit -m "qa: ${TICKET_SLUG}/${BRANCH_SLUG} PASS evidence"

# CRITICAL: worktree is on a detached HEAD; must use HEAD:qa-evidence refspec
PUSH_SUCCEEDED_STEADY=false
for i in 1 2 3; do
  if git -C "$WORKTREE_PATH" push origin HEAD:qa-evidence; then
    PUSH_SUCCEEDED_STEADY=true
    break
  fi
  git -C "$WORKTREE_PATH" fetch origin qa-evidence
  git -C "$WORKTREE_PATH" rebase origin/qa-evidence
done

git -C "$REPO" worktree remove "$WORKTREE_PATH" --force 2>/dev/null || true
git -C "$REPO" worktree prune 2>/dev/null || true
```

**Build `QA_EVIDENCE_URLS` (only after push succeeds):**

Build `QA_EVIDENCE_URLS` only when the push in the active path succeeded. `$GH_REPO` is the repo slug resolved at Phase 0 setup (e.g. `org/repo-name`, same variable used throughout the command). Use `jq -n --arg` to safely interpolate description strings that may contain quotes or special characters.

```bash
# PUSH_SUCCEEDED is true only if the first-create or steady-state push loop above exited with success
PUSH_SUCCEEDED="${PUSH_SUCCEEDED_FIRST_CREATE:-${PUSH_SUCCEEDED_STEADY:-false}}"

QA_EVIDENCE_URLS=()
if [ "$PUSH_SUCCEEDED" = "true" ]; then
  OWNER=$(echo "$GH_REPO" | cut -d/ -f1)
  REPO_NAME=$(echo "$GH_REPO" | cut -d/ -f2)
  for entry in "${QA_SCREENSHOT_PATHS[@]}"; do
    FNAME=$(basename "$(echo "$entry" | jq -r '.path')")
    CRITERION=$(echo "$entry" | jq -r '.criterion_id')
    DESC=$(echo "$entry" | jq -r '.description')
    RESULT=$(echo "$entry" | jq -r '.result')
    URL="https://github.com/${OWNER}/${REPO_NAME}/blob/qa-evidence/${TICKET_SLUG}/${BRANCH_SLUG}/${FNAME}"
    # Use jq --arg to safely encode description (handles quotes and special chars)
    ENTRY_JSON=$(jq -n --arg url "$URL" --arg cid "$CRITERION" --arg d "$DESC" --arg r "$RESULT" \
      '{"url":$url,"criterion_id":$cid,"description":$d,"result":$r}')
    QA_EVIDENCE_URLS+=("$ENTRY_JSON")
  done
fi
```

If any step in the above sequence fails (push fails after 3 retries, worktree creation fails, copy fails), `QA_EVIDENCE_URLS` remains `()` (empty) and the phase continues. Phase 8.5 is always soft-fail - do not block Phase 9.

Clean up temp dir:

```bash
rm -rf "$SCREENSHOTS_SRC" 2>/dev/null || true
```

Clean up the original `/tmp/qa_*` source files that were consumed. Run this unconditionally after the copy loop and temp-dir cleanup, but only when `QA_SCREENSHOT_PATHS` is non-empty. Use the parsed paths so only copied files are deleted. Guard with `|| true` so Phase 8.5 remains soft-fail.

```bash
if [ "${#QA_SCREENSHOT_PATHS[@]}" -gt 0 ]; then
  for entry in "${QA_SCREENSHOT_PATHS[@]}"; do
    SRC_PATH=$(echo "$entry" | jq -r '.path')
    rm -f "$SRC_PATH" 2>/dev/null || true
  done
fi
```

Also delete `/tmp/qa_devserver.log` if it exists. Run this unconditionally at the end of Phase 8.5, regardless of whether screenshots were consumed:

```bash
rm -f /tmp/qa_devserver.log 2>/dev/null || true
```

Emit breadcrumb: `[phase: qa-evidence | screenshots=<N> | urls=<M> | branch=qa-evidence]`
