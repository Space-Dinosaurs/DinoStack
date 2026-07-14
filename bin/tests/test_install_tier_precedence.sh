#!/usr/bin/env bash
# Purpose: Regression tests for .claude/install.sh tier/profile resolution
#          precedence (PR #422 review). Asserts:
#            - fresh install with no flags persists tier=minimal
#            - an explicit --profile on a machine with a persisted tier wins
#              over the stored tier (documented "CLI flag overrides all")
#            - reinstall with no flags keeps the stored tier
#            - the persisted (profile, tier) pair is always consistent per the
#              tier->profile mapping, so it can never mismatch
#
# Public API: ./bin/tests/test_install_tier_precedence.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, python3, mktemp. Runs the installer with a sandboxed
#                HOME and --config-dir so the real user config is never touched,
#                and an ambient GIT_DIR pointed at a throwaway repo so the
#                installer's pre-commit hook install cannot re-point the real
#                checkout's .git/hooks/pre-commit.
#
# Failure modes: any failing assertion prints and exits 1. Fully hermetic: all
#                writes land under a throwaway HOME/config dir and the sandboxed
#                GIT_DIR; stdin is /dev/null so the fresh-install skill_auto_load
#                prompt cannot block.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAILS=0
pass() { echo "  ok: $1"; }
fail() {
	echo "  FAIL: $1" >&2
	FAILS=$((FAILS + 1))
}

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
export HOME="$SANDBOX/home"
mkdir -p "$HOME"
CFG="$SANDBOX/cfg"
mkdir -p "$CFG"
CONFIG_JSON="$CFG/agentic-engineering.json"

# Hermetic git isolation: install.sh sources scripts/lib/precommit.sh and calls
# install_precommit_hook "$REPO_DIR", which resolves the hooks dir via
# `git -C "$REPO_DIR" rev-parse --git-path hooks` and symlinks pre-commit into
# it. Left alone that re-points the REAL checkout's .git/hooks/pre-commit. An
# ambient absolute GIT_DIR overrides the `git -C` target, so every git call in
# the installer resolves against this throwaway repo instead - the pre-commit
# symlink lands under SANDBOX and the real repo is never touched.
FAKE_REPO="$SANDBOX/fake-repo"
git init -q "$FAKE_REPO"
export GIT_DIR="$FAKE_REPO/.git"

read_key() {
	ae_key="$1"
	python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],""))' "$CONFIG_JSON" "$ae_key"
}

run_install() {
	# </dev/null detaches the child from this terminal: install.sh's fresh-install
	# skill_auto_load prompt opens /dev/tty directly, and without this the test
	# blocks on it interactively. With no tty the open() raises OSError and the
	# installer defaults skill_auto_load to false - the intended non-interactive path.
	bash "$REPO_DIR/.claude/install.sh" \
		--config-dir="$CFG" --no-identity --mode=opt-out "$@" \
		</dev/null >"$SANDBOX/out.log" 2>&1 || true
}

# The tier->profile mapping the installer must keep consistent.
assert_pair_consistent() {
	local ctx="$1" tier profile expected
	tier="$(read_key tier)"
	profile="$(read_key profile)"
	case "$tier" in
	minimal) expected="relaxed" ;;
	medium) expected="default" ;;
	full) expected="strict" ;;
	*)
		fail "$ctx: unexpected tier '$tier'"
		return
		;;
	esac
	[[ "$profile" == "$expected" ]] &&
		pass "$ctx: (profile=$profile, tier=$tier) pair consistent" ||
		fail "$ctx: mismatched pair profile=$profile tier=$tier (expected profile=$expected)"
}

# ---------------------------------------------------------------------------
# Test 1: fresh install, no flags -> tier=minimal persisted
# ---------------------------------------------------------------------------
run_install
[[ "$(read_key tier)" == "minimal" ]] &&
	pass "fresh install defaults to tier=minimal" ||
	fail "fresh install did not persist tier=minimal (got '$(read_key tier)')"
assert_pair_consistent "fresh install"

# ---------------------------------------------------------------------------
# Test 2: persist tier=full, then reinstall with --profile=relaxed.
# The profile flag must win over the stored tier -> tier becomes minimal.
# ---------------------------------------------------------------------------
run_install --tier=full
[[ "$(read_key tier)" == "full" ]] &&
	pass "--tier=full persisted" ||
	fail "--tier=full not persisted (got '$(read_key tier)')"

run_install --profile=relaxed
[[ "$(read_key tier)" == "minimal" ]] &&
	pass "--profile=relaxed overrides stored tier=full -> minimal" ||
	fail "--profile flag ignored: tier is '$(read_key tier)', expected minimal"
grep -q "derived from --profile=relaxed" "$SANDBOX/out.log" &&
	pass "echo names --profile flag as the winning source" ||
	fail "installer did not echo profile flag as source"
assert_pair_consistent "after --profile override"

# ---------------------------------------------------------------------------
# Test 3: reinstall with no flags keeps the stored tier (now minimal)
# ---------------------------------------------------------------------------
run_install --tier=medium
[[ "$(read_key tier)" == "medium" ]] || fail "setup: --tier=medium not persisted"
run_install
[[ "$(read_key tier)" == "medium" ]] &&
	pass "reinstall with no flags keeps stored tier=medium" ||
	fail "reinstall clobbered stored tier (got '$(read_key tier)')"
assert_pair_consistent "reinstall no flags"

# ---------------------------------------------------------------------------
# Test 4: --tier flag beats --profile flag when both are passed
# ---------------------------------------------------------------------------
run_install --tier=full --profile=relaxed
[[ "$(read_key tier)" == "full" ]] &&
	pass "--tier beats --profile when both passed" ||
	fail "--tier did not win over --profile (got '$(read_key tier)')"
assert_pair_consistent "--tier + --profile"

if [[ "$FAILS" -gt 0 ]]; then
	echo "FAILED: $FAILS assertion(s)"
	exit 1
fi
echo "All install-tier-precedence tests passed."
