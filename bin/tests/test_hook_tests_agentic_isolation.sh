#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Purpose: Fail when running the Python hook test suites writes into the
#          `.agentic/` of the checkout they run from, or of that checkout's
#          primary. A hook whose payload carries no `cwd` falls back to its
#          process cwd, and log_fire resolves a linked worktree to the
#          primary root, so a hook test that inherits the caller's cwd
#          appends fixture rows to the operator's real fire log. That is
#          how ~20k session-less enforce-turn-shape deny rows reached one.
#
#          The suites are run from a copy of the working tree placed in a
#          linked worktree of a scratch repo whose primary `.agentic/` is seeded
#          with a fire log and an events log. Both must stay byte-identical
#          and no other `.agentic/` entry may appear in either scratch
#          tree. A positive control then makes one cwd-less log_fire call
#          from the same worktree and requires the scratch primary's fire
#          log to grow, so a green run cannot mean "the detector saw
#          nothing because nothing could reach it".
#
#          Scope: every file list_hooks_py_tests returns except
#          test-hooks-pep604-guard.py, which re-executes all the others
#          (it would double the run and assert nothing new). The JS and sh
#          hook suites are not run here: log_fire is Python-only, and the
#          JS set costs about three minutes.
#
# Public API: bash bin/tests/test_hook_tests_agentic_isolation.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, git, python3, tar, cmp, find, mktemp;
#                scripts/lib/ci-test-discovery.sh; a git working tree.
#
# Downstream consumers: CI (the bin-sh-tests job auto-discovers
#                       bin/tests/test_*.sh), and scripts/check-local.sh.
#
# Failure modes: names the hook test file after which the scratch
#                `.agentic/` first differed. A hook test that exits nonzero
#                inside the scratch tree is itself a failure: a suite that
#                died early proves nothing about what it would have written.
#                Never reads or writes the real checkout's `.agentic/`.
#
# Retirement: when hook tests can no longer reach a checkout's `.agentic/`
#             by construction (for example every hook test running through
#             one shared runner that owns the subprocess cwd).
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PASS=0
FAIL=0
_pass() { PASS=$((PASS + 1)); echo "PASS: $1"; }
_fail() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

# shellcheck source=scripts/lib/ci-test-discovery.sh
. "$REPO_ROOT/scripts/lib/ci-test-discovery.sh"

TMPROOT="$(mktemp -d -t hook-tests-agentic-isolation.XXXXXX)"
cleanup() { rm -rf "$TMPROOT"; }
trap cleanup EXIT

PRIMARY="$TMPROOT/primary"
LINKED="$TMPROOT/linked"

git init -q "$PRIMARY"
git -C "$PRIMARY" -c user.email="test@example.com" -c user.name="test" \
  -c commit.gpgsign=false commit -q --no-verify --allow-empty -m base
git -C "$PRIMARY" worktree add -q "$LINKED" -b linked
# The whole working tree, not just hooks/: some hook tests read docs/ and
# content/. Untracked files are included so a not-yet-staged hook test is
# covered too.
( cd "$REPO_ROOT" && git ls-files -z --cached --others --exclude-standard \
    | tar -cf - --null -T - 2>/dev/null ) | ( cd "$LINKED" && tar -xf - )

if [ ! -f "$LINKED/.git" ] || [ ! -d "$LINKED/hooks/tests" ]; then
  echo "FAIL: could not build the scratch linked worktree under $TMPROOT"
  exit 1
fi

mkdir -p "$PRIMARY/.agentic"
printf '%s\n' '{"ts":"2000-01-01T00:00:00.000Z","hook":"seed","decision":"deny","reason":"seed"}' \
  > "$PRIMARY/.agentic/.enforcement-fires.jsonl"
printf '%s\n' '{"ts":"2000-01-01T00:00:00.000Z","type":"seed"}' > "$PRIMARY/.agentic/events.jsonl"
cp "$PRIMARY/.agentic/.enforcement-fires.jsonl" "$TMPROOT/fires.seed"
cp "$PRIMARY/.agentic/events.jsonl" "$TMPROOT/events.seed"

_listing() {
  find "$PRIMARY/.agentic" "$LINKED/.agentic" 2>/dev/null | LC_ALL=C sort
}
_untouched() {
  cmp -s "$PRIMARY/.agentic/.enforcement-fires.jsonl" "$TMPROOT/fires.seed" \
    && cmp -s "$PRIMARY/.agentic/events.jsonl" "$TMPROOT/events.seed" \
    && [ "$(_listing)" = "$SEED_LISTING" ]
}
SEED_LISTING="$(_listing)"

if ! listing="$(list_hooks_py_tests "$LINKED")"; then
  echo "FAIL: hook python test discovery failed in the scratch worktree"
  exit 1
fi

ran=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  [ "$f" = "hooks/tests/test-hooks-pep604-guard.py" ] && continue
  ran=$((ran + 1))
  ( cd "$LINKED" && python3 "$f" ) > "$TMPROOT/run.log" 2>&1 < /dev/null
  rc=$?
  if [ "$rc" -ne 0 ]; then
    _fail "$f exited $rc in the scratch worktree, so its writes were not fully exercised:
$(tail -n 15 "$TMPROOT/run.log")"
  fi
  if _untouched; then
    _pass "$f left the scratch .agentic/ untouched"
  else
    _fail "$f changed the scratch .agentic/ (it would write to a real checkout's); seeded with one line each:
$(wc -l "$PRIMARY/.agentic/.enforcement-fires.jsonl" "$PRIMARY/.agentic/events.jsonl" 2>&1)
$(_listing)"
    cp "$TMPROOT/fires.seed" "$PRIMARY/.agentic/.enforcement-fires.jsonl"
    cp "$TMPROOT/events.seed" "$PRIMARY/.agentic/events.jsonl"
    SEED_LISTING="$(_listing)"
  fi
done <<EOF
$listing
EOF

if [ "$ran" -eq 0 ]; then
  _fail "no hook python test was run"
fi

( cd "$LINKED" && python3 -c '
import sys
sys.path.insert(0, "hooks/lib")
import enforcement_log
enforcement_log.log_fire({}, "isolation-control", "deny", "positive control")
' ) > "$TMPROOT/control.log" 2>&1
if cmp -s "$PRIMARY/.agentic/.enforcement-fires.jsonl" "$TMPROOT/fires.seed"; then
  _fail "positive control: a cwd-less log_fire from the linked worktree did not reach the scratch primary's fire log, so the checks above could not have detected a leak:
$(cat "$TMPROOT/control.log")"
else
  _pass "positive control: a cwd-less log_fire from the linked worktree lands in the scratch primary's fire log"
fi

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
