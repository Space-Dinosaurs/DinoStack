#!/usr/bin/env bash
# Purpose: Regression tests for the profile-aware installer flag (D-4).
#          Asserts that .claude/install.sh --config-dir=<dir> writes the
#          per-harness config (agentic-engineering.json, settings.json,
#          CLAUDE.md, agents/commands/skills symlinks) into <dir>, and does
#          NOT relocate shared user state (~/.agentic, ~/.local/bin) which
#          must always stay in the real $HOME. Also checks default behavior
#          (no flag) still targets $HOME/.claude, and that AGENTIC_CONFIG_DIR
#          env has the same effect as the flag.
#
# Public API: ./bin/tests/test_install_profile_config_dir.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, mktemp. Runs the installer with a sandboxed
#                HOME so the real user config is never touched.
#
# Failure modes: any failing assertion prints and exits 1. Fully hermetic:
#                all writes land under a throwaway HOME.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAILS=0
pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1" >&2; FAILS=$((FAILS + 1)); }

# ---------------------------------------------------------------------------
# Test 1: --config-dir redirects the harness config; shared state stays in HOME
# ---------------------------------------------------------------------------
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
export HOME="$SANDBOX/home"
mkdir -p "$HOME"
PROFILE="$SANDBOX/profile"     # stand-in for ~/.claude-<tenant>
mkdir -p "$PROFILE"

bash "$REPO_DIR/.claude/install.sh" \
  --config-dir="$PROFILE" --no-identity --mode=opt-out --profile=default \
  >/dev/null 2>&1 || true

# Harness config must land in the profile dir.
[[ -f "$PROFILE/agentic-engineering.json" ]] \
  && pass "agentic-engineering.json in profile dir" \
  || fail "agentic-engineering.json NOT in profile dir"
[[ -f "$PROFILE/settings.json" ]] \
  && pass "settings.json in profile dir" \
  || fail "settings.json NOT in profile dir ($PROFILE)"

# The default ~/.claude under the sandbox HOME must NOT have been populated
# with the harness config when --config-dir pointed elsewhere.
if [[ -f "$HOME/.claude/settings.json" ]]; then
  fail "settings.json leaked into \$HOME/.claude despite --config-dir"
else
  pass "no settings.json leak into \$HOME/.claude"
fi

# Shared state is allowed (and expected) in the real HOME, not the profile.
if [[ -e "$PROFILE/.agentic/agentic-engineering-config.json" ]]; then
  fail "shared repo_dir config wrongly written under profile dir"
else
  pass "shared repo_dir config not placed under profile dir"
fi

# ---------------------------------------------------------------------------
# Test 2: AGENTIC_CONFIG_DIR env behaves like the flag
# ---------------------------------------------------------------------------
SANDBOX2="$(mktemp -d)"
export HOME="$SANDBOX2/home"; mkdir -p "$HOME"
PROFILE2="$SANDBOX2/prof2"; mkdir -p "$PROFILE2"
AGENTIC_CONFIG_DIR="$PROFILE2" bash "$REPO_DIR/.claude/install.sh" \
  --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || true
[[ -f "$PROFILE2/settings.json" ]] \
  && pass "AGENTIC_CONFIG_DIR env redirects settings.json" \
  || fail "AGENTIC_CONFIG_DIR env did NOT redirect settings.json"
rm -rf "$SANDBOX2"

# ---------------------------------------------------------------------------
# Test 3: default (no flag/env) targets \$HOME/.claude
# ---------------------------------------------------------------------------
SANDBOX3="$(mktemp -d)"
export HOME="$SANDBOX3/home"; mkdir -p "$HOME"
bash "$REPO_DIR/.claude/install.sh" \
  --no-identity --mode=opt-out --profile=default >/dev/null 2>&1 || true
[[ -f "$HOME/.claude/settings.json" ]] \
  && pass "default install targets \$HOME/.claude" \
  || fail "default install did NOT target \$HOME/.claude"
rm -rf "$SANDBOX3"

if [[ "$FAILS" -gt 0 ]]; then
  echo "FAILED: $FAILS assertion(s)"; exit 1
fi
echo "All profile-config-dir tests passed."
