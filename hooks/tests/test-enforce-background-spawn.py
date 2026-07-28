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
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fire_log_test_helper import run_hook_with_raising_log_fire

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-background-spawn.py"
)

# None of this file's payloads set a "cwd" field, so the hook's fire-logging
# helper (hooks/lib/enforcement_log.py) falls back to os.getcwd() - which,
# without an explicit subprocess cwd=, would be wherever this test file is
# invoked from (typically the live checkout). Pin the child process's cwd to
# an ephemeral temp dir so DENY-path fire-log writes never touch the repo.
_TEST_CWD = tempfile.mkdtemp(prefix="test-enforce-background-spawn-")


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
    # Live payload capture 2026-07-07 confirmed the harness DOES pass
    # run_in_background through for Agent spawns (see
    # hooks/enforce-background-spawn.py docstring and MEMORY.md - this
    # corrected an earlier assumption that the field was stripped). The hook
    # enforces an asymmetric rule for Agent: only an explicit
    # run_in_background=False is denied; an absent field allows (Agent is
    # already background-by-default at the harness level, so omitting it is
    # the correct norm) and True also allows. Sentinel suppression still
    # applies to Agent (tested in bin/tests/test_enforce_background_spawn.py).
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
        "Agent: run_in_background=false - DENY (only exact boolean False is denied for Agent)",
        json.dumps({"tool_name": "Agent", "tool_input": {"run_in_background": False}}),
        "DENY",
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

# fire-log integration: a DENY action must append a well-formed line to
# <cwd>/.agentic/.enforcement-fires.jsonl (hooks/lib/enforcement_log.py); a
# passthrough ALLOW (Agent, run_in_background omitted) must write nothing.
label_fl = "fire-log integration - deny writes a line, passthrough writes nothing"
_fire_cwd = tempfile.mkdtemp(prefix="test-enforce-background-spawn-firelog-")
_fire_log_path = os.path.join(_fire_cwd, ".agentic", ".enforcement-fires.jsonl")

# (a) DENY case: Agent with run_in_background explicitly False.
run_hook(json.dumps({
    "tool_name": "Agent",
    "cwd": _fire_cwd,
    "tool_input": {"run_in_background": False},
}))
ok_fl_a = os.path.exists(_fire_log_path)
if ok_fl_a:
    with open(_fire_log_path, "r", encoding="utf-8") as f:
        _fire_lines = [json.loads(ln) for ln in f if ln.strip()]
    ok_fl_a = (
        len(_fire_lines) == 1
        and _fire_lines[0].get("hook") == "enforce-background-spawn"
        and _fire_lines[0].get("decision") == "deny"
    )

# (b) Passthrough case: Agent, run_in_background omitted (allowed by
#     default) -> no additional line written.
run_hook(json.dumps({
    "tool_name": "Agent",
    "cwd": _fire_cwd,
    "tool_input": {},
}))
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
# deny is silently lost - because the pre-fix _deny() called log_fire()
# BEFORE print(). See hooks/tests/_fire_log_test_helper.py.
label_rf = "raising log_fire cannot suppress the deny decision"
_rc_rf, _stdout_rf, _stderr_rf = run_hook_with_raising_log_fire(
    "enforce-background-spawn.py",
    json.dumps({
        "tool_name": "Agent",
        "tool_input": {"run_in_background": False},
    }),
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
