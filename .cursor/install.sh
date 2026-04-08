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
array_append() {
  local _arr="$1"
  local _item="$2"
  eval "${_arr}+=(\"\${_item}\")"
}

symlink_files() {
  local src_dir="$1"
  local dst_dir="$2"
  local label="$3"
  local pattern="$4"
  local suffix="$5"
  local installed_name="installed_${suffix}"
  local skipped_name="skipped_${suffix}"
  local warned_name="warned_${suffix}"

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
        array_append "$skipped_name" "$name (already linked)"
        continue
      elif [[ "$current_target" == "$REPO_DIR"* ]]; then
        array_append "$skipped_name" "$name (already linked to agentic-engineering but different path: $current_target - skipping)"
        continue
      else
        array_append "$warned_name" "$name (symlink points elsewhere: $current_target - skipping)"
        continue
      fi
    elif [[ -e "$dst_file" ]]; then
      array_append "$warned_name" "$name (real file exists at destination - skipping)"
      continue
    fi

    ln -s "$src_file" "$dst_file"
    array_append "$installed_name" "$name"
  done
}

# ---------------------------------------------------------------------------
# Symlink rules (.mdc files)
# ---------------------------------------------------------------------------

echo "Linking rules..."
symlink_files "$RULES_SRC" "$RULES_DST" "rules" "*.mdc" rules

for f in "${installed_rules[@]+"${installed_rules[@]}"}"; do echo "  + $f"; done
for f in "${skipped_rules[@]+"${skipped_rules[@]}"}"; do echo "  = $f"; done
for f in "${warned_rules[@]+"${warned_rules[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Symlink reference docs (.md files in rules/references/)
# ---------------------------------------------------------------------------

echo "Linking reference docs..."
symlink_files "$REFS_SRC" "$REFS_DST" "references" "*.md" refs

for f in "${installed_refs[@]+"${installed_refs[@]}"}"; do echo "  + $f"; done
for f in "${skipped_refs[@]+"${skipped_refs[@]}"}"; do echo "  = $f"; done
for f in "${warned_refs[@]+"${warned_refs[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Symlink commands (.md files)
# ---------------------------------------------------------------------------

echo "Linking commands..."
symlink_files "$COMMANDS_SRC" "$COMMANDS_DST" "commands" "*.md" commands

for f in "${installed_commands[@]+"${installed_commands[@]}"}"; do echo "  + $f"; done
for f in "${skipped_commands[@]+"${skipped_commands[@]}"}"; do echo "  = $f"; done
for f in "${warned_commands[@]+"${warned_commands[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Run initial build
# ---------------------------------------------------------------------------

echo "Running initial build..."
bash "$REPO_DIR/.claude/build.sh"
bash "$REPO_DIR/.cursor/build.sh"

# ---------------------------------------------------------------------------
# Install pre-commit hook
# ---------------------------------------------------------------------------

echo "Installing pre-commit hook..."

HOOK_SRC="$REPO_DIR/hooks/pre-commit"
HOOK_DST="$REPO_DIR/.git/hooks/pre-commit"

if [[ -L "$HOOK_DST" ]]; then
  current_target="$(readlink "$HOOK_DST")"
  if [[ "$current_target" == "$HOOK_SRC" ]]; then
    echo "  = pre-commit hook already linked"
  else
    echo "  ! pre-commit hook points elsewhere: $current_target - skipping"
  fi
elif [[ -e "$HOOK_DST" ]]; then
  echo "  ! pre-commit hook is a real file (not a symlink) - skipping to preserve existing hook"
else
  ln -s "$HOOK_SRC" "$HOOK_DST"
  echo "  + pre-commit hook installed"
fi

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
