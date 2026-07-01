#!/usr/bin/env bash
# hooks/tests/test-hooks-staleness-core.sh
#
# Tests hooks/lib/hooks-staleness-core.sh against fixtures for all 4 states:
# never_migrated, half_applied, stale_but_stable, and current (silent).
# Mirrors the fake-$HOME approach used by
# hooks/tests/test-version-check-core-repo-dir.sh and
# bin/tests/test_hooks_snapshot.sh.
#
# Usage: bash hooks/tests/test-hooks-staleness-core.sh
# Must pass with zero failures.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
CORE="$REPO_ROOT/hooks/lib/hooks-staleness-core.sh"
SNAPSHOT_LIB="$REPO_ROOT/scripts/lib/hooks-snapshot.sh"

if [[ ! -f "$CORE" ]]; then
  echo "FAIL: $CORE not found" >&2
  exit 1
fi

_pass=0
_fail=0
pass() { echo "  PASS: $*"; _pass=$((_pass + 1)); }
fail() { echo "  FAIL: $*"; _fail=$((_fail + 1)); }

TMP_ROOT="$(mktemp -d)"
_cleanup() { rm -rf "$TMP_ROOT"; }
trap _cleanup EXIT

# A minimal fake "repo" tree carrying just enough of the source set for the
# staleness core to hash and the snapshot lib to sync. Must be a real git
# repo - resolve_repo_dir (scripts/lib/repo-dir.sh) validates repo_dir via
# `git rev-parse --git-dir` and falls back to $HOME/DinoStack otherwise.
_make_fake_repo() {
  local dir="$1"
  mkdir -p "$dir/hooks" "$dir/.codex/config" "$dir/.codex/hooks" \
           "$dir/.gemini/hooks" "$dir/.kimi/hooks"
  echo "risk" > "$dir/hooks/risk-reminder.sh"
  echo '{"hooks":{}}' > "$dir/.codex/config/hooks.json"
  echo "codex-risk" > "$dir/.codex/hooks/risk-reminder.sh"
  echo "gemini-risk" > "$dir/.gemini/hooks/risk-reminder.sh"
  echo "kimi-start" > "$dir/.kimi/hooks/session-start.sh"
  git init -q "$dir"
}

_make_config() {
  local home="$1" repo_dir="$2"
  mkdir -p "$home/.agentic"
  printf '{"repo_dir": "%s"}\n' "$repo_dir" > "$home/.agentic/agentic-engineering-config.json"
}

_run_core() {
  local home="$1"
  HOME="$home" bash "$CORE" 2>/dev/null
}

# =============================================================
# 1. never_migrated: snapshot/meta absent
# =============================================================
echo ""
echo "=== 1. never_migrated ==="

REPO1="$TMP_ROOT/repo1"
HOME1="$TMP_ROOT/home1"
_make_fake_repo "$REPO1"
mkdir -p "$HOME1"
_make_config "$HOME1" "$REPO1"

OUT1="$(_run_core "$HOME1")"
if [[ "$OUT1" == *"not yet snapshotted"* ]]; then
  pass "never_migrated message printed when snapshot is absent"
else
  fail "expected a never_migrated message, got: '$OUT1'"
fi

# =============================================================
# 2. current: after a clean sync with no adapter configs installed
# =============================================================
echo ""
echo "=== 2. current (silent) ==="

REPO2="$TMP_ROOT/repo2"
HOME2="$TMP_ROOT/home2"
_make_fake_repo "$REPO2"
mkdir -p "$HOME2"
_make_config "$HOME2" "$REPO2"
HOME="$HOME2" bash -c "source '$SNAPSHOT_LIB'; sync_hooks_snapshot '$REPO2'" >/dev/null 2>&1

OUT2="$(_run_core "$HOME2")"
if [[ -z "$OUT2" ]]; then
  pass "no output (current) when snapshot is fresh and no adapter configs are installed"
else
  fail "expected empty output for current state, got: '$OUT2'"
fi

# =============================================================
# 3. half_applied: claude settings.json still points at the checkout
# =============================================================
echo ""
echo "=== 3. half_applied ==="

REPO3="$TMP_ROOT/repo3"
HOME3="$TMP_ROOT/home3"
_make_fake_repo "$REPO3"
mkdir -p "$HOME3/.claude"
_make_config "$HOME3" "$REPO3"
HOME="$HOME3" bash -c "source '$SNAPSHOT_LIB'; sync_hooks_snapshot '$REPO3'" >/dev/null 2>&1

cat > "$HOME3/.claude/settings.json" <<EOF
{"hooks":{"SessionStart":[{"matcher":"*","hooks":[{"type":"command","command":"bash $REPO3/hooks/session-start-wrap.sh","timeout":5}]}]}}
EOF

OUT3="$(_run_core "$HOME3")"
if [[ "$OUT3" == *"partially applied"* ]]; then
  pass "half_applied message printed when claude settings.json still points at the checkout"
else
  fail "expected a half_applied message, got: '$OUT3'"
fi

# 3b. Once the settings.json is repointed at the snapshot, half_applied clears.
SNAP_DIR3="$(HOME="$HOME3" bash -c "source '$SNAPSHOT_LIB'; hooks_snapshot_dir '$REPO3'")"
cat > "$HOME3/.claude/settings.json" <<EOF
{"hooks":{"SessionStart":[{"matcher":"*","hooks":[{"type":"command","command":"bash $SNAP_DIR3/hooks/session-start-wrap.sh","timeout":5}]}]}}
EOF
OUT3B="$(_run_core "$HOME3")"
if [[ -z "$OUT3B" ]]; then
  pass "half_applied clears once claude settings.json points at the snapshot"
else
  fail "expected empty output once repointed at the snapshot, got: '$OUT3B'"
fi

# =============================================================
# 4. stale_but_stable: configs point at the snapshot, but live source moved
# =============================================================
echo ""
echo "=== 4. stale_but_stable ==="

REPO4="$TMP_ROOT/repo4"
HOME4="$TMP_ROOT/home4"
_make_fake_repo "$REPO4"
mkdir -p "$HOME4"
_make_config "$HOME4" "$REPO4"
HOME="$HOME4" bash -c "source '$SNAPSHOT_LIB'; sync_hooks_snapshot '$REPO4'" >/dev/null 2>&1

# Mutate the live source after the sync (simulates a bare `git pull`).
echo "risk-v2" > "$REPO4/hooks/risk-reminder.sh"

OUT4="$(_run_core "$HOME4")"
if [[ "$OUT4" == *"changed since the last snapshot sync"* ]]; then
  pass "stale_but_stable message printed when the live hook source moved on"
else
  fail "expected a stale_but_stable message, got: '$OUT4'"
fi

# =============================================================
# 5. Always exits 0 (fail-open), even for never_migrated / half_applied / stale
# =============================================================
echo ""
echo "=== 5. always exits 0 ==="

for h in "$HOME1" "$HOME3" "$HOME4"; do
  rc=0
  HOME="$h" bash "$CORE" >/dev/null 2>&1 || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    pass "exits 0 for HOME=$h"
  else
    fail "exited $rc (expected 0) for HOME=$h"
  fi
done

# =============================================================
# Results
# =============================================================
echo ""
echo "Results: $_pass passed, $_fail failed"
if [[ "$_fail" -gt 0 ]]; then
  exit 1
fi
echo "All tests passed."
