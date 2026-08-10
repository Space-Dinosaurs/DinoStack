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
#          that truncated copy twice against the CURRENT on-disk source of
#          bin/tests/test_hooks_snapshot_migration.sh (never git history or
#          any origin/* ref - hermetic, no fetch-depth dependency, cannot
#          invert after merge): once as POST-FIX (unmodified - the guard
#          save call this fix added stays in place before the first
#          install.sh invocation), once as PRE-FIX (the exact guard-save
#          block this fix introduced is mechanically stripped back out,
#          reproducing the too-late-guard structure the file had before
#          this change - see the "guard block marker" comment in
#          _build_truncated_copy below). It asserts the pre-fix copy leaves
#          the real hook mutated (RED - proves the bug reproduces) while
#          the post-fix copy restores it (GREEN - proves the fix works).
#          Because both reproductions are derived from the same current
#          working-tree file, this is unaffected by which SHA is checked
#          out and independent of `origin/main` being fetched, reachable,
#          or even existing. This is the
#          `bin/tests/test_hooks_snapshot_migration.sh` file named in the
#          spawn brief as the minimum-required coverage (the UNSAFE file);
#          the other four fixed files are not separately verified here
#          (see Major 1 in bin/tests/test_precommit_hook_guard_static.sh
#          for the static ordering assertion that covers all five).
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
# Build a truncated "crash before guard save" reproduction from the CURRENT
# on-disk source of test_hooks_snapshot_migration.sh - never git history or
# any origin/* ref (see file header). Pass variant POSTFIX to reproduce the
# file exactly as it stands (guard save call intact, before the first
# install.sh invocation); pass variant PREFIX to mechanically strip back out
# the exact guard-save block this fix (75225f67) introduced, reproducing the
# too-late-guard structure the file had before this change. Both variants
# then cut immediately after the first `fi` closing the first
# .claude/install.sh's _run_install check, then append `exit 1` - i.e.
# everything the file does BEFORE it would reach its own (PREFIX: never;
# POSTFIX: early-enough) guard save call.
# ---------------------------------------------------------------------------
_build_truncated_copy() {
  local variant="$1"
  local out_file="$2"
  local src_file="$TMP_ROOT/_src_$$.sh"
  cp "$REPO_DIR/bin/tests/test_hooks_snapshot_migration.sh" "$src_file" 2>/dev/null || return 1
  python3 - "$src_file" "$out_file" "$variant" <<'PYEOF'
import sys
src_path, out_path, variant = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src_path) as f:
    src = f.read()

if variant == "PREFIX":
    # Mechanically strip out the early guard-save block this fix (75225f67)
    # added, reproducing the pre-fix too-late-guard structure. This is a
    # transform of the CURRENT working-tree file, never git history, so it
    # is hermetic (no ref-availability dependency) and cannot invert after
    # merge - removing the very block the fix introduced always reproduces
    # the pre-fix defect, regardless of which commit is checked out.
    guard_block_marker = (
        '# Save the real pre-commit hook slot BEFORE the first '
        'install.sh invocation'
    )
    guard_call_marker = 'precommit_hook_guard_save "$REPO_DIR"\n'
    start = src.index(guard_block_marker)  # raises if the fix's own block is gone
    call_idx = src.index(guard_call_marker, start)
    end = call_idx + len(guard_call_marker)
    src = src[:start] + src[end:]
elif variant != "POSTFIX":
    raise ValueError("unknown variant: %r" % variant)

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
# 1. PRE-FIX (synthetic, derived from the current working-tree file with the
#    fix's own guard-save block mechanically stripped back out) truncated
#    copy: prove RED - the real hook is left mutated because, with that
#    block removed, no guard save call covers this early exit.
# ---------------------------------------------------------------------------
echo ""
echo "=== 1. Pre-fix (synthetic) reproduction: expect the real hook to be MUTATED ==="

if _build_truncated_copy "PREFIX" "$PREFIX_COPY"; then
  PREFIX_HOME="$TMP_ROOT/home-prefix"
  mkdir -p "$PREFIX_HOME"
  _run_truncated_copy "$PREFIX_COPY" "$PREFIX_HOME" || true

  STATE_AFTER_PREFIX="$(_resolve_precommit_state)"
  echo "  real hook slot after pre-fix truncated run: $STATE_AFTER_PREFIX"

  if [[ "$STATE_AFTER_PREFIX" != "$STATE_INITIAL" ]]; then
    _pass "pre-fix (synthetic) reproduction confirms the bug: real hook mutated ('$STATE_INITIAL' -> '$STATE_AFTER_PREFIX')"
  else
    _fail "pre-fix (synthetic) reproduction did NOT mutate the real hook - the baseline scenario did not reproduce the bug as expected"
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
  _fail "could not build the pre-fix (synthetic) truncated reproduction"
fi

# ---------------------------------------------------------------------------
# 2. POST-FIX (the current working-tree copy on disk, unmodified) truncated
#    copy: prove GREEN - the real hook is restored because the guard save
#    call now runs before the first install.sh invocation.
# ---------------------------------------------------------------------------
echo ""
echo "=== 2. Post-fix (working tree) reproduction: expect the real hook to be RESTORED ==="

if _build_truncated_copy "POSTFIX" "$POSTFIX_COPY"; then
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
