# Run with: python3 hooks/tests/test-enforce-no-abdication.py
"""
Unit + smoke tests for hooks/enforce-no-abdication.py.

Each case pipes a JSON payload into the hook via stdin and asserts ALLOW
(exit 0, no stdout) or BLOCK (exit 0, {"decision":"block","reason":"..."}).

The smoke checks at the bottom pipe crafted payloads into the actual hook
process to verify the end-to-end block/allow behavior, including valid-JSON
output shape.

Test coverage:
  - Kill-switch (AE_ABDICATION_GUARD_DISABLE=1) -> ALLOW
  - stop_hook_active=true -> ALLOW (primary re-entrancy guard)
  - Config disabled (abdication_guard_enabled not true) -> ALLOW
  - Config enabled + abdication message -> BLOCK with valid JSON
  - Config enabled + non-abdication message -> ALLOW
  - last_assistant_message field present (both cases)
  - transcript_path fallback when last_assistant_message absent
  - Each positive permission phrase
  - Each hard-stop negative gate token
  - (recommended) and "proceeding with" negative gate
  - Counter increments and CAP halts blocking
  - Counter resets on new user turn (via user_msg_count advance)
  - Corrupt counter file -> treated as 0
  - Malformed stdin -> ALLOW (fail-open)
  - Smoke: abdicating payload -> exactly one valid JSON block object
  - Smoke: clean payload -> empty stdout
"""

import json
import os
import subprocess
import sys
import tempfile
import shutil

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-no-abdication.py"
)

# Mirrors CONSECUTIVE_BLOCK_CAP in enforce-no-abdication.py. The hook runs as a
# subprocess so we cannot import the constant; this is a fixed-contract value.
CONSECUTIVE_BLOCK_CAP = 2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_hook(
    payload: str,
    env: dict | None = None,
    timeout: int = 10,
) -> tuple[int, str, str]:
    merged_env = os.environ.copy()
    # Default: disable kill-switch so tests can exercise the normal path.
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
    """ALLOW: exit 0 and no block decision in stdout."""
    if returncode != 0:
        return False
    stripped = stdout.strip()
    if not stripped:
        return True
    try:
        obj = json.loads(stripped)
        return obj.get("decision") != "block"
    except Exception:
        return True  # unparseable output -> not a block


def is_block(returncode: int, stdout: str) -> bool:
    """BLOCK: exit 0, {"decision":"block","reason":<non-empty str>} on stdout."""
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
    """Write a .agentic/config.json with abdication_guard_enabled set."""
    agentic_dir = os.path.join(tmp_dir, ".agentic")
    os.makedirs(agentic_dir, exist_ok=True)
    config_path = os.path.join(agentic_dir, "config.json")
    with open(config_path, "w") as f:
        json.dump({"abdication_guard_enabled": enabled}, f)
    return config_path


def make_transcript(tmp_dir: str, messages: list[dict]) -> str:
    """Write a JSONL transcript file and return its path."""
    path = os.path.join(tmp_dir, "transcript.jsonl")
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return path


# An abdication message that should trigger a block.
ABDICATING_MSG = "I've analyzed the problem. Would you like me to proceed with the fix?"

# A clean message that should not trigger a block.
CLEAN_MSG = "I've analyzed the problem and found the root cause. The fix involves updating the timeout parameter in config.ts."

# ---------------------------------------------------------------------------
# Test cases using last_assistant_message field (no transcript needed)
# ---------------------------------------------------------------------------

def make_payload(
    cwd: str,
    last_assistant_message: str | None = None,
    stop_hook_active: bool = False,
    transcript_path: str = "",
) -> str:
    payload: dict = {
        "hook_event_name": "Stop",
        "session_id": "test-session-001",
        "cwd": cwd,
        "stop_hook_active": stop_hook_active,
        "permission_mode": "default",
    }
    if last_assistant_message is not None:
        payload["last_assistant_message"] = last_assistant_message
    if transcript_path:
        payload["transcript_path"] = transcript_path
    return json.dumps(payload)


def run_cases(cases: list[tuple[str, str, str, dict | None]]) -> int:
    """Run a list of (label, payload, expected, env) tuples. Returns fail count."""
    failed = 0
    for label, payload, expected, env in cases:
        rc, stdout, stderr = run_hook(payload, env=env)
        if expected == "ALLOW":
            ok = is_allow(rc, stdout)
        else:
            ok = is_block(rc, stdout)
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{status}] {label}")
        if not ok:
            print(f"         expected: {expected}")
            print(f"         rc:       {rc}")
            print(f"         stdout:   {stdout!r}")
            print(f"         stderr:   {stderr!r}")
    return failed


# ---------------------------------------------------------------------------
# Build test cases
# ---------------------------------------------------------------------------

def build_cases(tmp_dir: str) -> list[tuple[str, str, str, dict | None]]:
    make_config_file(tmp_dir, enabled=True)
    disabled_dir = os.path.join(tmp_dir, "disabled_cwd")
    os.makedirs(disabled_dir, exist_ok=True)
    make_config_file(disabled_dir, enabled=False)

    no_config_dir = os.path.join(tmp_dir, "no_config_cwd")
    os.makedirs(no_config_dir, exist_ok=True)

    cases: list[tuple[str, str, str, dict | None]] = []

    # --- Kill-switch ---
    cases.append((
        "Kill-switch AE_ABDICATION_GUARD_DISABLE=1 -> ALLOW",
        make_payload(tmp_dir, last_assistant_message=ABDICATING_MSG),
        "ALLOW",
        {"AE_ABDICATION_GUARD_DISABLE": "1"},
    ))

    # --- stop_hook_active ---
    cases.append((
        "stop_hook_active=true -> ALLOW (primary re-entrancy guard)",
        make_payload(tmp_dir, last_assistant_message=ABDICATING_MSG, stop_hook_active=True),
        "ALLOW",
        None,
    ))

    # --- Config checks ---
    cases.append((
        "Config disabled (abdication_guard_enabled=false) -> ALLOW",
        make_payload(disabled_dir, last_assistant_message=ABDICATING_MSG),
        "ALLOW",
        None,
    ))
    cases.append((
        "Config absent (no config.json) -> ALLOW (fail-open default off)",
        make_payload(no_config_dir, last_assistant_message=ABDICATING_MSG),
        "ALLOW",
        None,
    ))

    # --- Core block/allow on last_assistant_message ---
    cases.append((
        "Abdication msg ('Would you like me to proceed') -> BLOCK",
        make_payload(tmp_dir, last_assistant_message=ABDICATING_MSG),
        "BLOCK",
        None,
    ))
    cases.append((
        "Clean msg (no permission phrase) -> ALLOW",
        make_payload(tmp_dir, last_assistant_message=CLEAN_MSG),
        "ALLOW",
        None,
    ))

    # --- Malformed stdin ---
    cases.append((
        "Malformed stdin -> ALLOW (fail-open)",
        "not-json",
        "ALLOW",
        None,
    ))
    cases.append((
        "Empty stdin -> ALLOW (fail-open)",
        "",
        "ALLOW",
        None,
    ))

    # --- Positive patterns (each phrase) ---
    # Each phrase test uses a fresh isolated subdirectory so counter state from
    # prior block events does not accumulate and hit the CAP before all phrases
    # are tested. (The cap test exercises counter accumulation separately.)
    for i, phrase_msg in enumerate([
        "want me to",
        "should I",
        "shall I",
        "would you like me to",
        "do you want me to",
        "let me know if you'd like",
        "ready to proceed",
        "should I go ahead",
        "want me to go ahead",
    ]):
        phrase_dir = os.path.join(tmp_dir, f"phrase_{i}")
        os.makedirs(phrase_dir, exist_ok=True)
        make_config_file(phrase_dir, enabled=True)
        msg = f"I've finished the analysis. {phrase_msg.capitalize()} continue with the implementation?"
        cases.append((
            f"Positive phrase '{phrase_msg}' + question mark -> BLOCK",
            make_payload(phrase_dir, last_assistant_message=msg),
            "BLOCK",
            None,
        ))

    # --- Negative gate tokens ---
    for gate_token in [
        "destructive",
        "irreversible",
        "force push",
        "force-push",
        "delete",
        "drop table",
        "schema migration",
        "production deploy",
        "cannot derive",
        "missing credential",
        "api key",
        "which environment",
        "which workspace",
        "merge to main",
    ]:
        msg = f"This operation is {gate_token}. Should I proceed?"
        cases.append((
            f"Negative gate '{gate_token}' suppresses block -> ALLOW",
            make_payload(tmp_dir, last_assistant_message=msg),
            "ALLOW",
            None,
        ))

    # --- Negative gate: irreversibility phrasings (Skeptic Major #2) ---
    # Full-sentence probes that previously wrongly BLOCKED.
    irreversibility_probes = [
        "This permanently removes the production database and cannot be undone. Should I proceed?",
        "This will permanently delete every record. Want me to proceed?",
        "This permanently wipes the cache. Should I go ahead?",
        "This action can't be undone. Want me to proceed?",
        "This will overwrite the existing file. Should I proceed?",
        "The data is unrecoverable after this. Want me to proceed?",
        "There is no undo for this step. Should I proceed?",
        "This risks data loss. Want me to proceed?",
    ]
    for i, probe in enumerate(irreversibility_probes):
        cases.append((
            f"Irreversibility probe #{i} suppresses block -> ALLOW",
            make_payload(tmp_dir, last_assistant_message=probe),
            "ALLOW",
            None,
        ))

    # --- Negative gate: product-judgment / design-fork (Skeptic Major #3) ---
    fork_probes = [
        "The choice changes the data model. Which direction do you want me to take?",
        "There are two viable paths. Which approach should I use?",
        "Which option do you want me to implement?",
        "Which of these schemas should I commit to?",
        "This changes the schema in a way that is hard to reverse. Should I proceed?",
        "This is a load-bearing decision. Want me to proceed?",
        "This is a design decision with long-term impact. Should I proceed?",
        "This changes the api contract. Want me to proceed?",
    ]
    for i, probe in enumerate(fork_probes):
        cases.append((
            f"Design-fork probe #{i} suppresses block -> ALLOW",
            make_payload(tmp_dir, last_assistant_message=probe),
            "ALLOW",
            None,
        ))

    # --- Special negative gates: (recommended) and proceeding with ---
    cases.append((
        "'(recommended)' suffix suppresses block -> ALLOW",
        make_payload(
            tmp_dir,
            last_assistant_message=(
                "Proceeding with approach A (recommended). Want me to start?"
            ),
        ),
        "ALLOW",
        None,
    ))
    cases.append((
        "'proceeding with' suppresses block -> ALLOW",
        make_payload(
            tmp_dir,
            last_assistant_message=(
                "Proceeding with the migration unless you say otherwise. Should I go ahead?"
            ),
        ),
        "ALLOW",
        None,
    ))
    cases.append((
        "'unless you say otherwise' suppresses block -> ALLOW",
        make_payload(
            tmp_dir,
            last_assistant_message=(
                "I'll use approach B unless you say otherwise. Want me to proceed?"
            ),
        ),
        "ALLOW",
        None,
    ))

    # --- No message text -> ALLOW ---
    cases.append((
        "Empty last_assistant_message + no transcript -> ALLOW",
        make_payload(tmp_dir, last_assistant_message=""),
        "ALLOW",
        None,
    ))

    return cases


# ---------------------------------------------------------------------------
# Counter tests (require filesystem state)
# ---------------------------------------------------------------------------

def test_counter_cap(tmp_dir: str) -> int:
    """Test that the counter cap halts blocking after CONSECUTIVE_BLOCK_CAP fires."""
    print("\n  [Counter cap tests]")
    failed = 0
    cap_dir = os.path.join(tmp_dir, "cap_cwd")
    os.makedirs(cap_dir, exist_ok=True)
    make_config_file(cap_dir, enabled=True)
    agentic_dir = os.path.join(cap_dir, ".agentic")

    # Seed the counter at CAP - 1 (1) with no user messages yet.
    counter_path = os.path.join(agentic_dir, ".abdication-guard-fire-count")
    with open(counter_path, "w") as f:
        json.dump({"count": 1, "last_user_msg_count": 0}, f)

    # First call: count=1, last_user_msg_count=0, no transcript -> should still block
    # (count < CAP=2) and increment to 2.
    payload1 = make_payload(cap_dir, last_assistant_message=ABDICATING_MSG)
    rc1, stdout1, _ = run_hook(payload1)
    ok1 = is_block(rc1, stdout1)
    print(f"    [{'PASS' if ok1 else 'FAIL'}] Counter at 1/2 -> BLOCK (fires, increments to 2)")
    if not ok1:
        failed += 1
        print(f"         rc={rc1} stdout={stdout1!r}")

    # Read counter - should now be 2.
    with open(counter_path) as f:
        state = json.load(f)
    ok_count = state["count"] == 2
    print(f"    [{'PASS' if ok_count else 'FAIL'}] Counter incremented to 2")
    if not ok_count:
        failed += 1

    # Second call: count=2 = CAP -> should NOT block.
    payload2 = make_payload(cap_dir, last_assistant_message=ABDICATING_MSG)
    rc2, stdout2, _ = run_hook(payload2)
    ok2 = is_allow(rc2, stdout2)
    print(f"    [{'PASS' if ok2 else 'FAIL'}] Counter at CAP=2 -> ALLOW (halted)")
    if not ok2:
        failed += 1
        print(f"         rc={rc2} stdout={stdout2!r}")

    return failed


def test_54360_loop_terminates(tmp_dir: str) -> int:
    """REGRESSION (Skeptic CRITICAL): the #54360 infinite-loop scenario.

    Simulates: stop_hook_active NEVER flips to true across re-entries (CC bug
    #54360), AND the model runs tools while "proceeding" so the transcript
    accumulates tool_result lines recorded as type:"user" between blocks.

    The OLD _count_user_messages counted those tool_result lines as user turns,
    so current_user_msg_count inflated on every re-entry, the reset condition
    (current > last) fired every time, count was pinned at 1, the CAP was never
    reached, and the hook blocked FOREVER.

    After the fix, tool_result and meta lines are NOT counted as genuine human
    turns, so the user-turn count stays flat across re-entries, the counter
    accumulates, and blocking STOPS at CONSECUTIVE_BLOCK_CAP. This test fails
    against the pre-fix code and passes after.
    """
    print("\n  [#54360 loop-termination regression]")
    failed = 0
    loop_dir = os.path.join(tmp_dir, "loop54360_cwd")
    os.makedirs(loop_dir, exist_ok=True)
    make_config_file(loop_dir, enabled=True)

    # The transcript at the moment the hook is first (re-)entered: one genuine
    # human turn, then an abdicating assistant message.
    transcript_lines = [
        # Genuine human turn (real text content) - CC native shape.
        {"type": "user", "message": {"content": [{"type": "text", "text": "Do the work"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": ABDICATING_MSG}]}},
    ]

    # We simulate up to CAP+2 re-entries. stop_hook_active stays FALSE the whole
    # time (the bug). Between each re-entry, the model "proceeded" and ran a
    # tool, so a tool_result line (type:"user") is appended - exactly the
    # inflation vector that broke the old counter.
    blocked_each_round = []
    max_rounds = CONSECUTIVE_BLOCK_CAP + 2
    for round_idx in range(max_rounds):
        transcript_path = make_transcript(loop_dir, transcript_lines)
        payload = json.dumps({
            "hook_event_name": "Stop",
            "session_id": "loop-54360",
            "cwd": loop_dir,
            "stop_hook_active": False,  # the bug: never propagates
            "permission_mode": "default",
            "transcript_path": transcript_path,
            "last_assistant_message": ABDICATING_MSG,
        })
        rc, stdout, _ = run_hook(payload)
        blocked = is_block(rc, stdout)
        blocked_each_round.append(blocked)

        # Simulate the model proceeding and running a tool: append a tool_result
        # line recorded as type:"user" (the inflation vector), plus the next
        # abdicating assistant message it re-stops on.
        transcript_lines.append({
            "type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"t{round_idx}", "content": "ok"}
            ]},
        })
        transcript_lines.append({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": ABDICATING_MSG}]},
        })

    # Assertion: the loop must TERMINATE. After CONSECUTIVE_BLOCK_CAP blocks the
    # hook must stop blocking (allow the stop), proving no infinite loop.
    num_blocks = sum(blocked_each_round)
    terminated = (not blocked_each_round[-1]) and num_blocks <= CONSECUTIVE_BLOCK_CAP
    print(
        f"    [{'PASS' if terminated else 'FAIL'}] #54360: stop_hook_active never flips + "
        f"tool_result inflation -> loop terminates at cap "
        f"(blocks={num_blocks}, pattern={blocked_each_round})"
    )
    if not terminated:
        failed += 1
        print(f"         blocked_each_round={blocked_each_round}")
        print(f"         num_blocks={num_blocks} (cap={CONSECUTIVE_BLOCK_CAP})")

    return failed


def test_counter_reset_on_new_user_turn(tmp_dir: str) -> int:
    """Test that a new user message resets the counter."""
    print("\n  [Counter reset tests]")
    failed = 0
    reset_dir = os.path.join(tmp_dir, "reset_cwd")
    os.makedirs(reset_dir, exist_ok=True)
    make_config_file(reset_dir, enabled=True)
    agentic_dir = os.path.join(reset_dir, ".agentic")

    # Seed counter at CAP with last_user_msg_count=1.
    counter_path = os.path.join(agentic_dir, ".abdication-guard-fire-count")
    with open(counter_path, "w") as f:
        json.dump({"count": 2, "last_user_msg_count": 1}, f)

    # Build a transcript with 2 user messages (simulating a new user turn).
    transcript = make_transcript(reset_dir, [
        {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
        {"role": "assistant", "content": [{"type": "text", "text": CLEAN_MSG}]},
        {"role": "user", "content": [{"type": "text", "text": "Now proceed"}]},
        {"role": "assistant", "content": [{"type": "text", "text": ABDICATING_MSG}]},
    ])

    # Call with transcript; user_msg_count=2 > last_user_msg_count=1 -> reset.
    # After reset, count=0 < CAP=2 -> should block.
    payload = make_payload(
        reset_dir,
        last_assistant_message=ABDICATING_MSG,
        transcript_path=transcript,
    )
    rc, stdout, _ = run_hook(payload)
    ok = is_block(rc, stdout)
    print(f"    [{'PASS' if ok else 'FAIL'}] Counter reset on new user turn (2>1) -> BLOCK again")
    if not ok:
        failed += 1
        print(f"         rc={rc} stdout={stdout!r}")

    return failed


def test_corrupt_counter_file(tmp_dir: str) -> int:
    """Test that a corrupt counter file is treated as 0."""
    print("\n  [Corrupt counter file tests]")
    failed = 0
    corrupt_dir = os.path.join(tmp_dir, "corrupt_cwd")
    os.makedirs(corrupt_dir, exist_ok=True)
    make_config_file(corrupt_dir, enabled=True)
    agentic_dir = os.path.join(corrupt_dir, ".agentic")
    counter_path = os.path.join(agentic_dir, ".abdication-guard-fire-count")
    with open(counter_path, "w") as f:
        f.write("NOT JSON {{{{")

    payload = make_payload(corrupt_dir, last_assistant_message=ABDICATING_MSG)
    rc, stdout, _ = run_hook(payload)
    ok = is_block(rc, stdout)
    print(f"    [{'PASS' if ok else 'FAIL'}] Corrupt counter file treated as 0 -> BLOCK")
    if not ok:
        failed += 1
        print(f"         rc={rc} stdout={stdout!r}")
    return failed


def test_transcript_fallback(tmp_dir: str) -> int:
    """Test transcript_path fallback when last_assistant_message is absent."""
    print("\n  [Transcript fallback tests]")
    failed = 0
    transcript_dir = os.path.join(tmp_dir, "transcript_cwd")
    os.makedirs(transcript_dir, exist_ok=True)
    make_config_file(transcript_dir, enabled=True)

    # Transcript with an abdicating assistant message.
    transcript = make_transcript(transcript_dir, [
        {"role": "user", "content": [{"type": "text", "text": "Do the thing"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "I've analyzed it."},
            {"type": "text", "text": " Would you like me to proceed?"},
        ]},
    ])
    # No last_assistant_message field - only transcript_path.
    payload = json.dumps({
        "hook_event_name": "Stop",
        "session_id": "test-transcript-001",
        "cwd": transcript_dir,
        "stop_hook_active": False,
        "permission_mode": "default",
        "transcript_path": transcript,
    })
    rc, stdout, _ = run_hook(payload)
    ok = is_block(rc, stdout)
    print(f"    [{'PASS' if ok else 'FAIL'}] Transcript fallback (abdicating) -> BLOCK")
    if not ok:
        failed += 1
        print(f"         rc={rc} stdout={stdout!r}")

    # Transcript with a clean assistant message.
    transcript2 = make_transcript(transcript_dir, [
        {"role": "user", "content": [{"type": "text", "text": "Do the thing"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": CLEAN_MSG},
        ]},
    ])
    payload2 = json.dumps({
        "hook_event_name": "Stop",
        "session_id": "test-transcript-002",
        "cwd": transcript_dir,
        "stop_hook_active": False,
        "permission_mode": "default",
        "transcript_path": transcript2,
    })
    rc2, stdout2, _ = run_hook(payload2)
    ok2 = is_allow(rc2, stdout2)
    print(f"    [{'PASS' if ok2 else 'FAIL'}] Transcript fallback (clean) -> ALLOW")
    if not ok2:
        failed += 1
        print(f"         rc={rc2} stdout={stdout2!r}")

    return failed


# ---------------------------------------------------------------------------
# Smoke tests: end-to-end subprocess verification of output shape
# ---------------------------------------------------------------------------

def test_smoke(tmp_dir: str) -> int:
    """End-to-end smoke checks: verify exact output shape from the hook process."""
    print("\n  [Smoke tests]")
    failed = 0

    smoke_dir = os.path.join(tmp_dir, "smoke_cwd")
    os.makedirs(smoke_dir, exist_ok=True)
    make_config_file(smoke_dir, enabled=True)

    # Smoke 1: abdicating payload -> exactly one valid JSON block object.
    payload_block = make_payload(smoke_dir, last_assistant_message=ABDICATING_MSG)
    rc, stdout, stderr = run_hook(payload_block)
    try:
        obj = json.loads(stdout.strip())
        shape_ok = (
            rc == 0
            and obj.get("decision") == "block"
            and isinstance(obj.get("reason"), str)
            and len(obj["reason"]) > 10
            # Ensure it is NOT nested under hookSpecificOutput (wrong shape for Stop hooks).
            and "hookSpecificOutput" not in obj
        )
    except Exception:
        shape_ok = False
    print(f"    [{'PASS' if shape_ok else 'FAIL'}] Smoke: abdicating -> valid flat block JSON (decision+reason at top level)")
    if not shape_ok:
        failed += 1
        print(f"         rc={rc} stdout={stdout!r} stderr={stderr!r}")

    # Smoke 2: clean payload -> empty stdout.
    smoke_dir2 = os.path.join(tmp_dir, "smoke_cwd2")
    os.makedirs(smoke_dir2, exist_ok=True)
    make_config_file(smoke_dir2, enabled=True)
    payload_allow = make_payload(smoke_dir2, last_assistant_message=CLEAN_MSG)
    rc2, stdout2, stderr2 = run_hook(payload_allow)
    empty_ok = rc2 == 0 and stdout2.strip() == ""
    print(f"    [{'PASS' if empty_ok else 'FAIL'}] Smoke: clean msg -> empty stdout (no JSON emitted)")
    if not empty_ok:
        failed += 1
        print(f"         rc={rc2} stdout={stdout2!r} stderr={stderr2!r}")

    # Smoke 3: kill-switch -> empty stdout even on abdicating message.
    smoke_dir3 = os.path.join(tmp_dir, "smoke_cwd3")
    os.makedirs(smoke_dir3, exist_ok=True)
    make_config_file(smoke_dir3, enabled=True)
    payload_kill = make_payload(smoke_dir3, last_assistant_message=ABDICATING_MSG)
    rc3, stdout3, _ = run_hook(payload_kill, env={"AE_ABDICATION_GUARD_DISABLE": "1"})
    kill_ok = rc3 == 0 and stdout3.strip() == ""
    print(f"    [{'PASS' if kill_ok else 'FAIL'}] Smoke: kill-switch -> empty stdout (enforcement disabled)")
    if not kill_ok:
        failed += 1
        print(f"         rc={rc3} stdout={stdout3!r}")

    return failed


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    total_failed = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Core parametric cases.
        cases = build_cases(tmp_dir)
        print(f"\nRunning {len(cases)} parametric cases...")
        total_failed += run_cases(cases)

        # Counter tests.
        total_failed += test_counter_cap(tmp_dir)
        total_failed += test_54360_loop_terminates(tmp_dir)
        total_failed += test_counter_reset_on_new_user_turn(tmp_dir)
        total_failed += test_corrupt_counter_file(tmp_dir)

        # Transcript fallback.
        total_failed += test_transcript_fallback(tmp_dir)

        # Smoke tests.
        total_failed += test_smoke(tmp_dir)

    print()
    total_cases = (
        len(cases)
        + 3   # counter cap: 3 assertions
        + 1   # #54360 loop-termination regression
        + 1   # counter reset
        + 1   # corrupt counter
        + 2   # transcript fallback
        + 3   # smoke checks
    )
    if total_failed == 0:
        print(f"All tests passed.")
        sys.exit(0)
    else:
        print(f"{total_failed} test assertion(s) FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
