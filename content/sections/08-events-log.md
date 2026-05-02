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

**V1 telemetry event types** (cost & latency observability; see `bin/agentic-emit`, `bin/agentic-parse-subagent-usage`, `bin/agentic-cost`):
- `spawn_start`: emitted by the conductor immediately before a Task tool call for engineer/skeptic/qa-engineer. `data` carries `tier`, `tool_use_id`, and `agent_id: null` (Claude Code assigns the agent id after the Task returns).
- `spawn_complete`: emitted by the conductor immediately after a Task tool call returns. `data` carries `tier`, `tool_use_id`, `agent_id`, `model`, `wall_seconds`, `tokens` (`input`, `output`, `cache_creation`, `cache_read` - kept separate because they price differently), and `status`.
  - **Skeptic-specific calibration fields** (when `agent == "skeptic"`): `data` additionally carries `findings_count` (`{critical, major, minor}`), `diff_lines` (integer; lines reviewed), `signed_off` (boolean), `iteration` (integer; loop iteration when sign-off occurred), and `meta_review` (always `null` at emission time; populated retroactively only via the separate `meta_review_complete` event below). The conductor constructs the merged `data` object inline before calling `bin/agentic-emit`; meta-Skeptic and the original Skeptic do NOT write to `.agentic/`. See `content/references/skeptic-protocol.md` Section 14 for the calibration mechanism specification.
- `conductor_direct`: emitted by the conductor when it edits directly under the Trivial path or answers from context. `data` carries `wall_seconds` and a `note`; tokens are zero in V1 (the conductor cannot read its own usage from inside the session - documented gap).
- `meta_review_complete`: emitted by the conductor when a sampled meta-Skeptic returns its textual divergence report. `agent == "skeptic-meta"`. `data` carries `original_task_id` (the task_id of the original Skeptic spawn under review), `divergence` (`{critical_missed, major_missed, minor_missed}` - each a list of finding titles), and `agreement` (boolean). The conductor parses meta-Skeptic's return text and constructs this payload itself; meta-Skeptic does not touch `.agentic/`. See `content/references/skeptic-protocol.md` Section 14.
- `session_total`: emitted exactly once per session by the Stop hook. `data` carries `wall_seconds`, summed `tokens`, `spawn_count`, and a `by_agent` rollup.

**Append discipline**: plain shell `>>` append. No fsync, no tmp+rename, no lock file. Single-writer-by-protocol means contention is structurally impossible. If a partial line ever appears (impossible under single-writer but for robustness), readers tolerate it - JSONL parsers skip malformed lines.

**Atomicity**: best-effort. Records are not size-bounded. Catastrophic events during write may leave a truncated line. Documented honestly; not load-bearing.

**Retention**: not auto-rotated. Manual `mv` to `events-prev.jsonl` if a file grows past concern. Project-local; gitignored; ~50KB per session is the operating budget.

**Consumer**: optional. /wrap may consult events.jsonl as supplementary signal for the structural session skeleton. Conversation-memory review remains primary. /wrap on a project with no events.jsonl works exactly as today.

Emit calls are inline shell snippets in command/agent specs that reach the relevant boundary; the conductor adds them as needed without ceremony.
