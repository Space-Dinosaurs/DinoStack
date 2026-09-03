#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Pin scripts/lib/ci-test-discovery.sh against the CI workflows it
#          claims to mirror. The library exists so a local runner executes
#          EXACTLY CI's test set; the moment the two diverge the library is
#          worse than nothing, because a green local run would then be
#          evidence for a set CI does not run.
#
#          Two independent axes:
#            1. Set equality against a FRESH INLINE re-derivation of each
#               workflow job's own loop, written out longhand here rather
#               than by calling the library (a library bug cannot hide
#               inside its own oracle).
#            2. Literal presence of each orphan / quarantine entry in the
#               workflow YAML, so a change to CI's list reddens this test
#               instead of silently making the library stale.
#
#          Plus the failure modes: zero-count hard-fail, a missing orphan,
#          and a quarantine arm naming a file that no longer exists.
#
# Public API: bash bin/tests/test_ci_test_discovery.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, grep, sort, diff. No network, no python, no
#                git. Runs under bash 3.2 and bash 5 alike.
#
# Downstream consumers: CI (the bin-sh-tests job auto-discovers
#                       bin/tests/test_*.sh), and scripts/check-local.sh.
#
# Failure modes: any set mismatch prints the diff naming which side has the
#                extra path; any missing workflow literal names the string
#                that vanished.
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT" || exit 1

LIB="$REPO_ROOT/scripts/lib/ci-test-discovery.sh"
BIN_WF="$REPO_ROOT/.github/workflows/bin-tests.yml"
HOOKS_WF="$REPO_ROOT/.github/workflows/hooks-tests.yml"

PASS=0
FAIL=0
_pass() { PASS=$((PASS + 1)); echo "PASS: $1"; }
_fail() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

for f in "$LIB" "$BIN_WF" "$HOOKS_WF"; do
  if [ ! -f "$f" ]; then
    echo "FAIL: required input not found: $f"
    exit 1
  fi
done

# shellcheck source=scripts/lib/ci-test-discovery.sh
. "$LIB"

TMPROOT="$(mktemp -d -t ci-test-discovery.XXXXXX)"
cleanup() { rm -rf "$TMPROOT"; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Axis 1: set equality vs. a fresh inline re-derivation of each workflow loop.
# ---------------------------------------------------------------------------

# bin-tests.yml :: bin-sh-tests, transcribed longhand.
_inline_bin_sh() {
  local files=(bin/tests/test_*.sh)
  local orphans=(
    tests/bootstrap-guard.test.sh
    scripts/test/repo-dir.test.sh
    .claude/tests/install-converge.test.sh
    .cursor/tests/install-converge.test.sh
  )
  local f
  for f in "${orphans[@]}"; do
    [ -f "$f" ] || { echo "MISSING ORPHAN $f" >&2; return 1; }
    files+=("$f")
  done
  for f in "${files[@]}"; do
    case "$f" in
      __no_quarantined_tests_yet__) continue ;;
    esac
    printf '%s\n' "$f"
  done | LC_ALL=C sort
}

# hooks-tests.yml :: hooks-js-tests, transcribed longhand.
_inline_hooks_js() {
  local f
  for f in hooks/tests/test-*.js; do
    case "$f" in
      hooks/tests/test-wrap-acquire-lock.js|hooks/tests/test-wrap-release-lock.js) continue ;;
    esac
    printf '%s\n' "$f"
  done | LC_ALL=C sort
}

# hooks-tests.yml :: hooks-sh-tests, transcribed longhand.
_inline_hooks_sh() {
  local f
  for f in hooks/tests/test-*.sh; do
    case "$f" in
      hooks/tests/test-version-check-core-repo-dir.sh) continue ;;
    esac
    printf '%s\n' "$f"
  done | LC_ALL=C sort
}

# bin-tests.yml :: hooks-python-tests, transcribed longhand.
_inline_hooks_py() {
  local f
  for f in hooks/tests/test-*.py; do
    printf '%s\n' "$f"
  done | LC_ALL=C sort
}

_assert_same_set() {
  # _assert_same_set <label> <lib-fn> <inline-fn>
  local label="$1" libfn="$2" inlinefn="$3"
  local a b
  a="$("$libfn" "$REPO_ROOT")" || { _fail "$label: library function returned nonzero"; return; }
  b="$("$inlinefn")" || { _fail "$label: inline re-derivation returned nonzero"; return; }
  if [ "$a" = "$b" ]; then
    _pass "$label: library list is byte-identical to a fresh inline re-derivation ($(printf '%s\n' "$a" | wc -l | tr -d ' ') files)"
  else
    _fail "$label: library list differs from the inline re-derivation:
$(diff <(printf '%s\n' "$b") <(printf '%s\n' "$a") | sed 's/^/    /')"
  fi
}

_assert_same_set "bin-sh-tests"       list_bin_sh_tests    _inline_bin_sh
_assert_same_set "hooks-js-tests"     list_hooks_js_tests  _inline_hooks_js
_assert_same_set "hooks-sh-tests"     list_hooks_sh_tests  _inline_hooks_sh
_assert_same_set "hooks-python-tests" list_hooks_py_tests  _inline_hooks_py

# A non-empty list is not implied by set equality: two identically-broken
# globs also match. Assert the real repo yields a plausible count.
for pair in "bin-sh-tests:list_bin_sh_tests" "hooks-js-tests:list_hooks_js_tests" \
            "hooks-sh-tests:list_hooks_sh_tests" "hooks-python-tests:list_hooks_py_tests"; do
  label="${pair%%:*}"
  fn="${pair#*:}"
  n="$("$fn" "$REPO_ROOT" | wc -l | tr -d ' ')"
  if [ "${n:-0}" -gt 0 ]; then
    _pass "$label: non-empty against the real repo ($n files)"
  else
    _fail "$label: resolved to zero files against the real repo"
  fi
done

# ---------------------------------------------------------------------------
# Axis 2: the workflow YAML still says what the library transcribed.
# ---------------------------------------------------------------------------
_assert_workflow_literal() {
  # _assert_workflow_literal <file> <literal>
  if grep -qF -- "$2" "$1"; then
    _pass "$(basename "$1") still contains '$2'"
  else
    _fail "$(basename "$1") no longer contains '$2' - CI's set changed and scripts/lib/ci-test-discovery.sh was not updated with it"
  fi
}

_assert_workflow_literal "$BIN_WF" "files=(bin/tests/test_*.sh)"
_assert_workflow_literal "$BIN_WF" "tests/bootstrap-guard.test.sh"
_assert_workflow_literal "$BIN_WF" "scripts/test/repo-dir.test.sh"
_assert_workflow_literal "$BIN_WF" ".claude/tests/install-converge.test.sh"
_assert_workflow_literal "$BIN_WF" ".cursor/tests/install-converge.test.sh"
_assert_workflow_literal "$BIN_WF" "__no_quarantined_tests_yet__"
_assert_workflow_literal "$BIN_WF" "for f in hooks/tests/test-*.py"
_assert_workflow_literal "$HOOKS_WF" "for f in hooks/tests/test-*.js"
_assert_workflow_literal "$HOOKS_WF" "hooks/tests/test-wrap-acquire-lock.js|hooks/tests/test-wrap-release-lock.js"
_assert_workflow_literal "$HOOKS_WF" "for f in hooks/tests/test-*.sh"
_assert_workflow_literal "$HOOKS_WF" "hooks/tests/test-version-check-core-repo-dir.sh"

# ---------------------------------------------------------------------------
# Failure modes.
# ---------------------------------------------------------------------------

# Zero-count hard-fail: a scratch root whose only test-*.js files are the two
# the quarantine subtracts. The remainder is empty, which must read as broken
# discovery, never as a clean run.
ZERO="$TMPROOT/zero"
mkdir -p "$ZERO/hooks/tests"
touch "$ZERO/hooks/tests/test-wrap-acquire-lock.js" "$ZERO/hooks/tests/test-wrap-release-lock.js"
out="$(list_hooks_js_tests "$ZERO" 2>&1)"
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "discovery is broken, not clean"; then
  _pass "zero-count hard-fail fires (rc=$rc) with the 'discovery is broken, not clean' message"
else
  _fail "zero remaining files must hard-fail; got rc=$rc, output: $out"
fi

# An empty glob (no candidate files at all) is the same failure.
EMPTY="$TMPROOT/empty"
mkdir -p "$EMPTY/hooks/tests"
out="$(list_hooks_py_tests "$EMPTY" 2>&1)"
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "discovery is broken, not clean"; then
  _pass "an empty glob hard-fails rather than returning an empty list"
else
  _fail "an empty glob must hard-fail; got rc=$rc, output: $out"
fi

# A named orphan that does not exist is a hard error, matching CI.
ORPH="$TMPROOT/orphan"
mkdir -p "$ORPH/bin/tests"
touch "$ORPH/bin/tests/test_something.sh"
out="$(list_bin_sh_tests "$ORPH" 2>&1)"
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "may have been renamed or moved"; then
  _pass "a missing named orphan hard-fails (rc=$rc), as bin-tests.yml does"
else
  _fail "a missing orphan must hard-fail; got rc=$rc, output: $out"
fi

# A quarantine arm naming a file that no longer exists is a hard error too:
# it excludes nothing, and it hides that the renamed file now runs unguarded.
QUAR="$TMPROOT/quarantine"
mkdir -p "$QUAR/hooks/tests"
touch "$QUAR/hooks/tests/test-alpha.js" "$QUAR/hooks/tests/test-wrap-acquire-lock.js"
out="$(list_hooks_js_tests "$QUAR" 2>&1)"
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "quarantine arm names a file that no longer exists"; then
  _pass "a quarantine arm naming a nonexistent file hard-fails (rc=$rc)"
else
  _fail "a stale quarantine arm must hard-fail; got rc=$rc, output: $out"
fi

# Output ordering is LC_ALL=C sorted, so a caller may partition on index.
SORTED="$TMPROOT/sorted"
mkdir -p "$SORTED/hooks/tests"
touch "$SORTED/hooks/tests/test-Zulu.js" "$SORTED/hooks/tests/test-alpha.js" "$SORTED/hooks/tests/test-Beta.js" \
      "$SORTED/hooks/tests/test-wrap-acquire-lock.js" "$SORTED/hooks/tests/test-wrap-release-lock.js"
out="$(list_hooks_js_tests "$SORTED" 2>&1)"
expected="hooks/tests/test-Beta.js
hooks/tests/test-Zulu.js
hooks/tests/test-alpha.js"
if [ "$out" = "$expected" ]; then
  _pass "output is LC_ALL=C sorted (uppercase before lowercase)"
else
  _fail "expected LC_ALL=C order, got:
$out"
fi

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
