# Agent Team (medium)

The medium tier ships a 6-agent team: `architect`, `debugger`, `engineer`, `investigator`, `orchestration-planner`, `skeptic`. All spawns run in background; the main session agent is the sole orchestrator — no agent spawns other agents.

## The team

| Agent                   | Role                                                                                                                                                                                                                                                                                          | Writes files? |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| `investigator`          | Codebase investigation. Traces data flow, maps blast radius, explores unfamiliar areas before design or implementation.                                                                                                                                                                       | No            |
| `debugger`              | Root cause analysis. Given a failure, diagnoses what's wrong and produces a fix brief.                                                                                                                                                                                                        | No            |
| `architect`             | Pre-implementation design. Reads the codebase, produces a structured technical plan with unit list and parallel/sequential ordering.                                                                                                                                                          | No            |
| `orchestration-planner` | Team composition and sequencing. Given a goal, produces a structured execution plan: which agents to spawn, in what order, with what handoffs, and where Skeptic review is needed. Optional for medium — the architect's inline `units[]` already carries `parallelizable` and `merge_order`. | No            |
| `engineer`              | Implements the change. Reads conventions, writes code, runs quality gates, reports clearly.                                                                                                                                                                                                   | Yes           |
| `skeptic`               | Adversarial reviewer. Reviews Worker output for Critical/Major/Minor findings. Cross-cutting review layer applied across every flow rather than producing a forward artifact.                                                                                                                 | No            |

`investigator`, `debugger`, and `architect` are read-only by construction (no Edit/Write/Agent tools). `skeptic` is hard-locked against Edit/Write/Agent. Only `engineer` ships write tools.

---

## Composed flows

### Standard feature

```
architect (plan)
    ↓
skeptic (plan review)  ←── required before proceeding
    ↓ sign-off
engineer (implement)  ←── re-routes findings
    ↓
skeptic (review)
    ↓ sign-off
done (manual QA / CI verifies runtime)
```

### Bug or broken test

```
debugger (diagnose)
    ↓ Confidence: High/Medium
engineer (implement fix)
    ↓
skeptic (review)
    ↓ sign-off
done

    ↓ Confidence: Low
escalate to human (describe what information is needed to close the diagnosis)
```

When the debugger returns `Confidence: Low`, do not proceed to engineer. The debugger's output will describe what specific information (logs, env values, reproduction steps, access to a running system) would close the diagnosis. Surface this to the user and wait for direction before re-spawning the debugger or proceeding to fix.

### Quick change (Low risk, 1-2 lines, no Elevated signals)

```
direct action (no agents needed)
    ↓
self-check
```

### Trivial change (single-file cosmetic or copy change, no logic impact)

```
[any subagent state] solo engineer Worker, isolation: "worktree"
    ↓
done (no Skeptic, no brief file, commit still required)
```

Trivial bypasses the Skeptic entirely. The conductor MUST NOT spawn a Skeptic for a Trivial task. The conductor availability rule drives the Worker/direct split: a conductor managing in-flight subagents must not block itself with direct implementation work — spawn the engineer Worker instead and remain available. If the Worker discovers mid-task that the change is not actually Trivial (e.g., the target file turns out to be a shared token file), it must stop and report; the conductor re-classifies as Elevated.

### Investigate before designing (unfamiliar area or shared utility)

```
investigator (map territory)
    ↓
architect (plan with grounded blast radius)
    ↓
skeptic (plan review)
    ↓ sign-off
engineer (implement) → skeptic (review) → done
```

`investigator` runs read-only codebase search and returns a compressed file:line table; it does not propose fixes. Use it when the right files are not yet known.

### Complex or ambiguous goal

```
orchestration-planner (produces execution plan)
    ↓
[execute the plan — agent sequence varies by task]
```

Use `orchestration-planner` when the right agent combination is not obvious, when multiple phases are likely, or when a high-level requirement needs decomposing before execution. It returns a structured plan the conductor follows directly. Skip when the architect's inline `units[]` already covers parallel/sequential ordering.

---

## Decision rules

**Use `orchestration-planner` when:**

- The task is complex and the right agents / sequencing are not immediately obvious
- Multiple phases are involved and you want to reason about them up front
- You want to avoid costly mid-task reclassification

**Use `architect` when:**

- The task involves meaningful design decisions (data model, API shape, integration points)
- The codebase is unfamiliar and exploration is needed before touching code
- The feature touches multiple subsystems and sequencing matters
- Skip it for well-understood, self-contained changes — go straight to `engineer`. The architect may also be mechanically skipped when the unit meets the simple/targeted-unit metric (`content/sections/04-risk-classification.md` §Simple/targeted unit (mechanical metric)) AND matches neither "Unfamiliar codebase area" nor "Architecture decision constraining future choices". Safety net: Mid-task reclassification (`content/sections/04-risk-classification.md` §Mid-task reclassification) applies if either hard exclusion turns out to be present after work starts.

**Use `debugger` when:**

- A test is failing and the root cause is not obvious
- A stack trace or production error needs diagnosis before a fix is attempted
- Skip it when the bug is already understood — go straight to `engineer`

**Use `investigator` when:**

- The target files are not yet known ("where does X live?", "what calls Y?", "map this directory")
- A shared-utility surface needs a per-consumer impact table before the architect designs
- Skip when the answer is a single `grep` away — do it inline

**Trivial risk skips Skeptic entirely.** Trivial tasks — single-file cosmetic or copy changes with no logic impact, where all qualifying signals hold — do not go through the Skeptic loop. A worktree-isolated `engineer` handles the shippable change with no Skeptic and no brief file; the conductor never edits the shippable tree directly (see the shippable/exempt classifier in `content/rules/conventions.md` §Git Workflow). When in doubt between Trivial and Elevated, choose Elevated.

---

## Spawning

Spawn all agents in background. The main session agent is the sole orchestrator — no agent spawns other agents.

When spawning `engineer`, include:

- The Architect's plan (if one was produced)
- Relevant file paths or codebase root
- Acceptance criteria
- 5-line inline Brief (scope, acceptance, non-goals, verification, blast radius) — no separate `docs/planning/<slug>.md` artifact in medium
- Session context (`~/.claude/projects/[hash]/context.md`)
- For Elevated-path spawns: the execution contract block from `METHODOLOGY.md` (Worker preamble section), with all required fields filled in from the architect's plan or orchestration-planner output

When spawned via `/implement-ticket` Phase 5 with a `task_id` in the execution contract, the engineer includes `task_id` in its return summary for conductor correlation. The conductor handles all `.agentic/tasks.jsonl` writes.

**Fan-out spawning.** When fan-out is active (N >= 2 parallel units), the conductor reads `unit_slug`, `merge_order`, and `skeptic_strategy` from the architect's `units[]` block at Phase 5 to determine worktree naming (`${FEATURE_BRANCH}-${unit_slug}`), merge ordering (sequential by `merge_order` value), and Skeptic review strategy (`per-unit` spawns one Skeptic per unit in parallel; `integration` defers to a single Skeptic after all units merge onto a scratch integration branch). All N engineers are spawned in a single message (parallel, background). The `task_id` field in each engineer's execution contract uses the format `<ticket_id>-<unit_slug>` for multi-unit correlation.

When spawning `skeptic` for architect plan review, include:

- The adversarial brief verbatim: "Check for internal consistency: does the document contradict itself, and are conclusions supported by the reasoning given? Surface assumptions: what is stated as fact but is actually assumed, and what would break if those assumptions are wrong? Check for prior decision conflicts: does this contradict established decisions or architectural constraints? Identify completeness gaps: what important questions does this document fail to answer, and what edge cases does it not address? Evaluate readability for the intended audience: would the engineer who needs to act on this have enough information to do so correctly and without guessing?"
- The architect's complete plan output
- Any established architectural constraints or prior decisions the Skeptic should check against

When spawning `skeptic` for engineer output review, include:

- The adversarial brief (run `/skeptic` for templates)
- The engineer's output (file paths or inline)
- Resolved issues preflight from prior rounds

---

## QA, wrap, and learnings in medium

Medium tier does **not** spawn `qa-engineer`, `wrap-ticket`, `learning-extractor`, or `learnings-agent`. Runtime verification is the operator's responsibility (manual browser walkthrough or CI). End-of-session sync uses `/wrap` for a plain-text summary. See the "When to upgrade to full" section in the medium skill (`skill://agentic-engineering-medium`) for the exact boundaries.

---

## Full tier only

These 12 agents ship only when `agentic_tier=full` (set via `/agentic-config` → tier full, or `--tier=full` on `/implement-ticket`): `qa-engineer`, `wrap-ticket`, `security-auditor`, `perf-analyst`, `dependency-auditor`, `release-orchestrator`, `product-discovery`, `adr-generator`, `adr-drift-detector`, `goal-condition-evaluator`, `learning-extractor`, `learnings-agent`.
