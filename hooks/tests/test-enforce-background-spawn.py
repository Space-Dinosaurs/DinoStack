# Run with: python3 hooks/tests/test-enforce-background-spawn.py
"""
Unit tests for hooks/enforce-background-spawn.py.

Each case pipes a JSON payload (or malformed string) into the hook via stdin
and asserts ALLOW (exit 0, no deny output) or DENY (exit 0, deny in stdout).
"""

import json
import os
import subprocess
import sys

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-background-spawn.py"
)


def run_hook(payload: str) -> tuple[int, str, str]:
    # AE_TEAM_ROUTING_DISABLE=1 isolates these background-enforcement /
    # sentinel-suppression cases from the team-routing branch (Unit D) so a
    # real ~/.agentic/team.yml on the machine running this suite can't
    # spuriously deny a case these tests never intended to exercise.
    # Team-routing behavior has its own coverage in
    # bin/tests/test_enforce_background_spawn.py.
    env = dict(os.environ)
    env["AE_TEAM_ROUTING_DISABLE"] = "1"
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def is_allow(returncode: int, stdout: str) -> bool:
    """ALLOW: exit 0 and no deny decision in stdout."""
    if returncode != 0:
        return False
    if not stdout.strip():
        return True
    try:
        obj = json.loads(stdout)
        decision = (
            obj.get("hookSpecificOutput", {}).get("permissionDecision", "")
        )
        return decision != "deny"
    except Exception:
        return True  # unparseable output -> not a deny


def is_deny(returncode: int, stdout: str) -> bool:
    """DENY: exit 0 and permissionDecision == deny in stdout."""
    if returncode != 0:
        return False
    try:
        obj = json.loads(stdout)
        decision = (
            obj.get("hookSpecificOutput", {}).get("permissionDecision", "")
        )
        return decision == "deny"
    except Exception:
        return False


cases = [
    # (label, payload_str, expected)
    # --- Legacy tool_name="Task" cases ---
    (
        "Task: run_in_background=true - ALLOW",
        json.dumps({"tool_name": "Task", "tool_input": {"run_in_background": True}}),
        "ALLOW",
    ),
    (
        "Task: run_in_background=false - DENY",
        json.dumps({"tool_name": "Task", "tool_input": {"run_in_background": False}}),
        "DENY",
    ),
    (
        "Task: run_in_background absent - DENY",
        json.dumps({"tool_name": "Task", "tool_input": {}}),
        "DENY",
    ),
    (
        "Task: run_in_background=null - DENY",
        json.dumps({"tool_name": "Task", "tool_input": {"run_in_background": None}}),
        "DENY",
    ),
    (
        "Task: run_in_background string 'true' - DENY (only boolean True accepted)",
        json.dumps({"tool_name": "Task", "tool_input": {"run_in_background": "true"}}),
        "DENY",
    ),
    (
        "Task: foreground-exempt wrap-ticket - ALLOW",
        json.dumps({
            "tool_name": "Task",
            "tool_input": {"subagent_type": "wrap-ticket", "run_in_background": False},
        }),
        "ALLOW",
    ),
    # --- tool_name="Agent" cases ---
    # Agent spawns are NOT background-enforced by this hook. The Claude Code
    # harness strips run_in_background from the Agent PreToolUse hook payload
    # (verified by live payload capture: tool_input keys for Agent are exactly
    # ['description', 'prompt', 'subagent_type'] - run_in_background is absent).
    # Agent is background-by-default at the harness level; enforcing it here
    # would brick every Agent spawn. Background enforcement applies to legacy
    # Task only. Sentinel suppression still applies to Agent (tested in
    # bin/tests/test_enforce_background_spawn.py).
    (
        "Agent: realistic harness payload (no run_in_background) - ALLOW",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {
                "description": "Implement the feature",
                "prompt": "...",
                "subagent_type": "engineer",
            },
        }),
        "ALLOW",
    ),
    (
        "Agent: run_in_background=false - ALLOW (not enforced for Agent; harness strips this field)",
        json.dumps({"tool_name": "Agent", "tool_input": {"run_in_background": False}}),
        "ALLOW",
    ),
    (
        "Agent: run_in_background absent - ALLOW (mirrors real harness payload shape)",
        json.dumps({"tool_name": "Agent", "tool_input": {}}),
        "ALLOW",
    ),
    (
        "Agent: run_in_background=true - ALLOW (enforcement not required; bg is harness default)",
        json.dumps({"tool_name": "Agent", "tool_input": {"run_in_background": True}}),
        "ALLOW",
    ),
    (
        "Agent: foreground-exempt wrap-ticket - ALLOW",
        json.dumps({
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "wrap-ticket", "run_in_background": False},
        }),
        "ALLOW",
    ),
    # --- Other tool passthrough ---
    (
        "non-Task/Agent tool (passthrough) - ALLOW",
        json.dumps({"tool_name": "Read", "tool_input": {}}),
        "ALLOW",
    ),
    (
        "malformed json - ALLOW (fail-open)",
        "not-json",
        "ALLOW",
    ),
    (
        "null tool_input - ALLOW (fail-open)",
        json.dumps({"tool_name": "Task", "tool_input": None}),
        "ALLOW",
    ),
    (
        "Agent: null tool_input - ALLOW (fail-open)",
        json.dumps({"tool_name": "Agent", "tool_input": None}),
        "ALLOW",
    ),
]

failed = 0
for label, payload, expected in cases:
    rc, stdout, stderr = run_hook(payload)
    if expected == "ALLOW":
        ok = is_allow(rc, stdout)
    else:
        ok = is_deny(rc, stdout)
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         payload:  {payload}")
        print(f"         rc:       {rc}")
        print(f"         stdout:   {stdout!r}")
        print(f"         stderr:   {stderr!r}")
        print(f"         expected: {expected}")

print()
if failed == 0:
    print(f"All {len(cases)} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{len(cases)} tests FAILED.")
    sys.exit(1)
