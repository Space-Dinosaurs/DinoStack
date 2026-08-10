#!/usr/bin/env bash
# Purpose: Unit tests for scripts/lib/hooks-snapshot.sh (DS-54): key
#          stability, bundled identity-helper deployment, sync idempotency,
#          publisher-lock recovery, delete-propagation (proves rm-then-copy,
#          not a merge), and the bounded-delete guard.
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
# Performance: < 10 s wall time (pure shell + python3, no network).

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
  mkdir -p "$dir/bin" "$dir/hooks/tests" "$dir/.codex/config" "$dir/.codex/hooks" \
           "$dir/.gemini/hooks" "$dir/.kimi/hooks"
  printf '#!/usr/bin/env python3\nprint("helper")\n' > "$dir/bin/ds-identity"
  chmod 700 "$dir/bin/ds-identity"
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

if [[ -L "$SNAP_DIR" && -d "$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$SNAP_DIR")" ]]; then
  _pass "published snapshot is an atomic symlink to an immutable generation"
else
  _fail "published snapshot is not a symlink to a complete immutable generation"
fi

if [[ -x "$SNAP_DIR/bin/ds-identity" ]]; then
  _pass "first sync copies the executable identity/telemetry helper"
else
  _fail "first sync omitted the executable identity/telemetry helper"
fi

# Per-path copy assertions for the remaining four in-scope adapter sources
# (Skeptic round-4 Minor 1: every source in hooks_source_paths() must have
# its own positive content assertion here, so dropping any single path from
# the copy loop reddens exactly its own check - not just the hooks/ and
# bin/ds-identity checks already above).
if [[ "$(cat "$SNAP_DIR/.codex/config/hooks.json" 2>/dev/null)" == '{"hooks":{}}' ]]; then
  _pass "first sync copies .codex/config/hooks.json"
else
  _fail "first sync omitted or corrupted .codex/config/hooks.json"
fi

if [[ "$(cat "$SNAP_DIR/.codex/hooks/risk-reminder.sh" 2>/dev/null)" == "codex-risk" ]]; then
  _pass "first sync copies .codex/hooks"
else
  _fail "first sync omitted or corrupted .codex/hooks"
fi

if [[ "$(cat "$SNAP_DIR/.gemini/hooks/risk-reminder.sh" 2>/dev/null)" == "gemini-risk" ]]; then
  _pass "first sync copies .gemini/hooks"
else
  _fail "first sync omitted or corrupted .gemini/hooks"
fi

if [[ "$(cat "$SNAP_DIR/.kimi/hooks/session-start.sh" 2>/dev/null)" == "kimi-start" ]]; then
  _pass "first sync copies .kimi/hooks"
else
  _fail "first sync omitted or corrupted .kimi/hooks"
fi

SAME_PROCESS_RC=0
HOME="$FAKE_HOME" bash -c "
  source '$LIB'
  sync_hooks_snapshot '$REPO_C' >/dev/null
  sync_hooks_snapshot '$REPO_C' >/dev/null
" || SAME_PROCESS_RC=$?
REPO_C_KEY="$(HOME="$FAKE_HOME" bash -c "source '$LIB'; hooks_snapshot_key '$REPO_C'")"
PUBLISH_LOCK="$FAKE_HOME/.agentic/hooks-snapshot/.${REPO_C_KEY}.publish.lock"
if [[ "$SAME_PROCESS_RC" -eq 0 && ! -e "$PUBLISH_LOCK" ]]; then
  _pass "same-process repeated publication releases its publisher lock"
else
  _fail "same-process repeated publication leaked or timed out on publisher lock"
fi

# A preexisting .versions symlink must never redirect staged generations or
# cleanup outside the validated snapshot base. The prior published snapshot
# is deliberately a real directory so the assertion also proves failure did
# not replace or remove it.
SYMLINK_HOME="$TMP_ROOT/symlink-home"
SYMLINK_REPO="$TMP_ROOT/symlink-repo"
SYMLINK_OUTSIDE="$TMP_ROOT/symlink-outside"
_make_fake_repo "$SYMLINK_REPO"
mkdir -p "$SYMLINK_HOME/.agentic/hooks-snapshot" "$SYMLINK_OUTSIDE"
SYMLINK_KEY="$(HOME="$SYMLINK_HOME" bash -c "source '$LIB'; hooks_snapshot_key '$SYMLINK_REPO'")"
mkdir "$SYMLINK_HOME/.agentic/hooks-snapshot/$SYMLINK_KEY"
echo "prior" > "$SYMLINK_HOME/.agentic/hooks-snapshot/$SYMLINK_KEY/prior"
ln -s "$SYMLINK_OUTSIDE" "$SYMLINK_HOME/.agentic/hooks-snapshot/.versions"
SYMLINK_SYNC_RC=0
HOME="$SYMLINK_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$SYMLINK_REPO' >/dev/null 2>&1" \
  || SYMLINK_SYNC_RC=$?
if [[ "$SYMLINK_SYNC_RC" -ne 0 \
  && "$(cat "$SYMLINK_HOME/.agentic/hooks-snapshot/$SYMLINK_KEY/prior" 2>/dev/null)" == "prior" \
  && -z "$(find "$SYMLINK_OUTSIDE" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  _pass ".versions symlink fails closed without external writes or prior-snapshot mutation"
else
  _fail ".versions symlink escaped validation, wrote outside, or changed the prior snapshot (rc=$SYMLINK_SYNC_RC)"
fi

SYMLINK_REMOVE_RC=0
HOME="$SYMLINK_HOME" bash -c "source '$LIB'; remove_hooks_snapshot '$SYMLINK_REPO' >/dev/null 2>&1" \
  || SYMLINK_REMOVE_RC=$?
if [[ "$SYMLINK_REMOVE_RC" -ne 0 \
  && "$(cat "$SYMLINK_HOME/.agentic/hooks-snapshot/$SYMLINK_KEY/prior" 2>/dev/null)" == "prior" \
  && -z "$(find "$SYMLINK_OUTSIDE" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  _pass ".versions symlink also makes cleanup fail closed"
else
  _fail ".versions symlink allowed cleanup to escape or mutate the prior snapshot (rc=$SYMLINK_REMOVE_RC)"
fi

# A publisher killed after mkdir but before writing pid leaves an empty lock.
# Once old enough, it must be reclaimed without weakening live lock exclusion.
mkdir "$PUBLISH_LOCK"
python3 - "$PUBLISH_LOCK" <<'PYEOF'
import os, sys, time
old = time.time() - 120
os.utime(sys.argv[1], (old, old), follow_symlinks=False)
PYEOF
EMPTY_LOCK_RC=0
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null" \
  || EMPTY_LOCK_RC=$?
if [[ "$EMPTY_LOCK_RC" -eq 0 && ! -e "$PUBLISH_LOCK" ]]; then
  _pass "stale empty publisher lock is reclaimed and sync succeeds"
else
  _fail "stale empty publisher lock wedged publication (rc=$EMPTY_LOCK_RC)"
fi

# A lock may contain a live PID but lack trustworthy start metadata if its
# publisher died between the pid and started writes. Preserve that ambiguous
# lock while it is fresh, then reclaim it after the same 60-second stale bound
# as a wholly empty lock so PID reuse cannot wedge publication forever.
mkdir "$PUBLISH_LOCK"
printf '%s\n' "$$" > "$PUBLISH_LOCK/pid"
python3 - "$PUBLISH_LOCK" <<'PYEOF'
import os, sys, time
old = time.time() - 120
os.utime(sys.argv[1], (old, old), follow_symlinks=False)
PYEOF
STALE_PID_ONLY_RC=0
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null" \
  || STALE_PID_ONLY_RC=$?
if [[ "$STALE_PID_ONLY_RC" -eq 0 && ! -e "$PUBLISH_LOCK" ]]; then
  _pass "stale live-PID publisher lock without started metadata is reclaimed and sync succeeds"
else
  _fail "stale live-PID publisher lock without started metadata wedged publication (rc=$STALE_PID_ONLY_RC)"
fi
rm -f "$PUBLISH_LOCK/pid" "$PUBLISH_LOCK/started"
rmdir "$PUBLISH_LOCK" 2>/dev/null || true

mkdir "$PUBLISH_LOCK"
printf '%s\n' "$$" > "$PUBLISH_LOCK/pid"
: > "$PUBLISH_LOCK/started"
python3 - "$PUBLISH_LOCK" <<'PYEOF'
import os, sys, time
old = time.time() - 120
os.utime(sys.argv[1], (old, old), follow_symlinks=False)
PYEOF
STALE_EMPTY_STARTED_RC=0
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null" \
  || STALE_EMPTY_STARTED_RC=$?
if [[ "$STALE_EMPTY_STARTED_RC" -eq 0 && ! -e "$PUBLISH_LOCK" ]]; then
  _pass "stale live-PID publisher lock with empty started metadata is reclaimed and sync succeeds"
else
  _fail "stale live-PID publisher lock with empty started metadata wedged publication (rc=$STALE_EMPTY_STARTED_RC)"
fi
rm -f "$PUBLISH_LOCK/pid" "$PUBLISH_LOCK/started"
rmdir "$PUBLISH_LOCK" 2>/dev/null || true

mkdir "$PUBLISH_LOCK"
printf '%s\n' "$$" > "$PUBLISH_LOCK/pid"
if ! HOME="$FAKE_HOME" bash -c "source '$LIB'; _hooks_snapshot_reclaim_publish_lock '$PUBLISH_LOCK'" \
  && [[ -d "$PUBLISH_LOCK" ]]; then
  _pass "fresh live-PID publisher lock without started metadata is not stolen"
else
  _fail "fresh live-PID publisher lock without started metadata was reclaimed"
fi
rm -f "$PUBLISH_LOCK/pid"
rmdir "$PUBLISH_LOCK"

mkdir "$PUBLISH_LOCK"
printf '%s\n' "$$" > "$PUBLISH_LOCK/pid"
: > "$PUBLISH_LOCK/started"
if ! HOME="$FAKE_HOME" bash -c "source '$LIB'; _hooks_snapshot_reclaim_publish_lock '$PUBLISH_LOCK'" \
  && [[ -d "$PUBLISH_LOCK" ]]; then
  _pass "fresh live-PID publisher lock with empty started metadata is not stolen"
else
  _fail "fresh live-PID publisher lock with empty started metadata was reclaimed"
fi
rm -f "$PUBLISH_LOCK/pid" "$PUBLISH_LOCK/started"
rmdir "$PUBLISH_LOCK"

# Populated start metadata does not make a failed `ps` result proof of PID
# reuse. Fresh ambiguity is preserved; stale ambiguity is reclaimed. Proven
# exact matches remain live regardless of age, while proven mismatches and
# dead PIDs are reclaimed immediately.
mkdir "$PUBLISH_LOCK"
printf '%s\n' "$$" > "$PUBLISH_LOCK/pid"
printf '%s\n' "recorded-start" > "$PUBLISH_LOCK/started"
if ! HOME="$FAKE_HOME" bash -c "source '$LIB'; ps() { return 1; }; _hooks_snapshot_reclaim_publish_lock '$PUBLISH_LOCK'" \
  && [[ -d "$PUBLISH_LOCK" ]]; then
  _pass "fresh populated live-PID lock is preserved when ps is unavailable"
else
  _fail "fresh populated live-PID lock was stolen when ps was unavailable"
fi
python3 - "$PUBLISH_LOCK" <<'PYEOF'
import os, sys, time
old = time.time() - 120
os.utime(sys.argv[1], (old, old), follow_symlinks=False)
PYEOF
if HOME="$FAKE_HOME" bash -c "source '$LIB'; ps() { return 1; }; _hooks_snapshot_reclaim_publish_lock '$PUBLISH_LOCK'" \
  && [[ ! -e "$PUBLISH_LOCK" ]]; then
  _pass "stale populated live-PID lock is reclaimed when ps is unavailable"
else
  _fail "stale populated live-PID lock wedged when ps was unavailable"
fi

mkdir "$PUBLISH_LOCK"
printf '%s\n' "$$" > "$PUBLISH_LOCK/pid"
ps -p "$$" -o lstart= 2>/dev/null | tr -d '\r' > "$PUBLISH_LOCK/started"
python3 - "$PUBLISH_LOCK" <<'PYEOF'
import os, sys, time
old = time.time() - 120
os.utime(sys.argv[1], (old, old), follow_symlinks=False)
PYEOF
if ! HOME="$FAKE_HOME" bash -c "source '$LIB'; _hooks_snapshot_reclaim_publish_lock '$PUBLISH_LOCK'" \
  && [[ -d "$PUBLISH_LOCK" ]]; then
  _pass "old exact PID/start live lock is preserved"
else
  _fail "old exact PID/start live lock was reclaimed"
fi
rm -f "$PUBLISH_LOCK/pid" "$PUBLISH_LOCK/started"
rmdir "$PUBLISH_LOCK"

mkdir "$PUBLISH_LOCK"
printf '%s\n' "$$" > "$PUBLISH_LOCK/pid"
printf '%s\n' "definitely-not-the-current-start" > "$PUBLISH_LOCK/started"
if HOME="$FAKE_HOME" bash -c "source '$LIB'; _hooks_snapshot_reclaim_publish_lock '$PUBLISH_LOCK'" \
  && [[ ! -e "$PUBLISH_LOCK" ]]; then
  _pass "proven PID/start mismatch is reclaimed immediately"
else
  _fail "proven PID/start mismatch was not reclaimed"
fi

DEAD_PID=99999999
while kill -0 "$DEAD_PID" 2>/dev/null; do DEAD_PID=$((DEAD_PID - 1)); done
mkdir "$PUBLISH_LOCK"
printf '%s\n' "$DEAD_PID" > "$PUBLISH_LOCK/pid"
printf '%s\n' "old-process" > "$PUBLISH_LOCK/started"
if HOME="$FAKE_HOME" bash -c "source '$LIB'; _hooks_snapshot_reclaim_publish_lock '$PUBLISH_LOCK'" \
  && [[ ! -e "$PUBLISH_LOCK" ]]; then
  _pass "dead PID lock is reclaimed immediately"
else
  _fail "dead PID lock was not reclaimed"
fi

# Immutable generations are retained conservatively but must remain bounded.
for generation_index in 1 2 3 4 5 6 7 8; do
  printf 'generation=%s\n' "$generation_index" > "$REPO_C/hooks/risk-reminder.sh"
  HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"
done
GENERATION_COUNT="$(find "$FAKE_HOME/.agentic/hooks-snapshot/.versions" -mindepth 1 -maxdepth 1 -type d -name "${REPO_C_KEY}.*" | wc -l | tr -d ' ')"
CURRENT_GENERATION="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$SNAP_DIR")"
if [[ "$GENERATION_COUNT" -le 4 && -d "$CURRENT_GENERATION" \
  && "$(cat "$SNAP_DIR/hooks/risk-reminder.sh")" == "generation=8" ]]; then
  _pass "immutable generation retention is bounded and preserves current"
else
  _fail "immutable generation retention is unbounded or removed current (count=$GENERATION_COUNT)"
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
  find -L "$dir" -type f -not -path "$dir/.snapshot-meta.json" | sort
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

HELPER_HASH_BEFORE="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['source_hash'])" "$SNAP_DIR/.snapshot-meta.json")"
echo "# helper changed" >> "$REPO_C/bin/ds-identity"
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"
HELPER_HASH_AFTER="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['source_hash'])" "$SNAP_DIR/.snapshot-meta.json")"

if [[ "$HELPER_HASH_AFTER" != "$HELPER_HASH_BEFORE" ]] && \
   cmp -s "$REPO_C/bin/ds-identity" "$SNAP_DIR/bin/ds-identity" && \
   [[ -x "$SNAP_DIR/bin/ds-identity" ]]; then
  _pass "identity-helper changes affect source_hash and refresh executable snapshot bytes"
else
  _fail "identity-helper change was omitted from snapshot hash/copy refresh"
fi

# A failed refresh must preserve the previously published generation.
PUBLISHED_BEFORE="$(readlink "$SNAP_DIR")"
SNAP_HELPER_BEFORE="$(shasum -a 256 "$SNAP_DIR/bin/ds-identity" | awk '{print $1}')"
mv "$REPO_C/bin/ds-identity" "$REPO_C/bin/ds-identity.saved"
FAILED_REFRESH_RC=0
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null 2>&1" \
  || FAILED_REFRESH_RC=$?
mv "$REPO_C/bin/ds-identity.saved" "$REPO_C/bin/ds-identity"
SNAP_HELPER_AFTER="$(shasum -a 256 "$SNAP_DIR/bin/ds-identity" | awk '{print $1}')"
if [[ "$FAILED_REFRESH_RC" -eq 1 && "$(readlink "$SNAP_DIR")" == "$PUBLISHED_BEFORE" \
  && "$SNAP_HELPER_AFTER" == "$SNAP_HELPER_BEFORE" ]]; then
  _pass "failed refresh preserves the prior published generation byte-for-byte"
else
  _fail "failed refresh changed or removed the prior published generation"
fi

# A reader pins one immutable generation with realpath, then observes a
# complete old or new tree while a refresh atomically retargets the public
# symlink. It must never observe a missing or mixed generation.
printf 'GEN=old\n' > "$REPO_C/hooks/risk-reminder.sh"
printf '#!/usr/bin/env python3\n# GEN=old\nprint(\"helper\")\n' \
  > "$REPO_C/bin/ds-identity"
chmod 700 "$REPO_C/bin/ds-identity"
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"
READER_RESULT="$TMP_ROOT/snapshot-reader-result"
python3 - "$SNAP_DIR" "$READER_RESULT" <<'PYEOF' &
import os
import pathlib
import sys
import time

public, result = sys.argv[1:3]
for _ in range(1000):
    generation = pathlib.Path(os.path.realpath(public))
    try:
        hook = (generation / "hooks" / "risk-reminder.sh").read_text()
        helper = (generation / "bin" / "ds-identity").read_text()
    except OSError as exc:
        pathlib.Path(result).write_text(f"missing:{exc}")
        raise SystemExit(1)
    hook_generation = "old" if "GEN=old" in hook else "new" if "GEN=new" in hook else "unknown"
    helper_generation = "old" if "GEN=old" in helper else "new" if "GEN=new" in helper else "unknown"
    if hook_generation != helper_generation or hook_generation == "unknown":
        pathlib.Path(result).write_text(
            f"mixed:{hook_generation}:{helper_generation}"
        )
        raise SystemExit(1)
    time.sleep(0.001)
pathlib.Path(result).write_text("ok")
PYEOF
READER_PID=$!
sleep 0.05
printf 'GEN=new\n' > "$REPO_C/hooks/risk-reminder.sh"
printf '#!/usr/bin/env python3\n# GEN=new\nprint(\"helper\")\n' \
  > "$REPO_C/bin/ds-identity"
chmod 700 "$REPO_C/bin/ds-identity"
HOME="$FAKE_HOME" bash -c "source '$LIB'; sync_hooks_snapshot '$REPO_C' >/dev/null"
READER_RC=0
wait "$READER_PID" || READER_RC=$?
if [[ "$READER_RC" -eq 0 && "$(cat "$READER_RESULT" 2>/dev/null)" == "ok" \
  && "$(cat "$SNAP_DIR/hooks/risk-reminder.sh")" == "GEN=new" \
  && "$(grep -c 'GEN=new' "$SNAP_DIR/bin/ds-identity")" -eq 1 ]]; then
  _pass "concurrent reader sees only complete old or new immutable generations"
else
  _fail "concurrent reader observed a missing or mixed snapshot generation ($(cat "$READER_RESULT" 2>/dev/null))"
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
    '$REPO_E/bin/ds-identity' \
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
    '$REPO_E/bin/ds-identity' \
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
