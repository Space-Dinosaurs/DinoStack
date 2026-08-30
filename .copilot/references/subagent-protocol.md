<!--
Purpose: The outer orchestration frame for multi-agent sessions: when the main
         agent delegates, how it spawns, what it must put into a spawn prompt, and
         what it expects back. Normative for every spawn in the methodology.

Public API: Read-only reference, reached on trigger from the pointer table in
            `content/sections/12-protocol-details.md`. Consumable parts most often
            cited elsewhere: Section 2 (the Seven Rules), Section 6 (decomposition
            and review scope), Section 7 (shared-repo and worktree isolation),
            Section 10 (Input Contract), Section 11 (Output Expectations, including
            the two spawn-prompt obligations: `.agentic/context.md` content and
            `SESSION_KEY`), and Section 13 (conductor context budget).

Upstream deps: content/references/risk-config-and-tiers.md (role-default tier table
               the Input Contract's model-param rule defers to);
               content/references/learnings-capture-instruction.md §Session identity
               (the consuming side of the `SESSION_KEY` contract, which fixes the
               spawn brief as the only source an agent may read the key from);
               content/references/agent-team.md (the normative named-agent table
               Rule 4's "prefer named agents" guidance points to).

Downstream consumers: content/references/agent-team.md §Spawning and
                      content/references/delegation-detail.md §Worker Preamble and
                      Execution Contract Template, the two spawn checklists a
                      conductor actually fills - both restate the `SESSION_KEY`
                      line and point back here for its derivation rule, so a change
                      to that rule must be reflected in both;
                      content/references/skeptic-protocol.md (Section 9 of this file
                      defines their relationship);
                      content/sections/12-protocol-details.md (the pointer table
                      naming which sections are reachable on which trigger).

Failure modes: Prose; does not execute. Its characteristic failure is silence, not
               error: a spawn obligation stated only here, with no pointer from the
               table and no restatement in a spawn checklist, is not resident in a
               conductor's context and is simply never performed.

Performance: Standard.
-->

# The Subagent Protocol — Orchestration Methodology

## 1. Overview

The Subagent Protocol is the outer orchestration frame for multi-agent sessions. It governs when and how the main session agent delegates work to subagents, with one non-negotiable objective: **the main session agent must always remain free to respond to the user**.

The core principle: **the main agent is a conductor, never an implementer.** The conductor is the main session agent: it decomposes work, spawns specialist subagents that do the implementation and investigation, stays available to the user, and synthesizes results when those subagents report back. It does not implement, investigate, or run multi-step operations inline.

The Skeptic Protocol is a specific review pattern orchestrated by the main agent after a Worker returns. The main agent spawns the Worker, reads the result, then spawns a fresh Skeptic to review it. The Subagent Protocol is the outer frame that determines whether and how to delegate; The Skeptic Protocol determines how the main agent reviews Worker output before accepting it.

The principles are system-agnostic and apply to any orchestration agent capable of spawning subagents. On the current Claude Code harness, background `Agent` spawns notify the main agent on completion.

---

## 2. The Seven Rules

### Rule 1 — Always background delegated tasks (most critical rule)

**All delegated tasks run in background by default. Foreground is permitted only for the direct-action cases listed in Rule 7.**

A foreground subagent blocks the main agent entirely. The main agent cannot respond to the user, cannot process other completions, and cannot provide progress updates while a foreground task is running. This is the most severe violation of the protocol — it converts the conductor into a blocked implementer.

Background tasks free the main agent immediately. The main agent gives the user an upfront status update, stays available for follow-up questions, and reads the task's output when the completion notification arrives or when the result is needed.

### Rule 2 — Parallel by default

**Independent tasks spawn simultaneously in a single message, not sequentially.**

When decomposing a request into multiple subtasks, if tasks A, B, and C are independent - meaning B does not depend on A's output and C does not depend on B's output - spawn all three in the same message as separate `Agent` tool calls. Sequential spawning of independent tasks wastes elapsed time proportional to the number of tasks.

The main agent should be actively looking for parallelism: "Can I start B before A finishes? Can C run while A and B are both running?" If the answer is yes, they run in parallel.

When the conductor spawns workers for a multi-unit plan with task-state tracking, each worker receives its `task_id` in the execution contract for identification. The conductor writes all task-state updates - workers do not write to `.agentic/tasks.jsonl`.

### Rule 3 — Spawn threshold

**Elevated risk → spawn Worker + fresh independent Skeptic. Low risk → direct action. Trivial risk → delegate the shippable edit to a worktree-isolated `engineer` (no Skeptic, no brief file); the conductor never edits the shippable tree directly (see the shippable/exempt classifier in `content/rules/conventions.md` §Git Workflow).** The Skeptic Protocol defines two Elevated tiers (Elevated and Elevated + Cleanup); the main agent selects the appropriate path per The Skeptic Protocol Sections 0 and 12.

The delegation decision is driven by risk, not by counting tool calls. Assess risk first (see The Skeptic Protocol Section 0). If any Elevated signal is present, delegate to a Worker and apply adversarial review. If all signals are Low, direct action is appropriate. Trivial requires ALL qualifying signals to hold simultaneously - any single disqualifier pushes the task to Elevated.

"Looks simple" is not a Low signal. The uncertainty rule applies: when in doubt, classify as Elevated and spawn a Worker. When in doubt between Trivial and Elevated, choose Elevated. **Downward tie-break counterweight:** this default is overridden only when a named Low or Trivial override's full definition - including every exclusion clause - is affirmatively satisfied and zero other Elevated signals are present; "provably small" means the override can be named and each exclusion individually confirmed against the diff, not a general impression that the change looks safe.

**Trivial escape hatch:** If a Worker spawned for a Trivial task discovers mid-execution that the change is not actually Trivial (e.g., the target file turns out to be a shared token file, or the change requires touching a second file), it must stop immediately, report the finding to the conductor, and the conductor re-classifies the task as Elevated and applies the full Worker + Skeptic flow from that point.

### Rule 4 — Agent type discipline

**Choose the right agent type for the task. The wrong type silently degrades the protocol.**

| Task type | Agent type to spawn |
|---|---|
| Code implementation, file changes | `engineer` Worker (or the appropriate named agent) |
| Pure shell / git operations, low-risk | Conductor-direct (Bash tool) - no shell-only agent type exists |
| Codebase exploration, reading many files | `investigator` |
| Web research, doc reading, analysis, synthesis | `investigator` (or the appropriate named agent) |
| Multi-step investigation with possible follow-up | `investigator` |

**Critical constraint (platform property):** No subagent can spawn subagents - none of them have access to the spawn (`Agent`) tool. The main agent is the sole orchestrator. This is a property of every subagent type, not of any one agent.

**Prefer named agents over `general-purpose`.** The task types above map to a named DinoStack agent whose role, tools, and review posture are already scoped to that task - use it. Fall back to `general-purpose` only when none of the named agents fit the task. See `content/references/agent-team.md` for the full named-agent table (roles, write permissions, when to spawn each). For low-risk pure-shell or git operations, the conductor runs the command directly via the Bash tool rather than delegating - the harness has no shell-only agent type.

**Two-lock read-only contract.** Read-only agents (`architect`, `investigator`, `skeptic`, `qa-engineer`, `debugger`, `security-auditor`, `orchestration-planner`, `perf-analyst`, `dependency-auditor`, `adr-drift-detector`, `goal-condition-evaluator`) are kept read-only by two independent mechanisms: (1) `Edit`/`Write`/`Agent` are omitted from their `tools:` grant, and (2) those same tools are listed in each spec's `disallowedTools:` frontmatter. Lock (2) is enforced by Claude Code's classifier-before-spawn (subagent spawns are evaluated against permission rules before launch), so even if a future edit mistakenly adds `Edit` to one of these specs, the spawn is still blocked. `Agent` is denied on every read-only agent as config-drift insurance: no subagent spawns subagents, and the `disallowedTools` entry makes that mechanical rather than convention. (The per-spec boilerplate "Note on `tools`" wording about using `Edit`/`Write` "as needed" does not apply to these locked agents; several of them write files via Bash without ever holding the `Write` tool - `qa-engineer`, `adr-drift-detector`, `dependency-auditor`, and `perf-analyst` each write their own full report (and, for `qa-engineer`, a screenshot-evidence JSON file) to a single file under `.agentic/audit-reports/` or, for `qa-engineer`, `/tmp/qa-reports/` (deliberately `/tmp/`, not `.agentic/` - `qa-engineer` always runs `isolation: "worktree"`, and `.agentic/` is gitignored so it is independent per worktree checkout, invisible to the conductor once the throwaway worktree is removed), via a Bash heredoc, scoped to that one path, and return only a small pointer object referencing it; `qa-engineer`'s durable knowledge-capture output is a separate `qa-knowledge-json` payload returned in its report text, which the conductor appends to `.agentic/qa.md`.)

### Rule 5 — The Skeptic Protocol is orchestrated by the main agent

**When any agent - Worker or named specialist - returns output that produces a document, plan, or artifact that will drive decisions or be acted on by others, the main agent applies The Skeptic Protocol.** This includes architect plans: an architect plan is a high-leverage artifact and must receive Skeptic review before the conductor acts on it (spawning engineers, running the orchestration-planner, or any other downstream action). A flawed plan compounds errors through every Worker that follows it.

The Subagent Protocol determines the outer orchestration: does this task get delegated, to what agent type, in the foreground or background? The Skeptic Protocol is the review loop the main agent runs after the Worker returns: spawn a fresh Skeptic, read findings, route back to a Worker if needed, repeat until sign-off.

The main agent's responsibility in the relationship between the two protocols:
- Write and pass the adversarial brief to the Skeptic (verbatim — never softened)
- Spawn a fresh Skeptic after each Worker return
- Route Skeptic findings back to a new Worker if Critical or Major findings remain
- Accept output only after the Skeptic grants sign-off

The Worker's responsibility:
- Implement the specific assigned change and return the complete output
- Return output for main-agent-orchestrated Skeptic review - Workers do not self-review for Elevated tasks

Full specification of The Skeptic Protocol: `~/DinoStack/.claude/skills/dinostack/references/skeptic-protocol.md`.

### Rule 6 — Check in, don't disappear

**When background tasks are running, the main agent stays visible and responsive.**

When spawning background tasks, the main agent immediately tells the user:
- What is being worked on
- Approximately how long it will take
- What the main agent can answer right now without waiting

When a background task completes, the main agent is notified, proactively reads its output, and presents a clear synthesis to the user. The main agent does not wait for the user to ask "is it done yet?" - it monitors and reports.

If the user asks a question while tasks are running, the main agent answers directly from context. It does not defer with "waiting for the subagent to finish." Background work and foreground conversation are independent.

**Phase breadcrumb convention** — At each natural orchestration boundary, include a `[phase: label]` marker in the status update to the user. These labels are emitted inline in conversation (not written to files), so they remain in the transcript on any termination - normal or abnormal. On normal session end they are also captured in context.md, which aids handoff. The transcript is the primary crash-recovery source; context.md is a bonus. This makes orchestration state crash-recoverable without any extra infrastructure.

Emit a phase label at: after spawning any agent, after any agent returns, after escalation, at task completion. When the same turn also carries an `## Operator decisions` block (see `content/sections/02-delegation.md`), the breadcrumb is emitted before that heading - it is never satisfied by placement after it.

Format: `[phase: label]` — one line, no surrounding prose required. Add parenthetical detail when it aids recovery (round number, pending finding count, Worker progress).

**Phase vocabulary:**

| Label | Meaning |
|---|---|
| `architect-planning` | Architect agent is working on design |
| `plan-review` | Skeptic is reviewing architect's plan |
| `investigating` | Investigator is exploring codebase or tracing data flow |
| `orchestration-planning` | Orchestration-planner is mapping agent composition and sequencing |
| `implementing` | Engineer/Worker is implementing; include progress if multiple Workers, e.g., `implementing (2/3)` |
| `diagnosing` | Debugger agent is performing root cause analysis |
| `security-auditing` | Security-auditor is reviewing for vulnerabilities |
| `skeptic-review` | Skeptic is reviewing implementation; include round and pending findings, e.g., `skeptic-review (round 2, 1 Major pending)` |
| `sign-off-achieved` | Skeptic granted sign-off |
| `escalating` | Finding contested beyond re-route limit, escalating to human |
| `applying-minors` | Minor findings being applied post-sign-off |
| `cleanup` | /simplify pass running (Elevated + Cleanup path only) |
| `cleanup-review` | Narrow Skeptic reviewing /simplify diff |
| `qa-review` | QA engineer is verifying the change in a browser |
| `[loop: skeptic \| iteration N/3 \| open findings: X Critical, Y Major]` | Emitted by the conductor during Phase 6 Skeptic loop iterations in `/ds-implement-ticket`; include current iteration count, max cap, and open finding counts |
| `[loop: qa \| iteration N/3 \| open failures: X]` | Emitted during Phase 6b QA loop iterations; include current iteration count, max cap, and open failure count |
| `[phase: task-state-init \| N tasks written]` | Conductor initialized `.agentic/tasks.jsonl` with N pending task entries from the orchestration plan's JSONL block |
| `profiling` | Perf analyst is measuring latency, memory, or throughput |
| `releasing` | Release orchestrator is executing the release sequence |
| `dep-auditing` | Dependency auditor is scanning lockfiles and running vulnerability tools |
| `complete` | All work done, synthesizing results |

Example status update: "Skeptic spawned for round 1 review. [phase: skeptic-review (round 1)]"

**Loop breadcrumb examples:**
- `[loop: skeptic | iteration 1/3 | open findings: 2 Critical, 1 Major]`
- `[loop: qa | iteration 2/3 | open failures: 1]`

**Disk write accompaniment.** Emitting a `[loop: ...]` breadcrumb is paired with an atomic write to the ticket's own `.agentic/loop-state-<LOOP_KEY>.json` (tmp+rename) - loop state is keyed per ticket, so two sessions on two tickets in one checkout write different files; the unkeyed `.agentic/loop-state.json` is the legacy path, still read on resume but no longer written. The breadcrumb is the in-transcript crash-recovery signal; the disk write is the cross-session persistence mechanism. Both happen at the same phase transition event. The `last_phase` and `last_phase_action` fields in the disk file are the authoritative resume keys (not `loop_state.phase`, which is used only to reconstruct in-context state on resume). See `/ds-implement-ticket` Resume check and Phase 6 for the full schema and write-trigger list.

**Loop transition rules (BLOCKED / NEEDS_CONTEXT / DONE_WITH_CONCERNS inside a Skeptic or QA loop):**

These transitions apply to fix-pass Engineer spawns inside `/ds-implement-ticket` Phase 6 (Skeptic loop) and Phase 6b (QA loop). The iteration counter tracks only genuine fix attempts.

| Engineer status | Action | Iteration counter |
|---|---|---|
| `DONE` or `DONE_WITH_CONCERNS` | Normal progression. `DONE_WITH_CONCERNS` concerns become additional Skeptic brief context on the next iteration. | Increments normally |
| `BLOCKED` | Treat as immediate `cap_reached` escalation regardless of current iteration count. Emit escalation format with `termination_reason: blocked` and wait for human direction. | NOT incremented |
| `NEEDS_CONTEXT` | Conductor re-supplies missing context and re-spawns the Engineer with the same findings brief and added context. If the conductor cannot supply the needed context, escalate to the human. | NOT incremented |

**Format re-invocations:** Format-noncompliant Skeptic re-invocations (skeptic-protocol.md Section 11 permits up to 3) do NOT increment the iteration counter. They are administrative retries, not new review rounds.

**Loop contract pointer:** `/ds-implement-ticket` Phase 6 and Phase 6b define the full loop contract (state schema, max-iteration cap, findings accumulation rules, convergence failure conditions, and escalation formats). This file covers only the breadcrumb vocabulary and engineer-status transition rules. Consult `/ds-implement-ticket` for the authoritative loop specification.

### Rule 7 — Direct actions permitted without subagent

**Some actions are instant and do not block. These are done directly by the main agent.**

- Reading a single specific file when the path is already known
- Answering a question directly from context already in memory
- `git status`, `git log`, `git diff` — read-only, instant
- `ds-memory query` / `ds-memory turns` — read-only, instant; lightweight memory retrieval
- Taking a screenshot or browser snapshot
- Synthesizing and explaining results that subagents have already returned
- A one or two-line edit to a single file, where the correct output is immediately apparent without reading any other file, **and no Elevated risk signals are present**

These actions do not block meaningfully and do not benefit from delegation. Delegating them adds latency and context overhead with no quality gain.

When uncertain whether an edit meets the "immediately apparent without reading any other file" criterion — or when any Elevated signal is present — delegate.

---

## 3. Decision Table

**Two-question structure:** First, determine whether to delegate (consult the table below). Second, determine whether to background (apply the background rule). These are independent questions evaluated in sequence.

**Background rule (evaluated after the delegation decision, mandatory for all delegated work):** All delegated tasks run in the background (the harness default for `Agent` spawns). Foreground is permitted only for direct-action cases (Rule 7). This applies to every row below that results in "Spawn subagent." Background is not a row at the bottom of the table - it is a mandatory modifier on all delegated work.

**Risk assessment drives delegation.** The rows below map risk signals to the delegation decision. Any single Elevated signal in a task triggers Worker + Skeptic review.

**Authoritative signal list:** The Elevated signal list in this table is derived from and subordinate to `content/sections/02-delegation.md` and `content/sections/04-risk-classification.md`, the canonical sources for risk classification (assembled into the METHODOLOGY.md / `/dinostack` skill embed). Consult those two sections directly when this table and the risk classification signals differ.

For the following five carrier rows, `relaxed` applies the ordered **relaxed ephemeral
chat-advice override** from the canonical risk section: all four predicates must pass before a
carrier is considered, then the complete remaining Elevated signal list is scanned and any
remaining Elevated signal wins. `default` and `strict` retain the baseline treatment.

| Signal / condition | Main agent direct? | Spawn Worker + Skeptic? |
|---|---|---|
| Read a single known file | Yes | No |
| `git status` / `git log` / `git diff` (read-only) | Yes | No |
| Answer a question from context in memory | Yes - but a recommendation is Elevated unless the relaxed ephemeral chat-advice override fully qualifies | No |
| Take a screenshot or snapshot | Yes | No |
| Synthesize already-returned subagent results | Yes - but a recommendation is Elevated unless the relaxed ephemeral chat-advice override fully qualifies | No |
| 1–2 line edit, single file, correct output apparent, no Elevated signals | Yes | No |
| Trivial risk (ALL qualifying signals hold) - any subagent state | No (delegate to worktree-isolated `engineer`; no Skeptic; no brief file) | No |
| Security / auth / crypto / payments / secrets | No | **Yes** |
| Irreversible operation (delete, migration, schema change, force push) | No | **Yes** |
| Architecture decision constraining future choices | Discussion only when the relaxed ephemeral chat-advice override fully qualifies; an actual decision is never direct | **Yes**, except qualifying relaxed discussion |
| Modifies protocol or infrastructure files | No | **Yes** |
| Production or shared state | No | **Yes** |
| Multi-file change (any size) (relaxed profile: see the bounded 2-3-file behavioral-edit Low override in `content/sections/04-risk-classification.md` §Risk profiles - classify by logical/structural scope, not how the diff is chunked into commits; failing the connectivity bound routes to Elevated) | No | **Yes** |
| New file creation (a new colocated test/fixture/snapshot accompanying an existing Low-tier edit rides that edit's tier - Low, never auto-Trivial; a new file that exports a public symbol, a shared utility, a protocol/infrastructure file, or a new top-level module remains Elevated regardless of profile) | No | **Yes** |
| Touches external APIs or services | No | **Yes** |
| Unfamiliar codebase area ("haven't Read this file in the current conversation", "Read it earlier but it changed since", "first time working in this subsystem") | No | **Yes** |
| Logic with emergent/non-obvious cross-component interactions | No | **Yes** |
| Changes to shared utilities, helpers, or abstractions used across many call sites (single-file but high blast radius) | No | **Yes** |
| User signals high stakes ("production", "critical", "don't mess this up") | No | **Yes** |
| Any Bash with side effects (writes, deletes, network, DB) | No | **Yes** |
| Document synthesis / architecture / planning | Chat discussion only when the relaxed ephemeral chat-advice override fully qualifies | **Yes**, except qualifying relaxed chat |
| Research that produces an artifact (doc, plan, recommendation) | Chat advice only when the relaxed ephemeral chat-advice override fully qualifies; artifact production is never direct | **Yes**, except qualifying relaxed chat |
| Configuration changes | No | **Yes** |
| Anything where a mistake costs time or data | No | **Yes** |

**Clarification - Trivial vs. the "1-2 line edit" row:** For cosmetic, copy, or Tailwind-class edits, the Trivial disqualifier checklist (ALL signals must hold) takes precedence over the older "1-2 line edit" row. A conductor must not bypass the Trivial disqualifier gate by invoking the "1-2 line" row - if an edit looks cosmetic, run the Trivial checklist first. Only if ALL Trivial signals hold does the Trivial path apply. If any disqualifier is present (e.g., the file is a shared token file, or the change touches 2+ files), the task is Elevated regardless of line count.

**Default rule:** when in doubt, classify as Elevated and spawn a Worker. Direct action is the narrow exception. **Downward tie-break counterweight:** same rule as the "### Rule 3 — Spawn threshold" section above - the default is overridden only when a named Low or Trivial override's full definition, including every exclusion clause, is affirmatively satisfied and zero other Elevated signals are present.

**Footnote — new file creation:** The 1–2 line direct-action exception applies exclusively to modifications of existing files. New file creation always requires a Worker regardless of line count. This footnote is distinct from the new-file colocated-test qualifier on the "New file creation" signal above (Section 3 table): that qualifier governs whether new-file creation triggers Elevated risk classification at all; this footnote governs only the separate 1–2 line direct-action carve-out for edits to existing files, which never applies to new files regardless of any qualifier above.

---

## 4. Agent Type Selection Guide

| Condition | Agent type |
|---|---|
| Task involves code or file changes | `engineer` Worker (Skeptic Protocol applies) |
| Task involves planning or design | `architect` (or `orchestration-planner` for team composition) |
| Task involves synthesis, research | `investigator` (or the appropriate named agent) |
| Task is low-risk pure shell / git, no delegation needed | Conductor-direct (Bash tool) - no shell-only agent type exists |
| Multi-file codebase exploration | `investigator` |
| None of the named agents fit the task | `general-purpose` Worker |

No subagent - named or `general-purpose` - can spawn further subagents; the main agent is the sole orchestrator (see Rule 4 above).

**Pure-shell and git operations are not a reason to skip the risk table.** Low-risk shell/git runs conductor-direct via the Bash tool; any shell task that touches code, synthesizes files, or carries Elevated risk signals is a Worker task that goes through Skeptic review - route it to the appropriate named agent (falling back to `general-purpose` only when none fit), never treat it as "just a shell command" to escape review.

---

## 5. Background vs. Foreground Decision Rule

**Default: background.**

**Absolute rule:** All delegated tasks run in background by default. Foreground is permitted only for the direct-action cases listed in Rule 7. If you need the result of a background task, spawn it in background, give the user a status update, and wait for the completion notification rather than blocking inline.

| Condition | Run mode |
|---|---|
| Delegated task (any dependency state) | Background (mandatory, no exceptions) |
| Direct-action case (Rule 7 list) AND result needed immediately | Foreground permitted |
| Direct-action case (Rule 7 list) AND result not immediately needed | Background preferred |
| Task is independent of other tasks | Background |

The only legitimate use of foreground is a direct-action case (Rule 7) whose result is required before the main agent can form any coherent response.

---

## 6. Composition Pattern - Decompose Before Delegating

The standard orchestration sequence:

1. **Decompose** - break the user's request into atomic units. Each unit should be a single concern that one focused Worker can implement correctly without needing context from other units' implementation details. "One agent, one task, one prompt."
2. **Classify risk per unit** - each atomic unit gets its own risk classification. Some may be Low (direct action), some Elevated (Worker + Skeptic).
3. **Spawn in parallel** - launch all independent Workers simultaneously (background). Sequence units that depend on each other's output.
4. **Stay available** - tell the user what is running and what to expect; answer any follow-up questions directly.
5. **Review with appropriate scope** - apply "decompose implementation, not review" (see below).
6. **Synthesize** - when Workers and Skeptics return, combine outputs into a clear summary.

### Review scope rules

Workers are decomposed for focus. Skeptic review is scoped for effectiveness:

- **Independent elevated units:** each gets its own Skeptic reviewing that unit's diff. Small diffs produce high-signal reviews.
- **Interdependent elevated units** (changes that must be consistent across files or components): separate focused Workers implement each piece, but **one Skeptic reviews the combined diff**. This integration Skeptic replaces per-unit Skeptics for these units - do not run both. Cross-cutting risks live in the interactions, not in individual files.
- **Low-risk units:** direct action with self-check. No Skeptic.

**Heuristic for interdependence:** if a bug in unit A would only be detectable by examining unit B's implementation, or if unit A's correctness depends on assumptions about unit B's interface, the units are interdependent and need an integration Skeptic.

**Fan-out Skeptic strategy mapping.** When the parallel fan-out primitive is active (N >= 2 independent units from the orchestration-planner), the planner's `skeptic_strategy` field is the authoritative source for which review mode applies:

- **`per-unit`**: each unit gets its own Skeptic reviewing that unit's individual diff (against `BASE_BRANCH`). Skeptics for independent units can be spawned in a single message (parallel) - they are reviewing non-overlapping diffs and there is no interference. This is the strategy when all units in the group are fully independent per the heuristic above.
- **`integration`**: one Skeptic reviews the combined diff from `BASE_BRANCH` after all units are merged, inside a dedicated integration worktree, onto `FEATURE_BRANCH` itself (never `$REPO` - see `/ds-implement-ticket` Phase 5's Merge phase). Provisionality comes from staying unpushed until Phase 8, not from a separate branch name. This replaces per-unit Skeptics - do not layer integration on top of per-unit. This strategy applies when units share an interface contract, shared data model, or cross-cutting concern. The integration Skeptic also serves as the Phase 6 gate (see `/ds-implement-ticket` Phase 6 guard).
- **`multi-dimensional`**: reserved for high-stakes Elevated units where correctness, security, and performance must all be reviewed in a single pass. The conductor fans out three reviewers in one message (parallel, background): a correctness-Skeptic, a `security-auditor`, and a `perf-analyst` - all reviewing the same diff simultaneously. The conductor then synthesizes all findings before opening any fix loop. This mirrors the `/simplify` fan-out pattern (see Section 12) applied to review rather than cleanup. Use `multi-dimensional` only for units in security-sensitive domains: authentication, payments, data migrations, crypto, secrets management, or any path where a correctness bug and a security flaw could coexist undetected. Sign-off requires all three reviewers to clear - a single open Critical or Major finding from any reviewer blocks completion.

The orchestration-planner's classification (written into the JSONL block at planning time) governs which strategy the conductor applies at Phase 5. The conductor reads `skeptic_strategy` from the planner's JSONL block - it does not re-derive the strategy from plan prose or apply the heuristic itself at execution time.

The principle: overusing Skeptics dilutes their value. Narrow Workers improve implementation correctness. Broad Skeptic scope (where warranted) catches interaction bugs that per-unit review would miss.

**Mid-task re-decomposition:** If a Worker discovers its scope is still too broad during execution, it returns partial output with a decomposition request. The conductor then decomposes further and re-spawns focused Workers. See Skeptic Protocol Section 5.

At no point in this sequence does the main agent become an implementer. All steps are conductor actions.

---

## 7. Shared Repo Isolation

**Parallel agents writing to the same git repository must use worktree isolation.**

### The rule

When spawning two or more agents that will write to the same git repository simultaneously, always pass `isolation: "worktree"` in the `Agent` tool call.

### Why

Git's working tree is shared state. When two agents run concurrently in the same directory and either agent runs `git checkout` or `git checkout -b`, it moves the working tree to a different branch - overwriting whatever the other agent has staged or modified. The second agent then reads, modifies, or commits files from the wrong branch. This is not a recoverable situation mid-run; the working tree state is silently corrupted.

Worktree isolation gives each agent its own copy of the repo at a separate filesystem path on its own branch. The agents do not share a working directory, so concurrent checkouts cannot interfere.

### How

Pass `isolation: "worktree"` in the `Agent` tool call when spawning parallel agents:

```
Agent(
  prompt="...",
  isolation="worktree"
)
```

The `Agent` tool creates a temporary git worktree for the agent to work in - an isolated copy of the repo at a separate path on its own branch. When the agent finishes, the worktree is cleaned up.

### Nested repo caveat

`isolation: "worktree"` requires Claude Code to be running inside the correct git repo root. If the project directory is nested inside a parent git repo, the `Agent` tool may walk up the directory tree and resolve to the parent repo instead - causing worktree creation to fail even though the project directory has its own `.git`.

**Symptom:** `isolation: "worktree"` fails with "Cannot create agent worktree: not in a git repository and no WorktreeCreate hooks are configured" even though Claude Code is launched from within the project directory.

**Diagnosis:** Run `git rev-parse --show-toplevel` from the project directory and from the parent. If both return different roots, the parent repo is interfering.

**Fix:** Add the project directory to the parent repo's `.gitignore`. This makes git (and the `Agent` tool) treat the project as an independent repo rather than a subdirectory of the parent.

```bash
# Example: authentic8/ nested inside ~/
echo "Documents/Development/authentic8/" >> ~/.gitignore
```

### Manually-managed named worktrees (fan-out primitive)

The fan-out primitive in `/ds-implement-ticket` Phase 5 uses a different worktree model from the Agent tool's `isolation: "worktree"`. Both are valid; the choice depends on whether merge order and branch naming matter.

| Mode | Branch naming | Cleanup | Use when |
|---|---|---|---|
| `isolation: "worktree"` (Agent tool) | Anonymous temporary branch, auto-named by the tool | Auto-cleaned by the tool if no changes; conductor removes after PR | Single-agent isolation; merge order does not matter |
| Manually-managed (fan-out) | Explicit named sub-branches: `${FEATURE_BRANCH}-${unit_slug}` | Conductor removes explicitly after all merges or escalation | Multi-branch fan-out; merge order and branch naming matter for history attribution |

Manually-managed worktrees are created with:

```bash
git -C $REPO worktree add ${REPO}/.worktrees/${FEATURE_BRANCH}-${unit_slug} \
  -b ${FEATURE_BRANCH}-${unit_slug} origin/$BASE_BRANCH
```

The `unit_slug` comes from the orchestration-planner's JSONL block. The conductor controls merge ordering (via `merge_order` from the planner) and removes worktrees and sub-branches explicitly after the merge phase. This model preserves attributable merge history in the git graph - each unit's sub-branch is visible in `git log --graph`, making conflict locality traceable.

### When NOT needed

- A single agent working alone — no parallel agent to collide with
- Agents working in fully separate repositories — no shared working tree
- Read-only agents that do not run `git checkout`, stage files, or commit

### Violation pattern

Two track agents spawned in parallel in the same directory. Track A checks out its feature branch. Track B checks out its feature branch. Track A's working tree is now on Track B's branch. Track A stages and commits files that were modified on the wrong branch. Both agents' work is corrupted.

---

## 8. Anti-Patterns

**Foreground blocking** - The most critical anti-pattern. Spawning delegated work on the foreground/synchronous path when it should run in the background. Blocks the main agent entirely for the duration. Foreground is reserved only for direct-action cases (Rule 7). There is no justification for foreground on any delegated work.

**Sequential when parallel is possible** — Spawning subagent B after waiting for subagent A when B does not depend on A's output. Multiplies elapsed time unnecessarily.

**Treating risky shell/git as conductor-direct to dodge review** - Running a shell or git operation that carries Elevated risk signals (writes to shared state, irreversible ops, multi-file effects) directly in the conductor instead of delegating to a Worker with Skeptic review. Low-risk shell/git is correctly conductor-direct; the anti-pattern is using "it's just a shell command" to escape the risk table. There is no shell-only agent type to misuse - the failure mode is now under-reviewing direct execution, not mis-routing to a degraded agent.

**Main agent doing implementation work** — The main agent writing code, editing multiple files, or running multi-step investigations inline rather than delegating. Violates the conductor principle and bypasses The Skeptic Protocol review gate.

**"Looks simple" rationalization** — Classifying work as Low risk to avoid delegation on genuinely risky work. Simple-looking tasks are where The Skeptic Protocol is most often skipped and where unreviewed errors accumulate. "Looks simple" is not a Low signal — apply the uncertainty rule and classify as Elevated when any doubt exists.

**Deferring synthesis** — Waiting for all background tasks to complete before responding to the user at all. The main agent should give an upfront status update immediately after spawning, and answer follow-up questions from context while tasks run.

**Softening adversarial briefs** — When passing a domain adversarial brief to a Worker (for The Skeptic Protocol), the main agent must pass it verbatim. Summarizing or softening the brief degrades adversarial independence.

**Priming adversarial briefs with conductor hypotheses** - Injecting a conductor-composed suspicion, hypothesis, or attention-steer ("look hard at X, I think it's wrong") into a Skeptic spawn brief or Global-context field 7. This is the inverse failure to softening: instead of weakening the brief, it manufactures findings where the conductor guessed and suppresses independent discovery everywhere else. There is no carve-out for an operator-attributed steer - see `content/references/skeptic-protocol.md` Section 7 "Neutrality requirement (independent of completeness)" for the full rule, the falsifiability distinction from subagent-sourced content, and why no legitimate capability is lost.

**Treating small edits as self-verifying** — Deciding that a small change doesn't need delegation because "it's only a couple of lines." The 1–2 line threshold for direct action applies only when the correct output is immediately apparent without reading any other file and no Elevated signals are present. Any edit involving Elevated signals must be delegated regardless of size.

---

## 9. Relationship to The Skeptic Protocol

The two protocols are complementary and operate at different levels of the agent stack.

| Dimension | The Subagent Protocol | The Skeptic Protocol |
|---|---|---|
| Scope | Main agent → subagent delegation | Main agent → Worker/Skeptic review loop |
| Question it answers | Should this be delegated, and how? | Is this implementation correct and safe? |
| Who applies it | Main agent (orchestration decisions) | Main agent (review orchestration after Worker returns) |
| When it activates | On every non-trivial task | On Elevated-risk tasks: code, file changes, or synthesis producing an artifact that drives decisions or action. Two Elevated tiers exist (Elevated and Elevated + Cleanup); the main agent selects based on implementation scope (see Skeptic Protocol Sections 0 and 12). Trivial-risk tasks bypass the Skeptic Protocol entirely. |
| Relationship | Outer frame | Inner review loop, orchestrated by main agent |

**Risk vocabulary recognized by this protocol:** Trivial (single-file cosmetic or copy change, no logic impact, no Skeptic), Low (direct action with self-check, no Skeptic), Elevated (Worker + Skeptic), Elevated + Cleanup (Worker + Skeptic + /simplify + narrow Skeptic). When in doubt between any two tiers, choose the higher tier.

The Subagent Protocol does not replace The Skeptic Protocol — it provides the orchestration context in which The Skeptic Protocol is invoked. After a Worker returns, the main agent drives the Skeptic loop: spawning fresh Skeptics, routing findings, and iterating until sign-off. Workers cannot spawn subagents (platform constraint) — the main agent is the sole orchestrator of both protocols.

---

## 10. Input Contract

When spawning an `engineer` Worker on an Elevated-risk task, the conductor includes an execution contract block in the spawn prompt. The canonical template lives in `METHODOLOGY.md` (Worker preamble section). Required: outputs, tool_scope, completion_conditions. Optional: budget (advisory, not enforced). Conditional: output_paths (required when pre-specified by the architect plan, otherwise "conductor-directed").

The conductor OMITS the `model` param to accept the spawned agent's frontmatter role-default tier (see the Role-default tier table in `content/references/risk-config-and-tiers.md`); it passes an explicit `model` param only to OVERRIDE a specific spawn - upgrading a Tier-2 agent to Tier 3 for a novel-architecture unit, asserting a mandated-Tier-3 Skeptic, or a Tier-1 mechanical task. Claude Code: `haiku`/`opus` for the override; other harnesses resolve from tier-map or omit. Codex/Gemini: if a tier-map file exists (`.agentic/tier-map.yml` project-local or `~/.agentic/tier-map.yml` user-global), pass `--model <resolved-name>` from it; if no tier-map exists, omit `--model` and the CLI uses its session default (there is no hardcoded fallback). The model param is an implementation detail of the spawn call, not part of the spawn prompt text.

Two spawn-prompt obligations are wider than this contract and are stated in Section 11 rather than here, because they hold for every Worker on every path rather than for contract-carrying `engineer` spawns only: the `.agentic/context.md` content, and the `SESSION_KEY` line. See Section 11, "**Spawning Workers**" and "**`SESSION_KEY` at spawn time**".

Scope: this contract applies to `engineer` spawns only for Phase 1.1. Other named Workers (`architect`, `investigator`, `debugger`, `qa-engineer`, `security-auditor`, `perf-analyst`, `release-orchestrator`, `dependency-auditor`, `orchestration-planner`, `general-purpose`) and Trivial-path solo `engineer` spawns are out of scope - use the existing freeform preamble for those.

---

## 11. Output Expectations

When a Worker returns to the main agent under this protocol, the main agent expects:

- **Final output** — the complete implementation artifact, or file paths to it if the output is large
- **Round summary** — what changes were made and why (if Skeptic findings were routed back)
- **Memory update requests** — any architectural decisions or qualifying context the Worker believes should be recorded (the main agent serializes these writes, not the Worker directly)

**Spawn-brief provenance:** every claim-bearing sentence the main agent writes into a spawn prompt (a value, path, count, or root-cause/rationale assertion) must carry a provenance tag per the provenance test in `content/sections/04-risk-classification.md`. This is a spawn-time obligation on the main agent, not on the Worker's return - the Skeptic checks it via Global-context field 7 (`content/references/skeptic-protocol.md` §4.5). Worked example, stated abstractly: a Skeptic Minor naming a suggested value is not license to invent the underlying rationale for a file the conductor never read - pass the finding and the file path to the engineer attributed to the Skeptic that raised it, and never with a rationale the conductor did not itself verify.

**Sign-off is the main agent's responsibility.** The main agent spawns Skeptics and accumulates the exchange log. A Worker does not return a sign-off statement — the Skeptic provides sign-off to the main agent directly.

**Re-route limit:** After the same finding is contested for 2 or more re-routes without resolution, the main agent stops and escalates that finding to the human with: the exchange log, the contested finding, and the Worker and Skeptic positions on it. Do not attempt further re-routes without human direction.

**Side effects:** Workers must not apply irreversible changes (file overwrites, database mutations, published state) without informing the main agent that sign-off is required before those changes are safe. Workers that must stage irreversible changes as part of their implementation must include a revert procedure in their return output.

**Spawning Workers:** The main agent must include the project context file content (`.agentic/context.md`) in each Worker's spawn prompt. Workers must not be expected to self-direct context reads - they may not have reliable access to the path or the protocol, and a worktree-isolated Worker cannot reach `.agentic/context.md` at all (`.agentic/` is gitignored, so it is absent from a fresh worktree checkout). The main agent is responsible for providing session context at spawn time.

**`SESSION_KEY` at spawn time:** The main agent must also include a `SESSION_KEY` line in **every** Worker's spawn prompt. This is the same shape of obligation as the context file above and holds for the same reason: `SESSION_KEY` is conductor-supplied session state, not something a Worker can derive. `content/references/learnings-capture-instruction.md` §Session identity makes the spawn brief the *only* source an agent may read it from, and an agent whose brief omits it skips shard capture **silently**. A missing line therefore raises no error anywhere; it just means the learning was never recorded.

Derive the value **once per session**, at the first Worker spawn, and pass that same value on every spawn thereafter:

1. If `$CLAUDE_CODE_SESSION_ID` is set and non-empty, use it verbatim.
2. Otherwise generate one key and carry it in the session's own working state:

```bash
printf 'ds-session-%s-%s\n' "$(date -u +%Y%m%dT%H%M%SZ)" \
  "$(od -An -N2 -tx1 /dev/urandom | tr -d ' \n')"
# ds-session-20260810T142233Z-9f2c
```

Three rules govern that derivation, each with a live counter-example in this repo:

- **Only Claude Code exposes a session id to the conductor's shell.** Every other adapter keeps its id inside its own hook or plugin process (`payload.session_id`; OpenCode's `.opencode/plugins/session-context.ts` reads `event.properties.sessionID`) and never exports it to the model's shell. On Claude Code a subagent inherits the identical `$CLAUDE_CODE_SESSION_ID`, so the brief line is belt-and-braces there rather than load-bearing. Pass it regardless, so one rule holds on every harness.
- **Never substitute a cross-harness environment variable.** `AGENTIC_SESSION_ID` and `CLAUDE_SESSION_UUID` are both empty in a live session, and `bin/ds-migrate` is silently degraded today precisely because it reads them. `content/commands/ds-wrap.md` records the same measurement for the wrap lock's `--session-id`.
- **Never synthesize a value inside Claude's id namespace.** The `ds-session-` prefix exists to keep a generated key visibly outside it. This mirrors the rule `content/commands/ds-implement-ticket.md` already applies to `loop-state-<LOOP_KEY>.json`, which writes `session_id: null` on a harness with no id of its own rather than inventing a uuid in the wrong namespace.

**Pass it as a literal string and persist nothing.** No file records the key. Nothing needs it to survive a restart: a shard is a per-session file by construction, and `ds-learning-shard rollup` reads every shard under the repo's shard directory regardless of how many sessions produced them. A key file under the conductor's `.agentic/` would in any case be unreachable from a worktree-isolated Worker, for exactly the reason given above about `.agentic/context.md`.

**Every spawn, not only the roles that can capture.** Just four roles can call `ds-learning-shard append`, and that membership list is enumerated in `content/references/learnings-capture-instruction.md` and cross-checked against the agent files by `bin/tests/test_agent_capability_claim_consistency.py`, which exists because the list has desynchronized before. Scoping this obligation to those four would make this paragraph a further site restating the list; a blanket rule cannot desync from a list it never restates. The cost is one ignored line in the briefs of roles that will not use it.

**Where a conductor actually meets this rule.** This file is trigger-loaded, so a rule stated only here is not resident when a conductor composes a spawn prompt. The `SESSION_KEY` line therefore also appears in the two checklists a conductor fills at spawn time: `content/references/agent-team.md` §Spawning (the ``When spawning `engineer`, include:`` list) and `content/references/delegation-detail.md` §Worker Preamble and Execution Contract Template. Both carry the field and defer to this paragraph for the derivation rule, so neither restates the four-role list either. Change all three together.

**Memory update serialization:** When parallel Workers produce memory update requests, the main agent serializes these writes: it invokes `/ds-memory-update` for each request sequentially after all Workers have returned. Workers must not invoke `/ds-memory-update` directly from within a parallel session - concurrent writes to the project's `MEMORY.md` may conflict.

**When The Skeptic Protocol was not invoked** (e.g., the task was Low risk pure research or investigation with no artifact produced), the Worker states explicitly: "No Skeptic Protocol invoked — task was [description]. No artifact requiring review." This prevents ambiguity in a return without a review record.

---

## 12. Sync with Related Documents

This document is the canonical source for The Subagent Protocol. **When this document and any condensed form diverge, this document governs.**

**Document hierarchy:**
- **This document** - canonical specification for the outer delegation frame; governs all conflicts within that scope
- **`~/.claude/CLAUDE.md`** - carries only the Skill Loading table that triggers the `/dinostack` skill; it does not itself contain risk classification rules or a delegation decision table on a session where the skill symlink resolves. The canonical risk signal list and delegation decision table live in `content/sections/02-delegation.md` and `content/sections/04-risk-classification.md`, which are assembled into the `/dinostack` skill embed and load when that skill is invoked
- **`~/DinoStack/.claude/skills/dinostack/references/skeptic-protocol.md`** - canonical specification for the inner Skeptic loop

When this document changes:
1. If the change affects the risk signal list or delegation decision table, update `content/sections/02-delegation.md` and/or `content/sections/04-risk-classification.md` to match, then rebuild the adapters (`bash scripts/build-all.sh`) so the change reaches the skill embed. Procedural changes (worktree rules, check-in behavior, parallel spawning details) are picked up automatically via pointers.
2. Check `~/DinoStack/.claude/skills/dinostack/references/skeptic-protocol.md` for sections that may be affected by changes to orchestration rules (particularly Sections 2, 5, 9, and 10).

## 13. Conductor context budget

Long-running conductor sessions accumulate stale state that degrades reliability: phase decisions made 20 turns ago may contradict current findings, crash-recovery artifacts (context.md, loop-state.json) diverge from actual session progress, and cross-phase drift makes it harder for operators to audit what happened. The Subagent Protocol therefore defines session-budget rules for the main conductor session to keep session state reliable and operator oversight tractable.

### 13.1 Soft limit (recommended: 15–20 conductor turns)

When the conductor reaches the soft limit, it MUST:
1. Warn the user that the session is approaching its recommended context budget.
2. Recommend `/ds-wrap` to preserve state and restart with a fresh context window.
3. Summarize what has been accomplished and what remains.
4. Offer to continue ONLY if the user explicitly confirms.

The soft limit is a signal, not a stop. The user may choose to continue, but they do so with informed consent.

### 13.2 Hard limit (recommended: 25–30 conductor turns)

When the conductor reaches the hard limit, it MUST:
1. Refuse further implementation work, Skeptic rounds, or subagent spawns.
2. Invoke `/ds-wrap` automatically (or instruct the user to do so).
3. Preserve all state via `context.md` and `MEMORY.md` updates.
4. Explain that the hard limit exists to protect output quality and that a fresh session is required.

The hard limit is absolute. No exception, no override.

### 13.3 Rationale

AE's structural delegation (subagents, worktrees) offloads most implementation work from the conductor. The conductor's role is coordination, synthesis, and decision-making. These tasks require high-fidelity context. A conductor that has been running for 30+ turns is operating with degraded context, increasing the risk of:
- Missing critical details from earlier turns
- Re-introducing bugs that were already fixed
- Making inconsistent decisions
- Producing stale crash-recovery artifacts (context.md, loop-state.json) that no longer reflect actual session state

The `/ds-wrap` + restart flow already handles session handoff. The context budget simply makes the handoff proactive rather than reactive.

### 13.4 Exceptions

The context budget applies to **implementation work** and **multi-turn planning**. It does NOT apply to:
- Single-turn Q&A or information retrieval
- Brief sessions that resolve quickly (fewer than 5 gray areas)
- Diagnostic-only work (reading logs, explaining errors)
