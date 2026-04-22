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
# Global skill symlink (optional - project-level skills work automatically)
# ---------------------------------------------------------------------------

SKILL_SRC="$REPO_DIR/.kimi/skills/agentic-engineering"
SKILL_DST="$HOME/.kimi/skills/agentic-engineering"

echo ""
echo "Global skill install (optional)..."

mkdir -p "$(dirname "$SKILL_DST")"

if [[ -L "$SKILL_DST" ]]; then
  current_target="$(readlink "$SKILL_DST")"
  if [[ "$current_target" == "$SKILL_SRC" ]]; then
    echo "  = agentic-engineering (already linked in ~/.kimi/skills/)"
  else
    echo "  ! agentic-engineering (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$SKILL_DST" ]]; then
  echo "  ! agentic-engineering (real file/directory exists at ~/.kimi/skills/agentic-engineering - skipping)"
else
  ln -s "$SKILL_SRC" "$SKILL_DST"
  echo "  + agentic-engineering skill linked to ~/.kimi/skills/agentic-engineering"
fi

echo ""
echo "Kimi adapter install complete."
echo ""
echo "Project-level usage: .kimi/AGENTS.md and .kimi/skills/ are automatically"
echo "discovered when working in this repository."
echo ""
echo "Global usage: the skill is now available in all projects via ~/.kimi/skills/."
