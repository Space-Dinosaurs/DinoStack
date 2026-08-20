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
 13. test_ticket_triage_marker_no_longer_exempts - the ds-ticket-triage
                                                    marker does NOT exempt
                                                    (M5 fix: it is not a
                                                    create path at all).
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
 32. test_python_urllib_post_to_comment_path_never_matches - a
                                                    urllib.request POST to a
                                                    non-create Jira path
                                                    (comment endpoint) never
                                                    matches.
 33. test_python_urllib_get_to_issue_create_path_never_matches - a
                                                    urllib.request GET (no
                                                    POST signal) to the
                                                    issue-create path never
                                                    matches.
 34. test_bash_grep_of_python_urllib_post_literal_never_matches - a grep
                                                    whose search pattern
                                                    contains a literal
                                                    urllib.request POST
                                                    string as DATA never
                                                    matches.
 35. test_bash_script_file_indirection_never_matches - documented residual:
                                                    a create routed through a
                                                    script file written to
                                                    disk and executed is
                                                    never counted, since
                                                    `_bash_is_creation`
                                                    inspects the command
                                                    string only.

Note: the numbers above are historical labels assigned when each entry was
added, not file positions - this file's test order has drifted from the
index across several PRs. This index is a partial, non-contiguous list;
not every test in the file is described here. Run `grep '^def test_'
bin/tests/test_enforce_ticket_batching.py` for the authoritative, current
list of tests in file order.

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


def _grant_path(cwd: str, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", session_id)
    return Path(cwd) / ".agentic" / f".ticket-batch-grant-{safe}.json"


def _write_grant(cwd: str, session_id: str, reason: str, granted_at: str | None = None) -> Path:
    """Writes a grant file. `granted_at` defaults to the current UTC time
    (fresh - within the hook's `_GRANT_TTL_SECONDS` freshness window) so
    every existing caller of this helper keeps exercising a VALID grant;
    pass an explicit, deliberately stale `granted_at` to test expiry."""
    import time as _time

    path = _grant_path(cwd, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if granted_at is None:
        granted_at = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    path.write_text(json.dumps({"reason": reason, "granted_at": granted_at}))
    return path


def _ensure_git_marker(cwd: str) -> None:
    """Best-effort: create a `.git` EXISTENCE marker (file-or-dir, matching
    hooks/lib/repo_root.py's existence-only check - never os.path.isdir())
    at cwd so `_state_path` resolves via the `.git`-ancestor walk instead
    of fail-opening.

    Round-4 rework (coverage-gate finding, DS-171 U1): `_state_path` now
    anchors to the resolved repo root via
    `resolve_agentic_cwd_with_diagnostics` and skips (returns None,
    caller fails open) when no `.git` ancestor is found - mirroring
    `enforce-skeptic-round-cap.py`'s identical strict-tier discipline and
    its test suite's identical `_ensure_git_marker` helper. Every test
    below that exercises real batching-counter behavior needs SOME `.git`
    ancestor to resolve against, or the hook fails open and none of the
    state-file assertions would ever fire. Silently no-ops (not a
    failure) when cwd does not exist - no test here needs that path, but
    matching the round-cap precedent's defensive shape costs nothing.
    `test_state_resolution_fails_open_with_no_git_ancestor` deliberately
    does NOT call this helper, since it tests the absence of a `.git`
    ancestor."""
    try:
        Path(cwd, ".git").mkdir(exist_ok=True)
    except OSError:
        pass


def test_first_creation_allows_silently():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert parsed is None
        assert not _fires_path(tmp).exists()
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_second_creation_allows_with_advisory():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
        for _ in range(4):
            rc, parsed = _run_hook(_jira_payload(tmp))
        assert _is_denied(parsed)
        # State never advanced past 2 (deny branch does not persist).
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 2


def test_bash_get_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
# against real data: `_is_triage_exempt` classified 0 of the transcripts
# on this machine as exempt before the fix, including this one - the
# round-3 engineer report scoped its scan to a single
# `CLAUDE_CONFIG_DIR` tree; the module docstring "Triage exemption" on
# the hook itself carries the corrected, full-corpus figure (both
# `~/.claude` and `~/.claude-moment8`: 622 transcripts, 3 genuine triage
# sessions, 3/3 exempted, 0 false positives). The message.content string
# carries BOTH the
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
        _ensure_git_marker(tmp)
        tpath = _transcript_with_marker(tmp, "<command-name>/ds-feedback-triage</command-name>")
        for _ in range(5):
            payload = _jira_payload(tmp)
            payload["transcript_path"] = tpath
            rc, parsed = _run_hook(payload)
            assert rc == 0
            assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_ticket_triage_marker_no_longer_exempts():
    """M5 fix: `/ds-ticket-triage` is NOT a create path at all (see its
    own file's "Composition and non-goals" - it never mutates tracker
    tickets), so a transcript carrying only its marker must NOT exempt
    creation calls from the batching cap - a prior version of this hook
    wrongly exempted it. State must advance normally (this is treated as
    an ordinary, non-exempt 1st creation)."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        tpath = _transcript_with_marker(tmp, "<command-name>/ds-ticket-triage</command-name>")
        payload = _jira_payload(tmp)
        payload["transcript_path"] = tpath
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None  # 1st creation still silently allows...
        # ...but it is COUNTED (not exempt) - the state file now exists.
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_no_slash_marker_form_still_exempts():
    """The slash is OPTIONAL in `_TRIAGE_MARKER_RE`, not required - this
    keeps the old (round-2) no-slash literal working too, in case a
    future harness version ever drops the slash. Regression guard
    against re-narrowing the pattern back to a single hardcoded form.
    Uses `/ds-feedback-triage` (the sole remaining exempt command as of
    the M5 fix - `/ds-ticket-triage` was removed from the pattern
    entirely, see `test_ticket_triage_marker_no_longer_exempts`)."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        tpath = _transcript_with_marker(tmp, "<command-name>ds-feedback-triage</command-name>")
        payload = _jira_payload(tmp)
        payload["transcript_path"] = tpath
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_real_ticket_triage_transcript_record_no_longer_exempts():
    """M5 fix regression test: uses a fixture copied VERBATIM out of a
    real, live Claude Code transcript on this machine (see
    `_REAL_TICKET_TRIAGE_RECORD_CONTENT`'s docstring) - a genuine
    `/ds-ticket-triage` invocation, not a hand-authored approximation -
    and proves the M5 removal actually took: this real record must NO
    LONGER exempt creation calls, since `_TRIAGE_MARKER_RE` no longer
    contains a `ds-ticket-triage` alternative at all (neither the
    `<command-name>` nor the `<command-message>` form the real record
    carries). This supersedes the pre-M5 version of this test, which
    asserted the opposite (exempt) - `/ds-ticket-triage` is not a create
    path (see its own file's "Composition and non-goals"), so the
    original exemption was itself the defect.

    Mutation evidence: re-adding `ds-ticket-triage` back into
    `_TRIAGE_MARKER_RE`'s alternation (reverting the M5 fix) flips this
    test from denied-and-counted back to silently-exempt, which is
    exactly the regression this test exists to catch."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        tpath = _transcript_with_real_ticket_triage_record(tmp)
        payload = _jira_payload(tmp)
        payload["transcript_path"] = tpath
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None  # 1st creation still silently allows...
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1  # ...but it is COUNTED, not exempt.


def test_command_message_alone_exempts_isolated():
    """Minor fix regression test: isolates the `<command-message>`
    alternative in `_TRIAGE_MARKER_RE` from the `<command-name>`
    alternative it always co-occurs with in every real transcript record
    on this machine (a genuine slash-command dispatch always writes BOTH
    tags together, so a test carrying both never exercises the
    `<command-message>` clause independently - its `<command-name>`
    clause alone would already be sufficient to pass it).

    Post-M5, `/ds-ticket-triage` is no longer a member of
    `_TRIAGE_MARKER_RE` at all (see
    `test_real_ticket_triage_transcript_record_no_longer_exempts`), so
    this fixture can no longer be sliced from the real
    `_REAL_TICKET_TRIAGE_RECORD_CONTENT` transcript data the way it was
    before that fix - it is hand-authored for `/ds-feedback-triage`
    instead, matching the shape (`<command-message>...</command-message>`
    with no leading slash) every real record on this machine has been
    observed to carry for that tag.

    Mutation evidence: deleting the `<command-message>` alternative from
    `_TRIAGE_MARKER_RE` flips this test RED while leaving every other
    test in the suite green - proving the alternative is exercised by
    this test and no other."""
    message_only = "<command-message>ds-feedback-triage</command-message>"
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        transcript = Path(tmp) / "transcript.jsonl"
        rec = {
            "type": "user",
            "message": {"role": "user", "content": message_only},
        }
        transcript.write_text(json.dumps(rec) + "\n")
        payload = _jira_payload(tmp)
        payload["transcript_path"] = str(transcript)
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_missing_session_id_failopen():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
        payload = _jira_payload(tmp)
        payload["transcript_path"] = str(Path(tmp) / "does-not-exist.jsonl")
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert parsed is None
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_two_sessions_get_independent_counters():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
        rc, parsed = _run_hook(_bash_payload(tmp, "grep -rn issueCreate hooks/"))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_git_show_pipe_grep_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = "git show HEAD~1 -- hooks/enforce-ticket-batching.py | grep issueCreate"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_echo_mentioning_token_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = "echo checking issueCreate mutation docs"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_cat_own_hook_source_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = "cat hooks/enforce-ticket-batching.py | grep issueCreate"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_grep_jira_endpoint_string_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = "grep -rn 'POST /rest/api/3/issue' docs/"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_curl_with_token_but_no_linear_endpoint_never_matches():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
        cmd = "python3 -c \"import urllib.request; urllib.request.urlopen('https://example.com')\""
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_python_urllib_post_to_comment_path_never_matches():
    """Isolates the Python-client verb signal from the CREATE-path
    requirement on the comment/sub-resource shape specifically: a
    urllib.request POST to /rest/api/3/issue/DS-1/comment (an update on
    an EXISTING issue, not a create) never matches, even though the
    Python-client signal, the POST signal, and the literal "issue" path
    segment are all present."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = (
            "python3 -c \"import urllib.request; "
            "urllib.request.Request('https://jira.example.com/rest/api/3/issue/DS-1/comment', "
            "method='POST')\""
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_python_urllib_get_to_issue_create_path_never_matches():
    """Isolates the Python-client verb signal from the POST-method
    requirement: a urllib.request GET (no method='POST' kwarg, no -X
    POST/--request POST flag, no bare POST token) against the Jira
    issue-create path never matches."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = (
            "python3 -c \"import urllib.request; "
            "urllib.request.urlopen('https://jira.example.com/rest/api/3/issue')\""
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_grep_of_python_urllib_post_literal_never_matches():
    """Residual false-positive fix, Python-client variant: a grep whose
    SEARCH PATTERN contains a literal urllib.request POST-to-Jira-
    issue-create string as DATA (not an actual outbound call) never
    matches - mirrors test_bash_grep_of_curl_post_literal_never_matches
    for the Python-client signal added alongside the shell-verb gate.
    Also covers the narrower shape the ticket brief named directly: a
    grep pattern that merely contains the word "python3" as literal
    text is not itself sufficient signal (the Python-client gate keys on
    urllib.request/requests.*/httpx.*, never on a bare "python3" token,
    so this also demonstrates that weaker design choice holds)."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = (
            "grep -rn 'python3 -c urllib.request.Request POST "
            "/rest/api/3/issue' bin/tests/"
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_script_file_indirection_never_matches():
    """Documented residual (module docstring "Residual Bash false-
    negative class"): a create routed through a script file WRITTEN to
    disk and then EXECUTED - `python3 /path/to/script.py`, with no
    inline HTTP-client reference, endpoint path, or POST verb in the
    command string itself - is never counted as a creation, even when
    the referenced file genuinely contains all three signals.
    `_bash_is_creation` inspects `tool_input.command` only; it never
    resolves or reads the referenced file, so the urllib.request call,
    the `/rest/api/3/issue` path, and the POST method living inside the
    script are invisible here. This pins the gap as intentional per the
    docstring, not an untested oversight.

    The referenced script is written to disk with a real create call
    (`urllib.request` POST to `/rest/api/3/issue`) so the assertion has
    something to be wrong about - a nonexistent script path would make
    this test pass under a mutated, file-reading hook for the wrong
    reason (nothing to read), independent of whether the mutation
    actually restores the signal.

    Mutation that would redden this assertion: making `_bash_is_creation`
    resolve `command`'s script-file argument and search ITS content for
    the same signals it already checks in the command string - since the
    script on disk here genuinely carries the client reference, the
    endpoint path, and the POST verb, a file-reading hook would
    reclassify this call as a creation. Confirmed by direct execution:
    patching the hook to read the referenced file's content into the
    string handed to `_bash_is_creation` flips this assertion (see
    the fix history for this test)."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        script_path = Path(tmp) / "file_tickets.py"
        script_path.write_text(
            "import urllib.request\n"
            "req = urllib.request.Request(\n"
            "    'https://jira.example.com/rest/api/3/issue',\n"
            "    data=b'{}',\n"
            "    method='POST',\n"
            ")\n"
            "urllib.request.urlopen(req)\n"
        )
        cmd = f"python3 {script_path}"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_grep_of_curl_post_literal_never_matches():
    """Residual false-positive fix: a grep whose SEARCH PATTERN contains
    a literal curl-POST-to-Jira-issue-create string as DATA (not an
    actual outbound call) never matches - the leading-verb mitigation."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = "grep -rn 'curl -X POST https://x/rest/api/3/issue' bin/tests/"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_cat_pipe_grep_linear_mutation_never_matches():
    """Residual false-positive fix: `cat file | grep ...` piping fetched
    text through grep for Linear mutation text never matches - the
    inspection-verb mitigation applies to EVERY pipeline segment (see
    `_bash_is_simple_inspection_command`), not just the first, so a
    pipeline of two inspection-only commands is still fully exempted.
    Uses `cat`, not `gh`, as the leading verb (see
    `test_bash_gh_pipe_no_longer_exempt_after_gh_removal` below for why
    `gh` specifically was moved out of this list)."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = (
            "cat pr-body.txt | "
            "grep -c 'curl https://api.linear.app/graphql issueCreate mutation'"
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_gh_removed_from_inspection_verb_list():
    """`gh` was removed from `_BASH_INSPECTION_LEADING_VERBS` (Minor fix:
    `gh api` genuinely issues outbound HTTP, so treating any `gh`
    invocation as read-only was factually wrong). Unit-level check since
    today's `_HTTP_CLIENT_VERB_RE` (no `gh` alternative) means the
    removal has no separately-observable effect via `_bash_is_creation`
    alone - this pins the set membership directly so re-adding `gh` does
    not silently reintroduce the false-safe assumption before any future
    widening of `_HTTP_CLIENT_VERB_RE` to include `gh` would make it
    observable end-to-end."""
    hook = _load_hook_module()
    assert "gh" not in hook._BASH_INSPECTION_LEADING_VERBS


def test_bash_gh_pipe_no_longer_exempt_after_gh_removal():
    """Documents the real behavioral consequence of dropping `gh`: a
    `gh ... | grep '<text containing a real client-verb + Jira/Linear
    signal>'` pipe is NO LONGER exempted purely because `gh` leads the
    first segment - `gh` no longer satisfies
    `_bash_is_simple_inspection_command`'s all-segments-inspection
    requirement, so the command falls through to the ordinary
    client-verb/endpoint checks, which this literal grep-pattern text
    happens to satisfy (the exact former
    `test_bash_gh_pr_view_pipe_grep_linear_mutation_never_matches`
    fixture, now asserting the opposite outcome). This is an accepted,
    intentional trade-off of the `gh` removal, not a new bug - route a
    grep over fetched-body text through a `cat`/`grep`-only pipeline
    (see `test_bash_cat_pipe_grep_linear_mutation_never_matches` above)
    when the literal search text could otherwise satisfy the Linear/Jira
    signal checks."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = (
            "gh pr view 123 --json body -q .body | "
            "grep -c 'curl https://api.linear.app/graphql issueCreate mutation'"
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        # The 1st creation this session is a SILENT allow (see module
        # docstring "Decision algorithm") - the observable signal that
        # this classified as a creation at all is the persisted count,
        # not stdout.
        assert parsed is None
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_bash_ds_defer_with_watched_tokens_never_matches():
    """The hook's own documented escape hatch is never itself classified
    as a creation, even when its --description text quotes the literal
    tokens this hook watches for (the exact example from the deny/
    advisory message templates)."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = (
            "bin/ds-defer append --repo . "
            "--description 'curl POST /rest/api/3/issue bypass' "
            "--reason failed_promotion_bar"
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        assert not _state_path(tmp, "sess-1").exists()


def test_bash_pipe_into_curl_after_inspection_verb_matches():
    """Critical containment fix: `cat p.json | curl -X POST
    .../rest/api/3/issue` DOES match - a prior version's leading-verb
    check keyed suppression off only the FIRST pipeline segment ("cat"),
    silently exempting the real outbound curl call chained in via `|`.
    Mutation evidence: reverting `_bash_is_simple_inspection_command`'s
    call site back to the old `_bash_leading_verb(command) in
    _BASH_INSPECTION_LEADING_VERBS` (first-segment-only) check flips this
    RED - the leading "cat" alone would suppress the whole command."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = "cat p.json | curl -X POST https://jira.example.com/rest/api/3/issue"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None  # 1st creation this session is a silent allow
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_bash_and_compound_curl_after_grep_matches():
    """Critical containment fix: `grep -q x f && curl -X POST
    .../issue` DOES match - `&&` chains a real outbound curl call after
    an inspection-only first command; the old first-segment-only leading
    verb check suppressed the whole compound via "grep" alone. Mutation
    evidence: reverting the segment-all-inspection containment (going
    back to a bare `_bash_leading_verb(command) in
    _BASH_INSPECTION_LEADING_VERBS` check with no `&&` awareness) flips
    this RED."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = "grep -q x f && curl -X POST https://jira.example.com/rest/api/3/issue"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_bash_newline_compound_curl_after_grep_matches():
    """Critical containment fix: a grep-leading, newline-separated
    compound command chaining a real outbound curl call on its second
    line DOES match - the old leading-verb check never split on newline
    at all, so any number of real commands following a leading grep on
    line 1 were unconditionally suppressed. Mutation evidence: reverting
    `_COMMAND_SEGMENT_SPLIT_RE` to drop the `\\n` alternative flips this
    RED."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = "grep -q x f\ncurl -X POST https://jira.example.com/rest/api/3/issue"
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_bash_ds_defer_mentioned_in_compound_still_matches():
    """Critical containment fix: a real outbound curl POST to the Jira
    issue-create endpoint, compounded via `&&` with an unrelated command
    that merely MENTIONS `ds-defer` as trailing text, DOES match - the
    old `_DS_DEFER_RE.search(command)` check scanned the WHOLE command
    string unconditionally, so a real creation call anywhere in a
    compound where `ds-defer` appeared ANYWHERE (not as the actual
    escape-hatch invocation) was silently exempted. Mutation evidence:
    reverting the `_bash_is_compound(command)` guard on the `ds-defer`
    check (back to a bare `_DS_DEFER_RE.search(command)`) flips this
    RED."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        cmd = (
            "curl -X POST https://jira.example.com/rest/api/3/issue "
            "&& echo ds-defer noted for later"
        )
        rc, parsed = _run_hook(_bash_payload(tmp, cmd))
        assert rc == 0
        assert parsed is None
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 1


def test_bash_post_word_case_sensitive_never_matches_ordinary_word():
    """The bare-standalone-POST fallback signal is case-SENSITIVE - an
    ordinary lowercase word containing "post" at a word boundary (e.g.
    "post-mortem" in a curl payload) must never be treated as an HTTP
    POST-method signal. Uses a real client verb (curl) and the real Jira
    issue-create path so the ONLY thing preventing a match is the
    case-sensitivity fix; without it (old case-insensitive \\bPOST\\b),
    this would match and flip to a creation."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
        genuine = json.dumps({
            "type": "system",
            "subtype": "local_command",
            "content": "<command-name>ds-feedback-triage</command-name>",
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
        _ensure_git_marker(tmp)
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
        _ensure_git_marker(tmp)
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


def test_is_triage_exempt_delegates_to_iter_capped_lines():
    """Minor fix regression test: `_is_triage_exempt` must actually
    DELEGATE its transcript scan to `_iter_capped_lines`, not bypass it
    with a bare `for line in fh:`. Prior coverage
    (`test_pathological_oversized_line_skipped_scan_continues`) is
    vacuous for this purpose: replacing `_iter_capped_lines(fh)` in the
    scan loop with a plain `for line in fh:` leaves the full 44-test
    (pre-fix) suite green, because Python's own unbounded `for line in
    fh:` also correctly reads a giant single-line-no-newline file to EOF
    and finds the genuine exempting record on the next real line -
    identical observable behavior to the capped version for that
    fixture, so it can never distinguish "capped" from "unbounded" reads.

    This test instead monkeypatches the MODULE-LEVEL `_iter_capped_lines`
    name with a call-counting spy and asserts `_is_triage_exempt` actually
    invokes it during a real scan - a call-site check, not a behavioral
    check, so it can't be satisfied by mere behavioral coincidence.
    Mutation evidence: reverting `_is_triage_exempt`'s scan loop to a
    bare `for line in fh:` (bypassing `_iter_capped_lines` entirely)
    flips this RED (spy never called), while leaving every other
    assertion in the suite green."""
    hook = _load_hook_module()
    calls = []
    original = hook._iter_capped_lines

    def _spy(fh):
        calls.append(fh)
        yield from original(fh)

    hook._iter_capped_lines = _spy
    try:
        with tempfile.TemporaryDirectory() as tmp:
            _ensure_git_marker(tmp)
            genuine = json.dumps({
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "<command-name>/ds-feedback-triage</command-name>",
                },
            })
            transcript = Path(tmp) / "transcript.jsonl"
            transcript.write_text(genuine + "\n")
            result = hook._is_triage_exempt(str(transcript))
    finally:
        hook._iter_capped_lines = original
    assert result is True
    assert len(calls) == 1


def test_state_resolution_fails_open_with_no_git_ancestor():
    """Round-4 rework regression (coverage-gate finding, DS-171 U1): when
    cwd has NO `.git` ancestor anywhere up the tree, `_state_path` must
    resolve to None and the hook must fail open (never deny, never write
    a state file at the unresolved cwd) - matching
    `enforce-skeptic-round-cap.py`'s identical
    `test_state_resolution_fails_open_with_no_git_ancestor` and
    `hooks/lib/repo_root.py`'s Failure modes section.

    Before this fix, `_state_path` joined `Path(cwd) / ".agentic" / ...`
    directly with no repo-root resolution at all, so it silently wrote
    the batching counter at the raw, unresolved cwd instead of skipping.
    Confirmed failing pre-fix: running this test against the unfixed
    `_state_path` (`return Path(cwd) / ".agentic" / f".ticket-batch-
    {safe_session}.json"`, no `_load_repo_root`/`found_git_ancestor`
    check) produced a written state file with `count == 1` at
    `tmp/.agentic/.ticket-batch-sess-1.json` - this test's own
    `assert not (Path(tmp) / ".agentic").exists()` line failed with
    `AssertionError`, since the directory demonstrably existed.

    Builds the payload directly (not via `_jira_payload` +
    `_ensure_git_marker`) so no `.git` marker is created - this is the
    one test in this suite that specifically needs cwd to have NO `.git`
    ancestor."""
    with tempfile.TemporaryDirectory() as tmp:
        # Deliberately NOT a git repo - no _ensure_git_marker call.
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert not _is_denied(parsed)
        assert not (Path(tmp) / ".agentic").exists(), (
            "a cwd with no .git ancestor must never get a ticket-batch "
            "state file written at the unresolved cwd - the hook must "
            "skip (fail open) entirely"
        )


# --- Operator-granted mid-session exception (bin/ds-ticket-grant) ---


def test_grant_allows_third_creation():
    """A valid grant present at the 3rd creation ALLOWS it (not denied),
    persists state to count==3, deletes the grant file, and logs
    "allow_grant" via log_fire - the end-to-end demonstration the ticket
    asks for."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        grant_path = _write_grant(tmp, "sess-1", "operator said: create it, I need this tracked now")
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert not _is_denied(parsed)
        out = parsed["hookSpecificOutput"]
        assert out["permissionDecision"] == "allow"
        assert "operator said: create it" in out["permissionDecisionReason"]
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 3
        assert not grant_path.exists(), "grant must be consumed (deleted) on use"
        fires = _fires_path(tmp).read_text().strip().splitlines()
        assert json.loads(fires[-1])["decision"] == "allow_grant"


def test_grant_consumed_does_not_allow_fourth():
    """The same grant that unblocked the 3rd creation must not also
    unblock a 4th - it was deleted on first use, so the 4th falls back to
    the ordinary deny path."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        _write_grant(tmp, "sess-1", "operator authorized one more")
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert not _is_denied(parsed)  # 3rd: granted
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert _is_denied(parsed), "a consumed grant must not allow a 4th creation"
        assert "4th" in parsed["hookSpecificOutput"]["permissionDecisionReason"]


def test_malformed_grant_file_denies_like_no_grant():
    """A grant file that exists but is not valid JSON must leave 3rd+
    behavior byte-identical to the absent-grant case: denied, state
    unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        grant_path = _grant_path(tmp, "sess-1")
        grant_path.parent.mkdir(parents=True, exist_ok=True)
        grant_path.write_text("{not valid json")
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert _is_denied(parsed)
        state = json.loads(_state_path(tmp, "sess-1").read_text())
        assert state["count"] == 2
        # A malformed grant is left in place (never "consumed") - the
        # hook never reached a state where consuming it would apply.
        assert grant_path.exists()


def test_empty_reason_grant_denies_like_no_grant():
    """A grant file with a present-but-empty `reason` field must deny,
    same as no grant at all - an unattributable grant is treated as
    absent."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        _write_grant(tmp, "sess-1", "   ")
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert _is_denied(parsed)


def test_absent_grant_file_denies():
    """No grant file at all (the ordinary, overwhelmingly common case)
    denies exactly as before this feature existed - no `.ticket-batch-
    grant-*.json` is ever created as a side effect of denying."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert _is_denied(parsed)
        assert not _grant_path(tmp, "sess-1").exists()


def test_grant_for_different_session_does_not_apply():
    """A grant written for one session_id must never unblock a different
    session's 3rd creation - the grant file is session-scoped by
    filename, same as the counter itself."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        payload_a = _jira_payload(tmp, session_id="sess-A")
        payload_b = _jira_payload(tmp, session_id="sess-B")
        _run_hook(payload_a)
        _run_hook(payload_a)
        _write_grant(tmp, "sess-B", "grant meant for a different session")
        rc, parsed = _run_hook(payload_a)
        assert rc == 0
        assert _is_denied(parsed)


def test_grant_path_is_session_scoped():
    """Unit-level check on `_grant_path` itself: two different session_ids
    against the same cwd MUST resolve to two different files. The
    end-to-end `test_grant_for_different_session_does_not_apply` above
    only proves a grant written under one literal filename is never read
    under a different literal filename - true of any two distinct paths
    regardless of whether session_id is actually consulted - so it cannot
    by itself catch a mutation that makes the grant filename stop
    depending on session_id (e.g. accidentally keying it off `cwd` alone).
    This test targets that specific mutation directly."""
    mod = _load_hook_module()
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        path_a = mod._grant_path(tmp, "sess-A")
        path_b = mod._grant_path(tmp, "sess-B")
        assert path_a is not None and path_b is not None
        assert path_a != path_b


def test_unreadable_agentic_dir_exits_cleanly():
    """The hook must still terminate correctly (exit 0, no traceback) when
    `.agentic/` exists but is unreadable - covering the grant lookup path
    added by this feature, not just the pre-existing state-file path.

    Strengthened beyond `rc == 0` (a Skeptic Minor: the original assertion
    would pass a mutation that turned this path into an ALLOW, an
    ALLOW_ADVISORY, or even an allow_grant - `rc` is 0 on every one of
    those, not just on the correct silent-allow-with-no-state-write this
    call is supposed to produce as the 1st creation this session).
    `parsed is None` pins the DECISION (silent allow, no
    permissionDecisionReason emitted, no fire-log entry) - the same
    invariant `test_first_creation_allows_silently` pins for a healthy
    `.agentic/`. State cannot be written either (the directory is
    unreadable/unwritable), so no `.ticket-batch-*.json` should exist."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        agentic_dir = Path(tmp) / ".agentic"
        agentic_dir.mkdir(mode=0o000)
        try:
            rc, parsed = _run_hook(_jira_payload(tmp))
            assert rc == 0
            assert parsed is None, "1st creation with an unreadable .agentic/ must silently allow"
        finally:
            agentic_dir.chmod(0o700)
        assert not _state_path(tmp, "sess-1").exists()


def test_grant_consumption_atomic_under_concurrency():
    """M1 (Skeptic Critical-adjacent fix): four hook processes racing
    against ONE grant file at the 3rd-creation point must produce exactly
    ONE `allow_grant`, not four. A round-1 version of this hook read the
    grant file (`_load_grant`) and deleted it (`_consume_grant`) as two
    separate steps after the ALLOW was already decided - every concurrent
    reader saw the still-present, still-valid file before any of them
    deleted it. `_load_and_consume_grant` closes this by validating THEN
    attempting `Path.unlink()` as the actual act of consumption, and only
    returning the grant to the caller whose unlink call succeeds; POSIX
    serializes directory-entry removal, so at most one of N concurrent
    unlink calls on the same path can succeed."""
    import concurrent.futures

    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        # Advance to count==2 (1st + 2nd creation) sequentially first, so
        # every concurrent call below is genuinely at the 3rd-creation
        # decision point.
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        _write_grant(tmp, "sess-1", "operator said: go ahead, create it now")

        def _fire():
            return _run_hook(_jira_payload(tmp))

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: _fire(), range(4)))

        for rc, _parsed in results:
            assert rc == 0
        fires = _fires_path(tmp).read_text().strip().splitlines()
        decisions = [json.loads(line)["decision"] for line in fires]
        allow_grants = [d for d in decisions if d == "allow_grant"]
        assert len(allow_grants) == 1, (
            f"expected exactly 1 allow_grant across 4 concurrent racers, got "
            f"{len(allow_grants)}: {decisions}"
        )
        # The grant file itself must be gone - consumed by the one winner.
        assert not _grant_path(tmp, "sess-1").exists()


def test_unwritable_agentic_dir_never_allows_grant_unboundedly():
    """M1 (Skeptic Critical-adjacent fix): with `.agentic/` at mode 0o555
    (readable/traversable, NOT writable), a valid grant can never be
    durably consumed - `Path.unlink()` always fails there (removing a
    directory entry needs write access to the directory, not the file).
    A round-1 version of this hook deleted the grant only as an
    afterthought AFTER already deciding to allow, so the failed delete
    never undid the allow, and every subsequent denied creation re-read
    the same still-present, still-valid grant file and allowed it again
    - unbounded, not one-shot (measured directly: 5 consecutive creates,
    5 allows, before this fix). This test asserts the FIXED, bounded
    behavior: zero allows across 5 consecutive attempts - since nothing
    can durably record consumption in an unwritable directory, the safe
    choice is to deny, not to allow without limit."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        _write_grant(tmp, "sess-1", "operator said: create it, this is fine")
        agentic_dir = Path(tmp) / ".agentic"
        agentic_dir.chmod(0o555)
        try:
            decisions = []
            for _ in range(5):
                rc, parsed = _run_hook(_jira_payload(tmp))
                assert rc == 0
                decisions.append(parsed)
        finally:
            agentic_dir.chmod(0o700)
        allow_grants = [
            d for d in decisions
            if d and d.get("hookSpecificOutput", {}).get("permissionDecision") == "allow"
        ]
        assert len(allow_grants) == 0, (
            f"expected zero allows under an unwritable .agentic/, got {len(allow_grants)}"
        )


def test_expired_grant_denies_and_is_pruned():
    """M2 fix: a grant older than `_GRANT_TTL_SECONDS` (10 minutes) must
    be treated as no grant at all AND pruned (deleted) on the read that
    discovers its age - it must not sit around indefinitely to fire on
    some later, unrelated 3rd+ creation."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        stale_ts = "2020-01-01T00:00:00Z"
        grant_path = _write_grant(tmp, "sess-1", "operator said: yes, do it", granted_at=stale_ts)
        assert grant_path.exists()
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert _is_denied(parsed), "an expired grant must not allow the 3rd creation"
        assert not grant_path.exists(), "an expired grant must be pruned (deleted) on read"


def test_missing_granted_at_denies_like_no_grant():
    """A grant file with a valid `reason` but no `granted_at` field at all
    (or a non-string one) cannot have its freshness verified, so it must
    resolve to "no grant" - same fail-toward-deny discipline as every
    other malformed-field case, never a phantom allow just because the
    reason happened to be well-formed."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        grant_path = _grant_path(tmp, "sess-1")
        grant_path.parent.mkdir(parents=True, exist_ok=True)
        grant_path.write_text(json.dumps({"reason": "operator said: go ahead"}))
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert _is_denied(parsed)


def test_fresh_grant_within_ttl_still_allows():
    """Sanity check that the TTL fix did not break the ordinary, common
    case: a grant written moments before the retry (well within
    `_GRANT_TTL_SECONDS`) still allows the 3rd creation - guards against a
    mutation that makes the TTL check reject everything, not just stale
    grants."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        _run_hook(_jira_payload(tmp))
        _run_hook(_jira_payload(tmp))
        _write_grant(tmp, "sess-1", "operator said: yes, right now")
        rc, parsed = _run_hook(_jira_payload(tmp))
        assert rc == 0
        assert not _is_denied(parsed)
        assert parsed["hookSpecificOutput"]["permissionDecision"] == "allow"


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
