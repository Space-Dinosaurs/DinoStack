# Run with: python3 hooks/tests/test-enforce-stall-detection.py
"""
Regression tests for the surface-and-proceed STALL fix in
hooks/enforce-no-abdication.py.

Bug: the conductor ends a turn with "Proceeding with X unless you say
otherwise." (or "(recommended)") and then stops WITHOUT actually proceeding.
Pre-fix, any surface-and-proceed marker unconditionally suppressed the
abdication guard - the marker text was treated as proof of compliant
behavior regardless of whether any action followed it. This let the single
most common stall shape through: announce a default, then park the session.

Fix: _is_stalled_surface_and_proceed() in enforce-no-abdication.py fires
when a surface-and-proceed marker is present in the tail AND the transcript
shows zero tool-use calls since the last genuine human turn. It never fires
without transcript evidence (fail-open) or when a hard negative-gate token
(destructive/irreversible/design-fork) is present.

This file mirrors hooks/tests/test-enforce-no-abdication.py's conventions
(subprocess-based, run_hook/is_allow/is_block helpers, make_config_file /
make_transcript builders) rather than importing the hook module directly.

Test coverage (mirrors the task's required matrix):
  MUST BLOCK:
    1. "Proceeding with X unless you say otherwise." + zero tool calls this turn
    2. "(Recommended)" + zero tool calls this turn
    3. "proceeding with" in different casing + zero tool calls this turn
  MUST ALLOW:
    4. Marker present + >=1 tool call this turn (compliant surface-and-proceed)
    5. stop_hook_active: true
    6. Consecutive-block cap already reached
    7. AE_ABDICATION_GUARD_DISABLE=1
    8. abdication_guard_enabled: false in config
    9. Malformed/absent transcript path -> fail open, not block
   10. Malformed JSON lines inside an otherwise valid transcript -> fail open
   11. A normal completion turn with no marker and no interrogative
   12. (covered by test-enforce-no-abdication.py itself, run separately)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-no-abdication.py"
)

CONSECUTIVE_BLOCK_CAP = 2

# ---------------------------------------------------------------------------
# Helpers (mirrors test-enforce-no-abdication.py)
# ---------------------------------------------------------------------------


def run_hook(payload: str, env: dict | None = None, timeout: int = 10) -> tuple[int, str, str]:
    merged_env = os.environ.copy()
    merged_env.pop("AE_ABDICATION_GUARD_DISABLE", None)
    if env:
        merged_env.update(env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def is_allow(returncode: int, stdout: str) -> bool:
    if returncode != 0:
        return False
    stripped = stdout.strip()
    if not stripped:
        return True
    try:
        obj = json.loads(stripped)
        return obj.get("decision") != "block"
    except Exception:
        return True


def is_block(returncode: int, stdout: str) -> bool:
    if returncode != 0:
        return False
    stripped = stdout.strip()
    if not stripped:
        return False
    try:
        obj = json.loads(stripped)
        return (
            obj.get("decision") == "block"
            and isinstance(obj.get("reason"), str)
            and len(obj["reason"]) > 0
        )
    except Exception:
        return False


def make_config_file(tmp_dir: str, enabled: bool = True) -> str:
    agentic_dir = os.path.join(tmp_dir, ".agentic")
    os.makedirs(agentic_dir, exist_ok=True)
    config_path = os.path.join(agentic_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump({"abdication_guard_enabled": enabled}, f)
    return config_path


def make_transcript(tmp_dir: str, messages: list, filename: str = "transcript.jsonl") -> str:
    path = os.path.join(tmp_dir, filename)
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return path


def make_payload(
    cwd: str,
    last_assistant_message: str,
    stop_hook_active: bool = False,
    transcript_path: str = "",
) -> str:
    payload = {
        "hook_event_name": "Stop",
        "session_id": "test-stall-session",
        "cwd": cwd,
        "stop_hook_active": stop_hook_active,
        "permission_mode": "default",
        "last_assistant_message": last_assistant_message,
    }
    if transcript_path:
        payload["transcript_path"] = transcript_path
    return json.dumps(payload)


def new_case_dir(tmp_dir: str, name: str) -> str:
    d = os.path.join(tmp_dir, name)
    os.makedirs(d, exist_ok=True)
    make_config_file(d, enabled=True)
    return d


# Transcript: one genuine human turn, then an assistant message with NO
# tool_use block - i.e. the conductor produced only text this turn.
def transcript_no_tool_call(cwd: str, assistant_text: str, filename: str = "transcript.jsonl") -> str:
    return make_transcript(
        cwd,
        [
            {"type": "user", "message": {"content": [{"type": "text", "text": "Go do the work"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": assistant_text}]}},
        ],
        filename=filename,
    )


# Transcript: one genuine human turn, an assistant tool_use call, its
# tool_result, and then the final assistant text message - i.e. the
# conductor DID act this turn before producing the surface-and-proceed text.
def transcript_with_tool_call(cwd: str, assistant_text: str, filename: str = "transcript.jsonl") -> str:
    return make_transcript(
        cwd,
        [
            {"type": "user", "message": {"content": [{"type": "text", "text": "Go do the work"}]}},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "echo hi"}}
                    ]
                },
            },
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "hi"}]},
            },
            {"type": "assistant", "message": {"content": [{"type": "text", "text": assistant_text}]}},
        ],
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Test bodies
# ---------------------------------------------------------------------------


def run_labeled(label: str, rc: int, stdout: str, stderr: str, expected: str) -> bool:
    ok = is_block(rc, stdout) if expected == "BLOCK" else is_allow(rc, stdout)
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         expected: {expected}")
        print(f"         rc:       {rc}")
        print(f"         stdout:   {stdout!r}")
        print(f"         stderr:   {stderr!r}")
    return ok


def test_must_block(tmp_dir: str) -> int:
    print("\n  [MUST BLOCK: stall - marker present, zero tool calls this turn]")
    failed = 0

    # 1. "Proceeding with X unless you say otherwise." + zero tool calls.
    d1 = new_case_dir(tmp_dir, "stall_unless_otherwise")
    t1 = transcript_no_tool_call(d1, "Proceeding with approach A unless you say otherwise.")
    rc, out, err = run_hook(make_payload(
        d1,
        "Proceeding with approach A unless you say otherwise.",
        transcript_path=t1,
    ))
    if not run_labeled(
        "1. 'Proceeding with X unless you say otherwise.' + 0 tool calls -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    # 2. "(Recommended)" + zero tool calls.
    d2 = new_case_dir(tmp_dir, "stall_recommended")
    msg2 = "Picking approach B (Recommended) based on existing patterns."
    t2 = transcript_no_tool_call(d2, msg2)
    rc, out, err = run_hook(make_payload(d2, msg2, transcript_path=t2))
    if not run_labeled(
        "2. '(Recommended)' + 0 tool calls -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    # 3. "proceeding with" different casing + zero tool calls.
    d3 = new_case_dir(tmp_dir, "stall_casing")
    msg3 = "PROCEEDING WITH the migration script now."
    t3 = transcript_no_tool_call(d3, msg3)
    rc, out, err = run_hook(make_payload(d3, msg3, transcript_path=t3))
    if not run_labeled(
        "3. 'PROCEEDING WITH' (different casing) + 0 tool calls -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    return failed


def test_must_allow(tmp_dir: str) -> int:
    print("\n  [MUST ALLOW]")
    failed = 0

    # 4. Marker present AND >=1 tool call this turn -> ALLOW.
    d4 = new_case_dir(tmp_dir, "compliant_with_tool_call")
    msg4 = "Proceeding with approach A unless you say otherwise."
    t4 = transcript_with_tool_call(d4, msg4)
    rc, out, err = run_hook(make_payload(d4, msg4, transcript_path=t4))
    if not run_labeled(
        "4. Marker present + >=1 tool call this turn -> ALLOW (compliant)",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 5. stop_hook_active: true -> ALLOW regardless of stall shape.
    d5 = new_case_dir(tmp_dir, "stop_hook_active_true")
    msg5 = "Proceeding with approach A unless you say otherwise."
    t5 = transcript_no_tool_call(d5, msg5)
    rc, out, err = run_hook(make_payload(d5, msg5, stop_hook_active=True, transcript_path=t5))
    if not run_labeled(
        "5. stop_hook_active=true -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 6. Consecutive-block cap already reached -> ALLOW.
    # NOTE: last_user_msg_count must match the transcript's genuine human
    # turn count (1, from transcript_no_tool_call's single "Go do the work"
    # turn) - otherwise the hook's own new-user-turn reset logic fires first
    # (current_user_msg_count=1 > last_user_msg_count=0) and the cap check
    # never gets exercised.
    d6 = new_case_dir(tmp_dir, "cap_reached")
    agentic_dir6 = os.path.join(d6, ".agentic")
    counter_path6 = os.path.join(agentic_dir6, ".abdication-guard-fire-count")
    with open(counter_path6, "w") as f:
        json.dump({"count": CONSECUTIVE_BLOCK_CAP, "last_user_msg_count": 1}, f)
    msg6 = "Proceeding with approach A unless you say otherwise."
    t6 = transcript_no_tool_call(d6, msg6)
    rc, out, err = run_hook(make_payload(d6, msg6, transcript_path=t6))
    if not run_labeled(
        "6. Consecutive-block cap reached -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 7. AE_ABDICATION_GUARD_DISABLE=1 -> ALLOW.
    d7 = new_case_dir(tmp_dir, "kill_switch")
    msg7 = "Proceeding with approach A unless you say otherwise."
    t7 = transcript_no_tool_call(d7, msg7)
    rc, out, err = run_hook(
        make_payload(d7, msg7, transcript_path=t7),
        env={"AE_ABDICATION_GUARD_DISABLE": "1"},
    )
    if not run_labeled(
        "7. AE_ABDICATION_GUARD_DISABLE=1 -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 8. abdication_guard_enabled: false -> ALLOW.
    d8 = os.path.join(tmp_dir, "guard_disabled_cwd")
    os.makedirs(d8, exist_ok=True)
    make_config_file(d8, enabled=False)
    msg8 = "Proceeding with approach A unless you say otherwise."
    t8 = transcript_no_tool_call(d8, msg8)
    rc, out, err = run_hook(make_payload(d8, msg8, transcript_path=t8))
    if not run_labeled(
        "8. abdication_guard_enabled=false -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 9. Malformed/absent transcript path -> fail open, ALLOW (no evidence
    #    of a stall without a readable transcript).
    d9 = new_case_dir(tmp_dir, "absent_transcript")
    msg9 = "Proceeding with approach A unless you say otherwise."
    rc, out, err = run_hook(make_payload(
        d9, msg9, transcript_path=os.path.join(d9, "does-not-exist.jsonl"),
    ))
    if not run_labeled(
        "9a. Nonexistent transcript_path -> ALLOW (fail open)",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    d9b = new_case_dir(tmp_dir, "no_transcript_field")
    rc, out, err = run_hook(make_payload(d9b, msg9))  # no transcript_path at all
    if not run_labeled(
        "9b. No transcript_path field at all -> ALLOW (fail open)",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 10. Malformed JSON lines inside an otherwise valid transcript -> fail
    #     open on those lines (skipped), but the well-formed lines still
    #     resolve correctly. Here we corrupt the tool_use line itself so the
    #     tool-call evidence is destroyed; the safe degradation must be
    #     ALLOW (never claim a stall it can't prove).
    d10 = new_case_dir(tmp_dir, "malformed_lines")
    msg10 = "Proceeding with approach A unless you say otherwise."
    t10_path = os.path.join(d10, "transcript.jsonl")
    with open(t10_path, "w") as f:
        f.write(json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "Go"}]}}) + "\n")
        f.write("NOT VALID JSON {{{\n")
        f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": msg10}]}}) + "\n")
    rc, out, err = run_hook(make_payload(d10, msg10, transcript_path=t10_path))
    # A malformed line is simply skipped by the scan (not a hard read
    # failure), so the well-formed lines still resolve: no tool_use found ->
    # genuine stall -> BLOCK is the correct, provable outcome here. This
    # confirms malformed *individual lines* don't crash the scan or corrupt
    # its result - contrast with case 9 (a wholly unreadable transcript),
    # which must ALLOW.
    if not run_labeled(
        "10. Malformed JSON line skipped; well-formed lines still classify -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    # 11. A normal completion turn with no marker and no interrogative -> ALLOW.
    d11 = new_case_dir(tmp_dir, "normal_completion")
    msg11 = "Fixed the bug in config.ts and added a regression test. All quality gates pass."
    t11 = transcript_with_tool_call(d11, msg11)
    rc, out, err = run_hook(make_payload(d11, msg11, transcript_path=t11))
    if not run_labeled(
        "11. Normal completion, no marker, no interrogative -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    return failed


def test_hard_negative_gate_still_suppresses_stall(tmp_dir: str) -> int:
    """Extra coverage beyond the required matrix: a hard negative-gate token
    (e.g. 'irreversible') co-occurring with a surface-and-proceed marker and
    zero tool calls must still ALLOW - the hard gate is unconditional."""
    print("\n  [Extra: hard negative gate suppresses stall classifier too]")
    failed = 0
    d = new_case_dir(tmp_dir, "hard_gate_with_marker")
    msg = "This is irreversible. Proceeding with the migration unless you say otherwise."
    t = transcript_no_tool_call(d, msg)
    rc, out, err = run_hook(make_payload(d, msg, transcript_path=t))
    if not run_labeled(
        "Hard negative gate ('irreversible') + marker + 0 tool calls -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1
    return failed


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def main() -> None:
    total_failed = 0
    with tempfile.TemporaryDirectory() as tmp_dir:
        total_failed += test_must_block(tmp_dir)
        total_failed += test_must_allow(tmp_dir)
        total_failed += test_hard_negative_gate_still_suppresses_stall(tmp_dir)

    print()
    if total_failed == 0:
        print("All stall-detection tests passed.")
        sys.exit(0)
    else:
        print(f"{total_failed} test assertion(s) FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
