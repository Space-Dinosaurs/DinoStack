#!/usr/bin/env bash
# Purpose: Unit tests for scripts/lib/hooks-snapshot.sh (DS-54): key
#          stability, sync idempotency, delete-propagation (proves
#          rm-then-copy, not a merge), and the bounded-delete guard.
#
# Public API: ./bin/tests/test_hooks_snapshot.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, mktemp.
#
# Downstream consumers: developer running locally before commit; CI.
#
# Failure modes: any assertion failure prints the failing assertion and exits
#                1. A temporary fake HOME and fake repo dirs are used; the
#                real $HOME/.agentic/hooks-snapshot is never touched.
#
# Performance: < 2 s wall time (pure shell + python3, no network).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$REPO_DIR/scripts/lib/hooks-snapshot.sh"

if [[ ! -f "$LIB" ]]; then
  echo "FAIL: $LIB not found" >&2
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

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

FAKE_HOME="$TMP_ROOT/home"
mkdir -p "$FAKE_HOME"

# A minimal fake "repo" tree carrying just enough of the source set to
# exercise sync_hooks_snapshot without depending on the real checkout layout.
_make_fake_repo() {
  local dir="$1"
  mkdir -p "$dir/hooks/tests" "$dir/.codex/config" "$dir/.codex/hooks" \
           "$dir/.gemini/hooks" "$dir/.kimi/hooks"
  echo "risk" > "$dir/hooks/risk-reminder.sh"
  echo "test-only" > "$dir/hooks/tests/should-be-excluded.sh"
  echo "manifest" > "$dir/hooks/AGENTS.md"
  echo '{"hooks":{}}' > "$dir/.codex/config/hooks.json"
  echo "codex-risk" > "$dir/.codex/hooks/risk-reminder.sh"
  echo "gemini-risk" > "$dir/.gemini/hooks/risk-reminder.sh"
  echo "kimi-start" > "$dir/.kimi/hooks/session-start.sh"
}

# =============================================================
# 1. hooks_snapshot_key: stable per repo_dir, differs across repo_dir
# =============================================================
echo ""
echo "=== 1. hooks_snapshot_key stability ==="

REPO_A="$TMP_ROOT/repo-a"
REPO_B="$TMP_ROOT/repo-b"
_make_fake_repo "$REPO_A"
_make_fake_repo "$REPO_B"

KEY_A1="$(HOME="$FAKE_HOME" bash -c "source '$LIB'; hooks_snapshot_key '$REPO_A'")"
KEY_A2="$(HOME="$FAKE_HOME" bash -c "source '$LIB'; hooks_snapshot_key '$REPO_A'")"
KEY_B="$(HOME="$FAKE_HOME" bash -c "source '$LIB'; hooks_snapshot_key '$REPO_B'")"

if [[ "$KEY_A1" == "$KEY_A2" ]]; then
  _pass "key is stable across repeated calls for the same repo_dir"
else
  _fail "key differs across calls for the same repo_dir ('$KEY_A1' vs '$KEY_A2')"
fi

if [[ "$KEY_A1" != "$KEY_B" ]]; then
  _pass "key differs across distinct repo_dirs"
else
  _fail "key is identical for two distinct repo_dirs ('$KEY_A1')"
fi

# =============================================================
# 2. sync_hooks_snapshot: idempotent + delete propagation
# =============================================================
echo ""
echo "=== 2. sync_hooks_snapshot idempotency + delete propagation ==="

REPO_C="$TMP_ROOT/repo-c"
_make_fake_repo "$REPO_C"
echo "extra" > "$REPO_C/hooks/extra.sh"

SNAP_DIR="$(HOME="$FAKE_HOME" bash -c "
  source '$LIB'
  sync_hooks_snapshot '$REPO_C' >/dev/null
  printf '%s' \"\$AE_HOOKS_SNAPSHOT_DIR\"
")"

if [[ -n "$SNAP_DIR" && -f "$SNAP_DIR/hooks/extra.sh" ]]; then
  _pass "first sync copies hooks/extra.sh into the snapshot"
else
  _fail "first sync did not produce the expected snapshot at '$SNAP_DIR'"
fi

if [[ -f "$SNAP_DIR/hooks/tests/should-be-excluded.sh" ]]; then
  _fail "hooks/tests/ was copied into the snapshot (must be excluded)"
else
  _pass "hooks/tests/ is excluded from the snapshot"
fi

if [[ -f "$SNAP_DIR/hooks/AGENTS.md" ]]; then
  _fail "hooks/AGENTS.md was copied into the snapshot (must be excluded)"
else
  _pass "hooks/AGENTS.md is excluded from the snapshot"
fi

CONTENT_BEFORE="$(find "$SNAP_DIR" -type f | sort | xargs -I{} sh -c 'echo {}; cat {}' 2>/dev/null)"

HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"

CONTENT_AFTER="$(find "$SNAP_DIR" -type f | sort | xargs -I{} sh -c 'echo {}; cat {}' 2>/dev/null)"

if [[ "$CONTENT_BEFORE" == "$CONTENT_AFTER" ]]; then
  _pass "re-sync with unchanged source is idempotent (identical file set + content)"
else
  _fail "re-sync with unchanged source produced a different tree"
fi

# Delete propagation: remove extra.sh from source, resync, must vanish from snapshot.
rm "$REPO_C/hooks/extra.sh"
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"

if [[ ! -f "$SNAP_DIR/hooks/extra.sh" ]]; then
  _pass "deleting a source file and re-syncing removes it from the snapshot (rm-then-copy)"
else
  _fail "deleted source file hooks/extra.sh still present in the snapshot after re-sync"
fi

# =============================================================
# 3. Bounded-delete guard
# =============================================================
echo ""
echo "=== 3. Bounded-delete guard ==="

REPO_D="$TMP_ROOT/repo-d"
_make_fake_repo "$REPO_D"

# 3a. Empty key -> fail-closed, return 1, no write under $HOME/.agentic.
GUARD_HOME_A="$TMP_ROOT/guard-home-a"
mkdir -p "$GUARD_HOME_A"
RC_A=0
HOME="$GUARD_HOME_A" bash -c "
  source '$LIB'
  hooks_snapshot_key() { echo ''; }
  sync_hooks_snapshot '$REPO_D' >/dev/null 2>&1
" || RC_A=$?

if [[ "$RC_A" -eq 1 ]]; then
  _pass "empty key: sync_hooks_snapshot returns 1"
else
  _fail "empty key: sync_hooks_snapshot returned $RC_A (expected 1)"
fi

if [[ ! -e "$GUARD_HOME_A/.agentic/hooks-snapshot" ]]; then
  _pass "empty key: no filesystem write under \$HOME/.agentic/hooks-snapshot"
else
  _fail "empty key: unexpected write under \$HOME/.agentic/hooks-snapshot"
fi

# 3b. Key containing ".." -> fail-closed, return 1, no write.
GUARD_HOME_B="$TMP_ROOT/guard-home-b"
mkdir -p "$GUARD_HOME_B"
RC_B=0
HOME="$GUARD_HOME_B" bash -c "
  source '$LIB'
  hooks_snapshot_key() { echo '../../etc'; }
  sync_hooks_snapshot '$REPO_D' >/dev/null 2>&1
" || RC_B=$?

if [[ "$RC_B" -eq 1 ]]; then
  _pass "'..'-in-key: sync_hooks_snapshot returns 1"
else
  _fail "'..'-in-key: sync_hooks_snapshot returned $RC_B (expected 1)"
fi

if [[ ! -e "$GUARD_HOME_B/.agentic/hooks-snapshot" ]]; then
  _pass "'..'-in-key: no filesystem write under \$HOME/.agentic/hooks-snapshot"
else
  _fail "'..'-in-key: unexpected write under \$HOME/.agentic/hooks-snapshot"
fi

# 3c. Key containing "/" -> fail-closed, return 1.
GUARD_HOME_C="$TMP_ROOT/guard-home-c"
mkdir -p "$GUARD_HOME_C"
RC_C=0
HOME="$GUARD_HOME_C" bash -c "
  source '$LIB'
  hooks_snapshot_key() { echo 'foo/bar'; }
  sync_hooks_snapshot '$REPO_D' >/dev/null 2>&1
" || RC_C=$?

if [[ "$RC_C" -eq 1 ]]; then
  _pass "'/'-in-key: sync_hooks_snapshot returns 1"
else
  _fail "'/'-in-key: sync_hooks_snapshot returned $RC_C (expected 1)"
fi

# 3d. Unresolvable repo_dir -> fail-closed, return 1.
RC_D=0
HOME="$GUARD_HOME_C" bash -c "
  source '$LIB'
  sync_hooks_snapshot '/nonexistent/definitely/not/a/repo/path/xyz' >/dev/null 2>&1
" || RC_D=$?

if [[ "$RC_D" -eq 1 ]]; then
  _pass "unresolvable repo_dir: sync_hooks_snapshot returns 1"
else
  _fail "unresolvable repo_dir: sync_hooks_snapshot returned $RC_D (expected 1)"
fi

# =============================================================
# 4. Absolute-path "tests" component must not spuriously exclude everything
#    (Skeptic Minor 1: excluded() must check the RELATIVE path within the
#    source root, never the absolute prefix leading up to it)
# =============================================================
echo ""
echo "=== 4. Absolute-path 'tests' component does not spuriously exclude everything ==="

# Nest the fake repo under a parent directory literally named "tests" so the
# ABSOLUTE path passed to compute_hooks_source_hash contains a "tests"
# component above the source root itself (distinct from the genuine
# hooks/tests/ subdir already exercised in section 2).
REPO_E="$TMP_ROOT/tests/parent-dir/repo-e"
_make_fake_repo "$REPO_E"

EMPTY_SHA256="$(python3 -c "import hashlib; print(hashlib.sha256(b'').hexdigest())")"

HASH_E1="$(HOME="$FAKE_HOME" bash -c "
  source '$LIB'
  compute_hooks_source_hash \
    '$REPO_E/hooks' \
    '$REPO_E/.codex/config/hooks.json' \
    '$REPO_E/.codex/hooks' \
    '$REPO_E/.gemini/hooks' \
    '$REPO_E/.kimi/hooks'
")"

if [[ -n "$HASH_E1" && "$HASH_E1" != "$EMPTY_SHA256" ]]; then
  _pass "source tree under an absolute path containing a 'tests' component still hashes real content (non-empty digest)"
else
  _fail "source tree under an absolute path containing a 'tests' component hashed to empty/constant digest (regression: absolute-path exclusion bug)"
fi

echo "changed" >> "$REPO_E/hooks/risk-reminder.sh"

HASH_E2="$(HOME="$FAKE_HOME" bash -c "
  source '$LIB'
  compute_hooks_source_hash \
    '$REPO_E/hooks' \
    '$REPO_E/.codex/config/hooks.json' \
    '$REPO_E/.codex/hooks' \
    '$REPO_E/.gemini/hooks' \
    '$REPO_E/.kimi/hooks'
")"

if [[ "$HASH_E2" != "$HASH_E1" ]]; then
  _pass "hash changes when content changes, even under a 'tests'-named absolute path component"
else
  _fail "hash did NOT change after content changed under a 'tests'-named absolute path component"
fi

# The genuine hooks/tests/ subdir and hooks/AGENTS.md exclusions must still
# hold under this same absolute-path scenario (the fix must not disturb the
# real relative-path exclusion it is scoped to preserve).
SNAP_DIR_E="$(HOME="$FAKE_HOME" bash -c "
  source '$LIB'
  sync_hooks_snapshot '$REPO_E' >/dev/null
  printf '%s' \"\$AE_HOOKS_SNAPSHOT_DIR\"
")"

if [[ -f "$SNAP_DIR_E/hooks/risk-reminder.sh" ]] && \
   [[ ! -f "$SNAP_DIR_E/hooks/tests/should-be-excluded.sh" ]] && \
   [[ ! -f "$SNAP_DIR_E/hooks/AGENTS.md" ]]; then
  _pass "real content is copied AND the genuine hooks/tests/ + hooks/AGENTS.md exclusions still hold under a 'tests'-named absolute path"
else
  _fail "exclusion/inclusion behavior broke under a 'tests'-named absolute path (snapshot at $SNAP_DIR_E)"
fi

# =============================================================
# Results
# =============================================================
echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
