#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that enforces the METHODOLOGY §Delegation
         orchestrator-singularity invariant by denying any subagent spawn
         issued from inside a subagent context. Only the main conductor
         session may spawn subagents; workers must return BLOCKED when they
         would otherwise try to delegate further. This converts a prose
         advisory into a hard gate on Claude Code.

         NOTE - Task/Agent rename: Claude Code renamed the subagent-spawn tool
         from "Task" to "Agent" in a recent release. This hook guards on BOTH
         names (`tool_name in ("Task", "Agent")`) for backward compatibility
         across Claude Code versions. The settings.json matcher is also wired
         for both names by install.sh (two PreToolUse blocks: one for "Task",
         one for "Agent"). The hook fires under either name; the internal guard
         is defensive belt-and-suspenders.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task" or "Agent").
            Reads JSON from stdin, writes hookSpecificOutput JSON to stdout when
            denying, exits 0 always. `would_deny(data: dict) -> str | None` is a
            pure, side-effect-free re-implementation of `main()`'s deny decision
            over the same top-level PreToolUse payload shape - imported by path
            by hooks/enforce-skeptic-round-cap.py's sibling-deny consultation.

Upstream deps: Python 3 stdlib only (os, sys, json, importlib.util). No
               external dependencies. `from __future__ import annotations`
               keeps the file importable on Python 3.8/3.9 (the `would_deny`
               PEP 604 `X | None` hint would otherwise crash there - same
               reason enforce-tier.py and enforce-skeptic-neutrality.py
               carry the same import). Best-effort dynamic import of the
               sibling hooks/lib/enforcement_log.py fire-logging helper -
               a failed import degrades to a no-op logger, never a crash.

Downstream consumers: Claude Code hook runner (PreToolUse event for the Task /
                      Agent tool). Wired via ~/.claude/settings.json by
                      .claude/install.sh (two matcher blocks: "Task" and "Agent").
                      hooks/enforce-skeptic-round-cap.py also imports this
                      module by path (importlib) for its `would_deny` function,
                      consulted before persisting round state - see that hook's
                      "Sibling-deny consultation" docstring paragraph.

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
    - Non-Task/Agent tool_name: passthrough (exit 0). Scoped to Task/Agent only.
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

from __future__ import annotations

import json
import os
import sys


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Falls back to a no-op when the sibling module cannot be loaded (missing
    file, syntax error, snapshot copy drift) - fire-logging is additive
    telemetry, never a hard dependency of the enforcement decision itself.

    Called lazily from inside the deny branch (never at module scope) so the
    overwhelming majority of invocations - every silent allow, and every
    kill-switched invocation that exits before reaching the deny branch -
    never read, compile, or exec this file at all.
    """
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "lib", "enforcement_log.py")
        spec = _ilu.spec_from_file_location("enforcement_log", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


def would_deny(data: dict) -> str | None:
    """Pure, side-effect-free re-implementation of `main()`'s deny decision,
    at the same top-level PreToolUse payload shape `main()` reads from
    stdin. Returns the deny reason string `main()` would print, or None
    when this hook would not deny (including a set kill switch, a
    non-Task/Agent tool_name, an absent/non-string/blank agent_id, or
    malformed input). Never calls `print`, `_load_log_fire`, or
    `sys.exit`; never raises.

    Consulted by hooks/enforce-skeptic-round-cap.py (via importlib by path)
    before persisting round state, so a spawn this hook would deny never
    advances the round counter - see that hook's module docstring."""
    if os.environ.get("AE_SINGULARITY_GUARD_DISABLE") == "1":
        return None
    try:
        if not isinstance(data, dict):
            return None

        # Only enforce on Task/Agent (subagent spawn). Claude Code renamed
        # this tool from "Task" to "Agent"; guard on both names so the hook
        # works across CC versions. install.sh wires two matcher blocks
        # ("Task" and "Agent") for belt-and-suspenders coverage.
        if data.get("tool_name") not in ("Task", "Agent"):
            return None

        # Read agent_id from the TOP LEVEL of the payload (not tool_input).
        # Absent or non-string agent_id means main conductor or ambiguous -
        # always allow to prevent blocking the conductor.
        agent_id = data.get("agent_id")
        if not (isinstance(agent_id, str) and agent_id.strip()):
            return None

        # Deny: a subagent attempted to spawn a nested subagent.
        tool_name = data.get("tool_name", "Task/Agent")
        return (
            tool_name
            + " spawn blocked: a subagent (agent_id="
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
    except Exception:
        return None


def main() -> None:
    # Kill-switch: fail-open immediately before touching stdin.
    if os.environ.get("AE_SINGULARITY_GUARD_DISABLE") == "1":
        sys.exit(0)

    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        deny_reason = would_deny(data)
        if deny_reason is None:
            sys.exit(0)

        # Decision print comes FIRST, unconditionally. Telemetry is loaded
        # and called only after the decision has reached stdout, and is
        # wrapped in its own try/except so a raising log_fire (e.g. a
        # signature mismatch from a half-applied lib snapshot) can never
        # suppress or follow this deny - see hooks/lib/enforcement_log.py
        # manifest "Failure modes".
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": deny_reason,
                    }
                }
            )
        )
        try:
            _load_log_fire()(
                data, "enforce-orchestrator-singularity", "deny", deny_reason
            )
        except Exception:
            pass
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
