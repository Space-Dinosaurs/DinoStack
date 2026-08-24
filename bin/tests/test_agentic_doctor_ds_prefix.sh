#!/usr/bin/env bash
# Purpose: Regression tests for the prefix-agnostic ~/.local/bin machinery in
#          bin/agentic-doctor - forward discovery of both agentic-* and ds-*
#          tools (BIN_TOOL_PREFIXES), plus the reverse-direction stale-link
#          detection/removal (check_local_bin_stale) added alongside it.
#          This is machinery for a LATER agentic-* -> ds-* rename; no tool
#          is actually renamed here.
#
# Public API: ./bin/tests/test_agentic_doctor_ds_prefix.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, mktemp, ln, readlink.
#
# Downstream consumers: developer running locally before commit; wired into
#                       the bin-sh-tests CI job via the bin/tests/test_*.sh
#                       glob (.github/workflows/bin-tests.yml).
#
# Failure modes: any test failure prints the failing assertion and exits 1.
#                Tests use isolated TEMP_HOME dirs with a fake ~/.claude,
#                fake ~/.agentic, and a fake repo bin/ - NEVER points at the
#                real ~/.claude or ~/.local/bin.
#
# Performance: <2 s wall time on a developer machine.

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOCTOR="$SCRIPT_DIR/agentic-doctor"

if [[ ! -x "$DOCTOR" ]]; then
  echo "FAIL: $DOCTOR not executable" >&2
  exit 1
fi

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
# Fixture: a fake DinoStack-looking repo with a bin/ dir containing both an
# agentic-* and a ds-* tool, plus a fake HOME with ~/.agentic config pointing
# at it. local_bin (~/.local/bin) starts out empty unless a test populates it.
# ---------------------------------------------------------------------------
setup_fixture() {
  TEMP_HOME="$(mktemp -d)"
  FAKE_REPO="$TEMP_HOME/fake-DinoStack"
  REAL_FAKE_REPO="$(python3 -c "import os; print(os.path.realpath('$FAKE_REPO'))")"

  mkdir -p "$FAKE_REPO/.git" "$FAKE_REPO/bin"

  # An existing agentic-* tool and a NEW ds-* tool, both real executable files.
  cat > "$FAKE_REPO/bin/agentic-kept" <<'EOF'
#!/usr/bin/env bash
echo kept
EOF
  chmod +x "$FAKE_REPO/bin/agentic-kept"

  cat > "$FAKE_REPO/bin/ds-newtool" <<'EOF'
#!/usr/bin/env bash
echo newtool
EOF
  chmod +x "$FAKE_REPO/bin/ds-newtool"

  # A non-tool file that must NEVER be picked up by either prefix scan.
  cat > "$FAKE_REPO/bin/_lib.py" <<'EOF'
# shared helper, not a CLI entry point
EOF

  mkdir -p "$TEMP_HOME/.agentic"
  cat > "$TEMP_HOME/.agentic/agentic-engineering-config.json" <<EOF
{
  "repo_dir": "$FAKE_REPO"
}
EOF
}

invoke_doctor() {
  # unset CLAUDE_CONFIG_DIR: a real value set in the invoking session would
  # make _plugins_dir() resolve OUTSIDE TEMP_HOME and silently scan the
  # real machine's plugins instead of these HOME-relative fixtures
  # (DS-198 round 3, Skeptic Major 2).
  (
    HOME="$TEMP_HOME"
    export HOME
    unset CLAUDE_CONFIG_DIR
    python3 "$DOCTOR" "$@"
  ) > "$TEMP_HOME/.out" 2>&1
  echo $? > "$TEMP_HOME/.exit"
}

# ---------------------------------------------------------------------------
# Test 1: read-only scan discovers BOTH agentic-kept and ds-newtool as
# missing ~/.local/bin links (proves prefix-agnostic forward discovery -
# goal (b) - and that a non-prefixed file like _lib.py is never surfaced).
# ---------------------------------------------------------------------------
setup_fixture
invoke_doctor
RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "1" ]]; then
  _pass "T1: read-only exits 1 (missing local_bin links are findings)"
else
  _fail "T1: expected exit 1, got $RC\n$OUT"
fi

if echo "$OUT" | grep -q "FIX symlink:.*agentic-kept.*(missing)"; then
  _pass "T1: agentic-kept discovered as a missing local_bin link"
else
  _fail "T1: agentic-kept not reported as missing\n$OUT"
fi

if echo "$OUT" | grep -q "FIX symlink:.*ds-newtool.*(missing)"; then
  _pass "T1: ds-newtool (ds-* prefix) discovered as a missing local_bin link"
else
  _fail "T1: ds-newtool not reported as missing - prefix-agnostic discovery broken\n$OUT"
fi

if echo "$OUT" | grep -q "_lib.py"; then
  _fail "T1: _lib.py must never be surfaced by the bin tool scan\n$OUT"
else
  _pass "T1: _lib.py correctly excluded from the bin tool scan"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 2: --fix creates ~/.local/bin symlinks for BOTH prefixes.
# ---------------------------------------------------------------------------
setup_fixture
invoke_doctor --fix
RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" || "$RC" == "2" ]]; then
  _pass "T2: --fix exits 0 or 2 (fix ran)"
else
  _fail "T2: expected exit 0 or 2, got $RC\n$OUT"
fi

KEPT_TARGET="$(readlink "$TEMP_HOME/.local/bin/agentic-kept" 2>/dev/null || echo "(not a link)")"
if [[ "$KEPT_TARGET" == "$FAKE_REPO/bin/agentic-kept" || "$KEPT_TARGET" == "$REAL_FAKE_REPO/bin/agentic-kept" ]]; then
  _pass "T2: agentic-kept linked into ~/.local/bin"
else
  _fail "T2: agentic-kept link target is '$KEPT_TARGET'"
fi

DS_TARGET="$(readlink "$TEMP_HOME/.local/bin/ds-newtool" 2>/dev/null || echo "(not a link)")"
if [[ "$DS_TARGET" == "$FAKE_REPO/bin/ds-newtool" || "$DS_TARGET" == "$REAL_FAKE_REPO/bin/ds-newtool" ]]; then
  _pass "T2: ds-newtool linked into ~/.local/bin (ds-* prefix)"
else
  _fail "T2: ds-newtool link target is '$DS_TARGET' - prefix-agnostic install repair broken"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 3: reverse-direction stale detection - a ~/.local/bin symlink whose
# raw target is rooted at repo_dir/bin but the target file no longer exists
# there is detected read-only, then removed by --fix, then a second
# read-only run exits 0 (idempotent).
# ---------------------------------------------------------------------------
setup_fixture
mkdir -p "$TEMP_HOME/.local/bin"
ln -s "$FAKE_REPO/bin/agentic-removed" "$TEMP_HOME/.local/bin/agentic-removed"
# Deliberately do NOT create $FAKE_REPO/bin/agentic-removed - simulates a
# tool that was renamed/removed upstream (the future ds-* rename scenario).

invoke_doctor
RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "1" ]]; then
  _pass "T3 read-only: stale reverse link is a finding (exits 1)"
else
  _fail "T3 read-only: expected exit 1, got $RC\n$OUT"
fi

if echo "$OUT" | grep -q "FIX symlink:.*agentic-removed.*(removed, stale)"; then
  _pass "T3 read-only: stale reverse link reported as removal candidate"
else
  _fail "T3 read-only: expected a '(removed, stale)' FIX line for agentic-removed\n$OUT"
fi

rm -rf "$TEMP_HOME"

setup_fixture
mkdir -p "$TEMP_HOME/.local/bin"
ln -s "$FAKE_REPO/bin/agentic-removed" "$TEMP_HOME/.local/bin/agentic-removed"

invoke_doctor --fix
RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ -L "$TEMP_HOME/.local/bin/agentic-removed" || -e "$TEMP_HOME/.local/bin/agentic-removed" ]]; then
  _fail "T3 --fix: agentic-removed should have been removed, but still exists"
else
  _pass "T3 --fix: stale reverse link was removed"
fi

# Second read-only run after --fix: this stale link is gone, but agentic-kept
# and ds-newtool are STILL missing from ~/.local/bin in this fixture (only
# --fix was run once, on the removal target), so a full exit-0 assertion
# would be a false negative. Assert narrowly: no local_bin_stale finding
# remains for agentic-removed specifically.
invoke_doctor
OUT2=$(cat "$TEMP_HOME/.out")
if echo "$OUT2" | grep -q "agentic-removed"; then
  _fail "T3 idempotent: agentic-removed still appears in output after removal\n$OUT2"
else
  _pass "T3 idempotent: agentic-removed no longer appears (link fully gone, not recreated)"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 4: reverse-direction safety - a real file, a live symlink pointing
# elsewhere, and a broken symlink pointing OUTSIDE repo_dir/bin must never
# be removed by check_local_bin_stale, even under --fix.
# ---------------------------------------------------------------------------
setup_fixture
mkdir -p "$TEMP_HOME/.local/bin"

# A real file (never a symlink) - must be left alone entirely.
printf 'real content\n' > "$TEMP_HOME/.local/bin/realfile"

# A live symlink pointing at an existing file OUTSIDE the repo - untouched.
EXTERNAL_DIR="$TEMP_HOME/external"
mkdir -p "$EXTERNAL_DIR"
printf 'external\n' > "$EXTERNAL_DIR/thing"
ln -s "$EXTERNAL_DIR/thing" "$TEMP_HOME/.local/bin/usertool"

# A BROKEN symlink whose target does NOT exist and is NOT rooted at
# repo_dir/bin (an operator's own unrelated broken link). Must be left
# alone - this is the case _is_ours() alone would have wrongly reclaimed.
ln -s "/nonexistent/elsewhere/thing" "$TEMP_HOME/.local/bin/foreigntool"

invoke_doctor --fix
OUT=$(cat "$TEMP_HOME/.out")

if [[ -f "$TEMP_HOME/.local/bin/realfile" ]] && [[ ! -L "$TEMP_HOME/.local/bin/realfile" ]]; then
  CONTENT="$(cat "$TEMP_HOME/.local/bin/realfile")"
  if [[ "$CONTENT" == "real content" ]]; then
    _pass "T4: real file untouched by --fix"
  else
    _fail "T4: real file content changed"
  fi
else
  _fail "T4: real file was removed or replaced by --fix"
fi

USERTOOL_TARGET="$(readlink "$TEMP_HOME/.local/bin/usertool" 2>/dev/null || echo "(removed)")"
if [[ "$USERTOOL_TARGET" == "$EXTERNAL_DIR/thing" ]]; then
  _pass "T4: live symlink pointing elsewhere untouched by --fix"
else
  _fail "T4: usertool symlink was changed/removed: '$USERTOOL_TARGET'"
fi

FOREIGN_TARGET="$(readlink "$TEMP_HOME/.local/bin/foreigntool" 2>/dev/null || echo "(removed)")"
if [[ "$FOREIGN_TARGET" == "/nonexistent/elsewhere/thing" ]]; then
  _pass "T4: broken symlink pointing outside repo_dir/bin untouched by --fix"
else
  _fail "T4: foreigntool (broken, non-repo target) was removed - unsafe over-reach: '$FOREIGN_TARGET'"
fi

if echo "$OUT" | grep -qE "(FIX|FAIL).*realfile"; then
  _fail "T4: real file must never appear as a FIX/FAIL finding\n$OUT"
else
  _pass "T4: real file never appears as a FIX/FAIL finding"
fi

if echo "$OUT" | grep -qE "(FIX|FAIL).*foreigntool"; then
  _fail "T4: foreign broken symlink must never appear as a FIX/FAIL finding\n$OUT"
else
  _pass "T4: foreign broken symlink never appears as a FIX/FAIL finding"
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Test 5: the "owned by the forward check" skip in check_local_bin_stale
# (bin/agentic-doctor ~lines 724-732) must suppress the DUPLICATE reverse
# recommendation for a link whose name matches a script still present in
# repo_dir/bin, while leaving the forward check's own repoint recommendation
# and repair intact.
#
# Fixture: ~/.local/bin/agentic-kept exists as a symlink whose raw target is
# a DIFFERENT, missing path under repo_dir/bin (agentic-kept-old, never
# created) - not the live repo_dir/bin/agentic-kept from setup_fixture. This
# is the only shape that reaches BOTH checks: the forward check
# (check_local_bin_symlinks) sees agentic-kept resolved != expected and
# recommends a repoint; the reverse check (check_local_bin_stale), absent
# its skip, would ALSO see a broken symlink whose raw target is lexically
# rooted at repo_dir/bin and recommend a removal for the very same link.
# ---------------------------------------------------------------------------
setup_fixture
mkdir -p "$TEMP_HOME/.local/bin"
ln -s "$FAKE_REPO/bin/agentic-kept-old" "$TEMP_HOME/.local/bin/agentic-kept"
# Deliberately do NOT create $FAKE_REPO/bin/agentic-kept-old.

invoke_doctor
OUT=$(cat "$TEMP_HOME/.out")

AGENTIC_KEPT_FIX_COUNT=$(echo "$OUT" | grep -c "FIX symlink:.*/agentic-kept ")
if [[ "$AGENTIC_KEPT_FIX_COUNT" == "1" ]]; then
  _pass "T5 read-only: exactly one FIX recommendation for agentic-kept (no duplicate)"
else
  _fail "T5 read-only: expected exactly 1 FIX recommendation for agentic-kept, got $AGENTIC_KEPT_FIX_COUNT\n$OUT"
fi

if echo "$OUT" | grep -qE "FIX symlink:.*/agentic-kept .*-> ($FAKE_REPO|$REAL_FAKE_REPO)/bin/agentic-kept$"; then
  _pass "T5 read-only: the one recommendation is the forward repoint, not a removal"
else
  _fail "T5 read-only: expected a forward repoint FIX line for agentic-kept\n$OUT"
fi

if echo "$OUT" | grep -q "FIX symlink:.*/agentic-kept .*(removed, stale)"; then
  _fail "T5 read-only: reverse check emitted a duplicate '(removed, stale)' recommendation for agentic-kept - the owned-by-forward-check skip is missing or broken\n$OUT"
else
  _pass "T5 read-only: no duplicate '(removed, stale)' recommendation for agentic-kept"
fi

rm -rf "$TEMP_HOME"

setup_fixture
mkdir -p "$TEMP_HOME/.local/bin"
ln -s "$FAKE_REPO/bin/agentic-kept-old" "$TEMP_HOME/.local/bin/agentic-kept"

invoke_doctor --fix
RC=$(cat "$TEMP_HOME/.exit")
OUT=$(cat "$TEMP_HOME/.out")

if [[ "$RC" == "0" || "$RC" == "2" ]]; then
  _pass "T5 --fix: exits 0 or 2 (fix ran)"
else
  _fail "T5 --fix: expected exit 0 or 2, got $RC\n$OUT"
fi

AGENTIC_KEPT_TARGET="$(readlink "$TEMP_HOME/.local/bin/agentic-kept" 2>/dev/null || echo "(removed)")"
if [[ "$AGENTIC_KEPT_TARGET" == "$FAKE_REPO/bin/agentic-kept" || "$AGENTIC_KEPT_TARGET" == "$REAL_FAKE_REPO/bin/agentic-kept" ]]; then
  _pass "T5 --fix: agentic-kept end state is REPOINTED at the live script (not removed)"
else
  _fail "T5 --fix: agentic-kept end state is '$AGENTIC_KEPT_TARGET' - expected a repoint to $FAKE_REPO/bin/agentic-kept, not a removal. If this failed, --fix removed a link that should have been repointed - the reverse check ran ahead of, or instead of, the forward check's repair."
fi

rm -rf "$TEMP_HOME"

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
echo
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
