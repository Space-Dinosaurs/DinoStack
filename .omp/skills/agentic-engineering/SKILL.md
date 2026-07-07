---
name: agentic-engineering
description: >
  Apply when the user mentions any software development work: implementing features, fixing bugs,
  reviewing or refactoring code, debugging, testing, deploying, working with agents or subagents,
  making architecture decisions, setting up projects, managing dependencies, writing scripts, or
  any task that involves reading, writing, or reasoning about code and systems.
---

> **IMPORTANT - READ THIS FIRST:** If `skill_auto_load: true` is set in `~/.claude/agentic-engineering.json`, this skill is configured to auto-load. Read this entire SKILL.md before taking any action on software development tasks. Do not start implementing until you have read the Rules section below.

The Agentic Engineering system defines how to plan, delegate, review, and ship software using a
structured multi-agent workflow. It covers risk classification, adversarial review, task
decomposition, and quality gates so that changes are correct, safe, and reviewable. Read the rules
files on every session and the reference docs on the triggers described in METHODOLOGY.md §Protocol Details (read on trigger).

**Conductor default: act, don't ask.** The conductor's job is to complete the goal, not to approve every step. Stop and ask only for destructive/irreversible actions, missing information only the user has, materially ambiguous acceptance criteria, or scope-completion decisions. Repeated stops within one task are a planning signal, not a virtue. See `Proactive autonomy` in METHODOLOGY.md §Delegation for the full rule, anti-patterns, and stop-frequency thresholds.

## Rules (read these files)

- **METHODOLOGY.md** - the assembled kernel: delegation, risk classification, activation preflight, planning gate,
  task decomposition, and worktree lifecycle; the core rules for when to act directly vs. spawn Workers and Skeptics.

- **rules/code-standards.md** - documentation lookups via Context7, tool discipline (Read always
  primary; prefer Glob/Grep when available, Bash `rg`/`grep`/`find` as the sanctioned fallback
  otherwise), code quality gates, package management conventions, and browser verification with
  agent-browser.

- **rules/conventions.md** - writing style, project structure, session context and memory handling,
  and git workflow including protected branches and worktree-per-feature conventions.

## Commands (invoke by name)

- `/agentic-help` - static, zero-token command reference; lists every slash command with a one-line description.
- `/agentic-status` - read-only resolver dump; shows the resolved mode, profile, and marker with provenance plus a plain-English explainer of what they do and how to change them.
- `/brief` - interactive planning dialogue; produces the Brief artifact before architect and engineer are spawned. Invoke when operator implies planning intent at session start, or use `/brief --from <path>` to extract a Brief from an existing PRD.
- `/pull-and-install` - update an existing agentic-engineering/DinoStack install (or fresh-install if none exists); invoke when the user says "pull and install DinoStack", "update DinoStack", "install the latest DinoStack", "reinstall agentic-engineering", or "update my AE install".

Run `/agentic-help` for the full command inventory.

## Reference Docs (read on trigger - see Protocol Details in METHODOLOGY.md)

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

- **references/doc-sync-obligation.md** - per-change doc-sync obligation: a reality-asserting
  change (alters a count/list/path/convention/behavior an intent-layer doc states) must update
  the affected docs in the same change; read when a change touches a documented surface.

- **references/role-models.md** - Pi / oh-my-pi per-role model routing and antagonist
  reviewer model diversity; read when resolving `role-models.yml` or spawning reviewers on Pi/omp.

- **references/model-discovery.md** - Pi/oh-my-pi model selection paths (ask-user
  wizard, harness-native, pin-by-hand) and the per-role ranking heuristics in
  `bin/agentic-models`; read when seeding `role-models.yml`.

- **references/cross-harness-teams.md** - `agentic-team` CLI and `team.yml` schema for
  orchestrating parallel agent teams across multiple AI harnesses; read when using
  `agentic-team` or configuring cross-harness dispatch with `team.yml`.

- **references/digest-return-pattern.md** - digest-return discipline: when a background
  loop-running spawn (multi-iteration Skeptic/QA, long investigation) returns, the conductor
  reads the structured digest and acts - it does not re-read the internal transcript; read
  when running a multi-unit plan with parallel background loops.

## Rules (read on trigger)

- **rules/module-manifest.md** - required manifest header format for non-trivial source files;
  read when creating or substantially modifying a file that exports a public symbol, exceeds ~50
  LOC, or implements a side-effecting operation.

## oh-my-pi (omp) usage

oh-my-pi discovers this skill from `.omp/skills/agentic-engineering/` for project-local use and from `~/.omp/agent/skills/agentic-engineering/` after global install.

**Auto-trigger:** The skill loads automatically when you describe software development work. Ask the agent to "use the agentic-engineering skill" for an explicit load.

**IMPORTANT:** oh-my-pi does NOT support custom markdown slash commands like `/init-project`, `/wrap`, `/brief`, or any other command referenced in the "Commands (invoke by name)" section above. That section describes Claude Code slash-command conventions - in oh-my-pi, invoke the same commands via natural language (e.g. "run init-project", "do a wrap") or by reading the corresponding `commands/<name>.md` file directly and following its instructions.

Read `METHODOLOGY.md` at skill load before applying the workflow. Read command details from `commands/<name>.md` when a workflow step asks you to run a command. Read references from `references/` and rules from `rules/` on their documented triggers.

## oh-my-pi subagent mapping

oh-my-pi provides built-in subagent types. Map agentic-engineering roles to them as follows:

- **`task`** (default) - general implementation work (maps to `engineer`, `debugger`, `qa-engineer`, `perf-analyst`). The standard Worker for Elevated-risk tasks.
- **`explore`** - fast read-only codebase exploration (maps to `investigator`, `dependency-auditor`, `adr-drift-detector`).
- **`plan`** - implementation planning and architecture design (maps to `architect`, `orchestration-planner`, `adr-generator`).
- **`designer`** - UI/UX design work (maps to designer roles).
- **`reviewer`** - adversarial code review (maps to `skeptic`, `security-auditor`).
- **`quick_task`** - lightweight, low-risk tasks that don't need full Worker + Skeptic review.

oh-my-pi also provides native commands that map to methodology workflows:
- `/plan` - maps to `orchestration-planner` or `architect` workflows
- `/review` - maps to `skeptic` adversarial review

When spawning a subagent, read the corresponding detailed agent file from `agents/<name>.md` and include its full instructions in the spawn prompt. The agent files contain role-specific constraints, reporting formats, and workflow rules that `references/agent-team.md` does not cover in detail.

| Agentic role | File to read | oh-my-pi subagent type |
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

For the **Skeptic** role, spawn a `reviewer` subagent or use oh-my-pi's native `/review` command, prepending the skeptic instructions from `agents/skeptic.md` (or `references/skeptic-protocol.md` for the protocol overview) and restricting its task to read-only review.
