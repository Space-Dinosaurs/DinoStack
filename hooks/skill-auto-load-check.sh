#!/usr/bin/env bash
# Purpose: Emits a skill-load instruction to stdout when skill_auto_load is enabled in the
#          dinostack config. Called by Claude Code, Codex, and Gemini hook handlers.
#          Gemini already always-loads the full methodology via its own root file
#          (.gemini/GEMINI.md), so this script gates Gemini out unconditionally before even
#          reading the flag - the nudge would be pure waste for it. Codex does NOT get this
#          treatment (DS-183): .codex/AGENTS.md is now a minimal trigger-load stub, not an
#          always-loaded embed of the full methodology, so Codex needs this nudge exactly like
#          Claude Code does - without it, a Codex session with skill_auto_load=true gets
#          neither the resident body nor a nudge, and the skill loads only if the model
#          voluntarily follows the stub's own "load on trigger" prose.
# Public API: bash hooks/skill-auto-load-check.sh (no args; reads ~/.claude/agentic-engineering.json)
#             AE_ADAPTER=gemini selects the Gemini skip path (Gemini has no reliable script-dir
#             signature to detect on its own, so its hook wiring must set this explicitly).
#             Codex is auto-detected via script_dir (*/.codex/hooks) - AE_ADAPTER=codex is not
#             set anywhere in this repo, so detection must not depend on it being present; it
#             selects the Codex-specific skill path below, not a skip.
# Upstream deps: ~/.claude/agentic-engineering.json (optional; missing = silent exit)
# Downstream consumers: .claude/install.sh (UserPromptSubmit hook), .codex/config/hooks.json
#                       (UserPromptSubmit hook), .gemini/install.sh (BeforeAgent hook)
# Failure modes: always exits 0; missing config, false flag, or gemini adapter = silent
#                no-op; never blocks hook chain
# Performance: <5ms on the gemini exit path (shell only, no python3);
#              <50ms otherwise (adds one python3 JSON parse)

ae_config="$HOME/.claude/agentic-engineering.json"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
adapter="${AE_ADAPTER:-}"
if [[ -z "$adapter" && "$script_dir" == *"/.codex/hooks" ]]; then
  adapter="codex"
fi

# Gemini's own root file already always-loads the full methodology, so it gets zero
# benefit from this nudge, regardless of the skill_auto_load flag - checked BEFORE
# reading the flag so this always fires for it. Codex is deliberately NOT in this
# case (DS-183) - see the Purpose comment above.
case "$adapter" in
  gemini)
    exit 0
    ;;
esac

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
  # Codex loads skills from $HOME/.agents/skills/, never $HOME/.claude/skills/ -
  # the Claude-specific path below would be wrong for a Codex session.
  if [[ "$adapter" == "codex" ]]; then
    skill_path="$HOME/.agents/skills/dinostack/SKILL.md"
  else
    skill_path="$HOME/.claude/skills/dinostack/SKILL.md"
  fi
  echo "SKILL CHECK [dinostack]: skill_auto_load=true."
  echo "Before responding to any software development request, read $skill_path."
  echo "Do not implement directly - follow the delegation and risk classification protocol in that file."
fi

exit 0
