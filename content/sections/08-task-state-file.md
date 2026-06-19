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
