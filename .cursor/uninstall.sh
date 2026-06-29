#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RULES_DST="$HOME/.cursor/rules"
REFS_DST="$HOME/.cursor/references"
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
array_append() {
  local _arr="$1"
  local _item="$2"
  eval "${_arr}+=(\"\${_item}\")"
}

remove_symlinks() {
  local dst_dir="$1"
  local label="$2"
  local pattern="$3"
  local suffix="$4"
  local removed_name="removed_${suffix}"
  local skipped_name="skipped_${suffix}"

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
      if [[ "$current_target" == "$REPO_DIR/"* ]]; then
        rm "$dst_file"
        array_append "$removed_name" "$name"
      else
        array_append "$skipped_name" "$name (points to $current_target - not ours)"
      fi
    else
      array_append "$skipped_name" "$name (real file - not removing)"
    fi
  done
}

# ---------------------------------------------------------------------------
# Remove rule symlinks (.mdc files)
# ---------------------------------------------------------------------------

echo "Removing rule symlinks..."
remove_symlinks "$RULES_DST" "rules" "*.mdc" rules

for f in "${removed_rules[@]+"${removed_rules[@]}"}"; do echo "  - $f"; done
for f in "${skipped_rules[@]+"${skipped_rules[@]}"}"; do echo "  = $f"; done

# ---------------------------------------------------------------------------
# Remove reference doc symlinks (.md files in references/)
# ---------------------------------------------------------------------------

echo "Removing reference doc symlinks..."
remove_symlinks "$REFS_DST" "references" "*.md" refs

for f in "${removed_refs[@]+"${removed_refs[@]}"}"; do echo "  - $f"; done
for f in "${skipped_refs[@]+"${skipped_refs[@]}"}"; do echo "  = $f"; done

# Also clean up the legacy path ($HOME/.cursor/rules/references/) if present
_legacy_refs_dir="$HOME/.cursor/rules/references"
if [[ -d "$_legacy_refs_dir" ]]; then
  _removed_legacy=0
  for _f in "$_legacy_refs_dir"/*.md; do
    [[ -e "$_f" || -L "$_f" ]] || continue
    if [[ -L "$_f" ]]; then
      _cur_target="$(readlink "$_f")"
      if [[ "$_cur_target" == "$REPO_DIR/"* ]]; then
        rm "$_f"
        _removed_legacy=$(( _removed_legacy + 1 ))
      fi
    fi
  done
  if [[ "$_removed_legacy" -gt 0 ]]; then
    echo "  - legacy $HOME/.cursor/rules/references/: removed $_removed_legacy symlink(s)"
  fi
  if [[ -d "$_legacy_refs_dir" ]] && [[ -z "$(ls -A "$_legacy_refs_dir" 2>/dev/null)" ]]; then
    rmdir "$_legacy_refs_dir"
    echo "  - legacy $HOME/.cursor/rules/references/ directory removed"
  fi
fi
unset _legacy_refs_dir _removed_legacy _f _cur_target

# ---------------------------------------------------------------------------
# Remove command symlinks (.md files)
# ---------------------------------------------------------------------------

echo "Removing command symlinks..."
remove_symlinks "$COMMANDS_DST" "commands" "*.md" commands

for f in "${removed_commands[@]+"${removed_commands[@]}"}"; do echo "  - $f"; done
for f in "${skipped_commands[@]+"${skipped_commands[@]}"}"; do echo "  = $f"; done

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

# ---------------------------------------------------------------------------
# Remove pre-commit hook symlink
# ---------------------------------------------------------------------------

echo "Removing pre-commit hook..."

HOOK_SRC="$REPO_DIR/hooks/pre-commit"
HOOK_DST="$REPO_DIR/.git/hooks/pre-commit"

if [[ -L "$HOOK_DST" ]]; then
  current_target="$(readlink "$HOOK_DST")"
  if [[ "$current_target" == "$HOOK_SRC" ]]; then
    rm "$HOOK_DST"
    echo "  - pre-commit hook removed"
  else
    echo "  = pre-commit hook points elsewhere: $current_target - not ours, skipping"
  fi
elif [[ -e "$HOOK_DST" ]]; then
  echo "  = pre-commit hook is a real file - not removing"
else
  echo "  = pre-commit hook not found - nothing to do"
fi

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
