# shellcheck shell=bash
# ---------------------------------------------------------------------------
# Purpose: Single source of truth for "which test files does CI actually run",
#          so a local runner can execute exactly CI's set instead of a
#          hand-maintained approximation of it. Each derivation below is
#          extracted VERBATIM from the corresponding workflow job's own
#          `files=(...)` / `orphans=(...)` / `case` blocks - the glob, the
#          named orphans, the quarantine arms, and the zero-count hard-fail
#          are reproduced, not paraphrased.
#
#          This file changes nothing in CI. The workflows remain the
#          authority; bin/tests/test_ci_test_discovery.sh pins these
#          functions against a fresh inline re-derivation of each workflow's
#          loop so the two cannot drift silently.
#
# Public API (every function prints one repo-relative path per line,
# LC_ALL=C sorted for determinism - a caller may partition the list on
# index):
#   list_bin_sh_tests    - the set .github/workflows/bin-tests.yml's
#                          bin-sh-tests job runs.
#   list_hooks_js_tests  - the set .github/workflows/hooks-tests.yml's
#                          hooks-js-tests job runs.
#   list_hooks_sh_tests  - the set .github/workflows/hooks-tests.yml's
#                          hooks-sh-tests job runs.
#   list_hooks_py_tests  - the set .github/workflows/bin-tests.yml's
#                          hooks-python-tests job runs.
#
#   Each takes an optional first argument: the repo root to resolve globs
#   against (default: the repo root containing this library).
#
# Upstream dependencies: bash 3.2+, the repo working tree. No git, no
#                        network, no python.
#
# Downstream consumers: scripts/check-local.sh,
#                       bin/tests/test_ci_test_discovery.sh.
#
# Failure modes (all print to stderr and return 1):
#   - A named orphan or quarantine entry does not exist on disk. A renamed
#     or deleted file that is still named in a workflow's list is a hard
#     error in CI today; it is a hard error here too, rather than a silently
#     shorter list.
#   - A derivation resolves to zero files: "discovery is broken, not clean".
#     A glob that stops matching must never read as a clean run.
#
# Performance: standard - four globs and a sort, no subprocess per file.
# ---------------------------------------------------------------------------

_ci_discovery_repo_root() {
  if [ -n "${1:-}" ]; then
    printf '%s\n' "$1"
    return 0
  fi
  # This file lives at <repo>/scripts/lib/ci-test-discovery.sh.
  ( cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd )
}

# _ci_discovery_glob <root> <pattern>
# Expands a repo-relative glob under <root>, printing repo-relative paths.
# Prints nothing when the glob matches no file (bash leaves the pattern
# unexpanded; the literal is filtered out by the -f test).
_ci_discovery_glob() {
  local root="$1" pattern="$2"
  local p
  for p in "$root"/$pattern; do
    [ -f "$p" ] || continue
    printf '%s\n' "${p#$root/}"
  done
}

# _ci_discovery_select <label> <root> <quarantine-list> <candidate-list>
#
# Both lists are newline-separated repo-relative paths. Verifies that every
# named entry - candidate AND quarantine - exists on disk, subtracts the
# quarantine set, hard-fails on a zero-length remainder, and prints the
# survivors LC_ALL=C sorted.
#
# A quarantine arm naming a file that no longer exists is a hard error, not a
# no-op: it excludes nothing, and it hides that whatever the file was renamed
# to is now running unquarantined.
_ci_discovery_select() {
  local label="$1" root="$2" quarantine="$3" candidates="$4"
  local q f keep count=0 kept=""

  while IFS= read -r q; do
    [ -n "$q" ] || continue
    if [ ! -f "$root/$q" ]; then
      echo "ERROR: $label: quarantined test file '$q' not found - the quarantine arm names a file that no longer exists" >&2
      return 1
    fi
  done <<EOF
$quarantine
EOF

  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if [ ! -f "$root/$f" ]; then
      echo "ERROR: $label: expected test file '$f' not found - it may have been renamed or moved" >&2
      return 1
    fi
    keep=1
    while IFS= read -r q; do
      [ -n "$q" ] || continue
      if [ "$f" = "$q" ]; then
        keep=0
        break
      fi
    done <<EOF
$quarantine
EOF
    if [ "$keep" -eq 1 ]; then
      kept="$kept$f
"
      count=$((count + 1))
    fi
  done <<EOF
$candidates
EOF

  if [ "$count" -eq 0 ]; then
    echo "ERROR: $label: discovery matched zero runnable files - discovery is broken, not clean" >&2
    return 1
  fi

  printf '%s' "$kept" | LC_ALL=C sort
}

# ---------------------------------------------------------------------------
# .github/workflows/bin-tests.yml :: bin-sh-tests
#
# Verbatim source:
#   files=(bin/tests/test_*.sh)
#   orphans=(
#     tests/bootstrap-guard.test.sh
#     scripts/test/repo-dir.test.sh
#     .claude/tests/install-converge.test.sh
#     .cursor/tests/install-converge.test.sh
#   )
#   ... case "$f" in __no_quarantined_tests_yet__) continue ;; esac
#
# The job's single `case` arm is the placeholder sentinel
# `__no_quarantined_tests_yet__`, which matches no real path - so the
# quarantine set is genuinely empty and nothing is subtracted here. When a
# real arm is added to that job, add its path to the `quarantine` string
# below in the same change.
# ---------------------------------------------------------------------------
list_bin_sh_tests() {
  local root
  root="$(_ci_discovery_repo_root "${1:-}")"

  local orphans="tests/bootstrap-guard.test.sh
scripts/test/repo-dir.test.sh
.claude/tests/install-converge.test.sh
.cursor/tests/install-converge.test.sh"

  local quarantine=""

  _ci_discovery_select "bin-sh-tests" "$root" "$quarantine" \
    "$(_ci_discovery_glob "$root" "bin/tests/test_*.sh")
$orphans"
}

# ---------------------------------------------------------------------------
# .github/workflows/hooks-tests.yml :: hooks-js-tests
#
# Verbatim source:
#   for f in hooks/tests/test-*.js; do
#     case "$f" in
#       hooks/tests/test-wrap-acquire-lock.js|hooks/tests/test-wrap-release-lock.js)
#         continue ;;
#     esac
#
# Those two are NOT orphaned - they run in the sibling wrap-lock-tests job.
# ---------------------------------------------------------------------------
list_hooks_js_tests() {
  local root
  root="$(_ci_discovery_repo_root "${1:-}")"

  local quarantine="hooks/tests/test-wrap-acquire-lock.js
hooks/tests/test-wrap-release-lock.js"

  _ci_discovery_select "hooks-js-tests" "$root" "$quarantine" \
    "$(_ci_discovery_glob "$root" "hooks/tests/test-*.js")"
}

# ---------------------------------------------------------------------------
# .github/workflows/hooks-tests.yml :: hooks-sh-tests
#
# Verbatim source: glob hooks/tests/test-*.sh, minus the DS-89 quarantine arm
# for hooks/tests/test-version-check-core-repo-dir.sh.
# ---------------------------------------------------------------------------
list_hooks_sh_tests() {
  local root
  root="$(_ci_discovery_repo_root "${1:-}")"

  local quarantine="hooks/tests/test-version-check-core-repo-dir.sh"

  _ci_discovery_select "hooks-sh-tests" "$root" "$quarantine" \
    "$(_ci_discovery_glob "$root" "hooks/tests/test-*.sh")"
}

# ---------------------------------------------------------------------------
# .github/workflows/bin-tests.yml :: hooks-python-tests
#
# Verbatim source: glob hooks/tests/test-*.py, no orphans, no quarantine.
# ---------------------------------------------------------------------------
list_hooks_py_tests() {
  local root
  root="$(_ci_discovery_repo_root "${1:-}")"

  _ci_discovery_select "hooks-python-tests" "$root" "" \
    "$(_ci_discovery_glob "$root" "hooks/tests/test-*.py")"
}
