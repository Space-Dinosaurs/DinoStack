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
    ("agentic-defer", ["--help"], 0),
    ("agentic-feedback", ["--help"], 0),
    ("agentic-configure", ["--help"], 0),
    ("agentic-team", ["--help"], 0),
    ("agentic-tracker", ["--help"], 0),
    ("agentic-branch-prune", ["--help"], 0),
    ("agentic-learning-shard", ["--help"], 0),
]

# Completeness backstop: every bin/agentic-* python CLI that carries the
# `_lib.py` sibling-resolution shim (the DS-66 bug surface) MUST appear in
# CASES above - a hardcoded list with no completeness check is exactly how
# agentic-tracker escaped this guard for one review round. This scan is
# narrower than the full class docstring (which also covers CLIs that
# resolve a sibling BINARY, e.g. agentic-configure -> agentic-team, already
# covered by their own entries/EXTRA_TESTS below) - it only catches the
# mechanically detectable `_lib.py` import shim.
#
# Matched bare (no surrounding quote), NOT '"_lib.py"' - a quoted marker is
# quote-style-sensitive (`parent / "_lib.py"` matches, `parent / '_lib.py'`
# does not), which lets a single-quoted import escape this exact backstop.
# A bare match risks one class of false positive (a prose mention of
# _lib.py with no actual import), which only costs a harmless CASES entry -
# the asymmetric-cost direction this backstop must fail toward, since the
# false-negative direction is precisely what it exists to prevent.
_LIB_SHIM_MARKER = "_lib.py"


def _bin_agentic_clis_with_lib_shim() -> set[str]:
    names = set()
    for path in REPO_BIN.glob("agentic-*"):
        if not path.is_file() or path.suffix:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _LIB_SHIM_MARKER in text:
            names.add(path.name)
    return names


def test_every_lib_shim_cli_is_covered_by_cases() -> None:
    covered = {name for name, _args, _rc in CASES}
    shimmed = _bin_agentic_clis_with_lib_shim()
    missing = shimmed - covered
    assert not missing, (
        f"bin/agentic-* CLIs carrying the _lib.py sibling-resolution shim "
        f"but missing from CASES: {sorted(missing)} - add a CASES entry so "
        f"the symlink-resolution regression guard actually covers them"
    )


def _symlinked_cli(tmp_path: Path, cli_name: str) -> tuple[Path, dict]:
    """Create a real os.symlink to bin/<cli_name> under an isolated fake
    ~/.local/bin, plus an isolated-HOME env dict - the shared setup for
    every through-symlink invocation in this module (mirrors how
    install.sh links bin/agentic-* into ~/.local/bin)."""
    real_bin_path = REPO_BIN / cli_name
    assert real_bin_path.is_file(), f"expected real CLI at {real_bin_path}"

    fake_local_bin = tmp_path / "local-bin"
    fake_local_bin.mkdir(exist_ok=True)
    symlink_path = fake_local_bin / cli_name
    if not symlink_path.exists():
        os.symlink(real_bin_path.resolve(), symlink_path)

    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)

    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    return symlink_path, env


@pytest.mark.parametrize("cli_name,args,expected_rc", CASES)
def test_cli_runs_through_path_symlink(cli_name: str, args: list[str], expected_rc: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        symlink_path, env = _symlinked_cli(Path(tmp), cli_name)

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


def test_agentic_configure_models_symlink_resolves_agentic_models() -> None:
    """Regression for DS-66 line ~134 (agentic-configure._models_suggestions).

    `--help` alone gives this site NO teeth: _models_suggestions is only
    reached when --models is supplied, and its failure mode is SILENT -
    `if not agentic_models.is_file(): return {}` - so a broken sibling
    resolution does not raise, error, or change the exit code. It just
    makes the CLI quietly ignore the requested --models ranking and fall
    back to the hardcoded 'sonnet' default for every role. Asserting
    exit 0 alone cannot distinguish "resolved the sibling and ranked
    opus" from "silently failed to resolve it and fell back to sonnet" -
    both exit 0. Instead assert the concrete positive signal: with
    --models opus, the skeptic role must resolve to 'opus' (verified
    against the unbroken CLI - see class docstring); if it silently
    falls back it resolves to the 'sonnet' default instead.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        symlink_path, env = _symlinked_cli(tmp_path, "agentic-configure")
        output_path = tmp_path / "role-models.yml"

        result = subprocess.run(
            [str(symlink_path), "--non-interactive", "--models", "opus", "--path", str(output_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"agentic-configure --models through symlink failed: rc={result.returncode} "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert output_path.is_file(), f"expected {output_path} to be written"
        text = output_path.read_text()
        assert "skeptic: opus" in text, (
            "agentic-configure --models opus invoked through a PATH symlink silently "
            "fell back to the sonnet default (sibling agentic-models binary not "
            f"resolved) instead of ranking the requested model. Written YAML:\n{text}"
        )


def test_agentic_configure_team_symlink_resolves_agentic_team() -> None:
    """Regression for DS-66 line ~201 (agentic-configure._cmd_team).

    `--help` alone gives this site NO teeth: the `team` subcommand
    dispatch (and its sibling agentic-team resolution) is only reached
    via `agentic-configure team ...`. Unlike the --models case this
    failure is NOT silent - a broken sibling resolution prints
    "agentic-team binary not found" and exits 2 - but it is still a full
    functional break of the team subcommand through a symlinked install
    that a --help-only probe cannot catch. Assert successful delegation:
    exit 0 and team.yml written with the assigned harness/model (mirrors
    bin/tests/test_agentic_configure.py::test_configure_team_shim_delegates_to_agentic_team).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        symlink_path, env = _symlinked_cli(tmp_path, "agentic-configure")
        output_path = tmp_path / "team.yml"

        result = subprocess.run(
            [
                str(symlink_path), "team", "--non-interactive",
                "--assign", "engineer=codex:gpt-5", "--path", str(output_path),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"agentic-configure team through symlink failed: rc={result.returncode} "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "agentic-team binary not found" not in result.stderr, (
            f"agentic-configure team: sibling agentic-team resolution failed through "
            f"symlink: stderr={result.stderr!r}"
        )
        assert output_path.is_file(), f"expected {output_path} to be written"
        text = output_path.read_text()
        assert "harness: codex" in text and "model: gpt-5" in text, (
            f"team.yml missing expected assignment; got:\n{text}"
        )


EXTRA_TESTS = [
    test_agentic_configure_models_symlink_resolves_agentic_models,
    test_agentic_configure_team_symlink_resolves_agentic_team,
    test_every_lib_shim_cli_is_covered_by_cases,
]


if __name__ == "__main__":
    failures = 0
    for name, args, expected_rc in CASES:
        try:
            test_cli_runs_through_path_symlink(name, args, expected_rc)
            print(f"PASS test_cli_runs_through_path_symlink[{name}]")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL test_cli_runs_through_path_symlink[{name}]: {exc}")
    for t in EXTRA_TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
    if failures:
        raise SystemExit(1)
    print("All tests passed.")
