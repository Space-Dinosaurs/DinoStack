# Technical Plan: Gap 1 - Cost & Latency Observability (Revised)

## Convergence note - iteration 3

Final-iteration revision. Three new Skeptic findings from iteration 2 closed:

- **Major (events.jsonl single-writer contradiction).** Resolved by adding implementation step 7a, which edits `content/rules/agent-methodology.md` Events log section to explicitly carve out the Stop hook as a sanctioned second writer (framing (b) per Skeptic guidance). Verbatim before/after wording is in step 7a. Acceptance criterion 10 added.
- **Minor (project-hash derivation fragility).** Resolved by tightening the `bin/agentic-parse-subagent-usage` manifest contract under "API / interface design" - the helper's module manifest header must document the O(N projects) glob fallback in its Failure modes and Performance fields. Acceptance criterion 11 added.
- **Minor (V1 boundary set silently under-reports session cost).** Resolved by adding a disclosure footer line to `/agentic-cost` output and the same line in `content/commands/agentic-cost.md` help text. Verbatim wording stated under "/agentic-cost CLI" and "/agentic-cost spec". Acceptance criterion 12 added.

## Convergence note (Skeptic findings resolution)

This revision addresses every finding from the prior Skeptic pass.

- **Critical (transcript schema wrong).** Resolved by on-disk verification (see "Verified transcript schema" below). Parser now opens parent session JSONL AND globs `<session-uuid>/subagents/agent-*.jsonl`. Correlation is by `agentId` from the parent's Task `tool_result` content, which carries `agentId` and `agentType` inline. `parentToolUseId` on subagent assistant turns is null and is NOT used.
- **Major 1 (self-report fallback inert).** Dropped from V1. Transcript-parsing is verified to work for Claude Code, so the `Telemetry:` block in agent return text is unnecessary and adds review surface. Engineer/Skeptic/Architect spec edits are removed from V1 scope. V2 may add it for non-Claude harnesses (Codex/Gemini) where transcript shape differs.
- **Major 2 (Stop hook session_total).** Specified explicitly: Stop hook re-reads `.agentic/events.jsonl` for the current session, sums `tokens_*` and `wall_seconds` across `spawn_complete` and `conductor_direct` events, appends one `session_total` line. Failure modes documented. `hooks/stop-context.js` manifest gains a third independent write path.
- **Major 3 (Gap 4 PR collision).** Declared a hard prerequisite: Gap 4 PR #27 merges first; Gap 1 rebases on updated `main`. Edit insertion points specified relative to Gap 4's post-merge text in the affected sections.
- **Major 4 (pricing footgun).** Picked option (b): opt-in `~/.agentic/pricing.yml`. `/agentic-cost` refuses to print dollar figures unless the file is present. Data model distinguishes `cache_creation_input_tokens` and `cache_read_input_tokens` so the rate file can price them separately.
- **Minor 1.** Schema verification is moved to a closed gate at the top of this plan ("Verified transcript schema"); Open Questions is empty.
- **Minor 2.** Trimmed to 5 V1 boundaries: engineer/skeptic/qa spawn pairs (6 events per typical iteration) plus `conductor_direct` plus `session_total`. Architect-spawn and plan-skeptic emits deferred to V2.
- **Minor 3.** Retention back-of-envelope stated: ~250 bytes/event x ~50 events ≈ 12.5 KB per long-loop session, well under the 50 KB budget.

## Verified transcript schema (closed gate)

Verified on disk against an active project on 2026-04-30:

- Parent session: `~/.claude/projects/<project-hash>/<session-uuid>.jsonl`
- Subagent transcripts: `~/.claude/projects/<project-hash>/<session-uuid>/subagents/agent-<agentId>.jsonl`
- Subagent meta: `~/.claude/projects/<project-hash>/<session-uuid>/subagents/agent-<agentId>.meta.json`
  - Shape: `{"agentType":"skeptic","description":"..."}`

Real example path consulted:
`/Users/tyson/.claude/projects/-Users-tyson-Documents-Development-ai-tools-agentic-engineering/1aecac02-2b72-4965-bf35-3e5599ad82c6/subagents/agent-a17e78ca1e42d63e9.jsonl`

**Subagent assistant turn** (verbatim field shape from line 2 of the file above):

```
{
  "parentUuid": "<chains within subagent file>",
  "isSidechain": true,
  "agentId": "a17e78ca1e42d63e9",
  "attributionAgent": "skeptic",
  "type": "assistant",
  "message": {
    "model": "claude-sonnet-4-6",
    "usage": {
      "input_tokens": 3,
      "cache_creation_input_tokens": 8503,
      "cache_read_input_tokens": 0,
      "output_tokens": 1
    }
  },
  "timestamp": "2026-04-28T15:48:22.758Z",
  "sessionId": "1aecac02-2b72-4965-bf35-3e5599ad82c6"
}
```

Notes:
- `parentToolUseId` is NOT present on subagent assistant turns - confirmed by Skeptic and re-verified here. Do not use it.
- `sessionId` on subagent lines points back to the PARENT session uuid - this is the correlation hop to the parent JSONL.
- `agentId` is the stable correlation key.

**Parent session correlation** (verbatim from parent JSONL, line 154 of the file above):

The parent session contains a `tool_result` user-message whose `content[]` includes inline `agentId` and `agentType`:

```
"agentId":"a17e78ca1e42d63e9","agentType":"skeptic"
```

The same `tool_result` carries `tool_use_id` (a `toolu_*` id) which matches the preceding Task `tool_use.id` in the parent. So the correlation chain is:

```
parent: tool_use{name:"Task", id:toolu_X} ──> tool_result{tool_use_id:toolu_X, agentId:A, agentType:T}
                                                                                     │
subagent file: agent-<A>.jsonl  <───────────────────────────────────────────────────┘
```

Parser uses the parent `tool_result` (not `tool_use`) as the correlation anchor because that is where `agentId` first appears.

## Approach

Add a single source-of-truth telemetry stream to `.agentic/events.jsonl` for tokens and wall-clock per spawned agent, plus session totals. The conductor (sole writer) emits two events per spawn (`spawn_start`, `spawn_complete`) using a small shell helper backed by transcript parsing. A standalone `agentic-cost` CLI reads `events.jsonl` and renders per-agent and per-session usage tables. Pricing is opt-in via `~/.agentic/pricing.yml`; without it the CLI prints token counts only and never invents dollar figures.

## Recommendation reasoning

Transcript parsing is the only authoritative source for token counts on Claude Code (subagents cannot write to events.jsonl per single-writer rule, and self-reported counts in return text are estimates). Verification on disk above proves the data is reachable from a single project hash with two file reads (parent session + subagent file). An opt-in pricing file is the only option that structurally prevents stale-rate dollar displays while still letting the user see costs when they choose to maintain rates. V1 instruments only the boundaries that drive cost (engineer/skeptic/qa) and defers architect/plan-skeptic emits because they fire once per loop and add review surface without proportional signal.

## Open Questions resolution

None. Schema gate closed above. All design decisions committed below.

## Data model

### `.agentic/events.jsonl` line shape (V1 additions)

Events.jsonl already exists per `content/rules/agent-methodology.md`. Adding two new event types and one terminal event. Existing fields (`ts`, `phase`, `event`, `agent`, `task_id`, `data`) unchanged.

**`spawn_start`** event:
```
{
  "ts": "2026-04-30T12:34:56.123Z",
  "phase": "implement",
  "event": "spawn_start",
  "agent": "engineer",
  "task_id": "T-3",
  "data": {
    "tier": 2,
    "tool_use_id": "toolu_01abc...",
    "agent_id": null
  }
}
```

`agent_id` is null at start (Claude Code assigns it after the Task tool returns); patched in by the conductor at `spawn_complete` time.

**`spawn_complete`** event:
```
{
  "ts": "2026-04-30T12:36:11.987Z",
  "phase": "implement",
  "event": "spawn_complete",
  "agent": "engineer",
  "task_id": "T-3",
  "data": {
    "tier": 2,
    "tool_use_id": "toolu_01abc...",
    "agent_id": "a17e78ca1e42d63e9",
    "model": "claude-sonnet-4-6",
    "wall_seconds": 75.864,
    "tokens": {
      "input": 4231,
      "output": 1820,
      "cache_creation": 12044,
      "cache_read": 38911
    },
    "status": "ok"
  }
}
```

`tokens.cache_creation` and `tokens.cache_read` are kept as separate fields because they price differently. `input` and `output` are the non-cached portions (verbatim from `message.usage.input_tokens` / `output_tokens` summed across all assistant turns in the subagent file).

**`conductor_direct`** event (when the conductor edits directly under the Trivial path or answers from context):
```
{
  "ts": "...",
  "phase": "implement",
  "event": "conductor_direct",
  "agent": null,
  "task_id": null,
  "data": {
    "wall_seconds": 12.4,
    "tokens": { "input": 0, "output": 0, "cache_creation": 0, "cache_read": 0 },
    "note": "trivial-path direct edit"
  }
}
```

V1 leaves token fields zero for `conductor_direct` - the conductor cannot read its own token usage from inside the session. Wall time is wall-clock between the prior boundary event and this one. Documented as a known gap, not a bug.

**`session_total`** event (Stop-hook only):
```
{
  "ts": "...",
  "phase": "session_end",
  "event": "session_total",
  "agent": null,
  "task_id": null,
  "data": {
    "wall_seconds": 1842.3,
    "tokens": { "input": 21044, "output": 9120, "cache_creation": 88421, "cache_read": 311009 },
    "spawn_count": 14,
    "by_agent": {
      "engineer": { "spawns": 6, "wall_seconds": 612.4, "tokens": {...} },
      "skeptic":  { "spawns": 7, "wall_seconds": 401.2, "tokens": {...} },
      "qa-engineer": { "spawns": 1, "wall_seconds": 88.0, "tokens": {...} }
    }
  }
}
```

### `~/.agentic/pricing.yml` (opt-in)

```
# Rates in USD per 1M tokens. User-maintained.
# /agentic-cost refuses to print dollar figures when this file is absent.
updated: 2026-04-15
models:
  claude-sonnet-4-6:
    input: 3.00
    output: 15.00
    cache_creation: 3.75
    cache_read: 0.30
  claude-opus-4-7:
    input: 15.00
    output: 75.00
    cache_creation: 18.75
    cache_read: 1.50
  claude-haiku-4:
    input: 0.80
    output: 4.00
    cache_creation: 1.00
    cache_read: 0.08
```

`/agentic-cost` looks up `model` from the `spawn_complete` event. If a model is missing from `pricing.yml`, that row's dollar columns render `?` and a footnote lists the missing model.

## API / interface design

### `agentic_emit` (shell helper)

A small bash function the conductor calls inline. NOT a long-running daemon. NOT an npm dependency.

Signature:
```
agentic_emit <event> <agent_or_-> <task_id_or_-> <json_data>
```

Example call sites (illustrative):
```
agentic_emit spawn_start engineer T-3 '{"tier":2,"tool_use_id":"toolu_01abc"}'
agentic_emit spawn_complete engineer T-3 '{"tier":2,"tool_use_id":"toolu_01abc","agent_id":"a17e78ca1e42d63e9","model":"claude-sonnet-4-6","wall_seconds":75.864,"tokens":{"input":4231,"output":1820,"cache_creation":12044,"cache_read":38911},"status":"ok"}'
```

The helper:
1. Computes `ts` (ISO8601 UTC).
2. Reads `phase` from `.agentic/loop-state.json` (`last_phase` field) if present, else `"unknown"`.
3. Appends one JSON object to `.agentic/events.jsonl` via plain `>>`.

Helper lives at `bin/agentic-emit` (single shell file, no deps). Sourced or shelled out by the conductor.

### `parse_subagent_usage` (helper invoked at spawn_complete)

Standalone script `bin/agentic-parse-subagent-usage`. Takes `<session-uuid>` and `<agent_id>` on argv, prints JSON `{tokens, model, wall_seconds}` on stdout.

Algorithm:
1. Resolve `~/.claude/projects/<project-hash>/<session-uuid>/subagents/agent-<agent_id>.jsonl`. Project-hash is derived from `pwd` using Claude Code's own scheme: replace `/` with `-` and prepend `-`. Verified by inspection of existing project dirs.
2. Read JSONL line by line. For each line where `type == "assistant"` and `message.usage` is present, sum `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`.
3. Take `model` from the first assistant line (`message.model`).
4. `wall_seconds`: `(last_assistant_ts) - (first_user_ts)` from the same file. ISO8601 parse via `date -d` (Linux) or `python3 -c` for portability; ship the python3 fallback for macOS BSD-date.
5. Print compact JSON.

Failure modes: file missing -> print `{"error":"transcript_not_found"}` and exit 0 (conductor records `status:"missing_transcript"` and zero tokens; does NOT block).

**Module manifest contract (REQUIRED for `bin/agentic-parse-subagent-usage`).** Per `content/rules/module-manifest.md`, this file's manifest header MUST cover the project-hash fallback explicitly:

- **Failure modes** field MUST state: "Primary path derives the project hash from `pwd` using Claude Code's `/`->`-` scheme. If the resulting directory does not exist (scheme drift, symlinked cwd, or non-standard project layout), the helper falls back to globbing `~/.claude/projects/*/<session-uuid>/subagents/agent-<agent_id>.jsonl` and selects the first match. If neither path resolves, exits 0 with `{\"error\":\"transcript_not_found\"}` - never raises."
- **Performance** field MUST state: "Primary path is two file opens (parent JSONL + subagent JSONL). Fallback glob is O(N projects) where N is the count of directories under `~/.claude/projects/`; typical N < 50 makes this <50 ms in practice but is not bounded by spec."

### `/agentic-cost` CLI (new file `content/commands/agentic-cost.md` and `bin/agentic-cost`)

Subcommands:
- `agentic-cost session [<session-uuid>]` - default: current project's most recent `session_total` event
- `agentic-cost task <task_id>` - aggregates all `spawn_complete` events for a given task_id
- `agentic-cost project [--since <date>]` - aggregates across all sessions in `.agentic/events.jsonl`

Output (no pricing.yml present):
```
agent       spawns   in       out      cache_cr  cache_rd  wall(s)
engineer    6        21044    9120     88421     311009    612.4
skeptic     7        4012     1840     21001     94221     401.2
qa-engineer 1        801      244      3001      9100      88.0
TOTAL       14       25857    11204    112423    414330    1101.6

Pricing not configured. Create ~/.agentic/pricing.yml to enable dollar columns.
Note: V1 instruments engineer/skeptic/qa only; architect/investigator/debugger spawns are not counted.
```

Output (pricing.yml present):
```
agent       spawns   tokens   $in     $out    $cache_cr  $cache_rd  $total   wall(s)
engineer    6        429594   0.063   0.137   0.331      0.093      0.624    612.4
...
TOTAL       ...                                                     1.42     1101.6

Rates as of 2026-04-15 from ~/.agentic/pricing.yml.
Note: V1 instruments engineer/skeptic/qa only; architect/investigator/debugger spawns are not counted.
```

If `pricing.yml.updated` is older than 90 days, append warning: `Rates are >90 days old; verify before quoting.`

## Boundary wiring (V1: 5 boundaries)

The conductor emits at exactly these points. Architect-spawn and plan-skeptic emits are deferred to V2.

| # | Boundary | Where | Event |
|---|---|---|---|
| 1 | Engineer spawn pair | `/implement-ticket` Phase 6 (engineer spawn) | `spawn_start` before Task call; `spawn_complete` after Task returns |
| 2 | Skeptic spawn pair | `/implement-ticket` Phase 6 (skeptic spawn) | same |
| 3 | QA spawn pair | `/implement-ticket` Phase 6b (qa spawn) | same |
| 4 | Conductor direct edit | Trivial-path direct edits in any command | `conductor_direct` after the edit |
| 5 | Session total | `hooks/stop-context.js` | `session_total` once at session end |

Per typical loop iteration: 6 events (3 spawn pairs). Plus 1 session_total. Plus N `conductor_direct`. Matches the ~50 events/long-loop budget.

## Stop-hook session_total protocol

`hooks/stop-context.js` already runs as an independent Node process at session end. V1 adds a third write path:

1. Resolve `<cwd>/.agentic/events.jsonl`. If absent or empty, append nothing.
2. Resolve current `sessionId` from the Stop-hook stdin payload (already available - the hook reads it to write `context.md`).
3. Read `events.jsonl` line by line. Skip malformed lines (JSON.parse in try/catch). For each line where `event in {"spawn_complete","conductor_direct"}` AND the line's session matches (correlation: `data.session_uuid` is added to spawn_complete payload at conductor side; for `conductor_direct` events, the conductor includes `data.session_uuid` similarly), accumulate tokens and wall_seconds. By-agent rollup keyed on `agent` field.
4. Append one `session_total` line via plain `>>`.
5. Failure modes: file missing or empty -> append nothing. Truncated last line -> JSON.parse fails, line skipped, no abort. fs.appendFileSync error -> swallow silently (consistent with hook's existing failure model).

`hooks/stop-context.js` module manifest gains the third write path verbatim:

```
* (3) events.jsonl write is best-effort; any fs error is swallowed
*     independently of paths (1) and (2). The append failure model is
*     identical to context.md - the next session can re-derive totals
*     from per-spawn events if needed.
```

Each `spawn_complete` and `conductor_direct` payload includes `data.session_uuid` so the Stop hook can filter to the current session without ambiguity. (Multiple sessions can write to the same project's events.jsonl across time; the file is per-project, not per-session.)

## New Skeptic finding (verbatim addition)

Insert into `content/references/skeptic-protocol.md` Section 6 (Findings classification), under Minor:

```
- **Missing telemetry emit at an instrumented boundary.** When a conductor spawns engineer/skeptic/qa or performs a Trivial-path direct edit and `.agentic/events.jsonl` does not contain the corresponding `spawn_start`/`spawn_complete` or `conductor_direct` events for that boundary, flag as **Minor**. Does not block sign-off; surfaced for awareness so cost dashboards stay accurate.
```

This is the only Skeptic-spec change in V1.

## /agentic-cost spec (summary)

File `content/commands/agentic-cost.md` defines the command surface and points implementations at `bin/agentic-cost`. Implementation is a single Python 3 script (stdlib + pyyaml; pyyaml is a soft dep - if absent, the CLI runs with token-only output and prints "Install pyyaml for pricing support."). No new methodology surface beyond the command file itself.

The command spec MUST include a "V1 scope" section with this verbatim line: "V1 instruments engineer/skeptic/qa only; architect/investigator/debugger spawns are not counted." The same line appears as a footer on every `agentic-cost session|task|project` output (see "Output" examples above) so users see the disclosure without reading the spec.

## Cross-harness scope

V1 is Claude Code only. The transcript schema verified above is Claude-Code-specific. Codex CLI and Gemini CLI emit tokens differently (and in some configs, not at all). V2 adds a harness adapter layer; out of scope here. The events.jsonl schema is harness-agnostic (it just records numbers), so V2 is purely additive.

## Implementation steps

Hard prerequisite: **Gap 4 PR #27 must merge first.** After that merges, this branch rebases on updated `main` before any of the spec edits below. The Engineer must read the post-merge text of `content/agents/skeptic.md`, `content/agents/architect.md`, and `content/commands/implement-ticket.md` before editing - the Telemetry self-report fallback is dropped from V1, so most spec edits in those files are also dropped (see "Files NOT edited in V1" below).

All work in a feature worktree off `main`: `feature/gap-1-cost-observability`.

1. **Create worktree.** `git worktree add ../wt-gap-1-cost feature/gap-1-cost-observability` from `main` (after Gap 4 merges).
2. **Write `bin/agentic-emit`** (new file, ~30 LOC bash). Module manifest header recommended.
3. **Write `bin/agentic-parse-subagent-usage`** (new file, Python 3 stdlib only, ~80 LOC). Module manifest header REQUIRED (over 50 LOC + side-effecting file read).
4. **Write `bin/agentic-cost`** (new file, Python 3, stdlib + optional pyyaml, ~150 LOC). Module manifest header REQUIRED.
5. **Edit `hooks/stop-context.js`**: add the session_total write path; update module manifest to reflect three write paths.
6. **Edit `content/commands/implement-ticket.md`**: insert `agentic_emit spawn_start` / `spawn_complete` calls bracketing engineer, skeptic, and qa spawns in Phase 6 and 6b. Insertion points are relative to Gap 4's post-merge text - the Engineer reads the merged file first and inserts adjacent to existing spawn invocations, NOT touching Gap 4's tiered enforcement language. (Gap 4 edits line ~245; this edit goes immediately before/after the Task tool calls in Phase 6 and 6b regardless of Gap 4's exact final line numbers.)
7. **Edit `content/rules/agent-methodology.md`** Events log section: document the new event types (`spawn_start`, `spawn_complete`, `conductor_direct`, `session_total`) in the schema reference. ~15 lines added under existing Schema bullet list.
7a. **Edit `content/rules/agent-methodology.md`** Events log section, single-writer paragraph: reconcile the Stop-hook session_total writer with the existing single-writer claim. Framing (b) per Skeptic guidance - explicit carve-out with rationale.

   **Before** (verbatim, current text in the Events log section):
   ```
   **Single-writer scope: the conductor is the sole writer of `.agentic/events.jsonl`.** Subagents do not write to it. Other `.agentic/` files retain their own writers (qa.md by qa-engineer, tasks.jsonl by conductor, loop-state.json by conductor + Stop hook). The single-writer claim is scoped to events.jsonl only.
   ```

   **After** (verbatim, replaces the paragraph above):
   ```
   **Writer scope: the conductor is the primary writer of `.agentic/events.jsonl`.** The Stop hook (`hooks/stop-context.js`) appends a single `session_total` event at session exit; this is sanctioned because the conductor turn has ended by the time the hook fires, so there is no contention. Subagents do not write to it. Other `.agentic/` files retain their own writers (qa.md by qa-engineer, tasks.jsonl by conductor, loop-state.json by conductor + Stop hook).
   ```

   This edit MUST be in the same PR as the `hooks/stop-context.js` session_total write path (step 5) so the spec and implementation land atomically.
8. **Edit `content/references/skeptic-protocol.md` Section 6**: append the Minor finding verbatim above.
9. **Create `content/commands/agentic-cost.md`** (new file, command spec). Module manifest header recommended. MUST include the "V1 scope" line verbatim per "/agentic-cost spec" above.
10. **Update root README** with one-line pointer to `/agentic-cost`. Trivial.
11. **Smoke test**: in a throwaway worktree, run a small `/implement-ticket` loop end-to-end; verify events.jsonl populates and `agentic-cost session` prints a sensible table both with and without `~/.agentic/pricing.yml`. Verify the V1-scope footer appears in both outputs.
12. **Open PR** into `main` after Skeptic sign-off.

### Files NOT edited in V1 (scope-creep avoidance)

- `content/agents/engineer.md` - no Telemetry block needed; transcript parsing is primary.
- `content/agents/skeptic.md` - no Telemetry block; only Section 6 of `skeptic-protocol.md` gains the Minor finding.
- `content/agents/architect.md` - no edits in V1.

This eliminates the Gap 4 collision risk on `skeptic.md` lines 35/69 and `architect.md` line 56 entirely.

## Acceptance criteria

1. After running a multi-unit `/implement-ticket` loop, `.agentic/events.jsonl` contains paired `spawn_start`/`spawn_complete` events for every engineer/skeptic/qa spawn.
2. Each `spawn_complete` event has non-zero token fields and a numeric `wall_seconds`.
3. `agentic-cost session` runs in <2s on a session with 50 events.
4. With `~/.agentic/pricing.yml` absent, `agentic-cost session` prints token counts only and the explicit "Pricing not configured" line. No dollar figures appear anywhere in output.
5. With `~/.agentic/pricing.yml` present and current, dollar columns appear with the "Rates as of YYYY-MM-DD" footer.
6. Stop hook appends exactly one `session_total` event per session end.
7. `hooks/stop-context.js` manifest documents three independent write paths.
8. Skeptic protocol Section 6 contains the new Minor finding verbatim.
9. No edits to `content/agents/engineer.md`, `content/agents/skeptic.md`, or `content/agents/architect.md` in this PR.
10. `content/rules/agent-methodology.md` Events log section reflects the framing-(b) revision verbatim from step 7a; no remaining text in the methodology states the conductor is the "sole" writer of events.jsonl.
11. `bin/agentic-parse-subagent-usage` module manifest header includes the project-hash fallback under Failure modes AND the O(N projects) note under Performance, both verbatim from "API / interface design".
12. Every `agentic-cost` output (session, task, project; with and without pricing.yml) ends with the line: "Note: V1 instruments engineer/skeptic/qa only; architect/investigator/debugger spawns are not counted." `content/commands/agentic-cost.md` help text contains the same line in its "V1 scope" section.

## Risks and limitations

- **Conductor token usage is unmeasured in V1.** `conductor_direct` events record wall time only. Closing this requires reading the parent session JSONL at session end; deferred to V2 to keep the Stop hook simple.
- **Rate drift on opt-in pricing.yml.** Mitigated by the >90-day staleness warning, but the user is the only line of defense. Documented in the command help text.
- **Project-hash derivation depends on Claude Code's internal naming scheme** (`/` -> `-`, leading `-`). Verified empirically against existing project dirs but not formally specified by Anthropic. If the scheme changes, `bin/agentic-parse-subagent-usage` falls back to scanning `~/.claude/projects/*/<session-uuid>/subagents/` for a directory match.
- **Truncated last events.jsonl line on crash.** Tolerated by the parser (skip malformed lines). May cause one missing `spawn_complete` after a hard kill; user-visible as a footnote in `agentic-cost` output: "N events skipped due to malformed lines."
- **No cross-harness coverage.** Codex/Gemini sessions produce no token data in V1. Documented in `agentic-cost` help.

## Retention back-of-envelope

~250 bytes/event x ~50 events per long-loop session ≈ 12.5 KB. Operating budget per `agent-methodology.md` is ~50 KB. Well under. Manual `mv` to `events-prev.jsonl` remains the rotation story; no auto-rotate in V1.

## Open questions

None.
