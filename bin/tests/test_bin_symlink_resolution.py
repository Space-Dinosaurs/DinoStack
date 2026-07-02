#!/usr/bin/env python3
"""
Shared regression guard (DS-66) for the install.sh PATH-symlink invocation
path, across every python CLI in bin/ that resolves a sibling file or
sibling binary (bin/_lib.py, bin/_role_spec.py, or another bin/agentic-*
binary) relative to its own __file__.

install.sh symlinks bin/agentic-* into ~/.local/bin but never symlinks
their sibling dependencies (_lib.py, _role_spec.py, other bin/agentic-*
binaries) alongside them. When Python resolves __file__ for a symlinked
entrypoint it reports the SYMLINK's path, so a bare `Path(__file__).parent`
sibling-file lookup lands in ~/.local/bin/ where the sibling does not
exist - raising FileNotFoundError at import time, before argument parsing
even runs (or, for agentic-configure's --models/team subcommands, at first
use). The fix is `Path(__file__).resolve().parent`, which follows the
symlink back to the real bin/ directory (a no-op when not symlinked).

This must be exercised via a real subprocess THROUGH an os.symlink (not an
in-process import) because the bug only manifests when the OS/interpreter
actually resolves __file__ to a symlink path - in-process importlib loading
never exercises it.

`--help` is used as the invocation because argparse imports the module
(where the sibling-resolution shim runs at module scope) before printing
usage and exiting - exercising the exact bug surface with zero side
effects. Note bin/agentic-config is a hand-rolled parser (not argparse)
that treats `--help` as an unrecognized positional and exits 2 with a
clean usage message - which is fine, since the shim still runs at import
time and still needs to be verified clean of the symlink-resolution bug;
its expected exit code is captured separately below rather than assuming
0 for every CLI.

Run with: python3 -m pytest bin/tests/test_bin_symlink_resolution.py -x
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_BIN = Path(__file__).resolve().parent.parent

# (cli name, args, expected exit code)
# agentic-config has no argparse --help; its hand-rolled parser treats
# --help as an unrecognized positional and exits 2 with a usage message.
# The rest are argparse-based and exit 0 on --help.
CASES = [
    ("agentic-identity", ["--help"], 0),
    ("agentic-migrate", ["--help"], 0),
    ("agentic-config", ["--help"], 2),
    ("agentic-feedback", ["--help"], 0),
    ("agentic-configure", ["--help"], 0),
    ("agentic-team", ["--help"], 0),
]


@pytest.mark.parametrize("cli_name,args,expected_rc", CASES)
def test_cli_runs_through_path_symlink(cli_name: str, args: list[str], expected_rc: int) -> None:
    real_bin_path = REPO_BIN / cli_name
    assert real_bin_path.is_file(), f"expected real CLI at {real_bin_path}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_local_bin = tmp_path / "local-bin"
        fake_local_bin.mkdir()
        symlink_path = fake_local_bin / cli_name
        os.symlink(real_bin_path.resolve(), symlink_path)

        fake_home = tmp_path / "home"
        fake_home.mkdir()

        env = dict(os.environ)
        env["HOME"] = str(fake_home)

        result = subprocess.run(
            [str(symlink_path), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == expected_rc, (
            f"{cli_name} invoked through PATH symlink returned unexpected "
            f"rc={result.returncode} (expected {expected_rc}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "_lib.py" not in result.stderr, (
            f"{cli_name}: _lib.py sibling-resolution failure through symlink: "
            f"stderr={result.stderr!r}"
        )
        assert "FileNotFoundError" not in result.stderr, (
            f"{cli_name}: FileNotFoundError through symlink invocation: "
            f"stderr={result.stderr!r}"
        )
        assert "Traceback" not in result.stderr, (
            f"{cli_name}: unhandled traceback through symlink invocation: "
            f"stderr={result.stderr!r}"
        )


if __name__ == "__main__":
    failures = 0
    for name, args, expected_rc in CASES:
        try:
            test_cli_runs_through_path_symlink(name, args, expected_rc)
            print(f"PASS test_cli_runs_through_path_symlink[{name}]")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL test_cli_runs_through_path_symlink[{name}]: {exc}")
    if failures:
        raise SystemExit(1)
    print("All tests passed.")
