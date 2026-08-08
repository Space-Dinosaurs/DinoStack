#!/usr/bin/env python3
"""
Purpose: Regression coverage for the bin/agentic-* -> bin/ds-* rename
         (24 tools). Confirms (1) every bin/ds-<suffix> real content file is
         present and executable; (2) every bin/agentic-<suffix> compat name
         is a symlink whose PATH-installed alias resolves to the identical
         real file as bin/ds-<suffix> (proven through a real os.symlink, not
         an in-process path comparison alone); (3) a representative safe
         subset of tools produce identical exit codes when invoked through a
         real PATH symlink under the OLD name vs. the NEW name directly; and
         (4) the four python bin/ds-* tools that load bin/_lib.py via
         Path(__file__).resolve().parent (config, feedback, migrate,
         tracker) resolve it correctly when invoked through a real PATH
         symlink installed under their OLD agentic-* name (not just their
         new ds- name, which bin/tests/test_bin_symlink_resolution.py
         already covers).

Public API: python3 -m pytest bin/tests/test_ds_rename_regression.py -q
            Also directly executable: python3 bin/tests/test_ds_rename_regression.py
            Exits 0 on all pass, 1 on any failure (direct-execution mode).

Upstream deps: Python 3 stdlib only (os, subprocess, pathlib, tempfile).
               pytest when run via the pytest entrypoint (optional for the
               direct-execution __main__ path).

Downstream consumers: bin-tests CI job (pytest bin/tests/ -q picks up every
                      test_*.py file automatically).

Failure modes: any assertion failure prints/raises and is counted; the
               direct-execution __main__ path exits 1 if any check fails.

Performance: < 15 s wall time (24 filesystem checks + ~15 subprocess spawns,
             all local, no network).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_BIN = Path(__file__).resolve().parent.parent

# The 24 renamed tools (suffix only). Independently re-derived against
# `ls bin/agentic-*` at review time per the spawn brief - bin/agentic-evidence
# exists but is NOT one of the 24 (pre-existing tool, out of this program's
# scope; flagged separately, not renamed).
SUFFIXES = [
    "base-sync", "calibrate", "codex-dispatch", "codex-session-id", "config",
    "configure", "cost", "disable", "doctor", "emit", "feedback", "help",
    "identity", "memory", "migrate", "models", "parse-subagent-usage",
    "resolve-worktree", "status", "team", "tracker", "update",
    "wrap-acquire-lock", "wrap-release-lock",
]

# The 4 real bin/_lib.py dependents (verified by grep against bin/ds-* at
# authoring time: config, feedback, migrate, tracker). The spawn brief cited
# "five tools" but an independent re-derivation (grep -l "_lib.py" across all
# 24 bin/ds-* files plus bin/agentic-evidence) found exactly 4 - reported as
# a discrepancy rather than silently trusting either count.
LIB_DEPENDENT_SUFFIXES = ["config", "feedback", "migrate", "tracker"]

# Representative safe-invocation subset for the through-symlink behavioral
# check: (suffix, args, stdin_devnull). Chosen so invocation is read-only /
# usage-only under an isolated HOME+CWD - no event writes, no lock files
# left in the real repo, no network. Node lock tools are deliberately
# excluded here (their default arg-less behavior acquires/creates a real
# lock directory) and are covered structurally by the symlink-target-
# identity check (test_all_agentic_names_resolve_to_matching_ds_file)
# instead.
SAFE_INVOCATIONS = [
    ("base-sync", [], False),
    ("calibrate", [], False),
    ("codex-dispatch", [], False),
    ("emit", [], False),
    ("help", [], False),
    ("memory", ["--help"], False),
    ("models", ["--help"], False),
    ("resolve-worktree", [], False),
    ("status", [], False),
]


def _repo_file(suffix: str) -> Path:
    return REPO_BIN / f"ds-{suffix}"


def test_all_24_ds_names_present_and_executable() -> None:
    missing = []
    not_exec = []
    for suffix in SUFFIXES:
        p = _repo_file(suffix)
        if not p.is_file():
            missing.append(str(p))
            continue
        if not os.access(p, os.X_OK):
            not_exec.append(str(p))
    assert not missing, f"missing bin/ds-* files: {missing}"
    assert not not_exec, f"bin/ds-* files not executable: {not_exec}"
    assert len(SUFFIXES) == 24, f"expected 24 renamed tools, list has {len(SUFFIXES)}"


def test_all_agentic_names_resolve_to_matching_ds_file() -> None:
    """Every bin/agentic-<suffix> is a symlink; resolved through a REAL
    os.symlink installed under a fake ~/.local/bin (mirroring how
    install.sh wires PATH), it must resolve to the exact same real file as
    bin/ds-<suffix>."""
    with tempfile.TemporaryDirectory() as tmp:
        fake_local_bin = Path(tmp) / "local-bin"
        fake_local_bin.mkdir()
        for suffix in SUFFIXES:
            old_repo_path = REPO_BIN / f"agentic-{suffix}"
            new_repo_path = REPO_BIN / f"ds-{suffix}"
            assert old_repo_path.is_symlink(), f"bin/agentic-{suffix} is not a symlink"
            assert new_repo_path.is_file(), f"bin/ds-{suffix} missing"

            installed = fake_local_bin / f"agentic-{suffix}"
            os.symlink(old_repo_path.resolve(), installed)

            resolved_old = installed.resolve()
            resolved_new = new_repo_path.resolve()
            assert resolved_old == resolved_new, (
                f"agentic-{suffix} (via PATH symlink) resolves to {resolved_old}, "
                f"expected it to match ds-{suffix} at {resolved_new}"
            )


def _run_through_symlink(tmp_path: Path, suffix: str, args: list[str], stdin_devnull: bool):
    """Invoke bin/agentic-<suffix> through a real PATH symlink under an
    isolated HOME+CWD, and separately invoke bin/ds-<suffix> directly under
    an equally isolated HOME+CWD. Returns (old_result, new_result)."""
    fake_local_bin = tmp_path / "local-bin"
    fake_local_bin.mkdir(exist_ok=True)
    old_repo_path = REPO_BIN / f"agentic-{suffix}"
    symlink_path = fake_local_bin / f"agentic-{suffix}"
    if not symlink_path.exists():
        os.symlink(old_repo_path.resolve(), symlink_path)

    def _invoke(cli_path: Path, home_suffix: str):
        fake_home = tmp_path / home_suffix
        fake_home.mkdir(exist_ok=True)
        env = dict(os.environ)
        env["HOME"] = str(fake_home)
        kwargs = dict(
            args=[str(cli_path), *args],
            env=env,
            cwd=str(fake_home),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if stdin_devnull:
            kwargs["stdin"] = subprocess.DEVNULL
        return subprocess.run(**kwargs)

    old_result = _invoke(symlink_path, "home-old")
    new_result = _invoke(REPO_BIN / f"ds-{suffix}", "home-new")
    return old_result, new_result


def test_representative_tools_behave_identically_through_old_symlink() -> None:
    failures = []
    for suffix, args, stdin_devnull in SAFE_INVOCATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            old_result, new_result = _run_through_symlink(Path(tmp), suffix, args, stdin_devnull)
            if old_result.returncode != new_result.returncode:
                failures.append(
                    f"{suffix}: exit code mismatch old(agentic-{suffix})="
                    f"{old_result.returncode} new(ds-{suffix})={new_result.returncode} "
                    f"old_stderr={old_result.stderr!r} new_stderr={new_result.stderr!r}"
                )
                continue
            for label, result in (("old", old_result), ("new", new_result)):
                for marker in ("_lib.py", "FileNotFoundError", "Traceback"):
                    if marker in result.stderr:
                        failures.append(
                            f"{suffix} ({label}): unexpected '{marker}' in stderr: {result.stderr!r}"
                        )
    assert not failures, "behavioral mismatches:\n" + "\n".join(failures)


def test_lib_py_resolves_through_old_name_symlink_for_all_dependents() -> None:
    """DS-66-class regression, exercised specifically through the OLD
    agentic-* compat name (not just the new ds- name)."""
    failures = []
    for suffix in LIB_DEPENDENT_SUFFIXES:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_local_bin = tmp_path / "local-bin"
            fake_local_bin.mkdir(exist_ok=True)
            old_repo_path = REPO_BIN / f"agentic-{suffix}"
            symlink_path = fake_local_bin / f"agentic-{suffix}"
            os.symlink(old_repo_path.resolve(), symlink_path)

            fake_home = tmp_path / "home"
            fake_home.mkdir(exist_ok=True)
            env = dict(os.environ)
            env["HOME"] = str(fake_home)

            result = subprocess.run(
                [str(symlink_path), "--help"],
                env=env,
                cwd=str(fake_home),
                capture_output=True,
                text=True,
                timeout=30,
            )
            # agentic-config's hand-rolled parser exits 2 on --help (matches
            # test_bin_symlink_resolution.py's documented CASES behavior);
            # the rest are argparse-based and exit 0.
            expected_rc = 2 if suffix == "config" else 0
            if result.returncode != expected_rc:
                failures.append(
                    f"agentic-{suffix} --help via symlink: rc={result.returncode} "
                    f"(expected {expected_rc}) stderr={result.stderr!r}"
                )
            for marker in ("_lib.py", "FileNotFoundError", "Traceback"):
                if marker in result.stderr:
                    failures.append(
                        f"agentic-{suffix} --help via symlink: unexpected '{marker}' "
                        f"in stderr: {result.stderr!r}"
                    )
    assert not failures, "\n".join(failures)


EXTRA_TESTS = [
    test_all_24_ds_names_present_and_executable,
    test_all_agentic_names_resolve_to_matching_ds_file,
    test_representative_tools_behave_identically_through_old_symlink,
    test_lib_py_resolves_through_old_name_symlink_for_all_dependents,
]


if __name__ == "__main__":
    failures = 0
    for t in EXTRA_TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
    if failures:
        sys.exit(1)
    print("All tests passed.")
