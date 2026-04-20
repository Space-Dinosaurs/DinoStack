#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/.claude/commands"
for src in "$ROOT/content/commands"/*.md; do
  cp "$src" "$ROOT/.claude/commands/$(basename "$src")"
done
echo "build.sh: regenerated .claude/commands/"
