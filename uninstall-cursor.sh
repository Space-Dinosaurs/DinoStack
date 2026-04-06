#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RULES_DST="$HOME/.cursor/rules"
REFS_DST="$HOME/.cursor/rules/references"
COMMANDS_DST="$HOME/.cursor/commands"
HOOKS_DST="$HOME/.cursor/hooks.json"

removed_rules=()
skipped_rules=()
removed_refs=()
skipped_refs=()
removed_commands=()
skipped_commands=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

remove_symlinks() {
  local dst_dir="$1"
  local label="$2"
  local pattern="$3"
  local -n removed_ref="$4"
  local -n skipped_ref="$5"

  if [[ ! -d "$dst_dir" ]]; then
    echo "  [skip] $label directory not found: $dst_dir"
    return
  fi

  for dst_file in "$dst_dir"/$pattern; do
    [[ -e "$dst_file" || -L "$dst_file" ]] || continue
    local name
    name="$(basename "$dst_file")"

    if [[ -L "$dst_file" ]]; then
      local current_target
      current_target="$(readlink "$dst_file")"
      if [[ "$current_target" == "$REPO_DIR"* ]]; then
        rm "$dst_file"
        removed_ref+=("$name")
      else
        skipped_ref+=("$name (points to $current_target - not ours)")
      fi
    else
      skipped_ref+=("$name (real file - not removing)")
    fi
  done
}

# ---------------------------------------------------------------------------
# Remove rule symlinks (.mdc files)
# ---------------------------------------------------------------------------

echo "Removing rule symlinks..."
remove_symlinks "$RULES_DST" "rules" "*.mdc" removed_rules skipped_rules

for f in "${removed_rules[@]+"${removed_rules[@]}"}"; do echo "  - $f"; done
for f in "${skipped_rules[@]+"${skipped_rules[@]}"}"; do echo "  = $f"; done

# ---------------------------------------------------------------------------
# Remove reference doc symlinks (.md files in rules/references/)
# ---------------------------------------------------------------------------

echo "Removing reference doc symlinks..."
remove_symlinks "$REFS_DST" "references" "*.md" removed_refs skipped_refs

for f in "${removed_refs[@]+"${removed_refs[@]}"}"; do echo "  - $f"; done
for f in "${skipped_refs[@]+"${skipped_refs[@]}"}"; do echo "  = $f"; done

# ---------------------------------------------------------------------------
# Remove command symlinks (.md files)
# ---------------------------------------------------------------------------

echo "Removing command symlinks..."
remove_symlinks "$COMMANDS_DST" "commands" "*.md" removed_commands skipped_commands

for f in "${removed_commands[@]+"${removed_commands[@]}"}"; do echo "  - $f"; done
for f in "${skipped_commands[@]+"${skipped_commands[@]}"}"; do echo "  = $f"; done

# ---------------------------------------------------------------------------
# hooks.json - manual step required
# ---------------------------------------------------------------------------

echo "Checking hooks.json..."

if [[ -e "$HOOKS_DST" ]]; then
  echo "  ! $HOOKS_DST was not automatically removed."
  echo "    If you installed it via install-cursor.sh, manually delete it or remove"
  echo "    any agentic-engineering entries if you have other hooks configured."
else
  echo "  = $HOOKS_DST not found - nothing to do."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Uninstall complete."
echo "  Rules removed:    ${#removed_rules[@]}"
echo "  Refs removed:     ${#removed_refs[@]}"
echo "  Commands removed: ${#removed_commands[@]}"
