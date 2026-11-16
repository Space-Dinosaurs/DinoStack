#!/usr/bin/env bash
# Purpose: Drive the real .claude/install.sh and .claude/uninstall.sh against a
#          scratch HOME and assert how the low-disk warning hook
#          (hooks/disk-space-warn.sh) is wired in the settings.json the
#          installer writes:
#          D1 - exactly one entry, in the PostToolUse "*" block, in the
#               guarded `test -f ... && bash ... || exit 0` form,
#               "timeout": 5, pointing into the hooks snapshot at a file
#               that exists
#          D2 - a second install leaves exactly one entry
#          D3 - after uninstall.sh the entry is gone
# Public API: ./bin/tests/test_install_disk_space_warn.sh
#             Exits 0 on all pass, 1 on any failure.
# Upstream deps: bash, python3, git, node (transitively, via build.sh), mktemp.
# Downstream consumers: CI (the bin/tests/test_*.sh glob in
#                       .github/workflows/bin-tests.yml).
# Failure modes: prints the failing assertion and exits 1. The real ~/.claude
#                is never touched; the git shim (from
#                bin/tests/test_install_cache_keepalive.sh) keeps install.sh
#                and uninstall.sh away from the live checkout's pre-commit hook.
# Performance: 3 install runs and 1 uninstall run, ~10 s on a warm tree.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="$REPO_DIR/.claude/install.sh"
UNINSTALL_SH="$REPO_DIR/.claude/uninstall.sh"

PASS=0
FAIL=0
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }

TMP_ROOT="$(mktemp -d)"
_cleanup() { find "$TMP_ROOT" -depth -delete 2>/dev/null; }
trap _cleanup EXIT INT TERM

FAKE_BIN="$TMP_ROOT/fakebin"
mkdir -p "$FAKE_BIN"
for tool in gh agent-browser lc jira rclone; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$FAKE_BIN/$tool"
  chmod +x "$FAKE_BIN/$tool"
done

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

HOME_DIR="$TMP_ROOT/home"
mkdir -p "$HOME_DIR/.claude"
printf '{"skill_auto_load": false}\n' > "$HOME_DIR/.claude/agentic-engineering.json"
cat > "$HOME_DIR/.claude.json" <<'EOF'
{"mcpServers":{"chrome-devtools":{"type":"stdio","command":"npx","args":["chrome-devtools-mcp@latest","--headless","--isolated"],"env":{}},"mcp-atlassian":{}}}
EOF
printf '{"permissions":{"defaultMode":"bypassPermissions"},"env":{"AGENT_BROWSER_IDLE_TIMEOUT_MS":"1800000"}}\n' \
  > "$HOME_DIR/.claude/settings.json"
SETTINGS="$HOME_DIR/.claude/settings.json"

run_script() {
  local script="$1" out="$HOME_DIR/.run_out" rc
  env -u AGENTIC_CONFIG_DIR -u CLAUDE_CONFIG_DIR -u CODEX_HOME -u PI_CODING_AGENT_DIR \
    PATH="$FAKE_BIN:$PATH" HOME="$HOME_DIR" bash "$script" \
    --mode=opt-out --profile=default --no-identity < /dev/null > "$out" 2>&1
  rc=$?
  if [[ $rc -ne 0 ]]; then
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

# entries -> one JSON line per disk-space-warn entry in any event, tagged with
# its event and matcher.
entries() {
  python3 - "$SETTINGS" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
for event, blocks in d.get("hooks", {}).items():
    for block in blocks:
        for h in block.get("hooks", []):
            if "disk-space-warn.sh" in h.get("command", ""):
                print(json.dumps({"event": event, "matcher": block.get("matcher"), **h}))
PYEOF
}

check_wired() {
  local label="$1" found n
  found="$(entries)"
  n="$(grep -c . <<< "$found")"
  if [[ "$n" -ne 1 ]]; then
    _fail "$label: expected exactly 1 disk-space-warn entry, found $n: $found"
    return
  fi
  if python3 - "$found" "$HOME_DIR" "$REPO_DIR" <<'PYEOF'
import json, os, re, sys
e = json.loads(sys.argv[1])
home, repo = sys.argv[2], sys.argv[3]
assert e["event"] == "PostToolUse" and e["matcher"] == "*", e
m = re.fullmatch(r"test -f (\S+/hooks/disk-space-warn\.sh) && bash (\S+) \|\| exit 0", e["command"])
assert m and m.group(1) == m.group(2), e["command"]
assert e.get("timeout") == 5, e
path = m.group(1)
assert path.startswith(os.path.join(home, ".agentic", "hooks-snapshot") + "/"), path
assert not path.startswith(repo + "/"), path
assert os.path.isfile(path), path
PYEOF
  then _pass "$label"; else _fail "$label: not the guarded PostToolUse(*) snapshot form: $found"; fi
}

if run_script "$INSTALL_SH"; then
  check_wired "D1: one guarded PostToolUse(*) entry, timeout 5, snapshot path"
else
  _fail "D1: install failed"
fi

if run_script "$INSTALL_SH"; then
  check_wired "D2: a second install leaves one entry"
else
  _fail "D2: second install failed"
fi

if run_script "$UNINSTALL_SH"; then
  if [[ -z "$(entries)" ]]; then
    _pass "D3: uninstall removed the entry"
  else
    _fail "D3: a disk-space-warn entry survived uninstall: $(entries)"
  fi
else
  _fail "D3: uninstall failed"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed."
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
