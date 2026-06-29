# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Canonical repo_dir resolver for the agentic-engineering install.
#          Centralises the resolution logic previously duplicated inline in
#          .claude/install.sh, hooks/lib/version-check-core.sh, bootstrap.sh,
#          and content/commands/update-agentic-engineering.md Step 0a.
#
# Public API:
#   resolve_repo_dir [--quiet]   - Resolve AE_REPO_DIR from config or fallback.
#                                  Sets AE_REPO_DIR in the caller's env.
#                                  Returns 0 on a valid git repo, 1 otherwise.
#                                  --quiet suppresses the "using fallback" warning.
#   validate_repo_dir <path>     - Returns 0 if <path> is a valid git repo,
#                                  1 otherwise. Prints nothing.
#   assert_canonical_match <session_root> - Canonicalize <session_root> and
#                                  $AE_REPO_DIR via pwd -P; return 0 if equal,
#                                  print a message to stderr and return 2 if not.
#
# Upstream dependencies:
#   $HOME/.agentic/agentic-engineering-config.json (repo_dir key, optional),
#   python3 (JSON parsing, matching existing codebase pattern),
#   git (rev-parse --git-dir for repo validation).
#
# Downstream consumers (planned migrators):
#   .claude/install.sh, hooks/lib/version-check-core.sh, bootstrap.sh,
#   content/commands/update-agentic-engineering.md Step 0a.
#
# Failure modes:
#   - Config absent or missing repo_dir key: falls back to $HOME/DinoStack.
#   - Fallback path is not a git repo: resolve_repo_dir returns 1; AE_REPO_DIR
#     is still set to the fallback so callers can print actionable messages.
#   - python3 absent: config read silently fails, fallback applies.
#   - Non-existent <path> passed to validate_repo_dir: returns 1.
#   - assert_canonical_match: returns 2 (not 1) so callers can distinguish
#     "bad path" (validate_repo_dir returns 1) from "wrong repo" (returns 2).
#   Safe to source under set -euo pipefail; no top-level side effects beyond
#   function definitions.
#
# Performance: standard - one git rev-parse per call; python3 JSON read only
#              when the config file exists.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# validate_repo_dir <path>
#   Returns 0 if <path> is the root of a valid git repository, 1 otherwise.
#   Prints nothing.
# ---------------------------------------------------------------------------
validate_repo_dir() {
  local path="$1"
  local rc=0
  git -C "$path" rev-parse --git-dir >/dev/null 2>&1 || rc=$?
  # git returns 128 for "not a git repo" and 1 for other errors; normalise both to 1
  [[ "$rc" -eq 0 ]]
}

# ---------------------------------------------------------------------------
# resolve_repo_dir [--quiet]
#   Resolution order:
#     1. repo_dir key from $HOME/.agentic/agentic-engineering-config.json
#     2. Fallback: $HOME/DinoStack
#   Sets AE_REPO_DIR in the caller's environment.
#   Returns 0 if AE_REPO_DIR is a valid git repo, 1 otherwise.
#   --quiet suppresses the "using fallback" warning printed to stderr.
# ---------------------------------------------------------------------------
resolve_repo_dir() {
  local quiet=false
  if [[ "${1:-}" == "--quiet" ]]; then
    quiet=true
  fi

  local ae_config="$HOME/.agentic/agentic-engineering-config.json"
  AE_REPO_DIR=""

  if [[ -f "$ae_config" ]]; then
    AE_REPO_DIR="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$ae_config" 2>/dev/null)" || AE_REPO_DIR=""
  fi

  if [[ -z "$AE_REPO_DIR" ]] || ! validate_repo_dir "$AE_REPO_DIR"; then
    if [[ -n "$AE_REPO_DIR" ]] && [[ "$quiet" == "false" ]]; then
      echo "agentic-engineering: repo_dir '$AE_REPO_DIR' is not a valid git repo - using fallback \$HOME/DinoStack" >&2
    fi
    AE_REPO_DIR="$HOME/DinoStack"
    if [[ "$quiet" == "false" ]] && [[ ! -d "$AE_REPO_DIR" ]]; then
      echo "agentic-engineering: fallback \$HOME/DinoStack does not exist" >&2
    fi
  fi

  export AE_REPO_DIR
  validate_repo_dir "$AE_REPO_DIR"
}

# ---------------------------------------------------------------------------
# assert_canonical_match <session_root>
#   Canonicalize <session_root> and $AE_REPO_DIR via pwd -P, then compare.
#   Returns 0 if they resolve to the same path.
#   Prints a message to stderr and returns 2 if they differ.
#   Mirrors the Step 0a pattern from update-agentic-engineering.md.
# ---------------------------------------------------------------------------
assert_canonical_match() {
  local session_root="$1"

  local ae_real=""
  local session_real=""
  ae_real="$(cd "$AE_REPO_DIR" 2>/dev/null && pwd -P || true)"
  session_real="$(cd "$session_root" 2>/dev/null && pwd -P || true)"

  if [[ -n "$session_real" ]] && [[ "$session_real" == "$ae_real" ]]; then
    return 0
  fi

  echo "agentic-engineering: session root '$session_real' does not match AE_REPO_DIR '$ae_real'" >&2
  return 2
}
