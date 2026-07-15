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
  8. CLI suite (L) - subprocess-level cmd_auto/cmd_confirm --scope profile
     coverage under a fake $HOME (rejection paths, provisional write, and the
     confirm->flushPendingBuffer profile_dir_filter wiring end-to-end).
  9. M suite - hardening: nonexistent highest-precedence env dir stops the
     scan (Python<->JS parity contract), symlink-escape rejection, file-as-
     profile-dir clean failure, non-string config_dir flush guard.

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
    """(J5) AGENTIC_CONFIG_DIR beats CLAUDE_CONFIG_DIR beats CODEX_HOME."""
    with tempfile.TemporaryDirectory(dir=str(Path.home())) as a, \
            tempfile.TemporaryDirectory(dir=str(Path.home())) as b, \
            tempfile.TemporaryDirectory(dir=str(Path.home())) as c:
        _write_identity_file(Path(a) / "identity.yml", "a-dev")
        _write_identity_file(Path(b) / "identity.yml", "b-dev")
        _write_identity_file(Path(c) / "identity.yml", "c-dev")

        # All three set -> AGENTIC_CONFIG_DIR (a) wins.
        restore = _patch_environ(set_pairs={
            "AGENTIC_CONFIG_DIR": a, "CLAUDE_CONFIG_DIR": b, "CODEX_HOME": c})
        try:
            p = _profile_identity_path()
            assert p == Path(a) / "identity.yml", f"Expected A path, got {p}"
        finally:
            restore()

        # AGENTIC cleared -> CLAUDE_CONFIG_DIR (b) wins.
        restore = _patch_environ(set_pairs={"CLAUDE_CONFIG_DIR": b, "CODEX_HOME": c},
                                 clear_keys=["AGENTIC_CONFIG_DIR"])
        try:
            p = _profile_identity_path()
            assert p == Path(b) / "identity.yml", f"Expected B path, got {p}"
        finally:
            restore()

        # Only CODEX_HOME set -> it wins (last-tier fallback).
        restore = _patch_environ(set_pairs={"CODEX_HOME": c},
                                 clear_keys=["AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR"])
        try:
            p = _profile_identity_path()
            assert p == Path(c) / "identity.yml", f"Expected C path, got {p}"
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


def test_profile_flush_matches_symlinked_filter_spelling():
    """(K4) round-trip: record tagged with realpath'd config_dir (JS writer)
    flushes under a filter built from the UN-resolved symlinked spelling."""
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

        # JS writer tags with fs.realpathSync -> the fully-resolved path.
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

        # Filter uses the symlinked spelling (what --profile-dir would carry).
        count = flushPendingBuffer("rt-dev", profile_dir_filter=str(symlinked_cfg))
        assert count == 1, f"Expected 1 flushed (realpath both sides), got {count}"
        assert not path_rec.exists(), \
            "Record must flush despite symlinked filter spelling"

        global_log = global_log_dir / "rt-dev.jsonl"
        lines = [l for l in global_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1
        assert json.loads(lines[0])["session_uuid"] == "uuid-symlink-rt"
        print("PASS test_profile_flush_matches_symlinked_filter_spelling")


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
    the flush (pre-guard: os.path.realpath(42) raised TypeError). Under a
    profile filter it is skipped (left in buffer); under a global flush it
    behaves as untagged."""
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

        # Global flush: no TypeError; coerced-to-'' record behaves as untagged.
        count = flushPendingBuffer("ns-dev")
        assert count == 1, f"Expected 1 flushed under global flush, got {count}"
        assert not path_bad.exists(), "Record must flush as untagged under global"
        print("PASS test_flush_non_string_config_dir_no_crash")


# ---------------------------------------------------------------------------
# Tests (L): CLI-level cmd_auto / cmd_confirm --scope profile (subprocess)
# ---------------------------------------------------------------------------

def _cli_env(fake_home: Path, extra_path: Path | None = None) -> dict:
    """Hermetic subprocess env: fake HOME, profile env vars unset."""
    env = dict(os.environ)
    for k in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        env.pop(k, None)
    env["HOME"] = str(fake_home)
    if extra_path is not None:
        env["PATH"] = str(extra_path) + os.pathsep + env.get("PATH", "")
    return env


def _run_cli(args: list[str], env: dict):
    """Run the real bin/agentic-identity via subprocess. Returns CompletedProcess."""
    import subprocess
    return subprocess.run(
        [sys.executable, str(_BIN_PATH)] + args,
        capture_output=True, text=True, env=env, timeout=30,
    )


def _fake_gh(bin_dir: Path, login: str) -> None:
    """Install a fake `gh` shim printing a fixed login (hermetic cmd_auto)."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\necho {login}\n", encoding="utf-8")
    gh.chmod(0o755)


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
        for k in ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
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
    test_profile_confirmed_beats_confirmed_global()
    test_project_confirmed_beats_confirmed_profile()
    test_confirmed_global_not_suppressed_by_provisional_profile()
    test_provisional_profile_used_when_no_confirmed_anywhere()
    test_env_detection_precedence()
    test_profile_dir_outside_home_rejected()
    test_profile_dir_override()
    test_profile_flush_only_own_config_dir_records()
    test_global_flush_skips_config_dir_tagged_records()
    test_profile_flush_matches_symlinked_filter_spelling()
    test_global_flush_still_attributes_untagged_legacy_records()
    test_no_env_profile_scope_absent()
    test_env_precedence_nonexistent_highest_wins()
    test_tilde_prefixed_env_expanded()
    test_symlink_escape_rejected()
    test_flush_non_string_config_dir_no_crash()
    test_cli_auto_profile_writes_provisional()
    test_cli_auto_profile_confirmed_rejected_without_force()
    test_cli_confirm_profile_flushes_tagged_pending()
    test_cli_confirm_profile_no_identity_errors()
    test_cli_profile_dir_is_regular_file_clean_error()
    test_cli_init_profile_happy_path()
    test_cli_init_profile_force_overwrites_confirmed()
    test_cli_show_profile_three_paths()
    test_cross_language_profile_resolution_agrees()
    print("All tests passed.")
