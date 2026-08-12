# Run with: python3 hooks/tests/test-enforce-askuserquestion-default.py
"""
Unit tests for hooks/enforce-askuserquestion-default.py.

This hook had no dedicated test file before the fire-logging change (G2,
hooks/AGENTS.md) added a sibling-module dynamic import to it - this file
covers both the pre-existing deny/allow behavior (previously untested) and
the new fire-log integration.

Each case pipes a JSON payload (or malformed string) into the hook via
stdin and asserts ALLOW (exit 0, no deny output) or DENY (exit 0, deny in
stdout).
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
    os.path.dirname(__file__), "..", "enforce-askuserquestion-default.py"
)

# Most payloads below don't set a "cwd" field, so the fire-logging helper
# falls back to os.getcwd(). Pin the child process's cwd to an ephemeral
# temp dir so DENY-path fire-log writes never touch the repo.
_TEST_CWD = tempfile.mkdtemp(prefix="test-enforce-askuserquestion-default-")


def run_hook(payload: str) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        cwd=_TEST_CWD,
    )
    return result.returncode, result.stdout, result.stderr


def is_allow(returncode: int, stdout: str) -> bool:
    if returncode != 0:
        return False
    if not stdout.strip():
        return True
    try:
        obj = json.loads(stdout)
        decision = obj.get("hookSpecificOutput", {}).get("permissionDecision", "")
        return decision != "deny"
    except Exception:
        return True


def is_deny(returncode: int, stdout: str) -> bool:
    if returncode != 0:
        return False
    try:
        obj = json.loads(stdout)
        decision = obj.get("hookSpecificOutput", {}).get("permissionDecision", "")
        return decision == "deny"
    except Exception:
        return False


def co_equal_ballot(recommended: bool = False) -> dict:
    options = [{"label": "Option A"}, {"label": "Option B"}]
    if recommended:
        options[0]["label"] = "Option A (Recommended)"
    return {
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"options": options}]},
    }


cases = [
    ("co-equal ballot, no recommended label -> DENY", json.dumps(co_equal_ballot()), "DENY"),
    ("ballot with a recommended label -> ALLOW", json.dumps(co_equal_ballot(recommended=True)), "ALLOW"),
    (
        "multiSelect true, no recommended label -> ALLOW",
        json.dumps({
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [{
                    "multiSelect": True,
                    "options": [{"label": "A"}, {"label": "B"}],
                }]
            },
        }),
        "ALLOW",
    ),
    (
        "single option, no recommended label -> ALLOW",
        json.dumps({
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"options": [{"label": "Only one"}]}]},
        }),
        "ALLOW",
    ),
    ("non-AskUserQuestion tool (passthrough) -> ALLOW", json.dumps({"tool_name": "Bash"}), "ALLOW"),
    ("malformed json -> ALLOW (fail-open)", "{not json", "ALLOW"),
    (
        "null tool_input -> ALLOW (fail-open)",
        json.dumps({"tool_name": "AskUserQuestion", "tool_input": None}),
        "ALLOW",
    ),
    (
        "questions not a list -> ALLOW (fail-open)",
        json.dumps({"tool_name": "AskUserQuestion", "tool_input": {"questions": "nope"}}),
        "ALLOW",
    ),
]

failed = 0
for label, payload, expected in cases:
    rc, stdout, stderr = run_hook(payload)
    ok = is_deny(rc, stdout) if expected == "DENY" else is_allow(rc, stdout)
    status = "PASS" if ok else "FAIL"
    if not ok:
        failed += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         payload:  {payload}")
        print(f"         rc:       {rc}")
        print(f"         stdout:   {stdout!r}")
        print(f"         stderr:   {stderr!r}")

# fire-log integration: a DENY action must append a well-formed line to
# <cwd>/.agentic/.enforcement-fires.jsonl; a passthrough ALLOW must write
# nothing.
label_fl = "fire-log integration - deny writes a line, passthrough writes nothing"
_fire_cwd = tempfile.mkdtemp(prefix="test-enforce-askuserquestion-default-firelog-")
_fire_log_path = os.path.join(_fire_cwd, ".agentic", ".enforcement-fires.jsonl")

deny_payload = co_equal_ballot()
deny_payload["cwd"] = _fire_cwd
subprocess.run(
    [sys.executable, HOOK_PATH],
    input=json.dumps(deny_payload),
    capture_output=True,
    text=True,
)
ok_fl_a = os.path.exists(_fire_log_path)
if ok_fl_a:
    with open(_fire_log_path, "r", encoding="utf-8") as f:
        _fire_lines = [json.loads(ln) for ln in f if ln.strip()]
    ok_fl_a = (
        len(_fire_lines) == 1
        and _fire_lines[0].get("hook") == "enforce-askuserquestion-default"
        and _fire_lines[0].get("decision") == "deny"
    )

allow_payload = co_equal_ballot(recommended=True)
allow_payload["cwd"] = _fire_cwd
subprocess.run(
    [sys.executable, HOOK_PATH],
    input=json.dumps(allow_payload),
    capture_output=True,
    text=True,
)
with open(_fire_log_path, "r", encoding="utf-8") as f:
    _fire_lines_after = [json.loads(ln) for ln in f if ln.strip()]
ok_fl_b = len(_fire_lines_after) == 1  # unchanged

ok_fl = ok_fl_a and ok_fl_b
status_fl = "PASS" if ok_fl else "FAIL"
if not ok_fl:
    failed += 1
print(f"  [{status_fl}] {label_fl}")

# PR #626 Skeptic Major sweep: pin deny_reason's source-count enumeration
# against the ASSEMBLED string (not source-line grep, which cannot see a
# string literal wrapped across concatenated source lines - see
# test-enforce-no-abdication.py's test_six_source_enumeration for the same
# class of defect in a sibling hook). deny_reason here does not enumerate
# member names (just "the six default sources"), so this only pins the
# count, but that is exactly the field this hook can regress on.
label_six = "deny_reason names six default sources, not five"
_rc_six, _stdout_six, _ = run_hook(json.dumps(co_equal_ballot()))
_deny_reason_six = ""
try:
    _obj_six = json.loads(_stdout_six)
    _deny_reason_six = _obj_six.get("hookSpecificOutput", {}).get(
        "permissionDecisionReason", ""
    ).lower()
except Exception:
    pass
ok_six = "six default sources" in _deny_reason_six and "five" not in _deny_reason_six
status_six = "PASS" if ok_six else "FAIL"
if not ok_six:
    failed += 1
print(f"  [{status_six}] {label_six}")
if not ok_six:
    print(f"         deny_reason: {_deny_reason_six!r}")

# Skeptic Critical regression: a raising log_fire() must NOT suppress the
# deny decision. Confirmed failing pre-fix: against a8ded298 (the commit
# under review), the copied-hook subprocess exits 0 with EMPTY stdout - the
# deny is silently lost - because the pre-fix inline log_fire() call ran
# BEFORE print(). See hooks/tests/_fire_log_test_helper.py.
label_rf = "raising log_fire cannot suppress the deny decision"
_rc_rf, _stdout_rf, _stderr_rf = run_hook_with_raising_log_fire(
    "enforce-askuserquestion-default.py",
    json.dumps(co_equal_ballot()),
)
ok_rf = _rc_rf == 0 and not is_allow(_rc_rf, _stdout_rf)
status_rf = "PASS" if ok_rf else "FAIL"
if not ok_rf:
    failed += 1
print(f"  [{status_rf}] {label_rf}")
if not ok_rf:
    print(f"         stdout: {_stdout_rf!r}")
    print(f"         stderr: {_stderr_rf[-500:]!r}")

total_tests = len(cases) + 3
print()
if failed == 0:
    print(f"All {total_tests} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total_tests} tests FAILED.")
    sys.exit(1)
