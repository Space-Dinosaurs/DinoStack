#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

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
        if "agentic-engineering" in cmd:
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

# context7 plugin note
echo ""
echo "  Note: Enable the 'context7' plugin in Claude Code settings — agents use it to look up current library and framework documentation instead of relying on training data."

# ---------------------------------------------------------------------------
# Community skills (optional install)
# ---------------------------------------------------------------------------

_community_skills_dir="$REPO_DIR/community-skills"
_installable_skills=()
_installable_descs=()

_parse_skill_desc_py="$(mktemp /tmp/parse_skill_desc.XXXXXX.py)"
cat > "$_parse_skill_desc_py" << 'SKILLPYEOF'
import sys, re

path = sys.argv[1]
try:
    with open(path, "r") as f:
        content = f.read()
except Exception:
    print("")
    sys.exit(0)

# Try YAML frontmatter
if content.startswith("---"):
    end = content.find("\n---", 3)
    if end != -1:
        frontmatter = content[3:end]
        for line in frontmatter.splitlines():
            m = re.match(r'^description\s*:\s*(.+)', line.strip())
            if m:
                desc = m.group(1).strip().strip("\"'")
                print(desc[:80] + ("..." if len(desc) > 80 else ""))
                sys.exit(0)

# Fallback: first non-heading non-blank line after frontmatter
start = 0
if content.startswith("---"):
    end = content.find("\n---", 3)
    if end != -1:
        start = end + 4

for line in content[start:].splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        print(line[:80] + ("..." if len(line) > 80 else ""))
        sys.exit(0)

print("")
SKILLPYEOF

if [[ -d "$_community_skills_dir" ]]; then
  for _skill_path in "$_community_skills_dir"/*/; do
    _skill_name="$(basename "$_skill_path")"
    [[ "$_skill_name" == "_template" ]] && continue
    [[ -f "$_skill_path/SKILL.md" ]] || continue
    _desc="$(python3 "$_parse_skill_desc_py" "$_skill_path/SKILL.md")"
    _installable_skills+=("$_skill_name")
    _installable_descs+=("$_desc")
  done
fi

rm -f "$_parse_skill_desc_py"

if [[ ${#_installable_skills[@]} -gt 0 ]]; then
  echo ""
  echo "Community skills available:"
  for _i in "${!_installable_skills[@]}"; do
    printf "  %d) %s - %s\n" "$((_i + 1))" "${_installable_skills[$_i]}" "${_installable_descs[$_i]}"
  done
  echo ""
  read -r -p "Install which? (comma-separated numbers like '1,3', 'all', or blank to skip): " _cs_input
  echo

  _cs_install=()
  _cs_lower="${_cs_input,,}"
  if [[ -z "$_cs_input" ]]; then
    : # blank - install nothing
  elif [[ "$_cs_lower" == "all" ]]; then
    _cs_install=("${_installable_skills[@]}")
  else
    IFS=',' read -ra _cs_tokens <<< "$_cs_input"
    for _token in "${_cs_tokens[@]}"; do
      _token="${_token// /}"
      if [[ "$_token" =~ ^[0-9]+$ ]]; then
        _idx=$((_token - 1))
        if [[ $_idx -ge 0 && $_idx -lt ${#_installable_skills[@]} ]]; then
          _cs_install+=("${_installable_skills[$_idx]}")
        else
          echo "  ! invalid number: $_token (out of range, skipping)"
        fi
      else
        echo "  ! invalid input: '$_token' (not a number, skipping)"
      fi
    done
  fi

  _cs_count=0
  for _skill_name in "${_cs_install[@]}"; do
    _src="$_community_skills_dir/$_skill_name"
    _dst="$HOME/.claude/skills/$_skill_name"
    mkdir -p "$HOME/.claude/skills"
    if [[ -L "$_dst" ]]; then
      _cur="$(readlink "$_dst")"
      if [[ "$_cur" == "$_src" ]]; then
        echo "  = $_skill_name (already linked)"
      else
        echo "  ! $_skill_name (symlink points elsewhere: $_cur - skipping)"
      fi
    elif [[ -e "$_dst" ]]; then
      echo "  ! $_skill_name (real file/directory exists at destination - skipping)"
    else
      ln -s "$_src" "$_dst"
      echo "  + $_skill_name"
      _cs_count=$((_cs_count + 1))
    fi
  done

  if [[ ${#_cs_install[@]} -eq 0 ]]; then
    echo "  No community skills selected."
  else
    echo "  Installed: $_cs_count community skill(s)."
  fi
fi

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
echo "System architecture reference: file://$REPO_DIR/docs/agentic-engineering.html"
