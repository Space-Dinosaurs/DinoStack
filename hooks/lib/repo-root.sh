# Purpose: Resolves the repo-root directory to anchor `.agentic/` state
#          writes for session-start-wrap.sh, instead of trusting the
#          harness-supplied payload cwd verbatim. No python3 or node
#          dependency - shells out to `git rev-parse --show-toplevel`.
#
# Public API: resolve_agentic_root "$start_dir"  (prints resolved root to
#             stdout, or an empty string on resolution failure)
#
# Upstream deps: git (rev-parse --show-toplevel)
#
# Downstream consumers: hooks/session-start-wrap.sh
#
# Failure modes: on any failure (start dir does not exist, not inside a
#   git repo, git not on PATH) prints an EMPTY STRING. Callers MUST skip
#   the .agentic write entirely on empty output - never fall back to
#   $cwd, which would silently reproduce the bug this resolver exists to
#   fix.
#
# Performance: one `git rev-parse` subprocess call per invocation.

resolve_agentic_root() {
  local start="$1" root
  root="$(cd "$start" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)" || root=""
  printf '%s' "$root"
}
