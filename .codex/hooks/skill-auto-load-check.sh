#!/usr/bin/env bash
# Purpose: Emits a skill-load instruction to stdout when skill_auto_load is enabled in the
#          agentic-engineering config. Called by Claude Code, Codex, and Gemini hook handlers.
# Public API: bash hooks/skill-auto-load-check.sh (no args; reads ~/.claude/agentic-engineering.json)
#             AE_ADAPTER=codex selects the Codex user-scope skill install path.
# Upstream deps: ~/.claude/agentic-engineering.json (optional; missing = silent exit)
# Downstream consumers: .claude/install.sh (UserPromptSubmit hook), .codex/config/hooks.json
#                       (UserPromptSubmit hook), .gemini/install.sh (BeforeAgent hook)
# Failure modes: always exits 0; missing config or unparseable cwd -> fail-ACTIVE; never blocks hook chain
# Performance: <10ms pure-stat guard; shell-native cwd extraction (no python3 on hot path)

ae_config="$HOME/.claude/agentic-engineering.json"

# --- Activation guard: dormant projects get no skill-load instruction. ---
# This hook otherwise ignores stdin; read it once (non-blocking) only to extract
# cwd for the guard. Fail-ACTIVE: missing lib / unparseable cwd -> run normally.
script_dir_guard="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$script_dir_guard/lib/activation.sh" ]]; then
  _payload="$(cat 2>/dev/null || true)"
  # Shell-native cwd extraction: first top-level "cwd" string value.
  # Handles compact or pretty-printed JSON; escaped quotes in the path are not
  # supported, but a parse failure falls through to fail-ACTIVE.
  _cwd="$(printf '%s' "$_payload" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  # shellcheck source=/dev/null
  source "$script_dir_guard/lib/activation.sh" 2>/dev/null || true
  if declare -f ae_is_active >/dev/null 2>&1 && [[ -n "$_cwd" ]]; then
    ae_is_active "$_cwd" || exit 0
  fi
fi

skill_auto_load=$(python3 -c "
import json, sys
try:
    with open('$ae_config') as f:
        val = json.load(f).get('skill_auto_load', False)
        print('true' if val is True else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")

if [[ "$skill_auto_load" == "true" ]]; then
  skill_path="$HOME/.claude/skills/agentic-engineering/SKILL.md"
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ "${AE_ADAPTER:-}" == "codex" || "$script_dir" == *"/.codex/hooks" ]]; then
    skill_path="$HOME/.agents/skills/agentic-engineering/SKILL.md"
  fi
  echo "SKILL CHECK [agentic-engineering]: skill_auto_load=true."
  echo "Before responding to any software development request, read $skill_path."
  echo "Do not implement directly - follow the delegation and risk classification protocol in that file."
fi

exit 0
