# conductor fixtures

Fixtures for the conductor / orchestration-planner component eval (Phase 3 of
the P2 self-improving-harness plan). Each fixture presents a mid-flow
scenario - goal, observed state, open findings, current phase - and labels
the single correct routing decision the orchestration-planner should emit.

## What this eval measures

Whether the named `orchestration-planner` subagent, given a structured
mid-flow scenario, selects the protocol-correct routing action as defined in
`content/agents/orchestration-planner.md` and `content/rules/agent-methodology.md`.
Sensitive to edits in either file.

## What this eval does NOT measure

- Main-session conductor in-flight routing (this is a proxy via the named
  subagent; the conductor eval runs the planner, not the session agent).
- Multi-turn recovery from mis-routing.
- Rationale quality beyond keyword coverage (the diagnostic surfaces a
  coverage fraction but does not fold it into `primary`).
- Interaction with real tool outputs.
- Session-level conductor behaviors that do not flow through
  orchestration-planner or agent-methodology.md.

## Fixture schema

Every fixture is a single `fixture.yaml` with these fields:

| Field | Type | Purpose |
|---|---|---|
| `id` | str | `co-NNN`. |
| `description` | str | One-line human summary used as the TSV `description` column. |
| `component` | str | Must be `conductor`. |
| `protocol_sha` | str | Git SHA of `content/agents/orchestration-planner.md` + `content/rules/agent-methodology.md` at labeling time. Runner warns on drift. |
| `scenario` | str (block) | Free-text paragraph: goal + what has happened so far. |
| `observed_state` | mapping | Structured mid-flow state. See below. |
| `inputs.invoke_instruction` | str | The final "task" line appended to the prompt. |
| `expected_decision` | mapping | The labeled correct decision. See below. |

### `observed_state`

| Field | Enum / type | Notes |
|---|---|---|
| `phase` | one of `skeptic_loop`, `qa_loop`, `pre_implementation`, `post_skeptic`, `phase7_quality_gate`, `fan_out_join`, `tight_fix_eligible`, `initial_planning` | The loop contract phase the conductor is in. |
| `iteration` | int | Current iteration (0 if N/A). |
| `max_iterations` | int | 3 by loop contract. |
| `last_engineer_status` | `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT` / null | From the prior engineer spawn if any. |
| `open_findings` | list of `{severity, id, re_raised}` | Accumulating findings_log-style entries. |
| `risk_signals` | list of str | Free-text tags pulled from `agent-methodology.md` signals. |
| `qa_triggers_matched` | bool / null | Whether the diff matches `.claude/qa.md` trigger patterns. |
| `other_context` | str (block) | Free-text task-specific details. |

### `expected_decision`

| Field | Enum / type | Notes |
|---|---|---|
| `decision_class` | one of `spawn_agent`, `re_enter_loop`, `escalate_cap_reached`, `escalate_convergence_failure`, `escalate_blocked`, `tight_fix_path`, `proceed_to_next_phase`, `terminate_clean`, `trivial_direct_edit` | Primary dimension. Full weight in the score. |
| `next_agent` | one of the named agents in `orchestration-planner.md`, or null | 0.5 weight sub-dimension when not null. |
| `loop_action` | `re_enter` / `exit_clean` / `exit_stalled` / null | 0.25 weight sub-dimension when not null. |
| `cost_class` | `critical` / `high` / `medium` / `low` | Diagnostic only. Not folded into primary (see below). |
| `rationale_keywords` | list of 3-5 stable terms | Diagnostic: fraction appearing (case-insensitive substring) in the planner's rationale is reported as `rationale_kw_coverage`. Not folded into primary. |
| `must_not_select` | list of agent names or decision classes | Hard penalty: if the planner chose any of these, 1.0 is subtracted before clipping. |

## cost_class rubric

`cost_class` is a fixture author's label for how expensive a wrong decision
would be in practice. It is used for fixture prioritization and triage, not
in the primary scalar.

| Class | When to label |
|---|---|
| `critical` | Escalation failures (missing a cap or convergence breach), security-surface routing, anything that would silently skip Skeptic on an Elevated change. |
| `high` | Wrong agent selection at a multi-phase handoff (e.g. skipping investigator before architect, skipping QA when triggered). |
| `medium` | Loop re-entry vs. alternative routing on a recoverable state (e.g. routing engineer into the right loop but wrong iteration framing). |
| `low` | Trivial direct-edit mis-classification that wastes one Worker spawn. |

Why `cost_class` is NOT in the primary scalar: folding it in would make
`primary` unbounded (one `critical` fixture could outweigh many `low` ones)
and would conflate two different questions: "did the conductor pick the
right routing?" vs. "how much does this specific fixture matter for
triage?". cost_class rides in diagnostic only. Known limitation, intentional.

## Match mechanics

- Enum fields (`decision_class`, `next_agent`, `loop_action`) are exact
  string match.
- `must_not_select` penalty triggers if the planner's chosen `next_agent`
  or `decision_class` is in the list.
- Rationale keywords are case-insensitive substring (no stemming).

## Known limitations

- **Labeled ground truth is author-defined.** Some routing decisions have
  genuinely ambiguous correct actions under `agent-methodology.md`; the
  fixture author's label is the operational definition for this eval.
- **Proxy measurement.** The eval invokes the named
  `orchestration-planner` subagent, not the main-session conductor. Session
  agent behavior outside the planner is not covered.
- **No multi-turn recovery.** A single decision is scored; the conductor's
  next move after a mis-route is not evaluated.

## Overfitting Rule

Any edit to `content/agents/orchestration-planner.md` or
`content/rules/agent-methodology.md` motivated wholly or partly by a TSV
score must satisfy the rule in
[`../../OVERFITTING-RULE.md`](../../OVERFITTING-RULE.md). Read it before
reacting to a score.
