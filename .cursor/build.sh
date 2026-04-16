#!/usr/bin/env bash
# manifest: .cursor/build.sh
# purpose: Build all Cursor adapter output files from content/ source
# outputs: .cursor/rules/*.mdc, .cursor/rules/references/*.md,
#          .cursor/commands/*.md, .cursor/agents/*.md
# side-effects: creates/overwrites files under .cursor/rules, .cursor/commands,
#               .cursor/agents; removes stale agent files from prior runs
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
RULES_DST="$REPO_DIR/.cursor/rules"
REFS_DST="$REPO_DIR/.cursor/rules/references"
COMMANDS_DST="$REPO_DIR/.cursor/commands"
FRONTMATTER_DIR="$REPO_DIR/.cursor/rules/frontmatter"

# Portable in-place sed: detects GNU sed vs BSD sed (macOS)
sed_inplace() {
  if sed --version >/dev/null 2>&1; then
    # GNU sed
    sed -i "$@"
  else
    # BSD sed (macOS)
    sed -i '' "$@"
  fi
}

# ---------------------------------------------------------------------------
# Rules: prepend YAML frontmatter from sidecar files to produce .mdc
# ---------------------------------------------------------------------------
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

# Transform .mdc rules for Cursor paths
for dst in "$RULES_DST"/*.mdc; do
  sed_inplace \
    -e 's|`references/|`.cursor/rules/references/|g' \
    -e 's|`rules/|`.cursor/rules/|g' \
    -e 's|~/.claude/projects/\[hash\]/context\.md|~/.cursor/projects/[hash]/context.md|g' \
    -e 's|~/.claude/projects/\[hash\]/memory/|.claude/memory/|g' \
    -e 's|~/.claude/agents/\([a-zA-Z_-]*\)\.md|subagent_type: "\1"|g' \
    -e 's|~/.claude/projects/|~/.cursor/projects/|g' \
    "$dst"
done

# ---------------------------------------------------------------------------
# References: copy from content/ and transform paths for Cursor
# ---------------------------------------------------------------------------
mkdir -p "$REFS_DST"
for src in "$CONTENT/references/"*.md; do
  dst="$REFS_DST/$(basename "$src")"
  rm -f "$dst"
  cp "$src" "$dst"
done

# Transform references for Cursor paths
for dst in "$REFS_DST"/*.md; do
  sed_inplace \
    -e 's|`references/|`.cursor/rules/references/|g' \
    -e 's|`rules/|`.cursor/rules/|g' \
    -e 's|~/.claude/projects/\[hash\]/context\.md|~/.cursor/projects/[hash]/context.md|g' \
    -e 's|~/.claude/projects/\[hash\]/memory/|.claude/memory/|g' \
    -e 's|~/.claude/agents/\([a-zA-Z_-]*\)\.md|subagent_type: "\1"|g' \
    -e 's|~/.claude/projects/|~/.cursor/projects/|g' \
    "$dst"
done

# ---------------------------------------------------------------------------
# Commands: copy from content/ and transform paths for Cursor
# ---------------------------------------------------------------------------
for src in "$CONTENT/commands/"*.md; do
  dst="$COMMANDS_DST/$(basename "$src")"
  rm -f "$dst"
  cp "$src" "$dst"
done

# Transform commands for Cursor paths
for dst in "$COMMANDS_DST"/*.md; do
  sed_inplace \
    -e 's|`references/|`.cursor/rules/references/|g' \
    -e 's|`rules/|`.cursor/rules/|g' \
    -e 's|~/.claude/projects/\[hash\]/context\.md|~/.cursor/projects/[hash]/context.md|g' \
    -e 's|~/.claude/projects/\[hash\]/memory/|.claude/memory/|g' \
    -e 's|~/.claude/agents/\([a-zA-Z_-]*\)\.md|subagent_type: "\1"|g' \
    -e 's|~/.claude/projects/|~/.cursor/projects/|g' \
    "$dst"
done

# ---------------------------------------------------------------------------
# Build .cursor/agents/ (instruction files from content/agents/*.md)
#
# Each content/agents/<name>.md has YAML frontmatter followed by the agent
# body. The body is extracted (stripping frontmatter and the prerequisite
# blockquote), then a usage note header is prepended. These are NOT Cursor-
# native agent configs — they are reference instructions the conductor reads
# before spawning a Task with the corresponding subagent_type.
# ---------------------------------------------------------------------------

AGENTS_DST="$REPO_DIR/.cursor/agents"
mkdir -p "$AGENTS_DST"

# Track generated files for stale cleanup
declare -a generated_agents=()

for src in "$CONTENT/agents/"*.md; do
  [ -f "$src" ] || continue
  name="$(basename "$src" .md)"
  dst="$AGENTS_DST/$name.md"
  generated_agents+=("$name.md")

  {
    echo "# ${name} Agent Instructions"
    echo ""
    echo "Include this in the Task prompt when spawning with \`subagent_type: \"${name}\"\`."
    echo ""
    echo "---"
    echo ""
    awk '
      BEGIN { in_fm=0; past_fm=0; skip_bq=0; skip_blank=0 }
      /^---$/ && !in_fm && !past_fm { in_fm=1; next }
      /^---$/ && in_fm { past_fm=1; next }
      past_fm {
        if (skip_bq) { if (/^>/) next; skip_bq=0; skip_blank=1 }
        if (skip_blank) { skip_blank=0; if (/^$/) next }
        if (/^>.*agentic-engineering/) { skip_bq=1; next }
        print
      }
    ' "$src"
  } > "$dst"
done

# Apply Cursor path transforms to generated agent files
for dst in "$AGENTS_DST"/*.md; do
  sed_inplace \
    -e 's|`references/|`.cursor/rules/references/|g' \
    -e 's|`rules/|`.cursor/rules/|g' \
    -e 's|~/.claude/projects/\[hash\]/context\.md|~/.cursor/projects/[hash]/context.md|g' \
    -e 's|~/.claude/projects/\[hash\]/memory/|.claude/memory/|g' \
    -e 's|~/.claude/agents/\([a-zA-Z_-]*\)\.md|subagent_type: "\1"|g' \
    -e 's|~/.claude/projects/|~/.cursor/projects/|g' \
    "$dst"
done

# Remove stale agent files not generated this run
for existing in "$AGENTS_DST"/*.md; do
  [ -f "$existing" ] || continue
  bname="$(basename "$existing")"
  found=0
  for gen in "${generated_agents[@]}"; do
    if [[ "$gen" == "$bname" ]]; then
      found=1
      break
    fi
  done
  if [[ $found -eq 0 ]]; then
    rm "$existing"
    echo "Removed stale agent file: $bname"
  fi
done

echo "Built ${#generated_agents[@]} agent instruction files in .cursor/agents/"
echo "Cursor adapter build complete."
