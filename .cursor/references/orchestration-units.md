<!--
Purpose: Full procedure for multi-unit orchestration in
         `/ds-implement-ticket`, moved verbatim out of
         content/commands/ds-implement-ticket.md so a single-unit run
         does not carry it. Covers Phase 3b after its trigger list
         (orchestration-planner spawn inputs, task-state initialization,
         cross-artifact alignment check, file-absent vs file-present
         task-state handling) and Phase 5's parallel fan-out path after
         its N=1 line (worktrees, join, partial success, per-unit /
         integration / multi-dimensional Skeptic strategies, merge
         phase, conflict recovery, fold-before-merge, cleanup).

Public API: Read-only reference document, addressed by its retained
            headings. Phase 3b's trigger and skip lists and the fan-out
            heading, N=1 line, and `brief_path`/`plan_path`
            normalization (shared with the single-engineer path) stay
            inline in content/commands/ds-implement-ticket.md, followed
            by a one-line `**Procedure:**` pointer to this file. The
            Phase 5 heading below is the parent of the moved subsection
            only; the single-engineer path stays in the command.

Upstream deps: none (prose reference only; no code, no runtime execution).
               Assumes content/references/task-state-file.md (the
               task-state fold) and the single-engineer path in
               content/commands/ds-implement-ticket.md Phase 5 are in
               context.

Downstream consumers: content/commands/ds-implement-ticket.md (Phase 3b
                      and fan-out pointer lines; Phase 6 guard names the
                      integration Skeptic defined here).

Failure modes: Prose reference; does not auto-execute. A conductor that
               skips the pointer fans out without the join, merge, or
               ownership gates - the inline trigger lines exist to make
               the Read unconditional when the trigger holds.

Performance: n/a (static reference document).
-->

## Phase 3b: Orchestration plan (conditional)

**When spawning `orchestration-planner`, provide:**
- The full ticket title and description
- The architect's complete output
- Instruction to produce: agent roster, execution phases (each with Give it / Returns / Proceed when fields), Skeptic checkpoints, and parallelization opportunities

The orchestration-planner's output drives Phase 5 agent spawning. If Phase 3b was skipped, Phase 5 falls back to the architect's plan directly.

### Task-state initialization (multi-unit only)

**Single-unit threshold:** If the orchestration plan identifies only 1 task, skip this step entirely. Task-state initialization is only warranted for plans with 2 or more tasks. For single-unit plans, the conductor operates as today (in-context state only).

After receiving the orchestration-planner's output and before Phase 4, initialize the task-state file:

```bash
mkdir -p .agentic && [ -f .agentic/tasks.jsonl ] || touch .agentic/tasks.jsonl
```

An empty file (0 bytes) is not corrupt - it means `touch` ran but the conductor was interrupted before the first append. Do NOT re-`touch` it and do not treat it as corrupt; the task-state fold over zero records is simply an empty index, identical to file-absent.

Also add `.agentic/` to the project's `.gitignore` if not already present.

**Generate identifiers (once per conductor session):**
- `session_id`: `<ISO-date>-<4hex>`, e.g. `20260415-a3f2`
- `task_id` per task: `<ticket_id>-<unit_slug>` (e.g. `ENG-42-auth-middleware`), or `<session_id>-<unit_slug>` for null-ticket projects

**Read the orchestration-planner's structured JSONL block** (the `## Task entries (machine-readable)` section at the end of the plan output). For each entry in that block, append a `pending` entry to `.agentic/tasks.jsonl`, **unless the task-state fold** (`content/references/task-state-file.md`) already reports records for that `task_id` - a concurrent conductor may have already initialized it, and appending a second `pending` for an already-live `task_id` degrades log hygiene even though it cannot regress a live claim (the fold's ownership rule already prevents that). Write tasks in dependency order - independent tasks (empty `depends_on`) first, dependent tasks after. Build each record in full and append it with **one complete `write()`** (`printf '%s\n' "$LINE" >> .agentic/tasks.jsonl`) - never composed from multiple writes, and never a rewrite; this is the append-only write contract every task-state write in this phase and Phase 5 follows. Each entry must include the fields from the schema: `task_id`, `session_id`, `ticket_id`, `unit_slug`, `status: pending`, `depends_on`, `created_at`, `updated_at`, `author_model` (set to `null` at init; populated by the conductor at engineer spawn in Phase 5 with the model id the engineer runs under), and the full `inputs` object (`description`, `acceptance_criteria`, `files_in_scope`, `quality_cmd`, `repo_path`, `base_branch`).

Emit breadcrumb: `[phase: task-state-init | N tasks written]`

### Cross-artifact alignment check (Brief present + planner returned units with non-empty criteria)

**Applies only when ALL hold:**
- `brief_path` is set (a Brief exists - operator-authored from Phase 0b, or conductor-authored at the promotion gate)
- The orchestration-planner returned a JSONL block with at least one unit carrying a non-empty `acceptance_criteria` array

When the guard does not apply (no Brief, or all units carry `acceptance_criteria: []`): emit `[phase: cross-artifact-check-skipped | no criteria to map]` and proceed to the promotion gate.

**This is a conductor-direct mechanical mapping, not a subagent and not adversarial review.** It complements the Skeptic-on-Brief; it does not replace it.

**Procedure:**
1. For each **Success criterion** in the Brief: scan every orchestration unit's `acceptance_criteria` array. Mark the criterion **COVERED** if at least one unit's entry explicitly addresses it; mark it **UNCOVERED** otherwise.
2. Produce a mapping table: `success criterion → covering unit_slug(s)`, or `"UNCOVERED"`.

**On any UNCOVERED criterion:** resolve before the Skeptic-on-Brief fires by one of:
- (a) Re-spawn the orchestration-planner with the specific uncovered criteria called out, so it adds or amends a unit's `acceptance_criteria`.
- (b) Surface the mismatch to the operator with a recommended resolution (descope the criterion from the Brief, or expand scope to cover it).

The conductor does not proceed to the Skeptic-on-Brief with an unresolved UNCOVERED criterion.

**On full coverage:** emit `[phase: cross-artifact-aligned | N/N criteria covered]` and proceed to the promotion gate.

See `content/references/planning-artifacts.md` §Gate semantics for where this step sits relative to the Skeptic-on-Brief.

**ALL writes to `.agentic/tasks.jsonl` are conductor-only.** Workers do not read or write the task file. Workers return their summaries to the conductor in the normal return path; the conductor extracts results and writes all updates. Every conductor write is a single-line append; every read applies the task-state fold. No lock is needed because no writer ever rewrites the file.

**File-absent vs file-present behavior:**

- **File absent:** Fresh start. Create the file and append `pending` entries as described above.
- **File present, empty (0 bytes):** Identical to absent for the fold - `touch` ran but the conductor was interrupted before the first append. Do NOT re-`touch`; do NOT treat as corrupt.
- **File present, non-empty:** Apply the **task-state fold** (`content/references/task-state-file.md` §Task-state fold) to build the in-memory per-`task_id` index before deciding anything - never read the latest raw line as the answer. Then classify each task by ownership × lifecycle per the fold's row grid (see `content/references/task-state-file.md` for the full 16-row matrix):
  - **Own tasks** (this session is the folded owner): `pending` → spawn; `in_progress` with no intervening foreign claim → in-session continuation (e.g., a prior worker returned BLOCKED and the human provided direction) - do not re-spawn, await the return; `done` → do not spawn, dependency satisfied, **merge permitted** (the only case that permits a merge - re-fold immediately before merging per the fold-before-merge gate in Phase 5's Merge phase, condition `owner == self AND status == done`). **Invariant self-check:** folding to `own + done` while this session holds no build record for the task (no `branch_name`/`commit_sha` under this session's own `session_id`) violates I2 and means an implementation bug - **escalate, never merge**; `failed`/`blocked`/`abandoned` → partial-success retry may append a fresh `in_progress` claim (cap 1 automatic retry).
  - **Foreign tasks, ticketed projects only** (a different session's `session_id` folds as owner; this ownership gate is structurally inert for null-ticket projects, where `task_id = <session_id>-<unit_slug>` and cross-session ids never collide - append-only still guarantees no state loss there, but there is no duplicate-fan-out protection): `pending` → spawn permitted, claim by appending `in_progress`; `in_progress` and fresh (< 10 min since the folded `updated_at`) → **do not spawn**, emit the row-7 warning below verbatim, do not merge, escalate; `in_progress` and stale (> 10 min) → orphan, spawn permitted, the fresh claim supersedes the prior one monotonically; `done` and this session holds no branch for the task → do not spawn, dependency satisfied; `done` and this session holds an outstanding branch for the task → do not spawn **and** do not merge that branch - the foreign owner's `done` is authoritative and this session's branch is a superseded generation whose commits may duplicate or conflict with the merged work; emit `WARNING: task <task_id> completed under session <X>; this session holds branch <B> for it. Not merging. Reconcile or discard manually.` and escalate; `failed`/`blocked`/`abandoned` → spawn permitted (retry), append `in_progress` with this session's own `session_id`.
  - **Dispossessed** (this session's claim was superseded by a later foreign `in_progress` - reachable because the 10-minute staleness window is shorter than the 30-minute fan-out join deadline): **do not spawn** (including the Phase 5 partial-success retry spawn), **do not merge** this session's branch, and **do not append a terminal status** - `done` is absorbing under the fold and would hijack the new owner's task. Append outputs anyway (durable, and excluded from the folded record by the cross-generation whitelist, but recoverable from the raw log). Emit: `WARNING: task <task_id> was taken over by session <X> while this session's engineer was running. Not merging. Reconcile manually.` and escalate.
  - **Legacy** (a record with no `session_id` - the schema has never mandated the field, so this includes both pre-fix records and any spec-compliant partial append that omits it): folds under a sentinel owner no session ever matches. Treated exactly as foreign-and-stale: `pending` → spawn permitted; `in_progress` → spawn permitted, **never** treated as fresh (an absent id cannot be shown live; blocking on it would deadlock every pre-fix project); `done` → do not spawn, and never mergeable by any viewer; `failed`/`blocked`/`abandoned` → spawn permitted.

  **Monotonic ownership.** Ownership is claimed only by an `in_progress` append and is never regained once superseded - a session whose claim was superseded cannot silently take the task back by appending outputs or any other later record; it must append a fresh `in_progress` claim through this same gate, and only when the fold currently permits a spawn for that task.

  On the foreign-and-fresh case, emit verbatim:

  ```
  WARNING: task <task_id> is in_progress under another session (session_id=<X>, updated_at=<Y>).
  Not spawning. Resolve manually (wait for that session, kill it, or restart task state) and retry.
  ```

  `<Y>` is the folded `updated_at` - the owner's latest append - the same value the 10-minute staleness test consumes.

  When the folded state, taken as a whole, shows orphaned tasks (`in_progress` or `blocked` entries stale under a different `session_id`, per the classification above): Log: "Found `.agentic/tasks.jsonl` with N orphaned tasks from a prior session." Surface the task list to the human with their last-known status and folded `updated_at` timestamp. Ask: "Do you want to resume from this state, or start fresh? (resume/restart)". On **restart**: rename the existing file to `.agentic/tasks.jsonl.YYYYMMDD-HHMMSS.bak`, create a new file, and proceed as fresh start - this is the one sanctioned truncation in the whole design, operator-confirmed, and never reachable from a malformed line. On **resume**: automatic resume is not yet implemented (P2). Display the last-known state of each task and say: "Automatic resume is not yet implemented. Here is the last-known state of each task: [table]. You can manually direct re-spawns for any in-progress tasks."
- **File present, different `session_id`, all terminal (`done`, `failed`, `abandoned`):** Historical records from a prior implementation. Append new entries for the current session without disturbing existing ones.

## Phase 5: Implement

### If parallel independent units were identified:

When this ticket has a Brief or Plan (Phase 4's "Commit and push the planning artifact" subsection ran and did not hit the gitignore no-op branch), `FEATURE_BRANCH` **is** the exact `BRANCH_NAME` value resolved there. Tickets with no Brief/Plan are unaffected; `FEATURE_BRANCH`'s origin for them remains as underspecified as before this ticket (Known limitations).

Use git worktrees to give each engineer an isolated copy. The orchestration-planner's JSONL block provides `unit_slug`, `merge_order`, and `skeptic_strategy` for each unit - read these fields to drive worktree naming, merge ordering, and Skeptic strategy. Before creating worktrees, prune stale state from any prior fan-out:

```bash
git -C $REPO worktree prune
# Leftover ${FEATURE_BRANCH}-${unit_slug} from a prior run: retire its checkout first
# ("$REPO_DIR/bin/ds-retire-carrier" <path>; any nonzero exit stops that unit - escalate).
# Then delete the branch (git branch -D) only if its tip is an ancestor of
# $FEATURE_BRANCH or origin/$BASE_BRANCH (git merge-base --is-ancestor); else escalate.
```

Create one worktree per unit, each rooted from `BASE_BRANCH` (loop over all N units from the planner's JSONL block in `merge_order` sequence):

```bash
# For each unit (unit_slug from planner JSONL block):
git -C $REPO worktree add ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} \
  -b ${FEATURE_BRANCH}-${unit_slug} origin/$BASE_BRANCH
```

**Task-state reads (when `.agentic/tasks.jsonl` is in use):** Before spawning, apply the **task-state fold** and verify all `depends_on` task_ids are folded `done`, then append a partial transition per unit moving status from `pending` -> `in_progress` - one `in_progress` claim record per unit. Include `assigned_agent` (the named agent type being spawned, e.g. 'engineer'), `worktree_path` (absolute path of the unit's worktree), `branch_name` (the unit's sub-branch `${FEATURE_BRANCH}-${unit_slug}`), `author_model` (the model id the engineer will run under, recorded so reviewer spawns - Skeptic, security-auditor - can select a different model when role-model routing is active; set to `null` when the model is unknown or role-model routing is off), and `ticket_id` (the ticket this unit belongs to - the Phase 9 Model: attribution read scopes on it).

Spawn one `engineer` agent per worktree in a single message (parallel, background). Each engineer works in its assigned worktree path and commits to its own sub-branch. Each agent's prompt should include:
- The execution contract block from `METHODOLOGY.md §Delegation > Worker preamble`, with fields filled in from the per-unit scope in the planner's JSONL block
- The unit's `task_id`, acceptance criteria, `files_in_scope`, `quality_cmd`, and worktree path
- The single-engineer list's `reviewer-bar` and review-rework bullets
- The per-unit scope: extracted from the orchestration-planner's JSONL block for that unit
- `brief_path_for_engineer`/`plan_path_for_engineer` (see "`brief_path`/`plan_path` normalization" in `ds-implement-ticket.md` §If parallel independent units were identified:) are **ticket-level** values, identical across every unit in this fan-out - they are NOT part of the per-unit JSONL scope and must be included in every unit's contract explicitly, not derived from it. This is the fix for Plan tier's own visibility gap: fan-out unit sub-branches are cut from `origin/$BASE_BRANCH`, never `FEATURE_BRANCH` (see "Create one worktree per unit, each rooted from `BASE_BRANCH`" above), so absolute-path delivery here is not optional belt-and-suspenders the way it is on the single-engineer path - it is the *only* visibility mechanism available to a fan-out unit engineer, since no git-native path exists for it at all.

**Join condition.** The conductor spawns all N engineers in a single message and waits for all N to return. After all N engineers return, apply the **task-state fold** to each unit's `task_id` and evaluate the join against the folded status - never a raw last-line read:

- **All-done join:** all N units fold to `status: done` (Skeptic signed off per P0 loop where applicable). Proceed to merge phase.
- **Partial success:** one or more units fold to `status: failed` or `status: blocked`, and one or more fold to `status: done`. Do NOT merge any branch. Apply partial success path (see below).
- **Total failure:** all units fold to failed or blocked. Clean up all worktrees, escalate to human with the orchestration-planner's original plan and all failure outputs. Recommend sequential implementation as fallback.
- **Blocked:** any unit folding to `status: blocked` is treated as failed for join evaluation. A worker returns `Status: BLOCKED` when it encounters a scope conflict, design ambiguity, or permission issue requiring human input.
- **Dispossessed (rows 14-16):** if a unit's fold shows this session was superseded by a foreign `in_progress` claim mid-flight, treat that unit as neither done nor eligible for merge regardless of what this session's own engineer returned - **do not merge this session's branch for it**, and if the foreign owner's fold shows `done` with this session still holding an outstanding branch (row 16), do not merge that branch either. Escalate per §3.3's row-14/15/16 disposition; do not fold this unit into the all-done or partial-success counts above as if this session owned it.

**Join timeout.** The join phase has a 30-minute total deadline. If the deadline elapses before all engineers have returned, units with no completion entry are treated as timed out (failed) and handled via the partial success path. Units that completed `status: done` before the deadline are still eligible for merge.

**Fallback: no task-state file.** If `.agentic/tasks.jsonl` is not in use, or is present but empty (0 bytes - the task-state fold over zero records is an empty index, identical to absent), derive status from each engineer's return value. Each engineer's return must include a structured status line as the first line: `Status: DONE`, `Status: DONE_WITH_CONCERNS`, or `Status: BLOCKED`. The engineer brief must explicitly require this structured first line.

After all engineers return, append an output-only entry per unit: write `worker_summary`, `commit_sha`, `files_modified`, and `quality_gate_passed` to each task's entry, with **no `status` field** - same rule as the single-unit output append in `ds-implement-ticket.md` §If work is a single logical unit (or units must be sequential): (§3.1/§3.2 of the task-state fold): an output append is never a claim. "Status remains `in_progress`" describes the folded status until Skeptic sign-off or final determination; it is not an instruction to write the field.

**Partial success path.** When one or more units fail and one or more succeed:
1. Record which units are `done` vs `failed`/`blocked`.
2. If done units are truly independent (no shared interface with failed units): merge them into `FEATURE_BRANCH` in `merge_order`, inside `$INTEGRATION_WORKTREE` (see Merge phase above). Leave failed units' worktrees in place.
3. Spawn a retry engineer for each failed unit, pointing it at the preserved worktree and the failure detail. Apply the **task-state fold** first: `inputs` survives generation boundaries because it is on the fold's cross-generation whitelist, so the retry brief reads a coherent `inputs` even when the failed unit's fold spans more than one session. The retry brief must include: (a) the original task brief from the folded `inputs` field, (b) the failure detail from `outputs.worker_summary` and `outputs.quality_gate_passed`, (c) the preserved worktree path, (d) any partial commits in the worktree, and (e) explicit instruction that this is a re-run, not a fresh start.
4. If the retry succeeds, merge and proceed to the Skeptic phase.
5. If the retry fails a second time, escalate to human with the full failure history.
6. Maximum retry depth: 1 automatic retry per unit.

**Per-unit Skeptic spawning (when `SKEPTIC_STRATEGY: per-unit`).** After each unit's engineer returns `done`, spawn a Skeptic for that unit's diff (unit worktree diff against `BASE_BRANCH`), including the Global-context input set (`## Global-context inputs` block per `content/references/skeptic-protocol.md` Section 4.5, field 6 = `$UNIT_KEY | ` + diff; field 7 per §4.5) alongside the adversarial brief. Per-unit Skeptics for independent units can be spawned in parallel (single message - they are reviewing non-overlapping diffs). Each unit's Skeptic integrates with the P0 persistence loop (Engineer -> Skeptic -> fix loop within the unit's worktree). A unit is `status: done` only after its Skeptic signs off, not after the engineer's first commit. After each unit's Skeptic/QA loop resolves, update the task entry to terminal status and populate `loop_state`, `outputs.skeptic_status`, and `outputs.skeptic_findings_count`.

**Integration Skeptic (when `SKEPTIC_STRATEGY: integration`).** Do NOT spawn per-unit Skeptics. Run the Merge phase below NOW - the ONE time it runs here. It stays provisional by staying unpushed until Phase 8. Spawn one integration Skeptic reviewing the combined diff from `BASE_BRANCH` to `$INTEGRATION_WORKTREE`'s `HEAD`, including the Global-context input set (`## Global-context inputs` block per Section 4.5, field 6 = `$UNIT_KEY | ` + diff; field 7 per §4.5). This Skeptic IS the Phase 6 gate here (see `ds-implement-ticket.md` §Phase 6: Skeptic review): draft the Phase 6 Step 1 PR text now for its Worker output; Phase 6 Steps 1-3 govern its findings. Pass it the orchestration-planner's independence annotation as the brief hint.

**Multi-dimensional Skeptic spawning (when `SKEPTIC_STRATEGY: multi-dimensional`).** Before spawning, declare per `content/references/skeptic-protocol.md` Section 13's Declaration format: `Risk: Elevated (multi-dimensional review) - [specific signal]` / `Tier: 3 (Opus)`. After each unit's engineer returns `done`, fan out `correctness-Skeptic + security-auditor + perf-analyst` in one message (parallel, background), reviewing that unit's diff (unit worktree diff against `BASE_BRANCH`), per `content/references/skeptic-protocol.md` Section 13's Workflow. The `correctness-Skeptic` spawn includes the Global-context input set (`## Global-context inputs` block per Section 4.5, field 6 = `$UNIT_KEY | ` + diff; field 7 per §4.5) - Step 0 BLOCKS without it. The `security-auditor` and `perf-analyst` spawns instead include the `## Supplemental context` block per §Supplemental-context block for multi-dimensional supplemental reviewers (informational only, not Step-0 enforced). A unit is `status: done` only after all three reviewers clear (Section 13 step 4) - a single open Critical or Major from any reviewer blocks completion. Section 13 defines only this per-unit gate, not cross-unit integration review, so merge-phase and Phase 6 timing follow the `per-unit` rules immediately below. Once all three reviewers clear, update the task entry to terminal status in a single append and populate `loop_state`, `outputs.skeptic_status` (the aggregate across the three reviewers - clear only when correctness-Skeptic, security-auditor, and perf-analyst have each cleared), and `outputs.skeptic_findings_count` (the summed count of findings across all three reviewers); per `content/references/task-state-file.md`'s field-level last-write-wins rule, `outputs.*` is session-scoped and overwritten on each write, so this composed value must land in one write, not three separate per-reviewer appends.

**Merge phase (all-done join).** Runs exactly once per ticket, inside a **dedicated integration worktree** - never `$REPO`. For `integration` it already ran above; do NOT repeat it. For `per-unit` and `multi-dimensional` it runs here first, after per-unit (or multi-dimensional) sign-off, merging sub-branches sequentially in `merge_order`. **Apply the fold-before-merge gate before each unit** - see "Fold-before-merge and branch verification" below:

```bash
INTEGRATION_WORKTREE="${REPO}/.agentic/worktrees/${FEATURE_BRANCH}"
# Same rule as the Elevated-path definition in ds-implement-ticket.md §If work is a single logical unit (or units must be sequential): (substitute
# $INTEGRATION_WORKTREE/$FEATURE_BRANCH for $WORKTREE_PATH/$BRANCH_NAME).
EXISTING_WT=""
_wt_path=""
while IFS= read -r _wt_line; do
  case "$_wt_line" in
    "worktree "*) _wt_path="${_wt_line#worktree }" ;;
    "branch refs/heads/$FEATURE_BRANCH") EXISTING_WT="$_wt_path" ;;
  esac
done < <(git -C $REPO worktree list --porcelain)
# `done < <(...)` is load-bearing - a pipe form would lose EXISTING_WT.
if [ -n "$EXISTING_WT" ]; then
  INTEGRATION_WORKTREE="$EXISTING_WT"   # reuse - apply reset-vs-recovery in ds-implement-ticket.md §If work is a single logical unit (or units must be sequential): first
elif git -C $REPO ls-remote --exit-code --heads origin "$FEATURE_BRANCH" >/dev/null 2>&1; then
  git -C $REPO fetch origin
  git -C $REPO worktree add "$INTEGRATION_WORKTREE" -B $FEATURE_BRANCH origin/$FEATURE_BRANCH
else
  git -C $REPO worktree add "$INTEGRATION_WORKTREE" -b $FEATURE_BRANCH origin/$BASE_BRANCH
fi

# For each unit in merge_order sequence:
git -C "$INTEGRATION_WORKTREE" merge --no-ff ${FEATURE_BRANCH}-${unit_slug}

# After each merge, check for conflicts before continuing:
# git -C "$INTEGRATION_WORKTREE" diff --name-only --diff-filter=U
# If that command outputs any file names, conflicts are present - apply N>2 conflict recovery below.
```

**N>2 conflict recovery.** On conflict at any step:
1. `git -C "$INTEGRATION_WORKTREE" merge --abort`
2. Stop; do not merge further.
3. Collect conflict files, all units' diffs, and the planner output. Then retire every unit checkout per **Worktree cleanup** below.
4. Spawn a single engineer with a conflict-resolution brief: all units' complete changes, the conflict markers, and explicit instruction to implement all units sequentially in a single worktree targeting `FEATURE_BRANCH`.
5. The sequential re-implementation engineer inherits a single-Skeptic review obligation (one Skeptic over combined diff, since units are now interdependent by fact of their conflict).
6. The conflict re-route counts as iteration 1 of the Phase 6 loop (do not double-count).

**Fold-before-merge and branch verification (third gate point).** Immediately before merging each unit's branch, re-apply the **task-state fold** to that unit's `task_id` and merge only if the folded state shows `owner == self AND status == done`. This is the third and final read-time ownership gate point - fold-before-spawn (Phase 5's spawn steps above) and fold-before-terminal-append (Phase 6) are the other two - and it is what makes the freeze lemma load-bearing rather than decorative: without it, a session could pass fold-before-spawn, have its claim superseded mid-flight (rows 14-16), and still merge on a stale read from earlier in the join. Any other folded result means **do not merge that unit's branch**: dispossessed (rows 14/15) or a foreign `done` while this session still holds an outstanding branch (row 16) both route to that row's disposition - escalate, do not merge. Also verify the worktree is on the expected branch:

```bash
# Confirm branch matches expected sub-branch before merging:
# git -C ${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug} rev-parse --abbrev-ref HEAD
# If the branch name does not match ${FEATURE_BRANCH}-${unit_slug}, abort that unit's merge and escalate.
```

**Post-merge integration quality check.** After all N merges complete cleanly on `FEATURE_BRANCH`, run `$QUALITY_CMD` from `$INTEGRATION_WORKTREE` (never `$REPO`). If it fails, spawn one engineer pointed at `$INTEGRATION_WORKTREE` with the failure output. The fix goes through a single Skeptic on the incremental diff before Phase 5 is complete; does NOT replace Phase 6.

**Worktree cleanup.** Retire each unit checkout at completion - after its merge, after escalation, or at a conflict re-route once step 3 has collected every unit's diff (§Carrier lifecycle by purpose in `content/references/worktree-lifecycle.md`). Delete a sub-branch only once `$FEATURE_BRANCH` contains its tip; an unmerged one stays and pins its commits:

```bash
# For each unit:
UNIT_WT="${REPO}/.agentic/worktrees/${FEATURE_BRANCH}-${unit_slug}"
if "$REPO_DIR/bin/ds-retire-carrier" --repo "$REPO" "$UNIT_WT" \
   && git -C $REPO merge-base --is-ancestor "${FEATURE_BRANCH}-${unit_slug}" "$FEATURE_BRANCH"; then
  git -C $REPO branch -D "${FEATURE_BRANCH}-${unit_slug}"
fi
git -C $REPO worktree prune
```

`$INTEGRATION_WORKTREE` is retired post-push by Phase 8's "Isolation worktree cleanup" block (resolved by `$BRANCH_NAME`).

For full worktree cleanup rules (isolation worktrees, feature worktrees, stale branch pruning), see `METHODOLOGY.md §Worktree Lifecycle`.

**Merge-conflict re-route and loop iteration:** If a merge conflict re-route occurred above and the re-routed Engineer's output then goes through Skeptic review in Phase 6, the conflict re-route counts as iteration 1 of the Phase 6 loop. Do not double-count: the conflict-resolution Engineer pass is the first fix pass; Phase 6 initializes its `iteration` counter at 1 to reflect this.
