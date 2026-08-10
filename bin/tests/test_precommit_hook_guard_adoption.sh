#!/usr/bin/env bash
# Purpose: Regression verifier for the precommit-hook-guard adoption fix
#          (worktree-hijack sandbox escape: install_precommit_hook / the
#          _ae_is_ours() re-point rule silently rewrites the REAL,
#          worktree-shared .git/hooks/pre-commit symlink whenever an
#          unguarded install.sh runs, and the change is never undone if the
#          script exits before reaching a guard call placed too late).
#
#          This verifier does NOT run the full ~20-40s
#          bin/tests/test_hooks_snapshot_migration.sh end-to-end (that would
#          only prove the happy path, which was never the bug - the bug is
#          an early exit BEFORE the guard's save call). Instead it builds a
#          truncated copy of that file's ".claude" section, cut immediately
#          after the FIRST .claude/install.sh invocation and forced to
#          `exit 1` there - simulating exactly the crash-before-guard-save
#          scenario that left the real hook dangling in production. It runs
#          that truncated copy twice: once reconstructed from the PRE-FIX
#          (origin/main) source, once from the POST-FIX (uncommitted working
#          tree) source, and asserts the pre-fix copy leaves the real hook
#          mutated (RED - proves the bug reproduces) while the post-fix
#          copy restores it (GREEN - proves the fix works). This is the
#          `bin/tests/test_hooks_snapshot_migration.sh` file named in the
#          spawn brief as the minimum-required coverage (the UNSAFE file);
#          the other four fixed files are not separately verified here.
#
# Public API: ./bin/tests/test_precommit_hook_guard_adoption.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, git, mktemp, readlink.
#
# Downstream consumers: developer running locally before commit; wired into
#                       the bin-sh-tests CI job via the bin/tests/test_*.sh
#                       glob (.github/workflows/bin-tests.yml).
#
# Failure modes: any assertion failure prints the failing assertion and
#                exits 1. The verifier's OWN access to the real pre-commit
#                hook slot is wrapped in bin/tests/lib/precommit-hook-guard.sh
#                (saved before either truncated copy runs, restored
#                unconditionally in the EXIT trap) - independent of whether
#                either truncated copy under test remembers its own guard,
#                so this verifier is safe regardless of which scenario it is
#                currently exercising.
#
# Performance: ~10-20 s wall time (two partial .claude/install.sh runs,
#              first-install-only, no second run / no build.sh re-verify).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

# shellcheck source=bin/tests/lib/precommit-hook-guard.sh
. "$REPO_DIR/bin/tests/lib/precommit-hook-guard.sh"

PASS=0
FAIL=0

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

_pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

TMP_ROOT="$(mktemp -d)"
# The truncated copies below MUST live DIRECTLY in bin/tests/ (not a
# subdirectory of it, and not $TMP_ROOT) - both the pre-fix and post-fix
# source compute REPO_DIR as `$(cd "$(dirname "$0")/../.." && pwd)`, which
# assumes the script sits exactly one level below REPO_DIR/bin/. A copy one
# directory level deeper (or outside bin/tests/ entirely) would resolve
# REPO_DIR one level too high (or to the wrong tree entirely). Dot-prefixed
# filenames so bin-sh-tests' `bin/tests/test_*.sh` glob never picks them up;
# removed unconditionally in the EXIT trap regardless of outcome.
PREFIX_COPY="$REPO_DIR/bin/tests/.tmp-precommit-guard-verify-prefix-$$.sh"
POSTFIX_COPY="$REPO_DIR/bin/tests/.tmp-precommit-guard-verify-postfix-$$.sh"
_cleanup() {
  rm -rf "$TMP_ROOT"
  rm -f "$PREFIX_COPY" "$POSTFIX_COPY"
  precommit_hook_guard_restore
}
trap _cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Verifier's own snapshot of the real hook slot - independent of the guard
# library's internal state, used only as the assertion side below.
# ---------------------------------------------------------------------------
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
    if command -v sha256sum >/dev/null 2>&1; then
      echo "(regular file: $(sha256sum "$hook" | awk '{print $1}'))"
    else
      echo "(regular file: $(shasum -a 256 "$hook" | awk '{print $1}'))"
    fi
  else
    echo "(absent)"
  fi
}

STATE_INITIAL="$(_resolve_precommit_state)"
echo "Real pre-commit hook slot before this run: $STATE_INITIAL"

precommit_hook_guard_save "$REPO_DIR"

# ---------------------------------------------------------------------------
# Build a truncated "crash before guard save" reproduction from a given
# source revision of test_hooks_snapshot_migration.sh (pass the literal
# string WORKTREE to read the current on-disk working-tree copy instead of
# a git revision - this file's own fix is uncommitted while this verifier
# runs, so `git show HEAD:...` would still return the pre-fix content).
# Cuts immediately after the first `fi` closing the first
# .claude/install.sh's _run_install check, then appends `exit 1` - i.e.
# everything the file does BEFORE it would reach its own (pre-fix:
# too-late; post-fix: early-enough) guard save call.
# ---------------------------------------------------------------------------
_build_truncated_copy() {
  local rev="$1"
  local out_file="$2"
  local src_file="$TMP_ROOT/_src_$$.sh"
  if [[ "$rev" == "WORKTREE" ]]; then
    cp "$REPO_DIR/bin/tests/test_hooks_snapshot_migration.sh" "$src_file" 2>/dev/null || return 1
  else
    git -C "$REPO_DIR" show "$rev:bin/tests/test_hooks_snapshot_migration.sh" > "$src_file" 2>/dev/null || return 1
  fi
  python3 - "$src_file" "$out_file" <<'PYEOF'
import sys
src_path, out_path = sys.argv[1], sys.argv[2]
with open(src_path) as f:
    src = f.read()
marker = 'claude: first install.sh run exited non-zero'
idx = src.index(marker)
# Extend to the end of the enclosing "fi" line.
fi_idx = src.index('\nfi\n', idx)
truncated = src[: fi_idx + len('\nfi\n')]
truncated += '\nexit 1\n'
with open(out_path, 'w') as f:
    f.write(truncated)
PYEOF
}

_run_truncated_copy() {
  local copy_file="$1"
  local fake_home="$2"
  mkdir -p "$fake_home/.claude"
  HOME="$fake_home" bash "$copy_file" < /dev/null > "$fake_home/.out" 2>&1
  return $?
}

# ---------------------------------------------------------------------------
# 1. PRE-FIX (origin/main) truncated copy: prove RED - the real hook is
#    left mutated because the file's own guard save call, at the time of
#    origin/main, runs too late to cover this early exit.
# ---------------------------------------------------------------------------
echo ""
echo "=== 1. Pre-fix (origin/main) reproduction: expect the real hook to be MUTATED ==="

if _build_truncated_copy "origin/main" "$PREFIX_COPY"; then
  PREFIX_HOME="$TMP_ROOT/home-prefix"
  mkdir -p "$PREFIX_HOME"
  _run_truncated_copy "$PREFIX_COPY" "$PREFIX_HOME" || true

  STATE_AFTER_PREFIX="$(_resolve_precommit_state)"
  echo "  real hook slot after pre-fix truncated run: $STATE_AFTER_PREFIX"

  if [[ "$STATE_AFTER_PREFIX" != "$STATE_INITIAL" ]]; then
    _pass "pre-fix (origin/main) reproduction confirms the bug: real hook mutated ('$STATE_INITIAL' -> '$STATE_AFTER_PREFIX')"
  else
    _fail "pre-fix (origin/main) reproduction did NOT mutate the real hook - the baseline scenario did not reproduce the bug as expected"
  fi

  # Restore before continuing to the post-fix half, using the guard's saved
  # pre-run state (not the mutated intermediate state).
  precommit_hook_guard_restore
  precommit_hook_guard_save "$REPO_DIR"
  STATE_RESTORED_AFTER_PREFIX="$(_resolve_precommit_state)"
  if [[ "$STATE_RESTORED_AFTER_PREFIX" == "$STATE_INITIAL" ]]; then
    _pass "verifier's own guard restored the real hook after the pre-fix reproduction"
  else
    _fail "verifier's own guard did NOT restore the real hook after the pre-fix reproduction ('$STATE_INITIAL' -> '$STATE_RESTORED_AFTER_PREFIX')"
  fi
else
  _fail "could not build the pre-fix (origin/main) truncated reproduction"
fi

# ---------------------------------------------------------------------------
# 2. POST-FIX (the uncommitted worktree copy on disk) truncated copy: prove
#    GREEN - the real hook is restored because the
#    guard save call now runs before the first install.sh invocation.
# ---------------------------------------------------------------------------
echo ""
echo "=== 2. Post-fix (working tree) reproduction: expect the real hook to be RESTORED ==="

if _build_truncated_copy "WORKTREE" "$POSTFIX_COPY"; then
  POSTFIX_HOME="$TMP_ROOT/home-postfix"
  mkdir -p "$POSTFIX_HOME"
  _run_truncated_copy "$POSTFIX_COPY" "$POSTFIX_HOME" || true

  STATE_AFTER_POSTFIX="$(_resolve_precommit_state)"
  echo "  real hook slot after post-fix truncated run: $STATE_AFTER_POSTFIX"

  if [[ "$STATE_AFTER_POSTFIX" == "$STATE_INITIAL" ]]; then
    _pass "post-fix (working tree) reproduction confirms the fix: real hook slot restored by the truncated copy's own EXIT trap ($STATE_AFTER_POSTFIX)"
  else
    _fail "post-fix (working tree) reproduction did NOT restore the real hook - the fix did not close the bug ('$STATE_INITIAL' -> '$STATE_AFTER_POSTFIX')"
  fi
else
  _fail "could not build the post-fix (working tree) truncated reproduction"
fi

# ---------------------------------------------------------------------------
# 3. Final safety net: whatever happened above, restore via the verifier's
#    own guard and assert the real hook slot is back to its pre-run state.
# ---------------------------------------------------------------------------
precommit_hook_guard_restore
STATE_FINAL="$(_resolve_precommit_state)"
echo ""
echo "Real pre-commit hook slot after this run: $STATE_FINAL"
if [[ "$STATE_FINAL" == "$STATE_INITIAL" ]]; then
  _pass "real pre-commit hook slot unchanged end-to-end across this verifier's own run ($STATE_FINAL)"
else
  _fail "real pre-commit hook slot NOT restored at end of verifier run - expected '$STATE_INITIAL', got '$STATE_FINAL'"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
