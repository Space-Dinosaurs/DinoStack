#!/usr/bin/env bash
# Purpose: Regression test for Codex skill auto-load hook wiring. Codex already
#          always-loads the full methodology via .codex/AGENTS.md, so the shared
#          skill-auto-load-check.sh script gates Codex out unconditionally
#          (DS-143) - it must emit zero output regardless of skill_auto_load.
#          Also carries a positive control asserting the opposite for a
#          non-codex/non-gemini (Claude's real) invocation shape: the nudge
#          must still reach stdout intact, with exit 0, and nothing on stderr.
# Public API: bash bin/tests/test_codex_skill_auto_load_hook.sh

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

PASS=0
FAIL=0

pass() { echo "PASS: $*"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $*" >&2; FAIL=$((FAIL + 1)); }

TMP_ROOT="$(mktemp -d)"
cleanup() { rm -rf "$TMP_ROOT"; }
trap cleanup EXIT

HOME_CODEX="$TMP_ROOT/home-codex"
SNAPSHOT="$TMP_ROOT/snapshot"
mkdir -p "$HOME_CODEX/.claude" "$HOME_CODEX/.codex" "$SNAPSHOT/.codex/config" "$SNAPSHOT/.codex/hooks"

printf '{"skill_auto_load": true}\n' > "$HOME_CODEX/.claude/agentic-engineering.json"
cp "$REPO_DIR/.codex/config/hooks.json" "$SNAPSHOT/.codex/config/hooks.json"
cp "$REPO_DIR/.codex/hooks/skill-auto-load-check.sh" "$SNAPSHOT/.codex/hooks/skill-auto-load-check.sh"
ln -s "$SNAPSHOT/.codex/config/hooks.json" "$HOME_CODEX/.codex/hooks.json"

skill_cmd="$(python3 - "$SNAPSHOT/.codex/config/hooks.json" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
for block in data["hooks"]["UserPromptSubmit"]:
    for hook in block["hooks"]:
        command = hook.get("command", "")
        if "skill-auto-load-check.sh" in command:
            print(command)
            raise SystemExit(0)
raise SystemExit("skill-auto-load-check command not found")
PYEOF
)"

if [[ "$skill_cmd" =~ ^bash[[:space:]]+\".+skill-auto-load-check\.sh\"$ ]]; then
  pass "codex hook command keeps '<interpreter> \"<path>\"' shape"
else
  fail "codex hook command does not keep '<interpreter> \"<path>\"' shape: $skill_cmd"
fi

if [[ "$skill_cmd" == *'$(dirname "$(dirname "$(realpath "$HOME/.codex/hooks.json")")")/hooks/skill-auto-load-check.sh'* ]]; then
  pass "codex hook command targets hooks.json-adjacent codex hook snapshot"
else
  fail "codex hook command does not target hooks.json-adjacent codex hook snapshot: $skill_cmd"
fi

out="$(HOME="$HOME_CODEX" bash -c "$skill_cmd" 2>&1)"
if [[ -z "$out" ]]; then
  pass "codex skill auto-load emits zero output (Codex already always-loads via .codex/AGENTS.md)"
else
  fail "expected zero output for codex, got: $out"
fi

if [[ "$out" != *"$HOME_CODEX/.claude/skills/dinostack/SKILL.md"* ]]; then
  pass "codex skill auto-load output does not point at Claude skill path"
else
  fail "codex output still points at Claude skill path: $out"
fi

# ---------------------------------------------------------------------------
# Positive control: a non-codex, non-gemini invocation (Claude's real shape -
# no AE_ADAPTER, script_dir NOT ending /.codex/hooks) must still emit the
# nudge. Without this assertion, deleting the entire gate (or short-circuiting
# the whole script) is invisible to this suite - it would still report
# 0 failed with every adapter silently getting zero output, including Claude.
#
# This hook's entire contract is stdout - Claude Code's UserPromptSubmit
# hook injects only stdout as context and never surfaces stderr to the
# model - so stdout and stderr are captured SEPARATELY below (never merged
# via 2>&1) and each is asserted on its own. The full three-line body and
# the exact skill path are asserted individually so a truncated or
# mis-pathed nudge fails, and the exit code is asserted because every call
# site invokes this script via $(...) without checking $? - Claude Code
# treats a non-zero UserPromptSubmit exit as blocking, so a silent exit 1
# here would be a real regression this suite must catch.
# ---------------------------------------------------------------------------
HOME_CLAUDE="$TMP_ROOT/home-claude"
CLAUDE_SCRIPT_DIR="$TMP_ROOT/claude-hooks"
mkdir -p "$HOME_CLAUDE/.claude" "$CLAUDE_SCRIPT_DIR"

printf '{"skill_auto_load": true}\n' > "$HOME_CLAUDE/.claude/agentic-engineering.json"
cp "$REPO_DIR/hooks/skill-auto-load-check.sh" "$CLAUDE_SCRIPT_DIR/skill-auto-load-check.sh"

CLAUDE_STDERR="$TMP_ROOT/claude-stderr.log"
claude_out="$(HOME="$HOME_CLAUDE" bash "$CLAUDE_SCRIPT_DIR/skill-auto-load-check.sh" 2>"$CLAUDE_STDERR")"
claude_rc=$?
claude_err="$(cat "$CLAUDE_STDERR")"

if [[ "$claude_out" == *"SKILL CHECK [dinostack]"* ]]; then
  pass "non-codex/non-gemini invocation (Claude's real shape) still emits the skill-load banner on stdout"
else
  fail "expected the skill-load banner on stdout for a non-codex/non-gemini invocation, got stdout: $claude_out"
fi

if [[ "$claude_out" == *"$HOME_CLAUDE/.claude/skills/dinostack/SKILL.md"* ]]; then
  pass "non-codex/non-gemini invocation points at the Claude skill path"
else
  fail "expected the Claude skill path on stdout, got stdout: $claude_out"
fi

if [[ "$claude_out" == *"Do not implement directly"* ]]; then
  pass "non-codex/non-gemini invocation emits the full three-line nudge body"
else
  fail "expected the third nudge line ('Do not implement directly') on stdout, got stdout: $claude_out"
fi

if [[ -z "$claude_err" ]]; then
  pass "non-codex/non-gemini invocation writes nothing to stderr"
else
  fail "expected empty stderr for a non-codex/non-gemini invocation, got stderr: $claude_err"
fi

if [[ "$claude_rc" -eq 0 ]]; then
  pass "non-codex/non-gemini invocation exits 0"
else
  fail "expected exit code 0 for a non-codex/non-gemini invocation, got: $claude_rc"
fi

echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
