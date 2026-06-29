<!--
Purpose: Full reference for the events log V1 telemetry event-type schemas and
         operational notes extracted from METHODOLOGY.md §Events log. Contains
         field-level data shapes for all active event types (spawn_start,
         spawn_complete, meta_review_complete, session_total,
         tool_failure_workaround) plus the deprecated conductor_direct block kept
         for historical reference, append discipline, atomicity, retention, and
         consumer notes. Also documents the per-developer session log
         (.agentic/session-log/) written by the Stop hook.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/09-events-log.md (pointer after Schema block),
            content/sections/12-protocol-details.md (Events log Protocol Details entry),
            content/references/conductor-operating-rules.md §learnings-agent
            (tool_failure_workaround emit site).

Upstream deps: content/sections/09-events-log.md (parent section; read that
               section first for writer scope and base schema);
               bin/agentic-emit, bin/agentic-parse-subagent-usage, bin/agentic-cost
               (the consumers of these event schemas);
               content/references/skeptic-protocol.md Section 14
               (calibration mechanism specification for Skeptic-specific fields).

Downstream consumers: conductor (constructs spawn_start/spawn_complete/
                      tool_failure_workaround payloads at orchestration boundaries);
                      Stop hook (constructs session_total payload at session exit AND
                      writes per-developer session log to .agentic/session-log/);
                      /wrap command (reads events.jsonl for structural session skeleton);
                      bin/agentic-cost team (reads .agentic/session-log/ for team rollup).

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

- `spawn_start`: emitted by the conductor immediately before an `Agent` tool call for engineer/skeptic/qa-engineer. `data` carries `tier`, `tool_use_id`, `agent_id: null` (Claude Code assigns the agent id after the `Agent` spawn returns), and `session_uuid` (see below).
- `spawn_complete`: emitted by the conductor immediately after an `Agent` tool call returns. `data` carries `tier`, `tool_use_id`, `agent_id`, `model`, `wall_seconds`, `tokens` (`input`, `output`, `cache_creation`, `cache_read` - kept separate because they price differently), `status`, and `session_uuid` (see below).
  - **Skeptic-specific calibration fields** (when `agent == "skeptic"`): `data` additionally carries `findings_count` (`{critical, major, minor}`), `diff_lines` (integer; lines reviewed), `signed_off` (boolean), `iteration` (integer; loop iteration when sign-off occurred), and `meta_review` (always `null` at emission time; populated retroactively only via the separate `meta_review_complete` event below). The conductor constructs the merged `data` object inline before calling `bin/agentic-emit`; meta-Skeptic and the original Skeptic do NOT write to `.agentic/`. See `content/references/skeptic-protocol.md` Section 14 for the calibration mechanism specification.
- `conductor_direct`: **[DEPRECATED - no longer emitted; hook-emitted `spawn_start` (data.source:"hook") now provides ad-hoc spawn telemetry]** _(Historical reference only.)_ Was emitted by the conductor when it edits directly under the Trivial path or answers from context. `data` carried `wall_seconds`, a `note`, and `session_uuid`; tokens were zero in V1 (the conductor cannot read its own usage from inside the session - documented gap).
- `meta_review_complete`: emitted by the conductor when a sampled meta-Skeptic returns its textual divergence report. `agent == "skeptic-meta"`. `data` carries `original_task_id` (the task_id of the original Skeptic spawn under review), `divergence` (`{critical_missed, major_missed, minor_missed}` - each a list of finding titles), `agreement` (boolean), and `session_uuid` (see below). The conductor parses meta-Skeptic's return text and constructs this payload itself; meta-Skeptic does not touch `.agentic/`. See `content/references/skeptic-protocol.md` Section 14.
- `session_total`: emitted exactly once per session by the Stop hook. `data` carries `wall_seconds`, summed `tokens`, `spawn_count`, and a `by_agent` rollup. The Stop hook also writes a mirrored rollup to `.agentic/session-log/<developer_id>.jsonl` (per-developer surface committed via Phase 8 telemetry commits; see "Per-developer session log" section below). `session_total` does NOT carry `data.session_uuid` - the Stop hook writes the equivalent at the top-level `session_uuid` field of the session-log line instead.
- `tool_failure_workaround`: emitted by the conductor when it resolves a tool or command failure via retry or workaround. `agent: null`. `data` carries `session_uuid` (see below), `tool` (tool or command name - no args, no secrets), `domain_tag` (a short domain label matching the learnings-agent domain vocabulary), and `note` (one sentence describing the workaround; no file contents, no output, no secrets). The emit site is defined in `content/references/conductor-operating-rules.md` §learnings-agent.

**`session_uuid` field (conductor-emitted events).** The four active conductor-emitted event types above (`spawn_start`, `spawn_complete`, `meta_review_complete`, `tool_failure_workaround`) each carry `data.session_uuid`. This is the Claude Code harness session uuid - the value in the `$CLAUDE_CODE_SESSION_ID` environment variable, which equals the value the Stop hook reads as `payload.session_id` at session exit. **`$CLAUDE_CODE_SESSION_ID` MUST equal the Stop hook's `payload.session_id`**; the U6 unit owns the runtime regression test asserting this equivalence (see `docs/planning/learnings-capture-system.md` §Addition 1). Stamping the same value on conductor-emitted events allows the Stop hook and any session-scoped reader to filter precisely to one session. Absent on legacy lines written before this schema addition; general readers treat absence as include for back-compat. The Stop-hook capture-gap backstop (`detectCaptureGap` in `hooks/stop-context.js`) treats absence as EXCLUDE - it only matches events that carry the current session's uuid, which avoids false nags from prior-session events. This deliberate inversion is documented; do not change it to absent=include in the backstop filter.

## Append discipline

Plain shell `>>` append. No fsync, no tmp+rename, no lock file. Single-writer-by-protocol means contention is structurally impossible. If a partial line ever appears (impossible under single-writer but for robustness), readers tolerate it - JSONL parsers skip malformed lines.

## Atomicity

Best-effort. Records are not size-bounded. Catastrophic events during write may leave a truncated line. Documented honestly; not load-bearing.

## Retention

Not auto-rotated. Manual `mv` to `events-prev.jsonl` if a file grows past concern. Project-local; gitignored; ~50KB per session is the operating budget.

## Consumer

Optional. /wrap may consult events.jsonl as supplementary signal for the structural session skeleton. Conversation-memory review remains primary. /wrap on a project with no events.jsonl works exactly as today.

## Per-developer session log (`.agentic/session-log/`)

The Stop hook writes a second target alongside `events.jsonl`. When a developer identity is set (via `agentic-identity init <handle>`), the hook appends one JSON line per session to `.agentic/session-log/<developer_id>.jsonl`. This file is committed to git via the `.agentic/session-log/` carve-out in `.gitignore`; `/implement-ticket` Phase 8 commits it as a SEPARATE commit on the PR branch when `commit_telemetry: true` (default) and identity is confirmed. Run `agentic-cost team` to aggregate all session-log files present on the local checkout.

**Canonical session-log line schema:**

```json
{
  "ts": "2026-05-28T12:00:00Z",
  "phase": "session_end",
  "event": "session_total",
  "agent": null,
  "task_id": null,
  "developer_id": "tyson",
  "session_uuid": "<uuid-v4>",
  "project_slug": "agentic-engineering",
  "branch": "main",
  "data": {
    "wall_seconds": 1234,
    "tokens": {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0},
    "spawn_count": 5,
    "by_agent": {"engineer": {"spawns": 2, "wall_seconds": 600, "tokens_total": 50000}}
  }
}
```

**Fields:**
- `developer_id`: handle from the effective identity (`<cwd>/.agentic/identity.yml` if present and wins the 4-tier resolution, else `~/.agentic/identity.yml`). Never inferred from git config.
- `session_uuid`: the Stop hook payload `session_id` field.
- `project_slug`: `path.basename(cwd)` - the directory name of the project root.
- `branch`: from `git symbolic-ref --short HEAD` (best-effort; empty string on failure).
- `data.by_agent`: keys are agent-type strings; values carry `spawns`, `wall_seconds`, `tokens_total` (sum of all token types).

**PII boundary:** Only the fields above are written. Excluded: prompt content, file paths, tool I/O, user messages, finding text, task descriptions, commit messages, environment variable values.

**No identity:** The session-log write is skipped only when the 4-tier resolution yields no effective identity - i.e. neither the project-local `<repo>/.agentic/identity.yml` nor the global `~/.agentic/identity.yml` resolves a usable handle (both absent, or only provisional handles present such that telemetry is buffered rather than written directly). A developer whose identity is confirmed at any tier (project-confirmed or global-confirmed) receives a normal session-log write; a developer with only provisional identities has telemetry buffered to `~/.agentic/session-log/.pending/` until `agentic-identity confirm` is run. When no tier resolves at all, the Stop hook appends a one-time nudge to `.agentic/context.md` directing the developer to run `agentic-identity init <handle>`. A sentinel at `~/.agentic/.identity-nudged` prevents repeated nudges.

**Aggregation:** `agentic-cost team` reads all `.agentic/session-log/*.jsonl` files on the local checkout and renders a per-developer rollup table sorted by total tokens. Because session-logs are committed via Phase 8 telemetry commits, the rollup reflects sessions from all developers whose telemetry has landed on the branch via pull after merge - enabling cross-developer team visibility without a separate aggregation service.
