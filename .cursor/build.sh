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

# References: copy as-is
mkdir -p "$REFS_DST"
cp "$CONTENT/references/"*.md "$REFS_DST/"

# Commands: copy as-is (no prerequisite for Cursor)
cp "$CONTENT/commands/"*.md "$COMMANDS_DST/"

echo "Cursor adapter build complete."
