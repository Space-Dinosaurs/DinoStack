#!/usr/bin/env bash
# Module: .copilot/install.sh
# Role: Install the VS Code Copilot adapter
# Inputs: .copilot/ source files; runs .copilot/build.sh to generate .github/ artifacts
# Outputs: symlinks at ~/.copilot/agents -> .github/agents,
#          ~/.copilot/prompts -> .github/prompts;
#          writes shared ~/.claude/agentic-engineering.json activation config;
#          links bin/agentic-* to ~/.local/bin;
#          prints the chat.hookFilesLocations VS Code setting snippet (user must add manually)
# Side-effects: creates ~/.copilot/ if absent; writes activation config
# Consumers: user runs manually; re-run after repo move to update absolute hook paths
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COPILOT_DIR="$REPO_DIR/.copilot"

# shellcheck source=scripts/lib/identity.sh
[[ -f "$REPO_DIR/scripts/lib/identity.sh" ]] && . "$REPO_DIR/scripts/lib/identity.sh" || {
  echo "  ! scripts/lib/identity.sh not found - identity setup skipped"
}

# ---------------------------------------------------------------------------
# Activation mode flags (shared across all adapters)
# Persists to ~/.claude/agentic-engineering.json. Read by the skill preflight.
# ---------------------------------------------------------------------------

AE_MODE_FLAG=""
AE_PROFILE_FLAG=""
AE_IDENTITY_FLAG=""
AE_NO_IDENTITY=false
for arg in "$@"; do
  case "$arg" in
    --mode=opt-in|--mode=opt-out) AE_MODE_FLAG="${arg#--mode=}" ;;
    --mode=*) echo "  ! ignoring unknown --mode value: ${arg#--mode=} (expected opt-in or opt-out)" ;;
    --profile=relaxed|--profile=default|--profile=strict) AE_PROFILE_FLAG="${arg#--profile=}" ;;
    --profile=*) echo "  ! ignoring unknown --profile value: ${arg#--profile=} (expected relaxed, default, or strict)" ;;
    --identity=*) AE_IDENTITY_FLAG="${arg#--identity=}" ;;
    --no-identity) AE_NO_IDENTITY=true ;;
  esac
done

AE_CONFIG_PATH="$HOME/.claude/agentic-engineering.json"
mkdir -p "$HOME/.claude"

AE_EXISTING_MODE=""
if [[ -f "$AE_CONFIG_PATH" ]]; then
  AE_EXISTING_MODE="$(python3 -c "
import json
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
if os.path.exists(path):
    try:
        with open(path) as f:
            config = json.load(f)
    except Exception:
        config = {}
else:
    config = {}
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
if os.path.exists(path):
    try:
        with open(path) as f:
            config = json.load(f)
    except Exception:
        config = {}
else:
    config = {}
config["mode"] = mode
config["profile"] = profile
config["set_at"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
if "skill_auto_load" not in config:
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write("Auto-load agentic-engineering skill at session start? [y/N] ")
            tty.flush()
            answer = (tty.readline() or "").strip().lower()
        config["skill_auto_load"] = answer in ("y", "yes")
    except OSError:
        config["skill_auto_load"] = False
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
    read -r -p "  Choice [1]: " AE_CHOICE
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
  echo "    Override later with: bash .copilot/install.sh --mode=opt-in"
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
  echo "    Override with: bash .copilot/install.sh --profile=relaxed|default|strict"
fi

# ---------------------------------------------------------------------------
# Step 1: Run build to ensure artifacts are up to date
# ---------------------------------------------------------------------------

echo ""
echo "Running build..."
bash "$COPILOT_DIR/build.sh"

# ---------------------------------------------------------------------------
# Step 2: Create ~/.copilot/ if needed and create symlinks
# ---------------------------------------------------------------------------

mkdir -p "$HOME/.copilot"

AGENTS_SRC="$REPO_DIR/.github/agents"
AGENTS_DST="$HOME/.copilot/agents"

PROMPTS_SRC="$REPO_DIR/.github/prompts"
PROMPTS_DST="$HOME/.copilot/prompts"

echo ""
echo "Linking ~/.copilot/agents -> .github/agents..."
if [[ -L "$AGENTS_DST" ]]; then
  current_target="$(readlink "$AGENTS_DST")"
  if [[ "$current_target" == "$AGENTS_SRC" ]]; then
    echo "  = ~/.copilot/agents (already linked)"
  else
    echo "  ! ~/.copilot/agents (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$AGENTS_DST" ]]; then
  BACKUP="${AGENTS_DST}.backup-$(date +%Y%m%d%H%M%S)"
  mv "$AGENTS_DST" "$BACKUP"
  ln -s "$AGENTS_SRC" "$AGENTS_DST"
  echo "  + ~/.copilot/agents linked (backup saved to $BACKUP)"
else
  ln -s "$AGENTS_SRC" "$AGENTS_DST"
  echo "  + ~/.copilot/agents -> $AGENTS_SRC"
fi

echo "Linking ~/.copilot/prompts -> .github/prompts..."
if [[ -L "$PROMPTS_DST" ]]; then
  current_target="$(readlink "$PROMPTS_DST")"
  if [[ "$current_target" == "$PROMPTS_SRC" ]]; then
    echo "  = ~/.copilot/prompts (already linked)"
  else
    echo "  ! ~/.copilot/prompts (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$PROMPTS_DST" ]]; then
  BACKUP="${PROMPTS_DST}.backup-$(date +%Y%m%d%H%M%S)"
  mv "$PROMPTS_DST" "$BACKUP"
  ln -s "$PROMPTS_SRC" "$PROMPTS_DST"
  echo "  + ~/.copilot/prompts linked (backup saved to $BACKUP)"
else
  ln -s "$PROMPTS_SRC" "$PROMPTS_DST"
  echo "  + ~/.copilot/prompts -> $PROMPTS_SRC"
fi

# ---------------------------------------------------------------------------
# Step 3: Link bin/ scripts to ~/.local/bin
# ---------------------------------------------------------------------------

ae_install_bins() {
  local bin_src="$REPO_DIR/bin"
  local bin_dst="$HOME/.local/bin"
  local path_created=false
  if [[ ! -d "$bin_src" ]]; then
    echo "  [skip] bin/ source directory not found: $bin_src"
    return
  fi
  if [[ ! -d "$bin_dst" ]]; then
    mkdir -p "$bin_dst"
    path_created=true
  fi
  for src_file in "$bin_src"/agentic-*; do
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
        ln -sfn "$src_file" "$dst_file"
        echo "  ~ $name (refreshed)"
      else
        echo "  ! $name (symlink points elsewhere - skipping)"
      fi
    elif [[ -e "$dst_file" ]]; then
      echo "  ! $name (real file at destination - skipping)"
    else
      ln -sfn "$src_file" "$dst_file"
      echo "  + $name"
    fi
  done
  if [[ "$path_created" == "true" ]]; then
    if [[ -t 0 ]] || [[ -r /dev/tty ]]; then
      echo ""
      echo "  Created ~/.local/bin and linked agentic binaries."
      echo "  Add this to your PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
  fi
}

echo ""
echo "Linking bin/ scripts to PATH..."
ae_install_bins

# ---------------------------------------------------------------------------
# Step 4: Developer identity
# ---------------------------------------------------------------------------

if declare -f _ae_setup_identity >/dev/null; then
  echo ""
  echo "Developer identity..."
  _ae_setup_identity
  echo "  Run 'agentic-identity show' to confirm your identity."
fi

# ---------------------------------------------------------------------------
# Summary and VS Code hooks configuration snippet
# ---------------------------------------------------------------------------

HOOKS_ABS="$REPO_DIR/.github/hooks"

echo ""
echo "Install complete."
echo ""
echo "What was installed:"
echo "  ~/.copilot/agents  -> $AGENTS_SRC"
echo "    Contains: Named agent markdown files (engineer, architect, debugger, etc.)"
echo ""
echo "  ~/.copilot/prompts -> $PROMPTS_SRC"
echo "    Contains: Slash-prompt files (implement-ticket, skeptic, wrap, etc.)"
echo ""
echo "  $REPO_DIR/.github/copilot-instructions.md"
echo "    Contains: Full agentic engineering methodology (auto-loaded by VS Code Copilot)"
echo ""
echo "  $REPO_DIR/.github/instructions/content-engineering.instructions.md"
echo "    Contains: Content authoring rules (scoped to content/**)"
echo ""
echo "=================================================================="
echo "ACTION REQUIRED: Add this to your VS Code settings.json"
echo "  (File > Preferences > Open User Settings (JSON))"
echo ""
echo '  "github.copilot.chat.hookFilesLocations": ["'"$HOOKS_ABS"'"]'
echo ""
echo "This enables three hooks:"
echo "  PreToolUse:    risk-reminder-copilot.sh  - risk classification reminder"
echo "  SessionStart:  session-start-copilot.sh  - load prior session context"
echo "  Stop:          stop-context-copilot.js   - save session context"
echo ""
echo "NOTE: Hooks require VS Code Copilot with the hooks Preview feature enabled."
echo "NOTE: If you move this repo, re-run bash .copilot/install.sh to update paths."
echo "=================================================================="
