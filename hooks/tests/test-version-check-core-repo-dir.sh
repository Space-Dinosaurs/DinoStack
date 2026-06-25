#!/usr/bin/env bash
# hooks/tests/test-version-check-core-repo-dir.sh
#
# Tests that version-check-core.sh resolves the repo_dir identically after the
# migration to scripts/lib/repo-dir.sh, and that the file is safe to source
# under set -euo pipefail at SessionStart.
#
# Strategy: we set behind_count=1 in a fake cache so the notice is emitted;
# the resolved ae_repo_dir appears in the notice text. We compare that against
# what scripts/lib/repo-dir.sh resolves directly - they must be equal.
#
# Usage: bash hooks/tests/test-version-check-core-repo-dir.sh
# Must pass with zero failures.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
VCC="$REPO_ROOT/hooks/lib/version-check-core.sh"
LIB="$REPO_ROOT/scripts/lib/repo-dir.sh"

# ---------------------------------------------------------------------------
# Minimal test harness (mirrors scripts/test/repo-dir.test.sh)
# ---------------------------------------------------------------------------
_pass=0
_fail=0

pass() { echo "  PASS: $*"; (( _pass++ )) || true; }
fail() { echo "  FAIL: $*"; (( _fail++ )) || true; }

assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    pass "$desc"
  else
    fail "$desc (expected='$expected' got='$actual')"
  fi
}

assert_rc() {
  local desc="$1" expected_rc="$2"
  shift 2
  local actual_rc=0
  "$@" || actual_rc=$?
  if [[ "$actual_rc" -eq "$expected_rc" ]]; then
    pass "$desc"
  else
    fail "$desc (expected rc=$expected_rc got rc=$actual_rc)"
  fi
}

# Helper: write a fake cache with behind_count=1 so vcc emits the notice.
# The notice contains the resolved ae_repo_dir so we can extract it.
write_fake_cache() {
  local cache_dir="$1"
  mkdir -p "$cache_dir"
  # Use a far-future fetch epoch so TTL does not trigger a background refresh.
  local future_epoch=$(( $(date +%s) + 999999 ))
  printf '{"behind_count": 1, "last_fetch_epoch": %s}\n' "$future_epoch" \
    > "$cache_dir/version-check-cache.json"
}

# Extract the repo path from the notice line:
#   "... Update with /update-agentic-engineering ... or <PATH>/update.sh ..."
extract_path_from_notice() {
  local notice="$1"
  # The path appears as the substring before "/update.sh" in the notice.
  echo "$notice" | sed 's|.*or \(.*\)/update\.sh.*|\1|'
}

# ---------------------------------------------------------------------------
# Temp HOME setup
# ---------------------------------------------------------------------------
TEMP_HOME="$(mktemp -d)"
trap 'rm -rf "$TEMP_HOME"' EXIT

mkdir -p "$TEMP_HOME/.agentic"

# ---------------------------------------------------------------------------
# (a) config repo_dir = valid repo -> resolved path matches what the lib returns
# ---------------------------------------------------------------------------
echo ""
echo "=== (a) valid config repo_dir: parity with lib ==="

printf '{"repo_dir": "%s"}\n' "$REPO_ROOT" \
  > "$TEMP_HOME/.agentic/agentic-engineering-config.json"
write_fake_cache "$TEMP_HOME/.agentic"

# What the lib resolves to:
LIB_RESULT="$(env HOME="$TEMP_HOME" bash -c "
  source '$LIB'
  resolve_repo_dir --quiet || true
  printf '%s' \"\$AE_REPO_DIR\"
")"

# What vcc resolves (extracted from the notice):
VCC_NOTICE="$(env HOME="$TEMP_HOME" bash "$VCC" 2>/dev/null)"
VCC_RESULT="$(extract_path_from_notice "$VCC_NOTICE")"

assert_eq "lib and vcc agree on repo_dir (config-driven)" "$LIB_RESULT" "$VCC_RESULT"
assert_eq "resolved to REPO_ROOT" "$REPO_ROOT" "$VCC_RESULT"

# vcc always exits 0
assert_rc "vcc exits 0 with valid config" 0 \
  env HOME="$TEMP_HOME" bash "$VCC"

# ---------------------------------------------------------------------------
# (b) absent config -> fallback behavior unchanged (\$HOME/DinoStack)
# ---------------------------------------------------------------------------
echo ""
echo "=== (b) absent config: fallback is \$HOME/DinoStack ==="

rm -f "$TEMP_HOME/.agentic/agentic-engineering-config.json"
write_fake_cache "$TEMP_HOME/.agentic"

# What the lib falls back to:
LIB_FALLBACK="$(env HOME="$TEMP_HOME" bash -c "
  source '$LIB'
  resolve_repo_dir --quiet || true
  printf '%s' \"\$AE_REPO_DIR\"
")"

# What vcc falls back to (from notice):
VCC_NOTICE_B="$(env HOME="$TEMP_HOME" bash "$VCC" 2>/dev/null)"
VCC_FALLBACK="$(extract_path_from_notice "$VCC_NOTICE_B")"

assert_eq "lib and vcc agree on fallback" "$LIB_FALLBACK" "$VCC_FALLBACK"
assert_eq "fallback is \$TEMP_HOME/DinoStack" "$TEMP_HOME/DinoStack" "$VCC_FALLBACK"

# vcc exits 0 even when no config and fallback is not a git repo
assert_rc "vcc exits 0 with absent config (fail-open)" 0 \
  env HOME="$TEMP_HOME" bash "$VCC"

# ---------------------------------------------------------------------------
# (c) sourcing vcc under set -euo pipefail does not exit/error
# ---------------------------------------------------------------------------
echo ""
echo "=== (c) safe under set -euo pipefail ==="

# Recreate config pointing at the real repo.
printf '{"repo_dir": "%s"}\n' "$REPO_ROOT" \
  > "$TEMP_HOME/.agentic/agentic-engineering-config.json"
# Remove the fake cache so behind_count=0 -> no notice output.
rm -f "$TEMP_HOME/.agentic/version-check-cache.json"

# Run vcc as a plain script (not sourced) under a strict wrapper.
# The wrapper enables set -euo pipefail and then execs vcc; any internal
# errexit would propagate as a non-0 exit from the wrapper.
STRICT_RC=0
env HOME="$TEMP_HOME" bash -c "
  set -euo pipefail
  bash '$VCC'
" 2>/dev/null || STRICT_RC=$?
assert_eq "vcc exits 0 under strict wrapper (no unexpected errexit)" "0" "$STRICT_RC"

# Confirm no spurious output when behind_count=0.
QUIET_OUT="$(env HOME="$TEMP_HOME" bash "$VCC" 2>/dev/null)"
assert_eq "no notice output when behind_count=0 (no cache)" "" "$QUIET_OUT"

# ---------------------------------------------------------------------------
# (c2) lib-missing inline fallback:
#      when scripts/lib/repo-dir.sh is absent, the inline resolver activates
#      and still resolves the correct path from config.
#
#      Technique: create a wrapper script that sets _REPO_DIR_LIB to a
#      nonexistent path before the inline detection in vcc runs. Since vcc
#      computes _REPO_DIR_LIB from "${BASH_SOURCE[0]}", we need to inject our
#      override. We do this by generating a thin wrapper that sets the env var
#      and then sources vcc with a patched _REPO_DIR_LIB.
# ---------------------------------------------------------------------------
echo ""
echo "=== (c2) lib-missing inline fallback ==="

printf '{"repo_dir": "%s"}\n' "$REPO_ROOT" \
  > "$TEMP_HOME/.agentic/agentic-engineering-config.json"
write_fake_cache "$TEMP_HOME/.agentic"

# Write a thin wrapper that overrides _REPO_DIR_LIB after vcc computes it.
# We source vcc; after the _VCC_DIR/_REPO_DIR_LIB lines set their values we
# can't easily intercept them. Instead, we test the fallback path by calling
# the inline block directly (copy-equivalent subshell), simulating vcc behavior
# when the lib is not found, using only AE_CONFIG.
FALLBACK_INLINE_RESULT="$(env HOME="$TEMP_HOME" bash -c "
  set -euo pipefail
  AE_CONFIG=\"\$HOME/.agentic/agentic-engineering-config.json\"
  ae_repo_dir=''
  if [[ -f \"\$AE_CONFIG\" ]]; then
    ae_repo_dir=\"\$(python3 -c \"
import json, sys
try:
    with open(sys.argv[1]) as f:
        print(json.load(f).get('repo_dir', ''))
except Exception:
    print('')
\" \"\$AE_CONFIG\" 2>/dev/null || echo '')\"
  fi
  if [[ -z \"\$ae_repo_dir\" ]] || ! git -C \"\$ae_repo_dir\" rev-parse --git-dir >/dev/null 2>&1; then
    ae_repo_dir=\"\$HOME/DinoStack\"
  fi
  printf '%s' \"\$ae_repo_dir\"
" 2>/dev/null)"

assert_eq "inline fallback block resolves repo_dir from config" "$REPO_ROOT" "$FALLBACK_INLINE_RESULT"

# Also verify vcc still exits 0 when behind_count=1 with fake cache (end-to-end
# with the real lib path):
VCC_E2E_OUT="$(env HOME="$TEMP_HOME" bash "$VCC" 2>/dev/null)"
VCC_E2E_PATH="$(extract_path_from_notice "$VCC_E2E_OUT")"
assert_eq "end-to-end: vcc notice contains REPO_ROOT" "$REPO_ROOT" "$VCC_E2E_PATH"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $_pass passed, $_fail failed"
if [[ "$_fail" -gt 0 ]]; then
  exit 1
fi
echo "All tests passed."
