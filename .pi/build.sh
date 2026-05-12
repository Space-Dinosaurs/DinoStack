#!/usr/bin/env bash
# Purpose: Build the native Pi coding agent adapter outputs from canonical content/.
# Public API: invoked as `bash .pi/build.sh`; idempotent.
# Upstream deps: content/commands/, content/references/, content/rules/, content/agents/,
#               content/sections/, content/SKILL.md, scripts/build-methodology.sh.
# Downstream consumers: .pi/skills/agentic-engineering/, .pi/prompts/.
# Failure modes: exits non-zero on missing inputs or assembly failure.
# Performance: standard.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
SKILL_DST="$REPO_DIR/.pi/skills/agentic-engineering"
PROMPTS_DST="$REPO_DIR/.pi/prompts"

mkdir -p "$SKILL_DST" "$PROMPTS_DST"

required=(
  "$CONTENT/SKILL.md"
  "$REPO_DIR/scripts/build-methodology.sh"
  "$SKILL_DST/SKILL.frontmatter.yaml"
)
for path in "${required[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "build.sh: missing $path" >&2
    exit 1
  fi
done

# Methodology: assemble content/sections/*.md into a single METHODOLOGY.md.
bash "$REPO_DIR/scripts/build-methodology.sh" > "$SKILL_DST/METHODOLOGY.md"

# SKILL.md: Pi implements the Agent Skills standard. Keep adapter frontmatter
# in .pi and derive body from canonical content/SKILL.md.
{
  cat "$SKILL_DST/SKILL.frontmatter.yaml"
  echo
  perl -0pe 's/\A<!--.*?-->\n\n?//s' "$CONTENT/SKILL.md"
  cat <<'PI_NOTES'

## Pi coding agent usage

Pi discovers this skill from `.pi/skills/agentic-engineering/` for project-local use and from `~/.pi/agent/skills/agentic-engineering/` after global install.

- Force-load with `/skill:agentic-engineering` when you want the methodology active immediately.
- Pi prompt templates in `.pi/prompts/` provide slash-command equivalents for the markdown commands in `content/commands/`.
- Read `METHODOLOGY.md` at skill load before applying the workflow.
- Read command details from `commands/<name>.md` when a prompt template asks you to run a command.
- Read references from `references/` and rules from `rules/` on their documented triggers.
PI_NOTES
} > "$SKILL_DST/SKILL.md"

link_dir() {
  local target="$1"
  local link="$2"
  if [[ -L "$link" ]]; then
    local current
    current="$(readlink "$link")"
    if [[ "$current" == "$target" ]]; then
      echo "  = $(basename "$link") (already linked)"
    else
      rm "$link"
      ln -s "$target" "$link"
      echo "  ~ $(basename "$link") (re-linked)"
    fi
  elif [[ -e "$link" ]]; then
    echo "build.sh: $link exists and is not a symlink" >&2
    exit 1
  else
    ln -s "$target" "$link"
    echo "  + $(basename "$link")"
  fi
}

# Relative symlinks keep project-local adapter portable across clone paths.
link_dir "../../../content/commands" "$SKILL_DST/commands"
link_dir "../../../content/references" "$SKILL_DST/references"
link_dir "../../../content/rules" "$SKILL_DST/rules"
link_dir "../../../content/agents" "$SKILL_DST/agents"

# Pi prompt templates are project-local slash-command equivalents. They expand
# into instructions that load the skill and then read the canonical command doc.
for src in "$CONTENT/commands/"*.md; do
  name="$(basename "$src" .md)"
  dst="$PROMPTS_DST/$name.md"
  title="$(sed -n '1s/^# *//p' "$src")"
  if [[ -z "$title" ]]; then
    title="$name"
  fi
  cat > "$dst" <<PROMPT_EOF
---
description: Run agentic-engineering command $title
argument-hint: "[arguments]"
---
Use the /skill:agentic-engineering skill. Load /skill:agentic-engineering, then read commands/$name.md from the loaded agentic-engineering skill directory. Execute that command with these arguments:

\$ARGUMENTS
PROMPT_EOF
done

for script in "$REPO_DIR/.pi"/*.sh; do
  [[ -e "$script" ]] || continue
  chmod +x "$script"
done

echo "Pi coding agent adapter build complete."
