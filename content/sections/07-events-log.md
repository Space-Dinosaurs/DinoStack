## Events log

`.agentic/events.jsonl` is an optional per-project structured event log. The conductor appends one line per orchestration boundary (worker spawn, worker return, Skeptic finding/sign-off, QA result, /wrap completion, finding fix). The file is gitignored.

**Single-writer scope: the conductor is the sole writer of `.agentic/events.jsonl`.** Subagents do not write to it. Other `.agentic/` files retain their own writers (qa.md by qa-engineer, tasks.jsonl by conductor, loop-state.json by conductor + Stop hook). The single-writer claim is scoped to events.jsonl only.

**Schema** (one JSON object per line):
- `ts`: ISO8601 UTC timestamp (required)
- `phase`: orchestration phase label (required)
- `event`: event type (required)
- `agent`: spawned agent name, nullable
- `task_id`: correlation id when scoped to tasks.jsonl, nullable
- `data`: free-form object for event-specific fields

**Append discipline**: plain shell `>>` append. No fsync, no tmp+rename, no lock file. Single-writer-by-protocol means contention is structurally impossible. If a partial line ever appears (impossible under single-writer but for robustness), readers tolerate it - JSONL parsers skip malformed lines.

**Atomicity**: best-effort. Records are not size-bounded. Catastrophic events during write may leave a truncated line. Documented honestly; not load-bearing.

**Retention**: not auto-rotated. Manual `mv` to `events-prev.jsonl` if a file grows past concern. Project-local; gitignored; ~50KB per session is the operating budget.

**Consumer**: optional. /wrap may consult events.jsonl as supplementary signal for the structural session skeleton. Conversation-memory review remains primary. /wrap on a project with no events.jsonl works exactly as today.

Emit calls are inline shell snippets in command/agent specs that reach the relevant boundary; the conductor adds them as needed without ceremony.
