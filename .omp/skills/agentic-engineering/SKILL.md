---
name: agentic-engineering
description: >
  Apply when the user mentions any software development work: implementing features, fixing bugs,
  reviewing or refactoring code, debugging, testing, deploying, working with agents or subagents,
  making architecture decisions, setting up projects, managing dependencies, writing scripts, or
  any task that involves reading, writing, or reasoning about code and systems.
---

## How to use this skill in Pi

**Auto-trigger:** The skill loads automatically when you describe software development work.

**Explicit load:** Ask the agent to "use the agentic-engineering skill" or reference the methodology directly.

**IMPORTANT:** Pi does NOT support custom markdown slash commands like `/init-project` or `/wrap`.
Those are Claude Code conventions. In Pi, always use natural language ("run init-project", "do a wrap").

---

The Agentic Engineering system defines how to plan, delegate, review, and ship software using a
structured multi-agent workflow. It covers risk classification, adversarial review, task
decomposition, and quality gates so that changes are correct, safe, and reviewable. Read the rules
files on every session and the reference docs on the triggers described in agent-methodology.md.

**Conductor default: act, don't ask.** The conductor's job is to complete the goal, not to approve every step. Stop and ask only for destructive/irreversible actions, missing information only the user has, materially ambiguous acceptance criteria, or scope-completion decisions. Repeated stops within one task are a planning signal, not a virtue. See `Proactive autonomy` in `rules/agent-methodology.md` for the full rule, anti-patterns, and stop-frequency thresholds.

## Pi-specific subagent mapping

Pi provides built-in subagent types. Map agentic-engineering roles to them as follows:

- **`task`** (default) - Use for general implementation work (maps to `engineer`, `debugger`, `qa-engineer`, `perf-analyst`). This is the standard Worker for Elevated-risk tasks.
- **`explore`** - Use for fast read-only codebase exploration (maps to `investigator`, `dependency-auditor`, `adr-drift-detector`).
- **`plan`** - Use for implementation planning and architecture design (maps to `architect`, `orchestration-planner`, `adr-generator`).
- **`designer`** - Use for UI/UX design work (maps to designer roles).
- **`reviewer`** - Use for adversarial code review (maps to `skeptic`, `security-auditor`).
- **`quick_task`** - Use for lightweight, low-risk tasks that don't need full Worker + Skeptic review.

Pi also provides native commands that map to methodology workflows:
- `/plan` - Maps to `orchestration-planner` or `architect` workflows
- `/review` - Maps to `skeptic` adversarial review

When spawning a subagent, read the corresponding **detailed agent file** from `agents/<name>.md` and include its full instructions in the spawn prompt. The agent files contain role-specific constraints, reporting formats, and workflow rules that `references/agent-team.md` does not cover in detail.

| Agentic role | File to read | Pi subagent type |
|---|---|---|
| `engineer` | `agents/engineer.md` | `task` |
| `debugger` | `agents/debugger.md` | `task` |
| `qa-engineer` | `agents/qa-engineer.md` | `task` |
| `perf-analyst` | `agents/perf-analyst.md` | `task` |
| `investigator` | `agents/investigator.md` | `explore` |
| `dependency-auditor` | `agents/dependency-auditor.md` | `explore` |
| `adr-drift-detector` | `agents/adr-drift-detector.md` | `explore` |
| `architect` | `agents/architect.md` | `plan` |
| `orchestration-planner` | `agents/orchestration-planner.md` | `plan` |
| `adr-generator` | `agents/adr-generator.md` | `plan` |
| `security-auditor` | `agents/security-auditor.md` | `reviewer` or `task` |
| `release-orchestrator` | `agents/release-orchestrator.md` | `task` |

For the **Skeptic** role, spawn a `reviewer` subagent or use Pi's native `/review` command, prepending the skeptic instructions from `agents/skeptic.md` (or `references/skeptic-protocol.md` for the protocol overview) and restricting its task to read-only review.

## Risk classification reminder

Perform a brief risk assessment before starting any task. Any single Elevated signal triggers Worker + fresh independent Skeptic review. Low risk permits direct action with a brief inline self-check. When in doubt, classify as Elevated.

**Elevated signals (any single one triggers adversarial review):** any code edit to file contents; security / auth / crypto / payments / secrets; irreversible operations; architecture decisions that constrain future choices; modifies protocol or infrastructure files; production or shared state; multi-file changes; new file creation; external APIs or services; unfamiliar codebase area; logic with emergent cross-component interactions; user signals high stakes; configuration changes; research that produces a document, recommendation, or plan to be acted on; changes to shared utilities used across many call sites; anything where a mistake costs time or data.

**Trivial signals (ALL must hold - any single disqualifier pushes to Elevated):** touches exactly one file; no change to control flow, data flow, state shape, API surface, or types; no change to shared design tokens, theme files, config, env, or CI; no change to anything a downstream consumer imports; reversible with a one-line revert; no security, auth, permissions, billing, or PII surface involved.

**Conductor rule for Trivial:** If no subagents are currently running, the conductor edits directly. If any subagent is currently running, spawn a single `task` subagent in foreground with no Skeptic.

## Rules (read these files)

- **rules/agent-methodology.md** - delegation model, risk classification, task decomposition, and
  worktree lifecycle; the core rules for when to act directly vs. spawn Workers and Skeptics.

- **rules/code-standards.md** - documentation lookups via Context7, tool discipline (read/write/edit/shell over Bash for reads), code quality gates, package management conventions, and browser verification.

- **rules/conventions.md** - writing style, project structure, session context and memory handling,
  and git workflow including protected branches and worktree-per-feature conventions.

## Reference Docs (read on trigger - see Protocol Details in agent-methodology.md)

- **references/skeptic-protocol.md** - Skeptic loop orchestration, findings classification
  (Critical/Major/Minor), sign-off format, adversarial briefs, and the Elevated + Cleanup path.

- **references/subagent-protocol.md** - parallel spawning rules, worktree isolation, check-in
  behavior, phase breadcrumbs, and task decomposition rules for multi-subagent plans.

- **references/agent-team.md** - named agent roles (engineer, architect, investigator, debugger,
  security-auditor, orchestration-planner), composed flows, decision rules, and spawn requirements.

- **references/design-goals.md** - design principles and goals of the Agentic Engineering system;
  read when evaluating whether a proposed change aligns with the system's intent.

- **references/regression-test-obligation.md** - per-finding regression-test obligation: every
  Skeptic finding fixed during a task must come with a regression test that would have caught it;
  read when fixing a Skeptic finding to confirm what counts as a valid regression test.

## Rules (read on trigger)

- **rules/module-manifest.md** - required manifest header format for non-trivial source files;
  read when creating or substantially modifying a file that exports a public symbol, exceeds ~50
  LOC, or implements a side-effecting operation.

## Commands

Command templates live in `commands/`. Pi does not support custom markdown commands, so load a specific command by asking the agent to run it (e.g. "run cleanup-worktrees"), or read the file directly from `commands/<name>.md` and follow its instructions.

Available commands:

- **cleanup-worktrees** - Clean up stale git worktrees and local branches.
- **configure-team** - Set up and verify a cross-harness agent team for role-to-harness dispatch.
- **implement-ticket** - End-to-end ticket implementation with architect, engineer, and skeptic.
- **init-project** - Initialize agentic-engineering in a new repository.
- **memory-update** - Update session context and memory files.
- **prune-harness** - Prune stale eval harness entries.
- **representation-audit** - Audit agent representation files for drift.
- **skeptic** - Run a focused Skeptic review on a specific change.
- **update-agentic-engineering** - Update this repo's content and rebuild adapters.
- **wrap** - End-of-session wrap-up: commit, context save, and loop state.
