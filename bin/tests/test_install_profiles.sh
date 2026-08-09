#!/usr/bin/env bash
# Purpose: Regression tests for the profile-agnostic installer (D-4).
#          Hermetic, sandboxed HOME. Exits 0 on all pass, 1 on any failure.
#
# Public API: ./bin/tests/test_install_profiles.sh
#
# Upstream deps: bash, scripts/install-profiles.sh, and (transitively via
#                that script) the 10 adapter .*/install.sh scripts.
#
# Downstream consumers: developer running locally before commit; CI
#                        (bin-sh-tests job).
#
# Failure modes: tests 1-8 increment $FAILS on any failing assertion; if
#                $FAILS > 0 after test 8 the script prints a summary and
#                exits 1. The later run_security_tests block (PR #416,
#                CWE-94/CWE-22/symlink regressions) reuses the same $FAILS
#                counter and fail()/pass() helpers; $FAILS is re-checked
#                after run_security_tests returns, so a failing security
#                assertion now also makes the script exit nonzero (fixed
#                DS-136 - previously it only printed "FAIL: ..." to stderr
#                and the script still exited 0).
#
# Performance: ~64 s in CI run 30968643749, driven by 5 indirect
#              .codex/install.sh calls (via scripts/install-profiles.sh);
#              expected to drop after the scripts/codex-skills.py check()
#              re-render cut (DS-136 Unit 2). Re-measure with
#              `time bash bin/tests/test_install_profiles.sh`.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAILS=0
pass() { echo "  ok: $1"; }
fail() {
	echo "  FAIL: $1" >&2
	FAILS=$((FAILS + 1))
}

cleanup() {
	chmod -R u+w "$SANDBOX" 2>/dev/null || true
	rm -rf "$SANDBOX"
}
trap cleanup EXIT

SANDBOX="$(mktemp -d)"
export HOME="$SANDBOX/home"
mkdir -p "$HOME"

# ---------------------------------------------------------------------------
# Test 1: discovery finds existing ~/.<harness>-* profile dirs and derives tenants
# ---------------------------------------------------------------------------
mkdir -p "$HOME/.claude-acme" "$HOME/.codex-acme" "$HOME/.omp-acme/agent" "$HOME/.pi-acme"
mkdir -p "$HOME/.claude-beta" "$HOME/.codex-beta" "$HOME/.pi-beta" # beta lacks omp -> skipped silently for omp

out="$($REPO_DIR/scripts/install-profiles.sh --discover --no-cursor \
	--no-identity --mode=opt-out --profile=default 2>&1 || true)"
[[ "$out" == *"claude-acme"* ]] && pass "discovery installs claude-acme" || fail "discovery missed claude-acme"
[[ "$out" == *"codex-acme"* ]] && pass "discovery installs codex-acme" || fail "discovery missed codex-acme"
[[ "$out" == *"pi-acme"* ]] && pass "discovery installs pi-acme" || fail "discovery missed pi-acme"
[[ "$out" == *"pi-beta"* ]] && pass "discovery installs pi-beta" || fail "discovery missed pi-beta"
[[ "$out" == *"omp-acme"* ]] && pass "discovery installs omp-acme" || fail "discovery missed omp-acme"
[[ "$out" == *"codex-beta"* ]] && pass "discovery installs codex-beta" || fail "discovery missed codex-beta"

# ---------------------------------------------------------------------------
# Test 2: --tenants= explicit override still works
# ---------------------------------------------------------------------------
rm -rf "$HOME/.claude-"* "$HOME/.codex-"* "$HOME/.omp-"* "$HOME/.pi-"*
mkdir -p "$HOME/.claude-foo" "$HOME/.codex-foo" "$HOME/.pi-foo"
out="$($REPO_DIR/scripts/install-profiles.sh --tenants="foo" --no-cursor \
	--no-identity --mode=opt-out --profile=default 2>&1 || true)"
[[ "$out" == *"claude-foo"* ]] && pass "explicit --tenants installs claude-foo" || fail "explicit --tenants missed claude-foo"
[[ "$out" != *"claude-acme"* ]] && pass "explicit --tenants ignores discovered acme" || fail "explicit --tenants still installed acme"

# ---------------------------------------------------------------------------
# Test 3: default (no --tenants, no --discover) does not create dirs
# ---------------------------------------------------------------------------
rm -rf "$HOME/.claude-"* "$HOME/.codex-"* "$HOME/.omp-"* "$HOME/.pi-"*
out="$($REPO_DIR/scripts/install-profiles.sh --no-cursor \
	--no-identity --mode=opt-out --profile=default 2>&1 || true)"
[[ "$out" == *"No tenant profile directories found"* ]] && pass "default reports no profiles and does nothing" || fail "default did not report empty profiles"
[[ ! -d "$HOME/.claude-default" ]] && pass "default did not create a profile dir" || fail "default created a profile dir unexpectedly"

# ---------------------------------------------------------------------------
# Test 4: --create-profile is gated: refused without explicit flag
# (same as test 3 - no creation without flag)
[[ ! -d "$HOME/.claude-new" ]] && pass "no implicit profile creation" || fail "implicit profile creation occurred"

# ---------------------------------------------------------------------------
# Test 5: pre-flight check reports creatable correctly
# ---------------------------------------------------------------------------
out="$($REPO_DIR/scripts/install-profiles.sh --create-profile=new --check-only --no-cursor 2>&1 || true)"
[[ "$out" == *"creatable (yes)"* ]] && pass "check-only reports creatable for new profile" || fail "check-only did not report creatable: $out"
[[ ! -d "$HOME/.claude-new" ]] && pass "check-only created no directories" || fail "check-only created directories"
[[ ! -d "$HOME/.pi-new" ]] && pass "check-only created no pi-new dir" || fail "check-only created pi-new dir"

# ---------------------------------------------------------------------------
# Test 6: pre-flight check refuses existing dirs (no clobber)
# ---------------------------------------------------------------------------
mkdir -p "$HOME/.claude-existing" "$HOME/.pi-existing"
out="$($REPO_DIR/scripts/install-profiles.sh --create-profile=existing --check-only --no-cursor 2>&1 || true)"
[[ "$out" == *"NOT creatable"* ]] && pass "check-only reports existing dir not creatable" || fail "check-only allowed existing dir"
[[ "$out" == *"already exists"* ]] && pass "check-only reports clobber reason" || fail "check-only did not report clobber reason"

# ---------------------------------------------------------------------------
# Test 7: pre-flight check reports unwritable parent as not creatable
# ---------------------------------------------------------------------------
mkdir -p "$HOME/readonly"
chmod 555 "$HOME/readonly"
HOME_BAK="$HOME"
export HOME="$HOME/readonly"
out="$($REPO_DIR/scripts/install-profiles.sh --create-profile=readonlychild --check-only --no-cursor 2>&1 || true)"
export HOME="$HOME_BAK"
[[ "$out" == *"NOT creatable"* ]] && pass "check-only reports unwritable parent" || fail "check-only did not report unwritable parent"
[[ "$out" == *"not writable"* ]] && pass "check-only reports writable reason" || fail "check-only did not report writable reason"

# ---------------------------------------------------------------------------
# Test 8: --create-profile actually creates dirs and installs
# ---------------------------------------------------------------------------
rm -rf "$HOME/.claude-"* "$HOME/.codex-"* "$HOME/.omp-"* "$HOME/.pi-"*
out="$($REPO_DIR/scripts/install-profiles.sh --create-profile=brandnew --no-cursor \
	--no-identity --mode=opt-out --profile=default 2>&1 || true)"
[[ -d "$HOME/.claude-brandnew" ]] && pass "create-profile created claude-brandnew" || fail "create-profile did not create claude-brandnew"
[[ -d "$HOME/.pi-brandnew" ]] && pass "create-profile created pi-brandnew" || fail "create-profile did not create pi-brandnew"
[[ "$out" == *"claude-brandnew"* ]] && pass "create-profile installed claude-brandnew" || fail "create-profile did not install claude-brandnew"

if [[ "$FAILS" -gt 0 ]]; then
	echo "FAILED: $FAILS assertion(s)"
	exit 1
fi
echo "All install-profiles tests passed."

# --- Security regression tests (PR #416 review: CWE-94 / CWE-22 / symlink) ---
run_security_tests() {
  local sb; sb="$(mktemp -d)"
  export HOME="$sb/home"; mkdir -p "$HOME"

  # 1) Code injection via --config-dir single-quote payload must NOT execute.
  rm -f "$sb/pwned"
  local evil="$sb/x'+__import__(\"os\").system(\"touch $sb/pwned\")+'"
  bash "$REPO_DIR/.claude/install.sh" --config-dir="$evil" --no-identity >/dev/null 2>&1 || true
  [[ -f "$sb/pwned" ]] && fail "CWE-94 injection executed" || pass "config-dir injection blocked"

  # 2) Path traversal via --harnesses must be rejected (not bash-executed).
  mkdir -p "$sb/evilbin"; echo "touch $sb/traversed" > "$sb/evilbin/install.sh"
  rm -f "$sb/traversed"
  mkdir -p "$HOME/.claude-t1"
  bash "$REPO_DIR/scripts/install-profiles.sh" --tenants="t1" \
       --harnesses="../../../../../../../$sb/evilbin" --no-cursor >/dev/null 2>&1 || true
  [[ -f "$sb/traversed" ]] && fail "CWE-22 traversal executed" || pass "harness traversal blocked"

  # 3) Symlinked config path must NOT be written through.
  local prof="$sb/prof"; mkdir -p "$prof"
  echo "KEEP" > "$sb/victim"
  ln -sf "$sb/victim" "$prof/agentic-engineering.json"
  bash "$REPO_DIR/.claude/install.sh" --config-dir="$prof" --mode=opt-out --no-identity >/dev/null 2>&1 || true
  grep -q KEEP "$sb/victim" && pass "symlink write blocked" || fail "symlink write truncated victim"

  # 3b) Symlinked settings.json must NOT be written through.
  local prof2="$sb/prof2"; mkdir -p "$prof2"
  echo "KEEP" > "$sb/victim2"
  ln -sf "$sb/victim2" "$prof2/settings.json"
  bash "$REPO_DIR/.claude/install.sh" --config-dir="$prof2" --mode=opt-out --no-identity >/dev/null 2>&1 || true
  grep -q KEEP "$sb/victim2" && pass "settings.json symlink write blocked" || fail "settings.json symlink write truncated victim"

  # 3c) install-profiles.sh must guard omp's ACTUAL config dir ($base/agent),
  # not just the profile base ($base). Plant a symlinked agent dir and confirm
  # install-profiles refuses it and leaves the victim target untouched.
  mkdir -p "$HOME/.omp-victim"          # real base dir (passes the $base guard)
  mkdir -p "$sb/omp_victim_target"
  echo "KEEP_OMP" > "$sb/omp_victim_target/inside.txt"
  ln -sfn "$sb/omp_victim_target" "$HOME/.omp-victim/agent"  # symlinked config dir
  out3c="$(bash "$REPO_DIR/scripts/install-profiles.sh" --tenants=victim --harnesses=omp \
           --no-cursor --no-identity --mode=opt-out --profile=default </dev/null 2>&1 || true)"
  # Match install-profiles.sh's OWN refusal message ("config dir is a symlink"),
  # not the inner installer's ("...install through symlinked config dir"), so this
  # assertion pins the outer guard specifically rather than passing on the inner
  # installer's independent (defense-in-depth) refusal.
  echo "$out3c" | grep -q "config dir is a symlink" \
    && pass "install-profiles refuses symlinked omp config dir" \
    || fail "install-profiles did NOT refuse symlinked omp config dir"
  if [[ ! -e "$sb/omp_victim_target/agentic-engineering.json" ]] \
     && grep -q KEEP_OMP "$sb/omp_victim_target/inside.txt"; then
    pass "install-profiles planted no file through symlinked omp config dir"
  else
    fail "install-profiles planted a file through symlinked omp config dir"
  fi
  rm -rf "$sb"
}
run_security_tests

if [[ "$FAILS" -gt 0 ]]; then
  echo "FAILED: $FAILS assertion(s) (including security regression tests)"
  exit 1
fi
echo "All install-profiles tests (including security regressions) passed."
