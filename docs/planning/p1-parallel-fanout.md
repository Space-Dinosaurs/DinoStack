# P1 Parallel Fan-out Primitive - Design Plan

## Problem statement

The agentic-engineering protocol can identify independent subtasks (via `orchestration-planner`) and can spawn engineers into isolated worktrees (Phase 5 of `/implement-ticket`), but the two capabilities are not connected into a first-class primitive. What exists today is a manual, two-engineer sketch: the conductor creates worktrees by hand, spawns agents in a single message, and then merges sequentially. There is no structured join condition, no worker-to-conductor signaling, no partial failure path, and no formal relationship to the Skeptic review loop or to the P0 persistence work.

The gap (identified in `docs/research/omc-comparison.md`): "No parallel fan-out primitive. Background subagents exist but no first-class 'spawn N engineers against N independent subtasks, join when all green.' orchestration-planner plans it; nothing executes it concurrently."

The result is that large tickets with parallel units are either serialized (safe but slow) or executed ad-hoc (fast but fragile). A first-class fan-out primitive closes this gap without abandoning the Skeptic-gated rigor that distinguishes this protocol from OMC's verify-and-loop approach.

---

## Scope

**In scope:**
- The fan-out contract: inputs, execution model, outputs
- Worker signaling mechanism (P1 task-state file integration)
- Join condition and partial-success handling
- Skeptic review strategy (per-unit vs integration)
- Merge strategy for N worktree branches
- Failure handling when one or more units fail
- Changes required to `/implement-ticket` Phase 5 and `orchestration-planner`
- Relationship to P0 persistence loop (per-unit looping)
- Relationship to P1 task-state file

**Out of scope:**
- The task-state file schema itself (owned by the P1 task-state file design)
- P0 persistence loop internals (owned by `p0-persistence-loop.md`)
- Rate-limit resumer (P2)
- HUD statusline (P2)
- Benchmark harness (P1, separate design)

---

## Current parallel path (as-is)

**The current Phase 5 parallel path is hardcoded for exactly two units.** The worktree creation and agent spawn blocks are written for `unit1` and `unit2` with no loop construct - there is no mechanism for extending the pattern to three or more units without ad-hoc duplication.

Phase 5 of `/implement-ticket` describes this two-unit parallel path. The conductor:

1. Creates worktrees manually with `git worktree add` for each unit.
2. Spawns one `engineer` per worktree "in the same message (parallel)."
3. After both return, checks for uncommitted changes via `git status --porcelain`. Note: this check detects uncommitted changes but does NOT verify that a commit was made. An engineer that returned without committing anything would pass this check.
4. Merges sequentially with `--no-ff`, checking for conflicts after each merge.
5. On conflict: aborts, falls back to a sequential re-implementation with a single engineer.
6. Cleans up worktrees and sub-branches.

**What is missing from the current path:**

- **N=2 hardcoded limitation (leading constraint):** The pattern is written for exactly two units. Scaling to three or more requires ad-hoc extension with no defined merge order. This is the most critical structural gap.
- No signaling: the conductor has no structured way to know whether a unit is green, failed, or blocked mid-run beyond reading its return value.
- No per-unit Skeptic loop: the current path drops straight to Phase 6 (a single Skeptic over the combined diff). For genuinely independent units, this loses the high signal-to-noise benefit of narrow diffs.
- No partial success path: if one unit fails and another succeeds, there is no defined protocol - the instruction to "abort" and fall back to sequential re-implementation loses the successful unit's work.
- No P0 integration: each engineer is one-shot. If a unit fails tests, there is no loop.
- Worktrees are created by the conductor directly, not derived from a structured plan artifact.

---

## Proposed fan-out contract

### Inputs

The fan-out primitive is triggered when `orchestration-planner` returns a plan containing two or more independent (non-dependent) units. The planner's output is the canonical input; the conductor must not derive parallelization itself.

Required inputs to the fan-out primitive:
- `N` task briefs, each fully self-contained (files, acceptance criteria, quality gate command, branch name prefix, repo path). A brief must be executable by an engineer without reading other units' briefs or output.
- `BASE_BRANCH`: the branch all worktrees are rooted from.
- `FEATURE_BRANCH`: the final merge target branch (already created in Phase 4).
- `QUALITY_CMD`: the quality gate command run inside each worktree.
- `SKEPTIC_STRATEGY`: `per-unit` or `integration` - determined by the dependency classification in the orchestration-planner's output (see Skeptic review strategy section below). (Derived from orchestration-planner output - the planner update required in Changes Required adds this field; until that update is deployed, conductor must infer from the planner's independence classification.)

### Execution model

1. Conductor creates one worktree per unit from `BASE_BRANCH`:
   ```bash
   git -C $REPO worktree add ${REPO}/.worktrees/${FEATURE_BRANCH}-unit${N} \
     -b ${FEATURE_BRANCH}-unit${N} origin/$BASE_BRANCH
   ```
2. Conductor spawns one `engineer` per worktree in a single message (parallel, background).
3. Each engineer works in its worktree, runs `QUALITY_CMD`, and returns its completion summary to the conductor.
4. Conductor reads each engineer's return summary, writes status updates to the task-state file, and determines join readiness.
5. When all units report green (or a timeout/escalation condition triggers), conductor executes the join phase.

### Outputs

On success: all unit sub-branches merged into `FEATURE_BRANCH`, worktrees cleaned up, task-state file updated to reflect merged status.

On partial or total failure: escalation report to the conductor with: which units succeeded, which failed, the failure output for failed units, and a recommended next action (retry failed units, sequential re-implementation, or escalate to human).

---

## Worker signaling and join condition

### Task-state file

The conductor writes status updates to `.agentic/tasks.jsonl` after reading each worker's return summary. Workers do NOT write to the task-state file - they return their summaries in the normal return path, and the conductor handles all file writes.

Entry shape follows the P1 task-state schema (see `p1-shared-task-state.md`). Key fields: `task_id` (format: `<session_id>-<unit_slug>`), `status` (`pending` -> `in_progress` -> `done`/`failed`/`blocked`), `outputs` (worker_summary, commit_sha, files_modified, quality_gate_passed, skeptic_status). The conductor writes all entries - workers return their summaries in the normal return path.

### Join condition

The conductor spawns all N engineers in a single message (parallel) and waits for all N to return. After all N engineers return (the conductor has all N return values), the conductor reads the task-state file to evaluate the join condition. The join fires once, after all engineers have returned - there is no per-engineer notification event in the protocol.

- **All-done join:** all N units reach `status: done` (meaning Skeptic signed off per the P0 loop). Proceed to merge.
- **Partial success:** one or more units reach `status: failed` and one or more reach `status: done`. Do not merge any branch. Evaluate partial success path (see Failure handling section).
- **Total failure:** all units reach `status: failed`. Abandon worktrees, clean up, escalate.
- **Blocked:** any unit reaches `status: blocked`. Treat as failed for that unit. A worker returns `Status: BLOCKED` when it encounters a scope conflict requiring human input - specifically the same conditions that produce `Status: BLOCKED` in the P0 persistence loop: design ambiguity, permission required, or dependency unavailable.

### Join timeout

The join phase has a 30-minute total deadline (configurable in the orchestration-planner output, defaulting to 30 minutes). The conductor waits up to 30 minutes for all N engineers to return. If the deadline elapses before all engineers have returned, the conductor reads the task-state file to identify which units have a completion entry (`status: done` or `status: failed`) and which do not. Units with no completion entry are treated as timed-out and handled as failed units for the partial-success path. Units that completed and reached `status: done` before the deadline are still eligible for merge.

### Fallback: no task-state file

If the P1 task-state file is not yet implemented in the target project, the conductor falls back to deriving status from each engineer's return value. In this fallback mode, the conductor derives status from each engineer's return value instead of the task-state file. Each engineer's return must include a structured status line as the first line of their response: `Status: DONE` or `Status: DONE_WITH_CONCERNS` or `Status: BLOCKED` (consistent with the existing execution contract pattern in `agent-methodology.md`). The engineer brief must explicitly require this structured first line. This fallback is lower reliability than the task-state file path but preserves the join logic as long as the structured status line requirement is enforced in the engineer brief.

---

## Skeptic review strategy for parallel units

The decision rule is defined in `content/rules/agent-methodology.md` Task Decomposition section (independent units get their own Skeptic; interdependent units share one integration Skeptic). The independence heuristic is in `content/references/subagent-protocol.md` Section 6: "if a bug in unit A would only be detectable by examining unit B's implementation, or if unit A's correctness depends on assumptions about unit B's interface." This section maps those rules onto the fan-out execution model.

The decision rule from `agent-methodology.md` Task Decomposition section applies directly:

> - **Independent elevated units (planner-identified):** each gets its own Skeptic (small diff, high signal)
> - **Interdependent elevated units (planner-identified):** separate focused Workers, but one Skeptic reviewing the combined diff - the integration Skeptic replaces per-unit Skeptics, not layers on top

### Mapping to fan-out

**`SKEPTIC_STRATEGY: per-unit`** - applies when `orchestration-planner` classified all N units as fully independent (no shared interface, no shared state, bug in unit A not detectable by examining unit B). Each unit gets its own Skeptic running against its unit's diff only. Skeptics for independent units can themselves be spawned in parallel (they are reviewing non-overlapping diffs; there is no interference). This is the default strategy for genuinely independent fan-out.

**`SKEPTIC_STRATEGY: integration`** - applies when `orchestration-planner` flagged units as parallel-but-interdependent (shared interface contract, shared data model, cross-cutting concern). Units are still implemented in parallel, but Skeptic review is deferred until after all units are complete and merged onto a scratch integration branch. The integration Skeptic reviews the combined diff against `BASE_BRANCH`. This replaces per-unit Skeptics, not layers on top.

### When per-unit Skeptic runs (P0 integration)

If the P0 persistence loop is active, each unit's Skeptic is part of its own loop: Engineer -> Skeptic -> (if findings) Engineer -> Skeptic -> done. This loop runs entirely within the unit's worktree. The conductor does not join until each unit's loop has produced a Skeptic sign-off - the conductor updates the task entry to `status: done` only after Skeptic sign-off, not after the engineer's first commit.

This means the join condition above is re-stated more precisely: a unit reaches `status: done` when its persistence loop has completed with Skeptic sign-off, not merely when the engineer committed.

### Review scope guard

The integration Skeptic (for `integration` strategy) must receive the full combined diff from `BASE_BRANCH` to the merged state, not the individual unit diffs. This ensures cross-unit interactions are visible to the reviewer. The conductor generates this diff after merging all unit branches onto a scratch integration branch (not `FEATURE_BRANCH` - the merge is provisional until the integration Skeptic signs off).

---

## Failure handling (partial success)

### One unit fails, others succeed

The failing unit's worktree and branch are preserved - do not clean them up. The conductor:

1. Records which units are green and which failed.
2. Evaluates whether the green units can be merged independently (they can, if the units are truly independent - no shared interface with the failed unit).
3. If independent: merge green units into `FEATURE_BRANCH`. Leave the failed unit's worktree in place.
4. Spawn a new engineer for the failed unit, pointing it at the preserved worktree and the failure detail from the task-state file. This is a re-run, not a re-implementation. The retry engineer receives: (1) the original task brief from the task-state file `inputs` field, (2) the failure detail from `outputs.worker_summary` and `outputs.quality_gate_passed`, (3) the preserved worktree path (the engineer continues in-place, not from a fresh worktree), (4) any partial commits in the worktree (the engineer may amend or build on them). The retry brief must include explicit instruction that this is a re-run, not a fresh start.
5. If the re-run succeeds, merge the now-green unit and proceed to the Skeptic phase.
6. If the re-run fails a second time, escalate to human with the full failure history.

### All units fail

Clean up all worktrees. Escalate to the conductor with: the orchestration-planner's original plan, all failure outputs, and a recommendation to attempt sequential implementation as a fallback.

### Conflict at merge time

If merging unit branches produces a git conflict (regardless of which merge step causes it):

1. Abort the current merge: `git merge --abort`.
2. Do not attempt the remaining merges.
3. Collect: the conflict files, the two units' diffs, the original orchestration-planner output.
4. Spawn a single engineer with the conflict resolution brief: both units' complete changes, the conflict markers, and explicit instruction to implement both units sequentially in a single worktree targeting `FEATURE_BRANCH`.
5. The sequential re-implementation engineer inherits the Skeptic review obligation (single Skeptic over combined diff, since units are now interdependent by the fact of their conflict).

This matches the existing Phase 5 fallback logic but makes it explicit for N>2: stop at the first conflict, do not attempt remaining merges, and recover via sequential re-implementation.

### Maximum retry depth

Per-unit re-runs: 1 automatic retry. On second failure, escalate. This prevents infinite loops on persistently broken units without requiring P0 persistence loop integration to be complete.

---

## Merge strategy

### Ordering

Merge unit branches into `FEATURE_BRANCH` sequentially in the order returned by `orchestration-planner` (which provides an explicit execution order even for parallel units). Sequential merge order matters for conflict locality: if a conflict arises, it is attributable to a specific pair of units.

Do not use octopus merge (`git merge unit1 unit2 unit3` in one command). Octopus merges do not permit conflict detection between individual pairs. Sequential `--no-ff` merges with conflict checks after each merge preserve attributability and recovery precision.

### Conflict detection

After each sequential merge:
```bash
git -C $REPO diff --name-only --diff-filter=U
```
If this outputs any file names, conflicts are present. Run `git merge --abort` and trigger the conflict recovery path described above.

### No-fast-forward policy

All merges use `--no-ff` to preserve the unit sub-branch structure in the git graph. This makes the merge history readable and makes `git bisect` or `git log --graph` traces attributable to specific parallel units.

### Post-merge verification

After all N merges complete cleanly, run `QUALITY_CMD` from `FEATURE_BRANCH` root. This catches integration failures that were invisible within individual worktrees (e.g., two units that each pass tests independently but whose combined changes break a test that exercises both). If this integration quality check fails, treat it as a post-merge failure: spawn an engineer on `FEATURE_BRANCH` to fix the integration failure before proceeding to Skeptic.

### Worktree cleanup

Clean up worktrees and sub-branches after all merges succeed (or after escalation, to avoid stale worktrees accumulating). Follow the Worktree Lifecycle rules from `agent-methodology.md`:

```bash
# For each unit branch:
git -C $REPO worktree remove ${REPO}/.worktrees/${FEATURE_BRANCH}-unit${N} --force
git -C $REPO branch -d ${FEATURE_BRANCH}-unit${N}
git worktree prune
```

---

## Relationship to P0 persistence loop

The P0 persistence loop (`p0-persistence-loop.md`) turns a single Engineer -> Skeptic cycle into a loop that repeats until Skeptic sign-off or max-iteration cap.

The parallel fan-out primitive is orthogonal to P0 and composes with it at the unit level:

- Each parallel unit runs its own persistence loop independently, in its own worktree.
- The fan-out conductor does not join until each unit's loop has completed (green or exhausted).
- This means the join can take longer than a single-shot parallel run, but the quality guarantee is the same: the conductor only merges units that have passed Skeptic review.
- The task-state file is the coordination surface: the conductor updates a unit's task entry to `status: done` only after its persistence loop exits with Skeptic sign-off, not after its first engineer commit.

**Max iteration cap:** Each unit's persistence loop has its own cap (defined in the P0 spec). If a unit exhausts its cap without Skeptic sign-off, the conductor updates that unit's task entry to `status: failed` with `notes: "persistence loop exhausted after N iterations"`. The conductor treats this as a unit failure and applies the partial success path.

**Independence of loops:** Units' persistence loops do not share context or communicate with each other. Each loop is fully self-contained in its worktree. This is essential for correctness - a Skeptic reviewing unit A's diff must not be influenced by unit B's in-progress implementation.

---

## Relationship to P1 task-state file

The task-state file (`docs/research/omc-comparison.md` describes it as `.agentic/tasks.jsonl`) is the shared coordination surface for the fan-out primitive. It serves two roles:

1. **Completion tracking:** the conductor writes each unit's status entry after the unit's persistence loop completes. The conductor reads these entries to determine join readiness.
2. **Crash recovery:** if the conductor session is interrupted mid-fan-out, the task-state file records which units have completed. On resume, the conductor can read the file, identify which units are still `in_progress` (entries with no completion update), and decide whether to re-spawn them or abandon.

### Entry lifecycle

| Event | Entry updated by conductor |
|---|---|
| Fan-out initiated | Conductor writes N entries with `status: pending` and `unit_slug`, `branch_name`, `worktree_path` filled in |
| Engineer assigned to unit | Conductor updates to `status: in_progress` (before spawn) |
| Unit persistence loop completes with Skeptic sign-off | Conductor updates to `status: done` (after Skeptic sign-off) |
| Unit fails or blocks | Conductor updates to `status: failed` or `status: blocked` |
| Unit branch merged | Conductor updates `outputs.commit_sha` on the existing `done` entry |

### Absence of task-state file

If `.agentic/tasks.jsonl` does not exist in the project, the conductor creates it at fan-out initiation. If the project has not adopted the P1 task-state file convention at all, fall back to in-memory state derived from engineer return values (see Worker signaling section above).

---

## Changes required

### `/implement-ticket` Phase 5

1. **Generalize from 2 to N units.** The current worktree creation and agent spawn blocks are written for exactly two units. Replace with a loop over `orchestration-planner`'s unit list.

2. **Add task-state file initialization.** Before spawning engineers, the conductor writes `pending` entries to `.agentic/tasks.jsonl` for each unit, then updates each to `in_progress` immediately before spawning the corresponding engineer.

3. **Replace implicit join with explicit join condition.** The current "after all engineers complete, verify..." language becomes the structured join condition: read task-state entries, evaluate `done`/`failed`/`blocked` per unit.

4. **Add partial success path.** Document the recovery procedure for one-unit-fails / others-succeed, referencing the failure handling section above.

5. **Add per-unit Skeptic spawning.** When `SKEPTIC_STRATEGY: per-unit`, spawn Skeptics for each unit's diff before the merge phase, not after. The current Phase 6 single-Skeptic-over-combined-diff becomes the `integration` strategy path.

6. **Add post-merge integration quality check.** After all merges, run `QUALITY_CMD` on `FEATURE_BRANCH` before declaring Phase 5 complete.

7. **Add conflict recovery path for N>2.** The current conflict instructions handle two units. The N>2 path: stop at first conflict, abort, collect all units' diffs, spawn single engineer for sequential re-implementation.

### `/implement-ticket` Phase 6

1. **Clarify Phase 6 interaction with fan-out Skeptic strategies.** Add a conditional guard at the start of Phase 6: when fan-out was active and `SKEPTIC_STRATEGY: integration`, the integration Skeptic from Phase 5 IS the Phase 6 gate - do not spawn a second Skeptic. When `SKEPTIC_STRATEGY: per-unit`, Phase 6 fires as normal (combined diff review after all merges). See Phase 6 interaction note in the Edge cases section for full rationale.

### `orchestration-planner`

1. **Extend the existing JSONL block with `skeptic_strategy` and `merge_order` fields.** The orchestration-planner's structured JSONL block (implemented in P1 task-state, which already includes `unit_slug`, `depends_on`, `description`, `acceptance_criteria`, `files_in_scope`) is extended with two additional fields: `skeptic_strategy` ("per-unit" | "integration") and `merge_order` (integer). The `unit_slug` field already serves as the unit identifier - no separate `unit_id` is needed; use `unit_slug` consistently. The planner must classify each parallel group as independent or interdependent when producing the JSONL block. This change to the planner prompt requires Skeptic review.

2. **Add independence criteria annotation.** The planner should annotate why units are classified as independent or interdependent. This annotation becomes the adversarial brief hint for the integration Skeptic (if applicable) - the Skeptic knows to look for interactions at the boundary the planner described.

### `content/rules/agent-methodology.md`

1. **Update Named agents bullet.** The fan-out primitive formalizes the orchestration-planner's role in a new way. Update the "Named agents:" bullet to note that when fan-out is active, the orchestration-planner output JSONL block includes `unit_slug`, `merge_order`, and `skeptic_strategy` fields, and that per-unit Skeptic spawning is a valid conductor behavior for parallel fan-out (complementing the existing "independent elevated units get their own Skeptic" rule in Task Decomposition).

### `content/references/subagent-protocol.md`

1. **Section 6 (review scope rules) - add fan-out Skeptic strategy.** Add fan-out Skeptic strategy to Section 6: per-unit Skeptics review individual unit diffs; integration Skeptic reviews the combined diff from `BASE_BRANCH`. The independence heuristic already in Section 6 drives which strategy applies. This section should note that the orchestration-planner's classification is the authoritative source for the fan-out strategy determination.

2. **Section 7 (worktree isolation) - document manually-managed worktrees.** Update Section 7 to document manually-managed worktrees as a valid alternative to `isolation: "worktree"` for multi-branch fan-out scenarios. Note the key difference: manually-managed worktrees use explicit named sub-branches and allow conductor-directed merge ordering; the Task tool's `isolation: "worktree"` creates anonymous temporary branches. Both are valid; choice depends on whether merge order and branch naming matter.

### `content/references/agent-team.md` (Minor)

1. **Update spawn guidance.** Note that when fan-out is active, the orchestration-planner output JSONL block includes `unit_slug`, `merge_order`, and `skeptic_strategy` fields that the conductor reads at Phase 5.

### Docs and slides

- **`docs/agentic-engineering.html`** - UPDATE REQUIRED. Add parallel fan-out as a named capability. The hub page should reflect that `/implement` can now orchestrate N independent units concurrently, not just sequentially.
- **`docs/slides/how-it-works-slides.md`** - UPDATE REQUIRED. The Phase 5 slide (or the Engineer -> Skeptic flow) should show the fan-out path: N worktrees, N engineers in parallel, per-unit Skeptic review, join condition. This is a significant protocol change that the main how-it-works deck must reflect.
- **`docs/slides/orchestration-planner-slides.md`** - UPDATE REQUIRED. Update to show the new output fields added to the JSONL block: `skeptic_strategy`, `merge_order` (alongside the existing `unit_slug`). Show how the planner's classification drives the fan-out execution path.
- **New deck consideration:** A standalone `docs/slides/parallel-fanout-slides.md` is warranted once the feature ships. Parallel fan-out with per-unit Skeptic loops is a first-class primitive complex enough to deserve dedicated teaching material covering: when fan-out applies, the SKEPTIC_STRATEGY decision, join conditions, partial-success handling, and the P1 task-state file coordination model.

---

## Edge cases and failure modes

### Worker commits to wrong branch

A worker running in its worktree could inadvertently check out a different branch (e.g., if its engineer brief contains an ambiguous `git checkout` instruction). The conductor detects this via `git -C <worktree> status --porcelain` before merging - if the worktree is clean but the branch name in the task-state file does not match `git -C <worktree> rev-parse --abbrev-ref HEAD`, abort that unit's merge and escalate.

### Worktree path collision

If a previous fan-out left stale worktrees (session crash, incomplete cleanup), `git worktree add` will fail with "path already exists." The conductor must run `git worktree prune` and check for stale `${FEATURE_BRANCH}-unit*` branches before creating new worktrees. If stale branches exist with the same names, delete them before creating new ones.

### N=1 degenerate case

If `orchestration-planner` returns exactly one independent unit, the fan-out primitive is not invoked - the conductor falls through to the standard single-engineer Phase 5 path. The primitive is defined for N >= 2.

### Units with shared file writes

If two units that `orchestration-planner` classified as independent both write to the same file, git will detect a conflict at merge time. This is a planner classification error. The recovery path (sequential re-implementation) is the correct fallback. A post-mortem note should be written to `.agentic/tasks.jsonl` or a findings entry should be promoted noting that the planner misclassified the units - this is a recurring failure mode worth tracking.

### Very large N (>4 units)

At N > 4, the merge phase becomes a significant source of conflict risk even for genuinely independent units (shared test fixtures, shared generated files). For N > 4, consider chunking: fan out in batches of 2-4, merge each batch, run integration check, then fan out the next batch. This is not a hard limit - it is a practical guidance note for the implementation. The conductor may use judgment on batch sizing based on the units' file overlap.

### Integration quality check failure after all-green per-unit Skeptics

This is the most subtle failure mode: all units pass their individual Skeptic reviews, all merges succeed cleanly, but the combined `FEATURE_BRANCH` fails the quality gate. This means the units are not as independent as the planner classified - there is a behavioral interaction that the unit-level tests did not cover. Recovery: spawn a single engineer on `FEATURE_BRANCH` with the integration failure output. This engineer has full context (all units' work is on the branch). The resulting fix goes through a single Skeptic on the incremental diff.

The integration quality check failure path is entirely within Phase 5. The fix engineer and its incremental Skeptic run before Phase 5 is declared complete. After the integration fix Skeptic signs off, Phase 5 is complete and the normal Phase 6 Skeptic gate applies to the full combined diff. The integration fix Skeptic does NOT replace Phase 6.

### Phase 6 interaction

The relationship between per-unit Skeptics, the integration quality check Skeptic, and Phase 6 depends on `SKEPTIC_STRATEGY`:

- **`per-unit` strategy:** N per-unit Skeptics ran on individual unit diffs during Phase 5. Phase 6 fires as normal - a Skeptic reviews the combined diff from `BASE_BRANCH` after all merges. This third review sees the full picture that the per-unit Skeptics could not: cross-unit interactions, emergent behaviors, and the combined diff scope. Phase 6 is not skipped for `per-unit` strategy.

- **`integration` strategy:** One integration Skeptic ran on the combined diff during Phase 5 (after all units were merged onto a scratch integration branch). This IS the Phase 6 gate. When the integration Skeptic signs off, Phase 6 is complete. Phase 6 must not fire again - that would duplicate review of an identical diff. The conductor must skip the Phase 6 Skeptic spawn when `SKEPTIC_STRATEGY: integration` and the integration Skeptic has already signed off.

---

## Open questions (resolved 2026-04-16)

**Q1: Task-state file schema ownership.**
Decision: **RESOLVED BY PRIOR WORK.** The P1 task-state schema is implemented and stable (see `p1-shared-task-state.md`). The fan-out plan uses the canonical schema fields (`task_id`, `unit_slug`, `status: pending|in_progress|done|failed|blocked|abandoned`, `outputs` object) rather than any custom schema. No separate schema definition is needed in this document.
Rationale: the task-state file design was completed first; the fan-out plan aligns to it rather than defining its own conflicting schema.

**Q2: Per-unit Skeptic parallelism.**
Decision: **CLOSED.** Per-unit Skeptics for independent units SHOULD be spawned in a single message (parallel). This is the existing `subagent-protocol.md` Rule 2 behavior: "Independent tasks spawn simultaneously in a single message." Per-unit Skeptics reviewing non-overlapping diffs are independent tasks and require no protocol extension.

**Q3: Orchestration-planner output format.**
Decision: **ADD FIELDS TO EXISTING JSONL BLOCK.** The orchestration-planner's structured JSONL block (implemented in P1 task-state) is extended with `skeptic_strategy` ("per-unit" | "integration") and `merge_order` (integer). The existing `unit_slug` field serves as the unit identifier - no separate `unit_id` field is needed; use `unit_slug` consistently. The planner prompt change requires Skeptic review.
Rationale: the P1 task-state design already established the structured JSONL block output pattern; extending it preserves the existing schema and avoids a second structured output format in planner output.

**Q4: P0 loop cap per unit vs global cap.**
Decision: **NO GLOBAL CAP.** Per-unit caps from P0 are sufficient. No additional global cap across units is required.
Rationale: a global cap adds cross-unit scheduling complexity without clear benefit. A 4-unit fan-out with per-unit cap 5 could spawn up to 20 engineers - this is acceptable given each unit is genuinely independent work. The conductor can escalate manually if total cost is excessive. Revisit if very-large-N fan-outs become common.

**Q5: Crash recovery for in-progress units.**
Decision: **IN-PROGRESS TREATED AS FAILED ON RESUME; TRIGGER RE-SPAWN.** When the conductor resumes and finds task entries with `status: in_progress` from a prior session, it cannot resume the dead background agent. Those entries are treated as failed (the conductor cannot verify what the agent did or did not complete). The conductor applies the partial success path: re-spawn failed units with the original brief from the task entry's `inputs` field.
Rationale: consistent with the P1 task-state orphan handling (see `p1-shared-task-state.md` "File present - different session" section). The conductor cannot resume a dead background agent, so treating `in_progress` as failed is the only safe option. The preserved worktree (if any) is passed to the re-spawned engineer as a starting point.
