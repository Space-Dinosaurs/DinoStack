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
#               (--tier/--non-interactive/--with-*/--permissions only where
#               supported, --mode everywhere, --config-dir per profile).
#            3. The plan summary echoes the selected adapters and the run
#               reports success (exit 0).
#            4. `skip` on the team/profile/tools/mcps screens suppresses those
#               code paths and maps to --no-tools/--no-mcp/--permissions=skip.
#            5. Team assignments become `configure --default-harness / --assign`
#               and tenant profiles fan out one install per (adapter, tenant)
#               with a composed --config-dir.
#            6. The composed claude command always carries --non-interactive so
#               no adapter can prompt after "Proceed"; codex (which does not
#               advertise --non-interactive) never receives it.
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
# Answer order: harnesses mode tier team profiles tools mcps permissions confirm.
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
# bash 3.2 + set -u: a bare "${SELECTED[*]}" join crashes when the multiselect
# returns zero selections (user confirms empty / presses q). Guard the idiom:
# every SELECTED[*] join must carry the '-' default. Repro of the raw trap:
#   /bin/bash -uc 'SELECTED=(); : "${SELECTED[*]}"'   (fails on 3.2)
if grep -n '"${SELECTED\[\*\]}"' "$TUI" >/dev/null; then
	fail "bare \"\${SELECTED[*]}\" join found (crashes empty on bash 3.2 -u)"
else
	pass "no bare \"\${SELECTED[*]}\" joins (empty-safe on bash 3.2)"
fi

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
# claude advertises --tier/--mode/--dormant/--non-interactive/--with-*/--permissions;
# codex advertises --mode/--dormant only (no --tier, no --non-interactive).
# ---------------------------------------------------------------------------
echo "Test 2: scripted flag composition"
run_tui "claude codex" "dormant" "minimal" "skip" "skip" "skip" "skip" "skip" "yes"
[[ "$RC" -eq 0 ]] && pass "exit 0 on success" || fail "expected exit 0, got $RC"
has "DRY_RUN: bash $REPO_DIR/.claude/install.sh --tier=minimal --mode=opt-in --dormant --non-interactive --no-tools --no-mcp --permissions=skip" "$OUT"
has "DRY_RUN: bash $REPO_DIR/.codex/install.sh --mode=opt-in --dormant" "$OUT"
# codex has no --tier / --non-interactive support -> must not carry those flags.
hasnt ".codex/install.sh --tier" "$OUT"
hasnt ".codex/install.sh --non-interactive" "$OUT"
# summary lists the selected adapters and the new screens.
has "- claude" "$OUT"
has "- codex" "$OUT"
has "tools=skip" "$OUT"
has "mcps=skip" "$OUT"
has "permissions=skip" "$OUT"
has "succeeded" "$OUT"

# ---------------------------------------------------------------------------
# Test 3: `skip` on team + profile + tools + mcps screens suppresses those paths.
# ---------------------------------------------------------------------------
echo "Test 3: skip team + profiles + tools + mcps"
run_tui "claude" "dormant" "medium" "skip" "skip" "skip" "skip" "skip" "yes"
hasnt "TEAM:" "$OUT"
has "--tier=medium" "$OUT"
has "--no-tools" "$OUT"
has "--no-mcp" "$OUT"
has "--permissions=skip" "$OUT"

# ---------------------------------------------------------------------------
# Test 4: team assignments -> configure delegation line.
# default=<h> becomes --default-harness; role=harness becomes --assign.
# ---------------------------------------------------------------------------
echo "Test 4: team assign delegation"
run_tui "claude codex" "resident" "full" "default=claude;engineer=codex" "skip" "skip" "skip" "skip" "yes"
has "TEAM: $REPO_DIR/bin/agentic-team configure --non-interactive" "$OUT"
has "--default-harness claude" "$OUT"
has "--assign engineer=codex" "$OUT"
# resident maps to opt-out and is passed everywhere.
has ".claude/install.sh --tier=full --mode=opt-out --resident" "$OUT"
has ".codex/install.sh --mode=opt-out" "$OUT"

# ---------------------------------------------------------------------------
# Test 5: tenant profiles fan out one install per (adapter, tenant) with
# a composed --config-dir. Both claude and codex advertise --config-dir.
# ---------------------------------------------------------------------------
echo "Test 5: tenant profile fan-out"
run_tui "claude codex" "dormant" "minimal" "skip" "acme beta" "skip" "skip" "skip" "yes"
has ".claude/install.sh --tier=minimal --mode=opt-in --dormant --config-dir=$HOME/.claude-acme" "$OUT"
has ".claude/install.sh --tier=minimal --mode=opt-in --dormant --config-dir=$HOME/.claude-beta" "$OUT"
has ".codex/install.sh --mode=opt-in --dormant --config-dir=$HOME/.codex-acme" "$OUT"
has ".codex/install.sh --mode=opt-in --dormant --config-dir=$HOME/.codex-beta" "$OUT"

# ---------------------------------------------------------------------------
# Test 6: declining the final confirm cancels with no install lines.
# ---------------------------------------------------------------------------
echo "Test 6: decline confirm cancels"
run_tui "claude" "dormant" "minimal" "skip" "skip" "skip" "skip" "skip" "no"
hasnt "DRY_RUN: bash" "$OUT"
has "cancelled" "$OUT"

# ---------------------------------------------------------------------------
# Test 7: malformed harness labels in scripted mode are skipped, not executed.
# ---------------------------------------------------------------------------
echo "Test 7: malformed harness labels rejected in scripted mode"
run_tui "claude,../../../tmp/evil,codex" "dormant" "minimal" "skip" "skip" "skip" "skip" "skip" "yes"
[[ "$RC" -eq 0 ]] && pass "exit 0 on valid labels" || fail "expected exit 0, got $RC"
hasnt ".tmp/evil/install.sh" "$OUT"
# Exactly two adapters were selected (claude + codex); the evil label produced no DRY_RUN line.
count=$(printf '%s' "$OUT" | grep -c 'DRY_RUN: bash .*/install.sh' || true)
[[ "$count" -eq 2 ]] && pass "exactly 2 DRY_RUN install lines" || fail "expected 2 DRY_RUN lines, got $count"
has "DRY_RUN: bash $REPO_DIR/.claude/install.sh --tier=minimal --mode=opt-in --dormant" "$OUT"
has "DRY_RUN: bash $REPO_DIR/.codex/install.sh --mode=opt-in --dormant" "$OUT"
has "unknown harness label '../../../tmp/evil'" "$OUT"

# ---------------------------------------------------------------------------
# Test 8: affirmative tools/mcps/permissions compose to the explicit flags.
# Unknown tool/mcp labels are filtered; only the documented subset is emitted.
# ---------------------------------------------------------------------------
echo "Test 8: affirmative tools/mcps/permissions composition"
run_tui "claude" "resident" "full" "skip" "skip" "lc jira bogus" "chrome-devtools" "bypass" "yes"
has "DRY_RUN: bash $REPO_DIR/.claude/install.sh --tier=full --mode=opt-out --resident --non-interactive --with-tools=lc,jira --with-mcp=chrome-devtools --permissions=bypass" "$OUT"
hasnt "bogus" "$OUT"
has "tools=lc jira" "$OUT"
has "mcps=chrome-devtools" "$OUT"
has "permissions=bypass" "$OUT"

# ---------------------------------------------------------------------------
# Test 9: prompt-free guarantee. The claude command always carries
# --non-interactive (so ae_confirm/identity/skill/permissions/tools/MCP prompts
# cannot fire after "Proceed"); codex never receives it (not advertised).
# ---------------------------------------------------------------------------
echo "Test 9: prompt-free guarantee"
run_tui "claude codex" "dormant" "minimal" "skip" "skip" "skip" "skip" "skip" "yes"
has ".claude/install.sh --tier=minimal --mode=opt-in --dormant --non-interactive" "$OUT"
hasnt ".codex/install.sh --non-interactive" "$OUT"
# Every adapter gets an explicit --mode, so none can re-prompt "Choice [1]".
has ".claude/install.sh --tier=minimal --mode=opt-in" "$OUT"
has ".codex/install.sh --mode=opt-in" "$OUT"

# ---------------------------------------------------------------------------
# Test 10: legacy 6-line answer files (pre-tools format: harnesses mode tier
# team profiles confirm) still work. Line 6 is a yes/no token and the queue
# drains right after it -> treated as confirm; tools/mcps/permissions skip.
# ---------------------------------------------------------------------------
echo "Test 10: legacy 6-line answer file shim"
run_tui "claude" "dormant" "minimal" "skip" "skip" "yes"
[[ "$RC" -eq 0 ]] && pass "legacy file ending 'yes' exits 0" || fail "expected exit 0, got $RC"
has "DRY_RUN: bash $REPO_DIR/.claude/install.sh --tier=minimal --mode=opt-in --dormant --non-interactive --no-tools --no-mcp --permissions=skip" "$OUT"
has "tools=skip" "$OUT"
has "mcps=skip" "$OUT"
has "deprecated 6-line answer file" "$OUT"
# legacy file ending "no" cancels with the fall-through marker (exit 75).
run_tui "claude" "dormant" "minimal" "skip" "skip" "no"
[[ "$RC" -eq 75 ]] && pass "legacy file ending 'no' exits 75" || fail "expected exit 75, got $RC"
hasnt "DRY_RUN: bash" "$OUT"
has "cancelled" "$OUT"
# current 9-line file with tools answer "yes" must NOT trip the shim (queue
# not drained after the tools pop).
run_tui "claude" "dormant" "minimal" "skip" "skip" "yes" "skip" "skip" "yes"
[[ "$RC" -eq 0 ]] && pass "9-line file with tools=yes exits 0" || fail "expected exit 0, got $RC"
hasnt "deprecated 6-line answer file" "$OUT"

# ---------------------------------------------------------------------------
echo
if [[ "$FAILS" -eq 0 ]]; then
	echo "ALL PASS"
	exit 0
fi
echo "$FAILS assertion(s) FAILED" >&2
exit 1
