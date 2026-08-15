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
 22. test_bash_grep_for_token_never_matches        - a bare grep for the
                                                    literal "issueCreate" token
                                                    never matches (Critical:
                                                    used to deny on the 3rd
                                                    such call).
 23. test_bash_git_show_pipe_grep_never_matches    - `git show <sha> | grep
                                                    issueCreate` never matches.
 24. test_bash_echo_mentioning_token_never_matches - an `echo` merely
                                                    mentioning "issueCreate"
                                                    never matches.
 25. test_bash_cat_own_hook_source_never_matches   - `cat` of the hook's own
                                                    source piped through grep
                                                    for the token never
                                                    matches.
 26. test_bash_grep_jira_endpoint_string_never_matches - a grep for the
                                                    literal Jira endpoint
                                                    string (including the
                                                    word "POST" as SEARCH
                                                    TEXT, not a real flag)
                                                    never matches.
 27. test_bash_linear_mutation_without_client_verb_never_matches - a genuine
                                                    Linear endpoint + mutation
                                                    + issueCreate token with
                                                    NO curl/wget/http verb
                                                    never matches (the client-
                                                    verb gate applies to both
                                                    sub-cases).
 27b. test_bash_curl_with_token_but_no_linear_endpoint_never_matches - a
                                                    real curl POST call with
                                                    the "issueCreate" token
                                                    present as DATA but never
                                                    targeting the Linear
                                                    endpoint never matches
                                                    (isolates the endpoint
                                                    requirement from the
                                                    client-verb gate).
 28. test_conductor_echo_marker_in_transcript_not_exempt - a transcript whose
                                                    only occurrence of the
                                                    triage marker is inside a
                                                    conductor-authored Bash
                                                    tool_result (echoed text)
                                                    does NOT exempt (Critical:
                                                    this used to be
                                                    self-grantable).
 29. test_genuine_slash_command_user_record_exempts - a transcript with a
                                                    genuine type=user,
                                                    string-content record
                                                    carrying the marker DOES
                                                    exempt.
 30. test_local_command_system_record_exempts      - a transcript with a
                                                    type=system,
                                                    subtype=local_command
                                                    record carrying the
                                                    marker DOES exempt.
 31. test_malformed_jsonl_line_skipped_not_fatal    - a transcript with one
                                                    malformed JSONL line
                                                    followed by a genuine
                                                    exempting record still
                                                    exempts (bad line skipped,
                                                    scan continues).

Run with: python3 -m pytest bin/tests/test_enforce_ticket_batching.py -x
       or: python3 bin/tests/test_enforce_ticket_batching.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_HOOK_PATH = Path(__file__).parent.parent.parent / "hooks" / "enforce-ticket-batching.py"


def _load_hook_module():
    """Direct (non-subprocess) import of the hook module, for unit-level
    tests against its internal functions/regexes (_record_is_exempt_
    marker_carrier, _TRIAGE_MARKER_RE, etc.) rather than only end-to-end
    subprocess behavior."""
    spec = importlib.util.spec_from_file_location("enforce_ticket_batching", str(_HOOK_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    """Genuine slash-command-invocation record shape - type=user with a
    plain-STRING message.content - matching the empirically-verified real
    Claude Code transcript format (see module docstring "Triage exemption"
    on the hook itself). Round 1's fixture used {"role": ..., "content":
    ...} with no top-level "type" field at all, which never matches any
    real transcript record and vacuously passed the old substring-search
    implementation only. `marker` is expected to be a full
    `<command-name>...</command-name>` string (with or without a leading
    slash after the tag) - callers below pass the REAL slash-bearing form
    copied verbatim out of a live transcript, per round-3 Critical."""
    transcript = Path(tmp) / "transcript.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": f"<command-message>run</command-message>{marker}",
            },
        })
        + "\n"
    )
    return str(transcript)


# Copied VERBATIM (byte-for-byte) out of a real, live Claude Code
# transcript on this machine
# ($CLAUDE_CONFIG_DIR=~/.claude-moment8/projects/
# -Users-tyson-Documents-Development-authentic8/
# 9d4a4d92-c101-495d-8b88-2cee74c582e2.jsonl), a genuine `/ds-ticket-
# triage` slash-command invocation - NOT hand-authored. This is the
# record shape the round-2 fixture (no leading slash) never matched
# against real data: `_is_triage_exempt` classified 0 of 621 top-level
# transcripts on this machine as exempt before the fix, including this
# one and the 1 other genuine `/ds-ticket-triage` session found (see
# round-3 engineer report). The message.content string carries BOTH the
# `<command-message>` (no slash) and `<command-name>` (with slash) tags
# in the same real record, in that order.
_REAL_TICKET_TRIAGE_RECORD_CONTENT = (
    "<command-message>ds-ticket-triage</command-message>\n"
    "<command-name>/ds-ticket-triage</command-name>\n"
    "<command-args>there was a claude code update and it interrupted "
    "several sessions. We need to figure out what got finished and what "
    "still needs worked on. I have AUT-511-517-512-518 and "
    "AUT-501-508-484-351 being worked on in two other sessions right "
    "now.</command-args>"
)


def _transcript_with_real_ticket_triage_record(tmp: str) -> str:
    """Writes a transcript containing the byte-for-byte real record
    above, wrapped in the same top-level envelope fields a genuine
    Claude Code `type: "user"` record carries (verified against the
    same live transcript this content was copied from)."""
    transcript = Path(tmp) / "transcript.jsonl"
    rec = {
        "parentUuid": "6fdc085f-24e6-405d-ba47-7b094cada287",
        "isSidechain": False,
        "type": "user",
        "message": {"role": "user", "content": _REAL_TICKET_TRIAGE_RECORD_CONTENT},
        "uuid": "77af2ae9-bae5-460c-971f-f888a67e6062",
    }
    transcript.write_text(json.dumps(rec) + "\n")
    return str(transcript)


def test_triage_marker_exempts_session():
    # Real accepted-shape marker carries a leading slash
    # (`<command-name>/ds-feedback-triage</command-name>`) - see the
    # round-3 Critical fix and `_TRIAGE_MARKER_RE`'s docstring on the
    # hook itself.
    with tempfile.TemporaryDirectory() as tmp:
        tpath = _transcript_with_marker(tmp, "<command-name>/ds-feedback-triage</command-name>")
        for _ in range(5):
            payload = _jira_payload(tmp)
            payload["transcript_path"] = tpath
            rc, parsed = _run_hook(payload)
            assert rc == 0
            assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_ticket_triage_marker_also_exempts():
    with tempfile.TemporaryDirectory() as tmp:
        tpath = _transcript_with_marker(tmp, "<command-name>/ds-ticket-triage</command-name>")
        payload = _jira_payload(tmp)
        payload["transcript_path"] = tpath
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_no_slash_marker_form_still_exempts():
    """The slash is OPTIONAL in `_TRIAGE_MARKER_RE`, not required - this
    keeps the old (round-2) no-slash literal working too, in case a
    future harness version ever drops the slash. Regression guard
    against re-narrowing the pattern back to a single hardcoded form."""
    with tempfile.TemporaryDirectory() as tmp:
        tpath = _transcript_with_marker(tmp, "<command-name>ds-ticket-triage</command-name>")
        payload = _jira_payload(tmp)
        payload["transcript_path"] = tpath
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_real_ticket_triage_transcript_record_exempts_session():
    """Critical fix regression test: uses a fixture copied VERBATIM out
    of a real, live Claude Code transcript on this machine (see
    `_REAL_TICKET_TRIAGE_RECORD_CONTENT`'s docstring) - a genuine
    `/ds-ticket-triage` invocation, not a hand-authored approximation.

    Mutation evidence: reverting `_TRIAGE_MARKER_RE` to the round-2
    no-slash-only pattern
    (`r"<command-name>ds-(?:feedback|ticket)-triage</command-name>"`,
    with no `<command-message>` alternative and no optional slash) makes
    this test fail, because the real record's `<command-name>` tag
    always carries the leading slash - confirmed by running the hook
    against this exact fixture with the pre-fix regex during round-3
    development (0 of 621 real top-level transcripts on this machine
    matched the no-slash pattern, including the 2 genuine
    `/ds-ticket-triage` sessions found by direct corpus scan)."""
    with tempfile.TemporaryDirectory() as tmp:
        tpath = _transcript_with_real_ticket_triage_record(tmp)
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


def _bash_payload(tmp: str, command: str, session_id: str = "sess-1") -> dict:
    return {
        "tool_name": "Bash",
        "cwd": tmp,
        "session_id": session_id,
        "tool_input": {"command": command},
    }


def test_bash_grep_for_token_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        rc, parsed = _run_hook(_bash_payload(tmp, "grep -rn issueCreate hooks/"))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_git_show_pipe_grep_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        cmd = "git show HEAD~1 -- hooks/enforce-ticket-batching.py | grep issueCreate"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_echo_mentioning_token_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        cmd = "echo checking issueCreate mutation docs"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_cat_own_hook_source_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        cmd = "cat hooks/enforce-ticket-batching.py | grep issueCreate"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_grep_jira_endpoint_string_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        cmd = "grep -rn 'POST /rest/api/3/issue' docs/"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_curl_with_token_but_no_linear_endpoint_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        # Client verb present, "issueCreate" token present, but never
        # targets the Linear GraphQL endpoint - isolates the endpoint
        # requirement itself from the client-verb gate above.
        cmd = "curl -s -X POST https://example.com/unrelated -d 'issueCreate mutation test'"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_linear_mutation_without_client_verb_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        # No curl/wget/http/httpie verb present anywhere - a raw payload
        # string being inspected/printed, not an actual outbound call.
        cmd = (
            "python3 -c \"print('api.linear.app/graphql mutation { "
            "issueCreate(input: {}) { success } }')\""
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_linear_endpoint_and_token_without_post_or_mutation_signal_never_matches():
    """Isolates the "and (_HTTP_POST_SIGNAL_RE... or
    _LINEAR_MUTATION_SIGNAL_RE...)" clause: a real curl call, targeting
    the real Linear GraphQL endpoint, carrying the literal issueCreate
    token, but with NEITHER an HTTP POST-method signal NOR the literal
    "mutation" keyword, must never match. Mutation-test: deleting the
    entire "and (...)" clause from `_bash_is_creation` makes this command
    match (curl + Linear endpoint + issueCreate token are all present),
    flipping this assertion to RED - the isolating test the round-3
    finding required."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = (
            "curl -s https://api.linear.app/graphql "
            "-d '{\"query\": \"{ issueCreate }\"}'"
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_python_urllib_post_to_jira_create_path_matches():
    """Positive case for the widened client-verb gate: a python3 -c
    urllib.request.Request(..., method='POST') call to the Jira
    issue-create endpoint IS classified as a creation - this is the
    documented working direct-REST bypass channel in this repo (curl/wget
    are hook-blocked here; see `.agentic/memory/
    creating-ds-jira-tickets.md`), which the round-2 shell-verb-only gate
    could never reach."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = (
            "python3 -c \"import urllib.request; "
            "urllib.request.Request('https://jira.example.com/rest/api/3/issue', "
            "method='POST')\""
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_python_urllib_mention_without_jira_path_never_matches():
    """Isolates the Python-client verb signal from the endpoint/POST
    requirement - a urllib.request call to an unrelated URL never
    matches, even though the client-verb gate is satisfied."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = "python3 -c \"import urllib.request; urllib.request.urlopen('https://example.com')\""
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_grep_of_curl_post_literal_never_matches():
    """Residual false-positive fix: a grep whose SEARCH PATTERN contains
    a literal curl-POST-to-Jira-issue-create string as DATA (not an
    actual outbound call) never matches - the leading-verb mitigation."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = "grep -rn 'curl -X POST https://x/rest/api/3/issue' bin/tests/"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_gh_pr_view_pipe_grep_linear_mutation_never_matches():
    """Residual false-positive fix: `gh pr view ... | grep ...` piping a
    fetched PR body through grep for Linear mutation text never matches -
    the leading-verb mitigation applies to the first pipeline segment."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = (
            "gh pr view 123 --json body -q .body | "
            "grep -c 'curl https://api.linear.app/graphql issueCreate mutation'"
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_ds_defer_with_watched_tokens_never_matches():
    """The hook's own documented escape hatch is never itself classified
    as a creation, even when its --description text quotes the literal
    tokens this hook watches for (the exact example from the deny/
    advisory message templates)."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = (
            "bin/ds-defer append --repo . "
            "--description 'curl POST /rest/api/3/issue bypass' "
            "--reason failed_promotion_bar"
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_post_word_case_sensitive_never_matches_ordinary_word():
    """The bare-standalone-POST fallback signal is case-SENSITIVE - an
    ordinary lowercase word containing "post" at a word boundary (e.g.
    "post-mortem" in a curl payload) must never be treated as an HTTP
    POST-method signal. Uses a real client verb (curl) and the real Jira
    issue-create path so the ONLY thing preventing a match is the
    case-sensitivity fix; without it (old case-insensitive \\bPOST\\b),
    this would match and flip to a creation."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = (
            "curl -s https://jira.example.com/rest/api/2/issue "
            "-d 'post-mortem notes, no real flag here'"
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_record_shape_gate_rejects_list_content_that_would_otherwise_match():
    """Unit-level test of `_record_is_exempt_marker_carrier` in
    isolation - repairs the round-3 Major finding that
    `test_conductor_echo_marker_in_transcript_not_exempt` below is
    vacuous: mutating the gate to accept `list` content left the
    32-test suite green, because `_record_marker_text` then returns a
    LIST (not a string) for that record, `_TRIAGE_MARKER_RE.search()`
    raises TypeError on a non-string argument, and `_is_triage_exempt`'s
    outer except silently catches it and returns False - the exact same
    observable result (not exempt) whether the gate did its job or
    merely happened not to matter. This test instead checks the gate
    function DIRECTLY, using a fixture where the marker text WOULD be
    found by a naive (gate-absent) substring/regex search over the
    record's raw serialization - proving the gate itself is what
    prevents the match, not an unrelated downstream crash.

    Mutation evidence: widening the gate's isinstance check from
    `isinstance(msg.get("content"), str)` to
    `isinstance(msg.get("content"), (str, list))` flips assertion (1)
    below from False to True - confirmed by running the mutated gate
    function directly against this exact fixture during round-3
    development."""
    hook = _load_hook_module()
    forged = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "tool_use_id": "toolu_fake",
                    "type": "tool_result",
                    "content": [
                        {
                            "type": "text",
                            "text": "<command-name>/ds-feedback-triage</command-name>",
                        }
                    ],
                }
            ],
        },
    }
    # (1) the shape gate rejects this record.
    assert hook._record_is_exempt_marker_carrier(forged) is False
    # (2) a naive substring/regex search over the raw serialization WOULD
    # find the marker - proving (1) is load-bearing, not vacuous.
    raw = json.dumps(forged)
    assert hook._TRIAGE_MARKER_RE.search(raw) is not None


def _transcript_with_records(tmp: str, lines: list[str]) -> str:
    transcript = Path(tmp) / "transcript.jsonl"
    transcript.write_text("\n".join(lines) + "\n")
    return str(transcript)


def test_conductor_echo_marker_in_transcript_not_exempt():
    with tempfile.TemporaryDirectory() as tmp:
        # Mirrors the real shape of a Bash tool_result record: type=user,
        # message.content is a LIST of tool_result blocks, not a string.
        forged = json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "tool_use_id": "toolu_fake",
                        "type": "tool_result",
                        "content": [
                            {
                                "type": "text",
                                "text": "<command-name>ds-feedback-triage</command-name>",
                            }
                        ],
                    }
                ],
            },
        })
        tpath = _transcript_with_records(tmp, [forged])
        payload = _jira_payload(tmp)
        payload["transcript_path"] = tpath
        for _ in range(3):
            rc, parsed = _run_hook(payload)
        assert rc == 0
        assert _is_denied(parsed)


def test_genuine_slash_command_user_record_exempts():
    with tempfile.TemporaryDirectory() as tmp:
        genuine = json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": "<command-name>ds-feedback-triage</command-name>",
            },
        })
        tpath = _transcript_with_records(tmp, [genuine])
        payload = _jira_payload(tmp)
        payload["transcript_path"] = tpath
        for _ in range(3):
            rc, parsed = _run_hook(payload)
            assert rc == 0
            assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_local_command_system_record_exempts():
    with tempfile.TemporaryDirectory() as tmp:
        genuine = json.dumps({
            "type": "system",
            "subtype": "local_command",
            "content": "<command-name>ds-ticket-triage</command-name>",
        })
        tpath = _transcript_with_records(tmp, [genuine])
        payload = _jira_payload(tmp)
        payload["transcript_path"] = tpath
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_malformed_jsonl_line_skipped_not_fatal():
    with tempfile.TemporaryDirectory() as tmp:
        genuine = json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": "<command-name>ds-feedback-triage</command-name>",
            },
        })
        tpath = _transcript_with_records(tmp, ["{not valid json", genuine])
        payload = _jira_payload(tmp)
        payload["transcript_path"] = tpath
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_pathological_oversized_line_skipped_scan_continues():
    """Minor fix regression test: a single physical JSONL line far larger
    than `_MAX_LINE_BYTES` (no embedded newline until its own end) is
    skipped as unparsable (it can never be valid complete JSON once
    truncated at the cap) WITHOUT the hook loading it into memory in one
    `readline()` call, and the scan continues to the next real line and
    still finds a genuine exempting record there."""
    with tempfile.TemporaryDirectory() as tmp:
        hook = _load_hook_module()
        oversized = "x" * (hook._MAX_LINE_BYTES * 2)
        genuine = json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": "<command-name>/ds-feedback-triage</command-name>",
            },
        })
        transcript = Path(tmp) / "transcript.jsonl"
        transcript.write_text(oversized + "\n" + genuine + "\n")
        payload = _jira_payload(tmp)
        payload["transcript_path"] = str(transcript)
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_iter_capped_lines_bounds_single_read_size():
    """Unit-level test of `_iter_capped_lines`: each individual
    `readline()`-backed chunk it yields is bounded by `_MAX_LINE_BYTES`
    characters, and the oversized-line remainder is fully consumed
    (bytes accounted for) before the next real line is yielded.

    Mutation evidence: reverting the transcript scan to the pre-fix
    `for line in fh:` form removes this bound entirely - a single
    physical line of any size is read whole in one call, which this test
    would have no way to pass for an oversized line (the test asserts
    every yielded chunk's length is capped; an unbounded read yields one
    chunk of the full oversized length instead)."""
    import io

    hook = _load_hook_module()
    oversized = "y" * (hook._MAX_LINE_BYTES * 2)
    genuine = "small line\n"
    fh = io.StringIO(oversized + "\n" + genuine)
    chunks = list(hook._iter_capped_lines(fh))
    for text, _consumed in chunks:
        assert len(text) <= hook._MAX_LINE_BYTES
    # First yielded item is the truncated head of the oversized line.
    assert len(chunks[0][0]) == hook._MAX_LINE_BYTES
    # Last yielded item is the genuine small line, reached intact.
    assert chunks[-1][0] == genuine
    # Total bytes consumed across all chunks equals the real total input
    # size (nothing silently dropped from the byte-accounting).
    total_input_bytes = len((oversized + "\n" + genuine).encode("utf-8"))
    assert sum(c for _t, c in chunks) == total_input_bytes


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
