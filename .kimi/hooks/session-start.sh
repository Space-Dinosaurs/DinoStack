#!/usr/bin/env bash
# Kimi SessionStart hook - Agentic Engineering activation check
#
# Prints a visible reminder when entering a project where agentic-engineering
# should be active. Kimi CLI SessionStart hook stdout is logged; we print to
# stderr for visibility in the terminal.
#
# Input: JSON on stdin with {session_id, cwd, source}
# Output: none (exit 0 = allow session to start)

set -euo pipefail

read -r input

# Extract cwd from JSON (simple parse, robust enough for our payload)
cwd=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || echo "")
source=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('source',''))" 2>/dev/null || echo "")

if [[ -z "$cwd" ]]; then
  exit 0
fi

# Check if project has agentic-engineering marker or .kimi/AGENTS.md
has_marker=false
if [[ -f "$cwd/AGENTS.md" ]]; then
  if grep -qi "agentic-engineering: opt-in" "$cwd/AGENTS.md" 2>/dev/null; then
    has_marker=true
  fi
fi
if [[ -f "$cwd/.kimi/AGENTS.md" ]]; then
  has_marker=true
fi

# Also check global config mode
ae_config="$HOME/.claude/agentic-engineering.json"
mode="opt-out"
skill_auto_load="false"
if [[ -f "$ae_config" ]]; then
  mode=$(python3 -c "
import json, sys
try:
    with open('$ae_config') as f:
        print(json.load(f).get('mode', 'opt-out'))
except Exception:
    print('opt-out')
" 2>/dev/null || echo "opt-out")
  skill_auto_load=$(python3 -c "
import json, sys
try:
    with open('$ae_config') as f:
        val = json.load(f).get('skill_auto_load', False)
    print('true' if val is True else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")
fi

# Only show reminder if the project looks like it should use agentic-engineering
# (has marker OR has .kimi/AGENTS.md OR mode=opt-out with no explicit opt-out marker)
if [[ "$has_marker" == "true" ]]; then
  >&2 echo ""
  >&2 echo "┌─────────────────────────────────────────────────────────────────────┐"
  >&2 echo "│  agentic-engineering: ACTIVE in this project                        │"
  >&2 echo "│  Load the skill: /skill:agentic-engineering                         │"
  >&2 echo "│  Conductor rule: delegate ALL work to subagents. No direct tools.   │"
  >&2 echo "└─────────────────────────────────────────────────────────────────────┘"
  >&2 echo ""
fi

# Emit skill-load instruction to stdout when skill_auto_load is enabled.
# Note: Kimi hook stdout routing to agent context is unverified per Kimi CLI docs.
# If stdout is not injected into agent context, this instruction is terminal-only.
# Update to use the correct channel once confirmed.
if [[ "$skill_auto_load" == "true" ]]; then
  echo "SKILL CHECK [agentic-engineering]: skill_auto_load=true."
  echo "Before responding to any software development request, read ~/.kimi/skills/agentic-engineering/SKILL.md."
  echo "Do not implement directly - follow the delegation and risk classification protocol in that file."
fi

# Newer-version-available notice (shared core; Kimi cannot use systemMessage,
# so the message is printed to stderr like the activation reminder above).
# The core resolves the clone dir + cache and prints the notice only when the
# local clone is behind upstream. AGENTIC_QUIET=1 suppresses it.
version_core="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/hooks/lib/version-check-core.sh"
if [[ "${AGENTIC_QUIET:-}" != "1" && -f "$version_core" ]]; then
  version_msg="$(bash "$version_core" 2>/dev/null || echo "")"
  if [[ -n "$version_msg" ]]; then
    >&2 echo "$version_msg"
  fi
fi

exit 0
