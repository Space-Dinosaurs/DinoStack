#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

AGENTS_SRC="$REPO_DIR/.claude/agents"
COMMANDS_SRC="$REPO_DIR/.claude/commands"
SKILLS_SRC="$REPO_DIR/.claude/skills/engineering"

AGENTS_DST="$HOME/.claude/agents"
COMMANDS_DST="$HOME/.claude/commands"
SKILLS_DST="$HOME/.claude/skills/engineering"
SETTINGS="$HOME/.claude/settings.json"

installed_agents=()
skipped_agents=()
warned_agents=()
installed_commands=()
skipped_commands=()
warned_commands=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

symlink_files() {
  local src_dir="$1"
  local dst_dir="$2"
  local label="$3"
  local -n installed_ref="$4"
  local -n skipped_ref="$5"
  local -n warned_ref="$6"

  if [[ ! -d "$src_dir" ]]; then
    echo "  [skip] $label source directory not found: $src_dir"
    return
  fi

  mkdir -p "$dst_dir"

  for src_file in "$src_dir"/*.md; do
    [[ -e "$src_file" ]] || continue
    local name
    name="$(basename "$src_file")"
    local dst_file="$dst_dir/$name"

    if [[ -L "$dst_file" ]]; then
      local current_target
      current_target="$(readlink "$dst_file")"
      if [[ "$current_target" == "$src_file" ]]; then
        skipped_ref+=("$name (already linked)")
        continue
      else
        warned_ref+=("$name (symlink points elsewhere: $current_target - skipping)")
        continue
      fi
    elif [[ -e "$dst_file" ]]; then
      warned_ref+=("$name (real file exists at destination - skipping)")
      continue
    fi

    ln -s "$src_file" "$dst_file"
    installed_ref+=("$name")
  done
}

# ---------------------------------------------------------------------------
# Symlink agents
# ---------------------------------------------------------------------------

echo "Linking agents..."
symlink_files "$AGENTS_SRC" "$AGENTS_DST" "agents" installed_agents skipped_agents warned_agents

for f in "${installed_agents[@]+"${installed_agents[@]}"}"; do echo "  + $f"; done
for f in "${skipped_agents[@]+"${skipped_agents[@]}"}"; do echo "  = $f"; done
for f in "${warned_agents[@]+"${warned_agents[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Symlink commands
# ---------------------------------------------------------------------------

echo "Linking commands..."
symlink_files "$COMMANDS_SRC" "$COMMANDS_DST" "commands" installed_commands skipped_commands warned_commands

for f in "${installed_commands[@]+"${installed_commands[@]}"}"; do echo "  + $f"; done
for f in "${skipped_commands[@]+"${skipped_commands[@]}"}"; do echo "  = $f"; done
for f in "${warned_commands[@]+"${warned_commands[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Symlink skill
# ---------------------------------------------------------------------------

echo "Linking skill: engineering..."

mkdir -p "$(dirname "$SKILLS_DST")"

if [[ -L "$SKILLS_DST" ]]; then
  current_target="$(readlink "$SKILLS_DST")"
  if [[ "$current_target" == "$SKILLS_SRC" ]]; then
    echo "  = engineering (already linked)"
  else
    echo "  ! engineering (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$SKILLS_DST" ]]; then
  echo "  ! engineering (real file/directory exists at destination - skipping)"
else
  ln -s "$SKILLS_SRC" "$SKILLS_DST"
  echo "  + engineering"
fi

# ---------------------------------------------------------------------------
# Update settings.json
# ---------------------------------------------------------------------------

echo "Updating ~/.claude/settings.json..."

python3 - <<PYEOF
import json, os, sys

settings_path = os.path.expanduser("~/.claude/settings.json")
repo_dir = os.environ.get("REPO_DIR", "")

# Read existing settings
if os.path.exists(settings_path):
    with open(settings_path, "r") as f:
        settings = json.load(f)
else:
    settings = {}

hooks = settings.setdefault("hooks", {})

# ---- UserPromptSubmit hook --------------------------------------------------
RISK_CMD = (
    "echo 'BEFORE ANY ACTION: classify risk first. "
    "Elevated = spawn Worker + Skeptic in background. "
    "Direct action ONLY for: reads, answering from memory, screenshots, "
    "synthesizing subagent results, diagnostic-only logging. "
    "When in doubt, classify Elevated.'"
)

ups_list = hooks.setdefault("UserPromptSubmit", [])

# Find or create a matcher "*" block
ups_star = None
for block in ups_list:
    if block.get("matcher") == "*":
        ups_star = block
        break

if ups_star is None:
    ups_star = {"matcher": "*", "hooks": []}
    ups_list.append(ups_star)

ups_star.setdefault("hooks", [])

already_has_risk = any(
    entry.get("command") == RISK_CMD
    for entry in ups_star["hooks"]
)

if already_has_risk:
    print("  = UserPromptSubmit risk-classification hook already present")
else:
    ups_star["hooks"].append({
        "type": "command",
        "command": RISK_CMD,
        "timeout": 5
    })
    print("  + Added UserPromptSubmit risk-classification hook")

# ---- Stop hook --------------------------------------------------------------
STOP_CMD = f"node {repo_dir}/hooks/stop-context.js"

stop_list = hooks.setdefault("Stop", [])

# Find or create a matcher "*" block
stop_star = None
for block in stop_list:
    if block.get("matcher") == "*":
        stop_star = block
        break

if stop_star is None:
    stop_star = {"matcher": "*", "hooks": []}
    stop_list.append(stop_star)

stop_star.setdefault("hooks", [])

# Look for any existing stop-context.js entry
replaced = False
already_correct = False
for entry in stop_star["hooks"]:
    cmd = entry.get("command", "")
    if "stop-context.js" in cmd:
        if cmd == STOP_CMD:
            already_correct = True
        else:
            entry["command"] = STOP_CMD
            replaced = True
        break

if already_correct:
    print("  = Stop hook already points to correct stop-context.js")
elif replaced:
    print(f"  ~ Replaced Stop hook stop-context.js with: {STOP_CMD}")
else:
    stop_star["hooks"].append({
        "type": "command",
        "command": STOP_CMD,
        "timeout": 5
    })
    print(f"  + Added Stop hook: {STOP_CMD}")

# ---- Write back -------------------------------------------------------------
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print("  settings.json written.")
PYEOF

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Install complete."
echo "  Agents linked:   ${#installed_agents[@]}"
echo "  Commands linked: ${#installed_commands[@]}"
