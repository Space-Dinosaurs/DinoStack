# Run with: python3 hooks/tests/test-enforce-stall-detection.py
"""
Regression tests for the surface-and-proceed STALL fix in
hooks/enforce-no-abdication.py.

Bug: the conductor ends a turn with "Proceeding with X unless you say
otherwise." and then stops WITHOUT actually proceeding. Pre-fix, any
surface-and-proceed marker unconditionally suppressed the abdication guard -
the marker text was treated as proof of compliant behavior regardless of
whether any action followed it. This let the single most common stall shape
through: announce a default, then park the session.

Fix: _is_stalled_surface_and_proceed() in enforce-no-abdication.py fires
when a stall-COMMITMENT marker ("proceeding with" / "unless you say
otherwise" - deliberately NOT a bare "(recommended)", which routinely labels
an already-derived choice with no pending action attached) is present in the
tail AND the transcript furnishes POSITIVE proof of zero tool-use calls
since the last genuine human turn (a successfully-read window, a located
human-turn boundary, and recognized assistant-entry shapes throughout). It
never fires on absence of evidence - unreadable/unparseable transcripts, a
window with no located boundary, or an unrecognized content shape all leave
the stall unproven - or when a hard negative-gate token
(destructive/irreversible/design-fork/spend-money/external-message) is
present.

Fix pass 2 (this file) closes three review findings on top of the above:
  - Finding 1: harness-injected `type:"user"` lines (background task-
    completion notifications, in particular) must not be mistaken for a
    genuine human-turn boundary. See test_dominant_compliant_shape().
  - Finding 2: the burden of proof for "zero tool calls this turn" is
    inverted - a stall is only asserted on POSITIVE evidence (successfully
    parsed window + located human-turn boundary + recognized assistant
    content shapes), never inferred from a read/parse failure or an
    unrecognized shape. See test_fail_closed_paths_must_allow().
  - Finding 3: a bare "(recommended)" is no longer a sufficient trigger for
    this classifier - only "proceeding with" / "unless you say otherwise"
    commit to a pending action. See test_bare_recommended_must_allow() and
    test_answer_from_context_must_allow().
  - Finding 6: the human-turn boundary mechanism itself (not just the
    presence of a marker/scan) is now exercised with multi-turn fixtures,
    an interleaved task-notification, and a compacted (no-user-turn) window.
    See test_multi_turn_boundary_cases().

Fix pass 3 (this file, further narrowing): the spend-money and external-
message hard-stop categories were bare-word matches ("spend", "cost", "send",
"post", "notify", ...) - a hard-gate hit SUPPRESSES the stall classifier
entirely, so the breadth was a utility bug, not merely a benign
false-negative: ordinary conductor vocabulary ("cost a few minutes",
"sending the brief to the engineer") silently disabled the guard on genuine
stalls. These two categories are now co-occurrence checks (action token +
monetary/authorization signal, or action token + external-facing target) -
see _hard_negative_gate_hit() in enforce-no-abdication.py and
test_hard_stop_cooccurrence_narrowing() below.

This file mirrors hooks/tests/test-enforce-no-abdication.py's conventions
(subprocess-based, run_hook/is_allow/is_block helpers, make_config_file /
make_transcript builders) rather than importing the hook module directly.

Test coverage:
  MUST BLOCK (genuine stalls - positive proof of a marker + zero tool calls
  this turn, scoped by a correctly-located human-turn boundary):
    1. "Proceeding with X unless you say otherwise." + zero tool calls
    2. "PROCEEDING WITH" different casing + zero tool calls
    3. Multi-turn: an EARLIER turn had a tool call, the CURRENT turn (marker,
       zero tool calls) must not inherit that earlier turn's evidence
    4. Malformed JSON line skipped; well-formed lines around it still prove
       a genuine stall
  MUST ALLOW:
    5. Marker present + >=1 tool call this turn (compliant)
    6. stop_hook_active: true
    7. Consecutive-block cap already reached
    8. AE_ABDICATION_GUARD_DISABLE=1
    9. abdication_guard_enabled: false in config
   10. Nonexistent transcript_path -> fail open (unproven)
   11. No transcript_path field at all -> fail open (unproven)
   12. A normal completion turn with no marker and no interrogative
   13. Hard negative gate ('irreversible') + marker + 0 tool calls
   14. Bare "(Recommended)" alone + zero tool calls (Finding 3 - no longer a
       sufficient trigger)
   15. Answer-from-context with no tool call and no pending action (Finding
       3's literal example)
   16. Zero-byte transcript + marker (Finding 2, fail-closed path 1)
   17. Garbage non-JSON lines only + marker (Finding 2, fail-closed path 2)
   18. Valid JSON, unexpected schema (no recognizable role) + marker
       (Finding 2, fail-closed path 3)
   19. Transcript with NO user turn at all / compacted window + marker
       (Finding 2, fail-closed path 4)
   20. tool_use in a non-list assistant content shape + marker (Finding 2,
       fail-closed path 5)
   21. Spend-money hard-stop + marker + zero tool calls (Finding 4)
   22. Dominant compliant shape: spawn tool_use -> harness task-notification
       -> "Unit N returned; proceeding with unit N+1 unless you say
       otherwise." (Finding 1 - the notification must not hide the earlier
       tool_use from the same turn)
   23-27. Fix pass 3 co-occurrence narrowing, MUST ALLOW (genuine hard-stops):
       spend + dollar amount + credit + "your OK"; post + PR comment;
       email + customer; force push (control, unaffected category);
       production delete/migration (control, unaffected category).
   28-31. Fix pass 3 co-occurrence narrowing, MUST BLOCK (ordinary vocabulary,
       previously wrongly suppressed): "sending" with no external target;
       "cost" with no monetary/authorization signal; a plain stall with no
       hard-stop vocabulary at all (control); "notifying" with no external
       target.
   32. (test-enforce-no-abdication.py itself, run separately, covers the
       classic-interrogative-path invariants)
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


# Transcript: TWO genuine human turns. The FIRST turn has an assistant
# tool_use call; the CURRENT (second) turn has an assistant message with NO
# tool_use - i.e. any tool-call evidence in the transcript belongs to a PRIOR
# turn and must not count as evidence for the current one.
def transcript_prior_turn_tool_call_current_turn_none(
    cwd: str, assistant_text: str, filename: str = "transcript.jsonl"
) -> str:
    return make_transcript(
        cwd,
        [
            {"type": "user", "message": {"content": [{"type": "text", "text": "First request"}]}},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "t0", "name": "Bash", "input": {"command": "echo old"}}
                    ]
                },
            },
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "t0", "content": "old"}]},
            },
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Did the first thing."}]}},
            {"type": "user", "message": {"content": [{"type": "text", "text": "Second request"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": assistant_text}]}},
        ],
        filename=filename,
    )


# Transcript: the dominant compliant conductor shape (Finding 1). A genuine
# human turn, then a spawn tool_use, its tool_result, a harness-injected
# background task-notification (type:"user", isMeta ABSENT, plain-string
# content - the real shape observed in ~/.claude/projects/ transcripts), and
# finally the assistant's proceeding-with digest. The task-notification must
# NOT be treated as a new human-turn boundary - the earlier tool_use is still
# "this turn"'s evidence.
def transcript_dominant_compliant_shape(cwd: str, assistant_text: str, filename: str = "transcript.jsonl") -> str:
    return make_transcript(
        cwd,
        [
            {"type": "user", "message": {"content": [{"type": "text", "text": "Go implement units 1-3"}]}},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "Agent", "input": {"description": "Unit 2"}}
                    ]
                },
            },
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "queued"}]},
            },
            {
                "type": "user",
                "message": {
                    "content": (
                        "<task-notification>\n<task-id>abc123</task-id>\n"
                        "<tool-use-id>toolu_01abc</tool-use-id>\n<status>completed</status>\n"
                        "<summary>Agent \"Unit 2\" completed</summary>\n<result>Status: DONE</result>\n"
                        "</task-notification>"
                    )
                },
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

    # 2. "proceeding with" different casing + zero tool calls.
    d2 = new_case_dir(tmp_dir, "stall_casing")
    msg2 = "PROCEEDING WITH the migration script now."
    t2 = transcript_no_tool_call(d2, msg2)
    rc, out, err = run_hook(make_payload(d2, msg2, transcript_path=t2))
    if not run_labeled(
        "2. 'PROCEEDING WITH' (different casing) + 0 tool calls -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    # 3. Finding 6: an EARLIER human turn had a tool call; the CURRENT turn
    #    (marker present, zero tool calls) must be judged on its own window,
    #    not inherit the earlier turn's evidence.
    d3 = new_case_dir(tmp_dir, "multi_turn_prior_tool_call")
    msg3 = "Proceeding with the second request unless you say otherwise."
    t3 = transcript_prior_turn_tool_call_current_turn_none(d3, msg3)
    rc, out, err = run_hook(make_payload(d3, msg3, transcript_path=t3))
    if not run_labeled(
        "3. Prior-turn tool call does NOT excuse a tool-call-free current turn -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    # 4. Malformed JSON lines inside an otherwise valid transcript. A
    #    malformed line is simply skipped by the scan (not a hard read
    #    failure); the surrounding well-formed lines still locate the
    #    boundary and show zero tool_use -> a provable stall -> BLOCK.
    #    Contrast with the fail-closed cases in test_fail_closed_paths_must_
    #    allow() below, where the WHOLE window is unrecognizable.
    d4 = new_case_dir(tmp_dir, "malformed_lines")
    msg4 = "Proceeding with approach A unless you say otherwise."
    t4_path = os.path.join(d4, "transcript.jsonl")
    with open(t4_path, "w") as f:
        f.write(json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "Go"}]}}) + "\n")
        f.write("NOT VALID JSON {{{\n")
        f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": msg4}]}}) + "\n")
    rc, out, err = run_hook(make_payload(d4, msg4, transcript_path=t4_path))
    if not run_labeled(
        "4. Malformed JSON line skipped; well-formed lines still classify -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    return failed


def test_must_allow(tmp_dir: str) -> int:
    print("\n  [MUST ALLOW]")
    failed = 0

    # 5. Marker present AND >=1 tool call this turn -> ALLOW.
    d5 = new_case_dir(tmp_dir, "compliant_with_tool_call")
    msg5 = "Proceeding with approach A unless you say otherwise."
    t5 = transcript_with_tool_call(d5, msg5)
    rc, out, err = run_hook(make_payload(d5, msg5, transcript_path=t5))
    if not run_labeled(
        "5. Marker present + >=1 tool call this turn -> ALLOW (compliant)",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 6. stop_hook_active: true -> ALLOW regardless of stall shape.
    d6 = new_case_dir(tmp_dir, "stop_hook_active_true")
    msg6 = "Proceeding with approach A unless you say otherwise."
    t6 = transcript_no_tool_call(d6, msg6)
    rc, out, err = run_hook(make_payload(d6, msg6, stop_hook_active=True, transcript_path=t6))
    if not run_labeled(
        "6. stop_hook_active=true -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 7. Consecutive-block cap already reached -> ALLOW.
    # NOTE: last_user_msg_count must match the transcript's genuine human
    # turn count (1, from transcript_no_tool_call's single "Go do the work"
    # turn) - otherwise the hook's own new-user-turn reset logic fires first
    # (current_user_msg_count=1 > last_user_msg_count=0) and the cap check
    # never gets exercised.
    d7 = new_case_dir(tmp_dir, "cap_reached")
    agentic_dir7 = os.path.join(d7, ".agentic")
    counter_path7 = os.path.join(agentic_dir7, ".abdication-guard-fire-count")
    with open(counter_path7, "w") as f:
        json.dump({"count": CONSECUTIVE_BLOCK_CAP, "last_user_msg_count": 1}, f)
    msg7 = "Proceeding with approach A unless you say otherwise."
    t7 = transcript_no_tool_call(d7, msg7)
    rc, out, err = run_hook(make_payload(d7, msg7, transcript_path=t7))
    if not run_labeled(
        "7. Consecutive-block cap reached -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 8. AE_ABDICATION_GUARD_DISABLE=1 -> ALLOW.
    d8 = new_case_dir(tmp_dir, "kill_switch")
    msg8 = "Proceeding with approach A unless you say otherwise."
    t8 = transcript_no_tool_call(d8, msg8)
    rc, out, err = run_hook(
        make_payload(d8, msg8, transcript_path=t8),
        env={"AE_ABDICATION_GUARD_DISABLE": "1"},
    )
    if not run_labeled(
        "8. AE_ABDICATION_GUARD_DISABLE=1 -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 9. abdication_guard_enabled: false -> ALLOW.
    d9 = os.path.join(tmp_dir, "guard_disabled_cwd")
    os.makedirs(d9, exist_ok=True)
    make_config_file(d9, enabled=False)
    msg9 = "Proceeding with approach A unless you say otherwise."
    t9 = transcript_no_tool_call(d9, msg9)
    rc, out, err = run_hook(make_payload(d9, msg9, transcript_path=t9))
    if not run_labeled(
        "9. abdication_guard_enabled=false -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 10. Nonexistent transcript_path -> fail open (no evidence of a stall
    #     without a readable transcript).
    d10 = new_case_dir(tmp_dir, "absent_transcript")
    msg10 = "Proceeding with approach A unless you say otherwise."
    rc, out, err = run_hook(make_payload(
        d10, msg10, transcript_path=os.path.join(d10, "does-not-exist.jsonl"),
    ))
    if not run_labeled(
        "10. Nonexistent transcript_path -> ALLOW (fail open)",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 11. No transcript_path field at all -> fail open.
    d11 = new_case_dir(tmp_dir, "no_transcript_field")
    rc, out, err = run_hook(make_payload(d11, msg10))  # no transcript_path at all
    if not run_labeled(
        "11. No transcript_path field at all -> ALLOW (fail open)",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 12. A normal completion turn with no marker and no interrogative -> ALLOW.
    d12 = new_case_dir(tmp_dir, "normal_completion")
    msg12 = "Fixed the bug in config.ts and added a regression test. All quality gates pass."
    t12 = transcript_with_tool_call(d12, msg12)
    rc, out, err = run_hook(make_payload(d12, msg12, transcript_path=t12))
    if not run_labeled(
        "12. Normal completion, no marker, no interrogative -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 13. Hard negative gate ('irreversible') + marker + 0 tool calls -> ALLOW.
    d13 = new_case_dir(tmp_dir, "hard_gate_with_marker")
    msg13 = "This is irreversible. Proceeding with the migration unless you say otherwise."
    t13 = transcript_no_tool_call(d13, msg13)
    rc, out, err = run_hook(make_payload(d13, msg13, transcript_path=t13))
    if not run_labeled(
        "13. Hard negative gate ('irreversible') + marker + 0 tool calls -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 14. Finding 3: a bare "(Recommended)" with no commitment phrase is no
    #     longer a sufficient trigger, even with zero tool calls this turn.
    d14 = new_case_dir(tmp_dir, "bare_recommended")
    msg14 = "Picking approach B (Recommended) based on existing patterns."
    t14 = transcript_no_tool_call(d14, msg14)
    rc, out, err = run_hook(make_payload(d14, msg14, transcript_path=t14))
    if not run_labeled(
        "14. Bare '(Recommended)' + 0 tool calls -> ALLOW (not a commitment marker)",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 15. Finding 3's literal example: answering from context with no tool
    #     call and no pending action stated must ALLOW (Low direct-action row).
    d15 = new_case_dir(tmp_dir, "answer_from_context")
    msg15 = "You asked which library. Option B (recommended) because it matches src/foo.ts."
    t15 = transcript_no_tool_call(d15, msg15)
    rc, out, err = run_hook(make_payload(d15, msg15, transcript_path=t15))
    if not run_labeled(
        "15. Answer-from-context, no tool call, no pending action -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    return failed


def test_fail_closed_paths_must_allow(tmp_dir: str) -> int:
    """Finding 2: five fail-closed transcript shapes, all with a stall
    marker present and (superficially) zero recognized tool calls. Each must
    ALLOW because the scan cannot furnish POSITIVE proof of a stall."""
    print("\n  [MUST ALLOW: Finding 2 fail-closed paths - absence of evidence != evidence of a stall]")
    failed = 0
    marker_msg = "Proceeding with approach A unless you say otherwise."

    # 16. Zero-byte transcript.
    d16 = new_case_dir(tmp_dir, "fail_closed_zero_byte")
    t16 = os.path.join(d16, "transcript.jsonl")
    with open(t16, "w"):
        pass
    rc, out, err = run_hook(make_payload(d16, marker_msg, transcript_path=t16))
    if not run_labeled(
        "16. Zero-byte transcript + marker -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 17. Garbage non-JSON lines only.
    d17 = new_case_dir(tmp_dir, "fail_closed_garbage")
    t17 = os.path.join(d17, "transcript.jsonl")
    with open(t17, "w") as f:
        f.write("not json at all\n")
        f.write("{{{ broken\n")
        f.write("also not json\n")
    rc, out, err = run_hook(make_payload(d17, marker_msg, transcript_path=t17))
    if not run_labeled(
        "17. Garbage non-JSON lines only + marker -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 18. Valid JSON, unexpected schema (no recognizable role/type field, no
    #     "user"/"assistant" discriminator at all).
    d18 = new_case_dir(tmp_dir, "fail_closed_unexpected_schema")
    t18 = make_transcript(d18, [
        {"foo": "bar", "baz": 1},
        {"event": "something_else", "payload": [1, 2, 3]},
    ])
    rc, out, err = run_hook(make_payload(d18, marker_msg, transcript_path=t18))
    if not run_labeled(
        "18. Valid JSON, unexpected schema + marker -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 19. Transcript with NO user turn at all (a compacted window) - only an
    #     assistant entry (and a non-user/non-assistant system-ish line).
    d19 = new_case_dir(tmp_dir, "fail_closed_no_user_turn")
    t19 = make_transcript(d19, [
        {"type": "system", "content": "conversation summary: prior turns compacted"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": marker_msg}]}},
    ])
    rc, out, err = run_hook(make_payload(d19, marker_msg, transcript_path=t19))
    if not run_labeled(
        "19. No user turn at all / compacted window + marker -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 20. tool_use in a non-list assistant content shape (a bare dict rather
    #     than a list of blocks) - cannot be proven to lack a tool_use.
    d20 = new_case_dir(tmp_dir, "fail_closed_nonlist_shape")
    t20 = make_transcript(d20, [
        {"type": "user", "message": {"content": [{"type": "text", "text": "Go do the work"}]}},
        {"type": "assistant", "message": {"content": {"type": "tool_use", "id": "t1", "name": "Bash"}}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": marker_msg}]}},
    ])
    rc, out, err = run_hook(make_payload(d20, marker_msg, transcript_path=t20))
    if not run_labeled(
        "20. tool_use in a non-list assistant content shape + marker -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    return failed


def test_spend_money_hard_stop_must_allow(tmp_dir: str) -> int:
    """Finding 4: spending money is a hard-stop per content/sections/
    02-delegation.md's enumeration. It must suppress the stall classifier
    exactly like the destructive/irreversible tokens already do."""
    print("\n  [MUST ALLOW: Finding 4 - spend-money hard-stop]")
    failed = 0
    d = new_case_dir(tmp_dir, "spend_money_hard_stop")
    msg = (
        "This run will spend about $400 of API credit. Proceeding with the "
        "smaller sample (recommended) needs your OK first."
    )
    t = transcript_no_tool_call(d, msg)
    rc, out, err = run_hook(make_payload(d, msg, transcript_path=t))
    if not run_labeled(
        "21. Spend-money hard-stop + marker + 0 tool calls -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1
    return failed


def test_hard_stop_cooccurrence_narrowing(tmp_dir: str) -> int:
    """Fix pass 2: the spend-money and external-message hard-stop categories
    were narrowed from bare-word matches to co-occurrence checks (action
    token + monetary/authorization signal, or action token + external-facing
    target). A hard-gate hit SUPPRESSES the stall classifier entirely, so an
    over-broad gate silences the guard on a genuine stall - not merely a
    benign false-negative. These cases pin both directions: genuine
    hard-stops must still suppress (ALLOW), and ordinary conductor vocabulary
    using the same action words must no longer suppress (BLOCK)."""
    print("\n  [Fix pass 2: spend/external-message hard-stop co-occurrence narrowing]")
    failed = 0

    # 23. Genuine spend hard-stop (dollar amount + "credit" + "your OK") ->
    #     ALLOW (suppressed). Same case as test_spend_money_hard_stop_must_
    #     allow's msg, duplicated here under the narrowing-specific label set
    #     for traceability with the fix-pass return notes.
    d23 = new_case_dir(tmp_dir, "narrowing_spend_genuine")
    msg23 = (
        "This run will spend about $400 of API credit. Proceeding with the "
        "smaller sample (recommended) needs your OK first."
    )
    t23 = transcript_no_tool_call(d23, msg23)
    rc, out, err = run_hook(make_payload(d23, msg23, transcript_path=t23))
    if not run_labeled(
        "23. Genuine spend hard-stop ($400, credit, your OK) -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 24. Genuine external-message hard-stop: "post" + "comment" on the PR.
    d24 = new_case_dir(tmp_dir, "narrowing_external_post_comment")
    msg24 = (
        "I can post a comment on the PR summarizing this. Proceeding with "
        "the summary unless you say otherwise."
    )
    t24 = transcript_no_tool_call(d24, msg24)
    rc, out, err = run_hook(make_payload(d24, msg24, transcript_path=t24))
    if not run_labeled(
        "24. Genuine external-message hard-stop (post a PR comment) -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 25. Genuine external-message hard-stop: "email" + "customer".
    d25 = new_case_dir(tmp_dir, "narrowing_external_email_customer")
    msg25 = (
        "That would email the customer directly. Proceeding with the draft "
        "unless you say otherwise."
    )
    t25 = transcript_no_tool_call(d25, msg25)
    rc, out, err = run_hook(make_payload(d25, msg25, transcript_path=t25))
    if not run_labeled(
        "25. Genuine external-message hard-stop (email the customer) -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 26. Force-push hard-stop (unaffected category, control) -> ALLOW.
    d26 = new_case_dir(tmp_dir, "narrowing_force_push_control")
    msg26 = (
        "This requires a force push to main. Proceeding with the rebase "
        "unless you say otherwise."
    )
    t26 = transcript_no_tool_call(d26, msg26)
    rc, out, err = run_hook(make_payload(d26, msg26, transcript_path=t26))
    if not run_labeled(
        "26. Force-push hard-stop (control, unaffected category) -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 27. Production-delete/schema-migration hard-stop (unaffected category,
    #     control) -> ALLOW.
    d27 = new_case_dir(tmp_dir, "narrowing_prod_delete_control")
    msg27 = (
        "This deletes the production table. Proceeding with the migration "
        "unless you say otherwise."
    )
    t27 = transcript_no_tool_call(d27, msg27)
    rc, out, err = run_hook(make_payload(d27, msg27, transcript_path=t27))
    if not run_labeled(
        "27. Production delete/migration hard-stop (control, unaffected category) -> ALLOW",
        rc, out, err, "ALLOW",
    ):
        failed += 1

    # 28. Ordinary internal-spawn narration using "sending" -> no external
    #     target present -> BLOCK (genuine stall, previously wrongly
    #     suppressed).
    d28 = new_case_dir(tmp_dir, "narrowing_sending_internal_spawn")
    msg28 = "Sending the brief to the engineer now. Proceeding with unit 3 unless you say otherwise."
    t28 = transcript_no_tool_call(d28, msg28)
    rc, out, err = run_hook(make_payload(d28, msg28, transcript_path=t28))
    if not run_labeled(
        "28. 'Sending the brief to the engineer' (no external target) -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    # 29. Ordinary "cost" vocabulary with no monetary/authorization signal ->
    #     BLOCK (genuine stall, previously wrongly suppressed).
    d29 = new_case_dir(tmp_dir, "narrowing_cost_minutes")
    msg29 = "This will cost a few minutes. Proceeding with the rebase unless you say otherwise."
    t29 = transcript_no_tool_call(d29, msg29)
    rc, out, err = run_hook(make_payload(d29, msg29, transcript_path=t29))
    if not run_labeled(
        "29. 'This will cost a few minutes' (no monetary/authorization signal) -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    # 30. No spend/external vocabulary at all -> BLOCK (baseline stall,
    #     control).
    d30 = new_case_dir(tmp_dir, "narrowing_plain_stall_control")
    msg30 = "Proceeding with the golden-text pin unless you say otherwise."
    t30 = transcript_no_tool_call(d30, msg30)
    rc, out, err = run_hook(make_payload(d30, msg30, transcript_path=t30))
    if not run_labeled(
        "30. Plain stall with no hard-stop vocabulary at all (control) -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    # 31. Ordinary "notifying" vocabulary with no external target -> BLOCK
    #     (genuine stall, previously wrongly suppressed).
    d31 = new_case_dir(tmp_dir, "narrowing_notifying_internal")
    msg31 = (
        "Notifying the sibling engineer of the base change. Proceeding with "
        "the cherry-pick unless you say otherwise."
    )
    t31 = transcript_no_tool_call(d31, msg31)
    rc, out, err = run_hook(make_payload(d31, msg31, transcript_path=t31))
    if not run_labeled(
        "31. 'Notifying the sibling engineer' (no external target) -> BLOCK",
        rc, out, err, "BLOCK",
    ):
        failed += 1

    return failed


def test_dominant_compliant_shape(tmp_dir: str) -> int:
    """Finding 1: the dominant conductor turn shape - spawn a tool, receive a
    harness task-notification, then report a proceeding-with digest for the
    next unit - must ALLOW. The task-notification (type:"user", isMeta
    ABSENT, plain-string content) must not be mistaken for a new human-turn
    boundary that would hide the earlier tool_use from view."""
    print("\n  [MUST ALLOW: Finding 1 - dominant compliant shape (spawn -> notification -> digest)]")
    failed = 0
    d = new_case_dir(tmp_dir, "dominant_compliant_shape")
    msg = "Unit 2 returned with sign-off. Proceeding with unit 3 unless you say otherwise."
    t = transcript_dominant_compliant_shape(d, msg)
    rc, out, err = run_hook(make_payload(d, msg, transcript_path=t))
    if not run_labeled(
        "22. Spawn -> task-notification -> proceeding-with digest -> ALLOW",
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
        total_failed += test_fail_closed_paths_must_allow(tmp_dir)
        total_failed += test_spend_money_hard_stop_must_allow(tmp_dir)
        total_failed += test_hard_stop_cooccurrence_narrowing(tmp_dir)
        total_failed += test_dominant_compliant_shape(tmp_dir)

    print()
    if total_failed == 0:
        print("All stall-detection tests passed.")
        sys.exit(0)
    else:
        print(f"{total_failed} test assertion(s) FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
