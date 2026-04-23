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
with open(path, "w") as f:
    json.dump({"mode": mode, "set_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}, f, indent=2)
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

# Copy SKILL.md so it survives branch switches
cp "$SKILL_SRC/SKILL.md" "$SKILL_DST/SKILL.md"
echo "  + SKILL.md copied to ~/.kimi/skills/agentic-engineering/"

# Absolute symlinks for content dirs so they resolve from ~/.kimi/skills/
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

link_abs "$REPO_DIR/content/commands"   "$SKILL_DST/commands"
link_abs "$REPO_DIR/content/references" "$SKILL_DST/references"
link_abs "$REPO_DIR/content/rules"      "$SKILL_DST/rules"
link_abs "$REPO_DIR/content/agents"     "$SKILL_DST/agents"

echo ""
echo "Kimi adapter install complete."
echo ""
echo "Project-level usage: .kimi/AGENTS.md and .kimi/skills/ are automatically"
echo "discovered when working in this repository."
echo ""
echo "Global usage: the skill is now available in all projects via ~/.kimi/skills/."
echo ""
echo "NOTE: If you edit files in content/, run 'bash .kimi/build.sh' to regenerate"
echo "AGENTS.md. The global skill's symlinks will pick up content changes instantly,"
echo "but SKILL.md changes require re-running install.sh."
echo ""
echo "IMPORTANT: Kimi does not support custom slash commands like /init-project."
echo "Invoke commands via: /skill:agentic-engineering <command-name>"
echo "   Example: /skill:agentic-engineering init-project"
echo "Or just ask: 'run init-project'"
