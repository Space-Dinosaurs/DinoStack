#!/usr/bin/env bash
# Purpose: Regression tests for the shell activation guard hooks/lib/activation.sh
#          (ae_is_active). Covers every activation layer, the fail-ACTIVE
#          contract, and the <10ms timing assertion from the plan (Unit 10, R3).
# Public API: bash hooks/tests/test_activation_guard.sh
#             Exits 0 on all pass, 1 on any failure. Hermetic: mktemp sandboxes
#             and a fake HOME so the real ~/.agentic is never touched.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$REPO_DIR/lib/activation.sh"

FAILS=0
pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1" >&2; FAILS=$((FAILS + 1)); }

# assert_active <label> <cwd>   -> expects rc 0 (active)
assert_active() { if ae_is_active "$2"; then pass "$1"; else fail "$1 (expected active)"; fi; }
# assert_dormant <label> <cwd>  -> expects rc 1 (dormant)
assert_dormant() { if ae_is_active "$2"; then fail "$1 (expected dormant)"; else pass "$1"; fi; }

# Layer 6: dormant (no marker).
D="$(mktemp -d)"
assert_dormant "no .agentic -> dormant" "$D"

# Layer 4: auto-detect.
mkdir -p "$D/.agentic"
assert_active "auto-detect .agentic dir -> active" "$D"

# Layer 3: tombstone overrides auto-detect.
: >"$D/.agentic/dormant"
assert_dormant "tombstone overrides auto-detect -> dormant" "$D"

# Layer 1: explicit active file overrides tombstone.
: >"$D/.agentic/active"
assert_active "active file overrides tombstone -> active" "$D"

# Layer 2: session file overrides tombstone.
D2="$(mktemp -d)"; mkdir -p "$D2/.agentic"
: >"$D2/.agentic/dormant"; : >"$D2/.agentic/active.session"
assert_active "active.session overrides tombstone -> active" "$D2"

# Layer 5: allowlist via fake HOME.
D3="$(mktemp -d)"   # no .agentic
FAKE_HOME="$(mktemp -d)"; mkdir -p "$FAKE_HOME/.agentic"
# Store the realpath so the guard's `cd && pwd -P` comparison matches on macOS.
(cd "$D3" && pwd -P) >"$FAKE_HOME/.agentic/activation.list"
OLD_HOME="$HOME"
export HOME="$FAKE_HOME"
assert_active "allowlisted cwd -> active" "$D3"
D4="$(mktemp -d)"
assert_dormant "non-listed cwd -> dormant" "$D4"
export HOME="$OLD_HOME"

# Fail-ACTIVE: indeterminate cwd (empty string).
assert_active "empty cwd -> fail-ACTIVE" ""

# Timing: <10ms/call on the hot (dormant) path.
DT="$(mktemp -d)"
N=100
start=$(python3 -c 'import time; print(time.perf_counter())')
for _ in $(seq "$N"); do ae_is_active "$DT" || true; done
end=$(python3 -c 'import time; print(time.perf_counter())')
per_ms=$(python3 -c "print(($end - $start)/$N*1000)")
# Shell forks are slower than in-process; assert a generous <10ms/call budget on
# the pure-stat path (the guard itself does only a few `[[ -e ]]` tests).
if python3 -c "import sys; sys.exit(0 if $per_ms < 10.0 else 1)"; then
  pass "dormant path <10ms/call (measured ${per_ms}ms)"
else
  fail "dormant path too slow (${per_ms}ms/call)"
fi

if [[ "$FAILS" -gt 0 ]]; then
  echo "" >&2; echo "$FAILS FAILED" >&2; exit 1
fi
echo ""; echo "ALL PASS"
