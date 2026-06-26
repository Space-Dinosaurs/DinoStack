#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

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
# Remove skill symlink
# ---------------------------------------------------------------------------

echo "Removing skill: agentic-engineering..."

SKILLS_SRC="$REPO_DIR/.opencode/skills/agentic-engineering"
SKILLS_DST="$HOME/.config/opencode/skills/agentic-engineering"

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
# Remove agent symlinks
# ---------------------------------------------------------------------------

echo "Removing agent symlinks..."
remove_symlinks "$HOME/.config/opencode/agents" "agents"

# ---------------------------------------------------------------------------
# Remove command symlinks
# ---------------------------------------------------------------------------

echo "Removing command symlinks..."
remove_symlinks "$HOME/.config/opencode/commands" "commands"

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
# Clean up opencode.json
# ---------------------------------------------------------------------------

echo "Updating ~/.config/opencode/opencode.json..."

python3 - <<'PYEOF'
import json, os

config_path = os.path.expanduser("~/.config/opencode/opencode.json")
repo_dir = os.environ.get("REPO_DIR", "")

if not os.path.exists(config_path):
    print("  = opencode.json not found - nothing to update")
    raise SystemExit(0)

with open(config_path, "r") as f:
    config = json.load(f)

changed = False

# Remove agentic-engineering skill permission
perm = config.get("permission", {})
if "skill" in perm and "agentic-engineering" in perm["skill"]:
    del perm["skill"]["agentic-engineering"]
    if not perm["skill"]:
        del perm["skill"]
    changed = True
    print("  - Removed agentic-engineering skill permission")

# Remove external directory entry for agentic-engineering repo
if "external_directory" in perm:
    to_remove = [k for k in perm["external_directory"] if repo_dir in k]
    for k in to_remove:
        del perm["external_directory"][k]
        changed = True
        print("  - Removed external_directory entry: " + k)
    if not perm["external_directory"]:
        del perm["external_directory"]

if not perm:
    config.pop("permission", None)

# Remove instructions pointing to agentic-engineering content
instructions = config.get("instructions", [])
new_instructions = [i for i in instructions if repo_dir not in i]
removed = len(instructions) - len(new_instructions)
if removed:
    config["instructions"] = new_instructions
    changed = True
    print("  - Removed " + str(removed) + " instruction references")

if changed:
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    print("  opencode.json written.")
else:
    print("  = No agentic-engineering entries found in opencode.json")

PYEOF

# ---------------------------------------------------------------------------
# Remove managed section from AGENTS.md
# ---------------------------------------------------------------------------

echo "Updating ~/.config/opencode/AGENTS.md..."

python3 - <<'PYEOF'
import os, re

target = os.path.expanduser("~/.config/opencode/AGENTS.md")
begin_marker = "<!-- BEGIN managed-by-agentic-engineering -->"
end_marker = "<!-- END managed-by-agentic-engineering -->"

if not os.path.exists(target):
    print("  - ~/.config/opencode/AGENTS.md not found, skipping")
    raise SystemExit(0)

with open(target, "r") as f:
    existing = f.read()

if begin_marker not in existing or end_marker not in existing:
    print("  - ~/.config/opencode/AGENTS.md has no managed-by-agentic-engineering section, skipping")
    raise SystemExit(0)

pattern = re.compile(
    r'\n?<!-- BEGIN managed-by-agentic-engineering -->.*?<!-- END managed-by-agentic-engineering -->\n?',
    re.DOTALL
)
updated = pattern.sub("", existing)
updated = updated.strip("\n")
if not updated:
    os.remove(target)
    print("  - Removed ~/.config/opencode/AGENTS.md (was only managed content)")
else:
    with open(target, "w") as f:
        f.write(updated + "\n")
    print("  - Removed managed-by-agentic-engineering section from ~/.config/opencode/AGENTS.md")
PYEOF

# ---------------------------------------------------------------------------
# Remove activation config
# ---------------------------------------------------------------------------

echo "Removing activation config..."
AE_CONFIG_PATH="$HOME/.config/opencode/agentic-engineering.json"
if [[ -f "$AE_CONFIG_PATH" ]]; then
  rm "$AE_CONFIG_PATH"
  echo "  - Removed $AE_CONFIG_PATH"
else
  echo "  = Not found, nothing to remove"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "OpenCode adapter uninstall complete."