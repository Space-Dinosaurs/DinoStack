# P0 Gemini Adapter - Design Plan

> Note: References to "agent-methodology.md" in this historical doc refer to what is now METHODOLOGY.md (assembled from content/sections/). See content/sections/README.md.

## Problem statement

The agentic-engineering repo ships adapters for Claude Code (`.claude/`), Cursor (`.cursor/`), and Codex CLI (`.codex/`). Google's Gemini CLI is absent. This is a concrete gap: OMC's multi-provider worker pool (`omc team N:provider`) treats Codex and Gemini as interchangeable worker backends. Without a Gemini adapter, this repo is Claude-plus-two rather than genuinely provider-agnostic, and any future parallel fan-out primitive built here cannot use Gemini workers without ad hoc configuration that lives outside the methodology.

The Gemini CLI is Google's open-source agentic coding assistant (released mid-2025, Apache 2.0). It reads a `GEMINI.md` context file and supports subagents, slash commands (called "tools" or "actions"), and hooks. It is a plausible second worker alongside Codex for long parallel jobs.

## Scope

This document designs the `.gemini/` adapter only.

Out of scope:
- The multi-provider parallel fan-out primitive (P1 - shared task-state file)
- The persistence loop (`/implement --until-green`) (separate P0 track)
- Changes to the methodology content itself (all content changes start in `content/`)
- Any Gemini-specific methodology rules (format changes only, substance unchanged)

## Existing adapter analysis

### Claude Code adapter (`.claude/`)

**Directory structure:**
- `.claude/build.sh` - generates command files (prepends prerequisite blockquote), creates hardlinks for references
- `.claude/install.sh` - creates per-file symlinks for agents and commands to `~/.claude/` (one `ln -s` per `.md` file, not a directory symlink); symlinks skill directory to `~/.claude/skills/agentic-engineering/`; injects hooks into `~/.claude/settings.json`; appends skill-loading block to `~/.claude/CLAUDE.md`; runs initial build
- `.claude/uninstall.sh` - removes symlinks
- `.claude/commands/*.md` - build artifacts (generated from `content/commands/` with prerequisite prepended)
- `.claude/skills/agentic-engineering/` - skill directory with `SKILL.md` and `references/` hardlinks
- `.claude/agents/` - the repo-side staging directory; individual agent `.md` files here are the sources for the per-file symlinks installed into `~/.claude/agents/`

**Install targets:**
- `~/.claude/agents/*.md` - per-file symlinks, one per agent `.md` file (not a directory symlink)
- `~/.claude/commands/*.md` - per-file symlinks, one per command `.md` file
- `~/.claude/skills/agentic-engineering/` - directory symlink to `.claude/skills/agentic-engineering/`
- `~/.claude/settings.json` - JSON merge for hooks
- `~/.claude/CLAUDE.md` - managed block append

**Hook mechanism:** JSON entries under `hooks.UserPromptSubmit` and `hooks.Stop` in `settings.json`. Commands are shell strings executed by the harness.

**Agent format:** Markdown files (`*.md`) with YAML frontmatter (`name`, `description`, `model`, `tools`). Loaded by Claude Code automatically from `~/.claude/agents/`.

**Commands transform:** `.claude/build.sh` prepends a prerequisite blockquote (`> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.`) to every command file. This is Claude Code-specific and does not appear in `content/commands/`.

### Codex adapter (`.codex/`)

**Directory structure:**
- `.codex/build.sh` - generates `AGENTS.md` (concatenates 3 rules files), generates `agents/*.toml` (from `content/agents/*.md`), hardlinks commands and references
- `.codex/install.sh` - symlinks skill, AGENTS.md, agents directory, and hooks.json to `~/.codex/`; adds `codex_hooks = true` to `~/.codex/config.toml`
- `.codex/AGENTS.md` - generated artifact (always-loaded global rules)
- `.codex/skill/SKILL.md` - static hand-authored file (trigger metadata + methodology summary for on-demand loading)
- `.codex/skill/references/` - symlink to `.codex/references/`
- `.codex/references/` - hardlinks to `content/references/`
- `.codex/commands/` - hardlinks from `content/commands/` (no transform - no prerequisite prepend)
- `.codex/agents/*.toml` - TOML agent files generated from `content/agents/*.md`
- `.codex/hooks.json` - hook config (UserPromptSubmit + Stop)
- `.codex/hooks/risk-reminder.sh` - echoes risk reminder to stdout (injected as developer context)
- `.codex/hooks/stop-context-codex.js` - writes session context to `~/.codex/projects/[hash]/context.md`

**Install targets:**
- `~/.agents/skills/agentic-engineering/` - directory symlink to `.codex/skill/`
- `~/.codex/AGENTS.md` - symlink to `.codex/AGENTS.md`
- `~/.codex/agents/` - directory symlink to `.codex/agents/`
- `~/.codex/hooks.json` - symlink to `.codex/hooks.json`
- `~/.codex/config.toml` - `codex_hooks = true` injected under `[features]`

**Agent format:** TOML files with `name`, `description`, `developer_instructions` fields. Generated by `build.sh`; `model` field intentionally omitted so agents inherit the session model.

**Always-loaded rules:** `AGENTS.md` at project root (or `~/.codex/AGENTS.md` globally) - Codex reads this automatically.

**Commands transform:** `.codex/build.sh` hardlinks `content/commands/*.md` to `.codex/commands/` with no transform. The prerequisite blockquote is Claude Code-specific and never appears in `content/` - Codex commands are used as-is.

**Hooks realpath-through-symlink pattern:** `~/.codex/hooks.json` is a symlink into the repo. Hook commands use `$(dirname "$(realpath "$HOME/.codex/hooks.json")")` to resolve the symlink back to the repo's `.codex/` directory, then navigate to `hooks/risk-reminder.sh` or `hooks/stop-context-codex.js`. This pattern lets hook script paths stay valid regardless of where the repo is cloned, because the path is computed at hook invocation time by following the symlink. The Gemini adapter must replicate this pattern if it uses a symlinked hooks config file.

### Key structural insight

Both adapters follow the same pattern:
1. A **build step** transforms `content/` into tool-native formats
2. An **install step** symlinks build artifacts to `~/.{tool}/` paths
3. An **always-loaded rules file** injects the methodology globally
4. **On-demand skill/reference docs** load when triggered
5. **Lifecycle hooks** fire risk reminder before each prompt and save context on stop
6. **Named agents** define specialist roles in tool-native format

The Gemini adapter must follow this same five-part shape.

### What ADAPTERS.md already answers

`ADAPTERS.md` contains a concept-mapping table and implementation checklist covering the core research needed:

- **Commands:** The checklist explicitly says to remove the `/agentic-engineering` prerequisite line when adapting commands for non-Claude tools (it is Claude Code-specific). The Gemini adapter follows the Codex pattern: hardlink `content/commands/*.md` with no transform, no prerequisite prepend.
- **Rules delivery:** Both "always-load" and "conditional/on-demand" mechanisms are identified as required, with the tool-native mechanism left as the open research question.
- **Hook scripts:** The checklist confirms hook scripts are shared from `hooks/` at the repo root.
- **Agent definitions:** The checklist identifies agent format as tool-specific and requires research.

The remaining unknowns (exact JSON schema for Gemini hooks, named agent file format, extension directory path) require reading Gemini CLI documentation or source - they are not answerable from this repo alone.

## Gemini CLI conventions (known vs unknown)

### Known (from public documentation and CLI source, as of April 2026)

**Configuration file:** Gemini CLI reads `GEMINI.md` at the project root and `~/.gemini/GEMINI.md` globally. This is directly parallel to Codex's `AGENTS.md` / `~/.codex/AGENTS.md`. It is plain markdown - no special frontmatter required for always-loading.

**Config directory:** `~/.gemini/` for user-scope configuration.

**Settings file:** `~/.gemini/settings.json` - JSON file for tool configuration.

**Hooks:** Configured via the `hooks` key in `~/.gemini/settings.json`. Event names are `SessionStart`, `BeforeAgent`, `BeforeToolSelection`, `BeforeTool`, `AfterModel`, `AfterAgent`, and `SessionEnd`. `BeforeAgent` fires after a user submits a prompt, before the agent begins planning; input field is `prompt` (the original user text); output field is `hookSpecificOutput.additionalContext` (text appended to the prompt for that turn only) - this is the correct event for per-prompt risk reminders. `SessionEnd` fires on session end. Both semantics differ from Claude Code's `UserPromptSubmit` / `Stop` in name but are functionally equivalent for this adapter's purposes.

**Slash commands:** Gemini CLI supports custom slash commands via TOML files at `~/.gemini/commands/` (user) or `.gemini/commands/` (project). Each TOML file has a `description` string and a `prompt` triple-quoted string. `{{args}}` interpolates invocation arguments; `@{path}` injects file contents. Commands are reloaded via `/commands reload`.

**Named agents:** Gemini CLI supports subagents via the `/agents` slash command. Files live at `~/.gemini/agents/*.md` (user) or `.gemini/agents/*.md` (project) in markdown with YAML frontmatter (required fields: `name`, `description`; optional: `kind: local`, `tools`, `model`, `temperature`, `max_turns`). The body is the system prompt. Invocation: `@agent-name` prefix or auto-selection based on description match.

### Open questions - now resolved

The prior "Unknown / requires research" questions (Q1 named agent format, Q2 hooks schema, Q3 extensions path, Q4 stop hook support) are resolved. See the "Open questions (resolved 2026-04-15)" section at the bottom of this document. Only Q5 (global config dir cross-platform) and Q7 (non-interactive worker invocation) remain open - both are non-blocking for this P0 adapter.

## Proposed `.gemini/` directory structure

```
.gemini/
  build.sh              Build script: generates GEMINI.md, generates TOML commands, hardlinks
                        references, generates agent definition files in Gemini-native format
  install.sh            Install script: symlinks build artifacts to ~/.gemini/
  uninstall.sh          Uninstall script: removes symlinks and reverts config changes
  README.md             Setup instructions for Gemini CLI users
  GEMINI.md             Generated always-loaded rules file (parallel to .codex/AGENTS.md)
  commands/             Generated TOML slash-command files (one per content/commands/*.md)
  references/           Hardlinks to content/references/
  agents/               Generated markdown+frontmatter agent files (from content/agents/*.md)
  hooks/
    risk-reminder.sh    Echoes risk classification reminder (parallel to .codex/hooks/risk-reminder.sh)
    stop-context-gemini.js  Writes session context on stop (parallel to .codex/hooks/stop-context-codex.js)
```

**File roles:**

- `GEMINI.md` - generated artifact concatenating the 3 rules files from `content/rules/` with a header and footer. Parallel to `.codex/AGENTS.md`. Loaded globally by Gemini CLI from `~/.gemini/GEMINI.md` (symlinked by install.sh).
- `commands/` - generated TOML files, one per `content/commands/*.md`. Format: `description` string and `prompt` triple-quoted string. Symlinked to `~/.gemini/commands/` by install.sh. Does not follow the Codex hardlink pattern because Gemini requires TOML, not markdown.
- `references/` - hardlinks to `content/references/`. Parallel to `.codex/references/`.
- `agents/` - generated markdown+frontmatter agent files, one per `content/agents/*.md`. Build transform adds `kind: local` and removes `model` (inherit session default). Symlinked to `~/.gemini/agents/` by install.sh.
- `hooks/risk-reminder.sh` - identical in logic to `.codex/hooks/risk-reminder.sh`. Outputs risk reminder to stdout.
- `hooks/stop-context-gemini.js` - writes minimal session context to `~/.gemini/projects/[hash]/context.md`.

## build.sh design

The Gemini `build.sh` mirrors `.codex/build.sh` in structure. Steps:

### 1. Generate `GEMINI.md`

Concatenate `content/rules/agent-methodology.md`, `content/rules/code-standards.md`, and `content/rules/conventions.md` with a header and protocol reference footer.

Header text:
```
# Agentic Engineering Protocol

This file loads the agentic engineering methodology into every Gemini CLI session in this repository.

**Note:** This file is auto-generated by `.gemini/build.sh` from `content/rules/`. Do not edit it directly.

For detailed protocol specs, see reference docs in `.gemini/references/` or `~/.gemini/references/` (if installed globally).

---
```

Footer text (identical in structure to Codex footer, with Gemini-adapted paths):
```
---

## Protocol Reference

For detailed protocol specs, see the reference docs:

- `skeptic-protocol.md`
- `subagent-protocol.md`
- `agent-team.md`
- `design-goals.md`

These live in `.gemini/references/` (local copies in this repo) or `~/.gemini/references/` after install.
```

### 2. Hardlink `references/`

Same logic as `.codex/build.sh`: hardlink each `content/references/*.md` to `.gemini/references/`, using the portable inode helper for macOS/Linux compat.

### 3. Generate `commands/` (TOML slash-command files)

For each `content/commands/*.md`, generate a Gemini TOML command file in `.gemini/commands/<name>.toml`. The build step reads the markdown source, extracts a one-line description (first non-empty line of the body, or a mapped value), and writes:

```toml
description = "<extracted description>"

prompt = """
<full markdown body of the command>
"""
```

`{{args}}` and `@{file-path}` are Gemini's interpolation primitives and may be used inside the prompt string for future command enhancements. The initial build wraps the existing command body verbatim without adding interpolation markers.

**Note:** If the command body contains any `"""` sequences, the build script must escape them before writing into the TOML triple-quoted string. This is unlikely given the methodology docs, but flag it as a verification item.

### 4. Generate `agents/`

Generate one `.gemini/agents/<name>.md` file per `content/agents/<name>.md`. The transform:

1. Reads the source file's YAML frontmatter.
2. Adds `kind: local` if not already present.
3. Removes the `model` field (agents inherit the session default model, matching the Codex pattern).
4. Preserves all other frontmatter fields (`name`, `description`, `tools`, `temperature`, `max_turns`, etc.) and the body unchanged.
5. Writes the result to `.gemini/agents/<name>.md`.

**Verification note:** If Gemini rejects unknown frontmatter fields (e.g., fields that are not in its supported set), the build script may need to whitelist only the fields Gemini accepts. Flag as a verification item in the Verification plan.

### 5. Stale file cleanup

Remove stale generated files from previous builds that no longer have a source file in `content/` - same pattern as Codex's TOML stale-file cleanup loop.

## install.sh design

The Gemini adapter ships its own `install.sh` at `.gemini/install.sh`. There is no root-level `install.sh` (the repo uses per-adapter install scripts).

### `.gemini/install.sh` steps

1. Run `.gemini/build.sh` to ensure artifacts are current.

2. **Symlink `~/.gemini/GEMINI.md`** to `.gemini/GEMINI.md`. Back up any existing non-symlink file (same backup pattern as Codex installer for `~/.codex/AGENTS.md`).

3. **Symlink `~/.gemini/commands/`** to `.gemini/commands/`. Back up any existing non-symlink directory at that path (same backup pattern as the Codex installer).

4. **Symlink `~/.gemini/agents/`** to `.gemini/agents/`. Back up any existing non-symlink directory at that path (same backup pattern as the Codex installer).

5. **Configure hooks in `~/.gemini/settings.json`:** Use the same Python JSON-merge pattern as `.claude/install.sh`. The install script computes the absolute path to the hooks directory at install time:

```bash
GEMINI_HOOKS_DIR="$(cd "$(dirname "$0")" && pwd)/hooks"
```

This absolute path is substituted into the hook command strings before the JSON merge is written. Using absolute paths is required because hook commands run in an arbitrary working directory (the user's project dir, not the agentic-engineering repo root) - CWD-relative paths like `bash .gemini/hooks/risk-reminder.sh` silently fail with "no such file or directory" in that context.

Merge the following structure into `~/.gemini/settings.json` under the `hooks` key, using `BeforeAgent` and `SessionEnd` event keys (NOT `UserPromptSubmit` / `Stop` - those are Claude Code events). The placeholder `<ABSOLUTE_PATH_TO_HOOKS>` must be replaced with the value of `$GEMINI_HOOKS_DIR` computed above:

```json
{
  "hooks": {
    "BeforeAgent": [
      {
        "matcher": "*",
        "hooks": [
          {
            "name": "risk-reminder",
            "type": "command",
            "command": "bash <ABSOLUTE_PATH_TO_HOOKS>/risk-reminder.sh"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "exit",
        "hooks": [
          {
            "name": "stop-context",
            "type": "command",
            "command": "node <ABSOLUTE_PATH_TO_HOOKS>/stop-context-gemini.js"
          }
        ]
      }
    ]
  }
}
```

Each hook entry has: `type` (required, currently only `"command"`), `command` (required, shell string), optional `name`, optional `timeout` (ms, default 60000). The outer entry has `matcher` (regex or exact string) and optional `sequential` (bool).

**Note:** `SessionEnd` matcher `"exit"` fires on clean session termination only (explicit `/exit` or graceful shutdown). Abrupt terminations (crashes, SIGKILL) do not trigger the hook. The stop-context save is best-effort and may be missed on unclean exits - same limitation as Claude's `Stop` hook.

**Post-install constraint:** The absolute paths embedded in `~/.gemini/settings.json` point to the repo location at install time. If the repo is moved after install, `.gemini/install.sh` must be re-run to update the embedded paths. This is the same constraint as the Codex adapter (the realpath-through-symlink trick also resolves against the repo path at invocation time). Document this constraint in `.gemini/README.md`.

**Gemini-specific adaptation - risk-reminder.sh output format:** The Codex `risk-reminder.sh` writes a plain-text risk reminder to stdout which Codex injects as developer context. Gemini's `BeforeAgent` hook uses a different mechanism: to inject context into the prompt the hook script must write JSON to stdout with the structure `{"hookSpecificOutput": {"additionalContext": "<reminder text>"}}`. Plain stdout text is not automatically appended to the prompt in Gemini. The engineer implementing `hooks/risk-reminder.sh` must output this JSON structure rather than plain text. This is a Gemini-specific adaptation from the Codex pattern.

6. **Summary output:** Print what was installed and where, matching the style of the Codex installer.

### No changes to `.claude/install.sh`

Each adapter's `install.sh` runs its own build as step 1. `.claude/install.sh` runs only `.claude/build.sh` and `.cursor/build.sh` - it does not run `.codex/build.sh`, and it should not run `.gemini/build.sh`. The Gemini build is triggered by `.gemini/install.sh` step 1 above. This is the established per-adapter pattern.

### Changes to `hooks/pre-commit` (required)

`hooks/pre-commit` runs all adapter builds whenever `content/` files are staged and re-stages the generated outputs. Currently it runs:

```bash
bash "$REPO_DIR/.claude/build.sh"
bash "$REPO_DIR/.cursor/build.sh"
bash "$REPO_DIR/.codex/build.sh"
```

And stages:
```bash
git add \
  "$REPO_DIR/.claude/commands/"*.md \
  "$REPO_DIR/.cursor/rules/"*.mdc \
  "$REPO_DIR/.cursor/rules/references/"*.md \
  "$REPO_DIR/.cursor/commands/"*.md \
  "$REPO_DIR/.codex/AGENTS.md" \
  "$REPO_DIR/.codex/references/"*.md \
  "$REPO_DIR/.codex/commands/"*.md
```

The Gemini adapter requires adding `.gemini/build.sh` to the build list and `.gemini/` outputs to the staging list:

```bash
bash "$REPO_DIR/.gemini/build.sh"
```

```bash
git add \
  ... \
  "$REPO_DIR/.gemini/GEMINI.md" \
  "$REPO_DIR/.gemini/references/"*.md \
  "$REPO_DIR/.gemini/commands/"*.toml
```

This is a required implementation step - the pre-commit hook is the enforcement mechanism that keeps all adapter outputs in sync with `content/` on every commit. Omitting `.gemini/` means Gemini adapter files can silently fall out of sync with `content/` after any rules or command change.

### README.md adapter table

`README.md` at repo root lists adapters in a table (lines 75-79). Add a Gemini row:

```markdown
| Gemini CLI | `.gemini/` | See [.gemini/README.md](.gemini/README.md) |
```

## content/ changes required (if any)

**No content changes are required.** The Gemini adapter is a format translation of existing `content/` files - same substance, different delivery format. This is consistent with the ADAPTERS.md principle: "Adapters translate format, not substance."

Potential future content addition (not part of this P0 adapter):
- A `content/references/gemini-adapter.md` reference doc if Gemini-specific limitations or workarounds accumulate enough to warrant documentation. Not needed for the initial adapter.

## Docs and slides

- **`docs/agentic-engineering.html`** - UPDATE REQUIRED. Add Gemini to the supported adapters list alongside Claude Code, Cursor, and Codex. The hub page currently shows three adapters; a fourth should be reflected.
- **`docs/slides/how-it-works-slides.md`** - UPDATE REQUIRED. Any slide showing the adapter list or provider logos should be updated to include Gemini as a fourth provider.
- **`docs/slides/getting-started-slides.md`** - REVIEW. If this deck mentions specific adapters or install commands, add a Gemini install option (`.gemini/install.sh`).
- **New deck:** No new deck warranted for an adapter addition alone. If the multi-provider worker pool feature (P1) ships later, a "multi-provider orchestration" deck would be the right vehicle - not this P0 adapter.

## Verification plan

After running `.gemini/install.sh`:

1. **Build artifacts exist:**
   - `ls .gemini/GEMINI.md` - file must exist and be non-empty
   - `ls .gemini/commands/` - should contain one `.toml` file per `content/commands/*.md`
   - `ls .gemini/references/` - should contain the same files as `content/references/`
   - `ls .gemini/agents/` - should contain one `.md` file per `content/agents/*.md`

2. **Hardlinks are valid (references):**
   - Run `stat -f %i content/references/skeptic-protocol.md .gemini/references/skeptic-protocol.md` - inode numbers must match

3. **Symlinks are correct:**
   - `readlink ~/.gemini/GEMINI.md` - must point to the repo's `.gemini/GEMINI.md`
   - `readlink ~/.gemini/commands/` - must point to the repo's `.gemini/commands/`
   - `readlink ~/.gemini/agents/` - must point to the repo's `.gemini/agents/`

4. **GEMINI.md content:**
   - Open `.gemini/GEMINI.md` and verify it contains sections from all 3 rules files
   - Confirm it contains the "Protocol Reference" footer

5. **Hook scripts are executable:**
   - `bash .gemini/hooks/risk-reminder.sh` - should print the risk reminder text to stdout with exit 0

6. **Commands directory check:**
   - `ls ~/.gemini/commands/*.toml` - should list one TOML file per `content/commands/*.md`
   - Open one file (e.g., `skeptic.toml`) and verify the `description` and `prompt` fields are populated

7. **Agents directory check:**
   - `ls ~/.gemini/agents/*.md` - should list one markdown file per `content/agents/*.md`
   - Open one file (e.g., `engineer.md`) and verify the frontmatter contains `kind: local` and does NOT contain a `model` field

8. **Commands reload test:**
   - After `/commands reload` in a Gemini CLI session, verify the installed commands appear in the slash-command autocomplete

9. **Gemini CLI loads context (manual verification):**
   - Open Gemini CLI in a project directory
   - Ask "What risk tiers does the agentic engineering protocol define?" - answer should reference Trivial/Low/Elevated/Elevated+Cleanup
   - This confirms `~/.gemini/GEMINI.md` is loading globally
   - Spawn a named agent via `@engineer <prompt>` and confirm Gemini discovers and activates the agent - this confirms `~/.gemini/agents/` is being read

10. **Idempotency:**
    - Run `.gemini/install.sh` twice - second run should print "already linked" for all targets, not re-create or fail

## Open questions (resolved 2026-04-15)

**Q1 - Gemini named agent format:** RESOLVED. Gemini CLI natively supports subagents via `/agents` slash command. Files live at `~/.gemini/agents/*.md` (user) or `.gemini/agents/*.md` (project). Format is markdown with YAML frontmatter: required fields `name`, `description`; optional `kind` (use `local`), `tools`, `model`, `temperature`, `max_turns`. Body is the system prompt. Invocation: `@agent-name` prefix or auto-selection based on description match. The adapter generates these files per the build.sh Step 4 above.

**Q2 - Hook schema:** RESOLVED. Gemini hooks live in `~/.gemini/settings.json` under the `hooks` key. Event names are `SessionStart`, `BeforeAgent`, `BeforeToolSelection`, `BeforeTool`, `AfterModel`, `AfterAgent`, `SessionEnd` (NOT `UserPromptSubmit` / `Stop` - those are Claude Code events). Mapping: `BeforeAgent` with matcher `"*"` for risk reminder; `SessionEnd` with matcher `"exit"` for stop context. Full schema is in the install.sh Step 5 JSON block above.

Citation for `BeforeAgent` semantic (Gemini CLI hooks reference, docs/hooks/reference.md): "BeforeAgent Hook: Fires after a user submits a prompt, but before the agent begins planning. Used for prompt validation or injecting dynamic context. Input Fields: prompt (string) - The original text submitted by the user. Output: hookSpecificOutput.additionalContext (string) - Text that is appended to the prompt for this turn only." This confirms `BeforeAgent` is the per-prompt equivalent of Claude Code's `UserPromptSubmit` and the mapping in this plan is correct.

**Q3 - User-scope commands path:** RESOLVED. Path is `~/.gemini/commands/` (not `~/.gemini/extensions/`). Format is TOML with `description` and `prompt` fields. Commands are reloaded via `/commands reload`. Full format documented in build.sh Step 3 above.

**Q4 - Stop hook support:** RESOLVED (side effect of Q2 research). Gemini supports `SessionEnd` with matcher `"exit"` which is functionally equivalent to Claude's `Stop` hook. Implement `hooks/stop-context-gemini.js` and wire it in the install script as documented in install.sh Step 5 above. Note: `SessionEnd` with matcher `"exit"` fires on clean session termination only (explicit `/exit` command or graceful shutdown). Abrupt terminations (crashes, SIGKILL, SIGTERM) do not trigger the hook. The stop-context save is therefore best-effort and may be missed on unclean exits - the same limitation as Claude's `Stop` hook.

**Q5 - Global config directory:** Still open (platform-dependent verification). `~/.gemini/` is the confirmed macOS/Linux path from context7 docs. Windows may use `%USERPROFILE%\.gemini\` but this adapter targets macOS/Linux like the Codex adapter. Re-classified as non-blocking.

**Q7 - Non-interactive worker invocation:** Still open. Out of scope for this P0 adapter. P1 (parallel fan-out) research needs to answer this before Gemini workers can be spawned headlessly.
