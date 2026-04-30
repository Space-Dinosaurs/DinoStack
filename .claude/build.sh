#!/usr/bin/env bash
# Purpose: Build the Claude Code adapter outputs from canonical content/.
# Public API: invoked as `bash .claude/build.sh`; idempotent.
# Upstream deps: content/commands/, content/references/, content/sections/, scripts/build-methodology.sh.
# Downstream consumers: .claude/commands/, .claude/skills/agentic-engineering/{METHODOLOGY.md,references/}.
# Failure modes: exits non-zero on missing inputs, broken hardlinks, or assembly script failure.
# Performance: standard.

set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
COMMANDS_DST="$REPO_DIR/.claude/commands"
SKILL_DST="$REPO_DIR/.claude/skills/agentic-engineering"
REFS_DST="$SKILL_DST/references"

PREREQ='> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.'

# Methodology: assemble content/sections/*.md into a single METHODOLOGY.md.
mkdir -p "$SKILL_DST"
bash "$REPO_DIR/scripts/build-methodology.sh" > "$SKILL_DST/METHODOLOGY.md"

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
  if [[ -e "$dst" ]] && [[ "$(stat -f %i "$src")" == "$(stat -f %i "$dst")" ]]; then
    continue
  fi
  rm -f "$dst"
  ln "$src" "$dst"
done

echo "Claude adapter build complete."
