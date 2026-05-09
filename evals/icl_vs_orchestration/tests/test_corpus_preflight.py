"""Tests for corpus.preflight_test_commands().

Covers:
  - clean collection (no error, no warning)
  - ImportError during collect -> warning emitted, no raise
  - bad path -> RuntimeError with ticket_id in message
  - tickets without test_command -> silently skipped

Note: preflight_test_commands internally calls ``["pytest", "--collect-only", ...]``
via subprocess. These tests mock subprocess.run to avoid requiring pytest on PATH
(the harness invokes the tests via ``python3 -m pytest``; the bare ``pytest`` binary
may not exist on all CI machines). The mocked returncode/output values match what
real pytest would return in each scenario.
"""
from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evals.icl_vs_orchestration.corpus import preflight_test_commands


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ticket(ticket_id: str, test_command: str | None = None) -> dict:
    """Build a minimal ticket dict as returned by load_corpus()."""
    ticket_yaml: dict = {
        "ticket_id": ticket_id,
        "ticket_class": "trivial",
        "description": f"Test ticket {ticket_id}",
    }
    if test_command is not None:
        ticket_yaml["test_command"] = test_command
    return {
        "ticket_id": ticket_id,
        "ticket_yaml": ticket_yaml,
        "ticket_dir": Path("/tmp"),
        "relevant_files_dir": Path("/tmp"),
        "architect_plan_path": None,
        "brief_path": None,
    }


def _subprocess_result(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a mock CompletedProcess."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# Clean collection passes
# ---------------------------------------------------------------------------

def test_preflight_clean_collection_passes(tmp_path):
    """pytest --collect-only exits 0 -> preflight returns None with no warning."""
    ticket = _make_ticket("t-ok", test_command="pytest tests/test_foo.py -q")
    log = logging.getLogger("preflight.test.clean")

    with patch("subprocess.run", return_value=_subprocess_result(0, "1 test collected")) as mock_run:
        result = preflight_test_commands([ticket], tmp_path, log)

    assert result is None
    # subprocess.run should have been called exactly once
    assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# ImportError is deferred (warning emitted, no raise)
# ---------------------------------------------------------------------------

def test_preflight_import_error_is_deferred(tmp_path, caplog):
    """--collect-only fails with ImportError -> warning logged, no exception."""
    ticket = _make_ticket("t-import-err", test_command="pytest tests/test_foo.py -q")
    log = logging.getLogger("preflight.test.import_err")

    import_err_output = (
        "ERRORS\n"
        "ImportError while importing test module 'tests/test_foo.py'.\n"
        "ModuleNotFoundError: No module named 'nonexistent_module'\n"
    )

    with caplog.at_level(logging.WARNING, logger="preflight.test.import_err"):
        with patch(
            "subprocess.run",
            return_value=_subprocess_result(1, stderr=import_err_output),
        ):
            # Must not raise
            preflight_test_commands([ticket], tmp_path, log)

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("preflight deferred" in str(m) for m in warning_messages), (
        f"expected 'preflight deferred' warning; got: {warning_messages}"
    )


# ---------------------------------------------------------------------------
# Bad path -> RuntimeError with ticket_id
# ---------------------------------------------------------------------------

def test_preflight_bad_path_raises(tmp_path):
    """--collect-only fails for a non-import reason -> RuntimeError with ticket_id."""
    ticket = _make_ticket(
        "t-bad-path",
        test_command="pytest /nonexistent/path/test_xyz_abc.py",
    )
    log = logging.getLogger("preflight.test.bad_path")

    bad_path_output = (
        "ERROR: not found: /nonexistent/path/test_xyz_abc.py\n"
        "(no name '/nonexistent/path/test_xyz_abc.py')\n"
    )

    with patch(
        "subprocess.run",
        return_value=_subprocess_result(4, stderr=bad_path_output),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            preflight_test_commands([ticket], tmp_path, log)

    assert "t-bad-path" in str(exc_info.value), (
        f"expected ticket_id 't-bad-path' in error message; got: {exc_info.value}"
    )


# ---------------------------------------------------------------------------
# Tickets without test_command are silently skipped
# ---------------------------------------------------------------------------

def test_preflight_skips_tickets_without_test_command(tmp_path):
    """Tickets without test_command (null or absent) -> no subprocess call, no raise."""
    ticket_null = _make_ticket("t-null", test_command=None)
    # ticket without test_command key at all
    ticket_no_key: dict = {
        "ticket_id": "t-no-key",
        "ticket_yaml": {
            "ticket_id": "t-no-key",
            "ticket_class": "trivial",
            "description": "no test_command key",
        },
        "ticket_dir": Path("/tmp"),
        "relevant_files_dir": Path("/tmp"),
        "architect_plan_path": None,
        "brief_path": None,
    }
    log = logging.getLogger("preflight.test.skip")

    with patch("subprocess.run") as mock_run:
        preflight_test_commands([ticket_null, ticket_no_key], tmp_path, log)
        assert mock_run.call_count == 0, (
            f"subprocess.run should not be called for tickets without test_command; "
            f"call_count={mock_run.call_count}"
        )
