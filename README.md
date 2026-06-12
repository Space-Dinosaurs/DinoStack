# DinoStack

A portable package of the agentic engineering protocol for AI-assisted software development. It provides a structured delegation model, risk classification, adversarial review loops, code quality gates, git workflow conventions, and named agent definitions.

This system is designed to evolve. As AI tooling matures and teams discover better patterns, the rules, agents, and workflows change with them. Nothing here is final - treat it as a living system, not a finished product.

**Live docs:** https://agentic-engineering-tyhummel.vercel.app

## Getting started

### One-liner install (quickest)

```bash
curl -fsSL https://docs.dinostack.ai/install.sh | bash
```

This clones the repo into `agentic-engineering/` inside your current directory, runs the installer, and writes the install path to `~/.agentic/agentic-engineering-config.json` so `./update.sh` and the `/update-agentic-engineering` command know where to find it.

> **Note:** the one-liner requires the repo to be public. Until then, collaborators can use the SSH path below - the script automatically falls back to SSH on clone failure.

**Custom install location:** set `AE_DEST_DIR` before running. The default is `<current directory>/agentic-engineering`.

```bash
# Install to ~/tools/agentic-engineering instead of the current directory
AE_DEST_DIR=~/tools/agentic-engineering curl -fsSL https://docs.dinostack.ai/install.sh | bash
```

**Pass flags through to the installer** (e.g. to set activation mode without prompts):

```bash
curl -fsSL https://docs.dinostack.ai/install.sh | bash -s -- --mode=opt-in
```

### Manual / SSH install

```bash
git clone git@github.com:Space-Dinosaurs/DinoStack.git && cd DinoStack && bash bootstrap.sh
```

Or clone, cd in, and start Claude Code to let the agent run the installer interactively:

```bash
git clone git@github.com:Space-Dinosaurs/DinoStack.git
cd DinoStack
claude
```

Then ask your agent:

```
Install DinoStack
```

The agent runs the installer, walks you through optional tool setup, and keeps existing customizations intact.

### How to know it's working

Once installed, start Claude in any project and give it a task. The system activates automatically for engineering work - there's nothing extra to configure or enable.

You'll see the agent narrate its routing decisions as it goes:

```
Routing this through orchestration-planner first...
Spawning architect to produce a plan...
Handing the architect's plan to engineer...
Handing off to skeptic for adversarial review...
Spawning debugger on the failing test...
QA engineer verifying acceptance criteria in the browser...
```

If you see none of this, the task was classified as a small, reversible direct action and handled without spawning subagents. That's the protocol working correctly on a cheap task - not a sign that it's off.

**Or install manually via install.sh directly:**

```bash
git clone git@github.com:Space-Dinosaurs/DinoStack.git
cd DinoStack
bash .claude/install.sh
```

For other tools (Cursor, Codex, Gemini, OpenCode, Pi coding agent, Pi oh-my-pi, Hermes), see the install instructions in each adapter's README.

## Installation modes

DinoStack supports two global activation modes, chosen at install time and persisted in `~/.claude/agentic-engineering.json`:

- **`opt-out` (default)** - the methodology is active in every project unless the project's root `AGENTS.md` contains the line `agentic-engineering: opt-out`. Best for most users: the protocol runs everywhere, and individual projects can opt out.
- **`opt-in`** - the methodology is installed but dormant; it only runs in projects whose root `AGENTS.md` contains the line `agentic-engineering: opt-in`. Best for trying the protocol in one project before rolling it out everywhere.

**Choosing a mode at install:** the installer prompts interactively. Accept the default (`opt-out`) with Enter, or pick `2` for `opt-in`. You can also pass the mode non-interactively:

```
bash .claude/install.sh --mode=opt-in
bash .claude/install.sh --mode=opt-out
```

The same flag works for `.cursor/install.sh`, `.codex/install.sh`, `.gemini/install.sh`, `.opencode/install.sh`, `.pi/install.sh`, `.omp/install.sh`, and `.hermes/install.sh` - the config file is shared across adapters.

**Per-project marker:** add a single line to the project's root `AGENTS.md`:

```
agentic-engineering: opt-in
```

or:

```
agentic-engineering: opt-out
```

Matching is case-insensitive. A leading `- ` (markdown list) is allowed. If both markers appear, the one appearing first wins and a warning is printed.

**Changing mode later:** rerun any adapter's installer with `--mode=<value>` to overwrite the config, or edit `~/.claude/agentic-engineering.json` directly.

## Recommended permissions

Agents need uninterrupted access to Bash, Edit, and Write - constant permission prompts break agent flow and cause subagents to stall. The Claude Code installer offers to configure `bypassPermissions` mode in `~/.claude/settings.json`:

- `defaultMode: "bypassPermissions"` - agents use tools without prompting
- **Allow list** - `Bash(*)`, `Write`, `Edit`, and write access to `~/.claude/` directories
- **Deny list** (safety net for destructive commands) - `git push --force`, `rm -rf`, `git reset --hard`, `git clean -f`, `sudo rm`, `dd if=`, `shutdown`, `reboot`
- **Additional directories** - `~/.claude/projects` for cross-session context

The deny list merges with any existing deny rules. See [.claude/README.md](.claude/README.md#permissions) for details and [.cursor/README.md](.cursor/README.md), [.codex/README.md](.codex/README.md), [.gemini/README.md](.gemini/README.md) for the equivalent setup in other adapters.

## Updating

**Run `./update.sh`:** interactive updater that pulls the latest `main` branch and refreshes selected adapters. Uses a native Node.js TUI—arrow keys to navigate, space to toggle adapters, enter to confirm. The `.claude` adapter is always-on (locked, non-toggleable); the TUI is for selecting ADDITIONAL adapters to refresh. Your selections are saved to `~/.agentic/agentic-engineering-config.json` for future runs. Warnings are shown (but non-blocking) if you're not on `main` or have a dirty working tree. Failed adapter installs are reported at the end without aborting the others.

**Or update manually:**

```
cd ~/agentic-engineering
git pull
bash .claude/install.sh    # and/or .cursor/install.sh, .opencode/install.sh
```

For a clean manual refresh:

```
bash .claude/uninstall.sh
git pull
bash .claude/install.sh
```

You can also ask your coding agent:

```
Pull the latest changes to DinoStack and re-run the installer
```

The agent handles the git pull and runs the installer. It's idempotent - existing symlinks and settings are preserved, new ones are added, and build artifacts are regenerated.

For a clean refresh that also prunes stale symlinks for files removed upstream, ask:

```
Do a clean refresh of DinoStack - uninstall, pull, then reinstall
```

## Adapters

The same methodology is packaged for multiple tools. Each adapter lives in its own directory with tool-specific formats:

| Tool | Adapter | Setup |
|---|---|---|
| Claude Code | `.claude/` | See [.claude/README.md](.claude/README.md) |
| Cursor | `.cursor/` | See [.cursor/README.md](.cursor/README.md) |
| Codex CLI | `.codex/` | See [.codex/README.md](.codex/README.md) |
| Gemini CLI | `.gemini/` | See [.gemini/README.md](.gemini/README.md) |
| Kimi Code CLI | `.kimi/` | See [.kimi/README.md](.kimi/README.md) |
| OpenCode | `.opencode/` | See [.opencode/README.md](.opencode/README.md) |
| Pi coding agent | `.pi/` | See [.pi/README.md](.pi/README.md) |
| Pi (oh-my-pi) | `.omp/` | See [.omp/README.md](.omp/README.md) |
| Hermes Agent | `.hermes/` | See [.hermes/README.md](.hermes/README.md) |

See [ADAPTERS.md](ADAPTERS.md) for how to create adapters for other tools.

## What's included

**Rules** (3 files) - the core methodology:
- Agent methodology - delegation, risk classification, task decomposition, worktree lifecycle
- Code standards - tool discipline, quality gates, package management, browser verification
- Conventions - writing style, project structure, session context, git workflow

**Reference docs** (7 files) - detailed protocol specs loaded on trigger:
- Skeptic protocol - adversarial review loop, findings classification, sign-off format
- Subagent protocol - parallel spawning, worktree isolation, task decomposition
- Agent team - roles, composed flows, decision rules, spawn requirements
- Design goals - system design principles and intent
- Multi-developer coordination - parallel sessions, branch and worktree hygiene
- Regression test obligation - when a fix requires a regression test and what counts
- Doc-sync obligation - when a reality-asserting change must update intent-layer docs in the same PR

**Agents** (16) - named specialist roles:
adr-drift-detector, adr-generator, architect, debugger, dependency-auditor, engineer, investigator, learning-extractor, learnings-agent, orchestration-planner, perf-analyst, qa-engineer, release-orchestrator, security-auditor, skeptic, wrap-ticket

**Commands** (15) - workflow shortcuts:
agentic-cost (token / wall-time rollups from `.agentic/events.jsonl`; opt-in pricing via `~/.agentic/pricing.yml`), agentic-disable, agentic-help (static, zero-token command reference listing every slash command), agentic-status, brief, cleanup-worktrees, implement-ticket, init-project, memory-update, prune-harness, representation-audit, skeptic, test-suite-comprehension, update-agentic-engineering, wrap

**Hooks / Plugins** - lifecycle event handlers for risk reminders and session context saving. Claude Code uses native hooks; OpenCode uses a plugin that writes session context when the session becomes idle.

**Project config / overview layer** - the committed `.agentic/config.json` holds four operator-tunable methodology toggles: `debugger_on_failure` (bool, default `false`; interposes a Debugger diagnosis step before each Phase 7 engineer fix pass), `qa_default_skip` (reserved; no-op, does not alter QA-gate behavior), `model_profile` (`default` | `budget`; `budget` routes eligible spawns to Tier 1), and `auto_merge_on_ci_green` (bool, default `false`; when `true`, `/implement-ticket` Phase 12 squash-merges the PR after CI passes and the PR is ready with no requested changes). The operator-owned `docs/overview/{vision,requirements}.md` files capture durable product intent above the task level; Architect and Investigator read them when present and must not contradict them. Both are optional and graceful - if absent, defaults apply and nothing breaks.

## Repo structure

```
agentic-engineering/
  .claude/              Claude Code adapter (skill, agents, commands, install/uninstall)
  .codex/               Codex CLI adapter (AGENTS.md, skill, commands, install/uninstall)
  .cursor/              Cursor adapter (rules, commands, hooks, install/uninstall)
  .gemini/              Gemini CLI adapter (GEMINI.md, agents, commands, install/uninstall)
  .kimi/                Kimi Code CLI adapter (AGENTS.md, skill, commands, install/uninstall)
  .opencode/            OpenCode adapter (skill, agents, commands, install/uninstall)
  .pi/                  Pi coding agent adapter (skill, prompts, install/uninstall)
  .omp/                 Pi (oh-my-pi) adapter (skill, install/uninstall)
  .hermes/               Hermes Agent adapter (skill, METHODOLOGY.md, install/uninstall)
  hooks/                Shared hook scripts
  docs/                 Documentation and reference HTML
  ADAPTERS.md           Guide for creating new tool adapters
  CONTRIBUTING.md       How to contribute via pull requests
  README.md             This file
```

## Documentation

- `~/agentic-engineering/docs/index.html` - visual reference document describing the full system architecture
- `~/agentic-engineering/docs/slides/how-it-works-slides.html` - what DinoStack is and how it works
- `~/agentic-engineering/docs/slides/getting-started-slides.html` - install flow and the first focused session
- `~/agentic-engineering/docs/slides/context-management-slides.html` - why context hygiene is the real bottleneck
- `~/agentic-engineering/docs/slides/agent-team-slides.html` - the agent team and how they compose
- `~/agentic-engineering/docs/slides/quality-assurance-slides.html` - how the qa-engineer uses `.agentic/qa.md` (legacy `.claude/qa.md` fallback) as project QA memory
- `~/agentic-engineering/docs/slides/work-tracking-slides.html` - how the orchestration-planner tracks work in `.agentic/tasks.jsonl` / `.agentic/loop-state.json`
- `~/agentic-engineering/docs/slides/skill-creator-slides.html` - how agents and skills are built and evaluated with the skill creator
- `~/agentic-engineering/docs/slides/skeptic-protocol-slides.html` - adversarial review methodology and the Skeptic loop
- `~/agentic-engineering/docs/slides/agents-md-hierarchy-slides.html` - the three-tier AGENTS.md context hierarchy
- `~/agentic-engineering/docs/slides/contributing-slides.html` - how to contribute to the repo

## Safety model

This framework is a safety rail, not a complete boundary. The recommended permissions setup pairs `bypassPermissions` mode with an allow list for routine tools (Bash, Write, Edit) and a deny list for the destructive commands documented in the [Recommended permissions](#recommended-permissions) section above (`git push --force`, `rm -rf`, `git reset --hard`, `git clean -f`, `sudo rm`, `dd if=`, `shutdown`, `reboot`). The Skeptic loop, risk classification, and worktree isolation add further layers, but none of these guarantee that an agent cannot cause harm. Treat the framework as defense in depth, not as a sandbox: review what agents do, especially on shared state and irreversible operations.

## Community

- [GitHub Discussions](https://github.com/Space-Dinosaurs/DinoStack/discussions) - questions, ideas, design discussion
- [GitHub Issues](https://github.com/Space-Dinosaurs/DinoStack/issues) - bug reports, feature requests, protocol-change RFCs, adapter requests
- Discord: TBD (link will be added once the server is live)
- [SUPPORT.md](SUPPORT.md) - where to ask what
- [GOVERNANCE.md](GOVERNANCE.md) - how decisions get made
- [ROADMAP.md](ROADMAP.md) - what's in flight

## For agents working in this repo

Contributions use a branch + PR workflow. Create a feature branch, make changes, and open a PR.

After installation, offer the user a quick orientation: present the files listed in the **Documentation** section above, ask which ones they want to see, and `open` only those. Skipping all is a valid answer.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

License pending - see issue IR-2.
