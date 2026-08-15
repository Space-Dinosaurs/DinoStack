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

**The Stop hook** (`hooks/stop-context.js`) appends a `session_total` event
on every TURN (it runs once per Stop invocation, which fires on every turn,
not once per session).

The Stop hook is not the only non-conductor writer: `hooks/pre-tool-use-spawn-emit.js`
(`PreToolUse(Task/Agent)`) appends a hook-emitted `spawn_start` mid-turn on
every subagent spawn, and `hooks/subagent-stop-spawn-emit.js` (`SubagentStop`,
DS-160) appends a hook-emitted `spawn_complete` whenever a subagent finishes -
both fire while the conductor's turn is still in progress. A fifth writer,
`hooks/conductor-overreach-nudge.js` (also a Stop hook), appends a
`conductor_overreach` event, but only when its `ratio_trigger` condition
fires - see below.

Subagent agents never emit events themselves; hooks firing on their spawns
and completions do.

## Event types

### spawn_start

Emitted immediately before an `Agent` tool call for engineer, skeptic, or
qa-engineer.

Key `data` fields: `tier`, `tool_use_id`, `agent_id` (null at emission;
Claude Code assigns it after the spawn returns), `session_uuid`.

The hook-emitted variant (`hooks/pre-tool-use-spawn-emit.js`,
`data.source:"hook"`) additionally carries `agentic_root_drift_levels`
(int) and `agentic_root_found_git` (boolean) - diagnostics from
`hooks/lib/repo-root.js`'s `resolveAgenticCwdWithDiagnostics`, which
anchors the `.agentic/` write to the repo root instead of the raw payload
`cwd` (DS-171). `found_git_ancestor:false` means no `.git` ancestor was
found and the write fell back to the payload cwd unchanged.

### spawn_complete

Emitted immediately after an `Agent` tool call returns.

Key `data` fields: `tier`, `tool_use_id`, `agent_id`, `model`,
`wall_seconds`, `tokens` (`input`, `output`, `cache_creation`, `cache_read`),
`status`, `session_uuid`.

When `agent == "skeptic"`, additional calibration fields are present:
`findings_count` (`{critical, major, minor}`), `diff_lines`, `signed_off`,
`iteration`.

**DS-160 hook-emitted variant.** `hooks/subagent-stop-spawn-emit.js`
(`SubagentStop`) also emits a deterministic `spawn_complete` with
`data.source:"hook"`, independent of the conductor-emitted event described
above - both may exist for the same spawn. The hook variant carries
`data.paired_spawn_id`, `data.wall_seconds` (real when paired, `null` if
unmatched or if the paired duration exceeds a 24h sanity ceiling, in which
case `data.suspect` is also `true`), and `data.tokens` (real, summed from
the subagent's own transcript, when it can be found, read, and yields at
least one parsed assistant-with-usage record) OR `data.tokens_note` (a
descriptive reason when it cannot - tokens and the note are mutually
exclusive, never both, never a zero-filled stand-in for "we could not
determine this"); it
does NOT carry the `tier`/`model`/`status`/calibration fields above. See
[content/references/events-log.md](../content/references/events-log.md) for
the full schema and how consumers avoid double-counting the two variants.

### session_total

Emitted by the Stop hook on every TURN (the Stop hook fires once per turn,
not once per session).

Key `data` fields: `wall_seconds`, summed `tokens`, `spawn_count`,
`by_agent` rollup (per-agent `spawns`, `wall_seconds`, `tokens_total`), and
(DS-171) `agentic_root_drift_levels` (int) / `agentic_root_found_git`
(boolean) - same diagnostics form as `spawn_start` above, computed for the
`.agentic/events.jsonl` write this event is appended to.

This event is also mirrored to `.agentic/session-log/<developer_id>.jsonl`
for team rollup via `ds-cost team` - the mirror does not carry the two
`agentic_root_*` fields (a separately-computed result shape; a successful
mirror write already proves resolution succeeded for that invocation).

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

### tracker_writeback

Emitted by the conductor at the W1 (Phase 1, In Progress) tracker-writeback
call site in `content/commands/ds-implement-ticket.md`, one event per W1 gate
evaluation the conductor actually reaches. It does NOT detect, and nothing
currently emits a signal for, the case where the conductor never reaches the
W1 prose at all.

Key `data` fields: `site` (currently always `"W1"`), `outcome`
(`"skipped"` | `"dispatched"` | `"dispatch_failed"`), `reason` (populated
only when `outcome == "skipped"`; one of `tracker_none`, `ticket_id_format`,
`prefix_mismatch`, `fetch_failed` - `null` for `dispatched`/`dispatch_failed`),
and `target_state`. Does not carry `session_uuid` - this is a boundary event,
not a spawn-bracketing one.

### conductor_overreach

Emitted by the registered Stop hook `hooks/conductor-overreach-nudge.js`
(warn-only; never blocks the stop) when the conductor made more than the
configured `conductor_overreach_threshold` (default 12; config-reversible
via `.agentic/config.json`) investigation-shaped tool calls
(`Read`/`Grep`/`Glob`, plus read-shaped `Bash`) with zero subagent spawns,
cumulatively across the ENTIRE session transcript - not a per-turn count.
Since `ratio_trigger` requires zero spawns for the whole transcript, a
session that spawns even once can never trigger for the rest of that
session. The transcript is read from `payload.transcript_path` (the real
Stop payload shape is `{session_id, transcript_path, cwd, hook_event_name,
stop_hook_active}` - there is no `transcript` array field on the live
payload), parsed as JSONL with a size ceiling and malformed-line tolerance,
after subtracting a mandated-preflight whitelist (including a post-spawn
spot-check window bound specifically to an Agent-tool spawn's own
`tool_result` - any other tool's result must not open or extend it).

**Calibration.** `bin/ds-measure-conductor-tool-calls` measures this exact
cumulative whole-transcript statistic (not a per-turn or run-length proxy)
against real session transcripts. The default of 12 is a provisional floor
used when the zero-spawn sample (the only sessions where `ratio_trigger`
can ever fire) is thin - re-run the calibrator on a larger sample before
trusting the default in a new environment.

Key `data` fields: `source` (always `"hook"`), `session_uuid`,
`conductor_tool_calls`, `live_or_completed_spawns` (always `0` when this
event fires), `ratio_trigger` (always `true` when this event fires),
`whitelisted_reads_excluded`, `transcript_note` (string or `null` - mirrors
`spawn_complete`'s `tokens_note`; always `null` on an event that actually
fires, since `ratio_trigger` requires a successfully-read transcript;
reserved so the detector's return shape never conflates "transcript
unavailable" with "genuinely zero calls").

**Non-redundancy.** `spawn_start`/`spawn_complete` fire only when a spawn
happens and carry no denominator for a spawn-free session;
`conductor_overreach` is the only event type carrying conductor tool-call
volume for a session with zero spawns. `ds-cost session`/`ds-cost project`
render a trended (by ISO week) rollup line of `ratio_trigger:true` counts
when present.

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

**Append discipline.** No fsync, no lock file. Multiple writers append
(conductor, the Stop hook, the two spawn-telemetry hooks, and the
conductor-overreach Stop hook, all noted above) via `appendFileSync`/`>>`,
each an `O_APPEND` write, so lines never interleave mid-write; no
cross-writer locking is needed.

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
