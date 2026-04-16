#!/usr/bin/env bash
# Cursor beforeSubmitPrompt hook — Risk classification reminder
#
# Mirrors the Claude Code risk-reminder hook. Plain text on stdout is added
# as extra context injected before the user's prompt.
#
# Input: JSON on stdin (prompt, etc.) - not used here.
# Output: Plain text on stdout injected as context before the turn.
#
# This hook is configured in .cursor/hooks.json.

cat <<'REMINDER'
BEFORE ANY ACTION: classify risk first.
- Elevated risk = spawn Worker + Skeptic in background. Do NOT act directly.
- Direct action ONLY for: reads, answering from memory, screenshots, synthesizing subagent results, diagnostic-only logging.
- When in doubt, classify Elevated.
REMINDER
