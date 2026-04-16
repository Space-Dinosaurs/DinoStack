#!/usr/bin/env bash
# Module: .gemini/install.sh
# Role: Install the Gemini CLI adapter into ~/.gemini/
# Inputs: .gemini/ build artifacts (GEMINI.md, commands/, agents/, hooks/)
# Outputs: symlinks at ~/.gemini/GEMINI.md, ~/.gemini/commands/, ~/.gemini/agents/;
#          hooks block merged into ~/.gemini/settings.json
# Side-effects: backs up existing non-symlink targets with .backup-<timestamp> suffix;
#               creates ~/.gemini/ if absent
# Consumers: user runs manually; re-run after repo move to update absolute hook paths
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GEMINI_DIR="$REPO_DIR/.gemini"

GEMINI_MD_SRC="$GEMINI_DIR/GEMINI.md"
GEMINI_MD_DST="$HOME/.gemini/GEMINI.md"

COMMANDS_SRC="$GEMINI_DIR/commands"
COMMANDS_DST="$HOME/.gemini/commands"

AGENTS_SRC="$GEMINI_DIR/agents"
AGENTS_DST="$HOME/.gemini/agents"

SETTINGS="$HOME/.gemini/settings.json"

# Absolute path to hooks directory - computed at install time.
# Hook commands embed this path so they work regardless of the working directory
# at hook invocation time (which is the user's project dir, not this repo root).
GEMINI_HOOKS_DIR="$GEMINI_DIR/hooks"

# ---------------------------------------------------------------------------
# Step 1: Run build to ensure artifacts are up to date
# ---------------------------------------------------------------------------

echo "Running build..."
bash "$GEMINI_DIR/build.sh"

# ---------------------------------------------------------------------------
# Step 2: Create ~/.gemini/ if it does not exist
# ---------------------------------------------------------------------------

mkdir -p "$HOME/.gemini"

# ---------------------------------------------------------------------------
# Step 3: Symlink ~/.gemini/GEMINI.md
# ---------------------------------------------------------------------------

echo "Linking global GEMINI.md..."

if [[ -L "$GEMINI_MD_DST" ]]; then
  current_target="$(readlink "$GEMINI_MD_DST")"
  if [[ "$current_target" == "$GEMINI_MD_SRC" ]]; then
    echo "  = ~/.gemini/GEMINI.md (already linked)"
  else
    echo "  ! ~/.gemini/GEMINI.md (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$GEMINI_MD_DST" ]]; then
  BACKUP="$GEMINI_MD_DST.backup-$(date +%Y%m%d%H%M%S)"
  echo ""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "  WARNING: ~/.gemini/GEMINI.md already exists and is NOT a symlink."
  echo "  Backing it up to: $BACKUP"
  echo "  The existing file will be REPLACED with the agentic-engineering symlink."
  echo "  To restore: cp \"$BACKUP\" \"$GEMINI_MD_DST\""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo ""
  mv "$GEMINI_MD_DST" "$BACKUP"
  ln -s "$GEMINI_MD_SRC" "$GEMINI_MD_DST"
  echo "  + ~/.gemini/GEMINI.md linked (backup saved to $BACKUP)"
else
  ln -s "$GEMINI_MD_SRC" "$GEMINI_MD_DST"
  echo "  + ~/.gemini/GEMINI.md linked to $GEMINI_MD_SRC"
fi

# ---------------------------------------------------------------------------
# Step 4: Symlink ~/.gemini/commands/
# ---------------------------------------------------------------------------

echo "Linking commands directory..."

if [[ -L "$COMMANDS_DST" ]]; then
  current_target="$(readlink "$COMMANDS_DST")"
  if [[ "$current_target" == "$COMMANDS_SRC" ]]; then
    echo "  = ~/.gemini/commands/ (already linked)"
  else
    echo "  ! ~/.gemini/commands/ (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$COMMANDS_DST" ]]; then
  BACKUP="${COMMANDS_DST}.backup-$(date +%Y%m%d%H%M%S)"
  echo ""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "  WARNING: ~/.gemini/commands/ already exists and is NOT a symlink."
  echo "  Backing it up to: $BACKUP"
  echo "  The existing directory will be REPLACED with the agentic-engineering symlink."
  echo "  To restore: mv \"$BACKUP\" \"$COMMANDS_DST\""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo ""
  mv "$COMMANDS_DST" "$BACKUP"
  ln -s "$COMMANDS_SRC" "$COMMANDS_DST"
  echo "  + ~/.gemini/commands/ linked (backup saved to $BACKUP)"
else
  ln -s "$COMMANDS_SRC" "$COMMANDS_DST"
  echo "  + ~/.gemini/commands/ linked to $COMMANDS_SRC"
fi

# ---------------------------------------------------------------------------
# Step 5: Symlink ~/.gemini/agents/
# ---------------------------------------------------------------------------

echo "Linking agents directory..."

if [[ -L "$AGENTS_DST" ]]; then
  current_target="$(readlink "$AGENTS_DST")"
  if [[ "$current_target" == "$AGENTS_SRC" ]]; then
    echo "  = ~/.gemini/agents/ (already linked)"
  else
    echo "  ! ~/.gemini/agents/ (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$AGENTS_DST" ]]; then
  BACKUP="${AGENTS_DST}.backup-$(date +%Y%m%d%H%M%S)"
  echo ""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "  WARNING: ~/.gemini/agents/ already exists and is NOT a symlink."
  echo "  Backing it up to: $BACKUP"
  echo "  The existing directory will be REPLACED with the agentic-engineering symlink."
  echo "  To restore: mv \"$BACKUP\" \"$AGENTS_DST\""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo ""
  mv "$AGENTS_DST" "$BACKUP"
  ln -s "$AGENTS_SRC" "$AGENTS_DST"
  echo "  + ~/.gemini/agents/ linked (backup saved to $BACKUP)"
else
  ln -s "$AGENTS_SRC" "$AGENTS_DST"
  echo "  + ~/.gemini/agents/ linked to $AGENTS_SRC"
fi

# ---------------------------------------------------------------------------
# Step 6: Configure hooks in ~/.gemini/settings.json
#
# Merges BeforeAgent (risk reminder) and SessionEnd (context save) hook entries
# into settings.json without clobbering unrelated user settings.
# Absolute paths to hook scripts are embedded at install time.
# ---------------------------------------------------------------------------

echo "Configuring hooks in ~/.gemini/settings.json..."

HOOKS_DIR_FOR_PYTHON="$GEMINI_HOOKS_DIR"

python3 - "$SETTINGS" "$HOOKS_DIR_FOR_PYTHON" <<'PYEOF'
import json, os, sys

settings_path = sys.argv[1]
hooks_dir = sys.argv[2]

# Read existing settings
if os.path.exists(settings_path):
    with open(settings_path, "r") as f:
        try:
            settings = json.load(f)
        except json.JSONDecodeError:
            settings = {}
else:
    settings = {}

hooks = settings.setdefault("hooks", {})

# ---- BeforeAgent hook (risk reminder) ----------------------------------------
RISK_CMD = f'bash "{hooks_dir}/risk-reminder.sh"'

ba_list = hooks.setdefault("BeforeAgent", [])

# Find or create a matcher "*" block
ba_star = None
for block in ba_list:
    if block.get("matcher") == "*":
        ba_star = block
        break

if ba_star is None:
    ba_star = {"matcher": "*", "hooks": []}
    ba_list.append(ba_star)

ba_star.setdefault("hooks", [])

already_has_risk = any(
    entry.get("name") == "risk-reminder" or
    ("risk-reminder.sh" in entry.get("command", "") and "agentic-engineering" in entry.get("command", ""))
    for entry in ba_star["hooks"]
)

if already_has_risk:
    print("  = BeforeAgent risk-reminder hook already present")
else:
    ba_star["hooks"].append({
        "name": "risk-reminder",
        "type": "command",
        "command": RISK_CMD
    })
    print(f"  + Added BeforeAgent risk-reminder hook: {RISK_CMD}")

# ---- SessionEnd hook (context save) ------------------------------------------
STOP_CMD = f'node "{hooks_dir}/stop-context-gemini.js"'

se_list = hooks.setdefault("SessionEnd", [])

# Find or create a matcher "exit" block
se_exit = None
for block in se_list:
    if block.get("matcher") == "exit":
        se_exit = block
        break

if se_exit is None:
    se_exit = {"matcher": "exit", "hooks": []}
    se_list.append(se_exit)

se_exit.setdefault("hooks", [])

already_correct = False
replaced = False
for entry in se_exit["hooks"]:
    cmd = entry.get("command", "")
    if "stop-context-gemini.js" in cmd:
        if "agentic-engineering" in cmd:
            already_correct = True
        else:
            entry["command"] = STOP_CMD
            replaced = True
        break

if already_correct:
    print("  = SessionEnd hook already points to correct stop-context-gemini.js")
elif replaced:
    print(f"  ~ Replaced SessionEnd hook with: {STOP_CMD}")
else:
    se_exit["hooks"].append({
        "name": "stop-context",
        "type": "command",
        "command": STOP_CMD
    })
    print(f"  + Added SessionEnd hook: {STOP_CMD}")

# ---- Write back --------------------------------------------------------------
os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print("  settings.json written.")
PYEOF

# ---------------------------------------------------------------------------
# Step 7: Write tier-map defaults for Gemini if not already present
# ---------------------------------------------------------------------------

mkdir -p "$HOME/.agentic"
TIER_MAP="$HOME/.agentic/tier-map.yml"
if [ ! -f "$TIER_MAP" ]; then
  cat > "$TIER_MAP" << 'TIEREOF'
# Provider tier maps for cost-aware routing
# Tier 1 = cheap/fast, Tier 2 = balanced, Tier 3 = max capability
gemini:
  tiers:
    1: gemini-2.0-flash
    2: gemini-2.0-pro
    3: gemini-ultra-2
TIEREOF
  echo "Created $TIER_MAP with Gemini defaults"
elif ! grep -q "^gemini:" "$TIER_MAP"; then
  cat >> "$TIER_MAP" << 'TIEREOF'

gemini:
  tiers:
    1: gemini-2.0-flash
    2: gemini-2.0-pro
    3: gemini-ultra-2
TIEREOF
  echo "Added Gemini section to $TIER_MAP"
else
  echo "Gemini section already present in $TIER_MAP"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Install complete."
echo ""
echo "What was installed:"
echo "  ~/.gemini/GEMINI.md  -> $GEMINI_MD_SRC"
echo "    Contains: Full agentic engineering methodology (loaded globally by Gemini CLI)"
echo ""
echo "  ~/.gemini/commands/  -> $COMMANDS_SRC"
echo "    Contains: TOML slash-command files (skeptic, implement-ticket, wrap, etc.)"
echo ""
echo "  ~/.gemini/agents/  -> $AGENTS_SRC"
echo "    Contains: Named agent markdown files (engineer, architect, debugger, etc.)"
echo ""
echo "  ~/.gemini/settings.json"
echo "    Updated: BeforeAgent (risk reminder) and SessionEnd (context save) hooks"
echo "    Hook scripts: $GEMINI_HOOKS_DIR/"
echo ""
echo "IMPORTANT - repo-move constraint:"
echo "  Hook commands in ~/.gemini/settings.json embed absolute paths to:"
echo "    $GEMINI_HOOKS_DIR/"
echo "  If you move the repo, re-run .gemini/install.sh to update these paths."
echo ""
echo "Next steps:"
echo "  1. Open Gemini CLI in a project directory."
echo "  2. ~/.gemini/GEMINI.md loads the methodology globally in every session."
echo "  3. Run /commands reload to activate slash commands."
echo "  4. Spawn named agents via @agent-name (e.g., @engineer, @architect)."
echo "  5. Risk reminder fires automatically before each prompt (BeforeAgent hook)."
echo "  6. Session context saved to ~/.gemini/projects/[hash]/context.md on /exit."
echo "  7. See .gemini/README.md for full documentation."
