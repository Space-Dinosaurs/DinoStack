#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DST="$HOME/.kimi/skills/agentic-engineering"
AE_CONFIG_PATH="$HOME/.claude/agentic-engineering.json"

removed=()
skipped=()

remove_if_ours() {
  local path="$1"
  local expected_target="$2"
  if [[ -L "$path" ]]; then
    local current
    current="$(readlink "$path")"
    if [[ "$current" == "$expected_target" ]]; then
      rm "$path"
      removed+=("$path")
    else
      skipped+=("$path (symlink points elsewhere: $current)")
    fi
  elif [[ -e "$path" ]]; then
    skipped+=("$path (not a symlink - manual removal required)")
  fi
}

echo "Uninstalling Kimi adapter..."

# Remove global skill symlink
remove_if_ours "$SKILL_DST" "$REPO_DIR/.kimi/skills/agentic-engineering"

# Remove per-command skill symlinks
for cmd_dir in "$REPO_DIR/.kimi/skills/"*/; do
  cmd_name="$(basename "$cmd_dir")"
  if [[ "$cmd_name" == "agentic-engineering" ]]; then
    continue
  fi
  if [[ ! -f "$cmd_dir/SKILL.md" ]]; then
    continue
  fi
  remove_if_ours "$HOME/.kimi/skills/$cmd_name" "$cmd_dir"
done

# ---------------------------------------------------------------------------
# Remove ~/.local/bin/agentic-* symlinks
# ---------------------------------------------------------------------------

echo "Removing bin symlinks from ~/.local/bin..."

BIN_DST="$HOME/.local/bin"

if [[ ! -d "$BIN_DST" ]]; then
  echo "  [skip] ~/.local/bin not found"
else
  _found_any=false
  for dst_file in "$BIN_DST"/agentic-*; do
    [[ -e "$dst_file" || -L "$dst_file" ]] || continue
    _found_any=true
    name="$(basename "$dst_file")"

    if [[ -L "$dst_file" ]]; then
      current_target="$(readlink "$dst_file")"
      if [[ "$current_target" == "$REPO_DIR/bin/"* ]]; then
        rm "$dst_file"
        echo "  - $name removed"
      else
        echo "  = $name (points to $current_target - not ours, skipping)"
      fi
    else
      echo "  = $name (real file - not removing)"
    fi
  done
  if [[ "$_found_any" == false ]]; then
    echo "  = no agentic-* entries found in ~/.local/bin"
  fi
fi

# Optionally remove activation config
if [[ -f "$AE_CONFIG_PATH" ]]; then
  echo ""
  read -p "Remove activation config ($AE_CONFIG_PATH)? [y/N] " REMOVE_CONFIG
  if [[ "$REMOVE_CONFIG" =~ ^[Yy]$ ]]; then
    rm "$AE_CONFIG_PATH"
    removed+=("$AE_CONFIG_PATH")
  else
    skipped+=("$AE_CONFIG_PATH (kept)")
  fi
fi

echo ""
if [[ ${#removed[@]} -gt 0 ]]; then
  echo "Removed:"
  for item in "${removed[@]}"; do
    echo "  - $item"
  done
fi
if [[ ${#skipped[@]} -gt 0 ]]; then
  echo "Skipped:"
  for item in "${skipped[@]}"; do
    echo "  = $item"
  done
fi

echo ""
echo "Kimi adapter uninstalled."
echo "Note: .kimi/ directory in the repo was NOT removed. Delete it manually if desired."
