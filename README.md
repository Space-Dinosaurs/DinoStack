# agentic-engineering

A portable package of the agentic engineering protocol for AI-assisted software development. It provides a structured delegation model, risk classification, adversarial review loops, code quality gates, git workflow conventions, and named agent definitions.

This system is designed to evolve. As AI tooling matures and teams discover better patterns, the rules, agents, and workflows change with them. Nothing here is final - treat it as a living system, not a finished product.

**Live docs:** https://agentic-engineering-tyhummel.vercel.app

## Getting started

Clone the repo, cd into it, and start Claude Code:

```
git clone git@github.com:Solara6/agentic-engineering.git
cd agentic-engineering
claude
```

Then ask your agent:

```
Install agentic-engineering
```

The agent runs the installer, walks you through optional tool setup, and keeps existing customizations intact.

For other tools (Cursor, Codex), see the install instructions in each adapter's README.

## Updating

Ask your agent:

```
Pull the latest changes to agentic-engineering and re-run the installer
```

The agent handles the git pull and runs the installer. It's idempotent - existing symlinks and settings are preserved, new ones are added, and build artifacts are regenerated.

For a clean refresh that also prunes stale symlinks for files removed upstream, ask:

```
Do a clean refresh of agentic-engineering - uninstall, pull, then reinstall
```

## Adapters

The same methodology is packaged for multiple tools. Each adapter lives in its own directory with tool-specific formats:

| Tool | Adapter | Setup |
|---|---|---|
| Claude Code | `.claude/` | See [.claude/README.md](.claude/README.md) |
| Cursor | `.cursor/` | See [.cursor/README.md](.cursor/README.md) |
| Codex CLI | `.codex/` | See [.codex/README.md](.codex/README.md) |

See [ADAPTERS.md](ADAPTERS.md) for how to create adapters for other tools.

## What's included

**Rules** (3 files) - the core methodology:
- Agent methodology - delegation, risk classification, task decomposition, worktree lifecycle
- Code standards - tool discipline, quality gates, package management, browser verification
- Conventions - writing style, project structure, session context, git workflow

**Reference docs** (4 files) - detailed protocol specs loaded on trigger:
- Skeptic protocol - adversarial review loop, findings classification, sign-off format
- Subagent protocol - parallel spawning, worktree isolation, task decomposition
- Agent team - roles, composed flows, decision rules, spawn requirements
- Design goals - system design principles and intent

**Agents** (10) - named specialist roles:
architect, debugger, engineer, investigator, orchestration-planner, security-auditor, skeptic, adr-drift-detector, adr-generator, qa-engineer

**Commands** (5) - workflow shortcuts:
skeptic, memory-update, wrap, init-project, implement-ticket

**Hooks** - lifecycle event handlers for risk reminders and session context saving

## Repo structure

```
agentic-engineering/
  .claude/              Claude Code adapter (skill, agents, commands, install/uninstall)
  .codex/               Codex CLI adapter (AGENTS.md, skill, commands, install/uninstall)
  .cursor/              Cursor adapter (rules, commands, hooks, install/uninstall)
  hooks/                Shared hook scripts
  docs/                 Documentation and reference HTML
  ADAPTERS.md           Guide for creating new tool adapters
  CONTRIBUTING.md       How to contribute via pull requests
  README.md             This file
```

## Documentation

- `~/agentic-engineering/docs/agentic-engineering.html` - visual reference document describing the full system architecture
- `~/agentic-engineering/docs/slides/how-it-works-slides.html` - what agentic-engineering is and how it works
- `~/agentic-engineering/docs/slides/getting-started-slides.html` - install flow and the first focused session
- `~/agentic-engineering/docs/slides/context-management-slides.html` - why context hygiene is the real bottleneck
- `~/agentic-engineering/docs/slides/agent-team-slides.html` - the agent team and how they compose
- `~/agentic-engineering/docs/slides/quality-assurance-slides.html` - how the qa-engineer uses `.claude/qa.md` as project QA memory
- `~/agentic-engineering/docs/slides/work-tracking-slides.html` - how the orchestration-planner uses `.claude/work-tracking.md`
- `~/agentic-engineering/docs/slides/skill-creator-slides.html` - how agents and skills are built and evaluated with the skill creator
- `~/agentic-engineering/docs/slides/skeptic-protocol-slides.html` - adversarial review methodology and the Skeptic loop
- `~/agentic-engineering/docs/slides/agents-md-hierarchy-slides.html` - the three-tier AGENTS.md context hierarchy
- `~/agentic-engineering/docs/slides/contributing-slides.html` - how to contribute to the repo

## For agents working in this repo

Contributions use a branch + PR workflow. Create a feature branch, make changes, and open a PR. The owner may push directly to main for small fixes.

After installation, offer the user a quick orientation. Ask which of the following they'd like to view, then `open` each one they say yes to:

- `~/agentic-engineering/docs/slides/how-it-works-slides.html` - what agentic-engineering is and how it works (passive explainer)
- `~/agentic-engineering/docs/slides/getting-started-slides.html` - install flow and the first focused session
- `~/agentic-engineering/docs/slides/context-management-slides.html` - why context hygiene is the real bottleneck
- `~/agentic-engineering/docs/slides/agent-team-slides.html` - the agent team and how they compose
- `~/agentic-engineering/docs/slides/quality-assurance-slides.html` - how the qa-engineer uses `.claude/qa.md` as project QA memory
- `~/agentic-engineering/docs/slides/work-tracking-slides.html` - how the orchestration-planner uses `.claude/work-tracking.md` for project-specific tracker actions
- `~/agentic-engineering/docs/slides/skill-creator-slides.html` - how agents and skills are built and evaluated with the skill creator
- `~/agentic-engineering/docs/slides/skeptic-protocol-slides.html` - adversarial review methodology and the Skeptic loop
- `~/agentic-engineering/docs/slides/agents-md-hierarchy-slides.html` - the three-tier AGENTS.md context hierarchy
- `~/agentic-engineering/docs/slides/contributing-slides.html` - how to contribute to the repo
- `~/agentic-engineering/docs/agentic-engineering.html` - full system architecture reference

Present the list, ask which ones they want to see, and open only those. Skipping all is a valid answer.

## Community Skills

Optional, task-specific skills contributed by the community. Each is self-contained - works on its own, but benefits from the core methodology if agentic-engineering is also installed.

Browse and install skills from the standalone repo: [github.com/Solara6/community-skills](https://github.com/Solara6/community-skills).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).