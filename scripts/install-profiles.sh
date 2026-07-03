#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Module Manifest
#
# Purpose: Install agentic-engineering into per-tenant PROFILE config dirs
#          (e.g. ~/.claude-solara6, ~/.codex-crocs) across the claude/codex/
#          omp/pi harnesses, plus the single global Cursor install. Each
#          harness install.sh is invoked with --config-dir pointed at the
#          tenant profile dir, so shared user state (~/.agentic, ~/.local/bin,
#          ~/.claude.json) is NOT relocated -- only the per-harness config dir
#          moves. This is the profile-aware counterpart to install-all.sh,
#          which only ever targets the default base dirs.
#
# Public API:
#   ./scripts/install-profiles.sh
#       [--tenants="a b c"]      (default: "crocs express-labs solara6 xrite")
#       [--harnesses="a b c"]    (default: "claude codex omp pi")
#       [--no-cursor]            (skip the global ~/.cursor install)
#       [--dry-run]              (forwarded to installers that support it)
#       [-h|--help]
#   Any other flags (e.g. --mode=opt-out --profile=default --no-identity) are
#   forwarded verbatim to each harness install.sh.
#
# Profile dir convention: ~/.<harness>-<tenant> for claude/codex/pi;
#   ~/.omp-<tenant>/agent for omp (its config root is <base>/agent). A profile
#   dir is installed into only if it already exists on disk -- this script
#   never creates a new tenant tree, it only (re)installs into existing ones.
#
# Upstream deps: bash 3.2+, the per-harness <adapter>/install.sh scripts.
#
# Failure modes: continue-on-error; failures collected and reported in a final
#   summary; exit non-zero if any install failed. Missing profile dirs are
#   skipped with a note (not a failure).
# =============================================================================

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TENANTS="crocs express-labs solara6 xrite"
HARNESSES="claude codex omp pi"
DO_CURSOR=true
PASSTHROUGH=()

print_help() { sed -n '3,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "$arg" in
    -h|--help) print_help; exit 0 ;;
    --tenants=*)   TENANTS="${arg#--tenants=}" ;;
    --harnesses=*) HARNESSES="${arg#--harnesses=}" ;;
    --no-cursor)   DO_CURSOR=false ;;
    *)             PASSTHROUGH+=("$arg") ;;   # --mode, --profile, --dry-run, etc.
  esac
done

# Map a harness label to the profile config dir for a tenant.
# omp's config root is <base>/agent; the others are the base dir itself.
profile_config_dir() {
  local harness="$1" tenant="$2"
  case "$harness" in
    omp) printf '%s/.omp-%s/agent' "$HOME" "$tenant" ;;
    *)   printf '%s/.%s-%s' "$HOME" "$harness" "$tenant" ;;
  esac
}

# The on-disk profile base dir (existence gate), independent of omp's /agent.
profile_base_dir() { printf '%s/.%s-%s' "$HOME" "$1" "$2"; }

SUCCEEDED=() ; FAILED=() ; SKIPPED=()

for tenant in $TENANTS; do
  for harness in $HARNESSES; do
    base="$(profile_base_dir "$harness" "$tenant")"
    label="$harness-$tenant"
    if [[ ! -d "$base" ]]; then
      echo "  ~ skip $label: profile dir $base does not exist"
      SKIPPED+=("$label")
      continue
    fi
    installer="$REPO_DIR/.$harness/install.sh"
    if [[ ! -f "$installer" ]]; then
      echo "  ! skip $label: no installer at $installer"
      SKIPPED+=("$label")
      continue
    fi
    cfg="$(profile_config_dir "$harness" "$tenant")"
    echo ""
    echo "==> $label  (--config-dir=$cfg)"
    rc=0
    bash "$installer" --config-dir="$cfg" "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}" || rc=$?
    if [[ "$rc" -eq 0 ]]; then SUCCEEDED+=("$label"); else
      echo "  ! $label failed (exit $rc)" >&2 ; FAILED+=("$label")
    fi
  done
done

# Global Cursor (single ~/.cursor, no per-tenant variants).
if [[ "$DO_CURSOR" == true && -f "$REPO_DIR/.cursor/install.sh" ]]; then
  echo ""
  echo "==> cursor (global ~/.cursor)"
  rc=0
  bash "$REPO_DIR/.cursor/install.sh" "${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}" || rc=$?
  if [[ "$rc" -eq 0 ]]; then SUCCEEDED+=("cursor"); else
    echo "  ! cursor failed (exit $rc)" >&2 ; FAILED+=("cursor")
  fi
fi

echo ""
echo "================================================================"
echo "install-profiles summary"
echo "================================================================"
echo "Succeeded (${#SUCCEEDED[@]}): ${SUCCEEDED[*]:-none}"
[[ ${#SKIPPED[@]}  -gt 0 ]] && echo "Skipped   (${#SKIPPED[@]}): ${SKIPPED[*]}"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "Failed    (${#FAILED[@]}): ${FAILED[*]}"
  exit 1
fi
echo ""
echo "All ${#SUCCEEDED[@]} install(s) succeeded."
