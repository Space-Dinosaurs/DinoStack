#!/usr/bin/env bash
# Purpose: Regression test for the bin/agentic-* -> bin/ds-* rename's
#          "silently disables identity setup on every existing user's first
#          upgrade" defect. .claude/install.sh's "Developer identity" block
#          must run AFTER ae_install_bins - the only step that symlinks
#          ds-identity onto PATH. Before the fix, the identity block ran at
#          line ~1383 (pre-rename) / a `ds-identity` guard fired at that same
#          early position post-rename, while ae_install_bins ran later at
#          line ~1717 - so a user upgrading from a pre-rename install who
#          held only the old agentic-* names in ~/.local/bin hit the
#          "ds-identity not found on PATH" branch and identity setup was
#          silently skipped.
#
# Public API: ./bin/tests/test_install_identity_bin_order.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, grep, mktemp, python3 (via install.sh's own use).
#
# Downstream consumers: developer running locally before commit; wired into
#                       the bin-sh-tests CI job via the bin/tests/test_*.sh
#                       glob (.github/workflows/bin-tests.yml).
#
# Failure modes: any assertion failure prints the failing assertion and
#                exits 1. Test 2 runs the REAL .claude/install.sh against a
#                fully faked HOME (with a fake ~/.local/bin seeded with only
#                the 25 pre-rename agentic-* names) but the real repo bin/ -
#                it writes only under the faked HOME plus the same three
#                live-tree side effects documented in
#                test_local_bin_ds_prefix_install.sh (git hooks pre-commit,
#                .claude/build.sh, .cursor/build.sh); empirically idempotent.
#
# Regression coverage:
#   - Test 1 (structural): the "ae_install_bins" call site precedes the
#     "_ae_setup_identity" call site in .claude/install.sh - byte-offset
#     ordering, not just presence.
#   - Test 2 (functional, simulated upgrade): a fake HOME whose
#     ~/.local/bin holds ONLY the 25 old agentic-* names (no ds-* names at
#     all - the exact pre-existing-install shape from before the rename) is
#     handed to the real .claude/install.sh. Asserts identity setup
#     actually proceeds (does not hit the "ds-identity not found on PATH"
#     skip branch) once ae_install_bins has had a chance to link ds-identity
#     onto PATH first. Two further POSITIVE assertions (not just absence of
#     the bad message) confirm the identity block genuinely executed: the
#     "Developer identity..." header is present, and one of
#     _ae_setup_identity's real branch-outcome messages (identity set to /
#     already set / setup skipped / init failed / non-interactive skip) is
#     present. Absence-only checking cannot distinguish "identity ran and
#     proceeded" from "the identity block never executed at all", and
#     degrades silently if that message is reworded; these two assertions
#     close that gap. (T1 already backstops outright deletion of the
#     ordering, so the pair as a whole is not vacuous.)

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_DIR/.claude/install.sh"

# shellcheck source=bin/tests/lib/precommit-hook-guard.sh
source "$REPO_DIR/bin/tests/lib/precommit-hook-guard.sh"

PASS=0
FAIL=0

_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

# ---------------------------------------------------------------------------
# Test 1 (structural): ae_install_bins call precedes _ae_setup_identity call.
# ---------------------------------------------------------------------------
bins_line="$(grep -n '^ae_install_bins$' "$INSTALL_SH" | head -1 | cut -d: -f1)"
identity_line="$(grep -n '^\s*_ae_setup_identity$' "$INSTALL_SH" | head -1 | cut -d: -f1)"

if [[ -z "$bins_line" ]]; then
  _fail "T1: could not find 'ae_install_bins' call site in $INSTALL_SH"
elif [[ -z "$identity_line" ]]; then
  _fail "T1: could not find '_ae_setup_identity' call site in $INSTALL_SH"
elif [[ "$bins_line" -lt "$identity_line" ]]; then
  _pass "T1: ae_install_bins (line $bins_line) precedes _ae_setup_identity (line $identity_line)"
else
  _fail "T1: ae_install_bins (line $bins_line) does NOT precede _ae_setup_identity (line $identity_line) - identity setup will run before ds-identity is on PATH"
fi

# ---------------------------------------------------------------------------
# Test 2 (functional, simulated upgrade): fake HOME with only the 25 old
# agentic-* names pre-populated in ~/.local/bin (as real executables, not
# symlinks into the repo - mirrors a genuine pre-rename install). Run the
# real .claude/install.sh and confirm identity setup proceeds rather than
# hitting the "ds-identity not found on PATH" skip branch.
# ---------------------------------------------------------------------------
FAKE_HOME=""
_cleanup() {
  precommit_hook_guard_restore
  [[ -n "$FAKE_HOME" && -d "$FAKE_HOME" ]] && rm -rf "$FAKE_HOME"
}
trap _cleanup EXIT

precommit_hook_guard_save "$REPO_DIR"

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.agentic" "$FAKE_HOME/.local/bin"

# 25 pre-rename bin/agentic-* real-file names, matching the current bin/
# directory's post-rename symlink set (the compat aliases) - i.e. every name
# a user's ~/.local/bin held before this rename shipped.
OLD_NAMES=()
for f in "$REPO_DIR"/bin/agentic-*; do
  [[ -L "$f" ]] || continue
  OLD_NAMES+=("$(basename "$f")")
done

if [[ "${#OLD_NAMES[@]}" -eq 0 ]]; then
  _fail "T2: could not enumerate any bin/agentic-* compat symlinks to simulate a pre-existing install"
else
  for name in "${OLD_NAMES[@]}"; do
    cat > "$FAKE_HOME/.local/bin/$name" <<'EOF'
#!/usr/bin/env bash
echo "fake pre-rename tool"
EOF
    chmod +x "$FAKE_HOME/.local/bin/$name"
  done

  ds_count_before="$(find "$FAKE_HOME/.local/bin" -name 'ds-*' | wc -l | tr -d ' ')"
  echo "pre-existing install has: ${#OLD_NAMES[@]} tools, ds-* count = $ds_count_before"

  if [[ "$ds_count_before" -ne 0 ]]; then
    _fail "T2: simulated pre-existing install unexpectedly already has ds-* names ($ds_count_before)"
  else
    _pass "T2: simulated pre-existing install seeded with ${#OLD_NAMES[@]} old agentic-* names, zero ds-* names"
  fi

  OUT="$(HOME="$FAKE_HOME" PATH="$FAKE_HOME/.local/bin:$PATH" bash "$INSTALL_SH" \
    --mode=opt-out --profile=default < /dev/null 2>&1)"
  RC=$?

  if [[ "$RC" -ne 0 ]]; then
    _fail "T2: .claude/install.sh exited $RC"
    echo "$OUT" >&2
  fi

  if echo "$OUT" | grep -q 'ds-identity not found on PATH'; then
    _fail "T2: identity setup SKIPPED - install.sh hit the 'ds-identity not found on PATH' branch (regression: identity runs before bins are linked)"
    echo "----- install.sh output -----" >&2
    echo "$OUT" >&2
    echo "------------------------------" >&2
  else
    _pass "T2: identity setup did not hit the 'ds-identity not found on PATH' skip branch - proceeded"
  fi

  # Positive assertions (not just absence-of-the-bad-message): confirm the
  # identity block actually EXECUTED and reached a real _ae_setup_identity
  # decision branch, rather than e.g. the whole "Developer identity" section
  # silently never running at all (which T1's absence-based check alone
  # cannot distinguish from "ran and proceeded" - see MINOR 3). T1 backstops
  # outright deletion of the ordering; these two backstop the block's own
  # non-execution or a silently-reworded header/branch message.
  if echo "$OUT" | grep -q 'Developer identity\.\.\.'; then
    _pass "T2: 'Developer identity...' header present - the identity block ran"
  else
    _fail "T2: 'Developer identity...' header not found in install.sh output - identity block did not run at all"
    echo "----- install.sh output -----" >&2
    echo "$OUT" >&2
    echo "------------------------------" >&2
  fi

  # One of _ae_setup_identity's 7 branch-outcome messages (identity.sh) must
  # appear - proves the function reached and printed a real decision, not
  # just an empty/no-op invocation. In this fake, non-TTY-but-not-actually-
  # readable HOME, the expected outcome is branch 5 or 7's skip message
  # ("identity setup skipped"); the full alternation also covers the other
  # outcomes so this stays valid if the harness environment changes.
  if echo "$OUT" | grep -qE "identity (set to|already set|setup skipped|init failed)|non-interactive install: skipped identity setup"; then
    _pass "T2: a real _ae_setup_identity branch-outcome message is present"
  else
    _fail "T2: no recognizable _ae_setup_identity branch-outcome message found - the block may have run without reaching a real decision branch"
    echo "----- install.sh output -----" >&2
    echo "$OUT" >&2
    echo "------------------------------" >&2
  fi

  if [[ -L "$FAKE_HOME/.local/bin/ds-identity" ]]; then
    _pass "T2: ds-identity was linked onto PATH before the identity block ran"
  else
    _fail "T2: ds-identity was not linked into fake ~/.local/bin by ae_install_bins"
  fi
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
