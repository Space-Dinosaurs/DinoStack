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
#                the real repo's bin/ (bin/ds-<unique>-test-fixture) and
#                removes it via an EXIT trap - never leaves a residual file
#                itself, but it runs the REAL .claude/uninstall.sh against
#                the live repo tree with only HOME faked: that uninstaller
#                touches $HOME/.claude/settings.json, $HOME/.claude/CLAUDE.md,
#                and $HOME/.agentic/hooks-snapshot, all scoped under the
#                faked HOME - but it ALSO calls uninstall_precommit_hook,
#                which resolves the git hooks directory via
#                `git rev-parse --git-path hooks` relative to the REAL
#                REPO_DIR, entirely independent of $HOME faking. Left
#                unguarded, that call would remove THIS checkout's real
#                <repo>/.git/hooks/pre-commit (or, from inside a linked
#                worktree, the common repo's hooks dir) and never restore
#                it. Test 2 saves the real pre-commit hook via
#                bin/tests/lib/precommit-hook-guard.sh before invoking
#                uninstall.sh and restores it unconditionally in the EXIT
#                trap, so this is the one real effect outside the faked
#                HOME and it is undone on every exit path (normal, failure,
#                or signal). Test 2 is NOT read-only with respect to the
#                faked HOME or the live pre-commit hook slot (both are
#                exercised and restored); Test 1 is read-only.
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
#     symlink, and leaves a foreign (non-repo) symlink untouched - and the
#     real pre-commit hook this run touches along the way survives byte-
#     for-byte (or symlink-target-for-symlink-target) unchanged afterward.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BIN_DIR="$REPO_DIR/bin"

# shellcheck source=bin/tests/lib/precommit-hook-guard.sh
. "$REPO_DIR/bin/tests/lib/precommit-hook-guard.sh"

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
# file, cleaned up on exit regardless of outcome. The real pre-commit hook
# slot this run also touches (see header) is saved before the run and
# restored in the same EXIT trap - see bin/tests/lib/precommit-hook-guard.sh.
# ---------------------------------------------------------------------------
# FIXTURE_NAME must be genuinely unique, not just second-resolution: two
# runs starting in the same wall-clock second (e.g. two developer machines,
# or a fast CI matrix) would otherwise collide on the same bin/ file, and
# each run's EXIT trap would then delete the OTHER run's still-in-use
# fixture from the real repo's bin/. $$ (this process's PID) plus a
# mktemp-derived suffix rules that out.
FIXTURE_NAME="ds-$(date +%s)-$$-$(mktemp -u XXXXXX)-test-fixture"
FIXTURE_PATH="$BIN_DIR/$FIXTURE_NAME"
FAKE_HOME=""

_cleanup() {
  [[ -n "$FIXTURE_PATH" && -f "$FIXTURE_PATH" ]] && rm -f "$FIXTURE_PATH"
  [[ -n "$FAKE_HOME" && -d "$FAKE_HOME" ]] && rm -rf "$FAKE_HOME"
  precommit_hook_guard_restore
}
trap _cleanup EXIT INT TERM

cat > "$FIXTURE_PATH" <<'EOF'
#!/usr/bin/env bash
echo ds-fixture
EOF
chmod +x "$FIXTURE_PATH"

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.agentic" "$FAKE_HOME/.local/bin" "$FAKE_HOME/external"

# Read-only snapshot of the real pre-commit hook slot's current state, used
# only to assert (below, after uninstall.sh runs and the guard restores it)
# that it survives this test byte-for-byte / target-for-target. Independent
# of precommit_hook_guard_save's own internal state - this is the assertion
# side, the guard call below is the protection side.
_resolve_precommit_state() {
  local hooks_dir
  if ! hooks_dir="$(git -C "$REPO_DIR" rev-parse --git-path hooks 2>/dev/null)" || [[ -z "$hooks_dir" ]]; then
    echo "(unresolved)"
    return
  fi
  case "$hooks_dir" in
    /*) : ;;
    *) hooks_dir="$REPO_DIR/$hooks_dir" ;;
  esac
  local hook="$hooks_dir/pre-commit"
  if [[ -L "$hook" ]]; then
    readlink "$hook"
  elif [[ -e "$hook" ]]; then
    # Hash the content, not just presence - a regular-file hook that changed
    # content but stayed a regular file must not read as "unchanged".
    if command -v sha256sum >/dev/null 2>&1; then
      echo "(regular file: $(sha256sum "$hook" | awk '{print $1}'))"
    else
      echo "(regular file: $(shasum -a 256 "$hook" | awk '{print $1}'))"
    fi
  else
    echo "(absent)"
  fi
}

EXPECTED_PRECOMMIT_STATE="$(_resolve_precommit_state)"
precommit_hook_guard_save "$REPO_DIR"

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

# Restore the real pre-commit hook slot NOW (not just in the EXIT trap) so
# the assertion below runs with the live checkout already back to normal,
# and so the window during which the real hook is absent/altered is as
# short as possible. precommit_hook_guard_restore is idempotent, so the
# EXIT trap's later call is a harmless no-op.
precommit_hook_guard_restore

ACTUAL_PRECOMMIT_STATE="$(_resolve_precommit_state)"
if [[ "$ACTUAL_PRECOMMIT_STATE" == "$EXPECTED_PRECOMMIT_STATE" ]]; then
  _pass "T2: real pre-commit hook slot restored to its pre-test state ($EXPECTED_PRECOMMIT_STATE)"
else
  _fail "T2: real pre-commit hook slot NOT restored - expected '$EXPECTED_PRECOMMIT_STATE', got '$ACTUAL_PRECOMMIT_STATE'"
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
