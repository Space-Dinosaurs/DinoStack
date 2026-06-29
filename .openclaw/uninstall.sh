#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Removes the OpenClaw adapter installation. Deletes per-skill-dir
#          symlinks under ~/.openclaw/skills/ that point into this repo,
#          removes the managed Skill Loading block from ~/.openclaw/AGENTS.md,
#          and prompts to remove ~/.openclaw/agentic-engineering.json.
#
# Public API: bash .openclaw/uninstall.sh
#
# Upstream deps: none (removal only).
#
# Downstream consumers: none.
#
# Failure modes: Exits non-zero on unexpected errors. Safe to re-run;
#                removal is conditional on symlink ownership checks.
#
# Performance: Standard.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

# ---------------------------------------------------------------------------
# Remove per-skill-dir symlinks under ~/.openclaw/skills/
# ---------------------------------------------------------------------------

echo "Removing skill symlinks..."

SKILLS_DST="$HOME/.openclaw/skills"
SKILLS_SRC="$REPO_DIR/.openclaw/skills"

if [[ ! -d "$SKILLS_DST" ]]; then
  echo "  [skip] ~/.openclaw/skills/ not found - nothing to remove"
else
  for skill_dst in "$SKILLS_DST"/*/; do
    [[ -e "$skill_dst" || -L "$skill_dst" ]] || continue
    skill_name="$(basename "$skill_dst")"

    if [[ -L "$skill_dst" ]]; then
      current_target="$(readlink "$skill_dst")"
      if [[ "$current_target" == "$SKILLS_SRC"* || "$current_target" == "$REPO_DIR/.openclaw/skills"* ]]; then
        rm "$skill_dst"
        echo "  - $skill_name"
      else
        echo "  = $skill_name (points to $current_target - not ours)"
      fi
    else
      echo "  = $skill_name (real directory - not removing)"
    fi
  done
fi

# ---------------------------------------------------------------------------
# Remove managed block from ~/.openclaw/AGENTS.md
# ---------------------------------------------------------------------------

echo ""
echo "Updating ~/.openclaw/AGENTS.md..."

python3 - <<'PYEOF'
import os, re

target = os.path.expanduser("~/.openclaw/AGENTS.md")
begin_marker = "<!-- BEGIN managed-by-agentic-engineering -->"
end_marker = "<!-- END managed-by-agentic-engineering -->"

if not os.path.exists(target):
    print("  = ~/.openclaw/AGENTS.md not found - nothing to update")
    raise SystemExit(0)

with open(target, "r") as f:
    existing = f.read()

if begin_marker not in existing or end_marker not in existing:
    print("  = ~/.openclaw/AGENTS.md has no managed-by-agentic-engineering section - nothing to remove")
    raise SystemExit(0)

pattern = re.compile(
    r'\n?<!-- BEGIN managed-by-agentic-engineering -->.*?<!-- END managed-by-agentic-engineering -->\n?',
    re.DOTALL
)
updated = pattern.sub("", existing)
updated = updated.strip("\n")
if not updated:
    os.remove(target)
    print("  - Removed ~/.openclaw/AGENTS.md (was only managed content)")
else:
    with open(target, "w") as f:
        f.write(updated + "\n")
    print("  - Removed managed-by-agentic-engineering section from ~/.openclaw/AGENTS.md")
PYEOF

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
# Prompt to remove activation config
# ---------------------------------------------------------------------------

echo ""
echo "Removing activation config..."
AE_CONFIG_PATH="$HOME/.openclaw/agentic-engineering.json"
if [[ -f "$AE_CONFIG_PATH" ]]; then
  if [[ -t 0 ]]; then
    read -r -p "  Remove $AE_CONFIG_PATH? [y/N] " yn
    yn="${yn:-N}"
    case "$yn" in
      y|Y|yes|YES)
        rm "$AE_CONFIG_PATH"
        echo "  - Removed $AE_CONFIG_PATH"
        ;;
      *)
        echo "  = Keeping $AE_CONFIG_PATH"
        ;;
    esac
  else
    rm "$AE_CONFIG_PATH"
    echo "  - Removed $AE_CONFIG_PATH (non-interactive)"
  fi
else
  echo "  = Not found, nothing to remove"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "OpenClaw adapter uninstall complete."
