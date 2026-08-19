#!/usr/bin/env bash
# Purpose: Regression guard for scripts/gate-provenance.sh (DS-182 Major 3).
#          Runs it against the real repo (not a scratch fixture - D1/D2/D3
#          read real .github/workflows/*.yml and module-manifest headers,
#          so a fixture would only prove the fixture's own shape) for the
#          six paths the DS-182 plan classifies by hand, asserting each
#          resolves to the documented outcome AND cites the rule (D1/D2/D3)
#          expected to fire. Also covers the usage-error path and a D2
#          instance (CHANGELOG.md) distinct from the D1/D3 paths above.
#
# Public API: ./bin/tests/test_gate_provenance.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, scripts/gate-provenance.sh, git (transitively, via
#                the script under test), the real .github/workflows/*.yml
#                and scripts/check-methodology-drift.sh module-manifest
#                header this suite's expectations were derived from - if
#                either drifts (a workflow's pathspec narrows, or the
#                methodology-drift script's manifest wording changes),
#                update this suite's expectations in the same commit.
#
# Downstream consumers: developer running locally before commit; CI (the
#                        bin-sh-tests job in .github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: gate script missing -> immediate FAIL. Any scenario's
#                observed exit code or output does not match the expected
#                shape -> FAIL naming the scenario and what was observed.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE_SCRIPT="$REPO_DIR/scripts/gate-provenance.sh"

if [[ ! -f "$GATE_SCRIPT" ]]; then
  echo "FAIL: $GATE_SCRIPT not found" >&2
  exit 1
fi

PASS=0
FAIL=0

_pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

# _assert_classification <path> <expected-prefix> <expected-rule-substring>
_assert_classification() {
  local target="$1" expected_prefix="$2" expected_rule="$3"
  local out rc
  out="$(cd "$REPO_DIR" && bash scripts/gate-provenance.sh "$target" 2>&1)"
  rc=$?

  if [[ $rc -eq 0 ]]; then
    _pass "gate-provenance.sh exits 0 for '$target'"
  else
    _fail "gate-provenance.sh exited $rc for '$target' (expected 0): $out"
  fi

  if [[ "$out" == "$expected_prefix:"* ]]; then
    _pass "'$target' classifies as $expected_prefix"
  else
    _fail "'$target' classified as [$out], expected to start with '$expected_prefix:'"
  fi

  if [[ -n "$expected_rule" ]]; then
    if echo "$out" | grep -qF "$expected_rule"; then
      _pass "'$target' cites the expected rule ($expected_rule)"
    else
      _fail "'$target' did not cite the expected rule ($expected_rule): $out"
    fi
  fi
}

# --- DERIVED via D1 (adapter-sync.yml's .claude/.codex pathspec) ---
_assert_classification ".codex/skill-compatibility.yml" "DERIVED" "D1:"
_assert_classification ".claude/skills/dinostack/SKILL.md" "DERIVED" "D1:"

# --- DERIVED via D1 (slides-sync.yml's docs/slides pathspec) ---
_assert_classification "docs/slides/foo.html" "DERIVED" "D1:"

# --- DERIVED via D3 (check-methodology-drift.sh's manifest "writes" line) ---
_assert_classification "scripts/.methodology-baseline.sha256" "DERIVED" "D3:"

# --- DERIVED via D2 (changelog-publish.yml's git add + git commit pair) ---
_assert_classification "CHANGELOG.md" "DERIVED" "D2:"

# --- AUTHORED (no rule fires) ---
_assert_classification "content/commands/ds-implement-ticket.md" "AUTHORED" ""
_assert_classification "content/templates/claude-managed-content.md" "AUTHORED" ""

# --- Usage error: wrong argument count exits 2 ---
usage_out="$(cd "$REPO_DIR" && bash scripts/gate-provenance.sh 2>&1)"
usage_rc=$?
if [[ $usage_rc -eq 2 ]]; then
  _pass "gate-provenance.sh with no args exits 2"
else
  _fail "gate-provenance.sh with no args exited $usage_rc (expected 2): $usage_out"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
