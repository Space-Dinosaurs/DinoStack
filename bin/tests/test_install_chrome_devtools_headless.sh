#!/usr/bin/env bash
# Purpose: Drive the real .claude/install.sh against a scratch HOME and assert
#          the chrome-devtools MCP registration it writes launches Chrome
#          headless on an isolated profile (U1), and that an operator whose
#          registration predates those flags is migrated rather than
#          short-circuited as "already configured" (U3).
#
#          The R2 cases, each a separate install run:
#            V1  - no prior chrome-devtools registration  -> entry created with
#                  --headless and --isolated
#            V2  - prior registration, operator accepts  -> args gain the flags;
#                  every sibling key of that entry, every other mcpServers
#                  entry, and every other top-level key is byte-identical
#            V1b - prior registration, operator declines -> the config file is
#                  byte-identical (cmp, not a parse-and-compare), paired with a
#                  positive assertion that the install reached the migration
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
#            V5  - a canonical entry driven straight at the extracted writer ->
#                  both flags are appended; an entry already carrying one of
#                  them gains only the other; one carrying both is left
#                  byte-identical rather than gaining a second copy
#            V6  - a registration that connects to a browser the operator
#                  already runs (--browser-url, --ws-endpoint, the camelCase
#                  spelling, and the -u alias) -> reported by name, no prompt
#                  and no write, because appending the flags there is what
#                  makes the server refuse to start; the report has to name
#                  --headless and the class it does not apply to, since it is
#                  read only where the server launches Chrome itself
#            V7  - a top-level JSON document that is not an object (array,
#                  string, number, null) -> named and skipped, never replaced
#            V8  - a JSON document deep enough to blow the decoder's recursion
#                  limit -> named as unreadable, with no traceback reaching the
#                  install output
#            V9  - a registration whose args do not name chrome-devtools-mcp
#                  (three shapes: no args key, an empty args list, a bare {}
#                  entry) -> the migration's args append would write the flags
#                  alone, a registration that cannot launch, so the state is
#                  reported by name and the file left byte-identical
#            V10 - the sibling mcp-atlassian block against a config whose
#                  mcpServers is an array -> the install still completes, the
#                  shape is named, and the array is not clobbered
#            V11 - the sibling mcp-atlassian writer on a run whose only file
#                  write is that one -> the operator's non-ASCII value and
#                  unrelated keys survive byte-for-byte, the file's mode is
#                  carried over, and no temp file is left behind
#            V12 - that writer killed inside its write window -> the operator's
#                  config is still byte-identical, because the write lands in a
#                  temp file and os.replace instead of truncating the target
#                  in place
#            V13 - four spellings of flags the migration cannot safely edit
#                  (--no-isolated, --BROWSER-URL=, --isolated=1, and
#                  --no-headless, the negation of the flag it writes) -> each
#                  left alone and reported. Three of the four were migrated
#                  before: the withdrawn flag list compared spellings, so a
#                  negation, a case variant and a negated own flag all slipped
#                  it. The safety rule is now the set of options the migration
#                  writes or reads, matched by normalized option name, so the
#                  case asserts the generality rather than any one spelling
#            V14 - an option the migration no longer writes or reads
#                  (--user-data-dir in its `=` and separate-token spellings,
#                  the --userDataDir camel spelling, and --channel either way)
#                  -> reported by name and left byte-identical. Nothing falls
#                  out of the option set shrinking: an argument outside it is
#                  the same refusal it always was, so an entry an older install
#                  pinned is not migrated and not damaged
#            V14b - the writer's own copy of the option-name rule, driven at the
#                  extracted writer, whose copy is what would do the appending:
#                  an entry spelling --headless the way the server ignores
#                  (--Headless) is refused there too
#            V15 - the shipped form: an entry carrying --headless and
#                  --isolated classifies "already configured" and is left
#                  byte-identical
#            V16 - --headless=false, the flag this migration writes spelled with
#                  a value -> reported and left alone, never called "already
#                  configured (headless)". The server accepts it (rc 0) and
#                  opens the window, so the report the operator got was the
#                  opposite of their state. Both flags are bare, so the same
#                  rule refuses --isolated=false
#            V17 - an entry carrying only one of the two flags -> migrated to
#                  the other alone, so the append is per-flag rather than a
#                  fixed pair
#            V18 - the option-name rule against the server's own reader. A case
#                  variant the server ignores (--Headless, --HEADLESS), a
#                  single-dash short-flag bundle (-headless) and an
#                  underscore-only name (--user_data_dir) are left alone and
#                  reported, because the server reads none of them as the
#                  option they name
#            plus the two V4 cases for the new rules, driven at the extracted
#            writer, whose own copies of them are what would do the appending
#
#          The ae_confirm prompt reads /dev/tty, so each case runs under a real
#          pseudo-terminal (python3 pty.fork) with the answer written once the
#          prompt text is observed. Every other prompt in install.sh is seeded
#          away (skill_auto_load key, permissions.defaultMode, env
#          AGENT_BROWSER_IDLE_TIMEOUT_MS, the five CLI_TOOLS on PATH, --mode and
#          --no-identity flags), so exactly one prompt is live per run - see the
#          seed list below. The container-shape fixture is the exception: its
#          mcpServers is a list, so the atlassian block's own key check finds
#          nothing and prompts, and that prompt gets its own seeded answer.
#
#          Mutation coverage (each mutation is run, not merely named):
#            (a) drop the --headless append           -> V1 reddens
#            (al) drop the --isolated append          -> V1 and V17 redden
#            (am) point the current-check at the option set the migration used to
#                write -> V15 reddens
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
#            (o) collapse a non-object top level into "absent" -> V7 reddens
#            (p) drop RecursionError from the classifier's except tuple
#                -> V8 reddens
#            (q) drop that except clause and the classifier's 2>/dev/null
#                -> V8 reddens on the traceback assertion itself
#            (s) disable the mcp-atlassian writer's mcpServers guard -> V10
#                reddens
#            (t) drop the mcp-atlassian exit-status capture -> V10 reddens
#            (u) collapse the classifier's unaccounted-argument state into
#                "stale" (the pre-fix catch-all the withdrawn flag list was
#                bolted onto) -> V6 reddens, and V13 reddens on a spelling that
#                list never held
#            (v) disable the writer's foreign-argument guard -> V4's conflict
#                case reddens
#            (w) collapse an entry that does not name the package into "stale"
#                (the pre-fix catch-all) -> V9 reddens
#            (x) disable the writer's package guard -> V4's foreign cases
#                redden
#            (y) drop ensure_ascii=False from the mcp-atlassian writer -> V11
#                reddens
#            (z) drop the mcp-atlassian writer's mode carry-over -> V11 reddens
#            (aa) restore the pre-fix in-place write (open(target, "w")) in
#                the mcp-atlassian writer -> V12 reddens
#            (ab) drop both way-out lines of the foreign-argument report, which
#                name --headless and the classes it does not apply to -> V13
#                reddens
#            (ac) case-fold an option name that carries no dash, restoring the
#                pre-fix normalization -> V18 reddens on a case variant the
#                server ignores, and V14b reddens on the writer's own copy of
#                that rule (the two are separate blocks and can drift)
#            (ae) fold a bare flag spelled with a value back to the option name
#                (the pre-fix reading of --headless=false) -> V16 reddens, and
#                so does the writer's own copy of it (V4's --headless=false
#                case)
#            (af) restore the withdrawn way-out sentence that told an
#                --isolated operator to drop --isolated -> the way-out case
#                reddens
#            (ag) drop the way-out line covering --headless=false -> V16
#                reddens
#            (aj) let a single-dash token through as a long option -> V18
#                reddens on -headless, which the server reads as a bundle of
#                single-letter flags
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
#                git shim below can escape its sandbox and mutate the live
#                primary checkout's pre-commit hook symlink - see Seed 5.
#
# Performance: 72 install runs per invocation (40 of the cases plus 32 mutation
#              runs of the installer), counted by shimming every `bash
#              <install.sh|.mutation-install-*.sh> --mode=...` invocation on
#              PATH. On a warm tree that run takes ~245 s. The
#              concurrent-writer, V4, V5, V12, V14b and the (c)/(k)/(l)/(m)/
#              (v)/(x)/(aa) mutations run the extracted writer instead, at
#              negligible cost, as do the writer halves of (ac) and (ae) - none
#              of those costs an install run.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_DIR/.claude/install.sh"
MUTATION_GLOB="$REPO_DIR/.claude/.mutation-install-$$-*"

# The package an entry has to name and the options the migration writes or
# reads - both read out of the installer rather than retyped. install.sh passes
# them to both python blocks as arguments and the writer blocks extracted below
# take them the same way, so retyping them here would let the V4/V6/V9
# assertions pass against a set the installer does not use.
CD_MCP_PACKAGE="$(sed -n 's/^CD_MCP_PACKAGE="\(.*\)"$/\1/p' "$INSTALL_SH")"
CD_MCP_OPTIONS="$(sed -n 's/^CD_MCP_OPTIONS="\(.*\)"$/\1/p' "$INSTALL_SH")"
for pair in CD_MCP_PACKAGE CD_MCP_OPTIONS; do
  if [[ -z "${!pair}" ]]; then
    echo "FAIL: could not read $pair out of $INSTALL_SH" >&2
    exit 1
  fi
done

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
# Seed 5 (git-level sandbox): running the real .claude/install.sh from an
# isolation worktree calls scripts/lib/precommit.sh's resolve_git_hooks_dir(),
# which shells out to `git -C "$REPO_DIR" rev-parse --git-path hooks`. From a
# worktree that resolves to the primary checkout's common .git/hooks dir, so an
# unsandboxed run re-points the live primary checkout's .git/hooks/pre-commit
# symlink at this disposable worktree. This shim (copied verbatim from
# bin/tests/test_install_worktree_isolation_spawn_guard.sh, which the plan's
# V14 names as the fixture to reuse) answers only that exact query and passes
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

# Snapshot the ambient git hooks dir (resolved through the real, unsandboxed
# git) before any install run, so the end-of-test assertion can prove the shim
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
# Seeds 1, 4 and 5, the prompt-suppression seeds that live under $HOME.
#   Seed 1: agentic-engineering.json carrying skill_auto_load -> suppresses
#           ae_write_mode's /dev/tty prompt (gated on the key being absent).
#   Seed 4: settings.json with permissions.defaultMode already
#           bypassPermissions -> suppresses the permissions tty_input prompt.
#   Seed 5: the same settings.json carrying AGENT_BROWSER_IDLE_TIMEOUT_MS ->
#           suppresses the agent-browser daemon idle-timeout prompt, which is
#           offered only when its key is absent. Any value suppresses it, so
#           this is the state a machine that has already run the installer is
#           in; without it every case here blocks on the prompt, because the
#           pty driver has no needle for it and waits out its own deadline.
# ---------------------------------------------------------------------------
seed_home() {
  local home="$1"
  mkdir -p "$home/.claude"
  printf '{"skill_auto_load": false}\n' > "$home/.claude/agentic-engineering.json"
  printf '{"permissions":{"defaultMode":"bypassPermissions"},"env":{"AGENT_BROWSER_IDLE_TIMEOUT_MS":"1800000"}}\n' > "$home/.claude/settings.json"
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

# The args the installer is expected to write for a migrated entry.
expected_args_json() {
  printf '["chrome-devtools-mcp@latest", "--headless", "--isolated"]'
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
  # R6 for the second capability this change removes: --isolated's cost needs its
  # own one-step way back, distinct from the sentence that restores the window.
  if ! grep -q "remove --isolated from its args" <<< "$out"; then
    _fail "V1: the profile-persistence way back was not stated at the accept prompt"
    return 1
  fi

  python3 - "$home/.claude.json" "$(expected_args_json)" <<'PYEOF'
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

  # Positive assertion that the stale entry was detected rather than
  # short-circuited: the pre-U3 code printed the message asserted absent below.
  if ! grep -q "Update the existing chrome-devtools MCP" <<< "$out"; then
    _fail "V2: the migration prompt was never reached"
    return 1
  fi
  if grep -q "chrome-devtools MCP already configured" <<< "$out"; then
    _fail "V2: install reported the entry as already configured"
    return 1
  fi

  # R6: the capability the change removes must be stated where the operator is
  # asked to accept it, together with a one-step way back. Ordering is the
  # load-bearing half - the same sentence printed after the prompt would not
  # inform the decision the prompt asks for.
  local trade_off_at prompt_at profile_back_at
  trade_off_at="$(grep -n "remove --headless from its args" <<< "$out" | head -1 | cut -d: -f1)"
  profile_back_at="$(grep -n "remove --isolated from its args" <<< "$out" | head -1 | cut -d: -f1)"
  prompt_at="$(grep -n "Update the existing chrome-devtools MCP" <<< "$out" | head -1 | cut -d: -f1)"
  if [[ -z "$trade_off_at" || -z "$prompt_at" || "$trade_off_at" -ge "$prompt_at" ]]; then
    _fail "V2: the trade-off and the way back are not stated before the accept prompt"
    return 1
  fi
  # The persistence way back is a second cost, so it has to be stated before the
  # prompt too rather than only somewhere in the output.
  if [[ -z "$profile_back_at" || "$profile_back_at" -ge "$prompt_at" ]]; then
    _fail "V2: the profile-persistence way back is not stated before the accept prompt"
    return 1
  fi

  python3 - "$home/.claude.json" "$TMP_ROOT/v2-before.json" "$(expected_args_json)" <<'PYEOF'
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
# with the flags alone. For the string form that yields `npx --headless
# --isolated`, a registration that cannot launch.
#
# A fourth fixture is the opposite case: a registration that is well formed but
# connects to a browser the operator already runs. Its browser connection is an
# argument this migration does not write, so the entry is reported and left
# alone rather than gaining two flags the server would never read there.
# ---------------------------------------------------------------------------
write_conflict_config() {
  local path="$1"
  shift
  local args_json
  args_json="$(printf '"chrome-devtools-mcp@latest"'; printf ', "%s"' "$@")"
  cat > "$path" <<EOF
{
  "numStartups": 42,
  "mcpServers": {
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "args": [
        $args_json
      ],
      "env": {}
    },
    "mcp-atlassian": {}
  }
}
EOF
}

write_shape_config() {
  local path="$1" shape="$2"
  case "$shape" in
  conflict)
    write_conflict_config "$path" "--browser-url=http://127.0.0.1:9222"
    ;;
  headless-false)
    # The flag this migration writes, spelled with the value that asks for the
    # window.
    write_conflict_config "$path" "--headless=false"
    ;;
  isolated-false)
    # The other bare flag, spelled the same way.
    write_conflict_config "$path" "--isolated=false"
    ;;
  user-data-dir)
    # The option an older install pinned the profile root with, which this
    # migration no longer writes or reads.
    write_conflict_config "$path" "--headless" "--user-data-dir=/tmp/legacy-profile"
    ;;
  channel)
    # Its sibling, likewise out of the option set now.
    write_conflict_config "$path" "--headless" "--channel=canary"
    ;;
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
  no-args)
    cat > "$path" <<'EOF'
{
  "numStartups": 42,
  "mcpServers": {
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "env": {}
    },
    "mcp-atlassian": {}
  }
}
EOF
    ;;
  empty-args)
    cat > "$path" <<'EOF'
{
  "numStartups": 42,
  "mcpServers": {
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "args": [],
      "env": {}
    },
    "mcp-atlassian": {}
  }
}
EOF
    ;;
  empty-entry)
    cat > "$path" <<'EOF'
{
  "numStartups": 42,
  "mcpServers": {
    "chrome-devtools": {},
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
  conflict | headless-false | isolated-false | user-data-dir | channel)
    printf 'passes an argument this installer does not write' ;;
  no-args | empty-args | empty-entry) printf 'args do not name the package this installer writes (%s)' "$CD_MCP_PACKAGE" ;;
  *) printf "the chrome-devtools entry has an args value that is not a list of strings" ;;
  esac
}

# ---------------------------------------------------------------------------
# V9: a registration whose args do not invoke the package. The migration's edit
# is an args append, so on one of these it writes the flags alone - `npx
# --headless --isolated`, a registration that cannot launch - and the
# entry then classifies current, so the installer never offers again. Before
# this fix all three classified "stale", the catch-all else of a chain whose
# other members were absent, a refused-flag state and current.
# ---------------------------------------------------------------------------
case_foreign_left_alone() {
  local script="$1" shape="$2"
  local home="$TMP_ROOT/foreign-$shape-home"
  local before="$TMP_ROOT/foreign-$shape-before.json"
  local out rc
  mkdir -p "$home"
  seed_home "$home"
  write_shape_config "$home/.claude.json" "$shape"
  cp "$home/.claude.json" "$before"

  # Both migration prompts are seeded so a mutated installer that goes back to
  # offering one cannot hang the pty for the whole driver deadline. The
  # unmutated run reaches neither.
  out="$(run_install "$script" "$home" '[["Configure chrome-devtools MCP", "y\n"], ["Update the existing chrome-devtools MCP", "y\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "$shape: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  # Checked before the naming assertion: the pre-fix behaviour was to classify
  # this as stale and offer the migration prompt, and that is the defect.
  if grep -q "Configure chrome-devtools MCP\|Update the existing chrome-devtools MCP" <<< "$out"; then
    _fail "$shape: an entry the migration cannot edit was offered a prompt"
    return 1
  fi
  if ! grep -qF "$(shape_needle "$shape")" <<< "$out"; then
    _fail "$shape: the entry that does not name the package was not reported"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "$shape: the unmigratable entry was modified (expected byte-identical)"
    return 1
  fi
  return 0
}

case_foreign_no_args() { case_foreign_left_alone "$1" no-args; }
case_foreign_empty_args() { case_foreign_left_alone "$1" empty-args; }
case_foreign_empty_entry() { case_foreign_left_alone "$1" empty-entry; }

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
# pre-rename re-stat is microseconds, so this runs the shipped writer block
# (extracted from install.sh, never retyped here) with one injected
# `time.sleep` to hold the window open, and rewrites the file from another
# process while it is open.
# ---------------------------------------------------------------------------
# extract_writer <source-install-sh> <output.py> - the source is a parameter
# because the mutation harness runs the extracted writer for a mutated copy.
extract_writer() {
  # Stops before the heredoc's terminating PYEOF, which is shell syntax, not
  # Python: leaving it in makes the extracted block raise NameError at its last
  # line, so an unmutated-looking run would fail on a traceback instead of on
  # the guard under test.
  awk '
    /^import json, os, re, stat, sys, tempfile$/ { f=1 }
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
    $0 == "import json, os, re, stat, sys, tempfile" { print; print "import time"; next }
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

  ( python3 "$writer" "$home/.claude.json" "$CD_MCP_PACKAGE" "$CD_MCP_OPTIONS" 2>"$err" ) &
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
  ( python3 "$py" "$home/.claude.json" "$CD_MCP_PACKAGE" "$CD_MCP_OPTIONS" 2>"$err" )
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
case_writer_conflict() { case_writer_refuses "$1" conflict; }
case_writer_headless_false() { case_writer_refuses "$1" headless-false; }
case_writer_isolated_false() { case_writer_refuses "$1" isolated-false; }
case_writer_user_data_dir() { case_writer_refuses "$1" user-data-dir; }
case_writer_channel() { case_writer_refuses "$1" channel; }
case_writer_no_args() { case_writer_refuses "$1" no-args; }
case_writer_empty_args() { case_writer_refuses "$1" empty-args; }
case_writer_empty_entry() { case_writer_refuses "$1" empty-entry; }

# ---------------------------------------------------------------------------
# V5: the append itself, driven straight at the extracted writer, one entry per
# row. Both flags are bare and independent, so the append is per-flag rather
# than a fixed pair: an entry carrying one of them must gain only the other,
# and one carrying both must come back byte-identical rather than with a second
# copy of each. The classifier never reaches the second and third rows (it
# short-circuits on "current" and on "stale" it would append the missing flag
# anyway), so this is the case that holds the writer's own append to account.
# ---------------------------------------------------------------------------
case_writer_appends() {
  local script="$1"
  local py="$TMP_ROOT/writer-append.py"
  local home="$TMP_ROOT/writer-append-home"
  local got want rc entry extra present
  mkdir -p "$home"
  if ! extract_writer "$script" "$py"; then
    return 1
  fi
  for entry in \
    '[]|["--headless", "--isolated"]' \
    '["--headless"]|["--isolated"]' \
    '["--isolated"]|["--headless"]' \
    '["--headless", "--isolated"]|[]'; do
    extra="${entry%%|*}"
    present="${entry##*|}"
    python3 - "$home/.claude.json" "$extra" <<'PYEOF'
import json, sys
path, extra = sys.argv[1], json.loads(sys.argv[2])
json.dump({
    "numStartups": 42,
    "mcpServers": {
        "chrome-devtools": {
            "type": "stdio", "command": "npx",
            "args": ["chrome-devtools-mcp@latest"] + extra, "env": {},
        },
        "mcp-atlassian": {},
    },
}, open(path, "w"), indent=2)
PYEOF
    ( HOME="$home" python3 "$py" "$home/.claude.json" "$CD_MCP_PACKAGE" "$CD_MCP_OPTIONS" ) >/dev/null 2>&1
    rc=$?
    if [[ "$rc" -ne 0 ]]; then
      _fail "writer append: the writer exited $rc on a migration target ($extra)"
      return 1
    fi
    want="$(python3 -c '
import json, sys
print(json.dumps(["chrome-devtools-mcp@latest"] + json.loads(sys.argv[1]) + json.loads(sys.argv[2])))' "$extra" "$present")"
    got="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["mcpServers"]["chrome-devtools"]["args"]))' "$home/.claude.json")"
    if [[ "$got" != "$want" ]]; then
      _fail "writer append: an entry carrying $extra migrated to the wrong args (want $want, got $got)"
      return 1
    fi
  done
  return 0
}

# ---------------------------------------------------------------------------
# V14b: the writer's own copy of the option-name rule, driven straight at the
# extracted writer. The classifier refuses a spelling the server ignores before
# the writer is ever reached, so V18 cannot exercise the writer's copy; this
# case does, because the writer's own copy is what would do the appending.
# ---------------------------------------------------------------------------
case_writer_alternate_spelling() {
  local script="$1"
  local py="$TMP_ROOT/writer-altspell.py"
  local home="$TMP_ROOT/writer-altspell-home"
  local before="$TMP_ROOT/writer-altspell-before.json"
  local rc
  mkdir -p "$home"
  if ! extract_writer "$script" "$py"; then
    return 1
  fi
  # --Headless is not the --headless option: yargs reads a long option whose
  # name carries no dash verbatim, so `.lower()` folding it would make the
  # writer append --isolated and leave the entry headed while reporting success.
  write_conflict_config "$home/.claude.json" "--Headless"
  cp "$home/.claude.json" "$before"
  ( HOME="$home" python3 "$py" "$home/.claude.json" "$CD_MCP_PACKAGE" "$CD_MCP_OPTIONS" ) >/dev/null 2>&1
  rc=$?
  if [[ "$rc" == "0" ]]; then
    _fail "writer alternate spelling: the writer accepted a spelling the server ignores"
    return 1
  fi
  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "writer alternate spelling: the writer modified an entry it refused"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# V6: a registration that connects to a browser the operator already runs must
# be left alone. Before this fix the classifier said "stale" and the writer
# exited 0 after appending, so the entry re-classified as "current" and the
# installer never offered again - with flags the server does not read there.
# ---------------------------------------------------------------------------
case_conflict_left_alone() {
  local script="$1" label="$2"
  shift 2
  local home="$TMP_ROOT/conflict-$label-home"
  local before="$TMP_ROOT/conflict-$label-before.json"
  local out rc
  mkdir -p "$home"
  seed_home "$home"
  write_conflict_config "$home/.claude.json" "$@"
  cp "$home/.claude.json" "$before"

  # A mutated installer that goes back to prompting would otherwise hang the
  # pty for the whole driver deadline, so both migration prompts are seeded.
  # The unmutated run reaches neither.
  out="$(run_install "$script" "$home" '[["Configure chrome-devtools MCP", "y\n"], ["Update the existing chrome-devtools MCP", "y\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "$label: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! grep -qF "$(shape_needle conflict)" <<< "$out"; then
    _fail "$label: the conflicting registration was not reported by name"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if grep -q "Configure chrome-devtools MCP\|Update the existing chrome-devtools MCP" <<< "$out"; then
    _fail "$label: a registration the migration cannot touch was offered a prompt"
    return 1
  fi
  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "$label: the conflicting registration was modified (expected byte-identical)"
    return 1
  fi
  # The flags are what would be appended, so their absence is asserted directly
  # rather than only through byte-identity.
  if grep -q -- "--headless\|--isolated" "$home/.claude.json"; then
    _fail "$label: the migration's flags were written alongside a browser connection"
    return 1
  fi
  # --headless is honored only where the server launches Chrome itself, so the
  # report has to name it and the class it does not apply to - an unscoped "add
  # --headless" is inert for a registration that connects to a browser already
  # running.
  if ! grep -q -- "--headless" <<< "$out"; then
    _fail "$label: the report did not name the flag that would remove the window"
    return 1
  fi
  if ! grep -q -- "--auto-connect" <<< "$out"; then
    _fail "$label: the report did not scope --headless to the class it works for"
    return 1
  fi
  return 0
}

case_conflict_browser_url() { case_conflict_left_alone "$1" browser-url "--browser-url=http://127.0.0.1:9222"; }
case_conflict_ws_endpoint() { case_conflict_left_alone "$1" ws-endpoint "--ws-endpoint=ws://127.0.0.1:9222/devtools/browser/abc"; }
case_conflict_camel() { case_conflict_left_alone "$1" camel "--browserUrl=http://127.0.0.1:9222"; }
case_conflict_alias() { case_conflict_left_alone "$1" alias "-u" "http://127.0.0.1:9222"; }

# case_foreign_args_left_alone <script> <label> <forbid> <args...>
#   The entry carries an argument the migration does not write: it is reported
#   by name, no prompt is offered, the file is byte-identical, and no new
#   profile root is written. <forbid> is a string the output must not contain
#   ("" for none), which is how a case pins a report it must never print.
#
#   Shared by the V13, V15 and V16 cases: each reports one registration the
#   migration cannot edit and must leave alone.
case_foreign_args_left_alone() {
  local script="$1" label="$2" forbid="$3"
  shift 3
  local home="$TMP_ROOT/unlisted-$label-home"
  local before="$TMP_ROOT/unlisted-$label-before.json"
  local out rc
  mkdir -p "$home"
  seed_home "$home"
  write_conflict_config "$home/.claude.json" "$@"
  cp "$home/.claude.json" "$before"

  # Both migration prompts are seeded so a mutated installer that goes back to
  # offering one cannot hang the pty for the whole driver deadline.
  out="$(run_install "$script" "$home" '[["Configure chrome-devtools MCP", "y\n"], ["Update the existing chrome-devtools MCP", "y\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "$label: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if grep -q "Configure chrome-devtools MCP\|Update the existing chrome-devtools MCP" <<< "$out"; then
    _fail "$label: a registration the migration does not write was offered a prompt"
    return 1
  fi
  if ! grep -qF "$(shape_needle conflict)" <<< "$out"; then
    _fail "$label: the registration was not reported as carrying an argument the migration does not write"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if [[ -n "$forbid" ]] && grep -qF "$forbid" <<< "$out"; then
    _fail "$label: the install reported '$forbid' for this registration"
    return 1
  fi
  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "$label: the registration was modified (expected byte-identical)"
    return 1
  fi
  # No flag is appended to an entry the migration refused, so the count is
  # compared rather than required to be zero: a fixture that carries one of
  # them already keeps exactly what it had.
  if [[ "$(grep -c -e "--headless" -e "--isolated" "$home/.claude.json")" \
        != "$(grep -c -e "--headless" -e "--isolated" "$before")" ]]; then
    _fail "$label: a flag was written beside an argument the migration does not write"
    return 1
  fi
  # The way out has to name --headless, scope it to the class it does not work
  # for, and say that --isolated can stay: the server takes `--headless
  # --isolated` (rc 0, v1.10.1), so the throwaway profile is not what has to go.
  if ! grep -q -- "--headless" <<< "$out"; then
    _fail "$label: the report did not name the flag that would remove the window"
    return 1
  fi
  if ! grep -q -- "--auto-connect" <<< "$out"; then
    _fail "$label: the report did not scope --headless to the class it works for"
    return 1
  fi
  if ! grep -qF "adding --headless beside --isolated" <<< "$out"; then
    _fail "$label: the report did not say that --isolated can stay under --headless"
    return 1
  fi
  # The negation of the flag the migration writes is a spelling of its own, so
  # the way out has to cover it too.
  if ! grep -qF "replacing that argument with --headless" <<< "$out"; then
    _fail "$label: the report did not cover a --headless=false spelling"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# V13: the same refusal, driven by spellings of a flag the migration cannot
# safely edit. The list this migration used to carry is gone - an entry is a
# migration target only when every one of its args is the package or an option
# the migration writes - so the property under test is the generality rather
# than any one spelling. `--isolated=1` is the control: its first token was in
# that list, so it was refused before and still must be.
# ---------------------------------------------------------------------------
case_conflict_unlisted_one() {
  local script="$1" label="$2"
  shift 2
  case_foreign_args_left_alone "$script" "$label" "" "$@"
}

case_conflict_unlisted_spelling() {
  local script="$1"
  # The reported instance; a case variant of a different option that the server
  # also refuses to combine with the pin; a boolean written as a value, which
  # the withdrawn list did catch; and the negation of the flag this migration
  # writes, which it used to append --headless beside, overriding the
  # operator's own --no-headless.
  case_conflict_unlisted_one "$script" no-isolated --no-isolated || return 1
  case_conflict_unlisted_one "$script" case-variant --BROWSER-URL=http://127.0.0.1:9222 || return 1
  case_conflict_unlisted_one "$script" boolean-value --isolated=1 || return 1
  case_conflict_unlisted_one "$script" negated-headless --no-headless || return 1
  return 0
}

# ---------------------------------------------------------------------------
# V14: the options an older install wrote and this migration no longer does.
# --user-data-dir (its `=` and separate-token spellings, and the --userDataDir
# camel one the server reads as the same option) and --channel are outside the
# option set now, so an entry carrying either gets the same refusal any other
# unknown argument gets: reported by name, no prompt, left byte-identical. The
# entry is not migrated and not damaged, and the report names the argument that
# stopped it.
# ---------------------------------------------------------------------------
case_former_option_left_alone() {
  local script="$1"
  case_conflict_unlisted_one "$script" former-user-data-dir --headless --user-data-dir=/tmp/legacy-profile || return 1
  case_conflict_unlisted_one "$script" former-user-data-dir-token --headless --user-data-dir /tmp/legacy-profile || return 1
  case_conflict_unlisted_one "$script" former-user-data-dir-camel --headless --userDataDir=/tmp/legacy-profile || return 1
  case_conflict_unlisted_one "$script" former-channel --headless --channel=canary || return 1
  case_conflict_unlisted_one "$script" former-channel-token --headless --channel canary || return 1
  return 0
}

# ---------------------------------------------------------------------------
# V15: the form this migration writes. An entry already carrying both flags is
# "already configured": no prompt, and the file byte-identical. The pair is not
# what makes it current - the classifier asks for each flag on its own - so this
# is the case that reddens when the current-check is left pointing at the option
# set this migration used to write.
# ---------------------------------------------------------------------------
case_current_form() {
  local script="$1" out rc
  local home="$TMP_ROOT/current-home"
  local before="$TMP_ROOT/current-before.json"
  mkdir -p "$home"
  seed_home "$home"
  write_conflict_config "$home/.claude.json" "--headless" "--isolated"
  cp "$home/.claude.json" "$before"

  # Both migration prompts are seeded so a mutated installer that goes back to
  # offering one cannot hang the pty for the whole driver deadline. The
  # unmutated run reaches neither.
  out="$(run_install "$script" "$home" '[["Configure chrome-devtools MCP", "y\n"], ["Update the existing chrome-devtools MCP", "y\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "V15: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! grep -q "chrome-devtools MCP already configured" <<< "$out"; then
    _fail "V15: an entry carrying --headless and --isolated was not read as already configured"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if grep -q "Configure chrome-devtools MCP\|Update the existing chrome-devtools MCP" <<< "$out"; then
    _fail "V15: an already-configured registration was offered a prompt"
    return 1
  fi
  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "V15: an already-current registration was rewritten"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# V16: a value on a flag this migration writes bare. Both flags are bare, so
# --headless=false and --isolated=false are each a spelling the migration does
# not write: the server accepts them (rc 0) and opens the window, so calling
# such an entry "already configured (headless)" is the one report it must never
# print. The first fixture is the sharp one: beside --isolated, a folded
# --headless=false is exactly the pair the current-check looks for, so before
# this fix that entry was reported configured and never offered the migration.
# ---------------------------------------------------------------------------
case_valued_flag_left_alone() {
  local script="$1" forbid="already configured (headless)"
  case_foreign_args_left_alone "$script" headless-false-isolated "$forbid" \
    "--headless=false" "--isolated" || return 1
  case_foreign_args_left_alone "$script" headless-false "$forbid" \
    "--headless=false" || return 1
  case_foreign_args_left_alone "$script" isolated-false "$forbid" \
    "--isolated=false" || return 1
  return 0
}

# ---------------------------------------------------------------------------
# V17: the append is per-flag. An entry carrying only one of the two is still a
# migration target and gains only the other - a check that called either flag
# alone "current" would leave that entry unmigrated, and an unconditional pair
# append would leave it carrying a duplicate.
# ---------------------------------------------------------------------------
case_partial_migration() {
  local script="$1" out rc got want
  local home="$TMP_ROOT/partial-home"
  mkdir -p "$home"
  seed_home "$home"
  write_conflict_config "$home/.claude.json" "--headless"
  cp "$home/.claude.json" "$TMP_ROOT/partial-before.json"

  out="$(run_install "$script" "$home" '[["Update the existing chrome-devtools MCP", "y\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "V17: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! grep -q "Update the existing chrome-devtools MCP" <<< "$out"; then
    _fail "V17: an entry carrying one of the two flags was not offered the migration"
    tail -20 <<< "$out" >&2
    return 1
  fi
  want='["chrome-devtools-mcp@latest", "--headless", "--isolated"]'
  got="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["mcpServers"]["chrome-devtools"]["args"]))' "$home/.claude.json")"
  if [[ "$got" != "$want" ]]; then
    _fail "V17: the missing flag was not appended on its own (want $want, got $got)"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# V18: the option-name rule against the server's own reader. The server is yargs
# (v1.10.1): it reads one leading dash as a bundle of single-letter flags, and
# takes a long option's spelling verbatim when that name carries no dash - so
# `--Headless` and `--HEADLESS` are unknown flags to it (it prints "Unknown
# arguments: --Headless" and launches headed), `-headless` is the single-letter
# flags h-e-a-d-l-e-s-s, and `--user_data_dir` is not the --user-data-dir option
# either. Folding case unconditionally read the first two as the headless option
# this migration writes, so an entry carrying one was migrated without ever
# gaining the window-removing flag while the installer reported it configured -
# the report this migration must never print for an entry that still opens the
# window.
# ---------------------------------------------------------------------------
case_option_name_matches_server() {
  local script="$1"
  case_foreign_args_left_alone "$script" case-variant-headless "" "--Headless" || return 1
  case_foreign_args_left_alone "$script" upper-case-headless "" "--HEADLESS" || return 1
  case_foreign_args_left_alone "$script" short-flag-bundle "" "-headless" || return 1
  case_foreign_args_left_alone "$script" underscore-name "" "--user_data_dir=/tmp/underscore-profile" || return 1
  return 0
}

# The way-out sentence, asserted on one representative foreign entry: every
# foreign entry gets the same report, so the entry does not matter. A named
# function because expect_case_fails passes a single argument to the case.
case_way_out_advice() {
  case_conflict_unlisted_one "$1" way-out --isolated --channel=canary
}

# ---------------------------------------------------------------------------
# V7: the four non-object top-level documents json.load accepts. Each one
# classified "absent" before this fix - only FileNotFoundError and a missing
# entry reached that state - so the operator was offered the create prompt for
# a file the writer then refused, an edit that could not be made.
# ---------------------------------------------------------------------------
write_top_level_config() {
  local path="$1" kind="$2"
  case "$kind" in
  array) printf '["legacy-server-A", "legacy-server-B"]\n' > "$path" ;;
  string) printf '"a config written as a bare string"\n' > "$path" ;;
  number) printf '42\n' > "$path" ;;
  null) printf 'null\n' > "$path" ;;
  esac
}

case_top_level_not_object() {
  local script="$1" kind="$2"
  local home="$TMP_ROOT/toplevel-$kind-home"
  local before="$TMP_ROOT/toplevel-$kind-before.json"
  local out rc
  mkdir -p "$home"
  seed_home "$home"
  write_top_level_config "$home/.claude.json" "$kind"
  cp "$home/.claude.json" "$before"

  # A non-object top level also defeats the atlassian block's own key check, so
  # that prompt fires and needs an answer.
  out="$(run_install "$script" "$home" '[["Configure chrome-devtools MCP", "y\n"], ["mcp-atlassian MCP", "n\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "$kind: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  # Checked before the naming assertion: the pre-fix behaviour was to classify
  # this as absent and offer the create prompt, and that is the defect. The
  # prompt message is what a mutation to the old classification reddens.
  if grep -q "Configure chrome-devtools MCP" <<< "$out"; then
    _fail "$kind: a file the writer cannot edit was offered the registration prompt"
    return 1
  fi
  if ! grep -qF "the file's top level is not a JSON object" <<< "$out"; then
    _fail "$kind: a non-object top level was not named"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "$kind: the non-object document was modified (expected byte-identical)"
    return 1
  fi
  return 0
}

case_top_level_array() { case_top_level_not_object "$1" array; }
case_top_level_string() { case_top_level_not_object "$1" string; }
case_top_level_number() { case_top_level_not_object "$1" number; }
case_top_level_null() { case_top_level_not_object "$1" null; }

# ---------------------------------------------------------------------------
# V8: a document deep enough to exhaust CPython's default recursion limit
# inside json.load. Two properties are asserted: the state is a named skip
# rather than a guess, and no traceback reaches the install output - a
# redirection written on an assignment does not apply to the command
# substitution inside it, so the classifier's stderr has to be redirected on
# the python command itself.
# ---------------------------------------------------------------------------
write_deep_json_config() {
  python3 - "$1" <<'PYEOF'
import sys
with open(sys.argv[1], "w") as f:
    f.write("[" * 200000 + "]" * 200000)
PYEOF
}

case_deeply_nested() {
  local script="$1"
  local home="$TMP_ROOT/deep-home"
  local before="$TMP_ROOT/deep-before.json"
  local out rc
  mkdir -p "$home"
  seed_home "$home"
  write_deep_json_config "$home/.claude.json"
  cp "$home/.claude.json" "$before"

  out="$(run_install "$script" "$home" '[["Configure chrome-devtools MCP", "y\n"], ["mcp-atlassian MCP", "n\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "deep: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  # Checked before the state assertion: the mutation that drops the
  # classifier's stderr redirection turns this fixture's exception into a
  # traceback on the install output, and that is the property under test.
  if grep -q "Traceback (most recent call last)" <<< "$out"; then
    _fail "deep: a traceback reached the install output"
    return 1
  fi
  if ! grep -qF "could not be read as JSON" <<< "$out"; then
    _fail "deep: a document the decoder cannot parse was not reported as unreadable"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "deep: the unreadable document was modified"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# V10: the sibling mcp-atlassian block. Its writer had no shape guard, so a
# config whose mcpServers is an array raised an uncaught TypeError - and
# because that python was not run as a tolerated condition, the non-zero exit
# aborted the whole install under `set -euo pipefail`.
# ---------------------------------------------------------------------------
case_atlassian_container() {
  local script="$1"
  local home="$TMP_ROOT/atl-container-home"
  local before="$TMP_ROOT/atl-container-before.json"
  local out rc
  mkdir -p "$home"
  seed_home "$home"
  write_shape_config "$home/.claude.json" container
  cp "$home/.claude.json" "$before"

  out="$(run_install "$script" "$home" '[["mcp-atlassian MCP", "y\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "atlassian container: a malformed config aborted the install (exit $rc)"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if grep -q "Traceback (most recent call last)" <<< "$out"; then
    _fail "atlassian container: a traceback reached the install output"
    return 1
  fi
  # Checked before the message assertion: a writer that coerces the container
  # instead of refusing clobbers the operator's server list, and that is the
  # damage under test - the message only reports it.
  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "atlassian container: the refused container was modified"
    return 1
  fi
  if ! grep -qF "mcp-atlassian MCP registration left unchanged" <<< "$out"; then
    _fail "atlassian container: the refusal was not reported as a no-op"
    tail -20 <<< "$out" >&2
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# V11/V12: the same atlassian writer, held to the two properties the
# chrome-devtools writer got in this branch. V11 is an installer run in which
# that writer is the only thing that writes: the write adds one key, so every
# unrelated byte of the operator's file rides through the serializer with it.
# V12 kills the writer inside its write window, which is where an in-place
# write would leave the operator's file truncated.
# ---------------------------------------------------------------------------
# The non-ASCII value is load-bearing for the same reason it is in the
# chrome-devtools fixture: json.dump's default ensure_ascii=True rewrites every
# non-ASCII string in the file as \uXXXX escapes, so an ASCII-only fixture
# cannot tell a surgical edit from a whole-file re-encoding.
#
# The chrome-devtools entry is already current, so the block above
# short-circuits and the atlassian write is the run's only file write. It is
# also what leaves the atlassian confirm as the run's only live prompt:
# ae_confirm reads one character, so an earlier answer's trailing newline stays
# in the tty buffer and is what the next prompt reads.
atlassian_write_fixture() {
  cat > "$1" <<'EOF'
{
  "numStartups": 42,
  "statusLineText": "café · waiting",
  "mcpServers": {
    "chrome-devtools": {
      "type": "stdio",
      "command": "npx",
      "args": [
        "chrome-devtools-mcp@latest",
        "--headless",
        "--isolated"
      ],
      "env": {}
    }
  }
}
EOF
  chmod 644 "$1"
}

case_atlassian_write() {
  local script="$1"
  local home="$TMP_ROOT/atl-write-home"
  local before="$TMP_ROOT/atl-write-before.json"
  local out rc
  mkdir -p "$home"
  seed_home "$home"
  atlassian_write_fixture "$home/.claude.json"
  cp "$home/.claude.json" "$before"

  # One live prompt: the sibling block is the case under test.
  out="$(run_install "$script" "$home" '[["mcp-atlassian MCP", "y\n"]]')"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    _fail "atlassian write: install exited $rc"
    tail -20 <<< "$out" >&2
    return 1
  fi
  if ! grep -qF "mcp-atlassian MCP configured" <<< "$out"; then
    _fail "atlassian write: the writer never ran"
    tail -20 <<< "$out" >&2
    return 1
  fi

  python3 - "$before" "$home/.claude.json" "$home" <<'PYEOF'
import json, os, stat, sys

before_path, after_path, home = sys.argv[1:4]
after = open(after_path, "rb").read()
assert "café · waiting".encode("utf-8") in after, \
    "the operator's non-ASCII value was re-encoded"
assert b"\\u00e9" not in after, "the file was re-serialized with ascii escapes"
data = json.loads(after.decode("utf-8"))
assert data["numStartups"] == 42, data
assert data["mcpServers"]["mcp-atlassian"] == {
    "type": "stdio", "command": "uvx", "args": ["mcp-atlassian"], "env": {}}, \
    data["mcpServers"]
assert data["mcpServers"]["chrome-devtools"]["args"] == [
    "chrome-devtools-mcp@latest", "--headless", "--isolated"], data["mcpServers"]
assert stat.S_IMODE(os.stat(after_path).st_mode) == 0o644, \
    oct(stat.S_IMODE(os.stat(after_path).st_mode))
leftovers = sorted(n for n in os.listdir(home) if n.startswith(".claude.json."))
assert not leftovers, leftovers
PYEOF
  if [[ $? -ne 0 ]]; then
    _fail "atlassian write: the write damaged the operator's config"
    return 1
  fi
  return 0
}

# extract_atlassian_writer <source-install-sh> <output.py>
# The anchor is this writer's own import line: the chrome-devtools writer
# imports `re` too (it normalizes option names) and no longer shares it.
extract_atlassian_writer() {
  awk '
    /^import json, os, stat, sys, tempfile$/ { f=1 }
    f && /^PYEOF$/ { exit }
    f { print }
  ' "$1" > "$2"
  if ! grep -q "mcp-atlassian" "$2" || ! grep -q "os.replace(tmp_path, target)" "$2"; then
    _fail "could not extract the shipped mcp-atlassian writer block from $1 (anchor moved?)"
    return 1
  fi
  if ! python3 -c 'import sys; compile(open(sys.argv[1]).read(), sys.argv[1], "exec")' "$2"; then
    _fail "the extracted mcp-atlassian writer block from $1 is not valid Python"
    return 1
  fi
  return 0
}

# Holds the writer's write window open so the case can kill it inside that
# window. The anchor is the temp-file write, which is the last line before the
# content lands, so a sleep injected after it is unambiguously inside the
# window for both the shipped writer and the in-place one mutation (aa)
# restores.
inject_atlassian_delay() {
  awk '
    /^import json, os, stat, sys, tempfile$/ { print; print "import time"; next }
    $0 == "        with os.fdopen(fd, \"w\", encoding=\"utf-8\") as f:" {
      print; print "            time.sleep(3)"; next }
    { print }
  ' "$1" > "$2"
  if ! grep -q "time.sleep(3)" "$2"; then
    _fail "could not inject the delay into $1 (anchor line moved?)"
    return 1
  fi
  return 0
}

case_atlassian_interrupted() {
  local writer="$1"
  local home before err
  local pid tries=0 entered=0
  # A directory per invocation, never a fixed path: a killed writer leaves its
  # temp file behind, and a later invocation polling for that leftover would
  # kill the new writer before it ever reached its write window.
  home="$(mktemp -d "$TMP_ROOT/atl-kill-XXXXXX")"
  before="$home/before.json"
  err="$home/err.txt"
  atlassian_write_fixture "$home/.claude.json"
  cp "$home/.claude.json" "$before"
  : > "$err"

  python3 "$writer" "$home/.claude.json" >/dev/null 2>"$err" &
  pid=$!
  # The temp file the writer creates is the marker that it is inside its write
  # window; without waiting for it the kill could land before the write and the
  # case would pass while proving nothing.
  while [[ "$tries" -lt 200 ]]; do
    if ls "$home"/.claude.json.* >/dev/null 2>&1; then
      entered=1
      break
    fi
    sleep 0.05
    tries=$((tries + 1))
  done
  if [[ "$entered" -ne 1 ]]; then
    kill -9 "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    _fail "interrupted write: the writer never reached its write window"
    return 1
  fi
  kill -9 "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null

  if ! cmp -s "$before" "$home/.claude.json"; then
    _fail "interrupted write: the operator's config was modified by a run that never finished"
    cat "$err" >&2
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Mutation harness: mutate the installer, re-run a case against the mutation,
# and require the case to FAIL. A case that cannot be made to fail proves
# nothing.
# ---------------------------------------------------------------------------
# Sets MUTATE_OUT (the mutated copy's path) and returns 0, or returns 1 and
# clears MUTATE_OUT when the sed pattern no longer matches anything. Must be
# called in the current shell, never in a command substitution: `_fail` inside
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

echo ""
echo "=== V1: no prior chrome-devtools registration ==="
run_case "V1: a fresh install writes the entry with --headless and --isolated" \
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
echo "=== V9: an entry whose args do not name the package is left alone ==="
run_case "V9: a registration with no args key is reported and skipped" \
  case_foreign_no_args "$INSTALL_SH"
run_case "V9: a registration with an empty args list is reported and skipped" \
  case_foreign_empty_args "$INSTALL_SH"
run_case "V9: a bare {} registration is reported and skipped" \
  case_foreign_empty_entry "$INSTALL_SH"

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
run_case "V4: the writer refuses a registration carrying a conflicting flag" \
  case_writer_conflict "$INSTALL_SH"
run_case "V4: the writer refuses a --headless=false spelling" \
  case_writer_headless_false "$INSTALL_SH"
run_case "V4: the writer refuses an --isolated=false spelling" \
  case_writer_isolated_false "$INSTALL_SH"
run_case "V4: the writer refuses a --user-data-dir spelling" \
  case_writer_user_data_dir "$INSTALL_SH"
run_case "V4: the writer refuses a --channel spelling" \
  case_writer_channel "$INSTALL_SH"
run_case "V4: the writer refuses a registration with no args key" \
  case_writer_no_args "$INSTALL_SH"
run_case "V4: the writer refuses a registration with an empty args list" \
  case_writer_empty_args "$INSTALL_SH"
run_case "V4: the writer refuses a bare {} registration" \
  case_writer_empty_entry "$INSTALL_SH"

echo ""
echo "=== V5: the flags a canonical entry gains, one per missing flag ==="
run_case "V5: the writer appends both flags, only the missing one, and none to an entry carrying both" \
  case_writer_appends "$INSTALL_SH"

echo ""
echo "=== V6: a registration that connects to a browser already running is left alone ==="
run_case "V6: --browser-url is reported and the flags are withheld" \
  case_conflict_browser_url "$INSTALL_SH"
run_case "V6: --ws-endpoint is reported and the flags are withheld" \
  case_conflict_ws_endpoint "$INSTALL_SH"
run_case "V6: the camelCase --browserUrl spelling is recognised too" \
  case_conflict_camel "$INSTALL_SH"
run_case "V6: the -u alias is recognised too" \
  case_conflict_alias "$INSTALL_SH"

echo ""
echo "=== V13: spellings the withdrawn flag list never held are refused too ==="
run_case "V13: --no-isolated, --BROWSER-URL=, --isolated=1 and --no-headless are all left alone" \
  case_conflict_unlisted_spelling "$INSTALL_SH"

echo ""
echo "=== V14: the options this migration no longer writes or reads ==="
run_case "V14: --user-data-dir in both spellings, its camel form, and --channel either way are all left alone" \
  case_former_option_left_alone "$INSTALL_SH"
run_case "V14b: the writer refuses a --Headless spelling the server ignores" \
  case_writer_alternate_spelling "$INSTALL_SH"

echo ""
echo "=== V15: the form this migration writes ==="
run_case "V15: an entry carrying --headless and --isolated is already configured and left byte-identical" \
  case_current_form "$INSTALL_SH"

echo ""
echo "=== V16: a value on a flag this migration writes bare ==="
run_case "V16: --headless=false and --isolated=false are reported, not called configured headless" \
  case_valued_flag_left_alone "$INSTALL_SH"

echo ""
echo "=== V17: an entry carrying one of the two flags ==="
run_case "V17: one flag present migrates to the other alone" \
  case_partial_migration "$INSTALL_SH"

echo ""
echo "=== V18: the option names the migration reads are the ones the server reads ==="
run_case "V18: a case variant, a short-flag bundle and an underscore-only name are all left alone" \
  case_option_name_matches_server "$INSTALL_SH"

echo ""
echo "=== V7: a top-level document that is not an object is named and skipped ==="
run_case "V7: a top-level array is named and skipped" \
  case_top_level_array "$INSTALL_SH"
run_case "V7: a top-level string is named and skipped" \
  case_top_level_string "$INSTALL_SH"
run_case "V7: a top-level number is named and skipped" \
  case_top_level_number "$INSTALL_SH"
run_case "V7: a top-level null is named and skipped" \
  case_top_level_null "$INSTALL_SH"

echo ""
echo "=== V8: a config too deep to parse is named, with no traceback ==="
run_case "V8: an unparseable-depth document is skipped without a traceback" \
  case_deeply_nested "$INSTALL_SH"

echo ""
echo "=== V10: the sibling mcp-atlassian block survives a malformed config ==="
run_case "V10: an array mcpServers does not abort the install" \
  case_atlassian_container "$INSTALL_SH"

echo ""
echo "=== V11: the sibling mcp-atlassian writer preserves the operator's file ==="
run_case "V11: a write that adds one key keeps unrelated bytes and the file's mode, and leaves no temp file" \
  case_atlassian_write "$INSTALL_SH"

echo ""
echo "=== V12: a writer killed inside its write window ==="
if extract_atlassian_writer "$INSTALL_SH" "$TMP_ROOT/atl.py" \
  && inject_atlassian_delay "$TMP_ROOT/atl.py" "$TMP_ROOT/atl_slow.py"; then
  run_case "V12: an interrupted write left the config byte-identical" \
    case_atlassian_interrupted "$TMP_ROOT/atl_slow.py"
fi

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

if mutate_installer 's/^    args.append("--isolated")$/    pass/' no-isolated-append; then
  if expect_case_fails "mutation (al) no --isolated append" case_v1_fresh "$MUTATE_OUT" \
    "V1: the fresh registration does not carry the headless flags"; then
    _pass "mutation (al): dropping the --isolated append reddens V1"
  fi
  if expect_case_fails "mutation (al) no --isolated append" case_partial_migration "$MUTATE_OUT" \
    "V17: the missing flag was not appended on its own"; then
    _pass "mutation (al): the same drop reddens V17's one-flag entry"
  fi
else
  _fail "mutation (al): the sed pattern no longer matches - the mutation was not applied"
fi

# (am): the current-check left pointing at the option set this migration used to
# write. The entry the migration itself produces then classifies "stale", so the
# installer offers the migration again on every run.
if mutate_installer 's/^elif "headless" in present and "isolated" in present:$/elif "headless" in present and "userDataDir" in present:/' stale-current-check; then
  if expect_case_fails "mutation (am) current-check on the old option set" case_current_form "$MUTATE_OUT" \
    "V15: an entry carrying --headless and --isolated was not read as already configured"; then
    _pass "mutation (am): leaving the current-check on userDataDir reddens V15"
  fi
else
  _fail "mutation (am): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/^elif "headless" in present and "isolated" in present:$/elif True:/' short-circuit; then
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

if mutate_installer 's/^    refuse("the chrome-devtools entry has an args value that is not a list of strings")$/    pass/;s/^if not any(a == package or a\.startswith(package + "@") for a in args):$/if False:/' coerce-args; then
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

if mutate_installer 's/indent=2, ensure_ascii=False/indent=2/' ascii-escape; then
  if expect_case_fails "mutation (e) ensure_ascii default" case_v2_accepted "$MUTATE_OUT" \
    "V2: accepting the migration changed something beyond"; then
    _pass "mutation (e): re-encoding non-ASCII reddens V2"
  fi
else
  _fail "mutation (e): the sed pattern no longer matches - the mutation was not applied"
fi

# Anchored on the chrome-devtools block's indentation: the mcp-atlassian block
# wraps its writer differently, so an unanchored pattern would now neutralise
# that block's guard as well and credit V1c with a mutation it did not make.
if mutate_installer 's/^    if ! python3 - /    if python3 - /' invert-guard; then
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

# (o): the pre-fix classifier treated a top-level non-object as "absent", which
# runs the create path against a file the writer refuses.
if mutate_installer 's/^    print("not-json-object")$/    print("absent")/' unrefuse-top-level; then
  if expect_case_fails "mutation (o) non-object top level treated as absent" case_top_level_array "$MUTATE_OUT" \
    "was offered the registration prompt"; then
    _pass "mutation (o): collapsing a non-object top level into absent reddens V7"
  fi
else
  _fail "mutation (o): the sed pattern no longer matches - the mutation was not applied"
fi

# (p)/(q): (p) lets the decoder's RecursionError escape, which routes the state
# to "undetermined"; (q) additionally drops the classifier's stderr redirection,
# so the escaping exception prints a traceback into the install output. The two
# are separate so each property has a mutation that reddens it on its own.
if mutate_installer 's/^except (OSError, ValueError, RecursionError):$/except (OSError,):/' narrow-except; then
  if expect_case_fails "mutation (p) RecursionError uncaught" case_deeply_nested "$MUTATE_OUT" \
    "was not reported as unreadable"; then
    _pass "mutation (p): letting RecursionError escape reddens V8"
  fi
else
  _fail "mutation (p): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer "s/^except (OSError, ValueError, RecursionError):\$/except (OSError,):/;s/<<'PYEOF' 2>\\/dev\\/null/<<'PYEOF'/" unsuppressed-stderr; then
  if expect_case_fails "mutation (q) classifier stderr unsuppressed" case_deeply_nested "$MUTATE_OUT" \
    "a traceback reached the install output"; then
    _pass "mutation (q): an escaping exception with the redirection dropped reddens V8 on the traceback"
  fi
else
  _fail "mutation (q): the sed pattern no longer matches - the mutation was not applied"
fi

# (s)/(t): the two halves of the mcp-atlassian fix. (s) removes the shape guard
# (the array is clobbered); (t) removes the exit-status capture (a refusal
# aborts the install). Both are range-limited to the atlassian block, because
# the chrome-devtools writer spells its own guard identically.
if mutate_installer '/^# mcp-atlassian MCP$/,/^# context7 plugin note$/ s/^    refuse("mcpServers is not a JSON object")$/    pass/' coerce-atlassian-container; then
  if expect_case_fails "mutation (s) atlassian coerces a non-object mcpServers" case_atlassian_container "$MUTATE_OUT" \
    "the refused container was modified"; then
    _pass "mutation (s): letting the atlassian writer replace a non-object mcpServers reddens V10"
  fi
else
  _fail "mutation (s): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer 's/ || AE_ATLASSIAN_RC=\$?$//' atlassian-abort; then
  if expect_case_fails "mutation (t) atlassian refusal not tolerated" case_atlassian_container "$MUTATE_OUT" \
    "a malformed config aborted the install"; then
    _pass "mutation (t): dropping the exit-status capture reddens V10"
  fi
else
  _fail "mutation (t): the sed pattern no longer matches - the mutation was not applied"
fi

# (u): the pre-fix classifier made every entry that was neither current nor
# absent a migration target whatever its args carried - the catch-all the
# spelling list was bolted onto. Asserted against both a spelling that list
# held and one it never did.
if mutate_installer 's/^    print("foreign-args")$/    print("stale")/' unrefuse-foreign-args; then
  if expect_case_fails "mutation (u) a conflicting registration treated as stale" case_conflict_browser_url "$MUTATE_OUT" \
    "was offered a prompt"; then
    _pass "mutation (u): collapsing foreign-args into stale reddens V6's --browser-url case"
  fi
  if expect_case_fails "mutation (u) an unenumerated conflicting spelling treated as stale" \
    case_conflict_unlisted_spelling "$MUTATE_OUT" "was offered a prompt"; then
    _pass "mutation (u): the same collapse reddens V13's spelling the old list never held"
  fi
else
  _fail "mutation (u): the sed pattern no longer matches - the mutation was not applied"
fi

# (v): the writer's own guard, driven directly through the V4 conflict case.
if mutate_installer 's/^if foreign is not None:$/if False:/' coerce-foreign; then
  if expect_case_fails "mutation (v) writer appends the pin beside an argument it does not write" case_writer_conflict "$MUTATE_OUT" \
    "the writer accepted a container it cannot edit surgically"; then
    _pass "mutation (v): disabling the writer's foreign-args guard reddens V4's conflict case"
  fi
else
  _fail "mutation (v): the sed pattern no longer matches - the mutation was not applied"
fi

# (ac): the normalization rule itself, with the foreign-args guard left in
# place. Case-folding a name that carries no dash is the pre-fix reading: it
# turns `--Headless`, an unknown flag to the server, into the headless option
# this migration writes, so the entry is migrated without ever gaining the
# flag that removes the window while the installer reports it configured. Both
# blocks return the name verbatim, and the sed hits both so the two cannot
# drift apart under it.
if mutate_installer 's/^        return name$/        return name.lower()/' fold-option-names; then
  if expect_case_fails "mutation (ac) the writer's copy of the fold" \
    case_writer_alternate_spelling "$MUTATE_OUT" \
    "the writer accepted a spelling the server ignores"; then
    _pass "mutation (ac): case-folding a dash-free name reddens V14b on the writer's own copy"
  fi
  if expect_case_fails "mutation (ac) the classifier reads a spelling the server ignores" \
    case_option_name_matches_server "$MUTATE_OUT" \
    "was offered a prompt"; then
    _pass "mutation (ac): the same fold reddens V18 on a case variant"
  fi
else
  _fail "mutation (ac): the sed pattern no longer matches - the mutation was not applied"
fi

# (w): the pre-fix classifier's catch-all else, which made every entry that was
# not already current a migration target whatever its args named.
if mutate_installer 's/^    print("args-not-our-package")$/    print("stale")/' unscope-stale; then
  if expect_case_fails "mutation (w) an entry that does not name the package treated as stale" \
    case_foreign_no_args "$MUTATE_OUT" \
    "was offered a prompt"; then
    _pass "mutation (w): collapsing args-not-our-package into stale reddens V9"
  fi
else
  _fail "mutation (w): the sed pattern no longer matches - the mutation was not applied"
fi

# (x): the writer's own copy of that guard, driven directly through V4.
if mutate_installer 's/^if not any(a == package or a\.startswith(package + "@") for a in args):$/if False:/' coerce-package; then
  if expect_case_fails "mutation (x) writer migrates an entry that does not name the package" \
    case_writer_no_args "$MUTATE_OUT" \
    "the writer accepted a container it cannot edit surgically"; then
    _pass "mutation (x): disabling the writer's package guard reddens V4's foreign cases"
  fi
else
  _fail "mutation (x): the sed pattern no longer matches - the mutation was not applied"
fi

# (y)/(z): the two halves of the mcp-atlassian write. Both are range-limited to
# the atlassian block, because the chrome-devtools writer spells its own
# serializer with the identical indent=2, ensure_ascii=False.
if mutate_installer '/^# mcp-atlassian MCP$/,/^# context7 plugin note$/ s/indent=2, ensure_ascii=False/indent=2/' atlassian-ascii; then
  if expect_case_fails "mutation (y) atlassian writer re-encodes non-ASCII" case_atlassian_write "$MUTATE_OUT" \
    "damaged the operator's config"; then
    _pass "mutation (y): dropping ensure_ascii=False reddens V11"
  fi
else
  _fail "mutation (y): the sed pattern no longer matches - the mutation was not applied"
fi

if mutate_installer '/^# mcp-atlassian MCP$/,/^# context7 plugin note$/ s/^            os\.chmod(tmp_path, stat\.S_IMODE(before\.st_mode))$/            pass/' atlassian-mode; then
  if expect_case_fails "mutation (z) atlassian writer drops the mode carry-over" case_atlassian_write "$MUTATE_OUT" \
    "damaged the operator's config"; then
    _pass "mutation (z): dropping the mode carry-over reddens V11"
  fi
else
  _fail "mutation (z): the sed pattern no longer matches - the mutation was not applied"
fi

# (aa): the pre-fix write, restored onto the extracted block. It truncates the
# target the moment the file is opened, which is the window V12 kills inside.
if [[ -f "$TMP_ROOT/atl_slow.py" ]]; then
  sed 's/^        with os\.fdopen(fd, "w", encoding="utf-8") as f:$/        with open(target, "w", encoding="utf-8") as f:/' \
    "$TMP_ROOT/atl_slow.py" > "$TMP_ROOT/atl_inplace.py"
  if cmp -s "$TMP_ROOT/atl_slow.py" "$TMP_ROOT/atl_inplace.py"; then
    _fail "mutation (aa): could not restore the in-place write (pattern no longer matches)"
  elif expect_case_fails "mutation (aa) atlassian writer writes in place" case_atlassian_interrupted "$TMP_ROOT/atl_inplace.py" \
    "the operator's config was modified by a run that never finished"; then
    _pass "mutation (aa): restoring the in-place write reddens V12"
  fi
fi

# (ab): the foreign-args report has to name --headless and the class it does
# not work for, or it repeats the old advice that was inert for a registration
# connecting to a browser the operator already runs. The way out is two lines,
# one per class of spelling, so the mutation drops both - dropping one leaves
# the other naming --headless and the case would redden on a later assertion,
# crediting this mutation with coverage it did not demonstrate.
if mutate_installer '/^  echo "  To lose the window by hand/,/^  echo "  One that writes --headless=false/d' drop-window-way-out; then
  if expect_case_fails "mutation (ab) foreign-args report omits the way out" \
    case_conflict_unlisted_spelling "$MUTATE_OUT" \
    "did not name the flag that would remove the window"; then
    _pass "mutation (ab): dropping the --headless line reddens V13"
  fi
else
  _fail "mutation (ab): the sed pattern no longer matches - the mutation was not applied"
fi

# (ae): the fold that read `--headless=false` as the option the migration
# writes, which left the report claiming the entry was configured headless.
# Both blocks carry the rule, so this sed hits the classifier's copy and the
# writer's at once - a fix applied to only one of them is not a way to pass.
if mutate_installer 's/^            if "=" in arg:$/            if False:/' fold-negated-bare-flag; then
  if expect_case_fails "mutation (ae) a bare flag spelled with a value folds to the option name" \
    case_valued_flag_left_alone "$MUTATE_OUT" \
    "was not reported as carrying an argument the migration does not write"; then
    _pass "mutation (ae): folding --headless=false to the option name reddens V16"
  fi
  if expect_case_fails "mutation (ae) the writer's own copy of the fold" \
    case_writer_headless_false "$MUTATE_OUT" \
    "the writer accepted a container it cannot edit surgically"; then
    _pass "mutation (ae): the writer's copy of the fold reddens V4's --headless=false case"
  fi
else
  _fail "mutation (ae): the sed pattern no longer matches - the mutation was not applied"
fi

# (af): the withdrawn way-out sentence, which told an operator whose entry sets
# --isolated to drop it - measured unnecessary, the server takes `--headless
# --isolated` (rc 0).
if mutate_installer 's/adding --headless beside --isolated removes the window and --isolated can stay\./dropping --isolated for --headless is what removes the window there./' restore-isolated-advice; then
  if expect_case_fails "mutation (af) the report tells an --isolated operator to drop the flag" \
    case_way_out_advice "$MUTATE_OUT" \
    "did not say that --isolated can stay under --headless"; then
    _pass "mutation (af): restoring the drop--isolated advice reddens the way-out case"
  fi
else
  _fail "mutation (af): the sed pattern no longer matches - the mutation was not applied"
fi

# (ag): the second way-out line, which is the only report the operator whose
# entry spells the window out by name gets.
if mutate_installer '/^  echo "  One that writes --headless=false/d' drop-negation-way-out; then
  if expect_case_fails "mutation (ag) the report omits the --headless=false spelling" \
    case_valued_flag_left_alone "$MUTATE_OUT" \
    "did not cover a --headless=false spelling"; then
    _pass "mutation (ag): dropping the negation way-out line reddens V16"
  fi
else
  _fail "mutation (ag): the sed pattern no longer matches - the mutation was not applied"
fi

# (aj): the rule that decides whether a token is a long option at all. `-headless`
# is the single-letter flag bundle h-e-a-d-l-e-s-s to the server, so reading it
# as a long option makes the migration treat a spelling the server ignores as
# the headless option it writes. The sed pattern matches both python blocks, so
# a rule that survives in only one of them is not a way to pass.
if mutate_installer 's/^    if not name\.startswith("--"):$/    if False:/' read-short-flags-as-long; then
  if expect_case_fails "mutation (aj) a single-dash token read as a long option" \
    case_option_name_matches_server "$MUTATE_OUT" \
    "was offered a prompt"; then
    _pass "mutation (aj): reading a short-flag bundle as a long option reddens V18's -headless case"
  fi
else
  _fail "mutation (aj): the sed pattern no longer matches - the mutation was not applied"
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
  _fail "ambient hooks dir's pre-commit symlink changed (sandbox failed): before '$AMBIENT_PRECOMMIT_BEFORE', after '$AMBIENT_PRECOMMIT_AFTER'"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
