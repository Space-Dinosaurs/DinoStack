<!--
Purpose: Full reference for the task-state file (.agentic/tasks.jsonl)
         extracted from content/sections/08-task-state-file.md. Contains:
         multi-unit plan initialization and maintenance lifecycle; the
         append-only write contract and the task-state fold (the single
         normative definition of how per-task_id records combine into a
         folded owner/status/fields triple); the read-time ownership gate;
         single-unit skip rule; protocol cross-reference (/ds-implement-ticket
         Phase 3b and Phase 5); and the author_model field (model id for
         reviewer-diversity routing).

Public API: Read-only reference document. Cross-referenced from:
            content/sections/08-task-state-file.md (parent section);
            content/sections/12-protocol-details.md (Task-state file
            Protocol Details entry).

Upstream deps: content/sections/08-task-state-file.md (parent section);
               /ds-implement-ticket Phase 3b (task-state initialization
               schema, file-absent/present behavior, orphan detection, the
               task-state fold) and Phase 5 (task_id correlation, author_model
               recording); content/agents/skeptic.md and
               content/agents/security-auditor.md (reviewer-diversity prose
               that consumes author_model); bin/tests/fold_model.py (the
               executable reference implementation of the fold - the prose
               below is a reading aid, not a second specification; where the
               two disagree, fold_model.py wins).

Downstream consumers: conductor (/ds-implement-ticket multi-unit orchestration;
                      appends to and folds tasks.jsonl - never a writer that
                      rewrites); engineer agents (receive task_id in
                      execution contract for identification only - never
                      write to tasks.jsonl); skeptic / security-auditor (read
                      author_model before selecting their own model);
                      /ds-implement-ticket Phase 9 (reads author_model for the
                      PR body Model: attribution line beside Developer:).

Failure modes: tasks.jsonl IS gitignored, like other .agentic/ state files
               (see ds-init-project.md's scaffolded .gitignore block and
               docs/secrets-and-permissions.md) but should not carry
               sensitive data. Single-unit plans skip this file entirely.
               Workers must never write to tasks.jsonl - only the conductor
               writes, and every conductor write is a single-line append.
               No lock is needed because no writer ever rewrites the file;
               concurrent-session safety comes from append-only writes plus
               the task-state fold at read time, not from write exclusion.

Performance: Standard (local JSONL append/read; no network).
-->

> Parent section: `content/sections/08-task-state-file.md`. This file contains the complete body of that section verbatim.

## Task-state file

When `/ds-implement-ticket` operates on a multi-unit plan (2 or more tasks), the conductor initializes `.agentic/tasks.jsonl` with one entry per task before spawning any workers and maintains it throughout the orchestration lifecycle by **appending** transition records - at spawn time (`pending` -> `in_progress`), after each worker returns (output fields populated), and after Skeptic/QA resolution (terminal status set). Workers receive `task_id` in the execution contract for identification purposes only; the conductor handles all reads and writes. Every conductor write is a single-line append; every read applies the **task-state fold** (defined below). No lock is needed because no writer ever rewrites the file - concurrent-session safety comes from the append-only write contract plus the fold, not from write exclusion. Single-unit plans skip task-state entirely (in-context state only). For the full protocol - schema, file-absent/present behavior, orphan detection, and the task-state fold - see `/ds-implement-ticket` Phase 3b (Task-state initialization) and Phase 5.

### The invariant set (normative)

Every rule below exists to hold one of these five invariants. They are stated first because a fold specified only as field rules, with no statement of what the rules are *for*, is the failure mode this document exists to close - the next edit to any one rule has nothing to check itself against.

- **I1 - Single merger.** At most one session ever merges a given unit.
- **I2 - No fictitious record.** The folded record never pairs fields originating in different generations; in particular a folded `done` and the `branch_name` / `commit_sha` / `outputs.skeptic_status` beside it always originate in the same `session_id`.
- **I3 - No post-terminal ownership change.** Once a group's folded status is `done`, no later record changes the folded `session_id`.
- **I4 - No unowned status transition.** A folded non-claim status transition is always attributable to the session that was the folded owner immediately before that record landed. A claim (`status: in_progress`) is the sanctioned exception - it *transfers* ownership - and is admissible only while the folded status is not `done`.
- **I5 - Owner-scoped freshness.** The folded `updated_at` is the one carried by the latest arrival-order record of the folded owner. No record from a non-owner can change it - this is what the 10-minute staleness test (below) reads.

I3, I4 and I5 hold by construction of the fold's state machine. I1 and I2 follow from them (a session merges only when the fold reports `owner == self AND status == done`; because the folded pair is stable once `status == done` (I3, I4), and only owner-scoped fields survive a `done` fold (I2's field rule below), a fold can never describe a build that did not happen or let two sessions merge the same unit).

### The task-state fold

**One complete JSON record per line.** Every conductor write builds the full record in memory and appends it with **one** `write()` - `printf '%s\n' "$LINE" >> .agentic/tasks.jsonl` - never composed from multiple writes, and never a rewrite. The sole exception is the operator-confirmed restart path (Phase 3b), which renames the file to a `.bak` and starts fresh; nothing else in this design truncates. A transition record carries `task_id`, `session_id`, `updated_at`, and only the fields that changed - never the full `inputs` object on a partial append. `status` appears in a record **only when the status actually changes**: an output-only append carries no `status` field at all, because an ownership claim is defined as an `in_progress` append, and re-emitting `status` on an output append would let a dispossessed session silently reclaim ownership by returning its engineer's outputs.

The fold consumes a `task_id` group's records **in arrival order** (the order they were appended to the file - never `updated_at`, which is not a reliable ordering key: a record can arrive late but carry an earlier timestamp, which is not prefix-monotonic and would let the past be rewritten) and carries the running state `(owner, status, fields)`:

- The earliest record bootstraps `owner := record.session_id` (the fallback when no record has claimed the task yet). Any later honored claim overrides it.
- A record with `status: in_progress` is a **claim**: it sets `owner := record.session_id` and `status := in_progress` - **unless** the folded status is already `done`, in which case the claim is **not honored** (I3).
- A record carrying any other `status` value is a **transition**, admitted only if `record.session_id == owner` at that point (I4), and ignored if the folded status is already `done` (`done` is absorbing; `failed`/`blocked`/`abandoned` are not, so a partial-success retry can legitimately return a task to `in_progress`).
- A record carrying no `status` field is never a claim and never a transition - it only contributes fields.
- A record carrying **no `session_id`** is **legacy**, not unparseable - the documented schema above has never mandated the field. It folds under a sentinel owner that no session ever matches: no viewer reads a legacy group as its own, no viewer may merge it, and it is always treated as foreign-and-stale (`in_progress` never reads as fresh - an absent id cannot be shown live, and blocking on it would deadlock every pre-fix project).
- **Fields** are field-level last-write-wins, bounded by a **cross-generation whitelist**: `task_id`, `ticket_id`, `unit_slug`, `depends_on`, `created_at`, and `inputs` may cross a `session_id` generation boundary (this is what keeps `inputs` alive across a retry's partial appends - a record-level scheme would lose it on the first partial write and silently break every retry brief). Every other field - including `assigned_agent`, `worktree_path`, `branch_name`, `author_model`, `loop_state`, and every `outputs.*` field - is **session-scoped**: folded only from records whose `session_id` equals the folded owner. This is a whitelist, not a blacklist, deliberately: a field added to the schema later is session-scoped by default rather than crossing generations silently.
- The folded `updated_at` (I5) follows the same session-scoped rule: it is the value carried by the **owner's own latest arrival-order record**, any status, output-only appends included - never the latest record in the group regardless of who wrote it. A foreign stray record must never refresh the incumbent's freshness, or the 10-minute staleness test below would pin forever and block legitimate orphan recovery.

The executable reference implementation is `bin/tests/fold_model.py`, exercised by `bin/tests/test_fold_invariants.py` over 2,400 generated interleavings at 2-5 concurrent sessions plus a dedicated legacy-writer sweep; it is the sole normative definition of the state machine above. Where this prose and `fold_model.py` disagree, `fold_model.py` wins and the prose is the defect.

### Read-time ownership gate (ticketed projects only)

In a null-ticket project (`TRACKER=none`, `task_id = <session_id>-<unit_slug>`) cross-session `task_id`s never collide, so ownership always reads `own` and this gate is structurally inert - append-only still guarantees no state loss, but it provides no duplicate-fan-out protection there.

In a ticketed project, three gate points apply the fold before an ownership-sensitive decision, and nowhere else: **fold-before-spawn** (before every worker spawn - do not spawn on a foreign-and-fresh task, or on a task this session has been dispossessed of), **fold-before-terminal-append** (a dispossessed session must never append a terminal status - `done` is absorbing and would hijack the new owner's task), and **fold-before-merge** (immediately before merging a unit's branch, re-fold and merge **only if `owner == self AND status == done`**). On a foreign-and-fresh (< 10 minutes since the folded `updated_at`) task, emit verbatim:

```
WARNING: task <task_id> is in_progress under another session (session_id=<X>, updated_at=<Y>).
Not spawning. Resolve manually (wait for that session, kill it, or restart task state) and retry.
```

Ownership is **monotonic**: it is claimed only by an `in_progress` append and is never regained once superseded. A session whose claim was superseded cannot silently take a task back by appending outputs or any other later record - it must append a fresh `in_progress` claim through the fold-before-spawn gate, and only when the fold currently permits a spawn for that task.

**Field: `author_model`** (string, nullable). The model id the implementing
engineer ran under for this task, or `null` when unknown (single-unit plans,
pre-P249 historical entries, or conductor-directed spawns where the model was
not recorded). Consumed by reviewer spawns (Skeptic, security-auditor) to pick
a different model when role-model routing is active -- reviewer-diversity
prose lives in `content/agents/skeptic.md` and `content/agents/security-auditor.md`.
The conductor records `author_model` at engineer spawn time (Phase 5) as part
of the ownership claim's append, and reviewer spawns read the folded value
before selecting their own model. `/ds-implement-ticket` Phase 9 also reads the
folded value to emit a `Model:` attribution line beside `Developer:` on the PR
body, so a PR carries the model(s) that produced it.
