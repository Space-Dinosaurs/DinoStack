#!/usr/bin/env bash
# Purpose: Verify the four .claude/skills/agentic-engineering/{agents,commands,
#          references,rules} symlinks are relative in the COMMITTED tree, not
#          the working tree. Isolation-worktree side effects have intermittently
#          rewritten these to absolute paths, which resolve fine on the machine
#          that broke them but silently break the skill for every other clone.
#          Root cause is unconfirmed (DS-104) - this script is detection only.
#
# Public API: bash scripts/check-symlinks-relative.sh [ref]
#             bash scripts/check-symlinks-relative.sh --staged
#             ref defaults to HEAD when omitted. --staged checks the git
#             index instead of a ref (used by the hooks/pre-commit gate to
#             catch an absolutized symlink before it is committed); --staged
#             and [ref] are mutually exclusive (exit 2 if both given). At
#             most one positional [ref] argument is accepted in either mode
#             - a second positional arg now exits 2 ("too many arguments"),
#             tightened by DS-136: previously any extra positional args
#             (e.g. `origin/main extra`) were silently ignored.
#             Exits 0 when all four symlinks are relative (leading char !=
#             "/") or staged for deletion, 1 when any is absolute or
#             missing, 2 on usage/environment error.
#
# Upstream deps: git ls-tree, git cat-file (ref mode); git ls-files -s and
#                git diff --cached --diff-filter=D (staged mode). No
#                working-tree filesystem access in either mode - the index
#                is not the working tree.
#
# Downstream consumers: .github/workflows/adapter-sync.yml (ref mode);
#                        hooks/pre-commit (--staged mode).
#
# Failure modes: any of the four paths absent from the tree/index, not a
#                symlink (mode != 120000), or resolving to an absolute path
#                -> exit 1 with the offending path(s) listed. In --staged
#                mode, a path staged for deletion is treated as a non-fatal
#                skip rather than "missing" (a legitimate removal of one of
#                these links must not block the commit that removes it) -
#                this deletion-aware skip applies ONLY in --staged mode; ref
#                mode's equivalent gap is pre-existing, CI-facing, and out
#                of scope here.
#
# Performance: O(1) - four fixed git object/index lookups.

set -euo pipefail

# --- MODE-SPECIFIC FIELD LAYOUT - DO NOT UNIFY ---
# `git ls-tree <ref>` emits:  <mode> <type> <sha>    (sha is field 3)
# `git ls-files -s`   emits:  <mode> <sha> <stage>   (sha is field 2)
# Sharing one awk parse across both modes WILL silently break one of them.

STAGED=0
REF=""

for arg in "$@"; do
  case "$arg" in
    --staged)
      STAGED=1
      ;;
    -*)
      echo "check-symlinks-relative.sh: unknown option: $arg" >&2
      exit 2
      ;;
    *)
      if [ -n "$REF" ]; then
        echo "check-symlinks-relative.sh: too many arguments" >&2
        exit 2
      fi
      REF="$arg"
      ;;
  esac
done

if [ "$STAGED" -eq 1 ] && [ -n "$REF" ]; then
  echo "check-symlinks-relative.sh: --staged and [ref] are mutually exclusive" >&2
  exit 2
fi

REF="${REF:-HEAD}"
SKILL_DIR=".claude/skills/agentic-engineering"
LINKS="agents commands references rules"

fail=0

for name in $LINKS; do
  path="$SKILL_DIR/$name"

  if [ "$STAGED" -eq 1 ]; then
    entry="$(git ls-files -s -- "$path" 2>/dev/null || true)"
  else
    entry="$(git ls-tree "$REF" -- "$path" 2>/dev/null || true)"
  fi

  if [ -z "$entry" ]; then
    if [ "$STAGED" -eq 1 ] && git diff --cached --name-only --diff-filter=D -- "$path" | grep -qx "$path"; then
      echo "check-symlinks-relative.sh: $path is staged for deletion - skipping" >&2
      continue
    fi
    if [ "$STAGED" -eq 1 ]; then
      echo "check-symlinks-relative.sh: $path is missing from the index" >&2
    else
      echo "check-symlinks-relative.sh: $path is missing from $REF" >&2
    fi
    fail=1
    continue
  fi

  mode="$(echo "$entry" | awk '{print $1}')"
  if [ "$STAGED" -eq 1 ]; then
    sha="$(echo "$entry" | awk '{print $2}')"
  else
    sha="$(echo "$entry" | awk '{print $3}')"
  fi

  if [ "$mode" != "120000" ]; then
    if [ "$STAGED" -eq 1 ]; then
      echo "check-symlinks-relative.sh: $path is not a symlink in the index (mode $mode)" >&2
    else
      echo "check-symlinks-relative.sh: $path is not a symlink in $REF (mode $mode)" >&2
    fi
    fail=1
    continue
  fi

  target="$(git cat-file -p "$sha")"

  case "$target" in
    /*)
      if [ "$STAGED" -eq 1 ]; then
        echo "check-symlinks-relative.sh: $path is ABSOLUTIZED in the index -> $target" >&2
      else
        echo "check-symlinks-relative.sh: $path is ABSOLUTIZED in $REF -> $target" >&2
      fi
      fail=1
      ;;
    *)
      echo "check-symlinks-relative.sh: $path -> $target (relative, OK)"
      ;;
  esac
done

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  if [ "$STAGED" -eq 1 ]; then
    echo "One or more agentic-engineering skill symlinks are staged as absolutized paths." >&2
  else
    echo "One or more agentic-engineering skill symlinks are absolutized in $REF." >&2
  fi
  echo "Restore them to relative form (e.g. ../../../content/<name>) before merging." >&2
  exit 1
fi

exit 0
