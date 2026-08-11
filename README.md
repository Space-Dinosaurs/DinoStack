<p align="center">
  <img alt="DinoStack" src="docs/images/dinostack-logo-banner.svg" width="360">
</p>

# DinoStack

A portable package of the agentic engineering protocol for AI-assisted software development. It provides a structured delegation model, risk classification, adversarial review loops, code quality gates, git workflow conventions, and named agent definitions.

This system is designed to evolve. As AI tooling matures and teams discover better patterns, the rules, agents, and workflows change with them. Nothing here is final - treat it as a living system, not a finished product.

**Live docs:** https://docs.dinostack.ai/

## Updating

Run `ds-update` from anywhere, no arguments.

| Path                | Command                          | When                                                                                                             |
| ------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Shell (recommended) | `ds-update`                 | Default; from any directory, no TTY                                                                              |
| In-session          | `/ds-update`                     | Inside Claude Code, any project                                                                                  |
| TUI                 | `./update.sh`                    | Interactive adapter selection                                                                                    |
| CI / scripts        | `git pull && ./install-all.sh`   | Non-interactive                                                                                                  |
| Repair drift        | `ds-doctor --fix`           | Fix broken symlinks/hooks (e.g. after moving the repo)                                                           |
| Check cross-harness | `ds-doctor --cross-harness` | Validate team.yml / role-models.yml, referenced harnesses, and model handles (add `--json` for machine output) |

Bootstrap is guarded against creating a second clone - if an existing install is detected it aborts and prints the update-in-place command.

Full details: [docs/updating.md](docs/updating.md).

Every `ds-*` CLI (e.g. `ds-update`, `ds-doctor`, `ds-cost`) has a permanent
`agentic-*` compat alias (e.g. `agentic-update`) - both names invoke the same
binary and behave identically. `ds-*` is the current primary name; the
`agentic-*` form is kept indefinitely for existing cron jobs and shell
aliases.

## Getting started

### One-liner install (quickest)

```bash
curl -fsSL https://docs.dinostack.ai/install.sh | bash
```

This clones the repo into `DinoStack/` inside your current directory, runs the installer, and writes the install path to `~/.agentic/agentic-engineering-config.json` so `./update.sh` and the `/ds-update` command know where to find it.

> **Note:** if the one-liner clone fails (e.g. network or auth issue), the script automatically falls back to SSH.

**Custom install location:** set `AE_DEST_DIR` before running. The default is `<current directory>/DinoStack`.

> **Folder naming:** both the one-liner and a plain `git clone` land in `DinoStack/`. Use `AE_DEST_DIR` to install elsewhere.

```bash
# Install to ~/tools/DinoStack instead of the current directory
curl -fsSL https://docs.dinostack.ai/install.sh | AE_DEST_DIR=~/tools/DinoStack bash
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

For other tools (Cursor, Codex, Gemini, OpenCode, Pi coding agent, Pi oh-my-pi, Hermes, OpenClaw, VS Code Copilot), see the install instructions in each adapter's README.

## Multiple profiles

If you run several isolated tenant config dirs per tool (e.g. `~/.claude-projectA`, `~/.codex-projectB`), install into them without relocating shared state. Every harness `install.sh` accepts `--config-dir=<dir>` (or the `AGENTIC_CONFIG_DIR` env var); only the per-harness config directory moves, while shared user state (`~/.agentic`, `~/.local/bin`, `~/.claude.json`) always stays in the real `$HOME`.

Codex has one activation-path exception for tenant isolation. Its default activation config is
`$HOME/.claude/agentic-engineering.json`. For a redirected Codex config directory, activation
moves into that selected directory as `agentic-engineering.json`; runtime precedence is
`AGENTIC_CONFIG_DIR` > `CODEX_HOME` > default. A redirected Codex install does not validate,
create, or mutate `$HOME/.claude`.

```bash
# one profile, one harness
bash .claude/install.sh --config-dir=$HOME/.claude-<tenant>

# discover existing profiles from disk and reinstall all of them
./scripts/install-profiles.sh

# explicit tenant list (still supported)
./scripts/install-profiles.sh \
  --tenants="acme beta" \
  --harnesses="claude codex omp pi"

# create a new profile and install into it (opt-in, gated by a pre-flight check)
./scripts/install-profiles.sh --create-profile=<tenant>

# check whether a new profile can be created without creating anything
./scripts/install-profiles.sh --create-profile=<tenant> --check-only
```

By default `install-profiles.sh` discovers tenants from existing `~/.<harness>-*` directories on disk, so it works for any tenant names. It never creates new profile directories unless you explicitly pass `--create-profile=<tenant>`. That path is gated by a pre-flight check that reports `creatable: yes/no` before creating anything, and it refuses to create a directory that already exists. Pass `--no-cursor` to skip the global Cursor install; extra flags (`--mode=`, `--profile=`, `--dry-run`) are forwarded to each harness installer.

## Installation modes

DinoStack supports two global activation modes, chosen at install time and persisted in `~/.claude/agentic-engineering.json`:

- **`opt-out` (default)** - the methodology is active in every project unless the project's root `AGENTS.md` contains the line `agentic-engineering: opt-out`. Best for most users: the protocol runs everywhere, and individual projects can opt out.
- **`opt-in`** - the methodology is installed but dormant; it only runs in projects whose root `AGENTS.md` contains the line `agentic-engineering: opt-in`. Best for trying the protocol in one project before rolling it out everywhere.

**Choosing a mode at install:** the installer prompts interactively. Accept the default (`opt-out`) with Enter, or pick `2` for `opt-in`. You can also pass the mode non-interactively:

```
bash .claude/install.sh --mode=opt-in
bash .claude/install.sh --mode=opt-out
```

The following flags work for all adapters (`.claude`, `.cursor`, `.codex`, `.gemini`, `.opencode`, `.pi`, `.omp`, `.kimi`, `.hermes`, `.openclaw`, and `.copilot`) - the config file is shared across adapters:

```
bash .claude/install.sh --identity=<handle>   # set developer identity (GitHub handle) non-interactively
bash .claude/install.sh --no-identity          # skip the developer-identity prompt
bash .claude/install.sh --dry-run             # preview symlink, CLAUDE.md managed-block update, and repo_dir changes; hook, build, and permission phases still execute
```

**Changing mode later:** rerun any adapter's installer with `--mode=<value>` to overwrite the config, or edit `~/.claude/agentic-engineering.json` directly.

## Recommended permissions

Agents need uninterrupted access to Bash, Edit, and Write - constant permission prompts break agent flow and cause subagents to stall. The Claude Code installer offers to configure `bypassPermissions` mode in `~/.claude/settings.json`:

- `defaultMode: "bypassPermissions"` - agents use tools without prompting
- **Allow list** - `Bash(*)`, the bare `Write` and `Edit` tool rules, and path-scoped `Edit(~/.claude/**)` / `Edit(~/.claude/projects/**)` rules. Only `Edit(path)` rules are matched by Claude Code's file-permission checks - path-scoped `Write(path)` rules are ignored and are migrated out of existing settings that already have the bare `Write` rule (left in place otherwise)
- **Deny list** (safety net for destructive commands) - `git push --force`, `rm -rf`, `git reset --hard`, `git clean -f`, `sudo rm`, `dd if=`, `shutdown`, `reboot`
- **Additional directories** - `~/.claude/projects` for cross-session context

The deny list merges with any existing deny rules. See [.claude/README.md](.claude/README.md#permissions) for details and [.cursor/README.md](.cursor/README.md), [.codex/README.md](.codex/README.md), [.gemini/README.md](.gemini/README.md) for the equivalent setup in other adapters. For Codex specifically, see [docs/codex-permissions.md](docs/codex-permissions.md) for the recommended trusted-work config and its tradeoffs.

## Initialize a project

After installation, run `/ds-init-project` in any new or existing project to scaffold the `AGENTS.md` hierarchy, `.agentic/config.json`, and related structure.

**Per-project activation marker:** add a single line to the project's root `AGENTS.md` to control whether the methodology is active in that project:

```
agentic-engineering: opt-in
```

or:

```
agentic-engineering: opt-out
```

Matching is case-insensitive. A leading `- ` (markdown list) is allowed. If both markers appear, the one appearing first wins and a warning is printed.

The per-project marker only has effect in combination with the global activation mode set at install (the `--mode` flag). See [Installation modes](#installation-modes).

- **Global `opt-out` (default):** every project is active unless it contains `agentic-engineering: opt-out`. Adding `opt-in` to a project has no effect - the project is already active.
- **Global `opt-in`:** every project is dormant unless it contains `agentic-engineering: opt-in`. Adding `opt-out` to a project has no effect - the project is already dormant.

## Project config

`.agentic/config.json` is seeded by `/ds-init-project` and holds twenty-two methodology toggles (one, `qa_default_skip`, is reserved/inert). The file is committed alongside `qa.md` and `deploy.md` - it travels with the repo. If absent, every toggle uses its default and nothing breaks.

- `debugger_on_failure` - boolean, default `false`. Interposes a Debugger diagnosis step before each Phase 7 engineer fix pass on quality-gate failures (Elevated path only).
- `qa_default_skip` - reserved; no-op. Documented for schema completeness; does not alter QA-gate behavior.
- `model_profile` - enum (`default` | `budget`), default `"default"` (absent key resolves to `"default"`). `budget` routes eligible spawns to Tier 1 to reduce cost; never applies to security-auditor or mandated-Tier-3 Skeptics.
- `auto_merge_on_ci_green` - boolean, default `false`. When `true`, Phase 12 squash-merges the PR after CI passes, the PR is ready, and no reviewer has requested changes.
- `capability_preflight_mode` - enum (`advisory` | `blocking`), default `blocking`. Controls whether a missing required agent dependency warns-and-proceeds or halts the spawn.
- `perceptual_diff_enabled` - boolean, default `false`. Opt-in Playwright screenshot diff against committed baselines; raises auto-Major on drift.
- `theme_aware` - boolean, default `false`. Opt-in per-theme QA tuples; qa-engineer runs scenarios in both light and dark themes.
- `storybook_enabled` - boolean, default `false`. Opt-in targeting of the Storybook iframe for `visual_conformance` and `accessibility` scenarios.
- `motion_aware` - boolean, default `false`. Opt-in CDP reduced-motion checks per scenario; absent motion scenarios on UI-visible Elevated units become a Major finding.
- `storybook_version` - enum (`6` | `7`), default `7`. Selects the Storybook URL format for `story_id` scenarios; set automatically by `/ds-init-project`.
- `commit_telemetry` - boolean, default `true`. Commits the per-developer session log as a separate commit on the PR branch, enabling `ds-cost team` aggregation after pull.
- `knowledge_commit_on_pr` - boolean, default `true`. When `true`, `/ds-implement-ticket` Phase 11e commits any changed `MEMORY.md`, `decisions.md`, and `.agentic/learnings.md` onto the ticket's PR branch (checkout-free, via a temporary index plus `commit-tree`), so a session's durable knowledge ships with the work that produced it. Set to `false` as a kill switch: the phase pushes operator-authored markdown onto a branch whose checks have already passed, which re-runs CI at a point where no phase revisits a red result.
- `deferred_wrap_daemon` - boolean, default `false`. Opt-in out-of-session daemon that picks up deferred `/ds-wrap` jobs; tuned by the `deferred_wrap_*` related keys.
- `abdication_guard_enabled` - boolean; requires an explicit `true` to run (absent/malformed config = guard does not fire; the shipped template and `/ds-init-project` set it). Stop hook that detects conductor abdication - asking permission for a non-destructive next step, announcing a surface-and-proceed default and then not acting on it, or a co-equal ballot in a prose `## Operator decisions` block - and injects a directive.
- `skill_candidate_detection` - boolean, default `true`. Master toggle for the skill-candidate detector; when `true`, the Stop hook surfaces recurring friction patterns as skill candidates at session start.
- `skill_candidate_nudge` - boolean, default `false`. Layer-2 opt-in in-session nudge; fires when a domain crosses the candidate threshold during the current session (requires `skill_candidate_detection: true`).
- `ticket_driven` - enum (`off` | `offer` | `require`). Controls whether the conductor creates a tracker ticket before spawning the first implementer on net-new work. Absent-key resolution: effective `offer` when `TRACKER != none`, `off` when `TRACKER == none`.
- `rework_detection` - boolean, default `true`. Disables the Phase 9 ledger write, Phase 1 detection, the notice, the `/ds-ticket-triage` badge, and the escalation with a single flag.
- `pending_merge_sweep` - boolean, default `true`. Controls the session-start pending-merge sweep that pushes the dev-complete transition (`TRACKER_STATE_DEV_COMPLETE`, which defaults to the resolved `TRACKER_STATE_DONE` value) to the tracker once a ticket's PR merges; set `false` to disable.
- `tracker_state_diagnostic` - boolean, default `true`. Controls whether the tracker writeback subagent emits a live diagnostic naming currently-available states when a configured `TRACKER_STATE_*` name cannot be used; set `false` to disable.
- `turn_shape_guard_enabled` - boolean, default `true` (absent key resolves to on). Stop hook (`hooks/enforce-turn-shape.py`) checks the conductor's final turn against the fixed-shape/warranted-turn rule. As of DS-156 this is NOT uniformly advisory: `_execution_prose_flag` (a non-Answer turn's structural shape) is BLOCKING; `_answer_relevance_flag` (opening-preamble/closing-recap phrasing on an Answer turn) remains advisory-only and only logs, bounded by a two-layer loop guard (`stop_hook_active` silent-exit plus a per-`cwd` counter cap of 2, sharing machinery with the abdication guard via `hooks/lib/loop_guard.py`) on how many times it can re-invoke the model on consecutive non-conforming turns; kill-switch: `AE_TURN_SHAPE_GUARD_DISABLE=1`.
- `worktree_read_guard_exemptions` - list of strings, default `[]`. Each entry is a path prefix (relative to the primary checkout root) exempted from the worktree-isolation read guard; a worktree-isolated subagent's `Read` under an exempt prefix is allowed even though it reaches into the primary checkout. Read by `hooks/enforce-worktree-read.py`; kill-switch: `AE_WORKTREE_READ_GUARD_DISABLE=1`.

Full field reference including related tuning keys (`storybook_url`, `deferred_wrap_*`): see `content/rules/conventions.md` §Project Config.

## Adapters

The same methodology is packaged for multiple tools. Each adapter lives in its own directory with tool-specific formats:

| Tool            | Adapter      | Setup                                          |
| --------------- | ------------ | ---------------------------------------------- |
| Claude Code     | `.claude/`   | See [.claude/README.md](.claude/README.md)     |
| Cursor          | `.cursor/`   | See [.cursor/README.md](.cursor/README.md)     |
| Codex CLI       | `.codex/`    | See [.codex/README.md](.codex/README.md)       |
| Gemini CLI      | `.gemini/`   | See [.gemini/README.md](.gemini/README.md)     |
| Kimi Code CLI   | `.kimi/`     | See [.kimi/README.md](.kimi/README.md)         |
| OpenCode        | `.opencode/` | See [.opencode/README.md](.opencode/README.md) |
| Pi coding agent | `.pi/`       | See [.pi/README.md](.pi/README.md)             |
| Pi (oh-my-pi)   | `.omp/`      | See [.omp/README.md](.omp/README.md)           |
| Hermes Agent    | `.hermes/`   | See [.hermes/README.md](.hermes/README.md)     |
| OpenClaw        | `.openclaw/` | See [.openclaw/README.md](.openclaw/README.md) |
| VS Code Copilot | `.copilot/`  | See [.copilot/README.md](.copilot/README.md)   |

Codex installs exactly four native Codex skills: `dinostack`, `brief`, `wrap`, and `implement-ticket`. Invoke its workflow skills with `$brief`, `$wrap`, and `$implement-ticket`; bare `/ds-brief`, `/ds-wrap`, and `/ds-implement-ticket` are canonical source names, not Codex invocation syntax. The workflow sources remain `content/commands/ds-brief.md`, `content/commands/ds-wrap.md`, and `content/commands/ds-implement-ticket.md`. `.codex/build.sh` runs `scripts/codex-skills.py` to transform the reviewed sources, generate each skill's `SKILL.md` and `RESOURCE-MAP.json`, validate relative symlink/resource-map closure, and synchronize the exact output allowlist. The read-only Codex skill check rejects drift.

See [ADAPTERS.md](ADAPTERS.md) for how to create adapters for other tools.

## What's included

**Rules** (3 files) - the core methodology:

- Agent methodology - delegation, risk classification, task decomposition, worktree lifecycle
- Code standards - tool discipline, quality gates, package management, browser verification
- Conventions - writing style, project structure, session context, git workflow

**Reference docs** (37 files) - detailed protocol specs loaded on trigger:

- Skeptic protocol - adversarial review loop, findings classification, sign-off format
- Subagent protocol - parallel spawning, worktree isolation, task decomposition
- Agent team - roles, composed flows, decision rules, spawn requirements
- Design goals - system design principles and intent
- Role-model routing - Pi/oh-my-pi per-role model selection and antagonist reviewer diversity
- Model discovery - Pi/oh-my-pi harness probe and per-role ranking heuristics
- Multi-developer coordination - parallel sessions, branch and worktree hygiene
- Regression test obligation - when a fix requires a regression test and what counts
- Doc-sync obligation - when a reality-asserting change must update intent-layer docs in the same PR
- Cross-harness agent teams - `ds-team` CLI, team.yml schema, cross-harness dispatch and collection
- Evidence-on-disk - spill/sketch/rehydrate protocol for large worker tool outputs
- Learnings capture instruction - what counts as a learning, the in-flight `ds-learning-shard append` path for the four roles it belongs to (`engineer`, `adr-generator`, `product-discovery`, `release-orchestrator`), and the `learnings_candidate[]` digest field for the three roles whose return contract declares it

**Agents** (18) - named specialist roles:
adr-drift-detector, adr-generator, architect, debugger, dependency-auditor, engineer, goal-condition-evaluator, investigator, learning-extractor, learnings-agent, orchestration-planner, perf-analyst, product-discovery, qa-engineer, release-orchestrator, security-auditor, skeptic, wrap-ticket

**Commands** (25) - workflow shortcuts:
ds-config (interactive settings viewer/editor for methodology mode/profile/toggles), ds-configure-team (cross-harness team setup and verification), ds-cost (token / wall-time rollups from `.agentic/events.jsonl`; opt-in pricing via `~/.agentic/pricing.yml`), ds-disable, ds-help (static, zero-token command reference listing every slash command), ds-identity, ds-status, ds-brief, ds-cleanup-worktrees, ds-feedback-triage (triage captured session friction from `~/.agentic/feedback.jsonl` into tracker tickets), ds-implement-ticket, ds-init-project, ds-memory-update, ds-migrate-project, ds-prune-harness, ds-representation-audit, ds-skeptic, ds-skill-candidates (read-only view of the skill-candidate backlog), ds-test-suite-comprehension, ds-ticket-status-sync, ds-ticket-triage (plan-only cross-ticket triage: dependencies, conflicts, parallel lanes), ds-update (pull and reinstall dinostack from upstream, or fresh-install if not yet set up), ds-update-agentic-engineering, ds-wrap, ds-wrap-deferred (non-interactive single-pass session enrichment for the deferred-wrap daemon)

**Hooks / Plugins** - lifecycle event handlers for risk reminders and session context saving. Claude Code uses native hooks; OpenCode uses a plugin that writes session context when the session becomes idle.

**Project config / overview layer** - the committed `.agentic/config.json` holds twenty-two methodology toggles (one reserved/inert; full list in the [Project config](#project-config) section above). The operator-owned `docs/overview/{vision,requirements}.md` files capture durable product intent above the task level; Architect, Investigator, and Engineer read them when present and must not contradict them. Both are optional and graceful - if absent, defaults apply and nothing breaks.

## Identity and Telemetry

`ds-cost` reports token and wall-time rollups per developer. For those rollups to be meaningful, each developer needs a registered handle so session logs are attributed correctly.

### Registering a handle (global)

The quickest path derives your handle from your GitHub login:

```bash
ds-identity auto      # derives handle from `gh api user`, writes it provisional
ds-identity confirm   # strips the provisional flag and flushes buffered sessions
```

Or set a handle manually:

```bash
ds-identity init <handle>   # writes ~/.agentic/identity.yml directly as confirmed
```

Until you confirm, telemetry is buffered in `~/.agentic/session-log/.pending/` - no sessions are lost. Confirmation flushes only pending records matching the confirmed effective scope and retains nonmatching records. Matching records start writing attributed logs; nonmatching records remain buffered for their own scope.

The pending record's canonical `identity_scope` comes from the effective
provisional identity, not merely the active profile. Identity targets and
parent directories are opened without following symlinks; special,
multiply-linked, and wrong-owner identity files are rejected.

Run `ds-identity show --scope effective` at any time to see the identity
that wins for the current project and profile.

### Per-profile and per-project overrides

For separate harness tenants or config profiles, store the identity beside
that profile's configuration:

```bash
AGENTIC_CONFIG_DIR=~/.claude-client-a ds-identity auto --scope profile
AGENTIC_CONFIG_DIR=~/.claude-client-a ds-identity confirm --scope profile
```

Profile config-dir detection uses `AGENTIC_CONFIG_DIR`, then
`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, then `PI_CODING_AGENT_DIR`. You can instead pass
`--profile-dir <dir>`. Profile dirs must remain lexically under `$HOME` and
must not contain symlinked components.

If you use a different handle for specific repos, set a project-scoped identity from inside that repo:

```bash
ds-identity init <handle> --scope project   # writes <repo>/.agentic/identity.yml
ds-identity confirm --scope project          # confirm a provisional project identity
```

The project file is covered by the existing `.agentic/*` gitignore umbrella - it is per-developer and never committed. The global identity is unchanged.

### Precedence

When multiple identity files exist, confirmation wins before scope:

**project-confirmed > profile-confirmed > global-confirmed > project-provisional > profile-provisional > global-provisional > none**

A provisional project or profile file never suppresses a working confirmed
identity. To see which handle is active in the current repo and profile:

```bash
ds-identity show --scope effective
```

### ds-cost attribution

`ds-cost team` aggregates `.agentic/session-log/<dev>.jsonl` files for the current repo. A developer who uses two different handles across repos appears as two rows - this is expected. Session logs are local-only (per machine); there is no automatic cross-machine aggregation.

## Tracker config: `.agentic/tracker.yml`

A repo whose tracker cannot be declared in a tracked, universally-inherited `AGENTS.md` - doing so would bake one operator's workspace, project key, or account ID into a public file - can still resolve `TRACKER` at runtime via a project-local, gitignored overlay.

```bash
ds-tracker init --tracker jira --prefix DS --base-url https://acme.atlassian.net
ds-tracker resolve --json   # merge algorithm, deterministically testable
ds-tracker show --scope project
```

The overlay is merged field-by-field over the `AGENTS.md` `## Tracker` / `## Linear` resolution chain, with the overlay winning and every changed field disclosed. `ds-tracker` refuses to write the file at a path git would track - it refuses an unignored path (fix: add a `.gitignore` line), refuses an already-tracked path (fix: `git rm --cached`), and fails closed when it cannot tell. An absent, malformed, incomplete, or credential-bearing overlay never blocks - it degrades to the `AGENTS.md` result with an actionable reason. See [configuration-reference.md](docs/configuration-reference.md) for the full field reference.

## Repo structure

```
DinoStack/
  .claude/              Claude Code adapter (skill, agents, commands, install/uninstall)
  .codex/               Codex CLI adapter (AGENTS.md, four native skills, commands, install/uninstall)
  .cursor/              Cursor adapter (rules, commands, hooks, install/uninstall)
  .gemini/              Gemini CLI adapter (GEMINI.md, agents, commands, install/uninstall)
  .kimi/                Kimi Code CLI adapter (AGENTS.md, skill, commands, install/uninstall)
  .opencode/            OpenCode adapter (skill, agents, commands, install/uninstall)
  .pi/                  Pi coding agent adapter (skill, prompts, install/uninstall)
  .omp/                 Pi (oh-my-pi) adapter (skill, install/uninstall)
  .hermes/               Hermes Agent adapter (skill, METHODOLOGY.md, install/uninstall)
  .openclaw/            OpenClaw adapter (skill tree, METHODOLOGY.md, install/uninstall)
  .copilot/             VS Code Copilot adapter (build.sh, references, install/uninstall)
  hooks/                Shared hook scripts
  docs/                 Documentation and reference HTML
  ADAPTERS.md           Guide for creating new tool adapters
  CONTRIBUTING.md       How to contribute via pull requests
  README.md             This file
```

## Documentation

- `~/DinoStack/docs/index.html` - visual reference document describing the full system architecture
- `~/DinoStack/docs/slides/how-it-works-slides.html` - what DinoStack is and how it works
- `~/DinoStack/docs/slides/getting-started-slides.html` - install flow and the first focused session
- `~/DinoStack/docs/slides/context-management-slides.html` - why context hygiene is the real bottleneck
- `~/DinoStack/docs/slides/agent-team-slides.html` - the agent team and how they compose
- `~/DinoStack/docs/slides/quality-assurance-slides.html` - how the qa-engineer uses `.agentic/qa.md` (legacy `.claude/qa.md` fallback) as project QA memory
- `~/DinoStack/docs/slides/work-tracking-slides.html` - how the orchestration-planner tracks work in `.agentic/tasks.jsonl` / the per-ticket `.agentic/loop-state-<LOOP_KEY>.json` (legacy: `.agentic/loop-state.json`)
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

DinoStack is the product; `dinostack` is the package it ships. The `dinostack` name appears throughout the internals - the `~/.claude/agentic-engineering.json` config, the `agentic-engineering: opt-in` marker, the `.agentic/` directory, the `/agentic-*` commands - and stays stable so existing installs keep working.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.
