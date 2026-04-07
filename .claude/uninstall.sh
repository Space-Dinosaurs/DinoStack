#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

AGENTS_DST="$HOME/.claude/agents"
COMMANDS_DST="$HOME/.claude/commands"
SKILLS_DST="$HOME/.claude/skills/engineering"
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

echo "Removing skill: engineering..."

SKILLS_SRC="$REPO_DIR/.claude/skills/engineering"

if [[ -L "$SKILLS_DST" ]]; then
  current_target="$(readlink "$SKILLS_DST")"
  if [[ "$current_target" == "$SKILLS_SRC" ]]; then
    rm "$SKILLS_DST"
    echo "  - engineering"
  else
    echo "  = engineering (points to $current_target - not ours, skipping)"
  fi
elif [[ -e "$SKILLS_DST" ]]; then
  echo "  = engineering (real file/directory - not removing)"
else
  echo "  = engineering (not found, nothing to remove)"
fi

# ---------------------------------------------------------------------------
# Update settings.json
# ---------------------------------------------------------------------------

echo "Updating ~/.claude/settings.json..."

python3 - <<PYEOF
import json, os

settings_path = os.path.expanduser("~/.claude/settings.json")
repo_dir = os.environ.get("REPO_DIR", "")

if not os.path.exists(settings_path):
    print("  settings.json not found - nothing to update.")
    raise SystemExit(0)

with open(settings_path, "r") as f:
    settings = json.load(f)

hooks = settings.get("hooks", {})

RISK_CMD = (
    "echo 'BEFORE ANY ACTION: classify risk first. "
    "Elevated = spawn Worker + Skeptic in background. "
    "Direct action ONLY for: reads, answering from memory, screenshots, "
    "synthesizing subagent results, diagnostic-only logging. "
    "When in doubt, classify Elevated.'"
)

changed = False

# ---- Remove risk-classification hook from UserPromptSubmit -----------------
ups_list = hooks.get("UserPromptSubmit", [])
new_ups_list = []
ups_list_changed = False
for block in ups_list:
    new_hooks = [
        e for e in block.get("hooks", [])
        if e.get("command") != RISK_CMD
    ]
    removed_count = len(block.get("hooks", [])) - len(new_hooks)
    if removed_count:
        changed = True
        ups_list_changed = True
        print(f"  - Removed risk-classification hook from UserPromptSubmit matcher '{block.get('matcher', '')}'")
    if new_hooks:
        block["hooks"] = new_hooks
        new_ups_list.append(block)
    elif removed_count:
        ups_list_changed = True
        print(f"    (matcher block now empty - removed)")

if ups_list_changed:
    if new_ups_list:
        hooks["UserPromptSubmit"] = new_ups_list
    elif "UserPromptSubmit" in hooks:
        del hooks["UserPromptSubmit"]
        print("  - Removed empty UserPromptSubmit key")

# ---- Remove stop-context.js hook from Stop ----------------------------------
stop_list = hooks.get("Stop", [])
new_stop_list = []
for block in stop_list:
    new_hooks = [
        e for e in block.get("hooks", [])
        if "agentic-engineering/hooks/stop-context.js" not in e.get("command", "")
    ]
    removed_count = len(block.get("hooks", [])) - len(new_hooks)
    if removed_count:
        changed = True
        print(f"  - Removed stop-context.js hook from Stop matcher '{block.get('matcher', '')}'")
    if new_hooks:
        block["hooks"] = new_hooks
        new_stop_list.append(block)
    elif removed_count:
        print(f"    (matcher block now empty - removed)")

if new_stop_list != stop_list:
    if new_stop_list:
        hooks["Stop"] = new_stop_list
    elif "Stop" in hooks:
        del hooks["Stop"]
        print("  - Removed empty Stop key")

if hooks != settings.get("hooks", {}):
    if hooks:
        settings["hooks"] = hooks
    else:
        settings.pop("hooks", None)

if not changed:
    print("  = No agentic-engineering hooks found - nothing removed.")
else:
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("  settings.json written.")
PYEOF

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
