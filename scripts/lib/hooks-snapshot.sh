# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Session-stable hook snapshotting (DS-54). Copies the hook-script
#          source set (hooks/, the bounded identity/telemetry helper, and the
#          four in-scope adapters' hook sources) out
#          of the live checkout into a per-checkout snapshot dir under
#          $HOME/.agentic/hooks-snapshot/<key>/, so a bare `git pull` cannot
#          silently rewire a hook command a live session already resolved.
#          Adapter install.sh scripts point their hook commands at the
#          snapshot instead of the checkout; a fresh install.sh run publishes
#          a complete immutable generation with one atomic symlink replacement.
#
# Public API:
#   hooks_snapshot_key <repo_dir>
#     -> prints "<basename(realpath repo_dir)>-<sha256_12(realpath repo_dir)>".
#   hooks_snapshot_dir <repo_dir>
#     -> prints "$HOME/.agentic/hooks-snapshot/$(hooks_snapshot_key repo_dir)".
#   hooks_source_paths <repo_dir>
#     -> prints, one per line, the six paths that together define "the hook
#        source" for <repo_dir> (hooks/, bin/ds-identity, and the four
#        in-scope adapters' hook sources) - the SOLE list, so
#        sync_hooks_snapshot's hash, hooks/lib/hooks-staleness-core.sh's
#        stale_but_stable check, and bin/ds-update's _hooks_snapshot_diverged
#        check all pass the same argument list to compute_hooks_source_hash
#        below and can never independently drift on what the six paths are.
#        Read one line at a time (`while IFS= read -r line; do arr+=("$line");
#        done < <(hooks_source_paths "$repo_dir")`) rather than word-splitting
#        the output, and never with `mapfile`/`readarray` (bash 3.2, the
#        macOS system bash, ships neither).
#   compute_hooks_source_hash <path>...
#     -> prints a single sha256 hex digest over the sorted (relpath, content)
#        pairs of every file under the given paths (files or directories).
#        Missing paths are skipped (fail-open). Directories named "tests" and
#        files named "AGENTS.md" are excluded, checked ONLY against the path
#        RELATIVE to the source root being walked - never against the
#        absolute prefix leading up to that root, so a checkout whose
#        absolute path itself contains a "tests" component does not have
#        every file spuriously excluded. Mirrors the sync_hooks_snapshot
#        copy exclusions on the same relative basis, so hashing and copying
#        agree on what "the hook source" means.
#   sync_hooks_snapshot <repo_dir> [--dry-run]
#     -> build a complete immutable generation, then atomically publish a
#        symlink to it at the snapshot dir. Prior generations remain reachable
#        until publication; four immutable generations are retained afterward.
#   remove_hooks_snapshot <repo_dir>
#     -> rm -rf the resolved snapshot dir (same bounded-delete guard).
#        Returns 1 if the guard fails or the dir does not exist.
#   hooks_config_points_at_snapshot <config_file> <format:json|toml> <needle_basename>
#     -> 0 if an entry whose command references needle_basename also
#        references a hooks-snapshot path; 1 otherwise (absent entry, parse
#        error, or entry still pointing at the checkout).
#
# Upstream dependencies: python3 (JSON parse/write, sha256, realpath), a
#   POSIX cp/rm/mkdir. No dependency on scripts/lib/repo-dir.sh - callers
#   pass repo_dir explicitly so the snapshot always reflects the specific
#   checkout that invoked install.sh, not whatever repo_dir a stale config
#   might name.
#
# Downstream consumers: .claude/install.sh, .gemini/install.sh,
#   .codex/install.sh, .kimi/install.sh, .claude/uninstall.sh,
#   hooks/lib/hooks-staleness-core.sh.
#
# Failure modes:
#   - Bounded-delete guard (mandatory on every rm -rf path): fails closed
#     (returns 1, no filesystem write) if repo_dir does not resolve, the
#     computed key is empty, the key contains ".." or "/" (explicit
#     path-traversal case match, independent of the structural checks), or
#     the resolved snapshot_dir is not a direct child of
#     $HOME/.agentic/hooks-snapshot (never equal to that base, never "/").
#   - compute_hooks_source_hash: unreadable files are skipped, not fatal;
#     an empty source set still produces a stable (empty-input) digest.
#   - sync_hooks_snapshot: any failure leaves the previous snapshot in place
#     and returns 1; callers
#     must treat a nonzero return as "leave AE_HOOKS_SNAPSHOT_DIR unset" so
#     the `AE_HOOKS_SNAPSHOT_DIR or repo_dir` fallback idiom degrades safely.
#   - Stale empty or ambiguous live-PID publisher locks with absent/empty
#     start metadata are reclaimed after 60 seconds; fresh ambiguous locks and
#     live locks whose PID/start metadata still match are preserved. Successful
#     publication keeps the current generation plus three recent fallbacks;
#     candidates are validated relative to a nofollow versions descriptor.
#   - Safe to source under set -euo pipefail; no top-level side effects
#     beyond function definitions.
#
# Performance: one staged cp -R of a small script tree (~sub-second);
#   compute_hooks_source_hash walks the same tree once more for the hash.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# hooks_snapshot_key <repo_dir>
# ---------------------------------------------------------------------------
hooks_snapshot_key() {
  local repo_dir="$1"
  python3 -c "
import hashlib, os, sys
repo_dir = sys.argv[1]
try:
    real = os.path.realpath(repo_dir)
except Exception:
    real = repo_dir
base = os.path.basename(real.rstrip('/')) or 'repo'
h = hashlib.sha256(real.encode('utf-8')).hexdigest()[:12]
print(f'{base}-{h}')
" "$repo_dir"
}

# ---------------------------------------------------------------------------
# hooks_snapshot_dir <repo_dir>
# ---------------------------------------------------------------------------
hooks_snapshot_dir() {
  local repo_dir="$1"
  local key
  key="$(hooks_snapshot_key "$repo_dir")"
  printf '%s/.agentic/hooks-snapshot/%s\n' "$HOME" "$key"
}

# ---------------------------------------------------------------------------
# hooks_source_paths <repo_dir>
#   Prints, one per line, the SOLE list of paths that define "the hook
#   source" for <repo_dir>. Every caller that needs this list (the sync
#   writer below, hooks/lib/hooks-staleness-core.sh's stale_but_stable
#   check, and bin/ds-update's _hooks_snapshot_diverged check) must call
#   this function rather than hand-copying the six paths - three unpinned
#   copies previously existed and could silently disagree on drift.
# ---------------------------------------------------------------------------
hooks_source_paths() {
  local repo_dir="$1"
  printf '%s\n' \
    "$repo_dir/hooks" \
    "$repo_dir/bin/ds-identity" \
    "$repo_dir/.codex/config/hooks.json" \
    "$repo_dir/.codex/hooks" \
    "$repo_dir/.gemini/hooks" \
    "$repo_dir/.kimi/hooks"
}

# ---------------------------------------------------------------------------
# compute_hooks_source_hash <path>...
# ---------------------------------------------------------------------------
compute_hooks_source_hash() {
  python3 - "$@" <<'PYEOF'
import hashlib, os, sys

def excluded(relative):
    # relative MUST be relative to the source root being walked (e.g.
    # "tests/foo.sh" or "AGENTS.md"), never the absolute path leading up to
    # that root. A checkout whose absolute path happens to contain a
    # directory component literally named "tests" (e.g.
    # /home/me/tests/DinoStack) must not have every file excluded just
    # because "tests" appears somewhere in the parent path.
    parts = relative.split("/")
    if "tests" in parts:
        return True
    if parts[-1] == "AGENTS.md":
        return True
    return False

entries = []
for arg in sys.argv[1:]:
    # Canonicalize (resolve symlinks, normalize) before using the path as the
    # relpath prefix. Two callers naming "the same" directory differently
    # (e.g. a macOS /var vs /private/var symlink alias between the sync-time
    # caller and a later staleness-check caller) must hash identically, or
    # every check would spuriously report drift that never happened.
    real_arg = os.path.realpath(arg)
    if not os.path.exists(real_arg):
        continue
    if os.path.isfile(real_arg):
        # A single-file source arg (e.g. .codex/config/hooks.json) has no
        # walked structure - the only relative thing to exclude on is its
        # own basename.
        if not excluded(os.path.basename(real_arg)):
            entries.append((real_arg, real_arg))
    elif os.path.isdir(real_arg):
        for root, dirs, files in os.walk(real_arg):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                relative = os.path.relpath(full, real_arg)
                if not excluded(relative):
                    rel = real_arg + "/" + relative
                    entries.append((rel, full))

entries.sort(key=lambda e: e[0])

h = hashlib.sha256()
for rel, full in entries:
    try:
        with open(full, "rb") as f:
            content = f.read()
    except Exception:
        continue
    h.update(rel.encode("utf-8"))
    h.update(b"\x00")
    h.update(content)
    h.update(b"\x00")

print(h.hexdigest())
PYEOF
}

# ---------------------------------------------------------------------------
# _hooks_snapshot_guard <repo_dir> (private)
#   Resolves + validates repo_dir and the snapshot dir it maps to. On
#   success, sets _HOOKS_SNAPSHOT_REAL_REPO_DIR and
#   _HOOKS_SNAPSHOT_RESOLVED_DIR and returns 0. On any violation, prints a
#   message to stderr and returns 1 without touching the filesystem.
# ---------------------------------------------------------------------------
_hooks_snapshot_guard() {
  local repo_dir="$1"

  local real_repo_dir=""
  real_repo_dir="$(cd "$repo_dir" 2>/dev/null && pwd -P || true)"
  if [[ -z "$real_repo_dir" ]]; then
    echo "hooks-snapshot: cannot resolve repo_dir '$repo_dir' (fail-closed)" >&2
    return 1
  fi

  local key=""
  key="$(hooks_snapshot_key "$real_repo_dir")"
  if [[ -z "$key" ]]; then
    echo "hooks-snapshot: empty snapshot key (fail-closed)" >&2
    return 1
  fi

  # Explicit path-traversal guard. Independent of the structural checks
  # below so the guard is self-sufficient even if hooks_snapshot_key is
  # ever redefined or monkey-patched by a caller/test.
  case "$key" in
    *..*|*/*)
      echo "hooks-snapshot: unsafe snapshot key '$key' (fail-closed)" >&2
      return 1
      ;;
  esac

  local base="$HOME/.agentic/hooks-snapshot"
  local snapshot_dir="$base/$key"

  case "$snapshot_dir" in
    "$base"/?*) : ;;
    *)
      echo "hooks-snapshot: snapshot_dir '$snapshot_dir' outside expected bounds (fail-closed)" >&2
      return 1
      ;;
  esac
  if [[ "$snapshot_dir" == "$base" || "$snapshot_dir" == "/" ]]; then
    echo "hooks-snapshot: snapshot_dir resolves to an unsafe path (fail-closed)" >&2
    return 1
  fi

  _HOOKS_SNAPSHOT_REAL_REPO_DIR="$real_repo_dir"
  _HOOKS_SNAPSHOT_RESOLVED_DIR="$snapshot_dir"
  return 0
}

_hooks_snapshot_reclaim_publish_lock() {
  local publish_lock="$1"
  [[ -d "$publish_lock" && ! -L "$publish_lock" ]] || return 1
  local stale_pid="" recorded_start="" current_start="" require_stale_age=false
  if [[ -f "$publish_lock/pid" && ! -L "$publish_lock/pid" ]]; then
    stale_pid="$(tr -cd '0-9' < "$publish_lock/pid" 2>/dev/null || true)"
  fi
  if [[ -n "$stale_pid" ]] && kill -0 "$stale_pid" 2>/dev/null; then
    if [[ -f "$publish_lock/started" && ! -L "$publish_lock/started" ]]; then
      recorded_start="$(cat "$publish_lock/started" 2>/dev/null || true)"
      current_start="$(ps -p "$stale_pid" -o lstart= 2>/dev/null | tr -d '\r' || true)"
      if [[ -n "$recorded_start" ]]; then
        if [[ -z "$current_start" ]]; then
          # A failed or unavailable ps cannot prove PID reuse. Treat it like
          # any other ambiguous live-PID lock: preserve it while fresh and
          # reclaim only after the bounded stale age.
          require_stale_age=true
        elif [[ "$recorded_start" == "$current_start" ]]; then
          return 1
        fi
      else
        require_stale_age=true
      fi
    else
      require_stale_age=true
    fi
  elif [[ -z "$stale_pid" ]]; then
    require_stale_age=true
  fi
  if [[ "$require_stale_age" == true ]]; then
    python3 - "$publish_lock" <<'PYEOF' || return 1
import os, stat, sys, time
st = os.lstat(sys.argv[1])
if not stat.S_ISDIR(st.st_mode) or time.time() - st.st_mtime < 60:
    raise SystemExit(1)
PYEOF
  fi
  rm -f -- "$publish_lock/pid" "$publish_lock/started"
  rmdir "$publish_lock" 2>/dev/null
}

# Validate and, when absent, create the snapshot storage hierarchy without
# following any path component. Every directory must belong to the effective
# user and must not be writable by group or other users. Printing the two
# validated paths is safe because the ownership/mode checks prevent another
# user from swapping a component after the descriptors close.
_hooks_snapshot_prepare_storage() {
  local mode="${1:---create}"
  python3 - "$HOME" "$mode" <<'PYEOF'
import os, stat, sys

home = os.path.abspath(sys.argv[1])
create = sys.argv[2] == "--create"
uid = os.geteuid()
flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)

def checked_dir(fd, label):
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode):
        raise RuntimeError(f"{label} is not a directory")
    if st.st_uid != uid:
        raise RuntimeError(f"{label} has wrong owner")
    if stat.S_IMODE(st.st_mode) & 0o022:
        raise RuntimeError(f"{label} is writable by group or other users")

def open_child(parent_fd, name, label):
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        fd = os.open(name, flags, dir_fd=parent_fd)
    checked_dir(fd, label)
    return fd

fds = []
try:
    home_fd = os.open(home, flags)
    fds.append(home_fd)
    checked_dir(home_fd, "HOME")
    agentic_fd = open_child(home_fd, ".agentic", "$HOME/.agentic")
    fds.append(agentic_fd)
    base_fd = open_child(agentic_fd, "hooks-snapshot", "snapshot base")
    fds.append(base_fd)
    versions_fd = open_child(base_fd, ".versions", "snapshot versions directory")
    fds.append(versions_fd)
    print(os.path.join(home, ".agentic", "hooks-snapshot"))
    print(os.path.join(home, ".agentic", "hooks-snapshot", ".versions"))
except (OSError, RuntimeError) as exc:
    print(f"hooks-snapshot: unsafe snapshot storage: {exc} (fail-closed)", file=sys.stderr)
    raise SystemExit(1)
finally:
    for fd in reversed(fds):
        os.close(fd)
PYEOF
}

_hooks_snapshot_prune_generations() {
  local versions_dir="$1" key="$2" snapshot_dir="$3"
  python3 - "$versions_dir" "$key" "$snapshot_dir" <<'PYEOF'
import heapq, os, shutil, stat, sys
versions, key, public = sys.argv[1:4]
flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
fd = os.open(versions, flags)
try:
    current = os.path.basename(os.path.realpath(public))
    prefix = key + "."
    keep = []
    candidates = []
    with os.scandir(fd) as entries:
        for entry in entries:
            name = entry.name
            if not name.startswith(prefix) or "/" in name or name in (".", ".."):
                continue
            try:
                target = entry.stat(follow_symlinks=False)
            except OSError as exc:
                print(f"hooks-snapshot: cannot inspect generation {name}: {exc}", file=sys.stderr)
                raise SystemExit(1)
            if not stat.S_ISDIR(target.st_mode):
                continue
            candidates.append(name)
            if name != current:
                item = (target.st_mtime_ns, name)
                if len(keep) < 3:
                    heapq.heappush(keep, item)
                elif item > keep[0]:
                    heapq.heapreplace(keep, item)
    retained = {current, *(name for _, name in keep)}
    for name in candidates:
        if name in retained:
            continue
        try:
            target = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(target.st_mode):
                shutil.rmtree(name, dir_fd=fd)
        except OSError as exc:
            print(f"hooks-snapshot: cannot prune generation {name}: {exc}", file=sys.stderr)
            raise SystemExit(1)
finally:
    os.close(fd)
PYEOF
}

# ---------------------------------------------------------------------------
# sync_hooks_snapshot <repo_dir> [--dry-run]
# ---------------------------------------------------------------------------
sync_hooks_snapshot() {
  local repo_dir="$1"
  shift || true
  local dry_run=false
  if [[ "${1:-}" == "--dry-run" ]]; then
    dry_run=true
  fi

  if ! _hooks_snapshot_guard "$repo_dir"; then
    return 1
  fi
  local real_repo_dir="$_HOOKS_SNAPSHOT_REAL_REPO_DIR"
  local snapshot_dir="$_HOOKS_SNAPSHOT_RESOLVED_DIR"

  if [[ "$dry_run" == "true" ]]; then
    echo "hooks-snapshot: [dry-run] would sync $real_repo_dir -> $snapshot_dir"
    AE_HOOKS_SNAPSHOT_DIR="$snapshot_dir"
    export AE_HOOKS_SNAPSHOT_DIR
    return 0
  fi

  if [[ ! -d "$real_repo_dir/hooks" || ! -f "$real_repo_dir/bin/ds-identity" ]]; then
    echo "hooks-snapshot: required hooks/helper source missing (previous snapshot preserved)" >&2
    return 1
  fi

  local storage_paths=""
  if ! storage_paths="$(_hooks_snapshot_prepare_storage)"; then
    return 1
  fi
  local base="" versions_dir=""
  base="${storage_paths%%$'\n'*}"
  versions_dir="${storage_paths#*$'\n'}"
  if [[ -z "$base" || -z "$versions_dir" ]]; then
    echo "hooks-snapshot: storage validation returned no paths (fail-closed)" >&2
    return 1
  fi
  local key=""
  key="$(basename "$snapshot_dir")"
  local nonce=""
  nonce="$(python3 -c 'import secrets; print(secrets.token_hex(12))')" || return 1
  local stage_dir="$versions_dir/.${key}.stage.$$.$nonce"
  local version_dir="$versions_dir/${key}.$nonce"
  if ! mkdir "$stage_dir"; then
    echo "hooks-snapshot: cannot create staged generation (previous snapshot preserved)" >&2
    return 1
  fi

  # --- Copy the source set, preserving checkout-relative layout ---
  # Driven by hooks_source_paths() - the SOLE list - so the copy set can
  # never independently drift from the hash set below. Plain cp -R/cp (NOT
  # rsync), then a targeted rm of the excluded hooks/ paths - matches
  # compute_hooks_source_hash's exclusions so a hooks/tests/ or
  # hooks/AGENTS.md edit alone never trips staleness. Directory vs file is
  # handled explicitly per-entry (cp -R vs cp) since the two need different
  # cp invocations; everything else about the loop is uniform.
  local -a _copy_source_paths=()
  local _copy_source_path _copy_src _copy_rel _copy_dest
  while IFS= read -r _copy_source_path; do
    _copy_source_paths+=("$_copy_source_path")
  done < <(hooks_source_paths "$real_repo_dir")

  for _copy_src in ${_copy_source_paths[@]+"${_copy_source_paths[@]}"}; do
    [[ -e "$_copy_src" ]] || continue
    _copy_rel="${_copy_src#"$real_repo_dir"/}"
    _copy_dest="$stage_dir/$_copy_rel"
    mkdir -p "$(dirname "$_copy_dest")" || {
      rm -rf -- "$stage_dir"
      return 1
    }
    if [[ -d "$_copy_src" ]]; then
      cp -R "$_copy_src" "$_copy_dest" || {
        rm -rf -- "$stage_dir"
        return 1
      }
    else
      cp "$_copy_src" "$_copy_dest" || {
        rm -rf -- "$stage_dir"
        return 1
      }
    fi
  done

  rm -rf "$stage_dir/hooks/tests"
  rm -f "$stage_dir/hooks/AGENTS.md"
  if [[ -f "$stage_dir/bin/ds-identity" ]]; then
    chmod 700 "$stage_dir/bin/ds-identity" || {
      rm -rf -- "$stage_dir"
      return 1
    }
  fi

  # --- Compute + persist the source hash + metadata (atomic write) ---
  local source_hash=""
  local -a _sync_source_paths=()
  while IFS= read -r _sync_source_path; do
    _sync_source_paths+=("$_sync_source_path")
  done < <(hooks_source_paths "$real_repo_dir")
  source_hash="$(compute_hooks_source_hash ${_sync_source_paths[@]+"${_sync_source_paths[@]}"})"

  local snapshotted_at=""
  snapshotted_at="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "")"

  if ! python3 - "$stage_dir/.snapshot-meta.json" "$real_repo_dir" "$source_hash" "$snapshotted_at" <<'PYEOF'
import json, sys, os
path, source_repo_dir, source_hash, snapshotted_at = sys.argv[1:5]
data = {
    "source_repo_dir": source_repo_dir,
    "source_hash": source_hash,
    "snapshotted_at": snapshotted_at,
}
tmp = path + ".tmp." + str(os.getpid())
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
os.replace(tmp, path)
PYEOF
  then
    rm -rf -- "$stage_dir"
    return 1
  fi

  # Serialize publishers only. Readers continue through the old immutable
  # generation while the next tree is staged and while another publisher waits.
  local publish_lock="$base/.${key}.publish.lock"
  local attempts=0
  until mkdir "$publish_lock" 2>/dev/null; do
    if _hooks_snapshot_reclaim_publish_lock "$publish_lock"; then
      continue
    fi
    attempts=$((attempts + 1))
    if [[ "$attempts" -ge 500 ]]; then
      rm -rf -- "$stage_dir"
      echo "hooks-snapshot: publish lock timeout (previous snapshot preserved)" >&2
      return 1
    fi
    sleep 0.02
  done
  printf '%s\n' "$$" > "$publish_lock/pid"
  ps -p "$$" -o lstart= 2>/dev/null | tr -d '\r' > "$publish_lock/started" || true

  local link_tmp="$base/.${key}.link.$$.$nonce"
  local publish_ok=false
  if mv "$stage_dir" "$version_dir" \
    && ln -s ".versions/$(basename "$version_dir")" "$link_tmp" \
    && python3 - "$snapshot_dir" "$link_tmp" "$base/.${key}.backup.$$.$nonce" <<'PYEOF'
import os
import shutil
import sys

target, link_tmp, backup = sys.argv[1:4]
had_target = os.path.lexists(target)
if had_target and not os.path.islink(target):
    os.rename(target, backup)
try:
    os.replace(link_tmp, target)
except BaseException:
    if had_target and os.path.lexists(backup) and not os.path.lexists(target):
        os.rename(backup, target)
    raise
if os.path.lexists(backup):
    if os.path.isdir(backup) and not os.path.islink(backup):
        shutil.rmtree(backup)
    else:
        os.unlink(backup)
PYEOF
  then
    publish_ok=true
  fi
  rm -f -- "$publish_lock/pid"
  rm -f -- "$publish_lock/started"
  rmdir "$publish_lock" 2>/dev/null || true
  if [[ "$publish_ok" != "true" ]]; then
    rm -f -- "$link_tmp"
    rm -rf -- "$stage_dir" "$version_dir"
    echo "hooks-snapshot: staged publication failed (previous snapshot recovered)" >&2
    return 1
  fi

  if ! _hooks_snapshot_prune_generations "$versions_dir" "$key" "$snapshot_dir"; then
    echo "hooks-snapshot: generation pruning failed" >&2
    return 1
  fi

  AE_HOOKS_SNAPSHOT_DIR="$snapshot_dir"
  export AE_HOOKS_SNAPSHOT_DIR
  echo "hooks-snapshot: synced $real_repo_dir -> $snapshot_dir"
  return 0
}

# ---------------------------------------------------------------------------
# remove_hooks_snapshot <repo_dir>
# ---------------------------------------------------------------------------
remove_hooks_snapshot() {
  local repo_dir="$1"

  if ! _hooks_snapshot_guard "$repo_dir"; then
    return 1
  fi
  local snapshot_dir="$_HOOKS_SNAPSHOT_RESOLVED_DIR"
  local key=""
  key="$(basename "$snapshot_dir")"

  local storage_paths=""
  if ! storage_paths="$(_hooks_snapshot_prepare_storage --existing)"; then
    return 1
  fi
  local base="" versions_dir=""
  base="${storage_paths%%$'\n'*}"
  versions_dir="${storage_paths#*$'\n'}"

  python3 - "$base" "$versions_dir" "$key" <<'PYEOF'
import os, shutil, stat, sys

base, versions, key = sys.argv[1:4]
flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
base_fd = os.open(base, flags)
versions_fd = os.open(versions, flags)
removed = False
try:
    try:
        target = os.stat(key, dir_fd=base_fd, follow_symlinks=False)
    except FileNotFoundError:
        target = None
    if target is not None:
        if stat.S_ISDIR(target.st_mode):
            shutil.rmtree(key, dir_fd=base_fd)
        else:
            os.unlink(key, dir_fd=base_fd)
        removed = True
    prefix = key + "."
    with os.scandir(versions_fd) as entries:
        names = [entry.name for entry in entries if entry.name.startswith(prefix)]
    for name in names:
        if "/" in name or name in (".", ".."):
            raise RuntimeError("unsafe generation name")
        target = os.stat(name, dir_fd=versions_fd, follow_symlinks=False)
        if not stat.S_ISDIR(target.st_mode):
            raise RuntimeError(f"unsafe generation entry: {name}")
        shutil.rmtree(name, dir_fd=versions_fd)
        removed = True
finally:
    os.close(versions_fd)
    os.close(base_fd)
raise SystemExit(0 if removed else 1)
PYEOF
}

# ---------------------------------------------------------------------------
# hooks_config_points_at_snapshot <config_file> <format:json|toml> <needle_basename>
# ---------------------------------------------------------------------------
hooks_config_points_at_snapshot() {
  local config_file="$1"
  local format="$2"
  local needle="$3"

  [[ -f "$config_file" ]] || return 1

  case "$format" in
    json)
      python3 -c "
import json, sys
config_file, needle = sys.argv[1], sys.argv[2]
try:
    with open(config_file) as f:
        data = json.load(f)
except Exception:
    sys.exit(1)

def walk(node):
    if isinstance(node, dict):
        cmd = node.get('command')
        if isinstance(cmd, str) and needle in cmd:
            yield cmd
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)

for cmd in walk(data):
    if 'hooks-snapshot' in cmd:
        sys.exit(0)
sys.exit(1)
" "$config_file" "$needle"
      ;;
    toml)
      python3 -c "
import sys
config_file, needle = sys.argv[1], sys.argv[2]
try:
    with open(config_file) as f:
        content = f.read()
except Exception:
    sys.exit(1)
for line in content.splitlines():
    if needle in line and 'hooks-snapshot' in line:
        sys.exit(0)
sys.exit(1)
" "$config_file" "$needle"
      ;;
    *)
      return 1
      ;;
  esac
}
