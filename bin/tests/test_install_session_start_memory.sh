#!/usr/bin/env bash
# Purpose: Drive the real .claude/install.sh and .claude/uninstall.sh against a
#          scratch HOME and assert how the main-session MEMORY.md hook
#          (hooks/session-start-memory.py) is wired in the settings.json the
#          installer actually writes - never install.sh's own source text.
#
#          I1 - exactly one entry, in the SessionStart "*" block, in the
#               guarded `test -f ... && python3 ... || exit 0` form,
#               "timeout": 5, pointing into the hooks snapshot (not the
#               checkout) at a file that exists
#          I2 - no entry under SubagentStart, Stop or UserPromptSubmit. Only
#               SessionStart reaches the main session alone
#          I3 - a second install leaves exactly one entry
#          I4 - with CLAUDE_CONFIG_DIR=$home/.claude-alt the entry lands in
#               .claude-alt/settings.json and $home/.claude/settings.json gains
#               none
#          I5 - after uninstall.sh the entry is gone and session-start-wrap.sh
#               (which uninstall does not remove) remains
#
#          Mutation coverage (each mutation is run, not merely named; a
#          mutation is a full copy of install.sh or uninstall.sh in .claude/,
#          because REPO_DIR is derived from the script's own path, removed by
#          the exit trap):
#            (i)   bare `python3 <path>` registration         -> I1 reddens
#            (ii)  registered under SubagentStart              -> I2 reddens
#            (iii) hook wiring writes $HOME/.claude/settings.json instead of
#                  the resolved $SETTINGS                      -> I4 reddens
#            (iv)  uninstall's removal deleted                 -> I5 reddens
#
# Public API: ./bin/tests/test_install_session_start_memory.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, perl, git, node (transitively, via build.sh),
#                mktemp.
#
# Downstream consumers: developer running locally before commit; CI (the
#                       bin/tests/test_*.sh glob in
#                       .github/workflows/bin-tests.yml).
#
# Failure modes: any assertion failure prints the failing assertion and exits
#                1. The real ~/.claude and ~/.claude.json are never touched;
#                the git shim (copied from
#                bin/tests/test_install_worktree_read_guard.sh) keeps
#                install.sh and uninstall.sh away from the live checkout's
#                pre-commit hook.
#
# Performance: 10 install runs and 2 uninstall runs, ~35 s on a warm tree.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_DIR/.claude/install.sh"
UNINSTALL_SH="$REPO_DIR/.claude/uninstall.sh"
MUTATION_GLOB="$REPO_DIR/.claude/.mutation-ssmem-$$-*"

PASS=0
FAIL=0
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  rm -rf "$TMP_ROOT"
  rm -f $MUTATION_GLOB
}
trap _cleanup EXIT INT TERM
rm -f $MUTATION_GLOB

FAKE_BIN="$TMP_ROOT/fakebin"
mkdir -p "$FAKE_BIN"
# Seed 3: no-op executables for the five CLI_TOOLS, so no install prompt fires.
for tool in gh agent-browser lc jira rclone; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$FAKE_BIN/$tool"
  chmod +x "$FAKE_BIN/$tool"
done

# Git-level sandbox, verbatim from test_install_worktree_read_guard.sh: answer
# only `rev-parse --git-path hooks` with a scratch dir, pass everything else
# through to the real git.
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

AMBIENT_HOOKS_DIR="$("$REAL_GIT" -C "$REPO_DIR" rev-parse --git-path hooks 2>/dev/null)"
case "$AMBIENT_HOOKS_DIR" in
  /*) : ;;
  *) AMBIENT_HOOKS_DIR="$REPO_DIR/$AMBIENT_HOOKS_DIR" ;;
esac
AMBIENT_PRECOMMIT="$AMBIENT_HOOKS_DIR/pre-commit"
AMBIENT_PRECOMMIT_BEFORE=""
[[ -L "$AMBIENT_PRECOMMIT" ]] && AMBIENT_PRECOMMIT_BEFORE="$(readlink "$AMBIENT_PRECOMMIT")"

# seed_home <home> <settings-dir>
# Seeds 1, 2, 4 and 5: skill_auto_load (ae_write_config prompt), both MCP
# servers already configured (MCP prompts), and a settings.json in
# <settings-dir> carrying permissions.defaultMode plus the idle-timeout key
# (permissions prompt and agent-browser prompt).
seed_home() {
  local home="$1" sdir="$2"
  mkdir -p "$home/.claude" "$sdir"
  printf '{"skill_auto_load": false}\n' > "$home/.claude/agentic-engineering.json"
  cat > "$home/.claude.json" <<'EOF'
{"mcpServers":{"chrome-devtools":{"type":"stdio","command":"npx","args":["chrome-devtools-mcp@latest","--headless","--isolated"],"env":{}},"mcp-atlassian":{}}}
EOF
  printf '{"permissions":{"defaultMode":"bypassPermissions"},"env":{"AGENT_BROWSER_IDLE_TIMEOUT_MS":"1800000"}}\n' \
    > "$sdir/settings.json"
}

# run_script <script> <home> [claude-config-dir]
run_script() {
  local script="$1" home="$2" ccd="${3:-}" out="$2/.run_out" rc
  if [[ -n "$ccd" ]]; then
    env -u AGENTIC_CONFIG_DIR -u CODEX_HOME -u PI_CODING_AGENT_DIR CLAUDE_CONFIG_DIR="$ccd" \
      PATH="$FAKE_BIN:$PATH" HOME="$home" bash "$script" \
      --mode=opt-out --profile=default --no-identity < /dev/null > "$out" 2>&1
  else
    env -u AGENTIC_CONFIG_DIR -u CLAUDE_CONFIG_DIR -u CODEX_HOME -u PI_CODING_AGENT_DIR \
      PATH="$FAKE_BIN:$PATH" HOME="$home" bash "$script" \
      --mode=opt-out --profile=default --no-identity < /dev/null > "$out" 2>&1
  fi
  rc=$?
  if [[ $rc -ne 0 ]]; then
    # Tolerated: the worktree-only pre-commit step after the settings wiring.
    if grep -q "Installing pre-commit hook" "$out" && \
       tail -n 5 "$out" | grep -q "\.git/hooks/pre-commit: Not a directory"; then
      return 0
    fi
    echo "  [$(basename "$script") exited $rc]" >&2
    tail -20 "$out" >&2
    return 1
  fi
  return 0
}

# mem_entries <settings.json> <event> -> one JSON line per session-start-memory
# entry, each tagged with the matcher of the block it sits in.
mem_entries() {
  python3 - "$1" "$2" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    sys.exit(0)
for block in d.get("hooks", {}).get(sys.argv[2], []):
    for h in block.get("hooks", []):
        if "session-start-memory.py" in h.get("command", ""):
            print(json.dumps({"matcher": block.get("matcher"), **h}))
PYEOF
}

has_entry() {
  python3 - "$1" "$2" "$3" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if any(sys.argv[3] in h.get("command", "")
                  for b in d.get("hooks", {}).get(sys.argv[2], [])
                  for h in b.get("hooks", [])) else 1)
PYEOF
}

# check_wired <settings.json> <home> <label>: I1 against one settings file.
check_wired() {
  local settings="$1" home="$2" label="$3" entries n
  entries="$(mem_entries "$settings" SessionStart)"
  n="$(grep -c . <<< "$entries")"
  if [[ "$n" -ne 1 ]]; then
    _fail "$label: expected exactly 1 session-start-memory entry under SessionStart, found $n"
    return 1
  fi
  if ! python3 - "$entries" "$home" "$REPO_DIR" <<'PYEOF'
import json, os, re, sys
e = json.loads(sys.argv[1])
home, repo = sys.argv[2], sys.argv[3]
m = re.fullmatch(r"test -f (\S+/hooks/session-start-memory\.py) && python3 (\S+) \|\| exit 0",
                 e["command"])
assert e["matcher"] == "*", e
assert m and m.group(1) == m.group(2), e["command"]
assert e.get("timeout") == 5, e
path = m.group(1)
assert path.startswith(os.path.join(home, ".agentic", "hooks-snapshot") + "/"), path
assert not path.startswith(repo + "/"), path
assert os.path.isfile(path), path
PYEOF
  then
    _fail "$label: SessionStart entry is not the guarded snapshot form with timeout 5: $entries"
    return 1
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Cases. Each takes the install (or uninstall) script under test.
# ---------------------------------------------------------------------------
case_i1() {
  local home="$TMP_ROOT/i1-$RANDOM"
  seed_home "$home" "$home/.claude"
  run_script "$1" "$home" || { _fail "I1: install failed"; return 1; }
  check_wired "$home/.claude/settings.json" "$home" "I1" || return 1
}

case_i2() {
  local home="$TMP_ROOT/i2-$RANDOM" event
  seed_home "$home" "$home/.claude"
  run_script "$1" "$home" || { _fail "I2: install failed"; return 1; }
  for event in SubagentStart Stop UserPromptSubmit; do
    if [[ -n "$(mem_entries "$home/.claude/settings.json" "$event")" ]]; then
      _fail "I2: session-start-memory is registered under $event"
      return 1
    fi
  done
}

case_i3() {
  local home="$TMP_ROOT/i3-$RANDOM"
  seed_home "$home" "$home/.claude"
  run_script "$1" "$home" || { _fail "I3: first install failed"; return 1; }
  run_script "$1" "$home" || { _fail "I3: second install failed"; return 1; }
  check_wired "$home/.claude/settings.json" "$home" "I3 (after a second install)" || return 1
}

case_i4() {
  local home="$TMP_ROOT/i4-$RANDOM"
  seed_home "$home" "$home/.claude-alt"
  run_script "$1" "$home" "$home/.claude-alt" || { _fail "I4: install failed"; return 1; }
  check_wired "$home/.claude-alt/settings.json" "$home" "I4" || return 1
  if [[ -n "$(mem_entries "$home/.claude/settings.json" SessionStart)" ]]; then
    _fail "I4: the hook was also written into \$HOME/.claude/settings.json"
    return 1
  fi
}

case_i5() {
  local uninstall="$1" home="$TMP_ROOT/i5-$RANDOM"
  seed_home "$home" "$home/.claude"
  run_script "$INSTALL_SH" "$home" || { _fail "I5: install failed"; return 1; }
  run_script "$uninstall" "$home" || { _fail "I5: uninstall failed"; return 1; }
  local settings="$home/.claude/settings.json"
  if [[ -n "$(mem_entries "$settings" SessionStart)" ]]; then
    _fail "I5: a session-start-memory entry survived uninstall"
    return 1
  fi
  if ! has_entry "$settings" SessionStart "session-start-wrap.sh"; then
    _fail "I5: uninstall removed session-start-wrap.sh, which it does not own"
    return 1
  fi
}

run_case() {
  if ( "$2" "$3" ); then _pass "$1"; else _fail "$1"; fi
}

# expect_mutation_fails <tag> <source> <perl-expr> <case-fn> <expected-reason>
# perl -0 so one expression can span the lines of a single registration.
expect_mutation_fails() {
  local tag="$1" src="$2" expr="$3" fn="$4" want="$5"
  local out="$REPO_DIR/.claude/.mutation-ssmem-$$-$tag.sh"
  perl -0pe "$expr" "$src" > "$out"
  if cmp -s "$src" "$out"; then
    _fail "mutation $tag: the perl pattern matched nothing (anchor moved?)"
    return 1
  fi
  if ! bash -n "$out"; then
    _fail "mutation $tag produced a script with a shell syntax error"
    return 1
  fi
  if ( "$fn" "$out" ) > "$TMP_ROOT/mut.out" 2> "$TMP_ROOT/mut.err"; then
    _fail "mutation $tag: the case passed against the mutated script"
    rm -f "$out"
    return 1
  fi
  rm -f "$out"
  local reason
  reason="$(grep '^FAIL:' "$TMP_ROOT/mut.err" | head -1)"
  echo "    (!) $tag -> $reason"
  if [[ "$reason" != *"$want"* ]]; then
    _fail "mutation $tag reddened for an unrelated reason (wanted '$want')"
    return 1
  fi
  _pass "mutation $tag reddens $fn"
}

echo "=== I1: guarded snapshot entry on SessionStart ==="
run_case "I1: one guarded entry, timeout 5, snapshot path" case_i1 "$INSTALL_SH"
echo "=== I2: never on SubagentStart, Stop or UserPromptSubmit ==="
run_case "I2: no entry under SubagentStart, Stop, UserPromptSubmit" case_i2 "$INSTALL_SH"
echo "=== I3: idempotent ==="
run_case "I3: a second install leaves one entry" case_i3 "$INSTALL_SH"
echo "=== I4: lands in the CLAUDE_CONFIG_DIR-redirected settings ==="
run_case "I4: entry in .claude-alt, none in \$HOME/.claude" case_i4 "$INSTALL_SH"
echo "=== I5: uninstall removes it ==="
run_case "I5: entry gone, session-start-wrap.sh kept" case_i5 "$UNINSTALL_SH"

echo "=== Mutations ==="
expect_mutation_fails "bare-python3" "$INSTALL_SH" \
  's/    f"test -f \{hooks_root\}\/hooks\/session-start-memory\.py && "\n    f"python3 (\{hooks_root\}\/hooks\/session-start-memory\.py) \|\| exit 0"/    f"python3 $1"/' \
  case_i1 "not the guarded snapshot form"
expect_mutation_fails "registered-on-subagentstart" "$INSTALL_SH" \
  's/    session_start_star\["hooks"\],\n    "session-start-memory\.py",/    hooks.setdefault("SubagentStart", [{"matcher": "*", "hooks": []}])[0]["hooks"],\n    "session-start-memory.py",/' \
  case_i2 "registered under SubagentStart"
expect_mutation_fails "wiring-writes-home-claude" "$INSTALL_SH" \
  's/^AE_SETTINGS_PATH="\$SETTINGS" python3 - <<(?=.PYEOF.$)/AE_SETTINGS_PATH="\$HOME\/.claude\/settings.json" python3 - <</m' \
  case_i4 "I4:"
expect_mutation_fails "uninstall-removal-deleted" "$UNINSTALL_SH" \
  's/^remove_hook\("SessionStart", "hooks\/session-start-memory\.py".*\n//mg' \
  case_i5 "survived uninstall"

echo "=== Ambient hook symlink unchanged ==="
AMBIENT_PRECOMMIT_AFTER=""
[[ -L "$AMBIENT_PRECOMMIT" ]] && AMBIENT_PRECOMMIT_AFTER="$(readlink "$AMBIENT_PRECOMMIT")"
if [[ "$AMBIENT_PRECOMMIT_AFTER" == "$AMBIENT_PRECOMMIT_BEFORE" ]]; then
  _pass "the git shim kept the ambient pre-commit symlink out of this test's reach"
else
  _fail "this test mutated the ambient pre-commit symlink ($AMBIENT_PRECOMMIT_BEFORE -> $AMBIENT_PRECOMMIT_AFTER)"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
