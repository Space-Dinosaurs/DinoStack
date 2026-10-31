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
_eq "exactly the eight keys" "$(_field "$PLAIN" '",".join(sorted(d))' DS-1)" \
  "base_branch,loop_key,mode,repo_dir,resume,rework,ticket_id,tracker"
_eq "a parsed id is ticket_id" "$(_field "$PLAIN" 'd["ticket_id"]' https://x.atlassian.net/browse/DS-7)" "DS-7"
_eq "no parseable id gives ticket_id null" "$(_field "$PLAIN" 'd["ticket_id"]' see the attached screenshot)" "None"
_eq "a lowercase id is not parsed (Phase 0 resolves it)" "$(_field "$PLAIN" 'd["ticket_id"]' aut-12)" "None"
_eq "base_branch defaults to main" "$(_field "$PLAIN" 'd["base_branch"]' DS-1)" "main"
_eq "no tracker config resolves TRACKER=none" "$(_field "$PLAIN" 'd["tracker"]["TRACKER"]' DS-1)" "none"

echo "--- mode dispatch ---"
_eq "one bare id is single"        "$(_field "$PLAIN" 'd["mode"]' DS-1)" "single"
_eq "freeform text is single"      "$(_field "$PLAIN" 'd["mode"]' fix the login page)" "single"
_eq "two ids are batch"            "$(_field "$PLAIN" 'd["mode"]' 'DS-1, DS-2')" "batch"
_eq "a batch has no ticket_id"     "$(_field "$PLAIN" 'd["ticket_id"]' 'DS-1, DS-2')" "None"
_eq "two issue URLs are batch"     "$(_field "$PLAIN" 'd["mode"]' https://x.atlassian.net/browse/DS-1 https://linear.app/w/issue/ENG-4/t)" "batch"
_eq "a repeated id is still single" "$(_field "$PLAIN" 'd["mode"]' DS-1 DS-1)" "single"
_eq "--ticket forces single over a batch input" "$(_field "$PLAIN" 'd["mode"]' --ticket DS-3 -- DS-1 DS-2)" "single"
_eq "--ticket sets ticket_id" "$(_field "$PLAIN" 'd["ticket_id"]' --ticket DS-3 -- DS-1 DS-2)" "DS-3"
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

# Candidate check table, null-ticket rows: the session's own keyed file is
# the exact-match row only when it is resumable; present but not resumable,
# a single other resumable session-* file is still recommended.
SES2="$TMP_ROOT/ses2"
mkdir -p "$SES2/.agentic"
printf '{"status":"complete"}' > "$SES2/.agentic/loop-state-session-sid.json"
printf '{"status":"interrupted","loop_key":"session-old"}' > "$SES2/.agentic/loop-state-session-old.json"
_eq "keyed session file not resumable, one other session candidate: recommended" \
  "$(_field "$SES2" 'd["resume"]["recommended"]' 'just some freeform text')" ".agentic/loop-state-session-old.json"

LEG="$TMP_ROOT/legacy"
mkdir -p "$LEG/.agentic"
printf '{"status":"interrupted","ticket_id":"DS-1"}' > "$LEG/.agentic/loop-state.json"
_eq "no keyed file, resumable legacy file: recommended" \
  "$(_field "$LEG" 'd["resume"]["recommended"]' DS-1)" ".agentic/loop-state.json"
_eq "resumable legacy file sets mode resume" "$(_field "$LEG" 'd["mode"]' DS-1)" "resume"
printf '{"status":"interrupted"}' > "$LEG/.agentic/loop-state-DS-1.json"
_eq "keyed file beats a resumable legacy file" \
  "$(_field "$LEG" 'd["resume"]["recommended"]' DS-1)" ".agentic/loop-state-DS-1.json"
printf '{"status":"complete"}' > "$LEG/.agentic/loop-state-DS-1.json"
_eq "a keyed file that is not resumable still blocks legacy adoption" \
  "$(_field "$LEG" 'd["resume"]["recommended"]' DS-1)" "None"

BRES="$TMP_ROOT/batch-resume"
mkdir -p "$BRES/.agentic"
printf '{"status":"interrupted"}' > "$BRES/.agentic/loop-state-session-sid.json"
_eq "a batch with a recommended file is still batch" \
  "$(_field "$BRES" 'd["mode"] + " " + str(d["resume"]["recommended"])' DS-1 DS-2)" "batch .agentic/loop-state-session-sid.json"

echo "--- oversized input is classified, never silently single ---"
BIG="$TMP_ROOT/big.txt"
python3 -c 'import sys; sys.stdout.write("x " * 1300000 + "DS-1 DS-2\n")' > "$BIG"
_eq "a 2.6 MB input still classifies as batch" \
  "$( (cd "$PLAIN" && "$SCRIPT" --repo "$PLAIN" --session-id sid --stdin < "$BIG" 2>/dev/null) \
      | head -1 | python3 -c 'import json, sys; print(json.load(sys.stdin)["mode"])')" "batch"

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
printf '# x\n\nBASE_BRANCH: trunk2 - the branch every PR targets\n' > "$G/AGENTS.md"
_eq "a declaration with trailing prose takes its first token" "$(_field "$G" 'd["base_branch"]' DS-1)" "trunk2"
printf '# x\n\n```\nBASE_BRANCH: fenced\n```\n' > "$G/AGENTS.md"
_eq "a fenced example is not a declaration" "$(_field "$G" 'd["base_branch"]' DS-1)" "trunk"

echo "--- operator text reaches the script verbatim and unexpanded ---"
HOSTILE_DIR="$TMP_ROOT/hostile"
mkdir -p "$HOSTILE_DIR/.agentic"
printf '%s\n' '{"ticket_id":"aut-12","pr_number":7,"opened_ts":"2026-01-01T00:00:00Z"}' \
  > "$HOSTILE_DIR/.agentic/ticket-ledger.jsonl"
_eq "--rework-only --ticket - reads a Phase-0-only id from stdin and returns its rework" \
  "$(cd "$HOSTILE_DIR" && printf 'aut-12\n' | "$SCRIPT" --repo "$HOSTILE_DIR" --session-id sid --rework-only --ticket - 2>/dev/null \
     | head -1 | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d["ticket_id"], d["rework"]["prior_attempts"])')" \
  "aut-12 1"

echo "--- the rework re-run can never re-key the ticket ---"
printf '{"status":"interrupted"}' > "$HOSTILE_DIR/.agentic/loop-state-aut-12.json"
RO_OUT="$(cd "$HOSTILE_DIR" && "$SCRIPT" --repo "$HOSTILE_DIR" --session-id sid --rework-only --ticket aut-12 2>/dev/null)"
_eq "rework-only output carries only ticket_id and rework" \
  "$(printf '%s\n' "$RO_OUT" | head -1 | python3 -c 'import json, sys; print(",".join(sorted(json.load(sys.stdin))))')" "rework,ticket_id"
_eq "rework-only injects no procedure even with a resumable keyed file" \
  "$(printf '%s\n' "$RO_OUT" | grep -c -- '--- procedure:')" "0"
rm -f "$HOSTILE_DIR/.agentic/loop-state-aut-12.json"
(cd "$HOSTILE_DIR" && "$SCRIPT" --repo "$HOSTILE_DIR" --rework-only -- aut-12 >/dev/null 2>&1)
_eq "--rework-only without --ticket is a usage error" "$?" "2"

# Run the command's own Setup-call and re-run fences, with hostile text in
# place of the placeholder. Each payload would create a marker file if any
# shell expanded it.
FAKE_HOME="$TMP_ROOT/home"
mkdir -p "$FAKE_HOME/.agentic"
printf '{"repo_dir": "%s"}\n' "$REPO_DIR" > "$FAKE_HOME/.agentic/agentic-engineering-config.json"
SPEC="$REPO_DIR/content/commands/ds-implement-ticket.md"
_fence() { # _fence <marker> <placeholder> <replacement-file> <out>
  python3 - "$SPEC" "$1" "$2" "$3" "$4" <<'PY'
import sys
spec, marker, placeholder, repl, out = sys.argv[1:]
text = open(spec).read()
i = text.index(marker)
block = text[i:text.index("\n```", i)] + "\n"
lines = block.split("\n")
assert lines.count(placeholder) == 1, "placeholder line not found: " + placeholder
lines[lines.index(placeholder)] = open(repl).read().rstrip("\n")
open(out, "w").write("\n".join(lines))
PY
}
M="$HOSTILE_DIR/pwned"
printf '%s\n' "DS-9 \`touch $M-tick\` \$(touch $M-sub) \$HOME \"quoted\" goal_mode=x" > "$TMP_ROOT/input.txt"
printf '%s\n' "ab\`touch $M-tick2\`\$(touch $M-sub2)\$HOME\"q\"" > "$TMP_ROOT/ticket.txt"
if _fence '# Setup call: ds-ticket-setup' '<input>' "$TMP_ROOT/input.txt" "$TMP_ROOT/setup.sh" \
   && _fence '# Setup call: rework re-run' '<ticket id>' "$TMP_ROOT/ticket.txt" "$TMP_ROOT/rerun.sh"; then
  _pass "extracted both Setup-call fences from the command"
  OUT1="$(cd "$HOSTILE_DIR" && HOME="$FAKE_HOME" CLAUDE_CODE_SESSION_ID=sid bash "$TMP_ROOT/setup.sh" 2>/dev/null | head -1)"
  OUT2="$(cd "$HOSTILE_DIR" && env -u REPO_DIR HOME="$FAKE_HOME" CLAUDE_CODE_SESSION_ID=sid bash "$TMP_ROOT/rerun.sh" 2>/dev/null | head -1)"
  _eq "Setup fence: the id inside hostile text is parsed" \
    "$(printf '%s' "$OUT1" | python3 -c 'import json, sys; print(json.load(sys.stdin)["ticket_id"])')" "DS-9"
  _eq "re-run fence is rework-only (no loop_key, no resume)" \
    "$(printf '%s' "$OUT2" | python3 -c 'import json, sys; print(",".join(sorted(json.load(sys.stdin))))')" "rework,ticket_id"
  _eq "re-run fence: the id arrives verbatim" \
    "$(printf '%s' "$OUT2" | python3 -c 'import json, sys; print(json.load(sys.stdin)["ticket_id"])')" \
    "$(cat "$TMP_ROOT/ticket.txt")"
  if ls "$HOSTILE_DIR" | grep -q pwned; then
    _fail "a backtick or \$(...) payload executed: $(ls "$HOSTILE_DIR" | grep pwned | tr '\n' ' ')"
  else
    _pass "no backtick or \$(...) payload executed"
  fi
else
  _fail "could not extract the Setup-call fences from the command"
fi

echo
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -gt 0 ] && exit 1
exit 0
