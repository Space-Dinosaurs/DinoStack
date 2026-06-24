#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

# shellcheck source=scripts/lib/identity.sh
[[ -f "$REPO_DIR/scripts/lib/identity.sh" ]] && . "$REPO_DIR/scripts/lib/identity.sh" || {
  echo "  ! scripts/lib/identity.sh not found - identity setup skipped"
}

# ---------------------------------------------------------------------------
# Activation mode (shared across all adapters)
#
# Writes ~/.claude/agentic-engineering.json with { "mode": "opt-out" | "opt-in",
# "profile": "relaxed" | "default" | "strict", "set_at": "<ISO8601>" }.
# Read by the skill preflight each session.
#
# Flags: --mode=opt-in | --mode=opt-out (optional)
#        --profile=relaxed | --profile=default | --profile=strict (optional)
# Interactive prompt when flag absent AND stdin is a TTY.
# Non-interactive default: opt-out.
# Idempotent: if the config already exists and --mode was not passed, keep it.
# ---------------------------------------------------------------------------

AE_MODE_FLAG=""
AE_PROFILE_FLAG=""
AE_IDENTITY_FLAG=""
AE_NO_IDENTITY=false
for arg in "$@"; do
  case "$arg" in
    --mode=opt-in|--mode=opt-out)
      AE_MODE_FLAG="${arg#--mode=}"
      ;;
    --mode=*)
      echo "  ! ignoring unknown --mode value: ${arg#--mode=} (expected opt-in or opt-out)"
      ;;
    --profile=relaxed|--profile=default|--profile=strict)
      AE_PROFILE_FLAG="${arg#--profile=}"
      ;;
    --profile=*)
      echo "  ! ignoring unknown --profile value: ${arg#--profile=} (expected relaxed, default, or strict)"
      ;;
    --identity=*)
      AE_IDENTITY_FLAG="${arg#--identity=}"
      ;;
    --no-identity)
      AE_NO_IDENTITY=true
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

AE_EXISTING_PROFILE=""
if [[ -f "$AE_CONFIG_PATH" ]]; then
  AE_EXISTING_PROFILE="$(python3 -c "
import json, sys
try:
    with open('$AE_CONFIG_PATH') as f:
        print(json.load(f).get('profile', ''))
except Exception:
    print('')
" 2>/dev/null)"
fi

ae_write_mode() {
  local mode="$1"
  python3 - "$AE_CONFIG_PATH" "$mode" <<'PYEOF'
import json, sys, os, datetime
path, mode = sys.argv[1], sys.argv[2]
# Read existing config or start fresh (preserves all keys including skill_auto_load)
if os.path.exists(path):
    try:
        with open(path) as f:
            config = json.load(f)
    except Exception:
        config = {}
else:
    config = {}
# Update only the fields ae_write_mode controls
config["mode"] = mode
config["profile"] = config.get("profile", "default")
config["set_at"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
with open(path, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
PYEOF
}

ae_write_config() {
  local mode="$1"
  local profile="$2"
  python3 - "$AE_CONFIG_PATH" "$mode" "$profile" <<'PYEOF'
import json, sys, os, datetime
path, mode, profile = sys.argv[1], sys.argv[2], sys.argv[3]
# Read existing config or start fresh
if os.path.exists(path):
    try:
        with open(path) as f:
            config = json.load(f)
    except Exception:
        config = {}
else:
    config = {}
# Always overwrite these keys
config["mode"] = mode
config["profile"] = profile
config["set_at"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
# skill_auto_load: preserve existing; prompt only on fresh install (key absent)
if "skill_auto_load" not in config:
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write("Auto-load agentic-engineering skill at session start? [y/N] ")
            tty.flush()
            answer = (tty.readline() or "").strip().lower()
        config["skill_auto_load"] = answer in ("y", "yes")
    except OSError:
        config["skill_auto_load"] = False
# Write back
with open(path, "w") as f:
    json.dump(config, f, indent=2)
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

echo ""
echo "Risk profile..."
if [[ -n "$AE_PROFILE_FLAG" ]]; then
  AE_CURRENT_MODE="$(python3 -c "
import json, sys
try:
    with open('$AE_CONFIG_PATH') as f:
        print(json.load(f).get('mode', 'opt-out'))
except Exception:
    print('opt-out')
" 2>/dev/null)"
  ae_write_config "$AE_CURRENT_MODE" "$AE_PROFILE_FLAG"
  echo "  + profile set to '$AE_PROFILE_FLAG' via --profile flag"
elif [[ -n "$AE_EXISTING_PROFILE" ]]; then
  echo "  = profile already set to '$AE_EXISTING_PROFILE' (keeping)"
else
  AE_CURRENT_MODE="$(python3 -c "
import json, sys
try:
    with open('$AE_CONFIG_PATH') as f:
        print(json.load(f).get('mode', 'opt-out'))
except Exception:
    print('opt-out')
" 2>/dev/null)"
  ae_write_config "$AE_CURRENT_MODE" "default"
  echo "  = profile defaulted to 'default' (wrote $AE_CONFIG_PATH)"
  echo "    Override with: bash .claude/install.sh --profile=relaxed|default|strict"
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

SKILL_AUTO_CMD = f"bash {repo_dir}/hooks/skill-auto-load-check.sh"

already_has_skill_auto = any(
    "skill-auto-load-check.sh" in entry.get("command", "")
    for entry in ups_star["hooks"]
)

if already_has_skill_auto:
    print("  = UserPromptSubmit skill-auto-load-check hook already present")
else:
    ups_star["hooks"].append({
        "type": "command",
        "command": SKILL_AUTO_CMD,
        "timeout": 5
    })
    print(f"  + Added UserPromptSubmit skill-auto-load-check hook")

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

# ---- SessionEnd hook (deferred-wrap finalize) -------------------------------
# Finalizes a cleanly-ended session's pending marker to `ready` so the daemon
# can drain it. Find-or-create; re-running install must NOT duplicate it.
SESSION_END_CMD = f"node {repo_dir}/hooks/session-end-wrap.js"

session_end_list = hooks.setdefault("SessionEnd", [])

session_end_star = None
for block in session_end_list:
    if block.get("matcher") == "*":
        session_end_star = block
        break

if session_end_star is None:
    session_end_star = {"matcher": "*", "hooks": []}
    session_end_list.append(session_end_star)

session_end_star.setdefault("hooks", [])

already_has_session_end = any(
    "session-end-wrap.js" in entry.get("command", "")
    for entry in session_end_star["hooks"]
)

if already_has_session_end:
    print("  = SessionEnd deferred-wrap hook already present")
else:
    session_end_star["hooks"].append({
        "type": "command",
        "command": SESSION_END_CMD,
        "timeout": 5
    })
    print(f"  + Added SessionEnd hook: {SESSION_END_CMD}")

# ---- SessionStart hook (version notice + deferred-wrap self-heal/launch) -----
# First SessionStart registration: the wrapper composes the version-check
# notice with the self-healing .claude-host sentinel and the guarded daemon
# launch. Find-or-create; re-running install must NOT duplicate it.
SESSION_START_CMD = f"bash {repo_dir}/hooks/session-start-wrap.sh"

session_start_list = hooks.setdefault("SessionStart", [])

session_start_star = None
for block in session_start_list:
    if block.get("matcher") == "*":
        session_start_star = block
        break

if session_start_star is None:
    session_start_star = {"matcher": "*", "hooks": []}
    session_start_list.append(session_start_star)

session_start_star.setdefault("hooks", [])

already_has_session_start = any(
    "session-start-wrap.sh" in entry.get("command", "")
    for entry in session_start_star["hooks"]
)

if already_has_session_start:
    print("  = SessionStart deferred-wrap hook already present")
else:
    session_start_star["hooks"].append({
        "type": "command",
        "command": SESSION_START_CMD,
        "timeout": 5
    })
    print(f"  + Added SessionStart hook: {SESSION_START_CMD}")

# ---- PreToolUse background-spawn enforcement hook ---------------------------
ENFORCE_BG_CMD = f"python3 {repo_dir}/hooks/enforce-background-spawn.py"

ptu_list = hooks.setdefault("PreToolUse", [])

# Find or create a matcher "Task" block
ptu_task = None
for block in ptu_list:
    if block.get("matcher") == "Task":
        ptu_task = block
        break

if ptu_task is None:
    ptu_task = {"matcher": "Task", "hooks": []}
    ptu_list.append(ptu_task)

ptu_task.setdefault("hooks", [])

already_has_enforce_bg = any(
    "enforce-background-spawn" in entry.get("command", "")
    for entry in ptu_task["hooks"]
)

if already_has_enforce_bg:
    print("  = PreToolUse background-spawn enforcement hook already present")
else:
    ptu_task["hooks"].append({
        "type": "command",
        "command": ENFORCE_BG_CMD,
        "timeout": 5
    })
    print("  + Added PreToolUse background-spawn enforcement hook")

# ---- PreToolUse orchestrator-singularity enforcement hook -------------------
# Denies Task spawns issued from inside a subagent context (detected via the
# top-level agent_id field). To disable: set AE_SINGULARITY_GUARD_DISABLE=1
# in the environment that launches Claude Code, then restart.
ENFORCE_SINGULARITY_CMD = f"python3 {repo_dir}/hooks/enforce-orchestrator-singularity.py"

already_has_enforce_singularity = any(
    "enforce-orchestrator-singularity" in entry.get("command", "")
    for entry in ptu_task["hooks"]
)

if already_has_enforce_singularity:
    print("  = PreToolUse orchestrator-singularity enforcement hook already present")
else:
    ptu_task["hooks"].append({
        "type": "command",
        "command": ENFORCE_SINGULARITY_CMD,
        "timeout": 5
    })
    print("  + Added PreToolUse orchestrator-singularity enforcement hook")
    print("    (To disable: set AE_SINGULARITY_GUARD_DISABLE=1 and restart Claude Code)")

# ---- PostToolUse capture-nudge hook -----------------------------------------
# Surfaces an in-session capture-gap nudge when a Task spawn launches and the
# session has a learning-worthy event with no learning captured yet. Matcher
# "Task"; find-or-create idempotent, identical pattern to the PreToolUse Task
# blocks above. Claude-Code-only (consistent with the deferred-wrap hooks).
CAPTURE_NUDGE_CMD = f"node {repo_dir}/hooks/post-tool-use-capture-nudge.js"

ptu_post_list = hooks.setdefault("PostToolUse", [])

# Find or create a matcher "Task" block.
ptu_post_task = None
for block in ptu_post_list:
    if block.get("matcher") == "Task":
        ptu_post_task = block
        break

if ptu_post_task is None:
    ptu_post_task = {"matcher": "Task", "hooks": []}
    ptu_post_list.append(ptu_post_task)

ptu_post_task.setdefault("hooks", [])

already_has_capture_nudge = any(
    "post-tool-use-capture-nudge" in entry.get("command", "")
    for entry in ptu_post_task["hooks"]
)

if already_has_capture_nudge:
    print("  = PostToolUse capture-nudge hook already present")
else:
    ptu_post_task["hooks"].append({
        "type": "command",
        "command": CAPTURE_NUDGE_CMD,
        "timeout": 5
    })
    print("  + Added PostToolUse capture-nudge hook")

# ---- PreToolUse AskUserQuestion default-enforcement hook --------------------
ENFORCE_AUQ_CMD = f"python3 {repo_dir}/hooks/enforce-askuserquestion-default.py"

# Find or create a SEPARATE matcher "AskUserQuestion" block (not the Task block).
ptu_auq = None
for block in ptu_list:
    if block.get("matcher") == "AskUserQuestion":
        ptu_auq = block
        break

if ptu_auq is None:
    ptu_auq = {"matcher": "AskUserQuestion", "hooks": []}
    ptu_list.append(ptu_auq)

ptu_auq.setdefault("hooks", [])

already_has_enforce_auq = any(
    "enforce-askuserquestion-default" in entry.get("command", "")
    for entry in ptu_auq["hooks"]
)

if already_has_enforce_auq:
    print("  = PreToolUse AskUserQuestion default-enforcement hook already present")
else:
    ptu_auq["hooks"].append({
        "type": "command",
        "command": ENFORCE_AUQ_CMD,
        "timeout": 5
    })
    print("  + Added PreToolUse AskUserQuestion default-enforcement hook")

# ---- Write back -------------------------------------------------------------
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print("  settings.json written.")
PYEOF

# ---------------------------------------------------------------------------
# Deferred-wrap .claude-host sentinel (belt; MAJOR-B)
#
# When install.sh runs INSIDE a project (a .agentic/ dir exists in the install
# cwd), drop the .agentic/wrap/claude-host sentinel for THAT project so the
# deferred-wrap feature can activate immediately. This is the belt for the
# install-cwd project only; the SessionStart self-heal (session-start-wrap.sh)
# is the PRIMARY mechanism that covers every project on its next Claude session.
# create-if-absent + fully fail-open; we never drop sentinels for arbitrary
# projects.
# ---------------------------------------------------------------------------
if [[ -d "$PWD/.agentic" && ! -f "$PWD/.agentic/wrap/claude-host" ]]; then
  mkdir -p "$PWD/.agentic/wrap" 2>/dev/null || true
  if : > "$PWD/.agentic/wrap/claude-host" 2>/dev/null; then
    echo "  + dropped deferred-wrap .agentic/wrap/claude-host sentinel in $PWD"
  fi
fi

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

@skills/agentic-engineering/METHODOLOGY.md
@skills/agentic-engineering/rules/code-standards.md
@skills/agentic-engineering/rules/conventions.md
@skills/agentic-engineering/rules/module-manifest.md
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
    if ae_confirm "  Install $cmd ($desc)? [y/N] "; then
      eval "$install_cmd" 2>&1 || echo "  ! $cmd install failed (non-blocking)"
    else
      echo "  - skipped $cmd"
    fi
  fi
done

# ---------------------------------------------------------------------------
# Developer identity
# ---------------------------------------------------------------------------

if declare -f _ae_setup_identity >/dev/null; then
  echo ""
  echo "Developer identity..."
  _ae_setup_identity
  echo "  Run 'agentic-identity show' to confirm your identity."
fi

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
  if ae_confirm "  Configure chrome-devtools MCP — inspect, screenshot, and interact with Chrome tabs for debugging and QA? [y/N] "; then
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
  if ae_confirm "  Configure mcp-atlassian MCP — interact with Jira and Confluence from Claude Code? [y/N] "; then
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

def tty_input(prompt: str) -> str:
    """Read a line from the controlling terminal.

    Required when this script is fed via stdin (heredoc): Python stdin is the
    program text, so builtin input() raises EOFError.
    """
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(prompt)
            tty.flush()
            return tty.readline() or ""
    except OSError:
        return ""

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
    resp = tty_input("  Configure recommended permission settings? [y/N] ").strip().lower()
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
# Symlink bin/ scripts to ~/.local/bin (PATH-accessible location)
# Resolution order:
#   1. If ~/.local/bin exists AND is on PATH -> use it.
#   2. If ~/.local/bin does NOT exist -> create it, symlink there, print PATH
#      guidance (skipped in non-TTY contexts).
# Never uses sudo. Never writes to /usr/local/bin.
# Idempotent: ln -sfn refreshes existing ae symlinks; skips real non-symlinks.
# ---------------------------------------------------------------------------

ae_install_bins() {
  local bin_src="$REPO_DIR/bin"
  local bin_dst="$HOME/.local/bin"
  local path_created=false

  if [[ ! -d "$bin_src" ]]; then
    echo "  [skip] bin/ source directory not found: $bin_src"
    return
  fi

  # Resolve target directory
  if [[ -d "$bin_dst" ]] && echo ":$PATH:" | grep -q ":$bin_dst:"; then
    # ~/.local/bin exists and is on PATH - use it directly
    true
  else
    # Create ~/.local/bin if absent
    if [[ ! -d "$bin_dst" ]]; then
      mkdir -p "$bin_dst"
      path_created=true
    fi
  fi

  # Symlink each file in bin/ (skip test directory and non-executable files)
  local linked=0
  local refreshed=0
  local skipped=0
  for src_file in "$bin_src"/agentic-*; do
    [[ -e "$src_file" ]] || continue
    [[ -f "$src_file" ]] || continue
    local name
    name="$(basename "$src_file")"
    local dst_file="$bin_dst/$name"

    if [[ -L "$dst_file" ]]; then
      local current_target
      current_target="$(readlink "$dst_file")"
      if [[ "$current_target" == "$src_file" ]]; then
        echo "  = $name (already linked)"
      elif [[ "$current_target" == "$REPO_DIR/bin/"* ]]; then
        # Refresh: points into our bin/ but different path (e.g. repo moved)
        ln -sfn "$src_file" "$dst_file"
        echo "  ~ $name (refreshed)"
        refreshed=$((refreshed + 1))
      else
        echo "  ! $name (symlink points elsewhere: $current_target - skipping)"
        skipped=$((skipped + 1))
      fi
    elif [[ -e "$dst_file" ]]; then
      echo "  ! $name (real file at destination - skipping to preserve)"
      skipped=$((skipped + 1))
    else
      ln -sfn "$src_file" "$dst_file"
      echo "  + $name -> $dst_file"
      linked=$((linked + 1))
    fi
  done

  if [[ "$path_created" == "true" ]]; then
    if [[ -t 0 ]] || [[ -r /dev/tty ]]; then
      echo ""
      echo "  Created ~/.local/bin and linked agentic binaries."
      echo "  Add this to your PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
      echo "  (add to ~/.zshrc or ~/.bashrc to make it permanent)"
      echo ""
    fi
  fi
}

echo "Linking bin/ scripts to PATH..."
ae_install_bins

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Install complete."
echo ""
echo "  agentic-engineering is installed. Open a new Claude Code session in any project,"
echo "  add 'agentic-engineering: opt-in' to its AGENTS.md, and the methodology activates."
echo "  Run 'agentic-identity show' to confirm your identity was saved."
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
echo "   11. $REPO_DIR/docs/index.html"
echo "       - full system architecture reference"
echo ""
echo "  Present the list, ask which ones they want to see, open only those."
