#!/usr/bin/env bash
# tests/bootstrap-guard.test.sh
#
# Regression tests for the rogue-clone guard in bootstrap.sh.
# Uses temp HOME + temp git repos; never touches real ~/.agentic or clones.
#
# Cases:
#   (a) config repo_dir = valid git repo at /path/A, AE_DEST_DIR = /path/B -> warns + exits 0, no clone
#   (b) AE_DEST_DIR = same as repo_dir -> proceeds past guard (no abort)
#   (c) absent config -> proceeds past guard
#   (d) config repo_dir = non-git path -> proceeds past guard
#
# For case (a): bootstrap.sh exits 0 immediately (guard fires before clone).
# For cases (b-d): the guard does not fire; bootstrap.sh continues and will
#   eventually fail trying to clone (no network) or find install.sh (not in
#   temp repo). We intercept at the clone step with a git stub for (a) only
#   (to verify no clone happens) and rely on the absence of guard messages
#   plus non-early-exit for (b-d). Cases (b-d) may exit non-zero after the
#   guard for unrelated reasons - we only check guard behavior.

set -euo pipefail

BOOTSTRAP_SH="$(cd "$(dirname "$0")/.." && pwd)/bootstrap.sh"
if [ ! -f "$BOOTSTRAP_SH" ]; then
  echo "FATAL: bootstrap.sh not found at $BOOTSTRAP_SH" >&2
  exit 1
fi

# Find the real git binary (before any PATH manipulation)
REAL_GIT="$(command -v git)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS=0
FAIL=0
TMPDIR_BASE="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_BASE"' EXIT

_pass() { echo "PASS: $1"; PASS=$((PASS+1)); }
_fail() { echo "FAIL: $1 - $2"; FAIL=$((FAIL+1)); }

# Create a minimal git repo (valid git dir, no network needed)
_make_git_repo() {
  local dir="$1"
  mkdir -p "$dir"
  git -C "$dir" init -q 2>/dev/null
  touch "$dir/.keep"
  git -C "$dir" add .keep 2>/dev/null
  git -C "$dir" -c user.email="t@t.com" -c user.name="T" commit -q -m "init" 2>/dev/null || true
}

# Write a config JSON to a given fake HOME
_write_config() {
  local home="$1" repo_dir="$2"
  mkdir -p "$home/.agentic"
  python3 -c "
import json, sys
data = {'repo_dir': sys.argv[1]}
print(json.dumps(data, indent=2))
" "$repo_dir" > "$home/.agentic/agentic-engineering-config.json"
}

# Git stub for case (a): intercepts 'git clone' (should never be reached),
# passes everything else to the real git using its absolute path.
# Uses $REAL_GIT_PATH env var to avoid PATH-based recursion.
_make_git_stub_no_clone() {
  local stub_bin="$1"
  mkdir -p "$stub_bin"
  cat > "$stub_bin/git" <<STUBEOF
#!/usr/bin/env bash
if [ "\${1:-}" = "clone" ]; then
  echo "STUB_CLONE_CALLED" >&2
  exit 0
fi
exec "\$REAL_GIT_PATH" "\$@"
STUBEOF
  chmod +x "$stub_bin/git"
}

# ---------------------------------------------------------------------------
# Case (a): valid different repo_dir -> guard fires, exits 0, no clone
# ---------------------------------------------------------------------------
test_case_a() {
  local tmp="$TMPDIR_BASE/case_a"
  local fake_home="$tmp/home"
  local path_a="$tmp/repoA"
  local path_b="$tmp/repoB"

  _make_git_repo "$path_a"
  _write_config "$fake_home" "$path_a"

  local stub_bin="$tmp/bin"
  _make_git_stub_no_clone "$stub_bin"

  local out
  local rc=0
  out="$(
    HOME="$fake_home" \
    AE_DEST_DIR="$path_b" \
    AE_HTTPS_URL="NOCLONE" \
    AE_SSH_URL="NOCLONE" \
    REAL_GIT_PATH="$REAL_GIT" \
    PATH="$stub_bin:$PATH" \
    bash "$BOOTSTRAP_SH" 2>&1
  )" || rc=$?

  if [ "$rc" -ne 0 ]; then
    _fail "case_a" "expected exit 0 from guard, got exit $rc. Output: $out"
    return
  fi
  if ! echo "$out" | grep -q "split-brain"; then
    _fail "case_a" "expected split-brain warning in output. Got: $out"
    return
  fi
  if echo "$out" | grep -q "STUB_CLONE_CALLED"; then
    _fail "case_a" "git clone was invoked despite guard"
    return
  fi
  if [ -d "$path_b" ]; then
    _fail "case_a" "path_b was created despite guard firing"
    return
  fi
  _pass "case_a: guard fires on valid different repo_dir"
}

# ---------------------------------------------------------------------------
# Case (b): AE_DEST_DIR == repo_dir (same canonical path) -> proceeds past guard
# ---------------------------------------------------------------------------
test_case_b() {
  local tmp="$TMPDIR_BASE/case_b"
  local fake_home="$tmp/home"
  local path_a="$tmp/repoA"

  _make_git_repo "$path_a"
  _write_config "$fake_home" "$path_a"

  local stub_bin="$tmp/bin"
  _make_git_stub_no_clone "$stub_bin"

  local out
  local rc=0
  # bootstrap.sh will exit non-zero after guard (no install.sh in temp repo);
  # we only care the guard did NOT fire.
  out="$(
    HOME="$fake_home" \
    AE_DEST_DIR="$path_a" \
    AE_HTTPS_URL="NOCLONE" \
    AE_SSH_URL="NOCLONE" \
    REAL_GIT_PATH="$REAL_GIT" \
    PATH="$stub_bin:$PATH" \
    bash "$BOOTSTRAP_SH" 2>&1
  )" || rc=$?

  if echo "$out" | grep -q "Aborting without cloning"; then
    _fail "case_b" "guard aborted when AE_DEST_DIR == repo_dir. Output: $out"
    return
  fi
  if echo "$out" | grep -q "split-brain"; then
    _fail "case_b" "split-brain warning when same path. Output: $out"
    return
  fi
  _pass "case_b: guard skipped when AE_DEST_DIR matches repo_dir"
}

# ---------------------------------------------------------------------------
# Case (c): no config file -> proceeds past guard
# ---------------------------------------------------------------------------
test_case_c() {
  local tmp="$TMPDIR_BASE/case_c"
  local fake_home="$tmp/home"
  local path_b="$tmp/repoB"

  mkdir -p "$fake_home"
  # No config written

  local stub_bin="$tmp/bin"
  _make_git_stub_no_clone "$stub_bin"

  local out
  local rc=0
  out="$(
    HOME="$fake_home" \
    AE_DEST_DIR="$path_b" \
    AE_HTTPS_URL="NOCLONE" \
    AE_SSH_URL="NOCLONE" \
    REAL_GIT_PATH="$REAL_GIT" \
    PATH="$stub_bin:$PATH" \
    bash "$BOOTSTRAP_SH" 2>&1
  )" || rc=$?

  if echo "$out" | grep -q "Aborting without cloning"; then
    _fail "case_c" "guard fired with no config. Output: $out"
    return
  fi
  if echo "$out" | grep -q "split-brain"; then
    _fail "case_c" "split-brain with no config. Output: $out"
    return
  fi
  _pass "case_c: guard skipped when no config present"
}

# ---------------------------------------------------------------------------
# Case (d): config repo_dir = non-git directory -> proceeds past guard
# ---------------------------------------------------------------------------
test_case_d() {
  local tmp="$TMPDIR_BASE/case_d"
  local fake_home="$tmp/home"
  local non_git="$tmp/not_a_repo"
  local path_b="$tmp/repoB"

  mkdir -p "$non_git"  # exists, but not a git repo
  _write_config "$fake_home" "$non_git"

  local stub_bin="$tmp/bin"
  _make_git_stub_no_clone "$stub_bin"

  local out
  local rc=0
  out="$(
    HOME="$fake_home" \
    AE_DEST_DIR="$path_b" \
    AE_HTTPS_URL="NOCLONE" \
    AE_SSH_URL="NOCLONE" \
    REAL_GIT_PATH="$REAL_GIT" \
    PATH="$stub_bin:$PATH" \
    bash "$BOOTSTRAP_SH" 2>&1
  )" || rc=$?

  if echo "$out" | grep -q "Aborting without cloning"; then
    _fail "case_d" "guard fired for non-git repo_dir. Output: $out"
    return
  fi
  if echo "$out" | grep -q "split-brain"; then
    _fail "case_d" "split-brain warning for non-git repo_dir. Output: $out"
    return
  fi
  _pass "case_d: guard skipped when repo_dir is not a valid git repo"
}

# ---------------------------------------------------------------------------
# Run all cases
# ---------------------------------------------------------------------------
echo "=== bootstrap-guard tests ==="
test_case_a
test_case_b
test_case_c
test_case_d
echo ""
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
