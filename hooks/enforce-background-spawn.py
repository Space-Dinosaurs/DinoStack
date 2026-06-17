#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that enforces the METHODOLOGY §Delegation background-by-default
         rule by denying any Task (subagent spawn) tool call that lacks
         run_in_background: true. Converts a prose advisory into a hard gate on
         Claude Code. Feeds the deny reason back to the model so it can re-issue
         the call correctly. Documented foreground-exempt agents (see
         FOREGROUND_EXEMPT) are allowed regardless of run_in_background.
         Confirmed-supported floor: Claude Code 2.1.178+ (the modern
         permissionDecision: "deny" path this hook emits is stable from that
         release). The hook fails open on parse error, so older builds degrade
         to no-enforcement rather than breaking.

Public API: Run as a Claude Code PreToolUse hook. Reads JSON from stdin,
            writes hookSpecificOutput JSON to stdout when denying, exits 0 always.

Upstream deps: Python 3 stdlib only (json, sys). No external dependencies.

Downstream consumers: Claude Code hook runner (PreToolUse event for the Task tool).
                      Wired via ~/.claude/settings.json by .claude/install.sh.

Failure modes:
    - Malformed stdin: fail-open (exit 0, no deny). A hook bug must never brick
      all spawns - the conductor can still work, just without enforcement.
    - Null or non-dict tool_input: fail-open (exit 0). Same contract - any parse
      or logic error exits 0 so enforcement gaps are never converted to blanket
      blocks.
    - Non-Task tool_name: passthrough (exit 0). This hook is scoped to Task only.
    - run_in_background absent, false, or non-boolean: deny with reason fed back
      to model. Only boolean True is accepted as the allow signal.
    - Foreground-exempt subagent_type (FOREGROUND_EXEMPT): allow regardless of
      run_in_background - these agents have a documented blocking-ordering
      requirement (e.g. wrap-ticket holds .agentic/wrap.lock).
    - Older Claude Code versions (pre-permissionDecision support, issue #4669):
      if a future version ignores permissionDecision: deny, switch to exit 2 with
      the reason on stderr as the fallback enforcement path.

Performance: < 1 ms per call (pure in-memory JSON parse + single print, no I/O).
"""

import json
import sys

# Documented foreground-exempt agents. wrap-ticket runs foreground/blocking
# in /implement-ticket Phase 11b: it holds .agentic/wrap.lock and MUST complete
# before Phase 12 cleanup, so it cannot be forced to background. This is the
# only methodology-sanctioned foreground Task spawn. Add others here only with
# an equivalent documented blocking-ordering requirement.
FOREGROUND_EXEMPT = {"wrap-ticket"}


def main() -> None:
    try:
        # Fail-open: never block on malformed input - a broken hook must not
        # prevent the conductor from spawning workers at all.
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        # Only enforce on Task (subagent spawn). All direct-action tools
        # (Read, Bash, Write, Edit, Glob, Grep, etc.) never use Task, so
        # there are no false positives from a blanket Task-scoped deny.
        if data.get("tool_name") != "Task":
            sys.exit(0)

        # tool_input may be null/missing. Null means no structured params -
        # treat as fail-open since we cannot make an enforcement decision
        # without a dict to inspect. `or {}` also handles missing key.
        raw_tinput = data.get("tool_input")
        if raw_tinput is None:
            sys.exit(0)
        tinput = raw_tinput if isinstance(raw_tinput, dict) else {}

        # Allow documented foreground-exempt agents regardless of run_in_background.
        if tinput.get("subagent_type") in FOREGROUND_EXEMPT:
            sys.exit(0)

        # Allow correctly-formed background spawns. Accept only boolean True -
        # string "false", 0, None, and other truthy-but-not-true values all deny.
        if tinput.get("run_in_background") is True:
            sys.exit(0)

        # Deny foreground spawns and feed back a clear, actionable reason
        # so the conductor re-issues with run_in_background: true.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Task spawn blocked: run_in_background is missing or false. "
                    "All delegated subagent spawns MUST set run_in_background: true "
                    "(METHODOLOGY.md §Delegation). Re-issue the Task call with "
                    "run_in_background: true. Direct-action cases (reads, memory "
                    "answers, synthesis) do not use Task at all - use the appropriate "
                    "dedicated tool instead."
                )
            }
        }))
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        # The fail-open promise must hold for every input shape.
        sys.exit(0)


if __name__ == "__main__":
    main()
