# VS Code Copilot Adapter

The `.copilot/` adapter makes the agentic engineering methodology available in
VS Code Copilot. It generates workspace-scoped artifacts under `.github/` that
Copilot loads automatically, and registers hooks that inject context at session
start and before each tool call.

## How it differs from .claude/

| Aspect | Claude Code (.claude/) | VS Code Copilot (.copilot/) |
|---|---|---|
| Methodology file | `.claude/skills/dinostack/SKILL.md` trigger-loaded via the `/dinostack` skill | `.github/skills/dinostack/SKILL.md` trigger-loaded via Copilot's Agent Skills primitive; `.github/copilot-instructions.md` is a resident stub pointer only |
| Agent picker | `Task` tool spawns subagents | Agent files in `.github/agents/` surfaced in chat UI |
| Commands | `/command` slash-commands | Prompt files in `.github/prompts/` |
| Hooks config | `settings.json` in `.claude/` | VS Code `chat.hookFilesLocations` setting |
| Identity config | `~/.claude/agentic-engineering.json` | Shared `~/.claude/agentic-engineering.json` |

## Prerequisites

- VS Code with GitHub Copilot extension installed and signed in
- VS Code Copilot hooks Preview feature enabled (see Settings > Extensions > Copilot)
- Node.js on PATH (required for the Stop context hook)
- Python 3 on PATH (required for `build.sh` and `install.sh`)

## Install

```bash
bash .copilot/install.sh
```

Flags:

| Flag | Effect |
|---|---|
| `--mode=opt-in` | Methodology active only when project's AGENTS.md opts in |
| `--mode=opt-out` | Methodology active everywhere unless AGENTS.md opts out (default) |
| `--profile=relaxed\|default\|strict` | Set risk classification profile |
| `--identity=<handle>` | Set developer identity handle |
| `--no-identity` | Skip identity setup |

After install, add the following line to your VS Code `settings.json`
(File > Preferences > Open User Settings (JSON)):

```json
"github.copilot.chat.hookFilesLocations": ["/absolute/path/to/DinoStack/.github/hooks"]
```

The install script prints the exact path for your machine.

## VS Code settings.json hooks snippet

```json
{
  "github.copilot.chat.hookFilesLocations": [
    "/path/to/DinoStack/.github/hooks"
  ]
}
```

Replace `/path/to/DinoStack` with the absolute path to this repo. Re-run
`bash .copilot/install.sh` if you move the repo - hook paths are absolute.

## Generated artifacts

| Artifact | Copilot mechanism | Source |
|---|---|---|
| `.github/copilot-instructions.md` | Auto-loaded stub for every chat session (pointer to the skill below) | `content/rules/` |
| `.github/skills/dinostack/SKILL.md` | Trigger-loaded methodology body - Copilot's native Agent Skills primitive, description-matched and injected only when relevant (DS-186) | `content/rules/` + `scripts/build-methodology.sh` |
| `.github/agents/*.md` | Agent picker in Copilot chat (`@agent-name`) | One per `content/agents/*.md` |
| `.github/prompts/*.prompt.md` | Slash-prompts in Copilot chat (`/prompt-name`) | One per `content/commands/*.md` |
| `.github/instructions/content-engineering.instructions.md` | Auto-loaded for `content/**` files | `content/rules/` (concise extract) |
| `.github/hooks/risk-reminder-copilot.sh` | PreToolUse hook - injects risk reminder | `.copilot/hooks/` |
| `.github/hooks/session-start-copilot.sh` | SessionStart hook - loads session context | `.copilot/hooks/` |
| `.github/hooks/stop-context-copilot.js` | Stop hook - saves session context | `.copilot/hooks/` |
| `.copilot/references/*.md` | Hardlinks for repo browsing (not Copilot-loaded) | `content/references/` |

All `.github/` files are committed and rebuilt deterministically by `build.sh`.
Never edit them directly - edit sources under `content/` instead.

## Skill trigger loading and Copilot code review

`.github/skills/dinostack/SKILL.md` is description-matched: Copilot decides
whether to load it based on the prompt and the skill's `description`
frontmatter field, and injects the file verbatim into context only when it
judges the skill relevant - it is not always resident. This applies uniformly
across Copilot chat, agent mode, the CLI, the app, and Copilot code review;
code review does not use a narrower, name-based trigger condition. The one
thing a `code-review`-named skill directory guarantees is pickup by code
review specifically - it does not change how any other surface decides
relevance, and this repo does not use that naming convention (the skill is
named `dinostack` for parity with the other adapters).

## Agent picker usage

After install, type `@` in the Copilot chat input to see available agents:

- `@engineer` - implement a scoped task
- `@architect` - design a solution
- `@skeptic` - adversarial code review
- `@investigator` - codebase exploration
- `@debugger` - root cause analysis
- `@orchestration-planner` - decompose multi-unit work
- `@qa-engineer` - functional QA verification

See `.github/agents/` for the full list.

## Slash-prompt usage

Type `/` in the Copilot chat input to see available prompts. Key prompts:

- `/ds-implement-ticket` - full orchestrated ticket implementation
- `/ds-skeptic` - run adversarial review on a diff
- `/ds-brief` - open a planning brief session
- `/ds-wrap` - summarize and save session context
- `/ds-init-project` - scaffold a new project

See `.github/prompts/` for the full list.

## Hooks preview warning

The hooks feature (`chat.hookFilesLocations`) is a Preview feature in VS Code
Copilot. It may change in future releases. If hooks stop working after a VS Code
update, check the Copilot release notes for the updated setting name or format.

## Shared activation config

The install script writes activation mode and profile to
`~/.claude/agentic-engineering.json`. This file is shared across all adapters
(Claude Code, Gemini CLI, Codex, Copilot). Changing it with one adapter's
install script affects all adapters.

## Rebuild

To regenerate `.github/` output without reinstalling:

```bash
bash .copilot/build.sh
```

## Uninstall

```bash
bash .copilot/uninstall.sh
```

This removes the `~/.copilot/agents` and `~/.copilot/prompts` symlinks.
Remember to also remove the `chat.hookFilesLocations` entry from your VS Code
`settings.json` (the uninstall script prints the exact line to remove).

## Known limitations

- No guaranteed instruction ordering: VS Code Copilot does not specify the order
  in which `copilot-instructions.md` and `*.instructions.md` files are concatenated.
  In practice the workspace root file loads first, but this is not guaranteed.
- UserPromptSubmit hooks are receive-only: Copilot does not allow
  UserPromptSubmit hooks to modify the prompt text. They can only inject
  `additionalContext` into the model's system context.
- Hook cwd in multi-root workspaces: when using a VS Code multi-root workspace,
  the `cwd` field in the hook JSON payload may refer to the workspace file
  directory rather than the active editor's project root. The session-start and
  stop hooks use this `cwd` to locate `.agentic/context.md` - verify the path
  is correct if context is not loading.
- Absolute paths embedded at build time: hook scripts receive their paths when
  `.copilot/build.sh` runs. If you move the repository, re-run
  `bash .copilot/install.sh` to update the `chat.hookFilesLocations` setting.
