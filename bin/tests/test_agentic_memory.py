#!/usr/bin/env python3
"""
Tests for agentic-memory: memory retrieval CLI.

Subcommands: query [keyword] [--since] [--until] [--type] [--agent]
             [--last N] [--source ...] [--topic]
             turns --last N

Run with: python3 bin/tests/test_agentic_memory.py
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

_BIN_PATH = Path(__file__).parent.parent / "agentic-memory"
_loader = importlib.machinery.SourceFileLoader("agentic_memory", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_memory", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-memory from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)


def _make_event(event: str, ts: str, agent: str | None = None, task_id: str | None = None, data: dict | None = None) -> str:
    return json.dumps({
        "ts": ts,
        "phase": "test",
        "event": event,
        "agent": agent,
        "task_id": task_id,
        "data": data or {},
    })


def _capture_query(args_ns: types.SimpleNamespace, cwd: str) -> tuple[int, str, str]:
    old_cwd = os.getcwd()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    out_cap = StringIO()
    err_cap = StringIO()
    sys.stdout = out_cap
    sys.stderr = err_cap
    try:
        os.chdir(cwd)
        rc = _mod.cmd_query(args_ns)
    finally:
        os.chdir(old_cwd)
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return rc, out_cap.getvalue(), err_cap.getvalue()


def _capture_turns(args_ns: types.SimpleNamespace, cwd: str) -> tuple[int, str, str]:
    old_cwd = os.getcwd()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    out_cap = StringIO()
    err_cap = StringIO()
    sys.stdout = out_cap
    sys.stderr = err_cap
    try:
        os.chdir(cwd)
        rc = _mod.cmd_turns(args_ns)
    finally:
        os.chdir(old_cwd)
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return rc, out_cap.getvalue(), err_cap.getvalue()


def _make_query_args(**kwargs) -> types.SimpleNamespace:
    defaults = {
        "keyword": None,
        "since": None,
        "until": None,
        "type": None,
        "agent": None,
        "last": None,
        "source": None,
        "topic": None,
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


def test_query_no_sources_returns_zero():
    """query with no source files -> exit 0, 'No results found'."""
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, _ = _capture_query(_make_query_args(), tmp)
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "No results found" in out, f"Expected 'No results found', got: {out!r}"
    print("PASS test_query_no_sources_returns_zero")


def test_query_events_jsonl_keyword_match():
    """query with keyword finds matching events."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events = agentic / "events.jsonl"
        events.write_text(
            _make_event("spawn_start", "2026-05-01T10:00:00Z", agent="engineer", task_id="T-1") + "\n"
            + _make_event("spawn_complete", "2026-05-01T10:01:00Z", agent="skeptic") + "\n"
        )

        old_events = _mod.EVENTS_PATH
        _mod.EVENTS_PATH = events
        try:
            rc, out, _ = _capture_query(_make_query_args(keyword="engineer", source="events.jsonl"), tmp)
        finally:
            _mod.EVENTS_PATH = old_events

        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "engineer" in out, f"Expected 'engineer' in output: {out!r}"
        assert "spawn_complete" not in out or "skeptic" not in out, (
            "Skeptic-only event should not match 'engineer' keyword"
        )
    print("PASS test_query_events_jsonl_keyword_match")


def test_query_events_date_filter():
    """--since and --until filter events by timestamp."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events = agentic / "events.jsonl"
        events.write_text(
            _make_event("old_event", "2026-01-01T00:00:00Z") + "\n"
            + _make_event("new_event", "2026-06-01T00:00:00Z") + "\n"
        )

        old_events = _mod.EVENTS_PATH
        _mod.EVENTS_PATH = events
        try:
            rc, out, _ = _capture_query(
                _make_query_args(source="events.jsonl", since="2026-05-01", until="2026-07-01"),
                tmp,
            )
        finally:
            _mod.EVENTS_PATH = old_events

        assert rc == 0
        assert "new_event" in out, f"Expected 'new_event' in output: {out!r}"
        assert "old_event" not in out, f"old_event should be filtered out: {out!r}"
    print("PASS test_query_events_date_filter")


def test_query_events_agent_filter():
    """--agent filters events by agent name."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events = agentic / "events.jsonl"
        events.write_text(
            _make_event("spawn_complete", "2026-05-01T10:00:00Z", agent="engineer") + "\n"
            + _make_event("spawn_complete", "2026-05-01T10:01:00Z", agent="skeptic") + "\n"
        )

        old_events = _mod.EVENTS_PATH
        _mod.EVENTS_PATH = events
        try:
            rc, out, _ = _capture_query(
                _make_query_args(source="events.jsonl", agent="engineer"),
                tmp,
            )
        finally:
            _mod.EVENTS_PATH = old_events

        assert rc == 0
        assert "engineer" in out
        # The skeptic line should not appear
        result_lines = [l for l in out.splitlines() if "skeptic" in l]
        assert not result_lines, f"skeptic should not appear in agent-filtered output: {out!r}"
    print("PASS test_query_events_agent_filter")


def test_query_events_last_filter():
    """--last N returns only the last N events."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events = agentic / "events.jsonl"
        lines = [_make_event(f"ev_{i}", f"2026-05-{i+1:02d}T10:00:00Z") for i in range(5)]
        events.write_text("\n".join(lines) + "\n")

        old_events = _mod.EVENTS_PATH
        _mod.EVENTS_PATH = events
        try:
            rc, out, _ = _capture_query(
                _make_query_args(source="events.jsonl", last=2),
                tmp,
            )
        finally:
            _mod.EVENTS_PATH = old_events

        assert rc == 0
        # Should contain ev_3 and ev_4 (last 2), not ev_0
        assert "ev_3" in out or "ev_4" in out, f"Expected last 2 events: {out!r}"
        assert "ev_0" not in out, f"ev_0 should not appear with --last 2: {out!r}"
    print("PASS test_query_events_last_filter")


def test_query_memory_md_keyword():
    """query searches MEMORY.md for keyword in section heading/body."""
    with tempfile.TemporaryDirectory() as tmp:
        memory = Path(tmp) / "MEMORY.md"
        memory.write_text(
            "## Architecture\nWe use Python for all CLIs.\n\n"
            "## Deployment\nUsing Railway for hosting.\n"
        )

        old_paths = _mod.MEMORY_PATHS
        _mod.MEMORY_PATHS = [memory]
        try:
            rc, out, _ = _capture_query(
                _make_query_args(keyword="python", source="MEMORY.md"),
                tmp,
            )
        finally:
            _mod.MEMORY_PATHS = old_paths

        assert rc == 0
        assert "Architecture" in out, f"Expected 'Architecture' section: {out!r}"
        assert "Deployment" not in out, f"Deployment section should be filtered: {out!r}"
    print("PASS test_query_memory_md_keyword")


def test_query_memory_md_topic():
    """--topic filters MEMORY.md by section heading."""
    with tempfile.TemporaryDirectory() as tmp:
        memory = Path(tmp) / "MEMORY.md"
        memory.write_text(
            "## Git Workflow\nAlways commit with -s for DCO.\n\n"
            "## Testing\nRun python3 bin/tests/*.py\n"
        )

        old_paths = _mod.MEMORY_PATHS
        _mod.MEMORY_PATHS = [memory]
        try:
            rc, out, _ = _capture_query(
                _make_query_args(topic="git", source="MEMORY.md"),
                tmp,
            )
        finally:
            _mod.MEMORY_PATHS = old_paths

        assert rc == 0
        assert "Git Workflow" in out, f"Expected 'Git Workflow' section: {out!r}"
        assert "Testing" not in out, f"Testing section should not appear: {out!r}"
    print("PASS test_query_memory_md_topic")


def test_query_missing_source_warning_on_stderr():
    """Missing source files produce a warning on stderr, not a crash."""
    with tempfile.TemporaryDirectory() as tmp:
        old_events = _mod.EVENTS_PATH
        _mod.EVENTS_PATH = Path(tmp) / "nonexistent.jsonl"
        try:
            rc, out, err = _capture_query(
                _make_query_args(source="events.jsonl"),
                tmp,
            )
        finally:
            _mod.EVENTS_PATH = old_events

        assert rc == 0, f"Expected rc=0 for missing source, got {rc}"
        assert "Warning" in err or "not found" in err, (
            f"Expected warning on stderr: {err!r}"
        )
    print("PASS test_query_missing_source_warning_on_stderr")


def test_query_malformed_jsonl_skipped():
    """Malformed JSONL lines are skipped; valid lines still returned."""
    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        agentic.mkdir()
        events = agentic / "events.jsonl"
        events.write_text(
            "NOT_VALID_JSON\n"
            + _make_event("good_event", "2026-05-01T10:00:00Z") + "\n"
        )

        old_events = _mod.EVENTS_PATH
        _mod.EVENTS_PATH = events
        try:
            rc, out, err = _capture_query(
                _make_query_args(source="events.jsonl"),
                tmp,
            )
        finally:
            _mod.EVENTS_PATH = old_events

        assert rc == 0
        assert "good_event" in out, f"Expected valid event in output: {out!r}"
        assert "Warning" in err or "malformed" in err, (
            f"Expected malformed line warning on stderr: {err!r}"
        )
    print("PASS test_query_malformed_jsonl_skipped")


def test_turns_no_context_returns_zero():
    """turns with no context.md -> exit 0, 'No results found'."""
    with tempfile.TemporaryDirectory() as tmp:
        old_ctx = _mod.CONTEXT_PATH
        _mod.CONTEXT_PATH = Path(tmp) / "nonexistent.md"
        try:
            args = types.SimpleNamespace(last=5)
            rc, out, _ = _capture_turns(args, tmp)
        finally:
            _mod.CONTEXT_PATH = old_ctx

        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "No results found" in out, f"Expected 'No results found': {out!r}"
    print("PASS test_turns_no_context_returns_zero")


def test_turns_with_heading_markers():
    """turns parses ## Turn headings from context.md."""
    with tempfile.TemporaryDirectory() as tmp:
        ctx = Path(tmp) / "context.md"
        ctx.write_text(
            "## Turn 1\nUser asked something.\n"
            "## Turn 2\nAgent responded.\n"
            "## Turn 3\nUser confirmed.\n"
        )

        old_ctx = _mod.CONTEXT_PATH
        _mod.CONTEXT_PATH = ctx
        try:
            args = types.SimpleNamespace(last=2)
            rc, out, _ = _capture_turns(args, tmp)
        finally:
            _mod.CONTEXT_PATH = old_ctx

        assert rc == 0, f"Expected rc=0, got {rc}"
        # last=2: the formatter labels sequentially (Turn 1, Turn 2) but content
        # comes from source turns 2 and 3. Check body content instead.
        assert "Agent responded" in out, f"Expected Turn 2 body in output: {out!r}"
        assert "User confirmed" in out, f"Expected Turn 3 body in output: {out!r}"
        assert "User asked something" not in out, f"Turn 1 body should be excluded with last=2: {out!r}"
    print("PASS test_turns_with_heading_markers")


def test_split_turns_separator_heuristic():
    """_split_turns uses '---' separators when no ## Turn headings exist."""
    text = "First block\nline2\n---\nSecond block\n---\nThird block"
    turns = _mod._split_turns(text)
    assert len(turns) == 3, f"Expected 3 turns from --- separators, got {len(turns)}"
    print("PASS test_split_turns_separator_heuristic")


def test_split_turns_blank_line_heuristic():
    """_split_turns falls back to blank-line separation."""
    text = "Block one\nline2\n\nBlock two\n\nBlock three"
    turns = _mod._split_turns(text)
    assert len(turns) == 3, f"Expected 3 turns from blank lines, got {len(turns)}"
    print("PASS test_split_turns_blank_line_heuristic")


def test_event_to_date_parses_iso():
    """_event_to_date parses standard ISO timestamps."""
    d = _mod._event_to_date("2026-05-15T10:00:00Z")
    assert d is not None, "Expected a date object"
    assert d.year == 2026 and d.month == 5 and d.day == 15, f"Unexpected date: {d}"
    print("PASS test_event_to_date_parses_iso")


def test_event_to_date_bad_input_returns_none():
    """_event_to_date returns None for invalid string timestamps."""
    # The function accepts str; None is not a valid call per the type annotation.
    assert _mod._event_to_date("not-a-date") is None
    assert _mod._event_to_date("") is None
    print("PASS test_event_to_date_bad_input_returns_none")


if __name__ == "__main__":
    test_query_no_sources_returns_zero()
    test_query_events_jsonl_keyword_match()
    test_query_events_date_filter()
    test_query_events_agent_filter()
    test_query_events_last_filter()
    test_query_memory_md_keyword()
    test_query_memory_md_topic()
    test_query_missing_source_warning_on_stderr()
    test_query_malformed_jsonl_skipped()
    test_turns_no_context_returns_zero()
    test_turns_with_heading_markers()
    test_split_turns_separator_heuristic()
    test_split_turns_blank_line_heuristic()
    test_event_to_date_parses_iso()
    test_event_to_date_bad_input_returns_none()
    print("All agentic-memory tests passed.")
