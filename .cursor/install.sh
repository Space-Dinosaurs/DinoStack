#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------------------
# Activation mode (shared across all adapters - see .claude/install.sh)
# Persists to ~/.claude/agentic-engineering.json. Read by the skill preflight.
# ---------------------------------------------------------------------------

AE_MODE_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --mode=opt-in|--mode=opt-out) AE_MODE_FLAG="${arg#--mode=}" ;;
    --mode=*) echo "  ! ignoring unknown --mode value: ${arg#--mode=} (expected opt-in or opt-out)" ;;
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
  echo "    Override later with: bash .cursor/install.sh --mode=opt-in"
fi

RULES_SRC="$REPO_DIR/.cursor/rules"
REFS_SRC="$REPO_DIR/.cursor/rules/references"
COMMANDS_SRC="$REPO_DIR/.cursor/commands"
HOOKS_SRC="$REPO_DIR/.cursor/hooks.json"

RULES_DST="$HOME/.cursor/rules"
REFS_DST="$HOME/.cursor/rules/references"
COMMANDS_DST="$HOME/.cursor/commands"
HOOKS_DST="$HOME/.cursor/hooks.json"

installed_rules=()
skipped_rules=()
warned_rules=()
installed_refs=()
skipped_refs=()
warned_refs=()
installed_commands=()
skipped_commands=()
warned_commands=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
array_append() {
  local _arr="$1"
  local _item="$2"
  eval "${_arr}+=(\"\${_item}\")"
}

symlink_files() {
  local src_dir="$1"
  local dst_dir="$2"
  local label="$3"
  local pattern="$4"
  local suffix="$5"
  local installed_name="installed_${suffix}"
  local skipped_name="skipped_${suffix}"
  local warned_name="warned_${suffix}"

  if [[ ! -d "$src_dir" ]]; then
    echo "  [skip] $label source directory not found: $src_dir"
    return
  fi

  mkdir -p "$dst_dir"

  for src_file in "$src_dir"/$pattern; do
    [[ -e "$src_file" ]] || continue
    local name
    name="$(basename "$src_file")"
    local dst_file="$dst_dir/$name"

    if [[ -L "$dst_file" ]]; then
      local current_target
      current_target="$(readlink "$dst_file")"
      if [[ "$current_target" == "$src_file" ]]; then
        array_append "$skipped_name" "$name (already linked)"
        continue
      elif [[ "$current_target" == "$REPO_DIR"* ]]; then
        array_append "$skipped_name" "$name (already linked to agentic-engineering but different path: $current_target - skipping)"
        continue
      else
        array_append "$warned_name" "$name (symlink points elsewhere: $current_target - skipping)"
        continue
      fi
    elif [[ -e "$dst_file" ]]; then
      array_append "$warned_name" "$name (real file exists at destination - skipping)"
      continue
    fi

    ln -s "$src_file" "$dst_file"
    array_append "$installed_name" "$name"
  done
}

# ---------------------------------------------------------------------------
# Symlink rules (.mdc files)
# ---------------------------------------------------------------------------

echo "Linking rules..."
symlink_files "$RULES_SRC" "$RULES_DST" "rules" "*.mdc" rules

for f in "${installed_rules[@]+"${installed_rules[@]}"}"; do echo "  + $f"; done
for f in "${skipped_rules[@]+"${skipped_rules[@]}"}"; do echo "  = $f"; done
for f in "${warned_rules[@]+"${warned_rules[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Symlink reference docs (.md files in rules/references/)
# ---------------------------------------------------------------------------

echo "Linking reference docs..."
symlink_files "$REFS_SRC" "$REFS_DST" "references" "*.md" refs

for f in "${installed_refs[@]+"${installed_refs[@]}"}"; do echo "  + $f"; done
for f in "${skipped_refs[@]+"${skipped_refs[@]}"}"; do echo "  = $f"; done
for f in "${warned_refs[@]+"${warned_refs[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Symlink commands (.md files)
# ---------------------------------------------------------------------------

echo "Linking commands..."
symlink_files "$COMMANDS_SRC" "$COMMANDS_DST" "commands" "*.md" commands

for f in "${installed_commands[@]+"${installed_commands[@]}"}"; do echo "  + $f"; done
for f in "${skipped_commands[@]+"${skipped_commands[@]}"}"; do echo "  = $f"; done
for f in "${warned_commands[@]+"${warned_commands[@]}"}"; do echo "  ! $f"; done

# ---------------------------------------------------------------------------
# Run initial build
# ---------------------------------------------------------------------------

echo "Running initial build..."
[[ -f "$REPO_DIR/.claude/build.sh" ]] && bash "$REPO_DIR/.claude/build.sh"
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
# Copy hooks.json
# ---------------------------------------------------------------------------

echo "Installing hooks.json..."

if [[ -e "$HOOKS_DST" ]]; then
  echo "  ! $HOOKS_DST already exists - skipping to preserve your customizations."
  echo "    Manually merge entries from $HOOKS_SRC if needed."
else
  cp "$HOOKS_SRC" "$HOOKS_DST"
  echo "  + hooks.json copied to $HOOKS_DST"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Install complete."
echo "  Rules linked:    ${#installed_rules[@]}"
echo "  Refs linked:     ${#installed_refs[@]}"
echo "  Commands linked: ${#installed_commands[@]}"
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
