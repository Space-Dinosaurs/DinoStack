#!/usr/bin/env python3
"""
Regression tests for agentic-identity: canonical shape fix and project-scope override.

Test groups:
  1. test_flushed_line_canonical_shape - flushed lines match canonical shape (original test).
  2. test_project_scope_flush_does_not_touch_other_repo_records (A) - repo_root_filter
     isolates flush to matching repo; other-repo pending files are left in buffer.
  3. test_confirmed_global_not_suppressed_by_provisional_project (B) - global-confirmed
     wins over project-provisional in 4-tier resolution.
  4. test_project_confirmed_beats_confirmed_global (C) - project-confirmed wins over
     global-confirmed in 4-tier resolution.
  5. test_no_repo_root_record_skipped_by_filter (D) - records with absent/empty repo_root
     are conservatively skipped when a repo_root_filter is active.
  6. test_global_scope_flush_unaffected (E) - no-filter flush attributes all pending records.

Regression test obligation: content/references/regression-test-obligation.md
Run with: python3 -m pytest bin/tests/test_agentic_identity.py -x
       or: python3 bin/tests/test_agentic_identity.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Load agentic-identity as a module (no .py extension)
# ---------------------------------------------------------------------------
_BIN_PATH = Path(__file__).parent.parent / "agentic-identity"
_loader = importlib.machinery.SourceFileLoader("agentic_identity", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_identity", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-identity from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

flushPendingBuffer = _mod.flushPendingBuffer
_resolve_effective_identity = _mod._resolve_effective_identity
_project_identity_path = _mod._project_identity_path


def _write_pending(pending_dir: Path, record: dict) -> Path:
    """Write a pending record file. Returns the path."""
    pending_dir.mkdir(parents=True, exist_ok=True)
    p = pending_dir / f"{record['session_uuid']}.json"
    p.write_text(json.dumps(record), encoding="utf-8")
    return p


def _patch_paths(tmp_path: Path):
    """Patch module-level paths to use tmp_path. Returns (pending_dir, log_dir, lock_path)."""
    pending_dir = tmp_path / "session-log" / ".pending"
    global_log_dir = tmp_path / "session-log"
    flush_lock = tmp_path / "session-log" / ".flush.lock"
    _mod.PENDING_DIR = pending_dir
    _mod.GLOBAL_SESSION_LOG_DIR = global_log_dir
    _mod.FLUSH_LOCK_PATH = flush_lock
    flush_lock.parent.mkdir(parents=True, exist_ok=True)
    flush_lock.touch(exist_ok=True)
    return pending_dir, global_log_dir, flush_lock


def _write_identity_file(path: Path, developer_id: str, provisional: bool = False) -> None:
    """Write a minimal identity.yml at path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"developer_id: {developer_id}", "created_at: 2026-01-01T00:00:00Z"]
    if provisional:
        lines.append("provisional: true")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Existing test (preserved)
# ---------------------------------------------------------------------------

def test_flushed_line_canonical_shape():
    """flushed line must match canonical shape; must NOT contain schema_version or repo_root."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, flush_lock = _patch_paths(tmp_path)

        # Pending record mimics what writePendingBuffer in stop-context.js writes.
        # Includes schema_version and repo_root - fields that must NOT appear in
        # the canonical output line.
        pending_record = {
            "schema_version": "1",
            "session_uuid": "test-uuid-1234",
            "ts": "2026-06-04T00:00:00.000Z",
            "project_slug": "my-project",
            "repo_root": "/home/user/my-project",
            "branch": "main",
            "data": {
                "wall_seconds": 42.0,
                "tokens": {"input": 100, "output": 50,
                           "cache_creation": 0, "cache_read": 0},
                "spawn_count": 3,
                "by_agent": {},
            },
        }
        _write_pending(pending_dir, pending_record)

        dev_id = "testdev"
        count = flushPendingBuffer(dev_id)
        assert count == 1, f"Expected 1 flushed, got {count}"

        global_log = global_log_dir / f"{dev_id}.jsonl"
        assert global_log.is_file(), "Global log not written"

        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1, f"Expected 1 line in global log, got {len(lines)}"

        row = json.loads(lines[0])

        # --- canonical fields must be present and correct ---
        assert row.get("phase") == "session_end", \
            f"phase should be 'session_end', got {row.get('phase')!r}"
        assert row.get("event") == "session_total", \
            f"event should be 'session_total', got {row.get('event')!r}"
        assert row.get("developer_id") == dev_id, \
            f"developer_id should be {dev_id!r}, got {row.get('developer_id')!r}"
        assert row.get("session_uuid") == "test-uuid-1234", \
            f"session_uuid mismatch: {row.get('session_uuid')!r}"
        assert "agent" in row, "canonical field 'agent' missing"
        assert "task_id" in row, "canonical field 'task_id' missing"
        assert row.get("project_slug") == "my-project", \
            f"project_slug mismatch: {row.get('project_slug')!r}"
        assert row.get("branch") == "main", \
            f"branch mismatch: {row.get('branch')!r}"
        assert "data" in row, "canonical field 'data' missing"

        # --- non-canonical fields must NOT appear (pre-fix regression sentinel) ---
        assert "schema_version" not in row, \
            "schema_version must NOT appear in canonical session-log line (pre-fix regression)"
        assert "repo_root" not in row, \
            "repo_root must NOT appear in canonical session-log line (pre-fix regression)"

        print("PASS test_flushed_line_canonical_shape")


# ---------------------------------------------------------------------------
# New tests (A-E): project-scope override regression suite
# ---------------------------------------------------------------------------

def test_project_scope_flush_does_not_touch_other_repo_records():
    """(A) repo_root_filter=/repo/a flushes only the /repo/a record; /repo/b file stays."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        record_a = {
            "session_uuid": "uuid-repo-a",
            "ts": "2026-06-01T00:00:00.000Z",
            "repo_root": "/repo/a",
            "project_slug": "a",
            "branch": "main",
            "data": {},
        }
        record_b = {
            "session_uuid": "uuid-repo-b",
            "ts": "2026-06-01T00:01:00.000Z",
            "repo_root": "/repo/b",
            "project_slug": "b",
            "branch": "main",
            "data": {},
        }
        path_a = _write_pending(pending_dir, record_a)
        path_b = _write_pending(pending_dir, record_b)

        count = flushPendingBuffer("a-dev", repo_root_filter="/repo/a")
        assert count == 1, f"Expected 1 flushed, got {count}"

        # /repo/a record was flushed - its file should be gone
        assert not path_a.exists(), "Pending file for /repo/a should have been removed"

        # /repo/b record was NOT touched - its file must still exist
        assert path_b.exists(), "Pending file for /repo/b must remain in buffer"

        # The flushed line must have developer_id == "a-dev"
        global_log = global_log_dir / "a-dev.jsonl"
        assert global_log.is_file(), "Global log for a-dev should exist"
        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1, f"Expected 1 flushed line, got {len(lines)}"
        row = json.loads(lines[0])
        assert row["developer_id"] == "a-dev"
        assert row["session_uuid"] == "uuid-repo-a"

        print("PASS test_project_scope_flush_does_not_touch_other_repo_records")


def test_confirmed_global_not_suppressed_by_provisional_project():
    """(B) provisional project + confirmed global -> effective is global-dev (_confirmed True, _scope global)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cwd = tmp_path / "myrepo"
        cwd.mkdir()

        # Project identity: provisional
        proj_path = cwd / ".agentic" / "identity.yml"
        _write_identity_file(proj_path, "project-dev", provisional=True)

        # Global identity: confirmed - patch IDENTITY_PATH on the module
        global_id_path = tmp_path / "global-identity.yml"
        _write_identity_file(global_id_path, "global-dev", provisional=False)
        original_identity_path = _mod.IDENTITY_PATH
        _mod.IDENTITY_PATH = global_id_path
        try:
            result = _resolve_effective_identity(cwd)
        finally:
            _mod.IDENTITY_PATH = original_identity_path

        assert result is not None, "Expected a resolved identity"
        assert result["developer_id"] == "global-dev", \
            f"Expected global-dev, got {result['developer_id']!r}"
        assert result["_scope"] == "global", \
            f"Expected scope=global, got {result['_scope']!r}"
        assert result["_confirmed"] is True, \
            f"Expected _confirmed=True, got {result['_confirmed']!r}"

        print("PASS test_confirmed_global_not_suppressed_by_provisional_project")


def test_project_confirmed_beats_confirmed_global():
    """(C) both confirmed -> project identity wins."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cwd = tmp_path / "myrepo"
        cwd.mkdir()

        # Project identity: confirmed
        proj_path = cwd / ".agentic" / "identity.yml"
        _write_identity_file(proj_path, "project-dev", provisional=False)

        # Global identity: confirmed
        global_id_path = tmp_path / "global-identity.yml"
        _write_identity_file(global_id_path, "global-dev", provisional=False)
        original_identity_path = _mod.IDENTITY_PATH
        _mod.IDENTITY_PATH = global_id_path
        try:
            result = _resolve_effective_identity(cwd)
        finally:
            _mod.IDENTITY_PATH = original_identity_path

        assert result is not None, "Expected a resolved identity"
        assert result["developer_id"] == "project-dev", \
            f"Expected project-dev, got {result['developer_id']!r}"
        assert result["_scope"] == "project", \
            f"Expected scope=project, got {result['_scope']!r}"
        assert result["_confirmed"] is True, \
            f"Expected _confirmed=True, got {result['_confirmed']!r}"

        print("PASS test_project_confirmed_beats_confirmed_global")


def test_no_repo_root_record_skipped_by_filter():
    """(D) record with absent repo_root is skipped by a non-None filter; file remains."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        record_no_root = {
            "session_uuid": "uuid-no-root",
            "ts": "2026-06-01T00:00:00.000Z",
            # repo_root intentionally absent
            "project_slug": "unknown",
            "branch": "main",
            "data": {},
        }
        pending_file = _write_pending(pending_dir, record_no_root)

        count = flushPendingBuffer("some-dev", repo_root_filter="/repo/x")
        assert count == 0, f"Expected 0 flushed (no-root record should be skipped), got {count}"

        # File must remain in the buffer
        assert pending_file.exists(), "Pending file with no repo_root must remain in buffer"

        print("PASS test_no_repo_root_record_skipped_by_filter")


def test_global_scope_flush_unaffected():
    """(E) no filter (repo_root_filter=None) attributes all pending records."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        record1 = {
            "session_uuid": "uuid-g1",
            "ts": "2026-06-01T00:00:00.000Z",
            "repo_root": "/repo/alpha",
            "project_slug": "alpha",
            "branch": "main",
            "data": {},
        }
        record2 = {
            "session_uuid": "uuid-g2",
            "ts": "2026-06-01T00:01:00.000Z",
            "repo_root": "/repo/beta",
            "project_slug": "beta",
            "branch": "main",
            "data": {},
        }
        _write_pending(pending_dir, record1)
        _write_pending(pending_dir, record2)

        count = flushPendingBuffer("g-dev")  # no filter
        assert count == 2, f"Expected 2 flushed, got {count}"

        global_log = global_log_dir / "g-dev.jsonl"
        assert global_log.is_file(), "Global log for g-dev should exist"
        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2, f"Expected 2 flushed lines, got {len(lines)}"
        uuids = {json.loads(l)["session_uuid"] for l in lines}
        assert uuids == {"uuid-g1", "uuid-g2"}, f"Unexpected session_uuids: {uuids}"

        print("PASS test_global_scope_flush_unaffected")


# ---------------------------------------------------------------------------
# Tests (F-H): O(M+N) dedup regression suite (#268)
# ---------------------------------------------------------------------------

def test_dedup_skips_already_flushed_uuid():
    """(F) pending file whose session_uuid is already in global log is skipped+unlinked."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        dev_id = "dedup-dev"
        already_present_uuid = "uuid-already-in-log"

        # Pre-populate global log with that uuid.
        global_log = global_log_dir / f"{dev_id}.jsonl"
        existing_line = json.dumps({
            "session_uuid": already_present_uuid,
            "developer_id": dev_id,
            "phase": "session_end",
            "event": "session_total",
            "agent": None,
            "task_id": None,
        })
        global_log.write_text(existing_line + "\n", encoding="utf-8")

        # Write a pending file with the same uuid.
        pending_record = {
            "session_uuid": already_present_uuid,
            "ts": "2026-06-10T00:00:00.000Z",
            "project_slug": "my-proj",
            "repo_root": "/repo/my-proj",
            "branch": "main",
            "data": {},
        }
        pending_path = _write_pending(pending_dir, pending_record)

        count = flushPendingBuffer(dev_id)
        assert count == 0, f"Expected 0 flushed (already deduped), got {count}"

        # Pending file must be unlinked (dedup path removes it).
        assert not pending_path.exists(), \
            "Pending file with already-flushed uuid must be unlinked"

        # Global log must still have exactly 1 line (no duplicate appended).
        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1, f"Global log must remain 1 line, got {len(lines)}"

        print("PASS test_dedup_skips_already_flushed_uuid")


def test_dedup_flushes_new_uuid_not_in_log():
    """(G) pending file whose uuid is NOT in the global log is flushed normally."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        dev_id = "dedup-dev2"
        existing_uuid = "uuid-existing"
        new_uuid = "uuid-brand-new"

        # Pre-populate global log with a DIFFERENT uuid.
        global_log = global_log_dir / f"{dev_id}.jsonl"
        existing_line = json.dumps({
            "session_uuid": existing_uuid,
            "developer_id": dev_id,
            "phase": "session_end",
            "event": "session_total",
            "agent": None,
            "task_id": None,
        })
        global_log.write_text(existing_line + "\n", encoding="utf-8")

        # Write pending file with a new uuid.
        pending_record = {
            "session_uuid": new_uuid,
            "ts": "2026-06-10T00:01:00.000Z",
            "project_slug": "my-proj",
            "repo_root": "/repo/my-proj",
            "branch": "main",
            "data": {},
        }
        pending_path = _write_pending(pending_dir, pending_record)

        count = flushPendingBuffer(dev_id)
        assert count == 1, f"Expected 1 flushed, got {count}"

        assert not pending_path.exists(), "Flushed pending file must be unlinked"

        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2, f"Expected 2 lines in global log, got {len(lines)}"
        uuids_in_log = {json.loads(l)["session_uuid"] for l in lines}
        assert new_uuid in uuids_in_log, f"{new_uuid!r} must appear in global log"

        print("PASS test_dedup_flushes_new_uuid_not_in_log")


def test_dedup_missing_global_log_flushes_all():
    """(H) missing global log (is_file() False) still flushes all pending files (fallback preserved)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        dev_id = "dedup-dev3"

        # Do NOT create the global log -> is_file() returns False -> seen_uuids empty.
        record1 = {
            "session_uuid": "uuid-fallback-1",
            "ts": "2026-06-10T00:00:00.000Z",
            "project_slug": "proj",
            "repo_root": "/repo/proj",
            "branch": "main",
            "data": {},
        }
        record2 = {
            "session_uuid": "uuid-fallback-2",
            "ts": "2026-06-10T00:01:00.000Z",
            "project_slug": "proj",
            "repo_root": "/repo/proj",
            "branch": "main",
            "data": {},
        }
        _write_pending(pending_dir, record1)
        _write_pending(pending_dir, record2)

        count = flushPendingBuffer(dev_id)
        assert count == 2, f"Expected 2 flushed (no prior log), got {count}"

        global_log = global_log_dir / f"{dev_id}.jsonl"
        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}"
        uuids_in_log = {json.loads(l)["session_uuid"] for l in lines}
        assert uuids_in_log == {"uuid-fallback-1", "uuid-fallback-2"}

        print("PASS test_dedup_missing_global_log_flushes_all")


def test_dedup_multi_pending_correct_across_several():
    """(H2) multi-pending: already-flushed uuids skipped, new uuids flushed — all in one pass."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        dev_id = "dedup-dev4"
        known_uuids = {"uuid-known-1", "uuid-known-2"}
        new_uuids = {"uuid-new-1", "uuid-new-2"}

        # Pre-populate global log with the known uuids.
        global_log = global_log_dir / f"{dev_id}.jsonl"
        lines_to_write = [
            json.dumps({"session_uuid": u, "developer_id": dev_id,
                        "phase": "session_end", "event": "session_total",
                        "agent": None, "task_id": None})
            for u in sorted(known_uuids)
        ]
        global_log.write_text("\n".join(lines_to_write) + "\n", encoding="utf-8")

        # Write 4 pending files: 2 known (should be skipped), 2 new (should flush).
        for u in known_uuids | new_uuids:
            _write_pending(pending_dir, {
                "session_uuid": u,
                "ts": "2026-06-10T00:00:00.000Z",
                "project_slug": "proj",
                "repo_root": "/repo/proj",
                "branch": "main",
                "data": {},
            })

        count = flushPendingBuffer(dev_id)
        assert count == 2, f"Expected 2 flushed (only new uuids), got {count}"

        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 4, f"Expected 4 lines total (2 old + 2 new), got {len(lines)}"
        uuids_in_log = {json.loads(l)["session_uuid"] for l in lines}
        assert uuids_in_log == known_uuids | new_uuids, \
            f"Unexpected uuids in log: {uuids_in_log}"

        print("PASS test_dedup_multi_pending_correct_across_several")


if __name__ == "__main__":
    test_flushed_line_canonical_shape()
    test_project_scope_flush_does_not_touch_other_repo_records()
    test_confirmed_global_not_suppressed_by_provisional_project()
    test_project_confirmed_beats_confirmed_global()
    test_no_repo_root_record_skipped_by_filter()
    test_global_scope_flush_unaffected()
    test_dedup_skips_already_flushed_uuid()
    test_dedup_flushes_new_uuid_not_in_log()
    test_dedup_missing_global_log_flushes_all()
    test_dedup_multi_pending_correct_across_several()
    print("All tests passed.")
