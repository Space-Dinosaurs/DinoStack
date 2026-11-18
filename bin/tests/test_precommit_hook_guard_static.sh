#!/usr/bin/env bash
# Purpose: Static check that every bin/tests/test_*.sh which runs a live
#          .claude/.cursor/.opencode install.sh or uninstall.sh (or
#          scripts/install-profiles.sh) against "$REPO_DIR" guards the real
#          pre-commit hook. Those installers call install_precommit_hook /
#          uninstall_precommit_hook, which resolve the hooks dir from the
#          real checkout regardless of a faked $HOME, so an unguarded test
#          repoints or deletes the developer's live .git/hooks/pre-commit.
#          Callers are discovered, not listed, so a new unguarded caller
#          fails here. Per caller it asserts: the guard library is sourced,
#          precommit_hook_guard_save "$REPO_DIR" runs before the first
#          installer reference (a VAR="$REPO_DIR/..." assignment is not a
#          reference; the first later use of $VAR is), and precommit_hook_guard_restore runs from
#          the EXIT trap (inline, or inside the function the trap names).
#
# Public API: ./bin/tests/test_precommit_hook_guard_static.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, awk, grep.
#
# Failure modes: a call inside a branch that never executes still passes;
#                this checks text and ordering, not runtime reachability.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TESTS_DIR="$REPO_DIR/bin/tests"

PASS=0
FAIL=0
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }

INSTALLER_RE='\$REPO_DIR/\.(claude|cursor|opencode)/(un)?install\.sh|\$REPO_DIR/scripts/install-profiles\.sh'

# Reads the production uninstall.sh source for a drift comparison; never runs it.
EXEMPT="test_uninstall_bin_symlink.sh"

# Prints: <source-line> <save-line> <first-installer-line> <restore-in-exit-trap:0|1>
_scan() {
  RE="$INSTALLER_RE" awk '
    BEGIN { re = ENVIRON["RE"] }
    {
      t = $0
      sub(/^[ \t]+/, "", t)
      if (t ~ /^#/) next
      if (match(t, /^_?[A-Za-z0-9_]+\(\)[ \t]*\{/)) {
        cur = substr(t, 1, index(t, "(") - 1)
        if (t ~ /\}[ \t]*$/) { if (t ~ /precommit_hook_guard_restore/) has[cur] = 1; cur = "" }
        next
      }
      if (t == "}") { cur = ""; next }
      if (cur != "" && t ~ /precommit_hook_guard_restore/) has[cur] = 1
      if (!src && t ~ /^(\.|source) "\$REPO_DIR\/bin\/tests\/lib\/precommit-hook-guard\.sh"$/) src = NR
      if (!save && t == "precommit_hook_guard_save \"$REPO_DIR\"") save = NR
      if (t ~ re && match(t, /^[A-Za-z_][A-Za-z0-9_]*="[^"]*"$/)) {
        alias[substr(t, 1, index(t, "=") - 1)] = 1
        next
      }
      if (!inst && t ~ re) inst = NR
      if (!inst) for (a in alias) if (index(t, "$" a) || index(t, "${" a "}")) inst = NR
      if (t ~ /^trap .*EXIT/) {
        trap_line = t
      }
    }
    END {
      ok = 0
      if (trap_line ~ /precommit_hook_guard_restore/) ok = 1
      else {
        n = trap_line
        sub(/^trap[ \t]+/, "", n)
        sub(/[ \t].*/, "", n)
        if (n in has) ok = 1
      }
      print src + 0, save + 0, inst + 0, ok
    }
  ' "$1"
}

found=0
for fpath in "$TESTS_DIR"/test_*.sh; do
  fname="$(basename "$fpath")"
  [[ "$fname" == "$EXEMPT" ]] && continue
  read -r src save inst reach < <(_scan "$fpath")
  [[ "$inst" -eq 0 ]] && continue
  found=$((found + 1))

  if [[ "$src" -gt 0 && "$save" -gt 0 && "$save" -lt "$inst" ]]; then
    _pass "$fname: guard sourced and saved (line $save) before the first installer reference (line $inst)"
  else
    _fail "$fname: runs a live installer (line $inst) without sourcing bin/tests/lib/precommit-hook-guard.sh and calling precommit_hook_guard_save \"\$REPO_DIR\" before it (source line $src, save line $save)"
  fi

  if [[ "$reach" -eq 1 ]]; then
    _pass "$fname: precommit_hook_guard_restore runs from the EXIT trap"
  else
    _fail "$fname: precommit_hook_guard_restore is not run from the EXIT trap"
  fi
done

# Discovery anchor: a known caller must be found, or the scan matched nothing.
if [[ "$found" -gt 0 ]] && _scan "$TESTS_DIR/test_hooks_snapshot_migration.sh" | awk '{exit !($3 > 0)}'; then
  _pass "discovered $found installer-running test files, including test_hooks_snapshot_migration.sh"
else
  _fail "discovery found no installer-running test files (or missed test_hooks_snapshot_migration.sh) - the scan is broken"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
[[ "$FAIL" -eq 0 ]]
