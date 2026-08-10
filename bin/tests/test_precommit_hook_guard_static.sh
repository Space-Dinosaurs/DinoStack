#!/usr/bin/env bash
# Purpose: Static regression coverage for the precommit-hook-guard adoption
#          fix (75225f67) across all FIVE files it touched -
#          bin/tests/test_precommit_hook_guard_adoption.sh only exercises
#          test_hooks_snapshot_migration.sh end-to-end (the UNSAFE file); the
#          other four (test_install_profiles.sh,
#          test_hooks_snapshot_no_live_rewire.sh, test_install_stop_cadence.sh,
#          test_install_profile_config_dir.sh) had zero regression coverage -
#          proven by mutation: reverting test_install_stop_cadence.sh to its
#          pre-fix content still yielded a clean run of the adoption
#          verifier. This file closes that gap with a cheap, deterministic
#          ordering assertion instead of five more end-to-end reproductions:
#          for each of the five files, assert (1) the guard library is
#          sourced, (2) precommit_hook_guard_save "$REPO_DIR" is called,
#          (3) that save call's line number is LESS THAN the line number of
#          the file's first real install.sh invocation (direct or via the
#          scripts/install-profiles.sh indirect invoker - see assertion 3
#          below), and (4) precommit_hook_guard_restore is called somewhere
#          in the file. Assertion (3) is the one that matters most for
#          "guard placed too late" (test_hooks_snapshot_migration.sh's guard
#          save originally ran right before the final .claude uninstall leg,
#          after two earlier install.sh calls had already mutated the real
#          hook unguarded - see 75225f67's commit message). Assertion (4) is
#          the one that matters for "guard removed entirely": save alone
#          protects nothing if nothing ever puts the real hook back. Save
#          without a paired restore is precisely the production defect this
#          PR exists to prevent - the real hook left repointed after a
#          SUCCESSFUL run, not just a crashed one. Only
#          test_hooks_snapshot_migration.sh has restore covered end-to-end
#          elsewhere (the adoption verifier's POSTFIX leg); the other four
#          have no coverage of restore at all outside this file.
#
#          Assertion (4) also makes a best-effort "reachable" check: restore
#          is reachable if it appears directly inside a `trap ... EXIT` line
#          (test_install_profile_config_dir.sh's inline-string traps), or
#          inside a function that some `trap <funcname> EXIT` line later
#          names (the `cleanup()`/`_cleanup()` pattern used by the other
#          four files). This is presence-plus-shape, not full control-flow
#          proof - see the "Static-match limits" section below for what it
#          does and does not prove; reachability failure is reported as an
#          additional PASS/FAIL alongside the plain presence assertion, not
#          a substitute for it, so a restore call this heuristic cannot
#          classify still counts as covered by assertion (4) alone.
#
# Static-match limits (both confirmed by the reviewer during the round that
# authored this file - stated here so the next reader knows what a green run
# does and does not prove):
#   - False negative: a save/restore call wrapped in a conditional that never
#     executes (e.g. `if false; then precommit_hook_guard_save "$REPO_DIR";
#     fi`) still matches this file's line-presence and ordering scans and
#     reports PASS - this checker verifies the call is TEXTUALLY PRESENT and
#     correctly ORDERED, not that it is reachable at runtime for every
#     control-flow path.
#   - False positive direction: the install.sh-invocation scan
#     (`/install\.sh"/`) matches any line containing that substring
#     immediately before a closing quote, including lines that merely
#     REFERENCE install.sh without running it - e.g.
#     test_install_profile_config_dir.sh:123's
#     `grep -Fq "_ae_identity_guidance" "$REPO_DIR/.$harness/install.sh"` is
#     a read, not an invocation, but still counts as an "install.sh
#     invocation" for ordering purposes. This is conservative in the
#     direction that matters (an earlier phantom "invocation" only makes the
#     ordering assertion stricter, never looser), so it is left as-is.
#
# Public API: ./bin/tests/test_precommit_hook_guard_static.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, awk.
#
# Downstream consumers: developer running locally before commit; wired into
#                       the bin-sh-tests CI job via the bin/tests/test_*.sh
#                       glob (.github/workflows/bin-tests.yml).
#
# Failure modes: any assertion failure prints the failing assertion and file
#                and exits 1. This file performs no filesystem mutation and
#                touches no git state - pure static text inspection of the
#                five target files, so it needs no cleanup trap.
#
# Performance: well under 1 s (five small awk passes).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

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

# The five files 75225f67 adopted the guard in. Set as positional params
# (not a plain space-separated string) so the `for ... in` below splits
# correctly under both bash and zsh - zsh does not word-split an unquoted
# variable reference by default, unlike bash.
set -- test_install_profiles.sh test_hooks_snapshot_no_live_rewire.sh test_install_stop_cadence.sh test_install_profile_config_dir.sh test_hooks_snapshot_migration.sh

# ---------------------------------------------------------------------------
# _line_numbers <file>
#   Prints five space-separated numbers (0 meaning "not found", except the
#   final field which is always 0 or 1):
#     <guard-source-line> <guard-save-line> <first-install-invocation-line>
#     <guard-restore-line> <restore-reachable-via-trap:0-or-1>
#   The first three scans skip comment lines (first non-whitespace char '#')
#   so a mention in a header/prose comment is never mistaken for the real
#   code. The install-invocation scan matches EITHER a direct invocation
#   (`/install\.sh"` - slash immediately before the literal filename,
#   deliberately excluding `uninstall.sh`, whose substring is
#   `uninstall.sh` with no slash directly before `install`) OR an indirect
#   invocation via scripts/install-profiles.sh, the only script any of the
#   five files call that itself shells out to an adapter install.sh
#   (scripts/install-profiles.sh:270,326) - grepped for repo-wide at review
#   time; no other indirect invoker exists today. The restore scan matches
#   any (non-comment) line containing the literal call, not just an
#   exact-trimmed match, because two of the five files call it from inside
#   an inline `trap '...' EXIT` string rather than as a bare statement. The
#   reachability flag is a best-effort structural check, not a proof - see
#   the file header's "Static-match limits" section.
# ---------------------------------------------------------------------------
_line_numbers() {
  awk '
    {
      line = $0
      trimmed = line
      sub(/^[ \t]+/, "", trimmed)
      if (trimmed ~ /^#/) next

      # Track the enclosing function (simple, single-level: these five
      # files never nest a function inside another) so a restore call
      # inside cleanup()/_cleanup() can be tied back to that function name.
      if (match(trimmed, /^(function[ \t]+)?[A-Za-z_][A-Za-z0-9_]*\(\)[ \t]*\{[ \t]*$/)) {
        fname = trimmed
        sub(/^function[ \t]+/, "", fname)
        sub(/\(\).*/, "", fname)
        curfunc = fname
      } else if (trimmed == "}") {
        curfunc = ""
      }

      if (src == 0 && trimmed == ". \"$REPO_DIR/bin/tests/lib/precommit-hook-guard.sh\"") src = NR
      if (save == 0 && trimmed == "precommit_hook_guard_save \"$REPO_DIR\"") save = NR
      if (inst == 0 && (line ~ /\/install\.sh"/ || line ~ /\/install-profiles\.sh/)) inst = NR

      if (line ~ /precommit_hook_guard_restore/) {
        if (rest == 0) rest = NR
        if (curfunc != "") func_has_restore[curfunc] = 1
        if (line ~ /trap /) direct_reach = 1
      }

      if (match(line, /trap[ \t]+[A-Za-z_][A-Za-z0-9_]*[ \t]+EXIT/)) {
        t = line
        sub(/^.*trap[ \t]+/, "", t)
        sub(/[ \t]+EXIT.*/, "", t)
        if (t in func_has_restore) reach_via_func = 1
      }
    }
    END {
      reach = (direct_reach || reach_via_func) ? 1 : 0
      print src+0, save+0, inst+0, rest+0, reach
    }
  ' "$1"
}

for fname in "$@"; do
  fpath="$REPO_DIR/bin/tests/$fname"
  if [[ ! -f "$fpath" ]]; then
    _fail "$fname: file not found at $fpath"
    continue
  fi

  read -r src_line save_line inst_line rest_line reachable < <(_line_numbers "$fpath")

  if [[ "$src_line" -gt 0 ]]; then
    _pass "$fname: guard library sourced (line $src_line)"
  else
    _fail "$fname: guard library is NOT sourced"
  fi

  if [[ "$save_line" -gt 0 ]]; then
    _pass "$fname: precommit_hook_guard_save is called (line $save_line)"
  else
    _fail "$fname: precommit_hook_guard_save is NOT called"
  fi

  if [[ "$inst_line" -eq 0 ]]; then
    _fail "$fname: no install.sh invocation found - cannot assert ordering (test drifted from the file's structure)"
  elif [[ "$save_line" -gt 0 && "$save_line" -lt "$inst_line" ]]; then
    _pass "$fname: guard save (line $save_line) runs before the first install.sh invocation (line $inst_line)"
  else
    _fail "$fname: guard save (line $save_line) does NOT run before the first install.sh invocation (line $inst_line) - guard is missing or placed too late"
  fi

  if [[ "$rest_line" -gt 0 ]]; then
    _pass "$fname: precommit_hook_guard_restore is called (line $rest_line)"
  else
    _fail "$fname: precommit_hook_guard_restore is NOT called - a guard save with no matching restore protects nothing"
  fi

  if [[ "$rest_line" -gt 0 ]]; then
    if [[ "$reachable" -eq 1 ]]; then
      _pass "$fname: precommit_hook_guard_restore is reachable from an EXIT trap (directly or via a trap-named function)"
    else
      _fail "$fname: precommit_hook_guard_restore is called but not observably reachable from an EXIT trap - restore may only run on the happy path"
    fi
  fi
done

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
