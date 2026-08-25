#!/usr/bin/env bash
# Module: .gemini/install.sh
# Role: Install the Gemini CLI adapter into ~/.gemini/
# Inputs: .gemini/ build artifacts (GEMINI.md, skills/dinostack/, commands/,
#          agents/, hooks/)
# Outputs: symlinks at ~/.gemini/skills/dinostack/, ~/.gemini/commands/,
#          ~/.gemini/agents/; ~/.gemini/GEMINI.md is symlinked to the stub
#          when the skill link resolves (SKILL_LINK_OK), or WRITTEN
#          (not symlinked, first-line-marked with GEMINI_MD_DEGRADE_MARKER)
#          with the full methodology body appended as a degrade path
#          otherwise - unless a FOREIGN, live symlink already occupies the
#          destination, in which case it is left untouched and nothing is
#          written (DS-184 - see _ae_classify_gemini_md_dst's own comment
#          block and the Step 3b case statements below for the full
#          contract); hooks block merged into ~/.gemini/settings.json,
#          pointed at the session-stable hooks snapshot (DS-54,
#          scripts/lib/hooks-snapshot.sh) when sync succeeds, else the
#          checkout
# Side-effects: backs up existing non-symlink, non-marker-owned targets with
#               .backup-<timestamp> suffix; DELETES a real file at
#               ~/.gemini/GEMINI.md (no backup) when it carries our own
#               GEMINI_MD_DEGRADE_MARKER first line - it is our own
#               generated artifact, not user data. On BOTH branches (round
#               6), a symlink at that destination is classified by the ONE
#               shared _ae_classify_gemini_md_dst function: "ours" (target
#               matches the current $GEMINI_MD_SRC - canonicalized via
#               _ae_paths_equal when the target exists, so an aliased
#               checkout path such as macOS /tmp -> /private/tmp still
#               matches, and by literal string equality when the target is
#               dangling) is replaced with no backup; "foreign-live" (resolves
#               somewhere else and exists) is left untouched with nothing
#               written; "foreign-dangling" (does not resolve, and is not
#               "ours") is of UNKNOWN provenance - could be the user's own
#               symlink to a since-deleted file - and is preserved via a
#               .backup-<timestamp> move, never deleted outright (DS-184
#               M1 fix, round 6 - round 5 backed this case up only on the
#               degrade branch while the healthy branch deleted the
#               identical input with no backup). Creates ~/.gemini/ if
#               absent; syncs the hooks snapshot dir.
# Consumers: user runs manually; re-run after repo move (or to refresh the
#            hooks snapshot) to update absolute hook paths
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GEMINI_DIR="$REPO_DIR/.gemini"

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
  echo "    Override later with: bash .gemini/install.sh --mode=opt-in"
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
  echo "    Override with: bash .gemini/install.sh --profile=relaxed|default|strict"
fi


GEMINI_MD_SRC="$GEMINI_DIR/GEMINI.md"
GEMINI_MD_DST="$HOME/.gemini/GEMINI.md"

COMMANDS_SRC="$GEMINI_DIR/commands"
COMMANDS_DST="$HOME/.gemini/commands"

AGENTS_SRC="$GEMINI_DIR/agents"
AGENTS_DST="$HOME/.gemini/agents"

SKILL_SRC="$GEMINI_DIR/skills/dinostack"
SKILL_DST="$HOME/.gemini/skills/dinostack"

SETTINGS="$HOME/.gemini/settings.json"

# Marker written as the first line of a degrade-path-generated GEMINI.md
# (DS-184 M2/M3 fix). Lets both install.sh and uninstall.sh recognize a
# real (non-symlink) GEMINI.md at the install destination as our own
# generated artifact rather than user data - a prior degrade-path write is
# overwritten in place with no backup, and uninstall.sh removes it outright
# instead of leaving it behind as an orphan the install-path can restore
# from later. A genuinely user-authored GEMINI.md never carries this line.
GEMINI_MD_DEGRADE_MARKER="<!-- dinostack:gemini-degrade-generated -->"

# Resolved-path comparison for "is this symlink ours" checks below (round 5
# Minor fix). A plain string compare of a symlink's readlink() target
# against our freshly-computed *_SRC path misclassifies our own symlink as
# foreign whenever the destination is reached via a symlinked-parent alias
# (e.g. $HOME resolving through a symlink) - the two paths differ textually
# while resolving to the same file. Falls back to a plain string compare
# when either side cannot be resolved (nonexistent path), which keeps
# dangling-symlink handling (compared elsewhere by existence, not this
# helper) unaffected. `readlink -f` is used rather than `realpath` for
# portability - confirmed present on both BSD readlink (macOS, `readlink
# [-fn]`) and GNU readlink.
_ae_paths_equal() {
  local a="$1" b="$2" resolved_a resolved_b
  resolved_a="$(readlink -f "$a" 2>/dev/null || true)"
  resolved_b="$(readlink -f "$b" 2>/dev/null || true)"
  if [[ -n "$resolved_a" && -n "$resolved_b" ]]; then
    [[ "$resolved_a" == "$resolved_b" ]]
  else
    [[ "$a" == "$b" ]]
  fi
}

# Prints the absolute, normalized target of the symlink at $1, WITHOUT
# requiring the target to exist. A relative `readlink` result is resolved
# against the symlink's OWN directory via python3's os.path.normpath/join
# (round 6, DS-184 M2 fix) - never against install.sh's CWD, which is what
# `readlink -f "$(readlink "$1")"` (the pre-fix shape used at the two
# GEMINI_MD_DST call sites below) silently did: a relative target like
# ".gemini/GEMINI.md" resolved from wherever install.sh happened to be
# invoked, not from the symlink's own parent directory, so a relative
# symlink whose CWD-relative resolution happened to equal $GEMINI_MD_SRC
# was misclassified as "ours" regardless of what it actually pointed at.
# Prints nothing (and returns 1) when $1 is not a symlink or has no
# readable target. Deliberately distinct from `_ae_paths_equal` above,
# which requires the target to EXIST to resolve it and is kept, unchanged,
# for the SKILL_DST alias-resolution case at Step 3a (still correct there -
# see the module manifest and round-5 review sign-off).
_ae_resolve_symlink_target_abs() {
  local link="$1" raw
  raw="$(readlink "$link" 2>/dev/null || true)"
  [[ -n "$raw" ]] || return 1
  if [[ "$raw" == /* ]]; then
    printf '%s\n' "$raw"
  else
    # Round 7, DS-184 minor fix: install.sh already hard-depends on python3
    # elsewhere (JSON config writes), and every symlink WE create is
    # absolute, so this branch only fires for a relative FOREIGN symlink -
    # but a silently-absent python3 previously let the caller's `|| true`
    # swallow the failure into an empty target_abs, misclassifying a
    # relative symlink whose resolution would have been "ours" as foreign
    # instead. Fail loudly (a stderr warning) rather than silently.
    if ! command -v python3 >/dev/null 2>&1; then
      echo "  ! python3 not found - cannot resolve relative symlink target for $link; treating as unresolved" >&2
      return 1
    fi
    python3 -c "
import os, sys
link_dir, raw_target = sys.argv[1], sys.argv[2]
print(os.path.normpath(os.path.join(link_dir, raw_target)))
" "$(dirname "$link")" "$raw"
  fi
}

# Classifies the destination path $1 for the shared GEMINI.md install
# decision (round 6, DS-184 M1/M2/M3 fix). Sets globals _AE_CLASS and
# _AE_CLASS_TARGET; never prints anything itself. $2 is the current
# $GEMINI_MD_SRC, $3 is $GEMINI_MD_DEGRADE_MARKER.
#
# _AE_CLASS is exactly one of:
#   absent            - nothing at the destination
#   ours              - a symlink whose target (resolved via
#                        _ae_resolve_symlink_target_abs, so a relative
#                        target is resolved correctly per M2 above) MATCHES
#                        the current $GEMINI_MD_SRC - via _ae_paths_equal
#                        (canonicalizes both sides through the filesystem
#                        when the target exists, so an aliased checkout
#                        path is not misclassified as foreign - round 7,
#                        M1 fix) for a live target, or literal string
#                        equality for a dangling one whose target literally
#                        names the current src path (the latter is a rare
#                        edge case in practice, since Step 1's build always
#                        recreates $GEMINI_MD_SRC before this runs - kept
#                        for robustness against races/partial builds)
#   foreign-live       - a symlink resolving to something that exists and
#                        is not $GEMINI_MD_SRC
#   foreign-dangling   - a symlink that does not resolve (dangling) and is
#                        not classified "ours" - provenance unknown: could
#                        be the user's own symlink to a since-deleted file,
#                        or a stale ours-symlink from BEFORE a repo move
#                        (indistinguishable from the outside), so treated
#                        as foreign and preserved via backup, never deleted
#                        outright (M1 fix - this is the exact class the
#                        pre-fix healthy branch mishandled)
#   ours-marked-file   - a real (non-symlink) file whose first line equals
#                        $GEMINI_MD_DEGRADE_MARKER exactly
#   foreign-file       - a real (non-symlink) file/directory without the
#                        marker
#
# Both the healthy and degrade branches below call ONLY this function to
# decide ownership - so they can never again classify the same destination
# differently from each other (the exact defect class M1/M3 kept
# reappearing at a new site every round).
_ae_classify_gemini_md_dst() {
  local dst="$1" src="$2" marker="$3" target_abs src_abs first_line
  _AE_CLASS=""
  _AE_CLASS_TARGET=""
  if [[ -L "$dst" ]]; then
    _AE_CLASS_TARGET="$(readlink "$dst" 2>/dev/null || true)"
    target_abs="$(_ae_resolve_symlink_target_abs "$dst" || true)"
    src_abs="$(readlink -f "$src" 2>/dev/null || echo "$src")"
    # Round 7, DS-184 M1 fix: `target_abs` is normalized but NOT
    # canonicalized against filesystem symlinks (see
    # _ae_resolve_symlink_target_abs's own comment - it deliberately does
    # not require the target to exist). Comparing it against `$src_abs`
    # alone (both canonicalized) is what round 6 shipped, and it silently
    # misclassifies our OWN live symlink as foreign whenever any component
    # of the checkout path is itself a symlink (e.g. macOS `/tmp` ->
    # `/private/tmp`) - `target_abs` still carries the un-resolved `/tmp/...`
    # form while `src_abs` has already been resolved to `/private/tmp/...`.
    # `_ae_paths_equal` fixes the live case: it resolves BOTH operands via
    # `readlink -f` when they exist, so an aliased checkout path
    # canonicalizes on both sides and the comparison holds regardless of
    # symlink aliasing. The `$src_abs` term is kept as an OR fallback for
    # the dangling-target "ours" case documented above (a dangling target
    # cannot be canonicalized by `readlink -f`, so `_ae_paths_equal` falls
    # back to literal string equality between `target_abs` and `$src` - the
    # un-resolved current-checkout form - while this term additionally
    # covers the case where `target_abs` happens to already equal the
    # resolved `$src_abs` string).
    if [[ -n "$target_abs" ]] && { _ae_paths_equal "$target_abs" "$src" || [[ "$target_abs" == "$src_abs" ]]; }; then
      _AE_CLASS="ours"
    elif [[ -e "$dst" ]]; then
      _AE_CLASS="foreign-live"
    else
      _AE_CLASS="foreign-dangling"
    fi
  elif [[ -e "$dst" ]]; then
    first_line="$(head -1 "$dst" 2>/dev/null || true)"
    if [[ "$first_line" == "$marker" ]]; then
      _AE_CLASS="ours-marked-file"
    else
      _AE_CLASS="foreign-file"
    fi
  else
    _AE_CLASS="absent"
  fi
}

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

# Absolute path to hooks directory - computed at install time.
# Hook commands embed this path so they work regardless of the working directory
# at hook invocation time (which is the user's project dir, not this repo root).
# DS-54: rooted at the hooks snapshot when one was successfully synced,
# falling back to the checkout ($GEMINI_DIR/hooks) otherwise.
GEMINI_HOOKS_DIR="$AE_HOOKS_ROOT/.gemini/hooks"

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
# Step 3a: Symlink ~/.gemini/skills/dinostack (DS-184)
#
# Mirrors .claude/install.sh's SKILL_LINK_OK gate: a skipped or not-yet-
# created skill symlink sets SKILL_LINK_OK=false. GEMINI.md linking (next
# step) branches on this - when the skill link does not resolve, the
# stub-only GEMINI.md would leave the session with no route to the
# methodology body at all, so install falls back to writing the full body
# directly into ~/.gemini/GEMINI.md instead of the stub.
# ---------------------------------------------------------------------------

echo "Linking skill: dinostack..."

SKILL_LINK_OK=true
SKILL_LINK_REASON=""

mkdir -p "$(dirname "$SKILL_DST")"

if [[ -L "$SKILL_DST" ]]; then
  current_target="$(readlink "$SKILL_DST")"
  if _ae_paths_equal "$current_target" "$SKILL_SRC"; then
    echo "  = ~/.gemini/skills/dinostack/ (already linked)"
  else
    echo "  ! ~/.gemini/skills/dinostack/ (symlink points elsewhere: $current_target - skipping)"
    SKILL_LINK_OK=false
    SKILL_LINK_REASON="symlink points outside this checkout: $current_target"
  fi
elif [[ -e "$SKILL_DST" ]]; then
  # Unlike the commands/agents symlinks above and below, a real file or
  # directory at the skill destination is NOT auto-backed-up and replaced
  # - it is left alone and SKILL_LINK_OK is set false, matching
  # .claude/install.sh's own skill-linking behavior (a skill link is a
  # trigger-load routing decision, not a leaf artifact to unconditionally
  # overwrite). Operator resolves the conflict manually, same as the
  # Claude adapter's skill link.
  echo "  ! ~/.gemini/skills/dinostack/ (real file/directory exists at destination - skipping)"
  SKILL_LINK_OK=false
  SKILL_LINK_REASON="real file/directory exists at destination"
else
  ln -s "$SKILL_SRC" "$SKILL_DST"
  echo "  + ~/.gemini/skills/dinostack/ linked to $SKILL_SRC"
fi

if [[ "$SKILL_LINK_OK" != "true" ]]; then
  echo ""
  echo "  WARNING: the dinostack skill is not linked ($SKILL_LINK_REASON)."
  echo "  ~/.gemini/GEMINI.md will carry the full methodology body directly"
  echo "  as a degrade path, instead of the trigger-loaded skill pointer,"
  echo "  so the session does not lose access to the methodology entirely."
fi

# ---------------------------------------------------------------------------
# Step 3b: Symlink (or, on a broken skill link, write) ~/.gemini/GEMINI.md
#
# When SKILL_LINK_OK, ~/.gemini/GEMINI.md is symlinked to the stub built by
# .gemini/build.sh - the full methodology loads on trigger via the skill
# instead. When the skill link could not be established, the stub alone
# would leave no route to the methodology at all, so install writes (not
# symlinks) a real file combining the stub with the full skill body
# appended - never silently dropping content (DS-184).
# ---------------------------------------------------------------------------

echo "Linking global GEMINI.md..."

# Writes the degrade-path body (stub + full skill text, marker-prefixed) to
# $GEMINI_MD_DST and records that a write actually happened, via the shared
# GEMINI_MD_DEGRADE_WRITTEN flag the Step 3b summary below consults - kept as
# one function so the three call sites below (fresh destination, our own
# marked artifact, a foreign file getting backed up) can never drift from
# each other (DS-184 M1/M2 fix).
_write_gemini_md_degrade_body() {
  {
    echo "$GEMINI_MD_DEGRADE_MARKER"
    cat "$GEMINI_MD_SRC"
    echo ""
    echo ""
    echo "---"
    echo ""
    echo "## Full methodology body (degrade path - skill link unavailable)"
    echo ""
    echo "The \`dinostack\` skill could not be linked ($SKILL_LINK_REASON), so the"
    echo "full methodology body is appended below directly, rather than left"
    echo "reachable only via a broken trigger-load pointer."
    echo ""
    cat "$SKILL_SRC/SKILL.full.md"
  } > "$GEMINI_MD_DST"
  echo "  + ~/.gemini/GEMINI.md written with full methodology body appended (degrade path)"
  GEMINI_MD_DEGRADE_WRITTEN=true
}

GEMINI_MD_DEGRADE_WRITTEN=false

# Both branches below classify the destination via the ONE shared
# _ae_classify_gemini_md_dst function (round 6, DS-184 M1/M2/M3 fix) -
# they differ only in what they WRITE for a given class, never in how they
# decide ownership or whether a backup is owed. See that function's own
# comment block above for the full _AE_CLASS enum and rationale.
_ae_classify_gemini_md_dst "$GEMINI_MD_DST" "$GEMINI_MD_SRC" "$GEMINI_MD_DEGRADE_MARKER"
GEMINI_MD_CLASS="$_AE_CLASS"
GEMINI_MD_CLASS_TARGET="$_AE_CLASS_TARGET"

if [[ "$SKILL_LINK_OK" == "true" ]]; then
  case "$GEMINI_MD_CLASS" in
    ours)
      echo "  = ~/.gemini/GEMINI.md (already linked)"
      ;;
    absent)
      ln -s "$GEMINI_MD_SRC" "$GEMINI_MD_DST"
      echo "  + ~/.gemini/GEMINI.md linked to $GEMINI_MD_SRC"
      ;;
    ours-marked-file)
      # Our own prior degrade-path artifact, not user data - replace it
      # with the symlink outright, no backup and no false "already
      # exists" warning.
      echo "  Replacing prior dinostack degrade-path GEMINI.md with the symlink (no backup - it's our own generated artifact)"
      rm "$GEMINI_MD_DST"
      ln -s "$GEMINI_MD_SRC" "$GEMINI_MD_DST"
      echo "  + ~/.gemini/GEMINI.md linked to $GEMINI_MD_SRC"
      ;;
    foreign-file)
      BACKUP="$GEMINI_MD_DST.backup-$(date +%Y%m%d%H%M%S)"
      echo ""
      echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
      echo "  WARNING: ~/.gemini/GEMINI.md already exists and is NOT a symlink."
      echo "  Backing it up to: $BACKUP"
      echo "  The existing file will be REPLACED with the dinostack symlink."
      echo "  To restore: cp \"$BACKUP\" \"$GEMINI_MD_DST\""
      echo "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
      echo ""
      mv "$GEMINI_MD_DST" "$BACKUP"
      ln -s "$GEMINI_MD_SRC" "$GEMINI_MD_DST"
      echo "  + ~/.gemini/GEMINI.md linked (backup saved to $BACKUP)"
      ;;
    foreign-dangling)
      # Round 6 / M1 fix: a dangling symlink not recognized as ours is of
      # UNKNOWN provenance - could be the user's own symlink to a
      # since-deleted file, or a stale ours-symlink from before a repo
      # move; the two are indistinguishable from the outside. Prior
      # rounds deleted it outright here while the degrade branch backed
      # up the identical input (M1) - both branches now agree: preserve
      # via backup, never delete without one.
      BACKUP="$GEMINI_MD_DST.backup-$(date +%Y%m%d%H%M%S)"
      echo ""
      echo "  WARNING: ~/.gemini/GEMINI.md is a dangling symlink (-> $GEMINI_MD_CLASS_TARGET) not"
      echo "  recognized as our own. It cannot be confirmed to be ours, so it is being"
      echo "  preserved (moved to $BACKUP) before linking. To restore: mv \"$BACKUP\" \"$GEMINI_MD_DST\""
      echo ""
      mv "$GEMINI_MD_DST" "$BACKUP"
      ln -s "$GEMINI_MD_SRC" "$GEMINI_MD_DST"
      echo "  + ~/.gemini/GEMINI.md linked (backup saved to $BACKUP)"
      ;;
    foreign-live)
      echo "  ! ~/.gemini/GEMINI.md (symlink points elsewhere: $GEMINI_MD_CLASS_TARGET - skipping)"
      ;;
  esac
else
  # Degrade path: the skill link is unavailable, so write a real file (not
  # a symlink) that carries the full methodology body directly, rather than
  # leaving the session with only the trigger-load pointer and no working
  # trigger to reach it.
  case "$GEMINI_MD_CLASS" in
    ours)
      echo "  Replacing dinostack symlink at ~/.gemini/GEMINI.md with the degrade-path body (skill link unavailable: $SKILL_LINK_REASON)"
      rm "$GEMINI_MD_DST"
      _write_gemini_md_degrade_body
      ;;
    absent)
      _write_gemini_md_degrade_body
      ;;
    ours-marked-file)
      # Our own prior degrade-path artifact, not user data - overwrite in
      # place rather than accumulating a fresh backup on every install.
      echo "  Overwriting prior dinostack degrade-path GEMINI.md (no backup - it's our own generated artifact)"
      rm "$GEMINI_MD_DST"
      _write_gemini_md_degrade_body
      ;;
    foreign-file)
      BACKUP="$GEMINI_MD_DST.backup-$(date +%Y%m%d%H%M%S)"
      echo "  Backing up existing ~/.gemini/GEMINI.md to: $BACKUP"
      mv "$GEMINI_MD_DST" "$BACKUP"
      _write_gemini_md_degrade_body
      ;;
    foreign-dangling)
      # Provenance unknown (see the healthy branch's identical case above -
      # both branches now classify and handle this input the same way);
      # preserved via backup, never deleted outright.
      BACKUP="$GEMINI_MD_DST.backup-$(date +%Y%m%d%H%M%S)"
      echo ""
      echo "  WARNING: ~/.gemini/GEMINI.md is a dangling symlink (-> $GEMINI_MD_CLASS_TARGET) not"
      echo "  recognized as our own. It cannot be confirmed to be ours, so it is being"
      echo "  preserved (moved to $BACKUP) rather than deleted, before writing the"
      echo "  degrade-path body in its place. To restore: mv \"$BACKUP\" \"$GEMINI_MD_DST\""
      echo ""
      mv "$GEMINI_MD_DST" "$BACKUP"
      _write_gemini_md_degrade_body
      ;;
    foreign-live)
      echo "  ! ~/.gemini/GEMINI.md (symlink points elsewhere: $GEMINI_MD_CLASS_TARGET - skipping degrade-path write; not ours to touch)"
      ;;
  esac
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
  echo "  The existing directory will be REPLACED with the dinostack symlink."
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
  echo "  The existing directory will be REPLACED with the dinostack symlink."
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

python3 - "$SETTINGS" "$HOOKS_DIR_FOR_PYTHON" "$AE_HOOKS_ROOT" <<'PYEOF'
import json, os, sys

settings_path = sys.argv[1]
hooks_dir = sys.argv[2]
# DS-54: repo_dir here is really "the root SKILL_CMD is built from" - it is
# AE_HOOKS_ROOT (the hooks snapshot when synced, else the checkout), passed
# in by the caller so SKILL_CMD lands at <root>/hooks/skill-auto-load-check.sh.
repo_dir = sys.argv[3]

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

def upsert_hook(hook_list, script_basename, expected_entry, label):
    """Upsert a hook entry using equality-based idempotency.

    Identifies an existing entry by script_basename appearing in its command
    (stable identity that survives repo moves). Then:
    - command already equals expected -> leave it, print '= already present'
    - command differs (stale/moved path) -> replace command (and name if set),
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

upsert_hook(
    ba_star["hooks"],
    "risk-reminder.sh",
    {"name": "risk-reminder", "type": "command", "command": RISK_CMD},
    "BeforeAgent risk-reminder hook",
)

# ---- BeforeAgent hook (skill auto-load check) --------------------------------
SKILL_CMD = f'AE_ADAPTER=gemini bash "{repo_dir}/hooks/skill-auto-load-check.sh"'

upsert_hook(
    ba_star["hooks"],
    "skill-auto-load-check.sh",
    {"name": "skill-auto-load-check", "type": "command", "command": SKILL_CMD},
    "BeforeAgent skill-auto-load-check hook",
)

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

upsert_hook(
    se_exit["hooks"],
    "stop-context-gemini.js",
    {"name": "stop-context", "type": "command", "command": STOP_CMD},
    "SessionEnd stop-context hook",
)

# ---- Write back --------------------------------------------------------------
os.makedirs(os.path.dirname(settings_path) or ".", exist_ok=True)
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print("  settings.json written.")
PYEOF

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
echo "Install complete."
echo ""
echo "What was installed:"
if [[ "$SKILL_LINK_OK" == "true" ]]; then
  echo "  ~/.gemini/skills/dinostack/  -> $SKILL_SRC"
else
  echo "  ~/.gemini/skills/dinostack/  (NOT linked - $SKILL_LINK_REASON)"
fi
echo "    Contains: Full agentic engineering methodology (trigger-loaded via"
echo "    Gemini CLI's activate_skill - DS-184; not loaded unconditionally)"
echo ""
if [[ "$SKILL_LINK_OK" == "true" ]]; then
  echo "  ~/.gemini/GEMINI.md  -> $GEMINI_MD_SRC"
  echo "    Contains: A small always-loaded stub pointing at the dinostack skill"
elif [[ "$GEMINI_MD_DEGRADE_WRITTEN" == "true" ]]; then
  echo "  ~/.gemini/GEMINI.md  (written directly, NOT symlinked - degrade path)"
  echo "    Contains: The stub PLUS the full methodology body appended, because"
  echo "    the skill link above could not be established ($SKILL_LINK_REASON)"
else
  echo "  ~/.gemini/GEMINI.md  (NOT written - a foreign symlink already occupies this path)"
  echo "    The degrade-path methodology body could not be delivered here; resolve"
  echo "    the conflicting symlink manually, then re-run install.sh"
fi
echo ""
echo "  ~/.gemini/commands/  -> $COMMANDS_SRC"
echo "    Contains: TOML slash-command files (ds-skeptic, ds-implement-ticket, ds-wrap, etc.)"
echo ""
echo "  ~/.gemini/agents/  -> $AGENTS_SRC"
echo "    Contains: Named agent markdown files (engineer, architect, debugger, etc.)"
echo ""
echo "  ~/.gemini/settings.json"
echo "    Updated: BeforeAgent (risk reminder, skill auto-load check) and SessionEnd (context save) hooks"
echo "    Hook scripts: $GEMINI_HOOKS_DIR/"
echo ""
echo "IMPORTANT - repo-move constraint:"
echo "  Hook commands in ~/.gemini/settings.json embed absolute paths to:"
echo "    $GEMINI_HOOKS_DIR/"
echo "  If you move the repo, re-run .gemini/install.sh to update these paths."
echo ""
echo "KNOWN LIMITATION - headless / non-interactive Gemini runs (DS-184):"
echo "  Gemini CLI denies the activate_skill tool by default outside an"
echo "  interactive session (packages/core/src/policy/policies/write.toml -"
echo "  non-interactive rule: decision=deny, priority=10). A scripted,"
echo "  non-interactive run will NOT load the dinostack skill's methodology"
echo "  body unless you opt in to one of two overrides yourself:"
echo "    1. --approval-mode yolo (or --yolo) - allows every tool, not"
echo "       scoped to activate_skill alone."
echo "    2. settings.tools.allowed: [\"activate_skill\", ...] in your own"
echo "       ~/.gemini/settings.json - scoped to the tools you list."
echo "  This installer deliberately does NOT enable either override for"
echo "  you - see .gemini/README.md for the full explanation."
echo ""
echo "Next steps:"
echo "  1. Open Gemini CLI in a project directory."
echo "  2. Invoke the dinostack skill (activate_skill) to load the full"
echo "     methodology - you will see a one-time per-session consent"
echo "     prompt naming the skill and the directory it gains access to."
echo "  3. Run /commands reload to activate slash commands."
echo "  4. Spawn named agents via @agent-name (e.g., @engineer, @architect)."
echo "  5. Risk reminder fires automatically before each prompt (BeforeAgent hook)."
echo "  6. Session context saved to ~/.gemini/projects/[hash]/context.md on /exit."
echo "  7. See .gemini/README.md for full documentation, including the"
echo "     headless-run limitation above."
