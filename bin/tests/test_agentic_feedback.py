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

Regression test obligation: content/references/regression-test-obligation.md
Run with: python3 -m pytest bin/tests/test_agentic_feedback.py -x
       or: python3 bin/tests/test_agentic_feedback.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
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


if __name__ == "__main__":
    test_append_valid_and_invalid_mixed()
    test_append_overwrites_caller_supplied_id_ts_status()
    test_append_empty_array_is_clean_noop()
    test_list_filters_by_scope_and_status()
    test_list_missing_file_returns_empty_array()
    test_mark_updates_only_target_status()
    test_mark_unknown_id_exits_1_and_leaves_file_unchanged()
    test_two_sequential_appends_both_land_under_shared_lock()
    print("All tests passed.")
