#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that enforces two METHODOLOGY rules on Claude Code:
         (1) Background-by-default rule - denies any Task (subagent spawn) that
         lacks run_in_background: true (existing behavior, unchanged).
         (2) Cross-harness team sentinel suppression - when a DinoStack cross-
         harness team run is active (sentinel <cwd>/.agentic/teamrun/.active
         exists and is LIVE), denies Task spawns outright AND denies Skill calls
         whose skill name starts with "oh-my-claudecode:" (OMC-skill detection).
         Tells the conductor to use `bin/agentic-team dispatch` instead.
         The sentinel is treated as EXPIRED (suppression lifted) when the PID it
         names is dead OR its mtime is older than 2 h - so a crashed conductor
         does not permanently suppress native Task spawns.
         Confirmed-supported floor: Claude Code 2.1.178+ (the modern
         permissionDecision: "deny" path this hook emits is stable from that
         release). The hook fails open on parse error, so older builds degrade
         to no-enforcement rather than breaking.

Public API: Run as a Claude Code PreToolUse hook. Reads JSON from stdin,
            writes hookSpecificOutput JSON to stdout when denying, exits 0 always.

Upstream deps: Python 3 stdlib only (json, os, sys, time, pathlib). No external
               dependencies.

Downstream consumers: Claude Code hook runner (PreToolUse event for Task and
                      Skill tools). Wired via ~/.claude/settings.json by
                      .claude/install.sh (no new wiring needed - same hook entry).

Failure modes:
    - Malformed stdin: fail-open (exit 0, no deny). A hook bug must never brick
      all spawns - the conductor can still work, just without enforcement.
    - Null or non-dict tool_input: fail-open (exit 0). Same contract - any parse
      or logic error exits 0 so enforcement gaps are never converted to blanket
      blocks.
    - Non-Task/non-Skill tool_name: passthrough (exit 0).
    - run_in_background absent, false, or non-boolean on Task: deny with reason
      fed back to model. Only boolean True is accepted as the allow signal.
    - Foreground-exempt subagent_type (FOREGROUND_EXEMPT): allow regardless of
      run_in_background - these agents have a documented blocking-ordering
      requirement (e.g. wrap-ticket holds .agentic/wrap.lock).
    - Sentinel present but PID dead or mtime > 2 h: sentinel treated as expired;
      normal background-spawn enforcement resumes. Fail-open on sentinel read
      errors.
    - Older Claude Code versions (pre-permissionDecision support, issue #4669):
      if a future version ignores permissionDecision: deny, switch to exit 2 with
      the reason on stderr as the fallback enforcement path.

Performance: < 2 ms per call (pure in-memory JSON parse + optional stat/proc
             check, no network I/O).
"""

import json
import os
import sys
import time
from pathlib import Path

# Documented foreground-exempt agents. wrap-ticket runs foreground/blocking
# in /implement-ticket Phase 11b: it holds .agentic/wrap.lock and MUST complete
# before Phase 12 cleanup, so it cannot be forced to background. This is the
# only methodology-sanctioned foreground Task spawn. Add others here only with
# an equivalent documented blocking-ordering requirement.
FOREGROUND_EXEMPT = {"wrap-ticket"}

# Sentinel path relative to cwd.
_SENTINEL_REL = ".agentic/teamrun/.active"

# Maximum age (seconds) before a sentinel is treated as stale regardless of PID.
_SENTINEL_MAX_AGE_S = 2 * 60 * 60  # 2 hours


def _sentinel_is_live(cwd: str) -> bool:
    """Return True iff the DinoStack team sentinel is present AND live.

    Live = file exists AND PID on first line is alive AND mtime <= 2 h old.
    Any I/O or parse error returns False (fail-open - suppression never sticks
    on a broken sentinel file).
    """
    sentinel = Path(cwd) / _SENTINEL_REL
    try:
        if not sentinel.exists():
            return False

        age = time.time() - sentinel.stat().st_mtime
        if age > _SENTINEL_MAX_AGE_S:
            return False

        first_line = sentinel.read_text(encoding="utf-8").splitlines()[0].strip()
        pid = int(first_line)

        # os.kill(pid, 0) raises OSError when the process does not exist.
        # NOTE: PID reuse - if the original conductor died and the OS recycled
        # its PID to a different process within the 2 h mtime window, this
        # check gives a false-live result. The mtime cap (_SENTINEL_MAX_AGE_S)
        # is the backstop: a sentinel older than 2 h is treated as expired
        # regardless of whether the PID happens to be alive.
        try:
            os.kill(pid, 0)
        except OSError:
            return False

        return True
    except Exception:
        # Any read/parse/stat error -> treat as absent (fail-open).
        return False


def _deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main() -> None:
    try:
        # Fail-open: never block on malformed input - a broken hook must not
        # prevent the conductor from spawning workers at all.
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        tool_name = data.get("tool_name")

        # ------------------------------------------------------------------ #
        # Foreground-exempt check (MUST come before sentinel suppression)    #
        # wrap-ticket holds .agentic/wrap.lock and MUST complete before      #
        # Phase 12 cleanup - it is the only sanctioned foreground Task.      #
        # Exemption applies regardless of sentinel state, so check first.    #
        # ------------------------------------------------------------------ #
        if tool_name == "Task":
            raw_tinput_early = data.get("tool_input")
            tinput_early = raw_tinput_early if isinstance(raw_tinput_early, dict) else {}
            if tinput_early.get("subagent_type") in FOREGROUND_EXEMPT:
                sys.exit(0)

        # ------------------------------------------------------------------ #
        # Cross-harness sentinel suppression (Unit 5b)                       #
        # Applies to non-exempt Task spawns and oh-my-claudecode:* Skills.   #
        # Exempt agents (wrap-ticket) already exited above.                  #
        # ------------------------------------------------------------------ #
        if tool_name in ("Task", "Skill"):
            cwd = data.get("cwd") or os.getcwd()
            if _sentinel_is_live(cwd):
                if tool_name == "Task":
                    _deny(
                        "Task spawn blocked: a DinoStack cross-harness team run is "
                        "active (.agentic/teamrun/.active sentinel present and live). "
                        "Dispatch workers via `bin/agentic-team dispatch` instead of "
                        "native Task. To resume native delegation, wait for the team "
                        "run to complete or run `agentic-team status --reap` to clear "
                        "an expired sentinel."
                    )
                # Skill: only block oh-my-claudecode:* calls.
                # The Claude Code Skill tool passes the skill name in
                # tool_input["skill"] - confirmed by PreToolUse payload
                # inspection and the existing test fixtures in
                # bin/tests/test_enforce_background_spawn.py (lines 176, 193).
                # We do NOT fall back to a "name" field: an absent or
                # unrecognised field means we cannot determine the skill -
                # fail-open (allow) rather than silently misidentify.
                tinput = data.get("tool_input")
                skill_name = ""
                if isinstance(tinput, dict):
                    raw = tinput.get("skill")
                    if isinstance(raw, str):
                        skill_name = raw
                if skill_name.startswith("oh-my-claudecode:"):
                    _deny(
                        f"Skill '{skill_name}' blocked: a DinoStack cross-harness "
                        "team run is active (.agentic/teamrun/.active sentinel "
                        "present and live). OMC skills must not be invoked while "
                        "the DinoStack team layer owns dispatch. Use "
                        "`bin/agentic-team dispatch` to assign work to workers."
                    )
                # Non-OMC Skill, Skill with absent/unrecognised field, or no
                # sentinel -> allow (fail-open).
                sys.exit(0)

        # ------------------------------------------------------------------ #
        # Existing background-spawn enforcement (behavior unchanged)          #
        # ------------------------------------------------------------------ #

        # Only enforce on Task (subagent spawn). All direct-action tools
        # (Read, Bash, Write, Edit, Glob, Grep, etc.) never use Task, so
        # there are no false positives from a blanket Task-scoped deny.
        if tool_name != "Task":
            sys.exit(0)

        # tool_input may be null/missing. Null means no structured params -
        # treat as fail-open since we cannot make an enforcement decision
        # without a dict to inspect. `or {}` also handles missing key.
        raw_tinput = data.get("tool_input")
        if raw_tinput is None:
            sys.exit(0)
        tinput = raw_tinput if isinstance(raw_tinput, dict) else {}

        # Foreground-exempt agents were already allowed before the sentinel
        # suppression block above. Any Task that reaches here is non-exempt.

        # Allow correctly-formed background spawns. Accept only boolean True -
        # string "false", 0, None, and other truthy-but-not-true values all deny.
        if tinput.get("run_in_background") is True:
            sys.exit(0)

        # Deny foreground spawns and feed back a clear, actionable reason
        # so the conductor re-issues with run_in_background: true.
        _deny(
            "Task spawn blocked: run_in_background is missing or false. "
            "All delegated subagent spawns MUST set run_in_background: true "
            "(METHODOLOGY.md §Delegation). Re-issue the Task call with "
            "run_in_background: true. Direct-action cases (reads, memory "
            "answers, synthesis) do not use Task at all - use the appropriate "
            "dedicated tool instead."
        )

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        # The fail-open promise must hold for every input shape.
        sys.exit(0)


if __name__ == "__main__":
    main()
