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
#   ROUND-2 REWORK (adversarial review Minor): this resolver is NOT
#   semantically mirrored to hooks/lib/repo-root.js / repo_root.py -
#   `git rev-parse --show-toplevel` fails when run from inside a bare
#   `.git` directory itself and requires `git` on PATH, where the JS/Py
#   walk is existence-only (checks for a `.git` entry at each level) and
#   has no external dependency. This divergence is DELIBERATE, not an
#   unfixed bug: this file's sole consumer, hooks/session-start-wrap.sh,
#   is a plain POSIX shell hook with no python3/node guarantee at the
#   point it runs (SessionStart, before any harness-specific runtime
#   assumption is safe to make) - `git` is the one dependency that
#   invocation environment can actually assume, since the hook is already
#   operating on a git checkout by construction. Re-implementing the
#   existence-only walk in bash would add real complexity (directory
#   traversal, symlink-safe realpath) to remove a dependency that is
#   already guaranteed present, for a resolver with exactly one caller
#   that already fails safe (empty-string skip, `-n "$resolved_root"`
#   guard, zero `|| echo "$cwd"` fallback - verified correct and
#   unchanged by this rework). If a second, non-git-guaranteed caller of
#   this file is ever added, revisit this decision.
#
# Performance: one `git rev-parse` subprocess call per invocation.

resolve_agentic_root() {
  local start="$1" root
  root="$(cd "$start" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)" || root=""
  printf '%s' "$root"
}
