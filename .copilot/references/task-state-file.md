<!--
Purpose: Full reference for the task-state file (.agentic/tasks.jsonl)
         extracted from content/sections/08-task-state-file.md. Contains:
         multi-unit plan initialization and maintenance lifecycle; conductor-
         sole-writer invariant; single-unit skip rule; protocol cross-
         reference (/implement-ticket Phase 3b and Phase 5); and the
         author_model field (model id for reviewer-diversity routing).

Public API: Read-only reference document. Cross-referenced from:
            content/sections/08-task-state-file.md (parent section);
            content/sections/12-protocol-details.md (Task-state file
            Protocol Details entry).

Upstream deps: content/sections/08-task-state-file.md (parent section);
               /implement-ticket Phase 3b (task-state initialization schema,
               file-absent/present behavior, orphan detection, field-level
               merge algorithm) and Phase 5 (task_id correlation, author_model
               recording); content/agents/skeptic.md and
               content/agents/security-auditor.md (reviewer-diversity prose
               that consumes author_model).

Downstream consumers: conductor (/implement-ticket multi-unit orchestration;
                      reads and writes tasks.jsonl as sole writer); engineer
                      agents (receive task_id in execution contract for
                      identification only - never write to tasks.jsonl);
                      skeptic / security-auditor (read author_model before
                      selecting their own model).

Failure modes: tasks.jsonl is NOT gitignored (unlike loop-state.json) but
               should not carry sensitive data. Single-unit plans skip this
               file entirely. Workers must never write to tasks.jsonl - only
               the conductor writes; no lock protocol is needed because of
               this sole-writer invariant.

Performance: Standard (local JSONL append/read; no network).
-->

> Parent section: `content/sections/08-task-state-file.md`. This file contains the complete body of that section verbatim.

## Task-state file

When `/implement-ticket` operates on a multi-unit plan (2 or more tasks), the conductor initializes `.agentic/tasks.jsonl` with one entry per task before spawning any workers and maintains it throughout the orchestration lifecycle - updating entries at spawn time (`pending` -> `in_progress`), after each worker returns (output fields populated), and after Skeptic/QA resolution (terminal status set). Workers receive `task_id` in the execution contract for identification purposes only; the conductor handles all reads and writes - no lock protocol is needed because the conductor is the sole writer. Single-unit plans skip task-state entirely (in-context state only). For the full protocol - schema, file-absent/present behavior, orphan detection, and field-level merge algorithm - see `/implement-ticket` Phase 3b (Task-state initialization) and Phase 5.

**Field: `author_model`** (string, nullable). The model id the implementing
engineer ran under for this task, or `null` when unknown (single-unit plans,
pre-P249 historical entries, or conductor-directed spawns where the model was
not recorded). Consumed by reviewer spawns (Skeptic, security-auditor) to pick
a different model when role-model routing is active -- reviewer-diversity
prose lives in `content/agents/skeptic.md` and `content/agents/security-auditor.md`.
The conductor records `author_model` at engineer spawn time (Phase 5) and
reviewer spawns read it before selecting their own model; the conductor remains
the sole writer of `.agentic/tasks.jsonl`.
