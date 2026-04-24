#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

# ---------------------------------------------------------------------------
# Activation mode (shared across all adapters)
#
# Writes ~/.claude/agentic-engineering.json with { "mode": "opt-out" | "opt-in",
# "set_at": "<ISO8601>" }. Read by the skill preflight each session.
#
# Flag: --mode=opt-in | --mode=opt-out (optional)
# Interactive prompt when flag absent AND stdin is a TTY.
# Non-interactive default: opt-out.
# Idempotent: if the config already exists and --mode was not passed, keep it.
# ---------------------------------------------------------------------------

AE_MODE_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --mode=opt-in|--mode=opt-out)
      AE_MODE_FLAG="${arg#--mode=}"
      ;;
    --mode=*)
      echo "  ! ignoring unknown --mode value: ${arg#--mode=} (expected opt-in or opt-out)"
      ;;
  esac
done

AE_CONFIG_PATH="$HOME/.claude/agentic-engineering.json"
mkdir -p "$HOME/.claude"

AE_EXISTING_MODE=""
if [[ -f "$AE_CONFIG_PATH" ]]; then
  AE_EXISTING_MODE="$(python3 -c "
import json, sys
try:
    with open('$AE_CONFIG_PATH') as f:
        print(json.load(f).get('mode', ''))
except Exception:
    print('')
" 2>/dev/null)"
fi

ae_write_mode() {
  local mode="$1"
  python3 - "$AE_CONFIG_PATH" "$mode" <<'PYEOF'
import json, sys, datetime
path, mode = sys.argv[1], sys.argv[2]
data = {"mode": mode, "set_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
}

echo ""
echo "Activation mode..."
if [[ -n "$AE_MODE_FLAG" ]]; then
  ae_write_mode "$AE_MODE_FLAG"
  echo "  + agentic-engineering mode set to '$AE_MODE_FLAG' via --mode flag (wrote $AE_CONFIG_PATH)"
elif [[ -n "$AE_EXISTING_MODE" ]]; then
  echo "  = agentic-engineering mode already set to '$AE_EXISTING_MODE' (keeping $AE_CONFIG_PATH)"
elif [[ -t 0 ]]; then
  echo "  Activation mode:"
  echo "    [1] opt-out (default) - active on every project unless a project's AGENTS.md opts out"
  echo "    [2] opt-in           - dormant until a project's AGENTS.md opts in"
  while true; do
    read -p "  Choice [1]: " AE_CHOICE
    AE_CHOICE="${AE_CHOICE:-1}"
    case "$AE_CHOICE" in
      1) ae_write_mode "opt-out"; echo "  + mode=opt-out written to $AE_CONFIG_PATH"; break ;;
      2) ae_write_mode "opt-in"; echo "  + mode=opt-in written to $AE_CONFIG_PATH"; break ;;
      *) echo "  ! please enter 1 or 2" ;;
    esac
  done
else
  ae_write_mode "opt-out"
  echo "  + non-interactive install: defaulted to mode=opt-out (wrote $AE_CONFIG_PATH)"
  echo "    Override later with: bash .claude/install.sh --mode=opt-in"
fi

AGENTS_SRC="$REPO_DIR/.claude/agents"
COMMANDS_SRC="$REPO_DIR/.claude/commands"
SKILLS_SRC="$REPO_DIR/.claude/skills/agentic-engineering"

AGENTS_DST="$HOME/.claude/agents"
COMMANDS_DST="$HOME/.claude/commands"
SKILLS_DST="$HOME/.claude/skills/agentic-engineering"
SETTINGS="$HOME/.claude/settings.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

symlink_files() {
  local src_dir="$1"
  local dst_dir="$2"
  local label="$3"

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
        echo "  = $name (already linked)"
        continue
      else
        echo "  ! $name (symlink points elsewhere: $current_target - skipping)"
        continue
      fi
    elif [[ -e "$dst_file" ]]; then
      echo "  ! $name (real file exists at destination - skipping)"
      continue
    fi

    ln -s "$src_file" "$dst_file"
    echo "  + $name"
  done
}

# ---------------------------------------------------------------------------
# Symlink agents
# ---------------------------------------------------------------------------

echo "Linking agents..."
symlink_files "$AGENTS_SRC" "$AGENTS_DST" "agents"

# ---------------------------------------------------------------------------
# Symlink commands
# ---------------------------------------------------------------------------

echo "Linking commands..."
symlink_files "$COMMANDS_SRC" "$COMMANDS_DST" "commands"

# ---------------------------------------------------------------------------
# Symlink skill
# ---------------------------------------------------------------------------

echo "Linking skill: agentic-engineering..."

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
  echo "  + agentic-engineering"
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
# Update ~/.claude/CLAUDE.md
# ---------------------------------------------------------------------------

echo "Updating ~/.claude/CLAUDE.md..."

python3 - <<'PYEOF'
import os, re

target = os.path.expanduser("~/.claude/CLAUDE.md")
begin_marker = "<!-- BEGIN managed-by-agentic-engineering -->"
end_marker = "<!-- END managed-by-agentic-engineering -->"

managed_content = """\
<!-- BEGIN managed-by-agentic-engineering -->
## Skill Loading

Before starting any task, check if a domain skill should be loaded:

| Signal | Skill |
|---|---|
| Code edits, debugging, testing, deployment, architecture decisions, git operations, agent orchestration, code review, refactoring, dependency management, project setup | `/agentic-engineering` |

If any signal matches, invoke the skill before proceeding. When in doubt, invoke it.
<!-- END managed-by-agentic-engineering -->"""

if os.path.exists(target):
    with open(target, "r") as f:
        existing = f.read()
else:
    existing = ""

if begin_marker in existing and end_marker in existing:
    pattern = re.compile(
        r'<!-- BEGIN managed-by-agentic-engineering -->.*?<!-- END managed-by-agentic-engineering -->',
        re.DOTALL
    )
    updated = pattern.sub(managed_content, existing)
    with open(target, "w") as f:
        f.write(updated)
    print("  = Updated managed-by-agentic-engineering section in ~/.claude/CLAUDE.md")
else:
    # Append to end of file
    if existing:
        updated = existing.rstrip("\n") + "\n\n" + managed_content + "\n"
    else:
        updated = managed_content + "\n"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write(updated)
    if existing:
        print("  + Appended managed-by-agentic-engineering section to ~/.claude/CLAUDE.md")
    else:
        print("  + Created ~/.claude/CLAUDE.md with managed-by-agentic-engineering section")
PYEOF

# ---------------------------------------------------------------------------
# Run initial build
# ---------------------------------------------------------------------------

echo "Running initial build..."
bash "$REPO_DIR/.claude/build.sh"
bash "$REPO_DIR/.cursor/build.sh"

# ---------------------------------------------------------------------------
# Install pre-commit hook
# ---------------------------------------------------------------------------

echo "Installing pre-commit hook..."

HOOK_SRC="$REPO_DIR/hooks/pre-commit"
HOOK_DST="$REPO_DIR/.git/hooks/pre-commit"

if [[ -L "$HOOK_DST" ]]; then
  current_target="$(readlink "$HOOK_DST")"
  if [[ "$current_target" == "$HOOK_SRC" ]]; then
    echo "  = pre-commit hook already linked"
  else
    echo "  ! pre-commit hook points elsewhere: $current_target - skipping"
  fi
elif [[ -e "$HOOK_DST" ]]; then
  echo "  ! pre-commit hook is a real file (not a symlink) - skipping to preserve existing hook"
else
  ln -s "$HOOK_SRC" "$HOOK_DST"
  echo "  + pre-commit hook installed"
fi

# ---------------------------------------------------------------------------
# Recommended tools (interactive, optional)
# ---------------------------------------------------------------------------

echo ""
echo "Recommended tools (optional):"
echo ""

# CLI tools
declare -a CLI_TOOLS=(
  "gh:GitHub CLI — create PRs, manage issues, and run repo operations from the terminal:brew install gh"
  "agent-browser:Headless browser — lets agents verify UI changes by taking snapshots and interacting with pages:npm install -g agent-browser"
  "lc:Linear CLI — create, update, and triage issues directly from Claude Code:npm install -g linearctl"
  "jira:Jira CLI — create, update, and triage Jira issues directly from Claude Code:brew install jira-cli"
  "rclone:Cloud file sync — read and write Google Drive files from the terminal:brew install rclone"
)

for tool_entry in "${CLI_TOOLS[@]}"; do
  IFS=: read -r cmd desc install_cmd <<< "$tool_entry"
  if command -v "$cmd" &>/dev/null; then
    echo "  = $cmd already installed"
  else
    read -p "  Install $cmd ($desc)? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
      eval "$install_cmd" 2>&1 || echo "  ! $cmd install failed (non-blocking)"
    else
      echo "  - skipped $cmd"
    fi
  fi
done

# chrome-devtools MCP
echo ""
CLAUDE_JSON="$HOME/.claude.json"
if [[ -f "$CLAUDE_JSON" ]] && python3 -c "
import json, sys
with open('$CLAUDE_JSON') as f:
    d = json.load(f)
sys.exit(0 if 'chrome-devtools' in d.get('mcpServers', {}) else 1)
" 2>/dev/null; then
  echo "  = chrome-devtools MCP already configured"
else
  read -p "  Configure chrome-devtools MCP — inspect, screenshot, and interact with Chrome tabs for debugging and QA? [y/N] " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    python3 - <<'PYEOF'
import json, os

target = os.path.expanduser("~/.claude.json")
if os.path.exists(target):
    with open(target) as f:
        data = json.load(f)
else:
    data = {}

servers = data.setdefault("mcpServers", {})
if "chrome-devtools" not in servers:
    servers["chrome-devtools"] = {
        "type": "stdio",
        "command": "npx",
        "args": ["chrome-devtools-mcp@latest"],
        "env": {}
    }
    with open(target, "w") as f:
        json.dump(data, f, indent=2)
    print("  + chrome-devtools MCP configured in ~/.claude.json")
else:
    print("  = chrome-devtools MCP already configured")
PYEOF
  else
    echo "  - skipped chrome-devtools MCP"
  fi
fi

# mcp-atlassian MCP
echo ""
if [[ -f "$CLAUDE_JSON" ]] && python3 -c "
import json, sys
with open('$CLAUDE_JSON') as f:
    d = json.load(f)
sys.exit(0 if 'mcp-atlassian' in d.get('mcpServers', {}) else 1)
" 2>/dev/null; then
  echo "  = mcp-atlassian MCP already configured"
else
  read -p "  Configure mcp-atlassian MCP — interact with Jira and Confluence from Claude Code? [y/N] " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    python3 - <<'PYEOF'
import json, os

target = os.path.expanduser("~/.claude.json")
if os.path.exists(target):
    with open(target) as f:
        data = json.load(f)
else:
    data = {}

servers = data.setdefault("mcpServers", {})
if "mcp-atlassian" not in servers:
    servers["mcp-atlassian"] = {
        "type": "stdio",
        "command": "uvx",
        "args": ["mcp-atlassian"],
        "env": {}
    }
    with open(target, "w") as f:
        json.dump(data, f, indent=2)
    print("  + mcp-atlassian MCP configured in ~/.claude.json")
else:
    print("  = mcp-atlassian MCP already configured")
PYEOF
  else
    echo "  - skipped mcp-atlassian MCP"
  fi
fi

# context7 plugin note
echo ""
echo "  Note: Enable the 'context7' plugin in Claude Code settings — agents use it to look up current library and framework documentation instead of relying on training data."


# ---------------------------------------------------------------------------
# Permissions configuration
# ---------------------------------------------------------------------------

echo ""

python3 - <<'PYEOF'
import json, os

settings_path = os.path.expanduser("~/.claude/settings.json")

if os.path.exists(settings_path):
    with open(settings_path, "r") as f:
        settings = json.load(f)
else:
    settings = {}

perms = settings.get("permissions", {})

recommended_allow = [
    "Bash(*)",
    "Write",
    "Write(~/.claude/**)",
    "Edit",
    "Edit(~/.claude/**)",
    "Write(~/.claude/projects/**)",
    "Edit(~/.claude/projects/**)"
]
recommended_deny = [
    "Bash(git push --force*)",
    "Bash(rm -rf*)",
    "Bash(git reset --hard*)",
    "Bash(git clean -f*)",
    "Bash(sudo rm*)",
    "Bash(dd if=*)",
    "Bash(shutdown*)",
    "Bash(reboot*)"
]

already_bypass = perms.get("defaultMode") == "bypassPermissions"

if already_bypass:
    # Already configured — silently merge any missing allow/deny rules
    existing_allow = set(perms.get("allow", []))
    existing_deny = set(perms.get("deny", []))
    missing_allow = set(recommended_allow) - existing_allow
    missing_deny = set(recommended_deny) - existing_deny
    missing_dir = "~/.claude/projects" not in perms.get("additionalDirectories", [])

    if missing_allow or missing_deny or missing_dir:
        perms["allow"] = list(existing_allow | set(recommended_allow))
        perms["deny"] = list(existing_deny | set(recommended_deny))
        perms.setdefault("additionalDirectories", [])
        if "~/.claude/projects" not in perms["additionalDirectories"]:
            perms["additionalDirectories"].append("~/.claude/projects")
        settings["permissions"] = perms
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        added = []
        if missing_allow:
            added.append(f"{len(missing_allow)} allow")
        if missing_deny:
            added.append(f"{len(missing_deny)} deny")
        print(f"  ~ Permissions: bypassPermissions already set, added {' and '.join(added)} rules")
    else:
        print("  = Permissions already configured (bypassPermissions mode)")
else:
    print("  Recommended: bypassPermissions mode with deny rules for destructive commands.")
    print("  Agents work best with uninterrupted tool access. The deny list blocks dangerous")
    print("  operations (force push, rm -rf, hard reset) as a safety net.")
    resp = input("  Configure recommended permission settings? [y/N] ").strip().lower()
    if resp == "y":
        existing_allow = set(perms.get("allow", []))
        existing_deny = set(perms.get("deny", []))

        perms["allow"] = list(existing_allow | set(recommended_allow))
        perms["deny"] = list(existing_deny | set(recommended_deny))
        perms["defaultMode"] = "bypassPermissions"
        perms.setdefault("additionalDirectories", [])
        if "~/.claude/projects" not in perms["additionalDirectories"]:
            perms["additionalDirectories"].append("~/.claude/projects")

        settings["permissions"] = perms

        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        print("  + Configured bypassPermissions mode with recommended allow/deny rules")
    else:
        print("  - skipped permissions configuration")
PYEOF

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Install complete."
echo ""
echo "Next steps (for the agent running this installer):"
echo ""
echo "  Offer the user a quick orientation. Ask which of the following they'd"
echo "  like to view, then 'open' each one they say yes to (skipping all is fine):"
echo ""
echo "    1. $REPO_DIR/docs/slides/how-it-works-slides.html"
echo "       - what agentic-engineering is and how it works"
echo "    2. $REPO_DIR/docs/slides/getting-started-slides.html"
echo "       - install flow and the first focused session"
echo "    3. $REPO_DIR/docs/slides/context-management-slides.html"
echo "       - why context hygiene is the real bottleneck"
echo "    4. $REPO_DIR/docs/slides/agent-team-slides.html"
echo "       - the agent team and how they compose"
echo "    5. $REPO_DIR/docs/slides/quality-assurance-slides.html"
echo "       - how the qa-engineer uses .claude/qa.md as project QA memory"
echo "    6. $REPO_DIR/docs/slides/work-tracking-slides.html"
echo "       - how the planner uses .claude/tracking.md for tracker actions"
echo "    7. $REPO_DIR/docs/slides/skill-creator-slides.html"
echo "       - how agents and skills are built and evaluated with the skill creator"
echo "    8. $REPO_DIR/docs/slides/skeptic-protocol-slides.html"
echo "       - adversarial review methodology and the Skeptic loop"
echo "    9. $REPO_DIR/docs/slides/agents-md-hierarchy-slides.html"
echo "       - the three-tier AGENTS.md context hierarchy"
echo "   10. $REPO_DIR/docs/slides/contributing-slides.html"
echo "       - how to contribute to the repo"
echo "   11. $REPO_DIR/docs/agentic-engineering.html"
echo "       - full system architecture reference"
echo ""
echo "  Present the list, ask which ones they want to see, open only those."
