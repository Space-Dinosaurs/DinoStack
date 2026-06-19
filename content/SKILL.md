<!--
Purpose: Canonical body text for the agentic-engineering skill loaded by AI coding agents.
         This file is the single source of truth for the skill's instructional content;
         adapter-specific frontmatter (name, description, trigger conditions) is kept
         separately in each adapter's build directory and prepended at build time.

Public API: consumed as-is by adapter build scripts (e.g. .claude/build.sh) which
            concatenate <adapter>/SKILL.frontmatter.yaml + this file to produce the
            final adapter SKILL.md.

Upstream deps: none (leaf content file; no imports or code dependencies).

Downstream consumers: .claude/skills/agentic-engineering/SKILL.md (assembled by
                      .claude/build.sh). Other adapters (.codex, .cursor, .kimi,
                      .opencode) maintain their own frontmatter and may derive from
                      this file if their body content converges.

Failure modes: edits here take effect for .claude after re-running .claude/build.sh.
               Adapters whose SKILL.md is a static committed file will drift silently
               until their own build or manual sync is run. No side effects at read time.

Performance: standard (static markdown file).
-->

> **IMPORTANT - READ THIS FIRST:** If `skill_auto_load: true` is set in `~/.claude/agentic-engineering.json`, this skill is configured to auto-load. Read this entire SKILL.md before taking any action on software development tasks. Do not start implementing until you have read the Rules section below.

The Agentic Engineering system defines how to plan, delegate, review, and ship software using a
structured multi-agent workflow. It covers risk classification, adversarial review, task
decomposition, and quality gates so that changes are correct, safe, and reviewable. Read the rules
files on every session and the reference docs on the triggers described in agent-methodology.md.

**Conductor default: act, don't ask.** The conductor's job is to complete the goal, not to approve every step. Stop and ask only for destructive/irreversible actions, missing information only the user has, materially ambiguous acceptance criteria, or scope-completion decisions. Repeated stops within one task are a planning signal, not a virtue. See `Proactive autonomy` in `rules/agent-methodology.md` for the full rule, anti-patterns, and stop-frequency thresholds.

## Rules (read these files)

- **rules/agent-methodology.md** - delegation model, risk classification, task decomposition, and
  worktree lifecycle; the core rules for when to act directly vs. spawn Workers and Skeptics.

- **rules/code-standards.md** - documentation lookups via Context7, tool discipline (Read always
  primary; prefer Glob/Grep when available, Bash `rg`/`grep`/`find` as the sanctioned fallback per
  #52004), code quality gates, package management conventions, and browser verification with
  agent-browser.

- **rules/conventions.md** - writing style, project structure, session context and memory handling,
  and git workflow including protected branches and worktree-per-feature conventions.

## Commands (invoke by name)

- `/agentic-help` - static, zero-token command reference; lists every slash command with a one-line description.
- `/agentic-status` - read-only resolver dump; shows the resolved mode, profile, preset, and marker with provenance plus a plain-English explainer of what they do and how to change them.
- `/brief` - interactive planning dialogue; produces the Brief artifact before architect and engineer are spawned. Invoke when operator implies planning intent at session start, or use `/brief --from <path>` to extract a Brief from an existing PRD.
- `/pull-and-install` - update an existing agentic-engineering/DinoStack install (or fresh-install if none exists); invoke when the user says "pull and install DinoStack", "update DinoStack", "install the latest DinoStack", "reinstall agentic-engineering", or "update my AE install".

Run `/agentic-help` for the full command inventory.

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

- **references/doc-sync-obligation.md** - per-change doc-sync obligation: a reality-asserting
  change (alters a count/list/path/convention/behavior an intent-layer doc states) must update
  the affected docs in the same change; read when a change touches a documented surface.

## Rules (read on trigger)

- **rules/module-manifest.md** - required manifest header format for non-trivial source files;
  read when creating or substantially modifying a file that exports a public symbol, exceeds ~50
  LOC, or implements a side-effecting operation.
