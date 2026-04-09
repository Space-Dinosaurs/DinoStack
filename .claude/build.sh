#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
COMMANDS_DST="$REPO_DIR/.claude/commands"

PREREQ='> **Prerequisite:** If the /agentic-engineering skill has not been loaded in this session, invoke it first before proceeding.'

# Commands: prepend prerequisite blockquote
for src in "$CONTENT/commands/"*.md; do
  name="$(basename "$src")"
  { echo "$PREREQ"; echo; cat "$src"; } > "$COMMANDS_DST/$name"
done

echo "Claude adapter build complete."
