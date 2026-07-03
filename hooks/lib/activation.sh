#!/usr/bin/env bash
# Purpose: Shared activation guard for agentic-engineering shell hooks. Sourced
#          (not executed) by session-start-wrap.sh, skill-auto-load-check.sh, and
#          any other *.sh hook, which call `ae_is_active "$cwd" || exit 0` as the
#          first side-effect gate. Dormant projects turn the globally-registered
#          methodology hooks into instant no-ops.
#
# Activation layers (first hit wins):
#   1. <cwd>/.agentic/active          -> ACTIVE (rc 0)
#   2. <cwd>/.agentic/active.session  -> ACTIVE (rc 0)
#   3. <cwd>/.agentic/dormant         -> DORMANT (rc 1) [tombstone overrides auto-detect]
#   4. <cwd>/.agentic/ dir exists     -> ACTIVE (rc 0) [zero-migration auto-detect]
#   5. cwd in ~/.agentic/activation.list -> ACTIVE (rc 0)
#   6. none                           -> DORMANT (rc 1)
#
# Public API: source this file, then `ae_is_active "<cwd>"`.
#   rc 0 = active (run the hook). rc 1 = dormant (hook should `exit 0` silently).
#   FAIL-ACTIVE: empty/indeterminate cwd returns 0 (active). Pure stat; no parse.
#
# Upstream deps: coreutils (stat via `[[ -e ]]`, `grep`). No python on hot path.
# Failure modes: never errors out the caller. Any ambiguity -> rc 0 (active), so
#                a guard bug preserves prior always-on behavior (plan R3).
# Performance: <10ms - a few `[[ -e ]]` tests + at most one grep of the flat list.

# Guarded against multiple sourcing (idempotent function definition).
ae_is_active() {
  local cwd="${1:-}"
  # Indeterminate cwd -> fail ACTIVE.
  [[ -z "$cwd" ]] && return 0

  local agentic="$cwd/.agentic"
  [[ -e "$agentic/active" ]] && return 0
  [[ -e "$agentic/active.session" ]] && return 0
  [[ -e "$agentic/dormant" ]] && return 1   # explicit tombstone
  [[ -d "$agentic" ]] && return 0           # auto-detect marker

  # Allowlist fast-path: realpath match against the flat list.
  local list="$HOME/.agentic/activation.list"
  if [[ -f "$list" ]]; then
    local target
    target="$(cd "$cwd" 2>/dev/null && pwd -P)" || target="$cwd"
    local line rp
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      rp="$(cd "$line" 2>/dev/null && pwd -P)" || rp="$line"
      [[ "$rp" == "$target" ]] && return 0
    done <"$list"
  fi

  return 1  # dormant
}
