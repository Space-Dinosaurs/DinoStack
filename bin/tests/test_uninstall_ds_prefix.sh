#!/usr/bin/env bash
# Purpose: Regression tests for the prefix-agnostic ~/.local/bin symlink
#          removal glob in every adapter uninstall.sh (uninstall-side
#          counterpart of the install-side goal (a) rename-safety machinery
#          covered by test_local_bin_ds_prefix_install.sh). No tool is
#          renamed by this change; these tests only prove the uninstall glob
#          would remove a ds-* named tool's symlink if one existed.
#
# Public API: ./bin/tests/test_uninstall_ds_prefix.sh
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
#                removes it via an EXIT trap - never leaves a residual file
#                itself, but it runs the REAL .claude/uninstall.sh against
#                the live repo tree with only HOME faked: that uninstaller
#                also touches $HOME/.claude/settings.json,
#                $HOME/.claude/CLAUDE.md, and $HOME/.agentic/hooks-snapshot -
#                all scoped under the faked HOME, never the real one. Test
#                2 is NOT read-only with respect to the faked HOME; Test 1
#                is read-only.
#
# Performance: ~3 s wall time on a developer machine (one real uninstall.sh
#              run).
#
# Regression coverage:
#   - Test 1 (structural): each of the 10 known glob sites across the 10
#     adapter uninstall.sh scripts that manage bin/ symlinks (one loop each;
#     .hermes/uninstall.sh manages no bins and is excluded) matches both
#     "agentic-*" and "ds-*". Catches a site left un-updated by name/line,
#     not just aggregate count.
#   - Test 2 (functional): .claude/uninstall.sh, run end-to-end against a
#     fake HOME but the REAL repo bin/, actually removes a ds-*-named
#     fixture symlink from ~/.local/bin alongside a real agentic-* tool's
#     symlink, and leaves a foreign (non-repo) symlink untouched.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BIN_DIR="$REPO_DIR/bin"

PASS=0
FAIL=0

_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

# ---------------------------------------------------------------------------
# Test 1 (structural): every known uninstall glob site matches BOTH prefixes.
# One (file, expected-occurrence-count) pair per adapter; every adapter
# carries exactly one loop on the uninstall side (unlike install.sh, where
# .codex has two).
# ---------------------------------------------------------------------------
declare -a SITES=(
  ".claude/uninstall.sh"
  ".cursor/uninstall.sh"
  ".gemini/uninstall.sh"
  ".opencode/uninstall.sh"
  ".omp/uninstall.sh"
  ".kimi/uninstall.sh"
  ".pi/uninstall.sh"
  ".codex/uninstall.sh"
  ".copilot/uninstall.sh"
  ".openclaw/uninstall.sh"
)

for file in "${SITES[@]}"; do
  # NOTE: do not name this variable "path" - it is a special zsh parameter
  # tied to $PATH (assigning to it silently replaces PATH and breaks every
  # subsequent command lookup, e.g. "grep: command not found", when this
  # script is run under zsh). Use site_file instead.
  site_file="$REPO_DIR/$file"
  if [[ ! -f "$site_file" ]]; then
    _fail "T1: $file not found"
    continue
  fi
  # Match only the loop declaration itself, not the surrounding comment or
  # the "no ... entries found" message line - both of those also legitimately
  # contain "agentic-*" and "ds-*" as plain prose/output text and would
  # otherwise inflate the count.
  count="$(grep -cE 'for dst_file in .*agentic-\*.*ds-\*.*; do' "$site_file" || true)"
  if [[ "$count" -eq 1 ]]; then
    _pass "T1: $file has 1 prefix-agnostic glob site"
  else
    _fail "T1: $file expected 1 prefix-agnostic glob site, found $count"
  fi
done

# ---------------------------------------------------------------------------
# Test 2 (functional): .claude/uninstall.sh actually removes a ds-*-prefixed
# tool's symlink, an agentic-*-prefixed tool's symlink, and leaves a foreign
# (non-repo) symlink alone. Uses the REAL repo bin/ (so REPO_DIR resolution
# inside uninstall.sh needs no faking) with one temporary untracked fixture
# file, cleaned up on exit regardless of outcome.
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
mkdir -p "$FAKE_HOME/.agentic" "$FAKE_HOME/.local/bin" "$FAKE_HOME/external"

# Case A: ds-*-prefixed symlink pointing into the real repo bin/ - MUST be removed.
ln -sfn "$FIXTURE_PATH" "$FAKE_HOME/.local/bin/$FIXTURE_NAME"

# Case B: a real agentic-* tool's symlink pointing into the real repo bin/ -
# MUST also be removed (sanity - proves the fix widened the glob, not swapped it).
ln -sfn "$BIN_DIR/agentic-doctor" "$FAKE_HOME/.local/bin/agentic-doctor"

# Case C: a foreign symlink pointing OUTSIDE the repo - must NOT be removed.
printf 'external\n' > "$FAKE_HOME/external/thing"
ln -sfn "$FAKE_HOME/external/thing" "$FAKE_HOME/.local/bin/agentic-foreign"

HOME="$FAKE_HOME" bash "$REPO_DIR/.claude/uninstall.sh" \
  < /dev/null > "$FAKE_HOME/.uninstall_out" 2>&1
RC=$?

if [[ $RC -ne 0 ]]; then
  _fail "T2: .claude/uninstall.sh exited $RC"
  cat "$FAKE_HOME/.uninstall_out" >&2
fi

if [[ ! -e "$FAKE_HOME/.local/bin/$FIXTURE_NAME" && ! -L "$FAKE_HOME/.local/bin/$FIXTURE_NAME" ]]; then
  _pass "T2: ds-*-prefixed fixture symlink removed by uninstall.sh"
else
  _fail "T2: expected $FAKE_HOME/.local/bin/$FIXTURE_NAME to be removed, but it still exists"
fi

if [[ ! -e "$FAKE_HOME/.local/bin/agentic-doctor" && ! -L "$FAKE_HOME/.local/bin/agentic-doctor" ]]; then
  _pass "T2: existing agentic-* tool (agentic-doctor) symlink also removed"
else
  _fail "T2: agentic-doctor symlink should have been removed"
fi

if [[ -L "$FAKE_HOME/.local/bin/agentic-foreign" ]]; then
  _pass "T2: foreign (non-repo) symlink preserved"
else
  _fail "T2: foreign (non-repo) symlink should NOT have been removed"
fi

rm -f "$FIXTURE_PATH"
rm -rf "$FAKE_HOME"
FAKE_HOME=""
FIXTURE_PATH=""

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
