#!/usr/bin/env bash
# WorktreeCreate hook for a multi-repo workspace (root is a plain folder of git
# repos). Installed by /ds-init-project; see content/references/subagent-protocol.md
# §Multi-repo workspace. stdin: hook JSON with `name`. stdout: one line, the
# physical worktree path. Everything else goes to stderr; non-zero fails the spawn.
set -euo pipefail

die() { echo "worktree-create: ERROR: $*" >&2; exit 1; }

SAFE='^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$'

NAME="$(python3 -c 'import json, sys; v = json.load(sys.stdin).get("name"); print(v if isinstance(v, str) else "")' 2>/dev/null)" \
  || die "could not parse hook input JSON"
[ -n "$NAME" ] || die "hook input has no 'name' field"
[[ "$NAME" =~ $SAFE ]] || die "unsafe worktree name: $NAME"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WS="${CLAUDE_PROJECT_DIR:-$SCRIPT_DIR/../..}"
WS="$(cd "$WS" && pwd -P)" || die "workspace root not found: $WS"

list_repos() {
  local d found=""
  for d in "$WS"/*/; do
    [ -d "$d.git" ] && found="$found $(basename "$d")"
  done
  echo "${found:- (none found)}"
}

TARGET_FILE="$WS/.agentic/worktree-target"
[ -f "$TARGET_FILE" ] || die "target file $TARGET_FILE is missing. Write one repo name to it before an isolation spawn. Repos:$(list_repos)"
T="$(head -n1 "$TARGET_FILE" | tr -d '[:space:]')"
[[ "$T" =~ $SAFE ]] || die "target '$T' in $TARGET_FILE is not a valid repo name. Repos:$(list_repos)"
REPO="$WS/$T"
[ -d "$REPO/.git" ] || die "target '$T' in $TARGET_FILE is not a repo with a .git directory under $WS. Repos:$(list_repos)"

BASE_DIR="$WS/.worktrees/$T"
WT="$BASE_DIR/$NAME"
BRANCH="worktree-$NAME"
[ -e "$WT" ] && die "worktree path already exists: $WT"
git -C "$REPO" show-ref --verify --quiet "refs/heads/$BRANCH" && die "branch $BRANCH already exists in $T"

mkdir -p "$BASE_DIR"

# Parallel spawns into one repo would collide on git's own locks.
LOCK="$BASE_DIR/.create.lock"
locked=0
for _ in $(seq 1 120); do
  if mkdir "$LOCK" 2>/dev/null; then locked=1; break; fi
  if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +5 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null || true
  fi
  sleep 1
done
[ "$locked" = 1 ] || die "could not acquire lock $LOCK"
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

# A stale origin ref would silently yield an old tree.
git -C "$REPO" fetch --quiet --prune origin >&2 || die "git fetch origin failed in $T"

REF="$(git -C "$REPO" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
if [ -z "$REF" ]; then
  for b in main master; do
    if git -C "$REPO" show-ref --verify --quiet "refs/remotes/origin/$b"; then REF="origin/$b"; break; fi
  done
fi
[ -n "$REF" ] || die "could not determine the origin default branch for $T"

git -C "$REPO" worktree add --quiet --no-track -b "$BRANCH" "$WT" "$REF" >&2 \
  || die "git worktree add failed for $T at $WT"

# Linked worktrees read the shared common dir's info/exclude, not a private one.
EXCLUDE="$(git -C "$WT" rev-parse --path-format=absolute --git-path info/exclude)"
mkdir -p "$(dirname "$EXCLUDE")"
PAT='.agentic/.ticket-scan-*.json'
grep -qxF "$PAT" "$EXCLUDE" 2>/dev/null || printf '%s\n' "$PAT" >> "$EXCLUDE"

echo "worktree-create: $T -> $WT (branch $BRANCH from $REF @ $(git -C "$WT" rev-parse --short HEAD))" >&2
(cd "$WT" && pwd -P)
