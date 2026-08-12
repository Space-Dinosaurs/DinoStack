<!--
Purpose: Full reference for the events log V1 telemetry event-type schemas and
         operational notes extracted from METHODOLOGY.md §Events log. Contains
         field-level data shapes for all active event types (spawn_start,
         spawn_complete, meta_review_complete, session_total,
         tool_failure_workaround, tracker_writeback) plus the deprecated
         conductor_direct block kept for historical reference, append
         discipline, atomicity, retention, and consumer notes. Also documents
         the per-developer session log (.agentic/session-log/) written by the
         Stop hook, and the enforcement fire log
         (.agentic/.enforcement-fires.jsonl) written by
         hooks/lib/enforcement_log.py.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/09-events-log.md (pointer after Schema block),
            content/sections/12-protocol-details.md (Events log Protocol Details entry),
            content/references/conductor-operating-rules.md §learnings-agent
            (tool_failure_workaround emit site),
            content/commands/ds-implement-ticket.md (W1 tracker-writeback
            outcome breadcrumb emit site).

Upstream deps: content/sections/09-events-log.md (parent section; read that
               section first for writer scope and base schema);
               bin/ds-emit, bin/ds-parse-subagent-usage, bin/ds-cost
               (the consumers of these event schemas);
               content/references/skeptic-protocol.md Section 14
               (calibration mechanism specification for Skeptic-specific fields).

Downstream consumers: conductor (constructs spawn_start/spawn_complete/
                      tool_failure_workaround payloads at orchestration boundaries);
                      the Stop hook (constructs a session_total payload on EVERY
                      turn - not just at session exit; see hooks/session-end-wrap.js,
                      the SessionEnd hook, for the once-per-session terminal
                      loop-state/batch-state mark - AND writes per-developer session
                      log to .agentic/session-log/);
                      /ds-wrap command (reads events.jsonl for structural session skeleton,
                      and .agentic/.enforcement-fires.jsonl for Part D.5 signal 3(b));
                      bin/ds-cost team (reads .agentic/session-log/ for team rollup).

Failure modes: Prose; does not execute. Schema drift between this reference and
               the actual event payloads emitted by the conductor causes
               bin/ds-cost and bin/ds-parse-subagent-usage to silently
               miscount or drop records.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §Events log. Read that section first for writer scope and base schema.

# Events Log - Full Reference

## V1 telemetry event types

(Cost & latency observability; see `bin/ds-emit`, `bin/ds-parse-subagent-usage`, `bin/ds-cost`.)

- `spawn_start`: emitted by the conductor immediately before an `Agent` tool call for engineer/skeptic/qa-engineer. `data` carries `tier`, `tool_use_id`, `agent_id: null` (Claude Code assigns the agent id after the `Agent` spawn returns), and `session_uuid` (see below).
- `spawn_complete`: emitted by the conductor immediately after an `Agent` tool call returns. `data` carries `tier`, `tool_use_id`, `agent_id`, `model`, `wall_seconds`, `tokens` (`input`, `output`, `cache_creation`, `cache_read` - kept separate because they price differently), `status`, and `session_uuid` (see below).
  - **Skeptic-specific calibration fields** (when `agent == "skeptic"`): `data` additionally carries `findings_count` (`{critical, major, minor}`), `diff_lines` (integer; lines reviewed), `signed_off` (boolean), `iteration` (integer; loop iteration when sign-off occurred), and `meta_review` (always `null` at emission time; populated retroactively only via the separate `meta_review_complete` event below). The conductor constructs the merged `data` object inline before calling `bin/ds-emit`; meta-Skeptic and the original Skeptic do NOT write to `.agentic/`. See `content/references/skeptic-protocol.md` Section 14 for the calibration mechanism specification.
  - **Hook-emitted variant (DS-160)**: both `spawn_start` and `spawn_complete` now also have a deterministic, hook-emitted variant (`data.source:"hook"`), independent of the conductor-emitted schema above; the two variants may coexist for the same spawn on disk, but consumers do NOT sum them additively - `hooks/stop-context.js` `scanSessionAggregate()` and `bin/ds-cost`'s `_aggregate_by_agent()` both apply a double-count guard: when a session has at least one conductor-emitted (non-hook) `spawn_complete`, ALL hook-emitted telemetry for that session (both `spawn_start` and `spawn_complete`) is excluded from the count entirely, since the conductor-emitted record is treated as authoritative for that spawn. In a session with NO conductor-emitted `spawn_complete` (a pure ad-hoc session), a hook-emitted `spawn_start` is the sole authoritative "this spawn happened" signal and is deduped by `data.spawn_id` so each real spawn contributes exactly once, including a spawn whose `SubagentStop` never fires. A hook-emitted `spawn_complete` NEVER creates a spawn count of its own (round-2 fix: an earlier version counted an unresolvable `spawn_complete` as its own spawn, which double-counted whenever its matching `spawn_start` was still visible to the consumer) - it only ENRICHES an already-counted spawn's `wall_seconds` when its `data.paired_spawn_id` resolves to a `spawn_start` already seen in that session; an unpaired or unresolvable `spawn_complete` contributes nothing to the aggregate and is available only as raw forensic data directly in `events.jsonl`. `hooks/pre-tool-use-spawn-emit.js` (`PreToolUse(Task/Agent)`) emits hook-sourced `spawn_start` on every subagent spawn with `data.spawn_id` (a fresh `crypto.randomUUID()`, always present - the correlation key for pairing), `data.tool_use_id` (best-effort, from the PreToolUse payload's top-level `tool_use_id` field), and `data.parent_agent_id` (best-effort, from the payload's top-level `agent_id` field; present only for a nested spawn issued from inside a running subagent, else `null`). `hooks/subagent-stop-spawn-emit.js` (`SubagentStop`) emits hook-sourced `spawn_complete` deterministically when a subagent actually finishes (unlike `PostToolUse(Task/Agent)`, which fires at spawn launch, not completion) with `data.paired_spawn_id` (the matched `spawn_start`'s `data.spawn_id`, or `null` if unmatched - pairing requires a same-session exact `data.tool_use_id` match first, falling back to same-session FIFO oldest-unmatched-spawn_start; it never pairs across sessions or when `session_id` is absent on either side) and a real `data.wall_seconds` (`null` if unmatched, OR if a match was found but the implied duration exceeds a 24h sanity ceiling - see `data.suspect` below); the event is always emitted even when pairing fails. `data.suspect` (boolean, hook-emitted `spawn_complete` only) is `true` when a pairing was found but produced an implausible (>86400s) duration - almost certainly a stale/mismatched pair rather than a genuine 24h+ subagent run; `data.wall_seconds` is `null` (never a fabricated ceiling value) whenever `data.suspect` is `true`, and consumers naturally contribute 0 wall-time for it (`Number(null)||0`) while still counting the spawn via its paired `spawn_start`. Both hook-emitted events carry `data.session_uuid`. `hooks/subagent-stop-spawn-emit.js` also resolves `data.tokens` (`{input, output, cache_creation, cache_read}`, summed from the subagent's own transcript JSONL under the active harness config dir - see `hooks/lib/config-dir.js` - via `bin/ds-parse-subagent-usage`'s sibling resolution logic) when that transcript can be found and read; `data.tokens` is ABSENT (never zero-filled) and `data.tokens_note` explains why (`"unavailable (transcript not found)"` or `"skipped (transcript too large)"` for a transcript at or above 20 MiB) when it cannot. `tokens` and `tokens_note` are mutually exclusive on a given event. The conductor-emitted `spawn_complete` schema (`tier`/`agent_id`/`model`/`tokens`/`status`/calibration fields) above is unchanged by this addition.
- `conductor_direct`: **[DEPRECATED - no longer emitted; hook-emitted `spawn_start` (data.source:"hook") now provides ad-hoc spawn telemetry]** _(Historical reference only.)_ Was emitted by the conductor when it edits directly under the Trivial path or answers from context. `data` carried `wall_seconds`, a `note`, and `session_uuid`; tokens were zero in V1 (the conductor cannot read its own usage from inside the session - documented gap).
- `meta_review_complete`: emitted by the conductor when a sampled meta-Skeptic returns its textual divergence report. `agent == "skeptic-meta"`. `data` carries `original_task_id` (the task_id of the original Skeptic spawn under review), `divergence` (`{critical_missed, major_missed, minor_missed}` - each a list of finding titles), `agreement` (boolean), and `session_uuid` (see below). The conductor parses meta-Skeptic's return text and constructs this payload itself; meta-Skeptic does not touch `.agentic/`. See `content/references/skeptic-protocol.md` Section 14.
- `session_total`: emitted by the Stop hook on EVERY turn (this is a pre-existing property, not introduced by the Stop hook's `--cadence=turn` loop-state/batch-state split described in `hooks/lib/state-mark.js` and the SessionEnd hook `hooks/session-end-wrap.js` - `writeSessionTotal` has always run on every Stop invocation; "once per session" was a prior inaccuracy in this doc, corrected here). `data` carries `wall_seconds`, summed `tokens`, `spawn_count`, and a `by_agent` rollup. The Stop hook also writes a mirrored rollup to `.agentic/session-log/<developer_id>.jsonl` (per-developer surface committed via Phase 8 telemetry commits; see "Per-developer session log" section below). `session_total` does NOT carry `data.session_uuid` - the Stop hook writes the equivalent at the top-level `session_uuid` field of the session-log line instead.
- `tool_failure_workaround`: emitted by the conductor when it resolves a tool or command failure via retry or workaround. `agent: null`. `data` carries `session_uuid` (see below), `tool` (tool or command name - no args, no secrets), `domain_tag` (a short domain label matching the learnings-agent domain vocabulary), and `note` (one sentence describing the workaround; no file contents, no output, no secrets). The emit site is defined in `content/references/conductor-operating-rules.md` §learnings-agent.
- `tracker_writeback`: emitted by the conductor at the W1 (Phase 1, In Progress) tracker-writeback call site in `content/commands/ds-implement-ticket.md`. `agent: null`. `data` carries `site` (currently always `"W1"` - reserved for extension to W2-W7 if their own observability gap is ever addressed the same way), `outcome` (`"skipped"` | `"dispatched"` | `"dispatch_failed"`), `reason` (populated only when `outcome == "skipped"`; one of `tracker_none`, `ticket_id_format`, `prefix_mismatch`, `fetch_failed` - `null` for `dispatched`/`dispatch_failed`), and `target_state` (the resolved `$TRACKER_STATE_IN_PROGRESS` value). Does not carry `session_uuid` - this is a boundary event rather than a spawn-bracketing one. Soft-fail (`2>/dev/null || true`); a missing or failing `ds-emit` never blocks Phase 1. **Coverage is narrower than it may read at a glance**: this fires one event per W1 gate evaluation the conductor actually reaches - it detects the case where the conductor reaches the gate and the gate declines (the `"skipped"` outcome and its reason code). It does NOT detect, and nothing currently emits a signal for, the case where the conductor never reaches the W1 prose at all.

**`session_uuid` field (conductor-emitted events).** Four of the five active conductor-emitted event types above (`spawn_start`, `spawn_complete`, `meta_review_complete`, `tool_failure_workaround`) each carry `data.session_uuid`; the fifth, `tracker_writeback`, does not (see its own entry above - a boundary event rather than a spawn-bracketing one). This is the Claude Code harness session uuid - the value in the `$CLAUDE_CODE_SESSION_ID` environment variable, which equals the value the Stop hook reads as `payload.session_id` on every turn (the Stop hook fires once per turn, not once per session). **`$CLAUDE_CODE_SESSION_ID` MUST equal the Stop hook's `payload.session_id`**; the U6 unit owns the runtime regression test asserting this equivalence (see `docs/planning/learnings-capture-system.md` §Addition 1). Stamping the same value on conductor-emitted events allows the Stop hook and any session-scoped reader to filter precisely to one session. Absent on legacy lines written before this schema addition; general readers treat absence as include for back-compat. The Stop-hook capture-gap backstop (`detectCaptureGap` in `hooks/stop-context.js`) treats absence as EXCLUDE - it only matches events that carry the current session's uuid, which avoids false nags from prior-session events. This deliberate inversion is documented; do not change it to absent=include in the backstop filter.

## Append discipline

Plain shell `>>` append (or the Node equivalent, `fs.appendFileSync`). No fsync, no tmp+rename, no lock file. There are multiple writers - the conductor, `hooks/pre-tool-use-spawn-emit.js`, and `hooks/subagent-stop-spawn-emit.js` (DS-160) all append independently. On a local filesystem, a single `O_APPEND` write is positioned and written atomically at end-of-file, so appends do not interleave mid-line. If a partial line ever appears anyway, readers tolerate it - JSONL parsers skip malformed lines.

## Atomicity

Best-effort. Records are not size-bounded. Catastrophic events during write may leave a truncated line. Documented honestly; not load-bearing.

## Retention

Not auto-rotated. Manual `mv` to `events-prev.jsonl` if a file grows past concern. Project-local; gitignored; ~50KB per session is the operating budget.

## Consumer

Optional. /ds-wrap may consult events.jsonl as supplementary signal for the structural session skeleton. Conversation-memory review remains primary. /ds-wrap on a project with no events.jsonl works exactly as today.

## Per-developer session log (`.agentic/session-log/`)

The Stop hook writes a second target alongside `events.jsonl`. When a developer identity is set (via `ds-identity init <handle>`), the hook appends one JSON line per session to `.agentic/session-log/<developer_id>.jsonl`. This file is committed to git via the `.agentic/session-log/` carve-out in `.gitignore`; `/ds-implement-ticket` Phase 8 commits it as a SEPARATE commit on the PR branch when `commit_telemetry: true` (default) and identity is confirmed. Run `ds-cost team` to aggregate all session-log files present on the local checkout.

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
  "project_slug": "dinostack",
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
- `developer_id`: handle from the 6-tier effective identity: project-confirmed > profile-confirmed > global-confirmed > project-provisional > profile-provisional > global-provisional. Profile identity is read from `<active-config-dir>/identity.yml`, with the config dir resolved from `AGENTIC_CONFIG_DIR`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, or `PI_CODING_AGENT_DIR`. Never inferred from git config.
- `session_uuid`: the Stop hook payload `session_id` field.
- `project_slug`: `path.basename(cwd)` - the directory name of the project root.
- `branch`: from `git symbolic-ref --short HEAD` (best-effort; empty string on failure).
- `data.by_agent`: keys are agent-type strings; values carry `spawns`, `wall_seconds`, `tokens_total` (sum of all token types).

**PII boundary:** Only the fields above are written. Excluded: prompt content, file paths, tool I/O, user messages, finding text, task descriptions, commit messages, environment variable values.

**No confirmed identity:** Direct session-log writes are skipped when the 6-tier resolution yields no confirmed identity. Project, active-profile, and global identity files are all considered. When only provisional identities exist, telemetry is buffered at `~/.agentic/session-log/.pending/`; each record carries canonical `identity_scope` from the winning provisional identity, and profile winners also carry `config_dir`. `ds-identity confirm --scope <winning-scope>` flushes only records whose `identity_scope` matches: profile confirmation additionally matches `config_dir`, project confirmation matches `repo_root`, and global confirmation accepts global-scope records even when a profile config dir is active. Nonmatching records remain buffered and cannot be reattributed by a later identity in another scope. When no tier resolves at all, the Stop hook appends a one-time nudge to this session's `.agentic/context.d/<session_id>.md` shard, from which the derived `.agentic/context.md` rollup carries it, directing the developer to run `ds-identity init <handle>`. A sentinel at `~/.agentic/.identity-nudged` prevents repeated nudges.

**Aggregation:** `ds-cost team` reads all `.agentic/session-log/*.jsonl` files on the local checkout and renders a per-developer rollup table sorted by total tokens. Because session-logs are committed via Phase 8 telemetry commits, the rollup reflects sessions from all developers whose telemetry has landed on the branch via pull after merge - enabling cross-developer team visibility without a separate aggregation service.

## Enforcement fire log (`.agentic/.enforcement-fires.jsonl`)

Written by `hooks/lib/enforcement_log.py`'s `log_fire()`, called lazily (from inside the action branch, never at module scope) by nine of the ten `hooks/enforce-*.py` PreToolUse/Stop hooks whenever they take a non-passthrough action - a deny, or an allow-with-advisory-reason. A silent allow (the overwhelming majority of invocations) never calls it, so the file stays small. `enforce-no-abdication.py` is the one exception: it keeps its own separate `.agentic/.abdication-guard-fire-count` counter, unchanged by this mechanism (see `hooks/AGENTS.md`).

**Canonical line schema (4 fields, one JSON object per line):**

```json
{"ts": "2026-07-27T12:00:00.000Z", "hook": "enforce-tier", "decision": "deny", "reason": "Agent spawn blocked: security-auditor was spawned with model='sonnet'..."}
```

- `ts`: ISO8601 UTC with millisecond precision (matches the `events.jsonl` convention).
- `hook`: short hook identifier, e.g. `"enforce-tier"`, `"enforce-shippable-edit"` - one of the nine consumer hooks enumerated below.
- `decision`: the action taken - free-form by design, not validated against an enum, so a future action shape never needs a lib change to be logged. Currently observed values: `"deny"` (eight hooks - `enforce-askuserquestion-default.py`, `enforce-background-spawn.py`, `enforce-orchestrator-singularity.py`, `enforce-shippable-edit.py`, `enforce-skeptic-round-cap.py`, `enforce-tier.py`, `enforce-turn-shape.py`, `enforce-worktree-read.py`) and `"allow_advisory"` (two hooks - `enforce-planning-artifact-spawn.py`, `enforce-turn-shape.py`). `enforce-turn-shape.py` (DS-156) is the one hook that can log EITHER value, depending on which of its two checks fired: `_execution_prose_flag` (BLOCKING, execution-turn structural shape) logs `"deny"`; `_answer_relevance_flag` (ADVISORY, answer-turn opening-preamble/closing-recap phrasing) logs `"allow_advisory"`.
- `reason`: human-readable reason string, truncated to 800 chars (the same text fed back to the model via `permissionDecisionReason`).

**No session correlation.** Unlike `events.jsonl`, this file carries no `session_uuid` or equivalent field - `log_fire()` writes only `cwd`-scoped, not session-scoped. A tally over this file is therefore a REPO-WIDE cumulative count across every session that has ever run since the file was created (or last rotated/deleted away), never a single-session count. Any consumer reporting this file's contents (e.g. `/ds-wrap` Part D.5 signal 3(b)) must state this scope explicitly.

**Atomicity:** each line is a single `os.write()` to an `O_APPEND`-opened file descriptor. The atomicity guarantee is POSIX's `O_APPEND` seek-to-end-plus-write semantics, not `PIPE_BUF` (which governs pipes/FIFOs, not regular files); this does not hold over NFS. Project-local `.agentic/` writes are the only current use, so the NFS caveat is noted but not a practical concern today.

**Retention:** not auto-rotated. Same operating posture as `events.jsonl` above - manual `mv` if it grows past concern. Project-local; gitignored.

**Consumer:** `/ds-wrap` Part D.5 signal 3(b) (Session-feedback capture signal, "Enforcement fire-log") reads only the last ~500 lines and tallies occurrences per `hook` value as a `guardrail-fire` feedback candidate.
