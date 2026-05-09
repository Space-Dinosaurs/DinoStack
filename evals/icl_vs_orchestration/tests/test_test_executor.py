"""Tests for test_executor.run_tests().

Covers:
  - pass outcome (returncode 0)
  - fail outcome (returncode != 0)
  - timeout (outcome="error", "timed out" in error)
  - OSError / missing binary (outcome="error", error non-empty)
  - no tests collected (pytest exit 5 -> outcome="fail")
  - stdout_tail truncation (capped at 500 chars)
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from evals.icl_vs_orchestration.test_executor import run_tests

# Use 'python -m pytest' so tests work even when the 'pytest' binary is not on PATH.
_PYTEST_CMD = f"{sys.executable} -m pytest"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_test(tmp_path: Path, name: str, content: str) -> Path:
    """Write a pytest-discoverable test file and return its path."""
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# Happy path: pass
# ---------------------------------------------------------------------------

def test_run_tests_pass(tmp_path):
    """Always-passing test -> outcome='pass', returncode=0, error=None."""
    _write_test(tmp_path, "test_pass.py", """\
        def test_pass():
            assert True
    """)
    result = run_tests(
        test_command=f"{_PYTEST_CMD} {tmp_path / 'test_pass.py'} -q",
        workspace=tmp_path,
    )
    assert result["outcome"] == "pass", f"expected 'pass', got {result}"
    assert result["returncode"] == 0
    assert result["error"] is None


# ---------------------------------------------------------------------------
# Fail path
# ---------------------------------------------------------------------------

def test_run_tests_fail(tmp_path):
    """Always-failing test -> outcome='fail', returncode != 0, error=None."""
    _write_test(tmp_path, "test_fail.py", """\
        def test_fail():
            assert False, "intentional failure"
    """)
    result = run_tests(
        test_command=f"{_PYTEST_CMD} {tmp_path / 'test_fail.py'} -q",
        workspace=tmp_path,
    )
    assert result["outcome"] == "fail", f"expected 'fail', got {result}"
    assert result["returncode"] != 0
    assert result["error"] is None


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

def test_run_tests_timeout(tmp_path):
    """Test that sleeps longer than timeout -> outcome='error', 'timed out' in error."""
    _write_test(tmp_path, "test_slow.py", """\
        import time

        def test_slow():
            time.sleep(5)
            assert True
    """)
    result = run_tests(
        test_command=f"{_PYTEST_CMD} {tmp_path / 'test_slow.py'} -q",
        workspace=tmp_path,
        timeout_seconds=1,
    )
    assert result["outcome"] == "error", f"expected 'error', got {result}"
    assert result["returncode"] is None
    assert result["error"] is not None
    assert "timed out" in result["error"], (
        f"expected 'timed out' in error, got: {result['error']!r}"
    )


# ---------------------------------------------------------------------------
# OSError / non-existent binary
# ---------------------------------------------------------------------------

def test_run_tests_oserror(tmp_path):
    """Non-existent binary -> outcome='error', returncode=None, error non-empty."""
    result = run_tests(
        test_command="nonexistent_binary_xyz_abc some_arg",
        workspace=tmp_path,
    )
    assert result["outcome"] == "error", f"expected 'error', got {result}"
    assert result["returncode"] is None
    assert result["error"] is not None and len(result["error"]) > 0, (
        f"expected non-empty error, got: {result['error']!r}"
    )


# ---------------------------------------------------------------------------
# No tests collected (pytest exit code 5)
# ---------------------------------------------------------------------------

def test_run_tests_no_tests_collected(tmp_path):
    """Empty workspace with no test files -> pytest exits with code 5 -> outcome='fail'.

    pytest exit code 5 means 'no tests were collected'. The executor maps any
    non-zero returncode to 'fail' (not 'error'), so this confirms that behavior.
    """
    # tmp_path is empty; no test files present
    result = run_tests(
        test_command=f"{_PYTEST_CMD} {tmp_path} -q",
        workspace=tmp_path,
    )
    # pytest exits 5 for no-tests-collected; executor maps non-zero -> "fail"
    assert result["outcome"] == "fail", (
        f"expected 'fail' for empty test dir, got {result}"
    )
    assert result["returncode"] == 5


# ---------------------------------------------------------------------------
# stdout_tail truncation
# ---------------------------------------------------------------------------

def test_run_tests_stdout_truncation(tmp_path):
    """Test that prints >2000 chars; stdout_tail must be <= 500 chars."""
    # Generate a test that prints a long string
    long_str = "X" * 3000
    _write_test(tmp_path, "test_loud.py", f"""\
        def test_loud():
            print({long_str!r})
            assert True
    """)
    result = run_tests(
        test_command=f"{_PYTEST_CMD} {tmp_path / 'test_loud.py'} -q -s",
        workspace=tmp_path,
    )
    assert len(result["stdout_tail"]) <= 500, (
        f"stdout_tail exceeds 500 chars: len={len(result['stdout_tail'])}"
    )
