#!/usr/bin/env bash
# Purpose: Emits a skill-load instruction to stdout when skill_auto_load is enabled in the
#          agentic-engineering config. Called by Claude Code, Codex, and Gemini hook handlers.
# Public API: bash hooks/skill-auto-load-check.sh (no args; reads ~/.claude/agentic-engineering.json)
# Upstream deps: ~/.claude/agentic-engineering.json (optional; missing = silent exit)
# Downstream consumers: .claude/install.sh (UserPromptSubmit hook), .codex/config/hooks.json
#                       (UserPromptSubmit hook), .gemini/install.sh (BeforeAgent hook)
# Failure modes: always exits 0; missing config or false flag = silent no-op; never blocks hook chain
# Performance: <50ms; python3 JSON parse only

ae_config="$HOME/.claude/agentic-engineering.json"

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
  echo "SKILL CHECK [agentic-engineering]: skill_auto_load=true."
  echo "Before responding to any software development request, read ~/.claude/skills/agentic-engineering/SKILL.md."
  echo "Do not implement directly - follow the delegation and risk classification protocol in that file."
fi

exit 0
