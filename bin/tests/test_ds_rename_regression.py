#!/usr/bin/env python3
"""
Purpose: Regression coverage for the bin/agentic-* -> bin/ds-* rename
         (25 tools: the original 24 plus bin/agentic-evidence, renamed to
         bin/ds-evidence in a follow-up gap-close pass after a concurrent
         session added it mid-rename). This 25-tool count (SUFFIXES below)
         is FIXED to that historical rename batch and is deliberately NOT
         kept in sync with every tool added to bin/ds-* afterward (e.g.
         bin/ds-defer, added directly as a ds-* tool with no prior
         agentic-* name to rename FROM) - see item (5) below for the
         count-driven sweep that catches those independently of this list.
         Do not conflate this 25 with `ls bin/ds-*`'s live, growing total.
         Confirms (1) every bin/ds-<suffix>
         real content file is present and executable; (2) every
         bin/agentic-<suffix> compat name is a symlink whose PATH-installed
         alias resolves to the identical real file as bin/ds-<suffix>
         (proven through a real os.symlink, not an in-process path
         comparison alone); (3) a representative safe subset of tools
         produce identical exit codes when invoked through a real PATH
         symlink under the OLD name vs. the NEW name directly; (4) the four
         python bin/ds-* tools that load bin/_lib.py via
         Path(__file__).resolve().parent (config, feedback, migrate,
         tracker) resolve it correctly when invoked through a real PATH
         symlink installed under their OLD agentic-* name (not just their
         new ds- name, which bin/tests/test_bin_symlink_resolution.py
         already covers); and (5) a COUNT-DRIVEN sweep - independent of the
         SUFFIXES list below - that enumerates every real bin/ds-* file on
         disk and asserts each has a working bin/agentic-* alias, so a
         future added tool that is renamed without updating SUFFIXES (or
         whose alias is simply missing) is still caught; (6) every
         bin/agentic-* alias resolves to an existing target (orphan-alias
         direction); and (7) every bin/ds-* path entry, symlink or not,
         resolves to an existing file (dangling-ds-symlink direction) -
         (6) and (7) close the one-direction gap in (5), which only ever
         walked from a real, non-symlink bin/ds-* file.

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

Performance: < 15 s wall time (25 filesystem checks + ~16 subprocess spawns,
             all local, no network).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_BIN = Path(__file__).resolve().parent.parent

# The 25 renamed tools (suffix only): the original 24 plus "evidence",
# renamed to bin/ds-evidence in a follow-up gap-close pass. Independently
# re-derived against `ls bin/agentic-*` at review time.
SUFFIXES = [
    "base-sync", "calibrate", "codex-dispatch", "codex-session-id", "config",
    "configure", "cost", "disable", "doctor", "emit", "evidence", "feedback",
    "help", "identity", "memory", "migrate", "models",
    "parse-subagent-usage", "resolve-worktree", "status", "team", "tracker",
    "update", "wrap-acquire-lock", "wrap-release-lock",
]

# The 5 real bin/_lib.py dependents (verified by grep against all 26
# bin/ds-* files currently on disk - a live count, NOT the fixed 25-entry
# SUFFIXES rename batch above; bin/ds-defer was added directly as a ds-*
# tool after the rename event and was never itself renamed, so it is
# intentionally absent from SUFFIXES but IS a genuine _lib.py dependent):
# config, defer, feedback, migrate, tracker. bin/ds-evidence is explicitly
# self-contained (imports no sibling module, per its own module manifest)
# and is NOT in this list.
LIB_DEPENDENT_SUFFIXES = ["config", "defer", "feedback", "migrate", "tracker"]

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
    ("evidence", ["--help"], False),
    ("help", [], False),
    ("memory", ["--help"], False),
    ("models", ["--help"], False),
    ("resolve-worktree", [], False),
    ("status", [], False),
]


def _repo_file(suffix: str) -> Path:
    return REPO_BIN / f"ds-{suffix}"


def test_all_25_ds_names_present_and_executable() -> None:
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
    assert len(SUFFIXES) == 25, f"expected 25 renamed tools, list has {len(SUFFIXES)}"


def test_every_ds_star_file_on_disk_has_a_working_agentic_alias() -> None:
    """Count-driven, list-independent: enumerate every real bin/ds-* file
    actually on disk (not the hardcoded SUFFIXES list above) and assert each
    has a bin/agentic-<suffix> symlink alias that resolves to it through a
    real PATH-installed symlink. Catches the next tool added to bin/ds-*
    whose compat alias is missing or whose SUFFIXES entry was forgotten -
    exactly the class of gap that left bin/agentic-evidence un-renamed for
    one review cycle in this program."""
    ds_files = sorted(
        p for p in REPO_BIN.iterdir()
        if p.is_file() and not p.is_symlink() and p.name.startswith("ds-")
    )
    assert ds_files, "no bin/ds-* files found on disk - unexpected"

    missing_alias = []
    broken_alias = []
    with tempfile.TemporaryDirectory() as tmp:
        fake_local_bin = Path(tmp) / "local-bin"
        fake_local_bin.mkdir()
        for ds_file in ds_files:
            suffix = ds_file.name[len("ds-"):]
            alias_path = REPO_BIN / f"agentic-{suffix}"
            if not alias_path.is_symlink():
                missing_alias.append(alias_path.name)
                continue
            installed = fake_local_bin / f"agentic-{suffix}"
            os.symlink(alias_path.resolve(), installed)
            if installed.resolve() != ds_file.resolve():
                broken_alias.append(
                    f"agentic-{suffix} resolves to {installed.resolve()}, "
                    f"expected {ds_file.resolve()}"
                )
    assert not missing_alias, f"bin/ds-* files with no bin/agentic-* alias: {missing_alias}"
    assert not broken_alias, "aliases resolving to the wrong file:\n" + "\n".join(broken_alias)


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


def test_no_orphan_agentic_alias_without_ds_target() -> None:
    """MINOR 1, direction 1: every bin/agentic-* symlink on disk must resolve
    to an EXISTING file. test_every_ds_star_file_on_disk_has_a_working_
    agentic_alias only walks ds-* -> agentic-* (and only counts real,
    non-symlink ds-* files); it never notices an orphan bin/agentic-zzz
    symlink whose ds-zzz target does not exist (e.g. the ds-* file was
    renamed again or deleted but the old-name alias was never updated or
    removed). This walks the OTHER direction: every bin/agentic-* symlink,
    regardless of whether a matching ds-* file exists."""
    agentic_symlinks = sorted(
        p for p in REPO_BIN.iterdir()
        if p.is_symlink() and p.name.startswith("agentic-")
    )
    assert agentic_symlinks, "no bin/agentic-* symlinks found on disk - unexpected"

    orphans = [p.name for p in agentic_symlinks if not p.resolve().is_file()]
    assert not orphans, f"bin/agentic-* aliases pointing at a nonexistent target: {orphans}"


def test_no_dangling_ds_star_symlink() -> None:
    """MINOR 1, direction 2: every bin/ds-* PATH ENTRY (real file OR
    symlink) must resolve to an existing file.
    test_every_ds_star_file_on_disk_has_a_working_agentic_alias filters its
    walk to `p.is_file() and not p.is_symlink()`, so a bin/ds-zzz that is
    ITSELF a dangling symlink (e.g. accidentally created pointing at a typo'd
    or removed path) is excluded from that walk entirely and never
    inspected by any existing test. This test enumerates every bin/ds-*
    entry unconditionally and asserts none is a broken symlink."""
    ds_entries = sorted(
        p for p in REPO_BIN.iterdir()
        if p.name.startswith("ds-") and (p.is_file() or p.is_symlink())
    )
    assert ds_entries, "no bin/ds-* entries found on disk - unexpected"

    dangling = [p.name for p in ds_entries if p.is_symlink() and not p.resolve().is_file()]
    assert not dangling, f"bin/ds-* entries that are dangling symlinks: {dangling}"


EXTRA_TESTS = [
    test_all_25_ds_names_present_and_executable,
    test_all_agentic_names_resolve_to_matching_ds_file,
    test_every_ds_star_file_on_disk_has_a_working_agentic_alias,
    test_representative_tools_behave_identically_through_old_symlink,
    test_lib_py_resolves_through_old_name_symlink_for_all_dependents,
    test_no_orphan_agentic_alias_without_ds_target,
    test_no_dangling_ds_star_symlink,
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
