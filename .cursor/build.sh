#!/usr/bin/env bash
# Purpose: Build the Cursor adapter rule files (.mdc) from content/ sources.
#          Methodology is assembled from content/sections/ via build-methodology.sh;
#          other rules are built from content/rules/*.md directly.
#
# Public API: bash .cursor/build.sh
#
# Upstream deps: content/rules/*.md, content/sections/[0-9][0-9]-*.md,
#                scripts/build-methodology.sh,
#                .cursor/rules/frontmatter/*.yaml,
#                .cursor/cursor-compat-preamble.md
#
# Downstream consumers: Cursor IDE (reads .cursor/rules/*.mdc at startup)
#
# Failure modes: exits non-zero if build-methodology.sh fails or any source file
#                is missing. Idempotent; safe to re-run.
#
# Side-effects: removes stale .cursor/commands/*.md files whose basename no
#               longer matches any content/commands/*.md source (e.g. after
#               a command rename or deletion upstream).
#
# Performance: O(total size of content/ sources); single-pass concatenations.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
RULES_DST="$REPO_DIR/.cursor/rules"
REFS_DST="$REPO_DIR/.cursor/references"
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

# Defense-in-depth: the loops below raw-cat hand-authored sidecar YAML files
# between "---" fences with no escaping - correctness today depends entirely
# on the sidecar author having hand-quoted any colon-space or leading-# value.
# Validate the resulting frontmatter actually parses before trusting it, so a
# future unquoted sidecar edit fails the build instead of shipping silently
# broken (or silently truncated) frontmatter.
validate_frontmatter() {
  local dst="$1"
  python3 - "$dst" <<'PYEOF'
import sys, re
import yaml

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    text = f.read()
m = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
if not m:
    sys.exit(f"ERROR: {path}: no YAML frontmatter block found")
try:
    yaml.safe_load(m.group(1))
except yaml.YAMLError as e:
    sys.exit(f"ERROR: {path}: invalid frontmatter YAML: {e}")
PYEOF
}

# Methodology: assemble from content/sections/ then prepend YAML frontmatter.
# content/rules/agent-methodology.md was deleted in Wave 1; the loop below
# covers only the remaining 3 rules files.
methodology_sidecar="$FRONTMATTER_DIR/agent-methodology.yaml"
methodology_dst="$RULES_DST/agent-methodology.mdc"
PREAMBLE_SRC="$REPO_DIR/.cursor/cursor-compat-preamble.md"
{ echo "---"; cat "$methodology_sidecar"; echo "---"; echo; cat "$PREAMBLE_SRC"; echo; echo; bash "$REPO_DIR/scripts/build-methodology.sh"; } > "$methodology_dst"
validate_frontmatter "$methodology_dst"

# Rules: prepend YAML frontmatter from sidecar files to produce .mdc.
# Covers code-standards, conventions, module-manifest (not agent-methodology).
for src in "$CONTENT/rules/"*.md; do
  name="$(basename "$src" .md)"
  sidecar="$FRONTMATTER_DIR/$name.yaml"
  dst="$RULES_DST/$name.mdc"
  if [[ -f "$sidecar" ]]; then
    { echo "---"; cat "$sidecar"; echo "---"; echo; cat "$src"; } > "$dst"
    validate_frontmatter "$dst"
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
declare -a generated_commands=()
for src in "$CONTENT/commands/"*.md; do
  name="$(basename "$src")"
  generated_commands+=("$name")
  hardlink_from_content "$src" "$COMMANDS_DST/$name"
done

# Remove stale command files (source was renamed or deleted upstream)
for existing in "$COMMANDS_DST"/*.md; do
  [ -f "$existing" ] || continue
  bname="$(basename "$existing")"
  found=0
  for gen in "${generated_commands[@]}"; do
    if [[ "$gen" == "$bname" ]]; then
      found=1
      break
    fi
  done
  if [[ $found -eq 0 ]]; then
    rm "$existing"
    echo "Removed stale command: $bname"
  fi
done

# project-scaffolding.yml and templates/: hardlink so agentic-migrate can resolve from adapter
CURSOR_DIR="$REPO_DIR/.cursor"
hardlink_from_content "$CONTENT/project-scaffolding.yml" "$CURSOR_DIR/project-scaffolding.yml"
mkdir -p "$CURSOR_DIR/templates/.agentic"
for tmpl_src in "$CONTENT"/templates/.agentic/*; do
  [[ -f "$tmpl_src" ]] || continue
  hardlink_from_content "$tmpl_src" "$CURSOR_DIR/templates/.agentic/$(basename "$tmpl_src")"
done

echo "Cursor adapter build complete."
