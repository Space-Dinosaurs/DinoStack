<!--
Purpose: Full reference for the task-state file protocol used in multi-unit
         /implement-ticket orchestration. Covers .agentic/tasks.jsonl schema,
         lifecycle (initialization, spawn update, return update, terminal status),
         sole-writer contract, and when task-state is skipped (single-unit plans).

Public API: Read-only reference document. Cross-referenced from:
            content/sections/08-task-state-file.md (parent section; pointer
            replaces body after kernel split);
            content/sections/12-protocol-details.md (Protocol Details entry).

Upstream deps: content/sections/08-task-state-file.md (parent section);
               content/commands/implement-ticket.md (Phase 3b Task-state
               initialization and Phase 5 where the conductor writes entries).

Downstream consumers: conductor (sole writer of tasks.jsonl); engineer Workers
                      (receive task_id for identification only, never write);
                      /implement-ticket Phase 5 (correlates worker returns with
                      task entries).

Failure modes: Prose; does not execute. Single-unit plans skip task-state
               entirely; no file is created and no lock is needed.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Task-state file. Read that section first for the full context of when task-state is used.

# Task-State File - Full Reference

## Task-state file body

When `/implement-ticket` operates on a multi-unit plan (2 or more tasks), the conductor initializes `.agentic/tasks.jsonl` with one entry per task before spawning any workers and maintains it throughout the orchestration lifecycle - updating entries at spawn time (`pending` -> `in_progress`), after each worker returns (output fields populated), and after Skeptic/QA resolution (terminal status set). Workers receive `task_id` in the execution contract for identification purposes only; the conductor handles all reads and writes - no lock protocol is needed because the conductor is the sole writer. Single-unit plans skip task-state entirely (in-context state only). For the full protocol - schema, file-absent/present behavior, orphan detection, and field-level merge algorithm - see `/implement-ticket` Phase 3b (Task-state initialization) and Phase 5.
