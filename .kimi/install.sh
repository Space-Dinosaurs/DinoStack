#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

# ---------------------------------------------------------------------------
# Run build first (generates AGENTS.md and symlinks)
# ---------------------------------------------------------------------------

echo "Building Kimi adapter..."
bash "$REPO_DIR/.kimi/build.sh"

# ---------------------------------------------------------------------------
# Activation mode (shared across all adapters)
# Persists to ~/.claude/agentic-engineering.json. Read by the skill preflight.
# ---------------------------------------------------------------------------

AE_MODE_FLAG=""
AE_PROFILE_FLAG=""
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
import json, sys, datetime
path, mode = sys.argv[1], sys.argv[2]
try:
    with open(path) as f:
        existing = json.load(f)
except Exception:
    existing = {}
profile = existing.get("profile", "default")
with open(path, "w") as f:
    json.dump({"mode": mode, "profile": profile, "set_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}, f, indent=2)
    f.write("\n")
PYEOF
}

ae_write_config() {
  local mode="$1"
  local profile="$2"
  python3 - "$AE_CONFIG_PATH" "$mode" "$profile" <<'PYEOF'
import json, sys, datetime
path, mode, profile = sys.argv[1], sys.argv[2], sys.argv[3]
data = {"mode": mode, "profile": profile, "set_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
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
  echo "    Override later with: bash .kimi/install.sh --mode=opt-in"
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
  echo "    Override with: bash .kimi/install.sh --profile=relaxed|default|strict"
fi

# ---------------------------------------------------------------------------
# Global skill install (optional - project-level skills work automatically)
#
# We copy SKILL.md and use absolute symlinks for commands/references/rules
# instead of symlinking the whole skill directory. This ensures the global
# skill stays valid even when you switch git branches (e.g. to a branch that
# doesn't have the .kimi/ adapter yet).
# ---------------------------------------------------------------------------

SKILL_SRC="$REPO_DIR/.kimi/skills/agentic-engineering"
SKILL_DST="$HOME/.kimi/skills/agentic-engineering"

echo ""
echo "Global skill install (optional)..."

mkdir -p "$SKILL_DST"

# Absolute symlinks for content dirs so they resolve from ~/.kimi/skills/"
link_abs() {
  local src="$1"
  local dst="$2"
  if [[ -L "$dst" ]]; then
    local current
    current="$(readlink "$dst")"
    if [[ "$current" == "$src" ]]; then
      echo "  = $(basename "$dst") (already linked)"
    else
      rm "$dst"
      ln -s "$src" "$dst"
      echo "  ~ $(basename "$dst") (re-linked)"
    fi
  elif [[ -e "$dst" ]]; then
    echo "  ! $(basename "$dst") exists and is not a symlink - leaving it"
  else
    ln -s "$src" "$dst"
    echo "  + $(basename "$dst")"
  fi
}

# Symlink SKILL.md (same treatment as content dirs)
link_abs "$SKILL_SRC/SKILL.md" "$SKILL_DST/SKILL.md"

link_abs "$REPO_DIR/content/commands"   "$SKILL_DST/commands"
link_abs "$REPO_DIR/content/references" "$SKILL_DST/references"
link_abs "$REPO_DIR/content/agents"     "$SKILL_DST/agents"

# ---------------------------------------------------------------------------
# Symlink migration: rules -> sections (5-case contract)
#
# Case 1: sections exists, rules absent        -> already migrated, no action
# Case 2: rules is a symlink, sections absent  -> unlink rules; create sections symlink
# Case 3: rules is a real dir, sections absent -> backup rules; create sections symlink
# Case 4: both rules and sections exist        -> ABORT (manual intervention required)
# Case 5: neither exists                       -> clean install, create sections symlink
# ---------------------------------------------------------------------------
_sections_dst="$SKILL_DST/sections"
_rules_dst="$SKILL_DST/rules"

if [[ -e "$_sections_dst" || -L "$_sections_dst" ]] && [[ ! -e "$_rules_dst" && ! -L "$_rules_dst" ]]; then
  # Case 1: already migrated
  echo "  = sections (already migrated)"
elif [[ -L "$_rules_dst" ]] && [[ ! -e "$_sections_dst" && ! -L "$_sections_dst" ]]; then
  # Case 2: rules is a symlink, sections absent
  rm "$_rules_dst"
  ln -s "$REPO_DIR/content/sections" "$_sections_dst"
  echo "  ~ sections (migrated from rules symlink)"
elif [[ -d "$_rules_dst" && ! -L "$_rules_dst" ]] && [[ ! -e "$_sections_dst" && ! -L "$_sections_dst" ]]; then
  # Case 3: rules is a real directory, sections absent - backup and create
  _backup="${_rules_dst}.bak.$(date +%Y%m%dT%H%M%S)"
  mv "$_rules_dst" "$_backup"
  ln -s "$REPO_DIR/content/sections" "$_sections_dst"
  echo "  ~ sections (migrated from real rules dir; backup at $_backup)"
elif [[ ( -e "$_rules_dst" || -L "$_rules_dst" ) ]] && [[ ( -e "$_sections_dst" || -L "$_sections_dst" ) ]]; then
  # Case 4: both exist - abort
  echo "  ! CONFLICT: both '$_rules_dst' and '$_sections_dst' exist." >&2
  echo "    Remove one manually, then re-run install.sh." >&2
  exit 1
else
  # Case 5: neither exists - clean install
  ln -s "$REPO_DIR/content/sections" "$_sections_dst"
  echo "  + sections"
fi

# ---------------------------------------------------------------------------
# Configure Kimi CLI hooks
# ---------------------------------------------------------------------------

KIMI_CONFIG="$HOME/.kimi/config.toml"
HOOK_SCRIPT="$REPO_DIR/.kimi/hooks/session-start.sh"

if [[ -f "$KIMI_CONFIG" ]]; then
  echo ""
  echo "Configuring Kimi CLI hooks..."

  # Check if the SessionStart hook already exists
  if grep -q "session-start.sh" "$KIMI_CONFIG" 2>/dev/null; then
    echo "  = SessionStart hook already configured"
  else
    cat >> "$KIMI_CONFIG" <<HOOKEOF

[[hooks]]
event = "SessionStart"
command = "bash $HOOK_SCRIPT"
matcher = ""
timeout = 5
HOOKEOF
    echo "  + Added SessionStart hook to ~/.kimi/config.toml"
  fi
else
  echo "  ! ~/.kimi/config.toml not found - skipping hook config"
fi

# ---------------------------------------------------------------------------
# Install per-command skills
# Each command (init-project, skeptic, wrap, etc.) is a separate skill directory
# that can be invoked directly via /skill:<command-name>.
# ---------------------------------------------------------------------------

echo ""
echo "Installing command skills..."

for cmd_dir in "$REPO_DIR/.kimi/skills/"*/; do
  cmd_name="$(basename "$cmd_dir")"

  # Skip the main skill directory
  if [[ "$cmd_name" == "agentic-engineering" ]]; then
    continue
  fi

  # Only process directories that have a SKILL.md (per-command skills)
  if [[ ! -f "$cmd_dir/SKILL.md" ]]; then
    continue
  fi

  dst="$HOME/.kimi/skills/$cmd_name"

  if [[ -L "$dst" ]]; then
    current_target="$(readlink "$dst")"
    if [[ "$current_target" == "$cmd_dir" ]]; then
      echo "  = $cmd_name (already linked)"
    else
      rm "$dst"
      ln -s "$cmd_dir" "$dst"
      echo "  ~ $cmd_name (re-linked)"
    fi
  elif [[ -e "$dst" ]]; then
    echo "  ! $cmd_name exists and is not a symlink - leaving it"
  else
    ln -s "$cmd_dir" "$dst"
    echo "  + $cmd_name"
  fi
done

echo ""
echo "Kimi adapter install complete."
echo ""
echo "Project-level usage: .kimi/AGENTS.md and .kimi/skills/ are automatically"
echo "discovered when working in this repository."
echo ""
echo "Global usage: the skill and all commands are now available in all projects"
echo "via ~/.kimi/skills/."
echo ""
echo "NOTE: If you edit files in content/, run 'bash .kimi/build.sh' to regenerate"
echo "AGENTS.md and per-command skills. The global skill's symlinks will pick up"
echo "content changes instantly, but SKILL.md changes require re-running install.sh."
echo ""
echo "Invoke commands directly: /skill:<command-name>"
echo "   Examples: /skill:wrap    /skill:skeptic    /skill:implement-ticket"
echo "Or load the full skill: /skill:agentic-engineering <command-name>"
echo "Or just ask: 'run init-project'"
