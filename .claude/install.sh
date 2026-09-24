#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: One-shot installer for dinostack. Symlinks agents,
#          commands, and the skill directory into ~/.claude/; syncs hook
#          scripts into a session-stable per-checkout snapshot dir (DS-54,
#          scripts/lib/hooks-snapshot.sh) and wires hooks in
#          ~/.claude/settings.json to point there instead of the checkout;
#          writes activation mode + risk profile; optionally configures
#          permissions, MCPs, and developer identity; writes repo_dir to
#          ~/.agentic/agentic-engineering-config.json with a clobber-guard
#          (never overwrites a valid different repo_dir).
#
# Public API:
#   bash .claude/install.sh [--mode=opt-in|opt-out] [--profile=relaxed|default|strict]
#                           [--identity=<handle>] [--no-identity] [--dry-run]
#                           [--config-dir=<dir>]
#   --config-dir=<dir> (or AGENTIC_CONFIG_DIR env): redirect the per-harness
#     config dir (agents/commands/skills/settings/CLAUDE.md/agentic-engineering.json)
#     to <dir> for per-profile installs. Shared state (~/.agentic, ~/.local/bin,
#     ~/.claude.json) always stays in the real $HOME. Default: ~/.claude.
#   CLAUDE_CONFIG_DIR env (DS-231): also redirects the harness config dir, but
#     ranks BELOW the flag and AGENTIC_CONFIG_DIR - full precedence is
#     --config-dir > AGENTIC_CONFIG_DIR > CLAUDE_CONFIG_DIR > ~/.claude. It is
#     deliberately NOT an "explicit redirect": it does not move
#     agentic-engineering.json and does not flip developer identity to profile
#     scope. See the AE_CONFIG_DIR consumer audit below for the per-consumer
#     follows/stays split and the measured reason for each "stays" row.
#   ae_resolve_write_target <path> (internal): resolves a bridge symlink to its
#     real path when that path stays under $HOME; refuses (rc 1) when it
#     escapes $HOME; passes a non-symlink through unchanged.
#   --dry-run: print symlink actions, the CLAUDE.md managed-block update
#              intent, and repo_dir write intent without executing them.
#              Hook wiring, build, and permission phases still execute.
#
# Upstream deps: bash 3.2+, python3, git, node (for hooks), ln, readlink.
#   The CLAUDE.md managed-block table body is single-sourced from
#   content/templates/claude-managed-content.md (manifest header stripped at
#   write time) - do not re-inline that table here.
#
# Downstream consumers: bootstrap.sh (calls this), /update-agentic-engineering,
#   developers running directly.
#
# Failure modes:
#   - Stale symlinks pointing to another methodology checkout are RE-POINTED
#     (converging / self-healing). Real files at dst are skipped (never touched).
#   - Symlinks to non-methodology paths are skipped; a warning is printed.
#   - repo_dir clobber-guard: if ~/.agentic/agentic-engineering-config.json
#     already holds a valid DIFFERENT repo_dir, a warning is printed and the
#     existing value is preserved. Only absent/invalid/same values are written.
#   - All interactive prompts fall back to a default when stdin is not a TTY.
#     The skill_auto_load prompt (fresh install only) defaults to yes ([Y/n],
#     blank = yes) both interactively and non-interactively.
#   - A skipped or not-yet-created skill symlink sets SKILL_LINK_OK=false and
#     emits an operator warning twice per run (once where the skip is
#     detected, once in the Summary block). Every --dry-run on a machine
#     without an existing, correctly-pointed skill link falls into this case
#     and emits the warning, since --dry-run never creates the symlink.
#   - DS-143 gate: the CLAUDE.md managed block drops its three @-import lines
#     ONLY when SKILL_LINK_OK == true; otherwise the imports are appended
#     after the table exactly as before, and a warning is printed - the
#     imports are never stripped without a working skill symlink to fall
#     back on. On the run that first strips the imports (old-format block
#     detected on disk pre-rewrite AND SKILL_LINK_OK == true), skill_auto_load
#     is force-set to true in agentic-engineering.json as a one-time
#     migration; this self-disarms once the old imports are gone from disk.
#     A "start a new session" registry-refresh notice prints unconditionally
#     whenever SKILL_LINK_OK == true (the strip gate allowed the skill-based
#     table to be (re)written) - including idempotent re-runs and update-path
#     runs where only the skill's regenerated body changed underneath an
#     unchanged CLAUDE.md, since the notice's subject is the skill registry,
#     not the CLAUDE.md byte diff. Suppressed only when the gate itself
#     blocked the strip (SKILL_LINK_OK != true).
#   - The managed-block table body's source,
#     content/templates/claude-managed-content.md, must retain its leading
#     HTML manifest comment with a "-->" terminator; if that terminator is
#     missing, install.sh fails loudly and leaves CLAUDE.md untouched rather
#     than silently shipping the whole template (manifest text included)
#     into the user's file. Contract matches
#     scripts/check-resident-budget.sh's own terminator requirement. A
#     missing/unreadable template file at that path fails the same way.
#
# Performance: ~5-10 s (one build pass, node/python3 calls for hooks/settings).
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_DIR

# shellcheck source=scripts/lib/identity.sh
[[ -f "$REPO_DIR/scripts/lib/identity.sh" ]] && . "$REPO_DIR/scripts/lib/identity.sh" || {
  echo "  ! scripts/lib/identity.sh not found - identity setup skipped"
}

# ---------------------------------------------------------------------------
# Activation mode (shared across all adapters)
#
# Writes ~/.claude/agentic-engineering.json with { "mode": "opt-out" | "opt-in",
# "profile": "relaxed" | "default" | "strict", "set_at": "<ISO8601>" }.
# Read by the skill preflight each session.
#
# Flags: --mode=opt-in | --mode=opt-out (optional)
#        --profile=relaxed | --profile=default | --profile=strict (optional)
# Interactive prompt when flag absent AND stdin is a TTY.
# Non-interactive default: opt-out.
# Idempotent: if the config already exists and --mode was not passed, keep it.
# ---------------------------------------------------------------------------

AE_MODE_FLAG=""
AE_PROFILE_FLAG=""
AE_IDENTITY_FLAG=""
AE_NO_IDENTITY=false
AE_DRY_RUN=false
# Initialized before the loop so an exported AE_CONFIG_DIR_FLAG in the calling
# environment can never be mistaken for a --config-dir flag passed on this
# invocation. Parity with .codex/install.sh:53.
AE_CONFIG_DIR_FLAG=""
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
    --config-dir=*)
      AE_CONFIG_DIR_FLAG="${arg#--config-dir=}"
      ;;
  esac
done

# ---------------------------------------------------------------------------
# ae_resolve_write_target <path>
#
# Resolve a write destination that may be a bridge symlink, without ever
# loosening the symlink-write refusals further down this script.
#
#   - <path> is a symlink whose realpath stays under $HOME: prints the
#     realpath, returns 0. The caller then writes to a REAL file, so the
#     os.path.islink() refusals never fire and a bridged install keeps
#     working instead of aborting.
#   - <path> is a symlink whose realpath escapes $HOME: prints nothing,
#     returns 1. The caller refuses. This is the CWE-59 case the refusals
#     exist for and it stays refused.
#   - <path> is not a symlink (or does not exist): prints <path> unchanged,
#     returns 0.
#
# Arguments are passed as argv, never interpolated into the Python source,
# for the same CWE-94 reason as ae_read_json_key below. Containment is a
# lexical check on the resolved path against the resolved $HOME, so a
# symlink chain that lands outside $HOME is caught however many hops it took.
# ---------------------------------------------------------------------------
ae_resolve_write_target() {
  python3 - "$1" "$HOME" <<'PYEOF'
import os, sys
path, home = sys.argv[1], sys.argv[2]
if not os.path.islink(path):
    print(path)
    sys.exit(0)
real = os.path.realpath(path)
home_real = os.path.realpath(home)
if real == home_real or real.startswith(home_real.rstrip(os.sep) + os.sep):
    print(real)
    sys.exit(0)
sys.exit(1)
PYEOF
}

# ---------------------------------------------------------------------------
# AE_CONFIG_DIR consumer audit (DS-231, AC4)
#
# Every consumer of AE_CONFIG_DIR below, and whether it FOLLOWS the resolved
# config dir or deliberately STAYS on the real $HOME. A row that stays names
# the measured reason, not an assertion.
#
# FOLLOWS the resolved config dir (these are what the harness reads):
#   AGENTS_DST / COMMANDS_DST / SKILLS_DST / SETTINGS  - the managed symlink
#     trees and settings.json the harness loads at startup.
#   AE_OUTPUT_STYLE_DST_DIR                            - /config reads the
#     style list from the active config dir; this is DS-231's reported defect.
#   CLAUDE.md (via AE_CLAUDE_MD_PATH)                  - the managed-block
#     file the harness imports.
#   the stale pre-rename skill prune                   - derives from
#     SKILLS_DST, so it must prune in the same tree it installs into.
#   the permissions scope label                        - already derived from
#     AE_CONFIG_DIR; grants write to the tree actually installed into.
#
# OUT-OF-FILE consumer that had to follow (DS-231 round 2):
#   .claude/uninstall.sh - resolves this same chain at its :7-25. It is not a
#     consumer of this variable, but it is the paired writer/remover of every
#     "FOLLOWS" row above, so a divergence there is silent and total: uninstall
#     would print "[skip] ... directory not found" for each managed tree and
#     still end "Uninstall complete.", leaving the symlinks, the settings.json
#     hook entries, and the CLAUDE.md managed block in place. Any future edit
#     to the AE_CONFIG_DIR expansion below must be mirrored there.
#
# SIBLING TOOL, resolved separately: bin/ds-doctor's _config_dir() re-implements
#   this chain (AGENTIC_CONFIG_DIR > CLAUDE_CONFIG_DIR > ~/.claude) rather than
#   reusing _lib.resolve_claude_config_dir(), whose four-var chain adds
#   CODEX_HOME and PI_CODING_AGENT_DIR for identity-profile resolution - vars
#   this installer does not consult. Measured: with only CODEX_HOME set, _lib
#   returns ~/.codex while this file returns ~/.claude. ds-doctor cannot see the
#   --config-dir flag at all; that limit is documented in its own docstring.
#
# STAYS on the real $HOME, with the reason:
#   AE_CONFIG_PATH (agentic-engineering.json) - four readers hardcode
#     $HOME/.claude/agentic-engineering.json with no config-dir chain:
#     bin/ds-config:86, bin/ds-status:127, bin/ds-disable:50, and
#     hooks/skill-auto-load-check.sh's `ae_config=` assignment (whose
#     redirect branch immediately below it is gated on `adapter == codex`,
#     so it never fires for Claude). Moving it
#     on a bare CLAUDE_CONFIG_DIR would split activation state: install
#     writes one file, every reader reads another. It still follows an
#     EXPLICIT redirect (flag / AGENTIC_CONFIG_DIR), which is the
#     pre-existing per-profile contract and is unchanged here.
#   $HOME/.agentic hooks snapshot - scripts/lib/hooks-snapshot.sh:131,255
#     anchor the snapshot base to "$HOME/.agentic" by contract, and
#     scripts/lib/repo-dir.sh:71 reads repo_dir from the same $HOME path.
#     Per-checkout shared state, not per-harness config.
#   $HOME/.local/bin - PATH wrappers are shared across every harness.
#   ~/.claude.json MCP blocks - not under AE_CONFIG_DIR at all, and read with
#     its own semantics. NOTE (measured, out of scope for DS-231): this file
#     is a second instance of the same defect class - on a host with
#     CLAUDE_CONFIG_DIR set, the harness reads <config-dir>/.claude.json while
#     this installer writes $HOME/.claude.json, so configured MCP servers can
#     diverge between the two. Deliberately NOT fixed here; follow-up ticket.
# ---------------------------------------------------------------------------

# Harness config directory (redirectable for per-profile installs).
# Precedence: --config-dir flag > AGENTIC_CONFIG_DIR env > CLAUDE_CONFIG_DIR
# env > default ~/.claude.
# Rationale for that order: the flag and AGENTIC_CONFIG_DIR are DinoStack's
# own "install into a separate profile tree" switches, so they must outrank a
# value that merely happens to be ambient. CLAUDE_CONFIG_DIR states where the
# HARNESS reads its config, so an install that ignores it is invisible to the
# tool it was made for - it therefore outranks only the hardcoded default.
# Same chain shape as .codex/install.sh:76 and .pi/install.sh:60.
# Only the per-harness config dir is redirected; shared user state
# (~/.agentic, ~/.local/bin, ~/.claude.json) always stays in the real $HOME.
AE_CONFIG_DIR="${AE_CONFIG_DIR_FLAG:-${AGENTIC_CONFIG_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}}}"

# An EXPLICIT request to relocate DinoStack-owned state. Deliberately excludes
# CLAUDE_CONFIG_DIR: that variable says where the harness reads, which is not
# a request to move DinoStack's own per-profile identity or activation state.
# Merely having it set must not flip identity scope from global to profile
# (_ae_identity_bind_config_dir's second argument, scripts/lib/identity.sh:58-60)
# nor move AE_CONFIG_PATH. This is a deliberate divergence from
# .codex/install.sh:79,90-93, which does include CODEX_HOME in both.
AE_CONFIG_DIR_EXPLICIT_REDIRECT="${AE_CONFIG_DIR_FLAG:-${AGENTIC_CONFIG_DIR:-}}"

# Symlink guard: never write THROUGH a symlink blindly. mkdir -p would
# silently follow a symlinked config dir and any subsequent writes land
# outside the intended per-profile tree (CWE-59 directory-level). A dir that
# is a symlink resolving to somewhere still under $HOME is a legitimate
# bridged layout (one config dir per harness, all pointing at one real tree),
# so resolve it and proceed on the REAL path; anything escaping $HOME is
# still refused outright. Resolution happens BEFORE the identity binding and
# AE_CONFIG_PATH below so every downstream consumer sees one real path.
if [[ -L "$AE_CONFIG_DIR" ]]; then
  if _ae_resolved_cfg_dir="$(ae_resolve_write_target "$AE_CONFIG_DIR")"; then
    echo "  = config dir is a symlink; installing into its target: $_ae_resolved_cfg_dir"
    AE_CONFIG_DIR="$_ae_resolved_cfg_dir"
    unset _ae_resolved_cfg_dir
  else
    echo "  ! refusing to install through symlinked config dir (target escapes \$HOME): $AE_CONFIG_DIR" >&2
    exit 1
  fi
fi

if declare -f _ae_identity_bind_config_dir >/dev/null; then
  if [[ -n "$AE_CONFIG_DIR_EXPLICIT_REDIRECT" ]]; then
    _ae_identity_bind_config_dir "$AE_CONFIG_DIR" true
  else
    _ae_identity_bind_config_dir "$AE_CONFIG_DIR" false
  fi
fi

# Activation config: pinned to the shared $HOME location unless an EXPLICIT
# redirect was requested. See the "STAYS on the real $HOME" audit row above
# for the four hardcoded readers that make this a correctness requirement
# rather than a style choice. Matches .codex/install.sh:90-93.
AE_CONFIG_PATH="$HOME/.claude/agentic-engineering.json"
if [[ -n "$AE_CONFIG_DIR_EXPLICIT_REDIRECT" ]]; then
  AE_CONFIG_PATH="$AE_CONFIG_DIR/agentic-engineering.json"
fi
# The activation file itself may be a bridge symlink on a multi-profile host
# (measured: ~/.claude-spacedinosaurs/agentic-engineering.json is a symlink
# into ~/.claude). Resolve it to the real path so the islink refusals guarding
# the two writes below see a real file rather than aborting the install.
if [[ -L "$AE_CONFIG_PATH" ]]; then
  if _ae_resolved_cfg_path="$(ae_resolve_write_target "$AE_CONFIG_PATH")"; then
    AE_CONFIG_PATH="$_ae_resolved_cfg_path"
    unset _ae_resolved_cfg_path
  else
    echo "  ! refusing to write activation config through symlink escaping \$HOME: $AE_CONFIG_PATH" >&2
    exit 1
  fi
fi

mkdir -p "$AE_CONFIG_DIR"
# AE_CONFIG_PATH's directory, separately: when CLAUDE_CONFIG_DIR redirects
# AE_CONFIG_DIR but the activation config stays pinned to $HOME/.claude (the
# normal DS-231 case), those are two DIFFERENT directories and the mkdir above
# only creates the first. On a host that uses an alternate config dir and has
# no $HOME/.claude at all, every writer of AE_CONFIG_PATH below would then die
# with FileNotFoundError. Harmless no-op whenever the two paths coincide.
mkdir -p "$(dirname "$AE_CONFIG_PATH")"

# Safe JSON-key reader: path/key/default passed as argv (NOT interpolated into
# the Python source), so a config dir containing quotes or other shell/Python
# metacharacters can never break out of the string literal (CWE-94 fix).
ae_read_json_key() {
  python3 - "$1" "$2" "$3" <<'PYEOF' 2>/dev/null
import json, sys
path, key, default = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f:
        print(json.load(f).get(key, default))
except Exception:
    print(default)
PYEOF
}

AE_EXISTING_MODE=""
if [[ -f "$AE_CONFIG_PATH" ]]; then
  AE_EXISTING_MODE="$(ae_read_json_key "$AE_CONFIG_PATH" mode "")"
fi

AE_EXISTING_PROFILE=""
if [[ -f "$AE_CONFIG_PATH" ]]; then
  AE_EXISTING_PROFILE="$(ae_read_json_key "$AE_CONFIG_PATH" profile "")"
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
config["set_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
# Symlink guard: never write through a symlink (open("w") would follow it and
# truncate the real target). If the config path is a symlink, refuse.
if os.path.islink(path):
    sys.stderr.write(f"refusing to write through symlink: {path}\n")
    sys.exit(1)
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
config["set_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
# skill_auto_load: preserve existing; prompt only on fresh install (key absent)
if "skill_auto_load" not in config:
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write("Auto-load dinostack skill at session start? [Y/n] ")
            tty.flush()
            answer = (tty.readline() or "").strip().lower()
        config["skill_auto_load"] = answer in ("", "y", "yes")
    except OSError:
        config["skill_auto_load"] = True
# Write back
# Symlink guard: never write through a symlink (open("w") would follow it and
# truncate the real target). If the config path is a symlink, refuse.
if os.path.islink(path):
    sys.stderr.write(f"refusing to write through symlink: {path}\n")
    sys.exit(1)
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
  echo "    Override later with: bash .claude/install.sh --mode=opt-in"
fi

echo ""
echo "Risk profile..."
if [[ -n "$AE_PROFILE_FLAG" ]]; then
  AE_CURRENT_MODE="$(ae_read_json_key "$AE_CONFIG_PATH" mode opt-out)"
  ae_write_config "$AE_CURRENT_MODE" "$AE_PROFILE_FLAG"
  echo "  + profile set to '$AE_PROFILE_FLAG' via --profile flag"
elif [[ -n "$AE_EXISTING_PROFILE" ]]; then
  echo "  = profile already set to '$AE_EXISTING_PROFILE' (keeping)"
else
  AE_CURRENT_MODE="$(ae_read_json_key "$AE_CONFIG_PATH" mode opt-out)"
  ae_write_config "$AE_CURRENT_MODE" "default"
  echo "  = profile defaulted to 'default' (wrote $AE_CONFIG_PATH)"
  echo "    Override with: bash .claude/install.sh --profile=relaxed|default|strict"
fi

AGENTS_SRC="$REPO_DIR/.claude/agents"
COMMANDS_SRC="$REPO_DIR/.claude/commands"
SKILLS_SRC="$REPO_DIR/.claude/skills/dinostack"

AGENTS_DST="$AE_CONFIG_DIR/agents"
COMMANDS_DST="$AE_CONFIG_DIR/commands"
SKILLS_DST="$AE_CONFIG_DIR/skills/dinostack"
SETTINGS="$AE_CONFIG_DIR/settings.json"
# On a bridged multi-profile host the harness config dir holds per-entry
# symlinks into another real config tree (measured: every entry of
# ~/.claude-spacedinosaurs is a symlink into ~/.claude). Resolve settings.json
# and CLAUDE.md to their real paths so the os.path.islink() write refusals
# below see real files. Those refusals are unchanged and still fire on
# anything that resolves outside $HOME - the resolver refuses that case here
# first, before any write is attempted.
if [[ -L "$SETTINGS" ]]; then
  if _ae_resolved_settings="$(ae_resolve_write_target "$SETTINGS")"; then
    SETTINGS="$_ae_resolved_settings"
    unset _ae_resolved_settings
  else
    echo "  ! refusing to write settings.json through symlink escaping \$HOME: $SETTINGS" >&2
    exit 1
  fi
fi

AE_CLAUDE_MD_PATH="$AE_CONFIG_DIR/CLAUDE.md"
if [[ -L "$AE_CLAUDE_MD_PATH" ]]; then
  if _ae_resolved_claude_md="$(ae_resolve_write_target "$AE_CLAUDE_MD_PATH")"; then
    AE_CLAUDE_MD_PATH="$_ae_resolved_claude_md"
    unset _ae_resolved_claude_md
  else
    echo "  ! refusing to write CLAUDE.md through symlink escaping \$HOME: $AE_CLAUDE_MD_PATH" >&2
    exit 1
  fi
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
#   Intentionally more conservative than ds-doctor on broken symlinks:
#   ds-doctor reclaims ALL broken symlinks in managed dirs regardless of
#   origin, while this predicate only reclaims broken symlinks whose target
#   string contains a /DinoStack/ or -DinoStack/ component (i.e., was clearly
#   a methodology path). Non-methodology broken symlinks are left untouched.
#   Must NOT match "MyDinoStackFork" or similar; only exact-component matches count.
_ae_is_ours() {
  local dst="$1"
  # Not a symlink -> not ours (real file: never touch)
  [[ -L "$dst" ]] || return 1
  # Broken symlink pointing to a non-methodology path is still "ours" when
  # the original target was under a DinoStack checkout. If it's broken and
  # clearly not a DinoStack path we should not re-point it.
  local current_target
  current_target="$(readlink "$dst")"
  # Broken symlink: if target was under a methodology checkout, ours.
  # The target string itself encodes the path even when the file is gone.
  if [[ ! -e "$dst" ]]; then
    # Broken - check if original target is a methodology path
    [[ "$current_target" == */DinoStack/* || "$current_target" == *-DinoStack/* ]] && return 0
    return 1
  fi
  # Live symlink: check if it resolves under a methodology checkout.
  [[ "$current_target" == */DinoStack/* || "$current_target" == *-DinoStack/* ]] && return 0
  return 1
}

symlink_files() {
  local src_dir="$1"
  local dst_dir="$2"
  local label="$3"

  if [[ ! -d "$src_dir" ]]; then
    echo "  [skip] $label source directory not found: $src_dir"
    return
  fi

  mkdir -p "$dst_dir"

  for src_file in "$src_dir"/*.md; do
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
      echo "  + $name (would create)"
    else
      ln -s "$src_file" "$dst_file"
      echo "  + $name"
    fi
  done
}

# ---------------------------------------------------------------------------
# Symlink agents
# ---------------------------------------------------------------------------

echo "Linking agents..."
symlink_files "$AGENTS_SRC" "$AGENTS_DST" "agents"

# ---------------------------------------------------------------------------
# Symlink commands
# ---------------------------------------------------------------------------

echo "Linking commands..."
symlink_files "$COMMANDS_SRC" "$COMMANDS_DST" "commands"

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
# Symlink skill
# ---------------------------------------------------------------------------

SKILL_LINK_OK=true
SKILL_LINK_REASON=""

echo "Linking skill: dinostack..."

mkdir -p "$(dirname "$SKILLS_DST")"

if [[ -L "$SKILLS_DST" ]]; then
  current_target="$(readlink "$SKILLS_DST")"
  if [[ "$current_target" == "$SKILLS_SRC" ]]; then
    echo "  = engineering (already linked)"
  elif _ae_is_ours "$SKILLS_DST"; then
    # Stale symlink pointing to another methodology checkout - re-point it.
    if [[ "$AE_DRY_RUN" == "true" ]]; then
      echo "  ~ engineering (would re-point to repo_dir)"
      SKILL_LINK_OK=false
      SKILL_LINK_REASON="dry-run: stale symlink not re-pointed"
    else
      ln -sfn "$SKILLS_SRC" "$SKILLS_DST"
      echo "  ~ engineering (re-pointed to repo_dir)"
    fi
  else
    if [[ "$AE_DRY_RUN" == "true" ]]; then
      echo "  ! engineering (would skip: symlink points outside methodology checkout: $current_target)"
      SKILL_LINK_OK=false
      SKILL_LINK_REASON="symlink points outside methodology checkout: $current_target"
    else
      echo "  ! engineering (symlink points elsewhere: $current_target - skipping)"
      SKILL_LINK_OK=false
      SKILL_LINK_REASON="symlink points outside methodology checkout: $current_target"
    fi
  fi
elif [[ -e "$SKILLS_DST" ]]; then
  if [[ "$AE_DRY_RUN" == "true" ]]; then
    echo "  ! engineering (would skip: real file/directory exists at destination)"
    SKILL_LINK_OK=false
    SKILL_LINK_REASON="real file/directory exists at destination"
  else
    echo "  ! engineering (real file/directory exists at destination - skipping)"
    SKILL_LINK_OK=false
    SKILL_LINK_REASON="real file/directory exists at destination"
  fi
else
  if [[ "$AE_DRY_RUN" == "true" ]]; then
    echo "  + dinostack (would create)"
    SKILL_LINK_OK=false
    SKILL_LINK_REASON="dry-run: symlink not created"
  else
    ln -s "$SKILLS_SRC" "$SKILLS_DST"
    echo "  + dinostack"
  fi
fi

_ae_skill_link_warning() {
  echo "  WARNING: the dinostack skill is not linked to this checkout ($SKILL_LINK_REASON)."
  echo "  CLAUDE.md's managed block may reference the skill; the reference will not resolve"
  echo "  until the link is established. Re-run without --dry-run, or resolve the noted"
  echo "  conflict above and re-run install.sh."
}

if [[ "$SKILL_LINK_OK" != "true" ]]; then
  echo ""
  _ae_skill_link_warning
fi

# ---------------------------------------------------------------------------
# Output style: dinostack (DS-171)
#
# Copies (not symlinks - matches the DS-96/DS-104 absolutized-symlink
# hazard avoidance already established for .claude/skills/dinostack/*) the
# built output style to ~/.claude/output-styles/dinostack.md. Installed
# unconditionally, idempotent (plain overwrite - a stale copy after a
# methodology update would otherwise never refresh). Deliberately does NOT
# select it: the `outputStyle` key in ~/.claude/settings.json is never
# touched here. No ae_confirm() prompt - a file copy that requires
# explicit /config selection to take effect is not a behavior change
# requiring consent, matching the precedent of unprompted skill/command
# installs elsewhere in this script.
# ---------------------------------------------------------------------------

AE_OUTPUT_STYLE_SRC="$SKILLS_SRC/output-styles/dinostack.md"
AE_OUTPUT_STYLE_DST_DIR="$AE_CONFIG_DIR/output-styles"
AE_OUTPUT_STYLE_DST="$AE_OUTPUT_STYLE_DST_DIR/dinostack.md"
AE_OUTPUT_STYLE_INSTALLED=false

if [[ -f "$AE_OUTPUT_STYLE_SRC" ]]; then
  if [[ "$AE_DRY_RUN" == "true" ]]; then
    echo "  + output style: dinostack (would install to $AE_OUTPUT_STYLE_DST)"
  else
    mkdir -p "$AE_OUTPUT_STYLE_DST_DIR"
    cp "$AE_OUTPUT_STYLE_SRC" "$AE_OUTPUT_STYLE_DST"
    echo "  + output style: dinostack (installed, not selected - select via /config)"
    AE_OUTPUT_STYLE_INSTALLED=true
  fi
fi

# ---------------------------------------------------------------------------
# Remove stale pre-rename skill symlink (agentic-engineering -> dinostack)
#
# The skill directory/name was renamed from "agentic-engineering" to
# "dinostack". A pre-rename install left a symlink node at
# skills/agentic-engineering pointing into this checkout; without pruning it,
# every existing install keeps that orphaned skill directory forever. Same
# ownership discipline as the stale-command prune above: this is a symlink
# node (unlinking never traverses its target, so no -r is needed), and we
# only remove it when _ae_is_ours() confirms it points inside a methodology
# checkout - never a real directory or a symlink pointing elsewhere.
# ---------------------------------------------------------------------------

_ae_stale_skill_dst="$(dirname "$SKILLS_DST")/agentic-engineering"
if _ae_is_ours "$_ae_stale_skill_dst"; then
  if [[ "$AE_DRY_RUN" == "true" ]]; then
    echo "  ~ agentic-engineering (would remove: stale pre-rename skill symlink)"
  else
    rm -f "$_ae_stale_skill_dst"
    echo "  - removed agentic-engineering (stale pre-rename skill symlink)"
  fi
fi

# ---------------------------------------------------------------------------
# Hook snapshot (DS-54)
#
# Copies hooks/ + the four in-scope adapters' hook sources into a
# per-checkout snapshot dir at $HOME/.agentic/hooks-snapshot/<key>/, so a
# bare `git pull` cannot silently rewire a live session's hook commands.
# Graceful degradation: any failure here leaves AE_HOOKS_SNAPSHOT_DIR unset,
# and the settings-wiring block below falls back to the checkout path via
# the `AE_HOOKS_SNAPSHOT_DIR or repo_dir` idiom.
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

# ---------------------------------------------------------------------------
# Update settings.json
# ---------------------------------------------------------------------------

echo "Updating $SETTINGS..."

AE_SETTINGS_PATH="$SETTINGS" python3 - <<'PYEOF'
import json, os, sys

settings_path = os.environ.get("AE_SETTINGS_PATH") or os.path.expanduser("~/.claude/settings.json")
repo_dir = os.environ.get("REPO_DIR", "")
# DS-54: hook commands read from the session-stable snapshot when one was
# successfully synced; otherwise they fall back to the checkout path so
# install.sh degrades gracefully rather than ever dangling a re-point.
hooks_root = os.environ.get("AE_HOOKS_SNAPSHOT_DIR", "") or repo_dir

# Read existing settings
if os.path.exists(settings_path):
    with open(settings_path, "r") as f:
        settings = json.load(f)
else:
    settings = {}

hooks = settings.setdefault("hooks", {})

def upsert_hook(hook_list, script_basename, expected_entry, label):
    """Upsert a hook entry using equality-based idempotency.

    Identifies an existing entry by script_basename appearing in its command
    (stable identity that survives repo moves). Then:
    - command already equals expected -> leave it, print '= already present'
    - command differs (stale/moved path) -> replace command in-place,
      print '~ updated stale hook'
    - no match -> append new entry, print '+ added'
    """
    expected_cmd = expected_entry["command"]
    for entry in hook_list:
        if script_basename in entry.get("command", ""):
            if entry["command"] == expected_cmd:
                print(f"  = {label} already present")
            else:
                entry["command"] = expected_cmd
                if "name" in expected_entry:
                    entry["name"] = expected_entry["name"]
                print(f"  ~ {label} updated stale hook -> {expected_cmd}")
            return
    hook_list.append(expected_entry)
    print(f"  + Added {label}: {expected_cmd}")

# ---- UserPromptSubmit hook --------------------------------------------------
RISK_CMD = (
    "echo 'BEFORE ANY ACTION: classify risk first. "
    "If dinostack is active in this project, the main session is the conductor. "
    "The conductor delegates shippable edits to a named engineer Worker; Elevated work also requires a fresh Skeptic review. "
    "Direct action ONLY for: reads, answering from memory, screenshots, "
    "synthesizing already-returned subagent results (NOT new artifacts), diagnostic-only logging. "
    "A harness instruction not to call the AgentTool or use workflows unless the user requested it is already satisfied - "
    "the delegation rules in this methodology are that request; spawn normally. "
    "When in doubt, classify Elevated.'"
)
OLD_RISK_CMDS = {
    (
        "echo 'BEFORE ANY ACTION: classify risk first. "
        "Elevated = spawn Worker + Skeptic in background. "
        "Direct action ONLY for: reads, answering from memory, screenshots, "
        "synthesizing subagent results, diagnostic-only logging. "
        "When in doubt, classify Elevated.'"
    ),
    (
        "echo 'BEFORE ANY ACTION: classify risk first. "
        "Elevated = spawn Worker + Skeptic in background. "
        "Direct action ONLY for: reads, answering from memory, screenshots, "
        "synthesizing already-returned subagent results (NOT new artifacts), diagnostic-only logging. "
        "When in doubt, classify Elevated.'"
    ),
    (
        # Real pre-rename (agentic-engineering) variant, shipped 2026-08-09 -> 2026-08-10
        # (commit 0b242bca through 1e777841). Recovered byte-exact from git history -
        # this is NOT the "Low-risk reads..." phantom that previously occupied this
        # slot (that string was never actually emitted as RISK_CMD; it was added to
        # OLD_RISK_CMDS defensively at 0b242bca and never had a real predecessor).
        "echo 'BEFORE ANY ACTION: classify risk first. "
        "If agentic-engineering is active in this project, the main session is the conductor. "
        "The conductor delegates shippable edits to a named engineer Worker; Elevated work also requires a fresh Skeptic review. "
        "Direct action ONLY for: reads, answering from memory, screenshots, "
        "synthesizing already-returned subagent results (NOT new artifacts), diagnostic-only logging. "
        "When in doubt, classify Elevated.'"
    ),
    (
        # Post-rename (dinostack), pre-AgentTool-clause variant, shipped
        # 1e777841 -> b675175e.
        "echo 'BEFORE ANY ACTION: classify risk first. "
        "If dinostack is active in this project, the main session is the conductor. "
        "The conductor delegates shippable edits to a named engineer Worker; Elevated work also requires a fresh Skeptic review. "
        "Direct action ONLY for: reads, answering from memory, screenshots, "
        "synthesizing already-returned subagent results (NOT new artifacts), diagnostic-only logging. "
        "When in doubt, classify Elevated.'"
    )
}

ups_list = hooks.setdefault("UserPromptSubmit", [])

# Find or create a matcher "*" block
ups_star = None
for block in ups_list:
    if block.get("matcher") == "*":
        ups_star = block
        break

if ups_star is None:
    ups_star = {"matcher": "*", "hooks": []}
    ups_list.append(ups_star)

ups_star.setdefault("hooks", [])

# Risk-classification hook uses command equality, with stale-string migration.
# A settings.json can accumulate MORE THAN ONE risk-classification entry (e.g. a
# stale pre-rename hook left behind by an older install.sh that only ever
# migrated the first match) - collapse every current-or-stale match down to
# exactly one canonical entry, updated in place at the position of the FIRST
# match so unrelated hooks keep their relative order and a no-op re-run stays
# byte-identical.
risk_match_indices = [
    i for i, entry in enumerate(ups_star["hooks"])
    if entry.get("command") == RISK_CMD or entry.get("command") in OLD_RISK_CMDS
]

if not risk_match_indices:
    ups_star["hooks"].append({
        "type": "command",
        "command": RISK_CMD,
        "timeout": 5
    })
    print("  + Added UserPromptSubmit risk-classification hook")
else:
    first_idx = risk_match_indices[0]
    first_entry = ups_star["hooks"][first_idx]
    was_current = first_entry.get("command") == RISK_CMD
    extra_indices = risk_match_indices[1:]
    if extra_indices:
        # Collapsing 2+ entries to 1 always rewrites the survivor - there is
        # no single "already present" entry to leave untouched.
        first_entry["type"] = "command"
        first_entry["command"] = RISK_CMD
        first_entry["timeout"] = 5
        for idx in sorted(extra_indices, reverse=True):
            del ups_star["hooks"][idx]
        print(
            f"  ~ UserPromptSubmit risk-classification hook collapsed "
            f"{len(risk_match_indices)} current/stale entries to 1 current entry"
        )
    elif was_current:
        # True no-op: do NOT touch command/timeout here. Rewriting an
        # operator's customized timeout (e.g. 30) back to the default 5 while
        # printing "already present" would silently discard a local override.
        # "type" is a narrow exception - setdefault only repairs a MISSING
        # key (never overwrites a present-but-wrong value), consistent with
        # upsert_hook's identify-by-command-then-repair contract above
        # without disturbing timeout.
        first_entry.setdefault("type", "command")
        print("  = UserPromptSubmit risk-classification hook already present")
    else:
        first_entry["type"] = "command"
        first_entry["command"] = RISK_CMD
        first_entry["timeout"] = 5
        print("  ~ UserPromptSubmit risk-classification hook updated stale reminder")

SKILL_AUTO_CMD = f"AE_ADAPTER=claude bash {hooks_root}/hooks/skill-auto-load-check.sh"

upsert_hook(
    ups_star["hooks"],
    "skill-auto-load-check.sh",
    {"type": "command", "command": SKILL_AUTO_CMD, "timeout": 5},
    "UserPromptSubmit skill-auto-load-check hook",
)

# ---- Stop hook --------------------------------------------------------------
# --cadence=turn: the Stop hook fires once per TURN (not once per session per
# the Claude Code docs), so it only refreshes loop-state/batch-state liveness
# here - the terminal interrupted-mark lives on the SessionEnd hook below
# (session-end-wrap.js), which fires once per session.
STOP_CMD = f"node {hooks_root}/hooks/stop-context.js --cadence=turn"

stop_list = hooks.setdefault("Stop", [])

# Find or create a matcher "*" block
stop_star = None
for block in stop_list:
    if block.get("matcher") == "*":
        stop_star = block
        break

if stop_star is None:
    stop_star = {"matcher": "*", "hooks": []}
    stop_list.append(stop_star)

stop_star.setdefault("hooks", [])

upsert_hook(
    stop_star["hooks"],
    "stop-context.js",
    {"type": "command", "command": STOP_CMD, "timeout": 5},
    "Stop hook stop-context.js",
)

# Abdication guard: blocks the stop and injects a "proceed" directive when the
# conductor ends a turn by asking permission for a non-destructive next step.
# Registered AFTER stop-context.js so the context writer runs first.
# Scoped to the main session Stop event only (NOT SubagentStop).
# Default off (abdication_guard_enabled must be true in .agentic/config.json).
# Disable via: AE_ABDICATION_GUARD_DISABLE=1 in the environment.
ENFORCE_ABDICATION_CMD = f"python3 {hooks_root}/hooks/enforce-no-abdication.py"

upsert_hook(
    stop_star["hooks"],
    "enforce-no-abdication.py",
    {"type": "command", "command": ENFORCE_ABDICATION_CMD, "timeout": 10},
    "Stop hook enforce-no-abdication.py",
)

# Turn-shape guard (DS-122; DS-156; DS-171). Checks the shape of the
# conductor's final assistant message. As of DS-156 NOT uniformly advisory:
# the execution-turn structural check (_execution_prose_flag) can block the
# stop; the operator-decisions per-item shape check (_decision_item_sprawl_flag)
# remains advisory-only and surfaces via additionalContext. As of DS-171 the
# former answer-turn phrasing check (_answer_relevance_flag), the zero-warrant
# status-only check (_status_only_flag), and the turn-volume check
# (_turn_charge/_volume_flag) are all deleted from this hook - those rules
# now live in the dinostack Claude Code output style (installed below),
# not here.
# Registered AFTER enforce-no-abdication.py.
# Default ON (turn_shape_guard_enabled must be explicitly false in
# .agentic/config.json to disable). Disable via:
# AE_TURN_SHAPE_GUARD_DISABLE=1 in the environment.
#
# Uses a GUARDED command string, unlike its siblings' bare `python3 {path}`
# form: `python3 <missing path>` exits 2 (the BLOCKING Stop code), so if
# this file were ever removed while the registration survives in the
# operator's settings.json, every stop would silently block until
# hand-fixed. The `test -f ... && ... || exit 0` guard prevents that.
ENFORCE_TURN_SHAPE_CMD = (
    f"test -f {hooks_root}/hooks/enforce-turn-shape.py && "
    f"python3 {hooks_root}/hooks/enforce-turn-shape.py || exit 0"
)

upsert_hook(
    stop_star["hooks"],
    "enforce-turn-shape.py",
    {"type": "command", "command": ENFORCE_TURN_SHAPE_CMD, "timeout": 10},
    "Stop hook enforce-turn-shape.py",
)

# conductor_overreach advisory nudge (DS unit DE). Registered AFTER
# enforce-turn-shape.py. Its exit code is always 0, but its
# additionalContext output is surfaced by the harness as feedback that
# continues the turn (see the hook's own module docstring for the
# stop_hook_active/sentinel loop-guard this makes load-bearing) - a missing
# script must not silently block every stop either, so this uses the same
# GUARDED command form as enforce-turn-shape.py above
# (`test -f ... && ... || exit 0`), not a bare `node {path}` (see rationale
# at enforce-turn-shape.py's comment above, and .claude/install.sh:779).
CONDUCTOR_OVERREACH_CMD = (
    f"test -f {hooks_root}/hooks/conductor-overreach-nudge.js && "
    f"node {hooks_root}/hooks/conductor-overreach-nudge.js || exit 0"
)

upsert_hook(
    stop_star["hooks"],
    "conductor-overreach-nudge.js",
    {"type": "command", "command": CONDUCTOR_OVERREACH_CMD, "timeout": 10},
    "Stop hook conductor-overreach-nudge.js",
)

# ---- SessionEnd hook (deferred-wrap finalize) -------------------------------
# Finalizes a cleanly-ended session's pending marker to `ready` so the daemon
# can drain it. Find-or-create; re-running install must NOT duplicate it.
SESSION_END_CMD = f"node {hooks_root}/hooks/session-end-wrap.js"

session_end_list = hooks.setdefault("SessionEnd", [])

session_end_star = None
for block in session_end_list:
    if block.get("matcher") == "*":
        session_end_star = block
        break

if session_end_star is None:
    session_end_star = {"matcher": "*", "hooks": []}
    session_end_list.append(session_end_star)

session_end_star.setdefault("hooks", [])

upsert_hook(
    session_end_star["hooks"],
    "session-end-wrap.js",
    {"type": "command", "command": SESSION_END_CMD, "timeout": 5},
    "SessionEnd deferred-wrap hook",
)

# ---- SessionStart hook (version notice + deferred-wrap self-heal/launch) -----
# First SessionStart registration: the wrapper composes the version-check
# notice with the self-healing .claude-host sentinel and the guarded daemon
# launch. Find-or-create; re-running install must NOT duplicate it.
SESSION_START_CMD = f"bash {hooks_root}/hooks/session-start-wrap.sh"

session_start_list = hooks.setdefault("SessionStart", [])

session_start_star = None
for block in session_start_list:
    if block.get("matcher") == "*":
        session_start_star = block
        break

if session_start_star is None:
    session_start_star = {"matcher": "*", "hooks": []}
    session_start_list.append(session_start_star)

session_start_star.setdefault("hooks", [])

upsert_hook(
    session_start_star["hooks"],
    "session-start-wrap.sh",
    {"type": "command", "command": SESSION_START_CMD, "timeout": 5},
    "SessionStart deferred-wrap hook",
)

# ---- PreToolUse background-spawn + orchestrator-singularity + tier hooks ----
# NOTE - Task/Agent rename: Claude Code renamed the subagent-spawn tool from
# "Task" to "Agent". We wire BOTH matcher names so the hooks fire under either
# CC version. The hooks themselves also guard on both names internally for
# belt-and-suspenders coverage. Two PreToolUse blocks are created: one for
# "Task" (legacy) and one for "Agent" (current), each containing both hooks.
ENFORCE_BG_CMD = f"python3 {hooks_root}/hooks/enforce-background-spawn.py"
ENFORCE_SINGULARITY_CMD = f"python3 {hooks_root}/hooks/enforce-orchestrator-singularity.py"
ENFORCE_TIER_CMD = f"python3 {hooks_root}/hooks/enforce-tier.py"

# Uses a GUARDED command string (like enforce-turn-shape.py, unlike its
# bare-`python3 {path}` siblings above): `python3 <missing path>` exits 2
# (BLOCKING on PreToolUse), so if this file were ever removed while the
# registration survives in the operator's settings.json, every Skeptic
# spawn would silently deny until hand-fixed. The guard prevents that.
ENFORCE_SKEPTIC_ROUND_CAP_CMD = (
    f"test -f {hooks_root}/hooks/enforce-skeptic-round-cap.py && "
    f"python3 {hooks_root}/hooks/enforce-skeptic-round-cap.py || exit 0"
)
# Guarded form (never bare `python3 {path}`): `python3 <missing>.py` exits 2,
# which is BLOCKING on PreToolUse - a registration that outlives this script
# would deny every Task/Agent spawn in every session. See hooks/AGENTS.md
# §Registering a new enforce-*.py hook.
ENFORCE_NESTED_WORKTREE_SPAWN_CMD = (
    f"test -f {hooks_root}/hooks/enforce-nested-worktree-spawn.py && "
    f"python3 {hooks_root}/hooks/enforce-nested-worktree-spawn.py || exit 0"
)
# Guarded form (never bare `python3 {path}`): `python3 <missing>.py` exits 2,
# which is BLOCKING on PreToolUse - a registration that outlives this script
# would deny every Skeptic spawn in every session. See hooks/AGENTS.md
# §Registering a new enforce-*.py hook.
ENFORCE_SKEPTIC_NEUTRALITY_CMD = (
    f"test -f {hooks_root}/hooks/enforce-skeptic-neutrality.py && "
    f"python3 {hooks_root}/hooks/enforce-skeptic-neutrality.py || exit 0"
)
# Guarded form (never bare `python3 {path}`): `python3 <missing>.py` exits 2,
# which is BLOCKING on PreToolUse - a registration that outlives this script
# would deny every engineer/qa-engineer/release-orchestrator spawn in every
# session. See hooks/AGENTS.md §Registering a new enforce-*.py hook.
ENFORCE_WORKTREE_ISOLATION_SPAWN_CMD = (
    f"test -f {hooks_root}/hooks/enforce-worktree-isolation-spawn.py && "
    f"python3 {hooks_root}/hooks/enforce-worktree-isolation-spawn.py || exit 0"
)

ptu_list = hooks.setdefault("PreToolUse", [])

for spawn_matcher in ("Task", "Agent"):
    # Find or create a matcher block for this tool name.
    ptu_block = None
    for block in ptu_list:
        if block.get("matcher") == spawn_matcher:
            ptu_block = block
            break

    if ptu_block is None:
        ptu_block = {"matcher": spawn_matcher, "hooks": []}
        ptu_list.append(ptu_block)

    ptu_block.setdefault("hooks", [])

    upsert_hook(
        ptu_block["hooks"],
        "enforce-background-spawn.py",
        {"type": "command", "command": ENFORCE_BG_CMD, "timeout": 5},
        f"PreToolUse({spawn_matcher}) background-spawn enforcement hook",
    )

    # DS-190: ADVISORY-ONLY (never denies) - warns once per session when a
    # Task/Agent spawn is issued from a conductor session whose own cwd is
    # itself inside a git worktree rather than the primary checkout. To
    # disable: set AE_NESTED_WORKTREE_GUARD_DISABLE=1 in the environment
    # that launches Claude Code, then restart.
    upsert_hook(
        ptu_block["hooks"],
        "enforce-nested-worktree-spawn.py",
        {"type": "command", "command": ENFORCE_NESTED_WORKTREE_SPAWN_CMD, "timeout": 5},
        f"PreToolUse({spawn_matcher}) nested-worktree-spawn advisory hook",
    )

    # Denies an engineer/qa-engineer/release-orchestrator spawn missing
    # isolation: "worktree" (content/sections/02-delegation.md's no-exception
    # worktree-isolation mandate). The hook carries a kill-switch (the
    # mandate is absolute, but its enforcement mechanism must stay
    # recoverable - see hooks/AGENTS.md §No gating on inferred session
    # capability and the hook's own module docstring). To disable: set
    # AE_WORKTREE_ISOLATION_GUARD_DISABLE=1 in the environment that
    # launches Claude Code, then restart.
    upsert_hook(
        ptu_block["hooks"],
        "enforce-worktree-isolation-spawn.py",
        {"type": "command", "command": ENFORCE_WORKTREE_ISOLATION_SPAWN_CMD, "timeout": 5},
        f"PreToolUse({spawn_matcher}) worktree-isolation-spawn enforcement hook",
    )

    # Denies spawns issued from inside a subagent context (detected via the
    # top-level agent_id field). To disable: set AE_SINGULARITY_GUARD_DISABLE=1
    # in the environment that launches Claude Code, then restart.
    upsert_hook(
        ptu_block["hooks"],
        "enforce-orchestrator-singularity.py",
        {"type": "command", "command": ENFORCE_SINGULARITY_CMD, "timeout": 5},
        f"PreToolUse({spawn_matcher}) orchestrator-singularity enforcement hook",
    )

    # Denies an EXPLICIT model downgrade on a mandated-Tier-3 review agent
    # (skeptic / security-auditor). Escalate-only, fail-open. To disable: set
    # AE_TIER_GUARD_DISABLE=1 in the environment that launches Claude Code.
    upsert_hook(
        ptu_block["hooks"],
        "enforce-tier.py",
        {"type": "command", "command": ENFORCE_TIER_CMD, "timeout": 5},
        f"PreToolUse({spawn_matcher}) tier-enforcement hook",
    )

    # Mechanically enforces the ad-hoc Skeptic round-budget policy
    # (content/sections/05-qa-gate.md §Re-route limits): denies a 4th
    # Skeptic round for the same unit unless the conductor has recorded an
    # explicit ship or escalate decision in the per-unit
    # .agentic/skeptic-round-*.json state file. Fires only on
    # subagent_type == "skeptic"; fail-open on any error (missing git repo,
    # unparsable state, write failure).
    upsert_hook(
        ptu_block["hooks"],
        "enforce-skeptic-round-cap.py",
        {"type": "command", "command": ENFORCE_SKEPTIC_ROUND_CAP_CMD, "timeout": 5},
        f"PreToolUse({spawn_matcher}) skeptic-round-cap enforcement hook",
    )

    # Mechanically enforces Skeptic-brief neutrality at spawn time
    # (content/references/skeptic-protocol.md §7 "Neutrality requirement"):
    # denies a spawn whose Global-context field 7 contains an untagged
    # claim-bearing sentence (the primary structural rule), or whose
    # adversarial brief matches a narrow conductor-composed-steer phrase
    # (categories B/C only). Fires only on subagent_type == "skeptic";
    # fail-open on any error. Kill-switch:
    # AE_SKEPTIC_NEUTRALITY_GUARD_DISABLE=1.
    upsert_hook(
        ptu_block["hooks"],
        "enforce-skeptic-neutrality.py",
        {"type": "command", "command": ENFORCE_SKEPTIC_NEUTRALITY_CMD, "timeout": 5},
        f"PreToolUse({spawn_matcher}) skeptic-neutrality enforcement hook",
    )

    # Emits a spawn_start telemetry event to .agentic/events.jsonl on every
    # subagent spawn. Fully fail-open (no deny, no stdout). Enables deterministic
    # events.jsonl creation in ad-hoc sessions that never run /implement-ticket.
    SPAWN_EMIT_CMD = f"node {hooks_root}/hooks/pre-tool-use-spawn-emit.js"
    upsert_hook(
        ptu_block["hooks"],
        "pre-tool-use-spawn-emit.js",
        {"type": "command", "command": SPAWN_EMIT_CMD, "timeout": 5},
        f"PreToolUse({spawn_matcher}) spawn-emit telemetry hook",
    )

# ---- PreToolUse ticket-batching guard (mcp jira/linear create + Bash bypass)
# Enforces the Follow-up Ticket Creation Discipline's operator-confirmation
# rule (content/references/delegation-detail.md §Follow-up Ticket Creation
# Discipline): allows the 1st tracker-ticket creation this session silently
# only while the transcript shows no subagent spawn and no existing-ticket
# arrival, and denies every other one without a bin/ds-ticket-grant
# grant. Fires on
# mcp__mcp-atlassian__jira_create_issue, mcp__linear__save_issue (creation
# only - an id-bearing call is an update and never counted), and Bash (a
# direct Jira REST POST or Linear issueCreate GraphQL bypass). Exempt when
# the session transcript carries a /ds-feedback-triage command marker. Fail-open on any error. Kill-switch:
# AE_TICKET_BATCH_GUARD_DISABLE=1.
#
# Uses a GUARDED command string, unlike a bare `python3 {path}` form - see
# the skeptic-round-cap block's comment above for why: a bare form exits 2
# (BLOCKING on PreToolUse) when the script is missing, so a registration
# outliving the script would deny every guarded MCP/Bash call in every
# session. The guard prevents that.
ENFORCE_TICKET_BATCHING_CMD = (
    f"test -f {hooks_root}/hooks/enforce-ticket-batching.py && "
    f"python3 {hooks_root}/hooks/enforce-ticket-batching.py || exit 0"
)

for ticket_matcher in (
    "mcp__mcp-atlassian__jira_create_issue",
    "mcp__linear__save_issue",
    "Bash",
):
    ptu_ticket_block = None
    for block in ptu_list:
        if block.get("matcher") == ticket_matcher:
            ptu_ticket_block = block
            break

    if ptu_ticket_block is None:
        ptu_ticket_block = {"matcher": ticket_matcher, "hooks": []}
        ptu_list.append(ptu_ticket_block)

    ptu_ticket_block.setdefault("hooks", [])

    upsert_hook(
        ptu_ticket_block["hooks"],
        "enforce-ticket-batching.py",
        {"type": "command", "command": ENFORCE_TICKET_BATCHING_CMD, "timeout": 5},
        f"PreToolUse({ticket_matcher}) ticket-batching guard hook",
    )

# ---- PostToolUse capture-nudge hook -----------------------------------------
# Surfaces an in-session capture-gap nudge when a subagent spawn launches and the
# session has a learning-worthy event with no learning captured yet. Claude Code
# renamed the spawn tool from "Task" to "Agent", so we wire BOTH matcher names
# (same dual Task/Agent block pattern as the PreToolUse hooks above), each
# find-or-create idempotent. Claude-Code-only (consistent with deferred-wrap hooks).
CAPTURE_NUDGE_CMD = f"node {hooks_root}/hooks/post-tool-use-capture-nudge.js"

ptu_post_list = hooks.setdefault("PostToolUse", [])

for spawn_matcher in ("Task", "Agent"):
    # Find or create a matcher block for this tool name.
    ptu_post_block = None
    for block in ptu_post_list:
        if block.get("matcher") == spawn_matcher:
            ptu_post_block = block
            break

    if ptu_post_block is None:
        ptu_post_block = {"matcher": spawn_matcher, "hooks": []}
        ptu_post_list.append(ptu_post_block)

    ptu_post_block.setdefault("hooks", [])

    upsert_hook(
        ptu_post_block["hooks"],
        "post-tool-use-capture-nudge.js",
        {"type": "command", "command": CAPTURE_NUDGE_CMD, "timeout": 5},
        f"PostToolUse({spawn_matcher}) capture-nudge hook",
    )

# ---- SubagentStop spawn-complete telemetry hook (DS-160) --------------------
# Fires when a subagent actually FINISHES (unlike PostToolUse(Task/Agent),
# which fires at spawn LAUNCH - see hooks/pre-tool-use-spawn-emit.js header).
# Emits a hook-sourced spawn_complete event with a real wall_seconds figure,
# closing the gap where spawn_complete previously depended entirely on the
# conductor LLM remembering to run `ds-emit spawn_complete ...` inline (an
# LLM-semantic event with no deterministic trigger). Fully fail-open, no
# stdout, no deny - matcher "*" since SubagentStop has no tool-name matcher.
SUBAGENT_STOP_SPAWN_EMIT_CMD = f"node {hooks_root}/hooks/subagent-stop-spawn-emit.js"

subagent_stop_list = hooks.setdefault("SubagentStop", [])

subagent_stop_star = None
for block in subagent_stop_list:
    if block.get("matcher") == "*":
        subagent_stop_star = block
        break

if subagent_stop_star is None:
    subagent_stop_star = {"matcher": "*", "hooks": []}
    subagent_stop_list.append(subagent_stop_star)

subagent_stop_star.setdefault("hooks", [])

upsert_hook(
    subagent_stop_star["hooks"],
    "subagent-stop-spawn-emit.js",
    {"type": "command", "command": SUBAGENT_STOP_SPAWN_EMIT_CMD, "timeout": 5},
    "SubagentStop spawn-emit telemetry hook",
)

# ---- PreToolUse AskUserQuestion default-enforcement hook --------------------
ptu_list = hooks.setdefault("PreToolUse", [])
ENFORCE_AUQ_CMD = f"python3 {hooks_root}/hooks/enforce-askuserquestion-default.py"

# Find or create a matcher "AskUserQuestion" block.
ptu_auq = None
for block in ptu_list:
    if block.get("matcher") == "AskUserQuestion":
        ptu_auq = block
        break

if ptu_auq is None:
    ptu_auq = {"matcher": "AskUserQuestion", "hooks": []}
    ptu_list.append(ptu_auq)

ptu_auq.setdefault("hooks", [])

upsert_hook(
    ptu_auq["hooks"],
    "enforce-askuserquestion-default.py",
    {"type": "command", "command": ENFORCE_AUQ_CMD, "timeout": 5},
    "PreToolUse AskUserQuestion default-enforcement hook",
)

# ---- PreToolUse planning-artifact advisory hook (Write + Edit matchers) ----
# Surfaces a non-blocking advisory when a docs/planning/ file is written
# without a recent architect spawn on record. WARN ONLY - never blocks writes.
# Kill-switch: AE_PLANNING_GUARD_DISABLE=1. Wired on both "Write" and "Edit"
# matchers; uses the same idempotent upsert pattern as the AUQ block above.
ENFORCE_PLANNING_CMD = f"python3 {hooks_root}/hooks/enforce-planning-artifact-spawn.py"

for file_matcher in ("Write", "Edit"):
    # Find or create a matcher block for this tool name.
    ptu_file_block = None
    for block in ptu_list:
        if block.get("matcher") == file_matcher:
            ptu_file_block = block
            break

    if ptu_file_block is None:
        ptu_file_block = {"matcher": file_matcher, "hooks": []}
        ptu_list.append(ptu_file_block)

    ptu_file_block.setdefault("hooks", [])

    upsert_hook(
        ptu_file_block["hooks"],
        "enforce-planning-artifact-spawn.py",
        {"type": "command", "command": ENFORCE_PLANNING_CMD, "timeout": 5},
        f"PreToolUse({file_matcher}) planning-artifact advisory hook",
    )

# ---- PreToolUse shippable-edit guard (Write + Edit + MultiEdit matchers) ---
# Denies a conductor-direct (agent_id absent) Write/Edit/MultiEdit against a
# shippable file inside the DinoStack checkout; allows the same edit from an
# engineer subagent (agent_id present). Mechanically backstops METHODOLOGY
# §Git Workflow's shippable/exempt classifier for the conductor (DS-94).
# Fully fail-open on any error. Kill-switch: AE_SHIPPABLE_GUARD_DISABLE=1.
# Wired on "Write", "Edit", and "MultiEdit" matchers; same idempotent
# upsert pattern as the planning-artifact block above.
ENFORCE_SHIPPABLE_CMD = f"python3 {hooks_root}/hooks/enforce-shippable-edit.py"

for file_matcher in ("Write", "Edit", "MultiEdit"):
    # Find or create a matcher block for this tool name.
    ptu_shippable_block = None
    for block in ptu_list:
        if block.get("matcher") == file_matcher:
            ptu_shippable_block = block
            break

    if ptu_shippable_block is None:
        ptu_shippable_block = {"matcher": file_matcher, "hooks": []}
        ptu_list.append(ptu_shippable_block)

    ptu_shippable_block.setdefault("hooks", [])

    upsert_hook(
        ptu_shippable_block["hooks"],
        "enforce-shippable-edit.py",
        {"type": "command", "command": ENFORCE_SHIPPABLE_CMD, "timeout": 5},
        f"PreToolUse({file_matcher}) shippable-edit guard hook",
    )

# ---- PreToolUse worktree-read guard ("Read" matcher) ------------------------
# Denies a worktree-isolated subagent (agent_id present) Read that reaches
# into the PRIMARY checkout instead of the agent's own isolation worktree
# (DS-150). caller_root comes from the payload's cwd field, primary_root
# from CLAUDE_PROJECT_DIR; both are realpath-normalized before the
# containment test. Never fires on a main-session call (agent_id absent) or
# a subagent that is not worktree-isolated. Fully fail-open on any error.
# Kill-switch: AE_WORKTREE_READ_GUARD_DISABLE=1.
#
# Uses a GUARDED command string, unlike a bare `python3 {path}` form:
# `python3 <missing path>` exits 2 (the BLOCKING PreToolUse code), so if
# this file were ever removed while the registration survives in the
# operator's settings.json, every Read in every session (conductor
# included) would silently deny until hand-fixed. The
# `test -f ... && ... || exit 0` guard prevents that.
ENFORCE_WORKTREE_READ_CMD = (
    f"test -f {hooks_root}/hooks/enforce-worktree-read.py && "
    f"python3 {hooks_root}/hooks/enforce-worktree-read.py || exit 0"
)

ptu_worktree_read_block = None
for block in ptu_list:
    if block.get("matcher") == "Read":
        ptu_worktree_read_block = block
        break

if ptu_worktree_read_block is None:
    ptu_worktree_read_block = {"matcher": "Read", "hooks": []}
    ptu_list.append(ptu_worktree_read_block)

ptu_worktree_read_block.setdefault("hooks", [])

upsert_hook(
    ptu_worktree_read_block["hooks"],
    "enforce-worktree-read.py",
    {"type": "command", "command": ENFORCE_WORKTREE_READ_CMD, "timeout": 5},
    "PreToolUse(Read) worktree-read guard hook",
)

# ---- PreToolUse worktree-write guard ("Write"/"Edit"/"MultiEdit" matchers) -
# Denies a worktree-isolated subagent (agent_id present) Write/Edit/MultiEdit
# that reaches into the PRIMARY checkout instead of the agent's own isolation
# worktree - the write-side companion to the read guard above. Catches the
# case enforce-shippable-edit.py cannot: a subagent that has silently fallen
# back to the primary checkout still carries a present agent_id and sails
# through that guard, which only gates on agent_id absence (conductor-vs-
# subagent), not on isolation containment. caller_root comes from the
# payload's cwd field, primary_root from CLAUDE_PROJECT_DIR; both are
# realpath-normalized before the containment test. Never fires on a
# main-session call (agent_id absent) or a subagent that is not worktree-
# isolated. Fully fail-open on any error.
# Kill-switch: AE_WORKTREE_WRITE_GUARD_DISABLE=1.
#
# Uses a GUARDED command string, unlike a bare `python3 {path}` form - see
# the worktree-read guard's comment above for why: a bare form exits 2
# (BLOCKING) when the script is missing, so a registration outliving the
# script would silently deny every Write/Edit/MultiEdit in every session.
ENFORCE_WORKTREE_WRITE_CMD = (
    f"test -f {hooks_root}/hooks/enforce-worktree-write.py && "
    f"python3 {hooks_root}/hooks/enforce-worktree-write.py || exit 0"
)

for file_matcher in ("Write", "Edit", "MultiEdit"):
    ptu_worktree_write_block = None
    for block in ptu_list:
        if block.get("matcher") == file_matcher:
            ptu_worktree_write_block = block
            break

    if ptu_worktree_write_block is None:
        ptu_worktree_write_block = {"matcher": file_matcher, "hooks": []}
        ptu_list.append(ptu_worktree_write_block)

    ptu_worktree_write_block.setdefault("hooks", [])

    upsert_hook(
        ptu_worktree_write_block["hooks"],
        "enforce-worktree-write.py",
        {"type": "command", "command": ENFORCE_WORKTREE_WRITE_CMD, "timeout": 5},
        f"PreToolUse({file_matcher}) worktree-write guard hook",
    )

# Symlink guard: never write through a symlink (open("w") follows it and truncates
# the real target). PoC verified: symlinking settings.json to a victim file and
# running installer overwrites the victim's content through the link.
if os.path.islink(settings_path):
    sys.stderr.write(f"refusing to write through symlink: {settings_path}\n")
    sys.exit(1)
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print("  settings.json written.")

# ---- Anti-orphan check: warn (non-fatal) on any hook command referencing a
# script path that does not exist on disk. Catches drift such as a hook
# wired against a moved/renamed/deleted script. Scoped to tokens containing
# "/hooks/" that end in .py, .js, or .sh, to avoid false-positiving on the
# echo-based risk-classification hook commands (which have no script path).
def _find_orphaned_hook_scripts(obj):
    orphans = []

    def _walk(node):
        if isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            cmd = node.get("command")
            if isinstance(cmd, str):
                for token in cmd.split():
                    if "/hooks/" in token and token.endswith((".py", ".js", ".sh")):
                        if not os.path.exists(token):
                            orphans.append(token)
            for v in node.values():
                if isinstance(v, (dict, list)):
                    _walk(v)

    _walk(obj)
    return orphans

_orphans = _find_orphaned_hook_scripts(settings)
if _orphans:
    print()
    for _orphan in sorted(set(_orphans)):
        print("  !! ORPHANED HOOK: " + _orphan + " referenced in " + settings_path + " does not exist on disk")
    print("  !! Non-fatal - re-run install.sh after the hook script is restored, or remove the stale entry.")
PYEOF

# ---------------------------------------------------------------------------
# Deferred-wrap .claude-host sentinel (belt; MAJOR-B)
#
# When install.sh runs INSIDE a project (a .agentic/ dir exists in the install
# cwd), drop the .agentic/wrap/claude-host sentinel for THAT project so the
# deferred-wrap feature can activate immediately. This is the belt for the
# install-cwd project only; the SessionStart self-heal (session-start-wrap.sh)
# is the PRIMARY mechanism that covers every project on its next Claude session.
# create-if-absent + fully fail-open; we never drop sentinels for arbitrary
# projects.
# ---------------------------------------------------------------------------
if [[ -d "$PWD/.agentic" && ! -f "$PWD/.agentic/wrap/claude-host" ]]; then
  mkdir -p "$PWD/.agentic/wrap" 2>/dev/null || true
  if : > "$PWD/.agentic/wrap/claude-host" 2>/dev/null; then
    echo "  + dropped deferred-wrap .agentic/wrap/claude-host sentinel in $PWD"
  fi
fi

# ---------------------------------------------------------------------------
# Update ~/.claude/CLAUDE.md
# ---------------------------------------------------------------------------

# DS-143: the Skill Loading table body is single-sourced from
# content/templates/claude-managed-content.md. When SKILL_LINK_OK == true
# (the skill symlink resolves, so the methodology loads on skill invocation
# instead), the three @-import lines are dropped and the registry-refresh
# restart notice below fires unconditionally, since the skill body was
# (re)written on this run regardless of whether CLAUDE.md's bytes changed.
# When SKILL_LINK_OK != true, the imports are appended after the table
# exactly as before, and a warning is printed instead of the notice - the
# imports must never be stripped without a working skill symlink to fall
# back on.
if [[ "$AE_DRY_RUN" == "true" ]]; then
  echo "  [dry-run] would update managed-by-agentic-engineering section in $AE_CLAUDE_MD_PATH"
else
echo "Updating $AE_CLAUDE_MD_PATH..."

AE_CONFIG_DIR="$AE_CONFIG_DIR" AE_CLAUDE_MD_PATH="$AE_CLAUDE_MD_PATH" AE_REPO_DIR="$REPO_DIR" AE_SKILL_LINK_OK="$SKILL_LINK_OK" AE_CONFIG_PATH="$AE_CONFIG_PATH" python3 - <<'PYEOF'
import json, os, re, sys

# Prefer the shell-resolved path: on a bridged host AE_CONFIG_DIR/CLAUDE.md is
# a symlink, and ae_resolve_write_target has already resolved it to the real
# file (or refused outright when it escaped $HOME). Falling back to the
# derivation keeps this block working if the variable is ever absent.
target = os.environ.get("AE_CLAUDE_MD_PATH") or os.path.join(
    os.environ.get("AE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "CLAUDE.md"
)
begin_marker = "<!-- BEGIN managed-by-agentic-engineering -->"
end_marker = "<!-- END managed-by-agentic-engineering -->"

repo_dir = os.environ.get("AE_REPO_DIR", "")
skill_link_ok = os.environ.get("AE_SKILL_LINK_OK", "") == "true"
config_path = os.environ.get("AE_CONFIG_PATH", "")

import_lines = [
    "@skills/dinostack/METHODOLOGY.md",
    "@skills/dinostack/rules/code-standards.md",
    "@skills/dinostack/rules/conventions.md",
]
# Migration detection must recognize an @-import line written under EITHER
# skill-directory name: a block on disk from before the skill directory was
# renamed from agentic-engineering to dinostack still carries the OLD path
# literal, not import_lines[0]'s current one. Checking only the current
# literal here would silently disarm the one-time skill_auto_load migration
# for exactly the pre-rename installs it exists to catch.
old_import_re = re.compile(r'@skills/(?:agentic-engineering|dinostack)/METHODOLOGY\.md')

template_path = os.path.join(repo_dir, "content", "templates", "claude-managed-content.md")
try:
    with open(template_path, "r") as f:
        template_raw = f.read()
except OSError as e:
    sys.stderr.write(f"  ! managed-content template not found or unreadable: {template_path} ({e})\n")
    sys.stderr.write("  ! CLAUDE.md was NOT touched.\n")
    sys.exit(1)

# Strip the leading manifest HTML comment: everything through the closing "-->"
# of that comment block. Only the body after it ships into CLAUDE.md.
# Contract aligned with scripts/check-resident-budget.sh (MINOR-3, DS-143
# Skeptic loop 2): require the "-->" terminator and fail loudly when absent,
# rather than silently falling back to shipping the whole file (manifest
# comment included) into the user's ~/.claude/CLAUDE.md.
close_idx = template_raw.find("-->")
if close_idx == -1:
    sys.stderr.write(
        f"  ! could not find manifest comment terminator ('-->') in {template_path}\n"
    )
    sys.stderr.write("  ! CLAUDE.md was NOT touched.\n")
    sys.exit(1)
template_body = template_raw[close_idx + 3:]
template_body = template_body.strip("\n")

block_lines = [begin_marker, template_body]
if not skill_link_ok:
    block_lines.append("")
    block_lines.extend(import_lines)
block_lines.append(end_marker)
managed_content = "\n".join(block_lines)

if os.path.exists(target):
    with open(target, "r") as f:
        existing = f.read()
else:
    existing = ""

# Compiled once - used both by the migration detection below and by the
# managed-block rewrite further down.
pattern = re.compile(
    r'<!-- BEGIN managed-by-agentic-engineering -->.*?<!-- END managed-by-agentic-engineering -->',
    re.DOTALL
)

# One-time migration: if a MANAGED BLOCK'S OWN CONTENT ON DISK BEFORE this
# rewrite still carried the old always-loaded @-import, AND this run is
# actually stripping it (skill_link_ok), force skill_auto_load=true so users
# are not left with neither the always-on imports nor the trigger-loaded
# skill. Detection is scoped to the managed block(s) only, not the whole
# file - a user's own prose elsewhere in CLAUDE.md that happens to contain
# the import string (their own notes, a hand-restored old block outside the
# markers, etc.) must never trigger this.
#
# Checked ALL matches, not just the first: the rewrite below (pattern.sub,
# no count=) replaces every managed block in the file, so detection must
# scan every one too - a file with two well-formed blocks (new-format first,
# old-format second) would otherwise strip the second block's imports while
# migrating stayed False, since a first-match-only check only inspects the
# first block.
#
# Self-disarming: the rewrite below replaces EVERY matched block with the
# same new-format managed_content, so once this run (or a user editing by
# hand) has removed the marker string from every managed block on disk,
# this condition can never fire again for this installation.
old_block_matches = list(pattern.finditer(existing))
migrating = skill_link_ok and config_path and any(
    old_import_re.search(m.group(0)) for m in old_block_matches
)

if migrating:
    try:
        if os.path.islink(config_path):
            raise OSError(f"refusing to write through symlink: {config_path}")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                cfg = json.load(f)
        else:
            cfg = {}
        cfg["skill_auto_load"] = True
        with open(config_path, "w") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        print("  + one-time migration: forced skill_auto_load=true (old @-imports were being removed)")
    except Exception as e:
        sys.stderr.write(f"  ! migration write failed: {e}\n")

# Symlink guard: never write through a symlink (open("w") follows it and truncates
# the real target). PoC verified: symlinking CLAUDE.md to a victim file and running
# installer overwrites the victim's content through the link.
if os.path.islink(target):
    sys.stderr.write(f"refusing to write through symlink: {target}\n")
    sys.exit(1)

if begin_marker in existing and end_marker in existing:
    # Use a callable replacement, not a string one: pattern.sub() interprets
    # backslash escapes (e.g. \1, \g<name>) in a string replacement, and the
    # template body is a markdown table where a literal pipe is written as
    # "\|" - a callable sidesteps that interpretation entirely (MINOR-1,
    # DS-143 Skeptic loop 2).
    updated = pattern.sub(lambda _: managed_content, existing)
    with open(target, "w") as f:
        f.write(updated)
    print(f"  = Updated managed-by-agentic-engineering section in {target}")
else:
    # Append to end of file
    if existing:
        updated = existing.rstrip("\n") + "\n\n" + managed_content + "\n"
    else:
        updated = managed_content + "\n"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write(updated)
    if existing:
        print(f"  + Appended managed-by-agentic-engineering section to {target}")
    else:
        print(f"  + Created {target} with managed-by-agentic-engineering section")
PYEOF

if [[ "$SKILL_LINK_OK" != "true" ]]; then
  echo "  WARNING: keeping the @-import lines in CLAUDE.md's managed block ($SKILL_LINK_REASON)."
  echo "  Resolve the skill symlink conflict noted above, then re-run install.sh to switch to"
  echo "  skill-triggered methodology loading."
else
  echo ""
  echo "IMPORTANT: skill definitions changed. Start a NEW Claude Code session"
  echo "before relying on /dinostack - the currently running session's"
  echo "skill registry may not reflect this update yet."
fi
fi

# ---------------------------------------------------------------------------
# Write repo_dir to ~/.agentic/agentic-engineering-config.json (guarded)
#
# Persists the canonical checkout path so hooks and /update-agentic-engineering
# can find it in future sessions (bootstrap.sh does this unconditionally, but
# standalone `bash .claude/install.sh` runs skip bootstrap, leaving repo_dir
# unset until now).
#
# Clobber-guard: ONLY writes when the config is absent, has no repo_dir key,
# has an invalid (non-git-repo) repo_dir, or already equals REPO_DIR.
# A valid DIFFERENT repo_dir is NEVER overwritten - a warning is printed
# instead. Use ds-doctor or set repo_dir manually if the intent is to
# switch canonical checkouts.
# ---------------------------------------------------------------------------

# Source the lib so we can call validate_repo_dir.
# Gracefully skip if the lib is not available (e.g. older checkout).
if [[ -f "$REPO_DIR/scripts/lib/repo-dir.sh" ]]; then
  # shellcheck source=scripts/lib/repo-dir.sh
  . "$REPO_DIR/scripts/lib/repo-dir.sh"

  _ae_write_repo_dir() {
    local target_repo_dir="$1"
    python3 - "$HOME/.agentic/agentic-engineering-config.json" "$target_repo_dir" <<'PYEOF'
import json, sys, os
cfg, repo_dir = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(cfg), exist_ok=True)
data = {}
if os.path.exists(cfg):
    try:
        with open(cfg) as f:
            data = json.load(f)
    except Exception:
        data = {}
data["repo_dir"] = repo_dir
# Atomic: write to tmp then rename
import tempfile
tmp = cfg + ".tmp." + str(os.getpid())
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
os.replace(tmp, cfg)
PYEOF
  }

  if [[ "$AE_DRY_RUN" == "true" ]]; then
    # Under --dry-run: determine which branch WOULD run and print intent only.
    _ae_config="$HOME/.agentic/agentic-engineering-config.json"
    _existing_repo_dir=""
    if [[ -f "$_ae_config" ]]; then
      _existing_repo_dir="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$_ae_config" 2>/dev/null)" || _existing_repo_dir=""
    fi
    if [[ -z "$_existing_repo_dir" ]]; then
      echo "  [dry-run] would write repo_dir=$REPO_DIR to $_ae_config"
    elif ! validate_repo_dir "$_existing_repo_dir"; then
      echo "  [dry-run] would update repo_dir=$REPO_DIR (previous '$_existing_repo_dir' was not a valid git repo)"
    else
      _existing_real="$(cd "$_existing_repo_dir" 2>/dev/null && pwd -P || echo "$_existing_repo_dir")"
      _this_real="$(cd "$REPO_DIR" 2>/dev/null && pwd -P || echo "$REPO_DIR")"
      if [[ "$_existing_real" == "$_this_real" ]]; then
        echo "  [dry-run] would skip repo_dir (already set to this checkout)"
      else
        echo "  [dry-run] would warn: existing repo_dir '$_existing_repo_dir' differs from '$REPO_DIR'; not overwriting"
      fi
    fi
  else
    _ae_config="$HOME/.agentic/agentic-engineering-config.json"
    _existing_repo_dir=""
    if [[ -f "$_ae_config" ]]; then
      _existing_repo_dir="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$_ae_config" 2>/dev/null)" || _existing_repo_dir=""
    fi

    if [[ -z "$_existing_repo_dir" ]]; then
      # No existing repo_dir - write unconditionally.
      if _ae_write_repo_dir "$REPO_DIR" 2>/dev/null; then
        echo "  + wrote repo_dir=$REPO_DIR to $_ae_config"
      else
        echo "  ! warning: failed to write repo_dir to $_ae_config (non-fatal)" >&2
      fi
    elif ! validate_repo_dir "$_existing_repo_dir"; then
      # Existing value is not a valid git repo - overwrite with current checkout.
      if _ae_write_repo_dir "$REPO_DIR" 2>/dev/null; then
        echo "  ~ updated repo_dir=$REPO_DIR (previous '$_existing_repo_dir' was not a valid git repo)"
      else
        echo "  ! warning: failed to update repo_dir in $_ae_config (non-fatal)" >&2
      fi
    else
      # Resolve both paths to canonical forms before comparing.
      _existing_real="$(cd "$_existing_repo_dir" 2>/dev/null && pwd -P || echo "$_existing_repo_dir")"
      _this_real="$(cd "$REPO_DIR" 2>/dev/null && pwd -P || echo "$REPO_DIR")"
      if [[ "$_existing_real" == "$_this_real" ]]; then
        echo "  = repo_dir already set to this checkout (keeping)"
      else
        # Valid DIFFERENT repo_dir - do NOT overwrite.
        echo "  warning: existing canonical repo_dir '$_existing_repo_dir' differs from this checkout '$REPO_DIR'; not overwriting. Run ds-doctor or set repo_dir manually if this is intended." >&2
      fi
    fi
  fi
else
  echo "  [skip] scripts/lib/repo-dir.sh not found - repo_dir write skipped"
fi

# ---------------------------------------------------------------------------
# Run initial build
# ---------------------------------------------------------------------------

echo "Running initial build..."
bash "$REPO_DIR/.claude/build.sh"
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
# Recommended tools (interactive, optional)
# ---------------------------------------------------------------------------

echo ""
echo "Recommended tools (optional):"
echo ""

# CLI tools
declare -a CLI_TOOLS=(
  "gh:GitHub CLI — create PRs, manage issues, and run repo operations from the terminal:brew install gh"
  "agent-browser:Headless browser — lets agents verify UI changes by taking snapshots and interacting with pages:npm install -g agent-browser"
  "lc:Linear CLI — create, update, and triage issues directly from Claude Code:npm install -g linearctl"
  "jira:Jira CLI — create, update, and triage Jira issues directly from Claude Code:brew install jira-cli"
  "rclone:Cloud file sync — read and write Google Drive files from the terminal:brew install rclone"
)

for tool_entry in "${CLI_TOOLS[@]}"; do
  IFS=: read -r cmd desc install_cmd <<< "$tool_entry"
  if command -v "$cmd" &>/dev/null; then
    echo "  = $cmd already installed"
  else
    if ae_confirm "  Install $cmd ($desc)? [y/N] "; then
      eval "$install_cmd" 2>&1 || echo "  ! $cmd install failed (non-blocking)"
    else
      echo "  - skipped $cmd"
    fi
  fi
done

# chrome-devtools MCP
echo ""
CLAUDE_JSON="$HOME/.claude.json"

# The registration launches Chrome headless on an isolated profile.
# The stdio server opens a visible window by default (`headless: {default:
# false}` in browser-options.js; only the unrelated --viaCli variant flips it),
# which is the desktop clutter this block exists to prevent. --isolated gives
# each server its own throwaway profile, so concurrent runs stop contending for
# one profile directory - sharing one, a second server's first page-scoped call
# fails with "The browser is already running for <path>", lazily, after
# initialize has already succeeded. The cost is that profile state does not
# survive a run, and a server killed without cleanup can leave its temp profile
# directory behind.
#
# An entry whose args carry an argument this migration does not write is
# reported and left alone, whatever that argument is. The rule is the whole
# option set rather than a list of spellings to refuse, because no such list
# can stay complete - the server takes a `no-` negation, a uniform-case
# variant, kebab or camel, and a `=value` for one option. So an entry is a
# migration target only when every one of its args is the package below or an
# option below, decided by the option name the server itself reads off the
# token: a spelling the server ignores is a skip. Both options are bare flags,
# so an argument carrying a value for one of them is not a spelling this
# migration writes either, and a registration that sets its own browser
# connection (--browser-url, --ws-endpoint, --auto-connect) keeps it: the
# server never reads --headless there, so the append would be inert while the
# installer reported the entry configured.
#
# State is detected rather than testing only "is the key present", because a
# registration written before the headless default shipped has the key but
# lacks the flags - a short-circuit there would leave that operator's window up
# forever. absent | stale | current are the states this writer can edit; every
# other state below leaves the file untouched, and none is rewritten blind.
#
# On top of that, none of the flag-based states below is reachable for an entry
# whose args do not invoke the package being configured. The migration's whole
# edit is an args append, so such an entry - a `{"command": "npx"}` one, an
# empty args list, a bare `{}` - would gain the flags alone: `npx --headless
# --isolated`, a registration that cannot launch, which would then classify
# current so the installer never offered again. Those entries are reported as
# themselves instead; the file is left as it is.
#
# The package the migration writes and the options it writes or reads.
# Single-sourced here because two separate python blocks consult them - the
# classifier to predict the writer's decision, the writer to refuse that
# registration if it ever reaches it - and the two must not drift. An option is
# named here the way the server names it, which is the form option_name() below
# derives from a token. --user-data-dir and --channel are deliberately not
# among them: an entry carrying either is now a flag this installer does not
# know, so it is reported and left byte-identical rather than migrated.
CD_MCP_PACKAGE="chrome-devtools-mcp"
CD_MCP_OPTIONS="headless,isolated"

CD_MCP_STATE="$(python3 - "$CLAUDE_JSON" "$CD_MCP_PACKAGE" "$CD_MCP_OPTIONS" <<'PYEOF' 2>/dev/null
import json, re, sys

target = sys.argv[1]
package = sys.argv[2]
options = set(sys.argv[3].split(","))


def option_name(arg):
    # The option the server reads off this arg, which is what decides whether
    # it is one the migration writes: a name the server does not read as an
    # option is a flag this installer does not know, not one it writes. The
    # server parses with yargs, which reads one leading dash as a bundle of
    # single-letter flags, takes a long option whose name holds no dash
    # verbatim (`--userDataDir` is the option; `--UserDataDir` and
    # `--user_data_dir` are not), and otherwise lowercases a uniform-case name
    # and folds each dash or underscore to the next character's upper case. A
    # `no-` negation folds to a name nothing below writes, which is the safe
    # direction - a negation inverts the meaning of the flag it names.
    name = arg.split("=", 1)[0]
    if not name.startswith("--"):
        return name
    name = name.lstrip("-")
    if "-" not in name:
        return name
    if name == name.lower() or name == name.upper():
        name = name.lower()
    folded = []
    upper_next = False
    for i, ch in enumerate(name):
        if upper_next:
            upper_next = False
            ch = ch.upper()
        if i != 0 and ch in "-_":
            upper_next = True
        elif ch not in "-_":
            folded.append(ch)
    return "".join(folded)


def survey(args):
    # (the first arg this migration does not write, the options it does write).
    present = set()
    for arg in args:
        if arg != package and not arg.startswith(package + "@"):
            if not arg.startswith("-"):
                return arg, present
            name = option_name(arg)
            if name not in options:
                return arg, present
            # Both options this migration writes are bare flags, so a value on
            # one of them is not a spelling it writes: `--headless=false` is the
            # window asked for by name, and the flags appended beside it would
            # leave that entry headed while the installer reported it
            # configured. Read as the foreign argument it is.
            if "=" in arg:
                return arg, present
            present.add(name)
    return None, present


try:
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    print("absent")
    sys.exit(0)
except (OSError, ValueError, RecursionError):
    print("unreadable")
    sys.exit(0)

# A container this writer cannot edit surgically is reported as itself, never
# collapsed into absent: absent runs the create path, which would write over
# content the operator owns (a legacy server list, an array standing where an
# entry belongs).
if not isinstance(data, dict):
    print("not-json-object")
    sys.exit(0)
servers = data.get("mcpServers")
if "mcpServers" in data and not isinstance(servers, dict):
    print("mcp-servers-not-object")
    sys.exit(0)
entry = servers.get("chrome-devtools") if isinstance(servers, dict) else None
if isinstance(servers, dict) and "chrome-devtools" in servers and not isinstance(entry, dict):
    print("entry-not-object")
    sys.exit(0)
raw_args = entry.get("args") if isinstance(entry, dict) else None
args_ok = isinstance(raw_args, list) and all(isinstance(a, str) for a in raw_args)
if isinstance(entry, dict) and "args" in entry and not args_ok:
    print("args-not-string-list")
    sys.exit(0)
args = [a for a in raw_args if isinstance(a, str)] if isinstance(raw_args, list) else []

foreign, present = survey(args)
if entry is None:
    print("absent")
elif not any(a == package or a.startswith(package + "@") for a in args):
    print("args-not-our-package")
elif foreign is not None:
    print("foreign-args")
elif "headless" in present and "isolated" in present:
    print("current")
else:
    print("stale")
PYEOF
)" || CD_MCP_STATE="undetermined"

if [[ "$CD_MCP_STATE" == "current" ]]; then
  echo "  = chrome-devtools MCP already configured (headless)"
elif [[ "$CD_MCP_STATE" == "unreadable" ]]; then
  echo "  ! $CLAUDE_JSON could not be read as JSON - leaving the chrome-devtools MCP entry untouched"
elif [[ "$CD_MCP_STATE" == "undetermined" ]]; then
  echo "  ! $CLAUDE_JSON could not be classified - leaving the chrome-devtools MCP entry untouched"
elif [[ "$CD_MCP_STATE" == "foreign-args" ]]; then
  echo "  = chrome-devtools MCP's registration passes an argument this installer does not write, so it is left untouched: the migration only appends the flags it writes, and only to a registration whose every argument is the package or one of those flags"
  echo "  To lose the window by hand, $CLAUDE_JSON takes --headless where the server launches Chrome itself. A registration that sets --browser-url, --ws-endpoint or --auto-connect attaches to a browser you already run and never reads --headless; one that sets --isolated launches its own throwaway profile, which --headless does not conflict with, so adding --headless beside --isolated removes the window and --isolated can stay."
  echo "  One that writes --headless=false has asked for the window by name, so replacing that argument with --headless is what removes it."
elif [[ "$CD_MCP_STATE" == "args-not-our-package" ]]; then
  echo "  = chrome-devtools MCP registration's args do not name the package this installer writes ($CD_MCP_PACKAGE); leaving that registration untouched"
elif [[ "$CD_MCP_STATE" == "not-json-object" || "$CD_MCP_STATE" == "mcp-servers-not-object" || "$CD_MCP_STATE" == "entry-not-object" || "$CD_MCP_STATE" == "args-not-string-list" ]]; then
  # Refuse rather than coerce. The writer below has no surgical edit for any
  # of these shapes, so it is never reached and the file stays untouched.
  CD_MCP_SHAPE=""
  case "$CD_MCP_STATE" in
    not-json-object) CD_MCP_SHAPE="the file's top level is not a JSON object" ;;
    mcp-servers-not-object) CD_MCP_SHAPE="mcpServers is not a JSON object" ;;
    entry-not-object) CD_MCP_SHAPE="the chrome-devtools entry is not a JSON object" ;;
    args-not-string-list) CD_MCP_SHAPE="the chrome-devtools entry has an args value that is not a list of strings" ;;
  esac
  echo "  ! $CLAUDE_JSON: $CD_MCP_SHAPE - leaving the chrome-devtools MCP entry untouched; fix that value by hand and re-run this installer"
else
  echo "  chrome-devtools launches Chrome headless on an isolated profile: an agent-driven browser opens no"
  echo "  window, so watching a page load live is gone (screenshots and script evaluation still work), and"
  echo "  profile state (cookies, logins, local storage) does not persist between runs. To get profile state"
  echo "  back, remove --isolated from its args in $CLAUDE_JSON and the next session picks that up. To get"
  echo "  the window back, remove --headless from its args and the next session picks that up too."
  if [[ "$CD_MCP_STATE" == "stale" ]]; then
    CD_MCP_QUESTION="  Update the existing chrome-devtools MCP registration to launch Chrome headless on an isolated profile? [y/N] "
  else
    CD_MCP_QUESTION="  Configure chrome-devtools MCP - inspect, screenshot, and interact with Chrome tabs for debugging and QA? [y/N] "
  fi
  if ae_confirm "$CD_MCP_QUESTION"; then
    # Every refusal exits non-zero without writing, and the write lands in a
    # same-directory temp file followed by os.replace, so an interrupted run
    # cannot truncate the operator's ~/.claude.json. The caller tolerates the
    # non-zero exit: a refusal is not a reason to fail the whole install.
    if ! python3 - "$CLAUDE_JSON" "$CD_MCP_PACKAGE" "$CD_MCP_OPTIONS" <<'PYEOF'
import json, os, re, stat, sys, tempfile

target = sys.argv[1]
package = sys.argv[2]
options = set(sys.argv[3].split(","))


def option_name(arg):
    # The option the server reads off this arg - see the classifier.
    name = arg.split("=", 1)[0]
    if not name.startswith("--"):
        return name
    name = name.lstrip("-")
    if "-" not in name:
        return name
    if name == name.lower() or name == name.upper():
        name = name.lower()
    folded = []
    upper_next = False
    for i, ch in enumerate(name):
        if upper_next:
            upper_next = False
            ch = ch.upper()
        if i != 0 and ch in "-_":
            upper_next = True
        elif ch not in "-_":
            folded.append(ch)
    return "".join(folded)


def survey(args):
    # (the first arg this migration does not write, the options it does write).
    # A bare flag spelled with a value is not an option this migration writes -
    # see the classifier for why.
    present = set()
    for arg in args:
        if arg != package and not arg.startswith(package + "@"):
            if not arg.startswith("-"):
                return arg, present
            name = option_name(arg)
            if name not in options:
                return arg, present
            if "=" in arg:
                return arg, present
            present.add(name)
    return None, present


def ask_manual(reason, entry_args):
    sys.stderr.write("\n".join([
        "  ! " + reason,
        "    To apply it by hand, set",
        '    mcpServers["chrome-devtools"]["args"] to:',
        "      " + json.dumps(entry_args),
        "    and re-run this installer.",
    ]) + "\n")


def refuse(shape):
    sys.stderr.write("\n".join([
        "  ! " + target + ": " + shape + ", so nothing was written.",
        "    Fix that value by hand (or remove it) and re-run this installer.",
    ]) + "\n")
    sys.exit(1)


if os.path.islink(target):
    sys.stderr.write("  ! refusing to write through symlink: " + target + "\n")
    sys.exit(1)

data = {}
before = None
if os.path.exists(target):
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
            before = os.fstat(f.fileno())
    except (OSError, ValueError):
        sys.stderr.write("  ! " + target + " is not readable JSON - left untouched\n")
        sys.exit(1)
    if not isinstance(data, dict):
        sys.stderr.write("  ! " + target + " is not a JSON object - left untouched\n")
        sys.exit(1)

# Each shape below has no surgical edit: the code after the guard can only
# replace the container wholesale, which loses whatever it held. Refusing
# leaves the file byte-identical instead.
if "mcpServers" in data and not isinstance(data["mcpServers"], dict):
    refuse("mcpServers is not a JSON object")
servers = data.get("mcpServers")
if not isinstance(servers, dict):
    servers = {}
    data["mcpServers"] = servers

if "chrome-devtools" in servers and not isinstance(servers["chrome-devtools"], dict):
    refuse("the chrome-devtools entry is not a JSON object")
entry = servers.get("chrome-devtools")
created = not isinstance(entry, dict)
if created:
    entry = {
        "type": "stdio",
        "command": "npx",
        "args": [package + "@latest"],
        "env": {},
    }
    servers["chrome-devtools"] = entry

raw_args = entry.get("args")
args_ok = isinstance(raw_args, list) and all(isinstance(a, str) for a in raw_args)
if "args" in entry and not args_ok:
    refuse("the chrome-devtools entry has an args value that is not a list of strings")

args = [a for a in raw_args if isinstance(a, str)] if isinstance(raw_args, list) else []

# The append below can only migrate an entry that already invokes this
# package. On anything else it writes the flags alone, which is a registration
# that cannot launch. The classifier reports the same entries, so a real
# install does not reach this.
if not any(a == package or a.startswith(package + "@") for a in args):
    refuse("the chrome-devtools entry's args do not name the package this"
           " installer writes (" + package + ")")

# An argument this migration does not write leaves the entry alone, whatever it
# is - see the classifier for why. Refused rather than migrated with the pin
# skipped: that would report a migration whose edit was not made. The
# classifier reports the same entries, so a real install does not reach this.
foreign, present = survey(args)
if foreign is not None:
    refuse("the chrome-devtools entry passes an argument this installer does"
           " not write (" + foreign + ")")

if "headless" not in present:
    args.append("--headless")
if "isolated" not in present:
    args.append("--isolated")
entry["args"] = args

fd, tmp_path = tempfile.mkstemp(
    dir=os.path.dirname(os.path.abspath(target)), prefix=".claude.json.")
try:
    # ensure_ascii=False and an explicit utf-8 encoding keep the round trip
    # byte-identical for every key the migration does not touch: the default
    # escapes each non-ASCII character, which rewrites unrelated values all
    # over the operator's file.
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    if before is not None:
        # mkstemp creates the temp file 0600 regardless of the target's own
        # mode; carry the operator's mode over so the swap does not narrow it.
        os.chmod(tmp_path, stat.S_IMODE(before.st_mode))
    # On the create path there is no operator mode to carry, so the new file
    # lands 0600 - narrower than the umask default this installer's write
    # produced before it went through a temp file, and the right side to err
    # on for ~/.claude.json, which can hold credentials.
    # Claude Code writes this file too. Re-check it immediately before the
    # rename and refuse rather than clobber an update landing in the window.
    now = os.stat(target) if os.path.exists(target) else None
    if before is None:
        moved = now is not None
    else:
        moved = now is None or (
            now.st_size, now.st_mtime_ns) != (before.st_size, before.st_mtime_ns)
    if moved:
        ask_manual(
            target + " changed while this installer was preparing its update,"
            " so nothing was written.",
            args)
        sys.exit(1)
    os.replace(tmp_path, target)
finally:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)

if created:
    print("  + chrome-devtools MCP configured (headless) in " + target)
else:
    print("  + chrome-devtools MCP updated to launch headless in " + target)
PYEOF
    then
      echo "  - chrome-devtools MCP registration left unchanged"
    fi
  else
    echo "  - skipped chrome-devtools MCP"
  fi
fi

# mcp-atlassian MCP
echo ""
if [[ -f "$CLAUDE_JSON" ]] && python3 -c "
import json, sys
with open('$CLAUDE_JSON') as f:
    d = json.load(f)
sys.exit(0 if 'mcp-atlassian' in d.get('mcpServers', {}) else 1)
" 2>/dev/null; then
  echo "  = mcp-atlassian MCP already configured"
else
  if ae_confirm "  Configure mcp-atlassian MCP — interact with Jira and Confluence from Claude Code? [y/N] "; then
    # Same shape as the chrome-devtools writer: a container this block cannot
    # edit surgically is refused rather than coerced, and the write goes
    # through a same-directory temp file and os.replace so an interrupted run
    # cannot truncate the operator's ~/.claude.json. The exit status is
    # captured rather than left to `set -e`, so a refusal - which is a normal
    # outcome for a malformed config file - cannot abort the whole install.
    AE_ATLASSIAN_RC=0
    python3 - "$CLAUDE_JSON" <<'PYEOF' || AE_ATLASSIAN_RC=$?
import json, os, stat, sys, tempfile

target = sys.argv[1]


def refuse(shape):
    sys.stderr.write("\n".join([
        "  ! " + target + ": " + shape + ", so nothing was written.",
        "    Fix that value by hand (or remove it) and re-run this installer.",
    ]) + "\n")
    sys.exit(1)


data = {}
if os.path.exists(target):
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, RecursionError):
        refuse("the file is not readable JSON")
    if not isinstance(data, dict):
        refuse("the file's top level is not a JSON object")

if "mcpServers" in data and not isinstance(data["mcpServers"], dict):
    refuse("mcpServers is not a JSON object")
servers = data.get("mcpServers")
if not isinstance(servers, dict):
    servers = {}
    data["mcpServers"] = servers

if "mcp-atlassian" not in servers:
    servers["mcp-atlassian"] = {
        "type": "stdio",
        "command": "uvx",
        "args": ["mcp-atlassian"],
        "env": {}
    }
    if os.path.islink(target):
        sys.stderr.write(f"refusing to write through symlink: {target}\n")
        sys.exit(1)
    before = os.stat(target) if os.path.exists(target) else None
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(os.path.abspath(target)), prefix=".claude.json.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        if before is not None:
            # mkstemp creates the temp file 0600 regardless of the target's
            # own mode; carry the operator's mode over so the swap does not
            # narrow it.
            os.chmod(tmp_path, stat.S_IMODE(before.st_mode))
        # On the create path the file lands 0600, which is narrower than the
        # umask default this installer's write produced before it went through
        # a temp file - see the chrome-devtools writer for why that is kept.
        os.replace(tmp_path, target)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    print("  + mcp-atlassian MCP configured in ~/.claude.json")
else:
    print("  = mcp-atlassian MCP already configured")
PYEOF
    if [[ "$AE_ATLASSIAN_RC" -ne 0 ]]; then
      echo "  - mcp-atlassian MCP registration left unchanged"
    fi
  else
    echo "  - skipped mcp-atlassian MCP"
  fi
fi

# context7 plugin note
echo ""
echo "  Note: Enable the 'context7' plugin in Claude Code settings — agents use it to look up current library and framework documentation instead of relying on training data."


# ---------------------------------------------------------------------------
# Permissions configuration
# ---------------------------------------------------------------------------

echo ""

AE_SETTINGS_PATH="$SETTINGS" AE_CONFIG_DIR="$AE_CONFIG_DIR" python3 - <<'PYEOF'
import json, os, sys

# Config-dir label for permission scopes: use ~ for the default home dir, else
# the redirected profile dir verbatim, so a --config-dir install grants write
# to its OWN profile tree, not the real ~/.claude.
_cfg_dir = os.environ.get("AE_CONFIG_DIR") or os.path.expanduser("~/.claude")
_home = os.path.expanduser("~")
_cfg_label = "~/.claude" if _cfg_dir == os.path.join(_home, ".claude") else _cfg_dir

def tty_input(prompt: str) -> str:
    """Read a line from the controlling terminal.

    Required when this script is fed via stdin (heredoc): Python stdin is the
    program text, so builtin input() raises EOFError.
    """
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(prompt)
            tty.flush()
            return tty.readline() or ""
    except OSError:
        return ""

settings_path = os.environ.get("AE_SETTINGS_PATH") or os.path.expanduser("~/.claude/settings.json")

if os.path.exists(settings_path):
    with open(settings_path, "r") as f:
        settings = json.load(f)
else:
    settings = {}

perms = settings.get("permissions", {})

recommended_allow = [
    "Bash(*)",
    "Write",
    "Edit",
    f"Edit({_cfg_label}/**)",
    f"Edit({_cfg_label}/projects/**)"
]
# Legacy rules from older installs: path-scoped Write() rules are ignored by
# Claude Code's file-permission checks (only Edit(path) rules match) and
# trigger a startup warning. Strip them wherever found.
legacy_allow = [
    f"Write({_cfg_label}/**)",
    f"Write({_cfg_label}/projects/**)"
]
recommended_deny = [
    "Bash(git push --force*)",
    "Bash(rm -rf*)",
    "Bash(git reset --hard*)",
    "Bash(git clean -f*)",
    "Bash(sudo rm*)",
    "Bash(dd if=*)",
    "Bash(shutdown*)",
    "Bash(reboot*)"
]

def _migrated_allow(existing_allow):
    """Merge recommended allow rules in and, conservatively, strip legacy
    path-scoped Write() rules out.

    Bare "Write" is unioned in from recommended_allow on every path
    regardless of this gate - the installer always grants it. Path-scoped
    Write(path) rules are ignored by Claude Code's file-permission checks
    (inert either way), so keeping or removing them changes no effective
    permission. What the gate actually controls is only whether the
    installer edits the redundant scoped rule out of the config text: the
    strip fires only when the bare "Write" rule is already present in
    existing_allow (i.e. present in the user's PRE-migration config). This
    avoids the installer making a surprising-looking edit - replacing a
    scoped rule with a broad one in the config text - to a config a user
    may have deliberately narrowed, without their input. Trade-off: for a
    user who removed bare Write but kept the scoped rule, the scoped rule
    (and Claude Code's startup warning about it) is left in place rather
    than cleaned up. Single-sourced so both the already-bypass and the
    fresh-configure branches apply the identical migration (regression
    cases (g) and (h) in install-converge.test.sh cover both branches of
    this gate)."""
    merged = existing_allow | set(recommended_allow)
    if "Write" in existing_allow:
        merged -= set(legacy_allow)
    return list(merged)

already_bypass = perms.get("defaultMode") == "bypassPermissions"

if already_bypass:
    # Already configured — silently merge any missing allow/deny rules
    existing_allow = set(perms.get("allow", []))
    existing_deny = set(perms.get("deny", []))
    missing_allow = set(recommended_allow) - existing_allow
    missing_deny = set(recommended_deny) - existing_deny
    missing_dir = f"{_cfg_label}/projects" not in perms.get("additionalDirectories", [])
    # Mirror _migrated_allow()'s gate: only count legacy rules as "stale" (and
    # report them as removed) when the bare "Write" rule is already present
    # pre-migration - otherwise _migrated_allow() will not strip them, and
    # reporting a removal here would be inaccurate.
    stale_allow = (existing_allow & set(legacy_allow)) if "Write" in existing_allow else set()

    if missing_allow or missing_deny or missing_dir or stale_allow:
        perms["allow"] = _migrated_allow(existing_allow)
        perms["deny"] = list(existing_deny | set(recommended_deny))
        if os.path.islink(settings_path):
            sys.stderr.write(f"refusing to write through symlink: {settings_path}\n")
            sys.exit(1)
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        parts = []
        if missing_allow:
            parts.append(f"added {len(missing_allow)} allow rules")
        if missing_deny:
            parts.append(f"added {len(missing_deny)} deny rules")
        if stale_allow:
            parts.append(f"removed {len(stale_allow)} legacy Write rules")
        print(f"  ~ Permissions: bypassPermissions already set, {' and '.join(parts)}")
    else:
        print("  = Permissions already configured (bypassPermissions mode)")
else:
    print("  Recommended: bypassPermissions mode with deny rules for destructive commands.")
    print("  Agents work best with uninterrupted tool access. The deny list blocks dangerous")
    print("  operations (force push, rm -rf, hard reset) as a safety net.")
    resp = tty_input("  Configure recommended permission settings? [y/N] ").strip().lower()
    if resp == "y":
        existing_allow = set(perms.get("allow", []))
        existing_deny = set(perms.get("deny", []))

        perms["allow"] = _migrated_allow(existing_allow)
        perms["deny"] = list(existing_deny | set(recommended_deny))
        perms["defaultMode"] = "bypassPermissions"
        perms.setdefault("additionalDirectories", [])
        if f"{_cfg_label}/projects" not in perms["additionalDirectories"]:
            perms["additionalDirectories"].append(f"{_cfg_label}/projects")

        settings["permissions"] = perms

        if os.path.islink(settings_path):
            sys.stderr.write(f"refusing to write through symlink: {settings_path}\n")
            sys.exit(1)
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        print("  + Configured bypassPermissions mode with recommended allow/deny rules")

    else:
        print("  - skipped permissions configuration")
PYEOF

# ---------------------------------------------------------------------------
# Symlink bin/ scripts to ~/.local/bin (PATH-accessible location)
# Resolution order:
#   1. If ~/.local/bin exists AND is on PATH -> use it.
#   2. If ~/.local/bin does NOT exist -> create it, symlink there, print PATH
#      guidance (skipped in non-TTY contexts).
# Never uses sudo. Never writes to /usr/local/bin.
# Idempotent: ln -sfn refreshes existing ae symlinks; skips real non-symlinks.
# ---------------------------------------------------------------------------

ae_install_bins() {
  local bin_src="$REPO_DIR/bin"
  local bin_dst="$HOME/.local/bin"
  local path_created=false

  if [[ ! -d "$bin_src" ]]; then
    echo "  [skip] bin/ source directory not found: $bin_src"
    return
  fi

  # Resolve target directory
  if [[ -d "$bin_dst" ]] && echo ":$PATH:" | grep -q ":$bin_dst:"; then
    # ~/.local/bin exists and is on PATH - use it directly
    true
  else
    # Create ~/.local/bin if absent
    if [[ ! -d "$bin_dst" ]]; then
      mkdir -p "$bin_dst"
      path_created=true
    fi
  fi

  # Symlink each file in bin/ (skip test directory and non-executable files)
  local linked=0
  local refreshed=0
  local skipped=0
  for src_file in "$bin_src"/agentic-* "$bin_src"/ds-*; do
    [[ -e "$src_file" ]] || continue
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
        # Refresh: points into our bin/ but different path (e.g. repo moved)
        ln -sfn "$src_file" "$dst_file"
        echo "  ~ $name (refreshed)"
        refreshed=$((refreshed + 1))
      else
        echo "  ! $name (symlink points elsewhere: $current_target - skipping)"
        skipped=$((skipped + 1))
      fi
    elif [[ -e "$dst_file" ]]; then
      echo "  ! $name (real file at destination - skipping to preserve)"
      skipped=$((skipped + 1))
    else
      ln -sfn "$src_file" "$dst_file"
      echo "  + $name -> $dst_file"
      linked=$((linked + 1))
    fi
  done

  if [[ "$path_created" == "true" ]]; then
    if [[ -t 0 ]] || [[ -r /dev/tty ]]; then
      echo ""
      echo "  Created ~/.local/bin and linked agentic binaries."
      echo "  Add this to your PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
      echo "  (add to ~/.zshrc or ~/.bashrc to make it permanent)"
      echo ""
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
echo "Install complete."
echo ""
echo "  dinostack is installed. Open a new Claude Code session in any project,"
echo "  add 'agentic-engineering: opt-in' to its AGENTS.md, and the methodology activates."
if [[ "$AE_OUTPUT_STYLE_INSTALLED" == "true" ]]; then
  echo "  The dinostack output style was installed but not selected - select it via /config."
fi
_ae_identity_guidance
echo ""
if [[ "$SKILL_LINK_OK" != "true" ]]; then
  _ae_skill_link_warning
  echo ""
fi
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
