#!/usr/bin/env bash
# Purpose: Regression spec for bin/ds-ticket-ci against a scripted fake gh,
#          run under /bin/bash, the PATH bash and zsh: a partial suite below
#          the required-check floor never passes, a count change resets the
#          two-poll confirmation, a red check exits 1 naming it, no checks at
#          all pass only with a zero floor, repeated unreadable reads exit 4,
#          the only fields requested are ones `gh pr checks` accepts, and
#          the script never marks ready or merges.
#
# Public API: none (standalone script; `bash bin/tests/test_ticket_ci.sh`).
#
# Upstream deps: bin/ds-ticket-ci (under test), jq, zsh (hard-required under
#                ${CI}, skipped with a notice locally when absent).
#
# Downstream consumers: CI (bin-sh-tests, auto-collected per
#                       .github/workflows/bin-tests.yml's shell-test glob).
#
# Failure modes: exits 1 when any assertion fails. All state lives under a
#                mktemp directory removed on exit.
#
# Performance: under a second per shell (--interval 0).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLI="$REPO_ROOT/bin/ds-ticket-ci"
SCRATCH="$(mktemp -d)"
trap 'find "$SCRATCH" -depth -delete 2>/dev/null' EXIT

fail_count=0
assert() {
  if [ "$1" -eq 0 ]; then
    echo "  PASS: $2"
  else
    echo "  FAIL: $2"
    fail_count=$((fail_count + 1))
  fi
}

mkdir -p "$SCRATCH/stub-bin"
# Fake gh. `pr checks` answers from $FAKE/poll.<n> (the last file repeats):
# a JSON array, NOCHECKS (what gh prints for a PR with no checks), or
# anything else verbatim as unparseable output. Field names gh rejects
# fail the way the real CLI does.
cat > "$SCRATCH/stub-bin/gh" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$FAKE/calls"
case "$1 $2" in
  "pr view") echo main; exit 0 ;;
  "pr ready") exit 0 ;;
  "pr checks")
    case "$*" in *status*|*conclusion*) echo 'Unknown JSON field: "status"' >&2; exit 1 ;; esac
    n=$(cat "$FAKE/n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$FAKE/n"
    f="$FAKE/poll.$n"
    [ -f "$f" ] || f=$(ls "$FAKE"/poll.* | sort -t. -k2 -n | tail -1)
    if [ "$(cat "$f")" = NOCHECKS ]; then
      echo "no checks reported on the 'feature/x' branch" >&2; exit 1
    fi
    cat "$f"; exit 8 ;;
  "api --paginate")
    [ "$3" = repos/o/r/rules/branches/main ] || exit 1
    [ -f "$FAKE/rules.json" ] && { cat "$FAKE/rules.json"; exit 0; }
    echo '{"message":"Not Found"}'; exit 1 ;;
  "api repos/o/r/branches/main/protection/required_status_checks")
    echo '{"message":"Branch not protected"}'; exit 1 ;;
esac
exit 1
EOF
chmod +x "$SCRATCH/stub-bin/gh"
export PATH="$SCRATCH/stub-bin:$PATH"

# checks <bucket>...: a check array with one entry per bucket.
checks() {
  local i=0 b out=""
  for b in "$@"; do
    i=$((i + 1))
    out="$out${out:+,}{\"name\":\"c$i\",\"state\":\"X\",\"bucket\":\"$b\"}"
  done
  printf '[%s]\n' "$out"
}

# scenario <name> <poll-file-content>...: a fresh fake state.
scenario() {
  FAKE="$SCRATCH/$SH_NAME-$1"
  export FAKE
  mkdir -p "$FAKE"
  shift
  local i=0 c
  for c in "$@"; do
    i=$((i + 1))
    printf '%s\n' "$c" > "$FAKE/poll.$i"
  done
}

polls_made() { grep -c '^pr checks' "$FAKE/calls"; }

required3='[{"type":"required_status_checks","parameters":{"required_status_checks":[{"context":"c1"},{"context":"c2"},{"context":"c3"}]}},{"type":"deletion"}]'

run_suite() {
  SH_NAME="$1"
  SH="$2"
  echo ""
  echo "== $SH_NAME ($SH) =="

  scenario partial "$(checks pass pass)"
  echo "$required3" > "$FAKE/rules.json"
  OUT="$("$SH" "$CLI" --pr 7 --gh-repo o/r --polls 4 --interval 0 2>&1)"
  [ $? -eq 2 ]
  assert $? "2 green checks against 3 required: timeout (exit 2), never passed"
  echo "$OUT" | grep -q 'floor: 3 | required: rules=3'
  assert $? "the floor is the base branch's required-check count"
  ! grep -q '^pr ready' "$FAKE/calls"
  assert $? "no ready call"

  scenario lazy "$(checks pass pass)" "$(checks pass pass pending)" "$(checks pass pass pass)" "$(checks pass pass pass)"
  echo "$required3" > "$FAKE/rules.json"
  "$SH" "$CLI" --pr 7 --gh-repo o/r --polls 10 --interval 0 >/dev/null 2>&1
  [ $? -eq 0 ] && [ "$(polls_made)" -eq 4 ]
  assert $? "late-registering checks: passes on the second all-green poll at the floor (poll 4)"
  ! grep -q '^pr ready' "$FAKE/calls"
  assert $? "a pass does not mark the PR ready (Phase 10b does, after its thread rule)"
  grep -q 'json name,state,bucket' "$FAKE/calls"
  assert $? "requests only name,state,bucket"

  scenario recount "$(checks pass skipping)" "$(checks pass skipping pass)" "$(checks pass skipping pass)"
  "$SH" "$CLI" --pr 7 --gh-repo o/r --polls 10 --interval 0 >/dev/null 2>&1
  [ $? -eq 0 ] && [ "$(polls_made)" -eq 3 ]
  assert $? "a count change between green polls restarts the confirmation (pass on poll 3)"

  scenario red "$(checks pass pending fail)" "$(checks pass cancel fail)"
  OUT="$("$SH" "$CLI" --pr 7 --gh-repo o/r --polls 10 --interval 0 2>&1)"
  [ $? -eq 1 ]
  assert $? "a red check exits 1"
  echo "$OUT" | grep -q 'result: failed | failing-checks: c2, c3'
  assert $? "the failed breadcrumb names every fail and cancel check"
  ! grep -q '^pr ready\|^pr merge' "$FAKE/calls"
  assert $? "a red check neither marks ready nor merges"

  scenario redtimeout "$(checks fail pending)"
  "$SH" "$CLI" --pr 7 --gh-repo o/r --polls 3 --interval 0 >/dev/null 2>&1
  [ $? -eq 1 ]
  assert $? "a failure still pending others at the poll budget exits 1, not 2"

  scenario nochecks NOCHECKS
  OUT="$("$SH" "$CLI" --pr 7 --gh-repo o/r --polls 10 --interval 0 2>&1)"
  [ $? -eq 0 ] && [ "$(polls_made)" -eq 4 ]
  assert $? "no checks registered and a zero floor: passed-by-default after 4 polls"
  echo "$OUT" | grep -q 'result: passed-by-default | no-checks'
  assert $? "passed-by-default breadcrumb"

  scenario nochecksfloor NOCHECKS
  "$SH" "$CLI" --pr 7 --gh-repo o/r --polls 6 --interval 0 --min-checks 1 >/dev/null 2>&1
  [ $? -eq 2 ]
  assert $? "no checks registered and a nonzero floor: timeout"

  scenario unreadable 'gh: HTTP 502'
  OUT="$("$SH" "$CLI" --pr 7 --gh-repo o/r --polls 20 --interval 0 2>&1)"
  [ $? -eq 4 ] && [ "$(polls_made)" -eq 5 ]
  assert $? "five consecutive unreadable reads exit 4"
  echo "$OUT" | grep -q 'read-error 1/5'
  assert $? "an unreadable read is reported, not counted as pending"

  scenario usage "$(checks pass)"
  "$SH" "$CLI" --gh-repo o/r >/dev/null 2>&1
  [ $? -eq 3 ]
  assert $? "missing --pr exits 3"
  "$SH" "$CLI" --pr 7 --gh-repo o/r --polls x >/dev/null 2>&1
  [ $? -eq 3 ]
  assert $? "a non-numeric --polls exits 3"
}

run_suite bash3 /bin/bash
run_suite bash "$(command -v bash)"
if command -v zsh >/dev/null 2>&1; then
  run_suite zsh "$(command -v zsh)"
elif [ -n "${CI:-}" ]; then
  echo "  FAIL: zsh not installed under CI"
  fail_count=$((fail_count + 1))
else
  echo "NOTICE: zsh not installed; zsh suite skipped"
fi

grep -q 'pr merge\|pr ready\|git push' "$CLI"
[ $? -ne 0 ]
assert $? "ds-ticket-ci has no merge, ready or push call"

echo ""
if [ "$fail_count" -eq 0 ]; then
  echo "ALL PASS"
  exit 0
fi
echo "$fail_count FAILED"
exit 1
