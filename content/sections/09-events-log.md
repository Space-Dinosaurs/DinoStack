## Events log

`.agentic/events.jsonl` is an optional per-project structured event log. The conductor appends one line per orchestration boundary (worker spawn, worker return, Skeptic finding/sign-off, QA result, /wrap completion, finding fix). The file is gitignored.

**Writer scope: the conductor is the primary writer of `.agentic/events.jsonl`.** The Stop hook (`hooks/stop-context.js`) appends a single `session_total` event at session exit; this is sanctioned because the conductor turn has ended by the time the hook fires, so there is no contention. Subagents do not write to it. Other `.agentic/` files retain their own writers (qa.md by qa-engineer, tasks.jsonl by conductor, loop-state.json by conductor + Stop hook).

**Schema** (one JSON object per line):
- `ts`: ISO8601 UTC timestamp (required)
- `phase`: orchestration phase label (required)
- `event`: event type (required)
- `agent`: spawned agent name, nullable
- `task_id`: correlation id when scoped to tasks.jsonl, nullable
- `data`: free-form object for event-specific fields

For the full V1 telemetry event-type schemas (field-level `data` shapes for `spawn_start`, `spawn_complete`, `conductor_direct`, `meta_review_complete`, `session_total`, `tool_failure_workaround`), per-developer session log, pending-buffer, `session_uuid`, append discipline, atomicity, retention, and consumer notes, see `content/references/events-log.md`.

Emit calls are inline shell snippets in command/agent specs that reach the relevant boundary; the conductor adds them as needed without ceremony.
