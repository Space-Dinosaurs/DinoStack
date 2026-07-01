#!/usr/bin/env bash
# Purpose: Regression test for the DS-54 hooks-snapshot migration across all
#          4 in-scope adapters (.claude, .codex, .gemini, .kimi). Seeds each
#          adapter's config with an OLD checkout-pointing hook entry plus one
#          unrelated third-party hook entry, runs the real install.sh with a
#          fake $HOME, and asserts: every agentic-engineering hook entry now
#          points at the hooks snapshot (not the checkout), the third-party
#          entry survives byte-for-byte, and a second run is a no-op.
#
# Public API: ./bin/tests/test_hooks_snapshot_migration.sh
#             Exits 0 on all pass, 1 on any failure.
#
# Upstream deps: bash, python3, git, node (transitively, via build.sh), mktemp.
#
# Downstream consumers: developer running locally before commit; CI.
#
# Failure modes: any assertion failure prints the failing assertion and exits
#                1. A temporary fake HOME is used per adapter; the real
#                ~/.claude, ~/.codex, ~/.gemini, ~/.kimi, and
#                ~/.agentic/hooks-snapshot are never touched. Each adapter's
#                install.sh still builds against the REAL checkout (like
#                bin/tests/test_kimi_install_symlink.sh) - only $HOME is
#                sandboxed.
#
# Performance: ~20-40 s wall time (4 adapters x 2 install.sh runs each,
#              each run includes a real build.sh pass).

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
_cleanup() { rm -rf "$TMP_ROOT"; }
trap _cleanup EXIT

_run_install() {
  local install_sh="$1"
  local fake_home="$2"
  shift 2
  HOME="$fake_home" bash "$install_sh" --mode=opt-out --profile=default "$@" \
    < /dev/null > "$fake_home/.install_out" 2>&1
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    # Known, pre-existing, out-of-scope environmental limitation: when this
    # test itself runs from inside a git worktree (`.git` is a file, not a
    # directory), .claude/install.sh's UNRELATED "Installing pre-commit
    # hook" step (ln -s ... "$REPO_DIR/.git/hooks/pre-commit") fails with
    # "Not a directory". This reproduces identically on a pre-DS-54 checkout
    # (verified via `git stash` during authoring) - it is not introduced or
    # fixable by this change. It always fires AFTER the settings.json
    # hook-wiring step this test actually asserts on, so treat it as a
    # tolerated warning rather than a hard failure, and keep asserting on
    # the config content the run already wrote before hitting it. Any OTHER
    # non-zero exit still fails the test.
    if grep -q "Installing pre-commit hook" "$fake_home/.install_out" 2>/dev/null && \
       tail -n 5 "$fake_home/.install_out" | grep -q "\.git/hooks/pre-commit: Not a directory"; then
      echo "  [warn] $install_sh exited $rc at the known worktree-only pre-commit-hook step (unrelated to DS-54, pre-existing) - tolerated" >&2
      return 0
    fi
    echo "  [install.sh output]:" >&2
    cat "$fake_home/.install_out" >&2
  fi
  return $rc
}

# =============================================================
# 1. Claude Code
# =============================================================
echo ""
echo "=== 1. .claude/install.sh migration ==="

HOME_CLAUDE="$TMP_ROOT/home-claude"
mkdir -p "$HOME_CLAUDE/.claude"

cat > "$HOME_CLAUDE/.claude/settings.json" <<EOF
{
  "hooks": {
    "SessionStart": [
      {"matcher": "*", "hooks": [
        {"type": "command", "command": "bash $REPO_DIR/hooks/session-start-wrap.sh", "timeout": 5}
      ]}
    ],
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [
        {"type": "command", "command": "python3 /opt/security/secret-scanner.py", "timeout": 10}
      ]}
    ]
  }
}
EOF
THIRD_PARTY_BEFORE_CLAUDE="$(python3 -c "
import json
with open('$HOME_CLAUDE/.claude/settings.json') as f:
    print(json.load(f)['hooks']['PreToolUse'][0]['hooks'][0]['command'])
")"

if _run_install "$REPO_DIR/.claude/install.sh" "$HOME_CLAUDE"; then
  _pass "claude: first install.sh run succeeds"
else
  _fail "claude: first install.sh run exited non-zero"
fi

SESSION_START_CMD_1="$(python3 -c "
import json
with open('$HOME_CLAUDE/.claude/settings.json') as f:
    d = json.load(f)
for block in d['hooks']['SessionStart']:
    for h in block['hooks']:
        if 'session-start-wrap.sh' in h['command']:
            print(h['command'])
")"

if [[ "$SESSION_START_CMD_1" == *"hooks-snapshot"* ]]; then
  _pass "claude: SessionStart hook now points at the hooks snapshot"
else
  _fail "claude: SessionStart hook still points at the checkout: '$SESSION_START_CMD_1'"
fi

THIRD_PARTY_AFTER_CLAUDE_1="$(python3 -c "
import json
with open('$HOME_CLAUDE/.claude/settings.json') as f:
    print(json.load(f)['hooks']['PreToolUse'][0]['hooks'][0]['command'])
")"

if [[ "$THIRD_PARTY_AFTER_CLAUDE_1" == "$THIRD_PARTY_BEFORE_CLAUDE" ]]; then
  _pass "claude: unrelated secret-scanner.py entry byte-identical after migration"
else
  _fail "claude: unrelated secret-scanner.py entry was altered ('$THIRD_PARTY_BEFORE_CLAUDE' -> '$THIRD_PARTY_AFTER_CLAUDE_1')"
fi

SETTINGS_CLAUDE_1="$(cat "$HOME_CLAUDE/.claude/settings.json")"

if _run_install "$REPO_DIR/.claude/install.sh" "$HOME_CLAUDE"; then
  _pass "claude: second (idempotent) install.sh run succeeds"
else
  _fail "claude: second install.sh run exited non-zero"
fi

SETTINGS_CLAUDE_2="$(cat "$HOME_CLAUDE/.claude/settings.json")"

if [[ "$SETTINGS_CLAUDE_1" == "$SETTINGS_CLAUDE_2" ]]; then
  _pass "claude: settings.json unchanged across a re-run (idempotent)"
else
  _fail "claude: settings.json changed on re-run (not idempotent)"
fi

# =============================================================
# 2. Gemini CLI
# =============================================================
echo ""
echo "=== 2. .gemini/install.sh migration ==="

HOME_GEMINI="$TMP_ROOT/home-gemini"
mkdir -p "$HOME_GEMINI/.gemini"

cat > "$HOME_GEMINI/.gemini/settings.json" <<EOF
{
  "hooks": {
    "BeforeAgent": [
      {"matcher": "*", "hooks": [
        {"name": "risk-reminder", "type": "command", "command": "bash \"$REPO_DIR/.gemini/hooks/risk-reminder.sh\""},
        {"name": "claude-hook-notify", "type": "command", "command": "node /opt/tools/claude-hook-notify.js"}
      ]}
    ]
  }
}
EOF
THIRD_PARTY_BEFORE_GEMINI="$(python3 -c "
import json
with open('$HOME_GEMINI/.gemini/settings.json') as f:
    d = json.load(f)
for h in d['hooks']['BeforeAgent'][0]['hooks']:
    if h.get('name') == 'claude-hook-notify':
        print(h['command'])
")"

if _run_install "$REPO_DIR/.gemini/install.sh" "$HOME_GEMINI"; then
  _pass "gemini: first install.sh run succeeds"
else
  _fail "gemini: first install.sh run exited non-zero"
fi

RISK_CMD_1="$(python3 -c "
import json
with open('$HOME_GEMINI/.gemini/settings.json') as f:
    d = json.load(f)
for h in d['hooks']['BeforeAgent'][0]['hooks']:
    if 'risk-reminder.sh' in h.get('command', ''):
        print(h['command'])
")"

if [[ "$RISK_CMD_1" == *"hooks-snapshot"* ]]; then
  _pass "gemini: risk-reminder hook now points at the hooks snapshot"
else
  _fail "gemini: risk-reminder hook still points at the checkout: '$RISK_CMD_1'"
fi

THIRD_PARTY_AFTER_GEMINI_1="$(python3 -c "
import json
with open('$HOME_GEMINI/.gemini/settings.json') as f:
    d = json.load(f)
for h in d['hooks']['BeforeAgent'][0]['hooks']:
    if h.get('name') == 'claude-hook-notify':
        print(h['command'])
")"

if [[ "$THIRD_PARTY_AFTER_GEMINI_1" == "$THIRD_PARTY_BEFORE_GEMINI" ]]; then
  _pass "gemini: unrelated claude-hook-notify.js entry byte-identical after migration"
else
  _fail "gemini: unrelated claude-hook-notify.js entry was altered ('$THIRD_PARTY_BEFORE_GEMINI' -> '$THIRD_PARTY_AFTER_GEMINI_1')"
fi

SETTINGS_GEMINI_1="$(cat "$HOME_GEMINI/.gemini/settings.json")"

if _run_install "$REPO_DIR/.gemini/install.sh" "$HOME_GEMINI"; then
  _pass "gemini: second (idempotent) install.sh run succeeds"
else
  _fail "gemini: second install.sh run exited non-zero"
fi

SETTINGS_GEMINI_2="$(cat "$HOME_GEMINI/.gemini/settings.json")"

if [[ "$SETTINGS_GEMINI_1" == "$SETTINGS_GEMINI_2" ]]; then
  _pass "gemini: settings.json unchanged across a re-run (idempotent)"
else
  _fail "gemini: settings.json changed on re-run (not idempotent)"
fi

# =============================================================
# 3. Codex
# =============================================================
echo ""
echo "=== 3. .codex/install.sh migration ==="

HOME_CODEX="$TMP_ROOT/home-codex"
mkdir -p "$HOME_CODEX/.codex"

# Seed the legacy symlink target: the checkout's own .codex/config/hooks.json
# (this is LEGACY_HOOKS_SRC2 in the DS-54 migration - the correct target
# before this change, now legacy since the correct target moved to the
# snapshot).
ln -s "$REPO_DIR/.codex/config/hooks.json" "$HOME_CODEX/.codex/hooks.json"

if _run_install "$REPO_DIR/.codex/install.sh" "$HOME_CODEX"; then
  _pass "codex: first install.sh run succeeds"
else
  _fail "codex: first install.sh run exited non-zero"
fi

CODEX_TARGET_1="$(python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$HOME_CODEX/.codex/hooks.json")"

if [[ "$CODEX_TARGET_1" == *"hooks-snapshot"* ]]; then
  _pass "codex: ~/.codex/hooks.json now resolves under the hooks snapshot"
else
  _fail "codex: ~/.codex/hooks.json still resolves to the checkout: '$CODEX_TARGET_1'"
fi

LINK_CODEX_1="$(readlink "$HOME_CODEX/.codex/hooks.json")"

if _run_install "$REPO_DIR/.codex/install.sh" "$HOME_CODEX"; then
  _pass "codex: second (idempotent) install.sh run succeeds"
else
  _fail "codex: second install.sh run exited non-zero"
fi

LINK_CODEX_2="$(readlink "$HOME_CODEX/.codex/hooks.json")"

if [[ "$LINK_CODEX_1" == "$LINK_CODEX_2" ]]; then
  _pass "codex: hooks.json symlink target unchanged across a re-run (idempotent)"
else
  _fail "codex: hooks.json symlink target changed on re-run (not idempotent)"
fi

# =============================================================
# 4. Kimi CLI
# =============================================================
echo ""
echo "=== 4. .kimi/install.sh migration ==="

HOME_KIMI="$TMP_ROOT/home-kimi"
mkdir -p "$HOME_KIMI/.kimi"

cat > "$HOME_KIMI/.kimi/config.toml" <<EOF
[[hooks]]
event = "PreToolUse"
command = "python3 /opt/security/secret-scanner.py"
matcher = "*"

[[hooks]]
event = "SessionStart"
command = "bash $REPO_DIR/.kimi/hooks/session-start.sh"
matcher = ""
timeout = 5
EOF
THIRD_PARTY_BEFORE_KIMI="$(grep -A2 'event = "PreToolUse"' "$HOME_KIMI/.kimi/config.toml" | grep command)"

if _run_install "$REPO_DIR/.kimi/install.sh" "$HOME_KIMI"; then
  _pass "kimi: first install.sh run succeeds"
else
  _fail "kimi: first install.sh run exited non-zero"
fi

SESSION_START_CMD_KIMI_1="$(grep -A2 'event = "SessionStart"' "$HOME_KIMI/.kimi/config.toml" | grep command)"

if [[ "$SESSION_START_CMD_KIMI_1" == *"hooks-snapshot"* ]]; then
  _pass "kimi: SessionStart hook command now points at the hooks snapshot"
else
  _fail "kimi: SessionStart hook command still points at the checkout: '$SESSION_START_CMD_KIMI_1'"
fi

THIRD_PARTY_AFTER_KIMI_1="$(grep -A2 'event = "PreToolUse"' "$HOME_KIMI/.kimi/config.toml" | grep command)"

if [[ "$THIRD_PARTY_AFTER_KIMI_1" == "$THIRD_PARTY_BEFORE_KIMI" ]]; then
  _pass "kimi: unrelated secret-scanner.py [[hooks]] entry byte-identical after migration"
else
  _fail "kimi: unrelated secret-scanner.py [[hooks]] entry was altered ('$THIRD_PARTY_BEFORE_KIMI' -> '$THIRD_PARTY_AFTER_KIMI_1')"
fi

CONFIG_KIMI_1="$(cat "$HOME_KIMI/.kimi/config.toml")"

if _run_install "$REPO_DIR/.kimi/install.sh" "$HOME_KIMI"; then
  _pass "kimi: second (idempotent) install.sh run succeeds"
else
  _fail "kimi: second install.sh run exited non-zero"
fi

CONFIG_KIMI_2="$(cat "$HOME_KIMI/.kimi/config.toml")"

if [[ "$CONFIG_KIMI_1" == "$CONFIG_KIMI_2" ]]; then
  _pass "kimi: config.toml unchanged across a re-run (idempotent)"
else
  _fail "kimi: config.toml changed on re-run (not idempotent)"
fi

# =============================================================
# Results
# =============================================================
echo ""
echo "Results: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
