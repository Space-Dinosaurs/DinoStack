#!/usr/bin/env bash
# Purpose: Build the Claude Code adapter outputs from canonical content/.
# Public API: invoked as `bash .claude/build.sh`; idempotent.
# Upstream deps: content/commands/, content/references/, content/sections/, content/SKILL.md,
#               content/project-scaffolding.yml, content/templates/,
#               scripts/build-methodology.sh, .claude/skills/agentic-engineering/SKILL.frontmatter.yaml.
# Downstream consumers: .claude/commands/, .claude/skills/agentic-engineering/{SKILL.md,METHODOLOGY.md,references/,
#                       project-scaffolding.yml,templates/}.
# Failure modes: exits non-zero on missing inputs, broken hardlinks, or assembly script failure.
# Performance: standard.

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
COMMANDS_DST="$REPO_DIR/.claude/commands"
SKILL_DST="$REPO_DIR/.claude/skills/agentic-engineering"
REFS_DST="$SKILL_DST/references"

PREREQ='> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.'

# Portable inode helper (macOS uses -f, Linux uses -c)
get_inode() {
  if stat -c %i /dev/null >/dev/null 2>&1; then
    stat -c %i "$1"
  else
    stat -f %i "$1"
  fi
}

# Methodology: assemble content/sections/*.md into a single METHODOLOGY.md.
mkdir -p "$SKILL_DST"
bash "$REPO_DIR/scripts/build-methodology.sh" > "$SKILL_DST/METHODOLOGY.md"

# SKILL.md: assemble from adapter-private frontmatter + canonical content/SKILL.md body.
# content/SKILL.md may begin with an HTML comment manifest block (<!-- ... -->); strip it
# before concatenating so the assembled output matches the expected adapter SKILL.md format.
FRONTMATTER="$SKILL_DST/SKILL.frontmatter.yaml"
if [[ ! -f "$FRONTMATTER" ]]; then
  echo "build.sh: missing $FRONTMATTER" >&2
  exit 1
fi
if [[ ! -f "$CONTENT/SKILL.md" ]]; then
  echo "build.sh: missing $CONTENT/SKILL.md" >&2
  exit 1
fi
{
  cat "$FRONTMATTER"
  echo
  # Strip leading HTML comment block (manifest header) if present, then emit body.
  perl -0pe 's/\A<!--.*?-->\n\n?//s' "$CONTENT/SKILL.md"
} > "$SKILL_DST/SKILL.md"

# Commands: prepend prerequisite blockquote
for src in "$CONTENT/commands/"*.md; do
  name="$(basename "$src")"
  { echo "$PREREQ"; echo; cat "$src"; } > "$COMMANDS_DST/$name"
done

# References: hardlink from content/ so edits stay in sync across adapters
mkdir -p "$REFS_DST"
for src in "$CONTENT/references/"*.md; do
  name="$(basename "$src")"
  dst="$REFS_DST/$name"
  if [[ -e "$dst" ]] && [[ "$(get_inode "$src")" == "$(get_inode "$dst")" ]]; then
    continue
  fi
  rm -f "$dst"
  ln "$src" "$dst"
done

# project-scaffolding.yml: hardlink from content/ so it stays in sync
SCAFFOLDING_SRC="$CONTENT/project-scaffolding.yml"
SCAFFOLDING_DST="$SKILL_DST/project-scaffolding.yml"
if [[ -e "$SCAFFOLDING_DST" ]] && [[ "$(get_inode "$SCAFFOLDING_SRC")" == "$(get_inode "$SCAFFOLDING_DST")" ]]; then
  :
else
  rm -f "$SCAFFOLDING_DST"
  ln "$SCAFFOLDING_SRC" "$SCAFFOLDING_DST"
fi

# templates/: hardlink .agentic seed files
mkdir -p "$SKILL_DST/templates/.agentic"
for tmpl_name in config.json learnings.md; do
  TMPL_SRC="$CONTENT/templates/.agentic/$tmpl_name"
  TMPL_DST="$SKILL_DST/templates/.agentic/$tmpl_name"
  if [[ -e "$TMPL_DST" ]] && [[ "$(get_inode "$TMPL_SRC")" == "$(get_inode "$TMPL_DST")" ]]; then
    :
  else
    rm -f "$TMPL_DST"
    ln "$TMPL_SRC" "$TMPL_DST"
  fi
done

echo "Claude adapter build complete."
