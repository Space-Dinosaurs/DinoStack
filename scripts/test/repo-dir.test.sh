#!/usr/bin/env bash
# scripts/test/repo-dir.test.sh
# Unit tests for scripts/lib/repo-dir.sh
#
# Usage: bash scripts/test/repo-dir.test.sh
# Must pass with zero failures. Uses a temp HOME to avoid touching real ~/.agentic.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LIB_DIR="$(cd "$SCRIPT_DIR/../lib" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"

# Source the lib under test (must have no top-level side effects)
# shellcheck source=../lib/repo-dir.sh
source "$LIB_DIR/repo-dir.sh"

# ---------------------------------------------------------------------------
# Minimal test harness
# ---------------------------------------------------------------------------
_pass=0
_fail=0

pass() { echo "  PASS: $*"; (( _pass++ )) || true; }
fail() { echo "  FAIL: $*"; (( _fail++ )) || true; }

assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    pass "$desc"
  else
    fail "$desc (expected='$expected' got='$actual')"
  fi
}

assert_rc() {
  local desc="$1" expected_rc="$2"
  shift 2
  local actual_rc=0
  "$@" || actual_rc=$?
  if [[ "$actual_rc" -eq "$expected_rc" ]]; then
    pass "$desc"
  else
    fail "$desc (expected rc=$expected_rc got rc=$actual_rc)"
  fi
}

# ---------------------------------------------------------------------------
# (a) validate_repo_dir
# ---------------------------------------------------------------------------
echo ""
echo "=== (a) validate_repo_dir ==="

assert_rc "valid git repo (repo root)" 0 validate_repo_dir "$REPO_ROOT"
assert_rc "non-git dir (/tmp) returns non-0" 1 validate_repo_dir "/tmp"
# note: validate_repo_dir normalises all non-0 git exit codes to 1
assert_rc "nonexistent path returns non-0" 1 validate_repo_dir "/nonexistent/path/that/does/not/exist"

# ---------------------------------------------------------------------------
# (b) resolve_repo_dir with temp HOME + temp config
# ---------------------------------------------------------------------------
echo ""
echo "=== (b) resolve_repo_dir ==="

ORIG_HOME="$HOME"
TEMP_HOME="$(mktemp -d)"
trap 'rm -rf "$TEMP_HOME"' EXIT

# b1: config points at the real repo root (valid git repo)
mkdir -p "$TEMP_HOME/.agentic"
printf '{"repo_dir": "%s"}\n' "$REPO_ROOT" > "$TEMP_HOME/.agentic/agentic-engineering-config.json"

# resolve_repo_dir runs in the same shell so AE_REPO_DIR is visible after the call
AE_REPO_DIR=""
HOME="$TEMP_HOME" resolve_repo_dir --quiet
assert_eq "AE_REPO_DIR set from config" "$REPO_ROOT" "$AE_REPO_DIR"

# also verify the rc is 0 in an isolated subshell
assert_rc "resolve_repo_dir returns 0 for valid repo (config-driven)" 0 \
  env HOME="$TEMP_HOME" bash -c "
    source '$LIB_DIR/repo-dir.sh'
    resolve_repo_dir --quiet
  "

# b2: config missing - falls back to \$HOME/DinoStack which does not exist; returns 1
rm "$TEMP_HOME/.agentic/agentic-engineering-config.json"
FALLBACK_RC=0
env HOME="$TEMP_HOME" bash -c "
  source '$LIB_DIR/repo-dir.sh'
  resolve_repo_dir --quiet
" || FALLBACK_RC=$?
assert_eq "resolve_repo_dir returns 1 when fallback is not a git repo" "1" "$FALLBACK_RC"

# b3: config present but repo_dir missing - should also fall back
printf '{"other_key": "irrelevant"}\n' > "$TEMP_HOME/.agentic/agentic-engineering-config.json"
MISSING_KEY_RC=0
env HOME="$TEMP_HOME" bash -c "
  source '$LIB_DIR/repo-dir.sh'
  resolve_repo_dir --quiet
" || MISSING_KEY_RC=$?
assert_eq "resolve_repo_dir returns 1 when config has no repo_dir key" "1" "$MISSING_KEY_RC"

# b4: config points at an invalid path - falls back, returns 1
printf '{"repo_dir": "/nonexistent/path"}\n' > "$TEMP_HOME/.agentic/agentic-engineering-config.json"
INVALID_PATH_RC=0
env HOME="$TEMP_HOME" bash -c "
  source '$LIB_DIR/repo-dir.sh'
  resolve_repo_dir --quiet
" || INVALID_PATH_RC=$?
assert_eq "resolve_repo_dir returns 1 when config path is not a git repo" "1" "$INVALID_PATH_RC"

HOME="$ORIG_HOME"

# ---------------------------------------------------------------------------
# (c) assert_canonical_match
# ---------------------------------------------------------------------------
echo ""
echo "=== (c) assert_canonical_match ==="

# Set AE_REPO_DIR to the real repo root for these tests
AE_REPO_DIR="$REPO_ROOT"

assert_rc "assert_canonical_match returns 0 for matching paths" 0 \
  assert_canonical_match "$REPO_ROOT"

# Test with a symlinked path that resolves to the same canonical dir
MATCH_RC=0
assert_canonical_match "$REPO_ROOT/" || MATCH_RC=$?
assert_eq "assert_canonical_match returns 0 for trailing-slash variant" "0" "$MATCH_RC"

# Mismatch: session root differs from AE_REPO_DIR
MISMATCH_RC=0
assert_canonical_match "/tmp" 2>/dev/null || MISMATCH_RC=$?
assert_eq "assert_canonical_match returns 2 for mismatched paths" "2" "$MISMATCH_RC"

# Mismatch: nonexistent session root (cd fails - session_real is empty)
NONEXIST_RC=0
assert_canonical_match "/nonexistent/path" 2>/dev/null || NONEXIST_RC=$?
assert_eq "assert_canonical_match returns 2 for nonexistent session root" "2" "$NONEXIST_RC"

# ---------------------------------------------------------------------------
# (d) verify sourcing has no top-level side effects
# ---------------------------------------------------------------------------
echo ""
echo "=== (d) no top-level side effects ==="

SIDE_EFFECT_OUT="$(bash -c "
  set -euo pipefail
  source '$LIB_DIR/repo-dir.sh'
  echo 'sourced-ok'
")"
assert_eq "sourcing repo-dir.sh under set -euo pipefail produces no output" "sourced-ok" "$SIDE_EFFECT_OUT"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $_pass passed, $_fail failed"
if [[ "$_fail" -gt 0 ]]; then
  exit 1
fi
echo "All tests passed."
