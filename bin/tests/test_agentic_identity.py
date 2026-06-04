#!/usr/bin/env python3
"""
Regression test for flushPendingBuffer canonical shape fix.

Verifies that flushed session-log lines match the canonical shape written by
hooks/stop-context.js writeSessionLog / writeSessionLogGlobal:
  {ts, phase, event, agent, task_id, developer_id, session_uuid,
   project_slug, branch, data}

The pre-fix behavior (dict(record) + developer_id) would produce lines that
include schema_version and repo_root, which are absent from the canonical
shape. Any consumer filtering on phase == 'session_end' / event == 'session_total'
would silently drop or misparse flushed records in a mixed-schema file.

Regression test obligation: content/references/regression-test-obligation.md
Run with: python3 bin/tests/test_agentic_identity.py
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


def _write_pending(pending_dir: Path, record: dict) -> Path:
    """Write a pending record file. Returns the path."""
    pending_dir.mkdir(parents=True, exist_ok=True)
    p = pending_dir / f"{record['session_uuid']}.json"
    p.write_text(json.dumps(record), encoding="utf-8")
    return p


def test_flushed_line_canonical_shape():
    """flushed line must match canonical shape; must NOT contain schema_version or repo_root."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pending_dir = tmp_path / "session-log" / ".pending"
        global_log_dir = tmp_path / "session-log"
        flush_lock = tmp_path / "session-log" / ".flush.lock"

        # Patch module-level paths
        _mod.PENDING_DIR = pending_dir
        _mod.GLOBAL_SESSION_LOG_DIR = global_log_dir
        _mod.FLUSH_LOCK_PATH = flush_lock

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
        flush_lock.parent.mkdir(parents=True, exist_ok=True)
        flush_lock.touch(exist_ok=True)

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


if __name__ == "__main__":
    test_flushed_line_canonical_shape()
    print("All tests passed.")
