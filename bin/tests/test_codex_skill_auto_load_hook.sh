#!/usr/bin/env bash
# Purpose: Regression test for Codex skill auto-load hook wiring. Codex already
#          always-loads the full methodology via .codex/AGENTS.md, so the shared
#          skill-auto-load-check.sh script gates Codex out unconditionally
#          (DS-143) - it must emit zero output regardless of skill_auto_load.
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

if [[ "$out" != *"$HOME_CODEX/.claude/skills/agentic-engineering/SKILL.md"* ]]; then
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
# ---------------------------------------------------------------------------
HOME_CLAUDE="$TMP_ROOT/home-claude"
CLAUDE_SCRIPT_DIR="$TMP_ROOT/claude-hooks"
mkdir -p "$HOME_CLAUDE/.claude" "$CLAUDE_SCRIPT_DIR"

printf '{"skill_auto_load": true}\n' > "$HOME_CLAUDE/.claude/agentic-engineering.json"
cp "$REPO_DIR/hooks/skill-auto-load-check.sh" "$CLAUDE_SCRIPT_DIR/skill-auto-load-check.sh"

claude_out="$(HOME="$HOME_CLAUDE" bash "$CLAUDE_SCRIPT_DIR/skill-auto-load-check.sh" 2>&1)"
if [[ "$claude_out" == *"SKILL CHECK [agentic-engineering]"* ]]; then
  pass "non-codex/non-gemini invocation (Claude's real shape) still emits the skill-load nudge"
else
  fail "expected the skill-load nudge for a non-codex/non-gemini invocation, got: $claude_out"
fi

echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
