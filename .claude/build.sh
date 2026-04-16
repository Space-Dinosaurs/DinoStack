#!/usr/bin/env bash
# manifest: .claude/build.sh
# purpose: Build all Claude Code adapter output files from content/ source
# outputs: .claude/commands/*.md (with prerequisite blockquote prepended),
#          .claude/skills/agentic-engineering/references/*.md
# reads-from: content/commands/*.md, content/references/*.md
# side-effects: creates/overwrites files under .claude/commands/ and
#               .claude/skills/agentic-engineering/references/; replaces
#               REFS_DST if it was previously a symlink
# failure-modes: set -euo pipefail — any missing source file or failed write
#                aborts the script; safe to re-run (idempotent writes)
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
COMMANDS_DST="$REPO_DIR/.claude/commands"
REFS_DST="$REPO_DIR/.claude/skills/agentic-engineering/references"

PREREQ='> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.'

sed_inplace() {
  if sed --version >/dev/null 2>&1; then
    sed -i "$@"
  else
    sed -i '' "$@"
  fi
}

# Commands: prepend prerequisite blockquote
for src in "$CONTENT/commands/"*.md; do
  name="$(basename "$src")"
  { echo "$PREREQ"; echo; cat "$src"; } > "$COMMANDS_DST/$name"
done

# References: copy from content/ (copies allow per-adapter sed transforms)
# If REFS_DST is currently a symlink (e.g. pointing to content/references),
# remove it so we can replace it with a real directory of expanded copies.
if [[ -L "$REFS_DST" ]]; then
  rm "$REFS_DST"
fi
mkdir -p "$REFS_DST"
for src in "$CONTENT/references/"*.md; do
  name="$(basename "$src")"
  dst="$REFS_DST/$name"
  cp "$src" "$dst"
done

# Expand relative reference/rule paths for Claude Code's Read tool
for dst in "$REFS_DST"/*.md; do
  sed_inplace \
    -e 's|`references/|`~/agentic-engineering/.claude/skills/agentic-engineering/references/|g' \
    -e 's|`rules/|`~/agentic-engineering/.claude/skills/agentic-engineering/rules/|g' \
    "$dst"
done

echo "Claude adapter build complete."
