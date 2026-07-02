#!/usr/bin/env python3
"""
Tests for agentic-feedback: home-dir feedback store CLI.

Test groups:
  1. test_append_valid_and_invalid_mixed - append writes valid items and
     skips invalid ones (count + stderr warning).
  2. test_append_overwrites_caller_supplied_id_ts_status - a draft that tries
     to supply id/ts/status is ignored; the CLI-assigned values win (m4).
  3. test_append_empty_array_is_clean_noop - empty --file array is a no-op
     (exit 0, store file untouched/absent).
  4. test_list_filters_by_scope_and_status - list applies --scope/--status
     filters correctly.
  5. test_list_missing_file_returns_empty_array - list on an absent store
     prints "[]" and returns 0.
  6. test_mark_updates_only_target_status - mark changes only the matching
     line's status; all other fields byte-identical.
  7. test_mark_unknown_id_exits_1_and_leaves_file_unchanged - mark on an
     unknown --id exits 1 and does not modify the store.
  8. test_two_sequential_appends_both_land_under_shared_lock - two
     sequential append calls (simulating two projects' /wrap runs) both
     land intact; final file is the union of valid items, one line each.
  9. test_concurrent_appends_serialize_under_real_multiprocess_contention -
     genuine cross-process concurrency via multiprocessing.Process: N
     workers each append many records to the SAME store at once; asserts
     exact expected line count and that every line is valid, non-torn
     JSON, proving the fcntl lock actually serializes writers (a version
     with the lock removed would drop and/or interleave lines).
  10. test_mark_warns_on_malformed_line_and_drops_it - mark's rewrite
      prints a stderr warning naming the line number of a malformed line
      it drops (visibility for a destructive silent skip).
  11. test_cli_runs_through_path_symlink_resolving_lib - regression guard
      for the install.sh PATH-symlink invocation path: invokes the CLI as
      a subprocess through a symlink (mimicking ~/.local/bin/agentic-feedback
      -> repo bin/agentic-feedback) and asserts it can still locate and
      load bin/_lib.py rather than raising FileNotFoundError.

Regression test obligation: content/references/regression-test-obligation.md
Run with: python3 -m pytest bin/tests/test_agentic_feedback.py -x
       or: python3 bin/tests/test_agentic_feedback.py
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
# Load agentic-feedback as a module (no .py extension)
# ---------------------------------------------------------------------------
_BIN_PATH = Path(__file__).parent.parent / "agentic-feedback"
_loader = importlib.machinery.SourceFileLoader("agentic_feedback", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_feedback", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-feedback from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

main = _mod.main


def _mp_append_worker(
    bin_path_str: str,
    feedback_path_str: str,
    lock_path_str: str,
    repo: str,
    session_uuid: str,
    batch_path_str: str,
) -> None:
    """Multiprocessing worker (module-level, picklable): fresh-imports
    bin/agentic-feedback in THIS process and patches FEEDBACK_PATH/LOCK_PATH
    before invoking `append`, then sys.exit()s with main()'s return code.

    Must be defined at module level (not a closure/lambda) so
    multiprocessing can pickle a reference to it for the child process.
    Each worker re-imports the CLI module and re-sets FEEDBACK_PATH/
    LOCK_PATH itself, because a multiprocessing worker does not inherit the
    parent test process's monkeypatched module globals (the child gets its
    own copy of the module either way - via re-import under 'spawn' or
    copy-on-write under 'fork' - so re-setting explicitly here is what
    makes the worker point at the shared tmp-dir store regardless of which
    start method the platform uses).
    """
    import importlib.machinery as _mp_ilm
    import importlib.util as _mp_ilu
    import sys as _mp_sys
    from pathlib import Path as _MpPath

    loader = _mp_ilm.SourceFileLoader("agentic_feedback_mp_worker", bin_path_str)
    spec = _mp_ilu.spec_from_loader("agentic_feedback_mp_worker", loader)
    worker_mod = _mp_ilu.module_from_spec(spec)
    loader.exec_module(worker_mod)

    worker_mod.FEEDBACK_PATH = _MpPath(feedback_path_str)
    worker_mod.LOCK_PATH = _MpPath(lock_path_str)

    rc = worker_mod.main([
        "agentic-feedback", "append",
        "--repo", repo, "--session-uuid", session_uuid, "--file", batch_path_str,
    ])
    _mp_sys.exit(rc)


def _patch_paths(tmp_path: Path):
    """Patch module-level FEEDBACK_PATH/LOCK_PATH to a per-test tmp dir.

    Returns (feedback_path, lock_path). Never touches the developer's real
    ~/.agentic/feedback.jsonl.
    """
    feedback_path = tmp_path / "feedback.jsonl"
    lock_path = tmp_path / "feedback.jsonl.lock"
    _mod.FEEDBACK_PATH = feedback_path
    _mod.LOCK_PATH = lock_path
    return feedback_path, lock_path


def _write_batch(tmp_path: Path, drafts: list) -> Path:
    batch_path = tmp_path / "batch.json"
    batch_path.write_text(json.dumps(drafts), encoding="utf-8")
    return batch_path


def _run(argv: list[str]) -> tuple[int, str, str]:
    """Invoke main() capturing stdout/stderr. Returns (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(["agentic-feedback"] + argv)
    return rc, out.getvalue(), err.getvalue()


VALID_DRAFT = {
    "scope": "project",
    "severity": "medium",
    "category": "tool-friction",
    "evidence": "curl failed in sandbox 3 times",
    "suggested_title": "curl blocked in sandbox",
    "suggested_body": "sandbox blocks curl; use ctx_execute instead",
}


def test_append_valid_and_invalid_mixed():
    """(1) append writes valid items and skips invalid ones."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        feedback_path, _ = _patch_paths(tmp_path)

        drafts = [
            dict(VALID_DRAFT),
            {"scope": "bogus-scope", "severity": "medium", "category": "tool-friction",
             "evidence": "x", "suggested_title": "y", "suggested_body": "z"},
            {"scope": "project", "severity": "medium", "category": "tool-friction",
             "evidence": "", "suggested_title": "y", "suggested_body": "z"},
        ]
        batch_path = _write_batch(tmp_path, drafts)

        rc, out, err = _run([
            "append", "--repo", "/repo/x", "--session-uuid", "s1", "--file", str(batch_path),
        ])
        assert rc == 0, f"Expected exit 0, got {rc}. stderr={err}"
        assert "Appended 1" in out, f"Expected 1 appended, got: {out}"
        assert "skipping draft" in err, f"Expected skip warnings on stderr, got: {err}"

        lines = [l for l in feedback_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1, f"Expected 1 line written, got {len(lines)}"

        print("PASS test_append_valid_and_invalid_mixed")


def test_append_overwrites_caller_supplied_id_ts_status():
    """(2) [m4] id/ts/status in a draft are ignored; CLI-assigned values win."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        feedback_path, _ = _patch_paths(tmp_path)

        malicious_draft = dict(VALID_DRAFT)
        malicious_draft["id"] = "attacker-supplied-id"
        malicious_draft["ts"] = "1999-01-01T00:00:00Z"
        malicious_draft["status"] = "dismissed"
        batch_path = _write_batch(tmp_path, [malicious_draft])

        rc, out, err = _run([
            "append", "--repo", "/repo/x", "--session-uuid", "s1", "--file", str(batch_path),
        ])
        assert rc == 0, f"Expected exit 0, got {rc}. stderr={err}"

        lines = [l for l in feedback_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["id"] != "attacker-supplied-id", "id must be CLI-assigned, not caller-supplied"
        assert row["ts"] != "1999-01-01T00:00:00Z", "ts must be CLI-assigned, not caller-supplied"
        assert row["status"] == "open", f"status must always be 'open' on append, got {row['status']!r}"

        print("PASS test_append_overwrites_caller_supplied_id_ts_status")


def test_append_empty_array_is_clean_noop():
    """(3) empty-array append is a clean no-op (exit 0, no file corruption)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        feedback_path, _ = _patch_paths(tmp_path)

        batch_path = _write_batch(tmp_path, [])

        rc, out, err = _run([
            "append", "--repo", "/repo/x", "--session-uuid", "s1", "--file", str(batch_path),
        ])
        assert rc == 0, f"Expected exit 0 on empty batch, got {rc}. stderr={err}"
        assert not feedback_path.exists(), "Empty batch must not create the store file"

        print("PASS test_append_empty_array_is_clean_noop")


def test_list_filters_by_scope_and_status():
    """(4) list filters by --scope and --status."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _patch_paths(tmp_path)

        drafts = [
            dict(VALID_DRAFT, scope="project", severity="high"),
            dict(VALID_DRAFT, scope="methodology", severity="low"),
        ]
        batch_path = _write_batch(tmp_path, drafts)
        rc, _, _ = _run([
            "append", "--repo", "/repo/x", "--session-uuid", "s1", "--file", str(batch_path),
        ])
        assert rc == 0

        rc, out, _ = _run(["list", "--scope", "project"])
        assert rc == 0
        rows = json.loads(out)
        assert len(rows) == 1 and rows[0]["scope"] == "project"

        # mark one item triaged, then filter by status
        target_id = rows[0]["id"]
        rc, _, _ = _run(["mark", "--id", target_id, "--status", "triaged"])
        assert rc == 0

        rc, out, _ = _run(["list", "--status", "triaged"])
        assert rc == 0
        rows = json.loads(out)
        assert len(rows) == 1 and rows[0]["id"] == target_id

        rc, out, _ = _run(["list", "--status", "open"])
        assert rc == 0
        rows = json.loads(out)
        assert len(rows) == 1 and rows[0]["scope"] == "methodology"

        print("PASS test_list_filters_by_scope_and_status")


def test_list_missing_file_returns_empty_array():
    """(5) list on an absent store prints '[]' and returns 0."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _patch_paths(tmp_path)

        rc, out, _ = _run(["list"])
        assert rc == 0
        assert json.loads(out) == []

        print("PASS test_list_missing_file_returns_empty_array")


def test_cli_runs_through_path_symlink_resolving_lib():
    """(11) Regression guard for the install.sh PATH-symlink invocation path.

    install.sh symlinks ~/.local/bin/agentic-feedback -> repo bin/agentic-feedback
    but never symlinks _lib.py alongside it. When Python resolves __file__ for a
    symlinked entrypoint it reports the SYMLINK's path, so `Path(__file__).parent`
    lands in ~/.local/bin/ where _lib.py does not exist. Must invoke via a real
    subprocess THROUGH the symlink (not an in-process import) because the bug
    only manifests when the OS/interpreter actually resolves __file__ to a
    symlink path, which in-process importlib loading (as used by _run() above)
    never exercises.
    """
    real_bin_path = Path(__file__).parent.parent / "agentic-feedback"
    assert real_bin_path.is_file(), f"expected real CLI at {real_bin_path}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_local_bin = tmp_path / "local-bin"
        fake_local_bin.mkdir()
        symlink_path = fake_local_bin / "agentic-feedback"
        os.symlink(real_bin_path.resolve(), symlink_path)

        fake_home = tmp_path / "home"
        fake_home.mkdir()

        env = dict(os.environ)
        env["HOME"] = str(fake_home)

        result = subprocess.run(
            [str(symlink_path), "list"],
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


def test_mark_updates_only_target_status():
    """(6) mark changes only the matching line's status; all else byte-identical."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        feedback_path, _ = _patch_paths(tmp_path)

        drafts = [dict(VALID_DRAFT, evidence="item A"), dict(VALID_DRAFT, evidence="item B")]
        batch_path = _write_batch(tmp_path, drafts)
        rc, _, _ = _run([
            "append", "--repo", "/repo/x", "--session-uuid", "s1", "--file", str(batch_path),
        ])
        assert rc == 0

        before_lines = [json.loads(l) for l in feedback_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        target = next(r for r in before_lines if r["evidence"] == "item A")
        other = next(r for r in before_lines if r["evidence"] == "item B")

        rc, out, _ = _run(["mark", "--id", target["id"], "--status", "dismissed"])
        assert rc == 0, out

        after_lines = [json.loads(l) for l in feedback_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        after_target = next(r for r in after_lines if r["id"] == target["id"])
        after_other = next(r for r in after_lines if r["id"] == other["id"])

        assert after_target["status"] == "dismissed"
        for key in target:
            if key == "status":
                continue
            assert after_target[key] == target[key], f"field {key!r} changed unexpectedly"

        assert after_other == other, "non-target row must be byte-identical (field-for-field)"

        print("PASS test_mark_updates_only_target_status")


def test_mark_unknown_id_exits_1_and_leaves_file_unchanged():
    """(7) mark on unknown --id exits 1 and does not modify the store."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        feedback_path, _ = _patch_paths(tmp_path)

        batch_path = _write_batch(tmp_path, [dict(VALID_DRAFT)])
        rc, _, _ = _run([
            "append", "--repo", "/repo/x", "--session-uuid", "s1", "--file", str(batch_path),
        ])
        assert rc == 0

        before = feedback_path.read_text(encoding="utf-8")

        rc, out, err = _run(["mark", "--id", "not-a-real-id", "--status", "dismissed"])
        assert rc == 1, f"Expected exit 1 for unknown id, got {rc}"
        assert "no feedback item" in err.lower()

        after = feedback_path.read_text(encoding="utf-8")
        assert before == after, "File must be unchanged after a failed mark"

        print("PASS test_mark_unknown_id_exits_1_and_leaves_file_unchanged")


def test_two_sequential_appends_both_land_under_shared_lock():
    """(8) two sequential appends (simulating two projects' /wrap runs) both land
    intact - final file is the union of valid items, one well-formed line each."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        feedback_path, _ = _patch_paths(tmp_path)

        batch1 = _write_batch(tmp_path, [dict(VALID_DRAFT, evidence="repo-a item")])
        rc1, _, _ = _run([
            "append", "--repo", "/repo/a", "--session-uuid", "sess-a", "--file", str(batch1),
        ])
        assert rc1 == 0

        batch2 = _write_batch(tmp_path, [dict(VALID_DRAFT, evidence="repo-b item")])
        rc2, _, _ = _run([
            "append", "--repo", "/repo/b", "--session-uuid", "sess-b", "--file", str(batch2),
        ])
        assert rc2 == 0

        lines = [l for l in feedback_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2, f"Expected 2 lines (union of both appends), got {len(lines)}"

        rows = [json.loads(l) for l in lines]
        evidences = {r["evidence"] for r in rows}
        assert evidences == {"repo-a item", "repo-b item"}
        repos = {r["repo"] for r in rows}
        assert repos == {"/repo/a", "/repo/b"}
        # Each line individually well-formed JSON (already implied by json.loads above).
        ids = {r["id"] for r in rows}
        assert len(ids) == 2, "Each appended item must get a distinct id"

        print("PASS test_two_sequential_appends_both_land_under_shared_lock")


def test_concurrent_appends_serialize_under_real_multiprocess_contention():
    """(9) genuine concurrency: N multiprocessing.Process workers each append
    many records to the SAME store at once. Asserts on COUNT and JSON-validity
    only (no timing/ordering assertions - deterministic and robust):
      (a) the final file has exactly the expected total line count, and
      (b) every line parses as valid JSON (no torn/interleaved half-lines).
    A version with the fcntl lock removed would be expected to drop and/or
    interleave lines under this contention - this test proves the lock
    actually serializes writers, unlike a sequential-call test."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        feedback_path = tmp_path / "feedback.jsonl"
        lock_path = tmp_path / "feedback.jsonl.lock"

        n_workers = 4
        n_per_worker = 25
        procs = []
        for w in range(n_workers):
            drafts = [
                dict(VALID_DRAFT, evidence=f"worker {w} item {i}")
                for i in range(n_per_worker)
            ]
            batch_path = tmp_path / f"batch-{w}.json"
            batch_path.write_text(json.dumps(drafts), encoding="utf-8")
            p = multiprocessing.Process(
                target=_mp_append_worker,
                args=(
                    str(_BIN_PATH), str(feedback_path), str(lock_path),
                    f"/repo/{w}", f"sess-{w}", str(batch_path),
                ),
            )
            procs.append(p)

        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)

        for w, p in enumerate(procs):
            assert p.exitcode == 0, f"worker {w} exited with {p.exitcode!r} (expected 0)"

        assert feedback_path.is_file(), "store file must exist after concurrent appends"
        lines = [ln for ln in feedback_path.read_text(encoding="utf-8").splitlines() if ln.strip()]

        expected_total = n_workers * n_per_worker
        assert len(lines) == expected_total, (
            f"Expected exactly {expected_total} lines under lock-serialized "
            f"contention, got {len(lines)} (a lost/torn write indicates the "
            f"lock did not serialize the workers)"
        )

        # Every line must be valid, non-torn JSON - json.loads raises on a
        # half-written/interleaved line, which a missing lock could produce.
        ids = set()
        for line in lines:
            row = json.loads(line)
            ids.add(row["id"])
        assert len(ids) == expected_total, (
            "every appended item must get a distinct id (no duplicate/corrupted rows)"
        )

        print("PASS test_concurrent_appends_serialize_under_real_multiprocess_contention")


def test_mark_warns_on_malformed_line_and_drops_it():
    """(10) mark's rewrite prints a stderr warning naming the line number of a
    malformed line it drops - visibility for what would otherwise be a
    silent, destructive skip during the full-file rewrite."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        feedback_path, _ = _patch_paths(tmp_path)

        batch_path = _write_batch(tmp_path, [dict(VALID_DRAFT, evidence="good item")])
        rc, _, _ = _run([
            "append", "--repo", "/repo/x", "--session-uuid", "s1", "--file", str(batch_path),
        ])
        assert rc == 0

        good_line = feedback_path.read_text(encoding="utf-8").rstrip("\n")
        good_id = json.loads(good_line)["id"]

        # Hand-corrupt the store: append a malformed (non-JSON) line at line 2.
        with open(feedback_path, "a", encoding="utf-8") as f:
            f.write("{this is not valid json\n")

        rc, out, err = _run(["mark", "--id", good_id, "--status", "triaged"])
        assert rc == 0, f"mark should still succeed despite a malformed line: {err}"
        assert "skipping malformed line 2" in err, (
            f"Expected a stderr warning naming line 2, got: {err!r}"
        )

        remaining_lines = [
            ln for ln in feedback_path.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        assert len(remaining_lines) == 1, "malformed line must be dropped from the rewrite"
        row = json.loads(remaining_lines[0])
        assert row["id"] == good_id
        assert row["status"] == "triaged"

        print("PASS test_mark_warns_on_malformed_line_and_drops_it")


if __name__ == "__main__":
    test_append_valid_and_invalid_mixed()
    test_append_overwrites_caller_supplied_id_ts_status()
    test_append_empty_array_is_clean_noop()
    test_list_filters_by_scope_and_status()
    test_list_missing_file_returns_empty_array()
    test_cli_runs_through_path_symlink_resolving_lib()
    test_mark_updates_only_target_status()
    test_mark_unknown_id_exits_1_and_leaves_file_unchanged()
    test_two_sequential_appends_both_land_under_shared_lock()
    test_concurrent_appends_serialize_under_real_multiprocess_contention()
    test_mark_warns_on_malformed_line_and_drops_it()
    print("All tests passed.")
