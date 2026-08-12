#!/usr/bin/env bash
# Purpose: Regression test for the DS-54 hooks-snapshot migration across all
#          4 in-scope adapters (.claude, .codex, .gemini, .kimi). Seeds each
#          adapter's config with an OLD checkout-pointing hook entry plus one
#          unrelated third-party hook entry, runs the real install.sh with a
#          fake $HOME, and asserts: every dinostack hook entry now
#          points at the hooks snapshot (not the checkout), the third-party
#          entry survives byte-for-byte, and a second run is a no-op.
#          Section 5 adds a second assertion class scoped to
#          RISK_CMD/OLD_RISK_CMDS specifically - see that section's own
#          lettered sub-header comments in the body below for the live,
#          current set of what it asserts; do not restate that list here.
#
#          NOTE: this file's run/invocation counts have gone stale
#          repeatedly (each addition changed the actual count without
#          updating every place a count was asserted). Do not
#          reintroduce a hardcoded count anywhere in this header or below -
#          derive it live with `grep -c '^\s*if _run_install' "$0"` (or
#          equivalent) if a count is ever genuinely needed, never restate it
#          as prose.
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
#                install.sh/uninstall.sh still builds/runs against the REAL
#                checkout (like bin/tests/test_kimi_install_symlink.sh) -
#                only $HOME is sandboxed, and these real-tree effects are
#                NOT limited to the .claude uninstall.sh call: every
#                `.claude/install.sh` invocation in this file calls
#                `install_precommit_hook` (writes <repo>/.git/hooks/pre-commit)
#                and runs `.claude/build.sh` + `.cursor/build.sh`; the
#                `.gemini`/`.codex`/`.kimi` invocations run only their own
#                adapter's `build.sh`. Grep `_run_install` for the current
#                call sites. These same effects (regenerating adapter build
#                artifacts in the live tree) are also documented in
#                bin/tests/test_local_bin_ds_prefix_install.sh; empirically
#                idempotent, but none of these runs are read-only. On top
#                of that, the .claude section's uninstall.sh run (below)
#                also calls uninstall_precommit_hook, which resolves the
#                git hooks directory via `git rev-parse --git-path hooks`
#                relative to the REAL REPO_DIR, independent of $HOME faking
#                - left unguarded it would remove this checkout's real
#                <repo>/.git/hooks/pre-commit. That call is saved before
#                and restored immediately after via
#                bin/tests/lib/precommit-hook-guard.sh (same guard used by
#                bin/tests/test_uninstall_ds_prefix.sh); the guard does not
#                cover the earlier install.sh pre-commit-hook writes above.
#
# Performance: wall time scales with the `_run_install` call count (grep it
#              for the live figure - see the NOTE above); each invocation
#              includes a real build.sh pass, so expect tens of seconds
#              rather than a fixed number.

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
  rm -rf "$TMP_ROOT"
  precommit_hook_guard_restore
}
trap _cleanup EXIT INT TERM

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
    # "Not a directory" in a linked worktree or "Operation not permitted" in a
    # restricted sandbox. This reproduces identically on a pre-DS-54 checkout
    # (verified via `git stash` during authoring) - it is not introduced or
    # fixable by this change. It always fires AFTER the settings.json
    # hook-wiring step this test actually asserts on, so treat it as a
    # tolerated warning rather than a hard failure, and keep asserting on
    # the config content the run already wrote before hitting it. Any OTHER
    # non-zero exit still fails the test.
    if grep -q "Installing pre-commit hook" "$fake_home/.install_out" 2>/dev/null && \
       tail -n 5 "$fake_home/.install_out" | grep -Eq "\.git/hooks/pre-commit: (Not a directory|Operation not permitted)"; then
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

HOME_CLAUDE_UNINSTALL="$TMP_ROOT/home-claude-uninstall"
mkdir -p "$HOME_CLAUDE_UNINSTALL/.claude"

cat > "$HOME_CLAUDE_UNINSTALL/.claude/settings.json" <<'EOF'
{
  "hooks": {
    "UserPromptSubmit": [
      {"matcher": "*", "hooks": [
        {"type": "command", "command": "echo 'BEFORE ANY ACTION: classify risk first. If dinostack is active in this project, the main session is the conductor. The conductor delegates shippable edits to a named engineer Worker; Elevated work also requires a fresh Skeptic review. Direct action ONLY for: reads, answering from memory, screenshots, synthesizing already-returned subagent results (NOT new artifacts), diagnostic-only logging. When in doubt, classify Elevated.'", "timeout": 5},
        {"type": "command", "command": "echo 'BEFORE ANY ACTION: classify risk first. If agentic-engineering is active in this project, the main session is the conductor. The conductor delegates shippable edits to a named engineer Worker; Elevated work also requires a fresh Skeptic review. Direct action ONLY for: reads, answering from memory, screenshots, synthesizing already-returned subagent results (NOT new artifacts), diagnostic-only logging. When in doubt, classify Elevated.'", "timeout": 5},
        {"type": "command", "command": "python3 /opt/security/prompt-scan.py", "timeout": 10}
      ]}
    ]
  }
}
EOF

# uninstall_precommit_hook (called by .claude/uninstall.sh) resolves the
# git hooks dir independent of $HOME - save/restore the real checkout's
# pre-commit hook around this one call (see header and
# bin/tests/lib/precommit-hook-guard.sh).
precommit_hook_guard_save "$REPO_DIR"
if HOME="$HOME_CLAUDE_UNINSTALL" bash "$REPO_DIR/.claude/uninstall.sh" > "$HOME_CLAUDE_UNINSTALL/.uninstall_out" 2>&1; then
  precommit_hook_guard_restore
  _pass "claude: uninstall.sh run succeeds"
else
  precommit_hook_guard_restore
  _fail "claude: uninstall.sh exited non-zero"
  cat "$HOME_CLAUDE_UNINSTALL/.uninstall_out" >&2
fi

CLAUDE_RISK_COUNT_AFTER_UNINSTALL="$(python3 -c "
import json
with open('$HOME_CLAUDE_UNINSTALL/.claude/settings.json') as f:
    d = json.load(f)
count = 0
for block in d.get('hooks', {}).get('UserPromptSubmit', []):
    for h in block.get('hooks', []):
        if h.get('command', '').startswith('echo \\'BEFORE ANY ACTION: classify risk first.'):
            count += 1
print(count)
")"

if [[ "$CLAUDE_RISK_COUNT_AFTER_UNINSTALL" == "0" ]]; then
  _pass "claude: uninstall removes current and migrated risk reminder commands"
else
  _fail "claude: uninstall left $CLAUDE_RISK_COUNT_AFTER_UNINSTALL risk reminder command(s)"
fi

CLAUDE_THIRD_PARTY_AFTER_UNINSTALL="$(python3 -c "
import json
with open('$HOME_CLAUDE_UNINSTALL/.claude/settings.json') as f:
    d = json.load(f)
for block in d.get('hooks', {}).get('UserPromptSubmit', []):
    for h in block.get('hooks', []):
        if h.get('command') == 'python3 /opt/security/prompt-scan.py':
            print(h['command'])
")"

if [[ "$CLAUDE_THIRD_PARTY_AFTER_UNINSTALL" == "python3 /opt/security/prompt-scan.py" ]]; then
  _pass "claude: uninstall preserves unrelated UserPromptSubmit hooks"
else
  _fail "claude: uninstall removed or altered unrelated UserPromptSubmit hook"
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

if HOME="$HOME_CODEX" bash "$REPO_DIR/.codex/uninstall.sh" > "$HOME_CODEX/.uninstall_out" 2>&1; then
  _pass "codex: uninstall.sh run succeeds"
else
  _fail "codex: uninstall.sh exited non-zero"
  cat "$HOME_CODEX/.uninstall_out" >&2
fi

if [[ ! -e "$HOME_CODEX/.codex/hooks.json" && ! -L "$HOME_CODEX/.codex/hooks.json" ]]; then
  _pass "codex: uninstall removes snapshot-backed hooks.json symlink"
else
  _fail "codex: uninstall left hooks.json behind: $(readlink "$HOME_CODEX/.codex/hooks.json" 2>/dev/null || echo '<not symlink>')"
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
# 5. OLD_RISK_CMDS historical coverage + install collapse-to-one
#    (Skeptic round 1 on fix/delegation-suppression-gaps: 1 Critical +
#    1 Major - OLD_RISK_CMDS omitted the pre-rename "agentic-engineering"
#    variant that actually shipped, and install.sh only migrated the
#    FIRST stale entry when more than one was present.)
# =============================================================
echo ""
echo "=== 5. OLD_RISK_CMDS historical coverage + install collapse-to-one ==="

# Byte-exact fixture data - pinned here, NOT derived via a git-log call at
# test time (a git-log-at-test-time approach would re-derive the same
# possibly-wrong answer the Critical finding was about). Recovered once via
# `git show <sha>:.claude/install.sh` against the commit that introduced
# each superseded RISK_CMD value (f4f60ebab5, 4d4b9e2199, 0b242bca,
# 1e777841) and pinned verbatim below.
FIXTURE_OLDEST="echo 'BEFORE ANY ACTION: classify risk first. Elevated = spawn Worker + Skeptic in background. Direct action ONLY for: reads, answering from memory, screenshots, synthesizing subagent results, diagnostic-only logging. When in doubt, classify Elevated.'"
FIXTURE_SECOND="echo 'BEFORE ANY ACTION: classify risk first. Elevated = spawn Worker + Skeptic in background. Direct action ONLY for: reads, answering from memory, screenshots, synthesizing already-returned subagent results (NOT new artifacts), diagnostic-only logging. When in doubt, classify Elevated.'"
FIXTURE_PRE_RENAME="echo 'BEFORE ANY ACTION: classify risk first. If agentic-engineering is active in this project, the main session is the conductor. The conductor delegates shippable edits to a named engineer Worker; Elevated work also requires a fresh Skeptic review. Direct action ONLY for: reads, answering from memory, screenshots, synthesizing already-returned subagent results (NOT new artifacts), diagnostic-only logging. When in doubt, classify Elevated.'"
FIXTURE_POST_RENAME="echo 'BEFORE ANY ACTION: classify risk first. If dinostack is active in this project, the main session is the conductor. The conductor delegates shippable edits to a named engineer Worker; Elevated work also requires a fresh Skeptic review. Direct action ONLY for: reads, answering from memory, screenshots, synthesizing already-returned subagent results (NOT new artifacts), diagnostic-only logging. When in doubt, classify Elevated.'"

# (a) every previously-shipped RISK_CMD literal is present in OLD_RISK_CMDS,
#     for both .claude/install.sh and .claude/uninstall.sh.
_assert_old_risk_cmds_coverage() {
  local file="$1"
  local label="$2"
  local extracted
  extracted="$(python3 -c "
import re, json, sys

def _strip_py_comments(text):
    out = []
    for line in text.split('\n'):
        idx = line.find('#')
        out.append(line if idx == -1 else line[:idx])
    return '\n'.join(out)

QSTR = r'\"(?:[^\"\\\\]|\\\\.)*\"'

def extract(path):
    src = open(path).read()
    m = re.search(r'^RISK_CMD = \(\n(.*?)\n\)\n', src, re.M | re.S)
    risk_cmd = ''.join(s[1:-1] for s in re.findall(QSTR, m.group(1)))
    m2 = re.search(r'^OLD_RISK_CMDS = \{\n(.*?)\n\}\n', src, re.M | re.S)
    old_block = _strip_py_comments(m2.group(1))
    tuple_re = re.compile(r'\(\s*((?:' + QSTR + r'\s*)+)\)', re.S)
    old_cmds = []
    for tm in tuple_re.finditer(old_block):
        strs = re.findall(QSTR, tm.group(1))
        old_cmds.append(''.join(s[1:-1] for s in strs))
    return risk_cmd, old_cmds

risk_cmd, old_cmds = extract(sys.argv[1])
print(json.dumps({'risk_cmd': risk_cmd, 'old_cmds': old_cmds}))
" "$file")"

  local ok=1
  for fixture in "$FIXTURE_OLDEST" "$FIXTURE_SECOND" "$FIXTURE_PRE_RENAME" "$FIXTURE_POST_RENAME"; do
    if ! python3 -c "
import json, sys
d = json.loads(sys.argv[1])
sys.exit(0 if sys.argv[2] in d['old_cmds'] else 1)
" "$extracted" "$fixture" 2>/dev/null; then
      ok=0
      _fail "$label: OLD_RISK_CMDS is missing a byte-exact historical value: '${fixture:0:70}...'"
    fi
  done
  if [[ "$ok" == "1" ]]; then
    _pass "$label: OLD_RISK_CMDS covers all 4 historically-shipped-but-superseded RISK_CMD values"
  fi

  # The current RISK_CMD must never itself sit inside OLD_RISK_CMDS (that
  # would make the "already present" branch unreachable).
  if python3 -c "
import json, sys
d = json.loads(sys.argv[1])
sys.exit(1 if d['risk_cmd'] in d['old_cmds'] else 0)
" "$extracted" 2>/dev/null; then
    _pass "$label: current RISK_CMD is not duplicated inside OLD_RISK_CMDS"
  else
    _fail "$label: current RISK_CMD is ALSO present in OLD_RISK_CMDS (self-referential)"
  fi
}

_assert_old_risk_cmds_coverage "$REPO_DIR/.claude/install.sh" "claude install.sh"
_assert_old_risk_cmds_coverage "$REPO_DIR/.claude/uninstall.sh" "claude uninstall.sh"

# (b) install.sh collapses N pre-existing current/stale risk-classification
#     entries down to exactly 1, in a single run - not just the first match.
HOME_CLAUDE_MULTI="$TMP_ROOT/home-claude-multi-stale"
mkdir -p "$HOME_CLAUDE_MULTI/.claude"

cat > "$HOME_CLAUDE_MULTI/.claude/settings.json" <<EOF
{
  "hooks": {
    "UserPromptSubmit": [
      {"matcher": "*", "hooks": [
        {"type": "command", "command": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$FIXTURE_OLDEST"), "timeout": 5},
        {"type": "command", "command": "python3 /opt/security/prompt-scan-multi.py", "timeout": 10},
        {"type": "command", "command": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$FIXTURE_PRE_RENAME"), "timeout": 5},
        {"type": "command", "command": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$FIXTURE_POST_RENAME"), "timeout": 5}
      ]}
    ]
  }
}
EOF

if _run_install "$REPO_DIR/.claude/install.sh" "$HOME_CLAUDE_MULTI"; then
  _pass "claude (multi-stale): install.sh run succeeds with 3 pre-existing risk-classification entries"
else
  _fail "claude (multi-stale): install.sh exited non-zero"
fi

MULTI_RISK_COUNT="$(python3 -c "
import json
with open('$HOME_CLAUDE_MULTI/.claude/settings.json') as f:
    d = json.load(f)
count = 0
for block in d.get('hooks', {}).get('UserPromptSubmit', []):
    for h in block.get('hooks', []):
        if h.get('command', '').startswith(\"echo 'BEFORE ANY ACTION: classify risk first.\"):
            count += 1
print(count)
")"

if [[ "$MULTI_RISK_COUNT" == "1" ]]; then
  _pass "claude (multi-stale): 3 pre-existing risk-classification entries collapse to exactly 1"
else
  _fail "claude (multi-stale): expected exactly 1 risk-classification entry after install, found $MULTI_RISK_COUNT"
fi

MULTI_THIRD_PARTY="$(python3 -c "
import json
with open('$HOME_CLAUDE_MULTI/.claude/settings.json') as f:
    d = json.load(f)
for block in d.get('hooks', {}).get('UserPromptSubmit', []):
    for h in block.get('hooks', []):
        if h.get('command') == 'python3 /opt/security/prompt-scan-multi.py':
            print(h['command'])
")"

if [[ "$MULTI_THIRD_PARTY" == "python3 /opt/security/prompt-scan-multi.py" ]]; then
  _pass "claude (multi-stale): unrelated third-party UserPromptSubmit hook survives the collapse"
else
  _fail "claude (multi-stale): unrelated third-party hook was altered or removed by the collapse"
fi

# (c) a true no-op (single entry, already current) must NOT rewrite an
#     operator's customized timeout - Skeptic round 2 Minor 1.
HOME_CLAUDE_CUSTOM_TIMEOUT="$TMP_ROOT/home-claude-custom-timeout"
mkdir -p "$HOME_CLAUDE_CUSTOM_TIMEOUT/.claude"

# Seed a settings.json holding the CURRENT RISK_CMD (extracted live from
# install.sh, not a fixture constant - it must match exactly or this seeds
# a "stale" entry instead of a no-op one) at a customized timeout of 30.
python3 -c "
import json, re, sys

def extract_risk_cmd(path):
    src = open(path).read()
    m = re.search(r'^RISK_CMD = \(\n(.*?)\n\)\n', src, re.M | re.S)
    QSTR = r'\"(?:[^\"\\\\]|\\\\.)*\"'
    return ''.join(s[1:-1] for s in re.findall(QSTR, m.group(1)))

risk_cmd = extract_risk_cmd(sys.argv[1])
settings = {
    'hooks': {
        'UserPromptSubmit': [
            {'matcher': '*', 'hooks': [
                {'type': 'command', 'command': risk_cmd, 'timeout': 30}
            ]}
        ]
    }
}
with open(sys.argv[2], 'w') as f:
    json.dump(settings, f, indent=2)
" "$REPO_DIR/.claude/install.sh" "$HOME_CLAUDE_CUSTOM_TIMEOUT/.claude/settings.json"

if _run_install "$REPO_DIR/.claude/install.sh" "$HOME_CLAUDE_CUSTOM_TIMEOUT"; then
  _pass "claude (custom timeout): install.sh run succeeds on an already-current entry with timeout=30"
else
  _fail "claude (custom timeout): install.sh exited non-zero"
fi

CUSTOM_TIMEOUT_AFTER="$(python3 -c "
import json
with open('$HOME_CLAUDE_CUSTOM_TIMEOUT/.claude/settings.json') as f:
    d = json.load(f)
for block in d.get('hooks', {}).get('UserPromptSubmit', []):
    for h in block.get('hooks', []):
        if h.get('command', '').startswith(\"echo 'BEFORE ANY ACTION: classify risk first.\"):
            print(h.get('timeout'))
")"

if [[ "$CUSTOM_TIMEOUT_AFTER" == "30" ]]; then
  _pass "claude (custom timeout): already-current no-op does not reset an operator's customized timeout"
else
  _fail "claude (custom timeout): expected timeout=30 preserved, got '$CUSTOM_TIMEOUT_AFTER'"
fi

# (d) the was_current no-op branch DOES repair a missing "type" key (via
#     setdefault) while still leaving a present timeout untouched - Skeptic
#     round 5 Minor 2. Seed an entry with the CURRENT RISK_CMD and a
#     customized timeout but NO "type" key at all.
HOME_CLAUDE_MISSING_TYPE="$TMP_ROOT/home-claude-missing-type"
mkdir -p "$HOME_CLAUDE_MISSING_TYPE/.claude"

python3 -c "
import json, re, sys

def extract_risk_cmd(path):
    src = open(path).read()
    m = re.search(r'^RISK_CMD = \(\n(.*?)\n\)\n', src, re.M | re.S)
    QSTR = r'\"(?:[^\"\\\\]|\\\\.)*\"'
    return ''.join(s[1:-1] for s in re.findall(QSTR, m.group(1)))

risk_cmd = extract_risk_cmd(sys.argv[1])
settings = {
    'hooks': {
        'UserPromptSubmit': [
            {'matcher': '*', 'hooks': [
                {'command': risk_cmd, 'timeout': 45}
            ]}
        ]
    }
}
with open(sys.argv[2], 'w') as f:
    json.dump(settings, f, indent=2)
" "$REPO_DIR/.claude/install.sh" "$HOME_CLAUDE_MISSING_TYPE/.claude/settings.json"

if _run_install "$REPO_DIR/.claude/install.sh" "$HOME_CLAUDE_MISSING_TYPE"; then
  _pass "claude (missing type): install.sh run succeeds on an already-current entry with no type key"
else
  _fail "claude (missing type): install.sh exited non-zero"
fi

MISSING_TYPE_RESULT="$(python3 -c "
import json
with open('$HOME_CLAUDE_MISSING_TYPE/.claude/settings.json') as f:
    d = json.load(f)
for block in d.get('hooks', {}).get('UserPromptSubmit', []):
    for h in block.get('hooks', []):
        if h.get('command', '').startswith(\"echo 'BEFORE ANY ACTION: classify risk first.\"):
            print(f\"{h.get('type')}|{h.get('timeout')}\")
")"

if [[ "$MISSING_TYPE_RESULT" == "command|45" ]]; then
  _pass "claude (missing type): setdefault repairs the missing type to 'command' while timeout=45 stays untouched"
else
  _fail "claude (missing type): expected 'command|45', got '$MISSING_TYPE_RESULT'"
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
