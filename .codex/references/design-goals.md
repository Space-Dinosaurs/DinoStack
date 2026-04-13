# Design Goals — claude-protocols

This document captures the design intent of the claude-protocols system. It is written for evaluators and auditors who need to understand **why** the system exists before examining how it works. Implementation details live in the canonical spec files. This document governs what those specs are trying to achieve.

---

## Goal 1 — Main agent stays maximally responsive

**The main session agent is a conductor, not a player.** Its value is in decomposing work correctly, passing precise context to Workers, and synthesizing results when they return. It must remain free to respond to the user at any point — including while background work is running. Any time the main agent does substantial work synchronously, the user waits. Any time the main agent handles multi-step work inline rather than delegating, it bypasses review and blocks the conversation.

**What this means in practice:**

- All delegated work runs in the background by default. A foreground subagent blocks the main agent entirely — the user cannot get a response, progress updates, or answers to follow-up questions while it runs.
- The spawn threshold is intentionally low. Anything requiring more than 2–3 tool calls gets delegated. "Looks simple" is not a reason to handle something inline.
- The main agent never implements code, investigates multi-file codebases, or runs multi-step operations inline — these always go to Workers.
- When multiple independent tasks exist, they are spawned in parallel. Sequential spawning of independent tasks multiplies elapsed time without benefit.
- The main agent stays available and gives the user a status update immediately after spawning background tasks. Background work and foreground conversation are independent.

**An evaluator should ask:** Does the main agent ever block, wait, or do substantial work inline? Is the spawn threshold being respected? Are independent tasks actually running in parallel?

The Subagent Protocol (`agent-methodology/subagent-protocol.md`) operationalizes this goal with specific rules, a decision table, and an anti-patterns section.

---

## Goal 2 — Adversarial accuracy

**LLMs are systematically overconfident about their own outputs.** A model that generates an implementation is anchored to that implementation. It will apply lower scrutiny when reviewing its own work than a fresh context would — not because it is dishonest, but because the reasoning that produced the output is still active in context. Self-review is structurally limited.

The Skeptic pattern counters this by introducing a genuinely independent reviewer. After a Worker implements, the main agent spawns a fresh Skeptic subagent - one with no memory of the implementation process, no access to the Worker's justifications, and no anchoring to the Worker's choices. That Skeptic applies an adversarial brief and returns classified findings. The Worker must address Critical and Major findings before returning. A new fresh Skeptic is spawned for each verification round, ensuring independence is never degraded by accumulated context.

**What this means in practice:**

- The Skeptic must always be a fresh invocation — never a continuation of a prior Skeptic round. A Skeptic that has heard the Worker's justifications is no longer independent.
- The adversarial brief must be specific enough that a bad implementation would actually fail it. Generic briefs produce generic findings and provide false assurance.
- The main agent must pass the brief verbatim. Softening or summarizing the brief degrades adversarial independence just as continuing a prior Skeptic does.
- The resolved issues preflight list prevents a fresh Skeptic from re-raising already-addressed findings as new Critical items — but it does not prevent the Skeptic from contesting a resolution it finds insufficient.
- The sign-off format is required, not optional. It requires the Skeptic to explicitly state what it reviewed and attest to an active search for problems. A sign-off without these elements is not a valid sign-off.
- The system uses two risk levels: Low (direct action with a brief inline self-check) and Elevated (Worker + fresh independent Skeptic, orchestrated by the main agent). There is no self-review path for Elevated work - adversarial independence requires a clean context that self-review cannot provide.

**An evaluator should ask:** Is the Skeptic actually fresh each round? Is the adversarial brief being passed verbatim? Is the brief specific enough to catch real problems? Are Critical and Major findings being genuinely resolved or just rationalized away?

The Skeptic Protocol (`agent-methodology/skeptic-protocol.md`) operationalizes this goal with the full loop definition, escalation rules, sign-off format, and adversarial brief templates.

---

## Goal 3 — Cross-session continuity without ceremony

**The system should maintain enough context for a new session to pick up where the last one left off — without requiring the user to manually maintain notes, repeat context, or run commands.**

Context is managed in three complementary tiers, each with different characteristics:

1. **Ephemeral turn-level context** (`~/.claude/projects/[hash]/context.md`) — written automatically by the Stop hook after every agent turn. Contains: recent user messages, files touched, tools used. No LLM call; pure text extraction from the session payload. Always current because it is overwritten on every turn — never stale. Workers read this at task start to orient without needing the full session history in their prompt.

2. **Decision log** (`.claude/rules/decisions.md`) — persistent, version-controlled, auto-loaded by Claude Code at startup. Contains architectural choices, technology decisions, scope resolutions, and deliberate tradeoffs. Updated via `/memory-update`, which spawns a background Worker with its own Skeptic loop to ensure accuracy before writing. Decisions are curated: a new entry that contradicts a prior one updates the prior one rather than appending a conflicting record.

3. **Architecture documentation** (`AGENTS.md`) - lean, auto-loaded, kept under ~40 lines for project roots. Architecture only - not decisions, not session state. The global `~/.claude/CLAUDE.md` is exempt from the line limit.

**What this means in practice:**

- The Stop hook runs silently after every turn. No user action is required to maintain turn-level context.
- The main agent includes the project context file content in each Worker's spawn prompt. Workers must not be expected to self-direct reads — they may not have reliable path knowledge.
- `/memory-update` is the only write path to `decisions.md`. Direct edits bypass the Skeptic accuracy loop.
- `AGENTS.md` does not accumulate decisions. The separation between architecture (`AGENTS.md`) and decisions (`decisions.md`) is a deliberate design constraint, not a style preference.
- `/wrap` is available for richer on-demand context enrichment — e.g., before handing off complex in-progress work. It is not required for normal operation; the Stop hook provides sufficient baseline continuity.

**An evaluator should ask:** Is the Stop hook actually firing and writing current context? Is `decisions.md` accurate and up-to-date — not stale or conflicted? Is `AGENTS.md` staying lean, or accumulating decisions it should not hold? Are Workers receiving context at spawn time?

The "Decisions & Context" section of `~/.claude/CLAUDE.md` operationalizes this goal. That file is symlinked from the repo's `.claude/CLAUDE.md` by `install.sh`, so the repo is the canonical source. The Stop hook implementation lives in `claude-hooks/stop-context.js`.

---

## Goal 4 - Context window efficiency

**Always-loaded instruction files must be as small as possible while preserving correct autonomous behavior.** The global `~/.claude/CLAUDE.md` is loaded into every conversation. Every line consumes context on every task, whether relevant or not. The system separates content into two categories using a trigger-pointer pattern:

**Inline content** - present in the always-loaded file because the agent needs it before making any decision. This includes: risk signal lists, delegation decision tables, core behavioral rules (conductor/player, background-by-default), and cross-cutting conventions (writing style, tool usage). These pass the chicken-and-egg test: removing them would cause the agent to miss a risk signal or behavioral rule before it knows to read anything else.

**Deferred content** - needed only after a trigger condition is met. This includes: protocol procedural details (Skeptic loop steps, sign-off format, adversarial briefs), escalation mechanics, worktree rules, and detailed rationale. Deferred content lives in canonical spec files and command files; the always-loaded file contains a pointer with a trigger condition, file path, and one-line summary.

**The chicken-and-egg constraint:** Risk classification content (signal lists, decision tables) must stay inline because they are evaluated before any other decision. If the agent had to read a file to learn the risk signals, it would either read the file on every task (no savings) or miss signals on tasks where it skipped the read (dangerous).

**Criteria for inline vs. deferred:**
- Stays inline: evaluated on every task; foundational behavioral rule; cross-cutting convention; deferring would require reading a file before knowing whether to read it
- Gets deferred: procedural detail for an already-triggered protocol; template or reference material; needed only in specific situations; trigger condition is unambiguous

**An evaluator should ask:** Would removing this line from the always-loaded file cause the agent to make a wrong classification or miss a behavioral rule on any task? If yes, it stays inline. If no, it should be a pointer.

The trigger-pointer pattern in `~/.claude/CLAUDE.md` operationalizes this goal. Risk signals and the delegation decision table are inline; protocol procedural details are pointers to canonical specs read on trigger.

---

## Non-Goals

The system deliberately does not attempt to:

- **Provide the AI with persistent memory of personal facts or preferences.** The context and decision systems capture project-affecting information only. Personal preferences, conversational history, and user identity information are out of scope. A new session has no recollection of who the user is or what they talked about last week.

- **Replace proper documentation.** `decisions.md` is a decision log, not a design document, API reference, or user guide. The protocols do not generate or maintain project documentation — that remains the responsibility of the project's authors.

- **Automate irreversible operations at the git or infrastructure boundary.** The system writes files and context automatically, but it does not commit to git, push code, merge PRs, or execute deployments on its own. Any action at a git or infrastructure boundary requires explicit human confirmation. The protocol's job is to produce correct, reviewed work product — not to push it anywhere without human direction.

- **Guarantee correctness.** The Skeptic Protocol significantly reduces error rates by introducing adversarial independent review, but it does not eliminate errors. A Skeptic that shares the same training biases as the Worker may miss the same classes of errors. The protocol provides defense in depth, not a proof of correctness.

- **Eliminate the need for human judgment.** Escalation paths exist precisely because some decisions are genuinely ambiguous. When the same finding is contested for 2 or more re-routes without resolution, the protocol escalates to the human rather than forcing a resolution. The system is designed to reduce the burden on human reviewers, not replace them.

- **Manage infrastructure or secrets.** The install script creates symlinks and registers a hook. It does not provision cloud resources, manage environment variables, handle credentials, or configure external services.
