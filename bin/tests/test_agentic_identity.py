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
  7. J/K suites - profile scope: 6-tier resolution, env detection, config_dir
     flush partition (see individual docstrings).
  8. CLI suite (L) - subprocess-level scope coverage under a fake $HOME:
     profile auto/confirm, project confirm with an active profile, global
     confirm partitioning, rejection paths, and end-to-end flush routing.
  9. M suite - hardening: nonexistent highest-precedence env dir stops the
     scan (Python<->JS parity contract), symlink-escape rejection, file-as-
     profile-dir clean failure, non-string config_dir flush guard.
  10. Final security review regressions - invalid parsed handles, final-target
      symlink/non-regular rejection, bounded corrupt reads, validated flush
      locks, Unicode Cc rejection, concurrent confirmation publication/routing,
      and public docs/manifest contracts.

Regression test obligation: content/references/regression-test-obligation.md
Run with: python3 -m pytest bin/tests/test_agentic_identity.py -x
       or: python3 bin/tests/test_agentic_identity.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stderr
from pathlib import Path

# ---------------------------------------------------------------------------
# Load agentic-identity as a module (no .py extension)
# ---------------------------------------------------------------------------
_BIN_PATH = Path(__file__).parent.parent / "agentic-identity"
_IDENTITY_DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "content"
    / "commands"
    / "ds-identity.md"
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_README_PATH = _REPO_ROOT / "README.md"
_IDENTITY_TELEMETRY_DOC_PATH = _REPO_ROOT / "docs" / "identity-telemetry.md"
_IDENTITY_SH_PATH = _REPO_ROOT / "scripts" / "lib" / "identity.sh"
_loader = importlib.machinery.SourceFileLoader("agentic_identity", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_identity", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-identity from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

flushPendingBuffer = _mod.flushPendingBuffer
_resolve_effective_identity = _mod._resolve_effective_identity
_project_identity_path = _mod._project_identity_path
_profile_identity_path = _mod._profile_identity_path
_profile_config_dir = _mod._profile_config_dir


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


def _write_noncanonical_confirmed_identity(path: Path, developer_id: str) -> bytes:
    """Write a confirmed identity with operator formatting that must survive confirm."""
    content = (
        "# operator-owned identity metadata\n"
        "created_at: 2026-01-01T00:00:00Z\n"
        "display_name: Test Operator\n"
        f"developer_id: {developer_id}\n"
        "\n"
        "# keep this trailing comment\n"
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _assert_single_flushed_record(
    fake_home: Path,
    developer_id: str,
    session_uuid: str,
) -> None:
    """Assert a scope confirm routed exactly one pending record to the global log."""
    global_log = (
        fake_home / ".agentic" / "session-log" / f"{developer_id}.jsonl"
    )
    assert global_log.is_file(), "Confirmation must write the global session log"
    rows = [
        json.loads(line)
        for line in global_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1, f"Expected one flushed record, got {len(rows)}"
    assert rows[0]["session_uuid"] == session_uuid
    assert rows[0]["developer_id"] == developer_id


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


def test_flush_claim_preserves_newer_same_session_publication():
    """A writer replacing the canonical pending path cannot be unlinked stale."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        pending_dir, global_log_dir, _ = _patch_paths(root)
        session_uuid = "uuid-pending-replacement-race"
        old_record = {
            "session_uuid": session_uuid,
            "ts": "2026-07-01T00:00:00Z",
            "project_slug": "project",
            "repo_root": "",
            "branch": "main",
            "identity_scope": "global",
            "data": {"tokens": {"total": 1}, "by_agent": {}},
        }
        newer_record = {
            **old_record,
            "ts": "2026-07-01T00:00:01Z",
            "data": {"tokens": {"total": 99}, "by_agent": {}},
        }
        _write_pending(pending_dir, old_record)

        original_read = _mod._read_pending_record_at
        injected = False

        def read_with_replacement(parent_fd, name):
            nonlocal injected
            record = original_read(parent_fd, name)
            if record is not None and not injected and name == f"{session_uuid}.json":
                injected = True
                assert _mod._write_pending_record_safely(newer_record)
            return record

        _mod._read_pending_record_at = read_with_replacement
        try:
            assert flushPendingBuffer("claim-dev", scope_filter="global") == 1
        finally:
            _mod._read_pending_record_at = original_read

        rows = [
            json.loads(line)
            for line in (global_log_dir / "claim-dev.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        assert len(rows) == 1
        assert rows[0]["session_uuid"] == session_uuid
        assert rows[0]["data"]["tokens"]["total"] == 99, rows
        assert not list(pending_dir.glob("*.json")), (
            "newer publication must remain pending or be flushed, never deleted stale"
        )
        print("PASS test_flush_claim_preserves_newer_same_session_publication")


def test_flush_replaces_attributed_total_published_immediately_after_claim():
    """A later cumulative pending record replaces its attributed UUID row."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        pending_dir, global_log_dir, _ = _patch_paths(root)
        session_uuid = "uuid-post-claim-cumulative-replacement"
        old_record = {
            "session_uuid": session_uuid,
            "ts": "2026-07-01T00:00:00Z",
            "project_slug": "project",
            "repo_root": "",
            "branch": "main",
            "identity_scope": "global",
            "data": {"tokens": {"total": 1}, "by_agent": {}},
        }
        newer_record = {
            **old_record,
            "ts": "2026-07-01T00:00:01Z",
            "data": {"tokens": {"total": 99}, "by_agent": {}},
        }
        _write_pending(pending_dir, old_record)

        original_claim = _mod._claim_pending_record_at
        original_iter = _mod._iter_bounded_pending_names
        published = False

        def snapshot_names(parent_fd):
            # A flush pass operates on the directory snapshot that existed at
            # enumeration time. The post-claim publication belongs to retry.
            yield from list(original_iter(parent_fd))

        def claim_then_publish(parent_fd, name):
            nonlocal published
            claimed_name = original_claim(parent_fd, name)
            if claimed_name is not None and not published:
                published = True
                assert _mod._write_pending_record_safely(newer_record)
            return claimed_name

        _mod._iter_bounded_pending_names = snapshot_names
        _mod._claim_pending_record_at = claim_then_publish
        try:
            assert flushPendingBuffer("claim-replace-dev", scope_filter="global") == 1
        finally:
            _mod._claim_pending_record_at = original_claim
            _mod._iter_bounded_pending_names = original_iter

        canonical = pending_dir / f"{session_uuid}.json"
        assert json.loads(canonical.read_text(encoding="utf-8"))["data"]["tokens"]["total"] == 99
        assert flushPendingBuffer("claim-replace-dev", scope_filter="global") == 1

        rows = [
            json.loads(line)
            for line in (global_log_dir / "claim-replace-dev.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        matching = [row for row in rows if row.get("session_uuid") == session_uuid]
        assert len(matching) == 1, matching
        assert matching[0]["data"]["tokens"]["total"] == 99, matching
        assert not list(pending_dir.glob("*.json"))
        print(
            "PASS "
            "test_flush_replaces_attributed_total_published_immediately_after_claim"
        )


def test_append_retries_when_canonical_log_rotates_before_flock():
    """An append cannot report success only on a displaced opened inode."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        log_path = root / "session-log" / "rotation-dev.jsonl"
        log_path.parent.mkdir()
        log_path.write_text("", encoding="utf-8")
        rotated_path = log_path.with_suffix(".rotated")
        line = json.dumps(
            {
                "session_uuid": "append-path-rotation",
                "data": {"tokens": {"total": 7}},
            },
            separators=(",", ":"),
        )

        original_open = _mod._open_safe_log_at
        original_lock = _mod._lock_fd_exclusive
        opened_log_fd = None
        rotated = False

        def remember_open(parent_fd, name, *, create=False):
            nonlocal opened_log_fd
            fd = original_open(parent_fd, name, create=create)
            if name == log_path.name and opened_log_fd is None:
                opened_log_fd = fd
            return fd

        def rotate_before_flock(fd, *, timeout):
            nonlocal rotated
            if fd == opened_log_fd and not rotated:
                rotated = True
                log_path.rename(rotated_path)
                log_path.write_text("", encoding="utf-8")
            return original_lock(fd, timeout=timeout)

        _mod._open_safe_log_at = remember_open
        _mod._lock_fd_exclusive = rotate_before_flock
        try:
            assert _mod._append_jsonl_safely(log_path, line)
        finally:
            _mod._lock_fd_exclusive = original_lock
            _mod._open_safe_log_at = original_open

        canonical_rows = [
            json.loads(raw)
            for raw in log_path.read_text(encoding="utf-8").splitlines()
            if raw.strip()
        ]
        assert [row["session_uuid"] for row in canonical_rows] == [
            "append-path-rotation"
        ], canonical_rows
        print("PASS test_append_retries_when_canonical_log_rotates_before_flock")


def test_append_retries_when_canonical_parent_rotates_before_publication():
    """A detached parent descriptor must never receive a successful publication."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        log_path = root / "session-log" / "parent-rotation.jsonl"
        log_path.parent.mkdir(parents=True)
        detached = root / "detached-session-log"
        original_open = _mod._open_safe_log_at
        rotated = False

        def rotate_parent(parent_fd, name, *, create=False):
            nonlocal rotated
            if not rotated:
                rotated = True
                log_path.parent.rename(detached)
                log_path.parent.mkdir(mode=0o700)
            return original_open(parent_fd, name, create=create)

        _mod._open_safe_log_at = rotate_parent
        try:
            assert _mod._append_jsonl_safely(
                log_path,
                json.dumps(
                    {
                        "session_uuid": "append-parent-rotation",
                        "ts": "2026-08-06T00:00:00Z",
                    }
                ),
            )
        finally:
            _mod._open_safe_log_at = original_open

        canonical_rows = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
        ]
        assert [row["session_uuid"] for row in canonical_rows] == [
            "append-parent-rotation"
        ]
        detached_log = detached / log_path.name
        assert not detached_log.exists() or detached_log.read_text() == ""
        print("PASS test_append_retries_when_canonical_parent_rotates_before_publication")


def test_lock_timeout_retries_with_backoff_and_succeeds():
    """DS-158 round 2: a transient lock-timeout RuntimeError from
    _lock_fd_exclusive must be retried by _write_jsonl_safely's attempt
    loop, not swallowed after a single attempt. Round 1 only raised the
    per-attempt timeout (2.0s -> 5.0s); that timeout still escaped the
    loop's `except FileNotFoundError` entirely and was caught only by the
    function's outer except, one shot, no retry - a bigger single wait does
    not change that shape. This forces two consecutive lock-timeout raises
    (matching what a real flock timeout raises, regardless of exact
    exception subclass) before delegating to the real flock, and asserts
    the record still lands durably and that more than one attempt occurred.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        log_path = root / "session-log" / "lock-timeout-dev.jsonl"
        log_path.parent.mkdir(parents=True)
        line = json.dumps(
            {"session_uuid": "lock-timeout-retry", "data": {"tokens": {"total": 3}}},
            separators=(",", ":"),
        )

        original_lock = _mod._lock_fd_exclusive
        attempts = {"n": 0}

        def flaky_lock(fd, *, timeout):
            attempts["n"] += 1
            if attempts["n"] <= 2:
                # Same exception family a real flock timeout raises
                # (RuntimeError); a plain RuntimeError here (rather than the
                # production-only _LockTimeoutError subclass) keeps this
                # test meaningful against a checkout that has not yet
                # defined that subclass, since what must be proven is that
                # the RETRY LOOP catches the timeout family, not that one
                # specific subclass exists.
                raise RuntimeError("forced test lock timeout")
            return original_lock(fd, timeout=timeout)

        _mod._lock_fd_exclusive = flaky_lock
        try:
            ok = _mod._append_jsonl_safely(log_path, line)
        finally:
            _mod._lock_fd_exclusive = original_lock

        assert ok is True, "a transient lock timeout must not drop the record"
        assert attempts["n"] == 3, (
            "expected exactly two forced timeouts before the real lock "
            f"succeeded on the third attempt, got {attempts['n']}"
        )
        rows = [
            json.loads(raw)
            for raw in log_path.read_text(encoding="utf-8").splitlines()
            if raw.strip()
        ]
        assert [row["session_uuid"] for row in rows] == ["lock-timeout-retry"], rows
        print("PASS test_lock_timeout_retries_with_backoff_and_succeeds")


def test_lock_timeout_gives_up_after_budget_exhausted_without_raising_to_caller():
    """A permanently-contended lock must still fail closed: _append_jsonl_safely
    returns False rather than raising to its caller, and the give-up path
    terminates within a bounded window rather than hanging. Shrinks the
    module's lock-retry budget/per-attempt cap for the duration of the test
    so the exhaustion path resolves quickly and deterministically.

    DS-158 round 3 Minor 1: this is a version-agnostic INVARIANT test (it
    also passes against the pre-round-2 code, verified in an ephemeral
    worktree at base 6701a1c5 with only this test file applied: 1 failed,
    1 passed) - it provides zero regression coverage for round 2 or round
    3's specific fixes. It is deliberately kept loose (elapsed < 5.0) so it
    keeps holding across future budget-shape changes; the tight,
    round-3-specific wall-clock bound lives in
    test_lock_retry_lock_timeout_clamped_to_remaining_budget and
    test_lock_retry_backoff_sleep_clamped_to_remaining_budget below, which
    are the actual regression coverage for Major 1/Major 3 of this round.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        log_path = root / "session-log" / "lock-timeout-exhausted.jsonl"
        log_path.parent.mkdir(parents=True)
        line = json.dumps({"session_uuid": "lock-timeout-exhausted"}, separators=(",", ":"))

        original_lock = _mod._lock_fd_exclusive
        original_budget = getattr(_mod, "SESSION_LOG_LOCK_BUDGET_SECONDS", None)
        original_cap = getattr(
            _mod, "SESSION_LOG_LOCK_PER_ATTEMPT_CAP_SECONDS", None
        )

        def always_timeout(fd, *, timeout):
            raise RuntimeError("forced permanent test lock timeout")

        _mod._lock_fd_exclusive = always_timeout
        # Shrink the budget (when present - round-1 code has no such
        # constant, and the give-up path there is bounded by its own single
        # 5.0s attempt regardless) so this resolves quickly under test.
        if original_budget is not None:
            _mod.SESSION_LOG_LOCK_BUDGET_SECONDS = 0.2
        if original_cap is not None:
            _mod.SESSION_LOG_LOCK_PER_ATTEMPT_CAP_SECONDS = 0.05
        try:
            started = time.monotonic()
            ok = _mod._append_jsonl_safely(log_path, line)
            elapsed = time.monotonic() - started
        finally:
            _mod._lock_fd_exclusive = original_lock
            if original_budget is not None:
                _mod.SESSION_LOG_LOCK_BUDGET_SECONDS = original_budget
            if original_cap is not None:
                _mod.SESSION_LOG_LOCK_PER_ATTEMPT_CAP_SECONDS = original_cap

        assert ok is False, "a permanently-contended lock must fail closed, not raise"
        assert elapsed < 5.0, (
            f"give-up path must not exceed a bounded budget, took {elapsed:.2f}s"
        )
        assert log_path.read_text(encoding="utf-8") == ""
        print(
            "PASS test_lock_timeout_gives_up_after_budget_exhausted_without_raising_to_caller"
        )


class _FakeTimeModule:
    """Deterministic stand-in for the `time` module used by DS-158 round 3's
    total-wall-clock regression tests.

    Rebinding `_mod.time` (not patching attributes on the real stdlib `time`
    module) means only lookups from inside ds-identity's own functions are
    affected - every other module's `import time` binding is untouched, so
    this carries none of the risk of globally freezing `time.monotonic()`
    for the whole test process (e.g. confusing a pytest-timeout watchdog).
    `monotonic()` and `sleep()` are faked against an internal fake clock
    that only ever advances by exactly what `sleep()` is asked to advance
    it by; unrecognized attributes fall through to the real module via
    `__getattr__`.
    """

    def __init__(self, real_time_module):
        self._real = real_time_module
        self._now = 0.0

    def monotonic(self):
        return self._now

    def sleep(self, seconds):
        self._now += seconds

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_hook_ceiling_matches_python_budget():
    """DS-158 round 3 Major 1: the JS caller's spawnSync ceiling must stay
    provably derived from this module's SESSION_LOG_LOCK_BUDGET_SECONDS,
    not merely agree with it by coincidence of two hand-maintained numbers.
    Parses both source files and asserts:
      - hooks/stop-context.js's SESSION_LOG_LOCK_BUDGET_MS (in
        milliseconds) equals SESSION_LOG_LOCK_BUDGET_SECONDS (in seconds)
        here, exactly (no unit-conversion drift).
      - the JS ceiling constant is literally the SUM of that budget
        constant and a named headroom constant (WRITE_HOOK_SPAWN_CEILING_MS
        = SESSION_LOG_LOCK_BUDGET_MS + HELPER_STARTUP_HEADROOM_MS), not a
        third, independently-chosen literal - so bumping the Python budget
        without touching the JS file already breaks this test, and vice
        versa for a JS-side ceiling bump that isn't grounded in these two
        named constants.
    """
    hook_js_path = _REPO_ROOT / "hooks" / "stop-context.js"
    js_source = hook_js_path.read_text(encoding="utf-8")

    budget_ms_match = re.search(
        r"const SESSION_LOG_LOCK_BUDGET_MS\s*=\s*(\d+);", js_source
    )
    headroom_ms_match = re.search(
        r"const HELPER_STARTUP_HEADROOM_MS\s*=\s*(\d+);", js_source
    )
    ceiling_match = re.search(
        r"const WRITE_HOOK_SPAWN_CEILING_MS\s*=\s*"
        r"SESSION_LOG_LOCK_BUDGET_MS\s*\+\s*HELPER_STARTUP_HEADROOM_MS;",
        js_source,
    )
    assert budget_ms_match, (
        "hooks/stop-context.js must define SESSION_LOG_LOCK_BUDGET_MS as a "
        "literal integer constant"
    )
    assert headroom_ms_match, (
        "hooks/stop-context.js must define HELPER_STARTUP_HEADROOM_MS as a "
        "literal integer constant"
    )
    assert ceiling_match, (
        "hooks/stop-context.js's WRITE_HOOK_SPAWN_CEILING_MS must be defined "
        "as the literal sum of SESSION_LOG_LOCK_BUDGET_MS + "
        "HELPER_STARTUP_HEADROOM_MS, not an independent literal"
    )

    budget_ms = int(budget_ms_match.group(1))
    assert budget_ms / 1000.0 == _mod.SESSION_LOG_LOCK_BUDGET_SECONDS, (
        f"hooks/stop-context.js SESSION_LOG_LOCK_BUDGET_MS ({budget_ms}ms) "
        "must equal bin/ds-identity's SESSION_LOG_LOCK_BUDGET_SECONDS "
        f"({_mod.SESSION_LOG_LOCK_BUDGET_SECONDS}s) exactly"
    )

    assert re.search(
        r"timeout:\s*WRITE_HOOK_SPAWN_CEILING_MS,", js_source
    ), (
        "the spawnSync call's `timeout` must reference "
        "WRITE_HOOK_SPAWN_CEILING_MS, not a standalone literal"
    )

    print("PASS test_hook_ceiling_matches_python_budget")


def test_lock_retry_lock_timeout_clamped_to_remaining_budget():
    """DS-158 round 3 Major 3: pins that a single lock attempt's `timeout`
    argument is clamped to the REMAINING shared budget, not the flat
    per-attempt cap. Mutation table (measured against this test):
      - unmutated code                                    -> PASS
      - drop the `lock_deadline - time.monotonic()` term
        from lock_timeout's min(...) (M3)                  -> FAILS

    Uses a fake, deterministic clock (see _FakeTimeModule) rather than real
    wall-clock sleeps, so this test has zero timing-jitter flakiness: the
    mocked lock call advances the fake clock by exactly the `timeout` value
    it was passed (modeling a real flock that blocks for its full timeout
    before giving up), and every other duration in this test is exact
    floating-point addition, not measured real time.

    Budget (0.2s) is deliberately SMALLER than the per-attempt cap (0.4s):
    with the clamp intact, attempt 0's lock_timeout is clipped to the full
    remaining budget (0.2s) and the retry loop gives up immediately after
    (remaining hits exactly 0). Without the clamp, attempt 0 spends the
    full uncapped 0.4s before the same give-up check fires - double the
    correct total.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        log_path = root / "session-log" / "lock-clamp-dev.jsonl"
        log_path.parent.mkdir(parents=True)
        line = json.dumps({"session_uuid": "lock-clamp"}, separators=(",", ":"))

        original_lock = _mod._lock_fd_exclusive
        original_time = _mod.time
        original_budget = _mod.SESSION_LOG_LOCK_BUDGET_SECONDS
        original_cap = _mod.SESSION_LOG_LOCK_PER_ATTEMPT_CAP_SECONDS

        fake_time = _FakeTimeModule(original_time)

        def blocking_timeout(fd, *, timeout):
            # Models a real flock that genuinely blocks for its full
            # timeout before reporting contention - this is what makes the
            # `timeout` argument's own magnitude observable as elapsed
            # wall clock, which is exactly what M3 corrupts.
            fake_time.sleep(timeout)
            raise RuntimeError("forced test lock timeout")

        _mod._lock_fd_exclusive = blocking_timeout
        _mod.time = fake_time
        _mod.SESSION_LOG_LOCK_BUDGET_SECONDS = 0.2
        _mod.SESSION_LOG_LOCK_PER_ATTEMPT_CAP_SECONDS = 0.4
        try:
            ok = _mod._append_jsonl_safely(log_path, line)
            elapsed = fake_time.monotonic()
        finally:
            _mod._lock_fd_exclusive = original_lock
            _mod.time = original_time
            _mod.SESSION_LOG_LOCK_BUDGET_SECONDS = original_budget
            _mod.SESSION_LOG_LOCK_PER_ATTEMPT_CAP_SECONDS = original_cap

        assert ok is False
        assert elapsed < 0.3, (
            "a single lock attempt must be clamped to the remaining shared "
            f"budget (expected ~0.2s), got {elapsed:.4f}s - the per-attempt "
            "cap is winning over the remaining-budget clamp"
        )
        print("PASS test_lock_retry_lock_timeout_clamped_to_remaining_budget")


def test_lock_retry_backoff_sleep_clamped_to_remaining_budget():
    """DS-158 round 3 Major 3: pins that the backoff sleep BETWEEN lock
    retries is clamped to the REMAINING shared budget, not just to its own
    linear-backoff cap. Mutation table (measured against this test):
      - unmutated code                                    -> PASS
      - drop the `remaining` term from the backoff sleep's
        min(...) call (M2)                                 -> FAILS

    Same deterministic fake-clock approach as
    test_lock_retry_lock_timeout_clamped_to_remaining_budget. Here the
    mocked lock call consumes ZERO fake time (an instantaneous EAGAIN-style
    contention), isolating the backoff-sleep clamp from the lock-timeout
    clamp covered by that sibling test - only the backoff `time.sleep(...)`
    calls advance the fake clock.

    Budget (0.12s) is tuned so the second attempt's linear-backoff term
    (0.10s) exceeds the actual remaining budget at that point (0.06s):
    with the clamp intact, that sleep is clipped to 0.06s and the loop
    gives up on the third attempt; without it, the sleep overshoots to the
    full 0.10s, pushing the total past what the clamp would allow.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        log_path = root / "session-log" / "backoff-clamp-dev.jsonl"
        log_path.parent.mkdir(parents=True)
        line = json.dumps({"session_uuid": "backoff-clamp"}, separators=(",", ":"))

        original_lock = _mod._lock_fd_exclusive
        original_time = _mod.time
        original_budget = _mod.SESSION_LOG_LOCK_BUDGET_SECONDS
        original_cap = _mod.SESSION_LOG_LOCK_PER_ATTEMPT_CAP_SECONDS

        fake_time = _FakeTimeModule(original_time)

        def instant_timeout(fd, *, timeout):
            # Zero fake-time cost: isolates the backoff-sleep clamp from
            # the lock-timeout clamp (covered by the sibling test above).
            raise RuntimeError("forced test lock timeout")

        _mod._lock_fd_exclusive = instant_timeout
        _mod.time = fake_time
        _mod.SESSION_LOG_LOCK_BUDGET_SECONDS = 0.12
        _mod.SESSION_LOG_LOCK_PER_ATTEMPT_CAP_SECONDS = 1.0
        try:
            ok = _mod._append_jsonl_safely(log_path, line)
            elapsed = fake_time.monotonic()
        finally:
            _mod._lock_fd_exclusive = original_lock
            _mod.time = original_time
            _mod.SESSION_LOG_LOCK_BUDGET_SECONDS = original_budget
            _mod.SESSION_LOG_LOCK_PER_ATTEMPT_CAP_SECONDS = original_cap

        assert ok is False
        assert elapsed < 0.15, (
            "backoff sleeps must be clamped to the remaining shared budget "
            f"(expected ~0.13s), got {elapsed:.4f}s - the linear-backoff cap "
            "is winning over the remaining-budget clamp"
        )
        print("PASS test_lock_retry_backoff_sleep_clamped_to_remaining_budget")


def test_write_hook_checkpoint_survives_sigkill_mid_global_append():
    """DS-158 round 3 Major 2 regression: the --status-file checkpoint must
    retain a CONFIRMED project outcome, and must NOT assert a global outcome
    it never observed, when the write-hook subprocess is killed while the
    global append is still contended.

    This runs the real `bin/ds-identity write-hook` subcommand as an actual
    subprocess (not an in-process call), holds a real flock on the global
    session log from a second process so the global append genuinely
    blocks/retries, waits for the checkpoint to confirm the project append
    landed, then SIGKILLs the write-hook process mid-global-attempt - the
    exact failure mode the round 3 Skeptic measured against round 2's code
    (project landed on disk, health reported it as failed because the
    process never got to print its final stdout status line).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        subprocess.run(
            ["git", "init", "-q"], cwd=project_dir, check=True,
            capture_output=True,
        )

        dev_id = "sigkill-dev"
        global_identity = fake_home / ".agentic" / "identity.yml"
        _write_identity_file(global_identity, dev_id, provisional=False)

        global_log_path = fake_home / ".agentic" / "session-log" / f"{dev_id}.jsonl"
        global_log_path.parent.mkdir(parents=True, exist_ok=True)
        global_log_path.touch()

        status_file = tmp_path / "status.json"

        env = dict(os.environ)
        env["HOME"] = str(fake_home)
        for key in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
                    "PI_CODING_AGENT_DIR", "AE_IDENTITY_DEBUG"):
            env.pop(key, None)

        locker_ready = tmp_path / "locker-ready"
        locker_release = tmp_path / "locker-release"
        locker_script = (
            "import fcntl, os, sys, time\n"
            f"fd = os.open({str(global_log_path)!r}, os.O_RDONLY)\n"
            "fcntl.flock(fd, fcntl.LOCK_EX)\n"
            f"open({str(locker_ready)!r}, 'w').close()\n"
            f"while not os.path.exists({str(locker_release)!r}):\n"
            "    time.sleep(0.01)\n"
            "os.close(fd)\n"
        )
        locker = subprocess.Popen([sys.executable, "-c", locker_script])
        proc = None
        try:
            deadline = time.monotonic() + 5.0
            while not locker_ready.exists():
                assert time.monotonic() < deadline, "locker never acquired the global lock"
                time.sleep(0.01)

            request = json.dumps({
                "identity": {
                    "developer_id": dev_id,
                    "provisional": False,
                    "identity_scope": "global",
                },
                "session_uuid": "sigkill-session",
                "branch": "main",
                "data": {
                    "wall_seconds": 1,
                    "tokens": {"input": 1, "output": 1, "cache_creation": 0, "cache_read": 0},
                    "spawn_count": 1,
                    "by_agent": {},
                },
            })

            proc = subprocess.Popen(
                [
                    sys.executable, str(_BIN_PATH), "write-hook",
                    "--cwd", str(project_dir),
                    "--status-file", str(status_file),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
            )
            proc.stdin.write(request)
            proc.stdin.close()

            checkpoint_deadline = time.monotonic() + 5.0
            checkpoint_seen = False
            while time.monotonic() < checkpoint_deadline:
                if status_file.exists():
                    try:
                        data = json.loads(status_file.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        data = None
                    if isinstance(data, dict) and data.get("project") is True:
                        checkpoint_seen = True
                        break
                time.sleep(0.02)

            assert checkpoint_seen, (
                "checkpoint must show project:true before the global append "
                "contends against the held lock"
            )

            proc.kill()
            proc.wait(timeout=5)
        finally:
            locker_release.touch()
            locker.wait(timeout=5)
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

        final = json.loads(status_file.read_text(encoding="utf-8"))
        assert final.get("project") is True, (
            f"checkpoint must retain the confirmed project outcome, got {final!r}"
        )
        assert "global" not in final, (
            "checkpoint must NOT contain a global key while the global "
            f"append was still interrupted mid-attempt, got {final!r}"
        )

        project_log = project_dir / ".agentic" / "session-log" / f"{dev_id}.jsonl"
        project_rows = [
            json.loads(line)
            for line in project_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [row["session_uuid"] for row in project_rows] == ["sigkill-session"], project_rows
        print("PASS test_write_hook_checkpoint_survives_sigkill_mid_global_append")


def test_write_hook_anchors_session_log_to_repo_root_from_drifted_cwd():
    """Round-2 rework regression (adversarial review Major 1): write-hook
    previously used the raw harness-payload --cwd verbatim, so a drifted
    cwd (e.g. a stray `cd` into a subdirectory across Bash tool calls)
    produced a PHANTOM `.agentic/session-log/` tree at the subdirectory
    instead of the real repo root - the exact bug class this ticket fixes,
    and the single highest-frequency producer of it since write-hook fires
    on every Stop. Confirmed failing pre-fix: running this test against
    the round-1 code (raw `cwd / ".agentic" / "session-log" / ...`, no
    resolver) writes the session-log line at
    `<project>/deep/nested/dir/.agentic/session-log/<dev>.jsonl` and
    leaves `<project>/.agentic/session-log/` entirely absent.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        subprocess.run(
            ["git", "init", "-q"], cwd=project_dir, check=True,
            capture_output=True,
        )
        drifted_cwd = project_dir / "deep" / "nested" / "dir"
        drifted_cwd.mkdir(parents=True)

        dev_id = "drift-dev"
        global_identity = fake_home / ".agentic" / "identity.yml"
        _write_identity_file(global_identity, dev_id, provisional=False)
        global_log_path = fake_home / ".agentic" / "session-log" / f"{dev_id}.jsonl"
        global_log_path.parent.mkdir(parents=True, exist_ok=True)
        global_log_path.touch()

        env = dict(os.environ)
        env["HOME"] = str(fake_home)
        for key in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
                    "PI_CODING_AGENT_DIR", "AE_IDENTITY_DEBUG"):
            env.pop(key, None)

        request = json.dumps({
            "identity": {
                "developer_id": dev_id,
                "provisional": False,
                "identity_scope": "global",
            },
            "session_uuid": "drift-session",
            "branch": "main",
            "data": {
                "wall_seconds": 1,
                "tokens": {"input": 1, "output": 1, "cache_creation": 0, "cache_read": 0},
                "spawn_count": 1,
                "by_agent": {},
            },
        })

        result = subprocess.run(
            [sys.executable, str(_BIN_PATH), "write-hook", "--cwd", str(drifted_cwd)],
            input=request, capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        status = json.loads(result.stdout)
        assert status.get("project") is True, status

        anchored_log = project_dir / ".agentic" / "session-log" / f"{dev_id}.jsonl"
        drifted_log = drifted_cwd / ".agentic" / "session-log" / f"{dev_id}.jsonl"
        assert anchored_log.is_file(), (
            "write-hook must anchor the session-log write to the repo root "
            f"({project_dir}), not the drifted payload cwd; expected {anchored_log} "
            "to exist"
        )
        assert not drifted_log.exists(), (
            "write-hook must NOT create a phantom .agentic/session-log/ tree "
            f"at the drifted cwd; found one at {drifted_log}"
        )
        rows = [
            json.loads(line)
            for line in anchored_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [row["session_uuid"] for row in rows] == ["drift-session"], rows
        print("PASS test_write_hook_anchors_session_log_to_repo_root_from_drifted_cwd")


def test_write_hook_skips_when_cwd_has_no_git_ancestor():
    """When the harness-payload cwd has no `.git` ancestor at all (e.g. the
    cwd itself was never inside a repo), write-hook must SKIP the write
    entirely rather than falling back to writing `.agentic/session-log/`
    at the raw unresolved cwd - the manifest-mandated discipline in
    hooks/lib/repo_root.py ("callers must treat that as a resolution
    failure and SKIP the write, never silently write at the fallback
    path"). Mirrors hooks/tests/fixtures/repo-root-cases.json's
    "no-git-ancestor-fallback" case setup (an orphan tmp subtree with no
    git_at key)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        orphan_cwd = tmp_path / "orphan" / "deep"
        orphan_cwd.mkdir(parents=True)

        dev_id = "orphan-dev"
        global_identity = fake_home / ".agentic" / "identity.yml"
        _write_identity_file(global_identity, dev_id, provisional=False)

        env = dict(os.environ)
        env["HOME"] = str(fake_home)
        for key in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
                    "PI_CODING_AGENT_DIR", "AE_IDENTITY_DEBUG"):
            env.pop(key, None)

        request = json.dumps({
            "identity": {
                "developer_id": dev_id,
                "provisional": False,
                "identity_scope": "global",
            },
            "session_uuid": "orphan-session",
            "branch": "",
            "data": {
                "wall_seconds": 1,
                "tokens": {"input": 1, "output": 1, "cache_creation": 0, "cache_read": 0},
                "spawn_count": 1,
                "by_agent": {},
            },
        })

        result = subprocess.run(
            [sys.executable, str(_BIN_PATH), "write-hook", "--cwd", str(orphan_cwd)],
            input=request, capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 1, (result.stdout, result.stderr)
        orphan_log = orphan_cwd / ".agentic" / "session-log" / f"{dev_id}.jsonl"
        assert not orphan_log.exists(), (
            f"write-hook must skip the write when no .git ancestor is found, "
            f"found a phantom log at {orphan_log}"
        )
        print("PASS test_write_hook_skips_when_cwd_has_no_git_ancestor")


def test_write_hook_does_not_climb_to_home_agentic_marker():
    """Round-3 rework regression (adversarial review Critical): the orphan
    cwd in test_write_hook_skips_when_cwd_has_no_git_ancestor above is a
    SIBLING of fake_home, so it never exercises the `.agentic/`-marker
    upward walk climbing all the way to $HOME (which always has
    `.agentic/` - it is the global identity/session store). This test
    places the orphan cwd as a DESCENDANT of fake_home instead: no `.git`
    anywhere, and the only `.agentic/` directory findable by an upward
    walk is fake_home's own global store. Before the round-3 fix,
    _resolved_hook_root's second-stage walk climbed past the orphan cwd
    all the way to $HOME and returned it, so write-hook appended a
    fabricated `project_slug` line straight into the REAL global
    session-log file - the exact poisoning the manifest's "skip, never
    fall back" discipline exists to prevent. Confirmed failing pre-fix:
    running this test against the unfixed _resolved_hook_root produced
    returncode 0 (not the required 1) and a `session_total` line bearing
    project_slug == fake_home.name appended to the global session-log."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        # No .git anywhere in this tree - only fake_home/.agentic exists,
        # created below by writing the global identity file into it.
        orphan_cwd = fake_home / "scratchdir" / "deep"
        orphan_cwd.mkdir(parents=True)

        dev_id = "home-climb-dev"
        global_identity = fake_home / ".agentic" / "identity.yml"
        _write_identity_file(global_identity, dev_id, provisional=False)
        global_log_path = fake_home / ".agentic" / "session-log" / f"{dev_id}.jsonl"

        env = dict(os.environ)
        env["HOME"] = str(fake_home)
        for key in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
                    "PI_CODING_AGENT_DIR", "AE_IDENTITY_DEBUG"):
            env.pop(key, None)

        request = json.dumps({
            "identity": {
                "developer_id": dev_id,
                "provisional": False,
                "identity_scope": "project",
            },
            "session_uuid": "home-climb-session",
            "branch": "",
            "data": {
                "wall_seconds": 1,
                "tokens": {"input": 1, "output": 1, "cache_creation": 0, "cache_read": 0},
                "spawn_count": 1,
                "by_agent": {},
            },
        })

        result = subprocess.run(
            [sys.executable, str(_BIN_PATH), "write-hook", "--cwd", str(orphan_cwd)],
            input=request, capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 1, (result.stdout, result.stderr)
        assert not global_log_path.exists(), (
            f"write-hook must never climb an orphan cwd's ancestor tree to "
            f"the global $HOME/.agentic/ store and poison it with a "
            f"fabricated project_slug, found a poisoned global log at "
            f"{global_log_path}"
        )
        print("PASS test_write_hook_does_not_climb_to_home_agentic_marker")


def test_write_hook_rejects_cwd_equal_to_home():
    """Round-4 rework regression (adversarial review Major): unlike the two
    tests above, this one calls write-hook with --cwd pointed AT fake_home
    itself, not a descendant of it. `~/.agentic/` always exists (it is the
    global identity/session store), so raw_cwd == $HOME always satisfies
    _resolved_hook_root's `.agentic/`-marker check - before the round-4 fix,
    $HOME was blessed as its own project root and write-hook wrote a
    project-shaped `session_total` line with a fabricated project_slug of
    the home directory's basename straight into the real global session-log
    file. This is depth-0 of the same corruption the round-3 fix closed one
    level up (an orphan cwd climbing to $HOME); here the cwd IS $HOME.
    Confirmed failing pre-fix: running this test against the unfixed
    _resolved_hook_root produced returncode 0 (not the required 1) and a
    poisoned `session_total` line in the global session-log."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        dev_id = "home-cwd-dev"
        global_identity = fake_home / ".agentic" / "identity.yml"
        _write_identity_file(global_identity, dev_id, provisional=False)
        global_log_path = fake_home / ".agentic" / "session-log" / f"{dev_id}.jsonl"

        env = dict(os.environ)
        env["HOME"] = str(fake_home)
        for key in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
                    "PI_CODING_AGENT_DIR", "AE_IDENTITY_DEBUG"):
            env.pop(key, None)

        request = json.dumps({
            "identity": {
                "developer_id": dev_id,
                "provisional": False,
                "identity_scope": "project",
            },
            "session_uuid": "home-cwd-session",
            "branch": "",
            "data": {
                "wall_seconds": 1,
                "tokens": {"input": 1, "output": 1, "cache_creation": 0, "cache_read": 0},
                "spawn_count": 1,
                "by_agent": {},
            },
        })

        result = subprocess.run(
            [sys.executable, str(_BIN_PATH), "write-hook", "--cwd", str(fake_home)],
            input=request, capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 1, (result.stdout, result.stderr)
        assert not global_log_path.exists(), (
            f"write-hook must never bless $HOME itself as a project root and "
            f"poison the real global $HOME/.agentic/ store with a fabricated "
            f"project_slug, found a poisoned global log at {global_log_path}"
        )
        print("PASS test_write_hook_rejects_cwd_equal_to_home")


def test_missing_log_race_dedups_against_locked_append_fd():
    """The first flush reads UUIDs only after opening and locking the log fd."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        pending_dir, global_log_dir, _ = _patch_paths(root)
        dev_id = "lazy-create-race-dev"
        session_uuid = "uuid-lazy-create-race"
        _write_pending(
            pending_dir,
            {
                "session_uuid": session_uuid,
                "ts": "2026-07-01T00:00:00Z",
                "project_slug": "project",
                "repo_root": "",
                "branch": "main",
                "identity_scope": "global",
                "data": {"tokens": {"total": 1}, "by_agent": {}},
            },
        )
        global_log = global_log_dir / f"{dev_id}.jsonl"
        direct_line = json.dumps(
            {
                "ts": "2026-07-01T00:00:01Z",
                "phase": "session_end",
                "event": "session_total",
                "agent": None,
                "task_id": None,
                "developer_id": dev_id,
                "session_uuid": session_uuid,
                "project_slug": "project",
                "branch": "main",
                "data": {"tokens": {"total": 99}, "by_agent": {}},
            },
            separators=(",", ":"),
        )

        original_open = _mod._open_safe_log_at
        injected = False

        def open_with_direct_writer(parent_fd, name, *, create=False):
            nonlocal injected
            if name == global_log.name and not injected:
                injected = True
                assert _mod._append_jsonl_safely(global_log, direct_line)
                if not create:
                    raise FileNotFoundError(name)
            return original_open(parent_fd, name, create=create)

        _mod._open_safe_log_at = open_with_direct_writer
        try:
            assert flushPendingBuffer(dev_id, scope_filter="global") == 0
        finally:
            _mod._open_safe_log_at = original_open

        rows = [
            json.loads(line)
            for line in global_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        matching = [row for row in rows if row.get("session_uuid") == session_uuid]
        assert len(matching) == 1, matching
        assert matching[0]["data"]["tokens"]["total"] == 99
        assert not (pending_dir / f"{session_uuid}.json").exists()
        print("PASS test_missing_log_race_dedups_against_locked_append_fd")


# ---------------------------------------------------------------------------
# Tests (J): profile scope + 6-tier resolution + env detection + back-compat
# ---------------------------------------------------------------------------

def _patch_environ(set_pairs=None, clear_keys=None):
    """Set/clear env vars; returns a restore thunk (call in finally). Hermetic."""
    set_pairs = set_pairs or {}
    clear_keys = clear_keys or ()
    prev: dict = {}
    added: list[str] = []
    for k in list(clear_keys):
        if k in os.environ:
            prev[k] = os.environ.pop(k)
    for k, v in set_pairs.items():
        if k in os.environ:
            if k not in prev:
                prev[k] = os.environ[k]
        else:
            added.append(k)
        os.environ[k] = v

    def _restore():
        for k in added:
            os.environ.pop(k, None)
        for k, v in prev.items():
            os.environ[k] = v

    return _restore


def test_profile_confirmed_beats_confirmed_global():
    """(J1) confirmed profile beats confirmed global in pass 1."""
    with tempfile.TemporaryDirectory() as tmp, \
            tempfile.TemporaryDirectory(dir=str(Path.home())) as prof:
        tmp_path = Path(tmp)
        cwd = tmp_path / "myrepo"
        cwd.mkdir()
        global_id_path = tmp_path / "global-identity.yml"
        _write_identity_file(global_id_path, "global-dev", provisional=False)
        _write_identity_file(Path(prof) / "identity.yml", "profile-dev", provisional=False)

        restore = _patch_environ(set_pairs={"AGENTIC_CONFIG_DIR": prof},
                                 clear_keys=["CLAUDE_CONFIG_DIR", "CODEX_HOME"])
        orig = _mod.IDENTITY_PATH
        _mod.IDENTITY_PATH = global_id_path
        try:
            result = _resolve_effective_identity(cwd)
        finally:
            _mod.IDENTITY_PATH = orig
            restore()

        assert result is not None, "Expected a resolved identity"
        assert result["developer_id"] == "profile-dev", \
            f"Expected profile-dev, got {result['developer_id']!r}"
        assert result["_scope"] == "profile", f"Expected scope=profile, got {result['_scope']!r}"
        assert result["_confirmed"] is True
        print("PASS test_profile_confirmed_beats_confirmed_global")


def test_project_confirmed_beats_confirmed_profile():
    """(J2) confirmed project beats confirmed profile (project is most specific)."""
    with tempfile.TemporaryDirectory() as tmp, \
            tempfile.TemporaryDirectory(dir=str(Path.home())) as prof:
        tmp_path = Path(tmp)
        cwd = tmp_path / "myrepo"
        cwd.mkdir()
        _write_identity_file(cwd / ".agentic" / "identity.yml", "project-dev", provisional=False)
        _write_identity_file(Path(prof) / "identity.yml", "profile-dev", provisional=False)

        restore = _patch_environ(set_pairs={"AGENTIC_CONFIG_DIR": prof},
                                 clear_keys=["CLAUDE_CONFIG_DIR", "CODEX_HOME"])
        try:
            result = _resolve_effective_identity(cwd)
        finally:
            restore()

        assert result is not None
        assert result["developer_id"] == "project-dev", \
            f"Expected project-dev, got {result['developer_id']!r}"
        assert result["_scope"] == "project", f"Expected scope=project, got {result['_scope']!r}"
        print("PASS test_project_confirmed_beats_confirmed_profile")


def test_confirmed_global_not_suppressed_by_provisional_profile():
    """(J3) provisional profile does NOT suppress a confirmed global."""
    with tempfile.TemporaryDirectory() as tmp, \
            tempfile.TemporaryDirectory(dir=str(Path.home())) as prof:
        tmp_path = Path(tmp)
        cwd = tmp_path / "myrepo"
        cwd.mkdir()
        global_id_path = tmp_path / "global-identity.yml"
        _write_identity_file(global_id_path, "global-dev", provisional=False)
        _write_identity_file(Path(prof) / "identity.yml", "profile-dev", provisional=True)

        restore = _patch_environ(set_pairs={"AGENTIC_CONFIG_DIR": prof},
                                 clear_keys=["CLAUDE_CONFIG_DIR", "CODEX_HOME"])
        orig = _mod.IDENTITY_PATH
        _mod.IDENTITY_PATH = global_id_path
        try:
            result = _resolve_effective_identity(cwd)
        finally:
            _mod.IDENTITY_PATH = orig
            restore()

        assert result is not None
        assert result["developer_id"] == "global-dev", \
            f"Expected global-dev, got {result['developer_id']!r}"
        assert result["_scope"] == "global", f"Expected scope=global, got {result['_scope']!r}"
        assert result["_confirmed"] is True
        print("PASS test_confirmed_global_not_suppressed_by_provisional_profile")


def test_provisional_profile_used_when_no_confirmed_anywhere():
    """(J4) with no project/global and only a provisional profile, pass 2 returns profile."""
    with tempfile.TemporaryDirectory() as tmp, \
            tempfile.TemporaryDirectory(dir=str(Path.home())) as prof:
        tmp_path = Path(tmp)
        cwd = tmp_path / "myrepo"
        cwd.mkdir()
        # Global points to a nonexistent file -> no global identity.
        global_id_path = tmp_path / "absent-global.yml"
        _write_identity_file(Path(prof) / "identity.yml", "profile-dev", provisional=True)

        restore = _patch_environ(set_pairs={"AGENTIC_CONFIG_DIR": prof},
                                 clear_keys=["CLAUDE_CONFIG_DIR", "CODEX_HOME"])
        orig = _mod.IDENTITY_PATH
        _mod.IDENTITY_PATH = global_id_path
        try:
            result = _resolve_effective_identity(cwd)
        finally:
            _mod.IDENTITY_PATH = orig
            restore()

        assert result is not None
        assert result["developer_id"] == "profile-dev", \
            f"Expected profile-dev, got {result['developer_id']!r}"
        assert result["_scope"] == "profile"
        assert result["_confirmed"] is False, "Provisional profile must be _confirmed=False"
        print("PASS test_provisional_profile_used_when_no_confirmed_anywhere")


def test_env_detection_precedence():
    """Profile discovery includes Pi after the shared/Claude/Codex bindings."""
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as a, \
            tempfile.TemporaryDirectory(dir=str(Path.home())) as b, \
            tempfile.TemporaryDirectory(dir=str(Path.home())) as c, \
            tempfile.TemporaryDirectory(dir=str(Path.home())) as d:
        _write_identity_file(Path(a) / "identity.yml", "a-dev")
        _write_identity_file(Path(b) / "identity.yml", "b-dev")
        _write_identity_file(Path(c) / "identity.yml", "c-dev")
        _write_identity_file(Path(d) / "identity.yml", "d-dev")

        # All four set -> AGENTIC_CONFIG_DIR (a) wins.
        restore = _patch_environ(set_pairs={
            "AGENTIC_CONFIG_DIR": a, "CLAUDE_CONFIG_DIR": b,
            "CODEX_HOME": c, "PI_CODING_AGENT_DIR": d})
        try:
            p = _profile_identity_path()
            assert p == Path(a) / "identity.yml", f"Expected A path, got {p}"
        finally:
            restore()

        # AGENTIC cleared -> CLAUDE_CONFIG_DIR (b) wins.
        restore = _patch_environ(set_pairs={
                                     "CLAUDE_CONFIG_DIR": b, "CODEX_HOME": c,
                                     "PI_CODING_AGENT_DIR": d},
                                 clear_keys=["AGENTIC_CONFIG_DIR"])
        try:
            p = _profile_identity_path()
            assert p == Path(b) / "identity.yml", f"Expected B path, got {p}"
        finally:
            restore()

        # CODEX_HOME remains ahead of Pi's native binding.
        restore = _patch_environ(set_pairs={
                                     "CODEX_HOME": c, "PI_CODING_AGENT_DIR": d},
                                 clear_keys=["AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR"])
        try:
            p = _profile_identity_path()
            assert p == Path(c) / "identity.yml", f"Expected C path, got {p}"
        finally:
            restore()

        # Pi's native runtime binding is the final supported fallback.
        restore = _patch_environ(set_pairs={"PI_CODING_AGENT_DIR": d},
                                 clear_keys=[
                                     "AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR",
                                     "CODEX_HOME",
                                 ])
        try:
            p = _profile_identity_path()
            assert p == Path(d) / "identity.yml", f"Expected D path, got {p}"
        finally:
            restore()

        print("PASS test_env_detection_precedence")


def test_profile_dir_outside_home_rejected():
    """(J6) config dir outside $HOME is rejected; profile scope is ignored."""
    with tempfile.TemporaryDirectory() as outside, \
            tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cwd = tmp_path / "myrepo"
        cwd.mkdir()
        global_id_path = tmp_path / "global-identity.yml"
        _write_identity_file(global_id_path, "global-dev", provisional=False)
        # Write a would-be profile identity in the outside-home dir (must be ignored).
        _write_identity_file(Path(outside) / "identity.yml", "intruder-dev", provisional=False)

        restore = _patch_environ(set_pairs={"AGENTIC_CONFIG_DIR": outside},
                                 clear_keys=["CLAUDE_CONFIG_DIR", "CODEX_HOME"])
        orig = _mod.IDENTITY_PATH
        _mod.IDENTITY_PATH = global_id_path
        try:
            assert _profile_identity_path() is None, \
                "Outside-$HOME config dir must yield None"
            result = _resolve_effective_identity(cwd)
        finally:
            _mod.IDENTITY_PATH = orig
            restore()

        assert result is not None
        assert result["developer_id"] == "global-dev", \
            f"Profile outside $HOME must be ignored; got {result['developer_id']!r}"
        assert result["_scope"] == "global"
        print("PASS test_profile_dir_outside_home_rejected")


def test_profile_dir_override():
    """(J7) --profile-dir override is used; outside-$HOME override is rejected."""
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as prof, \
            tempfile.TemporaryDirectory() as outside:
        _write_identity_file(Path(prof) / "identity.yml", "override-dev")
        p = _profile_identity_path(profile_dir=prof)
        assert p == Path(prof) / "identity.yml", f"Override path mismatch: {p}"
        bad = _profile_identity_path(profile_dir=outside)
        assert bad is None, "Outside-$HOME override must be rejected"
        print("PASS test_profile_dir_override")


def test_profile_flush_only_own_config_dir_records():
    """(K1) profile_dir_filter flushes only records tagged with that config_dir."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        mine = {
            "session_uuid": "uuid-prof-mine",
            "ts": "2026-07-01T00:00:00.000Z",
            "project_slug": "p",
            "repo_root": "/repo/p",
            "branch": "main",
            "config_dir": "/home/u/.claude-a",
            "data": {},
        }
        other = {
            "session_uuid": "uuid-prof-other",
            "ts": "2026-07-01T00:01:00.000Z",
            "project_slug": "p",
            "repo_root": "/repo/p",
            "branch": "main",
            "config_dir": "/home/u/.claude-b",
            "data": {},
        }
        untagged = {
            "session_uuid": "uuid-untagged",
            "ts": "2026-07-01T00:02:00.000Z",
            "project_slug": "p",
            "repo_root": "/repo/p",
            "branch": "main",
            "data": {},
        }
        path_mine = _write_pending(pending_dir, mine)
        path_other = _write_pending(pending_dir, other)
        path_untagged = _write_pending(pending_dir, untagged)

        count = flushPendingBuffer("prof-dev", profile_dir_filter="/home/u/.claude-a")
        assert count == 1, f"Expected 1 flushed (own tag only), got {count}"
        assert not path_mine.exists(), "Own-profile record must be flushed"
        assert path_other.exists(), "Other-profile record must remain in buffer"
        assert path_untagged.exists(), "Untagged record must remain under a profile filter"

        global_log = global_log_dir / "prof-dev.jsonl"
        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["session_uuid"] == "uuid-prof-mine"
        assert "config_dir" not in row, \
            "config_dir must NOT appear in canonical session-log line"
        print("PASS test_profile_flush_only_own_config_dir_records")


def test_global_flush_skips_config_dir_tagged_records():
    """(K2) None filter (global confirm) excludes tagged records; they stay pending."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        tagged = {
            "session_uuid": "uuid-tagged-g",
            "ts": "2026-07-01T00:00:00.000Z",
            "project_slug": "p",
            "repo_root": "/repo/p",
            "branch": "main",
            "config_dir": "/home/u/.claude-a",
            "data": {},
        }
        path_tagged = _write_pending(pending_dir, tagged)

        count = flushPendingBuffer("glob-dev")  # no filters
        assert count == 0, f"Expected 0 flushed (tagged record excluded), got {count}"
        assert path_tagged.exists(), \
            "Tagged record must remain in .pending under a global flush"
        print("PASS test_global_flush_skips_config_dir_tagged_records")


def test_profile_flush_rejects_symlinked_filter_spelling():
    """(K4) symlinked profile components are rejected and telemetry is retained."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()  # macOS: /var -> /private/var
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        # Real config tree + a symlinked ancestor pointing at it
        # (Stow/chezmoi-style ~/.config -> dotfiles/config).
        real_parent = tmp_path / "dotfiles" / "config"
        real_cfg = real_parent / "claude"
        real_cfg.mkdir(parents=True)
        link_parent = tmp_path / ".config"
        os.symlink(real_parent, link_parent)
        symlinked_cfg = link_parent / "claude"  # unresolved spelling

        # Legacy record from the former realpath-following writer.
        record = {
            "session_uuid": "uuid-symlink-rt",
            "ts": "2026-07-01T00:00:00.000Z",
            "project_slug": "p",
            "repo_root": "/repo/p",
            "branch": "main",
            "config_dir": str(real_cfg.resolve()),
            "data": {},
        }
        path_rec = _write_pending(pending_dir, record)

        # A symlinked --profile-dir no longer has routing authority.
        count = flushPendingBuffer("rt-dev", profile_dir_filter=str(symlinked_cfg))
        assert count == 0, f"Expected symlinked filter rejection, got {count}"
        assert path_rec.exists(), "Nonmatching-scope telemetry must remain buffered"
        assert not (global_log_dir / "rt-dev.jsonl").exists()
        print("PASS test_profile_flush_rejects_symlinked_filter_spelling")


def test_global_flush_still_attributes_untagged_legacy_records():
    """(K3) untagged legacy records flush unchanged under a global confirm."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        legacy = {
            "session_uuid": "uuid-legacy",
            "ts": "2026-07-01T00:00:00.000Z",
            "project_slug": "p",
            "repo_root": "/repo/p",
            "branch": "main",
            "data": {},
        }
        path_legacy = _write_pending(pending_dir, legacy)

        count = flushPendingBuffer("legacy-dev")
        assert count == 1, f"Expected 1 flushed, got {count}"
        assert not path_legacy.exists(), "Legacy record must be flushed"

        global_log = global_log_dir / "legacy-dev.jsonl"
        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1
        assert json.loads(lines[0])["session_uuid"] == "uuid-legacy"
        print("PASS test_global_flush_still_attributes_untagged_legacy_records")


def test_no_env_profile_scope_absent():
    """(J8) back-compat: with no config-dir env, profile scope is absent (4-tier behavior)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cwd = tmp_path / "myrepo"
        cwd.mkdir()
        global_id_path = tmp_path / "global-identity.yml"
        _write_identity_file(global_id_path, "global-dev", provisional=False)

        restore = _patch_environ(clear_keys=list(_mod.PROFILE_CONFIG_DIR_ENV))
        orig = _mod.IDENTITY_PATH
        _mod.IDENTITY_PATH = global_id_path
        try:
            assert _profile_identity_path() is None
            result = _resolve_effective_identity(cwd)
        finally:
            _mod.IDENTITY_PATH = orig
            restore()

        assert result is not None
        assert result["developer_id"] == "global-dev"
        assert result["_scope"] == "global", \
            f"With no env, scope must be global (no profile); got {result['_scope']!r}"
        print("PASS test_no_env_profile_scope_absent")


# ---------------------------------------------------------------------------
# Tests (M): env-scan contract, symlink escape, mkdir/flush hardening
# ---------------------------------------------------------------------------

def test_env_precedence_nonexistent_highest_wins():
    """(M2) a NOT-yet-created dir in the highest-precedence env var still wins:
    the scan STOPS there (no fall-through to a lower-precedence existing
    profile). Pins the Python contract the JS mirror must match."""
    ghost = Path.home() / f".agentic-ghost-{os.getpid()}"
    assert not ghost.exists(), f"fixture precondition: {ghost} must not exist"
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as existing:
        _write_identity_file(Path(existing) / "identity.yml", "existing-dev")
        restore = _patch_environ(
            set_pairs={"AGENTIC_CONFIG_DIR": str(ghost), "CLAUDE_CONFIG_DIR": existing},
            clear_keys=["CODEX_HOME"])
        try:
            cfg = _profile_config_dir()
        finally:
            restore()
        assert cfg == ghost, \
            f"Nonexistent highest-precedence dir must win (stop scan); got {cfg}"
        # And the derived identity path points into the ghost dir (holds no file).
        restore = _patch_environ(
            set_pairs={"AGENTIC_CONFIG_DIR": str(ghost), "CLAUDE_CONFIG_DIR": existing},
            clear_keys=["CODEX_HOME"])
        try:
            p = _profile_identity_path()
        finally:
            restore()
        assert p == ghost / "identity.yml", f"Expected ghost identity path, got {p}"
        print("PASS test_env_precedence_nonexistent_highest_wins")


def test_tilde_prefixed_env_expanded():
    """(M3) a literal ~-prefixed config-dir env value is expanded to $HOME
    (os.path.expanduser), matching the JS _expandUser mirror. Regression for
    the cross-language divergence where Python expanded ~ but Node resolved it
    to <cwd>/~/... - the two then read different identity.yml for one env var."""
    prof = Path.home() / f".claude-tenant-tilde-{os.getpid()}"
    prof.mkdir()
    try:
        _write_identity_file(prof / "identity.yml", "tilde-dev", provisional=False)
        restore = _patch_environ(
            set_pairs={"AGENTIC_CONFIG_DIR": f"~/{prof.name}"},
            clear_keys=["CLAUDE_CONFIG_DIR", "CODEX_HOME"])
        try:
            cfg = _profile_config_dir()
            p = _profile_identity_path()
        finally:
            restore()
        assert cfg == prof.resolve(), \
            f"~-prefixed env must expand to $HOME/{prof.name}, got {cfg}"
        assert p == prof.resolve() / "identity.yml", f"identity path mismatch: {p}"
    finally:
        (prof / "identity.yml").unlink(missing_ok=True)
        prof.rmdir()
    print("PASS test_tilde_prefixed_env_expanded")

def test_symlink_escape_rejected():
    """(Minor1) a symlink under $HOME pointing OUTSIDE $HOME is rejected by
    the containment check, via both the env scan and --profile-dir.
    Mirrors the JS [SYM] test."""
    link = Path.home() / f".agentic-escape-{os.getpid()}"
    with tempfile.TemporaryDirectory() as outside:
        _write_identity_file(Path(outside) / "identity.yml", "escape-dev")
        os.symlink(outside, link)
        try:
            restore = _patch_environ(
                set_pairs={"AGENTIC_CONFIG_DIR": str(link)},
                clear_keys=["CLAUDE_CONFIG_DIR", "CODEX_HOME"])
            try:
                assert _profile_config_dir() is None, \
                    "Escaping symlink via env must be rejected"
                assert _profile_identity_path() is None
            finally:
                restore()
            assert _profile_identity_path(profile_dir=str(link)) is None, \
                "Escaping symlink via --profile-dir must be rejected"
        finally:
            link.unlink(missing_ok=True)
    print("PASS test_symlink_escape_rejected")


def test_flush_non_string_config_dir_no_crash():
    """(Minor2) a pending record with a non-string config_dir must not crash
    the flush (pre-guard: os.path.realpath(42) raised TypeError). Strict schema
    validation leaves it buffered under every scope."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)

        bad = {
            "session_uuid": "uuid-bad-cfg",
            "ts": "2026-07-09T00:00:00.000Z",
            "project_slug": "p",
            "branch": "main",
            "config_dir": 42,  # malformed: non-string
            "data": {},
        }
        path_bad = _write_pending(pending_dir, bad)

        # Profile filter: no TypeError; record skipped (stays in buffer).
        count = flushPendingBuffer("ns-dev", profile_dir_filter="/home/u/.claude-a")
        assert count == 0, f"Expected 0 flushed under profile filter, got {count}"
        assert path_bad.exists(), "Malformed record must remain in buffer"

        # Global flush: no TypeError; malformed record remains quarantined.
        count = flushPendingBuffer("ns-dev")
        assert count == 0, f"Expected 0 flushed under global flush, got {count}"
        assert path_bad.exists(), "Malformed record must remain quarantined"
        assert not (global_log_dir / "ns-dev.jsonl").exists()
        print("PASS test_flush_non_string_config_dir_no_crash")


# ---------------------------------------------------------------------------
# Tests (L): CLI-level cmd_auto / cmd_confirm --scope profile (subprocess)
# ---------------------------------------------------------------------------

def _cli_env(fake_home: Path, extra_path: Path | None = None) -> dict:
    """Hermetic subprocess env: fake HOME, profile env vars unset."""
    env = dict(os.environ)
    for k in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
              "PI_CODING_AGENT_DIR"):
        env.pop(k, None)
    env["HOME"] = str(fake_home)
    if extra_path is not None:
        env["PATH"] = str(extra_path) + os.pathsep + env.get("PATH", "")
    return env


def _run_cli(args: list[str], env: dict, cwd: Path | None = None):
    """Run the real bin/agentic-identity via subprocess. Returns CompletedProcess."""
    import subprocess
    return subprocess.run(
        [sys.executable, str(_BIN_PATH)] + args,
        capture_output=True, text=True, env=env, cwd=cwd, timeout=30,
    )


def _fake_gh(bin_dir: Path, login: str) -> None:
    """Install a fake `gh` shim printing a fixed login (hermetic cmd_auto)."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\necho {login}\n", encoding="utf-8")
    gh.chmod(0o755)


def _identity_doc_section(start_heading: str, end_heading: str) -> str:
    """Return one command-doc section without pinning its complete prose."""
    text = _IDENTITY_DOC_PATH.read_text(encoding="utf-8")
    start = text.index(start_heading)
    end = text.index(end_heading, start)
    return text[start:end]


def test_docs_show_exit_contract():
    """The show docs distinguish normal absence from rejected profile input."""
    section = _identity_doc_section("### show", "### auto")
    assert "always exits `0`" not in section, \
        "show docs must not promise exit 0 for rejected --profile-dir"
    assert "absent identity" in section and "exits `0`" in section, \
        "show docs must state that an absent identity is a successful query"
    assert "rejected explicit" in section \
        and "`--profile-dir` returns exit `1`" in section, \
        "show docs must state that a rejected explicit --profile-dir exits 1"


def test_docs_confirm_already_confirmed_flush_contract():
    """Already-confirmed confirm preserves identity bytes but still flushes."""
    section = _identity_doc_section("### confirm", "## Provisional model")
    assert "already confirmed, `confirm` is a no-op" not in section, \
        "confirm docs must not call the already-confirmed path a no-op"
    assert "identity file remains unchanged" in section, \
        "confirm docs must state that confirmed identity bytes stay unchanged"
    assert "pending routing and flush still run" in section, \
        "confirm docs must state that pending telemetry is still routed/flushed"
    assert "already confirmed" in section and "exits `0`" in section, \
        "confirm docs must state the already-confirmed exit behavior"


def test_cli_auto_profile_writes_provisional():
    """(L1) `auto --scope profile --profile-dir <dir>` writes a provisional
    identity.yml under the profile dir (real CLI, fake $HOME + fake gh)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        fake_bin = tmp_path / "fakebin"
        _fake_gh(fake_bin, "auto-dev")
        env = _cli_env(fake_home, extra_path=fake_bin)

        r = _run_cli(["auto", "--scope", "profile", "--profile-dir", str(prof)], env)
        assert r.returncode == 0, f"auto failed: rc={r.returncode} stderr={r.stderr}"
        content = (prof / "identity.yml").read_text(encoding="utf-8")
        assert "developer_id: auto-dev" in content
        assert "provisional: true" in content
        assert "derived_from: gh" in content
        print("PASS test_cli_auto_profile_writes_provisional")


def test_cli_auto_profile_confirmed_rejected_without_force():
    """(L2) `auto --scope profile` over an already-CONFIRMED profile identity
    without --force is rejected (exit 2, message, identity unchanged)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        _write_identity_file(prof / "identity.yml", "settled-dev", provisional=False)
        before = (prof / "identity.yml").read_text(encoding="utf-8")
        fake_bin = tmp_path / "fakebin"
        _fake_gh(fake_bin, "usurper-dev")
        env = _cli_env(fake_home, extra_path=fake_bin)

        r = _run_cli(["auto", "--scope", "profile", "--profile-dir", str(prof)], env)
        assert r.returncode == 2, f"Expected rc=2, got {r.returncode} stderr={r.stderr}"
        assert "confirmed profile identity already set" in r.stderr, \
            f"Missing rejection message: {r.stderr!r}"
        after = (prof / "identity.yml").read_text(encoding="utf-8")
        assert after == before, "Identity file must be unchanged on rejection"
        print("PASS test_cli_auto_profile_confirmed_rejected_without_force")


def test_cli_confirm_profile_flushes_tagged_pending():
    """(L3) `confirm --scope profile` end-to-end: strips provisional AND
    flushes the pending record tagged with THAT profile's config_dir while
    leaving other-profile records in the buffer. A wiring bug in
    cmd_confirm's profile branch (wrong getattr dest, wrong filter path)
    fails this test."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        other_prof = fake_home / ".claude-other"
        _write_identity_file(prof / "identity.yml", "flush-dev", provisional=True)

        pending_dir = fake_home / ".agentic" / "session-log" / ".pending"
        mine = {
            "session_uuid": "uuid-cli-mine",
            "ts": "2026-07-09T00:00:00.000Z",
            "project_slug": "p",
            "branch": "main",
            "config_dir": str(prof),
            "data": {},
        }
        other = {
            "session_uuid": "uuid-cli-other",
            "ts": "2026-07-09T00:01:00.000Z",
            "project_slug": "p",
            "branch": "main",
            "config_dir": str(other_prof),
            "data": {},
        }
        path_mine = _write_pending(pending_dir, mine)
        path_other = _write_pending(pending_dir, other)

        env = _cli_env(fake_home)
        r = _run_cli(["confirm", "--scope", "profile", "--profile-dir", str(prof)], env)
        assert r.returncode == 0, f"confirm failed: rc={r.returncode} stderr={r.stderr}"

        content = (prof / "identity.yml").read_text(encoding="utf-8")
        assert "provisional" not in content, "provisional must be stripped on confirm"

        assert not path_mine.exists(), \
            "Pending record tagged with THIS profile dir must be flushed"
        assert path_other.exists(), \
            "Other-profile record must remain in the buffer"
        global_log = fake_home / ".agentic" / "session-log" / "flush-dev.jsonl"
        assert global_log.is_file(), "Global log must be written by the flush"
        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["session_uuid"] == "uuid-cli-mine"
        assert row["developer_id"] == "flush-dev"
        print("PASS test_cli_confirm_profile_flushes_tagged_pending")


def test_cli_confirm_project_with_active_profile_flushes_own_pending():
    """Project confirmation flushes its record under the active profile only.

    The Stop hook tags every pending record with the active profile config dir.
    Project confirmation must combine the repo-root and active-profile filters:
    flush this project's record, but preserve both another profile's record for
    the same project and this profile's record for another project.
    """
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        other_prof = fake_home / ".claude-other"
        project = tmp_path / "project"
        other_project = tmp_path / "other-project"
        project.mkdir()
        other_project.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(project)],
            check=True, capture_output=True, text=True,
        )
        _write_identity_file(
            project / ".agentic" / "identity.yml",
            "project-flush-dev",
            provisional=True,
        )

        pending_dir = fake_home / ".agentic" / "session-log" / ".pending"
        mine = {
            "session_uuid": "uuid-project-profile-mine",
            "ts": "2026-07-09T00:00:00.000Z",
            "project_slug": "project",
            "repo_root": str(project),
            "branch": "main",
            "config_dir": str(prof),
            "data": {},
        }
        other_profile = {
            "session_uuid": "uuid-project-other-profile",
            "ts": "2026-07-09T00:01:00.000Z",
            "project_slug": "project",
            "repo_root": str(project),
            "branch": "main",
            "config_dir": str(other_prof),
            "data": {},
        }
        other_repo = {
            "session_uuid": "uuid-profile-other-project",
            "ts": "2026-07-09T00:02:00.000Z",
            "project_slug": "other-project",
            "repo_root": str(other_project),
            "branch": "main",
            "config_dir": str(prof),
            "data": {},
        }
        path_mine = _write_pending(pending_dir, mine)
        path_other_profile = _write_pending(pending_dir, other_profile)
        path_other_repo = _write_pending(pending_dir, other_repo)

        env = _cli_env(fake_home)
        env["AGENTIC_CONFIG_DIR"] = str(prof)
        r = _run_cli(["confirm", "--scope", "project"], env, cwd=project)
        assert r.returncode == 0, \
            f"project confirm failed: rc={r.returncode} stderr={r.stderr}"

        assert not path_mine.exists(), \
            "Project record tagged with the active profile must be flushed"
        assert path_other_profile.exists(), \
            "Same-project record from another profile must remain buffered"
        assert path_other_repo.exists(), \
            "Same-profile record from another project must remain buffered"

        global_log = (
            fake_home / ".agentic" / "session-log" / "project-flush-dev.jsonl"
        )
        assert global_log.is_file(), "Project confirmation must write the global log"
        rows = [
            json.loads(line)
            for line in global_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [row["session_uuid"] for row in rows] == [
            "uuid-project-profile-mine"
        ]
        print(
            "PASS "
            "test_cli_confirm_project_with_active_profile_flushes_own_pending"
        )


def test_cli_confirm_global_preserves_profile_pending():
    """Global confirmation flushes only untagged records.

    Records tagged for either active profile remain buffered until that
    profile is confirmed, proving global confirmation cannot consume across
    profile boundaries.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof_a = fake_home / ".claude-a"
        prof_b = fake_home / ".claude-b"
        _write_identity_file(
            fake_home / ".agentic" / "identity.yml",
            "global-flush-dev",
            provisional=True,
        )

        pending_dir = fake_home / ".agentic" / "session-log" / ".pending"
        untagged = {
            "session_uuid": "uuid-global-untagged",
            "ts": "2026-07-09T00:00:00.000Z",
            "project_slug": "project",
            "repo_root": "/repo/project",
            "branch": "main",
            "data": {},
        }
        tagged_a = {
            "session_uuid": "uuid-global-profile-a",
            "ts": "2026-07-09T00:01:00.000Z",
            "project_slug": "project",
            "repo_root": "/repo/project",
            "branch": "main",
            "config_dir": str(prof_a),
            "data": {},
        }
        tagged_b = {
            "session_uuid": "uuid-global-profile-b",
            "ts": "2026-07-09T00:02:00.000Z",
            "project_slug": "project",
            "repo_root": "/repo/project",
            "branch": "main",
            "config_dir": str(prof_b),
            "data": {},
        }
        path_untagged = _write_pending(pending_dir, untagged)
        path_tagged_a = _write_pending(pending_dir, tagged_a)
        path_tagged_b = _write_pending(pending_dir, tagged_b)

        env = _cli_env(fake_home)
        r = _run_cli(["confirm", "--scope", "global"], env)
        assert r.returncode == 0, \
            f"global confirm failed: rc={r.returncode} stderr={r.stderr}"

        assert not path_untagged.exists(), \
            "Untagged pending record must flush under global confirmation"
        assert path_tagged_a.exists(), \
            "Profile A record must remain buffered after global confirmation"
        assert path_tagged_b.exists(), \
            "Profile B record must remain buffered after global confirmation"

        global_log = (
            fake_home / ".agentic" / "session-log" / "global-flush-dev.jsonl"
        )
        rows = [
            json.loads(line)
            for line in global_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [row["session_uuid"] for row in rows] == [
            "uuid-global-untagged"
        ]
        print("PASS test_cli_confirm_global_preserves_profile_pending")


def test_cli_confirm_already_confirmed_profile_preserves_bytes_and_flushes():
    """Profile confirm must preserve confirmed YAML bytes while routing its pending."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        other_prof = fake_home / ".claude-other"
        identity_path = prof / "identity.yml"
        before = _write_noncanonical_confirmed_identity(
            identity_path,
            "profile-byte-dev",
        )

        pending_dir = fake_home / ".agentic" / "session-log" / ".pending"
        mine = _write_pending(
            pending_dir,
            {
                "session_uuid": "uuid-confirmed-profile-mine",
                "ts": "2026-07-09T00:00:00.000Z",
                "project_slug": "project",
                "branch": "main",
                "config_dir": str(prof),
                "data": {},
            },
        )
        other = _write_pending(
            pending_dir,
            {
                "session_uuid": "uuid-confirmed-profile-other",
                "ts": "2026-07-09T00:01:00.000Z",
                "project_slug": "project",
                "branch": "main",
                "config_dir": str(other_prof),
                "data": {},
            },
        )

        env = _cli_env(fake_home)
        result = _run_cli(
            ["confirm", "--scope", "profile", "--profile-dir", str(prof)],
            env,
        )

        assert result.returncode == 0, result.stderr
        assert identity_path.read_bytes() == before, \
            "Already-confirmed profile identity bytes must remain exact"
        assert not mine.exists(), "Matching profile pending record must flush"
        assert other.exists(), "Other-profile pending record must remain buffered"
        _assert_single_flushed_record(
            fake_home,
            "profile-byte-dev",
            "uuid-confirmed-profile-mine",
        )
        print(
            "PASS "
            "test_cli_confirm_already_confirmed_profile_preserves_bytes_and_flushes"
        )


def test_cli_confirm_already_confirmed_project_preserves_bytes_and_flushes():
    """Project confirm must preserve confirmed YAML bytes while routing its pending."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        project = tmp_path / "project"
        other_project = tmp_path / "other-project"
        project.mkdir()
        other_project.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(project)],
            check=True,
            capture_output=True,
            text=True,
        )
        identity_path = project / ".agentic" / "identity.yml"
        before = _write_noncanonical_confirmed_identity(
            identity_path,
            "project-byte-dev",
        )

        pending_dir = fake_home / ".agentic" / "session-log" / ".pending"
        mine = _write_pending(
            pending_dir,
            {
                "session_uuid": "uuid-confirmed-project-mine",
                "ts": "2026-07-09T00:00:00.000Z",
                "project_slug": "project",
                "repo_root": str(project),
                "branch": "main",
                "config_dir": str(prof),
                "data": {},
            },
        )
        other = _write_pending(
            pending_dir,
            {
                "session_uuid": "uuid-confirmed-project-other",
                "ts": "2026-07-09T00:01:00.000Z",
                "project_slug": "other-project",
                "repo_root": str(other_project),
                "branch": "main",
                "config_dir": str(prof),
                "data": {},
            },
        )

        env = _cli_env(fake_home)
        env["AGENTIC_CONFIG_DIR"] = str(prof)
        result = _run_cli(["confirm", "--scope", "project"], env, cwd=project)

        assert result.returncode == 0, result.stderr
        assert identity_path.read_bytes() == before, \
            "Already-confirmed project identity bytes must remain exact"
        assert not mine.exists(), "Matching project pending record must flush"
        assert other.exists(), "Other-project pending record must remain buffered"
        _assert_single_flushed_record(
            fake_home,
            "project-byte-dev",
            "uuid-confirmed-project-mine",
        )
        project_log = (
            project
            / ".agentic"
            / "session-log"
            / "project-byte-dev.jsonl"
        )
        assert project_log.is_file(), "Project confirmation must write the project log"
        project_row = json.loads(project_log.read_text(encoding="utf-8").strip())
        assert project_row["session_uuid"] == "uuid-confirmed-project-mine"
        print(
            "PASS "
            "test_cli_confirm_already_confirmed_project_preserves_bytes_and_flushes"
        )


def test_cli_confirm_already_confirmed_global_preserves_bytes_and_flushes():
    """Global confirm must preserve confirmed YAML bytes while routing its pending."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        identity_path = fake_home / ".agentic" / "identity.yml"
        before = _write_noncanonical_confirmed_identity(
            identity_path,
            "global-byte-dev",
        )

        pending_dir = fake_home / ".agentic" / "session-log" / ".pending"
        mine = _write_pending(
            pending_dir,
            {
                "session_uuid": "uuid-confirmed-global-mine",
                "ts": "2026-07-09T00:00:00.000Z",
                "project_slug": "project",
                "branch": "main",
                "data": {},
            },
        )
        tagged = _write_pending(
            pending_dir,
            {
                "session_uuid": "uuid-confirmed-global-tagged",
                "ts": "2026-07-09T00:01:00.000Z",
                "project_slug": "project",
                "branch": "main",
                "config_dir": str(prof),
                "data": {},
            },
        )

        env = _cli_env(fake_home)
        result = _run_cli(["confirm", "--scope", "global"], env)

        assert result.returncode == 0, result.stderr
        assert identity_path.read_bytes() == before, \
            "Already-confirmed global identity bytes must remain exact"
        assert not mine.exists(), "Untagged global pending record must flush"
        assert tagged.exists(), "Profile-tagged pending record must remain buffered"
        _assert_single_flushed_record(
            fake_home,
            "global-byte-dev",
            "uuid-confirmed-global-mine",
        )
        print(
            "PASS "
            "test_cli_confirm_already_confirmed_global_preserves_bytes_and_flushes"
        )


def test_cli_confirm_profile_no_identity_errors():
    """(L4) `confirm --scope profile` with no profile identity exits 1 with a
    clear message (no traceback)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        env = _cli_env(fake_home)

        r = _run_cli(["confirm", "--scope", "profile", "--profile-dir", str(prof)], env)
        assert r.returncode == 1, f"Expected rc=1, got {r.returncode}"
        assert "no profile identity set" in r.stderr
        assert "Traceback" not in r.stderr
        print("PASS test_cli_confirm_profile_no_identity_errors")


def test_cli_profile_dir_is_regular_file_clean_error():
    """(Med) --profile-dir pointing at an existing regular file exits 1 with a
    clean message - the mkdir failure must not escape as a traceback."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        not_a_dir = fake_home / "notadir"
        not_a_dir.write_text("i am a file\n", encoding="utf-8")
        env = _cli_env(fake_home)

        r = _run_cli(
            ["init", "tester", "--scope", "profile", "--profile-dir", str(not_a_dir)],
            env)
        assert r.returncode == 1, \
            f"Expected rc=1, got {r.returncode} stderr={r.stderr!r}"
        assert "cannot create profile dir" in r.stderr, \
            f"Missing clean error message: {r.stderr!r}"
        assert "Traceback" not in r.stderr, f"Traceback leaked: {r.stderr!r}"
        print("PASS test_cli_profile_dir_is_regular_file_clean_error")

def test_cli_init_profile_happy_path():
    """(L5) `init <handle> --scope profile --profile-dir <dir>` writes a
    NON-provisional identity.yml (exit 0). Only the mkdir-failure branch of
    init was covered before - this pins the success path."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        env = _cli_env(fake_home)

        r = _run_cli(["init", "prof-init-dev", "--scope", "profile",
                      "--profile-dir", str(prof)], env)
        assert r.returncode == 0, f"init failed: rc={r.returncode} stderr={r.stderr}"
        content = (prof / "identity.yml").read_text(encoding="utf-8")
        assert "developer_id: prof-init-dev" in content
        assert "provisional" not in content, \
            "init writes a confirmed (non-provisional) identity"
        print("PASS test_cli_init_profile_happy_path")

def test_cli_init_profile_force_overwrites_confirmed():
    """(L6) `init --scope profile --force` overwrites an already-CONFIRMED
    profile identity; without --force it is rejected (exit 2)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        _write_identity_file(prof / "identity.yml", "old-dev", provisional=False)
        env = _cli_env(fake_home)

        # No --force over a confirmed identity -> rejected, unchanged.
        r = _run_cli(["init", "new-dev", "--scope", "profile",
                      "--profile-dir", str(prof)], env)
        assert r.returncode == 2, f"Expected rc=2, got {r.returncode} stderr={r.stderr}"
        assert "developer_id: old-dev" in (prof / "identity.yml").read_text(encoding="utf-8"), \
            "Identity must be unchanged without --force"

        # --force -> overwrite succeeds.
        r = _run_cli(["init", "new-dev", "--scope", "profile", "--force",
                      "--profile-dir", str(prof)], env)
        assert r.returncode == 0, f"--force init failed: rc={r.returncode} stderr={r.stderr}"
        content = (prof / "identity.yml").read_text(encoding="utf-8")
        assert "developer_id: new-dev" in content, "Identity must be overwritten with --force"
        print("PASS test_cli_init_profile_force_overwrites_confirmed")

def test_cli_show_profile_three_paths():
    """(L7) `show --scope profile` command-level coverage of its three print
    paths: no config-dir/no --profile-dir; --profile-dir set but no identity;
    identity present. Only the underlying helpers were unit-tested before."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        env = _cli_env(fake_home)  # profile env vars stripped

        # Path 1: no config-dir env, no --profile-dir -> "No profile scope..."
        r = _run_cli(["show", "--scope", "profile"], env)
        assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr}"
        assert "No profile scope" in r.stdout, f"stdout={r.stdout!r}"

        # Path 2: --profile-dir set but no identity file -> "No identity at profile scope."
        r = _run_cli(["show", "--scope", "profile", "--profile-dir", str(prof)], env)
        assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr}"
        assert "No identity at profile scope" in r.stdout, f"stdout={r.stdout!r}"

        # Path 3: identity present -> developer_id printed.
        _write_identity_file(prof / "identity.yml", "shown-dev", provisional=False)
        r = _run_cli(["show", "--scope", "profile", "--profile-dir", str(prof)], env)
        assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr}"
        assert "developer_id:  shown-dev" in r.stdout, f"stdout={r.stdout!r}"
        print("PASS test_cli_show_profile_three_paths")

def test_cross_language_profile_resolution_agrees():
    """(X1) Python (`agentic-identity show --scope effective`) and JS
    (`stop-context.js`) resolve the SAME winning identity on ONE identical
    fixture. Nothing else diffs their real output on the same input, so a
    precedence/containment change on one side unmirrored on the other would
    ship silently. Uses AGENTIC_CONFIG_DIR -> a profile dir under $HOME with a
    confirmed profile identity that must beat a confirmed global identity."""
    import subprocess
    js_hook = _BIN_PATH.parent.parent / "hooks" / "stop-context.js"
    if not js_hook.is_file():
        print("SKIP test_cross_language_profile_resolution_agrees (no JS hook)")
        return

    with tempfile.TemporaryDirectory() as tmp:
        # realpath tmp: macOS mkdtemp yields /var -> /private/var; both sides
        # realpath $HOME, so the fixture must live under the resolved spelling.
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        prof = fake_home / ".claude-tenant"
        project = tmp_path / "project"
        (project / ".agentic").mkdir(parents=True)
        # Confirmed global + confirmed profile: profile must win at both sides.
        _write_identity_file(fake_home / ".agentic" / "identity.yml",
                             "global-dev", provisional=False)
        _write_identity_file(prof / "identity.yml", "profile-dev", provisional=False)

        env = dict(os.environ)
        for k in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
                  "PI_CODING_AGENT_DIR"):
            env.pop(k, None)
        env["HOME"] = str(fake_home)
        env["AGENTIC_CONFIG_DIR"] = str(prof)

        # Python side: `show --scope effective` reports the resolved scope+id.
        py = subprocess.run(
            [sys.executable, str(_BIN_PATH), "show", "--scope", "effective"],
            capture_output=True, text=True, env=env, cwd=str(project), timeout=30)
        assert py.returncode == 0, f"py show failed: {py.stderr}"
        assert "developer_id:  profile-dev" in py.stdout, \
            f"Python did not resolve profile-dev: {py.stdout!r}"
        assert "scope:         profile" in py.stdout, \
            f"Python scope not profile: {py.stdout!r}"

        # JS side: run the hook; it writes a per-project session log keyed by
        # the winning developer_id. profile-dev winning => that log exists,
        # global-dev's does not.
        payload = json.dumps({"cwd": str(project), "session_id": "x1-uuid",
                              "transcript": []})
        js = subprocess.run(
            ["node", str(js_hook)], input=payload, capture_output=True, text=True,
            env=env, timeout=30)
        assert js.returncode == 0, f"js hook failed: {js.stderr}"
        js_log = project / ".agentic" / "session-log" / "profile-dev.jsonl"
        js_log_global = project / ".agentic" / "session-log" / "global-dev.jsonl"
        assert js_log.is_file(), \
            f"JS did not resolve profile-dev (no {js_log}); stderr={js.stderr}"
        assert not js_log_global.is_file(), \
            "JS resolved global-dev but Python resolved profile-dev (divergence)"
        print("PASS test_cross_language_profile_resolution_agrees")


def test_cross_language_unsafe_profile_candidate_falls_through():
    """Python and Node reject unsafe high candidates before profile selection.

    The table covers every precedence variable as either the unsafe high
    candidate or the safe lower candidate. The first row is the exact
    AGENTIC_CONFIG_DIR -> CLAUDE_CONFIG_DIR telemetry regression.
    """
    import subprocess

    js_hook = _BIN_PATH.parent.parent / "hooks" / "stop-context.js"
    if not js_hook.is_file():
        print("SKIP test_cross_language_unsafe_profile_candidate_falls_through "
              "(no JS hook)")
        return

    cases = (
        ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "lower-confirmed"),
        ("AGENTIC_CONFIG_DIR", "CODEX_HOME", "codex-lower-confirmed"),
        ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "codex-fallback-confirmed"),
    )
    for index, (unsafe_var, safe_var, expected_id) in enumerate(cases):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            bad_target = fake_home / f"bad-target-{index}"
            bad_target.mkdir()
            bad_profile = fake_home / "bad-profile"
            bad_profile.symlink_to(bad_target, target_is_directory=True)
            real_profile = fake_home / "real-profile"
            project = tmp_path / "project"
            (project / ".agentic").mkdir(parents=True)
            _write_identity_file(
                fake_home / ".agentic" / "identity.yml",
                "global-prov",
                provisional=True,
            )
            _write_identity_file(
                real_profile / "identity.yml",
                expected_id,
                provisional=False,
            )

            env = dict(os.environ)
            for key in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
                        "PI_CODING_AGENT_DIR"):
                env.pop(key, None)
            env["HOME"] = str(fake_home)
            env[unsafe_var] = str(bad_profile)
            env[safe_var] = str(real_profile)

            py = subprocess.run(
                [sys.executable, str(_BIN_PATH), "show", "--scope", "effective"],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(project),
                timeout=30,
            )
            assert py.returncode == 0, (
                f"{unsafe_var}->{safe_var} Python show failed: {py.stderr}"
            )
            assert f"developer_id:  {expected_id}" in py.stdout, (
                f"{unsafe_var}->{safe_var} Python selected wrong identity: "
                f"{py.stdout!r}"
            )
            assert "scope:         profile" in py.stdout, (
                f"{unsafe_var}->{safe_var} Python scope not profile: {py.stdout!r}"
            )

            payload = json.dumps({
                "cwd": str(project),
                "session_id": f"unsafe-fallthrough-{index}",
                "transcript": [],
            })
            js = subprocess.run(
                ["node", str(js_hook)],
                input=payload,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            assert js.returncode == 0, (
                f"{unsafe_var}->{safe_var} Node hook failed: {js.stderr}"
            )
            expected_log = (
                project / ".agentic" / "session-log" / f"{expected_id}.jsonl"
            )
            assert expected_log.is_file(), (
                f"{unsafe_var}->{safe_var} Node did not select {expected_id}"
            )
            assert not (
                project / ".agentic" / "session-log" / "global-prov.jsonl"
            ).exists(), (
                f"{unsafe_var}->{safe_var} Node selected global provisional"
            )
            pending_dir = (
                fake_home / ".agentic" / "session-log" / ".pending"
            )
            pending = list(pending_dir.glob("*.json")) if pending_dir.exists() else []
            assert not pending, (
                f"{unsafe_var}->{safe_var} created pending global-scope records: "
                f"{pending}"
            )

    print("PASS test_cross_language_unsafe_profile_candidate_falls_through")


def test_cli_invalid_parsed_handles_cannot_escape_session_log():
    """Parsed identity handles are revalidated before any flush path is built."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        identity_path = fake_home / ".agentic" / "identity.yml"
        pending_dir = fake_home / ".agentic" / "session-log" / ".pending"
        env = _cli_env(fake_home)

        cases = (
            (str(tmp_path / "absolute-escape"), tmp_path / "absolute-escape.jsonl"),
            ("../../traversal-escape", fake_home / "traversal-escape.jsonl"),
            ("InvalidUpper", fake_home / ".agentic" / "session-log" / "InvalidUpper.jsonl"),
        )
        for index, (handle, escaped_path) in enumerate(cases):
            identity_path.parent.mkdir(parents=True, exist_ok=True)
            identity_path.write_text(
                f"developer_id: {handle}\ncreated_at: 2026-01-01T00:00:00Z\n",
                encoding="utf-8",
            )
            pending_path = _write_pending(
                pending_dir,
                {
                    "session_uuid": f"invalid-handle-{index}",
                    "ts": "2026-07-25T00:00:00Z",
                    "project_slug": "project",
                    "branch": "main",
                    "data": {},
                },
            )

            result = _run_cli(["confirm", "--scope", "global"], env)

            assert result.returncode == 1, (
                f"Invalid parsed handle {handle!r} must fail closed: "
                f"rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            assert "Traceback" not in result.stderr
            assert pending_path.exists(), "Rejected identity must not consume pending telemetry"
            assert not escaped_path.exists(), (
                f"Invalid parsed handle created a log outside session-log: {escaped_path}"
            )
            pending_path.unlink()
        print("PASS test_cli_invalid_parsed_handles_cannot_escape_session_log")


def test_cli_identity_reads_reject_symlink_and_non_regular_targets():
    """Global, project, and profile reads reject final symlinks and directories."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(project)],
            check=True,
            capture_output=True,
            text=True,
        )
        profile = fake_home / ".claude-tenant"
        env = _cli_env(fake_home)

        scope_targets = (
            ("global", fake_home / ".agentic" / "identity.yml", None, None),
            ("project", project / ".agentic" / "identity.yml", project, None),
            ("profile", profile / "identity.yml", None, profile),
        )
        for scope, target, cwd, profile_dir in scope_targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            real_identity = tmp_path / f"{scope}-real-identity.yml"
            _write_identity_file(real_identity, f"{scope}-symlink-dev")
            target.symlink_to(real_identity)
            args = ["show", "--scope", scope]
            if profile_dir is not None:
                args += ["--profile-dir", str(profile_dir)]
            result = _run_cli(args, env, cwd=cwd)
            assert result.returncode in (0, 1)
            assert f"{scope}-symlink-dev" not in result.stdout, (
                f"{scope} final identity symlink was followed"
            )
            target.unlink()

            target.mkdir()
            result = _run_cli(args, env, cwd=cwd)
            assert result.returncode in (0, 1)
            assert "Traceback" not in result.stderr
            target.rmdir()
        print("PASS test_cli_identity_reads_reject_symlink_and_non_regular_targets")


def test_cli_identity_read_invalid_utf8_is_bounded():
    """Invalid UTF-8 returns the normal absent result without traceback."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        identity_path = fake_home / ".agentic" / "identity.yml"
        identity_path.parent.mkdir(parents=True)
        env = _cli_env(fake_home)

        identity_path.write_bytes(b"developer_id: utf8-dev\n\xff\n")
        result = _run_cli(["show", "--scope", "global"], env)
        assert result.returncode == 0
        assert "utf8-dev" not in result.stdout
        assert "Traceback" not in result.stderr
        print("PASS test_cli_identity_read_invalid_utf8_is_bounded")


def test_cli_identity_read_unreadable_file_is_bounded():
    """An unreadable identity returns the normal absent result without traceback."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        identity_path = fake_home / ".agentic" / "identity.yml"
        identity_path.parent.mkdir(parents=True)
        env = _cli_env(fake_home)
        identity_path.write_text("developer_id: unreadable-dev\n", encoding="utf-8")
        identity_path.chmod(0)
        try:
            result = _run_cli(["show", "--scope", "global"], env)
        finally:
            identity_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        assert result.returncode == 0
        assert "unreadable-dev" not in result.stdout
        assert "Traceback" not in result.stderr
        print("PASS test_cli_identity_read_unreadable_file_is_bounded")


def test_concurrent_provisional_confirm_is_atomic_and_routes_winner():
    """Two confirmations cannot share temp bytes or attribute to the losing handle."""
    import subprocess
    import textwrap

    worker = textwrap.dedent(
        """
        import importlib.machinery
        import importlib.util
        import os
        import sys
        import time
        from pathlib import Path

        module_path, target_raw, start_raw, handle, marker = sys.argv[1:]
        loader = importlib.machinery.SourceFileLoader("agentic_identity_worker", module_path)
        spec = importlib.util.spec_from_loader("agentic_identity_worker", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        start = Path(start_raw)
        while not start.exists():
            time.sleep(0.001)
        identity = {
            "developer_id": handle,
            "display_name": marker * 2000000,
            "created_at": f"2026-07-25T00:00:0{marker}Z",
            "provisional": True,
        }
        rc = mod._confirm_identity_file(identity, target_path=Path(target_raw))
        final = mod._read_identity(Path(target_raw))
        if rc == 0 and final is not None:
            mod.flushPendingBuffer(final["developer_id"])
        raise SystemExit(rc)
        """
    )

    for iteration in range(5):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            target = fake_home / ".agentic" / "identity.yml"
            initial_handle = "candidate-a" if iteration % 2 == 0 else "candidate-b"
            initial_marker = "1" if initial_handle == "candidate-a" else "2"
            target.parent.mkdir(parents=True)
            target.write_text(
                f"developer_id: {initial_handle}\n"
                f"display_name: {initial_marker * 2000000}\n"
                f"created_at: 2026-07-25T00:00:0{initial_marker}Z\n"
                "provisional: true\n",
                encoding="utf-8",
            )
            pending = _write_pending(
                fake_home / ".agentic" / "session-log" / ".pending",
                {
                    "session_uuid": f"concurrent-{iteration}",
                    "ts": "2026-07-25T00:00:00Z",
                    "project_slug": "project",
                    "branch": "main",
                    "data": {},
                },
            )
            start = tmp_path / "start"
            env = _cli_env(fake_home)
            command_a = [
                sys.executable, "-c", worker, str(_BIN_PATH), str(target),
                str(start), "candidate-a", "1",
            ]
            command_b = [
                sys.executable, "-c", worker, str(_BIN_PATH), str(target),
                str(start), "candidate-b", "2",
            ]
            proc_a = subprocess.Popen(
                command_a, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env,
            )
            proc_b = subprocess.Popen(
                command_b, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env,
            )
            start.touch()
            stdout_a, stderr_a = proc_a.communicate(timeout=30)
            stdout_b, stderr_b = proc_b.communicate(timeout=30)
            assert proc_a.returncode == 0, (
                f"candidate A failed: stdout={stdout_a!r} stderr={stderr_a!r}"
            )
            assert proc_b.returncode == 0, (
                f"candidate B failed: stdout={stdout_b!r} stderr={stderr_b!r}"
            )

            final = target.read_text(encoding="utf-8")
            expected_a = (
                "developer_id: candidate-a\n"
                f"display_name: {'1' * 2000000}\n"
                "created_at: 2026-07-25T00:00:01Z\n"
            )
            expected_b = (
                "developer_id: candidate-b\n"
                f"display_name: {'2' * 2000000}\n"
                "created_at: 2026-07-25T00:00:02Z\n"
            )
            assert final in (expected_a, expected_b), (
                "Concurrent confirmation cross-published or truncated candidate bytes"
            )
            assert (
                (final == expected_a and initial_handle == "candidate-a")
                or (final == expected_b and initial_handle == "candidate-b")
            ), "A stale concurrent candidate replaced the provisional bytes on disk"
            assert not list(target.parent.glob("identity.yml.tmp*")), (
                "Concurrent confirmation left temp debris"
            )
            winner = "candidate-a" if final == expected_a else "candidate-b"
            loser = "candidate-b" if winner == "candidate-a" else "candidate-a"
            assert not pending.exists(), "Winning confirmation must consume pending telemetry"
            winner_log = fake_home / ".agentic" / "session-log" / f"{winner}.jsonl"
            loser_log = fake_home / ".agentic" / "session-log" / f"{loser}.jsonl"
            assert winner_log.is_file(), "Pending telemetry must route to final identity"
            assert not loser_log.exists(), "Pending telemetry must not route to losing identity"
    print("PASS test_concurrent_provisional_confirm_is_atomic_and_routes_winner")


def test_public_docs_and_identity_manifest_describe_scoped_flush_and_api():
    """Public docs pin scoped pending retention and the shell manifest API."""
    for doc_path in (_README_PATH, _IDENTITY_TELEMETRY_DOC_PATH):
        text = doc_path.read_text(encoding="utf-8")
        assert "matching the confirmed effective scope" in text, doc_path
        assert "nonmatching records remain buffered" in text, doc_path
        assert "identity_scope" in text, doc_path
        assert "symlink" in text, doc_path

    manifest = _IDENTITY_SH_PATH.read_text(encoding="utf-8").split("_ae_setup_identity", 1)[0]
    assert "AE_IDENTITY_SCOPE" in manifest
    command_doc = _IDENTITY_DOC_PATH.read_text(encoding="utf-8")
    assert "O_NONBLOCK | O_NOFOLLOW" in command_doc
    assert "wrong-owner" in command_doc
    print("PASS test_public_docs_and_identity_manifest_describe_scoped_flush_and_api")


def test_winning_global_scope_routes_pending_despite_active_profile():
    """A global provisional winner stays global even while a profile is active."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(project)],
            check=True,
            capture_output=True,
            text=True,
        )
        profile = fake_home / ".claude-tenant"
        profile.mkdir()
        global_identity = fake_home / ".agentic" / "identity.yml"
        _write_identity_file(global_identity, "global-winner", provisional=True)
        env = _cli_env(fake_home)
        env["AGENTIC_CONFIG_DIR"] = str(profile)

        payload = json.dumps(
            {"cwd": str(project), "session_id": "winning-global", "transcript": []}
        )
        hook = subprocess.run(
            ["node", str(_REPO_ROOT / "hooks" / "stop-context.js")],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert hook.returncode == 0, hook.stderr
        pending_path = (
            fake_home
            / ".agentic"
            / "session-log"
            / ".pending"
            / "winning-global.json"
        )
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        assert pending.get("identity_scope") == "global"
        assert "config_dir" not in pending

        confirmed = _run_cli(["confirm", "--scope", "global"], env, cwd=project)
        assert confirmed.returncode == 0, confirmed.stderr
        global_log = (
            fake_home / ".agentic" / "session-log" / "global-winner.jsonl"
        )
        assert global_log.is_file(), "global_log=no: winning global record was retained"

        profile_init = _run_cli(
            [
                "init",
                "profile-later",
                "--scope",
                "profile",
                "--profile-dir",
                str(profile),
            ],
            env,
            cwd=project,
        )
        assert profile_init.returncode == 0, profile_init.stderr
        profile_log = (
            fake_home / ".agentic" / "session-log" / "profile-later.jsonl"
        )
        assert not profile_log.exists(), (
            "profile_log=yes: global record was reattributed to a later profile"
        )
        assert not pending_path.exists()
        print("PASS test_winning_global_scope_routes_pending_despite_active_profile")


def test_cli_identity_fifo_and_socket_reads_are_bounded():
    """Special identity files are rejected without blocking or consuming them."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        identity = fake_home / ".agentic" / "identity.yml"
        identity.parent.mkdir()
        env = _cli_env(fake_home)

        os.mkfifo(identity, 0o600)
        started = time.monotonic()
        try:
            fifo_result = subprocess.run(
                [sys.executable, str(_BIN_PATH), "show", "--scope", "global"],
                capture_output=True,
                text=True,
                env=env,
                timeout=2,
            )
        except subprocess.TimeoutExpired as exc:
            raise AssertionError("FIFO identity read blocked past 2 seconds") from exc
        elapsed = time.monotonic() - started
        assert elapsed < 1.5, f"FIFO read took {elapsed:.3f}s"
        assert fifo_result.returncode == 0
        assert identity.lstat().st_mode and stat.S_ISFIFO(identity.lstat().st_mode)
        identity.unlink()

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(identity))
            started = time.monotonic()
            socket_result = subprocess.run(
                [sys.executable, str(_BIN_PATH), "show", "--scope", "global"],
                capture_output=True,
                text=True,
                env=env,
                timeout=2,
            )
            elapsed = time.monotonic() - started
            assert elapsed < 1.5, f"socket read took {elapsed:.3f}s"
            assert socket_result.returncode == 0
            assert stat.S_ISSOCK(identity.lstat().st_mode)
        finally:
            sock.close()
        print("PASS test_cli_identity_fifo_and_socket_reads_are_bounded")


def test_cli_symlinked_identity_parents_fail_closed_for_reads_and_force_writes():
    """Global and project .agentic symlink parents never expose outside bytes."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(project)],
            check=True,
            capture_output=True,
            text=True,
        )
        env = _cli_env(fake_home)

        for scope, parent, cwd in (
            ("global", fake_home / ".agentic", project),
            ("project", project / ".agentic", project),
            ("profile", fake_home / ".claude-tenant", project),
        ):
            outside = tmp_path / f"outside-{scope}"
            outside.mkdir()
            outside_identity = outside / "identity.yml"
            outside_bytes = (
                f"developer_id: outside-{scope}\n"
                "# outside fixture must stay byte-identical\n"
            ).encode()
            outside_identity.write_bytes(outside_bytes)
            parent.symlink_to(outside, target_is_directory=True)

            suffix = (
                ["--profile-dir", str(parent)] if scope == "profile" else []
            )
            shown = _run_cli(
                ["show", "--scope", scope, *suffix], env, cwd=cwd
            )
            assert f"outside-{scope}" not in shown.stdout
            forced = _run_cli(
                [
                    "init",
                    f"inside-{scope}",
                    "--force",
                    "--scope",
                    scope,
                    *suffix,
                ],
                env,
                cwd=cwd,
            )
            assert forced.returncode == 1, (
                f"{scope} force write through symlinked parent succeeded: "
                f"stdout={forced.stdout!r} stderr={forced.stderr!r}"
            )
            assert outside_identity.read_bytes() == outside_bytes
            parent.unlink()
        print(
            "PASS "
            "test_cli_symlinked_identity_parents_fail_closed_for_reads_and_force_writes"
        )


def test_shared_scope_target_command_matrix_and_structure():
    """Every command uses one scope-target resolver across all concrete scopes."""
    import subprocess

    source = _BIN_PATH.read_text(encoding="utf-8")
    assert "class ScopeTarget" in source
    command_region = source[source.index("def cmd_init"):source.index("def main")]
    assert command_region.count("_resolve_scope_target(") >= 4
    assert 'if scope == "profile"' not in command_region
    assert 'if scope == "project"' not in command_region

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(project)],
            check=True,
            capture_output=True,
            text=True,
        )
        profile = fake_home / ".claude-tenant"
        fake_bin = tmp_path / "fakebin"
        _fake_gh(fake_bin, "matrix-auto")
        env = _cli_env(fake_home, extra_path=fake_bin)

        for scope in ("global", "profile", "project"):
            suffix = (
                ["--profile-dir", str(profile)] if scope == "profile" else []
            )
            shown_absent = _run_cli(
                ["show", "--scope", scope, *suffix], env, cwd=project
            )
            assert shown_absent.returncode == 0

            initialized = _run_cli(
                ["init", f"matrix-{scope}", "--scope", scope, *suffix],
                env,
                cwd=project,
            )
            assert initialized.returncode == 0, initialized.stderr
            identity_path = {
                "global": fake_home / ".agentic" / "identity.yml",
                "profile": profile / "identity.yml",
                "project": project / ".agentic" / "identity.yml",
            }[scope]
            confirmed_bytes = identity_path.read_bytes()

            shown = _run_cli(
                ["show", "--scope", scope, *suffix], env, cwd=project
            )
            assert f"matrix-{scope}" in shown.stdout
            confirmed = _run_cli(
                ["confirm", "--scope", scope, *suffix], env, cwd=project
            )
            assert confirmed.returncode == 0, confirmed.stderr
            assert identity_path.read_bytes() == confirmed_bytes

            auto_rejected = _run_cli(
                ["auto", "--scope", scope, *suffix], env, cwd=project
            )
            assert auto_rejected.returncode == 2
            auto_forced = _run_cli(
                ["auto", "--force", "--scope", scope, *suffix],
                env,
                cwd=project,
            )
            assert auto_forced.returncode == 0, auto_forced.stderr
            reconfirmed = _run_cli(
                ["confirm", "--scope", scope, *suffix], env, cwd=project
            )
            assert reconfirmed.returncode == 0, reconfirmed.stderr
            assert b"provisional:" not in identity_path.read_bytes()
        print("PASS test_shared_scope_target_command_matrix_and_structure")


def test_canonical_identity_scope_partition_and_retention():
    """Canonical scope tags route exactly once and retain nonmatching records."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        pending_dir, global_log_dir, _ = _patch_paths(tmp_path)
        profile = tmp_path / "profile"
        repo = tmp_path / "repo"
        profile.mkdir()
        repo.mkdir()
        records = {
            scope: _write_pending(
                pending_dir,
                {
                    "session_uuid": f"scope-{scope}",
                    "ts": "2026-07-25T00:00:00Z",
                    "project_slug": "repo",
                    "repo_root": str(repo),
                    "branch": "main",
                    "identity_scope": scope,
                    **({"config_dir": str(profile)} if scope == "profile" else {}),
                    "data": {},
                },
            )
            for scope in ("global", "profile", "project")
        }

        assert flushPendingBuffer("global-dev", scope_filter="global") == 1
        assert not records["global"].exists()
        assert records["profile"].exists() and records["project"].exists()

        assert flushPendingBuffer(
            "profile-dev",
            profile_dir_filter=str(profile),
            scope_filter="profile",
        ) == 1
        assert not records["profile"].exists()
        assert records["project"].exists()

        assert flushPendingBuffer(
            "project-dev",
            repo_root_filter=str(repo),
            scope_filter="project",
        ) == 1
        assert not records["project"].exists()
        for developer_id, scope in (
            ("global-dev", "global"),
            ("profile-dev", "profile"),
            ("project-dev", "project"),
        ):
            log = global_log_dir / f"{developer_id}.jsonl"
            assert f"scope-{scope}" in log.read_text(encoding="utf-8")
        print("PASS test_canonical_identity_scope_partition_and_retention")


def test_safe_identity_stat_rejects_wrong_owner_and_multiple_links():
    """The final-target predicate rejects wrong-owner and multiply-linked files."""
    from types import SimpleNamespace

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "identity.yml"
        target.write_text("developer_id: owner-dev\n", encoding="utf-8")
        current = target.stat()
        safe = {
            "st_mode": current.st_mode,
            "st_nlink": 1,
            "st_uid": os.geteuid(),
            "st_size": current.st_size,
        }
        assert _mod._safe_identity_stat(SimpleNamespace(**safe))
        assert not _mod._safe_identity_stat(
            SimpleNamespace(**{**safe, "st_uid": os.geteuid() + 1})
        )
        assert not _mod._safe_identity_stat(
            SimpleNamespace(**{**safe, "st_nlink": 2})
        )
        print("PASS test_safe_identity_stat_rejects_wrong_owner_and_multiple_links")


def test_identity_files_reject_group_or_world_writable_modes():
    """Identity reads fail closed when another account can rewrite the file."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        identity = root / "identity.yml"
        _write_identity_file(identity, "unsafe-mode")
        for mode in (0o620, 0o602, 0o666):
            identity.chmod(mode)
            assert _mod._read_identity(identity) is None, oct(mode)
        identity.chmod(0o600)
        assert _mod._read_identity(identity)["developer_id"] == "unsafe-mode"
        print("PASS test_identity_files_reject_group_or_world_writable_modes")


def test_display_name_rejects_control_characters():
    """Display names cannot inject YAML fields or terminal control sequences."""
    with tempfile.TemporaryDirectory() as tmp:
        fake_home = Path(tmp).resolve() / "home"
        fake_home.mkdir()
        env = _cli_env(fake_home)
        for display_name in (
            "Trusted\nprovisional: true",
            "Trusted\rderived_from: attacker",
            "Trusted\x1b[31m",
            "Trusted\u0085Next Line",
            "Trusted\u009bCSI",
        ):
            result = _run_cli(
                ["init", "display-safe", "--display-name", display_name, "--force"],
                env,
            )
            assert result.returncode == 1
            assert "display name" in result.stderr.lower()
        assert not (fake_home / ".agentic" / "identity.yml").exists()

        identity_path = fake_home / ".agentic" / "identity.yml"
        _write_identity_file(identity_path, "display-safe")
        with identity_path.open("a", encoding="utf-8") as handle:
            handle.write("display_name: Unsafe\u0085Control\n")
        result = _run_cli(["show", "--scope", "global"], env)
        assert result.returncode == 0
        assert "No identity set." in result.stdout
        assert "\u0085" not in result.stdout
        print("PASS test_display_name_rejects_control_characters")


def test_pending_flush_rejects_hostile_files_and_records_individually():
    """Hostile pending entries do not block a valid sibling or unsafe log writes."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        pending_dir, global_log_dir, _ = _patch_paths(root)
        valid = _write_pending(
            pending_dir,
            {
                "session_uuid": "valid-sibling",
                "ts": "2026-07-27T00:00:00Z",
                "project_slug": "project",
                "branch": "main",
                "data": {},
            },
        )
        os.mkfifo(pending_dir / "fifo.json", 0o600)
        (pending_dir / "huge.json").write_bytes(b"{" + b"x" * (5 * 1024 * 1024))
        (pending_dir / "array.json").write_text("[]", encoding="utf-8")
        (pending_dir / "unhashable.json").write_text(
            json.dumps({"session_uuid": [], "data": {}}),
            encoding="utf-8",
        )
        outside = root / "outside.json"
        outside.write_text(
            json.dumps({"session_uuid": "attacker", "data": {}}),
            encoding="utf-8",
        )
        (pending_dir / "symlink.json").symlink_to(outside)

        started = time.monotonic()
        count = flushPendingBuffer("safe-dev")
        elapsed = time.monotonic() - started
        assert elapsed < 1.5, f"pending FIFO blocked for {elapsed:.3f}s"
        assert count == 1
        assert not valid.exists()
        rows = [
            json.loads(line)
            for line in (global_log_dir / "safe-dev.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        assert [row["session_uuid"] for row in rows] == ["valid-sibling"]
        for hostile in (
            "fifo.json",
            "huge.json",
            "array.json",
            "unhashable.json",
            "symlink.json",
        ):
            assert (pending_dir / hostile).exists(), hostile

        unsafe_target = root / "unsafe-log-target"
        unsafe_target.write_text("KEEP\n", encoding="utf-8")
        unsafe_log = global_log_dir / "blocked-dev.jsonl"
        unsafe_log.symlink_to(unsafe_target)
        retry = _write_pending(
            pending_dir,
            {
                "session_uuid": "unsafe-output",
                "ts": "2026-07-27T00:00:01Z",
                "project_slug": "project",
                "branch": "main",
                "data": {},
            },
        )
        assert flushPendingBuffer("blocked-dev") == 0
        assert retry.exists()
        assert unsafe_target.read_text(encoding="utf-8") == "KEEP\n"
        print("PASS test_pending_flush_rejects_hostile_files_and_records_individually")


def test_nul_pending_metadata_is_quarantined_while_valid_sibling_flushes():
    """NUL/control metadata never reaches subprocess argv or partial attribution."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        pending_dir, global_log_dir, _ = _patch_paths(root)
        bad = _write_pending(
            pending_dir,
            {
                "session_uuid": "nul-repo",
                "ts": "2026-07-28T00:00:00Z",
                "project_slug": "project",
                "repo_root": f"{root}/project\u0000attacker",
                "branch": "main",
                "identity_scope": "global",
                "data": {},
            },
        )
        good = _write_pending(
            pending_dir,
            {
                "session_uuid": "valid-after-nul",
                "ts": "2026-07-28T00:00:01Z",
                "project_slug": "project",
                "repo_root": "",
                "branch": "main",
                "identity_scope": "global",
                "data": {},
            },
        )

        assert flushPendingBuffer("safe-dev", scope_filter="global") == 1
        assert bad.exists()
        assert not good.exists()
        rows = [
            json.loads(line)
            for line in (global_log_dir / "safe-dev.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        assert [row["session_uuid"] for row in rows] == ["valid-after-nul"]
        print("PASS test_nul_pending_metadata_is_quarantined_while_valid_sibling_flushes")


def test_pending_cap_is_streamed_and_pruning_emits_notice():
    """Cap enforcement scans at most cap+1 entries and reports safe pruning."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        pending_dir, _, _ = _patch_paths(root)
        pending_dir.mkdir(parents=True, exist_ok=True)
        for index in range(_mod.PENDING_CAP):
            _write_pending(
                pending_dir,
                {
                    "session_uuid": f"cap-{index:03d}",
                    "ts": f"2026-07-28T00:{index // 60:02d}:{index % 60:02d}Z",
                    "project_slug": "project",
                    "repo_root": "",
                    "branch": "main",
                    "identity_scope": "global",
                    "data": {},
                },
            )
        record = {
            "schema_version": 1,
            "session_uuid": "cap-new",
            "ts": "2026-07-28T23:59:59Z",
            "project_slug": "project",
            "repo_root": "",
            "branch": "main",
            "identity_scope": "global",
            "data": {},
        }
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            assert _mod._write_pending_record_safely(record)
        assert "pending buffer cap exceeded; pruned 1 oldest session(s)." in (
            stderr.getvalue()
        )
        assert len(list(pending_dir.glob("*.json"))) == _mod.PENDING_CAP

        for index in range(50):
            (pending_dir / f"junk-{index:03d}.json").write_text(
                "not-json",
                encoding="utf-8",
            )
        fd = os.open(pending_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            names = list(_mod._iter_bounded_pending_names(fd))
        finally:
            os.close(fd)
        assert len(names) <= _mod.PENDING_SCAN_LIMIT
        source = _BIN_PATH.read_text(encoding="utf-8")
        assert "os.listdir(parent_fd)" not in source
        print("PASS test_pending_cap_is_streamed_and_pruning_emits_notice")


def test_pending_scan_ignores_and_recovers_stale_internal_entries():
    """Invalid/internal entries cannot consume the canonical record budget."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        pending_dir, global_log_dir, _ = _patch_paths(root)
        pending_dir.mkdir(parents=True, exist_ok=True)
        old = time.time() - 7200
        for index in range(40):
            junk = pending_dir / f"junk-{index:03d}.json"
            junk.write_text("not-json", encoding="utf-8")
        for index in range(40):
            temp = pending_dir / f".record-{index:03d}.json.tmp.dead"
            temp.write_text("partial", encoding="utf-8")
            os.utime(temp, (old, old))
        for index in range(21):
            processing = pending_dir / f".processing.dead.{index:03d}.json"
            processing.write_text("invalid", encoding="utf-8")
            os.utime(processing, (old, old))
        recovered_record = {
            "session_uuid": "eligible-recovered",
            "ts": "2026-08-06T23:59:58Z",
            "project_slug": "project",
            "repo_root": "",
            "branch": "main",
            "identity_scope": "global",
            "data": {},
        }
        recovered = pending_dir / ".processing.dead.recover.json"
        recovered.write_text(json.dumps(recovered_record), encoding="utf-8")
        os.utime(recovered, (old, old))
        for index in range(_mod.PENDING_CAP):
            _write_pending(
                pending_dir,
                {
                    "session_uuid": f"eligible-{index:03d}",
                    "ts": f"2026-08-06T00:{index // 60:02d}:{index % 60:02d}Z",
                    "project_slug": "project",
                    "repo_root": "",
                    "branch": "main",
                    "identity_scope": "global",
                    "data": {},
                },
            )

        assert _mod._write_pending_record_safely(
            {
                "schema_version": 1,
                "session_uuid": "eligible-new",
                "ts": "2026-08-06T23:59:59Z",
                "project_slug": "project",
                "repo_root": "",
                "branch": "main",
                "identity_scope": "global",
                "data": {},
            }
        )
        valid = []
        fd = os.open(pending_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            valid = list(_mod._iter_bounded_pending_names(fd))
        finally:
            os.close(fd)
        assert len(valid) == _mod.PENDING_CAP
        assert "eligible-new.json" in valid
        assert "eligible-recovered.json" in valid
        assert not list(pending_dir.glob(".*.tmp.*"))
        assert not list(pending_dir.glob(".processing.*.json"))
        assert flushPendingBuffer("bounded-dev", scope_filter="global") == _mod.PENDING_CAP
        rows = [
            json.loads(line)
            for line in (global_log_dir / "bounded-dev.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(rows) == _mod.PENDING_CAP
        assert {row["session_uuid"] for row in rows} == set(valid_name[:-5] for valid_name in valid)
        print("PASS test_pending_scan_ignores_and_recovers_stale_internal_entries")


def test_bounded_subprocess_output_fails_safely():
    """gh/git children cannot force unbounded stdout or stderr capture."""
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('x'*20000); sys.stderr.write('y'*20000)",
    ]
    try:
        _mod._run_bounded_command(
            command,
            timeout=2,
            max_stdout=1024,
            max_stderr=1024,
        )
    except _mod._BoundedCommandError:
        pass
    else:
        raise AssertionError("oversized child output was accepted")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        fake_home = root / "home"
        fake_bin = root / "bin"
        fake_home.mkdir()
        fake_bin.mkdir()
        gh = fake_bin / "gh"
        gh.write_text(
            "#!/bin/sh\npython3 -c \"import sys; "
            "sys.stdout.write('x'*20000); sys.stderr.write('y'*20000)\"\n",
            encoding="utf-8",
        )
        gh.chmod(0o700)
        result = _run_cli(
            ["auto"],
            _cli_env(fake_home, extra_path=fake_bin),
        )
        assert result.returncode == 1
        assert not (fake_home / ".agentic" / "identity.yml").exists()
        print("PASS test_bounded_subprocess_output_fails_safely")


def test_flush_lock_rotation_serializes_two_flushers():
    """A rotated leaf aborts the old holder while a second flusher waits."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        pending_dir, global_log_dir, lock_path = _patch_paths(root)
        _write_pending(
            pending_dir,
            {
                "session_uuid": "rotation-session",
                "ts": "2026-07-28T00:00:00Z",
                "project_slug": "project",
                "repo_root": "",
                "branch": "main",
                "identity_scope": "global",
                "data": {},
            },
        )
        ready = root / "ready"
        release = root / "release"
        result_a = root / "result-a"
        result_b = root / "result-b"
        loader = (
            "import importlib.machinery,importlib.util,os,pathlib,sys,time\n"
            "p=pathlib.Path(sys.argv[1]); "
            "ldr=importlib.machinery.SourceFileLoader('aid',str(p)); "
            "spec=importlib.util.spec_from_loader('aid',ldr); "
            "m=importlib.util.module_from_spec(spec); ldr.exec_module(m)\n"
            "root=pathlib.Path(sys.argv[2]); "
            "m.PENDING_DIR=root/'session-log'/'.pending'; "
            "m.GLOBAL_SESSION_LOG_DIR=root/'session-log'; "
            "m.FLUSH_LOCK_PATH=root/'session-log'/'.flush.lock'\n"
        )
        worker_a = loader + (
            "orig=m._lock_fd_exclusive; calls=[0]\n"
            "def lock(fd,timeout):\n"
            " orig(fd,timeout=timeout); calls[0]+=1\n"
            " if calls[0]==2:\n"
            "  pathlib.Path(sys.argv[3]).touch()\n"
            "  while not pathlib.Path(sys.argv[4]).exists(): time.sleep(0.002)\n"
            "m._lock_fd_exclusive=lock\n"
            "pathlib.Path(sys.argv[5]).write_text(str(m.flushPendingBuffer('safe-dev')))\n"
        )
        worker_b = loader + (
            "pathlib.Path(sys.argv[3]).write_text(str(m.flushPendingBuffer('safe-dev')))\n"
        )
        proc_a = subprocess.Popen(
            [
                sys.executable,
                "-c",
                worker_a,
                str(_BIN_PATH),
                str(root),
                str(ready),
                str(release),
                str(result_a),
            ]
        )
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert time.monotonic() < deadline
            time.sleep(0.002)
        old_lock = lock_path.with_name(".flush.lock.rotated")
        lock_path.rename(old_lock)
        lock_path.write_bytes(b"")
        lock_path.chmod(0o600)
        proc_b = subprocess.Popen(
            [
                sys.executable,
                "-c",
                worker_b,
                str(_BIN_PATH),
                str(root),
                str(result_b),
            ]
        )
        time.sleep(0.05)
        assert not result_b.exists(), "second flusher bypassed the pinned parent lock"
        release.touch()
        assert proc_a.wait(timeout=10) == 0
        assert proc_b.wait(timeout=10) == 0
        assert result_a.read_text(encoding="utf-8") == "0"
        assert result_b.read_text(encoding="utf-8") == "1"
        rows = (global_log_dir / "safe-dev.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        assert len(rows) == 1
        assert json.loads(rows[0])["session_uuid"] == "rotation-session"
        print("PASS test_flush_lock_rotation_serializes_two_flushers")


def test_flush_lock_rejects_hostile_targets_without_blocking():
    """The flush mutex itself is descriptor-validated before flock is attempted."""
    import socket

    for kind in (
        "symlink",
        "hardlink",
        "fifo",
        "socket",
        "mode-620",
        "mode-602",
        "mode-666",
        "oversized",
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, _, lock_path = _patch_paths(root)
            lock_path.unlink()
            outside = root / "outside-lock"
            outside.write_text("KEEP\n", encoding="utf-8")
            if kind == "symlink":
                lock_path.symlink_to(outside)
            elif kind == "hardlink":
                os.link(outside, lock_path)
            elif kind == "fifo":
                os.mkfifo(lock_path, 0o600)
            elif kind == "socket":
                sock = socket.socket(socket.AF_UNIX)
                sock.bind(str(lock_path))
                sock.close()
            elif kind.startswith("mode-"):
                lock_path.write_text("KEEP\n", encoding="utf-8")
                lock_path.chmod(int(kind.removeprefix("mode-"), 8))
            else:
                lock_path.write_bytes(b"x" * (_mod.MAX_LOCK_BYTES + 1))

            started = time.monotonic()
            assert flushPendingBuffer("safe-dev") == 0
            elapsed = time.monotonic() - started
            assert elapsed < 1.5, f"{kind} lock blocked for {elapsed:.3f}s"
            if kind in ("symlink", "hardlink"):
                assert outside.read_text(encoding="utf-8") == "KEEP\n"
            elif kind == "fifo":
                assert stat.S_ISFIFO(lock_path.lstat().st_mode)
            elif kind == "socket":
                assert stat.S_ISSOCK(lock_path.lstat().st_mode)
            elif kind.startswith("mode-"):
                assert lock_path.read_text(encoding="utf-8") == "KEEP\n"
            else:
                assert lock_path.stat().st_size == _mod.MAX_LOCK_BYTES + 1

    from types import SimpleNamespace

    regular = Path(__file__).stat()
    safe = {
        "st_mode": regular.st_mode,
        "st_nlink": 1,
        "st_uid": os.geteuid(),
        "st_size": 0,
    }
    assert not _mod._safe_regular_stat(
        SimpleNamespace(**{**safe, "st_uid": os.geteuid() + 1}),
        size_limit=_mod.MAX_LOCK_BYTES,
    )
    print("PASS test_flush_lock_rejects_hostile_targets_without_blocking")


def test_descriptor_parent_swap_aba_cannot_select_attacker_identity():
    """A held parent fd stays on trusted bytes across path replacement ABA."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        selected = root / "selected"
        trusted_hold = root / "trusted-hold"
        attacker_hold = root / "attacker-hold"
        _write_identity_file(selected / "identity.yml", "trusted-dev")
        _write_identity_file(attacker_hold / "identity.yml", "attacker-dev")

        with _mod._open_identity_parent(selected / "identity.yml") as parent_fd:
            selected.rename(trusted_hold)
            attacker_hold.rename(selected)
            identity = _mod._read_identity_at(parent_fd, "identity.yml")
            selected.rename(attacker_hold)
            trusted_hold.rename(selected)

        assert identity is not None
        assert identity["developer_id"] == "trusted-dev"
        assert identity["developer_id"] != "attacker-dev"
        hook_source = (
            _REPO_ROOT / "hooks" / "stop-context.js"
        ).read_text(encoding="utf-8")
        assert "spawnSync(helper, ['resolve-hook'" in hook_source
        assert "_snapshotIdentityParents" not in hook_source
        print("PASS test_descriptor_parent_swap_aba_cannot_select_attacker_identity")


def _run_cli_pair(
    command_a: list[str],
    command_b: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    barrier_root: Path,
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    """Release two CLI processes from a shared start barrier."""
    worker = (
        "import os,sys,time,pathlib\n"
        "ready=pathlib.Path(sys.argv[1]); start=pathlib.Path(sys.argv[2])\n"
        "ready.touch()\n"
        "deadline=time.monotonic()+5\n"
        "while not start.exists():\n"
        "  assert time.monotonic()<deadline\n"
        "  time.sleep(0.002)\n"
        "os.execv(sys.argv[3], sys.argv[3:])\n"
    )
    start = barrier_root / "start"
    ready_a = barrier_root / "ready-a"
    ready_b = barrier_root / "ready-b"
    proc_a = subprocess.Popen(
        [sys.executable, "-c", worker, str(ready_a), str(start), *command_a],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=cwd,
    )
    proc_b = subprocess.Popen(
        [sys.executable, "-c", worker, str(ready_b), str(start), *command_b],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=cwd,
    )
    deadline = time.monotonic() + 5
    while not (ready_a.exists() and ready_b.exists()):
        assert time.monotonic() < deadline
        time.sleep(0.002)
    start.touch()
    stdout_a, stderr_a = proc_a.communicate(timeout=15)
    stdout_b, stderr_b = proc_b.communicate(timeout=15)
    return (
        subprocess.CompletedProcess(command_a, proc_a.returncode, stdout_a, stderr_a),
        subprocess.CompletedProcess(command_b, proc_b.returncode, stdout_b, stderr_b),
    )


def test_mutations_share_parent_lock_under_cross_command_races():
    """Init, auto, force-write, and confirm serialize on one parent lock."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        fake_home = root / "home"
        project = root / "project"
        fake_bin = root / "fakebin"
        fake_home.mkdir()
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        _fake_gh(fake_bin, "auto-racer")
        env = _cli_env(fake_home, extra_path=fake_bin)
        cli = [sys.executable, str(_BIN_PATH)]
        identity_path = fake_home / ".agentic" / "identity.yml"

        for iteration in range(6):
            if identity_path.exists():
                identity_path.unlink()
            barrier = root / f"init-pair-{iteration}"
            barrier.mkdir()
            result_a, result_b = _run_cli_pair(
                [*cli, "init", f"init-a-{iteration}"],
                [*cli, "init", f"init-b-{iteration}"],
                env=env,
                cwd=project,
                barrier_root=barrier,
            )
            assert sorted((result_a.returncode, result_b.returncode)) == [0, 2]
            winner = _mod._read_identity(identity_path)
            assert winner is not None
            assert winner["developer_id"] in {
                f"init-a-{iteration}",
                f"init-b-{iteration}",
            }
            assert not winner.get("provisional", False)

        for iteration in range(6):
            identity_path.unlink(missing_ok=True)
            barrier = root / f"auto-init-{iteration}"
            barrier.mkdir()
            auto_result, init_result = _run_cli_pair(
                [*cli, "auto"],
                [*cli, "init", f"confirmed-{iteration}"],
                env=env,
                cwd=project,
                barrier_root=barrier,
            )
            assert sorted((auto_result.returncode, init_result.returncode)) == [0, 2]
            first = identity_path.read_bytes()
            winner = _mod._read_identity(identity_path)
            assert winner is not None
            if winner.get("provisional", False):
                assert winner["developer_id"] == "auto-racer"
            else:
                assert winner["developer_id"] == f"confirmed-{iteration}"
            rejected_auto = _run_cli(["auto"], env, cwd=project)
            if not winner.get("provisional", False):
                assert rejected_auto.returncode == 2
                assert identity_path.read_bytes() == first

        for iteration in range(6):
            _write_identity_file(
                identity_path,
                f"provisional-{iteration}",
                provisional=True,
            )
            barrier = root / f"force-confirm-{iteration}"
            barrier.mkdir()
            force_result, confirm_result = _run_cli_pair(
                [*cli, "init", f"forced-{iteration}", "--force"],
                [*cli, "confirm"],
                env=env,
                cwd=project,
                barrier_root=barrier,
            )
            assert force_result.returncode == 0, force_result.stderr
            assert confirm_result.returncode == 0, confirm_result.stderr
            winner = _mod._read_identity(identity_path)
            assert winner is not None
            assert winner["developer_id"] == f"forced-{iteration}"
            assert not winner.get("provisional", False)
        print("PASS test_mutations_share_parent_lock_under_cross_command_races")


def test_activation_preflight_uses_one_bounded_identity_resolver():
    """Canonical and generated adapters must not retain the old read invariant."""
    repo = _BIN_PATH.parent.parent
    paths = [
        repo / "content/sections/01-activation-preflight.md",
        repo / ".claude/skills/dinostack/METHODOLOGY.md",
        repo / ".codex/AGENTS.md",
        repo / ".codex/skills/dinostack/METHODOLOGY.md",
        repo / ".cursor/rules/agent-methodology.mdc",
        repo / ".gemini/skills/dinostack/SKILL.md",
        repo / ".github/skills/dinostack/SKILL.md",
        repo / ".hermes/SKILL.md",
        repo / ".kimi/AGENTS.md",
        repo / ".omp/skills/dinostack/METHODOLOGY.md",
        repo / ".openclaw/skills/dinostack/METHODOLOGY.md",
        repo / ".opencode/skills/dinostack/METHODOLOGY.md",
        repo / ".pi/skills/dinostack/METHODOLOGY.md",
    ]
    stale_claims = (
        "Keep it to three file reads",
        "three file reads with no subagent spawn",
        "no prompt, no shell-out, no LLM reasoning",
        'The "fast, silent" preflight invariant is preserved',
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        marker = text.find("## Activation preflight")
        assert marker >= 0, f"missing Activation preflight in {path}"
        section = text[marker:]
        next_section = section.find("\n## ", len("\n## "))
        if next_section >= 0:
            section = section[:next_section]
        if "/.codex/" in str(path):
            assert (
                'AGENTIC_CONFIG_DIR="$AE_CODEX_CONFIG_DIR" ds-identity '
                'resolve-hook --cwd "$AE_PROJECT_DIR"'
            ) in section, path
        else:
            assert "ds-identity resolve-hook --cwd <cwd>" in section, path
        assert ("3-second" in section or "3 seconds" in section) \
            and "64 KiB" in section, path
        for stale in stale_claims:
            assert stale not in section, f"{path} retains stale claim: {stale}"
    print("PASS test_activation_preflight_uses_one_bounded_identity_resolver")


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
    test_flush_claim_preserves_newer_same_session_publication()
    test_flush_replaces_attributed_total_published_immediately_after_claim()
    test_append_retries_when_canonical_log_rotates_before_flock()
    test_append_retries_when_canonical_parent_rotates_before_publication()
    test_lock_timeout_retries_with_backoff_and_succeeds()
    test_lock_timeout_gives_up_after_budget_exhausted_without_raising_to_caller()
    test_hook_ceiling_matches_python_budget()
    test_lock_retry_lock_timeout_clamped_to_remaining_budget()
    test_lock_retry_backoff_sleep_clamped_to_remaining_budget()
    test_write_hook_checkpoint_survives_sigkill_mid_global_append()
    test_missing_log_race_dedups_against_locked_append_fd()
    test_profile_confirmed_beats_confirmed_global()
    test_project_confirmed_beats_confirmed_profile()
    test_confirmed_global_not_suppressed_by_provisional_profile()
    test_provisional_profile_used_when_no_confirmed_anywhere()
    test_env_detection_precedence()
    test_profile_dir_outside_home_rejected()
    test_profile_dir_override()
    test_profile_flush_only_own_config_dir_records()
    test_global_flush_skips_config_dir_tagged_records()
    test_profile_flush_rejects_symlinked_filter_spelling()
    test_global_flush_still_attributes_untagged_legacy_records()
    test_no_env_profile_scope_absent()
    test_env_precedence_nonexistent_highest_wins()
    test_tilde_prefixed_env_expanded()
    test_symlink_escape_rejected()
    test_flush_non_string_config_dir_no_crash()
    test_docs_show_exit_contract()
    test_docs_confirm_already_confirmed_flush_contract()
    test_cli_auto_profile_writes_provisional()
    test_cli_auto_profile_confirmed_rejected_without_force()
    test_cli_confirm_profile_flushes_tagged_pending()
    test_cli_confirm_project_with_active_profile_flushes_own_pending()
    test_cli_confirm_global_preserves_profile_pending()
    test_cli_confirm_already_confirmed_profile_preserves_bytes_and_flushes()
    test_cli_confirm_already_confirmed_project_preserves_bytes_and_flushes()
    test_cli_confirm_already_confirmed_global_preserves_bytes_and_flushes()
    test_cli_confirm_profile_no_identity_errors()
    test_cli_profile_dir_is_regular_file_clean_error()
    test_cli_init_profile_happy_path()
    test_cli_init_profile_force_overwrites_confirmed()
    test_cli_show_profile_three_paths()
    test_cross_language_profile_resolution_agrees()
    test_cross_language_unsafe_profile_candidate_falls_through()
    test_cli_invalid_parsed_handles_cannot_escape_session_log()
    test_cli_identity_reads_reject_symlink_and_non_regular_targets()
    test_cli_identity_read_invalid_utf8_is_bounded()
    test_cli_identity_read_unreadable_file_is_bounded()
    test_concurrent_provisional_confirm_is_atomic_and_routes_winner()
    test_public_docs_and_identity_manifest_describe_scoped_flush_and_api()
    test_winning_global_scope_routes_pending_despite_active_profile()
    test_cli_identity_fifo_and_socket_reads_are_bounded()
    test_cli_symlinked_identity_parents_fail_closed_for_reads_and_force_writes()
    test_shared_scope_target_command_matrix_and_structure()
    test_canonical_identity_scope_partition_and_retention()
    test_safe_identity_stat_rejects_wrong_owner_and_multiple_links()
    test_identity_files_reject_group_or_world_writable_modes()
    test_display_name_rejects_control_characters()
    test_pending_flush_rejects_hostile_files_and_records_individually()
    test_nul_pending_metadata_is_quarantined_while_valid_sibling_flushes()
    test_pending_cap_is_streamed_and_pruning_emits_notice()
    test_pending_scan_ignores_and_recovers_stale_internal_entries()
    test_bounded_subprocess_output_fails_safely()
    test_flush_lock_rotation_serializes_two_flushers()
    test_flush_lock_rejects_hostile_targets_without_blocking()
    test_descriptor_parent_swap_aba_cannot_select_attacker_identity()
    test_mutations_share_parent_lock_under_cross_command_races()
    test_activation_preflight_uses_one_bounded_identity_resolver()
    test_write_hook_anchors_session_log_to_repo_root_from_drifted_cwd()
    test_write_hook_skips_when_cwd_has_no_git_ancestor()
    test_write_hook_does_not_climb_to_home_agentic_marker()
    test_write_hook_rejects_cwd_equal_to_home()
    print("All tests passed.")
