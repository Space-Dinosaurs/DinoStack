#!/usr/bin/env bash
# Purpose: Regression suite for bin/ds-lane. Drives the real tool against a
#          scratch git repo (path contains a space) with a stub `claude`
#          (a bash script, so `ps` shows `/bin/bash <stub path> -p ...`, the
#          recorded path the tool's liveness check requires) and a stub
#          `osascript` whose reply is chosen by STUB_OSA_MODE. Never launches
#          a real claude session and never runs AppleScript against Terminal
#          (osacompile reads Terminal's static sdef without launching it).
#
# Public API: bash bin/tests/test_ds_lane.sh   (exit 0 all pass, 1 any fail)
#
# Upstream deps: bash, python3, git, jq, ps, pkill, script(1) for a pty
#                (BSD or util-linux form); zsh for the tab-command parity
#                case. jq or zsh missing: hard FAIL under ${CI}, SKIP locally.
#
# Downstream consumers: CI bin-sh-tests job (.github/workflows/bin-tests.yml
#                        auto-discovers bin/tests/test_*.sh).
#
# Failure modes: each case prints PASS/FAIL; the summary line carries both
#                counts and the exit status is 1 when any case failed.
#
# Test hygiene: everything lives under a mktemp -d root removed on exit,
#               after every process whose argv names that root is killed.
#               DS_LANE_TAB_LOCK points the tab lock inside that root, so
#               the machine's real /tmp/ds-lane-tab-<uid>.lock is never
#               touched.

set -u

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TOOL="$REPO_DIR/bin/ds-lane"

PASS=0
FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
check() { # check <description> <command...>
  local d="$1"; shift
  if "$@"; then _pass "$d"; else _fail "$d"; fi
}
eq() { [[ "$1" == "$2" ]]; }
contains() { [[ "$1" == *"$2"* ]]; }
died_with() { # died_with <rc> <output> <needle>
  [[ "$1" == 1 && "$2" == *"$3"* ]]
}

if [[ ! -x "$TOOL" ]]; then echo "FAIL: $TOOL missing or not executable" >&2; exit 1; fi

if ! command -v jq > /dev/null 2>&1; then
  if [[ -n "${CI:-}" ]]; then echo "FAIL: jq absent in CI - ds-lane cannot be exercised" >&2; exit 1; fi
  echo "SKIP: jq not found; ds-lane needs it"
  exit 0
fi
HAVE_ZSH=1
if ! command -v zsh > /dev/null 2>&1; then
  if [[ -n "${CI:-}" ]]; then echo "FAIL: zsh absent in CI - tab-command parity cannot be skipped here" >&2; exit 1; fi
  HAVE_ZSH=0
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/ds-lane-test.XXXXXX")"
TMP="$(cd "$TMP" && pwd -P)"
TAB_LOCK="$TMP/tab.lock"
cleanup() {
  pkill -f -- "$TMP/" 2> /dev/null
  sleep 0.3
  pkill -9 -f -- "$TMP/" 2> /dev/null
  rm -rf "$TMP"
}
trap cleanup EXIT

STUB="$TMP/stubs"
OSA_DIR="$STUB/osa"
LOG="$TMP/stublog"
mkdir -p "$STUB" "$OSA_DIR" "$LOG"

cat > "$STUB/claude-stub.sh" << 'EOF'
mode="" sid=""
prev=""
for a in "$@"; do
  case "$prev" in
    --permission-mode) mode="$a" ;;
    --resume) sid="$a" ;;
  esac
  prev="$a"
done
printf '%s ' "$@" >> "$STUB_LOG_DIR/claude-args"
echo >> "$STUB_LOG_DIR/claude-args"
[ -n "$sid" ] || sid="sess-$$"
jq -cn --arg s "$sid" --arg c "$PWD" --arg m "$mode" '{type: "system", subtype: "init", session_id: $s, cwd: $c, permissionMode: $m}'
while IFS= read -r line; do
  text="$(printf '%s' "$line" | jq -r '.message.content')"
  case "$text" in
    *STUB-FINISH*) out="LANE-DONE stub finished" ;;
    *STUB-BLOCK*) out="LANE-BLOCKED stub needs a decision" ;;
    *) out="ack" ;;
  esac
  jq -cn --arg t "$out" '{type: "assistant", parent_tool_use_id: null, message: {content: [{type: "text", text: $t}]}}'
  jq -cn --arg t "$out" '{type: "result", subtype: "success", is_error: false, result: $t}'
done
EOF
{ echo '#!/bin/bash'; cat "$STUB/claude-stub.sh"; } > "$STUB/claude"
chmod +x "$STUB/claude"
# A shebang install resolved through env: runs as `bash <path>/claude -p ...`.
mkdir -p "$STUB/shebang"
{ echo '#!/usr/bin/env bash'; cat "$STUB/claude-stub.sh"; } > "$STUB/shebang/claude"
chmod +x "$STUB/shebang/claude"

cat > "$OSA_DIR/osascript" << 'EOF'
#!/bin/bash
# argv: -e <script> <command> <conductor tty>  (close: -e <script> <own tty> <conductor tty>)
printf '%s' "$2" > "$STUB_LOG_DIR/osa-script"
printf '%s' "$3" > "$STUB_LOG_DIR/osa-cmd"
printf '%s' "$4" > "$STUB_LOG_DIR/osa-tty"
if [ "${STUB_OSA_GATE:-}" = 1 ]; then
  n=0
  while [ ! -e "$STUB_LOG_DIR/osa-go" ] && [ $n -lt 100 ]; do sleep 0.1; n=$((n + 1)); done
  [ -e "$STUB_LOG_DIR/osa-go" ] || { echo "gate never opened" >&2; exit 1; }
fi
case "${STUB_OSA_MODE:-kept}" in
  kept) echo "ok|tab|0|42|$4|Terminal|42|$4|Terminal" ;;
  guard) echo "ok|window|0|42|$4|Terminal|42|$4|Terminal" ;;
  orphan) echo "ok|tab|1|42|$4|Terminal|42|$4|Terminal" ;;
  orphan-window) echo "ok|window|2|42|$4|Terminal|42|$4|Terminal" ;;
  eight-fields) echo "ok|window|42|$4|Terminal|42|$4|Terminal" ;;
  notkept-window) echo "ok|tab|0|43|$4|Terminal|42|$4|Terminal" ;;
  notkept-tty) echo "ok|tab|0|42|/dev/ttys999|Terminal|42|$4|Terminal" ;;
  notkept-app) echo "ok|tab|0|42|$4|Safari|42|$4|Terminal" ;;
  nomatch) echo "nomatch" ;;
  close-ok) echo "ok" ;;
  close-busy) echo "busy" ;;
  close-notfront) echo "notfront" ;;
  fail) echo "execution error: stub refused (-1743)" >&2; echo "second line" >&2; exit 1 ;;
esac
EOF
chmod +x "$OSA_DIR/osascript"

export PATH="$OSA_DIR:$PATH"
export STUB_LOG_DIR="$LOG"
export DS_LANE_CLAUDE_BIN="$STUB/claude"
export DS_LANE_PERMISSION_MODE=bypassPermissions
export DS_LANE_TAB_LOCK_WAIT_S=1
export DS_LANE_TAB_LOCK="$TAB_LOCK"
export CLAUDE_CONFIG_DIR="$TMP/config"
export CLAUDE_CODE_SESSION_ID="conductor-sid"
export DS_LANE_NO_TAB=1
unset DS_LANE_RUN_DIR DS_LANE_MAX CLAUDE_CODE_EXECPATH STUB_OSA_MODE STUB_OSA_GATE

PRIMARY="$TMP/my repo"
mkdir -p "$PRIMARY"
git -C "$PRIMARY" init -q
git -C "$PRIMARY" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m init
RUN="$PRIMARY/.agentic/lanes/run"
PROMPT="$TMP/prompt.md"
echo "do the stub task" > "$PROMPT"
TOOL_REAL="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$TOOL")"

lane() { (cd "$PRIMARY" && "$TOOL" "$@"); }

wait_until() { # wait_until <seconds> <command...>
  local n=$(( $1 * 10 )); shift
  while (( n > 0 )); do
    if "$@"; then return 0; fi
    sleep 0.1
    n=$((n - 1))
  done
  return 1
}
list_col() { lane list "$1" | awk -v n="$1" -v c="$2" '$1 == n { print $c }'; }
state_is() { [[ "$(list_col "$1" 3)" == "$2" ]]; }
lane_down() { [[ "$(list_col "$1" 4)" == down ]]; }
init_field() { jq -r "select(.type == \"system\") | .$2" "$RUN/$1.jsonl" | tail -n1; }
last_tab_line() { tail -n1 "$RUN/$1.tab.log" 2> /dev/null; }
tab_line_is() { [[ "$(last_tab_line "$1")" == "$2" ]]; }
tab_lines() { wc -l < "$RUN/$1.tab.log" 2> /dev/null | tr -d ' '; }
tab_lines_above() { [[ "$(tab_lines "$1")" -gt "$2" ]]; }
has_file() { [[ -s "$1" ]]; }

# Runs a command with a controlling terminal (cwd: the primary checkout, tabs enabled).
run_in_pty() { # run_in_pty <outfile> <command...>
  local out="$1"; shift
  (
    cd "$PRIMARY" || exit 1
    unset DS_LANE_NO_TAB
    if script --version > /dev/null 2>&1; then
      script -q -e -c "$(printf '%q ' "$@")" /dev/null < /dev/null > "$out" 2>&1
    else
      script -q /dev/null "$@" < /dev/null > "$out" 2>&1
    fi
  )
}
# Runs `ds-lane open <name>` in a pty and waits for its .tab.log line.
open_in_pty() { # open_in_pty <name> [env assignments...]
  local name="$1" before; shift
  before="$(tab_lines "$name")"
  run_in_pty "$TMP/open.out" env "$@" "$TOOL" open "$name"
  wait_until 10 tab_lines_above "$name" "${before:-0}"
}

# --- R1/R2: help and literal hygiene ---
help_cmds="$("$TOOL" help | awk '/^  [a-z]/ { print $1 }' | tr '\n' ' ')"
check "help lists all 14 commands" eq "$help_cmds" "start send close reap resume list tail watch open open-all stop resume-hint count path "
check "no host-specific literal in bin/ds-lane (R2)" bash -c '! grep -nE "/Users/|claude-moment8|authentic8" "$1"' _ "$TOOL"

# --- input validation and repo resolution ---
out="$(lane start 'bad name' "$PROMPT" 2>&1)"; rc=$?
check "invalid lane name refused" died_with "$rc" "$out" "invalid lane name 'bad name'"
mkdir -p "$TMP/norepo"
out="$(cd "$TMP/norepo" && GIT_CEILING_DIRECTORIES="$TMP" "$TOOL" list 2>&1)"; rc=$?
check "outside a git repo dies" died_with "$rc" "$out" "not inside a git repository"
git clone -q --bare "$PRIMARY" "$TMP/bare.git"
git -C "$TMP/bare.git" worktree add -q "$TMP/barewt" 2> /dev/null
out="$(cd "$TMP/barewt" && "$TOOL" list 2>&1)"; rc=$?
check "bare primary dies" died_with "$rc" "$out" "is a bare repository"
check "bare primary writes no state" eq "$(ls -a "$TMP/barewt" "$TMP/bare.git" | grep -c '^\.agentic$')" 0

# --- lifecycle, marker contract, gitignore (R4, R5) ---
lane start a "$PROMPT" > /dev/null 2>&1
check "start creates the self-ignoring .gitignore" eq "$(cat "$PRIMARY/.agentic/lanes/.gitignore" 2> /dev/null)" "*"
check "prompts/ dir created" test -d "$PRIMARY/.agentic/lanes/prompts"
check "no lane file shows in git status" eq "$(git -C "$PRIMARY" status --porcelain)" ""
first_in="$(head -n1 "$RUN/a.in" | jq -r '.message.content')"
check "marker contract leads the first .in message" contains "$first_in" 'When the whole task is finished print a final line starting exactly `LANE-DONE` and the one-line outcome; if you must stop for a decision print a line starting exactly `LANE-BLOCKED` and the question. Print neither before then. Never poll or sleep.

do the stub task'
check "marker contract is the first thing in the message" eq "${first_in%%LANE-DONE*}" 'When the whole task is finished print a final line starting exactly `'
check "lane a alive after start" state_is a alive
check "permission mode taken from DS_LANE_PERMISSION_MODE" eq "$(init_field a permissionMode)" bypassPermissions
check "lane runs in the primary checkout" eq "$(init_field a cwd)" "$PRIMARY"
check "count is 1" eq "$(lane count)" 1
lane send a "STUB-FINISH please" > /dev/null
check "lane a reports done after a finishing send" wait_until 10 state_is a done
out="$(lane reap)"
check "reap closes a LANE-DONE lane" contains "$out" "reaped a (done): stdin closed"
check "reaped lane exits" wait_until 10 lane_down a
check "count back to 0" eq "$(lane count)" 0

DS_LANE_MAX=1 lane start b "$PROMPT" > /dev/null 2>&1
out="$(DS_LANE_MAX=1 lane start c "$PROMPT" 2>&1)"; rc=$?
check "cap refuses a second lane at DS_LANE_MAX=1" died_with "$rc" "$out" "refusing: 1 lanes running (max 1)"
check "refused lane wrote no files" eq "$(ls "$RUN" | grep -c '^c\.')" 0

lane send b "STUB-BLOCK" > /dev/null
check "lane b reports blocked" wait_until 10 state_is b blocked
out="$(lane reap)"
check "reap closes a LANE-BLOCKED lane" contains "$out" "reaped b (blocked): stdin closed"
check "blocked lane exits" wait_until 10 lane_down b
b_sid="$(init_field b session_id)"
lane resume b "STUB-FINISH ruling given" > /dev/null 2>&1
check "resume relaunches on the recorded session" contains "$(tail -n1 "$LOG/claude-args")" "--resume $b_sid "
check "resumed lane reports done" wait_until 10 state_is b done
lane reap > /dev/null
wait_until 10 lane_down b

lane start c "$PROMPT" > /dev/null 2>&1
out="$(lane list a b | awk 'NR > 1 { print $1 }' | tr '\n' ' ')"
check "list a b shows a and b only" eq "$out" "a b "
lane stop c > /dev/null

DS_LANE_CLAUDE_BIN="$STUB/shebang/claude" lane start sb "$PROMPT" > /dev/null 2>&1
check "shebang-installed claude lane shows alive" state_is sb alive
check "shebang-installed claude lane is counted" eq "$(lane count)" 1
out="$(lane start sb "$PROMPT" 2>&1)"; rc=$?
check "shebang-installed claude lane refuses a second start" died_with "$rc" "$out" "lane 'sb' is already running"
lane stop sb > /dev/null
check "stopped shebang lane goes down" wait_until 10 lane_down sb

out="$(cd "$PRIMARY" && env -u CLAUDE_CONFIG_DIR "$TOOL" resume-hint a)"
check "resume-hint without CLAUDE_CONFIG_DIR prints the bare resume command" eq "$out" "cd $(printf '%q' "$PRIMARY") && claude --resume $(init_field a session_id)"
out="$(lane resume-hint a)"
check "resume-hint names CLAUDE_CONFIG_DIR when set" contains "$out" "&& CLAUDE_CONFIG_DIR=$(printf '%q' "$CLAUDE_CONFIG_DIR") claude --resume "

# --- worktree anchoring (R3) ---
git -C "$PRIMARY" worktree add -q "$TMP/wt" -b wtb 2> /dev/null
(cd "$TMP/wt" && "$TOOL" start wtl "$PROMPT" > /dev/null 2>&1)
check "worktree call records state in the primary checkout" test -f "$RUN/wtl.meta"
check "worktree call writes nothing in the worktree" test ! -e "$TMP/wt/.agentic"
check "worktree-launched lane runs in the primary checkout" eq "$(init_field wtl cwd)" "$PRIMARY"
lane stop wtl > /dev/null
check "path from a worktree prints the primary checkout's state dir" eq "$(cd "$TMP/wt" && "$TOOL" path 2>&1)" "$PRIMARY/.agentic/lanes"

# --- liveness: a reused pid is never taken for the lane (stop must not signal it) ---
# Decoys are double-forked so they are not this shell's children: a signalled decoy is reaped at
# once instead of lingering as a zombie that kill -0 still finds.
args_have() { [[ "$(ps -p "$1" -o args= 2> /dev/null)" == *"$2"* ]]; }
# Lane r's recorded pid number now belongs to <pid>, as after the OS reuses it.
reuse_pid() { echo "$1" > "$RUN/r.pid"; echo "pid=$1" >> "$RUN/r.meta"; }
lane start r "$PROMPT" > /dev/null 2>&1
r_pid="$(cat "$RUN/r.pid")"
kill -9 "$r_pid" "$(cat "$RUN/r.tailpid")" 2> /dev/null
wait_until 5 bash -c '! kill -0 "$1" 2> /dev/null' _ "$r_pid"
decoy="$( ( (exec -a claude sleep 60) > /dev/null 2>&1 & echo $! ) )"
wait_until 5 args_have "$decoy" "claude 60"
reuse_pid "$decoy"
out="$(lane stop r)"
check "stop leaves a reused pid running an interactive claude alone" contains "$out" "lane 'r' not running"
sleep 0.5
check "the interactive-claude decoy is still alive" kill -0 "$decoy"
kill "$decoy" 2> /dev/null
sleep 1.1
decoy="$( (sleep 60 | "$STUB/claude" -p --input-format stream-json > /dev/null 2>&1 & echo $!) )"
wait_until 5 args_have "$decoy" "$STUB/claude -p "
reuse_pid "$decoy"
out="$(lane stop r)"
check "stop leaves a reused pid running the recorded claude path alone" contains "$out" "lane 'r' not running"
sleep 0.5
check "the recorded-path decoy is still alive" kill -0 "$decoy"
kill "$decoy" 2> /dev/null

# --- permission mode resolution (R6) ---
PROJ="$CLAUDE_CONFIG_DIR/projects/-proj"
mkdir -p "$PROJ"
{
  echo '{"type":"user","permissionMode":"plan"}'
  echo '{"type":"permission-mode","permissionMode":"default","sessionId":"conductor-sid"}'
  echo 'not json'
  echo '{"type":"permission-mode","permissionMode":"acceptEdits","sessionId":"conductor-sid"}'
  echo '{"type":"user","permissionMode":"plan"}'
} > "$PROJ/conductor-sid.jsonl"
(cd "$PRIMARY" && env -u DS_LANE_PERMISSION_MODE "$TOOL" start m1 "$PROMPT" > /dev/null 2>&1)
check "mode from the last permission-mode record" eq "$(init_field m1 permissionMode)" acceptEdits
lane stop m1 > /dev/null
{
  echo '{"type":"user","permissionMode":"default"}'
  echo '{"type":"assistant","permissionMode":"plan"}'
  echo '{"type":"user","permissionMode":"dontAsk"}'
  echo '{"type":"user"}'
} > "$PROJ/conductor-sid.jsonl"
(cd "$PRIMARY" && env -u DS_LANE_PERMISSION_MODE "$TOOL" start m2 "$PROMPT" > /dev/null 2>&1)
check "mode from the user-record fallback" eq "$(init_field m2 permissionMode)" dontAsk
lane stop m2 > /dev/null
(cd "$PRIMARY" && DS_LANE_PERMISSION_MODE=plan "$TOOL" start m3 "$PROMPT" > /dev/null 2>&1)
check "DS_LANE_PERMISSION_MODE wins over the transcript" eq "$(init_field m3 permissionMode)" plan
lane stop m3 > /dev/null
out="$(cd "$PRIMARY" && env -u DS_LANE_PERMISSION_MODE CLAUDE_CODE_SESSION_ID=no-such-session "$TOOL" start m4 "$PROMPT" 2>&1)"; rc=$?
check "unresolvable mode dies" died_with "$rc" "$out" "cannot determine the conductor's permission mode; set DS_LANE_PERMISSION_MODE"
check "unresolvable mode wrote no files" test ! -e "$RUN/m4.meta"

# --- tab opener (R7, R8, R13) ---
# The tty is resolved by `start` in the foreground and handed to the detached opener; the stub
# osascript is gated so it only answers after `start` has exited and its pty is gone.
rm -f "$LOG"/osa-*
run_in_pty "$TMP/pty1.out" env STUB_OSA_GATE=1 /bin/sh -c 'tty > "$1"; exec "$2" start t1 "$3"' sh "$TMP/pty1.tty" "$TOOL" "$PROMPT"
check "start in a pty returned before the opener finished" test ! -e "$RUN/t1.tab.log"
touch "$LOG/osa-go"
check "opener recorded an outcome" wait_until 10 has_file "$RUN/t1.tab.log"
pty_tty="$(cat "$TMP/pty1.tty")"
check "foreground-resolved tty reached osascript" eq "$(cat "$LOG/osa-tty" 2> /dev/null)" "$pty_tty"
check "tab.log: focus kept" tab_line_is t1 "focus: kept"
check "tab.log records the tab path" eq "$(head -n1 "$RUN/t1.tab.log")" "opened: tab"
check "tab command (no run-dir override)" eq "$(cat "$LOG/osa-cmd")" "cd $(printf '%q' "$PRIMARY") && DS_LANE_WATCH_CLOSE_TAB=1 DS_LANE_CONDUCTOR_TTY=$(printf '%q' "$pty_tty") $(printf '%q' "$TOOL_REAL") watch t1; exit"

# No AppleScript runs against Terminal here, so these pin the script's routing structure.
osa_script="$(cat "$LOG/osa-script")"
(cd "$PRIMARY" && STUB_OSA_MODE=close-ok "$TOOL" __close-tab /dev/ttys998 /dev/ttys997 "$TMP/capture.log")
cp "$LOG/osa-script" "$TMP/close.applescript"
close_script="$(cat "$TMP/close.applescript")"
osa_line() { printf '%s\n' "$1" | grep -n -F -- "$2" | head -n1 | cut -d: -f1; }
osa_before() { # osa_before <script> <earlier> <later>: both present, earlier first
  local a b
  a="$(osa_line "$1" "$2")"; b="$(osa_line "$1" "$3")"
  [[ -n "$a" && -n "$b" ]] && (( a < b ))
}
osa_prev_line() { printf '%s\n' "$1" | grep -B1 -F -- "$2" | head -n1 | tr -s ' '; }
check "AppleScript sends do script exactly twice" eq "$(printf '%s\n' "$osa_script" | grep -c 'do script')" 2
osa_handler() { printf '%s\n' "$1" | sed -n '/^on newTtys/,/^end newTtys/p'; }
check "the only targeted do script goes to the tab whose tty is targetTty" eq "$(osa_prev_line "$osa_script" 'do script theCmd in aTab')" " if tty of aTab is targetTty then"
check "targetTty is only ever empty or the single new tty" eq "$(printf '%s\n' "$osa_script" | grep -F 'set targetTty to' | tr -s ' ' | tr '\n' '|')" " set targetTty to \"\"| if (count of found) is 1 then set targetTty to item 1 of found|"
check "found is only ever empty or the new ttys" eq "$(printf '%s\n' "$osa_script" | grep -F 'set found to' | grep -v '^ *set found to {}$' | tr -s ' ' | tr '\n' '|')" " set found to my newTtys(beforeTtys)|"
check "new ttys are scanned across every window (native tabs are one-tab windows)" eq "$(osa_handler "$osa_script" | grep -E 'repeat with|does not contain' | tr -s ' ' | tr '\n' '|')" " repeat with aWin in windows| repeat with aTab in tabs of aWin| if beforeTtys does not contain t then set end of found to t|"
check "before-ttys recorded across every window, before Cmd-T" osa_before "$osa_script" 'set end of beforeTtys to (tty of aTab)' 'keystroke "t"'
check "before-ttys loop spans all windows" eq "$(printf '%s\n' "$osa_script" | sed -n '/^on run/,$p' | grep -B2 -F 'set end of beforeTtys' | head -n2 | tr -s ' ' | tr '\n' '|')" " repeat with aWin in windows| repeat with aTab in tabs of aWin|"
check "no single new tab -> new window" contains "$osa_script" 'if how is "window" then set cmdTty to tty of (do script theCmd)'
check "orphans exclude the tty running the command" eq "$(osa_prev_line "$osa_script" 'set orphans to orphans + 1')" " repeat with t in my newTtys(beforeTtys)"
check "orphan test compares against cmdTty" contains "$osa_script" 'if (contents of t) is not cmdTty then set orphans to orphans + 1'
check "nothing is closed by the open script" bash -c '! grep -qE "close |keystroke \"w\"" <<< "$1"' _ "$osa_script"
osa_run() { printf '%s\n' "$1" | sed -n '/^on run argv/,$p'; }
open_run="$(osa_run "$osa_script")"
close_run="$(osa_run "$close_script")"
check "conductor tab selected before Cmd-T" osa_before "$open_run" 'set selected of aTab to true' 'keystroke "t"'
# Terminal not running: return before any event that would launch it (compiling does not).
first_app_line() { printf '%s\n' "$1" | grep -m1 -F 'application ' | tr -s ' '; }
check "open returns nomatch before touching any app when Terminal is not running" eq "$(first_app_line "$open_run")" ' if application "Terminal" is not running then return "nomatch"'
check "close returns nomatch before touching any app when Terminal is not running" eq "$(first_app_line "$close_run")" ' if application "Terminal" is not running then return "nomatch"'
# Focus: afterwards the recorded front window is raised, not the conductor's window.
check "open raises the conductor window only before Cmd-T" eq "$(printf '%s\n' "$open_run" | grep -c 'set index of window id condWinId to 1')" 1
check "open records the conductor window's selected tab before selecting the conductor tab" osa_before "$open_run" 'set condWinSel to tty of selected tab of aWin' 'set selected of aTab to true'
check "open restores the conductor window's selected tab after the command" osa_before "$open_run" 'set orphans to 0' 'my selectTty(condWinSel)'
check "open then raises the recorded front window" osa_before "$open_run" 'my selectTty(condWinSel)' 'set index of window id recFrontId to 1'
check "open then re-selects the recorded front tab" osa_before "$open_run" 'set index of window id recFrontId to 1' 'my selectTty(recTty)'
check "close raises the recorded front window after Cmd-W" osa_before "$close_run" 'keystroke "w"' 'set index of window id recFrontId to 1'
check "close raises no other window after Cmd-W" eq "$(printf '%s\n' "$close_run" | sed -n '/keystroke "w"/,$p' | grep -c 'set index of')" 1
osa_encloses() { # osa_encloses <script> <if-line> <inner>: inner follows the if with no end if between
  local a b
  osa_before "$1" "$2" "$3" || return 1
  a="$(osa_line "$1" "$2")"; b="$(osa_line "$1" "$3")"
  ! printf '%s\n' "$1" | sed -n "${a},${b}p" | grep -q 'end if'
}
check "Cmd-T sent only while Terminal is frontmost" osa_encloses "$osa_script" 'if termFront then' 'keystroke "t"'
check "Cmd-W sent only for our tab in a frontmost Terminal" osa_encloses "$close_script" 'if termFront and selTty is myTty then' 'keystroke "w"'
check "open restores the frontmost app by process id" contains "$osa_script" 'whose unix id is recPid) to true'
check "close restores the frontmost app by process id" contains "$close_script" 'whose unix id is recPid) to true'
check "no activate by process name" bash -c '! grep -q "tell application recApp" "$1"' _ "$TOOL"
if command -v osacompile > /dev/null 2>&1; then
  check "open AppleScript compiles" osacompile -o "$TMP/open.scpt" "$LOG/osa-script"
  check "close AppleScript compiles" osacompile -o "$TMP/close.scpt" "$TMP/close.applescript"
fi

open_in_pty t1 STUB_OSA_MODE=guard
check "tab.log: no new tab -> new window, reported as misplaced" eq "$(tail -n2 "$RUN/t1.tab.log" | tr '\n' '|')" "opened: window|tab misplaced (new window, no new tab found); focus: kept|"
open_in_pty t1 STUB_OSA_MODE=orphan
check "tab.log: stray new tab reported as orphaned, not focus kept" eq "$(tail -n2 "$RUN/t1.tab.log" | tr '\n' '|')" "opened: tab|tab orphaned (1 other new tab(s) after Cmd-T, left open); focus: kept|"
open_in_pty t1 STUB_OSA_MODE=orphan-window
check "tab.log: orphan on the window path" tab_line_is t1 "tab orphaned (2 other new tab(s) after Cmd-T, left open); focus: kept"
open_in_pty t1 STUB_OSA_MODE=eight-fields
check "tab.log: output without an orphan count is an error" contains "$(last_tab_line t1)" "tab error: unexpected osascript output 'ok|window|42|"
open_in_pty t1 STUB_OSA_MODE=notkept-window
check "tab.log: focus NOT kept (front window changed)" contains "$(last_tab_line t1)" "focus: NOT kept (front window 43, tab "
open_in_pty t1 STUB_OSA_MODE=notkept-tty
check "tab.log: focus NOT kept (selected tab changed)" contains "$(last_tab_line t1)" "focus: NOT kept (front window 42, tab /dev/ttys999, app Terminal; was 42, "
open_in_pty t1 STUB_OSA_MODE=notkept-app
check "tab.log: focus NOT kept (frontmost app changed)" contains "$(last_tab_line t1)" ", app Safari; was 42, "
open_in_pty t1 STUB_OSA_MODE=nomatch
check "tab.log: no matching tab" tab_line_is t1 "tab skipped: no matching tab"
open_in_pty t1 STUB_OSA_MODE=fail
check "tab.log: osascript exit 1" tab_line_is t1 "tab error: execution error: stub refused (-1743); focus: unknown"

SANDBOX="$TMP/sandbox-bin"
mkdir -p "$SANDBOX"
for c in bash sh env python3 git jq ps awk tr grep cut mktemp mv rm rmdir mkdir cat date basename dirname tail head wc sed sleep nohup id tty; do
  ln -s "$(command -v "$c")" "$SANDBOX/$c"
done
open_in_pty t1 PATH="$SANDBOX"
check "tab.log: no osascript" tab_line_is t1 "tab skipped: no osascript"

# Lock busy: hold the (scratch) tab lock from another process, as a concurrent opener would.
python3 - "$TAB_LOCK" "$TMP/locked" << 'PY' &
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
open(sys.argv[2], "w").close()
time.sleep(8)
PY
holder=$!
check "scratch tab lock held by the test" wait_until 5 test -e "$TMP/locked"
open_in_pty t1 DS_LANE_TAB_LOCK_WAIT_S=1
check "tab.log: lock busy" tab_line_is t1 "tab skipped: lock busy"
kill "$holder" 2> /dev/null
wait "$holder" 2> /dev/null
open_in_pty t1
check "lock is free again once its holder is gone" tab_line_is t1 "focus: kept"

# Lock unavailable: the lock path is a directory.
rm -f "$TAB_LOCK"
mkdir "$TAB_LOCK"
open_in_pty t1
check "tab.log: lock unavailable" tab_line_is t1 "tab skipped: lock unavailable"
rmdir "$TAB_LOCK"
lane stop t1 > /dev/null

# Tab close outcomes, recorded in the lane's tab.log.
CLOSE_LOG="$TMP/close tab.log"
close_tab() { # close_tab <osa mode> [env assignments...]
  local mode="$1"; shift
  (cd "$PRIMARY" && env STUB_OSA_MODE="$mode" "$@" "$TOOL" __close-tab /dev/ttys998 /dev/ttys997 "$CLOSE_LOG")
  tail -n1 "$CLOSE_LOG" 2> /dev/null
}
check "close: ok" eq "$(close_tab close-ok)" "close: ok"
check "close: tab busy" eq "$(close_tab close-busy)" "close skipped: tab busy"
check "close: Terminal not frontmost" eq "$(close_tab close-notfront)" "close skipped: Terminal not frontmost"
check "close: no matching tab" eq "$(close_tab nomatch)" "close skipped: no matching tab"
check "close: osascript exit 1" eq "$(close_tab fail)" "close error: execution error: stub refused (-1743)"
check "close: no osascript" eq "$(close_tab close-ok PATH="$SANDBOX")" "close skipped: no osascript"
check "close passes its own and the conductor tty" eq "$(cat "$LOG/osa-cmd")|$(cat "$LOG/osa-tty")" "/dev/ttys998|/dev/ttys997"

# No ancestor with a terminal: start runs as an orphan in its own session.
python3 - "$TOOL" "$PROMPT" "$PRIMARY" "$TMP/orphan.out" << 'PY'
import os, sys, time
tool, prompt, cwd, out = sys.argv[1:5]
if os.fork():
    os.wait()
    sys.exit(0)
os.setsid()
middle = os.getpid()
if os.fork():
    os._exit(0)
for _ in range(100):
    if os.getppid() != middle:
        break
    time.sleep(0.05)
os.chdir(cwd)
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
os.dup2(fd, 1)
os.dup2(fd, 2)
env = dict(os.environ)
env.pop("DS_LANE_NO_TAB", None)
os.execve(tool, [tool, "start", "t3", prompt], env)
PY
check "tab.log: no conductor tty" wait_until 15 tab_line_is t3 "tab skipped: no conductor tty"
lane stop t3 > /dev/null

# Tab command parity (R7): run-dir override, and spaces in the primary, run dir and tool paths.
TOOL_COPY_DIR="$TMP/tool dir"
mkdir -p "$TOOL_COPY_DIR"
cp "$TOOL" "$TOOL_COPY_DIR/ds-lane"
rm -f "$LOG"/osa-*
run_in_pty "$TMP/pty2.out" env DS_LANE_RUN_DIR="$TMP/run dir" /bin/sh -c 'tty > "$1"; exec "$2" start t2 "$3"' sh "$TMP/pty2.tty" "$TOOL_COPY_DIR/ds-lane" "$PROMPT"
check "run-dir override lane opened a tab" wait_until 10 has_file "$TMP/run dir/t2.tab.log"
cmd="$(cat "$LOG/osa-cmd" 2> /dev/null)"
check "tab command carries the run-dir override" contains "$cmd" "DS_LANE_RUN_DIR=$(printf '%q' "$TMP/run dir") DS_LANE_WATCH_CLOSE_TAB=1"
cat > "$TMP/printer" << 'EOF'
#!/bin/bash
echo "pwd=$(pwd -P)"
echo "run_dir=${DS_LANE_RUN_DIR-unset}"
echo "close=${DS_LANE_WATCH_CLOSE_TAB-unset}"
echo "ctty=${DS_LANE_CONDUCTOR_TTY-unset}"
echo "argv0=$0"
for a in "$@"; do echo "arg=$a"; done
EOF
chmod +x "$TMP/printer"
mv "$TMP/printer" "$TOOL_COPY_DIR/ds-lane"
expected="pwd=$PRIMARY
run_dir=$TMP/run dir
close=1
ctty=$(cat "$TMP/pty2.tty")
argv0=$TOOL_COPY_DIR/ds-lane
arg=watch
arg=t2"
bash_argv="$(env -u DS_LANE_RUN_DIR bash -c "$cmd" 2>&1)"
check "tab command argv under bash -c" eq "$bash_argv" "$expected"
if (( HAVE_ZSH )); then
  zsh_argv="$(env -u DS_LANE_RUN_DIR zsh -f -c "$cmd" 2>&1)"
  check "tab command argv under zsh -c" eq "$zsh_argv" "$expected"
else
  echo "SKIP: zsh not found; zsh half of the tab-command parity case not run"
fi
(cd "$PRIMARY" && DS_LANE_RUN_DIR="$TMP/run dir" "$TOOL" stop t2 > /dev/null)

echo "ds-lane tests: $PASS passed, $FAIL failed"
(( FAIL == 0 ))
