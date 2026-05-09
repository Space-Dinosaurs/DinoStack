import importlib.machinery
import types
import json
import sys
from pathlib import Path
import pytest


def _load_bin(name):
    bin_path = Path(__file__).parent.parent.parent.parent / "bin" / name
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(bin_path))
    mod = types.ModuleType(name.replace("-", "_"))
    loader.exec_module(mod)
    return mod


def _write_events(events_path, events):
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _make_spawn_complete(critical=0, major=0, minor=0, diff_lines=100):
    return {
        "ts": "2026-05-09T00:00:00Z",
        "phase": "skeptic-review",
        "event": "spawn_complete",
        "agent": "skeptic",
        "data": {
            "findings_count": {"critical": critical, "major": major, "minor": minor},
            "diff_lines": diff_lines,
        },
    }


def test_density_warming_up_below_10_events(tmp_path, monkeypatch, capsys):
    """AC2: fewer than 10 qualifying spawn_complete events -> warming-up notice."""
    events_path = tmp_path / ".agentic" / "events.jsonl"
    _write_events(events_path, [_make_spawn_complete(major=1, diff_lines=100) for _ in range(5)])
    monkeypatch.setenv("AGENTIC_DIR", str(tmp_path / ".agentic"))
    mod = _load_bin("agentic-calibrate")
    result = mod.main(["density"])
    assert result == 0
    out = capsys.readouterr().out
    assert "warming" in out.lower(), f"expected warming-up notice; got: {out[:300]}"


def test_density_full_table_at_or_above_10_events(tmp_path, monkeypatch, capsys):
    """AC1: density = (critical + major + minor) / diff_lines * 100 per event."""
    events = [_make_spawn_complete(critical=2, major=3, minor=5, diff_lines=100) for _ in range(10)]
    _write_events(tmp_path / ".agentic" / "events.jsonl", events)
    monkeypatch.setenv("AGENTIC_DIR", str(tmp_path / ".agentic"))
    mod = _load_bin("agentic-calibrate")
    result = mod.main(["density"])
    assert result == 0
    out = capsys.readouterr().out
    # Per-row density = (2+3+5)/100 * 100 = 10.0
    # Aggregate density = (10*10 findings)/(10*100 lines) * 100 = 10.00 per 100 lines
    assert "10" in out, f"expected density 10.0 in output; got: {out[:500]}"
    # Warming-up notice must NOT appear (10 qualifying events meets threshold)
    assert "warming" not in out.lower(), f"unexpected warming-up notice at 10 events; got: {out[:300]}"


def test_density_excludes_zero_diff_rows(tmp_path, monkeypatch, capsys):
    """AC3: events with diff_lines == 0 are excluded from density calculation."""
    # 10 zero-diff rows (major=99 each) + 10 normal rows (major=1, diff_lines=100)
    # Zero-diff rows must be excluded from aggregate density computation.
    events = [_make_spawn_complete(major=99, diff_lines=0) for _ in range(10)]
    events += [_make_spawn_complete(major=1, diff_lines=100) for _ in range(10)]
    _write_events(tmp_path / ".agentic" / "events.jsonl", events)
    monkeypatch.setenv("AGENTIC_DIR", str(tmp_path / ".agentic"))
    mod = _load_bin("agentic-calibrate")
    result = mod.main(["density"])
    assert result == 0
    out = capsys.readouterr().out
    # If zero-diff rows were included, aggregate density would be dominated by major=99.
    # Expected aggregate (zero-diff excluded): 1/100*100 = 1.00 per 100 lines.
    assert "1.00" in out, f"expected aggregate density 1.00 (zero-diff excluded); got: {out[:500]}"
