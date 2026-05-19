#!/usr/bin/env bash
# Purpose: Regression test for .kimi/install.sh dir-symlink write-through guard.
#          Ensures that when ~/.kimi/skills/agentic-engineering is a directory
#          symlink pointing into the repo, install.sh replaces it with a real
#          directory and does NOT clobber tracked repo symlinks inside it.
#
# Public API: ./bin/tests/test_kimi_install_symlink.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, python3 (used by install.sh internally), mktemp.
#
# Downstream consumers: developer running locally before commit; can be
#                       wired into CI.
#
# Failure modes: any assertion failure prints the failing assertion and exits 1.
#                A temporary fake HOME is used; the real ~/.kimi is never touched.
#                Tracked repo symlinks are restored on exit via trap.
#
# Performance: ~5 s wall time on a developer machine (runs install.sh twice).
#
# Regression coverage:
#   - Major (Skeptic PR-114): a stale dir-symlink at ~/.kimi/skills/agentic-engineering
#     pointing into the repo caused install.sh to write individual file-symlinks
#     through the dir-symlink, corrupting tracked repo symlinks (SKILL.md,
#     agents, commands, references). The fix detects this and replaces the
#     dir-symlink with a real directory before writing into it. This test
#     re-creates the bug-trigger scenario to prevent regression.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_DIR/.kimi/install.sh"

if [[ ! -f "$INSTALL_SH" ]]; then
  echo "FAIL: $INSTALL_SH not found" >&2
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

# ---- Setup: save and restore tracked symlinks on exit ----
SKILL_SRC="$REPO_DIR/.kimi/skills/agentic-engineering"
TRACKED_TARGETS=()
for item in SKILL.md agents commands references; do
  if [[ -L "$SKILL_SRC/$item" ]]; then
    TRACKED_TARGETS+=("$item=$(readlink "$SKILL_SRC/$item")")
  fi
done

_restore_symlinks() {
  for entry in "${TRACKED_TARGETS[@]:-}"; do
    local name="${entry%%=*}"
    local target="${entry#*=}"
    local path="$SKILL_SRC/$name"
    # Only restore if it was corrupted (no longer a symlink or wrong target)
    if [[ ! -L "$path" ]] || [[ "$(readlink "$path")" != "$target" ]]; then
      rm -f "$path"
      ln -s "$target" "$path"
    fi
  done
}

FAKE_HOME=""
_cleanup() {
  if [[ -n "$FAKE_HOME" && -d "$FAKE_HOME" ]]; then
    rm -rf "$FAKE_HOME"
  fi
  _restore_symlinks
}
trap _cleanup EXIT

# ---- Helper: assert git status is clean for tracked skill items ----
_assert_git_clean() {
  local label="$1"
  local dirty
  dirty="$(git -C "$REPO_DIR" status --porcelain \
    -- ".kimi/skills/agentic-engineering/SKILL.md" \
       ".kimi/skills/agentic-engineering/agents" \
       ".kimi/skills/agentic-engineering/commands" \
       ".kimi/skills/agentic-engineering/references" \
    2>&1)"
  if [[ -n "$dirty" ]]; then
    _fail "$label: tracked repo symlinks were clobbered. git status output:"$'\n'"$dirty"
  else
    _pass "$label: tracked repo symlinks intact (git status clean)"
  fi
}

# ---- Reset tracked symlinks to a known clean state before each run ----
_reset_repo_symlinks() {
  git -C "$REPO_DIR" checkout -- \
    ".kimi/skills/agentic-engineering/SKILL.md" \
    ".kimi/skills/agentic-engineering/agents" \
    ".kimi/skills/agentic-engineering/commands" \
    ".kimi/skills/agentic-engineering/references" \
    2>/dev/null || true
}

# ---- Run install.sh with a fake HOME, suppressing interactive prompts ----
_run_install() {
  local fake_home="$1"
  # Pipe /dev/null to stdin to skip any interactive prompts (e.g. skill_auto_load).
  # Pass --mode=opt-out and --profile=default to skip interactive mode/profile selection.
  HOME="$fake_home" bash "$INSTALL_SH" --mode=opt-out --profile=default \
    < /dev/null > "$fake_home/.install_out" 2>&1
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "  [install.sh output]:" >&2
    cat "$fake_home/.install_out" >&2
    _fail "install.sh exited with code $rc"
  fi
  return $rc
}

# ============================================================
# Test 1: Regression - dir-symlink at dst triggers guard
# ============================================================

FAKE_HOME="$(mktemp -d)"

# Create the bug-trigger scenario: a directory symlink at
# <fakeHOME>/.kimi/skills/agentic-engineering pointing into the repo.
mkdir -p "$FAKE_HOME/.kimi/skills"
ln -s "$SKILL_SRC" "$FAKE_HOME/.kimi/skills/agentic-engineering"

# Ensure the repo symlinks are clean before running.
_reset_repo_symlinks

# First run
if _run_install "$FAKE_HOME"; then
  _assert_git_clean "regression-dir-symlink (first run)"
else
  : # _run_install already called _fail
fi

# ---- Test 2: Idempotency - second run must also leave git status clean ----

_reset_repo_symlinks

if _run_install "$FAKE_HOME"; then
  _assert_git_clean "regression-dir-symlink (idempotent second run)"
else
  : # _run_install already called _fail
fi

# ---- Test 3: dst is absent (clean install) - must not disturb repo symlinks ----

if [[ -n "$FAKE_HOME" && -d "$FAKE_HOME" ]]; then rm -rf "$FAKE_HOME"; fi
FAKE_HOME="$(mktemp -d)"
mkdir -p "$FAKE_HOME/.kimi/skills"
# No symlink or directory at dst - clean install path.

_reset_repo_symlinks

if _run_install "$FAKE_HOME"; then
  _assert_git_clean "clean-install (no prior dst)"
else
  : # _run_install already called _fail
fi

# ---- Results ----

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
