---
name: agentic-engineering
description: >
  Apply when the user mentions any software development work: implementing features, fixing bugs,
  reviewing or refactoring code, debugging, testing, deploying, working with agents or subagents,
  making architecture decisions, setting up projects, managing dependencies, writing scripts, or
  any task that involves reading, writing, or reasoning about code and systems.
---

The Agentic Engineering system defines how to plan, delegate, review, and ship software using a
structured multi-agent workflow. It covers risk classification, adversarial review, task
decomposition, and quality gates so that changes are correct, safe, and reviewable. Read the rules
files on every session and the reference docs on the triggers described in agent-methodology.md.

**BEFORE ANY ACTION: classify risk first.** Elevated = spawn Worker + Skeptic in background. Direct action ONLY for: reads, answering from memory, screenshots, synthesizing subagent results, diagnostic-only logging. When in doubt, classify Elevated.

**Conductor default: act, don't ask.** The conductor's job is to complete the goal, not to approve every step. Stop and ask only for destructive/irreversible actions, missing information only the user has, materially ambiguous acceptance criteria, or scope-completion decisions. Repeated stops within one task are a planning signal, not a virtue. See `Proactive autonomy` in `rules/agent-methodology.md` for the full rule, anti-patterns, and stop-frequency thresholds.

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
  criteria and entry format for `.agentic/findings.md`, and who reads the file; read when promoting
  a finding after Skeptic sign-off or when the Skeptic checks for repeated anti-patterns.

## Rules (read on trigger)

- **rules/module-manifest.md** - required manifest header format for non-trivial source files;
  read when creating or substantially modifying a file that exports a public symbol, exceeds ~50
  LOC, or implements a side-effecting operation.