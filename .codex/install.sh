#!/usr/bin/env bash
# Module: .codex/install.sh
# Role: Install the Codex CLI adapter into ~/.codex/ and ~/.agents/skills/
# Inputs: .codex/ build artifacts (AGENTS.md, agents/, skill/), .codex/config/hooks.json
# Outputs: symlinks at ~/.agents/skills/agentic-engineering, ~/.codex/AGENTS.md,
#          ~/.codex/agents/; ~/.codex/hooks.json symlinked to the session-stable
#          hooks snapshot (DS-54, scripts/lib/hooks-snapshot.sh) when sync
#          succeeds, else the checkout's .codex/config/hooks.json; codex_hooks
#          feature flag ensured in ~/.codex/config.toml
# Side-effects: backs up existing non-symlink targets with .backup-<timestamp>
#               suffix; syncs the hooks snapshot dir; may append to config.toml
# Consumers: user runs manually; re-run after repo move (or to refresh the
#            hooks snapshot) to update absolute hook paths
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

# shellcheck source=scripts/lib/identity.sh
[[ -f "$REPO_DIR/scripts/lib/identity.sh" ]] && . "$REPO_DIR/scripts/lib/identity.sh" || {
  echo "  ! scripts/lib/identity.sh not found - identity setup skipped"
}

# ---------------------------------------------------------------------------
# Activation mode (shared across all adapters - see .claude/install.sh)
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
  echo "    Override later with: bash .codex/install.sh --mode=opt-in"
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
  echo "    Override with: bash .codex/install.sh --profile=relaxed|default|strict"
fi

SKILL_SRC="$REPO_DIR/.codex/skill"
SKILL_DST="$HOME/.agents/skills/agentic-engineering"
OLD_SKILL_DST="$HOME/.codex/skills/agentic-engineering"

AGENTS_SRC="$REPO_DIR/.codex/AGENTS.md"
AGENTS_DST="$HOME/.codex/AGENTS.md"

NAMED_AGENTS_SRC="$REPO_DIR/.codex/agents"
NAMED_AGENTS_DST="$HOME/.codex/agents"

# ---------------------------------------------------------------------------
# Run build to ensure artifacts are up to date
# ---------------------------------------------------------------------------

echo "Running build..."
bash "$REPO_DIR/.codex/build.sh"

# ---------------------------------------------------------------------------
# Clean up old (incorrect) skill symlink at ~/.codex/skills/agentic-engineering/
# The correct path per Codex docs is ~/.agents/skills/<name>/, not ~/.codex/skills/.
# ---------------------------------------------------------------------------

if [[ -L "$OLD_SKILL_DST" ]]; then
  old_target="$(readlink "$OLD_SKILL_DST")"
  if [[ "$old_target" == "$SKILL_SRC" ]]; then
    rm "$OLD_SKILL_DST"
    echo "  - Removed stale symlink at $OLD_SKILL_DST (was pointing to $SKILL_SRC)"
  else
    echo "  ! $OLD_SKILL_DST points to $old_target (not ours - leaving it)"
  fi
elif [[ -e "$OLD_SKILL_DST" ]]; then
  echo "  ! Real file/directory at $OLD_SKILL_DST - not removing (manual cleanup may be needed)"
fi

# ---------------------------------------------------------------------------
# Symlink the agentic-engineering skill into ~/.agents/skills/
# Per Codex docs: user-scope skills load from $HOME/.agents/skills/<name>/SKILL.md
# ---------------------------------------------------------------------------

echo "Linking skill: agentic-engineering..."

mkdir -p "$(dirname "$SKILL_DST")"

if [[ -L "$SKILL_DST" ]]; then
  current_target="$(readlink "$SKILL_DST")"
  if [[ "$current_target" == "$SKILL_SRC" ]]; then
    echo "  = agentic-engineering (already linked)"
  else
    echo "  ! agentic-engineering (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$SKILL_DST" ]]; then
  echo "  ! agentic-engineering (real file/directory exists at destination - skipping)"
else
  ln -s "$SKILL_SRC" "$SKILL_DST"
  echo "  + agentic-engineering skill linked to $SKILL_DST"
fi

# ---------------------------------------------------------------------------
# Symlink ~/.codex/AGENTS.md to .codex/AGENTS.md
# Per Codex docs: global scope loads ~/.codex/AGENTS.md
# ---------------------------------------------------------------------------

echo "Linking global AGENTS.md..."

mkdir -p "$HOME/.codex"

if [[ -L "$AGENTS_DST" ]]; then
  current_target="$(readlink "$AGENTS_DST")"
  if [[ "$current_target" == "$AGENTS_SRC" ]]; then
    echo "  = ~/.codex/AGENTS.md (already linked)"
  else
    echo "  ! ~/.codex/AGENTS.md (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$AGENTS_DST" ]]; then
  BACKUP="$AGENTS_DST.backup-$(date +%Y%m%d%H%M%S)"
  echo ""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "  WARNING: ~/.codex/AGENTS.md already exists and is NOT a symlink."
  echo "  Backing it up to: $BACKUP"
  echo "  The existing file will be REPLACED with the agentic-engineering symlink."
  echo "  To restore: cp \"$BACKUP\" \"$AGENTS_DST\""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo ""
  mv "$AGENTS_DST" "$BACKUP"
  ln -s "$AGENTS_SRC" "$AGENTS_DST"
  echo "  + ~/.codex/AGENTS.md linked (backup saved to $BACKUP)"
else
  ln -s "$AGENTS_SRC" "$AGENTS_DST"
  echo "  + ~/.codex/AGENTS.md linked to $AGENTS_SRC"
fi

# ---------------------------------------------------------------------------
# Symlink ~/.codex/agents/ to .codex/agents/ (named agent TOML files)
# Per Codex docs: personal named agents load from ~/.codex/agents/<name>.toml
# ---------------------------------------------------------------------------

echo "Linking named agents directory..."

mkdir -p "$(dirname "$NAMED_AGENTS_DST")"

if [[ -L "$NAMED_AGENTS_DST" ]]; then
  current_target="$(readlink "$NAMED_AGENTS_DST")"
  if [[ "$current_target" == "$NAMED_AGENTS_SRC" ]]; then
    echo "  = ~/.codex/agents/ (already linked)"
  else
    echo "  ! ~/.codex/agents/ (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$NAMED_AGENTS_DST" ]]; then
  BACKUP="${NAMED_AGENTS_DST}.backup-$(date +%Y%m%d%H%M%S)"
  echo ""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "  WARNING: ~/.codex/agents/ already exists and is NOT a symlink."
  echo "  Backing it up to: $BACKUP"
  echo "  The existing directory will be REPLACED with the agentic-engineering symlink."
  echo "  To restore: mv \"$BACKUP\" \"$NAMED_AGENTS_DST\""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo ""
  mv "$NAMED_AGENTS_DST" "$BACKUP"
  ln -s "$NAMED_AGENTS_SRC" "$NAMED_AGENTS_DST"
  echo "  + ~/.codex/agents/ linked (backup saved to $BACKUP)"
else
  ln -s "$NAMED_AGENTS_SRC" "$NAMED_AGENTS_DST"
  echo "  + ~/.codex/agents/ linked to $NAMED_AGENTS_SRC"
fi

# ---------------------------------------------------------------------------
# Hook snapshot (DS-54)
#
# Copies hooks/ + the four in-scope adapters' hook sources into a
# per-checkout snapshot dir at $HOME/.agentic/hooks-snapshot/<key>/, so a
# bare `git pull` cannot silently rewire a live session's hook commands.
# Graceful degradation: any failure here leaves AE_HOOKS_SNAPSHOT_DIR unset
# and AE_HOOKS_ROOT falls back to the checkout ($REPO_DIR).
# ---------------------------------------------------------------------------

echo "Syncing hooks snapshot..."

AE_HOOKS_SNAPSHOT_DIR=""
if [[ -f "$REPO_DIR/scripts/lib/hooks-snapshot.sh" ]]; then
  # shellcheck source=scripts/lib/hooks-snapshot.sh
  if . "$REPO_DIR/scripts/lib/hooks-snapshot.sh" 2>/dev/null; then
    if ! sync_hooks_snapshot "$REPO_DIR"; then
      AE_HOOKS_SNAPSHOT_DIR=""
      echo "  ! hooks snapshot sync failed - hooks will read from the checkout (non-fatal)"
    fi
  else
    echo "  ! failed to source scripts/lib/hooks-snapshot.sh - hooks will read from the checkout (non-fatal)"
  fi
else
  echo "  [skip] scripts/lib/hooks-snapshot.sh not found - hooks will read from the checkout"
fi
export AE_HOOKS_SNAPSHOT_DIR
AE_HOOKS_ROOT="${AE_HOOKS_SNAPSHOT_DIR:-$REPO_DIR}"

# DS-54: HOOKS_SRC is rooted at the hooks snapshot when one was successfully
# synced, else the checkout (identical to the pre-DS-54 value). The embedded
# command strings inside .codex/config/hooks.json are unchanged - they derive
# their own hook-script root at runtime via
# dirname(dirname(realpath($HOME/.codex/hooks.json))), which resolves to the
# snapshot automatically once HOOKS_DST is re-pointed below.
HOOKS_SRC="$AE_HOOKS_ROOT/.codex/config/hooks.json"
# Both LEGACY_HOOKS_SRC candidates are checkout paths: the original
# pre-migration ~/.codex/hooks.json target, and (DS-54) the checkout's own
# .codex/config/hooks.json, which is now legacy too since the correct target
# moved to the snapshot.
LEGACY_HOOKS_SRC="$REPO_DIR/.codex/hooks.json"
LEGACY_HOOKS_SRC2="$REPO_DIR/.codex/config/hooks.json"
HOOKS_DST="$HOME/.codex/hooks.json"

CONFIG_FILE="$HOME/.codex/config.toml"

canonicalize_path() {
  python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"
}

# ---------------------------------------------------------------------------
# Symlink ~/.codex/hooks.json to the non-auto-discovered source file in
# .codex/config/. Keeping the canonical source out of .codex/hooks.json avoids
# double registration when developing agentic-engineering inside this repo.
# ---------------------------------------------------------------------------

echo "Linking hooks.json..."

if [[ -L "$HOOKS_DST" ]]; then
  current_target="$(readlink "$HOOKS_DST")"
  current_target_canonical="$(canonicalize_path "$current_target")"
  hooks_src_canonical="$(canonicalize_path "$HOOKS_SRC")"
  legacy_hooks_src_canonical="$(canonicalize_path "$LEGACY_HOOKS_SRC")"
  legacy_hooks_src2_canonical="$(canonicalize_path "$LEGACY_HOOKS_SRC2")"
  if [[ "$current_target_canonical" == "$hooks_src_canonical" ]]; then
    echo "  = ~/.codex/hooks.json (already linked)"
  elif [[ "$current_target_canonical" == "$legacy_hooks_src_canonical" || "$current_target_canonical" == "$legacy_hooks_src2_canonical" ]]; then
    rm "$HOOKS_DST"
    ln -s "$HOOKS_SRC" "$HOOKS_DST"
    echo "  + ~/.codex/hooks.json migrated from legacy source to $HOOKS_SRC"
  else
    echo "  ! ~/.codex/hooks.json (symlink points elsewhere: $current_target - skipping)"
  fi
elif [[ -e "$HOOKS_DST" ]]; then
  BACKUP="$HOOKS_DST.backup-$(date +%Y%m%d%H%M%S)"
  echo ""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "  WARNING: ~/.codex/hooks.json already exists and is NOT a symlink."
  echo "  Backing it up to: $BACKUP"
  echo "  The existing file will be REPLACED with the agentic-engineering symlink."
  echo "  To restore: cp \"$BACKUP\" \"$HOOKS_DST\""
  echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo ""
  mv "$HOOKS_DST" "$BACKUP"
  ln -s "$HOOKS_SRC" "$HOOKS_DST"
  echo "  + ~/.codex/hooks.json linked (backup saved to $BACKUP)"
else
  ln -s "$HOOKS_SRC" "$HOOKS_DST"
  echo "  + ~/.codex/hooks.json linked to $HOOKS_SRC"
fi

# ---------------------------------------------------------------------------
# Enable codex_hooks feature flag in ~/.codex/config.toml
# The hooks system requires [features] codex_hooks = true.
# We add the flag only if missing and preserve all existing content.
# If the config file does not exist, we create it with only this flag.
# ---------------------------------------------------------------------------

echo "Checking codex_hooks feature flag in config.toml..."

ADDED_CODEX_HOOKS_FLAG=0

if [[ -f "$CONFIG_FILE" ]]; then
  if grep -qE '^[[:space:]]*codex_hooks[[:space:]]*=[[:space:]]*true' "$CONFIG_FILE" 2>/dev/null; then
    echo "  = codex_hooks already enabled in $CONFIG_FILE"
  elif grep -qE '^[[:space:]]*codex_hooks[[:space:]]*=' "$CONFIG_FILE" 2>/dev/null; then
    echo ""
    echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "  WARNING: codex_hooks is present in $CONFIG_FILE but is NOT set to true."
    echo "  Hooks will not fire until you manually set it to:"
    echo "    codex_hooks = true"
    echo "  in the [features] section of $CONFIG_FILE"
    echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo ""
  else
    # File exists, flag is missing. Add it safely.
    # Check if [features] section exists
    if grep -q "^\[features\]" "$CONFIG_FILE" 2>/dev/null; then
      # [features] section exists - insert the flag after the FIRST match only
      # Use a temp file to avoid in-place issues
      TMPFILE="$(mktemp)"
      awk 'BEGIN{done=0} /^\[features\]/ && !done {print; print "codex_hooks = true"; done=1; next} 1' "$CONFIG_FILE" > "$TMPFILE"
      mv "$TMPFILE" "$CONFIG_FILE"
      echo "  + Added codex_hooks = true to existing [features] section in $CONFIG_FILE"
      ADDED_CODEX_HOOKS_FLAG=1
    else
      # No [features] section - append it
      printf '\n[features]\ncodex_hooks = true\n' >> "$CONFIG_FILE"
      echo "  + Appended [features] section with codex_hooks = true to $CONFIG_FILE"
      ADDED_CODEX_HOOKS_FLAG=1
    fi
  fi
else
  # Config file does not exist - create it with only the feature flag
  mkdir -p "$(dirname "$CONFIG_FILE")"
  printf '[features]\ncodex_hooks = true\n' > "$CONFIG_FILE"
  echo "  + Created $CONFIG_FILE with [features] codex_hooks = true"
  ADDED_CODEX_HOOKS_FLAG=1
fi

# Write a marker file so uninstall.sh knows to remove the flag
HOOKS_FLAG_MARKER="$HOME/.codex/.agentic-eng-added-codex-hooks-flag"
if [[ $ADDED_CODEX_HOOKS_FLAG -eq 1 ]]; then
  touch "$HOOKS_FLAG_MARKER"
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
echo "Install complete."
echo ""
echo "What was installed:"
echo "  ~/.agents/skills/agentic-engineering  -> $SKILL_SRC"
echo "    Contains: SKILL.md (trigger + methodology summary)"
echo "              references/ (skeptic-protocol, subagent-protocol, agent-team, design-goals)"
echo ""
echo "  ~/.codex/AGENTS.md  -> $AGENTS_SRC"
echo "    Contains: Full agentic engineering methodology (loaded globally by Codex)"
echo ""
echo "  ~/.codex/agents/  -> $NAMED_AGENTS_SRC"
echo "    Contains: Named agent TOML files (engineer, architect, debugger, investigator,"
echo "              qa-engineer, security-auditor, orchestration-planner, skeptic,"
echo "              adr-drift-detector, adr-generator)"
echo ""
echo "  ~/.codex/hooks.json  -> $HOOKS_SRC"
echo "    Contains: UserPromptSubmit (risk reminder) and Stop (context save) hooks"
echo "    Requires: [features] codex_hooks = true in ~/.codex/config.toml (added automatically)"
echo ""
echo "What is available in the repo:"
echo "  .codex/AGENTS.md       - Source for the global ~/.codex/AGENTS.md symlink"
echo "  .codex/agents/         - Generated named agent TOML files (source: content/agents/*.md)"
echo "  .codex/config/hooks.json - Source hooks configuration for ~/.codex/hooks.json"
echo "  .codex/hooks/          - Hook scripts (risk-reminder.sh, stop-context-codex.js)"
echo "  .codex/commands/       - Source command templates (hardlinks from content/commands/)"
echo "  .codex/references/     - Local copies of reference docs"
echo ""
echo "IMPORTANT - coexistence note:"
echo "  This install writes to ~/.agents/skills/, ~/.codex/AGENTS.md,"
echo "  ~/.codex/agents/, ~/.codex/hooks.json, and"
echo "  may have added codex_hooks = true to ~/.codex/config.toml."
echo "  Safe to run alongside the Claude Code adapter."
echo ""
echo "Next steps:"
echo "  1. Open Codex in a project that uses this methodology."
echo "  2. The agentic-engineering skill will trigger automatically for software development tasks."
echo "  3. ~/.codex/AGENTS.md loads the full methodology globally in every Codex session."
echo "  4. The project's AGENTS.md (if present) loads additional project-specific rules."
echo "  5. Risk reminder hook fires automatically before each prompt."
echo "  6. Session context saved to ~/.codex/projects/[hash]/context.md on Stop."
echo "  7. Command templates live in .codex/commands/ for manual use when needed."
echo "  8. See .codex/README.md for full documentation."
