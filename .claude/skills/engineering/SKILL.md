---
name: "engineering"
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

## Rules (read these files)

- **rules/agent-methodology.md** - delegation model, risk classification, task decomposition, and
  worktree lifecycle; the core rules for when to act directly vs. spawn Workers and Skeptics.

- **rules/code-standards.md** - tool discipline (Read/Glob/Grep over Bash for reads), code quality
  gates, package management conventions, and browser verification with agent-browser.

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
