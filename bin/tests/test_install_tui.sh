#!/usr/bin/env bash
# Purpose: Regression tests for scripts/install-tui.sh, the pure-bash TUI
#          installer. Drives the same code paths the interactive menus use,
#          but through the scripted-answer channel (INSTALL_TUI_SCRIPT) and
#          DRY_RUN=1 so nothing is actually installed. Asserts:
#            1. Non-TTY invocation with no scripted input falls through
#               silently with the fall-through marker exit code (75), so a
#               curl|bash caller can continue its flag-based flow.
#            2. Scripted answers compose the correct per-adapter install.sh
#               command lines, probing each target for the flags it advertises
#               (--tier only where supported, --config-dir per profile).
#            3. The plan summary echoes the selected adapters and the run
#               reports success (exit 0).
#            4. `skip` on the team/profile screens suppresses the TEAM: line
#               and per-tenant fan-out.
#            5. Team assignments become `configure --default-harness / --assign`
#               and tenant profiles fan out one install per (adapter, tenant)
#               with a composed --config-dir.
#
# Public API: ./bin/tests/test_install_tui.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash (3.2+ compatible target), mktemp. Hermetic: DRY_RUN=1
#                means no adapter install.sh is ever executed, and the
#                sandboxed HOME keeps profile-dir math off the real user config.
#
# Failure modes: any failing assertion prints and exits 1.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TUI="$REPO_DIR/scripts/install-tui.sh"
FAILS=0
pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1" >&2; FAILS=$((FAILS + 1)); }

# Assert $2 (haystack) contains $1 (needle).
has() {
	case "$2" in
	*"$1"*) pass "contains: $1" ;;
	*) fail "missing: $1" ;;
	esac
}
# Assert $2 does NOT contain $1.
hasnt() {
	case "$2" in
	*"$1"*) fail "unexpected: $1" ;;
	*) pass "absent: $1" ;;
	esac
}

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
export HOME="$SANDBOX/home"
mkdir -p "$HOME"

# Run the TUI in scripted+dry-run mode with the given answer lines (one per arg).
# Captures combined stdout/stderr; records exit code in $RC.
run_tui() {
	local ans="$SANDBOX/answers"
	: >"$ans"
	local line
	for line in "$@"; do printf '%s\n' "$line" >>"$ans"; done
	set +e
	OUT="$(INSTALL_TUI_SCRIPT="$ans" DRY_RUN=1 bash "$TUI" 2>&1)"
	RC=$?
	set -e
}

# ---------------------------------------------------------------------------
# Test 0: syntax is valid bash.
# ---------------------------------------------------------------------------
echo "Test 0: syntax"
if bash -n "$TUI" 2>/dev/null; then pass "bash -n clean"; else fail "bash -n failed"; fi

# ---------------------------------------------------------------------------
# Test 1: non-TTY, no scripted input -> silent fall-through (exit 75).
# stdin is /dev/null (not a TTY), INSTALL_TUI_SCRIPT unset, stdout captured
# (not a TTY) -> should_run() is false -> exit 75 with no plan output.
# ---------------------------------------------------------------------------
echo "Test 1: non-TTY fall-through"
set +e
FT_OUT="$(</dev/null bash "$TUI" 2>&1)"
FT_RC=$?
set -e
[[ "$FT_RC" -eq 75 ]] && pass "fall-through exit 75" || fail "expected exit 75, got $FT_RC"
hasnt "Install plan:" "$FT_OUT"

# ---------------------------------------------------------------------------
# Test 2: minimal scripted run -> composed flags + summary.
# claude advertises --tier (probed), codex does not; neither advertises
# --dormant yet, so no mode flag is composed.
# ---------------------------------------------------------------------------
echo "Test 2: scripted flag composition"
run_tui "claude codex" "dormant" "minimal" "skip" "skip" "yes"
[[ "$RC" -eq 0 ]] && pass "exit 0 on success" || fail "expected exit 0, got $RC"
has "DRY_RUN: bash $REPO_DIR/.claude/install.sh --tier=minimal" "$OUT"
has "DRY_RUN: bash $REPO_DIR/.codex/install.sh" "$OUT"
# codex has no --tier support -> must not carry the flag.
hasnt ".codex/install.sh --tier" "$OUT"
# no adapter advertises --dormant yet -> optimistic probe stays silent.
hasnt "--dormant" "$OUT"
# summary lists the selected adapters.
has "- claude" "$OUT"
has "- codex" "$OUT"
has "succeeded" "$OUT"

# ---------------------------------------------------------------------------
# Test 3: `skip` on team + profile screens suppresses those code paths.
# ---------------------------------------------------------------------------
echo "Test 3: skip team + profiles"
run_tui "claude" "dormant" "medium" "skip" "skip" "yes"
hasnt "TEAM:" "$OUT"
has "--tier=medium" "$OUT"

# ---------------------------------------------------------------------------
# Test 4: team assignments -> configure delegation line.
# default=<h> becomes --default-harness; role=harness becomes --assign.
# ---------------------------------------------------------------------------
echo "Test 4: team assign delegation"
run_tui "claude codex" "resident" "full" "default=claude;engineer=codex" "skip" "yes"
has "TEAM: $REPO_DIR/bin/agentic-team configure --non-interactive" "$OUT"
has "--default-harness claude" "$OUT"
has "--assign engineer=codex" "$OUT"

# ---------------------------------------------------------------------------
# Test 5: tenant profiles fan out one install per (adapter, tenant) with
# a composed --config-dir. Both claude and codex advertise --config-dir.
# ---------------------------------------------------------------------------
echo "Test 5: tenant profile fan-out"
run_tui "claude codex" "dormant" "minimal" "skip" "acme beta" "yes"
has ".claude/install.sh --tier=minimal --config-dir=$HOME/.claude-acme" "$OUT"
has ".claude/install.sh --tier=minimal --config-dir=$HOME/.claude-beta" "$OUT"
has ".codex/install.sh --config-dir=$HOME/.codex-acme" "$OUT"
has ".codex/install.sh --config-dir=$HOME/.codex-beta" "$OUT"

# ---------------------------------------------------------------------------
# Test 6: declining the final confirm cancels with no install lines.
# ---------------------------------------------------------------------------
echo "Test 6: decline confirm cancels"
run_tui "claude" "dormant" "minimal" "skip" "skip" "no"
hasnt "DRY_RUN: bash" "$OUT"
has "cancelled" "$OUT"

# ---------------------------------------------------------------------------
echo
if [[ "$FAILS" -eq 0 ]]; then
	echo "ALL PASS"
	exit 0
fi
echo "$FAILS assertion(s) FAILED" >&2
exit 1
