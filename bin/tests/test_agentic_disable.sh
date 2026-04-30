#!/usr/bin/env bash
# Purpose: Regression and smoke tests for bin/agentic-disable.
#
# Public API: ./bin/tests/test_agentic_disable.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3 (only to invoke the script under test),
#                grep, mktemp.
#
# Downstream consumers: developer running locally before commit; can be
#                       wired into CI.
#
# Failure modes: any test failure prints the failing assertion and exits 1.
#                Tests use isolated temp dirs; no global state mutated.
#                HOME is overridden per test to keep --global out of the
#                user's real ~/.claude.
#
# Performance: <1 s wall time on a developer machine.
#
# Regression coverage:
#   - Major (Skeptic Iter-N): both-markers + --force must NOT append a
#     duplicate opt-out, must remove opt-in, must print both messages,
#     and must exit 0.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DISABLE="$SCRIPT_DIR/agentic-disable"

if [[ ! -x "$DISABLE" ]]; then
  echo "FAIL: $DISABLE not executable" >&2
  exit 1
fi

PASS=0
FAIL=0

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

_pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

# Each test sets TMP itself, calls _setup, _invoke, then asserts.
_setup() {
  # $1 = AGENTS.md initial content, $2 = create_file ("yes"/"no")
  TMP="$(mktemp -d)"
  if [[ "$2" == "yes" ]]; then
    printf '%s' "$1" > "$TMP/AGENTS.md"
  fi
  mkdir -p "$TMP/home/.claude"
}

_invoke() {
  # All args passed to agentic-disable. Captures stdout/stderr to
  # $TMP/.out and exit code to $TMP/.exit.
  (cd "$TMP" && HOME="$TMP/home" python3 "$DISABLE" "$@") > "$TMP/.out" 2>&1
  echo "$?" > "$TMP/.exit"
}

# ---- Test 1: Regression - both markers + --force ----
_setup $'# Project\n\nagentic-engineering: opt-in\nagentic-engineering: opt-out\n' "yes"
_invoke --force
RC=$(cat "$TMP/.exit")
if [[ "$RC" != "0" ]]; then
  _fail "regression both-markers-force: expected exit 0, got $RC"
  cat "$TMP/.out" >&2
else
  optout_count=$(grep -c '^agentic-engineering: opt-out$' "$TMP/AGENTS.md" || true)
  optin_count=$(grep -c '^agentic-engineering: opt-in$' "$TMP/AGENTS.md" || true)
  if [[ "$optout_count" != "1" ]]; then
    _fail "regression both-markers-force: expected exactly 1 opt-out line, got $optout_count"
    cat "$TMP/AGENTS.md" >&2
  elif [[ "$optin_count" != "0" ]]; then
    _fail "regression both-markers-force: expected 0 opt-in lines, got $optin_count"
  elif ! grep -q "^--force: removed existing 'opt-in' marker" "$TMP/.out"; then
    _fail "regression both-markers-force: --force removal message missing"
    cat "$TMP/.out" >&2
  elif ! grep -q "already opted out" "$TMP/.out"; then
    _fail "regression both-markers-force: 'already opted out' message missing"
    cat "$TMP/.out" >&2
  else
    _pass "regression both-markers-force: opt-in removed, single opt-out preserved, both messages printed, exit 0"
  fi
fi
rm -rf "$TMP"

# ---- Test 2: Smoke - fresh create (no AGENTS.md) ----
_setup "" "no"
_invoke
RC=$(cat "$TMP/.exit")
if [[ "$RC" != "0" ]]; then
  _fail "fresh-create: expected exit 0, got $RC"
elif [[ ! -f "$TMP/AGENTS.md" ]]; then
  _fail "fresh-create: AGENTS.md not created"
elif ! grep -q '^agentic-engineering: opt-out$' "$TMP/AGENTS.md"; then
  _fail "fresh-create: opt-out marker missing"
else
  _pass "fresh-create: AGENTS.md created with opt-out marker"
fi
rm -rf "$TMP"

# ---- Test 3: Smoke - idempotent (opt-out already present, no force) ----
_setup $'# Project\n\nagentic-engineering: opt-out\n' "yes"
_invoke
RC=$(cat "$TMP/.exit")
optout_count=$(grep -c '^agentic-engineering: opt-out$' "$TMP/AGENTS.md" || true)
if [[ "$RC" != "0" ]]; then
  _fail "idempotent: expected exit 0, got $RC"
elif [[ "$optout_count" != "1" ]]; then
  _fail "idempotent: expected 1 opt-out line, got $optout_count"
else
  _pass "idempotent: no duplicate appended, exit 0"
fi
rm -rf "$TMP"

# ---- Test 4: Smoke - opt-in conflict without --force -> exit 2 ----
_setup $'# Project\n\nagentic-engineering: opt-in\n' "yes"
_invoke
RC=$(cat "$TMP/.exit")
if [[ "$RC" != "2" ]]; then
  _fail "optin-no-force: expected exit 2, got $RC"
elif ! grep -q '^agentic-engineering: opt-in$' "$TMP/AGENTS.md"; then
  _fail "optin-no-force: opt-in line was removed (must not be touched without --force)"
else
  _pass "optin-no-force: exit 2, opt-in untouched"
fi
rm -rf "$TMP"

# ---- Test 5: Smoke - opt-in conflict with --force, no existing opt-out ----
_setup $'# Project\n\nagentic-engineering: opt-in\n' "yes"
_invoke --force
RC=$(cat "$TMP/.exit")
optout_count=$(grep -c '^agentic-engineering: opt-out$' "$TMP/AGENTS.md" || true)
optin_count=$(grep -c '^agentic-engineering: opt-in$' "$TMP/AGENTS.md" || true)
if [[ "$RC" != "0" ]]; then
  _fail "optin-with-force: expected exit 0, got $RC"
elif [[ "$optout_count" != "1" ]]; then
  _fail "optin-with-force: expected 1 opt-out line, got $optout_count"
elif [[ "$optin_count" != "0" ]]; then
  _fail "optin-with-force: expected 0 opt-in lines, got $optin_count"
else
  _pass "optin-with-force: opt-in removed, opt-out appended, exit 0"
fi
rm -rf "$TMP"

echo
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
