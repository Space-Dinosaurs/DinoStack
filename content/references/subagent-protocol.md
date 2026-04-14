# The Subagent Protocol — Orchestration Methodology

## 1. Overview

The Subagent Protocol is the outer orchestration frame for multi-agent sessions. It governs when and how the main session agent delegates work to subagents, with one non-negotiable objective: **the main session agent must always remain free to respond to the user**.

The core principle: **the main agent is a conductor, never a player.** Its job is to decompose work, spawn subagents, stay available, and synthesize results. It does not implement, investigate, or run multi-step operations inline.

The Skeptic Protocol is a specific review pattern orchestrated by the main agent after a Worker returns. The main agent spawns the Worker, reads the result, then spawns a fresh Skeptic to review it. The Subagent Protocol is the outer frame that determines whether and how to delegate; The Skeptic Protocol determines how the main agent reviews Worker output before accepting it.

The principles are system-agnostic and apply to any orchestration agent capable of spawning subagents. Specific tool names (TaskOutput, etc.) used in examples are Claude Code implementation details.

---

## 2. The Seven Rules

### Rule 1 — Always background delegated tasks (most critical rule)

**All delegated tasks run in background by default. Foreground is permitted only for the direct-action cases listed in Rule 7.**

A foreground subagent blocks the main agent entirely. The main agent cannot respond to the user, cannot process other completions, and cannot provide progress updates while a foreground task is running. This is the most severe violation of the protocol — it converts the conductor into a blocked player.

Background tasks free the main agent immediately. The main agent gives the user an upfront status update, stays available for follow-up questions, and checks task output via TaskOutput when the task completes or when the result is needed.

### Rule 2 — Parallel by default

**Independent tasks spawn simultaneously in a single message, not sequentially.**

When decomposing a request into multiple subtasks, if tasks A, B, and C are independent — meaning B does not depend on A's output and C does not depend on B's output — spawn all three in the same message as separate Task invocations. Sequential spawning of independent tasks wastes elapsed time proportional to the number of tasks.

The main agent should be actively looking for parallelism: "Can I start B before A finishes? Can C run while A and B are both running?" If the answer is yes, they run in parallel.

### Rule 3 — Spawn threshold

**Elevated risk → spawn Worker + fresh independent Skeptic. Low risk → direct action. Trivial risk → conductor edits directly if no subagents are running; spawn a single `engineer` Worker in foreground (no Skeptic, no brief file) if any subagent is running.** The Skeptic Protocol defines two Elevated tiers (Elevated and Elevated + Cleanup); the main agent selects the appropriate path per The Skeptic Protocol Sections 0 and 12.

The delegation decision is driven by risk, not by counting tool calls. Assess risk first (see The Skeptic Protocol Section 0). If any Elevated signal is present, delegate to a Worker and apply adversarial review. If all signals are Low, direct action is appropriate. Trivial requires ALL qualifying signals to hold simultaneously - any single disqualifier pushes the task to Elevated.

"Looks simple" is not a Low signal. The uncertainty rule applies: when in doubt, classify as Elevated and spawn a Worker. When in doubt between Trivial and Elevated, choose Elevated.

### Rule 4 — Agent type discipline

**Choose the right agent type for the task. The wrong type silently degrades the protocol.**

| Task type | Agent type to spawn |
|---|---|
| Code implementation, file changes, synthesis | `general-purpose` Worker |
| Pure shell operations, no subagent spawning needed | `bash` agent |
| Codebase exploration, reading many files | `general-purpose` Worker |
| Web research, doc reading, analysis | `general-purpose` Worker |
| Multi-step investigation with possible follow-up | `general-purpose` Worker |

**Critical constraint:** Bash agents cannot spawn subagents — they do not have access to the Task tool. For implementation tasks that will go through Skeptic review, always use a general-purpose Worker. Bash agents lack the file and code tools needed to do substantive implementation work. Using a Bash agent for implementation tasks silently degrades output quality rather than failing explicitly.

**When in doubt, use a general-purpose Worker.** The cost of over-provisioning agent capability is negligible. The cost of under-provisioning is silent protocol degradation.

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

Full specification of The Skeptic Protocol: `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md`.

### Rule 6 — Check in, don't disappear

**When background tasks are running, the main agent stays visible and responsive.**

When spawning background tasks, the main agent immediately tells the user:
- What is being worked on
- Approximately how long it will take
- What the main agent can answer right now without waiting

When a background task completes, the main agent proactively reads its output via TaskOutput and presents a clear synthesis to the user. The main agent does not wait for the user to ask "is it done yet?" — it monitors and reports.

If the user asks a question while tasks are running, the main agent answers directly from context. It does not defer with "waiting for the subagent to finish." Background work and foreground conversation are independent.

**Phase breadcrumb convention** — At each natural orchestration boundary, include a `[phase: label]` marker in the status update to the user. These labels are emitted inline in conversation (not written to files), so they remain in the transcript on any termination - normal or abnormal. On normal session end they are also captured in context.md, which aids handoff. The transcript is the primary crash-recovery source; context.md is a bonus. This makes orchestration state crash-recoverable without any extra infrastructure.

Emit a phase label at: after spawning any agent, after any agent returns, after escalation, at task completion.

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
| `profiling` | Perf analyst is measuring latency, memory, or throughput |
| `releasing` | Release orchestrator is executing the release sequence |
| `dep-auditing` | Dependency auditor is scanning lockfiles and running vulnerability tools |
| `complete` | All work done, synthesizing results |

Example status update: "Skeptic spawned for round 1 review. [phase: skeptic-review (round 1)]"

### Rule 7 — Direct actions permitted without subagent

**Some actions are instant and do not block. These are done directly by the main agent.**

- Reading a single specific file when the path is already known
- Answering a question directly from context already in memory
- `git status`, `git log`, `git diff` — read-only, instant
- Taking a screenshot or browser snapshot
- Synthesizing and explaining results that subagents have already returned
- A one or two-line edit to a single file, where the correct output is immediately apparent without reading any other file, **and no Elevated risk signals are present**

These actions do not block meaningfully and do not benefit from delegation. Delegating them adds latency and context overhead with no quality gain.

When uncertain whether an edit meets the "immediately apparent without reading any other file" criterion — or when any Elevated signal is present — delegate.

---

## 3. Decision Table

**Two-question structure:** First, determine whether to delegate (consult the table below). Second, determine whether to background (apply the background rule). These are independent questions evaluated in sequence.

**Background rule (evaluated after the delegation decision, mandatory for all delegated work):** All delegated tasks run with `run_in_background: true`. Foreground is permitted only for direct-action cases (Rule 7). This applies to every row below that results in "Spawn subagent." Background is not a row at the bottom of the table — it is a mandatory modifier on all delegated work.

**Risk assessment drives delegation.** The rows below map risk signals to the delegation decision. Any single Elevated signal in a task triggers Worker + Skeptic review.

**Authoritative signal list:** The Elevated signal list in this table is derived from and subordinate to The Skeptic Protocol Section 0, which is the authoritative source for risk classification. Consult `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` Section 0 when the two differ.

| Signal / condition | Main agent direct? | Spawn Worker + Skeptic? |
|---|---|---|
| Read a single known file | Yes | No |
| `git status` / `git log` / `git diff` (read-only) | Yes | No |
| Answer from memory/context | Yes | No |
| Take a screenshot or snapshot | Yes | No |
| Synthesize already-returned subagent results | Yes | No |
| 1–2 line edit, single file, correct output apparent, no Elevated signals | Yes | No |
| Trivial risk (ALL qualifying signals hold) - no subagents currently running | Yes (direct edit, no Skeptic) | No |
| Trivial risk (ALL qualifying signals hold) - one or more subagents currently running | No (spawn solo `engineer` Worker in foreground; no Skeptic) | No |
| Security / auth / crypto / payments / secrets | No | **Yes** |
| Irreversible operation (delete, migration, schema change, force push) | No | **Yes** |
| Architecture decision that constrains future choices | No | **Yes** |
| Modifies protocol or infrastructure files | No | **Yes** |
| Production or shared state | No | **Yes** |
| Multi-file change (any size) | No | **Yes** |
| New file creation | No | **Yes** |
| Touches external APIs or services | No | **Yes** |
| Unfamiliar codebase area | No | **Yes** |
| Logic with emergent/non-obvious cross-component interactions | No | **Yes** |
| Changes to shared utilities, helpers, or abstractions used across many call sites (single-file but high blast radius) | No | **Yes** |
| User signals high stakes ("production", "critical", "don't mess this up") | No | **Yes** |
| Any Bash with side effects (writes, deletes, network, DB) | No | **Yes** |
| Research that produces a document, recommendation, or plan to be acted on | No | **Yes** |
| Document synthesis, architecture, or planning | No | **Yes** |
| Configuration changes | No | **Yes** |
| Anything where a mistake costs time or data | No | **Yes** |

**Default rule:** when in doubt, classify as Elevated and spawn a Worker. Direct action is the narrow exception.

**Footnote — new file creation:** The 1–2 line direct-action exception applies exclusively to modifications of existing files. New file creation always requires a Worker regardless of line count.

---

## 4. Agent Type Selection Guide

| Condition | Agent type |
|---|---|
| Task involves code or file changes | `general-purpose` Worker (Skeptic Protocol applies) |
| Task may require spawning further subagents | `general-purpose` Worker |
| Task involves synthesis, planning, research | `general-purpose` Worker |
| Task is pure shell with no side-effect ambiguity and no subagent spawning possible | `bash` agent |
| Multi-file codebase exploration | `general-purpose` Worker |

**Never assign a task to a Bash agent if the task involves code changes, file synthesis, or substantive implementation work.** Bash agents lack the file and code tools needed for this work. For any implementation task that will go through Skeptic review, use a general-purpose Worker.

---

## 5. Background vs. Foreground Decision Rule

**Default: background.**

**Absolute rule:** All delegated tasks run in background by default. Foreground is permitted only for the direct-action cases listed in Rule 7. If you need the result of a background task, spawn it in background, give the user a status update, and wait for the TaskOutput notification rather than blocking inline.

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

The principle: overusing Skeptics dilutes their value. Narrow Workers improve implementation correctness. Broad Skeptic scope (where warranted) catches interaction bugs that per-unit review would miss.

**Mid-task re-decomposition:** If a Worker discovers its scope is still too broad during execution, it returns partial output with a decomposition request. The conductor then decomposes further and re-spawns focused Workers. See Skeptic Protocol Section 5.

At no point in this sequence does the main agent become a player. All steps are conductor actions.

---

## 7. Shared Repo Isolation

**Parallel agents writing to the same git repository must use worktree isolation.**

### The rule

When spawning two or more agents that will write to the same git repository simultaneously, always pass `isolation: "worktree"` in the Task tool call.

### Why

Git's working tree is shared state. When two agents run concurrently in the same directory and either agent runs `git checkout` or `git checkout -b`, it moves the working tree to a different branch — overwriting whatever the other agent has staged or modified. The second agent then reads, modifies, or commits files from the wrong branch. This is not a recoverable situation mid-run; the working tree state is silently corrupted.

Worktree isolation gives each agent its own copy of the repo at a separate filesystem path on its own branch. The agents do not share a working directory, so concurrent checkouts cannot interfere.

### How

Pass `isolation: "worktree"` in the Task tool call when spawning parallel agents:

```
Task(
  prompt="...",
  isolation="worktree"
)
```

The Task tool creates a temporary git worktree for the agent to work in — an isolated copy of the repo at a separate path on its own branch. When the agent finishes, the worktree is cleaned up.

### Nested repo caveat

`isolation: "worktree"` requires Claude Code to be running inside the correct git repo root. If the project directory is nested inside a parent git repo, the Task tool may walk up the directory tree and resolve to the parent repo instead — causing worktree creation to fail even though the project directory has its own `.git`.

**Symptom:** `isolation: "worktree"` fails with "Cannot create agent worktree: not in a git repository and no WorktreeCreate hooks are configured" even though Claude Code is launched from within the project directory.

**Diagnosis:** Run `git rev-parse --show-toplevel` from the project directory and from the parent. If both return different roots, the parent repo is interfering.

**Fix:** Add the project directory to the parent repo's `.gitignore`. This makes git (and the Task tool) treat the project as an independent repo rather than a subdirectory of the parent.

```bash
# Example: authentic8/ nested inside ~/
echo "Documents/Development/authentic8/" >> ~/.gitignore
```

### When NOT needed

- A single agent working alone — no parallel agent to collide with
- Agents working in fully separate repositories — no shared working tree
- Read-only agents that do not run `git checkout`, stage files, or commit

### Violation pattern

Two track agents spawned in parallel in the same directory. Track A checks out its feature branch. Track B checks out its feature branch. Track A's working tree is now on Track B's branch. Track A stages and commits files that were modified on the wrong branch. Both agents' work is corrupted.

---

## 8. Anti-Patterns

**Foreground blocking** — The most critical anti-pattern. Spawning a subagent without `run_in_background: true` for any delegated task. Blocks the main agent entirely for the duration. Foreground is reserved only for direct-action cases (Rule 7). There is no justification for foreground on any delegated work.

**Sequential when parallel is possible** — Spawning subagent B after waiting for subagent A when B does not depend on A's output. Multiplies elapsed time unnecessarily.

**Bash agents for implementation tasks** — Assigning a Bash agent to any task involving code, file changes, or synthesis. Bash agents lack file and code tools needed for substantive implementation, and cannot spawn subagents for follow-up. The failure is silent degradation, not an explicit error.

**Main agent doing implementation work** — The main agent writing code, editing multiple files, or running multi-step investigations inline rather than delegating. Violates the conductor principle and bypasses The Skeptic Protocol review gate.

**"Looks simple" rationalization** — Classifying work as Low risk to avoid delegation on genuinely risky work. Simple-looking tasks are where The Skeptic Protocol is most often skipped and where unreviewed errors accumulate. "Looks simple" is not a Low signal — apply the uncertainty rule and classify as Elevated when any doubt exists.

**Deferring synthesis** — Waiting for all background tasks to complete before responding to the user at all. The main agent should give an upfront status update immediately after spawning, and answer follow-up questions from context while tasks run.

**Softening adversarial briefs** — When passing a domain adversarial brief to a Worker (for The Skeptic Protocol), the main agent must pass it verbatim. Summarizing or softening the brief degrades adversarial independence.

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

## 10. Output Expectations

When a Worker returns to the main agent under this protocol, the main agent expects:

- **Final output** — the complete implementation artifact, or file paths to it if the output is large
- **Round summary** — what changes were made and why (if Skeptic findings were routed back)
- **Memory update requests** — any architectural decisions or qualifying context the Worker believes should be recorded (the main agent serializes these writes, not the Worker directly)

**Sign-off is the main agent's responsibility.** The main agent spawns Skeptics and accumulates the exchange log. A Worker does not return a sign-off statement — the Skeptic provides sign-off to the main agent directly.

**Re-route limit:** After the same finding is contested for 2 or more re-routes without resolution, the main agent stops and escalates that finding to the human with: the exchange log, the contested finding, and the Worker and Skeptic positions on it. Do not attempt further re-routes without human direction.

**Side effects:** Workers must not apply irreversible changes (file overwrites, database mutations, published state) without informing the main agent that sign-off is required before those changes are safe. Workers that must stage irreversible changes as part of their implementation must include a revert procedure in their return output.

**Spawning Workers:** The main agent must include the project context file content (`~/.claude/projects/[hash]/context.md`) in each Worker's spawn prompt. Workers must not be expected to self-direct context reads — they may not have reliable access to the path or the protocol. The main agent is responsible for providing session context at spawn time.

**Memory update serialization:** When parallel Workers produce memory update requests, the main agent serializes these writes: it invokes `/memory-update` for each request sequentially after all Workers have returned. Workers must not invoke `/memory-update` directly from within a parallel session — concurrent writes to `.claude/rules/decisions.md` may conflict.

**When The Skeptic Protocol was not invoked** (e.g., the task was Low risk pure research or investigation with no artifact produced), the Worker states explicitly: "No Skeptic Protocol invoked — task was [description]. No artifact requiring review." This prevents ambiguity in a return without a review record.

---

## 11. Sync with Related Documents

This document is the canonical source for The Subagent Protocol. **When this document and any condensed form diverge, this document governs.**

**Document hierarchy:**
- **This document** - canonical specification; governs all conflicts
- **`~/.claude/CLAUDE.md`** - inline risk classification and delegation decision table; procedural details read from this document via trigger-condition pointers
- **`~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md`** - canonical specification for the inner Skeptic loop

When this document changes:
1. If the change affects the risk signal list or delegation decision table, update `~/.claude/CLAUDE.md` to match. Procedural changes (worktree rules, check-in behavior, parallel spawning details) are picked up automatically via pointers.
2. Check `~/agentic-engineering/.claude/skills/agentic-engineering/references/skeptic-protocol.md` for sections that may be affected by changes to orchestration rules (particularly Sections 2, 5, 9, and 10).
