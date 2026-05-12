"""
Purpose: Unit tests for evals.runner.invoker. Covers _MAX_TURNS_DEFAULT value
         and the max_turns override kwarg on invoke_run.

Public API: pytest test module; no public symbols.

Upstream deps: evals.runner.invoker (_MAX_TURNS_DEFAULT, _MAX_TURNS, invoke_run),
               unittest.mock, subprocess, pathlib.

Downstream consumers: pytest runner (evals/ test suite).

Failure modes: test isolation only; no real Claude CLI calls are made.

Performance: pure unit tests; negligible runtime.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

import evals.runner.invoker as invoker_module
from evals.runner.invoker import _MAX_TURNS, _MAX_TURNS_DEFAULT, invoke_run


# ---------------------------------------------------------------------------
# Regression: _MAX_TURNS raised to 40 (smoke v5 max_turns=6 too low)
# ---------------------------------------------------------------------------


class TestMaxTurnsDefault:
    """Regression: _MAX_TURNS must be >= 40 for SWE-bench fix tasks.

    Previously set to "6" - engineers hit max_turns and exited despite a
    $0.75 spend with no fix applied (smoke v5 regression). SWE-bench tasks
    need many tool turns: read files, edit, run tests, iterate.
    """

    def test_max_turns_default_is_40_or_higher(self):
        """_MAX_TURNS_DEFAULT must be >= 40 to give engineers enough turns."""
        assert _MAX_TURNS_DEFAULT >= 40, (
            f"_MAX_TURNS_DEFAULT must be >= 40 for SWE-bench fix tasks; "
            f"got {_MAX_TURNS_DEFAULT}. "
            "Engineers hit max_turns=6 and exited without fixing anything "
            "(smoke v5 regression)."
        )

    def test_max_turns_string_matches_default(self):
        """_MAX_TURNS string must equal str(_MAX_TURNS_DEFAULT)."""
        assert _MAX_TURNS == str(_MAX_TURNS_DEFAULT), (
            f"_MAX_TURNS ({_MAX_TURNS!r}) must equal str(_MAX_TURNS_DEFAULT) "
            f"({str(_MAX_TURNS_DEFAULT)!r}). They diverged."
        )

    def test_max_turns_not_six(self):
        """_MAX_TURNS must not be '6' - the pre-regression value."""
        assert _MAX_TURNS != "6", (
            "_MAX_TURNS must not be '6'. The original value caused engineers "
            "to hit max_turns on SWE-bench fix tasks and exit with no fix applied."
        )


# ---------------------------------------------------------------------------
# invoke_run max_turns kwarg override
# ---------------------------------------------------------------------------


class TestInvokeRunMaxTurnsOverride:
    """invoke_run must forward max_turns kwarg to the --max-turns CLI flag."""

    def _make_fake_run(self, captured_cmds: list) -> object:
        def fake_subprocess_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = '{"type":"result","subtype":"success"}\n'
            mock.stderr = ""
            return mock

        return fake_subprocess_run

    def test_default_max_turns_is_applied_in_agent_mode(self, tmp_path: Path):
        """invoke_run agent mode uses _MAX_TURNS (default 40) when max_turns not given."""
        captured_cmds: list[list] = []

        with patch("subprocess.run", side_effect=self._make_fake_run(captured_cmds)):
            with patch.object(invoker_module, "parse_stream_json", return_value={
                "status": "ok", "final_text": "", "tool_calls": [],
                "tokens": {}, "turns_used": 1, "_parse_warnings": [],
                "invocation_mode": "raw-prompt",
            }):
                invoke_run("test prompt", tmp_path, timeout_seconds=60)

        assert captured_cmds, "subprocess.run must have been called"
        cmd = captured_cmds[0]
        idx = cmd.index("--max-turns")
        actual_max_turns = cmd[idx + 1]
        assert actual_max_turns == str(_MAX_TURNS_DEFAULT), (
            f"Default agent mode must use _MAX_TURNS_DEFAULT={_MAX_TURNS_DEFAULT!r}; "
            f"got {actual_max_turns!r}. cmd={cmd}"
        )

    def test_max_turns_kwarg_overrides_default(self, tmp_path: Path):
        """invoke_run must use the caller-supplied max_turns, not _MAX_TURNS."""
        captured_cmds: list[list] = []

        with patch("subprocess.run", side_effect=self._make_fake_run(captured_cmds)):
            with patch.object(invoker_module, "parse_stream_json", return_value={
                "status": "ok", "final_text": "", "tool_calls": [],
                "tokens": {}, "turns_used": 1, "_parse_warnings": [],
                "invocation_mode": "raw-prompt",
            }):
                invoke_run("test prompt", tmp_path, timeout_seconds=60, max_turns=99)

        assert captured_cmds
        cmd = captured_cmds[0]
        idx = cmd.index("--max-turns")
        actual = cmd[idx + 1]
        assert actual == "99", (
            f"--max-turns must be '99' when max_turns=99 is passed; got {actual!r}. "
            f"cmd={cmd}"
        )

    def test_max_turns_kwarg_overrides_in_command_mode(self, tmp_path: Path):
        """invoke_run command mode must also respect max_turns kwarg."""
        captured_cmds: list[list] = []

        with patch("subprocess.run", side_effect=self._make_fake_run(captured_cmds)):
            with patch.object(invoker_module, "parse_stream_json", return_value={
                "status": "ok", "final_text": "", "tool_calls": [],
                "tokens": {}, "turns_used": 1, "_parse_warnings": [],
                "invocation_mode": "raw-prompt",
                "filesystem": {},
            }):
                invoke_run(
                    "test prompt", tmp_path, timeout_seconds=60,
                    mode="command", max_turns=15,
                )

        assert captured_cmds
        cmd = captured_cmds[0]
        idx = cmd.index("--max-turns")
        actual = cmd[idx + 1]
        assert actual == "15", (
            f"--max-turns must be '15' when max_turns=15 is passed in command mode; "
            f"got {actual!r}. cmd={cmd}"
        )
