#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that enforces the METHODOLOGY §Delegation
         orchestrator-singularity invariant by denying any Task (subagent
         spawn) issued from inside a subagent context. Only the main conductor
         session may spawn subagents; workers must return BLOCKED when they
         would otherwise try to delegate further. This converts a prose
         advisory into a hard gate on Claude Code.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task"). Reads
            JSON from stdin, writes hookSpecificOutput JSON to stdout when
            denying, exits 0 always.

Upstream deps: Python 3 stdlib only (os, sys, json). No external dependencies.

Downstream consumers: Claude Code hook runner (PreToolUse event for the Task
                      tool). Wired via ~/.claude/settings.json by
                      .claude/install.sh.

Failure modes:
    - Malformed stdin: fail-open (exit 0, no deny). A hook bug must never
      brick all spawns - the conductor can still work, just without enforcement.
    - Missing or null agent_id: fail-open (exit 0, ALLOW). The conductor
      session has no agent_id; ambiguous cases always allow to prevent
      false-positive blocks on the conductor.
    - Kill-switch (AE_SINGULARITY_GUARD_DISABLE=1): fail-open immediately
      (exit 0) before reading stdin. To disable: set
      AE_SINGULARITY_GUARD_DISABLE=1 in the shell that launches Claude Code,
      or remove the hook entry from ~/.claude/settings.json and restart.
    - Non-Task tool_name: passthrough (exit 0). Scoped to Task only.
    - Older Claude Code versions: if permissionDecision: deny is not
      honoured, switch to exit 2 with the reason on stderr as fallback.

Performance: < 1 ms per call (pure in-memory JSON parse + single print, no I/O).
"""

# Kill-switch + recovery:
#   To temporarily disable this guard:
#     1. Set AE_SINGULARITY_GUARD_DISABLE=1 in your environment, then restart
#        Claude Code so the hook process inherits the variable.
#     2. Alternatively, remove the "enforce-orchestrator-singularity" entry
#        from the hooks array in ~/.claude/settings.json, then restart.
#   To re-enable: unset the variable (or re-run .claude/install.sh).
#
# agent_id semantics (per official Claude Code hooks docs,
# https://code.claude.com/docs/en/hooks):
#   "Present only when the hook fires inside a subagent call. Use this to
#    distinguish subagent hook calls from main-thread calls."
#   - Main/conductor session: agent_id is ABSENT from the payload.
#   - Subagent session: agent_id is PRESENT and non-empty.
#   Therefore: deny if and only if agent_id is a non-empty string at the
#   TOP LEVEL of the parsed JSON (NOT inside tool_input).

import json
import os
import sys


def main() -> None:
    # Kill-switch: fail-open immediately before touching stdin.
    if os.environ.get("AE_SINGULARITY_GUARD_DISABLE") == "1":
        sys.exit(0)

    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        # Only enforce on Task (subagent spawn).
        if data.get("tool_name") != "Task":
            sys.exit(0)

        # Read agent_id from the TOP LEVEL of the payload (not tool_input).
        # Absent or non-string agent_id means main conductor or ambiguous -
        # always allow to prevent blocking the conductor.
        agent_id = data.get("agent_id")
        if not (isinstance(agent_id, str) and agent_id.strip()):
            sys.exit(0)

        # Deny: a subagent attempted to spawn a nested subagent.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Task spawn blocked: a subagent (agent_id="
                    + repr(agent_id)
                    + ") attempted to spawn a nested subagent. "
                    "The AE invariant is that the main conductor is the sole "
                    "orchestrator (METHODOLOGY.md §Delegation: 'No subagent can "
                    "spawn subagents - the main agent is the sole orchestrator.'). "
                    "Return BLOCKED from the current worker so the conductor can "
                    "re-route the spawn. "
                    "To disable this guard: set AE_SINGULARITY_GUARD_DISABLE=1 "
                    "and restart Claude Code."
                )
            }
        }))
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
