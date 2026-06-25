#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

# shellcheck source=scripts/lib/identity.sh
[[ -f "$REPO_DIR/scripts/lib/identity.sh" ]] && . "$REPO_DIR/scripts/lib/identity.sh" || {
  echo "  ! scripts/lib/identity.sh not found - identity setup skipped"
}

# ---------------------------------------------------------------------------
# Run build first (generates agents/ and commands/ from content/)
# ---------------------------------------------------------------------------

echo "Building OpenCode adapter..."
bash "$REPO_DIR/.opencode/build.sh"

# ---------------------------------------------------------------------------
# Activation mode
# ---------------------------------------------------------------------------

AE_MODE_FLAG=""
AE_PROFILE_FLAG=""
AE_IDENTITY_FLAG=""
AE_NO_IDENTITY=false
AE_DRY_RUN=false
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
    --dry-run)
      AE_DRY_RUN=true
      ;;
  esac
done

AE_CONFIG_PATH="$HOME/.config/opencode/agentic-engineering.json"
mkdir -p "$HOME/.config/opencode"

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
  echo "    Override later with: bash .opencode/install.sh --mode=opt-in"
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
  echo "    Override with: bash .opencode/install.sh --profile=relaxed|default|strict"
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# _ae_is_ours DST
#   Returns 0 (true) iff DST is "ours to own" - i.e. safe to re-point.
#   A destination is ours iff:
#     - it IS a symlink (never touch real files), AND
#     - its current target is broken OR resolves under a methodology checkout
#       (path contains a component equal to "DinoStack" or ending with "-DinoStack").
_ae_is_ours() {
  local dst="$1"
  [[ -L "$dst" ]] || return 1
  local current_target
  current_target="$(readlink "$dst")"
  if [[ ! -e "$dst" ]]; then
    [[ "$current_target" == */DinoStack/* || "$current_target" == *-DinoStack/* ]] && return 0
    return 1
  fi
  [[ "$current_target" == */DinoStack/* || "$current_target" == *-DinoStack/* ]] && return 0
  return 1
}

symlink_files() {
  local src_dir="$1"
  local dst_dir="$2"
  local label="$3"
  local pattern="${4:-*.md}"

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
        echo "  = $name (already linked)"
        continue
      elif _ae_is_ours "$dst_file"; then
        # Stale symlink pointing to another methodology checkout - re-point it.
        if [[ "$AE_DRY_RUN" == "true" ]]; then
          echo "  ~ $name (would re-point to repo_dir)"
        else
          ln -sfn "$src_file" "$dst_file"
          echo "  ~ $name (re-pointed to repo_dir)"
        fi
        continue
      else
        if [[ "$AE_DRY_RUN" == "true" ]]; then
          echo "  ! $name (would skip: symlink points outside methodology checkout: $current_target)"
        else
          echo "  ! $name (symlink points elsewhere: $current_target - skipping)"
        fi
        continue
      fi
    elif [[ -e "$dst_file" ]]; then
      if [[ "$AE_DRY_RUN" == "true" ]]; then
        echo "  ! $name (would skip: real file exists at destination)"
      else
        echo "  ! $name (real file exists at destination - skipping)"
      fi
      continue
    fi

    if [[ "$AE_DRY_RUN" == "true" ]]; then
      echo "  ~ $name (would create)"
    else
      ln -s "$src_file" "$dst_file"
      echo "  + $name"
    fi
  done
}

# ---------------------------------------------------------------------------
# Symlink skill
# ---------------------------------------------------------------------------

echo "Linking skill: agentic-engineering..."

SKILLS_SRC="$REPO_DIR/.opencode/skills/agentic-engineering"
SKILLS_DST="$HOME/.config/opencode/skills/agentic-engineering"

mkdir -p "$(dirname "$SKILLS_DST")"

if [[ -L "$SKILLS_DST" ]]; then
  current_target="$(readlink "$SKILLS_DST")"
  if [[ "$current_target" == "$SKILLS_SRC" ]]; then
    echo "  = agentic-engineering (already linked)"
  elif _ae_is_ours "$SKILLS_DST"; then
    # Stale symlink pointing to another methodology checkout - re-point it.
    if [[ "$AE_DRY_RUN" == "true" ]]; then
      echo "  ~ agentic-engineering (would re-point to repo_dir)"
    else
      ln -sfn "$SKILLS_SRC" "$SKILLS_DST"
      echo "  ~ agentic-engineering (re-pointed to repo_dir)"
    fi
  else
    if [[ "$AE_DRY_RUN" == "true" ]]; then
      echo "  ! agentic-engineering (would skip: symlink points outside methodology checkout: $current_target)"
    else
      echo "  ! agentic-engineering (symlink points elsewhere: $current_target - skipping)"
    fi
  fi
elif [[ -e "$SKILLS_DST" ]]; then
  echo "  ! agentic-engineering (real file/directory exists at destination - skipping)"
else
  if [[ "$AE_DRY_RUN" == "true" ]]; then
    echo "  + agentic-engineering (would create)"
  else
    ln -s "$SKILLS_SRC" "$SKILLS_DST"
    echo "  + agentic-engineering"
  fi
fi

# ---------------------------------------------------------------------------
# Symlink agents
# ---------------------------------------------------------------------------

echo "Linking agents..."
symlink_files "$REPO_DIR/.opencode/agents" "$HOME/.config/opencode/agents" "agents"

# ---------------------------------------------------------------------------
# Symlink commands
# ---------------------------------------------------------------------------

echo "Linking commands..."
symlink_files "$REPO_DIR/.opencode/commands" "$HOME/.config/opencode/commands" "commands"

# ---------------------------------------------------------------------------
# Symlink plugins
# ---------------------------------------------------------------------------

echo "Linking plugins..."

PLUGINS_SRC="$REPO_DIR/.opencode/plugins"
PLUGINS_DST="$HOME/.config/opencode/plugins"

# Route plugins through symlink_files; call once per extension because the
# helper's glob expansion does not handle brace patterns.
symlink_files "$PLUGINS_SRC" "$PLUGINS_DST" "plugins" "*.js"
symlink_files "$PLUGINS_SRC" "$PLUGINS_DST" "plugins" "*.ts"

# ---------------------------------------------------------------------------
# Update ~/.config/opencode/AGENTS.md with skill loading signal
# ---------------------------------------------------------------------------

echo "Updating ~/.config/opencode/AGENTS.md..."

python3 - <<'PYEOF'
import os, re

target = os.path.expanduser("~/.config/opencode/AGENTS.md")
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
    print("  = Updated managed-by-agentic-engineering section in ~/.config/opencode/AGENTS.md")
else:
    if existing:
        updated = existing.rstrip("\n") + "\n\n" + managed_content + "\n"
    else:
        updated = managed_content + "\n"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write(updated)
    if existing:
        print("  + Appended managed-by-agentic-engineering section to ~/.config/opencode/AGENTS.md")
    else:
        print("  + Created ~/.config/opencode/AGENTS.md with managed-by-agentic-engineering section")
PYEOF

# ---------------------------------------------------------------------------
# Configure opencode permissions
# ---------------------------------------------------------------------------

echo "Configuring opencode permissions..."

python3 - <<'PYEOF'
import json, os

config_path = os.path.expanduser("~/.config/opencode/opencode.json")
repo_dir = os.environ.get("REPO_DIR", "")

if os.path.exists(config_path):
    with open(config_path, "r") as f:
        config = json.load(f)
else:
    config = {"$schema": "https://opencode.ai/config.json"}

config.setdefault("permission", {})

# Allow the agentic-engineering skill
config["permission"].setdefault("skill", {})
config["permission"]["skill"]["agentic-engineering"] = "allow"

# Allow agents to spawn agentic-engineering subagents
config["permission"].setdefault("task", {})
config["permission"]["task"]["*"] = "allow"

# Allow external directory access to the agentic-engineering repo
config["permission"].setdefault("external_directory", {})
ae_path = repo_dir + "/**"
config["permission"]["external_directory"][ae_path] = "allow"

# Add instructions pointing to the rules files
instructions = config.get("instructions", [])
rules_files = [
    repo_dir + "/.opencode/skills/agentic-engineering/METHODOLOGY.md",
    repo_dir + "/content/rules/code-standards.md",
    repo_dir + "/content/rules/conventions.md",
    repo_dir + "/content/rules/module-manifest.md",
]
for rf in rules_files:
    if rf not in instructions:
        instructions.append(rf)
config["instructions"] = instructions

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")

print("  + Configured opencode.json with skill permissions, external directory access, and rule instructions")
PYEOF

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
  elif _ae_is_ours "$HOOK_DST"; then
    # Stale symlink pointing to another methodology checkout - re-point it.
    if [[ "$AE_DRY_RUN" == "true" ]]; then
      echo "  ~ pre-commit hook (would re-point to repo_dir)"
    else
      ln -sfn "$HOOK_SRC" "$HOOK_DST"
      echo "  ~ pre-commit hook (re-pointed to repo_dir)"
    fi
  else
    if [[ "$AE_DRY_RUN" == "true" ]]; then
      echo "  ! pre-commit hook (would skip: symlink points outside methodology checkout: $current_target)"
    else
      echo "  ! pre-commit hook points elsewhere: $current_target - skipping"
    fi
  fi
elif [[ -e "$HOOK_DST" ]]; then
  echo "  ! pre-commit hook is a real file (not a symlink) - skipping to preserve existing hook"
else
  if [[ "$AE_DRY_RUN" == "true" ]]; then
    echo "  + pre-commit hook (would create)"
  else
    ln -s "$HOOK_SRC" "$HOOK_DST"
    echo "  + pre-commit hook installed"
  fi
fi

# ---------------------------------------------------------------------------
# Symlink bin/ scripts to ~/.local/bin
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

echo "Linking bin/ scripts to PATH..."
ae_install_bins

# ---------------------------------------------------------------------------
# Developer identity
# ---------------------------------------------------------------------------
if declare -f _ae_setup_identity >/dev/null; then
  echo ""
  echo "Developer identity..."
  _ae_setup_identity
  echo "  Run 'agentic-identity show' to confirm your identity."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "OpenCode adapter install complete."
echo ""
echo "Installed to:"
echo "  ~/.config/opencode/skills/agentic-engineering/ -> $REPO_DIR/.opencode/skills/agentic-engineering/"
echo "  ~/.config/opencode/agents/ -> $REPO_DIR/.opencode/agents/"
echo "  ~/.config/opencode/commands/ -> $REPO_DIR/.opencode/commands/"
echo "  ~/.config/opencode/plugins/ -> $REPO_DIR/.opencode/plugins/"
echo ""
echo "Configuration updated:"
echo "  ~/.config/opencode/opencode.json (permissions, instructions)"
echo "  ~/.config/opencode/AGENTS.md (skill loading signal)"