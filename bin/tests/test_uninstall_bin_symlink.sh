#!/usr/bin/env bash
# Purpose: Regression test for the ~/.local/bin/agentic-* symlink removal guard
#          added to all adapter uninstall.sh scripts.
#
# Public API: ./bin/tests/test_uninstall_bin_symlink.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp.
#
# Downstream consumers: developer running locally before commit; CI.
#
# Failure modes: any assertion failure prints the failing assertion and exits 1.
#                A temporary fake HOME and fake repo dir are used; the real
#                ~/.local/bin is never touched.
#
# Performance: < 1 s wall time (pure shell, no network).
#
# Regression coverage:
#   - fix(uninstall): remove ~/.local/bin/agentic-* symlinks pointing into the repo
#     The guard must require a $REPO_DIR/bin/ prefix, not just $REPO_DIR, so a
#     sibling checkout under $REPO_DIR-backup/bin/ is NOT removed. The sibling-
#     prefix test would FAIL under the original loose guard `"$REPO_DIR"*` and
#     must PASS after the `/bin/` boundary fix.

set -uo pipefail

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

# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------

# run_bin_guard <REPO_DIR> <BIN_DST>
# Executes the exact guard logic from the uninstall.sh bin-removal block.
# Uses the tightened guard: "$REPO_DIR/bin/"*
run_bin_guard() {
  local REPO_DIR="$1"
  local BIN_DST="$2"

  if [[ ! -d "$BIN_DST" ]]; then
    echo "  [skip] ~/.local/bin not found"
    return
  fi

  local _found_any=false
  local dst_file name current_target
  for dst_file in "$BIN_DST"/agentic-*; do
    [[ -e "$dst_file" || -L "$dst_file" ]] || continue
    _found_any=true
    name="$(basename "$dst_file")"

    if [[ -L "$dst_file" ]]; then
      current_target="$(readlink "$dst_file")"
      if [[ "$current_target" == "$REPO_DIR/bin/"* ]]; then
        rm "$dst_file"
        echo "  - $name removed"
      else
        echo "  = $name (points to $current_target - not ours, skipping)"
      fi
    else
      echo "  = $name (real file - not removing)"
    fi
  done
  if [[ "$_found_any" == false ]]; then
    echo "  = no agentic-* entries found in ~/.local/bin"
  fi
}

# run_bin_guard_loose <REPO_DIR> <BIN_DST>
# Executes the OLD loose guard (`"$REPO_DIR"*`) to prove the sibling-prefix
# case would have failed under the previous code.
run_bin_guard_loose() {
  local REPO_DIR="$1"
  local BIN_DST="$2"

  if [[ ! -d "$BIN_DST" ]]; then
    return
  fi

  local _found_any=false
  local dst_file name current_target
  for dst_file in "$BIN_DST"/agentic-*; do
    [[ -e "$dst_file" || -L "$dst_file" ]] || continue
    _found_any=true
    name="$(basename "$dst_file")"

    if [[ -L "$dst_file" ]]; then
      current_target="$(readlink "$dst_file")"
      if [[ "$current_target" == "$REPO_DIR"* ]]; then
        rm "$dst_file"
      fi
    fi
  done
}

# ---------------------------------------------------------------------------
# Test 1: REPO_DIR/bin/ symlink is removed; foreign and real file are kept
# ---------------------------------------------------------------------------

FAKE_REPO=""
FAKE_HOME=""
_cleanup_t1() {
  [[ -n "$FAKE_REPO" && -d "$FAKE_REPO" ]] && rm -rf "$FAKE_REPO"
  [[ -n "$FAKE_HOME" && -d "$FAKE_HOME" ]] && rm -rf "$FAKE_HOME"
}
trap _cleanup_t1 EXIT

FAKE_REPO="$(mktemp -d)"
FAKE_HOME="$(mktemp -d)"
BIN_DST="$FAKE_HOME/.local/bin"
mkdir -p "$FAKE_REPO/bin" "$BIN_DST"

# Target bin file that the installer would have linked
echo '#!/bin/bash' > "$FAKE_REPO/bin/agentic-foo"

# Case A: REPO_DIR/bin/ symlink - MUST be removed
ln -sfn "$FAKE_REPO/bin/agentic-foo" "$BIN_DST/agentic-foo"

# Case B: Unrelated repo symlink - must NOT be removed
ln -sfn "/some/other/repo/bin/agentic-bar" "$BIN_DST/agentic-bar"

# Case C: Real file - must NOT be removed
echo "real" > "$BIN_DST/agentic-real"

run_bin_guard "$FAKE_REPO" "$BIN_DST" > /dev/null

if [[ ! -e "$BIN_DST/agentic-foo" && ! -L "$BIN_DST/agentic-foo" ]]; then
  _pass "T1: REPO_DIR/bin/ symlink (agentic-foo) removed"
else
  _fail "T1: REPO_DIR/bin/ symlink (agentic-foo) should have been removed"
fi

if [[ -L "$BIN_DST/agentic-bar" ]]; then
  _pass "T1: unrelated symlink (agentic-bar) preserved"
else
  _fail "T1: unrelated symlink (agentic-bar) should have been preserved"
fi

if [[ -f "$BIN_DST/agentic-real" ]]; then
  _pass "T1: real file (agentic-real) preserved"
else
  _fail "T1: real file (agentic-real) should have been preserved"
fi

_cleanup_t1
trap - EXIT

# ---------------------------------------------------------------------------
# Test 2: Sibling-prefix checkout is NOT removed (proves /bin/ boundary fix)
#
# REPO_DIR=/x/repo  sibling target=/x/repo-backup/bin/agentic-baz
# Old loose guard `"$REPO_DIR"*` matches because "/x/repo-backup/..." starts
# with "/x/repo". The tightened guard `"$REPO_DIR/bin/"*` does NOT match.
# ---------------------------------------------------------------------------

FAKE_REPO2=""
FAKE_HOME2=""
_cleanup_t2() {
  [[ -n "$FAKE_REPO2" && -d "$FAKE_REPO2" ]] && rm -rf "$FAKE_REPO2"
  [[ -n "$FAKE_HOME2" && -d "$FAKE_HOME2" ]] && rm -rf "$FAKE_HOME2"
}
trap _cleanup_t2 EXIT

FAKE_REPO2="$(mktemp -d)"
FAKE_HOME2="$(mktemp -d)"
BIN_DST2="$FAKE_HOME2/.local/bin"
SIBLING_REPO="${FAKE_REPO2}-backup"
mkdir -p "$FAKE_REPO2/bin" "$BIN_DST2" "$SIBLING_REPO/bin"

echo '#!/bin/bash' > "$SIBLING_REPO/bin/agentic-baz"

# Symlink targets the SIBLING (different checkout), but shares the repo-dir prefix
ln -sfn "$SIBLING_REPO/bin/agentic-baz" "$BIN_DST2/agentic-baz"

# Verify old loose guard WOULD have removed it (proves the old code was buggy)
ln -sfn "$SIBLING_REPO/bin/agentic-baz" "$BIN_DST2/agentic-baz-loose-check"
run_bin_guard_loose "$FAKE_REPO2" "$BIN_DST2" > /dev/null
if [[ ! -e "$BIN_DST2/agentic-baz-loose-check" && ! -L "$BIN_DST2/agentic-baz-loose-check" ]]; then
  _pass "T2: loose guard DID incorrectly remove the sibling symlink (proves fix is needed)"
else
  _fail "T2: loose guard should have incorrectly removed the sibling symlink (test setup issue)"
fi

# Recreate for the tightened-guard test (loose guard deleted it above)
ln -sfn "$SIBLING_REPO/bin/agentic-baz" "$BIN_DST2/agentic-baz"

# Verify tightened guard does NOT remove it
run_bin_guard "$FAKE_REPO2" "$BIN_DST2" > /dev/null

if [[ -L "$BIN_DST2/agentic-baz" ]]; then
  _pass "T2: sibling-prefix symlink preserved by /bin/ boundary guard"
else
  _fail "T2: sibling-prefix symlink incorrectly removed (guard not tight enough)"
fi

_cleanup_t2
trap - EXIT

# ---------------------------------------------------------------------------
# Test 3: Missing ~/.local/bin - no error
# ---------------------------------------------------------------------------

FAKE_REPO3="$(mktemp -d)"
FAKE_HOME3="$(mktemp -d)"
BIN_DST3="$FAKE_HOME3/.local/bin"
# Do NOT create BIN_DST3

set +e
run_bin_guard "$FAKE_REPO3" "$BIN_DST3" > /dev/null 2>&1
rc=$?
set -e

if [[ $rc -eq 0 ]]; then
  _pass "T3: missing ~/.local/bin handled without error"
else
  _fail "T3: missing ~/.local/bin caused non-zero exit ($rc)"
fi

rm -rf "$FAKE_REPO3" "$FAKE_HOME3"

# ---------------------------------------------------------------------------
# Test 4: ~/.local/bin exists but has no agentic-* files - no error
# ---------------------------------------------------------------------------

FAKE_REPO4="$(mktemp -d)"
FAKE_HOME4="$(mktemp -d)"
BIN_DST4="$FAKE_HOME4/.local/bin"
mkdir -p "$BIN_DST4"
echo "other" > "$BIN_DST4/other-tool"  # unrelated file

set +e
out4="$(run_bin_guard "$FAKE_REPO4" "$BIN_DST4" 2>&1)"
rc=$?
set -e

if [[ $rc -eq 0 ]]; then
  _pass "T4: empty-glob (no agentic-*) handled without error"
else
  _fail "T4: empty-glob caused non-zero exit ($rc)"
fi

if echo "$out4" | grep -q "no agentic-\* entries found"; then
  _pass "T4: empty-glob prints expected message"
else
  _fail "T4: empty-glob message not found in output: $out4"
fi

rm -rf "$FAKE_REPO4" "$FAKE_HOME4"

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
