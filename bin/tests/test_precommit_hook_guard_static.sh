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
#          sourced, (2) precommit_hook_guard_save "$REPO_DIR" is called, and
#          (3) that save call's line number is LESS THAN the line number of
#          the file's first real install.sh invocation. That third
#          assertion is the one that actually matters - it catches both
#          "guard removed" (assertion 2 fails) and "guard placed too late"
#          (assertion 3 fails), which was the exact defect this verifier
#          exists to catch (test_hooks_snapshot_migration.sh's guard save
#          originally ran right before the final .claude uninstall leg,
#          after two earlier install.sh calls had already mutated the real
#          hook unguarded - see 75225f67's commit message).
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
#   Prints three space-separated numbers (0 meaning "not found"):
#     <guard-source-line> <guard-save-line> <first-install-invocation-line>
#   All three scans skip comment lines (first non-whitespace char '#') so a
#   mention in a header/prose comment is never mistaken for the real code.
#   The install-invocation match is `/install\.sh"` (slash immediately
#   before the literal filename) - deliberately excludes `uninstall.sh`,
#   whose substring is `uninstall.sh` (no slash directly before `install`).
# ---------------------------------------------------------------------------
_line_numbers() {
  awk '
    {
      line = $0
      trimmed = line
      sub(/^[ \t]+/, "", trimmed)
      if (trimmed ~ /^#/) next
      if (src == 0 && trimmed == ". \"$REPO_DIR/bin/tests/lib/precommit-hook-guard.sh\"") src = NR
      if (save == 0 && trimmed == "precommit_hook_guard_save \"$REPO_DIR\"") save = NR
      if (inst == 0 && line ~ /\/install\.sh"/) inst = NR
    }
    END { print src+0, save+0, inst+0 }
  ' "$1"
}

for fname in "$@"; do
  fpath="$REPO_DIR/bin/tests/$fname"
  if [[ ! -f "$fpath" ]]; then
    _fail "$fname: file not found at $fpath"
    continue
  fi

  read -r src_line save_line inst_line < <(_line_numbers "$fpath")

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
done

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
