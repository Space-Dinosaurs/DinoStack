#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
RULES_DST="$REPO_DIR/.cursor/rules"
REFS_DST="$REPO_DIR/.cursor/rules/references"
COMMANDS_DST="$REPO_DIR/.cursor/commands"
FRONTMATTER_DIR="$REPO_DIR/.cursor/rules/frontmatter"

# Rules: prepend YAML frontmatter from sidecar files to produce .mdc
for src in "$CONTENT/rules/"*.md; do
  name="$(basename "$src" .md)"
  sidecar="$FRONTMATTER_DIR/$name.yaml"
  dst="$RULES_DST/$name.mdc"
  if [[ -f "$sidecar" ]]; then
    { echo "---"; cat "$sidecar"; echo "---"; echo; cat "$src"; } > "$dst"
  else
    echo "WARNING: no sidecar for $name, copying without frontmatter"
    cp "$src" "$dst"
  fi
done

hardlink_from_content() {
  local src="$1"
  local dst="$2"
  if [[ -e "$dst" ]] && [[ "$(stat -f %i "$src")" == "$(stat -f %i "$dst")" ]]; then
    return
  fi
  rm -f "$dst"
  ln "$src" "$dst"
}

# References: hardlink from content/ so edits stay in sync across adapters
mkdir -p "$REFS_DST"
for src in "$CONTENT/references/"*.md; do
  hardlink_from_content "$src" "$REFS_DST/$(basename "$src")"
done

# Commands: hardlink from content/ (no prerequisite transform for Cursor)
for src in "$CONTENT/commands/"*.md; do
  hardlink_from_content "$src" "$COMMANDS_DST/$(basename "$src")"
done

echo "Cursor adapter build complete."
