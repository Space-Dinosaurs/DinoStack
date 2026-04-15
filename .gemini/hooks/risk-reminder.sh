#!/usr/bin/env bash
# Gemini BeforeAgent hook - Risk classification reminder
#
# Mirrors the Codex risk-reminder hook. Gemini's BeforeAgent hook requires
# structured JSON output to inject context into the prompt for that turn.
#
# Input: JSON on stdin (prompt, session_id, etc.) - not used here.
# Output: JSON on stdout with hookSpecificOutput.additionalContext containing
#         the reminder text, which Gemini appends to the prompt for the turn.
#
# Reference: Gemini CLI hooks reference - BeforeAgent hook output format.

cat <<'REMINDER'
{
  "hookSpecificOutput": {
    "hookEventName": "BeforeAgent",
    "additionalContext": "BEFORE ANY ACTION: classify risk first.\n- Elevated risk = spawn Worker + Skeptic in background. Do NOT act directly.\n- Direct action ONLY for: reads, answering from memory, screenshots, synthesizing subagent results, diagnostic-only logging.\n- When in doubt, classify Elevated."
  }
}
REMINDER
