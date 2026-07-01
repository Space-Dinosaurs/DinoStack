# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Session-stable hook snapshotting (DS-54). Copies the hook-script
#          source set (hooks/ + the four in-scope adapters' hook sources) out
#          of the live checkout into a per-checkout snapshot dir under
#          $HOME/.agentic/hooks-snapshot/<key>/, so a bare `git pull` cannot
#          silently rewire a hook command a live session already resolved.
#          Adapter install.sh scripts point their hook commands at the
#          snapshot instead of the checkout; a fresh install.sh run refreshes
#          the snapshot in place.
#
# Public API:
#   hooks_snapshot_key <repo_dir>
#     -> prints "<basename(realpath repo_dir)>-<sha256_12(realpath repo_dir)>".
#   hooks_snapshot_dir <repo_dir>
#     -> prints "$HOME/.agentic/hooks-snapshot/$(hooks_snapshot_key repo_dir)".
#   compute_hooks_source_hash <path>...
#     -> prints a single sha256 hex digest over the sorted (relpath, content)
#        pairs of every file under the given paths (files or directories).
#        Missing paths are skipped (fail-open). Directories named "tests" and
#        files named "AGENTS.md" are excluded (mirrors the sync_hooks_snapshot
#        copy exclusions), so hashing and copying agree on what "the hook
#        source" means.
#   sync_hooks_snapshot <repo_dir> [--dry-run]
#     -> rm -rf + cp -R the source set into the snapshot dir, write
#        .snapshot-meta.json, export AE_HOOKS_SNAPSHOT_DIR. Returns 1 (no
#        filesystem write) on any bounded-delete guard failure. --dry-run
#        prints intent only, still exports AE_HOOKS_SNAPSHOT_DIR.
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
#     (the rm -rf only runs after the guard passes) and returns 1; callers
#     must treat a nonzero return as "leave AE_HOOKS_SNAPSHOT_DIR unset" so
#     the `AE_HOOKS_SNAPSHOT_DIR or repo_dir` fallback idiom degrades safely.
#   - Safe to source under set -euo pipefail; no top-level side effects
#     beyond function definitions.
#
# Performance: one full rm -rf + cp -R of a small script tree (~sub-second);
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
# compute_hooks_source_hash <path>...
# ---------------------------------------------------------------------------
compute_hooks_source_hash() {
  python3 - "$@" <<'PYEOF'
import hashlib, os, sys

def excluded(relpath):
    parts = relpath.split("/")
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
        if not excluded(real_arg):
            entries.append((real_arg, real_arg))
    elif os.path.isdir(real_arg):
        for root, dirs, files in os.walk(real_arg):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                rel = real_arg + "/" + os.path.relpath(full, real_arg)
                if not excluded(rel):
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

  rm -rf -- "$snapshot_dir"
  mkdir -p "$snapshot_dir"

  # --- Copy the source set, preserving checkout-relative layout ---
  # Plain cp -R (NOT rsync, NOT symlink) followed by a targeted rm of the
  # excluded paths - matches compute_hooks_source_hash's exclusions so a
  # hooks/tests/ or hooks/AGENTS.md edit alone never trips staleness.
  if [[ -d "$real_repo_dir/hooks" ]]; then
    cp -R "$real_repo_dir/hooks" "$snapshot_dir/hooks"
    rm -rf "$snapshot_dir/hooks/tests"
    rm -f "$snapshot_dir/hooks/AGENTS.md"
  fi
  if [[ -f "$real_repo_dir/.codex/config/hooks.json" ]]; then
    mkdir -p "$snapshot_dir/.codex/config"
    cp "$real_repo_dir/.codex/config/hooks.json" "$snapshot_dir/.codex/config/hooks.json"
  fi
  if [[ -d "$real_repo_dir/.codex/hooks" ]]; then
    mkdir -p "$snapshot_dir/.codex"
    cp -R "$real_repo_dir/.codex/hooks" "$snapshot_dir/.codex/hooks"
  fi
  if [[ -d "$real_repo_dir/.gemini/hooks" ]]; then
    mkdir -p "$snapshot_dir/.gemini"
    cp -R "$real_repo_dir/.gemini/hooks" "$snapshot_dir/.gemini/hooks"
  fi
  if [[ -d "$real_repo_dir/.kimi/hooks" ]]; then
    mkdir -p "$snapshot_dir/.kimi"
    cp -R "$real_repo_dir/.kimi/hooks" "$snapshot_dir/.kimi/hooks"
  fi

  # --- Compute + persist the source hash + metadata (atomic write) ---
  local source_hash=""
  source_hash="$(compute_hooks_source_hash \
    "$real_repo_dir/hooks" \
    "$real_repo_dir/.codex/config/hooks.json" \
    "$real_repo_dir/.codex/hooks" \
    "$real_repo_dir/.gemini/hooks" \
    "$real_repo_dir/.kimi/hooks")"

  local snapshotted_at=""
  snapshotted_at="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "")"

  python3 - "$snapshot_dir/.snapshot-meta.json" "$real_repo_dir" "$source_hash" "$snapshotted_at" <<'PYEOF'
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

  if [[ ! -e "$snapshot_dir" ]]; then
    return 1
  fi

  rm -rf -- "$snapshot_dir"
  return 0
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
