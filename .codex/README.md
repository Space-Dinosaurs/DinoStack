# DinoStack Codex adapter

The Codex adapter installs DinoStack's global methodology, named agents,
lifecycle hooks, and exactly four native Codex skills.

## Native skills

`.codex/skills/` is generated and contains only:

| Skill | Source and purpose |
|---|---|
| `dinostack` | Core engineering methodology generated from `content/SKILL.md` and the assembled methodology. |
| `brief` | Native `$brief` workflow generated from `content/commands/ds-brief.md`. |
| `wrap` | Native `$wrap` workflow generated from `content/commands/ds-wrap.md`. |
| `implement-ticket` | Native `$implement-ticket` workflow generated from `content/commands/ds-implement-ticket.md`. |

Each directory has a generated `SKILL.md`, `RESOURCE-MAP.json`, and
`.dinostack-skill.json`. The core skill also has generated `METHODOLOGY.md` and
relative resource symlinks to repository-owned rules, commands, agents,
references, sections, scripts, hooks, binaries, and project templates. The
three workflow skills link their `resources` entry to the core skill instead
of duplicating those resources.

`scripts/codex-skills.py` performs the deterministic transformation.
`.codex/skill-compatibility.yml` is the reviewed occurrence inventory, and
`.codex/skill-frontmatter/*.yml` supplies the four frontmatter blocks. Generated
skill files must not be edited by hand.

## Installation

```bash
git clone https://github.com/Space-Dinosaurs/DinoStack.git ~/DinoStack
bash ~/DinoStack/.codex/install.sh
```

The installer runs `.codex/build.sh`, then creates these user-scope skill
symlinks:

```text
~/.agents/skills/dinostack -> <checkout>/.codex/skills/dinostack
~/.agents/skills/brief               -> <checkout>/.codex/skills/brief
~/.agents/skills/wrap                -> <checkout>/.codex/skills/wrap
~/.agents/skills/implement-ticket    -> <checkout>/.codex/skills/implement-ticket
```

It does not overwrite a real file/directory or a symlink owned by another
installation. Reinstalling is idempotent, refreshes checkout-owned links, and
migrates the former single core-skill link when present. Old checkout-owned
links under the Codex config directory are removed because Codex user skills
belong under `~/.agents/skills/`.

The installer also:

- links `.codex/AGENTS.md` to the selected Codex config directory;
- links generated `.codex/agents/` TOML definitions;
- links snapshot-backed lifecycle hooks and enables `codex_hooks` when needed;
- links DinoStack command-line helpers into `~/.local/bin`;
- preserves or backs up user-owned config according to the installer guards.

The default activation config is `$HOME/.claude/agentic-engineering.json`.
For a redirected Codex config directory, activation is isolated at
`<selected-config>/agentic-engineering.json`; runtime precedence is
`AGENTIC_CONFIG_DIR` > `CODEX_HOME` > default. A redirected Codex install
does not validate, create, or mutate `$HOME/.claude`.

To update:

```bash
cd ~/DinoStack
git pull
bash .codex/install.sh
```

To remove checkout-owned installed artifacts:

```bash
bash ~/DinoStack/.codex/uninstall.sh
```

The uninstaller removes only owned symlinks/configuration and leaves real user
files, foreign symlinks, and the generated repository tree untouched.

## Build and verification lifecycle

`.codex/build.sh`:

1. assembles `.codex/AGENTS.md` and translates its workflow guidance through
   the same native-skill/manual-dispatch contract used by the skill generator;
2. rebuilds the relative `.codex/commands/` and `.codex/references/` symlink
   mirrors plus the shared hook symlink;
3. generates exactly four native skills through `scripts/codex-skills.py`;
4. regenerates named-agent TOML files.

Run the public build:

```bash
bash .codex/build.sh
```

Run the read-only skill and mirror check:

```bash
bash scripts/check-codex-skill-sync.sh
```

The equivalent direct check works from any current directory:

```bash
python3 scripts/codex-skills.py check --repo /absolute/path/to/DinoStack
```

If a reviewed canonical prose change creates or removes compatibility
occurrences, inspect and refresh the inventory before rebuilding:

```bash
python3 scripts/codex-skills.py inventory --repo . > .codex/skill-compatibility.yml
bash .codex/build.sh
bash scripts/check-codex-skill-sync.sh
```

CI runs the read-only check, the generator/mutation suite, a clean-clone build,
the public build, and a final clean-diff assertion. The repository pre-commit
hook also invokes the Codex skill check whenever relevant canonical inputs,
generator configuration, workflow gates, mirrors, or generated outputs are
staged.

## Other Codex adapter artifacts

- `.codex/AGENTS.md` - generated global methodology.
- `.codex/agents/*.toml` - generated named-agent definitions.
- `.codex/config/hooks.json` - lifecycle hook configuration.
- `.codex/hooks/` - Codex hook implementations and the shared-hook symlink.
- `.codex/commands/` - relative symlink mirror of canonical command documents
  for manual workflows not exposed as native skills.
- `.codex/references/` - relative symlink mirror of canonical references.

The native `$brief`, `$wrap`, and `$implement-ticket` skills are the supported
registered workflow entry points. Other command documents remain manual
resources loaded through the repository dispatcher when the generated
methodology directs Codex to them.

## Coexistence and permissions

Codex uses `~/.codex/` and `~/.agents/skills/`; Claude Code uses
`~/.claude/`. The adapters can coexist. Codex's current Stop hook writes
session continuity to `~/.codex/projects/[hash]/context.md`. Project-local
`<cwd>/.agentic/context.md` adoption belongs to the separate
context-writer-migration unit and has not shipped in this generator unit.

For a trusted checkout, the recommended Codex configuration is:

```toml
sandbox_mode = "danger-full-access"
approval_policy = "never"
```

Use stricter settings for untrusted repositories or prompts. See
[`docs/codex-permissions.md`](../docs/codex-permissions.md) for details.
