#!/usr/bin/env python3
"""
Tests for ds-defer: repo-scoped deferred-work sink CLI.

Test groups:
  1. test_append_owns_id_ts_status_pattern_hash - append always CLI-assigns
     id/ts/status/pattern_hash regardless of any caller-supplied values (there
     are no --id/--ts/--status flags on append, so nothing to overwrite - this
     asserts the fields are always present and CLI-shaped, never absent or
     caller-controlled).
  2. test_reason_enum_accepts_only_two_values_budget_exceeded_rejected -
     the 2-value enum validation; explicitly asserts budget_exceeded is
     REJECTED as invalid, pinning its deletion from the schema.
  3. test_repo_omission_is_hard_argparse_error_on_all_four_subcommands -
     omitting --repo is a hard argparse error (SystemExit, no cwd fallback)
     on append/list/count/ack.
  4. test_append_bootstraps_bare_repo_agentic_dir_at_mode_0700 - append
     against a repo with no .agentic/ creates it at mode 0o700.
  5. test_list_count_ack_do_not_bootstrap_bare_repo - list/count/ack against
     a bare repo (no .agentic/) do NOT create the directory and return the
     documented absent-store results (list->[], count->0, ack->error).
  6. test_count_status_open_prints_zero_not_error_on_absent_store - count
     --status open on an absent store prints "0" (not an error).
  7. test_lock_serializes_concurrent_append - genuine cross-process
     concurrency via multiprocessing.Process: N workers each append many
     records to the SAME repo store at once; asserts exact expected line
     count and that every line is valid, non-torn JSON.
  8. test_cli_runs_through_path_symlink_resolving_lib - regression guard for
     the install.sh PATH-symlink invocation path: invokes the CLI as a
     subprocess through a symlink and asserts it can still locate and load
     bin/_lib.py rather than raising FileNotFoundError.
  9. test_ack_updates_only_target_status - ack changes only the matching
     line's status; all other fields byte-identical; non-target row
     untouched.
  10. test_repo_is_a_locator_not_cwd_dependent - invoking from a different
      process cwd with --repo pointing elsewhere still resolves the store
      under --repo, not under cwd.

Regression test obligation: content/references/regression-test-obligation.md
Run with: python3 -m pytest bin/tests/test_ds_defer.py -x
       or: python3 bin/tests/test_ds_defer.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# ---------------------------------------------------------------------------
# Load ds-defer as a module (no .py extension)
# ---------------------------------------------------------------------------
_BIN_PATH = Path(__file__).parent.parent / "ds-defer"
_loader = importlib.machinery.SourceFileLoader("ds_defer", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("ds_defer", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for ds-defer from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

main = _mod.main


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Invoke main() capturing stdout/stderr. Returns (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(["ds-defer"] + argv)
    return rc, out.getvalue(), err.getvalue()


def _run_expect_system_exit(argv: list[str]) -> int:
    """Invoke main() expecting argparse to raise SystemExit (missing required
    arg). Returns the exit code. argparse writes its usage error to stderr
    and calls sys.exit(2) - it does not return normally."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            main(["ds-defer"] + argv)
    except SystemExit as exc:
        return exc.code
    raise AssertionError(f"Expected SystemExit for argv={argv}, but main() returned normally")


def _mp_append_worker(bin_path_str: str, repo: str, description: str) -> None:
    """Multiprocessing worker (module-level, picklable): fresh-imports
    bin/ds-defer in THIS process and invokes `append`, then sys.exit()s with
    main()'s return code. Must be module-level for multiprocessing pickling.
    """
    import importlib.machinery as _mp_ilm
    import importlib.util as _mp_ilu
    import sys as _mp_sys

    loader = _mp_ilm.SourceFileLoader("ds_defer_mp_worker", bin_path_str)
    spec = _mp_ilu.spec_from_loader("ds_defer_mp_worker", loader)
    worker_mod = _mp_ilu.module_from_spec(spec)
    loader.exec_module(worker_mod)

    rc = worker_mod.main([
        "ds-defer", "append",
        "--repo", repo, "--description", description,
        "--reason", "failed_promotion_bar",
    ])
    _mp_sys.exit(rc)


def test_append_owns_id_ts_status_pattern_hash():
    """(1) append always CLI-assigns id/ts/status/pattern_hash."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = str(Path(tmp) / "repo")
        Path(repo).mkdir()

        rc, out, err = _run([
            "append", "--repo", repo, "--description", "found a stray script",
            "--reason", "failed_promotion_bar",
        ])
        assert rc == 0, f"Expected exit 0, got {rc}. stderr={err}"

        store = Path(repo, ".agentic", "deferred-work.jsonl")
        lines = [l for l in store.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["status"] == "open"
        assert isinstance(row["id"], str) and len(row["id"]) > 0
        assert row["ts"].endswith("Z")
        assert isinstance(row["pattern_hash"], str) and len(row["pattern_hash"]) == 16

        print("PASS test_append_owns_id_ts_status_pattern_hash")


def test_reason_enum_accepts_only_two_values_budget_exceeded_rejected():
    """(2) 2-value enum validation; budget_exceeded is explicitly REJECTED."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = str(Path(tmp) / "repo")
        Path(repo).mkdir()

        # budget_exceeded must be rejected by argparse's choices= validation.
        rc = _run_expect_system_exit([
            "append", "--repo", repo, "--description", "x",
            "--reason", "budget_exceeded",
        ])
        assert rc != 0, "budget_exceeded must be rejected as an invalid --reason value"

        # Both real values must succeed.
        for reason in ("failed_promotion_bar", "out_of_band_manual_discovery"):
            rc, out, err = _run([
                "append", "--repo", repo, "--description", f"item for {reason}",
                "--reason", reason,
            ])
            assert rc == 0, f"Expected {reason!r} to be accepted, got rc={rc} stderr={err}"

        store = Path(repo, ".agentic", "deferred-work.jsonl")
        lines = [l for l in store.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2
        reasons = {json.loads(l)["reason"] for l in lines}
        assert reasons == {"failed_promotion_bar", "out_of_band_manual_discovery"}
        assert "budget_exceeded" not in reasons

        print("PASS test_reason_enum_accepts_only_two_values_budget_exceeded_rejected")


def test_repo_omission_is_hard_argparse_error_on_all_four_subcommands():
    """(3) omitting --repo is a hard argparse error (SystemExit), no cwd
    fallback, on all four subcommands."""
    cases = [
        ["append", "--description", "x", "--reason", "failed_promotion_bar"],
        ["list"],
        ["count"],
        ["ack", "--id", "some-id"],
    ]
    for argv in cases:
        rc = _run_expect_system_exit(argv)
        assert rc != 0, f"Expected --repo omission to error for {argv}, got rc={rc}"

    print("PASS test_repo_omission_is_hard_argparse_error_on_all_four_subcommands")


def test_append_bootstraps_bare_repo_agentic_dir_at_mode_0700():
    """(4) append against a repo with no .agentic/ creates it at mode 0o700."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = str(Path(tmp) / "bare-repo")
        Path(repo).mkdir()
        agentic_dir = Path(repo, ".agentic")
        assert not agentic_dir.exists(), "precondition: .agentic/ must not exist yet"

        rc, out, err = _run([
            "append", "--repo", repo, "--description", "first item ever",
            "--reason", "failed_promotion_bar",
        ])
        assert rc == 0, f"Expected exit 0, got {rc}. stderr={err}"
        assert agentic_dir.is_dir(), ".agentic/ must be created by append"
        mode = agentic_dir.stat().st_mode & 0o777
        assert mode == 0o700, f"Expected .agentic/ mode 0o700, got {oct(mode)}"

        print("PASS test_append_bootstraps_bare_repo_agentic_dir_at_mode_0700")


def test_list_count_ack_do_not_bootstrap_bare_repo():
    """(5) list/count/ack against a bare repo do NOT create .agentic/ and
    return the documented absent-store results."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = str(Path(tmp) / "bare-repo-2")
        Path(repo).mkdir()
        agentic_dir = Path(repo, ".agentic")

        rc, out, err = _run(["list", "--repo", repo])
        assert rc == 0
        assert json.loads(out) == []
        assert not agentic_dir.exists(), "list must not create .agentic/ on a bare repo"

        rc, out, err = _run(["count", "--repo", repo])
        assert rc == 0
        assert out.strip() == "0"
        assert not agentic_dir.exists(), "count must not create .agentic/ on a bare repo"

        rc, out, err = _run(["ack", "--repo", repo, "--id", "whatever"])
        assert rc == 1, "ack against an absent store must be a hard error"
        assert "no deferred-work store" in err.lower()
        assert not agentic_dir.exists(), "ack must not create .agentic/ on a bare repo"

        print("PASS test_list_count_ack_do_not_bootstrap_bare_repo")


def test_count_status_open_prints_zero_not_error_on_absent_store():
    """(6) count --status open on an absent store prints '0' (not an error)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = str(Path(tmp) / "bare-repo-3")
        Path(repo).mkdir()

        rc, out, err = _run(["count", "--repo", repo, "--status", "open"])
        assert rc == 0, f"Expected exit 0, got {rc}. stderr={err}"
        assert out.strip() == "0"

        print("PASS test_count_status_open_prints_zero_not_error_on_absent_store")


def test_lock_serializes_concurrent_append():
    """(7) genuine concurrency: N multiprocessing.Process workers each
    append many records to the SAME repo store at once. Asserts on COUNT
    and JSON-validity only: (a) exact expected total line count, and
    (b) every line parses as valid JSON (no torn/interleaved half-lines)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = str(Path(tmp) / "concurrent-repo")
        Path(repo).mkdir()

        n_workers = 4
        n_per_worker = 25
        procs = []
        for w in range(n_workers):
            for i in range(n_per_worker):
                p = multiprocessing.Process(
                    target=_mp_append_worker,
                    args=(str(_BIN_PATH), repo, f"worker {w} item {i}"),
                )
                procs.append(p)

        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=90)

        for idx, p in enumerate(procs):
            assert p.exitcode == 0, f"worker {idx} exited with {p.exitcode!r} (expected 0)"

        store = Path(repo, ".agentic", "deferred-work.jsonl")
        assert store.is_file(), "store file must exist after concurrent appends"
        lines = [ln for ln in store.read_text(encoding="utf-8").splitlines() if ln.strip()]

        expected_total = n_workers * n_per_worker
        assert len(lines) == expected_total, (
            f"Expected exactly {expected_total} lines under lock-serialized "
            f"contention, got {len(lines)} (a lost/torn write indicates the "
            f"lock did not serialize the workers)"
        )

        ids = set()
        for line in lines:
            row = json.loads(line)
            ids.add(row["id"])
        assert len(ids) == expected_total, (
            "every appended item must get a distinct id (no duplicate/corrupted rows)"
        )

        print("PASS test_lock_serializes_concurrent_append")


def test_cli_runs_through_path_symlink_resolving_lib():
    """(8) Regression guard for the install.sh PATH-symlink invocation path.

    install.sh symlinks ~/.local/bin/ds-defer -> repo bin/ds-defer but never
    symlinks _lib.py alongside it. When Python resolves __file__ for a
    symlinked entrypoint it reports the SYMLINK's path, so a bare
    `Path(__file__).parent` lands in ~/.local/bin/ where _lib.py does not
    exist. Must invoke via a real subprocess THROUGH the symlink (not an
    in-process import) because the bug only manifests when the OS/
    interpreter actually resolves __file__ to a symlink path.
    """
    real_bin_path = Path(__file__).parent.parent / "ds-defer"
    assert real_bin_path.is_file(), f"expected real CLI at {real_bin_path}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_local_bin = tmp_path / "local-bin"
        fake_local_bin.mkdir()
        symlink_path = fake_local_bin / "ds-defer"
        os.symlink(real_bin_path.resolve(), symlink_path)

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        repo = tmp_path / "repo"
        repo.mkdir()

        env = dict(os.environ)
        env["HOME"] = str(fake_home)

        result = subprocess.run(
            [str(symlink_path), "list", "--repo", str(repo)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"CLI invoked through PATH symlink failed (rc={result.returncode}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert json.loads(result.stdout.strip()) == []
        assert "FileNotFoundError" not in result.stderr

        print("PASS test_cli_runs_through_path_symlink_resolving_lib")


def test_ack_updates_only_target_status():
    """(9) ack changes only the matching line's status; all else
    byte-identical; non-target row untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = str(Path(tmp) / "repo")
        Path(repo).mkdir()

        rc, _, _ = _run([
            "append", "--repo", repo, "--description", "item A",
            "--reason", "failed_promotion_bar",
        ])
        assert rc == 0
        rc, _, _ = _run([
            "append", "--repo", repo, "--description", "item B",
            "--reason", "out_of_band_manual_discovery",
        ])
        assert rc == 0

        store = Path(repo, ".agentic", "deferred-work.jsonl")
        before_lines = [json.loads(l) for l in store.read_text(encoding="utf-8").splitlines() if l.strip()]
        target = next(r for r in before_lines if r["description"] == "item A")
        other = next(r for r in before_lines if r["description"] == "item B")

        rc, out, err = _run(["ack", "--repo", repo, "--id", target["id"]])
        assert rc == 0, err

        after_lines = [json.loads(l) for l in store.read_text(encoding="utf-8").splitlines() if l.strip()]
        after_target = next(r for r in after_lines if r["id"] == target["id"])
        after_other = next(r for r in after_lines if r["id"] == other["id"])

        assert after_target["status"] == "acknowledged"
        for key in target:
            if key == "status":
                continue
            assert after_target[key] == target[key], f"field {key!r} changed unexpectedly"

        assert after_other == other, "non-target row must be byte-identical"

        # ack on an already-unknown id fails cleanly.
        rc, out, err = _run(["ack", "--repo", repo, "--id", "not-a-real-id"])
        assert rc == 1
        assert "no deferred-work item" in err.lower()

        print("PASS test_ack_updates_only_target_status")


def test_repo_is_a_locator_not_cwd_dependent():
    """(10) --repo resolves the store regardless of process cwd; a second
    repo (never passed as --repo) is untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        repo_a = str(Path(tmp) / "repo-a")
        repo_b = str(Path(tmp) / "repo-b")
        Path(repo_a).mkdir()
        Path(repo_b).mkdir()

        cwd_before = os.getcwd()
        try:
            os.chdir(repo_b)  # cwd is repo_b, but --repo targets repo_a
            rc, out, err = _run([
                "append", "--repo", repo_a, "--description", "targets repo-a",
                "--reason", "failed_promotion_bar",
            ])
            assert rc == 0, err
        finally:
            os.chdir(cwd_before)

        assert Path(repo_a, ".agentic", "deferred-work.jsonl").is_file(), (
            "store must land under --repo, not under cwd"
        )
        assert not Path(repo_b, ".agentic").exists(), (
            "cwd (repo-b) must be untouched - store location must not depend on cwd"
        )

        print("PASS test_repo_is_a_locator_not_cwd_dependent")


if __name__ == "__main__":
    test_append_owns_id_ts_status_pattern_hash()
    test_reason_enum_accepts_only_two_values_budget_exceeded_rejected()
    test_repo_omission_is_hard_argparse_error_on_all_four_subcommands()
    test_append_bootstraps_bare_repo_agentic_dir_at_mode_0700()
    test_list_count_ack_do_not_bootstrap_bare_repo()
    test_count_status_open_prints_zero_not_error_on_absent_store()
    test_lock_serializes_concurrent_append()
    test_cli_runs_through_path_symlink_resolving_lib()
    test_ack_updates_only_target_status()
    test_repo_is_a_locator_not_cwd_dependent()
    print("All tests passed.")
