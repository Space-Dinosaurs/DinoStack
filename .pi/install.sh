#!/usr/bin/env bash
# Purpose: Install the native Pi coding agent adapter globally while keeping project-local discovery working.
# Public API: `bash .pi/install.sh [--mode=opt-in|--mode=opt-out] [--profile=relaxed|default|strict]`.
# Upstream deps: .pi/build.sh, ~/.pi/agent resource directories.
# Downstream consumers: Pi startup resource discovery.
# Failure modes: exits non-zero if build fails or destination conflicts with non-owned files.
# Performance: standard.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

AE_MODE_FLAG=""
AE_PROFILE_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --mode=opt-in|--mode=opt-out) AE_MODE_FLAG="${arg#--mode=}" ;;
    --mode=*) echo "  ! ignoring unknown --mode value: ${arg#--mode=} (expected opt-in or opt-out)" ;;
    --profile=relaxed|--profile=default|--profile=strict) AE_PROFILE_FLAG="${arg#--profile=}" ;;
    --profile=*) echo "  ! ignoring unknown --profile value: ${arg#--profile=} (expected relaxed, default, or strict)" ;;
  esac
done

echo "Building Pi coding agent adapter..."
bash "$REPO_DIR/.pi/build.sh"

AE_CONFIG_PATH="$HOME/.claude/agentic-engineering.json"
mkdir -p "$(dirname "$AE_CONFIG_PATH")"

json_get() {
  local key="$1"
  python3 - "$AE_CONFIG_PATH" "$key" <<'PY' 2>/dev/null || true
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    with open(path) as f:
        print(json.load(f).get(key, ""))
except Exception:
    print("")
PY
}

write_config() {
  local mode="$1"
  local profile="$2"
  python3 - "$AE_CONFIG_PATH" "$mode" "$profile" <<'PY'
import json, sys, os, datetime
path, mode, profile = sys.argv[1], sys.argv[2], sys.argv[3]
# Read existing config or start fresh
if os.path.exists(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
else:
    data = {}
# Always overwrite these keys
data["mode"] = mode
data["profile"] = profile
data["set_at"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
# skill_auto_load: preserve existing; prompt only on fresh install (key absent)
if "skill_auto_load" not in data:
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write("Auto-load agentic-engineering skill at session start? [y/N] ")
            tty.flush()
            answer = (tty.readline() or "").strip().lower()
        data["skill_auto_load"] = answer in ("y", "yes")
    except OSError:
        data["skill_auto_load"] = False
# Write back
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
}

existing_mode="$(json_get mode)"
existing_profile="$(json_get profile)"
mode="${existing_mode:-opt-out}"
profile="${existing_profile:-default}"

if [[ -n "$AE_MODE_FLAG" ]]; then
  mode="$AE_MODE_FLAG"
elif [[ -z "$existing_mode" && -t 0 ]]; then
  echo ""
  echo "Activation mode:"
  echo "  [1] opt-out (default) - active on every project unless AGENTS.md opts out"
  echo "  [2] opt-in           - dormant until AGENTS.md opts in"
  while true; do
    read -r -p "  Choice [1]: " choice
    choice="${choice:-1}"
    case "$choice" in
      1) mode="opt-out"; break ;;
      2) mode="opt-in"; break ;;
      *) echo "  ! please enter 1 or 2" ;;
    esac
  done
fi

if [[ -n "$AE_PROFILE_FLAG" ]]; then
  profile="$AE_PROFILE_FLAG"
fi
write_config "$mode" "$profile"
echo "  + activation config written to $AE_CONFIG_PATH (mode=$mode, profile=$profile)"

PI_HOME="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
SKILL_SRC="$REPO_DIR/.pi/skills/agentic-engineering"
SKILL_DST="$PI_HOME/skills/agentic-engineering"
PROMPT_SRC="$REPO_DIR/.pi/prompts"
PROMPT_DST="$PI_HOME/prompts"
EXT_SRC="$REPO_DIR/.pi/extensions/agentic-engineering"
EXT_DST="$PI_HOME/extensions/agentic-engineering"

mkdir -p "$SKILL_DST" "$PROMPT_DST" "$EXT_DST"
cp "$SKILL_SRC/SKILL.md" "$SKILL_DST/SKILL.md"
cp "$SKILL_SRC/METHODOLOGY.md" "$SKILL_DST/METHODOLOGY.md"
echo "  + skill files copied to $SKILL_DST"

link_abs() {
  local src="$1"
  local dst="$2"
  if [[ -L "$dst" ]]; then
    local current
    current="$(readlink "$dst")"
    if [[ "$current" == "$src" ]]; then
      echo "  = $(basename "$dst") (already linked)"
    elif [[ "$current" == "$REPO_DIR"/* ]]; then
      rm "$dst"
      ln -s "$src" "$dst"
      echo "  ~ $(basename "$dst") (re-linked)"
    else
      echo "  ! $(basename "$dst") exists as a symlink outside this repo - leaving it"
    fi
  elif [[ -e "$dst" ]]; then
    echo "install.sh: $dst exists and is not a symlink" >&2
    exit 1
  else
    ln -s "$src" "$dst"
    echo "  + $(basename "$dst")"
  fi
}

link_abs "$REPO_DIR/content/commands" "$SKILL_DST/commands"
link_abs "$REPO_DIR/content/references" "$SKILL_DST/references"
link_abs "$REPO_DIR/content/rules" "$SKILL_DST/rules"
link_abs "$REPO_DIR/content/agents" "$SKILL_DST/agents"

for src in "$PROMPT_SRC/"*.md; do
  name="$(basename "$src")"
  link_abs "$src" "$PROMPT_DST/$name"
done

link_abs "$EXT_SRC/index.ts" "$EXT_DST/index.ts"

echo ""
echo "Pi coding agent adapter install complete."
echo "Project-local: .pi/skills/ and .pi/prompts/ are auto-discovered in this repo."
echo "Global: skill installed to ~/.pi/agent/skills/, prompts linked to ~/.pi/agent/prompts/, and extension linked to ~/.pi/agent/extensions/."
echo "Use: pi, then /skill:agentic-engineering or slash prompts such as /brief and /wrap."
