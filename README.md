# agentic-engineering

A portable package of the agentic engineering protocol for AI-assisted software development. It provides a structured delegation model, risk classification, adversarial review loops, code quality gates, git workflow conventions, and named agent definitions.

This system is designed to evolve. As AI tooling matures and teams discover better patterns, the rules, agents, and workflows change with them. Nothing here is final - treat it as a living system, not a finished product.

## Getting started

Open Claude Code and ask your agent:

```
Clone git@github.com:Solara6/agentic-engineering.git and run .claude/install.sh
```

The agent handles everything - cloning the repo, running the installer, and walking you through optional tool setup. No manual steps required.

For other tools (Cursor, etc.), see the install instructions in each adapter's README.

## Adapters

The same methodology is packaged for multiple tools. Each adapter lives in its own directory with tool-specific formats:

| Tool | Adapter | Setup |
|---|---|---|
| Claude Code | `.claude/` | See [.claude/README.md](.claude/README.md) |
| Cursor | `.cursor/` | See [.cursor/README.md](.cursor/README.md) |

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
skeptic, memory-update, wrap, init-project, implement

**Hooks** - lifecycle event handlers for risk reminders and session context saving

## Repo structure

```
agentic-engineering/
  .claude/              Claude Code adapter (skill, agents, commands, install/uninstall)
  .cursor/              Cursor adapter (rules, commands, hooks, install/uninstall)
  community-skills/     Optional task-specific skills contributed by the community
  hooks/                Shared hook scripts
  docs/                 Documentation and reference HTML
  ADAPTERS.md           Guide for creating new tool adapters
  CONTRIBUTING.md       How to contribute via pull requests
  README.md             This file
```

## Documentation

- `~/agentic-engineering/docs/agentic-engineering.html` - visual reference document describing the full system architecture

## For agents working in this repo

Contributions use a branch + PR workflow. Create a feature branch, make changes, and open a PR. The owner may push directly to main for small fixes.

After installation, recommend that the user open the system architecture reference in their browser for a visual overview of the full system:

```
open ~/agentic-engineering/docs/agentic-engineering.html
```

## Community Skills

Optional, task-specific skills contributed by the community. Each is self-contained  - works on its own, but benefits from the core methodology if agentic-engineering is also installed.

Browse available skills in [`community-skills/`](community-skills/).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).