#!/usr/bin/env bash
# Purpose: Pin bin/ds-ticket-setup's mode dispatch, procedure injection,
#          BASE_BRANCH order, resume verdicts and read-only contract. The
#          loop-key and rework blocks it carries are pinned by
#          test_loop_key_derivation.sh and test_ticket_rework_ledger.sh.
#          Injection is the point of the script: in 26 eval control runs the
#          conductor Read a pointed-to reference 0 times, so batch, open_goal
#          and resume must print their procedure body.
#
# Public API: bash bin/tests/test_ds_ticket_setup.sh (exit 0 all pass, 1 any fail).
#             Discovered by the bin-sh-tests glob.
#
# Upstream deps: bash 3.2+, git, python3. All state lives in a mktemp dir.
#
# Failure modes: none beyond a failing assertion; no network.
#
# Performance: < 10 s (about 20 script runs).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$REPO_DIR/bin/ds-ticket-setup"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
_eq() { # _eq <label> <actual> <expected>
  if [ "$2" = "$3" ]; then _pass "$1 = '$2'"; else _fail "$1: got '$2' want '$3'"; fi
}

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

# _field <dir> <python expr over d> <args...> -> expr evaluated on line 1's JSON
_field() {
  local dir="$1" expr="$2"
  shift 2
  (cd "$dir" && "$SCRIPT" --repo "$dir" --session-id sid "$@" 2>/dev/null) | head -1 \
    | python3 -c 'import json, sys; d = json.load(sys.stdin); print(eval(sys.argv[1]))' "$expr"
}

PLAIN="$TMP_ROOT/plain"
mkdir -p "$PLAIN"

echo "--- JSON shape, outside any git repo, no tracker ---"
_eq "exactly the seven keys" "$(_field "$PLAIN" '",".join(sorted(d))' DS-1)" \
  "base_branch,loop_key,mode,repo_dir,resume,rework,tracker"
_eq "base_branch defaults to main" "$(_field "$PLAIN" 'd["base_branch"]' DS-1)" "main"
_eq "no tracker config resolves TRACKER=none" "$(_field "$PLAIN" 'd["tracker"]["TRACKER"]' DS-1)" "none"

echo "--- mode dispatch ---"
_eq "one bare id is single"        "$(_field "$PLAIN" 'd["mode"]' DS-1)" "single"
_eq "freeform text is single"      "$(_field "$PLAIN" 'd["mode"]' fix the login page)" "single"
_eq "two ids are batch"            "$(_field "$PLAIN" 'd["mode"]' 'DS-1, DS-2')" "batch"
_eq "two issue URLs are batch"     "$(_field "$PLAIN" 'd["mode"]' https://x.atlassian.net/browse/DS-1 https://linear.app/w/issue/ENG-4/t)" "batch"
_eq "a repeated id is still single" "$(_field "$PLAIN" 'd["mode"]' DS-1 DS-1)" "single"
_eq "goal_mode=open_goal wins over ids" "$(_field "$PLAIN" 'd["mode"]' DS-1 DS-2 goal_mode=open_goal max_iterations=3)" "open_goal"
_eq "an issue URL keys the loop on its id" "$(_field "$PLAIN" 'd["loop_key"]' https://linear.app/w/issue/ENG-4/title)" "ENG-4"

echo "--- procedure injection ---"
_inject_check() { # _inject_check <dir> <label> <ref> <args...>
  local dir="$1" label="$2" ref="$3" out first_heading close_line body_first
  shift 3
  out="$( (cd "$dir" && "$SCRIPT" --repo "$dir" --session-id sid "$@" 2>/dev/null) )"
  first_heading="$(grep -m1 '^## ' "$REPO_DIR/content/references/$ref")"
  if printf '%s\n' "$out" | grep -qF -- "--- procedure: content/references/$ref"; then
    _pass "$label prints the $ref procedure line"
  else
    _fail "$label does not print the $ref procedure line"
  fi
  if printf '%s\n' "$out" | grep -qxF -- "$first_heading"; then
    _pass "$label carries $ref's body ($first_heading)"
  else
    _fail "$label lacks $ref's body ($first_heading)"
  fi
  # The manifest ends at the first line that is exactly "-->"; a nested
  # "<!-- ... -->" inside it must not end the skip early.
  close_line="$(grep -n -m1 -x -- '-->' "$REPO_DIR/content/references/$ref" | cut -d: -f1)"
  body_first="$(sed -n "$((close_line + 1)),\$p" "$REPO_DIR/content/references/$ref" | grep -m1 -v '^[[:space:]]*$')"
  if [ "$(printf '%s\n' "$out" | sed -n '/^--- procedure:/,$p' | sed -n '2,$p' | grep -m1 -v '^[[:space:]]*$')" = "$body_first" ]; then
    _pass "$label skips $ref's manifest comment (body starts at: $body_first)"
  else
    _fail "$label printed part of $ref's manifest comment before: $body_first"
  fi
}
_inject_check "$PLAIN" "batch" batch-mode.md DS-1 DS-2
_inject_check "$PLAIN" "open_goal" open-goal-loop.md goal_mode=open_goal
if (cd "$PLAIN" && "$SCRIPT" --repo "$PLAIN" --session-id sid DS-1 2>/dev/null) | grep -q -- '--- procedure:'; then
  _fail "single mode injected a procedure"
else
  _pass "single mode injects nothing"
fi

echo "--- resume verdicts (read-only) ---"
RES="$TMP_ROOT/res"
mkdir -p "$RES/.agentic"
NOW="$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))')"
printf '{"status":"interrupted","last_phase":"skeptic"}' > "$RES/.agentic/loop-state-DS-1.json"
printf '{"status":"active","last_updated":"2020-01-01T00:00:00.000Z"}' > "$RES/.agentic/loop-state-DS-2.json"
printf '{"status":"active","last_updated":"%s"}' "$NOW" > "$RES/.agentic/loop-state-DS-3.json"
printf '{"status":"complete"}' > "$RES/.agentic/loop-state-DS-4.json"
printf '{not json' > "$RES/.agentic/loop-state-DS-5.json"
_eq "interrupted is resumable"      "$(_field "$RES" 'd["resume"]["keyed"]["verdict"]' DS-1)" "resumable"
_eq "stale active is resumable"     "$(_field "$RES" 'd["resume"]["keyed"]["verdict"]' DS-2)" "resumable"
_eq "fresh active is live"          "$(_field "$RES" 'd["resume"]["keyed"]["verdict"]' DS-3)" "live"
_eq "complete is clear"             "$(_field "$RES" 'd["resume"]["keyed"]["verdict"]' DS-4)" "clear"
_eq "unparseable is parse_error"    "$(_field "$RES" 'd["resume"]["keyed"]["verdict"]' DS-5)" "parse_error"
_eq "resumable keyed file sets mode resume" "$(_field "$RES" 'd["mode"]' DS-1)" "resume"
_eq "live keyed file does not"      "$(_field "$RES" 'd["mode"]' DS-3)" "single"
_eq "another ticket's file is never recommended" "$(_field "$RES" 'd["resume"]["recommended"]' DS-9)" "None"
_inject_check "$RES" "resume" cross-session-loop-resume.md DS-1

SES="$TMP_ROOT/ses"
mkdir -p "$SES/.agentic"
printf '{"status":"interrupted","loop_key":"session-old"}' > "$SES/.agentic/loop-state-session-old.json"
_eq "null ticket, one session candidate: recommended" \
  "$(_field "$SES" 'd["resume"]["recommended"]' 'just some freeform text')" ".agentic/loop-state-session-old.json"
_eq "a named ticket never adopts a session candidate" \
  "$(_field "$SES" 'd["resume"]["recommended"]' DS-9)" "None"
printf '{"status":"interrupted","loop_key":"session-old2"}' > "$SES/.agentic/loop-state-session-old2.json"
_eq "null ticket, two session candidates: none" \
  "$(_field "$SES" 'd["resume"]["recommended"]' 'just some freeform text')" "None"

BEFORE="$(cd "$RES" && find . -type f | LC_ALL=C sort | xargs cat | cksum)"
(cd "$RES" && "$SCRIPT" --repo "$RES" --session-id sid DS-4 >/dev/null 2>&1)
AFTER="$(cd "$RES" && find . -type f | LC_ALL=C sort | xargs cat | cksum)"
_eq "a run writes and deletes nothing" "$AFTER" "$BEFORE"

echo "--- BASE_BRANCH order ---"
G="$TMP_ROOT/git"
mkdir -p "$G"
git -C "$G" init -q -b trunk
git -C "$G" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
_eq "no candidate falls back to main" "$(_field "$G" 'd["base_branch"]' DS-1)" "main"
git -C "$G" branch master
_eq "main absent, master present: master" "$(_field "$G" 'd["base_branch"]' DS-1)" "master"
git -C "$G" branch development
_eq "local development beats main/master" "$(_field "$G" 'd["base_branch"]' DS-1)" "development"
git -C "$G" branch develop
_eq "local develop beats development" "$(_field "$G" 'd["base_branch"]' DS-1)" "develop"
git -C "$G" update-ref refs/remotes/origin/trunk HEAD
git -C "$G" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/trunk
_eq "origin/HEAD beats local develop" "$(_field "$G" 'd["base_branch"]' DS-1)" "trunk"
printf '# x\n\nDeclaration: `BASE_BRANCH: release`.\n' > "$G/AGENTS.md"
_eq "AGENTS.md declaration wins" "$(_field "$G" 'd["base_branch"]' DS-1)" "release"

echo
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -gt 0 ] && exit 1
exit 0
