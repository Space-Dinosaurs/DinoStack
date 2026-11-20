#!/usr/bin/env bash
# Purpose: regression spec for the multi-repo workspace WorktreeCreate and
#          WorktreeRemove hook templates in content/templates/multi-repo-workspace/
#          (content/references/subagent-protocol.md §Multi-repo workspace).
#          Runs the real scripts against a scratch workspace whose child repos
#          clone local bare origins; never touches the real checkout.
#
# Public API: none (`bash bin/tests/test_workspace_worktree_hooks.sh`).
#
# Upstream deps: the two templates; bin/ds-retire-carrier (via PATH); git; python3.
#
# Downstream consumers: CI (bin-tests.yml shell-test glob).
#
# Failure modes: exits 1 when any assertion fails; the scratch dir is deleted on exit.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
TEMPLATES="$REPO_ROOT/content/templates/multi-repo-workspace"
S="$(cd "$(mktemp -d)" && pwd -P)"

cleanup() {
  chmod -R u+w "$S" 2>/dev/null || true
  find "${S:?}" -depth -delete 2>/dev/null || true
}
trap cleanup EXIT

export HOME="$S/home"
export PATH="$REPO_ROOT/bin:$PATH"
export GIT_CONFIG_NOSYSTEM=1
mkdir -p "$HOME"
G=(git -c user.email=spec@example.com -c user.name=spec -c init.defaultBranch=main)

fail_count=0
assert() {
  if [ "$1" -eq 0 ]; then echo "  PASS: $2"; else echo "  FAIL: $2"; fail_count=$((fail_count + 1)); fi
}

WS="$S/ws"
mkdir -p "$WS/.claude/hooks" "$WS/.agentic"
cp "$TEMPLATES/worktree-create.sh" "$TEMPLATES/worktree-remove.sh" "$WS/.claude/hooks/"

for r in a b; do
  "${G[@]}" init -q --bare "$S/$r.git"
  "${G[@]}" clone -q "$S/$r.git" "$S/seed-$r" 2>/dev/null
  printf '.env\nbuild.log\n' > "$S/seed-$r/.gitignore"
  echo "$r" > "$S/seed-$r/README.md"
  "${G[@]}" -C "$S/seed-$r" add -A
  "${G[@]}" -C "$S/seed-$r" commit -q -m init
  "${G[@]}" -C "$S/seed-$r" push -q origin main 2>/dev/null
  "${G[@]}" clone -q "$S/$r.git" "$WS/$r" 2>/dev/null
  echo more >> "$S/seed-$r/README.md"
  "${G[@]}" -C "$S/seed-$r" commit -q -am advance
  "${G[@]}" -C "$S/seed-$r" push -q origin main 2>/dev/null
done

create() {
  printf '{"name":"%s"}' "$1" | CLAUDE_PROJECT_DIR="$WS" bash "$WS/.claude/hooks/worktree-create.sh" 2>"$S/create.err"
}
remove_json() {
  printf '%s' "$1" | CLAUDE_PROJECT_DIR="$WS" bash "$WS/.claude/hooks/worktree-remove.sh" 2>"$S/remove.err"
}
remove() { remove_json "{\"worktree_path\":\"$1\"}"; }

echo "create: target a"
echo a > "$WS/.agentic/worktree-target"
out="$(create c1)"; rc=$?
assert "$rc" "create exits 0"
[ "$(printf '%s\n' "$out" | wc -l | tr -d ' ')" = 1 ] && [ "$out" = "$WS/.worktrees/a/c1" ]
assert $? "stdout is exactly one line, the physical worktree path"
[ "$(git -C "$WS/.worktrees/a/c1" rev-parse HEAD)" = "$(git -C "$S/a.git" rev-parse main)" ]
assert $? "worktree is at the fresh origin tip, not the stale clone"
[ "$(git -C "$WS/.worktrees/a/c1" branch --show-current)" = worktree-c1 ]
assert $? "worktree is on branch worktree-c1"

echo "create: switch target to b"
echo b > "$WS/.agentic/worktree-target"
out="$(create c2)"; rc=$?
[ "$rc" -eq 0 ] && [ "$out" = "$WS/.worktrees/b/c2" ] && git -C "$WS/b" worktree list | grep -q "$WS/.worktrees/b/c2"
assert $? "spawn lands in b"

echo "create: missing target"
rm "$WS/.agentic/worktree-target"
out="$(create c3)"; rc=$?
[ "$rc" -ne 0 ] && [ -z "$out" ] && grep -q 'Repos: a b$' "$S/create.err" && [ ! -e "$WS/.worktrees/a/c3" ]
assert $? "fails, names no path, lists both repos"
echo a > "$WS/.agentic/worktree-target"

echo "remove: clean worktree with only a ticket-scan file"
mkdir -p "$WS/.worktrees/a/c1/.agentic"
echo '{}' > "$WS/.worktrees/a/c1/.agentic/.ticket-scan-x.json"
remove "$WS/.worktrees/a/c1"; rc=$?
[ "$rc" -eq 0 ] && [ ! -e "$WS/.worktrees/a/c1" ]
assert $? "exit 0 and the folder is gone"
git -C "$WS/a" show-ref --verify --quiet refs/heads/worktree-c1
assert $? "branch worktree-c1 is kept"

echo "remove: ignored .env is held"
wt="$(create e1)"
echo SECRET=1 > "$wt/.env"
remove "$wt"; rc=$?
[ "$rc" -eq 1 ] && [ -f "$wt/.env" ]
assert $? "exit 1 and .env survives in place"

echo "remove: ignored non-protected file is archived"
wt="$(create l1)"
echo log > "$wt/build.log"
remove "$wt"; rc=$?
[ "$rc" -eq 0 ] && [ ! -e "$wt" ] && find "$HOME/.agentic/worktree-archive" -name '*.ignored.tgz' -exec tar -tzf {} \; 2>/dev/null | grep -q 'build.log$'
assert $? "exit 0, folder gone, build.log archived under HOME/.agentic/worktree-archive"

echo "remove: unpinned commit on a detached HEAD is held"
wt="$(create d1)"
git -C "$wt" checkout -q --detach
echo x > "$wt/x.txt"
"${G[@]}" -C "$wt" add x.txt
"${G[@]}" -C "$wt" commit -q -m unpinned
sha="$(git -C "$wt" rev-parse HEAD)"
remove "$wt"; rc=$?
[ "$rc" -eq 1 ] && [ -d "$wt" ] && [ "$(git -C "$wt" rev-parse HEAD)" = "$sha" ]
assert $? "exit 1 and the commit stays reachable"

echo "remove: input and path validation"
remove_json '{}'; rc=$?
[ "$rc" -eq 1 ]
assert $? "missing worktree_path exits 1"
remove "$WS/.worktrees/a/nope"; rc=$?
[ "$rc" -eq 0 ]
assert $? "absent folder exits 0"
git -C "$WS/a" worktree add -q "$S/outside" >/dev/null 2>&1
remove "$S/outside"; rc=$?
[ "$rc" -eq 1 ] && [ -d "$S/outside" ]
assert $? "path outside .worktrees is refused"
ln -s "$S/outside" "$WS/.worktrees/a/link"
remove "$WS/.worktrees/a/link"; rc=$?
[ "$rc" -eq 1 ] && [ -d "$S/outside" ]
assert $? "symlink inside .worktrees resolving outside it is refused"
wt="$(create s1)"
ln -s "$wt" "$S/alias"
remove "$S/alias"; rc=$?
[ "$rc" -eq 0 ] && [ ! -e "$wt" ]
assert $? "path resolving into .worktrees/a/<name> is accepted"

echo
if [ "$fail_count" -ne 0 ]; then
  echo "FAILED: $fail_count assertion(s)"
  exit 1
fi
echo "ALL PASS"
