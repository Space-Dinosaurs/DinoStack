#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

# shellcheck source=scripts/lib/identity.sh
[[ -f "$REPO_DIR/scripts/lib/identity.sh" ]] && . "$REPO_DIR/scripts/lib/identity.sh" || {
  echo "  ! scripts/lib/identity.sh not found - identity setup skipped"
}

# ---------------------------------------------------------------------------
# Activation mode
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

AE_CONFIG_PATH="$HOME/.hermes/agentic-engineering.json"
mkdir -p "$HOME/.hermes"

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
data = {"mode": mode, "profile": profile, "set_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
with open(path, "w") as f:
    json.dump(data, f, indent=2)
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
echo "agentic-engineering Hermes adapter installer"
echo "============================================"
echo ""

echo "Activation mode..."
if [[ -n "$AE_MODE_FLAG" ]]; then
  ae_write_mode "$AE_MODE_FLAG"
  echo "  + mode set to '$AE_MODE_FLAG' via --mode flag (wrote $AE_CONFIG_PATH)"
elif [[ -n "$AE_EXISTING_MODE" ]]; then
  echo "  = mode already set to '$AE_EXISTING_MODE' (keeping $AE_CONFIG_PATH)"
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
  echo "    Override later with: bash .hermes/install.sh --mode=opt-in"
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
  echo "    Override with: bash .hermes/install.sh --profile=relaxed|default|strict"
fi

# ---------------------------------------------------------------------------
# Build artifacts if needed
# ---------------------------------------------------------------------------

echo ""
echo "Building skill artifacts..."
if [[ -x "$REPO_DIR/.hermes/build.sh" ]]; then
  bash "$REPO_DIR/.hermes/build.sh"
else
  echo "  ! build.sh not found or not executable at $REPO_DIR/.hermes/build.sh"
  exit 1
fi

# ---------------------------------------------------------------------------
# Install skill
# ---------------------------------------------------------------------------

SKILL_DST="$HOME/.hermes/skills/agentic-engineering"
SKILL_SRC="$REPO_DIR/.hermes/SKILL.md"

echo ""
echo "Installing skill..."

mkdir -p "$SKILL_DST"

# Remove old symlink or file if present
if [[ -L "$SKILL_DST/SKILL.md" ]]; then
  rm "$SKILL_DST/SKILL.md"
elif [[ -f "$SKILL_DST/SKILL.md" ]]; then
  mv "$SKILL_DST/SKILL.md" "$SKILL_DST/SKILL.md.backup-$(date +%s)"
  echo "  = backed up existing SKILL.md to SKILL.md.backup-*"
fi

ln -s "$SKILL_SRC" "$SKILL_DST/SKILL.md"
echo "  + symlinked $SKILL_DST/SKILL.md -> $SKILL_SRC"

# ---------------------------------------------------------------------------
# Developer identity
# ---------------------------------------------------------------------------
if declare -f _ae_setup_identity >/dev/null; then
  echo ""
  echo "Developer identity..."
  _ae_setup_identity
  echo "  Run 'agentic-identity show' to confirm your identity."
  echo "  (agentic-identity binaries are wired by other adapters e.g. .claude or .codex."
  echo "   If not on PATH, run 'agentic-identity init <handle>' after installing another adapter.)"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
echo "Installation complete!"
echo ""
echo "The agentic-engineering skill is now available to Hermes."
echo ""
echo "To verify, start a Hermes session in any project and ask:"
echo '  "What are the risk tiers in agentic engineering?"'
echo ""
echo "The skill auto-loads when tags match. You can also force-load it with:"
echo '  skill_view(name="agentic-engineering")'
echo ""
echo "Per-project opt-in/opt-out: add to the project's root AGENTS.md:"
echo "  agentic-engineering: opt-out"
echo "  agentic-engineering: opt-in"
echo ""
