#!/usr/bin/env python3
"""
Regression tests for hooks/enforce-skeptic-round-cap.py.

Test groups:
  1. test_round_1_2_3_allowed                      - rounds 1-3 all ALLOW, round_count advances.
  2. test_round_4_denied_no_decision                - 4th round with no recorded decision -> DENY,
                                                       message names round count and both permitted actions.
  3. test_round_4_allowed_with_escalate_decision     - decision:"escalate" recorded -> ALLOW, consumed
                                                       (decision reset to null after use).
  4. test_round_4_allowed_with_ship_decision_no_critical - decision:"ship", unresolved_critical:false -> ALLOW.
  5. test_round_4_denied_ship_with_unresolved_critical   - decision:"ship" AND unresolved_critical:true
                                                       -> DENY always, regardless of round/decision.
  6. test_non_skeptic_subagent_passthrough           - subagent_type == "engineer" -> allow, no state file written.
  7. test_non_agent_tool_passthrough                 - tool_name == "Read" -> allow, no crash.
  8. test_malformed_stdin_failopen                   - bad JSON on stdin -> exit 0, no deny.
  9. test_missing_cwd_failopen                       - payload with no cwd -> allow (cannot key rounds).
 10. test_non_git_cwd_failopen                       - cwd is not a git repo -> allow (no branch to key on).
 11. test_main_session_and_subagent_payload_shapes   - hook behaves identically whether agent_id/agent_type
                                                       are present (measured subagent payload) or absent
                                                       (measured main-session payload) - it never reads those keys.
 12. test_corrupt_state_file_treated_as_round_zero    - unparsable JSON on disk -> round 0, not a permanent block.
 13. test_different_branch_gets_independent_state     - two branches in the same repo never share a counter.

Run with: python3 -m pytest bin/tests/test_enforce_skeptic_round_cap.py -x
       or: python3 bin/tests/test_enforce_skeptic_round_cap.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_HOOK_PATH = Path(__file__).parent.parent.parent / "hooks" / "enforce-skeptic-round-cap.py"


def _init_repo(tmp_path: Path, branch: str = "feature/round-cap-test") -> str:
    """Create a throwaway git repo at tmp_path checked out on *branch*."""
    subprocess.run(["git", "init", "-q", "-b", branch, str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True
    )
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True
    )
    return branch


def _skeptic_payload(cwd: str, extra: dict | None = None) -> dict:
    payload = {
        "tool_name": "Agent",
        "cwd": cwd,
        "tool_input": {
            "subagent_type": "skeptic",
            "description": "review",
            "prompt": "review the diff",
        },
    }
    if extra:
        payload.update(extra)
    return payload


def _run_hook(payload: dict) -> tuple[int, dict | None]:
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    out = result.stdout.strip()
    parsed = json.loads(out) if out else None
    return result.returncode, parsed


def _is_denied(parsed: dict | None) -> bool:
    if not parsed:
        return False
    return parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def _deny_reason(parsed: dict | None) -> str:
    if not parsed:
        return ""
    return parsed.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


def _state_path(cwd: str, branch: str) -> Path:
    import re

    key = re.sub(r"[^A-Za-z0-9._-]", "-", branch)
    return Path(cwd) / ".agentic" / f"skeptic-round-{key}.json"


def _read_state(cwd: str, branch: str) -> dict:
    return json.loads(_state_path(cwd, branch).read_text())


# --------------------------------------------------------------------------- #
# 1. Rounds 1-3 permitted
# --------------------------------------------------------------------------- #
def test_round_1_2_3_allowed():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        branch = _init_repo(tmp_path)
        for expected_round in (1, 2, 3):
            rc, parsed = _run_hook(_skeptic_payload(tmp))
            assert rc == 0
            assert not _is_denied(parsed), f"round {expected_round} unexpectedly denied: {parsed}"
            state = _read_state(tmp, branch)
            assert state["round_count"] == expected_round


# --------------------------------------------------------------------------- #
# 2. 4th round denied with no decision recorded
# --------------------------------------------------------------------------- #
def test_round_4_denied_no_decision():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        branch = _init_repo(tmp_path)
        for _ in range(3):
            rc, parsed = _run_hook(_skeptic_payload(tmp))
            assert not _is_denied(parsed)

        rc, parsed = _run_hook(_skeptic_payload(tmp))
        assert rc == 0
        assert _is_denied(parsed), "4th round with no decision must be denied"
        reason = _deny_reason(parsed)
        assert "3 rounds" in reason
        assert '"ship"' in reason
        assert '"escalate"' in reason
        # round_count on disk must NOT have advanced past the cap.
        state = _read_state(tmp, branch)
        assert state["round_count"] == 3


# --------------------------------------------------------------------------- #
# 3. escalate decision unblocks the 4th round, then is consumed
# --------------------------------------------------------------------------- #
def test_round_4_allowed_with_escalate_decision():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        branch = _init_repo(tmp_path)
        for _ in range(3):
            _run_hook(_skeptic_payload(tmp))

        path = _state_path(tmp, branch)
        state = json.loads(path.read_text())
        state["decision"] = "escalate"
        path.write_text(json.dumps(state))

        rc, parsed = _run_hook(_skeptic_payload(tmp))
        assert rc == 0
        assert not _is_denied(parsed), f"escalate-authorized round 4 was denied: {parsed}"
        new_state = _read_state(tmp, branch)
        assert new_state["round_count"] == 4
        assert new_state["decision"] is None, "escalate must be consumed (single-use)"

        # A subsequent 5th-round attempt with no fresh escalate must deny again.
        rc, parsed = _run_hook(_skeptic_payload(tmp))
        assert _is_denied(parsed), "round 5 without a fresh escalate must deny"


# --------------------------------------------------------------------------- #
# 4. ship decision (no unresolved critical) unblocks the 4th round
# --------------------------------------------------------------------------- #
def test_round_4_allowed_with_ship_decision_no_critical():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        branch = _init_repo(tmp_path)
        for _ in range(3):
            _run_hook(_skeptic_payload(tmp))

        path = _state_path(tmp, branch)
        state = json.loads(path.read_text())
        state["decision"] = "ship"
        state["unresolved_critical"] = False
        path.write_text(json.dumps(state))

        rc, parsed = _run_hook(_skeptic_payload(tmp))
        assert rc == 0
        assert not _is_denied(parsed), f"ship decision with no Critical was denied: {parsed}"


# --------------------------------------------------------------------------- #
# 5. Critical always blocks - ship + unresolved_critical -> DENY regardless
# --------------------------------------------------------------------------- #
def test_round_4_denied_ship_with_unresolved_critical():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        branch = _init_repo(tmp_path)
        for _ in range(3):
            _run_hook(_skeptic_payload(tmp))

        path = _state_path(tmp, branch)
        state = json.loads(path.read_text())
        state["decision"] = "ship"
        state["unresolved_critical"] = True
        path.write_text(json.dumps(state))

        rc, parsed = _run_hook(_skeptic_payload(tmp))
        assert rc == 0
        assert _is_denied(parsed), "ship must never bypass an unresolved Critical"
        reason = _deny_reason(parsed)
        assert "Critical" in reason


# --------------------------------------------------------------------------- #
# 6/7. Passthrough for non-skeptic / non-Task-Agent tool calls
# --------------------------------------------------------------------------- #
def test_non_skeptic_subagent_passthrough():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        branch = _init_repo(tmp_path)
        payload = _skeptic_payload(tmp)
        payload["tool_input"]["subagent_type"] = "engineer"
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed)
        assert not _state_path(tmp, branch).exists()


def test_non_agent_tool_passthrough():
    with tempfile.TemporaryDirectory() as tmp:
        payload = {"tool_name": "Read", "cwd": tmp, "tool_input": {"file_path": "/x"}}
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed)


# --------------------------------------------------------------------------- #
# 8/9/10. Fail-open cases
# --------------------------------------------------------------------------- #
def test_malformed_stdin_failopen():
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input="not json{{{",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_missing_cwd_failopen():
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "skeptic"},
    }
    rc, parsed = _run_hook(payload)
    assert rc == 0
    assert not _is_denied(parsed)


def test_non_git_cwd_failopen():
    with tempfile.TemporaryDirectory() as tmp:
        # Deliberately NOT a git repo.
        rc, parsed = _run_hook(_skeptic_payload(tmp))
        assert rc == 0
        assert not _is_denied(parsed)
        assert not (Path(tmp) / ".agentic").exists()


# --------------------------------------------------------------------------- #
# 11. Payload key-shape independence (measured main-session vs subagent
#     payloads - hook must never assume either shape)
# --------------------------------------------------------------------------- #
def test_main_session_and_subagent_payload_shapes():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _init_repo(tmp_path)

        # Main-session shape: no agent_id/agent_type keys at all.
        main_payload = _skeptic_payload(tmp)
        rc1, parsed1 = _run_hook(main_payload)
        assert rc1 == 0
        assert not _is_denied(parsed1)

    with tempfile.TemporaryDirectory() as tmp2:
        tmp_path2 = Path(tmp2)
        _init_repo(tmp_path2)
        # Subagent shape: agent_id/agent_type present (should behave the same -
        # the hook does not branch on their presence).
        sub_payload = _skeptic_payload(
            tmp2, extra={"agent_id": "agent-abc123", "agent_type": "skeptic"}
        )
        rc2, parsed2 = _run_hook(sub_payload)
        assert rc2 == 0
        assert not _is_denied(parsed2)


# --------------------------------------------------------------------------- #
# 12. Corrupt state file is treated as round 0, not a permanent block
# --------------------------------------------------------------------------- #
def test_corrupt_state_file_treated_as_round_zero():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        branch = _init_repo(tmp_path)
        path = _state_path(tmp, branch)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json")

        rc, parsed = _run_hook(_skeptic_payload(tmp))
        assert rc == 0
        assert not _is_denied(parsed)
        state = _read_state(tmp, branch)
        assert state["round_count"] == 1


# --------------------------------------------------------------------------- #
# 13. Two branches in one repo never share a counter
# --------------------------------------------------------------------------- #
def test_different_branch_gets_independent_state():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        branch_a = _init_repo(tmp_path, branch="feature/unit-a")
        for _ in range(3):
            _run_hook(_skeptic_payload(tmp))
        rc, parsed = _run_hook(_skeptic_payload(tmp))
        assert _is_denied(parsed)

        subprocess.run(
            ["git", "-C", tmp, "checkout", "-q", "-b", "feature/unit-b"], check=True
        )
        rc, parsed = _run_hook(_skeptic_payload(tmp))
        assert not _is_denied(parsed), "new branch must start at round 1, not inherit unit-a's cap"
        state_b = _read_state(tmp, "feature/unit-b")
        assert state_b["round_count"] == 1
        state_a = _read_state(tmp, branch_a)
        assert state_a["round_count"] == 3


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
