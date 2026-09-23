#!/usr/bin/env bash
# Purpose: Regression test for .kimi/install.sh dir-symlink write-through guard,
#          and for this harness's own _restore_symlinks cleanup helper.
#          Ensures that when ~/.kimi/skills/dinostack is a directory
#          symlink pointing into the repo, install.sh replaces it with a real
#          directory and does NOT clobber tracked repo symlinks inside it; and
#          that _restore_symlinks, which the EXIT trap runs against those same
#          tracked symlinks, iterates zero times on an empty array.
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
#                check_restore_symlinks_empty_array exits nonzero with a
#                "RESTORE-ARGV VIOLATION:" prefix - either because a case's
#                logged argv did not match, or because the extractor could no
#                longer locate the _restore_symlinks() definition or the
#                TRACKED_TARGETS reference inside it ("extractor has drifted").
#
# Performance: ~5 s wall time on a developer machine (runs install.sh twice).
#
# Regression coverage:
#   - Major (Skeptic PR-114): a stale dir-symlink at ~/.kimi/skills/dinostack
#     pointing into the repo caused install.sh to write individual file-symlinks
#     through the dir-symlink, corrupting tracked repo symlinks (SKILL.md,
#     agents, commands, references). The fix detects this and replaces the
#     dir-symlink with a real directory before writing into it. This test
#     re-creates the bug-trigger scenario to prevent regression.
#   - DS-252: _restore_symlinks iterated over "${TRACKED_TARGETS[@]:-}", which
#     expands an EMPTY array to one EMPTY word rather than to nothing. With no
#     tracked symlink present the EXIT trap therefore ran one iteration with
#     entry="", attempting `rm -f "$SKILL_SRC/"` and `ln -s "" "$SKILL_SRC/"`
#     against the skill DIRECTORY itself. Fixed to the outer-UNQUOTED
#     ${TRACKED_TARGETS[@]+"${TRACKED_TARGETS[@]}"} and pinned by
#     check_restore_symlinks_empty_array, which EXECUTES the shipped helper
#     against argv-logging rm/ln stubs rather than grepping its spelling.

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
SKILL_SRC="$REPO_DIR/.kimi/skills/dinostack"
TRACKED_TARGETS=()
for item in SKILL.md agents commands references; do
  if [[ -L "$SKILL_SRC/$item" ]]; then
    TRACKED_TARGETS+=("$item=$(readlink "$SKILL_SRC/$item")")
  fi
done

_restore_symlinks() {
  for entry in ${TRACKED_TARGETS[@]+"${TRACKED_TARGETS[@]}"}; do
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

# DS-252 regression pin on _restore_symlinks' array expansion. It EXTRACTS the
# shipped function body from THIS file and EXECUTES it against PATH-first `rm`
# and `ln` stubs that log their own argv, rather than pattern-matching the
# expansion's spelling: a spelling pin passes for any construct that merely
# looks right, and the whole point of DS-252 is that a construct which looks
# right can be wrong.
#
# What is pinned: with an EMPTY TRACKED_TARGETS, the loop must run ZERO times.
# `"${TRACKED_TARGETS[@]:-}"` expands an empty array to ONE EMPTY WORD under
# /bin/bash 3.2.57, bash 5.3.9 and zsh 5.9 alike, so the loop runs once with
# entry="" and the EXIT trap then attempts `rm -f "$SKILL_SRC/"` followed by
# `ln -s "" "$SKILL_SRC/"` against the skill DIRECTORY itself. The correct
# spelling is the outer-UNQUOTED `${ARR[@]+"${ARR[@]}"}` (AGENTS.md
# "Empty-array expansion under `set -u`").
#
# Reddening mutations (all three EXECUTED at implementation):
#   M1 revert the expansion to `"${TRACKED_TARGETS[@]:-}"` - Case A logs 2
#      lines (`rm -f <scratch>/` and `ln -s  <scratch>/`) instead of 0.
#   M2 delete the `ln -s` line from _restore_symlinks - Case B logs 1 line
#      instead of 2.
#   M3 rename _restore_symlinks - the extractor hard-fails with
#      "RESTORE-ARGV VIOLATION: extractor has drifted" rather than passing
#      silently on an empty block.
check_restore_symlinks_empty_array() {
  local ok=0
  local self="${BASH_SOURCE[0]:-$0}"
  local block
  block="$(python3 - "$self" <<'PYEOF'
import sys

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
start = end = None
for i, raw in enumerate(lines):
    if start is None:
        if raw.startswith("_restore_symlinks() {"):
            start = i
        continue
    if raw == "}":
        end = i
        break
print("\n".join(lines[start:end + 1]) if start is not None and end is not None else "")
PYEOF
)"

  if [ -z "$block" ]; then
    echo "RESTORE-ARGV VIOLATION: extractor has drifted - could not locate the _restore_symlinks() definition in $self" >&2
    return 1
  fi
  if ! printf '%s' "$block" | grep -qF 'TRACKED_TARGETS'; then
    echo "RESTORE-ARGV VIOLATION: extractor has drifted - the extracted block does not carry TRACKED_TARGETS" >&2
    return 1
  fi

  local stub_dir scratch log
  stub_dir="$(mktemp -d)"
  scratch="$(mktemp -d)"
  log="$scratch/.argv.log"
  : > "$log"

  local stub_name
  for stub_name in rm ln; do
    cat > "$stub_dir/$stub_name" <<'STUBEOF'
#!/bin/sh
printf '%s %s\n' "$(basename "$0")" "$*" >> "$RESTORE_ARGV_LOG"
STUBEOF
    chmod +x "$stub_dir/$stub_name"
  done

  # case := <label>:<TRACKED_TARGETS initializer>
  local label init expected actual
  for label in empty one-entry; do
    if [ "$label" = "empty" ]; then
      init='TRACKED_TARGETS=()'
      expected=''
    else
      init='TRACKED_TARGETS=("agents=../../../content/agents")'
      expected="rm -f $scratch/agents
ln -s ../../../content/agents $scratch/agents"
    fi

    : > "$log"
    (
      PATH="$stub_dir:$PATH"
      export PATH
      RESTORE_ARGV_LOG="$log"
      export RESTORE_ARGV_LOG
      SKILL_SRC="$scratch"
      set -u
      eval "$block"
      eval "$init"
      _restore_symlinks
    )
    actual="$(cat "$log")"

    if [ "$actual" != "$expected" ]; then
      echo "RESTORE-ARGV VIOLATION: case '$label' logged:" >&2
      printf '%s\n' "${actual:-<empty>}" | sed 's/^/    got: /' >&2
      printf '%s\n' "${expected:-<empty>}" | sed 's/^/    want: /' >&2
      if [ "$label" = "empty" ]; then
        echo "  An empty-array expansion that yields one EMPTY word makes the EXIT trap run rm -f and ln -s against \$SKILL_SRC itself - use \${ARR[@]+\"\${ARR[@]}\"}, never \"\${ARR[@]:-}\"." >&2
      fi
      ok=1
    fi
  done

  rm -rf "$stub_dir" "$scratch" 2>/dev/null || true
  return "$ok"
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
    -- ".kimi/skills/dinostack/SKILL.md" \
       ".kimi/skills/dinostack/agents" \
       ".kimi/skills/dinostack/commands" \
       ".kimi/skills/dinostack/references" \
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
    ".kimi/skills/dinostack/SKILL.md" \
    ".kimi/skills/dinostack/agents" \
    ".kimi/skills/dinostack/commands" \
    ".kimi/skills/dinostack/references" \
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
# <fakeHOME>/.kimi/skills/dinostack pointing into the repo.
mkdir -p "$FAKE_HOME/.kimi/skills"
ln -s "$SKILL_SRC" "$FAKE_HOME/.kimi/skills/dinostack"

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

# ---- Test 4: DS-252 - _restore_symlinks must not iterate on an empty array ----

if check_restore_symlinks_empty_array; then
  _pass "restore-symlinks empty-array expansion (DS-252)"
else
  _fail "restore-symlinks empty-array expansion (DS-252)"
fi

# ---- Results ----

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
