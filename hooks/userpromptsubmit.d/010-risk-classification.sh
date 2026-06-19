#!/usr/bin/env bash
# Purpose: Emits the risk-classification instruction as plain text so Claude Code
#          folds it into additionalContext on every UserPromptSubmit event.
# Public API: bash hooks/userpromptsubmit.d/010-risk-classification.sh (no args; drains stdin)
# Upstream deps: none
# Downstream consumers: dino-dispatch.py (UserPromptSubmit event leaf)
# Failure modes: always exits 0; stdout is the risk-classification text
# Performance: <1ms; pure echo

# Drain stdin (dispatcher pipes the JSON payload; we do not use it)
cat > /dev/null

echo 'BEFORE ANY ACTION: classify risk first. Elevated = spawn Worker + Skeptic in background. Direct action ONLY for: reads, answering from memory, screenshots, synthesizing subagent results, diagnostic-only logging. When in doubt, classify Elevated.'

exit 0
