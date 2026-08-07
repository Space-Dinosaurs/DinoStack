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

echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
