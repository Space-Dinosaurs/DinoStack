---
name: agentic-engineering
description: >
  Apply when the user mentions any software development work: implementing features, fixing bugs,
  reviewing or refactoring code, debugging, testing, deploying, working with agents or subagents,
  making architecture decisions, setting up projects, managing dependencies, writing scripts, or
  any task that involves reading, writing, or reasoning about code and systems.
---

## How to use this skill in Kimi Code CLI

**Auto-trigger:** The skill loads automatically when you describe software development work.

**Explicit load:** Type `/skill:agentic-engineering` followed by your request.
Example: `/skill:agentic-engineering init-project`

**IMPORTANT:** Kimi does NOT support custom slash commands like `/init-project` or `/wrap`.
Those are Claude Code conventions. In Kimi, always use `/skill:agentic-engineering <command>`
or natural language ("run init-project", "do a wrap").

---

The Agentic Engineering system defines how to plan, delegate, review, and ship software using a
structured multi-agent workflow. It covers risk classification, adversarial review, task
decomposition, and quality gates so that changes are correct, safe, and reviewable. Read the rules
files on every session and the reference docs on the triggers described in agent-methodology.md.

**Conductor default: act, don't ask.** The conductor's job is to complete the goal, not to approve every step. Stop and ask only for destructive/irreversible actions, missing information only the user has, materially ambiguous acceptance criteria, or scope-completion decisions. Repeated stops within one task are a planning signal, not a virtue. See `Proactive autonomy` in `rules/agent-methodology.md` for the full rule, anti-patterns, and stop-frequency thresholds.

## Kimi-specific subagent mapping

Kimi Code CLI provides three built-in subagent types. Map agentic-engineering roles to them as follows:

- **`coder`** (default) - Use for general implementation work (maps to `engineer`, `debugger`, `qa-engineer`, `perf-analyst`). This is the standard Worker for Elevated-risk tasks.
- **`explore`** - Use for fast read-only codebase exploration (maps to `investigator`, `dependency-auditor`, `adr-drift-detector`).
- **`plan`** - Use for implementation planning and architecture design (maps to `architect`, `orchestration-planner`, `adr-generator`).

When spawning a subagent, include the full agent role description from `references/agent-team.md` in the spawn prompt so the subagent knows its responsibilities, constraints, and reporting format. The named agent definitions in `references/agent-team.md` are reference material - Kimi uses the built-in subagent types above with detailed role prompts.

For the **Skeptic** role, spawn a `coder` subagent but prepend the skeptic instructions from `references/skeptic-protocol.md` and restrict its task to read-only review (do not grant write access).

## Rules (read these files)

- **rules/agent-methodology.md** - delegation model, risk classification, task decomposition, and
  worktree lifecycle; the core rules for when to act directly vs. spawn Workers and Skeptics.

- **rules/code-standards.md** - documentation lookups via Context7, tool discipline (Read/Glob/Grep
  over Bash for reads), code quality gates, package management conventions, and browser verification
  with agent-browser.

- **rules/conventions.md** - writing style, project structure, session context and memory handling,
  and git workflow including protected branches and worktree-per-feature conventions.

## Reference Docs (read on trigger - see Protocol Details in agent-methodology.md)

- **references/skeptic-protocol.md** - Skeptic loop orchestration, findings classification
  (Critical/Major/Minor), sign-off format, adversarial briefs, and the Elevated + Cleanup path.

- **references/subagent-protocol.md** - parallel spawning rules, worktree isolation, check-in
  behavior, phase breadcrumbs, and task decomposition rules for multi-Worker plans.

- **references/agent-team.md** - named agent roles (engineer, architect, investigator, debugger,
  security-auditor, orchestration-planner), composed flows, decision rules, and spawn requirements.

- **references/design-goals.md** - design principles and goals of the Agentic Engineering system;
  read when evaluating whether a proposed change aligns with the system's intent.

- **references/findings-flywheel.md** - per-finding regression test obligation, pattern promotion
  criteria and entry format for findings files, and who reads the file; read when promoting
  a finding after Skeptic sign-off or when the Skeptic checks for repeated anti-patterns.

## Rules (read on trigger)

- **rules/module-manifest.md** - required manifest header format for non-trivial source files;
  read when creating or substantially modifying a file that exports a public symbol, exceeds ~50
  LOC, or implements a side-effecting operation.

## Commands

Command templates live in `commands/`. Load a specific command by asking the agent to run it (e.g. "run cleanup-worktrees"), or invoke it explicitly via `/skill:agentic-engineering` followed by the command name. The agent will read the corresponding file from `commands/<name>.md` and follow its instructions.

Available commands:

- **cleanup-worktrees** - Clean up stale git worktrees and local branches.
- **implement-ticket** - End-to-end ticket implementation with architect, engineer, and skeptic.
- **init-project** - Initialize agentic-engineering in a new repository.
- **memory-update** - Update session context and memory files.
- **prune-harness** - Prune stale eval harness entries.
- **representation-audit** - Audit agent representation files for drift.
- **skeptic** - Run a focused Skeptic review on a specific change.
- **update-agentic-engineering** - Update this repo's content and rebuild adapters.
- **wrap** - End-of-session wrap-up: commit, context save, and loop state.
