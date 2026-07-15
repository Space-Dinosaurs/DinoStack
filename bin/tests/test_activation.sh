#!/usr/bin/env bash
# Purpose: Hermetic fake-$HOME matrix for the dormant/resident install axis and
#          the /ds activation round-trip (Unit 11). Proves:
#            - dormant install writes the stub block with NO @-imports;
#            - resident install writes the legacy tier @-imports;
#            - --dormant / --resident flags and AE_DORMANCY env are honored;
#            - re-running the installer is idempotent (block replaced, not dup'd);
#            - agentic-ds activate/deactivate round-trips a scratch project.
#
# Public API: ./bin/tests/test_activation.sh  (exit 0 all-pass, 1 on any failure)
# Upstream deps: bash, mktemp, python3; .claude/install.sh; bin/agentic-ds;
#                scripts/lib/{stub,dormancy}.sh.
# Failure modes: any failing assertion increments FAILS; non-zero exit at end.
# Performance: two real .claude installs under a sandbox HOME; a few seconds.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAILS=0
pass() { echo "  ok: $1"; }
fail() {
	echo "  FAIL: $1" >&2
	FAILS=$((FAILS + 1))
}

cleanup() {
	chmod -R u+w "$SANDBOX" 2>/dev/null || true
	rm -rf "$SANDBOX"
}
trap cleanup EXIT

SANDBOX="$(mktemp -d)"
export HOME="$SANDBOX/home"
mkdir -p "$HOME"

# ---------------------------------------------------------------------------
# Test 1: dormant install -> stub block, NO @-imports
# ---------------------------------------------------------------------------
CFG1="$SANDBOX/dormant"
mkdir -p "$CFG1"
bash "$REPO_DIR/.claude/install.sh" --config-dir="$CFG1" --dormant \
	--no-identity --mode=opt-out --tier=minimal >/dev/null 2>&1 || true
md1="$CFG1/CLAUDE.md"
if [[ -f "$md1" ]]; then
	grep -q "agentic-engineering (dormant)" "$md1" && pass "dormant: stub heading present" || fail "dormant: stub heading missing"
	grep -q "@skills/agentic-engineering" "$md1" && fail "dormant: has @-import (should not)" || pass "dormant: no @-imports"
	grep -q "/ds activate" "$md1" && pass "dormant: activation instructions present" || fail "dormant: no activation instructions"
else
	fail "dormant: CLAUDE.md not written"
fi

# ---------------------------------------------------------------------------
# Test 2: resident install -> legacy tier @-imports
# ---------------------------------------------------------------------------
CFG2="$SANDBOX/resident"
mkdir -p "$CFG2"
bash "$REPO_DIR/.claude/install.sh" --config-dir="$CFG2" --resident \
	--no-identity --mode=opt-out --tier=medium >/dev/null 2>&1 || true
md2="$CFG2/CLAUDE.md"
if [[ -f "$md2" ]]; then
	grep -q "@skills/agentic-engineering/METHODOLOGY.md" "$md2" && pass "resident: methodology @-import present" || fail "resident: methodology @-import missing"
	grep -q "agentic-engineering (dormant)" "$md2" && fail "resident: has dormant stub (should not)" || pass "resident: no dormant stub"
else
	fail "resident: CLAUDE.md not written"
fi

# ---------------------------------------------------------------------------
# Test 3: AE_DORMANCY env override (dormant) with no flag
# ---------------------------------------------------------------------------
CFG3="$SANDBOX/envdormant"
mkdir -p "$CFG3"
AE_DORMANCY=dormant bash "$REPO_DIR/.claude/install.sh" --config-dir="$CFG3" \
	--no-identity --mode=opt-out --tier=minimal >/dev/null 2>&1 || true
md3="$CFG3/CLAUDE.md"
grep -q "agentic-engineering (dormant)" "$md3" 2>/dev/null && pass "env AE_DORMANCY=dormant honored" || fail "env AE_DORMANCY=dormant ignored"

# ---------------------------------------------------------------------------
# Test 4: non-interactive default (no flag, no env, no TTY) -> resident
# ---------------------------------------------------------------------------
CFG4="$SANDBOX/default"
mkdir -p "$CFG4"
bash "$REPO_DIR/.claude/install.sh" --config-dir="$CFG4" \
	--no-identity --mode=opt-out --tier=minimal </dev/null >/dev/null 2>&1 || true
md4="$CFG4/CLAUDE.md"
grep -q "agentic-engineering (dormant)" "$md4" 2>/dev/null && fail "default flipped to dormant (should be resident)" || pass "non-interactive default = resident"

# ---------------------------------------------------------------------------
# Test 5: idempotent re-run (dormant twice) -> exactly one managed block
# ---------------------------------------------------------------------------
bash "$REPO_DIR/.claude/install.sh" --config-dir="$CFG1" --dormant \
	--no-identity --mode=opt-out --tier=minimal >/dev/null 2>&1 || true
count="$(grep -c "BEGIN managed-by-agentic-engineering" "$md1" 2>/dev/null || echo 0)"
[[ "$count" == "1" ]] && pass "dormant re-run idempotent (1 managed block)" || fail "dormant re-run left $count managed blocks"

# ---------------------------------------------------------------------------
# Test 6: agentic-ds activate/deactivate round-trip in a scratch project
# ---------------------------------------------------------------------------
PROJ="$SANDBOX/proj"
mkdir -p "$PROJ"
DS="$REPO_DIR/bin/agentic-ds"
python3 "$DS" --cwd "$PROJ" activate --tier=medium >/dev/null 2>&1 || true
[[ -f "$PROJ/.agentic/active" ]] && pass "ds activate wrote .agentic/active" || fail "ds activate did not write active marker"
st="$(python3 "$DS" --cwd "$PROJ" status 2>/dev/null || true)"
echo "$st" | grep -qi "active" && pass "ds status reports active" || fail "ds status did not report active"
python3 "$DS" --cwd "$PROJ" deactivate >/dev/null 2>&1 || true
[[ -f "$PROJ/.agentic/dormant" ]] && pass "ds deactivate wrote tombstone" || fail "ds deactivate did not write tombstone"
[[ ! -f "$PROJ/.agentic/active" ]] && pass "ds deactivate removed active marker" || fail "ds deactivate left active marker"

# ---------------------------------------------------------------------------
# Test 7: symlink-class adapter (.codex) dormant stub file + uninstall removal
#   Codex has no --config-dir; it writes into $HOME/.codex, so use a dedicated
#   sandbox HOME to keep it hermetic.
# ---------------------------------------------------------------------------
CODEX_HOME="$SANDBOX/codexhome"
mkdir -p "$CODEX_HOME"
CODEX_AGENTS="$CODEX_HOME/.codex/AGENTS.md"

HOME="$CODEX_HOME" bash "$REPO_DIR/.codex/install.sh" --dormant \
	--no-identity --mode=opt-out </dev/null >/dev/null 2>&1 || true
if [[ -f "$CODEX_AGENTS" && ! -L "$CODEX_AGENTS" ]]; then
	pass "codex dormant: AGENTS.md is a real stub file (not symlink)"
else
	fail "codex dormant: AGENTS.md should be a real stub file"
fi
grep -q "agentic-engineering (dormant)" "$CODEX_AGENTS" 2>/dev/null && pass "codex dormant: stub body present" || fail "codex dormant: stub body missing"
cbytes="$(wc -c < "$CODEX_AGENTS" 2>/dev/null | tr -d ' ' || echo 99999)"
[[ "$cbytes" -le 2048 ]] && pass "codex dormant: stub within 2KB ($cbytes)" || fail "codex dormant: stub over budget ($cbytes)"

HOME="$CODEX_HOME" bash "$REPO_DIR/.codex/uninstall.sh" </dev/null >/dev/null 2>&1 || true
[[ ! -e "$CODEX_AGENTS" ]] && pass "codex uninstall: dormant stub removed" || fail "codex uninstall: dormant stub left behind"

# Resident install writes a symlink into the repo (not a stub file).
CODEX_HOME2="$SANDBOX/codexhome2"
mkdir -p "$CODEX_HOME2"
HOME="$CODEX_HOME2" bash "$REPO_DIR/.codex/install.sh" --resident \
	--no-identity --mode=opt-out </dev/null >/dev/null 2>&1 || true
[[ -L "$CODEX_HOME2/.codex/AGENTS.md" ]] && pass "codex resident: AGENTS.md is a symlink" || fail "codex resident: AGENTS.md should be a symlink"

if [[ "$FAILS" -gt 0 ]]; then
	echo "FAILED: $FAILS assertion(s)"
	exit 1
fi
echo "All activation matrix tests passed."
