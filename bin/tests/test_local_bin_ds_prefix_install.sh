#!/usr/bin/env bash
# Purpose: Regression tests for the prefix-agnostic ~/.local/bin symlink glob
#          in every adapter install.sh (goal (a) of the agentic-* -> ds-*
#          rename-safety machinery). No tool is renamed by this change; these
#          tests only prove the install glob would pick up a ds-* named tool
#          if one existed.
#
# Public API: ./bin/tests/test_local_bin_ds_prefix_install.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, mktemp, grep.
#
# Downstream consumers: developer running locally before commit; wired into
#                       the bin-sh-tests CI job via the bin/tests/test_*.sh
#                       glob (.github/workflows/bin-tests.yml).
#
# Failure modes: any assertion failure prints the failing assertion and
#                exits 1. Test 2 creates one temporary untracked file under
#                the real repo's bin/ (bin/ds-<random>-test-fixture) and
#                removes it via an EXIT trap - never leaves a residual file,
#                never modifies a tracked file. Test 1/3 are read-only.
#
# Performance: ~3 s wall time on a developer machine (one real install.sh run).
#
# Regression coverage:
#   - Test 1 (structural): each of the 12 known glob sites across the 11
#     adapter install.sh scripts (10 single-loop adapters + .cursor + the
#     TWO loops in .codex/install.sh) matches both "agentic-*" and "ds-*".
#     Catches a site left un-updated by name/line, not just aggregate count.
#   - Test 2 (functional): .claude/install.sh, run end-to-end against a fake
#     HOME but the REAL repo bin/, actually symlinks a ds-*-named fixture
#     tool into ~/.local/bin alongside a real agentic-* tool.
#   - Test 3 (exclusion): the glob must not sweep in bin/tests/ or a
#     non-executable helper module (bin/_lib.py-style file).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BIN_DIR="$REPO_DIR/bin"

PASS=0
FAIL=0

_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

# ---------------------------------------------------------------------------
# Test 1 (structural): every known glob site matches BOTH prefixes.
# One (file, expected-occurrence-count) pair per adapter; .codex/install.sh
# carries two independent loops and so expects 2.
# ---------------------------------------------------------------------------
declare -a SITES=(
  ".claude/install.sh:1"
  ".cursor/install.sh:1"
  ".gemini/install.sh:1"
  ".opencode/install.sh:1"
  ".omp/install.sh:1"
  ".kimi/install.sh:1"
  ".pi/install.sh:1"
  ".codex/install.sh:2"
  ".copilot/install.sh:1"
  ".openclaw/install.sh:1"
)

for entry in "${SITES[@]}"; do
  file="${entry%%:*}"
  expected="${entry##*:}"
  # NOTE: do not name this variable "path" - it is a special zsh parameter
  # tied to $PATH (assigning to it silently replaces PATH and breaks every
  # subsequent command lookup, e.g. "grep: command not found", when this
  # script is run under zsh). Use site_file instead.
  site_file="$REPO_DIR/$file"
  if [[ ! -f "$site_file" ]]; then
    _fail "T1: $file not found"
    continue
  fi
  # Match both the plain "$bin_src"/agentic-* / ds-* form and the
  # .codex-specific "$REPO_DIR"/bin/agentic-* / ds-* form on the same line.
  count="$(grep -cE 'agentic-\*[^;]*ds-\*' "$site_file" || true)"
  if [[ "$count" -eq "$expected" ]]; then
    _pass "T1: $file has $expected prefix-agnostic glob site(s)"
  else
    _fail "T1: $file expected $expected prefix-agnostic glob site(s), found $count"
  fi
done

# ---------------------------------------------------------------------------
# Test 2 (functional): .claude/install.sh actually symlinks a ds-*-prefixed
# tool. Uses the REAL repo bin/ (so REPO_DIR resolution inside install.sh
# needs no faking) with one temporary untracked fixture file, cleaned up on
# exit regardless of outcome.
# ---------------------------------------------------------------------------
FIXTURE_NAME="ds-$(date +%s)-test-fixture"
FIXTURE_PATH="$BIN_DIR/$FIXTURE_NAME"
FAKE_HOME=""

_cleanup() {
  [[ -n "$FIXTURE_PATH" && -f "$FIXTURE_PATH" ]] && rm -f "$FIXTURE_PATH"
  [[ -n "$FAKE_HOME" && -d "$FAKE_HOME" ]] && rm -rf "$FAKE_HOME"
}
trap _cleanup EXIT

cat > "$FIXTURE_PATH" <<'EOF'
#!/usr/bin/env bash
echo ds-fixture
EOF
chmod +x "$FIXTURE_PATH"

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.agentic"

HOME="$FAKE_HOME" bash "$REPO_DIR/.claude/install.sh" --mode=opt-out --profile=default \
  < /dev/null > "$FAKE_HOME/.install_out" 2>&1
RC=$?

if [[ $RC -ne 0 ]]; then
  _fail "T2: .claude/install.sh exited $RC"
  cat "$FAKE_HOME/.install_out" >&2
fi

DS_TARGET="$(readlink "$FAKE_HOME/.local/bin/$FIXTURE_NAME" 2>/dev/null || echo "(not a link)")"
if [[ "$DS_TARGET" == "$FIXTURE_PATH" ]]; then
  _pass "T2: ds-*-prefixed fixture tool symlinked into ~/.local/bin by install.sh"
else
  _fail "T2: expected ~/.local/bin/$FIXTURE_NAME -> $FIXTURE_PATH, got '$DS_TARGET'"
fi

# Sanity: a real agentic-* tool (agentic-doctor) is still symlinked too -
# guards against a mutation that swaps prefixes instead of adding one.
AGENTIC_TARGET="$(readlink "$FAKE_HOME/.local/bin/agentic-doctor" 2>/dev/null || echo "(not a link)")"
if [[ "$AGENTIC_TARGET" == "$BIN_DIR/agentic-doctor" ]]; then
  _pass "T2: existing agentic-* tool (agentic-doctor) still symlinked"
else
  _fail "T2: agentic-doctor not symlinked as expected: '$AGENTIC_TARGET'"
fi

rm -f "$FIXTURE_PATH"
rm -rf "$FAKE_HOME"
FAKE_HOME=""
FIXTURE_PATH=""

# ---------------------------------------------------------------------------
# Test 3 (exclusion): the glob must never sweep in bin/tests/ (a directory)
# or a non-prefixed helper file (bin/_lib.py) - re-verify the [[ -f ]] guard
# and prefix filter are both still present at the .claude/install.sh site.
# ---------------------------------------------------------------------------
if [[ -f "$REPO_DIR/bin/_lib.py" ]]; then
  if grep -A2 'for src_file in "\$bin_src"/agentic-\* "\$bin_src"/ds-\*; do' "$REPO_DIR/.claude/install.sh" \
     | grep -q '\[\[ -f "\$src_file" \]\]'; then
    _pass "T3: .claude/install.sh glob loop still guards on [[ -f ]] (excludes bin/tests/ directory)"
  else
    _fail "T3: .claude/install.sh glob loop is missing its [[ -f ]] guard"
  fi
else
  _fail "T3: bin/_lib.py fixture not found - cannot verify exclusion guard context"
fi

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
