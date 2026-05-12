#!/usr/bin/env bash
# Purpose: Uninstall global native Pi coding agent adapter artifacts created by .pi/install.sh.
# Public API: `bash .pi/uninstall.sh`.
# Upstream deps: ~/.pi/agent resource directories.
# Downstream consumers: none.
# Failure modes: skips files not owned by this repo.
# Performance: standard.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_HOME="$HOME/.pi/agent"
SKILL_DST="$PI_HOME/skills/agentic-engineering"
PROMPT_DST="$PI_HOME/prompts"
EXT_DST="$PI_HOME/extensions/agentic-engineering"
AE_CONFIG_PATH="$HOME/.claude/agentic-engineering.json"

removed=()
skipped=()

remove_path() {
  local path="$1"
  if [[ -e "$path" || -L "$path" ]]; then
    rm -rf "$path"
    removed+=("$path")
  fi
}

remove_link_if_ours() {
  local path="$1"
  local expected="$2"
  if [[ -L "$path" ]]; then
    local current
    current="$(readlink "$path")"
    if [[ "$current" == "$expected" ]]; then
      rm "$path"
      removed+=("$path")
    else
      skipped+=("$path (symlink points elsewhere: $current)")
    fi
  elif [[ -e "$path" ]]; then
    skipped+=("$path (not a symlink - manual removal required)")
  fi
}

echo "Uninstalling Pi coding agent adapter..."

if [[ -d "$SKILL_DST" ]]; then
  remove_path "$SKILL_DST/SKILL.md"
  remove_path "$SKILL_DST/METHODOLOGY.md"
  remove_link_if_ours "$SKILL_DST/commands" "$REPO_DIR/content/commands"
  remove_link_if_ours "$SKILL_DST/references" "$REPO_DIR/content/references"
  remove_link_if_ours "$SKILL_DST/rules" "$REPO_DIR/content/rules"
  remove_link_if_ours "$SKILL_DST/agents" "$REPO_DIR/content/agents"
  if rmdir "$SKILL_DST" 2>/dev/null; then
    removed+=("$SKILL_DST")
  else
    skipped+=("$SKILL_DST (directory not empty - manual removal required)")
  fi
fi

if [[ -d "$REPO_DIR/.pi/prompts" ]]; then
  for src in "$REPO_DIR/.pi/prompts/"*.md; do
    [[ -e "$src" ]] || continue
    remove_link_if_ours "$PROMPT_DST/$(basename "$src")" "$src"
  done
fi


if [[ -d "$EXT_DST" ]]; then
  remove_link_if_ours "$EXT_DST/index.ts" "$REPO_DIR/.pi/extensions/agentic-engineering/index.ts"
  if rmdir "$EXT_DST" 2>/dev/null; then
    removed+=("$EXT_DST")
  else
    skipped+=("$EXT_DST (directory not empty - manual removal required)")
  fi
fi

if [[ -f "$AE_CONFIG_PATH" && -t 0 ]]; then
  echo ""
  read -r -p "Remove activation config ($AE_CONFIG_PATH)? [y/N] " remove_config
  if [[ "$remove_config" =~ ^[Yy]$ ]]; then
    remove_path "$AE_CONFIG_PATH"
  else
    skipped+=("$AE_CONFIG_PATH (kept)")
  fi
fi

echo ""
if [[ ${#removed[@]} -gt 0 ]]; then
  echo "Removed:"
  for item in "${removed[@]}"; do echo "  - $item"; done
fi
if [[ ${#skipped[@]} -gt 0 ]]; then
  echo "Skipped:"
  for item in "${skipped[@]}"; do echo "  = $item"; done
fi

echo ""
echo "Pi coding agent adapter uninstalled. Repository .pi/ adapter files were not removed."
