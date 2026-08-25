<!-- corpora: minimal medium full -->
## Events log

`.agentic/events.jsonl` is an optional per-project structured event log. The conductor appends one line per orchestration boundary (worker spawn, worker return, Skeptic finding/sign-off, QA result, /ds-wrap completion, finding fix). The file is gitignored.

**Writer scope: `.agentic/events.jsonl` has six writers** - the conductor (appends per orchestration boundary), the Stop hook (`hooks/stop-context.js`, `session_total` per turn), two mid-turn spawn hooks (`hooks/pre-tool-use-spawn-emit.js`: `spawn_start`; `hooks/subagent-stop-spawn-emit.js`: `spawn_complete`, DS-160), the warn-only Stop hook `hooks/conductor-overreach-nudge.js` (`conductor_overreach`, only on `ratio_trigger`), and `bin/ds-agentic-repair --fix` (operator-invoked, not a hook - dedup-appends a phantom tree's events.jsonl, order-preserving). Append-only writes (not turn timing) give safety; only these hooks write on subagents' behalf. Other `.agentic/` files: qa.md, tasks.jsonl by conductor; `loop-state-<LOOP_KEY>.json`/legacy `loop-state.json` by conductor + Stop hook (liveness refresh) + SessionEnd hook (interrupted-mark).

**Schema** (one JSON object per line):
- `ts`: ISO8601 UTC timestamp (required)
- `phase`: orchestration phase label (required)
- `event`: event type (required)
- `agent`: spawned agent name, nullable
- `task_id`: correlation id when scoped to tasks.jsonl, nullable
- `data`: free-form object for event-specific fields

For the full V1 telemetry event-type schemas (field-level `data` shapes for `spawn_start`, `spawn_complete`, `meta_review_complete`, `session_total`, `tool_failure_workaround`, `tracker_writeback`, `conductor_overreach`), per-developer session log, pending-buffer, `session_uuid`, append discipline, atomicity, retention, and consumer notes, see `content/references/events-log.md`. (`conductor_direct` is deprecated and no longer emitted; its schema is preserved there for historical reference.)

Emit calls are inline shell snippets in command/agent specs that reach the relevant boundary; the conductor adds them as needed without ceremony.
