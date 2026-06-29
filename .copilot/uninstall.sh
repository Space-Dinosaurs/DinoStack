#!/usr/bin/env bash
# Module: .copilot/uninstall.sh
# Role: Remove the VS Code Copilot adapter symlinks installed by install.sh
# Inputs: currently installed symlinks at ~/.copilot/{agents,prompts}
# Outputs: symlinks removed if they point at this repo
# Side-effects: prints reminder to remove the VS Code settings.json entry
# Consumers: user runs manually to reverse install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

AGENTS_SRC="$REPO_DIR/.github/agents"
AGENTS_DST="$HOME/.copilot/agents"

PROMPTS_SRC="$REPO_DIR/.github/prompts"
PROMPTS_DST="$HOME/.copilot/prompts"

# ---------------------------------------------------------------------------
# Remove ~/.copilot/agents symlink
# ---------------------------------------------------------------------------

echo "Removing ~/.copilot/agents..."
if [[ -L "$AGENTS_DST" ]]; then
  current_target="$(readlink "$AGENTS_DST")"
  if [[ "$current_target" == "$AGENTS_SRC" ]]; then
    rm "$AGENTS_DST"
    echo "  - ~/.copilot/agents symlink removed"
    latest_backup="$(ls -td "${AGENTS_DST}.backup-"* 2>/dev/null | head -1 || true)"
    if [[ -n "$latest_backup" ]]; then
      mv "$latest_backup" "$AGENTS_DST"
      echo "  + Restored backup: $latest_backup"
    fi
  else
    echo "  = ~/.copilot/agents (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$AGENTS_DST" ]]; then
  echo "  = ~/.copilot/agents (real directory - not removing)"
else
  echo "  = ~/.copilot/agents (not found - nothing to do)"
fi

# ---------------------------------------------------------------------------
# Remove ~/.copilot/prompts symlink
# ---------------------------------------------------------------------------

echo "Removing ~/.copilot/prompts..."
if [[ -L "$PROMPTS_DST" ]]; then
  current_target="$(readlink "$PROMPTS_DST")"
  if [[ "$current_target" == "$PROMPTS_SRC" ]]; then
    rm "$PROMPTS_DST"
    echo "  - ~/.copilot/prompts symlink removed"
    latest_backup="$(ls -td "${PROMPTS_DST}.backup-"* 2>/dev/null | head -1 || true)"
    if [[ -n "$latest_backup" ]]; then
      mv "$latest_backup" "$PROMPTS_DST"
      echo "  + Restored backup: $latest_backup"
    fi
  else
    echo "  = ~/.copilot/prompts (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$PROMPTS_DST" ]]; then
  echo "  = ~/.copilot/prompts (real directory - not removing)"
else
  echo "  = ~/.copilot/prompts (not found - nothing to do)"
fi

# ---------------------------------------------------------------------------
# Remove ~/.local/bin/agentic-* symlinks (if they point at this repo)
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
# Summary
# ---------------------------------------------------------------------------

HOOKS_ABS="$REPO_DIR/.github/hooks"

echo ""
echo "Uninstall complete."
echo ""
echo "ACTION REQUIRED: Remove the hooks entry from your VS Code settings.json:"
echo '  "github.copilot.chat.hookFilesLocations": ["'"$HOOKS_ABS"'"]'
echo ""
echo "Note: The following files were NOT removed (they are repo artifacts):"
echo "  .github/copilot-instructions.md"
echo "  .github/agents/"
echo "  .github/prompts/"
echo "  .github/instructions/"
echo "  .github/hooks/"
echo "  .copilot/references/"
