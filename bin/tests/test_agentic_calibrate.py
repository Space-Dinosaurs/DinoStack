#!/usr/bin/env python3
"""
Tests for agentic-calibrate: Skeptic calibration rollup CLI.

Subcommands: density [--since ISO8601] [--task task_id]
             divergence [--since ISO8601]
             help

Exit codes: 0 success; 1 missing events log; 2 malformed input.

Run with: python3 bin/tests/test_agentic_calibrate.py
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

_BIN_PATH = Path(__file__).parent.parent / "agentic-calibrate"
_loader = importlib.machinery.SourceFileLoader("agentic_calibrate", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_calibrate", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-calibrate from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)


def _make_skeptic_spawn_complete(
    task_id: str,
    ts: str,
    findings_count: dict,
    diff_lines: int,
    signed_off: bool = True,
    iteration: int = 1,
) -> str:
    return json.dumps({
        "ts": ts,
        "phase": "skeptic",
        "event": "spawn_complete",
        "agent": "skeptic",
        "task_id": task_id,
        "data": {
            "findings_count": findings_count,
            "diff_lines": diff_lines,
            "signed_off": signed_off,
            "iteration": iteration,
        },
    })


def _make_meta_review_complete(
    task_id: str,
    ts: str,
    critical_missed: list,
    major_missed: list,
    minor_missed: list,
    agreement: bool,
) -> str:
    return json.dumps({
        "ts": ts,
        "phase": "meta_review",
        "event": "meta_review_complete",
        "agent": None,
        "task_id": task_id,
        "data": {
            "original_task_id": task_id,
            "agreement": agreement,
            "divergence": {
                "critical_missed": critical_missed,
                "major_missed": major_missed,
                "minor_missed": minor_missed,
            },
        },
    })


def _capture_cmd(cmd_fn, args_ns, events_path: Path) -> tuple[int, str, str]:
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    out_cap = StringIO()
    err_cap = StringIO()
    sys.stdout = out_cap
    sys.stderr = err_cap
    try:
        old_env = os.environ.get("AGENTIC_DIR")
        os.environ["AGENTIC_DIR"] = str(events_path.parent)
        try:
            rc = cmd_fn(args_ns)
        finally:
            if old_env is None:
                os.environ.pop("AGENTIC_DIR", None)
            else:
                os.environ["AGENTIC_DIR"] = old_env
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return rc, out_cap.getvalue(), err_cap.getvalue()


def test_density_missing_events_exits_one():
    """density with no events.jsonl -> exit 1."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events_path = agentic / "events.jsonl"  # does not exist
        args = types.SimpleNamespace(since=None, task=None)
        # sys.exit is called inside; catch it
        try:
            rc, _, err = _capture_cmd(_mod.cmd_density, args, events_path)
            assert False, "Expected SystemExit(1)"
        except SystemExit as e:
            assert e.code == 1, f"Expected exit code 1, got {e.code}"
    print("PASS test_density_missing_events_exits_one")


def test_density_empty_events_warming_up():
    """density with no qualifying spawn_complete events -> warming-up message.

    NOTE: this fixture was previously a conductor_direct event. conductor_direct
    is no longer emitted by the conductor (deprecated in scanSessionAggregate per
    Unit A of events-emission-fix). The assertion is unchanged: any non-skeptic-
    spawn_complete event must produce the warming-up message. We use session_total
    (which is what Stop hook now writes in every session) as the non-qualifying
    event so the fixture reflects realistic events.jsonl content.
    """
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events_path = agentic / "events.jsonl"
        # Write a session_total event - not a skeptic spawn_complete; warming-up expected.
        events_path.write_text(
            json.dumps({"ts": "2026-05-01T10:00:00Z", "event": "session_total",
                        "agent": None, "task_id": None,
                        "data": {"spawn_count": 0, "by_agent": {}}}) + "\n"
        )
        args = types.SimpleNamespace(since=None, task=None)
        rc, out, _ = _capture_cmd(_mod.cmd_density, args, events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "warming up" in out, f"Expected 'warming up' in output: {out!r}"
    print("PASS test_density_empty_events_warming_up")


def test_density_renders_table_rows():
    """density renders one row per qualifying spawn_complete."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events_path = agentic / "events.jsonl"
        lines = [
            _make_skeptic_spawn_complete(
                f"T-{i}", f"2026-05-{i+1:02d}T10:00:00Z",
                {"critical": 0, "major": 1, "minor": 0}, diff_lines=50,
            )
            for i in range(3)
        ]
        events_path.write_text("\n".join(lines) + "\n")
        args = types.SimpleNamespace(since=None, task=None)
        rc, out, _ = _capture_cmd(_mod.cmd_density, args, events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "T-0" in out or "T-1" in out or "T-2" in out, (
            f"Expected task IDs in output: {out!r}"
        )
        assert "warming up" in out, "Only 3 spawns; still warming up"
    print("PASS test_density_renders_table_rows")


def test_density_aggregate_above_threshold():
    """density shows aggregate line when >= WARMING_UP_THRESHOLD qualifying spawns."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events_path = agentic / "events.jsonl"
        n = _mod.WARMING_UP_THRESHOLD
        lines = [
            _make_skeptic_spawn_complete(
                f"T-{i}", f"2026-05-01T{10+i:02d}:00:00Z",
                {"critical": 0, "major": 1, "minor": 1}, diff_lines=100,
            )
            for i in range(n)
        ]
        events_path.write_text("\n".join(lines) + "\n")
        args = types.SimpleNamespace(since=None, task=None)
        rc, out, _ = _capture_cmd(_mod.cmd_density, args, events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "Aggregate" in out, f"Expected 'Aggregate' line above threshold: {out!r}"
        assert "warming up" not in out, f"Should not show warming-up above threshold: {out!r}"
    print("PASS test_density_aggregate_above_threshold")


def test_density_task_filter():
    """--task filters density rows to a specific task_id."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events_path = agentic / "events.jsonl"
        events_path.write_text(
            _make_skeptic_spawn_complete("TASK-A", "2026-05-01T10:00:00Z",
                                         {"critical": 1, "major": 0, "minor": 0}, 80) + "\n"
            + _make_skeptic_spawn_complete("TASK-B", "2026-05-01T10:01:00Z",
                                            {"critical": 0, "major": 0, "minor": 1}, 40) + "\n"
        )
        args = types.SimpleNamespace(since=None, task="TASK-A")
        rc, out, _ = _capture_cmd(_mod.cmd_density, args, events_path)
        assert rc == 0
        assert "TASK-A" in out, f"Expected TASK-A in filtered output: {out!r}"
        # TASK-B should not appear in the data rows (it's filtered out)
        data_lines = [l for l in out.splitlines() if "TASK-B" in l]
        assert not data_lines, f"TASK-B should be filtered out: {out!r}"
    print("PASS test_density_task_filter")


def test_density_since_filter():
    """--since filters events before the given timestamp."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events_path = agentic / "events.jsonl"
        events_path.write_text(
            _make_skeptic_spawn_complete("OLD", "2026-01-01T10:00:00Z",
                                         {"critical": 0, "major": 0, "minor": 1}, 10) + "\n"
            + _make_skeptic_spawn_complete("NEW", "2026-06-01T10:00:00Z",
                                            {"critical": 0, "major": 1, "minor": 0}, 20) + "\n"
        )
        args = types.SimpleNamespace(since="2026-05-01T00:00:00Z", task=None)
        rc, out, _ = _capture_cmd(_mod.cmd_density, args, events_path)
        assert rc == 0
        assert "NEW" in out, f"Expected NEW task in post-since output: {out!r}"
        old_rows = [l for l in out.splitlines() if "OLD" in l]
        assert not old_rows, f"OLD task should be filtered by --since: {out!r}"
    print("PASS test_density_since_filter")


def test_density_malformed_since_exits_two():
    """--since with invalid ISO8601 -> exit 2."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events_path = agentic / "events.jsonl"
        events_path.write_text("")
        args = types.SimpleNamespace(since="not-a-date", task=None)
        try:
            _capture_cmd(_mod.cmd_density, args, events_path)
            assert False, "Expected SystemExit(2)"
        except SystemExit as e:
            assert e.code == 2, f"Expected exit 2 for malformed since, got {e.code}"
    print("PASS test_density_malformed_since_exits_two")


def test_divergence_no_meta_events():
    """divergence with no meta_review_complete events -> informational message."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events_path = agentic / "events.jsonl"
        events_path.write_text(
            json.dumps({"ts": "2026-05-01T10:00:00Z", "event": "spawn_complete",
                        "agent": "engineer", "task_id": "T-1", "data": {}}) + "\n"
        )
        args = types.SimpleNamespace(since=None)
        rc, out, _ = _capture_cmd(_mod.cmd_divergence, args, events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "No meta_review_complete" in out, f"Expected empty-data message: {out!r}"
    print("PASS test_divergence_no_meta_events")


def test_divergence_renders_table():
    """divergence renders rate table from meta_review_complete events."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events_path = agentic / "events.jsonl"
        events_path.write_text(
            _make_meta_review_complete("T-1", "2026-05-01T10:00:00Z",
                                       ["missing-critical"], [], [], False) + "\n"
            + _make_meta_review_complete("T-2", "2026-05-02T10:00:00Z",
                                          [], [], [], True) + "\n"
        )
        args = types.SimpleNamespace(since=None)
        rc, out, _ = _capture_cmd(_mod.cmd_divergence, args, events_path)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "Sampled spawns: 2" in out, f"Expected 2 samples: {out!r}"
        assert "T-1" in out, f"Expected T-1 in output: {out!r}"
        assert "T-2" in out, f"Expected T-2 in output: {out!r}"
        assert "Full agreement" in out, f"Expected agreement rate: {out!r}"
    print("PASS test_divergence_renders_table")


def test_help_subcommand_exits_zero():
    """help subcommand prints help and exits 0."""
    args = types.SimpleNamespace()
    old_stdout = sys.stdout
    captured = StringIO()
    sys.stdout = captured
    try:
        rc = _mod.cmd_help(args)
    finally:
        sys.stdout = old_stdout
    assert rc == 0, f"Expected rc=0, got {rc}"
    out = captured.getvalue()
    assert "density" in out and "divergence" in out, (
        f"Expected subcommand names in help: {out!r}"
    )
    print("PASS test_help_subcommand_exits_zero")


def test_is_skeptic_spawn_complete():
    """_is_skeptic_spawn_complete identifies correct events."""
    yes = {"event": "spawn_complete", "agent": "skeptic"}
    no1 = {"event": "spawn_complete", "agent": "engineer"}
    no2 = {"event": "spawn_start", "agent": "skeptic"}
    assert _mod._is_skeptic_spawn_complete(yes) is True
    assert _mod._is_skeptic_spawn_complete(no1) is False
    assert _mod._is_skeptic_spawn_complete(no2) is False
    print("PASS test_is_skeptic_spawn_complete")


def test_is_meta_review_complete():
    """_is_meta_review_complete identifies correct events."""
    yes = {"event": "meta_review_complete"}
    no = {"event": "spawn_complete"}
    assert _mod._is_meta_review_complete(yes) is True
    assert _mod._is_meta_review_complete(no) is False
    print("PASS test_is_meta_review_complete")


if __name__ == "__main__":
    test_density_missing_events_exits_one()
    test_density_empty_events_warming_up()
    test_density_renders_table_rows()
    test_density_aggregate_above_threshold()
    test_density_task_filter()
    test_density_since_filter()
    test_density_malformed_since_exits_two()
    test_divergence_no_meta_events()
    test_divergence_renders_table()
    test_help_subcommand_exits_zero()
    test_is_skeptic_spawn_complete()
    test_is_meta_review_complete()
    print("All agentic-calibrate tests passed.")
