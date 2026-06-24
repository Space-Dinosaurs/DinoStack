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
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
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
    # --- Regression tests: tool_name="Agent" (CC rename, was failing silently) ---
    # Against the buggy guard (tool_name != "Task" -> sys.exit(0)), all of
    # these would incorrectly ALLOW. After the fix they must enforce normally.
    (
        "Agent: run_in_background=true - ALLOW (regression: was silently ALLOW)",
        json.dumps({"tool_name": "Agent", "tool_input": {"run_in_background": True}}),
        "ALLOW",
    ),
    (
        "Agent: run_in_background=false - DENY (regression: was silently ALLOW)",
        json.dumps({"tool_name": "Agent", "tool_input": {"run_in_background": False}}),
        "DENY",
    ),
    (
        "Agent: run_in_background absent - DENY (regression: was silently ALLOW)",
        json.dumps({"tool_name": "Agent", "tool_input": {}}),
        "DENY",
    ),
    (
        "Agent: run_in_background=null - DENY (regression: was silently ALLOW)",
        json.dumps({"tool_name": "Agent", "tool_input": {"run_in_background": None}}),
        "DENY",
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
