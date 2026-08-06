#!/usr/bin/env bash
# Purpose: Install the generated Codex adapter, exactly four native DinoStack
#          skills, named agents, hooks, activation/profile state, and PATH tools.
# Public API: bash .codex/install.sh [--mode=opt-in|opt-out]
#             [--profile=relaxed|default|strict] [--identity=<handle>]
#             [--no-identity] [--config-dir=<dir>]. AGENTIC_CONFIG_DIR provides
#             the first config-dir fallback; CODEX_HOME provides the second.
# Upstream deps: .codex/build.sh and its generated AGENTS.md, agents/, skills/,
#                and config/hooks.json outputs; scripts/lib/identity.sh and
#                scripts/lib/hooks-snapshot.sh when present; Bash and Python 3.
# Downstream consumers: manual installs and update workflows that populate
#                       ~/.agents/skills/, the selected Codex config directory,
#                       ~/.local/bin/, and shared activation/identity state.
# Failure modes: staged source build/drift and unsafe user destinations fail
#                before any user-state mutation; existing safe non-owned targets
#                are backed up before replacement; optional identity and snapshot
#                helpers degrade with explicit warnings.
# Performance: one isolated source copy/build plus local filesystem installation,
#              linear in repository and generated adapter size; no network access.
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
AE_CONFIG_DIR_FLAG=""
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
    --config-dir=*)
      AE_CONFIG_DIR_FLAG="${arg#--config-dir=}"
      ;;
  esac
done

# Codex harness config directory (redirectable for per-profile installs).
# Precedence: --config-dir flag > AGENTIC_CONFIG_DIR env > CODEX_HOME env >
# default ~/.codex.
# PATH tools stay in $HOME; activation follows an explicit redirected config.
CODEX_CONFIG_DIR="${AE_CONFIG_DIR_FLAG:-${AGENTIC_CONFIG_DIR:-${CODEX_HOME:-$HOME/.codex}}}"
# Public API note: --config-dir=<dir>, AGENTIC_CONFIG_DIR, or CODEX_HOME
# redirects this harness config dir for per-profile installs.
if declare -f _ae_identity_bind_config_dir >/dev/null; then
  if [[ -n "${AE_CONFIG_DIR_FLAG:-${AGENTIC_CONFIG_DIR:-${CODEX_HOME:-}}}" ]]; then
    _ae_identity_bind_config_dir "$CODEX_CONFIG_DIR" true
  else
    _ae_identity_bind_config_dir "$CODEX_CONFIG_DIR" false
  fi
fi

# Activation config path defaults to the shared $HOME location but is also
# redirectable via --config-dir so multi-tenant installs (one profile per
# harness-tenant pair) do not clobber each other or the shared default.
AE_CONFIG_PATH="$HOME/.claude/agentic-engineering.json"
if [[ -n "${AE_CONFIG_DIR_FLAG:-${AGENTIC_CONFIG_DIR:-${CODEX_HOME:-}}}" ]]; then
  AE_CONFIG_PATH="$CODEX_CONFIG_DIR/agentic-engineering.json"
fi

SKILLS_SRC="$REPO_DIR/.codex/skills"
SKILLS_DST="$HOME/.agents/skills"
LEGACY_SKILL_SRC="$REPO_DIR/.codex/skill"
SKILL_NAMES=(agentic-engineering brief wrap implement-ticket)

AGENTS_SRC="$REPO_DIR/.codex/AGENTS.md"
AGENTS_DST="$CODEX_CONFIG_DIR/AGENTS.md"

NAMED_AGENTS_SRC="$REPO_DIR/.codex/agents"
NAMED_AGENTS_DST="$CODEX_CONFIG_DIR/agents"

CONFIG_FILE="$CODEX_CONFIG_DIR/config.toml"
HOOKS_FLAG_MARKER="$CODEX_CONFIG_DIR/.agentic-eng-added-codex-hooks-flag"
HOOKS_DST="$CODEX_CONFIG_DIR/hooks.json"
HOOKS_SNAPSHOT_EXPECTED_DIR="$(python3 - "$REPO_DIR" "$HOME" <<'PYEOF'
import hashlib
import os
import sys

repo = os.path.realpath(sys.argv[1])
home = os.path.abspath(os.path.expanduser(sys.argv[2]))
base = os.path.basename(repo.rstrip("/")) or "repo"
key = f"{base}-{hashlib.sha256(repo.encode('utf-8')).hexdigest()[:12]}"
print(os.path.join(home, ".agentic", "hooks-snapshot", key))
PYEOF
)"

# Validate every user-controlled install root and its user-owned ancestry before
# the first mkdir, cleanup, config write, build, or link operation. This is a
# lexical lstat walk from the nearest shared user root: no destination path
# component may already be a symlink or non-directory. Redirected profile roots
# may be siblings of HOME when they share a non-root user-controlled ancestor.
ae_validate_install_roots() {
  python3 - "$HOME" "$@" <<'PYEOF'
import os
import stat
import sys
from pathlib import Path

home = Path(os.path.abspath(os.path.expanduser(sys.argv[1])))
try:
    home_info = os.lstat(home)
except OSError as exc:
    sys.stderr.write(f"unsafe install path: cannot inspect HOME {home}: {exc}\n")
    raise SystemExit(1)
if stat.S_ISLNK(home_info.st_mode) or not stat.S_ISDIR(home_info.st_mode):
    sys.stderr.write(f"unsafe install path: HOME must be a real directory: {home}\n")
    raise SystemExit(1)

for raw in sys.argv[2:]:
    target = Path(os.path.abspath(os.path.expanduser(raw)))
    base = Path(os.path.commonpath((str(home), str(target))))
    if base == Path(base.anchor):
        sys.stderr.write(
            f"unsafe install path: destination has no shared user root with HOME: {target}\n"
        )
        raise SystemExit(1)
    try:
        base_info = os.lstat(base)
    except OSError as exc:
        sys.stderr.write(f"unsafe install path: cannot inspect shared root {base}: {exc}\n")
        raise SystemExit(1)
    if stat.S_ISLNK(base_info.st_mode) or not stat.S_ISDIR(base_info.st_mode):
        sys.stderr.write(f"unsafe install path: shared root must be a real directory: {base}\n")
        raise SystemExit(1)
    relative = target.relative_to(base)
    current = base
    for component in relative.parts:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            sys.stderr.write(f"unsafe install path: cannot inspect {current}: {exc}\n")
            raise SystemExit(1)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            sys.stderr.write(
                f"unsafe install path: symlink or non-directory ancestor: {current}\n"
            )
            raise SystemExit(1)
        if info.st_uid != os.geteuid() or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            sys.stderr.write(
                f"unsafe install path: unowned or group/world-writable ancestor: {current}\n"
            )
            raise SystemExit(1)
PYEOF
}

# Prove the complete source checkout builds in an isolated, mode-0700 staging
# directory before touching HOME or any redirected Codex profile. The staged
# outputs must match the persistent symlink sources exactly; a stale checkout
# fails closed with instructions to rebuild it outside the installer.
CODEX_INSTALL_STAGE="$(python3 - <<'PYEOF'
import tempfile
print(tempfile.mkdtemp(prefix="dinostack-codex-install-"))
PYEOF
)"

ae_cleanup_install_stage() {
  python3 - "$CODEX_INSTALL_STAGE" <<'PYEOF'
import os
import shutil
import stat
import sys

path = os.path.abspath(sys.argv[1])
info = os.lstat(path)
if (
    not os.path.basename(path).startswith("dinostack-codex-install-")
    or stat.S_ISLNK(info.st_mode)
    or not stat.S_ISDIR(info.st_mode)
    or info.st_uid != os.geteuid()
    or stat.S_IMODE(info.st_mode) != 0o700
):
    raise SystemExit(f"refusing unsafe Codex install staging cleanup: {path}")
shutil.rmtree(path)
PYEOF
}
trap 'ae_cleanup_install_stage >/dev/null 2>&1 || true' EXIT

python3 - "$CODEX_INSTALL_STAGE" <<'PYEOF'
import os
import stat
import sys

path = os.path.abspath(sys.argv[1])
info = os.lstat(path)
if (
    stat.S_ISLNK(info.st_mode)
    or not stat.S_ISDIR(info.st_mode)
    or info.st_uid != os.geteuid()
    or stat.S_IMODE(info.st_mode) != 0o700
):
    raise SystemExit(f"unsafe Codex install staging directory: {path}")
PYEOF

python3 - "$REPO_DIR" "$CODEX_INSTALL_STAGE/repo" <<'PYEOF'
import shutil
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])

def ignored(directory, names):
    ignored_names = {
        name for name in names if name == "__pycache__" or name.endswith(".pyc")
    }
    if Path(directory).resolve() == source.resolve():
        ignored_names.update(name for name in names if name in {".git", ".agentic"})
    return ignored_names

shutil.copytree(source, destination, symlinks=True, ignore=ignored)
PYEOF

set +e
bash "$CODEX_INSTALL_STAGE/repo/.codex/build.sh" \
  >"$CODEX_INSTALL_STAGE/build.stdout" \
  2>"$CODEX_INSTALL_STAGE/build.stderr"
CODEX_STAGE_BUILD_RC=$?
set -e
if [[ $CODEX_STAGE_BUILD_RC -ne 0 ]]; then
  cat "$CODEX_INSTALL_STAGE/build.stdout"
  cat "$CODEX_INSTALL_STAGE/build.stderr" >&2
  ae_cleanup_install_stage
  trap - EXIT
  exit "$CODEX_STAGE_BUILD_RC"
fi

python3 - "$REPO_DIR" "$CODEX_INSTALL_STAGE/repo" <<'PYEOF'
import hashlib
import os
import stat
import sys
from pathlib import Path

source = Path(sys.argv[1])
staged = Path(sys.argv[2])
roots = (
    Path(".codex/AGENTS.md"),
    Path(".codex/agents"),
    Path(".codex/skills"),
)

def snapshot(base, relative):
    root = base / relative
    paths = [root]
    if root.is_dir() and not root.is_symlink():
        paths.extend(sorted(root.rglob("*")))
    records = {}
    for path in paths:
        key = path.relative_to(base).as_posix()
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            records[key] = ("link", os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            records[key] = (
                "file",
                stat.S_IMODE(info.st_mode),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        elif stat.S_ISDIR(info.st_mode):
            records[key] = ("directory", stat.S_IMODE(info.st_mode))
        else:
            records[key] = ("special", stat.S_IFMT(info.st_mode))
    return records

for relative in roots:
    if snapshot(source, relative) != snapshot(staged, relative):
        raise SystemExit(
            f"Codex install source is stale at {relative}; run bash .codex/build.sh "
            "and retry the installer"
        )
PYEOF

ae_cleanup_install_stage
trap - EXIT

ae_validate_install_roots \
  "$CODEX_CONFIG_DIR" \
  "$(dirname "$AE_CONFIG_PATH")" \
  "$HOME/.agents" \
  "$HOME/.agents/skills" \
  "$HOME/.agentic" \
  "$HOME/.agentic/hooks-snapshot" \
  "$HOME/.local" \
  "$HOME/.local/bin" \
  "$CODEX_CONFIG_DIR/skills"

# Validate every final mutable destination before the first write. Existing
# symlinks are accepted only when they already point at an installer-owned
# source. Existing regular files must be owned, single-link, and not writable
# by group or other. This makes a late malicious destination fail before an
# earlier activation/config/snapshot destination can be changed.
AE_FINAL_DESTINATIONS=(
  $'file\t'"$AE_CONFIG_PATH"
  $'file\t'"$CONFIG_FILE"
  $'file\t'"$HOOKS_FLAG_MARKER"
  $'file\t'"$HOME/.agentic/identity.yml"
  $'snapshot\t'"$HOOKS_SNAPSHOT_EXPECTED_DIR"$'\t'"$HOME/.agentic/hooks-snapshot/.versions"$'\t'"$(basename "$HOOKS_SNAPSHOT_EXPECTED_DIR")"
  $'file\t'"$HOOKS_SNAPSHOT_EXPECTED_DIR/.snapshot-meta.json"
  $'link\t'"$AGENTS_DST"$'\t'"$AGENTS_SRC"
  $'link\t'"$NAMED_AGENTS_DST"$'\t'"$NAMED_AGENTS_SRC"
  $'link\t'"$HOOKS_DST"$'\t'"$HOOKS_SNAPSHOT_EXPECTED_DIR/.codex/config/hooks.json"$'\t'"$REPO_DIR/.codex/config/hooks.json"$'\t'"$REPO_DIR/.codex/hooks.json"
)
for skill_name in "${SKILL_NAMES[@]}"; do
  if [[ "$skill_name" == "agentic-engineering" ]]; then
    AE_FINAL_DESTINATIONS+=(
      $'link\t'"$SKILLS_DST/$skill_name"$'\t'"$SKILLS_SRC/$skill_name"$'\t'"$LEGACY_SKILL_SRC"
      $'link\t'"$CODEX_CONFIG_DIR/skills/$skill_name"$'\t'"$SKILLS_SRC/$skill_name"$'\t'"$LEGACY_SKILL_SRC"
    )
  else
    AE_FINAL_DESTINATIONS+=(
      $'link\t'"$SKILLS_DST/$skill_name"$'\t'"$SKILLS_SRC/$skill_name"
      $'link\t'"$CODEX_CONFIG_DIR/skills/$skill_name"$'\t'"$SKILLS_SRC/$skill_name"
    )
  fi
done
for src_file in "$REPO_DIR"/bin/agentic-* "$REPO_DIR"/bin/ds-*; do
  [[ -f "$src_file" ]] || continue
  AE_FINAL_DESTINATIONS+=(
    $'link\t'"$HOME/.local/bin/$(basename "$src_file")"$'\t'"$src_file"
  )
done

ae_validate_install_destinations() {
  python3 - "$@" <<'PYEOF'
import os
import stat
import sys
from pathlib import Path

euid = os.geteuid()

def fail(path, reason):
    sys.stderr.write(f"unsafe install destination: {reason}: {path}\n")
    raise SystemExit(1)

def validate_owned(path, info, *, require_regular=False):
    if info.st_uid != euid:
        fail(path, "not owned by the current user")
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        fail(path, "group- or world-writable")
    if require_regular:
        if not stat.S_ISREG(info.st_mode):
            fail(path, "expected a regular file")
        if info.st_nlink != 1:
            fail(path, "regular file has multiple hard links")

for encoded in sys.argv[1:]:
    parts = encoded.split("\t")
    kind, path = parts[0], Path(os.path.abspath(os.path.expanduser(parts[1])))
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        continue
    except OSError as exc:
        fail(path, f"cannot inspect ({exc})")

    if kind == "file":
        if stat.S_ISLNK(info.st_mode):
            fail(path, "file is a symlink")
        validate_owned(path, info, require_regular=True)
        continue

    if kind == "directory":
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(path, "expected a real directory")
        validate_owned(path, info)
        continue

    if kind == "snapshot":
        if stat.S_ISLNK(info.st_mode):
            resolved = Path(os.path.realpath(path))
            versions = Path(os.path.realpath(os.path.expanduser(parts[2])))
            expected_prefix = parts[3] + "."
            if resolved.parent != versions or not resolved.name.startswith(expected_prefix):
                fail(path, f"snapshot link escapes immutable generations ({resolved})")
            try:
                target_info = os.stat(path)
            except OSError as exc:
                fail(path, f"cannot inspect snapshot generation ({exc})")
            if not stat.S_ISDIR(target_info.st_mode):
                fail(path, "snapshot generation is not a directory")
            validate_owned(resolved, target_info)
        elif stat.S_ISDIR(info.st_mode):
            # Legacy in-place snapshots are accepted for one migration sync.
            validate_owned(path, info)
        else:
            fail(path, "expected a snapshot directory or immutable-generation link")
        continue

    if kind != "link":
        fail(path, f"unknown preflight kind {kind!r}")

    if stat.S_ISLNK(info.st_mode):
        raw_target = os.readlink(path)
        resolved_target = os.path.realpath(path.parent / raw_target)
        allowed = parts[2:]
        if not any(
            raw_target == expected
            or resolved_target == os.path.realpath(os.path.expanduser(expected))
            for expected in allowed
        ):
            fail(path, f"symlink points outside installer-owned sources ({raw_target})")
    elif stat.S_ISREG(info.st_mode):
        validate_owned(path, info, require_regular=True)
    elif stat.S_ISDIR(info.st_mode):
        validate_owned(path, info)
    else:
        fail(path, "special file type")
PYEOF
}

ae_validate_install_destinations "${AE_FINAL_DESTINATIONS[@]}"

# Ensure the config dir exists before the first ae_write_* call. Without this,
# a redirected --config-dir pointing at a not-yet-existing directory makes
# open(path, "w") raise FileNotFoundError. Guard the dir symlink first: mkdir -p
# silently follows dir symlinks (CWE-59). Mirrors .pi/install.sh and .claude/install.sh.
AE_CONFIG_TARGET_DIR="$(dirname "$AE_CONFIG_PATH")"
[[ -L "$AE_CONFIG_TARGET_DIR" ]] && {
  echo "  ! refusing to install through symlinked config dir: $AE_CONFIG_TARGET_DIR" >&2
  exit 1
}
mkdir -p "$AE_CONFIG_TARGET_DIR"

# Safe JSON-key reader: path/key/default via argv, never interpolated into the
# Python source (defense-in-depth against quotes/metacharacters, CWE-94).
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
# Symlink guard: refuse to write through a symlink (open("w") follows it and
# truncates the real target). PoC verified for config.toml writer.
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
            tty.write("Auto-load agentic-engineering skill at session start? [y/N] ")
            tty.flush()
            answer = (tty.readline() or "").strip().lower()
        config["skill_auto_load"] = answer in ("y", "yes")
    except OSError:
        config["skill_auto_load"] = False
# Write back
# Symlink guard (see ae_write_mode).
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
  AE_CURRENT_MODE="$(ae_read_json_key "$AE_CONFIG_PATH" mode "opt-out")"
  ae_write_config "$AE_CURRENT_MODE" "$AE_PROFILE_FLAG"
  echo "  + profile set to '$AE_PROFILE_FLAG' via --profile flag"
elif [[ -n "$AE_EXISTING_PROFILE" ]]; then
  echo "  = profile already set to '$AE_EXISTING_PROFILE' (keeping)"
else
  AE_CURRENT_MODE="$(ae_read_json_key "$AE_CONFIG_PATH" mode "opt-out")"
  ae_write_config "$AE_CURRENT_MODE" "default"
  echo "  = profile defaulted to 'default' (wrote $AE_CONFIG_PATH)"
  echo "    Override with: bash .codex/install.sh --profile=relaxed|default|strict"
fi

# ---------------------------------------------------------------------------
# Clean up old (incorrect) skill symlinks under the Codex config directory.
# The correct path per Codex docs is ~/.agents/skills/<name>/.
# ---------------------------------------------------------------------------

for skill_name in "${SKILL_NAMES[@]}"; do
  old_skill_dst="$CODEX_CONFIG_DIR/skills/$skill_name"
  skill_src="$SKILLS_SRC/$skill_name"
  if [[ -L "$old_skill_dst" ]]; then
    old_target="$(readlink "$old_skill_dst")"
    if [[ "$old_target" == "$skill_src" || \
          ( "$skill_name" == "agentic-engineering" && "$old_target" == "$LEGACY_SKILL_SRC" ) ]]; then
      rm "$old_skill_dst"
      echo "  - Removed stale symlink at $old_skill_dst"
    else
      echo "  ! $old_skill_dst points to $old_target (not ours - leaving it)"
    fi
  elif [[ -e "$old_skill_dst" ]]; then
    echo "  ! Real file/directory at $old_skill_dst - not removing (manual cleanup may be needed)"
  fi
done

# ---------------------------------------------------------------------------
# Symlink all four native skills into ~/.agents/skills/
# Per Codex docs: user-scope skills load from $HOME/.agents/skills/<name>/SKILL.md
# ---------------------------------------------------------------------------

echo "Linking native skills..."

mkdir -p "$SKILLS_DST"

for skill_name in "${SKILL_NAMES[@]}"; do
  skill_src="$SKILLS_SRC/$skill_name"
  skill_dst="$SKILLS_DST/$skill_name"
  if [[ ! -d "$skill_src" || ! -f "$skill_src/SKILL.md" ]]; then
    echo "  ! generated skill is missing or incomplete: $skill_src" >&2
    exit 1
  fi
  if [[ -L "$skill_dst" ]]; then
    current_target="$(readlink "$skill_dst")"
    if [[ "$current_target" == "$skill_src" ]]; then
      echo "  = $skill_name (already linked)"
    elif [[ "$skill_name" == "agentic-engineering" && "$current_target" == "$LEGACY_SKILL_SRC" ]]; then
      ln -sfn "$skill_src" "$skill_dst"
      echo "  ~ $skill_name (migrated from deleted singular skill source)"
    else
      echo "  ! $skill_name (symlink points elsewhere: $current_target - skipping)"
    fi
  elif [[ -e "$skill_dst" ]]; then
    echo "  ! $skill_name (real file/directory exists at destination - skipping)"
  else
    ln -s "$skill_src" "$skill_dst"
    echo "  + $skill_name skill linked to $skill_dst"
  fi
done

# ---------------------------------------------------------------------------
# Symlink ~/.codex/AGENTS.md to .codex/AGENTS.md
# Per Codex docs: global scope loads ~/.codex/AGENTS.md
# ---------------------------------------------------------------------------

echo "Linking global AGENTS.md..."

# Symlink guard: refuse if harness config dir is a symlink (CWE-59).
[[ -L "$CODEX_CONFIG_DIR" ]] && {
  echo "  ! refusing to install through symlinked config dir: $CODEX_CONFIG_DIR" >&2
  exit 1
}
mkdir -p "$CODEX_CONFIG_DIR"

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
    # Symlink guard: refuse to write through a symlinked config.toml. A
    # `mv`/`printf >` redirect silently follows and truncates the real target.
    [[ -L "$CONFIG_FILE" ]] && {
      echo "  ! refusing to write through symlink: $CONFIG_FILE" >&2
      exit 1
    }
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
  # Symlink guard: refuse to write through a symlinked config.toml.
  [[ -L "$CONFIG_FILE" ]] && {
    echo "  ! refusing to write through symlink: $CONFIG_FILE" >&2
    exit 1
  }
  printf '[features]\ncodex_hooks = true\n' > "$CONFIG_FILE"
  echo "  + Created $CONFIG_FILE with [features] codex_hooks = true"
  ADDED_CODEX_HOOKS_FLAG=1
fi

# Write a marker file so uninstall.sh knows to remove the flag
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
for skill_name in "${SKILL_NAMES[@]}"; do
  echo "  ~/.agents/skills/$skill_name  -> $SKILLS_SRC/$skill_name"
done
echo "    Four native Codex skills: core methodology plus brief, wrap, and implement-ticket workflows"
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
echo "  .codex/commands/       - Source command templates (tracked relative symlinks to ../../content/commands/*.md)"
echo "  .codex/references/     - Reference docs (tracked relative symlinks to ../../content/references/*.md)"
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
