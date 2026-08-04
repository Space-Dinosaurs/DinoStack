#!/usr/bin/env bash
# Purpose: Regression test for the ~/.local/bin/agentic-*/ds-* symlink removal
#          guard added to all adapter uninstall.sh scripts. run_bin_guard is a
#          verbatim mirror of the for-loop block in .claude/uninstall.sh - see
#          Test 5, which mechanically enforces that the mirror cannot silently
#          drift from the production block again the way it did once already
#          (round 1 widened the production glob to ds-* and left this mirror
#          on the old single agentic-* glob with no gate to catch it).
#
# Public API: ./bin/tests/test_uninstall_bin_symlink.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, mktemp, git, awk.
#
# Downstream consumers: developer running locally before commit; CI.
#
# Failure modes: any assertion failure prints the failing assertion and exits 1.
#                A temporary fake HOME and fake repo dir are used; the real
#                ~/.local/bin is never touched. Test 5 reads (never writes)
#                the real .claude/uninstall.sh and this file's own source.
#
# Performance: < 1 s wall time (pure shell, no network).
#
# Regression coverage:
#   - fix(uninstall): remove ~/.local/bin/agentic-*/ds-* symlinks pointing
#     into the repo. The guard must require a $REPO_DIR/bin/ prefix, not just
#     $REPO_DIR, so a sibling checkout under $REPO_DIR-backup/bin/ is NOT
#     removed. The sibling-prefix test would FAIL under the original loose
#     guard `"$REPO_DIR"*` and must PASS after the `/bin/` boundary fix.
#   - Test 5 (mirror-sync guard): run_bin_guard's for-loop body must be
#     byte-identical (modulo leading/trailing whitespace) to the current
#     production for-loop block in .claude/uninstall.sh, so a future glob or
#     ownership-guard change to production that is not mirrored here fails
#     loudly instead of leaving this file's coverage silently stale.
#   - zsh compatibility: an unmatched glob (e.g. a ~/.local/bin with no
#     agentic-*/ds-* entries) must not abort the loop under zsh, which
#     treats an unmatched glob as an error by default (NOMATCH) unlike bash,
#     which leaves it as a literal string that the `[[ -e ]]` guard filters.
#     run_bin_guard/run_bin_guard_loose opt into `nullglob` for the duration
#     of the call, under zsh only, so an unmatched pattern expands to zero
#     words instead of erroring - this also fixes this file's own
#     pre-existing zsh baseline failure (Test 4), which was this exact class.

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

# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------

# run_bin_guard <REPO_DIR> <BIN_DST>
# Executes the exact guard logic from the uninstall.sh bin-removal block -
# see Test 5 below, which mechanically asserts the for-loop body (from the
# "for dst_file in ...agentic-*...ds-*...; do" line through its "done") is
# byte-identical (modulo leading/trailing whitespace) to the current
# production block in .claude/uninstall.sh. Do not hand-edit the loop body
# without also updating production (or vice versa) - Test 5 will catch the
# drift, but keep them in sync rather than relying on that as the only
# guard-rail.
run_bin_guard() {
  local REPO_DIR="$1"
  local BIN_DST="$2"

  # zsh treats an unmatched glob as an error (NOMATCH) by default, unlike
  # bash, which leaves it as a literal string filtered out below by the
  # `[[ -e ]]` guard. `nullglob` makes zsh behave like bash here: an
  # unmatched pattern expands to zero words. `local_options` auto-reverts
  # this at function return, so it never affects the caller. No-op under
  # bash (this whole block never executes there).
  if [[ -n "${ZSH_VERSION:-}" ]]; then
    setopt local_options nullglob
  fi

  if [[ ! -d "$BIN_DST" ]]; then
    echo "  [skip] ~/.local/bin not found"
    return
  fi

  local _found_any=false
  local dst_file name current_target
  for dst_file in "$BIN_DST"/agentic-* "$BIN_DST"/ds-*; do
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
    echo "  = no agentic-*/ds-* entries found in ~/.local/bin"
  fi
}

# run_bin_guard_loose <REPO_DIR> <BIN_DST>
# Executes the OLD loose guard (`"$REPO_DIR"*`) to prove the sibling-prefix
# case would have failed under the previous code. Intentionally still uses
# the single agentic-* glob (pre-widening) - this is the retired code path
# being demonstrated, not the current production block, so it is NOT
# covered by Test 5's equivalence check.
run_bin_guard_loose() {
  local REPO_DIR="$1"
  local BIN_DST="$2"

  if [[ -n "${ZSH_VERSION:-}" ]]; then
    setopt local_options nullglob
  fi

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
echo '#!/bin/bash' > "$FAKE_REPO/bin/ds-foo"

# Case A: REPO_DIR/bin/ symlink - MUST be removed
ln -sfn "$FAKE_REPO/bin/agentic-foo" "$BIN_DST/agentic-foo"

# Case A2: ds-*-prefixed REPO_DIR/bin/ symlink - MUST also be removed. This
# is the direct coverage for the widened glob (Test 5 below only proves the
# loop TEXT matches production; this proves the widened glob actually
# behaves as intended at runtime).
ln -sfn "$FAKE_REPO/bin/ds-foo" "$BIN_DST/ds-foo"

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

if [[ ! -e "$BIN_DST/ds-foo" && ! -L "$BIN_DST/ds-foo" ]]; then
  _pass "T1: REPO_DIR/bin/ ds-*-prefixed symlink (ds-foo) removed"
else
  _fail "T1: REPO_DIR/bin/ ds-*-prefixed symlink (ds-foo) should have been removed"
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
# Test 4: ~/.local/bin exists but has no agentic-*/ds-* files - no error.
# Also the direct regression coverage for the zsh unmatched-glob class: this
# is the case (a populated BIN_DST with zero matching entries) that used to
# abort this file under zsh before the nullglob guard was added to
# run_bin_guard.
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
  _pass "T4: empty-glob (no agentic-*/ds-*) handled without error"
else
  _fail "T4: empty-glob caused non-zero exit ($rc): $out4"
fi

if echo "$out4" | grep -q "no agentic-\*/ds-\* entries found"; then
  _pass "T4: empty-glob prints expected message"
else
  _fail "T4: empty-glob message not found in output: $out4"
fi

rm -rf "$FAKE_REPO4" "$FAKE_HOME4"

# ---------------------------------------------------------------------------
# Test 5 (mirror-sync guard): run_bin_guard's for-loop body must be
# byte-identical (modulo per-line leading/trailing whitespace) to the
# current production for-loop block in .claude/uninstall.sh. This is the
# "keep in sync" enforcement this mirror lacked - it fails whenever a future
# production change to the glob or ownership-guard logic is not mirrored
# here, instead of silently leaving this file's coverage stale.
#
# Extraction: capture from the line containing the two-glob for-loop
# declaration through its matching "done" (inclusive), then normalize by
# stripping leading/trailing whitespace per line and dropping blank lines.
# Applied identically to .claude/uninstall.sh (the production source of
# truth) and to this file's own source (via $0), so it self-locates
# run_bin_guard's loop without a hardcoded line range.
# ---------------------------------------------------------------------------

PROD_FILE="$REPO_DIR/.claude/uninstall.sh"
SELF_FILE="$REPO_DIR/bin/tests/test_uninstall_bin_symlink.sh"

_extract_glob_loop_block() {
  awk '
    /for dst_file in "\$BIN_DST"\/agentic-\* "\$BIN_DST"\/ds-\*; do/ { capture=1 }
    capture { print }
    capture && /^[[:space:]]*done[[:space:]]*$/ { exit }
  ' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^$/d'
}

PROD_GLOB_BLOCK="$(_extract_glob_loop_block "$PROD_FILE")"
MIRROR_GLOB_BLOCK="$(_extract_glob_loop_block "$SELF_FILE")"

if [[ -z "$PROD_GLOB_BLOCK" ]]; then
  _fail "T5: could not locate the production for-loop block in .claude/uninstall.sh (extraction pattern stale?)"
elif [[ -z "$MIRROR_GLOB_BLOCK" ]]; then
  _fail "T5: could not locate the mirrored for-loop block in run_bin_guard (extraction pattern stale?)"
elif [[ "$PROD_GLOB_BLOCK" == "$MIRROR_GLOB_BLOCK" ]]; then
  _pass "T5: run_bin_guard's for-loop body matches .claude/uninstall.sh's production block verbatim"
else
  _fail "T5: run_bin_guard has drifted from .claude/uninstall.sh's production for-loop block
--- production (.claude/uninstall.sh) ---
$PROD_GLOB_BLOCK
--- mirror (run_bin_guard) ---
$MIRROR_GLOB_BLOCK"
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
