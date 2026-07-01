#!/usr/bin/env python3
"""
Regression tests for hooks/enforce-background-spawn.py - Unit 5b additions.

Test groups:
  1. test_task_denied_when_sentinel_live                        - sentinel present+live -> Task denied.
  2. test_task_allowed_when_sentinel_absent                     - no sentinel -> background Task allowed.
  3. test_task_allowed_when_sentinel_pid_dead                   - sentinel with dead PID -> allowed.
  4. test_task_allowed_when_sentinel_mtime_stale                - sentinel mtime > 2h -> allowed.
  5. test_omc_skill_denied_when_sentinel_live                   - oh-my-claudecode:* Skill denied.
  6. test_normal_skill_allowed_when_sentinel_live               - non-OMC Skill always allowed.
  7. test_foreground_task_denied_no_sentinel                    - existing behavior: no bg flag denied.
  8. test_background_task_allowed_no_sentinel                   - existing: run_in_background=True ok.
  9. test_foreground_exempt_allowed_no_sentinel                 - wrap-ticket foreground exempt intact.
 10. test_malformed_stdin_failopen                              - bad JSON -> exit 0 (fail-open).
 11. test_sentinel_corrupt_failopen                             - unreadable sentinel -> allowed.
 12. test_wrap_ticket_allowed_when_sentinel_live                - MAJOR-1: wrap-ticket bypasses sentinel.
 13. test_wrap_ticket_allowed_when_sentinel_live_agent_tool     - MAJOR-1: same under tool_name=Agent.
 14. test_omc_skill_field_name_skill_key                        - MAJOR-2: "skill" key triggers deny.
 15. test_skill_absent_field_failopen                           - MAJOR-2: absent skill field -> allow.
 16. test_agent_allowed_without_run_in_background               - Agent w/o run_in_background -> ALLOWED (harness strips it).
 17. test_agent_denied_outright_when_sentinel_live_not_skill_detection - sentinel-live Agent -> denied via team-run path.
 18. test_omc_skill_denied_when_sentinel_live_agent_rename      - sentinel-live Skill oh-my-claudecode: -> denied.
 19. test_no_reap_string_in_any_deny_reason                     - sentinel deny reason contains no '--reap'.

Unit D - cross-harness team ROUTING enforcement (proactive, pre-sentinel):
 20. test_routing_denies_engineer_mapped_to_omp                 - enabled + engineer->omp -> deny w/ dispatch instruction.
 21. test_routing_allows_non_dispatchable_role_architect        - architect->omp -> allow (not dispatchable).
 22. test_routing_allows_when_enabled_false                     - enabled:false -> allow.
 23. test_routing_allows_when_team_yml_missing                  - no team.yml -> allow.
 24. test_routing_allows_on_malformed_yaml                      - malformed YAML -> fail-open, allow.
 25. test_routing_escape_hatch_disables_branch                  - AE_TEAM_ROUTING_DISABLE=1 -> allow.

Run with: python3 -m pytest bin/tests/test_enforce_background_spawn.py -x
       or: python3 bin/tests/test_enforce_background_spawn.py
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------------------
# Load the hook as a module (no .py extension issues; same pattern as
# test_agentic_configure.py)
# ---------------------------------------------------------------------------
_HOOK_PATH = Path(__file__).parent.parent.parent / "hooks" / "enforce-background-spawn.py"
_loader = importlib.machinery.SourceFileLoader("enforce_background_spawn", str(_HOOK_PATH))
_spec = importlib.util.spec_from_loader("enforce_background_spawn", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec from {_HOOK_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

_sentinel_is_live = _mod._sentinel_is_live
_SENTINEL_REL = _mod._SENTINEL_REL
_SENTINEL_MAX_AGE_S = _mod._SENTINEL_MAX_AGE_S


# ---------------------------------------------------------------------------
# Helper: run the hook end-to-end via subprocess (matches hook-test pattern
# used in test_agentic_configure.py which invokes the scripts directly).
# ---------------------------------------------------------------------------

def _run_hook(payload: dict, extra_env: dict | None = None) -> tuple[int, dict | None]:
    """Invoke the hook script with payload on stdin.

    Returns (returncode, parsed_stdout_json_or_None).

    By default AE_TEAM_ROUTING_DISABLE=1 is set so the new team-routing
    branch (Unit D) never fires for tests that predate it and are not
    exercising it - this isolates them from a real ~/.agentic/team.yml on
    the machine running the suite. Team-routing-specific tests pass
    extra_env WITHOUT that var (and point HOME at an isolated tmp dir) to
    exercise the branch deliberately.
    """
    env = dict(os.environ)
    env.setdefault("AE_TEAM_ROUTING_DISABLE", "1")
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    out = result.stdout.strip()
    parsed = json.loads(out) if out else None
    return result.returncode, parsed


def _is_denied(parsed: dict | None) -> bool:
    if not parsed:
        return False
    return (
        parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    )


def _deny_reason(parsed: dict | None) -> str:
    if not parsed:
        return ""
    return parsed.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


# ---------------------------------------------------------------------------
# Sentinel helpers
# ---------------------------------------------------------------------------

def _write_sentinel(sentinel_path: Path, pid: int) -> None:
    sentinel_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel_path.write_text(f"{pid}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: sentinel suppression (Unit 5b)
# ---------------------------------------------------------------------------

def test_task_denied_when_sentinel_live():
    """Task spawn denied when sentinel present with live PID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())  # current process = definitely alive

        payload = {
            "tool_name": "Task",
            "cwd": tmpdir,
            "tool_input": {"run_in_background": True, "subagent_type": "engineer"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert _is_denied(parsed), f"Expected deny, got: {parsed}"
        assert "agentic-team dispatch" in _deny_reason(parsed)


def test_task_allowed_when_sentinel_absent():
    """Task with run_in_background=True allowed when no sentinel."""
    with tempfile.TemporaryDirectory() as tmpdir:
        payload = {
            "tool_name": "Task",
            "cwd": tmpdir,
            "tool_input": {"run_in_background": True, "subagent_type": "engineer"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow, got: {parsed}"


def test_task_allowed_when_sentinel_pid_dead():
    """Task allowed when sentinel names a dead PID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        # PID 99999999 is virtually guaranteed to not exist.
        _write_sentinel(sentinel, 99999999)

        payload = {
            "tool_name": "Task",
            "cwd": tmpdir,
            "tool_input": {"run_in_background": True},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow (dead PID), got: {parsed}"


def test_task_allowed_when_sentinel_mtime_stale():
    """Task allowed when sentinel mtime is older than 2 h."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())

        # Back-date mtime by 3 hours.
        stale_time = time.time() - (_SENTINEL_MAX_AGE_S + 3600)
        os.utime(sentinel, (stale_time, stale_time))

        payload = {
            "tool_name": "Task",
            "cwd": tmpdir,
            "tool_input": {"run_in_background": True},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow (stale mtime), got: {parsed}"


def test_omc_skill_denied_when_sentinel_live():
    """oh-my-claudecode:* Skill denied when sentinel present+live."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())

        payload = {
            "tool_name": "Skill",
            "cwd": tmpdir,
            "tool_input": {"skill": "oh-my-claudecode:executor"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert _is_denied(parsed), f"Expected deny for OMC skill, got: {parsed}"
        assert "oh-my-claudecode:executor" in _deny_reason(parsed)


def test_normal_skill_allowed_when_sentinel_live():
    """Non-OMC Skill allowed even when sentinel present+live."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())

        payload = {
            "tool_name": "Skill",
            "cwd": tmpdir,
            "tool_input": {"skill": "graphify"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow for non-OMC skill, got: {parsed}"


# ---------------------------------------------------------------------------
# Tests: existing background-spawn enforcement (regression-safe)
# ---------------------------------------------------------------------------

def test_foreground_task_denied_no_sentinel():
    """Existing behavior: Task without run_in_background denied (no sentinel)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        payload = {
            "tool_name": "Task",
            "cwd": tmpdir,
            "tool_input": {"subagent_type": "engineer"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert _is_denied(parsed), f"Expected deny (no bg flag), got: {parsed}"
        assert "run_in_background" in _deny_reason(parsed)


def test_background_task_allowed_no_sentinel():
    """Existing behavior: Task with run_in_background=True allowed (no sentinel)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        payload = {
            "tool_name": "Task",
            "cwd": tmpdir,
            "tool_input": {"run_in_background": True, "subagent_type": "engineer"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow, got: {parsed}"


def test_foreground_exempt_allowed_no_sentinel():
    """Existing behavior: wrap-ticket foreground spawn exempt (no sentinel)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        payload = {
            "tool_name": "Task",
            "cwd": tmpdir,
            "tool_input": {"subagent_type": "wrap-ticket"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow (exempt), got: {parsed}"


def test_malformed_stdin_failopen():
    """Malformed JSON stdin -> exit 0, no deny (fail-open)."""
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input="not json {{{",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_sentinel_corrupt_failopen():
    """Sentinel with corrupt content (non-integer PID) -> fail-open, Task allowed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("not-a-pid\n", encoding="utf-8")

        payload = {
            "tool_name": "Task",
            "cwd": tmpdir,
            "tool_input": {"run_in_background": True},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow (corrupt sentinel), got: {parsed}"


# ---------------------------------------------------------------------------
# Tests: MAJOR-1 regression - wrap-ticket exempt even when sentinel live
# ---------------------------------------------------------------------------

def test_wrap_ticket_allowed_when_sentinel_live():
    """MAJOR-1 regression: wrap-ticket Task ALLOWED even when sentinel is live.

    wrap-ticket holds .agentic/wrap.lock and must complete before Phase 12
    cleanup. Blocking it when a team sentinel is live deadlocks the conductor.
    The FOREGROUND_EXEMPT check must fire before sentinel suppression.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())  # live sentinel

        payload = {
            "tool_name": "Task",
            "cwd": tmpdir,
            "tool_input": {"subagent_type": "wrap-ticket"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), (
            f"wrap-ticket must be allowed even when sentinel is live; got: {parsed}"
        )


def test_wrap_ticket_allowed_when_sentinel_live_agent_tool():
    """FOREGROUND_EXEMPT invariant under tool_name=Agent: wrap-ticket ALLOWED even
    when sentinel is live and the spawn tool is Agent (origin/main rename).

    Mirrors test_wrap_ticket_allowed_when_sentinel_live but uses tool_name='Agent'
    to pin that the FOREGROUND_EXEMPT check fires before sentinel suppression
    regardless of which tool name the harness uses.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())  # live sentinel

        payload = {
            "tool_name": "Agent",
            "cwd": tmpdir,
            "tool_input": {"subagent_type": "wrap-ticket"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), (
            f"wrap-ticket Agent spawn must be allowed even when sentinel is live; got: {parsed}"
        )


# ---------------------------------------------------------------------------
# Tests: MAJOR-2 regression - Skill field name and absent-field fail-open
# ---------------------------------------------------------------------------

def test_omc_skill_field_name_skill_key():
    """MAJOR-2: tool_input["skill"] is the canonical field for OMC skill name.

    The Claude Code Skill tool passes the skill name in tool_input["skill"].
    Source: PreToolUse payload inspection + test fixtures in this file.
    A payload with the correct field and an oh-my-claudecode: prefix must deny.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())

        payload = {
            "tool_name": "Skill",
            "cwd": tmpdir,
            "tool_input": {"skill": "oh-my-claudecode:ralph"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert _is_denied(parsed), (
            f"Expected deny for oh-my-claudecode: skill via 'skill' key, got: {parsed}"
        )
        assert "oh-my-claudecode:ralph" in _deny_reason(parsed)


def test_skill_absent_field_failopen():
    """MAJOR-2: Skill call with no recognisable skill field -> fail-open (allow).

    When tool_input contains no "skill" key (or an unrecognised structure),
    the hook cannot determine the skill name. Explicit behavior: ALLOW (fail-open).
    This prevents a missing/changed field from silently converting to a blanket deny.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())

        # No "skill" key - unrecognisable payload shape.
        payload = {
            "tool_name": "Skill",
            "cwd": tmpdir,
            "tool_input": {"unknown_field": "oh-my-claudecode:executor"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), (
            f"Skill with absent 'skill' field must fail-open (allow); got: {parsed}"
        )


# ---------------------------------------------------------------------------
# Direct unit tests for _sentinel_is_live
# ---------------------------------------------------------------------------

def test_sentinel_is_live_absent():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert _sentinel_is_live(tmpdir) is False


def test_sentinel_is_live_with_live_pid():
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())
        assert _sentinel_is_live(tmpdir) is True


def test_sentinel_is_live_dead_pid():
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, 99999999)
        assert _sentinel_is_live(tmpdir) is False


def test_sentinel_is_live_stale_mtime():
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())
        stale_time = time.time() - (_SENTINEL_MAX_AGE_S + 1)
        os.utime(sentinel, (stale_time, stale_time))
        assert _sentinel_is_live(tmpdir) is False


# ---------------------------------------------------------------------------
# Tests: PR #256 merge - Task/Agent rename UNION + reap-string removal
# ---------------------------------------------------------------------------

def test_agent_allowed_without_run_in_background():
    """Corrected (was PR256 (a)): Agent spawn without run_in_background -> ALLOWED.

    The Claude Code harness strips run_in_background from the Agent PreToolUse
    hook payload before the hook fires. Live payload capture confirmed that
    tool_input keys for an Agent spawn are exactly ['description', 'prompt',
    'subagent_type'] - run_in_background is absent. Enforcing it would deny
    every Agent spawn. The hook's background enforcement applies to the legacy
    'Task' tool name only; Agent is background-by-default at the harness level.

    This test uses the realistic harness payload shape (no run_in_background).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        payload = {
            "tool_name": "Agent",
            "cwd": tmpdir,
            "tool_input": {
                "description": "Implement the feature",
                "prompt": "...",
                "subagent_type": "engineer",
            },
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed), (
            f"Agent without run_in_background must be ALLOWED (harness strips "
            f"run_in_background from Agent hook payload); got: {parsed}"
        )


def test_agent_denied_outright_when_sentinel_live_not_skill_detection():
    """PR256 (b): sentinel-live + Agent -> denied OUTRIGHT via the team-run path.

    Agent must be _deny()'d by the sentinel-suppression block and NEVER reach
    the oh-my-claudecode skill-detection sub-block. Assert the deny reason is the
    team-run reason (mentions 'cross-harness team'), NOT a skill reason.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())  # live sentinel

        payload = {
            "tool_name": "Agent",
            "cwd": tmpdir,
            # run_in_background True so that, were ordering wrong, the bg path
            # would ALLOW it; a deny here proves the sentinel path fired first.
            "tool_input": {"run_in_background": True, "subagent_type": "engineer"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert _is_denied(parsed), f"Expected outright deny for Agent, got: {parsed}"
        reason = _deny_reason(parsed)
        assert "cross-harness team" in reason, f"must be team-run deny: {reason}"
        assert "Skill" not in reason, f"Agent must NOT enter skill detection: {reason}"


def test_omc_skill_denied_when_sentinel_live_agent_rename():
    """PR256 (c): sentinel-live + Skill 'oh-my-claudecode:foo' -> denied.

    Confirms the skill sub-block is still reachable (and only) for tool_name=Skill
    after the Task/Agent UNION.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())

        payload = {
            "tool_name": "Skill",
            "cwd": tmpdir,
            "tool_input": {"skill": "oh-my-claudecode:foo"},
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert _is_denied(parsed), f"Expected deny for OMC skill, got: {parsed}"
        assert "oh-my-claudecode:foo" in _deny_reason(parsed)


def test_no_reap_string_in_any_deny_reason():
    """PR256 (d): M1 - the Task/Agent sentinel deny reason contains no '--reap'.

    The phantom --reap clause was removed from agentic-team status; the sentinel now
    self-expires. No deny path may emit a '--reap' substring.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sentinel = Path(tmpdir) / _SENTINEL_REL
        _write_sentinel(sentinel, os.getpid())  # live sentinel

        for tname in ("Task", "Agent"):
            payload = {
                "tool_name": tname,
                "cwd": tmpdir,
                "tool_input": {"run_in_background": True, "subagent_type": "engineer"},
            }
            rc, parsed = _run_hook(payload)
            assert rc == 0
            assert _is_denied(parsed), f"{tname}: expected sentinel deny, got: {parsed}"
            assert "--reap" not in _deny_reason(parsed), (
                f"{tname} deny reason must not reference --reap: {_deny_reason(parsed)}"
            )


# ---------------------------------------------------------------------------
# Unit D: cross-harness team ROUTING enforcement
# ---------------------------------------------------------------------------

def _write_project_team_yml(cwd: str, content: str) -> None:
    team_dir = Path(cwd) / ".agentic"
    team_dir.mkdir(parents=True, exist_ok=True)
    (team_dir / "team.yml").write_text(content, encoding="utf-8")


def _routing_env(isolated_home: str) -> dict:
    """Env for routing-branch tests: routing branch ENABLED, HOME isolated
    from the real machine's ~/.agentic/team.yml."""
    return {"AE_TEAM_ROUTING_DISABLE": "", "HOME": isolated_home}


def test_routing_denies_engineer_mapped_to_omp(tmp_path):
    """team.yml enabled + engineer -> omp -> deny with dispatch instruction."""
    with tempfile.TemporaryDirectory() as home_dir:
        _write_project_team_yml(
            str(tmp_path),
            "enabled: true\ndefault_harness: claude\nroles:\n"
            "  engineer:\n    harness: omp\n    model: kimi/kimi-k2.7\n",
        )
        payload = {
            "tool_name": "Task",
            "cwd": str(tmp_path),
            "tool_input": {"run_in_background": True, "subagent_type": "engineer"},
        }
        rc, parsed = _run_hook(payload, extra_env=_routing_env(home_dir))
        assert rc == 0
        assert _is_denied(parsed), f"Expected routing deny, got: {parsed}"
        reason = _deny_reason(parsed)
        assert "bin/agentic-team dispatch" in reason
        assert "--harness omp" in reason
        assert "--role engineer" in reason
        assert "kimi/kimi-k2.7" in reason


def test_routing_allows_non_dispatchable_role_architect(tmp_path):
    """architect mapped to omp is NOT in the dispatchable set -> allow."""
    with tempfile.TemporaryDirectory() as home_dir:
        _write_project_team_yml(
            str(tmp_path),
            "enabled: true\nroles:\n  architect:\n    harness: omp\n",
        )
        payload = {
            "tool_name": "Task",
            "cwd": str(tmp_path),
            "tool_input": {"run_in_background": True, "subagent_type": "architect"},
        }
        rc, parsed = _run_hook(payload, extra_env=_routing_env(home_dir))
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow (non-dispatchable role), got: {parsed}"


def test_routing_allows_when_enabled_false(tmp_path):
    """enabled: false -> allow even though engineer maps to a non-claude harness."""
    with tempfile.TemporaryDirectory() as home_dir:
        _write_project_team_yml(
            str(tmp_path),
            "enabled: false\nroles:\n  engineer:\n    harness: omp\n",
        )
        payload = {
            "tool_name": "Task",
            "cwd": str(tmp_path),
            "tool_input": {"run_in_background": True, "subagent_type": "engineer"},
        }
        rc, parsed = _run_hook(payload, extra_env=_routing_env(home_dir))
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow (enabled:false), got: {parsed}"


def test_routing_allows_when_team_yml_missing(tmp_path):
    """No team.yml anywhere -> allow (no config, nothing to enforce)."""
    with tempfile.TemporaryDirectory() as home_dir:
        payload = {
            "tool_name": "Task",
            "cwd": str(tmp_path),
            "tool_input": {"run_in_background": True, "subagent_type": "engineer"},
        }
        rc, parsed = _run_hook(payload, extra_env=_routing_env(home_dir))
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow (missing team.yml), got: {parsed}"


def test_routing_allows_on_malformed_yaml(tmp_path):
    """Malformed YAML in project team.yml -> fail-open, allow."""
    with tempfile.TemporaryDirectory() as home_dir:
        _write_project_team_yml(str(tmp_path), "enabled: true\nroles: [this is not\n  a mapping")
        payload = {
            "tool_name": "Task",
            "cwd": str(tmp_path),
            "tool_input": {"run_in_background": True, "subagent_type": "engineer"},
        }
        rc, parsed = _run_hook(payload, extra_env=_routing_env(home_dir))
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow (malformed YAML fail-open), got: {parsed}"


def test_routing_escape_hatch_disables_branch(tmp_path):
    """AE_TEAM_ROUTING_DISABLE=1 -> routing branch skipped even though
    engineer is mapped to a non-claude harness with enabled: true."""
    with tempfile.TemporaryDirectory() as home_dir:
        _write_project_team_yml(
            str(tmp_path),
            "enabled: true\nroles:\n  engineer:\n    harness: omp\n",
        )
        payload = {
            "tool_name": "Task",
            "cwd": str(tmp_path),
            "tool_input": {"run_in_background": True, "subagent_type": "engineer"},
        }
        rc, parsed = _run_hook(
            payload, extra_env={"AE_TEAM_ROUTING_DISABLE": "1", "HOME": home_dir}
        )
        assert rc == 0
        assert not _is_denied(parsed), f"Expected allow (escape hatch), got: {parsed}"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import unittest

    # Collect and run all test_ functions as a minimal test runner.
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
