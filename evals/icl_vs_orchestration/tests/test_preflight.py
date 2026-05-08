"""Tests for CLI preflight binary checks - QA scenario 12."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_preflight_exits_4_when_python3_missing(tmp_path, monkeypatch):
    """cli.py _preflight() exits 4 with message naming the missing binary."""
    import os

    # Monkeypatch shutil.which to simulate bun present but python3 absent
    original_which = shutil.which

    def fake_which(name):
        if name == "python3":
            return None  # simulate missing
        return original_which(name)

    # We test the _preflight function directly to avoid PATH manipulation
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cli_test",
        Path("evals/icl_vs_orchestration/cli.py"),
    )
    # Test via module-level import
    from unittest.mock import patch
    import evals.icl_vs_orchestration.cli as cli_module

    captured_exits = []
    captured_stderr = []

    def mock_exit(code):
        captured_exits.append(code)
        raise SystemExit(code)

    with patch("shutil.which") as mock_which:
        mock_which.side_effect = lambda name: None if name == "python3" else "/usr/bin/bun"
        with patch("sys.exit", side_effect=mock_exit):
            with pytest.raises(SystemExit) as exc:
                cli_module._preflight()
    assert exc.value.code == 4


def test_preflight_passes_when_both_present(monkeypatch):
    """_preflight() does not exit when both python3 and bun are on PATH."""
    from unittest.mock import patch
    import evals.icl_vs_orchestration.cli as cli_module

    with patch("shutil.which") as mock_which:
        mock_which.side_effect = lambda name: f"/usr/bin/{name}"
        # Should not raise or exit
        cli_module._preflight()


def test_preflight_exits_4_when_bun_missing(monkeypatch):
    """_preflight() exits 4 when bun is missing from PATH."""
    from unittest.mock import patch
    import evals.icl_vs_orchestration.cli as cli_module

    def mock_exit(code):
        raise SystemExit(code)

    with patch("shutil.which") as mock_which:
        mock_which.side_effect = lambda name: None if name == "bun" else "/usr/bin/python3"
        with patch("sys.exit", side_effect=mock_exit):
            with pytest.raises(SystemExit) as exc:
                cli_module._preflight()
    assert exc.value.code == 4
