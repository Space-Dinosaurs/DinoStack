# Purpose: Resolves the repo-root directory to anchor `.agentic/` state
#          reads/writes for shell hooks, instead of trusting the
#          harness-supplied payload cwd verbatim. No python3 or node
#          dependency - shells out to `git rev-parse --show-toplevel`.
#
# Public API: resolve_agentic_root "$start_dir"  (prints resolved root to
#             stdout, or an empty string on resolution failure)
#
# Upstream deps: git (rev-parse --show-toplevel)
#
# Downstream consumers: hooks/session-start-wrap.sh,
#   .copilot/hooks/session-start-copilot.sh, .github/hooks/session-start-copilot.sh
#   (the latter two are hand-duplicated copies of each other, not
#   build-generated - keep them in sync by hand on any future edit)
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
#   unfixed bug: this file's consumers are all plain POSIX shell hooks with
#   no python3/node guarantee at the point they run (SessionStart, before
#   any harness-specific runtime assumption is safe to make) - `git` is the
#   one dependency that invocation environment can actually assume, since
#   the hook is already operating on a git checkout by construction.
#   Re-implementing the existence-only walk in bash would add real
#   complexity (directory traversal, symlink-safe realpath) to remove a
#   dependency that is already guaranteed present. Every consumer already
#   fails safe (empty-string skip, `-n "$resolved_root"` guard or
#   equivalent, zero `|| echo "$cwd"`/`|| echo "$(pwd)"` fallback -
#   verified correct for all three at last audit). If a caller of this
#   file that CANNOT assume git-on-PATH is ever added, revisit this
#   decision for that caller specifically.
#
# Performance: one `git rev-parse` subprocess call per invocation.

resolve_agentic_root() {
  local start="$1" root
  root="$(cd "$start" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null)" || root=""
  printf '%s' "$root"
}
