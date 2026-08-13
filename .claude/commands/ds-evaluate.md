---
description: "Evaluate methodology effectiveness against the North Star pillars from live telemetry."
---

> **Prerequisite:** If the /dinostack skill has not been loaded in this session, invoke it first before proceeding.

# /ds-evaluate

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

<!--
Purpose: Evaluate the methodology's effectiveness against the North Star pillars. Reads the pillar
         text LIVE from docs/overview/vision.md at runtime (never hardcoded), runs bin/ds-evaluate
         (the deterministic signal collector) for measured telemetry, spawns parallel per-pillar
         scoring subagents, and writes a date-stamped report.

Public API: /ds-evaluate (conductor-invoked; no flags, no subcommands). Reads docs/overview/vision.md
            and the bin/ds-evaluate JSON rollup; writes docs/planning/ds-evaluate-YYYY-MM-DD.md.

Upstream deps: docs/overview/vision.md (North Star pillar text); bin/ds-evaluate (signal collector,
               sibling unit); METHODOLOGY.md (activation preflight); the operator's telemetry files
               (read by the collector).

Downstream consumers: build-all.sh (regenerates this command into all 11 adapter dirs); the operator,
                      who reads the conductor-presented digest and docs/planning/ds-evaluate-YYYY-MM-DD.md.

Failure modes: scores are advisory, never a gate. Sparse telemetry degrades to a finding, never a
               false 0. Self-report bias when a scoring model evaluates the methodology it runs under
               is mitigated by Step 3's non-dominant-model guidance.

Performance: one deterministic collector run plus N parallel lens spawns (N = number of pillars),
             each ~15 tool calls. Negligible at the intended cadence.
-->

Evaluates the methodology's effectiveness against the North Star pillars. The conductor runs a deterministic signal collector (`bin/ds-evaluate --repo <repo>`) to gather measured telemetry, spawns one parallel scoring subagent per pillar, and merges the verdicts into a per-pillar scorecard. The pillar text is read LIVE from `docs/overview/vision.md` at runtime - it is never hardcoded here, so a pillar edit needs no command change.

**When to use:** periodically (quarterly), after a methodology change, or when the operator wants a pillar-by-pillar effectiveness snapshot grounded in measured signals rather than impression.

**Do not use to:** categorize failure modes per model/harness (use `/ds-failure-audit`), count tokens (use `/ds-cost`), or gate a merge - the scores are advisory by design.

## Positioning: the effectiveness-per-pillar axis

The methodology already measures three axes of agent work; this command adds the fourth:

| Axis | Command / tool | What it measures |
|---|---|---|
| Cost | `/ds-cost` (`bin/ds-cost`) | token and wall-time rollups per agent/session/task from `.agentic/events.jsonl` |
| Friction-to-skill | `/ds-skill-candidates` | recurring workflow-friction domains (lifetime counts, accumulate >= 3) |
| Failure modes | `/ds-failure-audit` | failure modes per model/harness with quantified frequency |
| **Pillar effectiveness** | **`/ds-evaluate`** | **methodology effectiveness against the North Star pillars, per pillar** |

This command is the effectiveness-per-pillar axis, alongside `/ds-failure-audit` (failure modes per model/harness), `/ds-skill-candidates` (friction-to-skill), and `/ds-cost` (tokens). It reuses their telemetry via the deterministic collector and cross-references them - it does NOT re-implement failure-mode categorization, friction-to-skill detection, or token rollups. `/ds-failure-audit` answers "which model/harness failed, how often, in what way"; `/ds-skill-candidates` answers "what workflow friction recurs"; this command answers "how well does the methodology serve each North Star pillar".

## Step 1 - Activation preflight

Run the Activation preflight from `METHODOLOGY.md`. If inactive, no-op and exit.

## Step 2 - Signal collection

The conductor runs the deterministic collector and reads its JSON rollup (stdout):

```
bin/ds-evaluate --repo <repo>
```

The rollup is the single measured-signal input to every pillar lens. Pass it verbatim to each lens. Per-signal data-quality caveats - both documented facts; state them in the report rather than "fixing" the numbers:

- **Tokens zero-filled:** token fields are zero when token attribution is unavailable (e.g. no opt-in pricing configured for `/ds-cost`). A 0 tokens signal is an absence of data, not a measurement of 0 - the report must say so.
- **Enforcement-fires is repo-cumulative, not session-scoped:** the enforcement-fires tally the collector reads (`.agentic/.enforcement-fires.jsonl`) is a repo-wide cumulative count. Never present an enforcement-fires figure as a per-session count.

If the collector fails or returns an empty rollup, treat the invocation as a sparsity finding (see Edge cases) - never proceed with an invented signal baseline.

## Step 3 - Pillar-lens scoring

Extract the North Star pillar list from `docs/overview/vision.md` (the "North Star" section) at runtime. Spawn ONE `investigator` subagent per pillar, in parallel (background), each briefed with:

- the pillar's verbatim text (from the live vision.md read in this invocation - never from memory)
- the signal JSON rollup verbatim
- the compact verdict contract below

Prefer a non-dominant model for at least one lens (self-report bias mitigation, mirroring `/ds-failure-audit` Step 2). If the operator has only one model, run all lenses under it and note the bias in the report.

Keep the brief contract compact - this command's output is a report, not a PR. Each lens returns a structured verdict:

- **score:** 1-5 (5 = the methodology fully serves this pillar)
- **evidence:** file:line references where the signal rollup / telemetry grounds the score
- **gaps:** concrete weaknesses against this pillar
- **action:** ONE candidate action that would most improve this pillar's score

## Lens brief (verbatim - compact contract)

"Score the dinostack methodology against this North Star pillar. Read the pillar text and the signal JSON rollup provided, and return a structured verdict: score (1-5), evidence with file:line references, gaps, and ONE action candidate. Ground every score in the signals; where the signal rollup does not cover a pillar, say 'insufficient data' instead of inventing a score. You are producing a report input, not a PR - keep the verdict to a few paragraphs."

## Step 4 - Synthesis

After the lenses return, the conductor:

1. Merges the verdicts into a per-pillar scorecard.
2. Writes the report to `docs/planning/ds-evaluate-YYYY-MM-DD.md` (gitignored - never committed).
3. Returns a compact digest inline: per-pillar scores, the top gap, and the top action candidate.
4. Flags gaps as actionable findings - optionally filed via the tracker helper, mirroring `/ds-feedback-triage` (only operator-approved items are filed).

## Report template

```
# /ds-evaluate - YYYY-MM-DD

## Signals
- Collector rollup: [signals present, coverage]
- Caveats: [tokens zero-filled / enforcement-fires repo-cumulative stated if used]

## Per-pillar scorecard

| Pillar | Score (1-5) | Evidence | Top gap | Action candidate |
|---|---|---|---|---|

## Gaps and actionable findings
[one per gap; optionally filed via the tracker helper]
```

## Edge cases

- **Signal sparsity:** insufficient data is a finding ("not enough telemetry to score this pillar"), never a false 0. A lens that cannot ground its score in the signal rollup says so, and the scorecard marks the pillar unrated.
- **Collector failure:** if `bin/ds-evaluate` errors or returns an empty rollup, the report records the failure as a finding and stops - it does not proceed with fabricated signals.

## Non-goals

- **Raw-transcript mining is OUT of scope** - the same stance as `/ds-failure-audit`. If a gap needs transcript-level evidence, the report flags it as such rather than expanding its own read scope.
- **Scores are advisory** - no gate, no required status check. The report informs; it does not block.
- **On-demand, not CI-wired** - this is the first cut. Wiring `/ds-evaluate` into CI is a deliberate future decision, not a requirement of this command.

## Risks and failure modes

- **Self-report bias (primary):** a lens scoring the methodology it runs under may rate its own host generously. Mitigated by Step 3's non-dominant-model guidance for at least one lens.
- **Hardcoded-pillar drift:** if pillar text were pasted into a lens brief from memory instead of read live, a vision.md edit would silently desync the report. This command always reads `docs/overview/vision.md` in the same invocation.
- **Signal sparsity:** thin telemetry makes scores noisy. The report must state per-pillar signal coverage so the operator can judge confidence.
- **Over-precision:** a score with a single weak evidence item reads as more certain than it is. Lenses report evidence first, score second, and mark small samples explicitly.
