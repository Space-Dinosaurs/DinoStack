---
name: dinostack
description: Structured multi-agent software engineering workflow for planning, delegation, review, risk classification, quality gates, and shipping code. Use for software development tasks, implementation planning, code review, debugging, refactoring, and release work.
---

> **IMPORTANT - READ THIS FIRST:** If `skill_auto_load: true` is set in `~/.claude/agentic-engineering.json`, this skill is configured to auto-load. Read this entire SKILL.md before taking any action on software development tasks. Do not start implementing until you have read the Rules section below.

The Agentic Engineering system defines how to plan, delegate, review, and ship software using a
structured multi-agent workflow. It covers risk classification, adversarial review, task
decomposition, and quality gates so that changes are correct, safe, and reviewable. Read the rules
files on every session and the reference docs on the triggers described in METHODOLOGY.md §Protocol Details (read on trigger).

**Early relaxed-advice routing gate.** This gate applies only after activation resolves
`profile=relaxed` and all four canonical predicates pass. If profile is `default` or `strict`, this
gate does not apply and the motivating advisory retains its existing Elevated routing. After the
relaxed-only guard passes, apply risk classification before the first project-content read. Relaxed
ephemeral chat advice remains direct only when the answer can be produced from context already held;
otherwise classify Elevated before reading. Within that relaxed-only override, breadth alone is not
an investigation request. For the exact prompt `How would you recommend changing DinoStack?` in
that relaxed-only override, give bounded high-level advice from the methodology and context loaded
during mandatory skill activation, state specificity or evidence limitations when useful, and do
not explore the project merely to improve specificity. Within that relaxed-only override, only an
explicit user request for unfamiliar, repository-specific, multi-file or multi-read evidence is
Elevated and delegated before any project-content read.

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

- `/ds-help` - static, zero-token command reference; lists every slash command with a one-line description.
- `/ds-status` - read-only resolver dump; shows the resolved mode, profile, and marker with provenance plus a plain-English explainer of what they do and how to change them.
- `/ds-brief` - interactive planning dialogue; produces the Brief artifact before architect and engineer are spawned. Invoke when operator implies planning intent at session start, or use `/ds-brief --from <path>` to extract a Brief from an existing PRD.
- `/ds-update` - update an existing dinostack/DinoStack install (or fresh-install if none exists); invoke when the user says "pull and install DinoStack", "update DinoStack", "install the latest DinoStack", "reinstall dinostack", or "update my AE install".

Run `/ds-help` for the full command inventory.

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
  `bin/ds-models`; read when seeding `role-models.yml`.

- **references/evidence-on-disk.md** - spill/sketch/rehydrate protocol for large
  tool output; when to spill, the three-step loop, teardown, and ephemerality.

- **references/cross-harness-teams.md** - `ds-team` CLI and `team.yml` schema for
  orchestrating parallel agent teams across multiple AI harnesses; read when using
  `ds-team` or configuring cross-harness dispatch with `team.yml`.

- **references/digest-return-pattern.md** - digest-return discipline: when a background
  loop-running spawn (multi-iteration Skeptic/QA, long investigation) returns, the conductor
  reads the structured digest and acts - it does not re-read the internal transcript; read
  when running a multi-unit plan with parallel background loops.

- **references/learnings-capture-instruction.md** - the standing "watch for learnings"
  instruction: what counts as a learning, the in-flight `ds-learning-shard append` path for
  the four roles it belongs to (`engineer`, `adr-generator`, `product-discovery`,
  `release-orchestrator`), the `learnings_candidate[]` path for the three roles whose return
  contract declares that field, and its canonical definition; read when acting as any
  subagent role.

- **references/command-authoring.md** - authoring discipline for commands, skills, and
  agent definitions: trigger-keyword descriptions (always injected into context even when
  unused, so enumerate when to fire, not behavior) and bad/good example-pair seeding to
  encode taste; read when authoring or editing a command file, skill definition, or agent
  definition.

## Rules (read on trigger)

- **rules/module-manifest.md** - required manifest header format for non-trivial source files;
  read when creating or substantially modifying a file that exports a public symbol, exceeds ~50
  LOC, or implements a side-effecting operation.

## Pi coding agent usage

Pi discovers this skill from `.pi/skills/dinostack/` for project-local use and from `~/.pi/agent/skills/dinostack/` after global install.

- Force-load with `/skill:dinostack` when you want the methodology active immediately.
- Pi prompt templates in `.pi/prompts/` provide slash-command equivalents for the markdown commands in `content/commands/`.
- Read `METHODOLOGY.md` at skill load before applying the workflow.
- Read command details from `commands/<name>.md` when a prompt template asks you to run a command.
- Read references from `references/` and rules from `rules/` on their documented triggers.
