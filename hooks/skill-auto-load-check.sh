#!/usr/bin/env bash
# Purpose: Emits a skill-load instruction to stdout when skill_auto_load is enabled in the
#          dinostack config AND the current turn's prompt looks like a software-development
#          request (applicability filter, DS-218 round 3). Called by Claude Code, Codex, and
#          Gemini hook handlers. Neither Codex nor Gemini always-loads the full methodology via
#          its own root file anymore: as of DS-183, .codex/AGENTS.md is a minimal trigger-load
#          stub (not an always-loaded embed), and as of DS-184, .gemini/GEMINI.md is likewise a
#          small stub pointing at the trigger-loaded dinostack skill
#          (.gemini/skills/dinostack/SKILL.md). Both harnesses now get the same nudge Claude
#          Code does, each pointed at its own skill load path - without it, a session with
#          skill_auto_load=true gets neither the resident body nor a nudge, and the skill loads
#          only if the model voluntarily follows its stub's own "load on trigger" prose.
# Public API: bash hooks/skill-auto-load-check.sh (no args; reads ~/.claude/agentic-engineering.json
#             for skill_auto_load, and optionally a JSON payload on stdin with a "prompt" string
#             field - two structurally-independent command substitutions, not one). No stdin
#             piped (legacy invocation shape) is a supported input and always fires when
#             skill_auto_load=true. AE_ADAPTER=gemini selects the Gemini skill_path branch
#             (Gemini has no reliable script-dir signature to detect on its own, so its hook
#             wiring must set this explicitly). Codex is auto-detected via script_dir
#             (*/.codex/hooks) - AE_ADAPTER=codex is not set anywhere in this repo, so detection
#             must not depend on it being present.
# Upstream deps: ~/.claude/agentic-engineering.json (optional; missing = silent exit). Best-effort
#                stdin JSON payload, "prompt" field only, read via a single bounded os.read
#                capped at 65536 bytes (never a buffered/looping read - see Failure modes).
# Downstream consumers: .claude/install.sh (UserPromptSubmit hook), .codex/config/hooks.json
#                       (UserPromptSubmit hook), .gemini/install.sh (BeforeAgent hook)
# Failure modes: always exits 0; missing config or false flag = silent no-op; a confidently
#                non-matching prompt suppresses the banner; every stdin failure mode - select
#                timeout, partial/truncated payload, malformed JSON, missing or non-string
#                "prompt", an empty or whitespace-only "prompt" string, decode error -
#                resolves to "unknown" and FIRES (fail-open), never silently suppresses (round
#                4 Major 1: empty/whitespace prompt is absence of evidence, not a confident
#                negative, so it must fire like an absent prompt does, not suppress like a
#                genuine no-match does); the content read cannot hang past the select timeout
#                because it is a single os.read syscall, never a buffered read that loops
#                toward EOF; never blocks the hook chain.
# Performance: when skill_auto_load is false, the content_state read is skipped entirely (round
#              4 Minor 1) - only the one python3 JSON parse for the config flag runs. When
#              skill_auto_load is true, bounded to ~1s worst case by the select() timeout, then
#              one non-blocking os.read syscall and one regex match - never proportional to
#              producer behavior.
# Note (round 5): the `skill_auto_load == "true"` operand in the final condition (below) is
#                 redundant with the earlier guard that gates content_state, since content_state
#                 can only ever be something other than "no_match" when that guard already ran.
#                 It is kept as defense-in-depth against a future edit to the guard, not because
#                 it is load-bearing today - the flag's load-bearing gate is the earlier guard.

ae_config="$HOME/.claude/agentic-engineering.json"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
adapter="${AE_ADAPTER:-}"
if [[ -z "$adapter" && "$script_dir" == *"/.codex/hooks" ]]; then
  adapter="codex"
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

# Structurally independent of the substitution above: this one's failure mode is
# "unknown" (fire), never "false" (silence). A hard death here (process kill,
# exception, timeout) must never be conflatable with a confidently-false config flag -
# that conflation is exactly what round 1 and round 2 got wrong (see module manifest).
# Gated behind skill_auto_load: when the flag is false the final condition below can
# never fire regardless of content_state, so skip the python3 spawn and bounded read
# entirely rather than pay their cost on every turn for a user who has the feature off
# (round 4 Minor 1 - this cannot change fail-open semantics since the default below is
# "no_match", the same value the AND with skill_auto_load already forces in that case).
content_state="no_match"
if [[ "$skill_auto_load" == "true" ]]; then
  content_state=$(python3 -c "
import json, os, re, select, sys
try:
    ready, _, _ = select.select([sys.stdin], [], [], 1.0)
    if not ready:
        print('unknown')
    else:
        # os.read is a single syscall returning whatever is currently available.
        # It never loops toward EOF like sys.stdin.read()/TextIOWrapper.read() do -
        # that looping is what defeated the select() bound in round 2.
        data = os.read(sys.stdin.fileno(), 65536)
        payload = json.loads(data.decode('utf-8'))
        prompt = payload.get('prompt')
        # An empty or whitespace-only string is absence of evidence, not a negative
        # determination - it must resolve to 'unknown' (fire) via the except branch,
        # never fall through to the pattern match on '' (which would report
        # 'no_match' and silently suppress the banner every turn - round 4 Major 1).
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('prompt missing, not a string, or empty/whitespace-only')
        pattern = re.compile(
            r'\b(code|edit|debug|test|deploy|architect|refactor|depend|implement|'
            r'ticket|build|script|commit|merge|spawn|agent|plan|git|orchestrat|'
            r'review|bug|hook)|\bpr\b|pull request',
            re.IGNORECASE,
        )
        print('match' if pattern.search(prompt) else 'no_match')
except Exception:
    print('unknown')
" 2>/dev/null || echo "unknown")
fi

if [[ "$skill_auto_load" == "true" && "$content_state" != "no_match" ]]; then
  case "$adapter" in
    gemini)
      skill_path="$HOME/.gemini/skills/dinostack/SKILL.md"
      load_instruction="invoke the dinostack skill (activate_skill), or read $skill_path directly if activate_skill is unavailable in this session"
      ;;
    codex)
      skill_path="$HOME/.agents/skills/dinostack/SKILL.md"
      load_instruction="read $skill_path"
      ;;
    *)
      skill_path="$HOME/.claude/skills/dinostack/SKILL.md"
      load_instruction="read $skill_path"
      ;;
  esac
  echo "SKILL CHECK [dinostack]: skill_auto_load=true."
  echo "Before responding to any software development request, $load_instruction."
  echo "Do not implement directly - follow the delegation and risk classification protocol in that file."
fi

exit 0
