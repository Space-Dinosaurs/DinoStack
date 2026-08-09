#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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
AE_DRY_RUN=false
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
    --dry-run)
      AE_DRY_RUN=true
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
            tty.write("Auto-load dinostack skill at session start? [y/N] ")
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
  echo "  + dinostack mode set to '$AE_MODE_FLAG' via --mode flag (wrote $AE_CONFIG_PATH)"
elif [[ -n "$AE_EXISTING_MODE" ]]; then
  echo "  = dinostack mode already set to '$AE_EXISTING_MODE' (keeping $AE_CONFIG_PATH)"
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
  echo "    Override with: bash .cursor/install.sh --profile=relaxed|default|strict"
fi

RULES_SRC="$REPO_DIR/.cursor/rules"
REFS_SRC="$REPO_DIR/.cursor/references"
COMMANDS_SRC="$REPO_DIR/.cursor/commands"
HOOKS_SRC="$REPO_DIR/.cursor/hooks.json"

RULES_DST="$HOME/.cursor/rules"
REFS_DST="$HOME/.cursor/references"
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
      elif _ae_is_ours "$dst_file"; then
        # Stale symlink pointing to another methodology checkout - re-point it.
        if [[ "$AE_DRY_RUN" == "true" ]]; then
          array_append "$skipped_name" "$name (would re-point to repo_dir)"
        else
          ln -sfn "$src_file" "$dst_file"
          array_append "$installed_name" "$name (re-pointed to repo_dir)"
        fi
        continue
      else
        if [[ "$AE_DRY_RUN" == "true" ]]; then
          array_append "$warned_name" "$name (would skip: symlink points outside methodology checkout: $current_target)"
        else
          array_append "$warned_name" "$name (symlink points elsewhere: $current_target - skipping)"
        fi
        continue
      fi
    elif [[ -e "$dst_file" ]]; then
      if [[ "$AE_DRY_RUN" == "true" ]]; then
        array_append "$warned_name" "$name (would skip: real file exists at destination)"
      else
        array_append "$warned_name" "$name (real file exists at destination - skipping)"
      fi
      continue
    fi

    if [[ "$AE_DRY_RUN" == "true" ]]; then
      array_append "$installed_name" "$name (would create)"
    else
      ln -s "$src_file" "$dst_file"
      array_append "$installed_name" "$name"
    fi
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
# Legacy cleanup: remove stale $HOME/.cursor/rules/references/ symlinks
# created by versions prior to the references relocation (refs moved from
# .cursor/rules/references/ to .cursor/references/). Idempotent; no-op when
# the legacy path is absent.
# ---------------------------------------------------------------------------

_legacy_refs_dir="$HOME/.cursor/rules/references"
if [[ -d "$_legacy_refs_dir" ]]; then
  _removed_legacy=0
  for _f in "$_legacy_refs_dir"/*.md; do
    [[ -e "$_f" || -L "$_f" ]] || continue
    if [[ -L "$_f" ]]; then
      _cur_target="$(readlink "$_f")"
      if [[ "$_cur_target" == "$REPO_DIR/"* ]]; then
        rm "$_f"
        _removed_legacy=$(( _removed_legacy + 1 ))
      fi
    fi
  done
  if [[ "$_removed_legacy" -gt 0 ]]; then
    echo "  ~ legacy $HOME/.cursor/rules/references/: removed $_removed_legacy stale symlink(s)"
  fi
  # Remove the directory if now empty
  if [[ -d "$_legacy_refs_dir" ]] && [[ -z "$(ls -A "$_legacy_refs_dir" 2>/dev/null)" ]]; then
    rmdir "$_legacy_refs_dir"
    echo "  ~ legacy $HOME/.cursor/rules/references/ directory removed (was empty)"
  fi
fi
unset _legacy_refs_dir _removed_legacy _f _cur_target

# ---------------------------------------------------------------------------
# Symlink reference docs (.md files in references/)
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
# Remove stale pre-DS-26 command symlinks
#
# DS-26 renamed all 25 methodology commands to a ds- prefix. This is a
# LITERAL hand-enumerated allowlist of the 25 OLD names - never a glob or a
# set-difference against $COMMANDS_DST. That directory is a shared,
# operator-owned user-level location that may contain files we do not own
# (e.g. a personal flow-dev.md); scanning it and removing anything not in
# our generated set would delete operator files we have no business
# touching. Only entries in this exact allowlist are candidates, and even
# then only removed if _ae_is_ours() confirms the symlink points inside
# this methodology checkout.
# ---------------------------------------------------------------------------

echo "Removing stale pre-DS-26 command symlinks..."
_ae_stale_pre_ds26_commands=(
  agentic-config.md agentic-cost.md agentic-disable.md agentic-help.md
  agentic-identity.md agentic-status.md brief.md cleanup-worktrees.md
  configure-team.md feedback-triage.md implement-ticket.md init-project.md
  memory-update.md migrate-project.md prune-harness.md pull-and-install.md
  representation-audit.md skeptic.md skill-candidates.md
  test-suite-comprehension.md ticket-status-sync.md ticket-triage.md
  update-agentic-engineering.md wrap-deferred.md wrap.md
)
for _ae_old_name in "${_ae_stale_pre_ds26_commands[@]}"; do
  _ae_old_dst="$COMMANDS_DST/$_ae_old_name"
  if _ae_is_ours "$_ae_old_dst"; then
    if [[ "$AE_DRY_RUN" == "true" ]]; then
      echo "  ~ $_ae_old_name (would remove: stale pre-DS-26 command symlink)"
    else
      rm -f "$_ae_old_dst"
      echo "  - removed $_ae_old_name (stale pre-DS-26 command symlink)"
    fi
  fi
done

# ---------------------------------------------------------------------------
# Remove stale post-DS-26 command symlinks (renamed commands)
#
# A command can also be renamed after DS-26 (its own ds- prefix stays, only
# the basename changes). Same allowlist discipline as above: literal old
# names only, never a glob or set-difference against $COMMANDS_DST.
# ---------------------------------------------------------------------------

echo "Removing stale post-DS-26 command symlinks..."
_ae_stale_renamed_commands=(
  ds-pull-and-install.md
)
for _ae_old_name in "${_ae_stale_renamed_commands[@]}"; do
  _ae_old_dst="$COMMANDS_DST/$_ae_old_name"
  if _ae_is_ours "$_ae_old_dst"; then
    if [[ "$AE_DRY_RUN" == "true" ]]; then
      echo "  ~ $_ae_old_name (would remove: stale renamed command symlink)"
    else
      rm -f "$_ae_old_dst"
      echo "  - removed $_ae_old_name (stale renamed command symlink)"
    fi
  fi
done

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

if [[ -f "$REPO_DIR/scripts/lib/precommit.sh" ]]; then
  # shellcheck source=scripts/lib/precommit.sh
  . "$REPO_DIR/scripts/lib/precommit.sh"
  install_precommit_hook "$REPO_DIR"
else
  echo "  ! scripts/lib/precommit.sh not found - pre-commit hook install skipped"
fi

# ---------------------------------------------------------------------------
# Copy hooks.json
#
# The checked-in template keeps the stop hook's command RELATIVE ("node
# hooks/stop-context.js") - do not "fix" it to an absolute path. Converging
# to the resolved absolute path is install.sh's job (below), on every run,
# in both branches of the exists-check: this lets a future repo move
# re-point an already-installed hooks.json with a simple re-run, and keeps
# the template diff-stable across machines with different checkout paths.
# ---------------------------------------------------------------------------

CURSOR_STOP_JS="$REPO_DIR/.cursor/hooks/stop-context-cursor.js"
CURSOR_STOP_CMD="node \"$CURSOR_STOP_JS\""

# _ae_cursor_converge_hooks_stop DST NEW_CMD
#   Rewrites every hooks.stop[] entry in DST whose "command" matches the
#   AE-managed stop-context hook filename - old "stop-context.js" or the
#   current "stop-context-cursor.js" port, at any path - to NEW_CMD. Every
#   other key (beforeSubmitPrompt, locally-added stop entries) is left
#   untouched. Prints exactly one token to stdout for the caller to branch
#   on:
#     - a positive integer: that many entries were converged and written.
#     - 0: already current - no entry needed rewriting.
#     - ERR: genuine failure - python3 unavailable, DST is not valid JSON,
#       hooks.stop is missing or not a list, or the atomic write raised.
#       DST is left untouched on disk in every ERR case, and a
#       human-readable diagnostic is also printed to stderr describing the
#       cause. Callers MUST treat ERR as "stop hook not converged" and
#       must never print a reassuring success/"already current" message on
#       this path - 0 (legitimate no-op) and ERR (failed to converge) are
#       deliberately distinct tokens so the two cannot be conflated.
#   Writes atomically (tmp file + rename in the same directory) and only
#   when at least one entry actually changed - repeat runs on an
#   already-converged file leave it byte-identical.
_ae_cursor_converge_hooks_stop() {
  local dst="$1"
  local new_cmd="$2"

  if ! command -v python3 >/dev/null 2>&1; then
    echo "  ! python3 not found - leaving $dst untouched (stop hook not converged)" >&2
    echo ERR
    return 0
  fi

  python3 - "$dst" "$new_cmd" <<'PYEOF'
import json, os, re, sys, tempfile

dst, new_cmd = sys.argv[1], sys.argv[2]
# Path-segment anchored: the filename must start at a path/quote/space
# boundary (or string start) and end at a quote/space boundary (or string
# end). An unanchored search would also clobber a user's own entry whose
# command merely CONTAINS the substring, e.g. a custom
# 'bash "/home/u/my-stop-context.js"' or 'node scripts/nonstop-context.js'
# hook - both false-positive-matched under the prior unanchored .search().
# \x22/\x27 (=" and ') avoid quote-nesting inside this raw string.
pattern = re.compile(r'(?:^|[/\\\x22\x27 ])stop-context(-cursor)?\.js(?:[\x22\x27]|$| )')

try:
    with open(dst) as f:
        data = json.load(f)
except Exception as e:
    print(f"  ! {dst}: not valid JSON ({e}) - stop hook not converged", file=sys.stderr)
    print("ERR")
    sys.exit(0)

hooks = data.get("hooks") if isinstance(data, dict) else None
if not isinstance(hooks, dict):
    print(f"  ! {dst}: no \"hooks\" object found - stop hook not converged", file=sys.stderr)
    print("ERR")
    sys.exit(0)

stop_list = hooks.get("stop")
if not isinstance(stop_list, list):
    print(f"  ! {dst}: hooks.stop is missing or not a list - stop hook not converged", file=sys.stderr)
    print("ERR")
    sys.exit(0)

changed = 0
for entry in stop_list:
    if not isinstance(entry, dict):
        continue
    command = entry.get("command")
    if isinstance(command, str) and pattern.search(command) and command != new_cmd:
        entry["command"] = new_cmd
        changed += 1

if changed > 0:
    dir_name = os.path.dirname(dst) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.rename(tmp_path, dst)
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        print(f"  ! {dst}: failed to write converged hooks.json ({e}) - stop hook not converged", file=sys.stderr)
        print("ERR")
        sys.exit(0)

print(changed)
PYEOF
}

echo "Installing hooks.json..."

if [[ -e "$HOOKS_DST" ]]; then
  _ae_changed="$(_ae_cursor_converge_hooks_stop "$HOOKS_DST" "$CURSOR_STOP_CMD")"
  if [[ "$_ae_changed" == "ERR" ]]; then
    echo "  ! hooks.json convergence FAILED - stop hook may still point at the OLD blocking command (bounded reader NOT wired). Fix the cause above and re-run install."
  elif [[ "${_ae_changed:-0}" -gt 0 ]]; then
    echo "  ~ $HOOKS_DST converged ($_ae_changed stop hook entry updated)"
  else
    echo "  = $HOOKS_DST already current - preserving customizations"
  fi
else
  cp "$HOOKS_SRC" "$HOOKS_DST"
  _ae_changed="$(_ae_cursor_converge_hooks_stop "$HOOKS_DST" "$CURSOR_STOP_CMD")"
  if [[ "$_ae_changed" == "ERR" ]]; then
    echo "  ! hooks.json copied to $HOOKS_DST but stop hook convergence FAILED - bounded reader NOT wired (old blocking command may still be active). Fix the cause above and re-run install."
  elif [[ "${_ae_changed:-0}" -gt 0 ]]; then
    echo "  + hooks.json copied to $HOOKS_DST (stop -> $CURSOR_STOP_CMD)"
  else
    echo "  = hooks.json copied to $HOOKS_DST (stop hook already current)"
  fi
fi
unset _ae_changed

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
  for src_file in "$bin_src"/agentic-* "$bin_src"/ds-*; do
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
  _ae_identity_guidance
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "NOTE: Cursor hooks.json is installed as a copy, not a symlink."
echo "Existing Cursor users must re-run install.sh to receive updated hooks."
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
echo "       - what dinostack is and how it works"
echo "    2. $REPO_DIR/docs/slides/getting-started-slides.html"
echo "       - install flow and the first focused session"
echo "    3. $REPO_DIR/docs/slides/context-management-slides.html"
echo "       - why context hygiene is the real bottleneck"
echo "    4. $REPO_DIR/docs/slides/agent-team-slides.html"
echo "       - the agent team and how they compose"
echo "    5. $REPO_DIR/docs/slides/quality-assurance-slides.html"
echo "       - how the qa-engineer uses .claude/qa.md as project QA memory"
echo "    6. $REPO_DIR/docs/slides/work-tracking-slides.html"
echo "       - how the planner uses .agentic/tracking.md for tracker actions"
echo "    7. $REPO_DIR/docs/slides/skeptic-protocol-slides.html"
echo "       - adversarial review methodology and the Skeptic loop"
echo "    8. $REPO_DIR/docs/slides/agents-md-hierarchy-slides.html"
echo "       - the three-tier AGENTS.md context hierarchy"
echo "    9. $REPO_DIR/docs/slides/contributing-slides.html"
echo "       - how to contribute to the repo"
echo "   10. $REPO_DIR/docs/index.html"
echo "       - full system architecture reference"
echo ""
echo "  Present the list, ask which ones they want to see, open only those."
