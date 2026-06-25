#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Tests for .cursor/install.sh and .opencode/install.sh
#          symlink-convergence behaviour (mirrors .claude/tests/install-converge.test.sh).
#
# Public API: bash .cursor/tests/install-converge.test.sh
#             Exits 0 on all pass, non-zero on any failure.
#
# Upstream deps: bash, python3, ln, readlink, mktemp.
#
# Downstream consumers: developer running locally; CI.
#
# Failure modes: each failing test is printed to stderr; exits 1 if any fail.
#                All side effects use TEMP HOME dirs; the real ~/.cursor,
#                ~/.config/opencode, and ~/.local/bin are NEVER touched.
#
# Performance: ~10 s wall time (runs install.sh multiple times with fake HOME).
#
# Regression coverage:
#   - Stale "ours" symlink (target under .../DinoStack/...) is RE-POINTED.
#   - Broken "ours" symlink is re-pointed.
#   - Real file at dst is left untouched (skip).
#   - Symlink pointing outside any methodology checkout is skipped.
#   - --dry-run makes no filesystem changes.
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CURSOR_INSTALL="$REPO_DIR/.cursor/install.sh"
OPENCODE_INSTALL="$REPO_DIR/.opencode/install.sh"

PASS=0
FAIL=0
FAKE_HOME=""

_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

_cleanup() {
  if [[ -n "$FAKE_HOME" && -d "$FAKE_HOME" ]]; then
    rm -rf "$FAKE_HOME"
  fi
}
trap _cleanup EXIT

# ---------------------------------------------------------------------------
# Source for a concrete fixture .mdc file (cursor rules directory).
# ---------------------------------------------------------------------------
CURSOR_RULES_SRC="$REPO_DIR/.cursor/rules"
_pick_cursor_fixture() {
  local f
  for f in "$CURSOR_RULES_SRC"/*.mdc; do
    [[ -e "$f" ]] && { echo "$f"; return 0; }
  done
  echo ""
}
CURSOR_FIXTURE_SRC="$(_pick_cursor_fixture)"
if [[ -z "$CURSOR_FIXTURE_SRC" ]]; then
  echo "SKIP: no .mdc fixture file found in $CURSOR_RULES_SRC - cursor tests skipped"
  SKIP_CURSOR=true
else
  SKIP_CURSOR=false
  CURSOR_FIXTURE_NAME="$(basename "$CURSOR_FIXTURE_SRC")"
fi

# ---------------------------------------------------------------------------
# Source for a concrete fixture .md file (opencode agents directory).
# Note: opencode/agents is build-generated but we are testing the symlink_files
# predicate with the pattern; use the agents dir as the fixture source.
# ---------------------------------------------------------------------------
OPENCODE_AGENTS_SRC="$REPO_DIR/.opencode/agents"
_pick_opencode_fixture() {
  local f
  for f in "$OPENCODE_AGENTS_SRC"/*.md; do
    [[ -e "$f" ]] && { echo "$f"; return 0; }
  done
  echo ""
}
OPENCODE_FIXTURE_SRC="$(_pick_opencode_fixture)"
if [[ -z "$OPENCODE_FIXTURE_SRC" ]]; then
  echo "SKIP: no .md fixture in $OPENCODE_AGENTS_SRC - opencode symlink_files test skipped"
  SKIP_OPENCODE=true
else
  SKIP_OPENCODE=false
  OPENCODE_FIXTURE_NAME="$(basename "$OPENCODE_FIXTURE_SRC")"
fi

# ---------------------------------------------------------------------------
# _run_cursor FAKE_HOME [extra args...]
# Runs .cursor/install.sh with a fake HOME, capturing output.
# Passes --mode=opt-out --profile=default to suppress interactive prompts.
# Wires SKIP_IDENTITY so the identity step does not attempt ssh/gh operations.
# ---------------------------------------------------------------------------
_run_cursor() {
  local fake_home="$1"
  shift
  mkdir -p "$fake_home/.cursor/rules"
  mkdir -p "$fake_home/.local/bin"
  HOME="$fake_home" AE_NO_IDENTITY=true bash "$CURSOR_INSTALL" \
    --mode=opt-out --profile=default --no-identity "$@" \
    < /dev/null > "$fake_home/.install_out" 2>&1
  return $?
}

# ---------------------------------------------------------------------------
# _run_opencode FAKE_HOME [extra args...]
# Runs .opencode/install.sh with a fake HOME, capturing output.
# ---------------------------------------------------------------------------
_run_opencode() {
  local fake_home="$1"
  shift
  mkdir -p "$fake_home/.config/opencode/agents"
  mkdir -p "$fake_home/.config/opencode/skills"
  mkdir -p "$fake_home/.local/bin"
  HOME="$fake_home" AE_NO_IDENTITY=true bash "$OPENCODE_INSTALL" \
    --mode=opt-out --profile=default --no-identity "$@" \
    < /dev/null > "$fake_home/.install_out" 2>&1
  return $?
}

# ===========================================================================
# CURSOR TESTS
# ===========================================================================

if [[ "$SKIP_CURSOR" != "true" ]]; then
  echo ""
  echo "--- cursor symlink_files tests ---"

  # -------------------------------------------------------------------------
  # Cursor (a): stale "ours" symlink gets re-pointed.
  # -------------------------------------------------------------------------
  FAKE_HOME="$(mktemp -d)"
  mkdir -p "$FAKE_HOME/.cursor/rules"
  FAKE_OTHER="/tmp/other-DinoStack/path/$CURSOR_FIXTURE_NAME"
  ln -s "$FAKE_OTHER" "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME"

  _run_cursor "$FAKE_HOME" || true

  if [[ -L "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME" ]]; then
    actual_target="$(readlink "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME")"
    if [[ "$actual_target" == "$CURSOR_FIXTURE_SRC" ]]; then
      _pass "cursor (a): stale 'ours' symlink re-pointed"
    else
      _fail "cursor (a): expected '$CURSOR_FIXTURE_SRC', got '$actual_target'"
    fi
  else
    _fail "cursor (a): $CURSOR_FIXTURE_NAME is not a symlink after install"
  fi
  rm -rf "$FAKE_HOME"

  # -------------------------------------------------------------------------
  # Cursor (b): broken "ours" symlink gets re-pointed.
  # -------------------------------------------------------------------------
  FAKE_HOME="$(mktemp -d)"
  mkdir -p "$FAKE_HOME/.cursor/rules"
  ln -s "/nonexistent/DinoStack/path/$CURSOR_FIXTURE_NAME" "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME"

  _run_cursor "$FAKE_HOME" || true

  if [[ -L "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME" ]]; then
    actual_target="$(readlink "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME")"
    if [[ "$actual_target" == "$CURSOR_FIXTURE_SRC" ]]; then
      _pass "cursor (b): broken 'ours' symlink re-pointed"
    else
      _fail "cursor (b): expected '$CURSOR_FIXTURE_SRC', got '$actual_target'"
    fi
  else
    _fail "cursor (b): $CURSOR_FIXTURE_NAME is not a symlink after install"
  fi
  rm -rf "$FAKE_HOME"

  # -------------------------------------------------------------------------
  # Cursor (c): real file at dst is left untouched.
  # -------------------------------------------------------------------------
  FAKE_HOME="$(mktemp -d)"
  mkdir -p "$FAKE_HOME/.cursor/rules"
  REAL_FILE_CONTENT="# real user file - must not be clobbered"
  printf '%s\n' "$REAL_FILE_CONTENT" > "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME"

  _run_cursor "$FAKE_HOME" || true

  if [[ -f "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME" ]] && \
     [[ ! -L "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME" ]]; then
    actual_content="$(cat "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME")"
    if [[ "$actual_content" == "$REAL_FILE_CONTENT" ]]; then
      _pass "cursor (c): real file at dst untouched"
    else
      _fail "cursor (c): real file content was altered"
    fi
  else
    _fail "cursor (c): real file was replaced by a symlink"
  fi
  rm -rf "$FAKE_HOME"

  # -------------------------------------------------------------------------
  # Cursor (d): out-of-checkout symlink is left untouched.
  # -------------------------------------------------------------------------
  FAKE_HOME="$(mktemp -d)"
  mkdir -p "$FAKE_HOME/.cursor/rules"
  OUTSIDE_TARGET="/tmp/user/unrelated/$CURSOR_FIXTURE_NAME"
  ln -s "$OUTSIDE_TARGET" "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME"

  _run_cursor "$FAKE_HOME" || true

  if [[ -L "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME" ]]; then
    actual_target="$(readlink "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME")"
    if [[ "$actual_target" == "$OUTSIDE_TARGET" ]]; then
      _pass "cursor (d): out-of-checkout symlink untouched"
    else
      _fail "cursor (d): out-of-checkout symlink was changed to '$actual_target'"
    fi
  else
    _fail "cursor (d): $CURSOR_FIXTURE_NAME is no longer a symlink"
  fi
  rm -rf "$FAKE_HOME"

  # -------------------------------------------------------------------------
  # Cursor (e): --dry-run changes nothing.
  # -------------------------------------------------------------------------
  FAKE_HOME="$(mktemp -d)"
  mkdir -p "$FAKE_HOME/.cursor/rules"
  ln -s "/nonexistent/DinoStack/old/$CURSOR_FIXTURE_NAME" "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME"
  OLD_TARGET="$(readlink "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME")"

  _run_cursor "$FAKE_HOME" --dry-run || true

  if [[ -L "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME" ]]; then
    actual_target="$(readlink "$FAKE_HOME/.cursor/rules/$CURSOR_FIXTURE_NAME")"
    if [[ "$actual_target" == "$OLD_TARGET" ]]; then
      _pass "cursor (e): --dry-run left symlink unchanged"
    else
      _fail "cursor (e): --dry-run changed symlink to '$actual_target'"
    fi
  else
    _fail "cursor (e): $CURSOR_FIXTURE_NAME is no longer a symlink after --dry-run"
  fi

  if grep -q "would re-point" "$FAKE_HOME/.install_out" 2>/dev/null; then
    _pass "cursor (e): --dry-run output includes 'would re-point'"
  else
    _fail "cursor (e): --dry-run output missing 'would re-point'"
  fi
  rm -rf "$FAKE_HOME"
fi

# ===========================================================================
# OPENCODE TESTS
# ===========================================================================

if [[ "$SKIP_OPENCODE" != "true" ]]; then
  echo ""
  echo "--- opencode symlink_files tests ---"

  OPENCODE_AGENTS_DST_SUBPATH=".config/opencode/agents"

  # -------------------------------------------------------------------------
  # OpenCode (a): stale "ours" symlink gets re-pointed.
  # -------------------------------------------------------------------------
  FAKE_HOME="$(mktemp -d)"
  mkdir -p "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH"
  FAKE_OTHER_OC="/tmp/other-DinoStack/oc/$OPENCODE_FIXTURE_NAME"
  ln -s "$FAKE_OTHER_OC" "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME"

  _run_opencode "$FAKE_HOME" || true

  if [[ -L "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME" ]]; then
    actual_target="$(readlink "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME")"
    if [[ "$actual_target" == "$OPENCODE_FIXTURE_SRC" ]]; then
      _pass "opencode (a): stale 'ours' symlink re-pointed"
    else
      _fail "opencode (a): expected '$OPENCODE_FIXTURE_SRC', got '$actual_target'"
    fi
  else
    _fail "opencode (a): $OPENCODE_FIXTURE_NAME is not a symlink after install"
  fi
  rm -rf "$FAKE_HOME"

  # -------------------------------------------------------------------------
  # OpenCode (b): broken "ours" symlink gets re-pointed.
  # -------------------------------------------------------------------------
  FAKE_HOME="$(mktemp -d)"
  mkdir -p "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH"
  ln -s "/nonexistent/DinoStack/oc/$OPENCODE_FIXTURE_NAME" \
        "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME"

  _run_opencode "$FAKE_HOME" || true

  if [[ -L "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME" ]]; then
    actual_target="$(readlink "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME")"
    if [[ "$actual_target" == "$OPENCODE_FIXTURE_SRC" ]]; then
      _pass "opencode (b): broken 'ours' symlink re-pointed"
    else
      _fail "opencode (b): expected '$OPENCODE_FIXTURE_SRC', got '$actual_target'"
    fi
  else
    _fail "opencode (b): $OPENCODE_FIXTURE_NAME is not a symlink after install"
  fi
  rm -rf "$FAKE_HOME"

  # -------------------------------------------------------------------------
  # OpenCode (c): real file at dst is left untouched.
  # -------------------------------------------------------------------------
  FAKE_HOME="$(mktemp -d)"
  mkdir -p "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH"
  REAL_FILE_CONTENT_OC="# real opencode user file - must not be clobbered"
  printf '%s\n' "$REAL_FILE_CONTENT_OC" > "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME"

  _run_opencode "$FAKE_HOME" || true

  if [[ -f "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME" ]] && \
     [[ ! -L "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME" ]]; then
    actual_content="$(cat "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME")"
    if [[ "$actual_content" == "$REAL_FILE_CONTENT_OC" ]]; then
      _pass "opencode (c): real file at dst untouched"
    else
      _fail "opencode (c): real file content was altered"
    fi
  else
    _fail "opencode (c): real file was replaced by a symlink"
  fi
  rm -rf "$FAKE_HOME"

  # -------------------------------------------------------------------------
  # OpenCode (d): out-of-checkout symlink is left untouched.
  # -------------------------------------------------------------------------
  FAKE_HOME="$(mktemp -d)"
  mkdir -p "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH"
  OUTSIDE_TARGET_OC="/tmp/user/totally-unrelated-oc/$OPENCODE_FIXTURE_NAME"
  ln -s "$OUTSIDE_TARGET_OC" "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME"

  _run_opencode "$FAKE_HOME" || true

  if [[ -L "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME" ]]; then
    actual_target="$(readlink "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME")"
    if [[ "$actual_target" == "$OUTSIDE_TARGET_OC" ]]; then
      _pass "opencode (d): out-of-checkout symlink untouched"
    else
      _fail "opencode (d): out-of-checkout symlink was changed to '$actual_target'"
    fi
  else
    _fail "opencode (d): $OPENCODE_FIXTURE_NAME is no longer a symlink"
  fi
  rm -rf "$FAKE_HOME"

  # -------------------------------------------------------------------------
  # OpenCode (e): --dry-run changes nothing.
  # -------------------------------------------------------------------------
  FAKE_HOME="$(mktemp -d)"
  mkdir -p "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH"
  ln -s "/nonexistent/DinoStack/old-oc/$OPENCODE_FIXTURE_NAME" \
        "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME"
  OLD_TARGET_OC="$(readlink "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME")"

  _run_opencode "$FAKE_HOME" --dry-run || true

  if [[ -L "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME" ]]; then
    actual_target="$(readlink "$FAKE_HOME/$OPENCODE_AGENTS_DST_SUBPATH/$OPENCODE_FIXTURE_NAME")"
    if [[ "$actual_target" == "$OLD_TARGET_OC" ]]; then
      _pass "opencode (e): --dry-run left symlink unchanged"
    else
      _fail "opencode (e): --dry-run changed symlink to '$actual_target'"
    fi
  else
    _fail "opencode (e): $OPENCODE_FIXTURE_NAME is no longer a symlink after --dry-run"
  fi

  if grep -q "would re-point" "$FAKE_HOME/.install_out" 2>/dev/null; then
    _pass "opencode (e): --dry-run output includes 'would re-point'"
  else
    _fail "opencode (e): --dry-run output missing 'would re-point'"
  fi
  rm -rf "$FAKE_HOME"
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
