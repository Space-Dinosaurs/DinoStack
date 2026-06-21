# Run with: python3 hooks/tests/test-enforce-orchestrator-singularity.py
"""
Unit tests for hooks/enforce-orchestrator-singularity.py.

Each case pipes a JSON payload (or malformed string) into the hook via stdin
and asserts ALLOW (exit 0, no deny output) or DENY (exit 0, deny in stdout).
"""

import json
import os
import subprocess
import sys

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-orchestrator-singularity.py"
)


def run_hook(payload: str, extra_env: dict | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    env.pop("AE_SINGULARITY_GUARD_DISABLE", None)  # clean slate per test
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        env=env,
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
    # (label, payload_str, expected, extra_env)
    (
        "absent agent_id",
        json.dumps({"tool_name": "Task", "tool_input": {}}),
        "ALLOW",
        None,
    ),
    (
        "null agent_id",
        json.dumps({"tool_name": "Task", "agent_id": None}),
        "ALLOW",
        None,
    ),
    (
        "empty-string agent_id",
        json.dumps({"tool_name": "Task", "agent_id": ""}),
        "ALLOW",
        None,
    ),
    (
        "non-empty agent_id",
        json.dumps({
            "tool_name": "Task",
            "agent_id": "abc-123",
            "agent_type": "engineer",
        }),
        "DENY",
        None,
    ),
    (
        "non-Task tool (passthrough)",
        json.dumps({"tool_name": "Read", "agent_id": "abc-123"}),
        "ALLOW",
        None,
    ),
    (
        "malformed json",
        "not-json",
        "ALLOW",
        None,
    ),
    (
        "kill-switch (AE_SINGULARITY_GUARD_DISABLE=1)",
        json.dumps({
            "tool_name": "Task",
            "agent_id": "abc-123",
            "agent_type": "engineer",
        }),
        "ALLOW",
        {"AE_SINGULARITY_GUARD_DISABLE": "1"},
    ),
]

failed = 0
for label, payload, expected, extra_env in cases:
    rc, stdout, stderr = run_hook(payload, extra_env)
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
