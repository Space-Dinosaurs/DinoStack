# DinoStack

A portable package of the agentic engineering protocol for AI-assisted software development. It provides a structured delegation model, risk classification, adversarial review loops, code quality gates, git workflow conventions, and named agent definitions.

This system is designed to evolve. As AI tooling matures and teams discover better patterns, the rules, agents, and workflows change with them. Nothing here is final - treat it as a living system, not a finished product.

**Live docs:** https://docs.dinostack.ai/

## Getting started

### One-liner install (quickest)

```bash
curl -fsSL https://docs.dinostack.ai/install.sh | bash
```

This clones the repo into `DinoStack/` inside your current directory, runs the installer, and writes the install path to `~/.agentic/agentic-engineering-config.json` so `./update.sh` and the `/update-agentic-engineering` command know where to find it.

> **Note:** if the one-liner clone fails (e.g. network or auth issue), the script automatically falls back to SSH.

**Custom install location:** set `AE_DEST_DIR` before running. The default is `<current directory>/DinoStack`.

> **Folder naming:** both the one-liner and a plain `git clone` land in `DinoStack/`. Use `AE_DEST_DIR` to install elsewhere.

```bash
# Install to ~/tools/DinoStack instead of the current directory
AE_DEST_DIR=~/tools/DinoStack curl -fsSL https://docs.dinostack.ai/install.sh | bash
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

For other tools (Cursor, Codex, Gemini, OpenCode, Pi coding agent, Pi oh-my-pi, Hermes, OpenClaw), see the install instructions in each adapter's README.

## Installation modes

DinoStack supports two global activation modes, chosen at install time and persisted in `~/.claude/agentic-engineering.json`:

- **`opt-out` (default)** - the methodology is active in every project unless the project's root `AGENTS.md` contains the line `agentic-engineering: opt-out`. Best for most users: the protocol runs everywhere, and individual projects can opt out.
- **`opt-in`** - the methodology is installed but dormant; it only runs in projects whose root `AGENTS.md` contains the line `agentic-engineering: opt-in`. Best for trying the protocol in one project before rolling it out everywhere.

**Choosing a mode at install:** the installer prompts interactively. Accept the default (`opt-out`) with Enter, or pick `2` for `opt-in`. You can also pass the mode non-interactively:

```
bash .claude/install.sh --mode=opt-in
bash .claude/install.sh --mode=opt-out
```

The following flags work for all adapters (`.claude`, `.cursor`, `.codex`, `.gemini`, `.opencode`, `.pi`, `.omp`, `.kimi`, `.hermes`, and `.openclaw`) - the config file is shared across adapters:

```
bash .claude/install.sh --identity=<handle>   # set developer identity (GitHub handle) non-interactively
bash .claude/install.sh --no-identity          # skip the developer-identity prompt
```

**Changing mode later:** rerun any adapter's installer with `--mode=<value>` to overwrite the config, or edit `~/.claude/agentic-engineering.json` directly.

## Recommended permissions

Agents need uninterrupted access to Bash, Edit, and Write - constant permission prompts break agent flow and cause subagents to stall. The Claude Code installer offers to configure `bypassPermissions` mode in `~/.claude/settings.json`:

- `defaultMode: "bypassPermissions"` - agents use tools without prompting
- **Allow list** - `Bash(*)`, `Write`, `Edit`, and write access to `~/.claude/` directories
- **Deny list** (safety net for destructive commands) - `git push --force`, `rm -rf`, `git reset --hard`, `git clean -f`, `sudo rm`, `dd if=`, `shutdown`, `reboot`
- **Additional directories** - `~/.claude/projects` for cross-session context

The deny list merges with any existing deny rules. See [.claude/README.md](.claude/README.md#permissions) for details and [.cursor/README.md](.cursor/README.md), [.codex/README.md](.codex/README.md), [.gemini/README.md](.gemini/README.md) for the equivalent setup in other adapters.

## Initialize a project

After installation, run `/init-project` in any new or existing project to scaffold the `AGENTS.md` hierarchy, `.agentic/config.json`, and related structure.

**Per-project activation marker:** add a single line to the project's root `AGENTS.md` to control whether the methodology is active in that project:

```
agentic-engineering: opt-in
```

or:

```
agentic-engineering: opt-out
```

Matching is case-insensitive. A leading `- ` (markdown list) is allowed. If both markers appear, the one appearing first wins and a warning is printed.

With the global mode set to `opt-out` (the default), a project without any marker still runs the methodology. With `opt-in` mode, a project must have the `opt-in` marker or the methodology stays dormant.

## Updating

Run `./update.sh` for an interactive TUI updater (arrow keys, space to toggle adapters). For non-interactive or CI use, run `git pull` first then `./install-all.sh`.

Full details - manual update steps, clean-refresh procedure, and agent-driven update prompts: see [docs/updating.md](docs/updating.md).

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
| OpenClaw | `.openclaw/` | See [.openclaw/README.md](.openclaw/README.md) |

See [ADAPTERS.md](ADAPTERS.md) for how to create adapters for other tools.

## Documentation

- `~/DinoStack/docs/index.html` - visual reference document describing the full system architecture
- `~/DinoStack/docs/slides/how-it-works-slides.html` - what DinoStack is and how it works
- `~/DinoStack/docs/slides/getting-started-slides.html` - install flow and the first focused session
- `~/DinoStack/docs/slides/context-management-slides.html` - why context hygiene is the real bottleneck
- `~/DinoStack/docs/slides/agent-team-slides.html` - the agent team and how they compose
- `~/DinoStack/docs/slides/quality-assurance-slides.html` - how the qa-engineer uses `.agentic/qa.md` (legacy `.claude/qa.md` fallback) as project QA memory
- `~/DinoStack/docs/slides/work-tracking-slides.html` - how the orchestration-planner tracks work in `.agentic/tasks.jsonl` / `.agentic/loop-state.json`
- `~/DinoStack/docs/slides/skill-creator-slides.html` - how agents and skills are built and evaluated with the skill creator
- `~/DinoStack/docs/slides/skeptic-protocol-slides.html` - adversarial review methodology and the Skeptic loop
- `~/DinoStack/docs/slides/agents-md-hierarchy-slides.html` - the three-tier AGENTS.md context hierarchy
- `~/DinoStack/docs/slides/contributing-slides.html` - how to contribute to the repo

Full inventory of rules, agents, commands, and config toggles: see [docs/components.md](docs/components.md).

Per-developer attribution and telemetry setup: see [docs/identity-telemetry.md](docs/identity-telemetry.md).

## Safety

The framework is a safety rail, not a complete boundary. The deny list and Skeptic loop reduce risk; neither is a sandbox. See [SAFETY.md](SAFETY.md) for the full safety model and the recommended deny list.

## Community

- [GitHub Discussions](https://github.com/Space-Dinosaurs/DinoStack/discussions) - questions, ideas, design discussion
- [GitHub Issues](https://github.com/Space-Dinosaurs/DinoStack/issues) - bug reports, feature requests, protocol-change RFCs, adapter requests
- Discord: TBD (link will be added once the server is live)
- [SUPPORT.md](SUPPORT.md) - where to ask what
- [GOVERNANCE.md](GOVERNANCE.md) - how decisions get made
- [ROADMAP.md](ROADMAP.md) - what's in flight

## Naming

DinoStack is the product; `agentic-engineering` is the package it ships. The `agentic-engineering` name appears throughout the internals - the `~/.claude/agentic-engineering.json` config, the `agentic-engineering: opt-in` marker, the `.agentic/` directory, the `/agentic-*` commands - and stays stable so existing installs keep working.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.
