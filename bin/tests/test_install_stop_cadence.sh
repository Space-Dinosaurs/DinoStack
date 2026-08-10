#!/usr/bin/env bash
# Purpose: Assert that .claude/install.sh wires the Stop hook with
#          --cadence=turn (the per-turn liveness-refresh dispatch) and that
#          the SessionEnd hook still names session-end-wrap.js (the
#          once-per-session terminal interrupted-mark writer).
#
# CRITICAL: this assertion MUST read the GENERATED $FAKE_HOME/.claude/settings.json,
# NEVER .claude/install.sh's own source text. Reading the source would only
# prove the string is present in the script, not that install.sh actually
# wires it into the installed config - the failure mode this test exists to
# catch is a Python f-string typo or a stale upsert_hook() match that leaves
# the OLD command in place on re-install.
#
# Public API: ./bin/tests/test_install_stop_cadence.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, git, node (transitively, via build.sh), mktemp.
#
# Downstream consumers: developer running locally before commit; CI.
#
# Failure modes: any assertion failure prints the failing assertion and exits
#                1. A temporary fake HOME is used; the real ~/.claude is never
#                touched. install.sh requires FOUR distinct prompt-suppression
#                seeds (see below) across THREE mechanisms - `< /dev/null`
#                alone does NOT suppress ae_confirm, which reads /dev/tty
#                directly. Re-derive the seed list if this test starts
#                hanging: `grep -nE '/dev/tty|ae_confirm|read -p'
#                .claude/install.sh scripts/lib/identity.sh` (a bare
#                `/dev/tty` grep on install.sh alone finds only 1 of 4).
#                Separately, the .claude/install.sh run below also calls
#                install_precommit_hook, which resolves the git hooks
#                directory via `git rev-parse --git-path hooks` relative to
#                the REAL REPO_DIR, independent of $HOME faking - left
#                unguarded it would rewrite this checkout's real
#                <repo>/.git/hooks/pre-commit symlink. Guarded via
#                bin/tests/lib/precommit-hook-guard.sh: saved before the
#                install.sh call and restored unconditionally in the EXIT
#                trap.
#
# Performance: ~10-15 s wall time (one .claude/install.sh run, which builds
#              all adapters via .claude/build.sh + .cursor/build.sh).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

# shellcheck source=bin/tests/lib/precommit-hook-guard.sh
. "$REPO_DIR/bin/tests/lib/precommit-hook-guard.sh"

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
  precommit_hook_guard_restore
  rm -rf "$TMP_ROOT"
}
trap _cleanup EXIT

FAKE_HOME="$TMP_ROOT/home"
mkdir -p "$FAKE_HOME/.claude"

# Save the real pre-commit hook slot before the install.sh call below.
precommit_hook_guard_save "$REPO_DIR"

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
# THE core assertions - read the GENERATED settings.json, never install.sh's
# own source.
# ---------------------------------------------------------------------------

STOP_CMD="$(python3 -c "
import json
with open('$SETTINGS') as f:
    d = json.load(f)
for block in d.get('hooks', {}).get('Stop', []):
    for h in block.get('hooks', []):
        if 'stop-context.js' in h.get('command', ''):
            print(h['command'])
" 2>/dev/null)"

if [[ -z "$STOP_CMD" ]]; then
  _fail "no Stop hook command found containing stop-context.js in generated settings.json"
elif [[ "$STOP_CMD" =~ /stop-context\.js\ --cadence=turn($|[[:space:]]) ]]; then
  _pass "installed Stop hook command matches /stop-context.js --cadence=turn(\\s|\$): '$STOP_CMD'"
else
  _fail "installed Stop hook command does NOT match /stop-context.js --cadence=turn(\\s|\$): '$STOP_CMD'"
fi

SESSION_END_CMD="$(python3 -c "
import json
with open('$SETTINGS') as f:
    d = json.load(f)
for block in d.get('hooks', {}).get('SessionEnd', []):
    for h in block.get('hooks', []):
        if 'session-end-wrap.js' in h.get('command', ''):
            print(h['command'])
" 2>/dev/null)"

if [[ -n "$SESSION_END_CMD" ]]; then
  _pass "SessionEnd hook still names session-end-wrap.js: '$SESSION_END_CMD'"
else
  _fail "SessionEnd hook does NOT name session-end-wrap.js (generated settings.json has no matching entry)"
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
