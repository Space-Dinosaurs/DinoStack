---
name: ds-failure-audit
description: "Purpose: Mines the operator's own session telemetry and categorizes failure modes per model/harness"
user-invocable: true
---
# /ds-failure-audit

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

<!--
Purpose: Mines the operator's own session telemetry and categorizes failure modes per model/harness
         with quantified frequency. Conductor-invoked: orchestrates a single audit subagent that does
         the failure-mode categorization; the command itself never attempts deterministic
         categorization - a deterministic hook cannot reliably detect an LLM-semantic event.

Public API: /ds-failure-audit (conductor-invoked; no flags, no subcommands). Reads
            .agentic/events.jsonl, .agentic/session-log/*.jsonl, ~/.agentic/session-log/*.jsonl, and
            optionally .agentic/.enforcement-fires.jsonl; writes docs/planning/failure-audit-YYYY-MM-DD.md.

Upstream deps: content/references/events-log.md (event schemas); the operator's own telemetry files
               (.agentic/events.jsonl, both session-log surfaces); hooks/subagent-stop-spawn-emit.js and
               hooks/pre-tool-use-spawn-emit.js (hook-emitted spawn_start/spawn_complete variants);
               METHODOLOGY.md (activation preflight); bin/ds-cost (optional scoping rollups in Step 1).

Downstream consumers: build-all.sh (regenerates this command into all 11 adapter dirs); the operator,
                      who reads the conductor-presented report at docs/planning/failure-audit-YYYY-MM-DD.md.

Failure modes: the audit is agent-driven and read-only over telemetry; it soft-fails on missing sources
               (absent events.jsonl/session-log degrades the scope note, never errors). The single report
               write goes to docs/planning/ (gitignored); no telemetry file is modified. Self-report bias
               when the auditing model is the dominant one in the telemetry is mitigated by Step 2's
               non-dominant-model guidance.

Performance: one audit subagent spawn (~40 tool calls) per invocation plus a deterministic scoping pass
             of a handful of ls/grep calls. Negligible at the intended quarterly cadence.
-->

Mines the operator's own session telemetry and categorizes failure modes per model/harness with quantified frequency. Conductor-invoked: the conductor orchestrates a single audit subagent, and the subagent does the failure-mode categorization. The command itself never attempts deterministic categorization - a deterministic hook cannot reliably detect an LLM-semantic event (see the methodology design constraint), so failure-mode identification is agent-driven by construction.

**When to use:** when the operator wants data-driven evidence for agent-config changes - e.g. "which model kills the wrong process most often?", "how often do my agents stop early?", "which harness needs a stricter verify gate?". Run quarterly, after a model/harness change, or when workflow friction clusters suggest a model-specific pattern.

**Do not use to:** count tokens (use `/ds-cost`), turn recurring workflow friction into skills (use `/ds-skill-candidates`), or replace editorial judgment about a single observed incident. The output is a quantified trend report, not a verdict on any one session.

## Sibling tooling (this command fills the failure-mode axis)

The methodology already measures two axes of agent work; this command adds the third:

| Axis | Command / tool | What it measures |
|---|---|---|
| Cost | `/ds-cost` (`bin/ds-cost`) | token and wall-time rollups per agent/session/task from `.agentic/events.jsonl` |
| Friction-to-skill | `/ds-skill-candidates` | recurring workflow-friction domains (lifetime counts, accumulate >= 3) |
| **Failure modes** | **`/ds-failure-audit`** | **failure modes per model/harness with quantified frequency** |

The audit reuses the same telemetry the two siblings read - it is a new read pattern over existing files, not a parallel telemetry silo. Where the siblings surface "what happened" (cost) and "what recurred" (friction), this command surfaces "which model/harness failed, how often, and in what way".

**Related command:** `/ds-evaluate` is the pillar-effectiveness axis - it scores the methodology against the North Star pillars from live telemetry, using this audit's failure-mode categories as one measured input. This command stays focused on failure-mode categorization; `/ds-evaluate` does the per-pillar scoring.

## What the audit reads

The audit subagent reads three telemetry sources, plus one optional supplementary source if present:

1. `.agentic/events.jsonl` - orchestration-boundary telemetry: `spawn_start`, `spawn_complete` (the conductor-emitted `spawn_complete` variant carries `data.model`, `data.status`, `data.session_uuid`, and Skeptic calibration fields `findings_count`/`iteration`/`signed_off`; the hook-emitted variant carries none of the model/status/calibration fields by design - see Model axis), `session_total`, `tool_failure_workaround` (`data.tool`, `data.domain_tag`, `data.note`), `tracker_writeback`, `meta_review_complete`. Full schemas: `content/references/events-log.md`.
2. `.agentic/session-log/*.jsonl` - per-session rollups: `ts`, `developer_id`, `session_uuid`, `project_slug`, `branch`, and `data.by_agent`.
3. `~/.agentic/session-log/*.jsonl` - the global cross-project mirror of the same per-session schema.
4. `.agentic/.enforcement-fires.jsonl` - OPTIONAL supplementary: the guardrail fire log written by `hooks/lib/enforcement_log.py`. Repo-wide cumulative, NOT session-scoped - any tally from it must state that scope. Consult it only for guardrail-fire failure modes; never treat it as a per-session count. Rows carry `decision` values `"deny"`, `"allow_advisory"`, and `"allow"`; the `"allow"` rows come from `enforce-no-abdication.py`, the one hook that logs every verdict path rather than only its actions, so exclude them from any count of guardrail fires (they are clean conductor turns). They are still useful as the denominator when judging whether a guard is inert.

**Model axis:** only `spawn_complete.data.model` in `.agentic/events.jsonl` carries model identity. Session-log lines carry no model field. This is a rare, near-extinct event class: the dominant `spawn_complete` on real telemetry is hook-emitted (`data.source:"hook"`, written by `hooks/subagent-stop-spawn-emit.js`) and carries no `model`/`status`/calibration fields by design (`content/references/events-log.md` "Hook-emitted variant (DS-160)"); the model-carrying conductor-emitted variant is an LLM-semantic event observed on well under 1% of spawns, none after 2026-07-10 (`hooks/subagent-stop-spawn-emit.js:11-16`). Treat per-model attribution as unavailable unless the Step 1 scoping pass actually finds `data.model` values on disk.
**Harness axis:** V1 telemetry is Claude Code only (the same limitation `/ds-cost` documents for Codex/Gemini). The report renders a harness column that is currently always `claude-code`; the shape extends when cross-harness telemetry exists.

## Step 1 - Scope the audit (deterministic pre-step)

The conductor runs a read-only scoping pass to tell the audit agent what exists. This step is deterministic and reuses existing readers; the conductor does NOT categorize anything here.

1. Enumerate the sources:
   `ls -la .agentic/events.jsonl .agentic/session-log/*.jsonl ~/.agentic/session-log/*.jsonl 2>/dev/null`
2. Optionally reuse `/ds-cost` rollups as scoping context: `bin/ds-cost operator` (cross-project session counts) and `bin/ds-cost team` (per-developer counts).
3. Optionally extract the model set deterministically:
   `grep -o '"model":"[^"]*"' .agentic/events.jsonl | sort | uniq -c | sort -rn`

Write a one-paragraph scoping note with: which sources exist, how many session-log lines each has, and the model set. Pass this note verbatim to the audit agent in Step 3.

## Step 2 - Choose the audit agent's model/harness

The audit subagent runs under the model/harness the operator chooses. For objectivity, prefer a model/harness that is NOT dominant in the telemetry being audited - an agent categorizing its own failure modes carries the same self-report bias the technique exists to expose. If the operator has only one model, run the audit under it and note the bias in the report's Coverage limits.

## Step 3 - Spawn the audit agent

Spawn a single `investigator` Worker in background with the following execution contract (NLH format per `METHODOLOGY.md`):

*"You are a Worker agent. Produce a failure-mode audit of this operator's session telemetry and return your complete report. The main agent will present the report to the user."*

- outputs: a structured failure-mode report written to `docs/planning/failure-audit-YYYY-MM-DD.md` (substitute today's date) and returned in full
- budget: ~40 tool calls
- tool_scope: Read, Glob, Grep (read-only; the only write is the report path)
- completion_conditions: all available sources from the scoping note read; failure modes categorized per model/harness; every category carries a quantified frequency (count + relative share with an explicit denominator); coverage limits stated; report written using the template below; no telemetry file modified
- output_paths: `docs/planning/failure-audit-YYYY-MM-DD.md`

Pass the Audit brief below verbatim in the spawn prompt.

## Audit brief (verbatim - the binding contract)

You are categorizing failure modes in an operator's own AI-assistant sessions, per model and harness, with quantified frequency. This is agent-driven analysis - there is no deterministic classifier behind you, and you must not assume one ran. You read the raw telemetry and derive categories from evidence.

Data sources and what each contains:

1. `.agentic/events.jsonl` - orchestration-boundary telemetry: `spawn_start`, `spawn_complete` (the conductor-emitted `spawn_complete` variant carries `data.model`, `data.status`, `data.session_uuid`, and Skeptic calibration fields `findings_count`/`iteration`/`signed_off`; the hook-emitted variant carries none of the model/status/calibration fields by design - see Model axis), `session_total`, `tool_failure_workaround` (`data.tool`, `data.domain_tag`, `data.note`), `tracker_writeback`, `meta_review_complete`. Full schemas: `content/references/events-log.md`.
2. `.agentic/session-log/*.jsonl` - per-session rollups: `ts`, `developer_id`, `session_uuid`, `project_slug`, `branch`, `data.by_agent`.
3. `~/.agentic/session-log/*.jsonl` - global cross-project mirror, same schema.
4. `.agentic/.enforcement-fires.jsonl` - OPTIONAL, only if present: guardrail fire log. REPO-WIDE cumulative, not session-scoped - any tally from it must state that scope explicitly. Exclude `decision == "allow"` rows from any fire count (see the reading list above).

Rules:

- **Model axis:** only `spawn_complete.data.model` in `.agentic/events.jsonl` carries model identity. Session-log lines carry no model field. Declare the model axis unavailable - and state it as a coverage limit rather than inventing model attribution - when ANY of these holds: (1) events.jsonl is absent, (2) it has no `spawn_complete` lines, or (3) its `spawn_complete` lines exist but none carries `data.model` (the common case - hook-emitted `spawn_complete` carries no model field by design). When the axis is unavailable, report at the harness/session level, and fall back to per-agent rollups (`data.by_agent` in the session-log files - these are agent types, not models) only if some model identity is genuinely recoverable from what is present; otherwise mark per-model counts as unavailable. Never substitute the harness column for the model column.
- **Harness axis:** V1 telemetry is Claude Code only. Render the harness column as `claude-code` and state the limitation.
- **Categorization is evidence-derived, not a fixed taxonomy.** Derive failure-mode categories from clusters of signals you observe. Seed categories to look for (derive from evidence, do not force): "stopping early / no verification" (spawns with truncated scope; high rework; `tool_failure_workaround` notes describing manual follow-up), "tool misuse / destructive action" (`tool_failure_workaround` events naming process-kill or destructive tools), "convergence failure" (Skeptic `spawn_complete` with high `iteration`, `signed_off: false`, or large `findings_count` - note these calibration fields exist only on the sparse conductor-emitted skeptic variant; when they are absent, derive this category from what is actually present, e.g. repeated rework across rounds, a task accumulating many spawns in one session, or `tool_failure_workaround` notes describing review-loop friction, and do not force it when no calibration or rework evidence exists), "partial/rough draft delivery" (spawns whose downstream status implies rework), "guardrail fire" (enforcement-fires entries, stated repo-wide).
- **Every category needs quantified frequency: a count and a relative share, with the denominator named.** Preferred denominators, in order: (a) the model's sessions, (b) the model's spawns, (c) total sessions. State which you used. Example: "stopping early: 7 occurrences in 12 Opus 5 sessions (58% of Opus 5 sessions)". Do not report a count without a denominator.
- **Coverage limits are findings, not failures.** If a category cannot be quantified from telemetry alone (e.g. the raw transcript is not in scope), say so in the Coverage limits section and recommend whether a transcript-level audit is warranted.
- **Do not modify any telemetry file.** Read-only. The only file you write is the report at `docs/planning/failure-audit-YYYY-MM-DD.md`.

## Report template

The audit writes the report using this exact structure:

```
# Failure-Mode Audit - YYYY-MM-DD

## Scope
- Sources read: [list]
- Sessions analyzed: N (local: a, global: b)
- Models observed: [list]
- Harnesses observed: [list]
- Coverage limits: [what could not be determined]

## Failure modes by model/harness

### Model: <model-id> / Harness: <harness>
- **<failure-mode>** - count: N (X% of <denominator>)
  - Evidence: [event types / file lines]
  - Example: "<one concrete note>"
  - Severity: high | medium | low

(repeat per category; repeat per model/harness)

## Cross-model comparison

| Failure mode | model A (n=..) | model B (n=..) | ... |
|---|---|---|---|

## Recommended config changes
[one data-driven suggestion per failure mode, each tied to a quantified row above]
```

## Step 4 - Present to user

After the audit agent returns, the conductor:

1. Reads the report file.
2. Presents inline: models/harnesses covered, top failure modes by frequency, the cross-model comparison, and the full report path.
3. Does not change agent config itself. Approved follow-ups are implemented as normal ticket/PR work.

## Risks and failure modes

- **Self-report bias (primary):** an audit agent categorizing the same model it runs under may under-count its own failure modes. Mitigated by Step 2's guidance to route the audit under a non-dominant model/harness when available.
- **Telemetry sparsity:** a small number of sessions makes relative shares noisy. The audit must state the denominator and total session count so the operator can judge confidence.
- **Model-axis loss:** if events.jsonl is absent, lacks `spawn_complete` lines, or has `spawn_complete` lines with no `data.model` field (the common case - hook-emitted `spawn_complete` carries no model by design), the model axis is unavailable and the report degrades to a harness/session-level view, with per-model counts marked unavailable. Stated as a coverage limit, not a failure.
- **Over-quantification:** a category with count 1 given a precise percentage reads as more certain than it is. The audit reports small counts as raw counts first, percentage second.
- **Scope creep into transcripts:** raw session transcripts are NOT in scope. The audit flags when transcript-level evidence would be needed rather than expanding its own read scope.
