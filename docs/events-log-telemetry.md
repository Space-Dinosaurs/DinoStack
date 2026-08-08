<!--
Purpose: Operator-facing guide to .agentic/events.jsonl - the structured
         event log that records orchestration boundaries. Covers the base
         schema, main event types, who writes what, and how ds-cost
         consumes the data. Complements docs/identity-telemetry.md (which
         covers identity setup, not the event data model).

Public API: Operator-facing prose. Entry point for operators who want to
            understand what is being logged, consume the log themselves,
            or troubleshoot ds-cost output.
            The full V1 event-type schemas live in
            content/references/events-log.md.

Upstream deps: content/sections/09-events-log.md (writer scope and base
               schema); content/references/events-log.md (full V1 schemas,
               per-developer session log, append discipline, PII boundary).

See also: docs/identity-telemetry.md (identity setup and ds-cost
          team rollup).

Downstream consumers: docs site root index.

Failure modes: Stale if new event types are added, field names change, or
               the per-developer session log schema changes. Update alongside
               content/references/events-log.md.

Performance: Standard.
-->

# Events log telemetry

`.agentic/events.jsonl` is a per-project structured log of orchestration
boundaries. It is optional, gitignored, and written locally - no data leaves
the machine. `ds-cost` reads it to produce token and wall-time reports.

For identity setup (registering a developer handle so sessions are attributed
correctly), see [docs/identity-telemetry.md](identity-telemetry.md).

## Base schema

Each line is one JSON object:

```json
{
  "ts":      "2026-05-28T12:00:00Z",
  "phase":   "worker-spawn",
  "event":   "spawn_start",
  "agent":   "engineer",
  "task_id": "task-001",
  "data":    { ... }
}
```

| Field | Required | Notes |
|---|---|---|
| `ts` | yes | ISO8601 UTC timestamp |
| `phase` | yes | Orchestration phase label (e.g. `worker-spawn`, `session_end`) |
| `event` | yes | Event type (see below) |
| `agent` | - | Spawned agent name; `null` when not agent-scoped |
| `task_id` | - | Correlation id for multi-unit plans; matches `.agentic/tasks.jsonl`; `null` otherwise |
| `data` | - | Free-form object with event-specific fields |

## Who writes what

**The conductor** is the primary writer. It appends one line at each
orchestration boundary: worker spawn, worker return, Skeptic finding/sign-off,
QA result, /ds-wrap completion, finding fix.

**The Stop hook** (`hooks/stop-context.js`) appends a single `session_total`
event at session exit. This is the only sanctioned non-conductor writer;
because the conductor turn has already ended when the hook fires, there is no
contention.

Subagents do not write to `events.jsonl`.

## Event types

### spawn_start

Emitted immediately before an `Agent` tool call for engineer, skeptic, or
qa-engineer.

Key `data` fields: `tier`, `tool_use_id`, `agent_id` (null at emission;
Claude Code assigns it after the spawn returns), `session_uuid`.

### spawn_complete

Emitted immediately after an `Agent` tool call returns.

Key `data` fields: `tier`, `tool_use_id`, `agent_id`, `model`,
`wall_seconds`, `tokens` (`input`, `output`, `cache_creation`, `cache_read`),
`status`, `session_uuid`.

When `agent == "skeptic"`, additional calibration fields are present:
`findings_count` (`{critical, major, minor}`), `diff_lines`, `signed_off`,
`iteration`.

### session_total

Emitted exactly once per session by the Stop hook.

Key `data` fields: `wall_seconds`, summed `tokens`, `spawn_count`,
`by_agent` rollup (per-agent `spawns`, `wall_seconds`, `tokens_total`).

This event is also mirrored to `.agentic/session-log/<developer_id>.jsonl`
for team rollup via `ds-cost team`.

### meta_review_complete

Emitted when a sampled meta-Skeptic returns a divergence report.
`agent == "skeptic-meta"`.

Key `data` fields: `original_task_id`, `divergence` (`{critical_missed,
major_missed, minor_missed}`), `agreement`, `session_uuid`.

### tool_failure_workaround

Emitted when the conductor resolves a tool or command failure via retry or
workaround.

Key `data` fields: `tool` (tool or command name - no args, no secrets),
`domain_tag` (short domain label), `note` (one sentence describing the
workaround - no file contents, no output, no secrets), `session_uuid`.

This feeds the skill-candidate detection system. See
[docs/skill-candidates.md](skill-candidates.md).

## ds-cost

`ds-cost` reads `events.jsonl` and the per-developer session logs to
produce token and wall-time reports.

```bash
ds-cost            # current session summary
ds-cost team       # per-developer rollup across all committed session logs
```

Session logs at `.agentic/session-log/<developer_id>.jsonl` are committed to
git via `/ds-implement-ticket` Phase 8 (when `commit_telemetry: true` and
identity is confirmed). `ds-cost team` therefore reflects sessions from
all developers whose telemetry has landed on the branch via pull after merge.

## Practical notes

**Append discipline.** Plain shell `>>` append. No fsync, no lock file.
Single-writer-by-protocol means contention is structurally impossible.

**Retention.** Not auto-rotated. Manual `mv events.jsonl events-prev.jsonl`
if the file grows past concern. Roughly 50 KB per active session.

**PII boundary.** Only structured fields are written. Excluded: prompt
content, file paths in tool I/O, user messages, finding text, task
descriptions, commit messages, environment variable values.

**No events.jsonl.** `/ds-wrap` works normally on projects with no events log.
The log is supplementary signal for the session skeleton, not required.

## Related references

- `content/references/events-log.md` - full V1 event-type schemas with
  field-level `data` shapes, session-log schema, append discipline,
  atomicity, retention, and PII boundary
- `content/sections/09-events-log.md` - writer scope and base schema
  (the section that events-log.md expands)
- `docs/identity-telemetry.md` - identity setup and ds-cost team
  rollup (the prerequisite for attributed session logs)
- `docs/skill-candidates.md` - how tool_failure_workaround events feed
  the skill-candidate detection system
