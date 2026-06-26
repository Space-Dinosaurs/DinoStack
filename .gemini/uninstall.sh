#!/usr/bin/env bash
# Module: .gemini/uninstall.sh
# Role: Remove the Gemini CLI adapter from ~/.gemini/
# Inputs: currently installed symlinks and settings at ~/.gemini/
# Outputs: symlinks removed; hooks block removed from ~/.gemini/settings.json;
#          .backup-<timestamp> files restored if present
# Side-effects: modifies ~/.gemini/settings.json in-place
# Consumers: user runs manually to reverse install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GEMINI_DIR="$REPO_DIR/.gemini"

GEMINI_MD_SRC="$GEMINI_DIR/GEMINI.md"
GEMINI_MD_DST="$HOME/.gemini/GEMINI.md"

COMMANDS_SRC="$GEMINI_DIR/commands"
COMMANDS_DST="$HOME/.gemini/commands"

AGENTS_SRC="$GEMINI_DIR/agents"
AGENTS_DST="$HOME/.gemini/agents"

SETTINGS="$HOME/.gemini/settings.json"

# ---------------------------------------------------------------------------
# Remove ~/.gemini/GEMINI.md symlink and restore backup if one exists
# ---------------------------------------------------------------------------

echo "Removing global GEMINI.md..."

if [[ -L "$GEMINI_MD_DST" ]]; then
  current_target="$(readlink "$GEMINI_MD_DST")"
  if [[ "$current_target" == "$GEMINI_MD_SRC" ]]; then
    rm "$GEMINI_MD_DST"
    echo "  - ~/.gemini/GEMINI.md symlink removed"

    # Restore the most recent backup if one exists
    latest_backup="$(ls -t "${GEMINI_MD_DST}.backup-"* 2>/dev/null | head -1 || true)"
    if [[ -n "$latest_backup" ]]; then
      mv "$latest_backup" "$GEMINI_MD_DST"
      echo "  + Restored backup: $latest_backup -> ~/.gemini/GEMINI.md"
    fi
  else
    echo "  = ~/.gemini/GEMINI.md (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$GEMINI_MD_DST" ]]; then
  echo "  = ~/.gemini/GEMINI.md (real file - not removing)"
else
  echo "  = ~/.gemini/GEMINI.md (not found - nothing to do)"
fi

# ---------------------------------------------------------------------------
# Remove ~/.gemini/commands/ symlink and restore backup if one exists
# ---------------------------------------------------------------------------

echo "Removing commands directory..."

if [[ -L "$COMMANDS_DST" ]]; then
  current_target="$(readlink "$COMMANDS_DST")"
  if [[ "$current_target" == "$COMMANDS_SRC" ]]; then
    rm "$COMMANDS_DST"
    echo "  - ~/.gemini/commands/ symlink removed"

    # Restore the most recent backup if one exists
    latest_backup="$(ls -td "${COMMANDS_DST}.backup-"* 2>/dev/null | head -1 || true)"
    if [[ -n "$latest_backup" ]]; then
      mv "$latest_backup" "$COMMANDS_DST"
      echo "  + Restored backup: $latest_backup -> ~/.gemini/commands/"
    fi
  else
    echo "  = ~/.gemini/commands/ (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$COMMANDS_DST" ]]; then
  echo "  = ~/.gemini/commands/ (real directory - not removing)"
else
  echo "  = ~/.gemini/commands/ (not found - nothing to do)"
fi

# ---------------------------------------------------------------------------
# Remove ~/.gemini/agents/ symlink and restore backup if one exists
# ---------------------------------------------------------------------------

echo "Removing agents directory..."

if [[ -L "$AGENTS_DST" ]]; then
  current_target="$(readlink "$AGENTS_DST")"
  if [[ "$current_target" == "$AGENTS_SRC" ]]; then
    rm "$AGENTS_DST"
    echo "  - ~/.gemini/agents/ symlink removed"

    # Restore the most recent backup if one exists
    latest_backup="$(ls -td "${AGENTS_DST}.backup-"* 2>/dev/null | head -1 || true)"
    if [[ -n "$latest_backup" ]]; then
      mv "$latest_backup" "$AGENTS_DST"
      echo "  + Restored backup: $latest_backup -> ~/.gemini/agents/"
    fi
  else
    echo "  = ~/.gemini/agents/ (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$AGENTS_DST" ]]; then
  echo "  = ~/.gemini/agents/ (real directory - not removing)"
else
  echo "  = ~/.gemini/agents/ (not found - nothing to do)"
fi

# ---------------------------------------------------------------------------
# Remove hooks block from ~/.gemini/settings.json
#
# Uses Python JSON merge to surgically remove only the keys this installer
# added (BeforeAgent risk-reminder, SessionEnd stop-context). Does not
# clobber unrelated user settings.
# ---------------------------------------------------------------------------

echo "Removing hooks from ~/.gemini/settings.json..."

if [[ -f "$SETTINGS" ]]; then
  python3 - "$SETTINGS" "$GEMINI_DIR/hooks" <<'PYEOF'
import json, os, sys

settings_path = sys.argv[1]
hooks_dir = sys.argv[2]

with open(settings_path, "r") as f:
    try:
        settings = json.load(f)
    except json.JSONDecodeError:
        print("  ! settings.json is not valid JSON - skipping hooks removal")
        sys.exit(0)

hooks = settings.get("hooks", {})
changed = False

# ---- Remove BeforeAgent risk-reminder entries installed by this adapter ----
ba_list = hooks.get("BeforeAgent", [])
for block in ba_list:
    if block.get("matcher") == "*":
        original_len = len(block.get("hooks", []))
        block["hooks"] = [
            e for e in block.get("hooks", [])
            if not (
                e.get("name") == "risk-reminder" or
                ("risk-reminder.sh" in e.get("command", "") and "agentic-engineering" in e.get("command", ""))
            )
        ]
        if len(block["hooks"]) < original_len:
            changed = True
            print("  - Removed BeforeAgent risk-reminder hook")
        # Remove empty matcher blocks
ba_list[:] = [b for b in ba_list if b.get("hooks")]
if not ba_list:
    hooks.pop("BeforeAgent", None)
    changed = True

# ---- Remove SessionEnd stop-context entries installed by this adapter ------
se_list = hooks.get("SessionEnd", [])
for block in se_list:
    if block.get("matcher") == "exit":
        original_len = len(block.get("hooks", []))
        block["hooks"] = [
            e for e in block.get("hooks", [])
            if not (
                e.get("name") == "stop-context" or
                ("stop-context-gemini.js" in e.get("command", "") and "agentic-engineering" in e.get("command", ""))
            )
        ]
        if len(block["hooks"]) < original_len:
            changed = True
            print("  - Removed SessionEnd stop-context hook")
se_list[:] = [b for b in se_list if b.get("hooks")]
if not se_list:
    hooks.pop("SessionEnd", None)
    changed = True

# Remove empty hooks object
if not hooks:
    settings.pop("hooks", None)
    changed = True

if not changed:
    print("  = No agentic-engineering hooks found in settings.json")
else:
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("  settings.json written.")
PYEOF
else
  echo "  = ~/.gemini/settings.json not found - nothing to remove"
fi

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
      if [[ "$current_target" == "$REPO_DIR"* ]]; then
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
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Uninstall complete."
echo ""
echo "Note: The following files were NOT removed (they are part of the repo, not installed):"
echo "  .gemini/GEMINI.md      - stays in the repo (generated artifact)"
echo "  .gemini/agents/        - stays in the repo (generated markdown files)"
echo "  .gemini/commands/      - stays in the repo (generated TOML files)"
echo "  .gemini/references/    - stays in the repo (hardlinks)"
echo "  .gemini/hooks/         - stays in the repo (hook scripts)"
echo ""
echo "If you want to remove the full repo, delete ~/DinoStack/ manually."
