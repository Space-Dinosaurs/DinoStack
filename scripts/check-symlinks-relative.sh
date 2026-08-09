#!/usr/bin/env bash
# Purpose: Verify the four .claude/skills/dinostack/{agents,commands,
#          references,rules} symlinks are relative in the COMMITTED tree, not
#          the working tree. Isolation-worktree side effects have intermittently
#          rewritten these to absolute paths, which resolve fine on the machine
#          that broke them but silently break the skill for every other clone.
#          Root cause is unconfirmed (DS-104) - this script is detection only.
#
# Public API: bash scripts/check-symlinks-relative.sh [ref]
#             ref defaults to HEAD. Exits 0 when all four symlinks are
#             relative (leading char != "/"), 1 when any is absolute or
#             missing, 2 on usage/environment error.
#
# Upstream deps: git ls-tree, git cat-file. No working-tree filesystem access -
#                operates purely on the git object database for the given ref.
#
# Downstream consumers: .github/workflows/adapter-sync.yml
#
# Failure modes: any of the four paths absent from the tree, not a symlink
#                (mode != 120000), or resolving to an absolute path -> exit 1
#                with the offending path(s) listed.
#
# Performance: O(1) - four fixed git object lookups.

set -euo pipefail

REF="${1:-HEAD}"
SKILL_DIR=".claude/skills/dinostack"
LINKS="agents commands references rules"

fail=0

for name in $LINKS; do
  path="$SKILL_DIR/$name"
  entry="$(git ls-tree "$REF" -- "$path" 2>/dev/null || true)"

  if [ -z "$entry" ]; then
    echo "check-symlinks-relative.sh: $path is missing from $REF" >&2
    fail=1
    continue
  fi

  mode="$(echo "$entry" | awk '{print $1}')"
  sha="$(echo "$entry" | awk '{print $3}')"

  if [ "$mode" != "120000" ]; then
    echo "check-symlinks-relative.sh: $path is not a symlink in $REF (mode $mode)" >&2
    fail=1
    continue
  fi

  target="$(git cat-file -p "$sha")"

  case "$target" in
    /*)
      echo "check-symlinks-relative.sh: $path is ABSOLUTIZED in $REF -> $target" >&2
      fail=1
      ;;
    *)
      echo "check-symlinks-relative.sh: $path -> $target (relative, OK)"
      ;;
  esac
done

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "One or more dinostack skill symlinks are absolutized in $REF." >&2
  echo "Restore them to relative form (e.g. ../../../content/<name>) before merging." >&2
  exit 1
fi

exit 0
