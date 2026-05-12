---
name: agentic-engineering
description: Structured multi-agent software engineering workflow for planning, delegation, review, risk classification, quality gates, and shipping code. Use for software development tasks, implementation planning, code review, debugging, refactoring, and release work.
---

The Agentic Engineering system defines how to plan, delegate, review, and ship software using a
structured multi-agent workflow. It covers risk classification, adversarial review, task
decomposition, and quality gates so that changes are correct, safe, and reviewable. Read the rules
files on every session and the reference docs on the triggers described in agent-methodology.md.

**Conductor default: act, don't ask.** The conductor's job is to complete the goal, not to approve every step. Stop and ask only for destructive/irreversible actions, missing information only the user has, materially ambiguous acceptance criteria, or scope-completion decisions. Repeated stops within one task are a planning signal, not a virtue. See `Proactive autonomy` in `rules/agent-methodology.md` for the full rule, anti-patterns, and stop-frequency thresholds.

## Rules (read these files)

- **rules/agent-methodology.md** - delegation model, risk classification, task decomposition, and
  worktree lifecycle; the core rules for when to act directly vs. spawn Workers and Skeptics.

- **rules/code-standards.md** - documentation lookups via Context7, tool discipline (Read/Glob/Grep
  over Bash for reads), code quality gates, package management conventions, and browser verification
  with agent-browser.

- **rules/conventions.md** - writing style, project structure, session context and memory handling,
  and git workflow including protected branches and worktree-per-feature conventions.

## Commands (invoke by name)

- `/brief` - interactive planning dialogue; produces the Brief artifact before architect and engineer are spawned. Invoke when operator implies planning intent at session start, or use `/brief --from <path>` to extract a Brief from an existing PRD.

## Reference Docs (read on trigger - see Protocol Details in agent-methodology.md)

- **references/skeptic-protocol.md** - Skeptic loop orchestration, findings classification
  (Critical/Major/Minor), sign-off format, adversarial briefs, and the Elevated + Cleanup path.

- **references/subagent-protocol.md** - parallel spawning rules, worktree isolation, check-in
  behavior, phase breadcrumbs, and task decomposition rules for multi-Worker plans.

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

## Pi coding agent usage

Pi discovers this skill from `.pi/skills/agentic-engineering/` for project-local use and from `~/.pi/agent/skills/agentic-engineering/` after global install.

- Force-load with `/skill:agentic-engineering` when you want the methodology active immediately.
- Pi prompt templates in `.pi/prompts/` provide slash-command equivalents for the markdown commands in `content/commands/`.
- Read `METHODOLOGY.md` at skill load before applying the workflow.
- Read command details from `commands/<name>.md` when a prompt template asks you to run a command.
- Read references from `references/` and rules from `rules/` on their documented triggers.
