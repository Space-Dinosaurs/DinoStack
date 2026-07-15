#!/usr/bin/env bash
# Purpose: Shared activation guard for agentic-engineering shell hooks. Sourced
#          (not executed) by session-start-wrap.sh, skill-auto-load-check.sh, and
#          any other *.sh hook, which call `ae_is_active "$cwd" || exit 0` as the
#          first side-effect gate. Dormant projects turn the globally-registered
#          methodology hooks into instant no-ops.
#
# Activation layers (first hit wins), evaluated per candidate root while walking
# from cwd up to the outermost git root (so worktree-isolated subagents inherit
# the project root's activation instead of going silently dormant):
#   1. <root>/.agentic/active          -> ACTIVE (rc 0)
#   2. <root>/.agentic/active.session  -> ACTIVE (rc 0)
#   3. <root>/.agentic/dormant         -> DORMANT (rc 1) [tombstone overrides auto-detect]
#   4. <root>/.agentic/ dir exists     -> ACTIVE (rc 0) [zero-migration auto-detect]
#   5. any candidate root in ~/.agentic/activation.list -> ACTIVE (rc 0)
#   6. none                            -> DORMANT (rc 1)
#
# Worktree-zone hardening: candidate roots at or below
# <outermost-git-root>/.agentic/worktrees/ are subagent scratch space, not
# operator boundaries. Markers at those levels (active, active.session,
# dormant) are IGNORED and the walk continues up: a subagent must not be able
# to disable enforce-* hooks by writing its own dormant tombstone, and an
# active marker in scratch space is meaningless. The project root's own
# markers always decide.
#
# Public API: source this file, then `ae_is_active "<cwd>"`.
#   rc 0 = active (run the hook). rc 1 = dormant (hook should `exit 0` silently).
#   FAIL-ACTIVE: empty/indeterminate cwd returns 0 (active). Pure stat; no parse.
#
# Upstream deps: bash builtins only (`[[ -e ]]`, `[[ -d ]]`, `cd`, `pwd -P`).
#   No subshells in the walk loop; the only forks are `cd && pwd -P`
#   realpath resolution (once per call, plus allowlist lines when reached).
# Failure modes: never errors out the caller. Any ambiguity -> rc 0 (active), so
#                a guard bug preserves prior always-on behavior (plan R3).
# Performance: <10ms - a few `[[ -e ]]` tests per ancestor plus at most one
#              scan of the flat allowlist.

# ae_realpath <path> -> physical path on stdout, or empty on failure.
# One subshell fork; callers invoke it at most twice per guard call.
ae_realpath() {
  ( cd "$1" 2>/dev/null && pwd -P ) || return 1
}

# ae_in_worktree_zone <root> <bound> -> rc 0 if <root> is at or below
# <bound>/.agentic/worktrees/ (subagent scratch space; markers there ignored).
# Pure string math on already-canonical paths; no forks.
ae_in_worktree_zone() {
  local root="$1" bound="$2"
  [[ -n "$bound" ]] || return 1
  local rel="${root#"$bound"/}"
  # No strip -> root == bound (or bound not a prefix): outside the zone.
  [[ "$rel" == "$root" ]] && return 1
  # Zone == .agentic/worktrees or anything below it.
  [[ "$rel" == ".agentic/worktrees" || "$rel" == .agentic/worktrees/* ]]
}

# Guarded against multiple sourcing (idempotent function definition).
ae_is_active() {
  local cwd="${1:-}"
  # Indeterminate cwd -> fail ACTIVE.
  [[ -z "$cwd" ]] && return 0

  local start bound
  start="$(ae_realpath "$cwd")" || start="$cwd"
  # Outermost .git-bearing ancestor (incl. cwd). Worktrees carry a .git *file*;
  # the main checkout carries a .git *dir*; both count via `[[ -e ]]`.
  bound=""
  local cur="$start"
  while true; do
    [[ -e "$cur/.git" ]] && bound="$cur"
    local parent="${cur%/*}"
    [[ -z "$parent" ]] && parent="/"
    [[ "$parent" == "$cur" ]] && break
    cur="$parent"
  done

  # Walk from cwd up to the bound (inclusive), skipping worktree-zone levels.
  cur="$start"
  while true; do
    if ! ae_in_worktree_zone "$cur" "$bound"; then
      local agentic="$cur/.agentic"
      [[ -e "$agentic/active" ]] && return 0
      [[ -e "$agentic/active.session" ]] && return 0
      [[ -e "$agentic/dormant" ]] && return 1   # explicit tombstone
      [[ -d "$agentic" ]] && return 0           # auto-detect marker
    fi
    if [[ -z "$bound" || "$cur" == "$bound" ]]; then
      break
    fi
    local parent="${cur%/*}"
    [[ -z "$parent" ]] && parent="/"
    [[ "$parent" == "$cur" ]] && break
    cur="$parent"
  done

  # Allowlist fast-path: realpath match of ANY candidate root against the list.
  # Cheap literal-prefix string match first (zero forks); only a candidate hit
  # pays the per-line canonicalize fork, so large lists stay cheap.
  local list="$HOME/.agentic/activation.list"
  if [[ -f "$list" ]]; then
    local line croot rp
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      croot="$start"
      while true; do
        if [[ "$croot" == "$line" || "$croot" == "$line"/* ]]; then
          rp="$(ae_realpath "$line")" || rp="$line"
          [[ "$croot" == "$rp" ]] && return 0
        fi
        if [[ -z "$bound" || "$croot" == "$bound" ]]; then
          break
        fi
        local cparent="${croot%/*}"
        [[ -z "$cparent" ]] && cparent="/"
        [[ "$cparent" == "$croot" ]] && break
        croot="$cparent"
      done
    done <"$list"
  fi

  return 1  # dormant
}
