# DinoStack - Gemini CLI Adapter

## What this provides

- **GEMINI.md** - A small always-loaded stub pointing at the trigger-loaded `dinostack` skill (DS-184). It no longer carries the methodology body itself - see "Trigger-loaded methodology (DS-184)" below.
- **`dinostack` skill** - `.gemini/skills/dinostack/SKILL.md` - the full methodology body (agent methodology, code standards, conventions), trigger-loaded via Gemini CLI's `activate_skill` instead of loaded unconditionally in every session.
- **Reference docs** (5) - skeptic protocol, subagent protocol, agent team, design goals, regression test obligation
- **Global GEMINI.md** - `~/.gemini/GEMINI.md` symlinked to `.gemini/GEMINI.md` (the stub) for global session loading, when the skill link below resolves; otherwise written directly with the full body appended (see the degrade path below)
- **Global skill** - `~/.gemini/skills/dinostack/` symlinked to `.gemini/skills/dinostack/` for global session availability
- **Named agents** - `~/.gemini/agents/` symlinked to `.gemini/agents/` - 13 agent markdown files generated from `content/agents/*.md`
- **Slash commands** - `~/.gemini/commands/` symlinked to `.gemini/commands/` - TOML command files for `skeptic`, `implement-ticket`, `wrap`, and others
- **Lifecycle hooks** - `BeforeAgent` (risk reminder) and `SessionEnd` (context save) configured in `~/.gemini/settings.json`

## Prerequisites

- Gemini CLI installed and on your PATH (`gemini --version` should succeed)
- Node.js available (`node --version` should succeed) - required for the stop-context hook
- macOS or Linux (this adapter targets Unix-like systems; Windows support is untested)

## Installation

```bash
git clone https://github.com/Space-Dinosaurs/DinoStack.git ~/DinoStack
bash ~/DinoStack/.gemini/install.sh
```

This:
1. Runs `.gemini/build.sh` to ensure all artifacts are current
2. Symlinks `.gemini/skills/dinostack/` to `~/.gemini/skills/dinostack/` (the trigger-loaded methodology body)
3. Symlinks `.gemini/GEMINI.md` to `~/.gemini/GEMINI.md` when the skill link above resolved cleanly (a small always-loaded stub pointing at the skill); if it did not, writes `~/.gemini/GEMINI.md` directly with the full methodology body appended instead, so the session does not silently lose access to the methodology (see "Trigger-loaded methodology (DS-184)" below)
4. Symlinks `.gemini/commands/` to `~/.gemini/commands/` (TOML slash-command files)
5. Symlinks `.gemini/agents/` to `~/.gemini/agents/` (named agent markdown files)
6. Merges `BeforeAgent` and `SessionEnd` hook entries into `~/.gemini/settings.json`

If `~/.gemini/GEMINI.md` already exists and is not a symlink, the installer backs it up to `~/.gemini/GEMINI.md.backup-<timestamp>` before replacing it with the symlink, printing a loud warning - **unless** that file is our own prior degrade-path artifact (first line `<!-- dinostack:gemini-degrade-generated -->`), in which case it is replaced outright with no backup, since it is generated content, not user data. A symlink already occupying `~/.gemini/GEMINI.md` is classified the same way on BOTH the healthy and degrade paths: a symlink whose target matches the current install's stub (points at it directly, or is dangling with that exact target - e.g. after a repo move) is replaced with no backup; a symlink resolving to something else that still exists is genuinely foreign and left untouched with nothing written - **which means no methodology loads on this harness at all until you resolve the conflict manually and re-run install.sh**; a symlink that does not resolve (dangling) and does NOT point at the stub is of unknown provenance - it could be your own symlink to a file you since deleted - and is preserved via a `.backup-<timestamp>` move (not deleted outright) before the replacement is written. The uninstaller restores the most recent backup if one exists, and separately deletes a marker-carrying degrade-path GEMINI.md outright (also not user data). Same backup behavior applies to `~/.gemini/commands/` and `~/.gemini/agents/`. The skill symlink at `~/.gemini/skills/dinostack/` is the one exception: a pre-existing real file or directory there is left alone (not auto-backed-up) and the installer falls back to the degrade path above - resolve the conflict manually, then re-run install.sh.

## Post-install verification

After running the installer, verify the following:

1. **`dinostack` skill loads on trigger (DS-184):**
   Open Gemini CLI in any project, invoke the `dinostack` skill (or start any software development task and let it fire on trigger), then ask:
   > "What risk tiers does the DinoStack protocol define?"
   The answer should reference Trivial/Low/Elevated/Elevated+Cleanup. If it does not, check that `~/.gemini/skills/dinostack/` exists and is a valid symlink, and that the session accepted the per-session `activate_skill` consent prompt. Note: this is an operator-verified check, not one this repo's own CI or install script can certify - it depends on the live Gemini CLI harness actually injecting the skill body at invocation time.

2. **Slash commands available:**
   In a Gemini CLI session, run `/commands reload` then type `/ds-skeptic` - it should appear in autocomplete. If not, check that `~/.gemini/commands/` is a symlink to the repo's `.gemini/commands/` directory.

3. **Named agents available:**
   In a Gemini CLI session, type `@engineer` - Gemini should auto-complete and activate the engineer agent. Check `~/.gemini/agents/` if it does not.

## Uninstall

```bash
~/DinoStack/.gemini/uninstall.sh
```

This removes the four symlinks (`skills/dinostack/`, `GEMINI.md`, `commands/`, `agents/` - see `.gemini/uninstall.sh` for the definitive list), deletes a real (non-symlink) `~/.gemini/GEMINI.md` if it carries our own degrade-path marker, and surgically removes the `BeforeAgent` and `SessionEnd` hook entries from `~/.gemini/settings.json` without touching any other user settings. Backups are restored if present; a genuinely user-authored `GEMINI.md` (no marker) is left alone.

## How it works

### Trigger-loaded methodology (DS-184)

Gemini CLI supports project-local, trigger-loaded skills (`.gemini/skills/<name>/SKILL.md`), discovered at session start and invoked on demand via the `activate_skill` tool - see `docs/cli/skills.md` on the `google-gemini/gemini-cli` repo. DinoStack ships its methodology as one such skill, `.gemini/skills/dinostack/SKILL.md`, generated by `build.sh` from `content/sections/` (the assembled methodology body) plus `content/rules/code-standards.md` and `content/rules/conventions.md`.

This is the same problem DS-143 solved for Claude Code (moving the methodology body out of the always-imported root file into a trigger-loaded skill), applied to the Gemini adapter. Committing `.gemini/skills/dinostack/SKILL.md` into a repo is sufficient for a consumer project to use it - no global install is required for project-local use.

**GEMINI.md is now a small stub.** `.gemini/GEMINI.md` still loads unconditionally (project-scoped from the project root, or globally from `~/.gemini/GEMINI.md`), but it now only points at the `dinostack` skill rather than carrying the full methodology body. Invoke the skill (`activate_skill`) at the start of any software development work to load the full protocol.

**Skill discovery tiers.** Gemini CLI discovers skills in four tiers, lowest to highest precedence: built-in, extension, user (`~/.gemini/skills/` or the `~/.agents/skills/` alias), workspace (`.gemini/skills/` or the `.agents/skills/` alias, project-local). Workspace outranks user; within a tier, the `.agents/skills/` alias outranks `.gemini/skills/`.

**Per-session consent prompt.** The first time a session invokes `activate_skill` for a non-built-in skill, Gemini CLI shows a confirmation prompt naming the skill, its purpose, and the directory path it gains access to. This is a normal per-session UI interaction in an interactive Gemini CLI session, not an install-time prompt - `install.sh` never touches it.

**Known limitation - headless / non-interactive runs.** Gemini CLI's policy engine denies the `activate_skill` tool by default outside an interactive session: `packages/core/src/policy/policies/write.toml` defines an interactive rule (`activate_skill` -> `ask_user`, priority 10) and a separate non-interactive rule listing `activate_skill` among tools with `decision = "deny"`, priority 10. A plain non-interactive (`gemini -p ...` scripted) run is therefore **denied** the skill, not prompted for it - and since GEMINI.md no longer carries the full body either, a scripted run that neither invokes an override nor has a broken-skill-link degrade file installed gets **no route to the methodology at all**. This is a known, deliberate limitation of DS-184, not an oversight - DinoStack does not silently weaken your security posture to close it. Two documented overrides exist if you want headless access, both opt-in and both yours to enable:

1. `--approval-mode yolo` (or `--yolo`) - allows every tool, not scoped to `activate_skill` alone. `yolo.toml` allows `toolName = "*"` at priority 998.
2. A targeted allowlist: add `"activate_skill"` to `tools.allowed` in your own `~/.gemini/settings.json` - `docs/reference/configuration.md`: "**`tools.allowed`** (array): Tool names that bypass the confirmation dialog." (The `--allowed-tools` flag form is marked deprecated in favour of the Policy Engine.)

`install.sh` prints this same limitation and both override routes in its install summary. It never writes `activate_skill` into your `settings.tools.allowed` and never defaults you into `--approval-mode yolo` - that is a deliberate choice you make, not one made for you.

**Empirically verifying that the injection arrives intact in a fresh Gemini session is an operator task**, not something this adapter or its install script can self-certify.

### Named agents

Named agents are markdown files with YAML frontmatter that Gemini loads from `~/.gemini/agents/` (personal) or `.gemini/agents/` (project-scoped). Each file defines one agent (name, description, kind, tools, and a system prompt body).

The installer symlinks `~/.gemini/agents/` to `.gemini/agents/`, which contains generated markdown files. These files are generated by `build.sh` from `content/agents/*.md`. The transform adds `kind: local` and removes the `model` field so each agent inherits the session model (the same rationale as the Codex adapter - Anthropic model IDs are not valid in Gemini CLI).

Invoke agents via `@agent-name` (e.g., `@engineer`, `@architect`, `@skeptic`) or let Gemini auto-select based on description match.

### Slash commands

Gemini CLI supports custom slash commands via TOML files at `~/.gemini/commands/`. Each file has a `description` string and a `prompt` triple-quoted string. Commands are reloaded in-session via `/commands reload`.

The installer symlinks `~/.gemini/commands/` to `.gemini/commands/`, which contains TOML files generated by `build.sh` from `content/commands/*.md`. The `/dinostack` prerequisite blockquote that Claude Code prepends is NOT present here - it is Claude Code-specific and never appears in `content/` source files.

### Lifecycle hooks

Hooks are configured in `~/.gemini/settings.json` under the `hooks` key. Two hooks are wired:

| Hook event | Script | What it does |
|---|---|---|
| `BeforeAgent` (matcher: `"*"`) | `.gemini/hooks/risk-reminder.sh` | Emits the risk classification reminder as additional context before every prompt turn |
| `SessionEnd` (matcher: `"exit"`) | `.gemini/hooks/stop-context-gemini.js` | Writes a minimal `context.md` to `~/.gemini/projects/[hash]/` on session end |

**BeforeAgent** fires after a user submits a prompt but before the agent begins planning. The hook outputs structured JSON (`hookSpecificOutput.additionalContext`) which Gemini appends to the prompt for that turn.

**SessionEnd** fires on clean session termination (explicit `/exit` or graceful shutdown). Abrupt terminations (crashes, SIGKILL) do **not** trigger this hook. The context save is therefore **best-effort** and may be missed on unclean exits. For reliable context capture, use the `/ds-wrap` command before ending a session.

### Reference docs

Reference docs are available in `.gemini/references/` as hardlinks to `content/references/`.

## Build

The build script generates the `dinostack` skill (`.gemini/skills/dinostack/SKILL.md`), the `GEMINI.md` stub, command TOML files, agent markdown files, and hardlinks reference docs:

```bash
bash ~/DinoStack/.gemini/build.sh
```

Run after `git pull` to regenerate artifacts from updated source files. The pre-commit hook in this repo runs `.gemini/build.sh` automatically whenever `content/` files are staged.

## Repo-move constraint

The `BeforeAgent` and `SessionEnd` hook commands in `~/.gemini/settings.json` embed **absolute paths** to the hook scripts at install time:

```json
"command": "bash /path/to/DinoStack/.gemini/hooks/risk-reminder.sh"
```

If you move the repo after install, these paths become stale and hooks will silently fail. To fix, re-run `.gemini/install.sh` from the new repo location - it will update the embedded paths.

## Updating

Pull and re-run the installer - it is idempotent:

```bash
cd ~/DinoStack
git pull
bash .gemini/install.sh
```

For a clean refresh:

```bash
bash .gemini/uninstall.sh
git pull
bash .gemini/install.sh
```

## Coexistence with other adapters

This adapter is designed to run alongside Claude Code, Cursor, and Codex adapters without collision:

- **Config paths are disjoint:** Gemini uses `~/.gemini/`, Claude Code uses `~/.claude/`, Codex uses `~/.codex/`
- **Context files are disjoint:** Gemini writes to `~/.gemini/projects/[hash]/context.md`
- **Settings.json merge is surgical:** Install and uninstall add/remove only the specific hook entries this adapter manages; unrelated user settings are preserved
