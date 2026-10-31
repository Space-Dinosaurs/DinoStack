#!/usr/bin/env bash
# Purpose: Regression guard for the SessionStart worktree sweep launched by
#          hooks/session-start-wrap.sh. Runs the real hook against a scratch
#          git repo with a stub `ds-cleanup-worktrees` (a Python script, since
#          the hook invokes `python3 "$DS_CLEANUP_BIN"`) that answers
#          `--count-only` at once and otherwise sleeps ~4s, records a call
#          count, and prints a sentinel `STUB_REAP_RAN`. Asserts the hook
#          never waits on the sweep (the DS-196 pipe-inheritance defect: a
#          backgrounded child holding the caller's stdout pipe blocks the
#          caller for the sweep's full duration), that the sweep appends to
#          its per-repo log, and that a second launch within 6 h is skipped.
#          The AE_WORKTREE_REAP_DISABLE kill switch is covered by
#          hooks/tests/test-session-start-wrap-worktree-nudge.js (W19).
#
# Public API: ./bin/tests/test_worktree_reap_pipe_return.sh
#             Exits 0 on all pass, 1 on any failure.
#             Auto-wired into CI by the bin/tests/test_*.sh glob in
#             .github/workflows/bin-tests.yml - no orphans entry needed.
#
# Upstream deps: bash, git, python3, grep. Runs hooks/session-start-wrap.sh
#                from the checkout. No network.
#
# Downstream consumers: developer running locally before commit; CI
#                       (.github/workflows/bin-tests.yml).
#
# Failure modes: a failing assertion below; all state lives under
#                `mktemp -d` with a scratch HOME, never the real
#                ~/.agentic/worktree-reap/.
#
# Performance: ~15s wall time (three stub runs of ~4s, polled).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/hooks/session-start-wrap.sh"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

if [[ ! -f "$HOOK" ]]; then
  echo "FAIL: $HOOK not found" >&2
  exit 1
fi

SCRATCH="$(mktemp -d)"
trap 'find "$SCRATCH" -depth -delete 2>/dev/null || true' EXIT
FAKE_HOME="$SCRATCH/home"
MOCK_REPO="$SCRATCH/mock-dinostack"
PROJECT="$SCRATCH/project"
CALL_COUNT_FILE="$SCRATCH/call-count"
mkdir -p "$FAKE_HOME/.agentic" "$MOCK_REPO/bin"

# resolve_repo_dir only accepts a repo_dir that is a git repo.
git init -q "$MOCK_REPO"
printf '{"repo_dir": "%s"}\n' "$MOCK_REPO" > "$FAKE_HOME/.agentic/agentic-engineering-config.json"
cat > "$MOCK_REPO/bin/ds-cleanup-worktrees" <<STUB_EOF
import sys, time
if '--count-only' in sys.argv:
    print('ds-cleanup-worktrees: mode=count-only entries=2')
    sys.exit(0)
path = '$CALL_COUNT_FILE'
try:
    count = int(open(path).read())
except (OSError, ValueError):
    count = 0
open(path, 'w').write(str(count + 1))
time.sleep(4)
print('STUB_REAP_RAN')
STUB_EOF
chmod +x "$MOCK_REPO/bin/ds-cleanup-worktrees"

git init -q "$PROJECT"
PROJECT_ROOT="$(cd "$PROJECT" && pwd -P)"
REAP_ID="$(python3 -c 'import hashlib, sys; print(hashlib.sha1(sys.argv[1].encode()).hexdigest()[:8])' "$PROJECT_ROOT")"
LOG_FILE="$FAKE_HOME/.agentic/worktree-reap/project-${REAP_ID}.log"

now_ms() { python3 -c 'import time; print(int(time.time() * 1000))'; }
call_count() { cat "$CALL_COUNT_FILE" 2>/dev/null || echo 0; }
run_hook() {
  printf '{"cwd": "%s", "source": "startup"}' "$PROJECT" \
    | env -u AE_WORKTREE_REAP_DISABLE HOME="$FAKE_HOME" AGENTIC_WRAP_DAEMON=1 bash "$HOOK" | cat >/dev/null
}
wait_for_sentinels() {
  local want="$1"
  for _ in $(seq 1 100); do
    if [[ "$(grep -c 'STUB_REAP_RAN' "$LOG_FILE" 2>/dev/null)" -ge "$want" ]]; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

echo ""
echo "--- (a): the hook, piped through | cat, returns well before the ~4s sweep finishes ---"
start_ms="$(now_ms)"
run_hook
elapsed_ms=$(( $(now_ms) - start_ms ))
if [[ "$elapsed_ms" -lt 3000 ]]; then
  _pass "(a) piped hook returned in ${elapsed_ms}ms (< 3000ms) despite the stub's ~4s sweep"
else
  _fail "(a) piped hook took ${elapsed_ms}ms (>= 3000ms) - the sweep is holding the hook's pipe"
fi

echo ""
echo "--- (b): the sweep appends a header and its own output to the per-repo log ---"
if wait_for_sentinels 1; then
  header_count="$(grep -cE "^=== reap .* pid [0-9]+ root ${PROJECT_ROOT} ===$" "$LOG_FILE")"
  if [[ "$header_count" -eq 1 ]] && [[ "$(call_count)" -eq 1 ]]; then
    _pass "(b) $LOG_FILE holds one header and the stub's output"
  else
    _fail "(b) log present but wrong shape (header_count=$header_count, calls=$(call_count))"
  fi
else
  _fail "(b) $LOG_FILE never contained STUB_REAP_RAN within the poll window"
fi

echo ""
echo "--- (c): a second session within 6 h launches nothing; a log older than 6 h launches again ---"
run_hook
sleep 5
if [[ "$(call_count)" -eq 1 ]]; then
  _pass "(c) second launch within 6 h skipped (calls=1)"
else
  _fail "(c) second launch within 6 h ran the sweep again (calls=$(call_count))"
fi
python3 -c 'import os, sys, time; t = time.time() - 7 * 3600; os.utime(sys.argv[1], (t, t))' "$LOG_FILE"
run_hook
if wait_for_sentinels 2 && [[ "$(call_count)" -eq 2 ]]; then
  _pass "(c) a log older than 6 h lets the next session launch the sweep"
else
  _fail "(c) a stale log did not relaunch the sweep (calls=$(call_count))"
fi

echo ""
echo "PASS=$PASS FAIL=$FAIL"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
