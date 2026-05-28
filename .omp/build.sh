#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$REPO_DIR/content"
SKILL_DST="$REPO_DIR/.omp/skills/agentic-engineering"

# ---------------------------------------------------------------------------
# Ensure symlinks in skill directory
# ---------------------------------------------------------------------------

mkdir -p "$SKILL_DST"

symlink_dir() {
  local target="$1"
  local link="$2"
  if [[ -L "$link" ]]; then
    current="$(readlink "$link")"
    if [[ "$current" == "$target" ]]; then
      echo "  = $(basename "$link") (already linked)"
    else
      rm "$link"
      ln -s "$target" "$link"
      echo "  ~ $(basename "$link") (re-linked)"
    fi
  elif [[ -e "$link" ]]; then
    echo "  ! $(basename "$link") exists and is not a symlink - leaving it"
  else
    ln -s "$target" "$link"
    echo "  + $(basename "$link")"
  fi
}

symlink_dir "../../../content/references" "$SKILL_DST/references"
symlink_dir "../../../content/rules"     "$SKILL_DST/rules"
symlink_dir "../../../content/commands"  "$SKILL_DST/commands"
symlink_dir "../../../content/agents"    "$SKILL_DST/agents"
symlink_dir "../../../content/templates" "$SKILL_DST/templates"

# project-scaffolding.yml: hardlink (single file, not a dir)
SCAFFOLDING_SRC="$REPO_DIR/content/project-scaffolding.yml"
SCAFFOLDING_DST="$SKILL_DST/project-scaffolding.yml"
if [[ -L "$SCAFFOLDING_DST" ]]; then
  rm "$SCAFFOLDING_DST"
fi
if [[ ! -e "$SCAFFOLDING_DST" ]]; then
  ln "$SCAFFOLDING_SRC" "$SCAFFOLDING_DST" 2>/dev/null || cp "$SCAFFOLDING_SRC" "$SCAFFOLDING_DST"
  echo "  + project-scaffolding.yml"
fi

# ---------------------------------------------------------------------------
# Make scripts executable
# ---------------------------------------------------------------------------

for script in "$REPO_DIR/.omp"/*.sh; do
  [[ -e "$script" ]] || continue
  chmod +x "$script"
done

echo "Pi (oh-my-pi) adapter build complete."
