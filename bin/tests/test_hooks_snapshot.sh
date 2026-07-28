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

# .snapshot-meta.json is excluded from this byte-comparison on purpose: its
# `snapshotted_at` field is stamped at second resolution by sync_hooks_snapshot
# on EVERY call (scripts/lib/hooks-snapshot.sh), by design - a fresh
# re-sync a second later is expected to change that field. Asserting raw
# byte-equality on this file is a race against the wall-clock second
# boundary (measured ~7% flake rate in CI). The fields that genuinely must
# stay stable across an idempotent re-sync - `source_hash`, `source_repo_dir`,
# and the JSON key set - are checked separately below via targeted field
# comparisons that skip `snapshotted_at` on purpose. Do not remove this
# exclusion to "fix" a perceived coverage gap - it would reintroduce the flake;
# extend the targeted comparisons below instead.
_snapshot_files() {
  # Exclude .snapshot-meta.json only at the snapshot root, not at any depth -
  # a same-named file inside a copied hooks/ subtree must still be compared.
  local dir="$1"
  find "$dir" -type f -not -path "$dir/.snapshot-meta.json" | sort
}

_snapshot_content() {
  local dir="$1" f
  while IFS= read -r f; do
    printf '%s\n' "$f"
    cat "$f"
  done < <(_snapshot_files "$dir")
}

# Read a single top-level field from a .snapshot-meta.json file. A missing
# file, malformed JSON, or a missing key all surface as a python traceback on
# stderr (intentionally not suppressed - a prior version of this file swallowed
# stderr on its comparator and produced a 100% vacuous pass on macOS; see
# PR #506) and an empty string on stdout. Callers must not conflate "empty"
# with "changed" - see the accurate-message requirement below.
_meta_field() {
  local meta_file="$1" field="$2"
  python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])" \
    "$meta_file" "$field"
}

# Read the sorted set of top-level keys from a .snapshot-meta.json file, one
# per line. Same error-surfacing contract as _meta_field above.
_meta_keys() {
  local meta_file="$1"
  python3 -c "import json,sys; [print(k) for k in sorted(json.load(open(sys.argv[1])).keys())]" \
    "$meta_file"
}

SOURCE_HASH_BEFORE="$(_meta_field "$SNAP_DIR/.snapshot-meta.json" source_hash)"
REPO_DIR_BEFORE="$(_meta_field "$SNAP_DIR/.snapshot-meta.json" source_repo_dir)"
KEYS_BEFORE="$(_meta_keys "$SNAP_DIR/.snapshot-meta.json")"
CONTENT_BEFORE="$(_snapshot_content "$SNAP_DIR")"

HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"

SOURCE_HASH_AFTER="$(_meta_field "$SNAP_DIR/.snapshot-meta.json" source_hash)"
REPO_DIR_AFTER="$(_meta_field "$SNAP_DIR/.snapshot-meta.json" source_repo_dir)"
KEYS_AFTER="$(_meta_keys "$SNAP_DIR/.snapshot-meta.json")"
CONTENT_AFTER="$(_snapshot_content "$SNAP_DIR")"

if [[ "$CONTENT_BEFORE" == "$CONTENT_AFTER" ]]; then
  _pass "re-sync with unchanged source is idempotent (identical file set + content, excluding .snapshot-meta.json's timestamp)"
else
  _fail "re-sync with unchanged source produced a different tree"
fi

# Each stability check below distinguishes "both sides empty" (not a real
# comparison - missing/malformed file or key, reported as such) from
# "changed" (a real regression, reported with the differing values). A
# message that says "changed" when both sides were simply empty misdescribes
# the failure and misleads whoever debugs it next (Finding 2, PR #506
# follow-up).
if [[ -z "$SOURCE_HASH_BEFORE" && -z "$SOURCE_HASH_AFTER" ]]; then
  _fail ".snapshot-meta.json source_hash: both sides empty (missing/malformed .snapshot-meta.json or missing 'source_hash' key - not a stability comparison)"
elif [[ "$SOURCE_HASH_BEFORE" == "$SOURCE_HASH_AFTER" ]]; then
  _pass ".snapshot-meta.json source_hash is stable across an idempotent re-sync"
else
  _fail ".snapshot-meta.json source_hash changed across an idempotent re-sync ('$SOURCE_HASH_BEFORE' vs '$SOURCE_HASH_AFTER')"
fi

# source_repo_dir stability: catches a corrupted/rewired source path across
# an idempotent re-sync (e.g. a bug that repoints the snapshot at a different
# repo_dir). Both syncs above pass the identical $REPO_C argument, so this is
# a stability assertion, not an absolute-value validation of source_repo_dir
# itself - see the reviewer's Minor rationale in PR #506 follow-up.
if [[ -z "$REPO_DIR_BEFORE" && -z "$REPO_DIR_AFTER" ]]; then
  _fail ".snapshot-meta.json source_repo_dir: both sides empty (missing/malformed .snapshot-meta.json or missing 'source_repo_dir' key - not a stability comparison)"
elif [[ "$REPO_DIR_BEFORE" == "$REPO_DIR_AFTER" ]]; then
  _pass ".snapshot-meta.json source_repo_dir is stable and non-empty across an idempotent re-sync"
else
  _fail ".snapshot-meta.json source_repo_dir changed across an idempotent re-sync ('$REPO_DIR_BEFORE' vs '$REPO_DIR_AFTER')"
fi

# Key-set stability: catches schema drift (a junk key silently added, or a
# key going missing) that a source_hash-only comparison can't see.
if [[ -z "$KEYS_BEFORE" && -z "$KEYS_AFTER" ]]; then
  _fail ".snapshot-meta.json key set: both sides empty (missing/malformed .snapshot-meta.json) - not a stability comparison"
elif [[ "$KEYS_BEFORE" == "$KEYS_AFTER" ]]; then
  _pass ".snapshot-meta.json key set is stable across an idempotent re-sync"
else
  _fail ".snapshot-meta.json key set changed across an idempotent re-sync (before: [$(echo "$KEYS_BEFORE" | tr '\n' ' ')], after: [$(echo "$KEYS_AFTER" | tr '\n' ' ')])"
fi

# Delete propagation: remove extra.sh from source, resync, must vanish from snapshot.
rm "$REPO_C/hooks/extra.sh"
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"

if [[ ! -f "$SNAP_DIR/hooks/extra.sh" ]]; then
  _pass "deleting a source file and re-syncing removes it from the snapshot (rm-then-copy)"
else
  _fail "deleted source file hooks/extra.sh still present in the snapshot after re-sync"
fi

# Finding 3 regression: a file literally named .snapshot-meta.json nested
# inside a copied hooks/ subtree (NOT at the snapshot root) must still be
# compared - the root-scoped exclusion in _snapshot_files must not match it
# at any depth. Two distinct properties are asserted separately, each with
# its own message, so a failure names exactly which property broke:
#   (a) the nested path is actually present in the compared file set at all
#       (a direct membership check - not an inference from before/after
#       inequality, which can pass for the wrong reason if an unrelated file
#       changes elsewhere in the tree at the same time); and
#   (b) a content change to that nested file is detected across a re-sync
#       (the property this test exists to catch in the first place).
mkdir -p "$REPO_C/hooks/nested"
echo '{"decoy":"v1"}' > "$REPO_C/hooks/nested/.snapshot-meta.json"
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"
NESTED_BEFORE="$(_snapshot_content "$SNAP_DIR")"
NESTED_FILES_BEFORE="$(_snapshot_files "$SNAP_DIR")"

echo '{"decoy":"v2"}' > "$REPO_C/hooks/nested/.snapshot-meta.json"
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"
NESTED_AFTER="$(_snapshot_content "$SNAP_DIR")"

if echo "$NESTED_FILES_BEFORE" | grep -q '/hooks/nested/\.snapshot-meta\.json$'; then
  _pass "a nested hooks/.../.snapshot-meta.json is present in the compared file set (not excluded at depth)"
elif [[ -z "$NESTED_FILES_BEFORE" ]]; then
  _fail "the compared file set is empty or unreadable (snapshot dir missing or inaccessible) - not a membership comparison"
else
  _fail "a nested hooks/.../.snapshot-meta.json is absent from the compared file set - the root-scoped exclusion in _snapshot_files matched it at the wrong depth"
fi

if [[ "$NESTED_BEFORE" != "$NESTED_AFTER" ]]; then
  _pass "a content change to the nested hooks/.../.snapshot-meta.json is detected across a re-sync"
else
  _fail "a content change to the nested hooks/.../.snapshot-meta.json was not detected across a re-sync"
fi

rm -rf "$REPO_C/hooks/nested"
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"

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
