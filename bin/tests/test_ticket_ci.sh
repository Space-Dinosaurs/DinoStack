#!/usr/bin/env bash
# Purpose: Regression spec for bin/ds-ticket-ci against a scripted fake gh,
#          run under /bin/bash, the PATH bash and zsh: no pass while a
#          required check (from rulesets, enforced branch protection or
#          --required) is absent, however many other checks are green; an
#          unreadable required set exits 4 before polling; a count change
#          resets the two-poll confirmation; a red check exits 1 naming it;
#          no checks at all pass only with no required checks; repeated
#          unreadable reads exit 4; the only fields requested are ones
#          `gh pr checks` accepts; the script never marks ready or merges.
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
# fail the way the real CLI does. Rules come from $FAKE/rules.json (none
# when absent) and branch protection from $FAKE/branch.json (unprotected
# when absent); $FAKE/rules.fail makes the rules read fail.
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
    [ -f "$FAKE/rules.fail" ] && { echo 'gh: HTTP 403' >&2; exit 1; }
    [ -f "$FAKE/rules.json" ] && { cat "$FAKE/rules.json"; exit 0; }
    echo '[]'; exit 0 ;;
  "api repos/o/r/branches/main")
    [ -f "$FAKE/branch.json" ] && { cat "$FAKE/branch.json"; exit 0; }
    echo '{"protected":false,"protection":{"enabled":false,"required_status_checks":{"enforcement_level":"off","contexts":[],"checks":[]}}}'; exit 0 ;;
esac
exit 1
EOF
chmod +x "$SCRATCH/stub-bin/gh"
export PATH="$SCRATCH/stub-bin:$PATH"

# checks <name>=<bucket>...: a check array.
checks() {
  local a out=""
  for a in "$@"; do
    out="$out${out:+,}{\"name\":\"${a%%=*}\",\"state\":\"X\",\"bucket\":\"${a#*=}\"}"
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

rules_ltb='[{"type":"required_status_checks","parameters":{"required_status_checks":[{"context":"lint"},{"context":"test"},{"context":"build"}]}},{"type":"deletion"}]'
branch_ltb='{"protected":true,"protection":{"enabled":true,"required_status_checks":{"enforcement_level":"non_admins","contexts":["lint","test"],"checks":[{"context":"build","app_id":null}]}}}'

run_suite() {
  SH_NAME="$1"
  SH="$2"
  echo ""
  echo "== $SH_NAME ($SH) =="

  scenario othernames "$(checks lint=pass docs=pass CodeQL=pass)"
  echo "$rules_ltb" > "$FAKE/rules.json"
  OUT="$("$SH" "$CLI" --pr 7 --gh-repo o/r --polls 5 --interval 0 2>&1)"
  [ $? -eq 2 ]
  assert $? "required [lint,test,build] vs green [lint,docs,CodeQL]: timeout (exit 2), never passed"
  echo "$OUT" | grep -q 'required not passing: build, test'
  assert $? "the timeout breadcrumb names the required checks not passing"

  scenario protected "$(checks lint=pass test=pass docs=pass)"
  echo "$branch_ltb" > "$FAKE/branch.json"
  "$SH" "$CLI" --pr 7 --gh-repo o/r --polls 4 --interval 0 >/dev/null 2>&1
  [ $? -eq 2 ]
  assert $? "an enforced branch-protection check (build) absent: never passed"

  scenario rulesfail "$(checks lint=pass)"
  touch "$FAKE/rules.fail"
  OUT="$("$SH" "$CLI" --pr 7 --gh-repo o/r --polls 5 --interval 0 2>&1)"
  [ $? -eq 4 ] && [ "$(polls_made)" -eq 0 ]
  assert $? "unreadable required set with one green check: exit 4 before polling"
  echo "$OUT" | grep -q 'result: unreadable'
  assert $? "unreadable breadcrumb"

  scenario override "$(checks lint=pass test=pass)"
  touch "$FAKE/rules.fail"
  "$SH" "$CLI" --pr 7 --gh-repo o/r --required lint,test,build --polls 4 --interval 0 >/dev/null 2>&1
  [ $? -eq 2 ]
  assert $? "--required names an absent check: never passed"

  scenario lazy "$(checks lint=pass test=pass)" "$(checks lint=pass test=pass build=pending)" \
    "$(checks lint=pass test=pass build=pass)" "$(checks lint=pass test=pass build=pass)"
  echo "$rules_ltb" > "$FAKE/rules.json"
  "$SH" "$CLI" --pr 7 --gh-repo o/r --polls 10 --interval 0 >/dev/null 2>&1
  [ $? -eq 0 ] && [ "$(polls_made)" -eq 4 ]
  assert $? "late-registering required check: passes on the second all-green poll with all required (poll 4)"
  ! grep -q '^pr ready' "$FAKE/calls"
  assert $? "a pass does not mark the PR ready (Phase 10b does, after its thread rule)"
  grep -q 'json name,state,bucket' "$FAKE/calls"
  assert $? "requests only name,state,bucket"

  scenario recount "$(checks a=pass b=skipping)" "$(checks a=pass b=skipping c=pass)" "$(checks a=pass b=skipping c=pass)"
  "$SH" "$CLI" --pr 7 --gh-repo o/r --polls 10 --interval 0 >/dev/null 2>&1
  [ $? -eq 0 ] && [ "$(polls_made)" -eq 3 ]
  assert $? "a count change between green polls restarts the confirmation (pass on poll 3)"

  scenario red "$(checks a=pass b=pending c=fail)" "$(checks a=pass b=cancel c=fail)"
  OUT="$("$SH" "$CLI" --pr 7 --gh-repo o/r --polls 10 --interval 0 2>&1)"
  [ $? -eq 1 ]
  assert $? "a red check exits 1"
  echo "$OUT" | grep -q 'result: failed | failing-checks: b, c'
  assert $? "the failed breadcrumb names every fail and cancel check"
  ! grep -q '^pr ready\|^pr merge' "$FAKE/calls"
  assert $? "a red check neither marks ready nor merges"

  scenario redtimeout "$(checks a=fail b=pending)"
  "$SH" "$CLI" --pr 7 --gh-repo o/r --polls 3 --interval 0 >/dev/null 2>&1
  [ $? -eq 1 ]
  assert $? "a failure still pending others at the poll budget exits 1, not 2"

  scenario nochecks NOCHECKS
  OUT="$("$SH" "$CLI" --pr 7 --gh-repo o/r --polls 10 --interval 0 2>&1)"
  [ $? -eq 0 ] && [ "$(polls_made)" -eq 4 ]
  assert $? "no checks registered and none required: passed-by-default after 4 polls"
  echo "$OUT" | grep -q 'result: passed-by-default | no-checks'
  assert $? "passed-by-default breadcrumb"

  scenario nochecksrequired NOCHECKS
  echo "$rules_ltb" > "$FAKE/rules.json"
  "$SH" "$CLI" --pr 7 --gh-repo o/r --polls 6 --interval 0 >/dev/null 2>&1
  [ $? -eq 2 ]
  assert $? "no checks registered with required checks: timeout"

  scenario unreadable 'gh: HTTP 502'
  OUT="$("$SH" "$CLI" --pr 7 --gh-repo o/r --polls 20 --interval 0 2>&1)"
  [ $? -eq 4 ] && [ "$(polls_made)" -eq 5 ]
  assert $? "five consecutive unreadable reads exit 4"
  echo "$OUT" | grep -q 'read-error 1/5'
  assert $? "an unreadable read is reported, not counted as pending"

  scenario usage "$(checks a=pass)"
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
