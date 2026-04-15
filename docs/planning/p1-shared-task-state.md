# P1 Shared Task-State File - Design Plan

## Problem statement

The current orchestration model is fully conductor-centric: all task state lives in the conductor's in-context working memory. The conductor spawns workers, waits for returns, synthesizes results, and advances to the next phase. This works for single-session linear workflows but breaks in three distinct ways:

1. **No worker coordination without conductor round-trips.** If two engineers are running in parallel, neither can see what the other is doing. They cannot signal readiness, report partial completion, or surface a blocker without routing through the conductor. All coordination is sequential (conductor waits for both, then acts), even when a downstream worker could have started as soon as the first upstream worker finished.

2. **No durable state across session boundaries.** The in-context loop state introduced by the P0 persistence loop is ephemeral - if the session dies (rate limit, crash, user closes the terminal), all loop progress is lost. The conductor must reconstruct from git log and manual inspection, or restart from scratch.

3. **No visibility into in-flight parallelism.** When N engineers are running concurrently against N git worktrees, the conductor has no structured record of which unit maps to which worktree, what each unit's scope is, or which ones have finished. The only check today is `git status --porcelain` on each worktree path after all workers return - a polling approach that assumes all workers run to completion without mid-task coordination needs.

The gap is stated directly in `docs/research/omc-comparison.md` (item 4 in "Where we are materially behind"): "No shared task-state file. Conductor carries everything in context. A `.agentic/tasks.jsonl` would let workers coordinate without conductor round-trips and let a loop resume after restart."

This document designs that file.

---

## Scope

**In scope:**
- Schema for a task entry in `.agentic/tasks.jsonl`
- Read/write protocol: who writes what, when, under what locking strategy
- Conductor behavior when the file is absent (fresh start) vs. present (possible resume)
- Worker behavior: what workers read from and write to the file
- Relationship to the P0 in-context loop state (complementary, not redundant)
- How this file enables P2 cross-session resume without implementing it yet
- File location, naming, gitignore status
- Which methodology files need updating when this is implemented

**Explicitly out of scope:**
- The parallel fan-out primitive itself (the mechanism that actually spawns N workers in parallel and joins them) - this is the other half of the P1 plan and is a separate design document
- Cross-session resume implementation - this is P2
- Rate-limit daemon or `omc wait` equivalent - this is P2
- Cost-aware model routing - this is P2

---

## Relationship to P0 loop state and P2 cross-session resume

### P0 in-context loop state (complementary)

The P0 persistence loop defines a `LOOP_STATE` object the conductor maintains in working memory across Skeptic and QA iterations. That state is intentionally in-context only (P0's own scope section explicitly defers file-based persistence to P1). The two mechanisms serve different purposes and operate at different granularities:

| Dimension | P0 in-context loop state | P1 `.agentic/tasks.jsonl` |
|---|---|---|
| Granularity | Per-finding, per-iteration within a single Engineer/Skeptic/QA loop | Per-task, per-unit across the full orchestration plan |
| Lifetime | Current session only - lost on session exit | Durable across session boundaries |
| Consumer | Conductor only (reads and updates inline) | Conductor + workers (workers write status; conductor reads) |
| Purpose | Prevent re-litigation of closed findings; bound the loop | Track which tasks exist, who owns them, what state they are in |
| Scope | Phase 6 and 6b of `/implement-ticket` | Any multi-unit orchestration plan |

The P0 state is fine-grained review bookkeeping; the P1 state is coarse-grained execution tracking. In a full P1+P0 execution: the conductor writes tasks to `.agentic/tasks.jsonl` before spawning workers; workers update their task entries as they run; the conductor reads task entries to determine when to advance; when Phase 6 begins for a given task, the P0 LOOP_STATE object is initialized in-context for that task's Skeptic loop. The two are composable - P0 state is ephemeral and nested inside a single task's review phase; P1 state is durable and spans the full task lifecycle.

**Open question OQ-4 from the P0 plan** asked whether loop state should be written to a file for observability, noting it would be "a step toward the P2 cross-session resume feature." This P1 design answers that: yes, but as part of the task-state entry rather than a separate loop-state file. Each task entry in `.agentic/tasks.jsonl` carries a `loop_state` field that the conductor populates when Phase 6 begins. This provides the post-mortem visibility OQ-4 was asking for and positions P2 to read it for resume.

### P2 cross-session resume (enabled, not implemented)

The P2 cross-session resume use case requires that when a session dies mid-orchestration, the next session can read `.agentic/tasks.jsonl`, identify which tasks are `in_progress` or `blocked`, reconstruct the execution context, and continue without restarting from scratch.

This design intentionally includes every field P2 will need, without implementing the resume logic:

- `status` values include `in_progress`, `blocked`, and `abandoned` - all states a resumed session must handle
- `assigned_agent` records which agent was running so the resumed conductor can decide whether to re-spawn or verify completion
- `worktree_path` records the git worktree so the resumed conductor can inspect it
- `started_at` and `updated_at` timestamps let P2 detect stale in-progress tasks (tasks whose `updated_at` is more than N minutes old are likely dead from a session exit)
- `inputs` and `outputs` are fully specified so a resumed session can reconstruct the worker brief without re-reading the original ticket
- `loop_state` is the P0 LOOP_STATE object serialized to JSON, enabling P2 to resume a Skeptic loop mid-iteration

P2 only needs to implement the resume decision logic (read file, classify task states, decide what to restart) - the data is already there.

---

## Schema

### File format

`.agentic/tasks.jsonl` - newline-delimited JSON. One JSON object per line, one line per task. JSONL is chosen over plain JSON for:

- Append-only safety: a worker can append a new line without reading and rewriting the entire file (important for concurrent writes - see locking section)
- Partial reads: a session can `tail -n 1` to get the latest state of any task it already has the ID for
- Post-mortem legibility: `jq` works naturally on JSONL; a plain JSON array requires the file to be well-formed at all times

Tasks are never deleted from the file. Completed or abandoned tasks remain as historical records. The conductor queries by `task_id` and `status` - it reads all lines and builds an in-memory index at session start.

### Task entry schema

```jsonc
{
  // Identity
  "task_id": "string",          // Unique ID. Format: "<ticket-id>-<unit-slug>", e.g. "ENG-42-auth-middleware"
                                 // For tasks without a ticket: "<session-date>-<4hex>-<unit-slug>", e.g. "20260415-a3f2-auth-middleware"
  "session_id": "string",       // Conductor session identifier: ISO date + random 4-char hex, e.g. "20260415-a3f2"
                                 // Generated once per conductor session and included in every task entry.
                                 // Used as the primary session discriminator (supersedes ticket_id for null-ticket projects).
  "ticket_id": "string | null", // Source ticket (Linear issue, Jira key, or null if no tracker)
  "unit_slug": "string",        // Short human-readable label for this unit, e.g. "auth-middleware", "db-migrations"
  "created_at": "ISO8601",      // When the conductor created this entry
  "updated_at": "ISO8601",      // Last write timestamp (conductor or worker)

  // Status
  "status": "pending | in_progress | done | failed | blocked | abandoned",
  //   pending:     created by conductor, worker not yet spawned
  //   in_progress: worker spawned, not yet returned
  //   done:        worker returned Status: DONE and Skeptic signed off (if applicable)
  //   failed:      worker returned a non-DONE status, or Skeptic raised unresolved Critical/Major
  //   blocked:     worker returned Status: BLOCKED (design conflict requiring human input)
  //   abandoned:   conductor decided to drop this task (cap reached, human cancelled, etc.)

  // Assignment
  "assigned_agent": "string | null",  // Named agent type: "engineer", "architect", etc. Null until spawned.
  "worktree_path": "string | null",   // Absolute path to the git worktree for this task. Null if not using worktrees.
  "branch_name": "string | null",     // Git branch this task is working on

  // Dependencies
  "depends_on": ["task_id", ...],     // IDs of tasks that must reach status=done before this task can start
                                       // Empty array means no dependencies (can start immediately / run in parallel)

  // Inputs - the brief the worker receives
  "inputs": {
    "description": "string",           // What this task must accomplish (from orchestration-planner output or architect plan)
    "acceptance_criteria": ["string"], // Verbatim acceptance criteria the worker must satisfy
    "files_in_scope": ["string"],      // File paths the worker is expected to touch (informational, not a lock)
    "quality_cmd": "string | null",    // The $QUALITY_CMD to run before finishing
    "repo_path": "string",             // Absolute path to the repo root (or worktree root)
    "base_branch": "string"            // The branch workers diff against and eventually merge into
  },

  // Outputs - populated by the worker on return
  "outputs": {
    "worker_summary": "string | null",  // The worker's return summary (Status: DONE / BLOCKED / etc.)
    "commit_sha": "string | null",      // The commit SHA the worker produced, if any
    "files_modified": ["string"],       // Actual files the worker touched (from git diff)
    "quality_gate_passed": "boolean | null",  // Whether $QUALITY_CMD passed
    "skeptic_status": "pending | signed_off | rejected | skipped | null",
    "skeptic_findings_count": {
      "critical": "integer | null",
      "major": "integer | null",
      "minor": "integer | null"
    }
  },

  // Loop state - the P0 LOOP_STATE object, serialized here for durability
  // Null until Phase 6 begins for this task. Updated by the conductor after each iteration.
  "loop_state": {
    "phase": "skeptic | qa | null",
    "iteration": "integer",
    "max_iterations": "integer",
    "findings_log": [...],      // Same schema as P0 LOOP_STATE findings_log
    "qa_failures_log": [...],   // Same schema as P0 LOOP_STATE qa_failures_log
    "termination_reason": "null | clean | cap_reached | convergence_failure | blocked"
  } | null,

  // Metadata
  "orchestration_plan_ref": "string | null",  // Label or phase reference from the orchestration-planner output
  "notes": "string | null"                    // Free-text conductor notes (blockers, human decisions pending, etc.)
}
```

### Status transition diagram

```
pending -> in_progress  (conductor spawns worker)
in_progress -> done     (worker returns DONE, Skeptic signs off or is not required)
in_progress -> failed   (Skeptic rejected, loop cap reached with open Critical/Major)
in_progress -> blocked  (worker returns BLOCKED)
in_progress -> abandoned (conductor cancels, e.g. dependency task failed making this moot)
blocked -> in_progress  (human provides direction, conductor re-spawns)
failed -> in_progress   (human directs a re-run, conductor re-spawns)
pending -> abandoned    (conductor cancels before worker is spawned)
```

A task never moves backward past `pending`. A `done` task is terminal - it is never updated after Skeptic sign-off. If a re-run is needed after `done` (e.g., a regression discovered later), a new task entry is appended with a new `task_id`.

---

## Read/write protocol

### Who writes what and when

**Conductor writes:**
- Creates the initial task entry (status: `pending`) when it has the orchestration plan and is ready to begin spawning
- Updates status from `pending` -> `in_progress` immediately before spawning the worker
- Updates `outputs.skeptic_status`, `outputs.skeptic_findings_count`, and `loop_state` after each Skeptic or QA iteration (the worker does not update these)
- Updates status to `done`, `failed`, or `blocked` based on final loop outcomes
- Writes the `notes` field when a human decision is pending or a blocker is logged

**Workers write:**
- Update status from `in_progress` -> (remains `in_progress`) and write `outputs.worker_summary`, `outputs.commit_sha`, `outputs.files_modified`, `outputs.quality_gate_passed` when they return their result
- Workers do NOT update `skeptic_status`, `loop_state`, or dependency relationships - those are conductor concerns

**Workers do NOT read:**
- Workers are given their complete brief in the spawn prompt. They do not read the task file to get their instructions. This keeps workers stateless with respect to the file - they can run in environments where the file is not accessible.

**Why workers write but don't read:** The file is a coordination surface for the conductor, not a shared blackboard. Workers write their results so the conductor can read them without carrying all return values in context (particularly useful for long-running parallel tasks where context pressure is real). Workers reading the file would create coupling between worker execution and file structure, making workers harder to reason about and test.

### Locking strategy for concurrent writes

Multiple workers running in parallel against different worktrees may try to write to the file simultaneously. JSONL's append-only nature mitigates most of the risk: each write is a single line append. POSIX O_APPEND semantics ensure each `write()` call is positioned at end-of-file, but byte-level atomicity for concurrent writes from multiple processes is not guaranteed on regular files on macOS (APFS). The lock protocol is therefore required for correctness, not merely as a precaution.

Workers use a write protocol with a lock file:

**Lock file:** `.agentic/tasks.lock`

**Write protocol for workers:**

```bash
# Acquire lock (spin with backoff, max 30 seconds)
# TASK_STATE_FILE must be an absolute path passed by the conductor in the spawn prompt.
# Using an absolute path is required because workers run from the worktree root, not the
# parent repo root, and .agentic/ does not exist relative to the worktree.
TASKS_FILE="${TASK_STATE_FILE:-.agentic/tasks.jsonl}"  # absolute path from spawn prompt
LOCK="${TASKS_FILE%.jsonl}.lock"
TIMEOUT=30  # seconds
ELAPSED=0
while ! mkdir "$LOCK" 2>/dev/null; do
  sleep 1
  ELAPSED=$((ELAPSED + 1))
  if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "WARN: tasks.lock acquire timeout after ${TIMEOUT}s - writing without lock" >&2
    break
  fi
done

# Write (append a single line)
echo '<json-object>' >> "$TASKS_FILE"

# Release lock
rmdir "$LOCK" 2>/dev/null || true
```

**Note on lock timeout and race conditions:** The 30-second timeout addresses stale locks from dead workers (session killed mid-write). It also fires if a legitimate holder takes more than 30 seconds - this is a true concurrent-write race condition. To minimize this risk, task entries should be kept compact (single-line JSON, well under 1 KB), so writes complete in milliseconds. The conductor detects any resulting corruption at session start (see malformed-line handling below).

`mkdir` is atomic on all POSIX filesystems - it either creates the directory (lock acquired) or fails (lock held). This is simpler and more portable than `flock` (which requires a file descriptor, not available in all agent execution environments).

**Conductor writes are always single-threaded** (the conductor is a single agent that does not run concurrent tool calls against the same file). The conductor does not need the lock protocol. It should still check for the presence of the lock before writing and wait if a worker is holding it, but in practice conductor writes happen after workers return, not concurrently.

**Lock timeout policy:** A lock held for more than 30 seconds indicates a dead worker (session killed mid-write) or a legitimate holder that is running slowly. Either way, the writer proceeds without the lock and logs a warning. The conductor, at session start, reads all lines in the file. Lines that are not valid JSON are skipped with a warning, and their corresponding tasks are treated as orphaned (status unknown). After loading the file, the conductor logs the count of skipped malformed lines. If any malformed lines are found, the conductor surfaces a message to the human: "N malformed task entries found (likely from a concurrent write race). Corresponding tasks are treated as orphaned." This is a degraded-mode fallback, not a normal path.

---

## Conductor behavior (file absent vs present)

### File absent (fresh start)

When `/implement-ticket` Phase 3b produces an orchestration plan and the conductor is about to enter Phase 5, it checks for `.agentic/tasks.jsonl`:

```bash
mkdir -p .agentic
[ -f .agentic/tasks.jsonl ] || touch .agentic/tasks.jsonl
```

If the file does not exist: fresh start. The conductor creates it, appends one entry per task identified in the orchestration plan (all with status `pending`), and proceeds normally to Phase 5. Tasks are written in dependency order - independent tasks (empty `depends_on`) are written first, dependent tasks after. Writing them in this order makes the file easier to read but does not enforce execution order (the conductor enforces order by checking `depends_on` at spawn time).

**No file, no error:** A missing file is not an error condition - it is the expected state at the start of any new implementation. The file is an optional coordination aid, not a requirement for the workflow to function.

### File present - same session, same ticket (continuation)

If the file exists AND contains entries with the current `session_id`, the conductor is resuming within the same session (e.g., the conductor spawned Phase 5 workers, one returned BLOCKED, and the human is providing direction). `session_id` (not `ticket_id`) is the primary discriminator - this correctly handles null-ticket projects where `ticket_id` would be null for all entries and could not distinguish sessions. The conductor reads all entries for this session_id, builds the in-memory status index using the field-level merge algorithm, and determines next action:

- Any `pending` tasks whose `depends_on` are all `done`: spawn workers for them
- Any `in_progress` tasks: check whether the worker is still running; if the worker already returned (session has the return in context), update the file entry
- Any `blocked` tasks: surface to human, wait for direction
- Any `failed` tasks: follow the loop contract (escalate if cap reached, re-spawn if human directs)
- All `done`: Phase 5 is complete; proceed to post-implementation phases

### File present - different session (possible resume - P2)

If the file exists AND contains entries with a different `session_id` (or no `session_id`, for files written before this schema version) AND those entries have `in_progress` or `blocked` status AND the current conductor session does not have the corresponding worker return in context, these are orphaned tasks from a dead session. This is the P2 use case.

In P1 (this design), the conductor's behavior on detecting orphaned tasks is:

1. Log the detection: "Found `.agentic/tasks.jsonl` with N orphaned tasks from a prior session."
2. Surface the task list to the human with their last-known status and `updated_at` timestamp.
3. Ask: "Do you want to resume from this state, or start fresh? (resume/restart)"
4. On **restart**: rename the existing file to `.agentic/tasks.jsonl.YYYYMMDD-HHMMSS.bak`, create a new file, and proceed as fresh start.
5. On **resume**: this is the P2 implementation path. In P1, the conductor cannot automatically resume - it lacks the in-context worker state, branch checkout confirmation, and loop state reconstruction logic that P2 will implement. The conductor should say: "Automatic resume is not yet implemented. Here is the last-known state of each task: [table]. You can manually direct re-spawns for any in-progress tasks."

**P2 will replace step 5** with actual resume logic: inspect each orphaned task's worktree, check git status, rebuild LOOP_STATE from the `loop_state` field, re-spawn blocked/in-progress workers with the original brief from `inputs`.

### File present - different session / different ticket

If the file contains only entries for a different `session_id` (and/or different `ticket_id`) that are all in terminal states (`done`, `failed`, `abandoned`), the conductor does not interact with those entries. They are records from a prior implementation. The conductor appends new entries for the current session without disturbing the existing ones. Over time the file accumulates history.

**File size management:** Because tasks are never deleted and the file accumulates history, a long-lived project will eventually grow the file to a non-trivial size. This is acceptable - JSONL files with hundreds of entries are still fast to read. The P2 implementation may want to introduce a rotation policy (archive entries older than N days to `.agentic/tasks.YYYYMM.jsonl.bak`), but this is not needed for P1.

---

## Worker behavior

Workers in this design are largely unaware of the task-state file. Their behavior changes in two ways:

### At task completion, workers write their result entry

Before returning their final summary to the conductor, workers write a result record. This is a single append to `.agentic/tasks.jsonl` with the worker's `task_id`, `status` set to `in_progress` (the conductor will update the terminal status after Skeptic review), and the populated `outputs` fields.

Workers receive their `task_id` and the absolute path to the task file in the spawn prompt. The conductor MUST include both as fields in the execution contract block. The absolute path is required because workers run from the worktree root (not the parent repo root), and `.agentic/` exists only at the parent repo root - a relative path would silently create a disconnected file in the worktree:

```
- task_id: ENG-42-auth-middleware  (write this to the task_state_file on completion)
- task_state_file: /absolute/path/to/repo/.agentic/tasks.jsonl  (absolute path - required for worktree isolation)
```

Workers that complete without errors write:
```json
{"task_id": "ENG-42-auth-middleware", "updated_at": "...", "status": "in_progress",
 "outputs": {"worker_summary": "...", "commit_sha": "abc1234", "files_modified": [...],
              "quality_gate_passed": true, "skeptic_status": null}}
```

Workers that return BLOCKED write:
```json
{"task_id": "ENG-42-auth-middleware", "updated_at": "...", "status": "blocked",
 "outputs": {"worker_summary": "BLOCKED: ...", "commit_sha": null, "files_modified": [],
              "quality_gate_passed": null, "skeptic_status": null}}
```

**Workers write a partial entry, not the full entry.** The conductor holds the full entry (including `inputs`, `depends_on`, `orchestration_plan_ref`, etc.) from when it created the task. Workers only write the fields they know: identity fields (`task_id`, `updated_at`, `status`) and `outputs`. The conductor reads all entries for each `task_id` and merges them field-by-field to produce the authoritative in-memory record. A worker's partial entry (containing only outputs) is merged with the conductor's initial entry (containing inputs and identity) - neither entry alone is complete or authoritative.

**Field-level merge algorithm:** When building the in-memory index, the conductor does NOT simply take the last entry per `task_id` as a complete replacement. Instead: for each `task_id`, the conductor iterates all entries in file order, starting with an empty record. For each entry, it merges field-by-field into the record: for each field present in the entry, if the entry's value is non-null, it overwrites the record's value; null or missing fields are skipped (carry forward the prior value). This yields a merged record that combines the conductor's initial identity/input fields with the worker's latest output fields.

### Workers do not consult the file for their brief

Workers receive everything they need in the spawn prompt. They do not read `.agentic/tasks.jsonl` to get their task description. This separation is intentional:
- Workers in isolated worktrees may not have the file in their working directory (worktrees do not inherit the parent repo's untracked files)
- Workers should not need to parse JSON to know what to do - the brief is in their prompt
- Keeping workers file-unaware makes them usable in contexts where the file does not exist (e.g., a one-off engineer spawn outside of a full `/implement-ticket` invocation)

---

## File location and lifecycle

### Location

`.agentic/tasks.jsonl` - at the project repo root, in the `.agentic/` directory.

The `.agentic/` prefix is chosen to avoid collision with tool-specific directories (`.claude/`, `.cursor/`, `.codex/`) and to signal that this is project-agnostic agentic tooling state. It parallels OMC's `.omc/state/` naming convention without adopting OMC's specific path.

### Gitignore status

`.agentic/tasks.jsonl` should be **gitignored**.

Rationale:
- Task state is session-specific and environment-specific. Committing it would create noise in the git log and merge conflicts for teams.
- The file contains absolute paths (`worktree_path`, `repo_path`) that differ across machines.
- The primary value of the file is within a session (coordination) and across sessions on the same machine (P2 resume). Sharing it across machines via git is not a use case for P1 or P2.

The `.agentic/` directory itself should be added to `.gitignore`. If the project already has a `.gitignore`, the conductor adds `.agentic/` to it as part of file creation. If not, the conductor creates a minimal `.gitignore` containing only `.agentic/`.

Exception: teams that want shared task history across machines may choose to commit the file. The design supports this - the format is stable and human-readable. The default is gitignored; opt-in to commit is a team decision, not a methodology decision.

### Lock file

`.agentic/tasks.lock` is a directory (created by `mkdir`, removed by `rmdir` after write). It is transient - it should not exist for more than a few seconds during any write. It is also gitignored via the `.agentic/` entry.

### Backup files

`.agentic/tasks.jsonl.YYYYMMDD-HHMMSS.bak` - created when the conductor renames a prior session's file on user-directed restart. Also gitignored via the `.agentic/` entry.

---

## Changes required (which methodology files reference this)

Using the 7-surface audit pattern from MEMORY.md:

1. **`content/commands/implement-ticket.md`** - UPDATE REQUIRED. Phase 3b (orchestration plan) must add a step: after the orchestration plan is received, create `.agentic/tasks.jsonl` entries for each planned task before spawning any workers. Phase 5 must add task-state reads to the parallel worker spawn/join flow. Phase 5's post-merge verification step should read task entries rather than only checking `git status --porcelain`. Introduce conductor behavior rules for "file absent" and "file present" per the Conductor Behavior section above.

2. **`content/rules/agent-methodology.md`** - UPDATE REQUIRED. The Worker preamble section must add `task_id` and `task_state_file` as new fields in the execution contract block template. Add a sentence to the Worker preamble rule: "Workers that complete a task write their result to the file at `task_state_file` (absolute path) before returning their final summary. The `task_id` and `task_state_file` fields are provided in the spawn prompt." Add a brief "Task-state file" subsection cross-referencing this design for when it applies (Elevated, multi-unit only - not for Trivial or single-unit spawns). Note that the `task_state_file` field must be an absolute path - a relative path would resolve to the worktree root and silently create a disconnected file.

3. **`content/agents/orchestration-planner.md`** - UPDATE REQUIRED. Add a step 7.5 to the Planning Process: "If the plan includes 2 or more independent tasks (parallelization opportunities exist), note the `.agentic/tasks.jsonl` entry shape for each task in the Conductor Actions section - the conductor will create these entries before spawning." The planner does not write the file itself (it is read-only), but it should produce enough structure in its output that the conductor can create entries without inferring fields. Also add cycle validation: the orchestration-planner must validate that the plan's `depends_on` graph is acyclic before outputting the plan. A cycle in the plan (task A depends on task B, task B depends on task A) would cause the conductor to deadlock. The planner is the earlier, cheaper gate; conductor-side cycle detection (edge case 6) is a safety net, not the primary check.

4. **`content/references/subagent-protocol.md`** - UPDATE REQUIRED. Add a new phase breadcrumb: `[phase: task-state-init | N tasks written]` emitted by the conductor after writing initial task entries. Add a note to the parallel spawn section (Section 2 or 5) that workers receive their `task_id` in the spawn prompt and are expected to write their result entry before returning.

5. **`content/references/agent-team.md`** - Minor update. Add a row to the agent table for the task-state write responsibility: "Engineer, when spawned via `/implement-ticket` Phase 5 with a `task_id`, writes a result entry to `.agentic/tasks.jsonl` on completion." This is documentation-only; no behavior change.

6. **`content/commands/init-project.md`** - UPDATE REQUIRED. The scaffold step should add `.agentic/` to `.gitignore` if not already present. If the project shows parallel fan-out signals (3+ distinct modules, complex orchestration history), add a note in the scaffolded `AGENTS.md` that `.agentic/tasks.jsonl` is the task coordination surface.

7. **`content/commands/wrap.md`** - Minor update. The wrap command captures stable facts at session end. Add: "If `.agentic/tasks.jsonl` exists and has entries from the current session, note the final task statuses (done/blocked/failed counts) in the session wrap summary. Do not copy task entries into MEMORY.md - they are already durable in the file."

9. **Docs and slides** - UPDATE REQUIRED.
   - **`docs/agentic-engineering.html`** - Add a brief mention of `.agentic/tasks.jsonl` as the task coordination surface for multi-unit orchestration. This is infrastructure-level - a sentence or bullet, not a prominent feature callout.
   - **`docs/slides/how-it-works-slides.md`** - If a parallel fan-out slide is added (per P1 fan-out plan), the task-state file is best documented there as the coordination layer rather than as a standalone slide. No independent update needed unless the fan-out deck is not created.
   - **New deck:** No standalone deck warranted for the task-state file itself. It is supporting infrastructure for fan-out - document it within the fan-out deck (`parallel-fanout-slides.md` if created).

8. **`content/agents/engineer.md`** - UPDATE REQUIRED. The engineer agent definition must be updated to describe the task-state write responsibility: when spawned via `/implement-ticket` Phase 5 with a `task_id` and `task_state_file` in the execution contract block, the engineer writes its result entry to the task-state file before returning its final summary. The write protocol (lock acquire, append, lock release) and the partial entry schema (`task_id`, `session_id`, `updated_at`, `status`, `outputs` fields) must be included in or referenced from the engineer agent definition so that an engineer spawned from its definition knows to perform this step. The `task_state_file` value in the execution contract block is an absolute path - the engineer must use it verbatim (not a relative path) because the engineer runs from the worktree root where `.agentic/` does not exist.

---

## Edge cases and failure modes

**1. Worker dies mid-write (partial JSONL line).** The conductor reads all lines at session start. If a line is not valid JSON, it is skipped with a warning. The task it represents remains in its last-known conductor-written state (typically `in_progress`). The conductor treats it as an orphaned task per the "file present, different session" rules - surfaces to the human for direction. No data loss: the conductor's initial `pending` entry for that task is still in the file.

**2. Two workers race to write for the same `task_id`.** Should not happen in a correct implementation (one worker per task), but if it does, both entries are appended. The conductor's field-level merge algorithm applies normally: fields from both entries are merged in file order, with later non-null values overwriting earlier ones. The conductor logs a warning if it detects multiple worker-written entries for the same `task_id` (i.e., two entries each containing `outputs` fields).

**3. Lock held by a dead worker (session killed during write).** The lock directory `.agentic/tasks.lock` persists after the write fails. The next writer detects the lock directory, hits the 30-second timeout, writes without the lock (with a warning), and continues. The conductor, at session start, checks for a stale lock (created more than 5 minutes ago based on filesystem mtime) and removes it before any writes. Stale lock detection (portable, works on macOS and Linux via GNU/BSD find): `find .agentic/tasks.lock -maxdepth 0 -type d -mmin +5 -exec rmdir {} \; 2>/dev/null`. Note: `stat -f %m` (macOS) and `stat -c %Y` (Linux) are platform-specific alternatives; the `find -mmin` form above is portable and preferred.

**4. File exists but is from a completely different project.** The conductor checks that the first entry's `ticket_id` (or `task_id` prefix) is plausibly related to the current context. If not, it warns and asks the human whether to archive it. It does not silently overwrite or ignore it. In practice, since `.agentic/` is at the repo root and gitignored, this can only happen if someone manually copied the file - a rare scenario.

**5. Worktree path in `outputs` does not exist at session resume.** When P2 resume logic reads `worktree_path` from a prior session's task entry, the worktree may have been cleaned up (removed by the prior session's Phase 5 cleanup, or by the human manually). P2 resume logic must check for worktree existence before attempting to read it. This is a P2 concern; P1 only writes the path, it does not read it for resume.

**6. Tasks with circular dependencies.** If the orchestration-planner (incorrectly) produces a plan where task A `depends_on` task B and task B `depends_on` task A, the conductor would deadlock (neither can start). The conductor must check for cycles when reading the task entries at session start. Cycle detection is a simple DFS on the `depends_on` graph. If a cycle is found, the conductor surfaces it as a plan error and stops, requiring human correction. It does not attempt to auto-resolve.

**7. Task count mismatch between orchestration plan and file entries.** If the orchestration plan identified 3 tasks but the file has only 2 entries (conductor was interrupted during file initialization), the conductor detects the gap by comparing the plan's task list against the file. It appends the missing entries (status `pending`) and proceeds. This is safe because `pending` tasks with no `in_progress` or `done` state are no-ops to re-create.

**8. Single-unit tasks (no parallelism).** For single-engineer, single-unit tasks, the conductor does not need `.agentic/tasks.jsonl` - there is nothing to coordinate. Creating a single-entry task file for a one-shot engineer spawn adds overhead without benefit. Rule: only initialize `.agentic/tasks.jsonl` when the orchestration plan identifies 2 or more tasks. For single-unit plans, the conductor operates as today (in-context state only). This also avoids cluttering `.agentic/` for simple tickets.

---

## Open questions

1. **Should workers write to the task file directly, or return a structured result that the conductor writes?** The current design has workers write directly (with the lock protocol). An alternative is workers return structured JSON in their summary text, and the conductor parses and writes it. Worker-writes are lower conductor context pressure (results are durable even if the conductor is context-heavy); conductor-writes are simpler and eliminate the lock entirely. Tradeoff: worker-writes require workers to have write access to `.agentic/` (a permission grant), which may not hold in all execution environments. **Needs human decision before implementation.**

2. **Should the task file be per-ticket or a single project-wide accumulator?** The current design uses a single accumulator (all tickets append to one file). An alternative is one file per ticket invocation: `.agentic/tasks-ENG-42.jsonl`. Per-ticket files eliminate the need for `ticket_id` filtering and make resume unambiguous. Single-file accumulates history naturally. The multi-file approach also interacts better with P2 resume (no need to search for the right file). **Needs human decision.**

3. **Should the orchestration-planner output a structured task list (JSON) in addition to its current prose plan, to make conductor task-entry creation deterministic?** Currently the planner outputs a Markdown plan; the conductor must parse it to extract task IDs, scopes, and dependencies. Adding a machine-readable section (e.g., a JSONL block at the end of the plan) would make task-entry creation reliable. This is a planner output format change. **Needs human decision.**

4. **Should the task file be the source of truth for Phase 5 parallelism decisions, or remain advisory?** In this design, `depends_on` is the coordinator, but the conductor still makes the final spawn decision. An alternative model (closer to OMC's `team-plan -> team-exec`) would have the conductor always consult the file for which tasks are ready to spawn. This is a more autonomous model. The current design keeps the conductor in control; the file is an audit trail, not a scheduler. **Architectural decision - recommend conservative (conductor-in-control) for P1, revisit at P2.**

5. **How should the file behave in a team setting (multiple humans sharing a repo)?** If two humans are each running conductors against the same repo simultaneously, their workers could both write to the same file. The lock protocol handles the write atomicity, but the `ticket_id` scoping does not prevent one conductor from reading the other's entries. This is a team coordination problem outside the scope of P1 (which assumes solo/pair workflow per the repo's stated target audience). **Defer to P2 or beyond.**
