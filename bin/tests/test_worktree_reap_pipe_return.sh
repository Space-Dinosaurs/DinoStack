#!/usr/bin/env bash
# Purpose: Regression guard for the DS-196 session-start reap pipe-inheritance
#          fix. Extracts the ACTUAL fenced bash block from
#          content/references/worktree-lifecycle.md's "## Session-start
#          prune script" section (never a hand-retyped reimplementation, per
#          the fence-extraction pattern established at
#          bin/tests/test_ticket_triage_inflight.sh:151:
#          `awk '/^```/{f=!f; next} f'` against a pre-sliced section body)
#          and executes it in a disposable scratch git repo with a stub
#          `ds-cleanup-worktrees` (sleeps ~2s, exits 0, records a call count,
#          and echoes a fixed sentinel `STUB_REAP_RAN` to its own stdout) and
#          a no-op stub `ds-branch-prune`, both placed first on PATH. Closes
#          the measured defect: the backgrounded subshell inherited the
#          caller's stdout pipe, so `&` never decoupled it and a harness
#          Bash-tool call blocked for the reap's full duration.
#
# Public API: ./bin/tests/test_worktree_reap_pipe_return.sh
#             Exits 0 on all pass, 1 on any failure.
#             Auto-wired into CI by the bin/tests/test_*.sh glob in
#             .github/workflows/bin-tests.yml:232 - no orphans entry needed.
#
# Upstream deps: bash, git, awk, sed, grep, date. Reads
#                content/references/worktree-lifecycle.md from the checkout.
#                No jq, no python3, no network (the scratch `origin` remote
#                is a local bare repo, never a real network fetch).
#
# Downstream consumers: developer running locally before commit; CI
#                       (.github/workflows/bin-tests.yml).
#
# Failure modes: a failing assertion below; all git/file state is created
#                under `mktemp -d` and never touches the real checkout's
#                own `.agentic/worktree-reap.log`.
#
# Performance: ~2-4s wall time (dominated by the stub's ~2s sleep, run twice).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DOC="$REPO_DIR/content/references/worktree-lifecycle.md"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }

if [[ ! -f "$DOC" ]]; then
  echo "FAIL: $DOC not found" >&2
  exit 1
fi

# Section body, extracted once - scoped to the Session-start prune script
# section only, so this test never sees an unrelated fenced block elsewhere
# in the file.
START_LINE="$(grep -n '^## Session-start prune script' "$DOC" | head -1 | cut -d: -f1)"
END_LINE="$(grep -n '^## Ad-hoc (non-`/ds-implement-ticket`) worktree cleanup obligation' "$DOC" | head -1 | cut -d: -f1)"
if [[ -z "$START_LINE" || -z "$END_LINE" ]]; then
  echo "FAIL: could not locate the Session-start prune script section boundaries" >&2
  exit 1
fi
SECTION_BODY="$(sed -n "${START_LINE},${END_LINE}p" "$DOC")"

FENCE="$(printf '%s\n' "$SECTION_BODY" | awk '/^```/{f=!f; next} f')"
if [[ -z "$FENCE" ]]; then
  echo "FAIL: Session-start prune script fence extracted empty - heading mismatch or missing code fence" >&2
  exit 1
fi

BLOCK_FILE="$(mktemp)"
printf '%s\n' "$FENCE" > "$BLOCK_FILE"
trap 'rm -f "$BLOCK_FILE"' EXIT

# --- Stub bin/, placed first on PATH ---------------------------------------
STUB_BIN_DIR="$(mktemp -d)"
cat > "$STUB_BIN_DIR/ds-cleanup-worktrees" <<'STUB_EOF'
#!/usr/bin/env bash
if [[ -n "${STUB_CALL_COUNT_FILE:-}" ]]; then
  count=0
  [[ -f "$STUB_CALL_COUNT_FILE" ]] && count="$(cat "$STUB_CALL_COUNT_FILE")"
  echo $((count + 1)) > "$STUB_CALL_COUNT_FILE"
fi
sleep 2
echo "STUB_REAP_RAN"
exit 0
STUB_EOF
chmod +x "$STUB_BIN_DIR/ds-cleanup-worktrees"
cat > "$STUB_BIN_DIR/ds-branch-prune" <<'STUB_EOF'
#!/usr/bin/env bash
exit 0
STUB_EOF
chmod +x "$STUB_BIN_DIR/ds-branch-prune"

# --- Disposable scratch repo, with a local bare `origin` so `git fetch
# origin` (the block's first line) succeeds without any real network call.
WORK_DIR="$(mktemp -d)"
ORIGIN_DIR="$(mktemp -d)/origin.git"
git init -q --bare "$ORIGIN_DIR"
git init -q "$WORK_DIR"
git -C "$WORK_DIR" remote add origin "$ORIGIN_DIR"

CLEANUP_DIRS=("$STUB_BIN_DIR" "$WORK_DIR" "$(dirname "$ORIGIN_DIR")")
_cleanup_all() {
  rm -f "$BLOCK_FILE" 2>/dev/null || true
  for d in "${CLEANUP_DIRS[@]}"; do
    rm -rf "$d" 2>/dev/null || true
  done
}
trap _cleanup_all EXIT

REPO_ROOT_RESOLVED="$(cd "$WORK_DIR" && git rev-parse --show-toplevel)"
LOG_FILE="$REPO_ROOT_RESOLVED/.agentic/worktree-reap.log"

echo ""
echo "--- (a): the extracted block piped through | cat returns well under 1s, even though the stub sleeps ~2s ---"
CALL_COUNT_FILE_A="$WORK_DIR/.call_count_a"
rm -f "$CALL_COUNT_FILE_A"
start_ns=$(date +%s%N)
(
  cd "$WORK_DIR" || exit 1
  PATH="$STUB_BIN_DIR:$PATH" STUB_CALL_COUNT_FILE="$CALL_COUNT_FILE_A" bash "$BLOCK_FILE"
) | cat >/dev/null
end_ns=$(date +%s%N)
elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))
if [[ "$elapsed_ms" -lt 1000 ]]; then
  _pass "(a) piped call returned in ${elapsed_ms}ms (< 1000ms) despite the stub's ~2s sleep"
else
  _fail "(a) piped call took ${elapsed_ms}ms (>= 1000ms) - the subshell is still blocking the pipe"
fi

echo ""
echo "--- (b): after a bounded poll (up to 5s), the reap log contains the header line and the stub's STUB_REAP_RAN sentinel exactly once ---"
found=0
for _ in $(seq 1 50); do
  if [[ -f "$LOG_FILE" ]] && grep -q 'STUB_REAP_RAN' "$LOG_FILE" 2>/dev/null; then
    found=1
    break
  fi
  sleep 0.1
done
if [[ "$found" -eq 1 ]]; then
  # `grep -c` always prints a count (0 or more) to its own stdout, even on
  # zero matches - it only exits nonzero. `|| echo 0` here would therefore
  # APPEND a second "0" line inside the same command substitution on a
  # no-match run, producing a two-line value like "0\n0" that then fails
  # the `-ge`/`-eq` integer comparisons below with a bad-math error instead
  # of comparing. Trust grep's own printed count; no fallback needed.
  header_count="$(grep -cE '^=== reap .* pid [0-9]+ ===$' "$LOG_FILE" 2>/dev/null)"
  sentinel_count="$(grep -cF 'STUB_REAP_RAN' "$LOG_FILE" 2>/dev/null)"
  if [[ "$header_count" -ge 1 && "$sentinel_count" -eq 1 ]]; then
    _pass "(b) log contains the header line and exactly one STUB_REAP_RAN sentinel"
  else
    _fail "(b) log present but wrong shape (header_count=$header_count, sentinel_count=$sentinel_count)"
  fi
else
  _fail "(b) log at $LOG_FILE never contained STUB_REAP_RAN within the 5s poll window"
fi

echo ""
echo "--- (c): with AE_WORKTREE_REAP_DISABLE=1, the stub is never invoked (checked after the same poll window) ---"
CALL_COUNT_FILE_C="$WORK_DIR/.call_count_c"
rm -f "$CALL_COUNT_FILE_C"
(
  cd "$WORK_DIR" || exit 1
  PATH="$STUB_BIN_DIR:$PATH" STUB_CALL_COUNT_FILE="$CALL_COUNT_FILE_C" AE_WORKTREE_REAP_DISABLE=1 bash "$BLOCK_FILE"
) | cat >/dev/null
sleep 5
if [[ ! -f "$CALL_COUNT_FILE_C" ]]; then
  _pass "(c) stub call-count file absent - AE_WORKTREE_REAP_DISABLE=1 fully suppressed the reap invocation"
elif [[ "$(cat "$CALL_COUNT_FILE_C")" == "0" ]]; then
  _pass "(c) stub call-count file reads 0 - AE_WORKTREE_REAP_DISABLE=1 fully suppressed the reap invocation"
else
  _fail "(c) stub was invoked ($(cat "$CALL_COUNT_FILE_C") call(s)) despite AE_WORKTREE_REAP_DISABLE=1"
fi

echo ""
echo "PASS=$PASS FAIL=$FAIL"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
