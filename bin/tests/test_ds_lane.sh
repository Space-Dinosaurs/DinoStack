#!/usr/bin/env bash
# Purpose: Regression suite for bin/ds-lane. Drives the real tool against a
#          scratch git repo (path contains a space) with a stub `claude`
#          (a bash script, so `ps` shows `/bin/bash <stub path> -p ...`, the
#          recorded path the tool's liveness check requires) and a stub
#          `osascript` whose reply is chosen by STUB_OSA_MODE. Never launches
#          a real claude session and never runs AppleScript against Terminal
#          (osacompile reads Terminal's static sdef without launching it).
#          On macOS it runs the real on-screen window query (a JXA
#          CoreGraphics call that sends no Apple event) by absolute path.
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
# argv: -e <script> <command> <conductor tty> <on-screen JXA>
#   (close: -e <script> <own tty> <conductor tty> <on-screen JXA>)
printf '%s' "$2" > "$STUB_LOG_DIR/osa-script"
printf '%s' "$3" > "$STUB_LOG_DIR/osa-cmd"
printf '%s' "$4" > "$STUB_LOG_DIR/osa-tty"
printf '%s' "$5" > "$STUB_LOG_DIR/osa-jxa"
if [ "${STUB_OSA_GATE:-}" = 1 ]; then
  n=0
  while [ ! -e "$STUB_LOG_DIR/osa-go" ] && [ $n -lt 100 ]; do sleep 0.1; n=$((n + 1)); done
  [ -e "$STUB_LOG_DIR/osa-go" ] || { echo "gate never opened" >&2; exit 1; }
fi
# Open replies: ok|how|orphans|front window|its tab|app (observed), the same three recorded, then
# the conductor window's selected tab observed and recorded, then whether the conductor window is on
# screen in the current Space. native-*: a native-tab Terminal, where every tab is a one-tab
# window, so the conductor window's selected tab is always the conductor's.
case "${STUB_OSA_MODE:-kept}" in
  kept) echo "ok|tab|0|42|$4|Terminal|42|$4|Terminal|$4|$4|on" ;;
  guard) echo "ok|window|0|42|$4|Terminal|42|$4|Terminal|$4|$4|on" ;;
  orphan) echo "ok|tab|1|42|$4|Terminal|42|$4|Terminal|$4|$4|on" ;;
  orphan-window) echo "ok|window|2|42|$4|Terminal|42|$4|Terminal|$4|$4|on" ;;
  eight-fields) echo "ok|window|42|$4|Terminal|42|$4|Terminal" ;;
  nine-fields) echo "ok|tab|0|42|$4|Terminal|42|$4|Terminal" ;;
  notkept-window) echo "ok|tab|0|43|$4|Terminal|42|$4|Terminal|$4|$4|on" ;;
  notkept-tty) echo "ok|tab|0|42|/dev/ttys999|Terminal|42|$4|Terminal|$4|$4|on" ;;
  notkept-app) echo "ok|tab|0|42|$4|Safari|42|$4|Terminal|$4|$4|on" ;;
  notkept-cond) echo "ok|tab|0|43|/dev/ttys900|Terminal|43|/dev/ttys900|Terminal|/dev/ttys999|$4|on" ;;
  native-other-front) echo "ok|tab|0|51|/dev/ttys900|Terminal|51|/dev/ttys900|Terminal|$4|$4|on" ;;
  native-moved) echo "ok|tab|0|52|/dev/ttys999|Terminal|51|/dev/ttys900|Terminal|$4|$4|on" ;;
  eleven-fields) echo "ok|tab|0|42|$4|Terminal|42|$4|Terminal|$4|$4" ;;
  bad-space) echo "ok|tab|0|42|$4|Terminal|42|$4|Terminal|$4|$4|maybe" ;;
  offscreen) echo "ok|window|0|42|$4|Terminal|42|$4|Terminal|$4|$4|off" ;;
  space-unknown) echo "ok|window|0|42|$4|Terminal|42|$4|Terminal|$4|$4|unknown" ;;
  nomatch) echo "nomatch" ;;
  close-ok) echo "ok" ;;
  close-busy) echo "busy" ;;
  close-notfront) echo "notfront" ;;
  close-offscreen) echo "offscreen" ;;
  close-spaceunknown) echo "spaceunknown" ;;
  fail) echo "execution error: stub refused (-1743)" >&2; echo "second line" >&2; exit 1 ;;
  fail-other) echo "execution error: stub syntax error (-2741)" >&2; exit 1 ;;
  # A previous watch tab's closer appends to the same tab log while this open is still running.
  close-first) echo "close skipped: tab busy" >> "$STUB_TAB_LOG"; sleep 1; echo "ok|tab|0|42|$4|Terminal|42|$4|Terminal|$4|$4|on" ;;
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
check "help lists all 15 commands" eq "$help_cmds" "start send close reap resume list tail watch open open-all stop resume-hint count path doctor "
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
run_in_pty "$TMP/pty1.out" env STUB_OSA_GATE=1 DS_LANE_TAB_WAIT_S=1 /bin/sh -c 'tty > "$1"; exec "$2" start t1 "$3"' sh "$TMP/pty1.tty" "$TOOL" "$PROMPT"
check "start in a pty returned before the opener finished" test ! -e "$RUN/t1.tab.log"
check "start gives up on the tab outcome after DS_LANE_TAB_WAIT_S" contains "$(cat "$TMP/pty1.out")" "tab: unknown (no outcome after 1s)"
check "an unknown tab outcome names the tab log and the tab-less path" contains "$(cat "$TMP/pty1.out")" "fix: the tab opener has not finished (if macOS is showing a permission dialog, answer Allow). Its result will be the last line of $RUN/t1.tab.log, and \`ds-lane open t1\` retries it; meanwhile the lane is running without a tab: follow it with \`ds-lane tail t1\`"
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
check "open restores the conductor window's selected tab after the command" osa_before "$open_run" 'set orphans to 0' 'my selectTty(condWinSel, false)'
check "open then raises the recorded front window" osa_before "$open_run" 'my selectTty(condWinSel, false)' 'set index of window id recFrontId to 1'
check "open then re-selects the recorded front tab" osa_before "$open_run" 'set index of window id recFrontId to 1' 'my selectTty(recTty, false)'
# Native tabs: a one-tab window's selected tab cannot be changed, so the conductor's tab is
# reselected in its tab group by raising its window, before the recorded front window is raised.
select_handler="$(printf '%s\n' "$osa_script" | sed -n '/^on selectTty/,/^end selectTty/p' | tr -s ' ' | tr '\n' '|')"
check "selectTty raises a one-tab window only when it is on this Space and selects only within multi-tab windows" contains "$select_handler" "| if tty of aTab is t then| if (count of tabs of aWin) is 1 then| if my spaceOf(id of aWin) is \"on\" then set index of aWin to 1| else if not loneOnly then| set selected of aTab to true| end if| return|"
check "open and close share the same selectTty handler" eq "$(printf '%s\n' "$close_script" | sed -n '/^on selectTty/,/^end selectTty/p' | tr -s ' ' | tr '\n' '|')" "$select_handler"
check "open restores the conductor window's tab with one-tab windows raised" contains "$open_run" 'my selectTty(condWinSel, false)'
check "close selects the conductor's lone tab after closing a one-tab window" contains "$(printf '%s\n' "$close_run" | grep -A3 -F 'close aWin' | tr -s ' ' | tr '\n' '|')" ' close aWin| set outcome to "ok"| set winSel to condTty| set loneOnly to true|'
check "close restores that selection before raising the recorded front window" osa_before "$close_run" 'my selectTty(winSel, loneOnly)' 'set index of window id recFrontId to 1'
check "close leaves loneOnly off unless a one-tab window was closed" eq "$(printf '%s\n' "$close_run" | grep -c 'set loneOnly to')" 2
check "open observes the conductor window's selected tab after restoring the app" osa_before "$open_run" 'whose unix id is recPid) to true' 'if tty of aTab is condTty then set obsCond to tty of selected tab of aWin'
check "open reports observed then recorded conductor window tab" contains "$open_run" '& "|" & recApp & "|" & obsCond & "|" & condWinSel'
osa_encloses() { # osa_encloses <script> <if-line> <inner>: inner follows the if with no end if between
  local a b
  osa_before "$1" "$2" "$3" || return 1
  a="$(osa_line "$1" "$2")"; b="$(osa_line "$1" "$3")"
  ! printf '%s\n' "$1" | sed -n "${a},${b}p" | grep -q 'end if'
}
# Spaces: raising or activating onto a window that is not on screen in the current Space pulls it
# into this Space or switches Space, so every raise is gated on spaceOf.
space_handler="$(printf '%s\n' "$osa_script" | sed -n '/^on spaceOf/,/^end spaceOf/p' | tr -s ' ' | tr '\n' '|')"
check "spaceOf answers unknown when the on-screen query fails" contains "$space_handler" '| on error| set shown to ""| end try| end if| if shown is "" then return "unknown"|'
check "spaceOf answers on only for an id in the on-screen list" contains "$space_handler" '| if ("," & shown & ",") contains ("," & (winId as text) & ",") then return "on"| return "off"|'
check "open and close share the same spaceOf handler" eq "$(printf '%s\n' "$close_script" | sed -n '/^on spaceOf/,/^end spaceOf/p' | tr -s ' ' | tr '\n' '|')" "$space_handler"
check "open raises the conductor window only when it is on this Space" osa_encloses "$open_run" 'if condSpace is "on" then' 'set index of window id condWinId to 1'
check "open activates Terminal only when the conductor window is on this Space" osa_encloses "$open_run" 'if condSpace is "on" then' 'activate'
check "open activates Terminal exactly once" eq "$(printf '%s\n' "$open_run" | grep -c 'activate')" 1
check "Cmd-T is never sent unless the conductor window was raised (termFront starts false)" osa_before "$open_run" 'set termFront to false' 'if condSpace is "on" then'
check "open raises the recorded front window only when it is on this Space" osa_encloses "$open_run" 'if my spaceOf(recFrontId) is "on" then' 'set index of window id recFrontId to 1'
check "open reports the conductor window's Space last" contains "$open_run" '& "|" & condWinSel & "|" & condSpace'
check "open's only window raises are the three Space-gated ones" eq "$(printf '%s\n' "$osa_script" | grep -c 'set index of')" 3
check "close raises the recorded front window only when it is on this Space" osa_encloses "$close_run" 'if my spaceOf(recFrontId) is "on" then' 'set index of window id recFrontId to 1'
check "close returns before selecting or raising a window that is not on this Space" osa_before "$close_run" 'if winSpace is not "on" then return "spaceunknown"' 'set selected of aTab to true'
check "close checks the Space of the window it would raise" osa_before "$close_run" 'set winSpace to my spaceOf(id of aWin)' 'if winSpace is "off" then return "offscreen"'
check "close's only window raises are the three Space-gated ones" eq "$(printf '%s\n' "$close_script" | grep -c 'set index of')" 3
check "open and close read the on-screen query from their third argument" eq "$(printf '%s\n' "$open_run" "$close_run" | grep -c 'set onScreenJxa to item 3 of argv')" 2
check "the on-screen query is passed to osascript" contains "$(cat "$LOG/osa-jxa")" '$.kCGWindowListOptionOnScreenOnly'
# A CoreGraphics query, not an Apple event: it reads the window list and touches no app.
if [[ -x /usr/bin/osascript ]]; then
  check "the on-screen query prints comma-separated window ids" bash -c '[[ "$(/usr/bin/osascript -l JavaScript -e "$1")" =~ ^[0-9]+(,[0-9]+)*$ ]]' _ "$(cat "$LOG/osa-jxa")"
  # Native tabs: once Cmd-T puts the watch tab in front, the conductor's window leaves the
  # on-screen list. A stand-in query answers 42 on its first call and 7 after, and the real
  # handlers must keep answering from the first reading so the restore raises still run.
  cat > "$TMP/space-ids.sh" << 'SH'
#!/bin/sh
f="$(dirname "$0")/space-calls"
n="$(cat "$f" 2> /dev/null || echo 0)"
echo $((n + 1)) > "$f"
if [ "$n" = 0 ]; then echo 42; else echo 7; fi
SH
  space_jxa="var a = Application.currentApplication(); a.includeStandardAdditions = true; a.doShellScript($(python3 -c 'import json, sys; print(json.dumps("/bin/sh " + sys.argv[1]))' "$TMP/space-ids.sh"))"
  space_handlers="$(printf '%s\n' "$osa_script" | sed -n '1,/^end selectTty/p')"
  space_probe="$space_handlers
on run argv
  set onScreenJxa to item 1 of argv
  return (my spaceOf(42)) & \" \" & (my spaceOf(42)) & \" \" & (my spaceOf(7))
end run"
  check "spaceOf keeps the reading taken before anything changed" eq "$(/usr/bin/osascript -e "$space_probe" "$space_jxa" 2>&1)" "on on off"
  check "spaceOf ran the on-screen query once" eq "$(cat "$TMP/space-calls" 2> /dev/null)" 1
  check "open takes the Space reading before selecting the conductor tab" osa_before "$open_run" 'if recFrontId is not missing value then my spaceOf(recFrontId)' 'set selected of aTab to true'
  check "close takes the Space reading before closing or selecting anything" osa_before "$close_run" 'if recFrontId is not missing value then my spaceOf(recFrontId)' 'close aWin'
  # Terminal's window id must be the CGWindowID the on-screen list carries. Reading the ids is an
  # Apple event to Terminal: it raises nothing, but on a machine that has not granted this terminal
  # Automation access to Terminal it would block on a consent dialog, so it is opt-in.
  if [[ "${DS_LANE_TEST_TERMINAL_IDS:-}" == 1 ]] && [[ "$(/usr/bin/osascript -e 'application "Terminal" is running')" == true ]]; then
    term_ids="$(/usr/bin/osascript -e 'tell application "Terminal" to get id of every window' | tr -d ' ')"
    cg_ids="$(/usr/bin/osascript -l JavaScript -e 'ObjC.import("CoreGraphics"); ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo($.kCGWindowListOptionAll, $.kCGNullWindowID))).filter(function (w) { return w.kCGWindowOwnerName === "Terminal"; }).map(function (w) { return w.kCGWindowNumber; }).join(",")')"
    check "Terminal reports at least one window id" bash -c '[[ "$1" =~ ^[0-9]+(,[0-9]+)*$ ]]' _ "$term_ids"
    check "every Terminal window id is a CGWindowID of a Terminal window" bash -c 'for i in ${1//,/ }; do [[ ",$2," == *",$i,"* ]] || exit 1; done' _ "$term_ids" "$cg_ids"
  else
    echo "SKIP: Terminal window id == CGWindowID (set DS_LANE_TEST_TERMINAL_IDS=1 with Terminal running)"
  fi
fi
check "close raises the recorded front window after Cmd-W" osa_before "$close_run" 'keystroke "w"' 'set index of window id recFrontId to 1'
check "close raises no other window after Cmd-W" eq "$(printf '%s\n' "$close_run" | sed -n '/keystroke "w"/,$p' | grep -c 'set index of')" 1
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
open_in_pty t1 STUB_OSA_MODE=nine-fields
check "tab.log: output without the conductor window's tab is an error" contains "$(last_tab_line t1)" "tab error: unexpected osascript output 'ok|tab|0|42|"
open_in_pty t1 STUB_OSA_MODE=eleven-fields
check "tab.log: output without the conductor window's Space is an error" contains "$(last_tab_line t1)" "tab error: unexpected osascript output 'ok|tab|0|42|"
open_in_pty t1 STUB_OSA_MODE=bad-space
check "tab.log: a Space value other than on, off or unknown is an error" contains "$(last_tab_line t1)" "tab error: unexpected osascript output 'ok|tab|0|42|"
open_in_pty t1 STUB_OSA_MODE=offscreen
check "tab.log: conductor window not on this Space -> not raised, new window" eq "$(tail -n2 "$RUN/t1.tab.log" | tr '\n' '|')" "opened: window|conductor window not raised (not on screen in this Space: another Space, minimized or a background tab; new window used); focus: kept|"
check "open prints the not-on-this-Space fix" contains "$(cat "$TMP/open.out")" "fix: the conductor's Terminal window was not on screen in your current Space (it is on another Space, minimized, or a background tab of its window), so it was left where it is and the lane opened in a new window here. To get a tab instead, bring the conductor's tab to the front in your current Space and run \`ds-lane open t1\`."
check "open does not blame Accessibility for a window left on another Space" bash -c '! grep -q Accessibility "$1"' _ "$TMP/open.out"
open_in_pty t1 STUB_OSA_MODE=space-unknown
check "tab.log: Space query failed -> not raised, new window" eq "$(tail -n2 "$RUN/t1.tab.log" | tr '\n' '|')" "opened: window|conductor window not raised (could not tell whether it is on this Space; new window used); focus: kept|"
check "open prints the Space-query fix" contains "$(cat "$TMP/open.out")" "fix: the query for windows on your current Space failed, so the conductor's Terminal window was left where it is and the lane opened in a new window here. Retry with \`ds-lane open t1\`."
open_in_pty t1 STUB_OSA_MODE=notkept-cond
check "tab.log: focus NOT kept (conductor window's selected tab changed)" contains "$(last_tab_line t1)" "focus: NOT kept (front window 43, tab /dev/ttys900, app Terminal, conductor window tab /dev/ttys999; was 43, /dev/ttys900, Terminal, /dev/"
open_in_pty t1 STUB_OSA_MODE=native-other-front
check "tab.log: native tabs, another window in front, conductor reselected: focus kept" eq "$(tail -n2 "$RUN/t1.tab.log" | tr '\n' '|')" "opened: tab|focus: kept|"
open_in_pty t1 STUB_OSA_MODE=native-moved
check "tab.log: native tabs, front window not restored: focus NOT kept" contains "$(last_tab_line t1)" "focus: NOT kept (front window 52, tab /dev/ttys999, app Terminal, conductor window tab /dev/"
open_in_pty t1 STUB_OSA_MODE=notkept-window
check "tab.log: focus NOT kept (front window changed)" contains "$(last_tab_line t1)" "focus: NOT kept (front window 43, tab "
open_in_pty t1 STUB_OSA_MODE=notkept-tty
check "tab.log: focus NOT kept (selected tab changed)" contains "$(last_tab_line t1)" "focus: NOT kept (front window 42, tab /dev/ttys999, app Terminal, conductor window tab "
open_in_pty t1 STUB_OSA_MODE=notkept-app
check "tab.log: focus NOT kept (frontmost app changed)" contains "$(last_tab_line t1)" ", app Safari, conductor window tab "
open_in_pty t1 STUB_OSA_MODE=nomatch
check "tab.log: no matching tab" tab_line_is t1 "tab skipped: no matching tab"
open_in_pty t1 STUB_OSA_MODE=fail
check "tab.log: osascript exit 1" tab_line_is t1 "tab error: execution error: stub refused (-1743); focus: unknown"
check "open prints the Automation fix for an authorization error" contains "$(cat "$TMP/open.out")" "fix: macOS blocked the Apple event. Open System Settings > Privacy & Security > Automation, find the app this session runs in and allow it to control Terminal and System Events. If no entry is listed, run \`ds-lane open t1\` once and answer Allow when macOS asks."

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
check "close: window not on this Space" eq "$(close_tab close-offscreen)" "close skipped: window not on screen in this Space"
check "close: Space query failed" eq "$(close_tab close-spaceunknown)" "close skipped: Space unknown"
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

# --- tab outcome and fix printed by start/resume; doctor ---
ENV_BIN="$(command -v env)"
PY3="$(command -v python3)"
# Runs <command...> in a pty; stdout+stderr go to <outfile>, the exit status to <outfile>.rc.
pty_capture() { # pty_capture <outfile> <command...>
  local out="$1"; shift
  rm -f "$out" "$out.rc"
  run_in_pty "$TMP/pty.scratch" /bin/sh -c 'out="$1"; shift; "$@" > "$out" 2>&1; echo $? > "$out.rc"' sh "$out" "$@"
}
# Runs <command...> with no terminal on any ancestor (an orphan in its own session), cwd the
# primary checkout; same outputs as pty_capture.
cat > "$TMP/orphan.py" << 'PY'
import os, sys, time
cwd, out = sys.argv[1:3]
argv = sys.argv[3:]
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
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
os.dup2(fd, 1)
os.dup2(fd, 2)
pid = os.fork()
if pid == 0:
    os.execv(argv[0], argv)
_, st = os.waitpid(pid, 0)
with open(out + ".rc.tmp", "w") as f:
    f.write("%d\n" % (st >> 8))
os.rename(out + ".rc.tmp", out + ".rc")
PY
orphan_capture() { # orphan_capture <outfile> <absolute command...>
  local out="$1"; shift
  rm -f "$out" "$out.rc"
  "$PY3" "$TMP/orphan.py" "$PRIMARY" "$out" "$@"
  wait_until 30 test -s "$out.rc"
}
tab_of() { grep '^tab: ' "$1"; }
fix_of() { grep '^fix: ' "$1"; }
no_fix() { ! grep -q '^fix: ' "$1"; }
rc_of() { cat "$1.rc" 2> /dev/null; }

check "the test PATH resolves osascript to the stub, never the real one" eq "$(command -v osascript)" "$OSA_DIR/osascript"

SO="$TMP/start.out"
start_pty() { # start_pty <name> [env assignments...]
  local name="$1"; shift
  pty_capture "$SO" env DS_LANE_TAB_WAIT_S=10 "$@" "$TOOL" start "$name" "$PROMPT"
}

start_pty o1 STUB_OSA_MODE=kept
check "start: tab opened with focus kept" eq "$(tab_of "$SO")" "tab: opened: tab; focus: kept"
check "start: no fix line when the tab opened with focus kept" no_fix "$SO"
check "start: still prints the lane pid first" eq "$(head -n1 "$SO")" "$(cat "$RUN/o1.pid")"
start_rcs="o1=$(rc_of "$SO")"
lane stop o1 > /dev/null
out="$(lane resume o1 2>&1)"; rc=$?
check "resume: prints the tab line too" contains "$out" "tab: disabled (DS_LANE_NO_TAB=1)"
lane stop o1 > /dev/null

start_pty o2 STUB_OSA_MODE=nomatch
check "start: no matching tab" eq "$(tab_of "$SO")" "tab: tab skipped: no matching tab"
check "start: no matching tab -> run the conductor in Terminal.app or go tab-less" contains "$(fix_of "$SO")" "Run the conductor directly in Terminal.app (not another terminal app, an IDE terminal, tmux or SSH) to get tabs; until then the lane is running without a tab: follow it with \`ds-lane tail o2\`, and set DS_LANE_NO_TAB=1 to skip tabs."
start_rcs+=" o2=$(rc_of "$SO")"
check "start: lane launched with no matching tab" state_is o2 alive
lane stop o2 > /dev/null

start_pty o3 STUB_OSA_MODE=fail
check "start: authorization error" eq "$(tab_of "$SO")" "tab: tab error: execution error: stub refused (-1743); focus: unknown"
check "start: authorization error -> Automation settings path" contains "$(fix_of "$SO")" "fix: macOS blocked the Apple event. Open System Settings > Privacy & Security > Automation, find the app this session runs in and allow it to control Terminal and System Events. If no entry is listed, run \`ds-lane open o3\` once and answer Allow when macOS asks. Until then the lane is running without a tab: follow it with \`ds-lane tail o3\`"
start_rcs+=" o3=$(rc_of "$SO")"
check "start: lane launched despite the tab error" state_is o3 alive
lane stop o3 > /dev/null

start_pty o4 STUB_OSA_MODE=fail-other
check "start: other osascript error" eq "$(tab_of "$SO")" "tab: tab error: execution error: stub syntax error (-2741); focus: unknown"
check "start: other osascript error -> retry, not the consent wording" contains "$(fix_of "$SO")" "fix: the tab opener failed with the message above. Retry with \`ds-lane open o4\`"
lane stop o4 > /dev/null

start_pty o5 STUB_OSA_MODE=guard
check "start: new-window fallback" eq "$(tab_of "$SO")" "tab: opened: window; tab misplaced (new window, no new tab found); focus: kept"
check "start: new-window fallback -> Accessibility settings path" contains "$(fix_of "$SO")" "Open System Settings > Privacy & Security > Accessibility and turn on the app this session runs in; if it is not listed, add it with the + button. Later lanes then open as tabs."
start_rcs+=" o5=$(rc_of "$SO")"
lane stop o5 > /dev/null

orphan_capture "$SO" "$ENV_BIN" -u DS_LANE_NO_TAB "$TOOL" start o6 "$PROMPT"
check "start: no conductor tty" eq "$(tab_of "$SO")" "tab: tab skipped: no conductor tty"
check "start: no conductor tty -> headless session, use ds-lane tail" contains "$(fix_of "$SO")" "fix: this session has no terminal of its own (headless or bridge session), so tabs are unavailable here; the lane is running without a tab: follow it with \`ds-lane tail o6\`"
start_rcs+=" o6=$(rc_of "$SO")"
check "start: lane launched with no conductor tty" state_is o6 alive
lane stop o6 > /dev/null
check "start: exit 0 with a tab, no matching tab, a tab error, the new-window fallback and no conductor tty" eq "$start_rcs" "o1=0 o2=0 o3=0 o5=0 o6=0"

lane stop o3 > /dev/null
before_close="$(tab_lines o3)"
pty_capture "$SO" env DS_LANE_TAB_WAIT_S=10 STUB_OSA_MODE=close-first STUB_TAB_LOG="$RUN/o3.tab.log" "$TOOL" resume o3
check "the stub wrote a close line before the open outcome" eq "$(tail -n "+$((before_close + 1))" "$RUN/o3.tab.log" | head -n1)" "close skipped: tab busy"
check "resume: a close line from the previous watch tab is not reported as the outcome" eq "$(tab_of "$SO")" "tab: opened: tab; focus: kept"
lane stop o3 > /dev/null

out="$(lane start o7 "$PROMPT" 2>&1)"; rc=$?
check "start: DS_LANE_NO_TAB=1 says tabs are disabled" eq "$(printf '%s\n' "$out" | grep '^tab: ')" "tab: disabled (DS_LANE_NO_TAB=1)"
check "start: DS_LANE_NO_TAB=1 prints no fix and exits 0" eq "$rc|$(printf '%s\n' "$out" | grep -c '^fix: ')" "0|0"
lane stop o7 > /dev/null

rm -f "$LOG/osa-go"
t0=$SECONDS
pty_capture "$SO" env STUB_OSA_GATE=1 DS_LANE_TAB_WAIT_S=1 "$TOOL" start o8 "$PROMPT"
check "start: an opener that never answers is reported after the bounded wait" eq "$(tab_of "$SO")" "tab: unknown (no outcome after 1s)"
check "start: the wait is bounded (init 5s + tab 1s + slack)" test $((SECONDS - t0)) -lt 11
check "start: exit 0 and lane launched with the outcome unknown" eq "$(rc_of "$SO")|$(list_col o8 3)" "0|alive"
touch "$LOG/osa-go"
wait_until 15 has_file "$RUN/o8.tab.log"
lane stop o8 > /dev/null

# A leading zero must not be read as octal: 08 is a valid setting, and the opener answers at once.
start_pty o9 DS_LANE_TAB_WAIT_S=08 STUB_OSA_MODE=kept
check "start: DS_LANE_TAB_WAIT_S=08 is accepted" eq "$(rc_of "$SO")|$(tab_of "$SO")" "0|tab: opened: tab; focus: kept"
check "start: DS_LANE_TAB_WAIT_S=08 raises no arithmetic error" bash -c '! grep -qE "value too great|syntax error|invalid" "$1"' _ "$SO"
lane stop o9 > /dev/null

# doctor: every case runs on a hermetic PATH (stub uname and osascript, the symlink sandbox), so
# neither the host's tools nor its real osascript are reachable.
FAKEHOME="$TMP/home"
DOCBIN="$TMP/docbin"
mkdir -p "$FAKEHOME/.local/bin" "$TMP/home-nolink/.local/bin" "$DOCBIN"
ln -s "$TOOL" "$FAKEHOME/.local/bin/ds-lane"
printf '#!/bin/sh\necho "${STUB_UNAME:-Darwin}"\n' > "$DOCBIN/uname"
chmod +x "$DOCBIN/uname"
DOC_PATH="$FAKEHOME/.local/bin:$DOCBIN:$OSA_DIR:$SANDBOX"
check "the doctor PATH resolves osascript to the stub" eq "$("$ENV_BIN" PATH="$DOC_PATH" /bin/sh -c 'command -v osascript')" "$OSA_DIR/osascript"
check "the sandbox PATH has no osascript at all" eq "$("$ENV_BIN" PATH="$DOCBIN:$SANDBOX" /bin/sh -c 'command -v osascript')" ""
DO="$TMP/doctor.out"
doctor_env=(HOME="$FAKEHOME" PATH="$DOC_PATH" TERM_PROGRAM=Apple_Terminal STUB_UNAME=Darwin)
doctor_pty() { # doctor_pty [env assignments...]; an empty value unsets as far as the tool can tell
  pty_capture "$DO" "$ENV_BIN" "${doctor_env[@]}" "$@" "$TOOL" doctor
}
doc_has() { grep -qF -- "$1" "$DO"; }
fix_after() { # fix_after <line prefix>: the line following the first line that starts with it
  awk -v p="$1" 'found { print; exit } index($0, p) == 1 { found = 1 }' "$DO"
}
TABLESS='lanes still run without tabs: start them with DS_LANE_NO_TAB=1 and follow each with `ds-lane tail <name>`'
rm -f "$LOG"/osa-*

doctor_pty
check "doctor all-ok: exit 0" eq "$(rc_of "$DO")" 0
check "doctor all-ok: no FAIL line" bash -c '! grep -q "^FAIL" "$1"' _ "$DO"
check "doctor all-ok: the eight checkable lines are ok" eq "$(grep -c '^ok ' "$DO")" 8
check "doctor all-ok: macOS" doc_has "ok         platform: macOS"
check "doctor all-ok: claude resolved as start resolves it" doc_has "ok         claude: $STUB/claude"
check "doctor all-ok: ds-lane found on PATH" doc_has "ok         ds-lane on PATH: $FAKEHOME/.local/bin/ds-lane"
check "doctor all-ok: Terminal.app" doc_has "ok         Terminal.app: TERM_PROGRAM=Apple_Terminal"
check "doctor: Automation consent is unverified, with the settings path" contains "$(fix_after 'unverified Automation consent: unverified until first tab open')" "open System Settings > Privacy & Security > Automation, find the app the conductor runs in and allow it to control Terminal and System Events; an entry appears there only after macOS has asked once."
check "doctor: Accessibility consent is unverified, with the settings path" contains "$(fix_after 'unverified Accessibility consent: unverified until first tab open')" "open System Settings > Privacy & Security > Accessibility and turn on the app the conductor runs in; if it is not listed, add it with the + button."
check "doctor all-ok: tabs unverified, never claimed working" doc_has "tabs: unverified (no check failed;"
check "doctor all-ok: launch offer available" eq "$(tail -n2 "$DO" | head -n1)" "launch offer: available (ds-lane is on PATH)"
check "doctor all-ok: last line says lanes run headless" eq "$(tail -n1 "$DO")" "headless lanes: available (claude, python3 and jq resolve; $TABLESS)"

doctor_pty STUB_UNAME=Linux
check "doctor non-macOS: exit 1" eq "$(rc_of "$DO")" 1
check "doctor non-macOS: platform FAIL with the tab-less path" eq "$(fix_after 'FAIL       platform: Linux; watch tabs open only in macOS Terminal.app')" "           fix: Tabs cannot open on this platform; $TABLESS."
check "doctor non-macOS: tabs unavailable, lanes still headless" eq "$(tail -n3 "$DO" | cut -c1-25 | tr '\n' '|')" "tabs: unavailable (1 chec|launch offer: available (|headless lanes: available|"

doctor_pty PATH="$FAKEHOME/.local/bin:$DOCBIN:$SANDBOX"
check "doctor no osascript: exit 1" eq "$(rc_of "$DO")" 1
check "doctor no osascript: FAIL names where it ships" contains "$(fix_after 'FAIL       osascript: not found on PATH')" "fix: osascript ships with macOS at /usr/bin/osascript: put /usr/bin on this session's PATH; until then $TABLESS."

doctor_pty DS_LANE_CLAUDE_BIN=
check "doctor no claude: exit 1" eq "$(rc_of "$DO")" 1
check "doctor no claude: FAIL says how to point at it" contains "$(fix_after 'FAIL       claude: not found (DS_LANE_CLAUDE_BIN, PATH, CLAUDE_CODE_EXECPATH)')" "set DS_LANE_CLAUDE_BIN to the full path of the claude executable; no lane can start without it."
check "doctor no claude: lanes cannot run headless either" eq "$(tail -n1 "$DO")" "headless lanes: unavailable (claude, python3 and jq must all resolve)"

doctor_pty PATH="$DOCBIN:$OSA_DIR:$SANDBOX"
check "doctor ~/.local/bin off PATH: exit 1" eq "$(rc_of "$DO")" 1
check "doctor ~/.local/bin off PATH: tabs are not called unavailable, the launch offer is" eq "$(tail -n3 "$DO" | head -n2 | sed 's/ (.*//' | tr '\n' '|')" "tabs: unverified|launch offer: unavailable: ds-lane not on PATH|"
path_fix="$(fix_after 'FAIL       ds-lane on PATH: not found on PATH (~/.local/bin is not on PATH)')"
check "doctor ~/.local/bin off PATH: fix names ds-doctor --fix and the export line" contains "$path_fix" "Run \`$(dirname "$TOOL_REAL")/ds-doctor --fix\`, then add this line to your shell profile (~/.zshrc for zsh, the macOS default; ~/.bash_profile for bash) and start a new terminal and session: export PATH=\"\$HOME/.local/bin:\$PATH\""
# The printed export line is pasted into the operator's shell profile: it must work in both shells.
export_line="export PATH=${path_fix##*export PATH=}"
check "the printed export line puts ds-lane on PATH under bash" eq "$("$ENV_BIN" HOME="$FAKEHOME" PATH="$SANDBOX" "$SANDBOX/bash" -c "$export_line; command -v ds-lane" 2>&1)" "$FAKEHOME/.local/bin/ds-lane"
if (( HAVE_ZSH )); then
  check "the printed export line puts ds-lane on PATH under zsh" eq "$("$ENV_BIN" HOME="$FAKEHOME" PATH="$SANDBOX" "$(command -v zsh)" -f -c "$export_line; command -v ds-lane" 2>&1)" "$FAKEHOME/.local/bin/ds-lane"
else
  echo "SKIP: zsh not found; zsh half of the export-line case not run"
fi
doctor_pty HOME="$TMP/home-nolink" PATH="$TMP/home-nolink/.local/bin:$DOCBIN:$OSA_DIR:$SANDBOX"
check "doctor ~/.local/bin on PATH without the link: fix is ds-doctor --fix alone" eq "$(fix_after 'FAIL       ds-lane on PATH: not found on PATH (~/.local/bin is on PATH but holds no ds-lane)')" "           fix: Run \`$(dirname "$TOOL_REAL")/ds-doctor --fix\` to create the ~/.local/bin links; a session offers to launch lanes only when ds-lane is on PATH."

orphan_capture "$DO" "$ENV_BIN" "${doctor_env[@]}" "$TOOL" doctor
check "doctor no conductor tty: exit 1" eq "$(rc_of "$DO")" 1
check "doctor no conductor tty: FAIL with the tab-less path" eq "$(fix_after 'FAIL       conductor terminal: no ancestor process has a terminal (headless, bridge or IDE-spawned session)')" "           fix: Tabs open only beside a conductor session running in a macOS Terminal.app tab; in this session $TABLESS."

doctor_pty TERM_PROGRAM=iTerm.app
check "doctor other terminal app: exit 1" eq "$(rc_of "$DO")" 1
check "doctor other terminal app: FAIL names the observed app and Terminal.app" contains "$(fix_after 'FAIL       Terminal.app: TERM_PROGRAM=iTerm.app; tabs open only beside a conductor running directly in macOS Terminal.app')" "fix: Run the conductor session directly in macOS Terminal.app"
doctor_pty TERM_PROGRAM=
check "doctor unknown terminal app: unverified, not guessed, exit 0" eq "$(rc_of "$DO")|$(grep -c '^unverified Terminal.app: TERM_PROGRAM is not set' "$DO")" "0|1"

pty_capture "$DO" "$ENV_BIN" "${doctor_env[@]}" "$TOOL" doctor --json
check "doctor --json all-ok: parses, exit 0, tabs unverified, every non-ok check carries a fix" eq "$(rc_of "$DO")|$(jq -r '[.tabs, .launch_offer, .headless, (.checks | length), (all(.checks[]; .status != "FAIL")), (all(.checks[]; (.status == "ok") == (.fix == "")))] | join(",")' "$DO" 2>&1)" "0|unverified,true,true,10,true,true"
pty_capture "$DO" "$ENV_BIN" "${doctor_env[@]}" STUB_UNAME=Linux DS_LANE_CLAUDE_BIN= "$TOOL" doctor --json
check "doctor --json failing: parses, exit 1, tabs unavailable, not headless" eq "$(rc_of "$DO")|$(jq -r '[.tabs, .headless, ([.checks[] | select(.status == "FAIL") | .check] | join("+"))] | join(",")' "$DO" 2>&1)" "1|unavailable,false,platform+claude"
pty_capture "$DO" "$ENV_BIN" "${doctor_env[@]}" PATH="$DOCBIN:$OSA_DIR:$SANDBOX" "$TOOL" doctor --json
check "doctor --json ds-lane off PATH: exit 1, tabs unverified, launch offer false" eq "$(rc_of "$DO")|$(jq -r '[.tabs, .launch_offer, .headless] | join(",")' "$DO" 2>&1)" "1|unverified,false,true"
# No pty: JSON validity does not depend on a terminal, and a pty wrapper would requote the value.
out="$("$ENV_BIN" "${doctor_env[@]}" TERM_PROGRAM=$'a\tb\001"c\\\nd' "$TOOL" doctor --json 2> /dev/null)"
check "doctor --json stays valid with control characters, quotes and backslashes in a value" eq "$(printf '%s\n' "$out" | jq -r '.checks[] | select(.check == "Terminal.app") | .detail | startswith("TERM_PROGRAM=a\tb\"c\\\nd; tabs")' 2>&1)" "true"
out="$(cd "$TMP/norepo" && GIT_CEILING_DIRECTORIES="$TMP" "$ENV_BIN" "${doctor_env[@]}" "$TOOL" doctor 2>&1)"
check "doctor runs outside a git repo" contains "$out" "ok         platform: macOS"
check "doctor never ran osascript (no Apple event, no consent prompt)" eq "$(ls "$LOG" | grep -c '^osa-')" 0

echo "ds-lane tests: $PASS passed, $FAIL failed"
(( FAIL == 0 ))
