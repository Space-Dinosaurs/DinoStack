#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SKILL_SRC="$REPO_DIR/.codex/skill"
SKILL_DST="$HOME/.agents/skills/agentic-engineering"
OLD_SKILL_DST="$HOME/.codex/skills/agentic-engineering"

AGENTS_SRC="$REPO_DIR/.codex/AGENTS.md"
AGENTS_DST="$HOME/.codex/AGENTS.md"

# ---------------------------------------------------------------------------
# Remove the agentic-engineering skill symlink from ~/.agents/skills/
# ---------------------------------------------------------------------------

echo "Removing skill: agentic-engineering..."

if [[ -L "$SKILL_DST" ]]; then
  current_target="$(readlink "$SKILL_DST")"
  if [[ "$current_target" == "$SKILL_SRC" ]]; then
    rm "$SKILL_DST"
    echo "  - agentic-engineering skill symlink removed from $SKILL_DST"
  else
    echo "  = $SKILL_DST (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$SKILL_DST" ]]; then
  echo "  = $SKILL_DST (real file/directory - not removing)"
else
  echo "  = $SKILL_DST (not found - nothing to do)"
fi

# Also clean up old (incorrect) symlink at ~/.codex/skills/ if present
if [[ -L "$OLD_SKILL_DST" ]]; then
  old_target="$(readlink "$OLD_SKILL_DST")"
  if [[ "$old_target" == "$SKILL_SRC" ]]; then
    rm "$OLD_SKILL_DST"
    echo "  - Removed stale legacy symlink at $OLD_SKILL_DST"
  fi
fi

# ---------------------------------------------------------------------------
# Remove ~/.codex/AGENTS.md symlink and restore backup if one exists
# ---------------------------------------------------------------------------

echo "Removing global AGENTS.md..."

if [[ -L "$AGENTS_DST" ]]; then
  current_target="$(readlink "$AGENTS_DST")"
  if [[ "$current_target" == "$AGENTS_SRC" ]]; then
    rm "$AGENTS_DST"
    echo "  - ~/.codex/AGENTS.md symlink removed"

    # Restore the most recent backup if one exists
    latest_backup="$(ls -t "${AGENTS_DST}.backup-"* 2>/dev/null | head -1 || true)"
    if [[ -n "$latest_backup" ]]; then
      mv "$latest_backup" "$AGENTS_DST"
      echo "  + Restored backup: $latest_backup -> ~/.codex/AGENTS.md"
    fi
  else
    echo "  = ~/.codex/AGENTS.md (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$AGENTS_DST" ]]; then
  echo "  = ~/.codex/AGENTS.md (real file - not removing)"
else
  echo "  = ~/.codex/AGENTS.md (not found - nothing to do)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Uninstall complete."
echo ""
echo "Note: The following files were NOT removed (they are part of the repo, not installed):"
echo "  .codex/AGENTS.md       - stays in the repo"
echo "  .codex/references/     - stays in the repo"
echo "  .codex/commands/       - stays in the repo"
echo ""
echo "If you want to remove the full repo, delete ~/agentic-engineering/ manually."
