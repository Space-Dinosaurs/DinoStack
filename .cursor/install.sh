#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RULES_SRC="$REPO_DIR/.cursor/rules"
REFS_SRC="$REPO_DIR/.cursor/rules/references"
COMMANDS_SRC="$REPO_DIR/.cursor/commands"
HOOKS_SRC="$REPO_DIR/.cursor/hooks.json"

RULES_DST="$HOME/.cursor/rules"
REFS_DST="$HOME/.cursor/rules/references"
COMMANDS_DST="$HOME/.cursor/commands"
HOOKS_DST="$HOME/.cursor/hooks.json"

installed_rules=()
skipped_rules=()
warned_rules=()
installed_refs=()
skipped_refs=()
warned_refs=()
installed_commands=()
skipped_commands=()
warned_commands=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

symlink_files() {
  local src_dir="$1"
  local dst_dir="$2"
  local label="$3"
  local pattern="$4"
  local -n installed_ref="$5"
  local -n skipped_ref="$6"
  local -n warned_ref="$7"

  if [[ ! -d "$src_dir" ]]; then
    echo "  [skip] $label source directory not found: $src_dir"
    return
  fi

  mkdir -p "$dst_dir"

  for src_file in "$src_dir"/$pattern; do
    [[ -e "$src_file" ]] || continue
    local name
    name="$(basename "$src_file")"
    local dst_file="$dst_dir/$name"

    if [[ -L "$dst_file" ]]; then
      local current_target
      current_target="$(readlink "$dst_file")"
      if [[ "$current_target" == "$src_file" ]]; then
        skipped_ref+=("$name (already linked)")
        continue
      elif [[ "$current_target" == "$REPO_DIR"* ]]; then
        skipped_ref+=("$name (already linked to agentic-engineering but different path: $current_target - skipping)")
        continue
      else
        warned_ref+=("$name (symlink points elsewhere: $current_target - skipping)")
        continue
      fi
    elif [[ -e "$dst_file" ]]; then
      warned_ref+=("$name (real file exists at destination - skipping)")
      continue
    fi

    ln -s "$src_file" "$dst_file"
    installed_ref+=("$name")
  done
}

# ---------------------------------------------------------------------------
# Symlink rules (.mdc files)
# ---------------------------------------------------------------------------

echo "Linking rules..."
symlink_files "$RULES_SRC" "$RULES_DST" "rules" "*.mdc" installed_rules skipped_rules warned_rules

for f in "${installed_rules[@]+"${installed_rules[@]}"}"; do echo "  + $f"; done
for f in "${skipped_rules[@]+"${skipped_rules[@]}"}"; do echo "  = $f"; done
for f in "${warned_rules[@]+"${warned_rules[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Symlink reference docs (.md files in rules/references/)
# ---------------------------------------------------------------------------

echo "Linking reference docs..."
symlink_files "$REFS_SRC" "$REFS_DST" "references" "*.md" installed_refs skipped_refs warned_refs

for f in "${installed_refs[@]+"${installed_refs[@]}"}"; do echo "  + $f"; done
for f in "${skipped_refs[@]+"${skipped_refs[@]}"}"; do echo "  = $f"; done
for f in "${warned_refs[@]+"${warned_refs[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Symlink commands (.md files)
# ---------------------------------------------------------------------------

echo "Linking commands..."
symlink_files "$COMMANDS_SRC" "$COMMANDS_DST" "commands" "*.md" installed_commands skipped_commands warned_commands

for f in "${installed_commands[@]+"${installed_commands[@]}"}"; do echo "  + $f"; done
for f in "${skipped_commands[@]+"${skipped_commands[@]}"}"; do echo "  = $f"; done
for f in "${warned_commands[@]+"${warned_commands[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Copy hooks.json
# ---------------------------------------------------------------------------

echo "Installing hooks.json..."

if [[ -e "$HOOKS_DST" ]]; then
  echo "  ! $HOOKS_DST already exists - skipping to preserve your customizations."
  echo "    Manually merge entries from $HOOKS_SRC if needed."
else
  cp "$HOOKS_SRC" "$HOOKS_DST"
  echo "  + hooks.json copied to $HOOKS_DST"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Install complete."
echo "  Rules linked:    ${#installed_rules[@]}"
echo "  Refs linked:     ${#installed_refs[@]}"
echo "  Commands linked: ${#installed_commands[@]}"
