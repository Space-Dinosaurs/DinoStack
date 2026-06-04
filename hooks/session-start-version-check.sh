#!/usr/bin/env bash
# Purpose: Claude Code SessionStart wrapper for the "newer version available"
#          notice. Calls the adapter-neutral core and, when the core prints a
#          non-empty notice, emits it as a SessionStart `systemMessage` (shown
#          to the user, NOT added to Claude's context). When there is nothing to
#          say, emits a bare `{"suppressOutput": true}`.
# Public API: bash hooks/session-start-version-check.sh
#             (reads SessionStart JSON on stdin, ignores it; writes a single
#              JSON object to stdout; always exits 0.)
# Upstream deps: hooks/lib/version-check-core.sh (resolution + cache + refresh),
#                python3 (JSON-escapes the message), AGENTIC_QUIET env var.
# Downstream consumers: Claude Code SessionStart hook, wired via
#                       ~/.claude/settings.json by .claude/install.sh.
# Failure modes: always exits 0 (fail-open). If the core fails or prints nothing
#                the wrapper emits `{"suppressOutput": true}`. AGENTIC_QUIET=1
#                suppresses the systemMessage but still emits suppressOutput so
#                the SessionStart contract is satisfied.
# Performance: one subshell call to the core (read path is sub-10ms, no blocking
#              network) plus one python3 invocation to build JSON.

set -euo pipefail

# Drain stdin without blocking the hook if no payload is sent.
cat >/dev/null 2>&1 || true

CORE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/version-check-core.sh"

msg=""
if [[ -f "$CORE" ]]; then
  msg="$(bash "$CORE" 2>/dev/null || echo "")"
fi

# AGENTIC_QUIET=1 suppresses the user-facing message but still satisfies the
# SessionStart JSON contract with suppressOutput.
if [[ "${AGENTIC_QUIET:-}" == "1" ]]; then
  msg=""
fi

if [[ -n "$msg" ]]; then
  # Build the JSON with python3 so the message is correctly escaped.
  python3 -c "
import json, sys
print(json.dumps({'systemMessage': sys.argv[1], 'suppressOutput': True}))
" "$msg" 2>/dev/null || printf '{"suppressOutput": true}\n'
else
  printf '{"suppressOutput": true}\n'
fi

exit 0
