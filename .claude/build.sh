#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
COMMANDS_DST="$REPO_DIR/.claude/commands"
REFS_DST="$REPO_DIR/.claude/skills/agentic-engineering/references"

PREREQ='> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.'

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
