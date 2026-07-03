#!/usr/bin/env bash
# Purpose: Shared install-time dormancy decision for every adapter. One copy of
#          the dormant/resident prompt, the --dormant/--resident flag parse, and
#          the CI-safe default so the 11 install.sh scripts don't each reinvent
#          it. Uses the existing ae_confirm() TTY-safe prompt (never bare read).
#
# Public API (source this file, then call):
#   ae_resolve_dormancy "$@"
#       Reads --dormant / --resident from the passed args, else prompts via
#       ae_confirm when a TTY is present, else defaults to KEEP-CURRENT
#       (non-interactive installs never flip an existing choice). Prints the
#       resolved mode ("dormant" | "resident") to stdout. Honors the env
#       override AE_DORMANCY (dormant|resident) for scripted tests.
#
# Contract:
#   - --resident wins over --dormant if both are passed (explicit opt-in to full).
#   - Non-interactive (no /dev/tty) + no flag + no env  -> "resident" (back-compat:
#     the pre-dormancy installer always wrote the full block; CI stays green).
#   - Interactive + no flag -> prompt; default answer (Enter) = resident.
#
# Upstream deps: scripts/lib/identity.sh (ae_confirm); bash.
# Downstream consumers: every adapter install.sh.
# Failure modes: none — always prints exactly one of dormant|resident.
# Performance: one prompt at most.

# Pull in ae_confirm if the caller hasn't already sourced identity.sh.
if ! declare -f ae_confirm >/dev/null 2>&1; then
  _AE_DORM_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # shellcheck source=scripts/lib/identity.sh
  [[ -f "$_AE_DORM_LIB_DIR/identity.sh" ]] && . "$_AE_DORM_LIB_DIR/identity.sh"
fi

ae_resolve_dormancy() {
  local want=""  # "", "dormant", or "resident"

  # 1. Env override (scripted tests / CI matrix).
  case "${AE_DORMANCY:-}" in
    dormant) want="dormant" ;;
    resident) want="resident" ;;
  esac

  # 2. Flags (explicit intent; --resident wins over --dormant).
  local arg
  for arg in "$@"; do
    case "$arg" in
      --resident) want="resident" ;;
      --dormant) [[ "$want" == "resident" ]] || want="dormant" ;;
    esac
  done

  if [[ -n "$want" ]]; then
    echo "$want"
    return 0
  fi

  # 3. Interactive prompt (only when a TTY is readable and ae_confirm exists).
  #    Framed as dormant opt-in so ae_confirm's default-NO maps to the safe
  #    back-compat default (resident). Enter / anything non-y = resident.
  if [[ -r /dev/tty ]] && declare -f ae_confirm >/dev/null 2>&1; then
    if ae_confirm "  Install methodology DORMANT (off until you run /ds activate per project)? Default no = resident/always-on. [y/N] "; then
      echo "dormant"
    else
      echo "resident"
    fi
    return 0
  fi

  # 4. Non-interactive default: keep the legacy resident behavior.
  echo "resident"
}
# Note: the dormant stub writer lives in scripts/lib/stub.sh as
# ae_install_stub_file (single source; symlink-guarded, backs up real files).
