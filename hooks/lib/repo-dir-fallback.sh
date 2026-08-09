# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Shared AE_REPO_DIR resolver for SessionStart-path hook scripts
#          that run from the deployed hooks-snapshot dir, where
#          scripts/lib/repo-dir.sh (the canonical resolver) is NOT present.
#          sync_hooks_snapshot copies `hooks/` wholesale plus exactly one
#          extra file, bin/ds-identity (scripts/lib/hooks-staleness-core.sh:
#          423,430) - it never copies scripts/. hooks/lib/, by contrast, IS
#          copied wholesale as part of `hooks/`, which is what makes this
#          file (unlike scripts/lib/repo-dir.sh itself) reachable from the
#          deployed layout.
#
#          Extracted (round-2 Skeptic Major) from two call sites that had
#          each independently reimplemented this exact inline fallback -
#          hooks/lib/version-check-core.sh and hooks/session-start-wrap.sh -
#          which is precisely the duplication the architect plan's own
#          "Alternatives considered" section rejected inventing. Both call
#          sites now source this one file instead.
#
# Public API:
#   resolve_ae_repo_dir_with_fallback
#     Sets AE_REPO_DIR in the caller's environment. No return-code contract
#     beyond "AE_REPO_DIR is always set to something" - callers that need to
#     know whether the result is a valid git repo should validate it
#     themselves (as version-check-core.sh and session-start-wrap.sh both
#     already do for their own purposes).
#
#     Resolution order:
#       1. scripts/lib/repo-dir.sh's resolve_repo_dir --quiet, when that
#          file exists relative to THIS file's own location (i.e. the
#          dev-checkout layout, where scripts/ sits alongside hooks/).
#       2. Inline fallback (used whenever scripts/lib/repo-dir.sh is
#          absent - the deployed hooks-snapshot layout, or a partial/older
#          checkout): read repo_dir from
#          $HOME/.agentic/agentic-engineering-config.json via python3; if
#          that path is empty or not a valid git repo, fall back to
#          $HOME/DinoStack.
#
# Upstream deps: $HOME/.agentic/agentic-engineering-config.json (optional;
#                repo_dir key), python3 (JSON parse, fallback path only),
#                git (repo validation, fallback path only). All optional;
#                a missing python3 or git degrades to the $HOME/DinoStack
#                fallback value rather than erroring.
#
# Downstream consumers: hooks/lib/version-check-core.sh,
#                       hooks/session-start-wrap.sh.
#
# Failure modes: never errors under set -euo pipefail (uses `|| true` /
#                `|| echo ""` throughout). Worst case on total resolution
#                failure: AE_REPO_DIR is set to $HOME/DinoStack, which the
#                caller is expected to validate before trusting it points
#                at a real, git-tracked clone.
#
# Performance: primary branch is one file existence check plus one
#              `git rev-parse --git-dir` call. Fallback branch adds one
#              python3 subprocess (JSON read) and one git validation call.
#              No network I/O either way.
# ---------------------------------------------------------------------------

resolve_ae_repo_dir_with_fallback() {
  # Compute this file's own directory so the primary-lib path is correct
  # regardless of which caller sources it (session-start-wrap.sh lives in
  # hooks/, version-check-core.sh lives in hooks/lib/ - this file's own
  # location, not the caller's, is what must be stable).
  local _rdf_dir
  _rdf_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local _repo_dir_lib="$_rdf_dir/../../scripts/lib/repo-dir.sh"

  AE_REPO_DIR=""

  if [[ -f "$_repo_dir_lib" ]]; then
    # Source the shared lib (defines functions only, no top-level side
    # effects; safe under set -euo pipefail). resolve_repo_dir --quiet sets
    # AE_REPO_DIR and returns 0 on a valid git repo, 1 otherwise. The
    # `|| true` makes this fail-open so set -e does not abort when the
    # resolved path is not a git repo.
    # shellcheck source=../../scripts/lib/repo-dir.sh
    source "$_repo_dir_lib"
    resolve_repo_dir --quiet || true
  else
    # Inline fallback: used whenever scripts/lib/repo-dir.sh is absent -
    # the deployed hooks-snapshot layout, or a partial/older checkout.
    local _ae_config="$HOME/.agentic/agentic-engineering-config.json"
    if [[ -f "$_ae_config" ]]; then
      AE_REPO_DIR="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$_ae_config" 2>/dev/null || echo "")"
    fi
    if [[ -z "$AE_REPO_DIR" ]] || ! git -C "$AE_REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
      AE_REPO_DIR="$HOME/DinoStack"
    fi
  fi

  export AE_REPO_DIR
}
