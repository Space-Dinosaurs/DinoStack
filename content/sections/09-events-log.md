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

Additionally, the Stop hook writes a one-line per-session rollup to `.agentic/session-log/<developer_id>.jsonl` - a committed per-developer surface for team-level aggregation. See `content/references/events-log.md` "Per-developer session log" for the schema.

**Pending-buffer (pre-attribution staging).** When no confirmed identity exists at session exit - i.e., `agentic-identity init` has not yet been run - the Stop hook writes the session telemetry record to `~/.agentic/session-log/.pending/<session_uuid>.json` instead of a named per-developer log. This file is a staging area only: it is not an `events.jsonl` event type, it is not read by `agentic-cost`, and it carries no `developer_id` field. When the user later runs `agentic-identity confirm` or `agentic-identity init <handle>`, the identity layer flushes all pending records, stamps each with the confirmed handle, and appends them to the appropriate per-project and global session-log files as if they had been written at session time.

For the full V1 telemetry event-type schemas (field-level `data` shapes for `spawn_start`, `spawn_complete`, `conductor_direct`, `meta_review_complete`, `session_total`), append discipline, atomicity, retention, and consumer notes, see `content/references/events-log.md`.

Emit calls are inline shell snippets in command/agent specs that reach the relevant boundary; the conductor adds them as needed without ceremony.
