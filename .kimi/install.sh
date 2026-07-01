#!/usr/bin/env bash
# Purpose: Installs the agentic-engineering skill for the Kimi CLI adapter.
#          Runs build.sh to generate AGENTS.md and per-command skills, writes
#          the activation mode/profile to ~/.claude/agentic-engineering.json,
#          wires up global skill symlinks under ~/.kimi/skills/, and wires
#          the SessionStart hook in ~/.kimi/config.toml at the session-stable
#          hooks snapshot (DS-54, scripts/lib/hooks-snapshot.sh) when sync
#          succeeds, else the checkout.
#
# Public API: bash .kimi/install.sh [--mode=opt-in|opt-out] [--profile=relaxed|default|strict]
#             Safe to re-run (idempotent). No required arguments.
#             When invoked non-interactively (stdin not a TTY), defaults to
#             mode=opt-out, profile=default without prompting.
#
# Upstream deps: bash 3.2+, python3 (for JSON config reads/writes and realpath
#                resolution), git (via build.sh), REPO_DIR layout with content/
#                tree, .kimi/build.sh, .kimi/skills/agentic-engineering/ as
#                the per-adapter skill source.
#
# Downstream consumers: humans installing the adapter manually;
#                       scripts/update.js (generic multi-adapter updater,
#                       launched via ./update.sh) invokes this script for
#                       each selected adapter after pulling new content.
#
# Failure modes: exits non-zero on build.sh failure (propagated). Partial
#                install is possible if the script exits mid-run; re-running
#                is safe. The dir-symlink guard prevents write-through
#                corruption: if ~/.kimi/skills/agentic-engineering is a
#                directory symlink pointing into the repo, the symlink is
#                removed and replaced with a real directory before any files
#                are written, ensuring tracked repo symlinks (SKILL.md, agents,
#                commands, references) are never clobbered. The sections/rules
#                migration is a 5-case contract; Case 4 (both exist) exits 1
#                and requires manual intervention. The SessionStart hook wire
#                (DS-54) is an atomic block-scoped TOML rewrite: any parse
#                ambiguity in ~/.kimi/config.toml (more than one matching
#                [[hooks]] block, or an unrecognized command-line shape)
#                aborts with NO write at all, leaving the prior config.toml
#                untouched - it never corrupts, it degrades to "hook not
#                (re)wired" and prints a warning instead.
#
# Performance: ~2-5 s wall time (dominated by build.sh git operations).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

# shellcheck source=scripts/lib/identity.sh
[[ -f "$REPO_DIR/scripts/lib/identity.sh" ]] && . "$REPO_DIR/scripts/lib/identity.sh" || {
  echo "  ! scripts/lib/identity.sh not found - identity setup skipped"
}

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

# If $SKILL_DST is a symlink pointing back into the repo (stale install style),
# remove it and create a real directory. Writing individual files through a
# dir-symlink that resolves to $SKILL_SRC would corrupt tracked repo symlinks.
if [[ -L "$SKILL_DST" ]]; then
  _dst_real="$(python3 -c "import os.path; print(os.path.realpath('$SKILL_DST'))")"
  _src_real="$(python3 -c "import os.path; print(os.path.realpath('$SKILL_SRC'))")"
  if [[ "$_dst_real" == "$_src_real" ]]; then
    rm "$SKILL_DST"
    echo "  ~ removed stale dir-symlink at $SKILL_DST (was pointing into repo)"
  fi
fi
mkdir -p "$SKILL_DST"

# Absolute symlinks for content dirs so they resolve from ~/.kimi/skills/
# Canonical comparison (realpath both sides) so a no-op install is truly a no-op.
link_abs() {
  local src="$1"
  local dst="$2"
  if [[ -L "$dst" ]]; then
    local current_abs src_abs
    current_abs="$(python3 -c "import os.path; print(os.path.realpath('$(readlink "$dst")'))" 2>/dev/null || python3 -c "import os.path; print(os.path.realpath(os.path.join('$(dirname "$dst")', os.readlink('$dst'))))")"
    src_abs="$(python3 -c "import os.path; print(os.path.realpath('$src'))")"
    if [[ "$current_abs" == "$src_abs" ]]; then
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

# SKILL.md: point at the actual content file, not the intermediate repo symlink.
# Using $REPO_DIR/content/SKILL.md avoids a self-referential link when $SKILL_DST
# is a stale dir-symlink pointing at $SKILL_SRC.
link_abs "$REPO_DIR/content/SKILL.md"  "$SKILL_DST/SKILL.md"

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
# Hook snapshot (DS-54)
#
# Copies hooks/ + the four in-scope adapters' hook sources into a
# per-checkout snapshot dir at $HOME/.agentic/hooks-snapshot/<key>/, so a
# bare `git pull` cannot silently rewire a live session's hook commands.
# Graceful degradation: any failure here leaves AE_HOOKS_SNAPSHOT_DIR unset
# and AE_HOOKS_ROOT falls back to the checkout ($REPO_DIR).
# ---------------------------------------------------------------------------

echo ""
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

# ---------------------------------------------------------------------------
# Configure Kimi CLI hooks
#
# DS-54: replaces the old presence-only `grep -q session-start.sh` upsert
# with an atomic block-scoped TOML rewrite. Finds the [[hooks]] block whose
# command references session-start.sh (a block runs from a "[[hooks]]"
# heading to the next top-level heading or EOF), rewrites ONLY that block's
# command line if it differs from the expected snapshot-rooted command,
# no-ops if already correct, and appends a fresh block only when none is
# found. Any parse ambiguity (more than one matching block, or a command
# line that does not match the plain `command = "..."` shape) aborts with NO
# write at all - degrading to "hook not (re)wired" rather than ever
# corrupting config.toml. Written via a temp file + `mv -f` for atomicity.
# Unrelated [[hooks]] entries (other events, third-party tools) are left
# byte-for-byte untouched because they never match the session-start.sh scan.
# ---------------------------------------------------------------------------

KIMI_CONFIG="$HOME/.kimi/config.toml"
HOOK_SCRIPT="$AE_HOOKS_ROOT/.kimi/hooks/session-start.sh"

if [[ -f "$KIMI_CONFIG" ]]; then
  echo ""
  echo "Configuring Kimi CLI hooks..."

  python3 - "$KIMI_CONFIG" "$HOOK_SCRIPT" <<'PYEOF'
import os
import sys

config_path, hook_script = sys.argv[1], sys.argv[2]
expected_command = f"bash {hook_script}"
expected_line = f'command = "{expected_command}"\n'

try:
    with open(config_path) as f:
        lines = f.readlines()
except Exception as e:
    print(f"  ! could not read {config_path}: {e} - aborting hook wiring (no-op)")
    sys.exit(0)

# Find every "[[hooks]]" heading line.
block_starts = [i for i, line in enumerate(lines) if line.strip() == "[[hooks]]"]

# For each block (heading to next top-level heading or EOF), record the
# index of a "command" line that references session-start.sh, if any.
matches = []
for idx, start in enumerate(block_starts):
    end = block_starts[idx + 1] if idx + 1 < len(block_starts) else len(lines)
    # A different top-level heading (not another [[hooks]]) also ends a
    # block early, so an unrelated trailing table is never swallowed.
    for j in range(start + 1, end):
        stripped = lines[j].strip()
        if stripped.startswith("[") and stripped != "[[hooks]]":
            end = j
            break
    for j in range(start, end):
        if "command" in lines[j] and "session-start.sh" in lines[j]:
            matches.append(j)

if len(matches) > 1:
    print(f"  ! ambiguous session-start.sh hook entries ({len(matches)} found) in {config_path} - aborting hook wiring (no-op, never corrupts)")
    sys.exit(0)

if len(matches) == 1:
    cmd_line_idx = matches[0]
    stripped = lines[cmd_line_idx].strip()
    if not (stripped.startswith("command") and "=" in stripped):
        print(f"  ! could not parse existing command line in {config_path} - aborting hook wiring (no-op, never corrupts)")
        sys.exit(0)
    if stripped == expected_line.strip():
        print("  = SessionStart hook already configured")
        sys.exit(0)
    lines[cmd_line_idx] = expected_line
    action = "updated"
else:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] = lines[-1] + "\n"
    lines.append("\n")
    lines.append("[[hooks]]\n")
    lines.append('event = "SessionStart"\n')
    lines.append(expected_line)
    lines.append('matcher = ""\n')
    lines.append("timeout = 5\n")
    action = "added"

tmp = config_path + ".tmp." + str(os.getpid())
try:
    with open(tmp, "w") as f:
        f.writelines(lines)
    os.replace(tmp, config_path)
except Exception as e:
    print(f"  ! failed to write {config_path}: {e} - aborting hook wiring (no-op)")
    try:
        os.remove(tmp)
    except Exception:
        pass
    sys.exit(0)

if action == "updated":
    print(f"  ~ SessionStart hook command updated -> {expected_command}")
else:
    print(f"  + Added SessionStart hook to {config_path}")
PYEOF
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
