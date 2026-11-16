#!/usr/bin/env bash
# Purpose: Behavioral tests for hooks/disk-space-warn.sh against a stub `df`
#          and a scratch HOME: silent above the threshold; fires once below
#          it with valid PostToolUse JSON naming absolute tool paths from a
#          fake repo_dir config; silent again within 30 minutes; off at 0;
#          `abc`, `08` and an overflow value behave as 50; exit 0 and
#          silent on a df failure or an unwritable HOME; never reads stdin.
# Public API: bash hooks/tests/test-disk-space-warn.sh (exit 0 all pass, 1 any fail).
# Upstream deps: bash, git, python3, mkfifo.
# Downstream consumers: .github/workflows/hooks-tests.yml (hooks/tests/test-*.sh glob).
# Failure modes: prints FAIL lines and exits 1. Never touches the real HOME.

set -uo pipefail

HOOK="$(cd "$(dirname "$0")/.." && pwd)/disk-space-warn.sh"
TMP_ROOT="$(mktemp -d)"
PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
_cleanup() {
  chmod -R u+w "$TMP_ROOT" 2>/dev/null
  find "$TMP_ROOT" -depth -delete 2>/dev/null
}
trap _cleanup EXIT

STUB="$TMP_ROOT/stub"
mkdir -p "$STUB"
cat > "$STUB/df" <<'EOF'
#!/bin/sh
[ -n "${STUB_DF_FAIL:-}" ] && exit 1
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "/dev/disk9 1000000000 1 ${STUB_DF_AVAIL_KB} 50% /Volumes/Big Disk"
EOF
chmod +x "$STUB/df"

REPO="$TMP_ROOT/repo"
mkdir -p "$REPO/bin"
git init -q "$REPO"
for tool in ds-disk ds-cleanup-worktrees; do
  printf '#!/bin/sh\nexit 0\n' > "$REPO/bin/$tool"
  chmod +x "$REPO/bin/$tool"
done

GIB=1048576
N=0
# new_home: sets H to a fresh HOME whose repo_dir config names the fake repo.
new_home() {
  N=$((N + 1))
  H="$TMP_ROOT/home$N"
  mkdir -p "$H/.agentic"
  printf '{"repo_dir": "%s"}\n' "$REPO" > "$H/.agentic/agentic-engineering-config.json"
}

# run_hook <home> <avail_kb> [VAR=value...]: stdout in $OUT, exit status in $RC.
run_hook() {
  local h="$1" avail="$2"
  shift 2
  OUT="$(env -u AE_DISK_WARN_FREE_GB HOME="$h" PATH="$STUB:$PATH" CLAUDE_PROJECT_DIR="$TMP_ROOT" \
    STUB_DF_AVAIL_KB="$avail" "$@" "$BASH" "$HOOK" < /dev/null)"
  RC=$?
}

expect_silent() {
  if [[ "$RC" -eq 0 && -z "$OUT" ]]; then _pass "$1"; else _fail "$1 (rc=$RC out=$OUT)"; fi
}

expect_fires() {
  if [[ "$RC" -ne 0 ]]; then _fail "$1: rc=$RC"; return; fi
  if python3 - "$OUT" "$REPO" <<'PYEOF'
import json, sys
d = json.loads(sys.argv[1])
repo = sys.argv[2]
h = d["hookSpecificOutput"]
assert h["hookEventName"] == "PostToolUse", h
msg = h["additionalContext"]
assert f'"{repo}/bin/ds-disk" --sweep' in msg, msg
assert f'"{repo}/bin/ds-cleanup-worktrees" --dry-run --explain' in msg, msg
assert "/Volumes/Big Disk" in msg, msg
assert "threshold 50 GiB" in msg, msg
assert len(d) == 1
PYEOF
  then _pass "$1"; else _fail "$1 (out=$OUT)"; fi
}

new_home
run_hook "$H" $((60 * GIB))
expect_silent "above threshold: silent"

new_home
run_hook "$H" $((40 * GIB))
expect_fires "below threshold: fires with absolute tool paths"
if [[ "$(grep -c 'threshold_gib=50' "$H/.agentic/disk-warn.log" 2>/dev/null)" == 1 ]]; then
  _pass "fire appended one log line"
else
  _fail "fire did not append exactly one log line"
fi
run_hook "$H" $((40 * GIB))
expect_silent "second call within 30 min: silent"
touch -t 202001010000 "$H/.agentic/disk-warn.stamp"
run_hook "$H" $((40 * GIB))
expect_fires "stamp older than 30 min: fires again"

new_home
run_hook "$H" $((1 * GIB)) AE_DISK_WARN_FREE_GB=0
expect_silent "threshold 0: silent"
if [[ ! -e "$H/.agentic/disk-warn.stamp" ]]; then _pass "threshold 0: no stamp written"; else _fail "threshold 0 wrote a stamp"; fi

for v in abc 08 99999999999999999999 -5 ""; do
  new_home
  run_hook "$H" $((40 * GIB)) "AE_DISK_WARN_FREE_GB=$v"
  expect_fires "AE_DISK_WARN_FREE_GB='$v' behaves as 50"
done

new_home
run_hook "$H" $((7 * GIB)) AE_DISK_WARN_FREE_GB=8
if [[ "$OUT" == *"threshold 8 GiB"* ]]; then _pass "valid threshold 8 is honored"; else _fail "threshold 8 not honored: $OUT"; fi
new_home
run_hook "$H" $((10 * GIB)) AE_DISK_WARN_FREE_GB=9
expect_silent "10 GiB free under threshold 9: silent"

new_home
run_hook "$H" $((40 * GIB)) STUB_DF_FAIL=1
expect_silent "df failure: exit 0, silent"

H="$TMP_ROOT/readonly-home"
mkdir -p "$H"
chmod 555 "$H"
run_hook "$H" $((40 * GIB))
expect_silent "unwritable HOME: exit 0, silent"
chmod 755 "$H"

new_home
FIFO="$TMP_ROOT/stdin.fifo"
mkfifo "$FIFO"
exec 3<>"$FIFO"
env -u AE_DISK_WARN_FREE_GB HOME="$H" PATH="$STUB:$PATH" CLAUDE_PROJECT_DIR="$TMP_ROOT" \
  STUB_DF_AVAIL_KB=$((40 * GIB)) "$BASH" "$HOOK" < "$FIFO" > /dev/null &
HOOK_PID=$!
for i in 1 2 3 4 5 6 7 8 9 10; do
  kill -0 "$HOOK_PID" 2>/dev/null || break
  sleep 0.5
done
if kill -0 "$HOOK_PID" 2>/dev/null; then
  kill "$HOOK_PID" 2>/dev/null
  _fail "hook blocked on an open, empty stdin"
else
  _pass "hook never reads stdin"
fi
wait "$HOOK_PID" 2>/dev/null
exec 3>&-

echo ""
echo "Results: $PASS passed, $FAIL failed."
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
