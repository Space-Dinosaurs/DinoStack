#!/usr/bin/env python3
"""
Tests for agentic-help: static help text CLI.

agentic-help prints a fixed HELP_TEXT block to stdout and always exits 0.
No subcommands, no flags.

Run with: python3 bin/tests/test_agentic_help.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from io import StringIO
from pathlib import Path

_BIN_PATH = Path(__file__).parent.parent / "agentic-help"
_loader = importlib.machinery.SourceFileLoader("agentic_help", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_help", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-help from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)


def _capture_main(argv: list[str]) -> tuple[int, str]:
    old_stdout = sys.stdout
    captured = StringIO()
    sys.stdout = captured
    try:
        rc = _mod.main(argv)
    finally:
        sys.stdout = old_stdout
    return rc, captured.getvalue()


def test_exits_zero():
    """main() always returns 0."""
    rc, _ = _capture_main(["agentic-help"])
    assert rc == 0, f"Expected rc=0, got {rc}"
    print("PASS test_exits_zero")


def test_prints_help_text():
    """Output equals the module-level HELP_TEXT constant."""
    rc, out = _capture_main(["agentic-help"])
    assert rc == 0
    assert out == _mod.HELP_TEXT, (
        f"Output does not match HELP_TEXT.\nGot:\n{out}\nExpected:\n{_mod.HELP_TEXT}"
    )
    print("PASS test_prints_help_text")


def test_known_commands_listed():
    """Core slash commands appear in the output."""
    _, out = _capture_main(["agentic-help"])
    for cmd in ("/agentic-status", "/implement-ticket", "/brief", "/agentic-cost"):
        assert cmd in out, f"Expected {cmd!r} in help output"
    print("PASS test_known_commands_listed")


def test_no_args_same_as_any_args():
    """main() ignores argv beyond the first element (no flags)."""
    _, out1 = _capture_main(["agentic-help"])
    _, out2 = _capture_main(["agentic-help", "--ignored", "extra"])
    assert out1 == out2, "Output should be identical regardless of args"
    print("PASS test_no_args_same_as_any_args")


def test_help_text_not_empty():
    """HELP_TEXT constant is non-empty."""
    assert _mod.HELP_TEXT and len(_mod.HELP_TEXT) > 100, "HELP_TEXT should be non-trivial"
    print("PASS test_help_text_not_empty")


if __name__ == "__main__":
    test_exits_zero()
    test_prints_help_text()
    test_known_commands_listed()
    test_no_args_same_as_any_args()
    test_help_text_not_empty()
    print("All agentic-help tests passed.")
