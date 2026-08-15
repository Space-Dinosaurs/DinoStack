#!/usr/bin/env python3
"""
Regression tests for hooks/enforce-ticket-batching.py.

Test groups:
  1. test_first_creation_allows_silently        - 1st creation -> allow, no
                                                    stdout, no fire-log entry.
  2. test_second_creation_allows_with_advisory   - 2nd creation -> allow WITH
                                                    an `allow_advisory` fire-log
                                                    entry and a non-empty
                                                    permissionDecisionReason.
  3. test_third_creation_denies                  - 3rd creation -> deny.
  4. test_fourth_creation_still_denies            - a denied call never
                                                    advances state, so a 4th
                                                    attempt also denies.
  5. test_bash_get_never_matches                 - a GET to the Jira issue
                                                    endpoint is never classified
                                                    as a creation.
  6. test_bash_post_matches                      - a POST to the Jira
                                                    issue-create endpoint IS
                                                    classified as a creation.
  7. test_bash_post_to_existing_issue_never_matches - a POST to
                                                    /rest/api/2/issue/DS-123
                                                    (an update, not a create)
                                                    never matches.
  8. test_linear_issue_create_mutation_matches   - a Bash curl carrying the
                                                    literal issueCreate GraphQL
                                                    mutation name matches.
  9. test_linear_save_issue_with_id_is_update    - mcp__linear__save_issue
                                                    WITH an `id` field is never
                                                    counted as a creation.
 10. test_linear_save_issue_without_id_is_create - mcp__linear__save_issue with
                                                    NO `id` field IS counted.
 11. test_jira_create_issue_always_creation      - mcp__mcp-atlassian__jira_
                                                    create_issue always counts.
 12. test_triage_marker_exempts_session          - a transcript containing the
                                                    ds-feedback-triage command
                                                    marker exempts every
                                                    creation call for the rest
                                                    of the session.
 13. test_ticket_triage_marker_also_exempts      - the ds-ticket-triage marker
                                                    exempts too.
 14. test_missing_session_id_failopen            - payload with no session_id
                                                    -> allow, no state written.
 15. test_missing_cwd_failopen                   - payload with no cwd ->
                                                    allow, no state written.
 16. test_kill_switch_disables                   - AE_TICKET_BATCH_GUARD_DISABLE=1
                                                    -> allow unconditionally,
                                                    even on what would be the
                                                    3rd creation.
 17. test_non_creation_tool_passthrough           - Read/Write tool_name ->
                                                    allow, no state written.
 18. test_malformed_stdin_failopen                - bad JSON on stdin -> exit 0.
 19. test_corrupt_state_file_treated_as_zero       - unparsable JSON on disk
                                                    -> count 0, not a permanent
                                                    block.
 20. test_unreadable_transcript_not_exempt         - a transcript_path that
                                                    does not exist never exempts
                                                    (fails to not-exempt, not to
                                                    exempt).
 21. test_two_sessions_get_independent_counters    - two different session_ids
                                                    in the same cwd never share
                                                    a counter.

Run with: python3 -m pytest bin/tests/test_enforce_ticket_batching.py -x
       or: python3 bin/tests/test_enforce_ticket_batching.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_HOOK_PATH = Path(__file__).parent.parent.parent / "hooks" / "enforce-ticket-batching.py"


def _run_hook(payload: dict, env: dict | None = None) -> tuple[int, dict | None]:
    import os

    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=run_env,
    )
    out = result.stdout.strip()
    parsed = json.loads(out) if out else None
    return result.returncode, parsed


def _is_denied(parsed: dict | None) -> bool:
    if not parsed:
        return False
    return parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def _is_advisory(parsed: dict | None) -> bool:
    if not parsed:
        return False
    out = parsed.get("hookSpecificOutput", {})
    return out.get("permissionDecision") == "allow" and bool(out.get("permissionDecisionReason"))


def _jira_payload(cwd: str, session_id: str = "sess-1") -> dict:
    return {
        "tool_name": "mcp__mcp-atlassian__jira_create_issue",
        "cwd": cwd,
        "session_id": session_id,
        "tool_input": {"project_key": "DS", "summary": "test ticket"},
    }


def _fires_path(cwd: str) -> Path:
    return Path(cwd) / ".agentic" / ".enforcement-fires.jsonl"


def _state_path(cwd: str, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", session_id)
    return Path(cwd) / ".agentic" / f".ticket-batch-{safe}.json"


def test_first_creation_allows_silently():
    with tempfile.TemporaryDirectory() as tmp:
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert parsed is None
        assert not _fires_path(tmp).exists()
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_second_creation_allows_with_advisory():
    with tempfile.TemporaryDirectory() as tmp:
        _run_hook(_jira_payload(tmp))
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert not _is_denied(parsed)
        assert _is_advisory(parsed)
        fires = _fires_path(tmp).read_text().strip().splitlines()
        assert len(fires) == 1
        entry = json.loads(fires[0])
        assert entry["decision"] == "allow_advisory"
        assert entry["hook"] == "enforce-ticket-batching"


def test_third_creation_denies():
    with tempfile.TemporaryDirectory() as tmp:
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert _is_denied(parsed)
        fires = _fires_path(tmp).read_text().strip().splitlines()
        assert len(fires) == 2
        assert json.loads(fires[-1])["decision"] == "deny"


def test_fourth_creation_still_denies():
    with tempfile.TemporaryDirectory() as tmp:
        for _ in range(4):
            rc, parsed = _run_hook(_jira_payload(tmp))
        assert _is_denied(parsed)
        # State never advanced past 2 (deny branch does not persist).
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 2


def test_bash_get_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        payload = {
            "tool_name": "Bash",
            "cwd": tmp,
            "session_id": "sess-1",
            "tool_input": {"command": "curl -s https://jira.example.com/rest/api/2/issue?jql=foo"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_post_matches():
    with tempfile.TemporaryDirectory() as tmp:
        payload = {
            "tool_name": "Bash",
            "cwd": tmp,
            "session_id": "sess-1",
            "tool_input": {
                "command": "curl -s -X POST https://jira.example.com/rest/api/2/issue -d '{}'"
            },
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_bash_post_to_existing_issue_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        payload = {
            "tool_name": "Bash",
            "cwd": tmp,
            "session_id": "sess-1",
            "tool_input": {
                "command": "curl -s -X POST https://jira.example.com/rest/api/2/issue/DS-123/transitions -d '{}'"
            },
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_linear_issue_create_mutation_matches():
    with tempfile.TemporaryDirectory() as tmp:
        payload = {
            "tool_name": "Bash",
            "cwd": tmp,
            "session_id": "sess-1",
            "tool_input": {
                "command": "curl -s https://api.linear.app/graphql -d 'mutation { issueCreate(input: {}) { success } }'"
            },
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_linear_save_issue_with_id_is_update():
    with tempfile.TemporaryDirectory() as tmp:
        payload = {
            "tool_name": "mcp__linear__save_issue",
            "cwd": tmp,
            "session_id": "sess-1",
            "tool_input": {"id": "abc-123", "state": "In Progress"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_linear_save_issue_without_id_is_create():
    with tempfile.TemporaryDirectory() as tmp:
        payload = {
            "tool_name": "mcp__linear__save_issue",
            "cwd": tmp,
            "session_id": "sess-1",
            "tool_input": {"title": "New ticket", "teamId": "team-1"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_jira_create_issue_always_creation():
    with tempfile.TemporaryDirectory() as tmp:
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def _transcript_with_marker(tmp: str, marker: str) -> str:
    transcript = Path(tmp) / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"role": "user", "content": f"<command-message>run</command-message>{marker}"})
        + "\n"
    )
    return str(transcript)


def test_triage_marker_exempts_session():
    with tempfile.TemporaryDirectory() as tmp:
        tpath = _transcript_with_marker(tmp, "<command-name>ds-feedback-triage</command-name>")
        for _ in range(5):
            payload = _jira_payload(tmp)
            payload["transcript_path"] = tpath
            rc, parsed = _run_hook(payload)
            assert rc == 0
            assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_ticket_triage_marker_also_exempts():
    with tempfile.TemporaryDirectory() as tmp:
        tpath = _transcript_with_marker(tmp, "<command-name>ds-ticket-triage</command-name>")
        payload = _jira_payload(tmp)
        payload["transcript_path"] = tpath
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_missing_session_id_failopen():
    with tempfile.TemporaryDirectory() as tmp:
        payload = _jira_payload(tmp)
        del payload["session_id"]
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not (Path(tmp) / ".agentic").exists() or not any(
            (Path(tmp) / ".agentic").glob(".ticket-batch-*.json")
        )


def test_missing_cwd_failopen():
    payload = {
        "tool_name": "mcp__mcp-atlassian__jira_create_issue",
        "session_id": "sess-1",
        "tool_input": {},
    }
    rc, parsed = _run_hook(payload)
    assert rc == 0
    assert parsed is None


def test_kill_switch_disables():
    with tempfile.TemporaryDirectory() as tmp:
        env = {"AE_TICKET_BATCH_GUARD_DISABLE": "1"}
        for _ in range(4):
            rc, parsed = _run_hook(_jira_payload(tmp), env=env)
            assert rc == 0
            assert parsed is None
        assert not (Path(tmp) / ".agentic").exists() or not any(
            (Path(tmp) / ".agentic").glob(".ticket-batch-*.json")
        )


def test_non_creation_tool_passthrough():
    with tempfile.TemporaryDirectory() as tmp:
        payload = {
            "tool_name": "Read",
            "cwd": tmp,
            "session_id": "sess-1",
            "tool_input": {"file_path": "/tmp/x"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not (Path(tmp) / ".agentic").exists()


def test_malformed_stdin_failopen():
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input="{not valid json",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_corrupt_state_file_treated_as_zero():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = _state_path(tmp, "sess-1")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{not json")
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert parsed is None
        state = json.loads(state_path.read_text())
        assert state["count"] == 1


def test_unreadable_transcript_not_exempt():
    with tempfile.TemporaryDirectory() as tmp:
        payload = _jira_payload(tmp)
        payload["transcript_path"] = str(Path(tmp) / "does-not-exist.jsonl")
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_two_sessions_get_independent_counters():
    with tempfile.TemporaryDirectory() as tmp:
        payload_a = _jira_payload(tmp, session_id="sess-A")
        payload_b = _jira_payload(tmp, session_id="sess-B")
        _run_hook(payload_a)
        _run_hook(payload_a)
        rc, parsed = _run_hook(payload_b)
        assert rc == 0
        assert parsed is None
        state_b = json.loads(_state_path(tmp, "sess-B").read_text())
        assert state_b["count"] == 1


if __name__ == "__main__":
    import inspect

    failures = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures.append(name)
                print(f"FAIL {name}: {e}")
    if failures:
        print(f"\n{len(failures)} failed: {failures}")
        sys.exit(1)
    print("\nAll tests passed.")
