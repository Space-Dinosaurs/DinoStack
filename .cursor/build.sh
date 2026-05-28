#!/usr/bin/env bash
# Purpose: Build the Cursor adapter rule files (.mdc) from content/ sources.
#          Methodology is assembled from content/sections/ via build-methodology.sh;
#          other rules are built from content/rules/*.md directly.
#
# Public API: bash .cursor/build.sh
#
# Upstream deps: content/rules/*.md, content/sections/[0-9][0-9]-*.md,
#                scripts/build-methodology.sh,
#                .cursor/rules/frontmatter/*.yaml
#
# Downstream consumers: Cursor IDE (reads .cursor/rules/*.mdc at startup)
#
# Failure modes: exits non-zero if build-methodology.sh fails or any source file
#                is missing. Idempotent; safe to re-run.
#
# Performance: O(total size of content/ sources); single-pass concatenations.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
RULES_DST="$REPO_DIR/.cursor/rules"
REFS_DST="$REPO_DIR/.cursor/rules/references"
COMMANDS_DST="$REPO_DIR/.cursor/commands"
FRONTMATTER_DIR="$REPO_DIR/.cursor/rules/frontmatter"

# Portable inode helper (macOS uses -f, Linux uses -c)
get_inode() {
  if stat -c %i /dev/null >/dev/null 2>&1; then
    stat -c %i "$1"
  else
    stat -f %i "$1"
  fi
}

# Methodology: assemble from content/sections/ then prepend YAML frontmatter.
# content/rules/agent-methodology.md was deleted in Wave 1; the loop below
# covers only the remaining 3 rules files.
methodology_sidecar="$FRONTMATTER_DIR/agent-methodology.yaml"
methodology_dst="$RULES_DST/agent-methodology.mdc"
{ echo "---"; cat "$methodology_sidecar"; echo "---"; echo; bash "$REPO_DIR/scripts/build-methodology.sh"; } > "$methodology_dst"

# Rules: prepend YAML frontmatter from sidecar files to produce .mdc.
# Covers code-standards, conventions, module-manifest (not agent-methodology).
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
  if [[ -e "$dst" ]] && [[ "$(get_inode "$src")" == "$(get_inode "$dst")" ]]; then
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

# project-scaffolding.yml and templates/: hardlink so agentic-migrate can resolve from adapter
CURSOR_DIR="$REPO_DIR/.cursor"
hardlink_from_content "$CONTENT/project-scaffolding.yml" "$CURSOR_DIR/project-scaffolding.yml"
mkdir -p "$CURSOR_DIR/templates/.agentic"
hardlink_from_content "$CONTENT/templates/.agentic/config.json" "$CURSOR_DIR/templates/.agentic/config.json"

echo "Cursor adapter build complete."
