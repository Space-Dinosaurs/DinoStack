#!/usr/bin/env bash
#
# Purpose: Runtime regression test for DS-220 (DS-217 unit 2 follow-up):
#          asserts automation/dinostack-worktree-reap/run.sh's summary NOTE
#          for a nonzero `pr_query_error_total` is derived by scanning the
#          FULL `rows` list, not just the worst-5 `top` slice, and that the
#          NOTE only ever appears when the failure count is actually
#          nonzero. Builds two INDEPENDENT `mktemp -d` roots (never a shared
#          LOG_DIR - run.sh derives its log filename at one-second
#          granularity and opens it append-mode, so sharing a directory
#          makes any assertion timing-dependent), each with its own
#          `logs/` subdir, its own copy of the real run.sh, its own
#          config.env, and its own stub `DS_CLEANUP_BIN` python script that
#          ignores its arguments and prints a fixed JSON payload. The
#          fail-root payload has 6 rows: 5 clean rows plus one row named
#          `unique-tail-repo-zzz` (shares no substring with the other five
#          in either direction) ranked LOWEST by `nonroot_worktrees` - so it
#          is never in the worst-5 `top` slice - carrying
#          `pr_query_error_count: 2` and a top-level
#          `pr_query_error_total: 2`. The clean-root payload has the same
#          6-row shape with every `pr_query_error_count` (and the top-level
#          total) at 0.
#
#          Two named mutations this test is verified to redden (see the
#          Failure modes note below for how each was confirmed):
#            (1) revert the implementation's scan source from `rows` to
#                `top` inside run.sh's summary-builder heredoc - the
#                fail-root NOTE assertions (repo name, backtick phrase,
#                FLOOR phrase) all fail, since `unique-tail-repo-zzz` never
#                appears in `top`.
#            (2) make the NOTE block unconditional (drop the
#                `if pr_query_error_total:` guard) - the clean-root
#                negative assertion (NOTE phrase absent) fails, since the
#                NOTE then prints even when the failure count is 0.
#
# Public API: ./bin/tests/test_worktree_reap_summary_query_failures.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3 (invokes the real run.sh, which itself shells
#                out to "$PYTHON_BIN" against the stub DS_CLEANUP_BIN this
#                test writes), mktemp, grep. Never touches
#                ~/.dinostack-worktree-reap or any real repo.
#
# Downstream consumers: bin-sh-tests CI job (auto-collected via the
#                        bin/tests/test_*.sh glob in
#                        .github/workflows/bin-tests.yml).
#
# Failure modes: fails loud on a missing/empty log file (never a vacuous
#                pass on an absent artifact); the clean-root sub-case
#                asserts exit 0, a non-empty log, AND the positive control
#                "worst-repos summary:" BEFORE asserting the NOTE phrase is
#                absent, so an accidentally-empty or never-written log
#                cannot be misread as "the NOTE is correctly absent". Both
#                named mutations above were manually applied to run.sh and
#                confirmed to redden the specific assertions cited, then
#                reverted before this file was committed.
#
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REAL_RUN_SH="$REPO_ROOT/automation/dinostack-worktree-reap/run.sh"

FAILURES=0
fail() {
  echo "FAIL: $1" >&2
  FAILURES=$((FAILURES + 1))
}
pass() {
  echo "PASS: $1"
}

if [[ ! -f "$REAL_RUN_SH" ]]; then
  fail "run.sh not found at $REAL_RUN_SH"
  echo "=== 1 failure(s) ===" >&2
  exit 1
fi

# --- Shared no-op PATH shim: never narrow PATH (breaks mkdir/date/head/
#     find/tail/tr/cut) - only prepend a directory holding a no-op
#     `osascript` so run.sh's best-effort banner never pops a real macOS
#     notification during this test. -------------------------------------
FAKEBIN="$(mktemp -d)"
cat >"$FAKEBIN/osascript" <<'SH'
#!/bin/bash
exit 0
SH
chmod +x "$FAKEBIN/osascript"
export PATH="$FAKEBIN:$PATH"

CLEANUP_ROOTS=()
cleanup() {
  for d in ${CLEANUP_ROOTS[@]+"${CLEANUP_ROOTS[@]}"}; do
    rm -f "$d"/* "$d"/logs/* 2>/dev/null || true
    rmdir "$d/logs" 2>/dev/null || true
    rmdir "$d" 2>/dev/null || true
  done
  rm -f "$FAKEBIN/osascript" 2>/dev/null || true
  rmdir "$FAKEBIN" 2>/dev/null || true
}
trap cleanup EXIT

# --- setup_root <root> <payload_file> ------------------------------------
# Materializes one independent run root: a copy of the real run.sh, its own
# config.env (own LOG_DIR, own stub DS_CLEANUP_BIN), and a stub python
# script that ignores every argument and prints the given fixed payload.
setup_root() {
  local root="$1"
  local payload_file="$2"

  cp "$REAL_RUN_SH" "$root/run.sh"
  chmod +x "$root/run.sh"
  mkdir -p "$root/logs"

  cp "$payload_file" "$root/payload.json"

  cat >"$root/fake-ds-cleanup-worktrees.py" <<'PYEOF'
#!/usr/bin/env python3
import os
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "payload.json"), encoding="utf-8") as f:
    print(f.read().strip())
PYEOF

  cat >"$root/config.env" <<EOF
DS_CLEANUP_BIN="$root/fake-ds-cleanup-worktrees.py"
PYTHON_BIN="python3"
LOG_DIR="$root/logs"
EXTRA_PATH=""
EOF
}

# --- Fail-root: 6 rows, lowest-ranked row carries the query failure. -----
FAIL_ROOT="$(mktemp -d)"
CLEANUP_ROOTS+=("$FAIL_ROOT")
FAIL_PAYLOAD="$(mktemp)"
cat >"$FAIL_PAYLOAD" <<'JSON'
{
  "tier": "deep",
  "rows": [
    {"repo": "aaa-repo-one", "nonroot_worktrees": 50, "eligible": 5, "pr_query_error_count": 0},
    {"repo": "bbb-repo-two", "nonroot_worktrees": 40, "eligible": 4, "pr_query_error_count": 0},
    {"repo": "ccc-repo-three", "nonroot_worktrees": 30, "eligible": 3, "pr_query_error_count": 0},
    {"repo": "ddd-repo-four", "nonroot_worktrees": 20, "eligible": 2, "pr_query_error_count": 0},
    {"repo": "eee-repo-five", "nonroot_worktrees": 10, "eligible": 1, "pr_query_error_count": 0},
    {"repo": "unique-tail-repo-zzz", "nonroot_worktrees": 1, "eligible": 1, "pr_query_error_count": 2}
  ],
  "truncated": false,
  "pr_query_error_total": 2
}
JSON
setup_root "$FAIL_ROOT" "$FAIL_PAYLOAD"
rm -f "$FAIL_PAYLOAD"

# --- Clean-root: same 6-row shape, every failure count at 0. -------------
CLEAN_ROOT="$(mktemp -d)"
CLEANUP_ROOTS+=("$CLEAN_ROOT")
CLEAN_PAYLOAD="$(mktemp)"
cat >"$CLEAN_PAYLOAD" <<'JSON'
{
  "tier": "deep",
  "rows": [
    {"repo": "clean-repo-one", "nonroot_worktrees": 50, "eligible": 5, "pr_query_error_count": 0},
    {"repo": "clean-repo-two", "nonroot_worktrees": 40, "eligible": 4, "pr_query_error_count": 0},
    {"repo": "clean-repo-three", "nonroot_worktrees": 30, "eligible": 3, "pr_query_error_count": 0},
    {"repo": "clean-repo-four", "nonroot_worktrees": 20, "eligible": 2, "pr_query_error_count": 0},
    {"repo": "clean-repo-five", "nonroot_worktrees": 10, "eligible": 1, "pr_query_error_count": 0},
    {"repo": "clean-repo-six", "nonroot_worktrees": 1, "eligible": 1, "pr_query_error_count": 0}
  ],
  "truncated": false,
  "pr_query_error_total": 0
}
JSON
setup_root "$CLEAN_ROOT" "$CLEAN_PAYLOAD"
rm -f "$CLEAN_PAYLOAD"

# --- latest_log <root> ---------------------------------------------------
# Finds the single run-*.log run.sh just wrote in <root>/logs.
latest_log() {
  local root="$1"
  find "$root/logs" -maxdepth 1 -name 'run-*.log' -type f | sort | tail -1
}

# === Fail-root sub-case ====================================================
bash "$FAIL_ROOT/run.sh" >/dev/null 2>&1
fail_rc=$?
if [[ "$fail_rc" -eq 0 ]]; then
  pass "fail-root run.sh exited 0"
else
  fail "fail-root run.sh exited $fail_rc (expected 0)"
fi

FAIL_LOG="$(latest_log "$FAIL_ROOT")"
if [[ -z "$FAIL_LOG" || ! -f "$FAIL_LOG" ]]; then
  fail "fail-root: no run-*.log found under $FAIL_ROOT/logs"
elif [[ ! -s "$FAIL_LOG" ]]; then
  fail "fail-root: log file $FAIL_LOG is empty"
else
  pass "fail-root: log file exists and is non-empty"

  if grep -qF "worst-repos summary:" "$FAIL_LOG"; then
    pass "fail-root: log contains positive-control 'worst-repos summary:' line"
  else
    fail "fail-root: log missing positive-control 'worst-repos summary:' line"
  fi

  if grep -qF "unique-tail-repo-zzz" "$FAIL_LOG"; then
    pass "fail-root: log names the lowest-ranked affected repo (unique-tail-repo-zzz)"
  else
    fail "fail-root: log does not name unique-tail-repo-zzz - the scan is not covering the full rows list"
  fi

  if grep -qF 'had a `gh pr list` query failure' "$FAIL_LOG"; then
    pass "fail-root: log contains the backtick-quoted \`gh pr list\` precedent phrase"
  else
    fail "fail-root: log missing the backtick-quoted \`gh pr list\` precedent phrase"
  fi

  if grep -qF "Worktree counts above are exact" "$FAIL_LOG" \
      && grep -qF "FLOOR, not an exact figure" "$FAIL_LOG"; then
    pass "fail-root: log contains the FLOOR disclosure scoped to eligible only"
  else
    fail "fail-root: log missing the FLOOR disclosure (worktree-counts-exact + FLOOR phrase co-occurring)"
  fi
fi

# === Clean-root sub-case ===================================================
bash "$CLEAN_ROOT/run.sh" >/dev/null 2>&1
clean_rc=$?
if [[ "$clean_rc" -eq 0 ]]; then
  pass "clean-root run.sh exited 0"
else
  fail "clean-root run.sh exited $clean_rc (expected 0)"
fi

CLEAN_LOG="$(latest_log "$CLEAN_ROOT")"
if [[ -z "$CLEAN_LOG" || ! -f "$CLEAN_LOG" ]]; then
  fail "clean-root: no run-*.log found under $CLEAN_ROOT/logs"
elif [[ ! -s "$CLEAN_LOG" ]]; then
  fail "clean-root: log file $CLEAN_LOG is empty"
else
  pass "clean-root: log file exists and is non-empty"

  # Positive control FIRST - an absence assertion on a missing/empty file
  # would otherwise pass vacuously.
  if grep -qF "worst-repos summary:" "$CLEAN_LOG"; then
    pass "clean-root: log contains positive-control 'worst-repos summary:' line"

    if grep -qF 'had a `gh pr list` query failure' "$CLEAN_LOG"; then
      fail "clean-root: log unexpectedly contains the query-failure NOTE phrase"
    else
      pass "clean-root: log correctly omits the query-failure NOTE phrase"
    fi
  else
    fail "clean-root: log missing positive-control 'worst-repos summary:' line - cannot trust the absence check below"
  fi
fi

if [[ "$FAILURES" -gt 0 ]]; then
  echo "=== $FAILURES failure(s) ===" >&2
  exit 1
fi

echo "=== all checks passed ==="
exit 0
