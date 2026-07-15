#!/usr/bin/env bash
# Purpose: Regression tests for the AE_NON_INTERACTIVE truthiness gate in
#          scripts/lib/identity.sh (ae_noninteractive + ae_confirm). The TUI
#          and CI callers export numeric/boolean spellings (1/true/yes); every
#          spelling other than empty/0/false/no must count as non-interactive,
#          and ae_confirm must default to "no" without touching /dev/tty.
#
# Public API: ./bin/tests/test_identity_noninteractive.sh (exit 0 pass, 1 fail)
# Upstream deps: bash 3.2+. Hermetic: sources identity.sh in subshells only.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIB="$REPO_DIR/scripts/lib/identity.sh"
FAILS=0
pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1" >&2; FAILS=$((FAILS + 1)); }

echo "Test 1: ae_noninteractive truthiness table"
# AE_NON_INTERACTIVE=1 (the spelling install-tui exports historically) -> ON.
if (AE_NON_INTERACTIVE=1; source "$LIB"; ae_noninteractive); then
	pass "AE_NON_INTERACTIVE=1 -> non-interactive"
else
	fail "AE_NON_INTERACTIVE=1 not treated as non-interactive"
fi
# AE_NON_INTERACTIVE=0 -> OFF.
if (AE_NON_INTERACTIVE=0; source "$LIB"; ae_noninteractive); then
	fail "AE_NON_INTERACTIVE=0 treated as non-interactive"
else
	pass "AE_NON_INTERACTIVE=0 -> interactive"
fi

echo "Test 2: ae_confirm defaults to no under AE_NON_INTERACTIVE=1 (no tty read)"
# Must return non-zero (default no) immediately, without reading /dev/tty.
if (AE_NON_INTERACTIVE=1; source "$LIB"; ae_confirm "  Install foo? [y/N] " >/dev/null); then
	fail "ae_confirm returned yes under AE_NON_INTERACTIVE=1"
else
	pass "ae_confirm defaults to no under AE_NON_INTERACTIVE=1"
fi

echo
if [[ "$FAILS" -eq 0 ]]; then echo "ALL PASS"; exit 0; fi
echo "$FAILS assertion(s) FAILED" >&2
exit 1
