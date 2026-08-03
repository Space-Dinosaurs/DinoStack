# Run with: python3 hooks/tests/test-enforce-orchestrator-singularity.py
"""
Unit tests for hooks/enforce-orchestrator-singularity.py.

Each case pipes a JSON payload (or malformed string) into the hook via stdin
and asserts ALLOW (exit 0, no deny output) or DENY (exit 0, deny in stdout).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fire_log_test_helper import run_hook_with_raising_log_fire

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-orchestrator-singularity.py"
)

# None of this file's payloads set a "cwd" field, so the hook's fire-logging
# helper (hooks/lib/enforcement_log.py) falls back to os.getcwd() - which,
# without an explicit subprocess cwd=, would be wherever this test file is
# invoked from (typically the live checkout). Pin the child process's cwd to
# an ephemeral temp dir so DENY-path fire-log writes never touch the repo.
_TEST_CWD = tempfile.mkdtemp(prefix="test-enforce-orchestrator-singularity-")


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
        cwd=_TEST_CWD,
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
    # --- Legacy tool_name="Task" cases ---
    (
        "Task: absent agent_id",
        json.dumps({"tool_name": "Task", "tool_input": {}}),
        "ALLOW",
        None,
    ),
    (
        "Task: null agent_id",
        json.dumps({"tool_name": "Task", "agent_id": None}),
        "ALLOW",
        None,
    ),
    (
        "Task: empty-string agent_id",
        json.dumps({"tool_name": "Task", "agent_id": ""}),
        "ALLOW",
        None,
    ),
    (
        "Task: non-empty agent_id",
        json.dumps({
            "tool_name": "Task",
            "agent_id": "abc-123",
            "agent_type": "engineer",
        }),
        "DENY",
        None,
    ),
    (
        "Task: kill-switch (AE_SINGULARITY_GUARD_DISABLE=1)",
        json.dumps({
            "tool_name": "Task",
            "agent_id": "abc-123",
            "agent_type": "engineer",
        }),
        "ALLOW",
        {"AE_SINGULARITY_GUARD_DISABLE": "1"},
    ),
    # --- Regression tests: tool_name="Agent" (CC rename, was failing silently) ---
    # These cases MUST deny under the fixed hook. Against the buggy guard
    # (tool_name != "Task" -> sys.exit(0)), they would all incorrectly ALLOW.
    (
        "Agent: non-empty agent_id - DENY (regression: was silently ALLOW)",
        json.dumps({
            "tool_name": "Agent",
            "agent_id": "abc-123",
            "agent_type": "engineer",
        }),
        "DENY",
        None,
    ),
    (
        "Agent: absent agent_id - ALLOW (conductor has no agent_id)",
        json.dumps({"tool_name": "Agent", "tool_input": {}}),
        "ALLOW",
        None,
    ),
    (
        "Agent: null agent_id - ALLOW",
        json.dumps({"tool_name": "Agent", "agent_id": None}),
        "ALLOW",
        None,
    ),
    (
        "Agent: empty-string agent_id - ALLOW",
        json.dumps({"tool_name": "Agent", "agent_id": ""}),
        "ALLOW",
        None,
    ),
    (
        "Agent: kill-switch disables guard",
        json.dumps({
            "tool_name": "Agent",
            "agent_id": "abc-123",
            "agent_type": "engineer",
        }),
        "ALLOW",
        {"AE_SINGULARITY_GUARD_DISABLE": "1"},
    ),
    # --- Other tool passthrough ---
    (
        "non-Task/Agent tool (passthrough)",
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

# fire-log integration: a DENY action must append a well-formed line to
# <cwd>/.agentic/.enforcement-fires.jsonl; a passthrough ALLOW must write
# nothing.
label_fl = "fire-log integration - deny writes a line, passthrough writes nothing"
_fire_cwd = tempfile.mkdtemp(prefix="test-enforce-orchestrator-singularity-firelog-")
_fire_log_path = os.path.join(_fire_cwd, ".agentic", ".enforcement-fires.jsonl")

run_hook(json.dumps({"tool_name": "Agent", "cwd": _fire_cwd, "agent_id": "wt-1"}))
ok_fl_a = os.path.exists(_fire_log_path)
if ok_fl_a:
    with open(_fire_log_path, "r", encoding="utf-8") as f:
        _fire_lines = [json.loads(ln) for ln in f if ln.strip()]
    ok_fl_a = (
        len(_fire_lines) == 1
        and _fire_lines[0].get("hook") == "enforce-orchestrator-singularity"
        and _fire_lines[0].get("decision") == "deny"
    )

run_hook(json.dumps({"tool_name": "Agent", "cwd": _fire_cwd}))  # no agent_id -> ALLOW
with open(_fire_log_path, "r", encoding="utf-8") as f:
    _fire_lines_after = [json.loads(ln) for ln in f if ln.strip()]
ok_fl_b = len(_fire_lines_after) == 1  # unchanged

ok_fl = ok_fl_a and ok_fl_b
status_fl = "PASS" if ok_fl else "FAIL"
if not ok_fl:
    failed += 1
print(f"  [{status_fl}] {label_fl}")

# Skeptic Critical regression: a raising log_fire() must NOT suppress the
# deny decision. Confirmed failing pre-fix: against a8ded298 (the commit
# under review), the copied-hook subprocess exits 0 with EMPTY stdout - the
# deny is silently lost - because the pre-fix inline log_fire() call ran
# BEFORE print(). See hooks/tests/_fire_log_test_helper.py.
label_rf = "raising log_fire cannot suppress the deny decision"
_rc_rf, _stdout_rf, _stderr_rf = run_hook_with_raising_log_fire(
    "enforce-orchestrator-singularity.py",
    json.dumps({"tool_name": "Agent", "agent_id": "wt-1"}),
)
ok_rf = _rc_rf == 0 and not is_allow(_rc_rf, _stdout_rf)
status_rf = "PASS" if ok_rf else "FAIL"
if not ok_rf:
    failed += 1
print(f"  [{status_rf}] {label_rf}")
if not ok_rf:
    print(f"         stdout: {_stdout_rf!r}")
    print(f"         stderr: {_stderr_rf[-500:]!r}")

total_tests = len(cases) + 2

print()
if failed == 0:
    print(f"All {total_tests} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total_tests} tests FAILED.")
    sys.exit(1)
