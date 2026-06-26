#!/usr/bin/env python3
"""
Tests for agentic-cost session/task/project/operator subcommands.
(retro and team are covered by test_agentic_cost_retro.py and
test_agentic_cost_team.py respectively.)

Run with: python3 bin/tests/test_agentic_cost_subcommands.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import types
from io import StringIO
from pathlib import Path

_COST_PATH = Path(__file__).parent.parent / "agentic-cost"
loader = importlib.machinery.SourceFileLoader("agentic_cost", str(_COST_PATH))
spec = importlib.util.spec_from_loader("agentic_cost", loader)
if spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-cost from {_COST_PATH}")
_mod = importlib.util.module_from_spec(spec)
loader.exec_module(_mod)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spawn_complete(
    agent: str,
    task_id: str | None,
    session_uuid: str | None,
    ts: str,
    input_tokens: int = 100,
    output_tokens: int = 50,
    wall_seconds: float = 10.0,
    model: str = "claude-sonnet",
) -> str:
    return json.dumps({
        "ts": ts,
        "phase": "test",
        "event": "spawn_complete",
        "agent": agent,
        "task_id": task_id,
        "data": {
            "session_uuid": session_uuid,
            "model": model,
            "wall_seconds": wall_seconds,
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "cache_creation": 0,
                "cache_read": 0,
            },
        },
    })


def _make_session_line(
    developer_id: str,
    session_uuid: str,
    project_slug: str,
    ts: str,
    wall: float = 60.0,
    input_tokens: int = 1000,
    output_tokens: int = 500,
) -> str:
    return json.dumps({
        "ts": ts,
        "phase": "session_end",
        "event": "session_total",
        "agent": None,
        "task_id": None,
        "developer_id": developer_id,
        "session_uuid": session_uuid,
        "project_slug": project_slug,
        "branch": "main",
        "data": {
            "wall_seconds": wall,
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "cache_creation": 0,
                "cache_read": 0,
            },
            "spawn_count": 1,
            "by_agent": {},
        },
    })


def _capture_cmd(cmd_fn, args_ns, events_path: Path | None = None,
                 session_log_dir: Path | None = None,
                 global_log_dir: Path | None = None) -> tuple[int, str, str]:
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    out_cap = StringIO()
    err_cap = StringIO()
    sys.stdout = out_cap
    sys.stderr = err_cap

    orig_events = _mod.EVENTS_PATH
    orig_session = _mod.SESSION_LOG_DIR
    orig_global = _mod.GLOBAL_SESSION_LOG_DIR

    if events_path is not None:
        _mod.EVENTS_PATH = events_path
    if session_log_dir is not None:
        _mod.SESSION_LOG_DIR = session_log_dir
    if global_log_dir is not None:
        _mod.GLOBAL_SESSION_LOG_DIR = global_log_dir

    try:
        rc = cmd_fn(args_ns)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        _mod.EVENTS_PATH = orig_events
        _mod.SESSION_LOG_DIR = orig_session
        _mod.GLOBAL_SESSION_LOG_DIR = orig_global

    return rc, out_cap.getvalue(), err_cap.getvalue()


# ---------------------------------------------------------------------------
# cmd_session tests
# ---------------------------------------------------------------------------

def test_session_no_events_empty_table():
    """session with missing events.jsonl -> exit 0, TOTAL row at zero."""
    with tempfile.TemporaryDirectory() as tmp:
        nonexistent = Path(tmp) / "events.jsonl"
        args = types.SimpleNamespace(session_uuid=None)
        rc, out, _ = _capture_cmd(_mod.cmd_session, args, events_path=nonexistent)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "TOTAL" in out, f"Expected TOTAL row even with no events: {out!r}"
    print("PASS test_session_no_events_empty_table")


def test_session_all_events_aggregated():
    """session with no UUID filter aggregates all spawn_complete events."""
    with tempfile.TemporaryDirectory() as tmp:
        events_path = Path(tmp) / "events.jsonl"
        events_path.write_text(
            _make_spawn_complete("engineer", "T-1", "uuid-A", "2026-05-01T10:00:00Z",
                                  input_tokens=200, output_tokens=100) + "\n"
            + _make_spawn_complete("skeptic", "T-1", "uuid-A", "2026-05-01T10:01:00Z",
                                   input_tokens=150, output_tokens=80) + "\n"
        )
        args = types.SimpleNamespace(session_uuid=None)
        rc, out, _ = _capture_cmd(_mod.cmd_session, args, events_path=events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "engineer" in out, f"Expected engineer row: {out!r}"
        assert "skeptic" in out, f"Expected skeptic row: {out!r}"
        assert "TOTAL" in out
    print("PASS test_session_all_events_aggregated")


def test_session_uuid_filter():
    """session with UUID filter shows only matching events."""
    with tempfile.TemporaryDirectory() as tmp:
        events_path = Path(tmp) / "events.jsonl"
        events_path.write_text(
            _make_spawn_complete("engineer", "T-1", "uuid-A", "2026-05-01T10:00:00Z",
                                  input_tokens=500) + "\n"
            + _make_spawn_complete("engineer", "T-2", "uuid-B", "2026-05-01T10:01:00Z",
                                   input_tokens=300) + "\n"
        )
        args = types.SimpleNamespace(session_uuid="uuid-A")
        rc, out, _ = _capture_cmd(_mod.cmd_session, args, events_path=events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "engineer" in out
        # uuid-B had 300 input tokens; uuid-A had 500. TOTAL should reflect only uuid-A
        assert "500" in out, f"Expected 500 tokens from uuid-A: {out!r}"
    print("PASS test_session_uuid_filter")


def test_session_v1_footer_present():
    """session output always includes the V1 disclosure footer."""
    with tempfile.TemporaryDirectory() as tmp:
        events_path = Path(tmp) / "events.jsonl"
        events_path.write_text("")
        args = types.SimpleNamespace(session_uuid=None)
        rc, out, _ = _capture_cmd(_mod.cmd_session, args, events_path=events_path)
        assert rc == 0
        assert _mod.V1_FOOTER in out, f"V1 footer missing from session output: {out!r}"
    print("PASS test_session_v1_footer_present")


# ---------------------------------------------------------------------------
# cmd_task tests
# ---------------------------------------------------------------------------

def test_task_filters_by_task_id():
    """task subcommand shows only events with the specified task_id."""
    with tempfile.TemporaryDirectory() as tmp:
        events_path = Path(tmp) / "events.jsonl"
        events_path.write_text(
            _make_spawn_complete("engineer", "TASK-A", None, "2026-05-01T10:00:00Z",
                                  input_tokens=400) + "\n"
            + _make_spawn_complete("engineer", "TASK-B", None, "2026-05-01T10:01:00Z",
                                   input_tokens=200) + "\n"
        )
        args = types.SimpleNamespace(task_id="TASK-A")
        rc, out, _ = _capture_cmd(_mod.cmd_task, args, events_path=events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "400" in out, f"Expected 400 tokens for TASK-A: {out!r}"
        assert "200" not in out or "TASK-B" not in out, (
            f"TASK-B tokens should not appear: {out!r}"
        )
    print("PASS test_task_filters_by_task_id")


def test_task_no_matching_events_empty_table():
    """task with non-existent task_id -> exit 0, TOTAL row at zero."""
    with tempfile.TemporaryDirectory() as tmp:
        events_path = Path(tmp) / "events.jsonl"
        events_path.write_text(
            _make_spawn_complete("engineer", "TASK-X", None, "2026-05-01T10:00:00Z") + "\n"
        )
        args = types.SimpleNamespace(task_id="NO-SUCH-TASK")
        rc, out, _ = _capture_cmd(_mod.cmd_task, args, events_path=events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "TOTAL" in out
    print("PASS test_task_no_matching_events_empty_table")


def test_task_v1_footer_present():
    """task output always includes the V1 disclosure footer."""
    with tempfile.TemporaryDirectory() as tmp:
        events_path = Path(tmp) / "events.jsonl"
        events_path.write_text("")
        args = types.SimpleNamespace(task_id="T-1")
        rc, out, _ = _capture_cmd(_mod.cmd_task, args, events_path=events_path)
        assert rc == 0
        assert _mod.V1_FOOTER in out, f"V1 footer missing: {out!r}"
    print("PASS test_task_v1_footer_present")


# ---------------------------------------------------------------------------
# cmd_project tests
# ---------------------------------------------------------------------------

def test_project_all_events_no_since():
    """project with no --since shows all events."""
    with tempfile.TemporaryDirectory() as tmp:
        events_path = Path(tmp) / "events.jsonl"
        events_path.write_text(
            _make_spawn_complete("engineer", "T-1", None, "2026-01-01T10:00:00Z",
                                  input_tokens=999) + "\n"
        )
        args = types.SimpleNamespace(since=None)
        rc, out, _ = _capture_cmd(_mod.cmd_project, args, events_path=events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "999" in out, f"Expected 999 tokens in output: {out!r}"
    print("PASS test_project_all_events_no_since")


def test_project_since_filter():
    """project --since filters old events."""
    with tempfile.TemporaryDirectory() as tmp:
        events_path = Path(tmp) / "events.jsonl"
        events_path.write_text(
            _make_spawn_complete("engineer", "OLD", None, "2026-01-01T10:00:00Z",
                                  input_tokens=777) + "\n"
            + _make_spawn_complete("skeptic", "NEW", None, "2026-06-01T10:00:00Z",
                                   input_tokens=333) + "\n"
        )
        args = types.SimpleNamespace(since="2026-05-01")
        rc, out, _ = _capture_cmd(_mod.cmd_project, args, events_path=events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "333" in out, f"Expected 333 tokens (NEW event): {out!r}"
        assert "777" not in out, f"777 should be filtered by --since: {out!r}"
    print("PASS test_project_since_filter")


def test_project_invalid_since_returns_two():
    """project with invalid --since date -> exit 2."""
    with tempfile.TemporaryDirectory() as tmp:
        events_path = Path(tmp) / "events.jsonl"
        events_path.write_text("")
        args = types.SimpleNamespace(since="not-a-date")
        rc, _, err = _capture_cmd(_mod.cmd_project, args, events_path=events_path)
        assert rc == 2, f"Expected rc=2 for invalid date, got {rc}"
        assert "invalid" in err.lower(), f"Expected error message in stderr: {err!r}"
    print("PASS test_project_invalid_since_returns_two")


def test_project_v1_footer_present():
    """project output always includes the V1 disclosure footer."""
    with tempfile.TemporaryDirectory() as tmp:
        events_path = Path(tmp) / "events.jsonl"
        events_path.write_text("")
        args = types.SimpleNamespace(since=None)
        rc, out, _ = _capture_cmd(_mod.cmd_project, args, events_path=events_path)
        assert rc == 0
        assert _mod.V1_FOOTER in out, f"V1 footer missing: {out!r}"
    print("PASS test_project_v1_footer_present")


# ---------------------------------------------------------------------------
# cmd_operator tests
# ---------------------------------------------------------------------------

def test_operator_no_data_guidance_message():
    """operator with empty global log dir -> exit 0, guidance message."""
    with tempfile.TemporaryDirectory() as tmp:
        global_log = Path(tmp) / "session-log"
        global_log.mkdir()
        args = types.SimpleNamespace(since=None, json=False)
        rc, out, _ = _capture_cmd(_mod.cmd_operator, args, global_log_dir=global_log)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "No operator session data" in out, (
            f"Expected guidance message: {out!r}"
        )
    print("PASS test_operator_no_data_guidance_message")


def test_operator_aggregates_by_developer_and_project():
    """operator aggregates (developer_id, project_slug) across global session logs."""
    with tempfile.TemporaryDirectory() as tmp:
        global_log = Path(tmp) / "session-log"
        global_log.mkdir()
        (global_log / "alice.jsonl").write_text(
            _make_session_line("alice", "uuid-1", "proj-alpha", "2026-05-01T10:00:00Z",
                                input_tokens=1000) + "\n"
            + _make_session_line("alice", "uuid-2", "proj-beta", "2026-05-02T10:00:00Z",
                                  input_tokens=500) + "\n"
        )
        (global_log / "bob.jsonl").write_text(
            _make_session_line("bob", "uuid-3", "proj-alpha", "2026-05-03T10:00:00Z",
                                input_tokens=800) + "\n"
        )
        args = types.SimpleNamespace(since=None, json=False)
        rc, out, _ = _capture_cmd(_mod.cmd_operator, args, global_log_dir=global_log)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "alice" in out, f"Expected alice in output: {out!r}"
        assert "bob" in out, f"Expected bob in output: {out!r}"
        assert "proj-alpha" in out, f"Expected proj-alpha in output: {out!r}"
        assert "proj-beta" in out, f"Expected proj-beta in output: {out!r}"
    print("PASS test_operator_aggregates_by_developer_and_project")


def test_operator_json_mode():
    """operator --json produces valid JSON keyed by developer."""
    with tempfile.TemporaryDirectory() as tmp:
        global_log = Path(tmp) / "session-log"
        global_log.mkdir()
        (global_log / "alice.jsonl").write_text(
            _make_session_line("alice", "uuid-1", "proj-x", "2026-05-01T10:00:00Z") + "\n"
        )
        args = types.SimpleNamespace(since=None, json=True)
        rc, out, _ = _capture_cmd(_mod.cmd_operator, args, global_log_dir=global_log)
        assert rc == 0, f"Expected rc=0, got {rc}"
        data = json.loads(out)
        assert "alice" in data, f"Expected 'alice' in JSON output: {data}"
        assert "proj-x" in data["alice"], f"Expected 'proj-x' in alice's projects: {data}"
    print("PASS test_operator_json_mode")


def test_operator_since_filter():
    """operator --since filters records before cutoff."""
    with tempfile.TemporaryDirectory() as tmp:
        global_log = Path(tmp) / "session-log"
        global_log.mkdir()
        (global_log / "alice.jsonl").write_text(
            _make_session_line("alice", "old", "old-proj", "2026-01-01T10:00:00Z",
                                input_tokens=9999) + "\n"
            + _make_session_line("alice", "new", "new-proj", "2026-06-01T10:00:00Z",
                                  input_tokens=111) + "\n"
        )
        args = types.SimpleNamespace(since="2026-05-01", json=False)
        rc, out, _ = _capture_cmd(_mod.cmd_operator, args, global_log_dir=global_log)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "new-proj" in out, f"Expected new-proj in filtered output: {out!r}"
        assert "old-proj" not in out, f"old-proj should be filtered: {out!r}"
    print("PASS test_operator_since_filter")


def test_operator_since_filters_all_returns_guidance():
    """operator --since that filters everything -> guidance message, exit 0."""
    with tempfile.TemporaryDirectory() as tmp:
        global_log = Path(tmp) / "session-log"
        global_log.mkdir()
        (global_log / "alice.jsonl").write_text(
            _make_session_line("alice", "old", "old-proj", "2026-01-01T10:00:00Z") + "\n"
        )
        args = types.SimpleNamespace(since="2030-01-01", json=False)
        rc, out, _ = _capture_cmd(_mod.cmd_operator, args, global_log_dir=global_log)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "No operator session data" in out, (
            f"Expected guidance message when all filtered: {out!r}"
        )
    print("PASS test_operator_since_filters_all_returns_guidance")


# ---------------------------------------------------------------------------
# _aggregate_operator unit tests
# ---------------------------------------------------------------------------

def test_aggregate_operator_groups_by_dev_and_project():
    """_aggregate_operator groups by (developer_id, project_slug)."""
    records = [
        {"developer_id": "alice", "project_slug": "proj-a",
         "data": {"wall_seconds": 10.0, "tokens": {"input": 100, "output": 50,
                                                     "cache_creation": 0, "cache_read": 0}}},
        {"developer_id": "alice", "project_slug": "proj-a",
         "data": {"wall_seconds": 20.0, "tokens": {"input": 200, "output": 100,
                                                     "cache_creation": 0, "cache_read": 0}}},
        {"developer_id": "alice", "project_slug": "proj-b",
         "data": {"wall_seconds": 5.0, "tokens": {"input": 50, "output": 25,
                                                    "cache_creation": 0, "cache_read": 0}}},
    ]
    agg = _mod._aggregate_operator(records)
    key_aa = ("alice", "proj-a")
    key_ab = ("alice", "proj-b")
    assert key_aa in agg, f"Expected key {key_aa} in agg"
    assert key_ab in agg, f"Expected key {key_ab} in agg"
    assert agg[key_aa]["sessions"] == 2
    assert agg[key_aa]["tokens"]["input"] == 300
    assert agg[key_ab]["sessions"] == 1
    assert agg[key_ab]["tokens"]["input"] == 50
    print("PASS test_aggregate_operator_groups_by_dev_and_project")


def test_aggregate_operator_skips_missing_developer_id():
    """_aggregate_operator skips records without developer_id."""
    records = [
        {"project_slug": "proj-x",
         "data": {"wall_seconds": 5.0, "tokens": {"input": 100, "output": 50,
                                                    "cache_creation": 0, "cache_read": 0}}},
        {"developer_id": "bob", "project_slug": "proj-y",
         "data": {"wall_seconds": 10.0, "tokens": {"input": 200, "output": 80,
                                                     "cache_creation": 0, "cache_read": 0}}},
    ]
    agg = _mod._aggregate_operator(records)
    assert len(agg) == 1, f"Expected 1 bucket (no-dev record skipped), got {len(agg)}"
    assert ("bob", "proj-y") in agg
    print("PASS test_aggregate_operator_skips_missing_developer_id")


def test_filter_records_since():
    """_filter_records_since drops records before cutoff."""
    records = [
        {"ts": "2026-01-01T00:00:00Z", "developer_id": "alice"},
        {"ts": "2026-06-01T00:00:00Z", "developer_id": "bob"},
    ]
    filtered = _mod._filter_records_since(records, "2026-05-01")
    assert len(filtered) == 1, f"Expected 1 record after since filter, got {len(filtered)}"
    assert filtered[0]["developer_id"] == "bob"
    print("PASS test_filter_records_since")


if __name__ == "__main__":
    # session
    test_session_no_events_empty_table()
    test_session_all_events_aggregated()
    test_session_uuid_filter()
    test_session_v1_footer_present()
    # task
    test_task_filters_by_task_id()
    test_task_no_matching_events_empty_table()
    test_task_v1_footer_present()
    # project
    test_project_all_events_no_since()
    test_project_since_filter()
    test_project_invalid_since_returns_two()
    test_project_v1_footer_present()
    # operator
    test_operator_no_data_guidance_message()
    test_operator_aggregates_by_developer_and_project()
    test_operator_json_mode()
    test_operator_since_filter()
    test_operator_since_filters_all_returns_guidance()
    # unit helpers
    test_aggregate_operator_groups_by_dev_and_project()
    test_aggregate_operator_skips_missing_developer_id()
    test_filter_records_since()
    print("All agentic-cost session/task/project/operator tests passed.")
