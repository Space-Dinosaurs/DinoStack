#!/usr/bin/env python3
"""
Regression tests for hooks/enforce-background-spawn.py - Unit 5b additions.

Test groups:
  1. test_task_denied_when_sentinel_live           - sentinel present+live -> Task denied.
  2. test_task_allowed_when_sentinel_absent        - no sentinel -> background Task allowed.
  3. test_task_allowed_when_sentinel_pid_dead      - sentinel with dead PID -> allowed.
  4. test_task_allowed_when_sentinel_mtime_stale   - sentinel mtime > 2h -> allowed.
  5. test_omc_skill_denied_when_sentinel_live      - oh-my-claudecode:* Skill denied.
  6. test_normal_skill_allowed_when_sentinel_live  - non-OMC Skill always allowed.
  7. test_foreground_task_denied_no_sentinel       - existing behavior: no bg flag denied.
  8. test_background_task_allowed_no_sentinel      - existing: run_in_background=True ok.
  9. test_foreground_exempt_allowed_no_sentinel    - wrap-ticket foreground exempt intact.
 10. test_malformed_stdin_failopen                 - bad JSON -> exit 0 (fail-open).
 11. test_sentinel_corrupt_failopen               - unreadable sentinel -> allowed.

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

def _run_hook(payload: dict) -> tuple[int, dict | None]:
    """Invoke the hook script with payload on stdin.

    Returns (returncode, parsed_stdout_json_or_None).
    """
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
