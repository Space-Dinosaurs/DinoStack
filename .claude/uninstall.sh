#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

AGENTS_DST="$HOME/.claude/agents"
COMMANDS_DST="$HOME/.claude/commands"
SKILLS_DST="$HOME/.claude/skills/agentic-engineering"
SETTINGS="$HOME/.claude/settings.json"



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

remove_symlinks() {
  local dst_dir="$1"
  local label="$2"

  if [[ ! -d "$dst_dir" ]]; then
    echo "  [skip] $label directory not found: $dst_dir"
    return
  fi

  for dst_file in "$dst_dir"/*.md; do
    [[ -e "$dst_file" || -L "$dst_file" ]] || continue
    local name
    name="$(basename "$dst_file")"

    if [[ -L "$dst_file" ]]; then
      local current_target
      current_target="$(readlink "$dst_file")"
      if [[ "$current_target" == "$REPO_DIR"* ]]; then
        rm "$dst_file"
        echo "  - $name"
      else
        echo "  = $name (points to $current_target - not ours)"
      fi
    else
      echo "  = $name (real file - not removing)"
    fi
  done
}

# ---------------------------------------------------------------------------
# Remove agent symlinks
# ---------------------------------------------------------------------------

echo "Removing agent symlinks..."
remove_symlinks "$AGENTS_DST" "agents"

# ---------------------------------------------------------------------------
# Remove command symlinks
# ---------------------------------------------------------------------------

echo "Removing command symlinks..."
remove_symlinks "$COMMANDS_DST" "commands"

# ---------------------------------------------------------------------------
# Remove skill symlink
# ---------------------------------------------------------------------------

echo "Removing skill: agentic-engineering..."

SKILLS_SRC="$REPO_DIR/.claude/skills/agentic-engineering"

if [[ -L "$SKILLS_DST" ]]; then
  current_target="$(readlink "$SKILLS_DST")"
  if [[ "$current_target" == "$SKILLS_SRC" ]]; then
    rm "$SKILLS_DST"
    echo "  - agentic-engineering"
  else
    echo "  = agentic-engineering (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$SKILLS_DST" ]]; then
  echo "  = agentic-engineering (real file/directory - not removing)"
else
  echo "  = agentic-engineering (not found, nothing to remove)"
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
# Update settings.json
# ---------------------------------------------------------------------------

echo "Updating ~/.claude/settings.json..."

python3 "$REPO_DIR/hooks/lib/settings-migrate.py" uninstall "$REPO_DIR"

# ---------------------------------------------------------------------------
# Remove managed section from ~/.claude/CLAUDE.md
# ---------------------------------------------------------------------------

echo "Updating ~/.claude/CLAUDE.md..."

python3 - <<'PYEOF'
import os, re

target = os.path.expanduser("~/.claude/CLAUDE.md")
begin_marker = "<!-- BEGIN managed-by-agentic-engineering -->"
end_marker = "<!-- END managed-by-agentic-engineering -->"

if not os.path.exists(target):
    print("  - ~/.claude/CLAUDE.md not found, skipping")
    raise SystemExit(0)

with open(target, "r") as f:
    existing = f.read()

if begin_marker not in existing or end_marker not in existing:
    print("  - ~/.claude/CLAUDE.md has no managed-by-agentic-engineering section, skipping")
    raise SystemExit(0)

pattern = re.compile(
    r'\n?<!-- BEGIN managed-by-agentic-engineering -->.*?<!-- END managed-by-agentic-engineering -->\n?',
    re.DOTALL
)
updated = pattern.sub("", existing)
updated = updated.strip("\n")
if not updated:
    os.remove(target)
    print("  - Removed ~/.claude/CLAUDE.md (was only managed content)")
else:
    with open(target, "w") as f:
        f.write(updated + "\n")
    print("  - Removed managed-by-agentic-engineering section from ~/.claude/CLAUDE.md")
PYEOF

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Uninstall complete."
