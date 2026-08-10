#!/usr/bin/env bash
# Purpose: Assert that .claude/install.sh wires the PreToolUse(Read)
#          worktree-read guard (enforce-worktree-read.py, DS-150) with a
#          GUARDED command string (`test -f ... && python3 ... || exit 0`),
#          NOT a bare `python3 <path>` form.
#
#          CRITICAL-1: `python3 <missing path>` exits 2, which is the
#          BLOCKING PreToolUse code - if the registration in
#          ~/.claude/settings.json ever outlives the script on disk (this
#          PR reverted, a branch switch/bisect to a commit predating the
#          file, a moved checkout), an unguarded command denies EVERY Read
#          in EVERY session, conductor included. That violates the flat
#          prohibition at hooks/AGENTS.md ("no hook may deny conductor
#          Read/Grep/Glob"). This repo has already had this exact incident
#          once with a different hook (dead settings.json path killed all
#          Write/Edit); this test exists so it cannot recur silently here.
#
# CRITICAL: this assertion MUST read the GENERATED $FAKE_HOME/.claude/settings.json,
# NEVER .claude/install.sh's own source text - same discipline as
# test_install_stop_cadence.sh, which this file's fixture setup is copied
# from verbatim (the four prompt-suppression seeds).
#
# Public API: ./bin/tests/test_install_worktree_read_guard.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, git, node (transitively, via build.sh), mktemp.
#
# Downstream consumers: developer running locally before commit; CI.
#
# Failure modes: any assertion failure prints the failing assertion and
#                exits 1. A temporary fake HOME is used; the real
#                ~/.claude is never touched.
#
# Performance: ~10-15 s wall time (one .claude/install.sh run, which builds
#              all adapters via .claude/build.sh + .cursor/build.sh).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

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

TMP_ROOT="$(mktemp -d)"
_cleanup() {
  rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

FAKE_HOME="$TMP_ROOT/home"
mkdir -p "$FAKE_HOME/.claude"

# ---------------------------------------------------------------------------
# Seed 1: skill_auto_load key present -> suppresses the ae_write_config
# /dev/tty prompt (gated `if "skill_auto_load" not in config:`).
# ---------------------------------------------------------------------------
cat > "$FAKE_HOME/.claude/agentic-engineering.json" <<'EOF'
{"skill_auto_load": false}
EOF

# ---------------------------------------------------------------------------
# Seed 2: ~/.claude.json with both MCP servers pre-configured -> suppresses
# both MCP ae_confirm gates (they check $HOME/.claude.json).
# ---------------------------------------------------------------------------
cat > "$FAKE_HOME/.claude.json" <<'EOF'
{"mcpServers":{"chrome-devtools":{},"mcp-atlassian":{}}}
EOF

# ---------------------------------------------------------------------------
# Seed 3: no-op executables for the five CLI_TOOLS on PATH -> suppresses the
# five ae_confirm "Install <tool>?" prompts (command -v succeeds for all 5).
# ---------------------------------------------------------------------------
FAKE_BIN="$TMP_ROOT/fakebin"
mkdir -p "$FAKE_BIN"
for tool in gh agent-browser lc jira rclone; do
  cat > "$FAKE_BIN/$tool" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$FAKE_BIN/$tool"
done

# ---------------------------------------------------------------------------
# Seed 4: ~/.claude/settings.json with permissions.defaultMode already set to
# bypassPermissions -> suppresses the tty_input permissions-configuration
# prompt (its gate reads perms.get("defaultMode"), which is otherwise only
# ever written inside that same prompt's own yes-branch).
# ---------------------------------------------------------------------------
cat > "$FAKE_HOME/.claude/settings.json" <<'EOF'
{"permissions":{"defaultMode":"bypassPermissions"}}
EOF

echo ""
echo "=== Running .claude/install.sh against a fully-seeded fake HOME ==="

PATH="$FAKE_BIN:$PATH" HOME="$FAKE_HOME" bash "$REPO_DIR/.claude/install.sh" \
  --mode=opt-out --profile=default --no-identity \
  < /dev/null > "$FAKE_HOME/.install_out" 2>&1
INSTALL_RC=$?

# Tolerated failure signature (copied from
# bin/tests/test_hooks_snapshot_no_live_rewire.sh lines 68-83): from a git
# worktree, install.sh's UNRELATED "Installing pre-commit hook" step fails
# after the settings.json wiring this test asserts on has already completed.
if [[ $INSTALL_RC -ne 0 ]]; then
  if grep -q "Installing pre-commit hook" "$FAKE_HOME/.install_out" 2>/dev/null && \
     tail -n 5 "$FAKE_HOME/.install_out" | grep -q "\.git/hooks/pre-commit: Not a directory"; then
    echo "  [warn] install.sh exited $INSTALL_RC at the known worktree-only pre-commit-hook step (unrelated, pre-existing) - tolerated" >&2
  else
    echo "  [install.sh output]:" >&2
    cat "$FAKE_HOME/.install_out" >&2
    _fail "install.sh exited $INSTALL_RC for an unexpected reason"
  fi
fi

SETTINGS="$FAKE_HOME/.claude/settings.json"
if [[ -f "$SETTINGS" ]]; then
  _pass "install.sh wrote ~/.claude/settings.json"
else
  echo "  [install.sh output]:" >&2
  cat "$FAKE_HOME/.install_out" >&2
  _fail "install.sh did not write ~/.claude/settings.json"
  echo ""
  echo "Results: $PASS passed, $FAIL failed."
  exit 1
fi

# ---------------------------------------------------------------------------
# THE core assertion - read the GENERATED settings.json, never install.sh's
# own source. Find the PreToolUse "Read" matcher block's
# enforce-worktree-read.py command and assert it carries the
# `test -f ... && ... || exit 0` guard, not a bare `python3 <path>` form.
# ---------------------------------------------------------------------------

READ_CMD="$(python3 -c "
import json
with open('$SETTINGS') as f:
    d = json.load(f)
for block in d.get('hooks', {}).get('PreToolUse', []):
    if block.get('matcher') != 'Read':
        continue
    for h in block.get('hooks', []):
        if 'enforce-worktree-read.py' in h.get('command', ''):
            print(h['command'])
" 2>/dev/null)"

if [[ -z "$READ_CMD" ]]; then
  _fail "no PreToolUse(Read) hook command found containing enforce-worktree-read.py in generated settings.json"
elif [[ "$READ_CMD" == test\ -f*enforce-worktree-read.py*"&&"*python3*enforce-worktree-read.py*"||"*exit\ 0 ]]; then
  _pass "installed PreToolUse(Read) worktree-read-guard command carries the guarded 'test -f ... && ... || exit 0' form: '$READ_CMD'"
else
  _fail "installed PreToolUse(Read) worktree-read-guard command does NOT carry the guarded form (CRITICAL-1 regression): '$READ_CMD'"
fi

# A bare `python3 <path>` form (no preceding `test -f`) must NOT be present -
# this is the exact defect CRITICAL-1 flagged; assert its absence directly
# rather than only asserting the guarded form's presence.
if [[ "$READ_CMD" == python3* ]]; then
  _fail "installed command starts with a bare 'python3' invocation (unguarded - CRITICAL-1 regression): '$READ_CMD'"
else
  _pass "installed command does not start with a bare, unguarded 'python3' invocation"
fi

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
