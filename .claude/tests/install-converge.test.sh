#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Tests for .claude/install.sh symlink-convergence and guarded
#          repo_dir write (Changes 1-3 in the converging-symlinks PR).
#
# Public API: bash .claude/tests/install-converge.test.sh
#             Exits 0 on all pass, non-zero on any failure.
#
# Upstream deps: bash, python3, git, ln, readlink, mktemp.
#
# Downstream consumers: developer running locally; CI.
#
# Failure modes: failures print the failing test name and exit 1.
#                All side effects use TEMP HOME dirs; the real ~/.claude and
#                ~/.agentic are NEVER touched.
#
# Performance: ~10 s wall time (runs install.sh multiple times with fake HOME).
#
# Regression coverage:
#   - Change 1: stale "ours" symlink (target under .../DinoStack/...) is
#     RE-POINTED rather than skipped.
#   - Change 1: broken "ours" symlink is re-pointed.
#   - Change 1: a real file at dst is left untouched (skip).
#   - Change 1: a symlink pointing outside any methodology checkout is skipped.
#   - Change 2: --dry-run makes no filesystem changes.
#   - Change 3: clobber guard - valid DIFFERENT repo_dir is NOT overwritten;
#     absent/invalid repo_dir IS written.
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_DIR/.claude/install.sh"

if [[ ! -f "$INSTALL_SH" ]]; then
  echo "FAIL: $INSTALL_SH not found" >&2
  exit 1
fi

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
# Helper: run install.sh with a temp HOME, capturing output.
# Passes --mode=opt-out --profile=default to suppress interactive prompts.
# Extra args are passed through.
# ---------------------------------------------------------------------------
_run_install() {
  local fake_home="$1"
  shift
  # Ensure the fake HOME has the minimal ~/.agentic dir so repo-dir.sh works.
  mkdir -p "$fake_home/.agentic"
  # Run install.sh with fake HOME; stdin is /dev/null to skip TTY prompts.
  HOME="$fake_home" bash "$INSTALL_SH" --mode=opt-out --profile=default "$@" \
    < /dev/null > "$fake_home/.install_out" 2>&1
  return $?
}

# Source dir that install.sh will symlink FROM (agents dir used as a concrete target).
AGENTS_SRC="$REPO_DIR/.claude/agents"

# Pick one .md file from agents/ to use as a concrete fixture target.
_pick_fixture_file() {
  local f
  for f in "$AGENTS_SRC"/*.md; do
    [[ -e "$f" ]] && { echo "$f"; return 0; }
  done
  echo ""
}

FIXTURE_SRC="$(_pick_fixture_file)"
if [[ -z "$FIXTURE_SRC" ]]; then
  echo "FAIL: no .md fixture file found in $AGENTS_SRC" >&2
  exit 1
fi
FIXTURE_NAME="$(basename "$FIXTURE_SRC")"

# ===========================================================================
# Test cases
# ===========================================================================

# ---------------------------------------------------------------------------
# Case (a): stale "ours" symlink (target under fake .../DinoStack/...) gets
#           RE-POINTED to the correct src.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/agents"
# Create a fake "other DinoStack checkout" path (doesn't need to exist for
# the ownership predicate - just needs to match */DinoStack/*).
FAKE_OTHER="/tmp/other-DinoStack/path/to/$FIXTURE_NAME"
ln -s "$FAKE_OTHER" "$FAKE_HOME/.claude/agents/$FIXTURE_NAME"

_run_install "$FAKE_HOME" || true

# After install, the symlink should now point to the real src.
if [[ -L "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]]; then
  actual_target="$(readlink "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"
  if [[ "$actual_target" == "$FIXTURE_SRC" ]]; then
    _pass "case (a): stale 'ours' symlink re-pointed"
  else
    _fail "case (a): expected target '$FIXTURE_SRC', got '$actual_target'"
  fi
else
  _fail "case (a): $FIXTURE_NAME is not a symlink after install"
fi

# Also verify that the install output mentioned re-pointing (~ line).
if grep -q "~ $FIXTURE_NAME" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (a): install output includes re-point indicator"
else
  _fail "case (a): install output did not include '~ $FIXTURE_NAME' indicator"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (b): broken "ours" symlink (target under DinoStack, but file is gone)
#           gets RE-POINTED.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/agents"
# A symlink under a methodology path that does not actually exist.
ln -s "/nonexistent/DinoStack/path/$FIXTURE_NAME" "$FAKE_HOME/.claude/agents/$FIXTURE_NAME"

_run_install "$FAKE_HOME" || true

if [[ -L "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]]; then
  actual_target="$(readlink "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"
  if [[ "$actual_target" == "$FIXTURE_SRC" ]]; then
    _pass "case (b): broken 'ours' symlink re-pointed"
  else
    _fail "case (b): expected target '$FIXTURE_SRC', got '$actual_target'"
  fi
else
  _fail "case (b): $FIXTURE_NAME is not a symlink after install"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (c): a REAL file at dst is left untouched (skip).
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/agents"
REAL_FILE_CONTENT="# real user file - must not be clobbered"
printf '%s\n' "$REAL_FILE_CONTENT" > "$FAKE_HOME/.claude/agents/$FIXTURE_NAME"

_run_install "$FAKE_HOME" || true

# Must still be a regular file, not a symlink.
if [[ -f "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]] && [[ ! -L "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]]; then
  actual_content="$(cat "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"
  if [[ "$actual_content" == "$REAL_FILE_CONTENT" ]]; then
    _pass "case (c): real file at dst untouched"
  else
    _fail "case (c): real file content was altered"
  fi
else
  _fail "case (c): real file was replaced by a symlink"
fi

# Also check the install output says "skipping" for this file.
if grep -q "! $FIXTURE_NAME" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (c): install output indicates skip for real file"
else
  _fail "case (c): install output did not mention skip for '$FIXTURE_NAME'"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (d): symlink pointing OUTSIDE any methodology checkout is left untouched.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/agents"
# Target is outside any DinoStack path (no DinoStack component).
OUTSIDE_TARGET="/tmp/user/totally-unrelated/$FIXTURE_NAME"
ln -s "$OUTSIDE_TARGET" "$FAKE_HOME/.claude/agents/$FIXTURE_NAME"

_run_install "$FAKE_HOME" || true

# Symlink should still point to the original outside target.
if [[ -L "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]]; then
  actual_target="$(readlink "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"
  if [[ "$actual_target" == "$OUTSIDE_TARGET" ]]; then
    _pass "case (d): out-of-checkout symlink untouched"
  else
    _fail "case (d): out-of-checkout symlink was changed to '$actual_target'"
  fi
else
  _fail "case (d): $FIXTURE_NAME is no longer a symlink (was clobbered)"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (e): --dry-run changes nothing.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.claude/agents"
# Set up a stale "ours" symlink that would normally be re-pointed.
ln -s "/nonexistent/DinoStack/old/$FIXTURE_NAME" "$FAKE_HOME/.claude/agents/$FIXTURE_NAME"
OLD_TARGET="$(readlink "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"

_run_install "$FAKE_HOME" --dry-run || true

# Symlink must NOT have been changed.
if [[ -L "$FAKE_HOME/.claude/agents/$FIXTURE_NAME" ]]; then
  actual_target="$(readlink "$FAKE_HOME/.claude/agents/$FIXTURE_NAME")"
  if [[ "$actual_target" == "$OLD_TARGET" ]]; then
    _pass "case (e): --dry-run left symlink unchanged"
  else
    _fail "case (e): --dry-run changed symlink to '$actual_target' (expected '$OLD_TARGET')"
  fi
else
  _fail "case (e): $FIXTURE_NAME is no longer a symlink after --dry-run"
fi

# Dry-run output should mention "would re-point".
if grep -q "would re-point" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (e): --dry-run output includes 'would re-point'"
else
  _fail "case (e): --dry-run output did not include 'would re-point'"
fi

# The repo_dir config file must NOT be created or modified under --dry-run.
if [[ ! -f "$FAKE_HOME/.agentic/agentic-engineering-config.json" ]]; then
  _pass "case (e): --dry-run did not create the repo_dir config file"
else
  _fail "case (e): --dry-run created ~/.agentic/agentic-engineering-config.json (must not mutate config)"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (f1): clobber guard - config with a valid DIFFERENT repo_dir is NOT
#            overwritten; a warning is printed.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.agentic"

# Create a fake "other valid repo" that passes validate_repo_dir (a git repo).
FAKE_OTHER_REPO="$(mktemp -d)"
git -C "$FAKE_OTHER_REPO" init -q
git -C "$FAKE_OTHER_REPO" commit --allow-empty -q -m "init" 2>/dev/null || true

# Write it as the existing repo_dir in the config.
python3 - "$FAKE_HOME/.agentic/agentic-engineering-config.json" "$FAKE_OTHER_REPO" <<'PYEOF'
import json, sys, os
cfg, repo_dir = sys.argv[1], sys.argv[2]
with open(cfg, "w") as f:
    json.dump({"repo_dir": repo_dir}, f, indent=2)
    f.write("\n")
PYEOF

_run_install "$FAKE_HOME" || true

# Config must still contain the original other repo_dir.
actual_repo_dir="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$FAKE_HOME/.agentic/agentic-engineering-config.json" 2>/dev/null)"

if [[ "$actual_repo_dir" == "$FAKE_OTHER_REPO" ]]; then
  _pass "case (f1): valid different repo_dir not overwritten"
else
  _fail "case (f1): repo_dir was changed to '$actual_repo_dir' (expected '$FAKE_OTHER_REPO')"
fi

# Install output (stderr merged into stdout via 2>&1 in _run_install) should
# contain the warning.
if grep -q "warning:" "$FAKE_HOME/.install_out" 2>/dev/null; then
  _pass "case (f1): warning printed for different valid repo_dir"
else
  _fail "case (f1): no warning printed for different valid repo_dir"
fi

rm -rf "$FAKE_OTHER_REPO" "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (f2): absent repo_dir in config IS written.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.agentic"
# Write config with no repo_dir key.
python3 - "$FAKE_HOME/.agentic/agentic-engineering-config.json" <<'PYEOF'
import json, sys
with open(sys.argv[1], "w") as f:
    json.dump({"mode": "opt-out"}, f, indent=2)
    f.write("\n")
PYEOF

_run_install "$FAKE_HOME" || true

actual_repo_dir="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$FAKE_HOME/.agentic/agentic-engineering-config.json" 2>/dev/null)"

if [[ -n "$actual_repo_dir" ]]; then
  _pass "case (f2): absent repo_dir was written (value: $actual_repo_dir)"
else
  _fail "case (f2): repo_dir was not written when config had no repo_dir key"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Case (f3): invalid repo_dir in config IS overwritten.
# ---------------------------------------------------------------------------

FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.agentic"
# Write config with a repo_dir that is not a git repo.
python3 - "$FAKE_HOME/.agentic/agentic-engineering-config.json" <<'PYEOF'
import json, sys
with open(sys.argv[1], "w") as f:
    json.dump({"repo_dir": "/nonexistent/path/that/is/not/a/git/repo"}, f, indent=2)
    f.write("\n")
PYEOF

_run_install "$FAKE_HOME" || true

actual_repo_dir="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
" "$FAKE_HOME/.agentic/agentic-engineering-config.json" 2>/dev/null)"

if [[ -n "$actual_repo_dir" ]] && [[ "$actual_repo_dir" != "/nonexistent/path/that/is/not/a/git/repo" ]]; then
  _pass "case (f3): invalid repo_dir overwritten (new value: $actual_repo_dir)"
else
  _fail "case (f3): invalid repo_dir was not overwritten (got '$actual_repo_dir')"
fi

rm -rf "$FAKE_HOME"

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
