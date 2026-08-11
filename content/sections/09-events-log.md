## Events log

`.agentic/events.jsonl` is an optional per-project structured event log. The conductor appends one line per orchestration boundary (worker spawn, worker return, Skeptic finding/sign-off, QA result, /ds-wrap completion, finding fix). The file is gitignored.

**Writer scope: `.agentic/events.jsonl` has four writers** - the conductor (inline appends at each orchestration boundary), the Stop hook (`hooks/stop-context.js`, a `session_total` event on every TURN), and the two spawn-telemetry hooks that fire mid-turn: `hooks/pre-tool-use-spawn-emit.js` (`spawn_start` on every subagent spawn) and `hooks/subagent-stop-spawn-emit.js` (`spawn_complete` on every subagent completion, added DS-160). Safety comes from append-only writes - no writer rewrites the file - not turn timing. Subagent agents never write to it themselves; only these hooks do, on their behalf. Other `.agentic/` files retain their own writers (qa.md by conductor, tasks.jsonl by conductor, the per-ticket `loop-state-<LOOP_KEY>.json` and the legacy `loop-state.json` by conductor + Stop hook (per-turn liveness refresh) + SessionEnd hook (terminal interrupted-mark)).

**Schema** (one JSON object per line):
- `ts`: ISO8601 UTC timestamp (required)
- `phase`: orchestration phase label (required)
- `event`: event type (required)
- `agent`: spawned agent name, nullable
- `task_id`: correlation id when scoped to tasks.jsonl, nullable
- `data`: free-form object for event-specific fields

For the full V1 telemetry event-type schemas (field-level `data` shapes for `spawn_start`, `spawn_complete`, `meta_review_complete`, `session_total`, `tool_failure_workaround`), per-developer session log, pending-buffer, `session_uuid`, append discipline, atomicity, retention, and consumer notes, see `content/references/events-log.md`. (`conductor_direct` is deprecated and no longer emitted; its schema is preserved there for historical reference.)

Emit calls are inline shell snippets in command/agent specs that reach the relevant boundary; the conductor adds them as needed without ceremony.
