#!/usr/bin/env bash
# Kimi SessionStart hook - Agentic Engineering activation check
#
# Prints a visible reminder when entering a project where dinostack
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

# Check if project has dinostack marker or .kimi/AGENTS.md
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

# Only show reminder if the project looks like it should use dinostack
# (has marker OR has .kimi/AGENTS.md OR mode=opt-out with no explicit opt-out marker)
if [[ "$has_marker" == "true" ]]; then
  >&2 echo ""
  >&2 echo "┌─────────────────────────────────────────────────────────────────────┐"
  >&2 echo "│  dinostack: ACTIVE in this project                        │"
  >&2 echo "│  Load the skill: /skill:dinostack                         │"
  >&2 echo "│  Classify risk first. Main session is the conductor.                │"
  >&2 echo "│  Shippable edits go to named engineer Workers; Elevated also        │"
  >&2 echo "│  requires a fresh Skeptic. Low-risk direct action remains OK.       │"
  >&2 echo "└─────────────────────────────────────────────────────────────────────┘"
  >&2 echo ""
fi

# Emit skill-load instruction to stdout when skill_auto_load is enabled.
# Note: Kimi hook stdout routing to agent context is unverified per Kimi CLI docs.
# If stdout is not injected into agent context, this instruction is terminal-only.
# Update to use the correct channel once confirmed.
if [[ "$skill_auto_load" == "true" ]]; then
  echo "SKILL CHECK [dinostack]: skill_auto_load=true."
  echo "Before responding to any software development request, read ~/.kimi/skills/dinostack/SKILL.md."
  echo "Classify risk first. If dinostack is active, the main session is the conductor: delegate shippable edits to a named engineer Worker; Elevated work also requires a fresh Skeptic; Low-risk reads, diagnostics, synthesis, and other allowed Low tasks remain direct-action OK."
fi

exit 0
