"""Tests for ds-doctor's check_claude_version (Claude Code CLI version floor).

Each test puts a stub `claude` executable on an otherwise-empty PATH, so the
real CLI is never consulted and the result does not depend on the host.

Run with: python3 -m pytest bin/tests/test_ds_doctor_claude_version.py -x
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import stat
from pathlib import Path

import pytest

_BIN = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("_ds_doctor_cv", str(_BIN / "ds-doctor"))
_spec = importlib.util.spec_from_loader("_ds_doctor_cv", _loader)
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)


def _run(monkeypatch, tmp_path, script=None, fix=False):
    stub_dir = tmp_path / "stubbin"
    stub_dir.mkdir()
    if script is not None:
        stub = stub_dir / "claude"
        stub.write_text("#!/bin/sh\n" + script + "\n")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", str(stub_dir))
    doc = _mod.Doctor(repo_dir=tmp_path, fix=fix, json_mode=True)
    _mod.check_claude_version(doc)
    found = [(s, m) for s, m in doc.findings if m.startswith("claude_version:")]
    assert len(found) == 1, found
    return doc, found[0]


@pytest.mark.parametrize("version", ["2.1.280", "2.1.286", "1.9.999", "2.0.400"])
def test_below_floor_warns(monkeypatch, tmp_path, version):
    doc, (status, msg) = _run(monkeypatch, tmp_path, f'echo "{version} (Claude Code)"')
    assert status == "WARN", msg
    assert version in msg and "2.1.287" in msg
    assert "claude update" in msg
    assert "conservative floor" in msg
    assert not doc.has_unresolved_findings()


def test_below_floor_fix_mode_stays_nonblocking(monkeypatch, tmp_path):
    doc, (status, msg) = _run(monkeypatch, tmp_path, 'echo "2.1.280 (Claude Code)"', fix=True)
    assert status == "WARN", msg
    assert not doc.has_unfixable()
    assert not doc.has_unresolved_findings()


def test_at_floor_ok(monkeypatch, tmp_path):
    _, (status, msg) = _run(monkeypatch, tmp_path, 'echo "2.1.287 (Claude Code)"')
    assert status == "OK", msg


@pytest.mark.parametrize("version", ["2.1.288", "2.2.0", "2.1.1000", "3.0.0", "10.0.0"])
def test_above_floor_ok(monkeypatch, tmp_path, version):
    _, (status, msg) = _run(monkeypatch, tmp_path, f'echo "{version} (Claude Code)"')
    assert status == "OK", msg
    assert version in msg


def test_missing_binary_skips(monkeypatch, tmp_path):
    _, (status, msg) = _run(monkeypatch, tmp_path, script=None)
    assert status == "SKIP", msg
    assert "not on PATH" in msg


def test_garbage_output_skips(monkeypatch, tmp_path):
    _, (status, msg) = _run(monkeypatch, tmp_path, 'echo "Claude Code (dev build)"')
    assert status == "SKIP", msg
    assert "unparseable" in msg


def test_nonzero_exit_skips(monkeypatch, tmp_path):
    _, (status, msg) = _run(monkeypatch, tmp_path, 'echo "2.1.280 (Claude Code)"; exit 3')
    assert status == "SKIP", msg
    assert "exited 3" in msg


def test_timeout_skips(monkeypatch, tmp_path):
    monkeypatch.setattr(_mod, "_CLAUDE_VERSION_TIMEOUT_S", 0.5)
    _, (status, msg) = _run(monkeypatch, tmp_path, 'exec /bin/sleep 5')
    assert status == "SKIP", msg
    assert "TimeoutExpired" in msg


def test_wired_into_main():
    src = (_BIN / "ds-doctor").read_text()
    main_body = src[src.index("def main() -> int:"):]
    assert "check_claude_version(doc)" in main_body
