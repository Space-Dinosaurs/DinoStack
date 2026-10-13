"""Tests for ds-doctor's check_local_bin_on_path: ~/.local/bin, where the bin
wrappers are linked, must be on PATH or no ds-* command resolves by name.

Every case runs the real `ds-doctor --json` entry point with HOME pointed at a
scratch dir, so the check is exercised as wired into main(), not in isolation.

Run with: python3 -m pytest bin/tests/test_ds_doctor_local_bin_path.py -x
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_BIN = Path(__file__).resolve().parent.parent
_EXPORT_LINE = 'export PATH="$HOME/.local/bin:$PATH"'


def _doctor(tmp_path, on_path, extra_args=()):
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in (
        "AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR")}
    env["HOME"] = str(home)
    path = [p for p in env.get("PATH", "").split(os.pathsep) if p and "/.local/bin" not in p]
    if on_path:
        path.insert(0, str(local_bin))
    env["PATH"] = os.pathsep.join(path)
    r = subprocess.run(
        [sys.executable, str(_BIN / "ds-doctor"), "--json", *extra_args],
        capture_output=True, text=True, env=env, timeout=120,
    )
    payload = json.loads(r.stdout)
    found = [f for f in payload["findings"] if f["message"].startswith("local_bin_path:")]
    assert len(found) == 1, payload["findings"]
    return r.returncode, found[0], local_bin


def test_off_path_warns_with_the_exact_export_line(tmp_path):
    _, finding, local_bin = _doctor(tmp_path, on_path=False)
    assert finding["status"] == "WARN", finding
    assert f"{local_bin} is not on PATH" in finding["message"]
    assert _EXPORT_LINE in finding["message"]
    assert "~/.zshrc for zsh, the macOS default; ~/.bash_profile for bash" in finding["message"]


def test_on_path_is_ok(tmp_path):
    _, finding, local_bin = _doctor(tmp_path, on_path=True)
    assert finding["status"] == "OK", finding
    assert f"{local_bin} is on PATH" in finding["message"]


def test_warn_does_not_change_the_exit_code(tmp_path):
    rc_off, _, _ = _doctor(tmp_path, on_path=False)
    rc_on, _, _ = _doctor(tmp_path, on_path=True)
    assert rc_off == rc_on


def test_fix_does_not_touch_a_shell_profile(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    profile = home / ".zshrc"
    profile.write_text("# operator profile\n")
    _, finding, _ = _doctor(tmp_path, on_path=False, extra_args=("--fix",))
    assert finding["status"] == "WARN", finding
    assert profile.read_text() == "# operator profile\n"
    assert not (home / ".bashrc").exists()
