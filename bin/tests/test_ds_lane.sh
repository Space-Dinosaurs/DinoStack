#!/usr/bin/env bash
# Purpose: Regression suite for bin/ds-lane. Drives the real tool against a
#          scratch git repo (path contains a space) with a stub `claude`
#          (run as `exec -a claude /bin/bash claude-stub.sh` so the tool's
#          argv[0] liveness check accepts it) and a stub `osascript` whose
#          reply is chosen by STUB_OSA_MODE. Never launches a real claude
#          session and never runs AppleScript against Terminal.
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
#               The only path outside it is the tool's fixed tab lock
#               /tmp/ds-lane-tab-<uid>.lock, created by the lock-busy case
#               only when absent and removed afterwards.

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
TAB_LOCK="/tmp/ds-lane-tab-$(id -u).lock"
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
printf '#!/bin/bash\nexec -a claude /bin/bash %q "$@"\n' "$STUB/claude-stub.sh" > "$STUB/claude"
chmod +x "$STUB/claude"

cat > "$OSA_DIR/osascript" << 'EOF'
#!/bin/bash
# argv: -e <script> <command> <conductor tty>
printf '%s' "$2" > "$STUB_LOG_DIR/osa-script"
printf '%s' "$3" > "$STUB_LOG_DIR/osa-cmd"
printf '%s' "$4" > "$STUB_LOG_DIR/osa-tty"
if [ "${STUB_OSA_GATE:-}" = 1 ]; then
  n=0
  while [ ! -e "$STUB_LOG_DIR/osa-go" ] && [ $n -lt 100 ]; do sleep 0.1; n=$((n + 1)); done
  [ -e "$STUB_LOG_DIR/osa-go" ] || { echo "gate never opened" >&2; exit 1; }
fi
case "${STUB_OSA_MODE:-kept}" in
  kept) echo "ok|tab|42|$4|Terminal|42|$4|Terminal" ;;
  guard) echo "ok|window|42|$4|Terminal|42|$4|Terminal" ;;
  notkept-window) echo "ok|tab|43|$4|Terminal|42|$4|Terminal" ;;
  notkept-tty) echo "ok|tab|42|/dev/ttys999|Terminal|42|$4|Terminal" ;;
  notkept-app) echo "ok|tab|42|$4|Safari|42|$4|Terminal" ;;
  nomatch) echo "nomatch" ;;
  fail) echo "execution error: stub refused (-1743)" >&2; echo "second line" >&2; exit 1 ;;
esac
EOF
chmod +x "$OSA_DIR/osascript"

export PATH="$OSA_DIR:$PATH"
export STUB_LOG_DIR="$LOG"
export DS_LANE_CLAUDE_BIN="$STUB/claude"
export DS_LANE_PERMISSION_MODE=bypassPermissions
export DS_LANE_TAB_LOCK_WAIT_S=1
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
check "help lists all 13 commands" eq "$help_cmds" "start send close reap resume list tail watch open open-all stop resume-hint count "
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

osa_script="$(cat "$LOG/osa-script")"
check "AppleScript sends do script exactly twice" eq "$(printf '%s\n' "$osa_script" | grep -c 'do script')" 2
check "do script into the new tab only behind the tty guard" eq "$(printf '%s\n' "$osa_script" | grep -B1 'do script theCmd in newTab' | head -n1 | tr -s ' ')" " if tty of newTab is not condTty then"
check "guard-tripped branch opens a new window" eq "$(printf '%s\n' "$osa_script" | grep -A3 'do script theCmd in newTab' | sed -n 3,4p | tr -s ' ')" " else
 do script theCmd"
if command -v osacompile > /dev/null 2>&1; then
  check "open AppleScript compiles" osacompile -o "$TMP/open.scpt" "$LOG/osa-script"
  sed -n "/^CLOSE_TAB_OSA='/,/^end run'/p" "$TOOL" | sed -e "1s/^CLOSE_TAB_OSA='//" -e "\$s/'\$//" > "$TMP/close.applescript"
  check "close AppleScript compiles" osacompile -o "$TMP/close.scpt" "$TMP/close.applescript"
fi

open_in_pty t1 STUB_OSA_MODE=guard
check "tab.log: guard tripped -> new window, focus kept" eq "$(tail -n2 "$RUN/t1.tab.log" | tr '\n' '|')" "opened: window|focus: kept|"
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

if [[ -e "$TAB_LOCK" ]]; then
  echo "SKIP: $TAB_LOCK already exists; lock-busy case not run"
else
  mkdir "$TAB_LOCK" && echo "$$" > "$TAB_LOCK/pid"
  open_in_pty t1 DS_LANE_TAB_LOCK_WAIT_S=1
  check "tab.log: lock busy" tab_line_is t1 "tab skipped: lock busy"
  rm -f "$TAB_LOCK/pid"
  rmdir "$TAB_LOCK"
fi
lane stop t1 > /dev/null

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
