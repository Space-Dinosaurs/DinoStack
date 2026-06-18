#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

echo ""
echo "agentic-engineering Hermes adapter uninstaller"
echo "=============================================="
echo ""

SKILL_DST="$HOME/.hermes/skills/agentic-engineering"
AE_CONFIG_PATH="$HOME/.hermes/agentic-engineering.json"

# Remove skill symlink
if [[ -L "$SKILL_DST/SKILL.md" ]]; then
  rm "$SKILL_DST/SKILL.md"
  echo "  - removed skill symlink"
elif [[ -f "$SKILL_DST/SKILL.md" ]]; then
  rm "$SKILL_DST/SKILL.md"
  echo "  - removed skill file"
fi

# Remove empty skill directory
if [[ -d "$SKILL_DST" ]]; then
  rmdir "$SKILL_DST" 2>/dev/null || true
fi

# Optionally remove config (TTY-safe: defaults to keep when non-interactive)
if [[ -f "$AE_CONFIG_PATH" ]]; then
  confirm="n"
  # Test that /dev/tty is actually openable (not just stat-readable) before prompting.
  if { true </dev/tty; } 2>/dev/null; then
    read -r -p "Remove activation mode config ($AE_CONFIG_PATH)? [y/N]: " confirm </dev/tty || confirm="n"
  fi
  if [[ "$confirm" =~ ^[Yy]$ ]]; then
    rm "$AE_CONFIG_PATH"
    echo "  - removed $AE_CONFIG_PATH"
  else
    echo "  = kept $AE_CONFIG_PATH"
  fi
fi

echo ""
echo "Uninstall complete."
echo ""
