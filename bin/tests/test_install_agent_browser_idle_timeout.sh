#!/usr/bin/env bash
# Purpose: Drive the real .claude/install.sh against a scratch HOME and assert
#          that the agent-browser daemon idle timeout it writes lands in an
#          EXISTING env object without disturbing anything else in the file
#          (DS-254 U8).
#
#          The property under test is preservation, not insertion. The
#          operator's ~/.claude/settings.json already holds an operator-owned
#          env object (measured: DISABLE_AUTOUPDATER) inside a file with more
#          than a dozen top-level keys, so the two destructive shapes - replace
#          the env object, replace the document - each silently drop values the
#          operator put there. A case that only checks the new key arrived
#          cannot see either, so every case here asserts what SURVIVED.
#
#          The cases, each a separate run:
#            A1 - a settings.json carrying DISABLE_AUTOUPDATER plus three
#                 sibling top-level keys, operator accepts -> env gains exactly
#                 one key and holds both, every sibling key is unchanged, no
#                 top-level key appears beyond the hook block the installer
#                 already writes, and the cost of accepting (a long-idle QA run
#                 loses its browser session) is printed BEFORE the prompt that
#                 asks for it
#            A2 - the same file, operator declines -> the key is absent and the
#                 operator's own env value is intact
#            A3 - a settings.json whose key is already set to a RAISED value
#                 -> no prompt at all and the operator's number is left as it
#                 is. Rewriting it back to the default would make the
#                 documented way back ("raise it") a lie
#            B1 - the extracted writer on a canonical fixture -> the file on
#                 disk is byte-for-byte a re-serialization of the same document
#                 with the one key added, the non-ASCII sibling value is not
#                 re-encoded as \uXXXX escapes, the file's mode is carried over
#                 from the operator's file rather than narrowed to mkstemp's
#                 0600, and no temp file is left behind
#            B2 - env is not a JSON object -> refused by name, file
#                 byte-identical, no traceback
#            B3 - the top level is not a JSON object -> refused by name, file
#                 byte-identical
#            B4 - the file rewritten from another process inside the writer's
#                 write window -> the writer refuses, names the key to set by
#                 hand, and the other writer's content survives
#            B5 - the writer killed inside its write window -> the operator's
#                 file is still byte-identical, because the write lands in a
#                 temp file and os.replace rather than truncating the target
#
#          Mutation coverage (each mutation is run, not merely named):
#            (a) replace the env object instead of setting into it -> A1 and
#                B1 redden. Driven at both levels on purpose: the writer case
#                is cheap and the installer case is the one the ticket is
#                about
#            (b) disable the top-level object guard   -> B3 reddens
#            (c) disable the env-object guard         -> B2 reddens
#            (d) disable the pre-rename re-stat guard -> B4 reddens
#            (e) make the write land in the target in place rather than in a
#                temp file -> B5 reddens
#            (f) drop ensure_ascii=False              -> B1 reddens
#            (g) classify an already-set key as absent -> A3 reddens
#            (h) ignore the ae_confirm answer (write either way) -> A2 reddens
#            (i) drop the mode carry-over             -> B1 reddens
#            (j) drop the cost sentence printed before the accept prompt -> A1
#                reddens
#          A mutation is a full copy of .claude/install.sh, so it must live in
#          .claude/ too (REPO_DIR is derived from the script's own path). Those
#          copies are removed by the exit trap.
#
#          The ae_confirm prompt reads /dev/tty, so the installer cases run
#          under a real pseudo-terminal (python3 pty.fork) with the answer
#          written once the prompt text is observed. Every other prompt in
#          install.sh is seeded away (Seeds 1-4 below), so exactly one prompt is
#          live per installer case. Seed 5 is what suppresses the prompt in a
#          case that must NOT reach it: it seeds the key itself.
#
# Public API: ./bin/tests/test_install_agent_browser_idle_timeout.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3 (pty), git, node (transitively, via build.sh),
#                mktemp.
#
# Downstream consumers: developer running locally before commit; CI (the
#                       bin/tests/test_*.sh glob in
#                       .github/workflows/bin-tests.yml).
#
# Failure modes: any assertion failure prints the failing assertion and exits
#                1. A temporary fake HOME is used; the real ~/.claude and
#                ~/.claude.json are never touched. A faked $HOME without the
#                git shim below can escape its sandbox and mutate the live
#                primary checkout's pre-commit hook symlink - see Seed 6.
#
# Performance: 7 install runs (three cases plus four installer-level mutation
#              runs), ~50 s on a warm tree. Every other case runs the extracted
#              writer directly, at negligible cost, as do the writer halves of
#              (b)-(f) and (i).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_DIR/.claude/install.sh"
MUTATION_GLOB="$REPO_DIR/.claude/.mutation-install-$$-*"

IDLE_KEY="AGENT_BROWSER_IDLE_TIMEOUT_MS"
IDLE_DEFAULT="1800000"
PROMPT_NEEDLE="Set $IDLE_KEY in"
COST_NEEDLE="loses its browser session mid-run"

PASS=0
FAIL=0

_fail() {
  echo "FAIL: $1" >&2
  FAIL=$((FAIL + 1))
}

_pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

# run_case <label> <case-fn> <install-script>
# The case runs in a subshell so its `out`/`rc` cannot leak; the verdict is
# counted here, in the parent, because a counter incremented inside a subshell
# never reaches the harness total.
run_case() {
  local label="$1" fn="$2" script="$3"
  if ( "$fn" "$script" ); then
    _pass "$label"
  else
    _fail "$label"
  fi
}

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  rm -rf "$TMP_ROOT"
  rm -f $MUTATION_GLOB
}
trap _cleanup EXIT INT TERM
rm -f $MUTATION_GLOB

FAKE_BIN="$TMP_ROOT/fakebin"
mkdir -p "$FAKE_BIN"

# ---------------------------------------------------------------------------
# Seed 3: no-op executables for the five CLI_TOOLS on PATH, so `command -v`
# succeeds for each and no "Install <tool>?" prompt fires.
# ---------------------------------------------------------------------------
for tool in gh agent-browser lc jira rclone; do
  cat > "$FAKE_BIN/$tool" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$FAKE_BIN/$tool"
done

# ---------------------------------------------------------------------------
# Seed 6 (git-level sandbox): running the real .claude/install.sh from an
# isolation worktree calls scripts/lib/precommit.sh's resolve_git_hooks_dir(),
# which shells out to `git -C "$REPO_DIR" rev-parse --git-path hooks`. From a
# worktree that resolves to the primary checkout's common .git/hooks dir, so an
# unsandboxed run re-points the live primary checkout's .git/hooks/pre-commit
# symlink at this disposable worktree. The shim is copied verbatim from
# bin/tests/test_install_worktree_read_guard.sh, which every sibling installer
# suite shares.
# ---------------------------------------------------------------------------
REAL_GIT="$(command -v git)"
SCRATCH_HOOKS_DIR="$TMP_ROOT/scratch-git-hooks"
mkdir -p "$SCRATCH_HOOKS_DIR"
cat > "$FAKE_BIN/git" <<EOF
#!/usr/bin/env bash
joined=" \$* "
if [[ "\$joined" == *" rev-parse "* && "\$joined" == *" --git-path "* && "\$joined" == *" hooks"* ]]; then
  echo "$SCRATCH_HOOKS_DIR"
  exit 0
fi
exec "$REAL_GIT" "\$@"
EOF
chmod +x "$FAKE_BIN/git"

export AE_TEST_PATH="$FAKE_BIN:$PATH"

AMBIENT_HOOKS_DIR="$("$REAL_GIT" -C "$REPO_DIR" rev-parse --git-path hooks 2>/dev/null)"
case "$AMBIENT_HOOKS_DIR" in
  /*) : ;;
  *) AMBIENT_HOOKS_DIR="$REPO_DIR/$AMBIENT_HOOKS_DIR" ;;
esac
AMBIENT_PRECOMMIT="$AMBIENT_HOOKS_DIR/pre-commit"
AMBIENT_PRECOMMIT_BEFORE=""
if [[ -L "$AMBIENT_PRECOMMIT" ]]; then
  AMBIENT_PRECOMMIT_BEFORE="$(readlink "$AMBIENT_PRECOMMIT")"
fi

# ---------------------------------------------------------------------------
# The fixture document. Three sibling top-level keys beyond env, so "everything
# else survived" is a real assertion rather than an empty one, and a non-ASCII
# value, so a whole-file re-encoding shows up as a byte difference. Written
# through python rather than a heredoc so the bytes are exactly what a
# canonical re-serialization of the same document produces, which is what makes
# the byte-identity comparison below meaningful.
#
# write_settings_fixture <path> <idle-value|"">
# write_settings_expected <path> <idle-value>
# ---------------------------------------------------------------------------
write_settings_fixture() {
  python3 - "$1" "$2" <<'PYEOF'
import json, sys

path, idle = sys.argv[1], sys.argv[2]
doc = {
    "numStartups": 7,
    "statusLineText": "café · waiting",
    "env": {"DISABLE_AUTOUPDATER": "1"},
    "permissions": {"defaultMode": "bypassPermissions"},
    "projects": {"/tmp/example": {"history": [{"display": "hello"}]}},
}
if idle:
    doc["env"]["AGENT_BROWSER_IDLE_TIMEOUT_MS"] = idle
with open(path, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2, ensure_ascii=False)
    f.write("\n")
PYEOF
}

write_settings_expected() {
  python3 - "$1" "$2" <<'PYEOF'
import json, sys

path, value = sys.argv[1], sys.argv[2]
doc = {
    "numStartups": 7,
    "statusLineText": "café · waiting",
    "env": {"DISABLE_AUTOUPDATER": "1", "AGENT_BROWSER_IDLE_TIMEOUT_MS": value},
    "permissions": {"defaultMode": "bypassPermissions"},
    "projects": {"/tmp/example": {"history": [{"display": "hello"}]}},
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2, ensure_ascii=False)
    f.write("\n")
PYEOF
}

# ---------------------------------------------------------------------------
# seed_home <home> <idle-value|"">
# Seeds 1, 2, 4 and 5, the prompt-suppression seeds that live under $HOME.
#   Seed 1: agentic-engineering.json carrying skill_auto_load -> suppresses
#           ae_write_mode's /dev/tty prompt (gated on the key being absent).
#   Seed 2: ~/.claude.json with both MCP servers already configured -> the
#           chrome-devtools entry must classify CURRENT (it names the package
#           and carries both flags the migration writes), not merely exist.
#   Seed 4: settings.json with permissions.defaultMode already
#           bypassPermissions -> suppresses the permissions tty_input prompt.
#   Seed 5: the idle-timeout key, when <idle-value> is non-empty -> suppresses
#           the agent-browser prompt, which is how an installer case that is not
#           ABOUT that prompt keeps zero live prompts.
# ---------------------------------------------------------------------------
seed_home() {
  local home="$1" idle="${2:-}"
  mkdir -p "$home/.claude"
  printf '{"skill_auto_load": false}\n' > "$home/.claude/agentic-engineering.json"
  cat > "$home/.claude.json" <<'EOF'
{"mcpServers":{"chrome-devtools":{"type":"stdio","command":"npx","args":["chrome-devtools-mcp@latest","--headless","--isolated"],"env":{}},"mcp-atlassian":{}}}
EOF
  write_settings_fixture "$home/.claude/settings.json" "$idle"
}

# ---------------------------------------------------------------------------
# run_install <install-script> <home> <answers-json>
#   answers-json: [[<output needle>, <answer>], ...] - each answer is written
#   to the pty once its own needle has appeared in the install's output, so no
#   stray character can reach a prompt that has not appeared yet.
# Prints the combined install output and exits with the installer's status.
# ---------------------------------------------------------------------------
run_install() {
  local script="$1" home="$2" answers="$3"
  python3 - "$script" "$home" "$answers" <<'PYEOF'
import json, os, pty, select, sys, time

script, home, answers_json = sys.argv[1:4]
answers = [(n.encode(), a.encode()) for n, a in json.loads(answers_json)]

cmd = [
    "env",
    "-u", "AGENTIC_CONFIG_DIR", "-u", "CLAUDE_CONFIG_DIR",
    "-u", "CODEX_HOME", "-u", "PI_CODING_AGENT_DIR",
    "PATH=" + os.environ["AE_TEST_PATH"],
    "HOME=" + home,
    "bash", script, "--mode=opt-out", "--profile=default", "--no-identity",
]

pid, master = pty.fork()
if pid == 0:
    try:
        os.execvp(cmd[0], cmd)
    except OSError:
        os._exit(127)

out = bytearray()
answered = set()
eof = False
reaped = None
started = time.time()
deadline = started + 300

while not eof and time.time() < deadline:
    try:
        ready = select.select([master], [], [], 0.25)[0]
    except OSError:
        eof = True
        break
    if ready:
        try:
            chunk = os.read(master, 65536)
        except OSError:
            eof = True
            break
        if chunk:
            out += chunk
        else:
            eof = True
            break
    else:
        done, st = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            reaped = st
            eof = True
            break
    for needle, answer in answers:
        if needle not in answered and needle in out:
            try:
                os.write(master, answer)
            except OSError:
                pass
            answered.add(needle)

# The pty reaches EOF a moment before the process is reapable - it closes the
# slave, then finishes exiting - so a single WNOHANG sample here reports a
# completed install as a timeout on a loaded machine. Poll for a bounded grace
# period instead, so only a process that really is stuck is ever killed.
grace = time.time() + 30
while reaped is None and time.time() < grace:
    done, st = os.waitpid(pid, os.WNOHANG)
    if done == pid:
        reaped = st
    else:
        time.sleep(0.05)

timed_out = reaped is None
if timed_out:
    os.kill(pid, 9)
    os.waitpid(pid, 0)

# The install can write its last line and exit inside the 0.25 s window of a
# not-ready select, so the loop can break with those bytes still unread in the
# pty buffer. Without this drain an assertion on the installer's final message
# fails intermittently on a loaded machine.
while True:
    try:
        if not select.select([master], [], [], 0)[0]:
            break
        chunk = os.read(master, 65536)
    except OSError:
        break
    if not chunk:
        break
    out += chunk

sys.stdout.write(out.decode("utf-8", "replace"))
elapsed = time.time() - started
if timed_out:
    sys.stderr.write(
        "\n[pty driver] install did not finish within %ds (%.1fs elapsed)\n"
        % (int(deadline - started), elapsed))
    sys.exit(124)
if elapsed > 30:
    sys.stderr.write("\n[pty driver] install took %.1fs\n" % elapsed)
if os.WIFEXITED(reaped):
    sys.exit(os.WEXITSTATUS(reaped))
sys.exit(128 + os.WTERMSIG(reaped))
PYEOF
}

# ---------------------------------------------------------------------------
# A1: the operator's file gains the key and loses nothing else.
# ---------------------------------------------------------------------------
case_install_preserves_siblings() {
  local script="$1" out rc
  local home="$TMP_ROOT/a1-home"
  mkdir -p "$home"
  seed_home "$home" ""
  cp "$home/.claude/settings.json" "$TMP_ROOT/a1-before.json"

  out="$(run_install "$script" "$home" "[[\"$PROMPT_NEEDLE\", \"y\n\"]]")"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "A1: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi

  if ! grep -qF "$PROMPT_NEEDLE" <<< "$out"; then
    _fail "A1: the idle-timeout prompt was never reached"
    return 1
  fi
  if ! grep -qF "$COST_NEEDLE" <<< "$out"; then
    _fail "A1: the capability this change removes was never stated"
    return 1
  fi
  # Ordering is the load-bearing half: the same sentence printed after the
  # prompt would not inform the decision the prompt asks for.
  local cost_at prompt_at
  cost_at="$(grep -nF "$COST_NEEDLE" <<< "$out" | head -1 | cut -d: -f1)"
  prompt_at="$(grep -nF "$PROMPT_NEEDLE" <<< "$out" | head -1 | cut -d: -f1)"
  if [[ -z "$cost_at" || -z "$prompt_at" || "$cost_at" -ge "$prompt_at" ]]; then
    _fail "A1: the cost and its way back are not stated before the accept prompt"
    return 1
  fi
  if ! grep -qF "agent-browser daemon idle timeout set in" <<< "$out"; then
    _fail "A1: the accepted write was not reported"
    return 1
  fi

  # The destructive shapes this case exists to catch: replacing the env object
  # drops DISABLE_AUTOUPDATER, replacing the document drops the siblings.
  python3 - "$TMP_ROOT/a1-before.json" "$home/.claude/settings.json" "$IDLE_DEFAULT" <<'PYEOF'
import json, sys

before = json.load(open(sys.argv[1], encoding="utf-8"))
after = json.load(open(sys.argv[2], encoding="utf-8"))
expected_value = sys.argv[3]

assert after["env"] == {
    "DISABLE_AUTOUPDATER": "1",
    "AGENT_BROWSER_IDLE_TIMEOUT_MS": expected_value,
}, after["env"]
# A value rather than a number: Claude Code's env map is strings, and a bare
# number there is not the type the harness reads.
assert isinstance(after["env"]["AGENT_BROWSER_IDLE_TIMEOUT_MS"], str), \
    after["env"]["AGENT_BROWSER_IDLE_TIMEOUT_MS"]
for key in ("numStartups", "statusLineText", "projects"):
    assert after[key] == before[key], (key, after[key], before[key])
# "Only the new key added" stated as a set difference. "hooks" is the block the
# installer already wired before this change - it is the one top-level key a
# run is allowed to introduce here, and asserting it explicitly is what keeps
# this from being a subset check in disguise.
assert set(after) - set(before) == {"hooks"}, set(after) - set(before)
assert not set(before) - set(after), set(before) - set(after)
PYEOF
  if [[ $? -ne 0 ]]; then
    _fail "A1: accepting the write dropped or added a top-level value the operator owned"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# A2: declining writes nothing at all.
# ---------------------------------------------------------------------------
case_install_declined() {
  local script="$1" out rc
  local home="$TMP_ROOT/a2-home"
  mkdir -p "$home"
  seed_home "$home" ""

  out="$(run_install "$script" "$home" "[[\"$PROMPT_NEEDLE\", \"n\n\"]]")"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "A2: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! grep -qF "$PROMPT_NEEDLE" <<< "$out"; then
    _fail "A2: the idle-timeout prompt was never reached"
    return 1
  fi
  if grep -qF "$IDLE_KEY" "$home/.claude/settings.json"; then
    _fail "A2: the declined key was written anyway"
    return 1
  fi
  if ! grep -qF "skipped the agent-browser daemon idle timeout" <<< "$out"; then
    _fail "A2: the decline was not reported"
    return 1
  fi
  python3 - "$home/.claude/settings.json" <<'PYEOF'
import json, sys
after = json.load(open(sys.argv[1], encoding="utf-8"))
assert after["env"] == {"DISABLE_AUTOUPDATER": "1"}, after["env"]
PYEOF
  if [[ $? -ne 0 ]]; then
    _fail "A2: declining altered the operator's own env value"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# A3: an operator-raised value is left alone and never re-asked.
# ---------------------------------------------------------------------------
case_install_already_set() {
  local script="$1" out rc
  local home="$TMP_ROOT/a3-home"
  mkdir -p "$home"
  seed_home "$home" "900000"

  out="$(run_install "$script" "$home" "[[\"$PROMPT_NEEDLE\", \"y\n\"]]")"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "A3: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if grep -qF "$PROMPT_NEEDLE" <<< "$out"; then
    _fail "A3: a key that is already set was offered the prompt again"
    return 1
  fi
  if ! grep -qF "agent-browser daemon idle timeout already set" <<< "$out"; then
    _fail "A3: the already-set state was not reported"
    return 1
  fi
  python3 - "$home/.claude/settings.json" <<'PYEOF'
import json, sys
after = json.load(open(sys.argv[1], encoding="utf-8"))
assert after["env"] == {
    "DISABLE_AUTOUPDATER": "1",
    "AGENT_BROWSER_IDLE_TIMEOUT_MS": "900000",
}, after["env"]
PYEOF
  if [[ $? -ne 0 ]]; then
    _fail "A3: the operator's raised value was rewritten"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# The extracted writer. The installer cases above prove the end-to-end
# behaviour; these drive the block that actually performs the write, so the
# byte-level and refusal properties are held to account without an install run
# per case - and so a guard the installer's classifier already intercepted is
# still exercised, which is what would matter if the file changed between the
# classifier's read and the writer's.
# ---------------------------------------------------------------------------
# extract_writer <source-install-sh> <output.py>
extract_writer() {
  awk '
    /^import json, os, sys, tempfile$/ { f=1 }
    f && /^PYEOF$/ { exit }
    f { print }
  ' "$1" > "$2"
  if ! grep -qF 'env["AGENT_BROWSER_IDLE_TIMEOUT_MS"] = value' "$2" ||
    ! grep -qF 'os.replace(tmp_path, target)' "$2"; then
    _fail "could not extract the shipped idle-timeout writer block from $1 (anchor line moved?)"
    return 1
  fi
  if ! python3 -c 'import sys; compile(open(sys.argv[1]).read(), sys.argv[1], "exec")' "$2"; then
    _fail "the extracted idle-timeout writer block from $1 is not valid Python"
    return 1
  fi
  return 0
}

# inject_delay <source.py> <output.py>
# Holds the write window open on the way to the pre-rename re-stat: the temp
# file is written and the target is still untouched, which is exactly the window
# B4 rewrites through and B5 kills inside.
inject_delay() {
  awk '
    /^import json, os, sys, tempfile$/ { print; print "import time"; next }
    $0 == "        os.chmod(tmp_path, before.st_mode & 0o7777)" {
      print; print "        time.sleep(5)"; next }
    { print }
  ' "$1" > "$2"
  if ! grep -q "time.sleep(5)" "$2"; then
    _fail "could not inject the delay into $1 (anchor line moved?)"
    return 1
  fi
  return 0
}

# wait_for_write_window <home> <pid> - returns 0 once the writer's temp file
# exists, meaning it is inside the window. The temp file is the marker; without
# waiting for it a kill or a rewrite could land before the write and the case
# would pass while proving nothing.
wait_for_write_window() {
  local home="$1" pid="$2" tries=0
  while [[ "$tries" -lt 200 ]]; do
    if ls "$home"/.settings.json.* >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    sleep 0.05
    tries=$((tries + 1))
  done
  return 1
}

# ---------------------------------------------------------------------------
# B1: the write is a re-serialization of the same document with one key added.
# ---------------------------------------------------------------------------
case_writer_preserves_bytes() {
  local script="$1"
  local py="$TMP_ROOT/writer.py"
  local home="$TMP_ROOT/b1-home"
  local rc mode leftovers
  mkdir -p "$home"
  if ! extract_writer "$script" "$py"; then
    return 1
  fi
  write_settings_fixture "$home/settings.json" ""
  write_settings_expected "$home/expected.json" "$IDLE_DEFAULT"
  # A non-default mode, so the carry-over is asserted rather than assumed: a
  # mkstemp temp file is 0600 whatever the operator's file was.
  chmod 640 "$home/settings.json"

  ( AE_SETTINGS_PATH="$home/settings.json" python3 "$py" "$IDLE_DEFAULT" ) >/dev/null 2>"$home/err.txt"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "B1: the writer exited $rc on the canonical fixture"
    cat "$home/err.txt" >&2
    return 1
  fi
  # Checked before the whole-file comparison, so a mutation to ensure_ascii is
  # named by the assertion it reddens rather than by the diff below.
  if ! grep -qF "café · waiting" "$home/settings.json"; then
    _fail "B1: the operator's non-ASCII value was re-encoded as escapes"
    return 1
  fi
  if ! cmp -s "$home/expected.json" "$home/settings.json"; then
    _fail "B1: the write is not a pure re-serialization with the one key added"
    diff "$home/expected.json" "$home/settings.json" >&2
    return 1
  fi
  mode="$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o7777))' "$home/settings.json")"
  if [[ "$mode" != "0o640" ]]; then
    _fail "B1: the file mode was not carried over (want 0o640, got $mode)"
    return 1
  fi
  leftovers="$(find "$home" -name '.settings.json.*' -print)"
  if [[ -n "$leftovers" ]]; then
    _fail "B1: a temp file was left behind: $leftovers"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# B2/B3: a container the writer has no surgical edit for is refused by name and
# never written, which is what keeps the operator's file intact.
# ---------------------------------------------------------------------------
case_writer_refuses_shape() {
  local script="$1" shape="$2" needle="$3"
  local py="$TMP_ROOT/writer-$shape.py"
  local home="$TMP_ROOT/b-shape-$shape"
  local before="$TMP_ROOT/b-shape-$shape-before.json"
  local rc
  mkdir -p "$home"
  if ! extract_writer "$script" "$py"; then
    return 1
  fi
  case "$shape" in
  env-not-object)
    printf '{"numStartups":7,"env":["DISABLE_AUTOUPDATER"],"projects":{}}\n' > "$home/settings.json"
    ;;
  top-level-array)
    printf '["legacy-setting-A","legacy-setting-B"]\n' > "$home/settings.json"
    ;;
  esac
  cp "$home/settings.json" "$before"

  ( AE_SETTINGS_PATH="$home/settings.json" python3 "$py" "$IDLE_DEFAULT" ) >/dev/null 2>"$home/err.txt"
  rc=$?
  if [[ "$rc" == "0" ]]; then
    _fail "$shape: the writer accepted a container it cannot edit surgically (exit 0)"
    return 1
  fi
  if ! grep -qF "$needle" "$home/err.txt"; then
    _fail "$shape: the refusal did not name the shape"
    cat "$home/err.txt" >&2
    return 1
  fi
  if grep -q "Traceback (most recent call last)" "$home/err.txt"; then
    _fail "$shape: a traceback reached the writer's output"
    return 1
  fi
  if ! cmp -s "$before" "$home/settings.json"; then
    _fail "$shape: the refused container was modified (expected byte-identical)"
    return 1
  fi
  return 0
}

case_writer_env_not_object() {
  case_writer_refuses_shape "$1" env-not-object "env is not a JSON object"
}

case_writer_top_level_array() {
  case_writer_refuses_shape "$1" top-level-array "the file's top level is not a JSON object"
}

# ---------------------------------------------------------------------------
# B4: an update landing from another writer inside the window is refused rather
# than clobbered, and the refusal names the key so the operator can set it.
# ---------------------------------------------------------------------------
case_writer_concurrent() {
  local script="$1"
  local py="$TMP_ROOT/writer-race.py"
  local home="$TMP_ROOT/b4-home"
  local rc wpid
  mkdir -p "$home"
  if ! extract_writer "$script" "$py"; then
    return 1
  fi
  if ! inject_delay "$py" "$py.delayed"; then
    return 1
  fi
  write_settings_fixture "$home/settings.json" ""
  : > "$home/err.txt"

  ( AE_SETTINGS_PATH="$home/settings.json" python3 "$py.delayed" "$IDLE_DEFAULT" 2>"$home/err.txt" ) &
  wpid=$!
  if ! wait_for_write_window "$home" "$wpid"; then
    kill -9 "$wpid" 2>/dev/null
    wait "$wpid" 2>/dev/null
    _fail "B4: the writer never reached its write window"
    return 1
  fi
  printf '{"changedByAnotherWriter":true}\n' > "$home/settings.json"
  wait "$wpid"
  rc=$?

  if [[ "$rc" == "0" ]]; then
    _fail "B4: the writer overwrote a file that changed under it"
    return 1
  fi
  if ! grep -q "changed while this installer was preparing its update" "$home/err.txt"; then
    _fail "B4: no manual-edit message was printed"
    cat "$home/err.txt" >&2
    return 1
  fi
  if ! grep -qF "$IDLE_KEY" "$home/err.txt"; then
    _fail "B4: the manual-edit message does not name the key to set by hand"
    return 1
  fi
  if ! grep -q "changedByAnotherWriter" "$home/settings.json"; then
    _fail "B4: the other writer's update was lost"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# B5: killed inside the write window, the operator's file is untouched. This is
# what an in-place write cannot do, so this is the case that reddens when the
# write shape regresses.
# ---------------------------------------------------------------------------
case_writer_interrupted() {
  local script="$1"
  local py="$TMP_ROOT/writer-kill.py"
  local home pid
  # A directory per invocation, never a fixed path: a killed writer leaves its
  # temp file behind, and a later invocation polling for that leftover would
  # kill the new writer before it ever reached its write window.
  home="$(mktemp -d "$TMP_ROOT/b5-XXXXXX")"
  if ! extract_writer "$script" "$py"; then
    return 1
  fi
  if ! inject_delay "$py" "$py.delayed"; then
    return 1
  fi
  write_settings_fixture "$home/settings.json" ""
  cp "$home/settings.json" "$home/before.json"

  ( AE_SETTINGS_PATH="$home/settings.json" python3 "$py.delayed" "$IDLE_DEFAULT" ) >/dev/null 2>&1 &
  pid=$!
  if ! wait_for_write_window "$home" "$pid"; then
    kill -9 "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    _fail "B5: the writer never reached its write window"
    return 1
  fi
  # The temp file is created before the content is written, so waiting for it
  # alone can kill inside that gap. The window's own sleep is 5 s; 1.5 s past
  # the marker is comfortably inside it and comfortably after the write.
  sleep 1.5
  kill -9 "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null

  if ! cmp -s "$home/before.json" "$home/settings.json"; then
    _fail "B5: the operator's settings file was modified by a run that never finished"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Mutation harness: mutate the installer, re-run a case against the mutation,
# and require the case to FAIL. A case that cannot be made to fail proves
# nothing.
# ---------------------------------------------------------------------------
MUTATE_OUT=""
mutate_installer() {
  local expr="$1" tag="$2"
  local out="$REPO_DIR/.claude/.mutation-install-$$-$tag.sh"
  sed "$expr" "$INSTALL_SH" > "$out"
  if cmp -s "$INSTALL_SH" "$out"; then
    rm -f "$out"
    MUTATE_OUT=""
    return 1
  fi
  # A sed range whose end pattern never matches deletes to EOF, and the cases
  # then redden because the installer is truncated rather than because of the
  # behaviour under test. Reject a syntactically broken mutation here so that
  # failure cannot be credited as coverage.
  if ! bash -n "$out"; then
    rm -f "$out"
    MUTATE_OUT=""
    _fail "mutation $tag produced a script with a shell syntax error"
    return 1
  fi
  MUTATE_OUT="$out"
  return 0
}

# expect_case_fails <label> <case-fn> <install-script> <expected-reason>
expect_case_fails() {
  local label="$1" fn="$2" script="$3" want="$4"
  if ( "$fn" "$script" ) >"$TMP_ROOT/expect-fail.out" 2>"$TMP_ROOT/expect-fail.err"; then
    _fail "$label: the case unexpectedly passed against the mutated installer"
    tail -5 "$TMP_ROOT/expect-fail.out" >&2
    return 1
  fi
  # Print which assertion reddened, so a mutation that fails the case for an
  # unrelated reason cannot be mistaken for targeted coverage.
  local reason
  reason="$(grep '^FAIL:' "$TMP_ROOT/expect-fail.err" | tail -1)"
  if [[ -z "$reason" ]]; then
    _fail "$label: the case failed without naming an assertion"
    return 1
  fi
  echo "    (!) $reason"
  if [[ "$reason" != *"$want"* ]]; then
    _fail "$label: reddened for an unrelated reason (wanted '$want')"
    tail -15 "$TMP_ROOT/expect-fail.err" >&2
    return 1
  fi
  return 0
}

# expect_mutation_fails <sed-expr> <tag> <install-script> <case-fn> <expected-reason>
expect_mutation_fails() {
  local expr="$1" tag="$2" script="$3" fn="$4" want="$5"
  if ! mutate_installer "$expr" "$tag"; then
    _fail "mutation $tag: the sed pattern matched nothing (anchor moved?)"
    return 1
  fi
  local out="$MUTATE_OUT"
  if ! expect_case_fails "mutation $tag" "$fn" "$out" "$want"; then
    rm -f "$out"
    MUTATE_OUT=""
    return 1
  fi
  rm -f "$out"
  MUTATE_OUT=""
  return 0
}

echo ""
echo "=== A1: the operator's file gains the key and loses nothing else ==="
run_case "A1: DISABLE_AUTOUPDATER and the sibling keys survive, the cost is stated first" \
  case_install_preserves_siblings "$INSTALL_SH"

echo ""
echo "=== A2: declining writes nothing ==="
run_case "A2: a declined prompt leaves the operator's env value untouched" \
  case_install_declined "$INSTALL_SH"

echo ""
echo "=== A3: an operator-raised value is never re-asked or rewritten ==="
run_case "A3: an already-set key is reported and left at the operator's value" \
  case_install_already_set "$INSTALL_SH"

echo ""
echo "=== B1: the write is a pure re-serialization with one key added ==="
run_case "B1: byte-identical apart from the new key, non-ASCII intact, mode carried over" \
  case_writer_preserves_bytes "$INSTALL_SH"

echo ""
echo "=== B2/B3: containers the writer cannot edit are refused, not coerced ==="
run_case "B2: a non-object env is named and skipped, file byte-identical" \
  case_writer_env_not_object "$INSTALL_SH"
run_case "B3: a non-object top level is named and skipped, file byte-identical" \
  case_writer_top_level_array "$INSTALL_SH"

echo ""
echo "=== B4: a concurrent update is refused, not clobbered ==="
run_case "B4: the writer refuses and names the key to set by hand" \
  case_writer_concurrent "$INSTALL_SH"

echo ""
echo "=== B5: an interrupted write cannot truncate the operator's file ==="
run_case "B5: the file is byte-identical after the writer is killed inside its window" \
  case_writer_interrupted "$INSTALL_SH"

echo ""
echo "=== Mutations ==="
# (a) the env object is replaced rather than set into.
ENV_REPLACED='s|^env = data.setdefault("env", {})$|env = {}; data["env"] = env|'
expect_mutation_fails "$ENV_REPLACED" "env-object-replaced" "$INSTALL_SH" \
  case_install_preserves_siblings "dropped or added a top-level value the operator owned"
expect_mutation_fails "$ENV_REPLACED" "env-object-replaced-writer" "$INSTALL_SH" \
  case_writer_preserves_bytes "not a pure re-serialization"
# (b)
expect_mutation_fails 's|^if not isinstance(data, dict):$|if False:|' \
  "top-level-guard-disabled" "$INSTALL_SH" case_writer_top_level_array "did not name the shape"
# (c)
expect_mutation_fails 's|^if "env" in data and not isinstance(data\["env"\], dict):$|if False:|' \
  "env-guard-disabled" "$INSTALL_SH" case_writer_env_not_object "did not name the shape"
# (d)
expect_mutation_fails 's|^    if moved:$|    if False:|' \
  "restat-guard-disabled" "$INSTALL_SH" case_writer_concurrent "overwrote a file that changed under it"
# (e) the content lands in the target itself, the shape an interrupted run
# truncates. The pattern carries the block's 4-space indent, which is what
# keeps it off the mcp-atlassian writer's identically spelled line one nesting
# level deeper.
expect_mutation_fails 's|^    with os.fdopen(fd, "w", encoding="utf-8") as f:$|    with open(target, "w", encoding="utf-8") as f:|' \
  "in-place-write-restored" "$INSTALL_SH" case_writer_interrupted "modified by a run that never finished"
# (f)
expect_mutation_fails 's|json.dump(data, f, indent=2, ensure_ascii=False)|json.dump(data, f, indent=2)|' \
  "ensure-ascii-restored" "$INSTALL_SH" case_writer_preserves_bytes "re-encoded as escapes"
# (g)
expect_mutation_fails 's|print("set" if "AGENT_BROWSER_IDLE_TIMEOUT_MS" in env else "absent")|print("absent")|' \
  "already-set-classified-absent" "$INSTALL_SH" case_install_already_set "offered the prompt again"
# (h) the prompt is still asked and still printed; only its answer stops
# deciding anything.
expect_mutation_fails 's@\(Set AGENT_BROWSER_IDLE_TIMEOUT_MS in \$SETTINGS? \[y/N\] "\); then@\1 || true; then@' \
  "confirm-gate-ignored" "$INSTALL_SH" case_install_declined "the declined key was written anyway"
# (i)
expect_mutation_fails 's|^        os.chmod(tmp_path, before.st_mode & 0o7777)$|        pass|' \
  "mode-carryover-dropped" "$INSTALL_SH" case_writer_preserves_bytes "the file mode was not carried over"
# (j)
expect_mutation_fails 's|^  echo "  The cost: .*$|  true|' \
  "cost-sentence-dropped" "$INSTALL_SH" case_install_preserves_siblings "was never stated"

# ---------------------------------------------------------------------------
# The git shim must have kept the ambient hooks dir out of this test's reach.
# ---------------------------------------------------------------------------
echo ""
echo "=== Ambient hook symlink unchanged ==="
AMBIENT_PRECOMMIT_AFTER=""
if [[ -L "$AMBIENT_PRECOMMIT" ]]; then
  AMBIENT_PRECOMMIT_AFTER="$(readlink "$AMBIENT_PRECOMMIT")"
fi
if [[ "$AMBIENT_PRECOMMIT_AFTER" == "$AMBIENT_PRECOMMIT_BEFORE" ]]; then
  _pass "the git shim kept the ambient pre-commit symlink out of this test's reach"
else
  _fail "this test mutated the ambient pre-commit symlink ($AMBIENT_PRECOMMIT_BEFORE -> $AMBIENT_PRECOMMIT_AFTER)"
fi

echo ""
echo "=== Results ==="
echo "PASS: $PASS"
echo "FAIL: $FAIL"
if [[ "$FAIL" -ne 0 ]]; then
  exit 1
fi
exit 0
