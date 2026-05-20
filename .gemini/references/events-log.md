<!--
Purpose: Full reference for the events log V1 telemetry event-type schemas and
         operational notes extracted from METHODOLOGY.md §Events log. Contains
         field-level data shapes for all 5 event types, plus append discipline,
         atomicity, retention, and consumer notes.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/08-events-log.md (pointer after Schema block),
            content/sections/11-protocol-details.md (Events log Protocol Details entry).

Upstream deps: content/sections/08-events-log.md (parent section; read that
               section first for writer scope and base schema);
               bin/agentic-emit, bin/agentic-parse-subagent-usage, bin/agentic-cost
               (the consumers of these event schemas);
               content/references/skeptic-protocol.md Section 14
               (calibration mechanism specification for Skeptic-specific fields).

Downstream consumers: conductor (constructs spawn_start/spawn_complete/conductor_direct
                      payloads at orchestration boundaries);
                      Stop hook (constructs session_total payload at session exit);
                      /wrap command (reads events.jsonl for structural session skeleton).

Failure modes: Prose; does not execute. Schema drift between this reference and
               the actual event payloads emitted by the conductor causes
               bin/agentic-cost and bin/agentic-parse-subagent-usage to silently
               miscount or drop records.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Events log. Read that section first for writer scope and base schema.

# Events Log - Full Reference

## V1 telemetry event types

(Cost & latency observability; see `bin/agentic-emit`, `bin/agentic-parse-subagent-usage`, `bin/agentic-cost`.)

- `spawn_start`: emitted by the conductor immediately before a Task tool call for engineer/skeptic/qa-engineer. `data` carries `tier`, `tool_use_id`, and `agent_id: null` (Claude Code assigns the agent id after the Task returns).
- `spawn_complete`: emitted by the conductor immediately after a Task tool call returns. `data` carries `tier`, `tool_use_id`, `agent_id`, `model`, `wall_seconds`, `tokens` (`input`, `output`, `cache_creation`, `cache_read` - kept separate because they price differently), and `status`.
  - **Skeptic-specific calibration fields** (when `agent == "skeptic"`): `data` additionally carries `findings_count` (`{critical, major, minor}`), `diff_lines` (integer; lines reviewed), `signed_off` (boolean), `iteration` (integer; loop iteration when sign-off occurred), and `meta_review` (always `null` at emission time; populated retroactively only via the separate `meta_review_complete` event below). The conductor constructs the merged `data` object inline before calling `bin/agentic-emit`; meta-Skeptic and the original Skeptic do NOT write to `.agentic/`. See `content/references/skeptic-protocol.md` Section 14 for the calibration mechanism specification.
- `conductor_direct`: emitted by the conductor when it edits directly under the Trivial path or answers from context. `data` carries `wall_seconds` and a `note`; tokens are zero in V1 (the conductor cannot read its own usage from inside the session - documented gap).
- `meta_review_complete`: emitted by the conductor when a sampled meta-Skeptic returns its textual divergence report. `agent == "skeptic-meta"`. `data` carries `original_task_id` (the task_id of the original Skeptic spawn under review), `divergence` (`{critical_missed, major_missed, minor_missed}` - each a list of finding titles), and `agreement` (boolean). The conductor parses meta-Skeptic's return text and constructs this payload itself; meta-Skeptic does not touch `.agentic/`. See `content/references/skeptic-protocol.md` Section 14.
- `session_total`: emitted exactly once per session by the Stop hook. `data` carries `wall_seconds`, summed `tokens`, `spawn_count`, and a `by_agent` rollup.

## Append discipline

Plain shell `>>` append. No fsync, no tmp+rename, no lock file. Single-writer-by-protocol means contention is structurally impossible. If a partial line ever appears (impossible under single-writer but for robustness), readers tolerate it - JSONL parsers skip malformed lines.

## Atomicity

Best-effort. Records are not size-bounded. Catastrophic events during write may leave a truncated line. Documented honestly; not load-bearing.

## Retention

Not auto-rotated. Manual `mv` to `events-prev.jsonl` if a file grows past concern. Project-local; gitignored; ~50KB per session is the operating budget.

## Consumer

Optional. /wrap may consult events.jsonl as supplementary signal for the structural session skeleton. Conversation-memory review remains primary. /wrap on a project with no events.jsonl works exactly as today.
