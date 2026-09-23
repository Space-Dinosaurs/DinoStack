#!/usr/bin/env bash
# Purpose: Drive the REAL .claude/install.sh against a scratch HOME and assert
#          the chrome-devtools MCP registration it writes launches Chrome
#          headless against a pinned profile root (U1), and that an operator
#          whose registration predates those flags is MIGRATED rather than
#          short-circuited as "already configured" (U3).
#
#          The R2 cases, each a separate install run:
#            V1  - no prior chrome-devtools registration  -> entry created with
#                  --headless and --user-data-dir=<HOME>/.cache/.../chrome-profile
#            V2  - prior registration, operator accepts  -> args gain the flags;
#                  every sibling key of that entry, every other mcpServers
#                  entry, and every other top-level key is byte-identical
#            V1b - prior registration, operator declines -> the config file is
#                  byte-identical (cmp, not a parse-and-compare), paired with a
#                  positive assertion that the install REACHED the migration
#                  prompt (a no-op install would otherwise pass vacuously)
#            V1c - a refused write (symlinked config) -> the installer still
#                  completes and the file behind the symlink is untouched
#            V1d - an unparseable config       -> skipped with a message, never
#                  replaced
#            V3  - a container the writer cannot edit surgically (three shapes:
#                  a non-object mcpServers, a non-object chrome-devtools entry,
#                  an args value that is not a list of strings) -> the
#                  classifier names the shape and skips, without offering a
#                  prompt for an edit it cannot make, and the file is
#                  byte-identical
#            V4  - the same shapes driven straight at the writer block (the
#                  last guard before a temp file exists) -> non-zero exit, the
#                  shape named, the file byte-identical
#            V5  - a stale entry carrying --channel=canary -> the pinned root
#                  carries the same channel suffix the MCP appends, and a
#                  --channel=stable entry (the control) gets the unsuffixed one
#
#          The ae_confirm prompt reads /dev/tty, so each case runs under a real
#          pseudo-terminal (python3 pty.fork) with the answer written once the
#          prompt text is observed. Every other prompt in install.sh is seeded
#          away (skill_auto_load key, permissions.defaultMode, the five
#          CLI_TOOLS on PATH, --mode and --no-identity flags), so exactly one
#          prompt is live per run - see the seed list below. The container-shape
#          fixture is the exception: its mcpServers is a list, so the atlassian
#          block's own key check finds nothing and prompts, and that prompt gets
#          its own seeded answer.
#
#          MUTATION COVERAGE (each mutation is RUN, not merely named):
#            (a) drop the --headless append           -> V1 reddens
#            (b) report "current" for any existing key (the pre-U3
#                short-circuit)                       -> V2 and V1b redden
#            (c) drop the pre-rename re-stat guard    -> the concurrent-writer
#                case reddens
#            (d) invert the refuse-guard's exit handling -> V1c reddens
#            (e) drop ensure_ascii=False (re-encode non-ASCII) -> V2 reddens
#            (f) call an unparseable config "absent" -> V1d reddens
#            (g) drop the trade-off statement printed before the accept prompt
#                -> V2 and V1 redden
#            (h) collapse a non-object mcpServers into "absent" (the pre-fix
#                classifier)                            -> V3's container case
#                reddens
#            (i) collapse a non-object entry into "absent" -> V3's entry case
#                reddens
#            (j) collapse a non-string-list args into "absent" -> V3's args case
#                reddens
#            (k) disable the writer's mcpServers guard (the pre-fix coercion)
#                -> V4's container case reddens
#            (l) disable the writer's entry guard -> V4's entry case reddens
#            (m) disable the writer's args guard -> V4's args cases redden
#            (n) pin the unsuffixed root for every channel (channel-blind)
#                -> V5 reddens
#          A mutation is a full copy of .claude/install.sh, so it must live in
#          .claude/ too (REPO_DIR is derived from the script's own path). Those
#          copies are removed by the exit trap.
#
# Public API: ./bin/tests/test_install_chrome_devtools_headless.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3 (pty), git, node (transitively, via build.sh),
#                mktemp.
#
# Downstream consumers: developer running locally before commit; CI (the
#                       bin/tests/test_*.sh glob in .github/workflows/bin-tests.yml).
#
# Failure modes: any assertion failure prints the failing assertion and exits
#                1. A temporary fake HOME is used; the real ~/.claude and
#                ~/.claude.json are never touched. A faked $HOME without the
#                git shim below can escape its sandbox and mutate the LIVE
#                primary checkout's pre-commit hook symlink - see Seed 5.
#
# Performance: 19 install runs per invocation (8 of the cases plus 11 mutation
#              runs of the installer), measured at ~78 s total on a warm tree.
#              The concurrent-writer and V4/V5 cases run the extracted writer
#              instead, at negligible cost.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_DIR/.claude/install.sh"
MUTATION_GLOB="$REPO_DIR/.claude/.mutation-install-$$-*"

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
# counted HERE, in the parent, because a counter incremented inside a subshell
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
# Seed 5 (git-level sandbox): running the REAL .claude/install.sh from an
# isolation worktree calls scripts/lib/precommit.sh's resolve_git_hooks_dir(),
# which shells out to `git -C "$REPO_DIR" rev-parse --git-path hooks`. From a
# worktree that resolves to the PRIMARY checkout's common .git/hooks dir, so an
# unsandboxed run re-points the live primary checkout's .git/hooks/pre-commit
# symlink at this disposable worktree. This shim (copied verbatim from
# bin/tests/test_install_worktree_isolation_spawn_guard.sh, which the plan's
# V14 names as the fixture to reuse) answers ONLY that exact query and passes
# every other git invocation through to the real binary.
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

# Snapshot the AMBIENT git hooks dir (resolved through the real, unsandboxed
# git) BEFORE any install run, so the end-of-test assertion can prove the shim
# prevented any mutation. The live symlink legitimately points at whichever
# checkout last ran the installer, so this is a before/after comparison rather
# than a comparison against this worktree's own path.
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
# seed_home <home>
# Seeds 1 and 4, the two prompt-suppression seeds that live under $HOME.
#   Seed 1: agentic-engineering.json carrying skill_auto_load -> suppresses
#           ae_write_mode's /dev/tty prompt (gated on the key being absent).
#   Seed 4: settings.json with permissions.defaultMode already
#           bypassPermissions -> suppresses the permissions tty_input prompt.
# ---------------------------------------------------------------------------
seed_home() {
  local home="$1"
  mkdir -p "$home/.claude"
  printf '{"skill_auto_load": false}\n' > "$home/.claude/agentic-engineering.json"
  printf '{"permissions":{"defaultMode":"bypassPermissions"}}\n' > "$home/.claude/settings.json"
}

# ---------------------------------------------------------------------------
# A pre-existing registration written before the headless default shipped,
# alongside a sibling MCP server and unrelated top-level keys, so "everything
# else is untouched" is a real assertion rather than an empty one.
# ---------------------------------------------------------------------------
# The non-ASCII value below is load-bearing, not decoration: a JSON round trip
# with json.dump's default ensure_ascii=True rewrites every non-ASCII string in
# the file as \uXXXX escapes, so a fixture made only of ASCII cannot tell a
# surgical rewrite from a whole-file re-encoding.
write_stale_config() {
  cat > "$1" <<'EOF'
{
  "numStartups": 42,
  "statusLineText": "café · waiting",
  "mcpServers": {
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "args": [
        "chrome-devtools-mcp@latest"
      ],
      "env": {}
    },
    "mcp-atlassian": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "mcp-atlassian"
      ],
      "env": {}
    }
  },
  "projects": {
    "/tmp/example": {
      "history": [
        {
          "display": "hello"
        }
      ]
    }
  }
}
EOF
}

# The args the installer is expected to write for <home>, built exactly as the
# installer builds them (os.path.expanduser resolves HOME at install time).
expected_args_json() {
  printf '["chrome-devtools-mcp@latest", "--headless", "--user-data-dir=%s/.cache/chrome-devtools-mcp/chrome-profile"]' "$1"
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
# The five installer-driven cases.
# ---------------------------------------------------------------------------

# V1: no prior chrome-devtools registration.
case_v1_fresh() {
  local script="$1" out rc
  local home="$TMP_ROOT/v1-home"
  mkdir -p "$home"
  seed_home "$home"
  # mcp-atlassian pre-registered so the SECOND MCP block short-circuits and
  # this run has exactly one live prompt.
  printf '{"mcpServers":{"mcp-atlassian":{"type":"stdio","command":"uvx","args":["mcp-atlassian"],"env":{}}}}\n' > "$home/.claude.json"

  out="$(run_install "$script" "$home" '[["Configure chrome-devtools MCP", "y\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "V1: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi

  if ! grep -q "Configure chrome-devtools MCP" <<< "$out"; then
    _fail "V1: the registration prompt was never reached"
    return 1
  fi
  if ! grep -q "remove --headless from its args" <<< "$out"; then
    _fail "V1: the trade-off and the way back were not stated at the accept prompt"
    return 1
  fi

  python3 - "$home/.claude.json" "$(expected_args_json "$home")" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
entry = data["mcpServers"]["chrome-devtools"]
assert entry["type"] == "stdio", entry
assert entry["command"] == "npx", entry
assert entry["env"] == {}, entry
assert entry["args"] == json.loads(sys.argv[2]), entry["args"]
assert "mcp-atlassian" in data["mcpServers"], data["mcpServers"]
PYEOF
  if [[ $? -ne 0 ]]; then
    _fail "V1: the fresh registration does not carry the headless flags"
    return 1
  fi
  return 0
}

# V2: prior registration, operator accepts -> args rewritten, nothing else moves.
case_v2_accepted() {
  local script="$1" out rc
  local home="$TMP_ROOT/v2-home"
  mkdir -p "$home"
  seed_home "$home"
  write_stale_config "$home/.claude.json"
  cp "$home/.claude.json" "$TMP_ROOT/v2-before.json"

  out="$(run_install "$script" "$home" '[["Update the existing chrome-devtools MCP", "y\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "V2: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi

  # Positive assertion that the stale entry was DETECTED rather than
  # short-circuited: the pre-U3 code printed the message asserted absent below.
  if ! grep -q "Update the existing chrome-devtools MCP" <<< "$out"; then
    _fail "V2: the migration prompt was never reached"
    return 1
  fi
  if grep -q "chrome-devtools MCP already configured" <<< "$out"; then
    _fail "V2: install reported the entry as already configured"
    return 1
  fi

  # R6: the capability the change removes must be stated WHERE THE OPERATOR IS
  # ASKED TO ACCEPT IT, together with a one-step way back. Ordering is the
  # load-bearing half - the same sentence printed after the prompt would not
  # inform the decision the prompt asks for.
  local trade_off_at prompt_at
  trade_off_at="$(grep -n "remove --headless from its args" <<< "$out" | head -1 | cut -d: -f1)"
  prompt_at="$(grep -n "Update the existing chrome-devtools MCP" <<< "$out" | head -1 | cut -d: -f1)"
  if [[ -z "$trade_off_at" || -z "$prompt_at" || "$trade_off_at" -ge "$prompt_at" ]]; then
    _fail "V2: the trade-off and the way back are not stated before the accept prompt"
    return 1
  fi

  python3 - "$home/.claude.json" "$TMP_ROOT/v2-before.json" "$(expected_args_json "$home")" <<'PYEOF'
import json, sys
after = json.load(open(sys.argv[1], encoding="utf-8"))
before = json.load(open(sys.argv[2], encoding="utf-8"))
want = json.loads(sys.argv[3])

assert after["mcpServers"]["chrome-devtools"]["args"] == want, \
    after["mcpServers"]["chrome-devtools"]["args"]
assert list(after.keys()) == list(before.keys()), (list(after.keys()), list(before.keys()))
for key in before:
    if key != "mcpServers":
        assert json.dumps(after[key]) == json.dumps(before[key]), key
assert list(after["mcpServers"].keys()) == list(before["mcpServers"].keys())
for name in before["mcpServers"]:
    if name != "chrome-devtools":
        assert json.dumps(after["mcpServers"][name]) == json.dumps(before["mcpServers"][name]), name
siblings_before = {k: v for k, v in before["mcpServers"]["chrome-devtools"].items() if k != "args"}
siblings_after = {k: v for k, v in after["mcpServers"]["chrome-devtools"].items() if k != "args"}
assert json.dumps(siblings_after) == json.dumps(siblings_before), (siblings_after, siblings_before)
# Strongest form: the file on disk is exactly a re-serialization of the
# intended data, so nothing but "args" moved, appeared or disappeared. The
# non-ASCII value in the fixture makes this catch a whole-file re-encoding as
# well as a structural change.
want_doc = json.loads(json.dumps(before))
want_doc["mcpServers"]["chrome-devtools"]["args"] = want
with open(sys.argv[1], encoding="utf-8") as fh:
    on_disk = fh.read()
assert on_disk == json.dumps(want_doc, indent=2, ensure_ascii=False), \
    "file is not a pure re-serialization with args changed"
PYEOF
  if [[ $? -ne 0 ]]; then
    _fail "V2: accepting the migration changed something beyond mcpServers['chrome-devtools']['args']"
    return 1
  fi
  return 0
}

# V1b: prior registration, operator declines -> byte-identical file.
case_v1b_declined() {
  local script="$1" out rc
  local home="$TMP_ROOT/v1b-home"
  mkdir -p "$home"
  seed_home "$home"
  write_stale_config "$home/.claude.json"
  cp "$home/.claude.json" "$TMP_ROOT/v1b-before.json"

  out="$(run_install "$script" "$home" '[["Update the existing chrome-devtools MCP", "n\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "V1b: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi

  # Positive half: the install really reached the prompt. Without this half a
  # truncated or no-op install sails through the byte-identity check below.
  if ! grep -q "Update the existing chrome-devtools MCP" <<< "$out"; then
    _fail "V1b: the migration prompt was never reached"
    return 1
  fi
  if grep -q "chrome-devtools MCP already configured" <<< "$out"; then
    _fail "V1b: install reported the entry as already configured"
    return 1
  fi
  if ! grep -q "skipped chrome-devtools MCP" <<< "$out"; then
    _fail "V1b: install did not report the decline"
    return 1
  fi

  if ! cmp -s "$TMP_ROOT/v1b-before.json" "$home/.claude.json"; then
    _fail "V1b: declining modified the config file (expected byte-identical)"
    return 1
  fi
  return 0
}

# V1c: a refused write must not end the install. Drives the symlink refusal,
# which is the same exit-non-zero-without-writing path the concurrent-writer
# guard takes, and asserts both halves: the installer still completes, and the
# file behind the symlink is untouched.
case_v1c_refusal_nonfatal() {
  local script="$1" out rc
  local home="$TMP_ROOT/v1c-home"
  local real="$TMP_ROOT/v1c-real-config.json"
  mkdir -p "$home"
  seed_home "$home"
  printf '{"mcpServers":{"mcp-atlassian":{}}}\n' > "$real"
  ln -s "$real" "$home/.claude.json"
  cp "$real" "$TMP_ROOT/v1c-before.json"

  out="$(run_install "$script" "$home" '[["Configure chrome-devtools MCP", "y\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "V1c: a refused write aborted the whole install (exit $rc)"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! grep -q "refusing to write through symlink" <<< "$out"; then
    _fail "V1c: the symlink refusal was never reached"
    return 1
  fi
  if ! grep -q "chrome-devtools MCP registration left unchanged" <<< "$out"; then
    _fail "V1c: install did not report the refusal as a no-op"
    return 1
  fi
  if ! cmp -s "$TMP_ROOT/v1c-before.json" "$real"; then
    _fail "V1c: the refusal still modified the file the symlink points at"
    return 1
  fi
  return 0
}

# V1d: an unparseable config is never rewritten. The chrome-devtools block
# skips it with a message rather than replacing a file it cannot read.
case_v1d_unparseable() {
  local script="$1" out rc
  local home="$TMP_ROOT/v1d-home"
  mkdir -p "$home"
  seed_home "$home"
  printf '{"mcpServers": {"chrome-devtools": {"args": ["chrome-devtools-mcp@latest"]}\n' > "$home/.claude.json"
  cp "$home/.claude.json" "$TMP_ROOT/v1d-before.json"

  # The atlassian block runs its own check on the same file and, finding
  # nothing, prompts. The chrome-devtools answer is listed only so a mutated
  # installer that wrongly classifies this file as absent cannot hang the pty
  # for the whole driver deadline; the unmutated run never reaches it.
  out="$(run_install "$script" "$home" '[["Configure chrome-devtools MCP", "y\n"], ["mcp-atlassian MCP", "n\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "V1d: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! grep -q "could not be read as JSON" <<< "$out"; then
    _fail "V1d: an unparseable config did not produce the skip message"
    return 1
  fi
  if grep -q "Configure chrome-devtools MCP" <<< "$out"; then
    _fail "V1d: an unparseable config was offered the registration prompt anyway"
    return 1
  fi
  if ! cmp -s "$TMP_ROOT/v1d-before.json" "$home/.claude.json"; then
    _fail "V1d: an unparseable config was modified"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# V3/V4 fixtures: the container shapes the writer has no surgical edit for.
# Each one was coerced before this fix - a non-object mcpServers was replaced
# outright (both legacy servers lost), a non-object entry was replaced, and an
# args value that is not a list of strings was discarded and then overwritten
# with the flags alone. For the string form that yields
# `npx --headless --user-data-dir=...`, a registration that cannot launch.
# ---------------------------------------------------------------------------
write_shape_config() {
  local path="$1" shape="$2"
  case "$shape" in
  container)
    cat > "$path" <<'EOF'
{
  "numStartups": 42,
  "mcpServers": [
    "legacy-server-A",
    "legacy-server-B"
  ]
}
EOF
    ;;
  entry)
    cat > "$path" <<'EOF'
{
  "numStartups": 42,
  "mcpServers": {
    "chrome-devtools": [
      "chrome-devtools-mcp@latest"
    ],
    "mcp-atlassian": {}
  }
}
EOF
    ;;
  args-string)
    cat > "$path" <<'EOF'
{
  "numStartups": 42,
  "mcpServers": {
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "args": "chrome-devtools-mcp@latest",
      "env": {}
    },
    "mcp-atlassian": {}
  }
}
EOF
    ;;
  args-element)
    cat > "$path" <<'EOF'
{
  "numStartups": 42,
  "mcpServers": {
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "args": [
        "chrome-devtools-mcp@latest",
        123
      ],
      "env": {}
    },
    "mcp-atlassian": {}
  }
}
EOF
    ;;
  esac
}

# The phrase a refusal must name. The classifier-driven message and the
# writer's own message carry it verbatim, so one needle pins both paths.
shape_needle() {
  case "$1" in
  container) printf 'mcpServers is not a JSON object' ;;
  entry) printf 'the chrome-devtools entry is not a JSON object' ;;
  *) printf "the chrome-devtools entry has an args value that is not a list of strings" ;;
  esac
}

# V3: a container the writer cannot edit is refused by the classifier, so the
# file never reaches the writer and no prompt offers an edit that cannot be
# made. Asserts the shape is named, no chrome-devtools prompt was offered, the
# install still completes, and the file is byte-identical.
case_shape_refused() {
  local script="$1" shape="$2"
  local home="$TMP_ROOT/shape-$shape-home"
  local before="$TMP_ROOT/shape-$shape-before.json"
  local out rc
  mkdir -p "$home"
  seed_home "$home"
  write_shape_config "$home/.claude.json" "$shape"
  cp "$home/.claude.json" "$before"

  # The container fixture has no mcp-atlassian key to find (its mcpServers is a
  # list), so the atlassian block prompts and needs an answer; the other two
  # fixtures carry mcp-atlassian and never reach that prompt.
  out="$(run_install "$script" "$home" '[["Configure chrome-devtools MCP", "y\n"], ["mcp-atlassian MCP", "n\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "$shape: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! grep -qF "$(shape_needle "$shape")" <<< "$out"; then
    _fail "$shape: the refusal did not name the shape"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if grep -q "Configure chrome-devtools MCP" <<< "$out"; then
    _fail "$shape: a container the writer cannot edit was offered the registration prompt"
    return 1
  fi
  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "$shape: the refused shape was modified (expected byte-identical)"
    return 1
  fi
  return 0
}

case_shape_container() { case_shape_refused "$1" container; }
case_shape_entry() { case_shape_refused "$1" entry; }
case_shape_args_string() { case_shape_refused "$1" args-string; }

# ---------------------------------------------------------------------------
# Concurrent-writer guard. The window between the writer's read and its
# pre-rename re-stat is microseconds, so this runs the SHIPPED writer block
# (extracted from install.sh, never retyped here) with one injected
# `time.sleep` to hold the window open, and rewrites the file from another
# process while it is open.
# ---------------------------------------------------------------------------
# extract_writer <source-install-sh> <output.py> - the source is a parameter
# because the mutation harness runs the extracted writer for a mutated copy.
extract_writer() {
  # Stops BEFORE the heredoc's terminating PYEOF, which is shell syntax, not
  # Python: leaving it in makes the extracted block raise NameError at its last
  # line, so an unmutated-looking run would fail on a traceback instead of on
  # the guard under test.
  awk '
    /^import json, os, stat, sys, tempfile$/ { f=1 }
    f && /^PYEOF$/ { exit }
    f { print }
  ' "$1" > "$2"
  if ! grep -q "os.replace(tmp_path, target)" "$2"; then
    _fail "could not extract the shipped writer block from $1 (anchor line moved?)"
    return 1
  fi
  if ! python3 -c 'import sys; compile(open(sys.argv[1]).read(), sys.argv[1], "exec")' "$2"; then
    _fail "the extracted writer block from $1 is not valid Python"
    return 1
  fi
  return 0
}

inject_delay() {
  awk '
    $0 == "import json, os, stat, sys, tempfile" { print; print "import time"; next }
    $0 == "    now = os.stat(target) if os.path.exists(target) else None" { print "    time.sleep(2)"; print; next }
    { print }
  ' "$1" > "$2"
  if ! grep -q "time.sleep(2)" "$2"; then
    _fail "could not inject the delay into $1 (anchor line moved?)"
    return 1
  fi
  return 0
}

case_concurrent_writer() {
  local writer="$1"
  local home="$TMP_ROOT/race-home"
  local err="$TMP_ROOT/race.err"
  mkdir -p "$home"
  write_stale_config "$home/.claude.json"
  : > "$err"

  ( python3 "$writer" "$home/.claude.json" 2>"$err" ) &
  local wpid=$!
  sleep 0.7
  printf '{"mcpServers":{},"changedByAnotherWriter":true}\n' > "$home/.claude.json"
  wait "$wpid"
  local rc=$?

  if [[ "$rc" == "0" ]]; then
    _fail "concurrent-writer: the writer overwrote a file that changed under it"
    return 1
  fi
  if ! grep -q "changed while this installer was preparing its update" "$err"; then
    _fail "concurrent-writer: no manual-edit message was printed"
    return 1
  fi
  if ! grep -q "changedByAnotherWriter" "$home/.claude.json"; then
    _fail "concurrent-writer: the other writer's update was lost"
    return 1
  fi
  if ! grep -q '"--headless"' "$err"; then
    _fail "concurrent-writer: the manual-edit message does not name the args to write"
    return 1
  fi
  return 0
}

# V4: the same container shapes driven straight at the writer block. The
# classifier intercepts them in a real install run, so this is the case that
# holds the writer's own guard to account: non-zero exit, the shape named, and
# the file byte-identical. It is also the guard that still holds if the file
# changes between the classifier's read and the writer's.
case_writer_refuses() {
  local script="$1" shape="$2"
  local home="$TMP_ROOT/writer-$shape-home"
  local py="$TMP_ROOT/writer-$shape.py"
  local before="$TMP_ROOT/writer-$shape-before.json"
  local err="$TMP_ROOT/writer-$shape.err"
  local rc
  mkdir -p "$home"
  write_shape_config "$home/.claude.json" "$shape"
  cp "$home/.claude.json" "$before"
  if ! extract_writer "$script" "$py"; then
    return 1
  fi
  : > "$err"
  ( python3 "$py" "$home/.claude.json" 2>"$err" )
  rc=$?
  if [[ "$rc" == "0" ]]; then
    _fail "$shape: the writer accepted a container it cannot edit surgically (exit 0)"
    return 1
  fi
  if ! grep -qF "$(shape_needle "$shape")" "$err"; then
    _fail "$shape: the writer's refusal did not name the shape"
    cat "$err" >&2
    return 1
  fi
  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "$shape: the writer modified a container it refused"
    return 1
  fi
  return 0
}

case_writer_container() { case_writer_refuses "$1" container; }
case_writer_entry() { case_writer_refuses "$1" entry; }
case_writer_args_string() { case_writer_refuses "$1" args-string; }
case_writer_args_element() { case_writer_refuses "$1" args-element; }

# V5: the pinned profile root must be the directory the server itself would
# have chosen. Its default is channel-suffixed for any non-stable channel, so a
# fixed unsuffixed pin moves a canary operator's profile instead of matching it.
# The stable fixture is the control: it is what makes a channel-blind
# implementation redden here too.
write_channel_config() {
  local path="$1" channel="$2"
  cat > "$path" <<EOF
{
  "mcpServers": {
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "args": [
        "chrome-devtools-mcp@latest",
        "--channel=$channel"
      ],
      "env": {}
    },
    "mcp-atlassian": {}
  }
}
EOF
}

case_writer_channel_suffix() {
  local script="$1"
  local py="$TMP_ROOT/writer-channel.py"
  local got want rc
  if ! extract_writer "$script" "$py"; then
    return 1
  fi
  for pair in "canary:chrome-profile-canary" "stable:chrome-profile"; do
    local channel="${pair%%:*}" dirname="${pair##*:}"
    local home="$TMP_ROOT/channel-$channel-home"
    mkdir -p "$home"
    write_channel_config "$home/.claude.json" "$channel"
    ( HOME="$home" python3 "$py" "$home/.claude.json" ) >/dev/null 2>&1
    rc=$?
    if [[ "$rc" -ne 0 ]]; then
      _fail "channel=$channel: the writer exited $rc on a legitimate stale entry"
      return 1
    fi
    want="[\"chrome-devtools-mcp@latest\", \"--channel=$channel\", \"--headless\", \"--user-data-dir=$home/.cache/chrome-devtools-mcp/$dirname\"]"
    got="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["mcpServers"]["chrome-devtools"]["args"]))' "$home/.claude.json")"
    if [[ "$got" != "$want" ]]; then
      _fail "channel=$channel: the pinned profile root is wrong (want $want, got $got)"
      return 1
    fi
  done
  return 0
}

# ---------------------------------------------------------------------------
# Mutation harness: mutate the installer, re-run a case against the mutation,
# and require the case to FAIL. A case that cannot be made to fail proves
# nothing.
# ---------------------------------------------------------------------------
# Sets MUTATE_OUT (the mutated copy's path) and returns 0, or returns 1 and
# clears MUTATE_OUT when the sed pattern no longer matches anything. Must be
# called in the CURRENT shell, never in a command substitution: `_fail` inside
# a subshell cannot reach the harness total.
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
# The case must fail, and it must fail on the assertion the mutation targets.
# Without the reason check the pty driver's own timeout reddens the case and the
# mutation gets credited with coverage it never demonstrated.
expect_case_fails() {
  local label="$1" fn="$2" script="$3" want="$4"
  if ( "$fn" "$script" ) >"$TMP_ROOT/expect-fail.out" 2>"$TMP_ROOT/expect-fail.err"; then
    _fail "$label: the case unexpectedly PASSED against the mutated installer"
    tail -5 "$TMP_ROOT/expect-fail.out" >&2
    return 1
  fi
  # Print WHICH assertion reddened, so a mutation that fails the case for an
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

echo ""
echo "=== V1: no prior chrome-devtools registration ==="
run_case "V1: a fresh install writes the entry with --headless and the pinned profile root" \
  case_v1_fresh "$INSTALL_SH"

echo ""
echo "=== V2: prior registration, operator accepts ==="
run_case "V2: the stale entry's args gained the flags and nothing else changed" \
  case_v2_accepted "$INSTALL_SH"

echo ""
echo "=== V1b: prior registration, operator declines ==="
run_case "V1b: reaching the prompt and declining left the config byte-identical" \
  case_v1b_declined "$INSTALL_SH"

echo ""
echo "=== V1c: a refused write does not abort the install ==="
run_case "V1c: the symlink refusal is reported, non-fatal, and leaves the file untouched" \
  case_v1c_refusal_nonfatal "$INSTALL_SH"

echo ""
echo "=== V1d: an unparseable config is never rewritten ==="
run_case "V1d: a config that is not JSON is skipped, not replaced" \
  case_v1d_unparseable "$INSTALL_SH"

echo ""
echo "=== V3: containers the writer cannot edit are refused, not coerced ==="
run_case "V3: a non-object mcpServers is named and skipped, file byte-identical" \
  case_shape_container "$INSTALL_SH"
run_case "V3: a non-object chrome-devtools entry is named and skipped, file byte-identical" \
  case_shape_entry "$INSTALL_SH"
run_case "V3: a non-string-list args is named and skipped, file byte-identical" \
  case_shape_args_string "$INSTALL_SH"

echo ""
echo "=== V4: the writer refuses each shape directly, non-zero and without writing ==="
run_case "V4: the writer refuses a non-object mcpServers" \
  case_writer_container "$INSTALL_SH"
run_case "V4: the writer refuses a non-object chrome-devtools entry" \
  case_writer_entry "$INSTALL_SH"
run_case "V4: the writer refuses a string args value" \
  case_writer_args_string "$INSTALL_SH"
run_case "V4: the writer refuses an args list containing a non-string" \
  case_writer_args_element "$INSTALL_SH"
run_case "V5: the pinned profile root carries the entry's own channel suffix" \
  case_writer_channel_suffix "$INSTALL_SH"

echo ""
echo "=== Concurrent-writer guard ==="
if extract_writer "$INSTALL_SH" "$TMP_ROOT/writer.py" && inject_delay "$TMP_ROOT/writer.py" "$TMP_ROOT/writer_slow.py"; then
  run_case "concurrent-writer: a file changed under the writer is refused, not clobbered" \
    case_concurrent_writer "$TMP_ROOT/writer_slow.py"
fi

echo ""
echo "=== Mutations (each must redden the case it targets) ==="
if mutate_installer 's/^    args.append("--headless")$/    pass/' no-headless; then
  if expect_case_fails "mutation (a) no --headless append" case_v1_fresh "$MUTATE_OUT" \
    "V1: the fresh registration does not carry the headless flags"; then
    _pass "mutation (a): dropping the --headless append reddens V1"
  fi
else
  _fail "mutation (a): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/^elif "--headless" in args and any(a\.startswith("--user-data-dir=") for a in args):$/elif True:/' short-circuit; then
  if expect_case_fails "mutation (b) pre-U3 short-circuit" case_v2_accepted "$MUTATE_OUT" \
    "V2: the migration prompt was never reached"; then
    _pass "mutation (b): treating any existing key as current reddens V2"
  fi
  if expect_case_fails "mutation (b) pre-U3 short-circuit" case_v1b_declined "$MUTATE_OUT" \
    "V1b: the migration prompt was never reached"; then
    _pass "mutation (b): treating any existing key as current reddens V1b"
  fi
else
  _fail "mutation (b): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer '/^  echo "  chrome-devtools launches Chrome headless/,/remove --headless from its args/d' drop-trade-off; then
  if expect_case_fails "mutation (g) drop the R6 trade-off statement" case_v2_accepted "$MUTATE_OUT" \
    "V2: the trade-off and the way back are not stated before the accept prompt"; then
    _pass "mutation (g): dropping the trade-off statement reddens V2"
  fi
  if expect_case_fails "mutation (g) drop the R6 trade-off statement" case_v1_fresh "$MUTATE_OUT" \
    "V1: the trade-off and the way back were not stated at the accept prompt"; then
    _pass "mutation (g): dropping the trade-off statement reddens V1's fresh path too"
  fi
else
  _fail "mutation (g): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/    print("unreadable")/    print("absent")/' treat-unparseable-as-absent; then
  if expect_case_fails "mutation (f) unparseable treated as absent" case_v1d_unparseable "$MUTATE_OUT" \
    "V1d: an unparseable config did not produce the skip message"; then
    _pass "mutation (f): calling an unparseable config absent reddens V1d"
  fi
else
  _fail "mutation (f): the sed pattern no longer matches - the mutation was not applied"
fi

# (h)-(j): the pre-fix classifier collapsed each uneditable container into
# "absent", which runs the create path against a file that already has content.
if mutate_installer 's/^    print("mcp-servers-not-object")$/    print("absent")/' unrefuse-container; then
  if expect_case_fails "mutation (h) non-object mcpServers treated as absent" case_shape_container "$MUTATE_OUT" \
    "was offered the registration prompt"; then
    _pass "mutation (h): collapsing a non-object mcpServers into absent reddens its refusal case"
  fi
else
  _fail "mutation (h): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/^    print("entry-not-object")$/    print("absent")/' unrefuse-entry; then
  if expect_case_fails "mutation (i) non-object entry treated as absent" case_shape_entry "$MUTATE_OUT" \
    "was offered the registration prompt"; then
    _pass "mutation (i): collapsing a non-object entry into absent reddens its refusal case"
  fi
else
  _fail "mutation (i): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/^    print("args-not-string-list")$/    print("absent")/' unrefuse-args; then
  if expect_case_fails "mutation (j) non-string-list args treated as absent" case_shape_args_string "$MUTATE_OUT" \
    "was offered the registration prompt"; then
    _pass "mutation (j): collapsing a non-string-list args into absent reddens its refusal case"
  fi
else
  _fail "mutation (j): the sed pattern no longer matches - the mutation was not applied"
fi

# (k)-(m): remove a writer guard. Each mutation restores exactly the pre-fix
# coercion (the code the guard sits in front of replaces the container
# wholesale), so these are the mutations that reproduce the reported damage.
if mutate_installer 's/^    refuse("mcpServers is not a JSON object")$/    pass/' coerce-container; then
  if expect_case_fails "mutation (k) writer coerces a non-object mcpServers" case_writer_container "$MUTATE_OUT" \
    "the writer accepted a container it cannot edit surgically"; then
    _pass "mutation (k): letting the writer replace a non-object mcpServers reddens its refusal case"
  fi
else
  _fail "mutation (k): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/^    refuse("the chrome-devtools entry is not a JSON object")$/    pass/' coerce-entry; then
  if expect_case_fails "mutation (l) writer coerces a non-object entry" case_writer_entry "$MUTATE_OUT" \
    "the writer accepted a container it cannot edit surgically"; then
    _pass "mutation (l): letting the writer replace a non-object entry reddens its refusal case"
  fi
else
  _fail "mutation (l): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/^    refuse("the chrome-devtools entry has an args value that is not a list of strings")$/    pass/' coerce-args; then
  if expect_case_fails "mutation (m) writer discards a non-list args" case_writer_args_string "$MUTATE_OUT" \
    "the writer accepted a container it cannot edit surgically"; then
    _pass "mutation (m): letting the writer discard a string args reddens its refusal case"
  fi
  if expect_case_fails "mutation (m) writer discards a non-string args element" case_writer_args_element "$MUTATE_OUT" \
    "the writer accepted a container it cannot edit surgically"; then
    _pass "mutation (m): letting the writer drop a non-string args element reddens its refusal case"
  fi
else
  _fail "mutation (m): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/^    return "" if channel in (None, "stable") else "-" + channel$/    return ""/' channel-blind; then
  if expect_case_fails "mutation (n) channel-blind pinned root" case_writer_channel_suffix "$MUTATE_OUT" \
    "the pinned profile root is wrong"; then
    _pass "mutation (n): pinning the unsuffixed root for every channel reddens V5"
  fi
else
  _fail "mutation (n): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/indent=2, ensure_ascii=False/indent=2/' ascii-escape; then
  if expect_case_fails "mutation (e) ensure_ascii default" case_v2_accepted "$MUTATE_OUT" \
    "V2: accepting the migration changed something beyond"; then
    _pass "mutation (e): re-encoding non-ASCII reddens V2"
  fi
else
  _fail "mutation (e): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/if ! python3 - /if python3 - /' invert-guard; then
  if expect_case_fails "mutation (d) inverted refuse-guard" case_v1c_refusal_nonfatal "$MUTATE_OUT" \
    "V1c: install did not report the refusal as a no-op"; then
    _pass "mutation (d): inverting the refuse-guard's exit handling reddens V1c"
  fi
else
  _fail "mutation (d): the sed pattern no longer matches - the mutation was not applied"
fi

if [[ -f "$TMP_ROOT/writer_slow.py" ]]; then
  sed 's/^    if moved:$/    if False:/' "$TMP_ROOT/writer_slow.py" > "$TMP_ROOT/writer_unguarded.py"
  if cmp -s "$TMP_ROOT/writer_slow.py" "$TMP_ROOT/writer_unguarded.py"; then
    _fail "mutation (c): could not remove the pre-rename guard (pattern no longer matches)"
  elif expect_case_fails "mutation (c) no pre-rename guard" case_concurrent_writer "$TMP_ROOT/writer_unguarded.py" \
    "concurrent-writer: the writer overwrote a file that changed under it"; then
    _pass "mutation (c): dropping the pre-rename re-stat reddens the concurrent-writer case"
  fi
fi

# ---------------------------------------------------------------------------
# Sandbox-effectiveness assertions (same discipline as
# test_install_worktree_isolation_spawn_guard.sh): the git shim must have
# absorbed the pre-commit install, and the ambient hooks dir must be untouched.
# ---------------------------------------------------------------------------
echo ""
if [[ -L "$SCRATCH_HOOKS_DIR/pre-commit" ]]; then
  _pass "pre-commit hook was installed into the scratch git-hooks sandbox, not the ambient hooks dir"
else
  _fail "no scratch-hooks pre-commit symlink - the git shim may not have intercepted the call"
fi
AMBIENT_PRECOMMIT_AFTER=""
if [[ -L "$AMBIENT_PRECOMMIT" ]]; then
  AMBIENT_PRECOMMIT_AFTER="$(readlink "$AMBIENT_PRECOMMIT")"
fi
if [[ "$AMBIENT_PRECOMMIT_AFTER" == "$AMBIENT_PRECOMMIT_BEFORE" ]]; then
  _pass "ambient hooks dir's pre-commit symlink is unchanged by these install runs (before: '$AMBIENT_PRECOMMIT_BEFORE', after: '$AMBIENT_PRECOMMIT_AFTER')"
else
  _fail "ambient hooks dir's pre-commit symlink CHANGED (sandbox failed): before '$AMBIENT_PRECOMMIT_BEFORE', after '$AMBIENT_PRECOMMIT_AFTER'"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
