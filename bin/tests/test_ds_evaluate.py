#!/usr/bin/env python3
"""
Tests for bin/ds-evaluate: the /ds-evaluate signal collector CLI.

Covers: synthetic-tree extraction of every signal source (session-log,
events, enforcement-fires, resident floor, vision pillars), omission of
absent/empty sources (the green-often-means-the-check-did-not-run
discipline), zero-filled token handling, the non-DinoStack guard (exit 1),
the --help and --json flags, the --repo default of cwd, and budget-gate
omission when the gate scripts are missing.

Run with: python3 -m pytest bin/tests/test_ds_evaluate.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).parent.parent / "ds-evaluate"
PY = sys.executable


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_repo(tmp_path: Path, with_sections: bool = True) -> Path:
    repo = tmp_path / "repo"
    if with_sections:
        (repo / "content" / "sections").mkdir(parents=True, exist_ok=True)
    else:
        repo.mkdir(parents=True, exist_ok=True)
    return repo


def _run(repo: Path, *extra: str, cwd: Path | None = None, home: Path | None = None):
    env = os.environ.copy()
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run(
        [PY, str(BIN), "--repo", str(repo), *extra],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        cwd=str(cwd) if cwd is not None else None,
    )


def _run_repo(repo: Path, home: Path, *extra: str):
    """Run ds-evaluate against repo with an isolated HOME; return parsed JSON."""
    proc = _run(repo, *extra, home=home)
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)


# Sample signal-source contents -------------------------------------------------

_SESSION_LOG_LINE = (
    '{"ts": "2026-08-01T10:00:00Z", "phase": "session_end", "event": "session_total", '
    '"agent": null, "task_id": null, "developer_id": "admin", "session_uuid": "a", '
    '"project_slug": "repo", "branch": "main", "data": {"wall_seconds": %d, '
    '"tokens": {"input": %d, "output": %d, "cache_creation": %d, "cache_read": %d}, '
    '"spawn_count": %d, "by_agent": {}}}'
)

_EVENT_LINES = [
    json.dumps({"ts": "2026-08-01T10:00:00Z", "phase": "orchestration", "event": "spawn_start", "agent": "engineer", "data": {"tier": 1, "session_uuid": "s1"}}),
    json.dumps({"ts": "2026-08-01T11:00:00Z", "phase": "orchestration", "event": "spawn_complete", "agent": "engineer", "data": {"tier": 1, "model": "sonnet", "wall_seconds": 10, "status": "ok", "session_uuid": "s1"}}),
    json.dumps({"ts": "2026-08-01T12:00:00Z", "phase": "session_end", "event": "session_total", "agent": None, "data": {"wall_seconds": 100, "tokens": {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0}, "spawn_count": 1}}),
]

_FIRE_LINES = [
    json.dumps({"ts": "2026-08-01T12:00:00.000Z", "hook": "enforce-tier", "decision": "deny", "reason": "blocked"}),
    json.dumps({"ts": "2026-08-02T12:00:00.000Z", "hook": "enforce-tier", "decision": "allow_advisory", "reason": "advised"}),
    json.dumps({"ts": "2026-08-03T12:00:00.000Z", "hook": "enforce-shippable-edit", "decision": "deny", "reason": "blocked"}),
]

_VISION_MD = """# DinoStack Product Vision (North Star)

## North Star (what every change should serve)

1. **Guard operator attention.** Surface decisions and work-stoppages, not status.
2. **Produce verifiable outcomes autonomously.** Agents should drive work to a checkable result.
"""


def _populate_full_tree(repo: Path) -> None:
    """Write every signal source the collector reads."""
    _write(
        repo / ".agentic" / "session-log" / "admin-fullmetalblanket.jsonl",
        _SESSION_LOG_LINE % (100, 0, 0, 0, 0, 3) + "\n"
        + _SESSION_LOG_LINE % (200, 0, 0, 0, 0, 5) + "\n",
    )
    _write(repo / ".agentic" / "events.jsonl", "\n".join(_EVENT_LINES) + "\n")
    _write(repo / ".agentic" / ".enforcement-fires.jsonl", "\n".join(_FIRE_LINES) + "\n")
    _write(repo / "CLAUDE.md", "")
    _write(repo / "AGENTS.md", "hello")
    _write(repo / "MEMORY.md", "")
    _write(repo / ".agentic" / "memory" / "MEMORY.md", "abc")
    _write(repo / "docs" / "overview" / "vision.md", _VISION_MD)


# Tests ------------------------------------------------------------------------


def test_full_synthetic_tree(tmp_path):
    """All present sources are extracted; absent ones (budget_gates) omitted."""
    repo = _make_repo(tmp_path)
    home = tmp_path / "home"
    _populate_full_tree(repo)

    data = _run_repo(repo, home)

    # Signal 1: session-log aggregation.
    session_log = data["session_log"]
    assert session_log["files"] == 1
    assert session_log["sessions"] == 2
    assert session_log["wall_seconds"] == 300
    assert session_log["spawn_count"] == 8
    assert "tokens" not in session_log  # all-zero -> omitted
    assert session_log["tokens_data_quality"] == "zero-filled"

    # Signal 2: events.jsonl.
    events = data["events"]
    assert events["by_phase"] == {"orchestration": 2, "session_end": 1}
    assert events["by_event"] == {
        "session_total": 1,
        "spawn_complete": 1,
        "spawn_start": 1,
    }
    assert events["spawn_start"] == 1
    assert events["spawn_complete"] == 1

    # Signal 3: enforcement fires.
    fires = data["enforcement_fires"]
    assert fires["deny_total"] == 2
    assert fires["allow_advisory_total"] == 1
    assert fires["by_hook"] == {
        "enforce-shippable-edit": {"allow_advisory": 0, "deny": 1},
        "enforce-tier": {"allow_advisory": 1, "deny": 1},
    }
    assert fires["newest_ts"] == "2026-08-03T12:00:00.000Z"
    assert len(fires["last_10_days"]) == 10
    assert fires["last_10_days"]["2026-08-03"] == 1
    assert fires["last_10_days"]["2026-08-02"] == 1
    assert fires["last_10_days"]["2026-08-01"] == 1
    assert "2026-07-24" not in fires["last_10_days"]  # outside the 10-day window
    assert fires["last_10_days"]["2026-07-25"] == 0  # window start, no fires

    # Signal 5: resident floor (isolated HOME -> ~/.claude/CLAUDE.md omitted).
    floor = data["resident_floor"]
    assert "~/.claude/CLAUDE.md" not in floor["files"]
    assert floor["files"] == {
        "AGENTS.md": 5,
        "CLAUDE.md": 0,
        "MEMORY.md": 0,
        ".agentic/memory/MEMORY.md": 3,
    }
    assert floor["sum"] == 8

    # Signal 6: vision pillars read live from the synthetic vision.md.
    assert data["vision_pillars"] == [
        "1. Guard operator attention",
        "2. Produce verifiable outcomes autonomously",
    ]

    # Signal 4: no scripts/ dir -> budget_gates omitted entirely.
    assert "budget_gates" not in data


def test_missing_and_empty_sources_omitted(tmp_path):
    """A bare repo yields no signal keys (no false zeros), exit 0, no crash."""
    repo = _make_repo(tmp_path)
    home = tmp_path / "home"

    data = _run_repo(repo, home)
    assert data == {}

    # Empty (not just missing) files also produce no keys.
    _write(repo / ".agentic" / "events.jsonl", "")
    _write(repo / ".agentic" / "session-log" / "admin.jsonl", "")
    _write(repo / ".agentic" / ".enforcement-fires.jsonl", "\n")
    _write(repo / "docs" / "overview" / "vision.md", "# no pillars\n")

    data = _run_repo(repo, home)
    assert data == {}


def test_zero_filled_tokens_omitted(tmp_path):
    """All-zero token figures -> token fields omitted + zero-filled note."""
    repo = _make_repo(tmp_path)
    home = tmp_path / "home"
    _write(
        repo / ".agentic" / "session-log" / "admin.jsonl",
        _SESSION_LOG_LINE % (100, 0, 0, 0, 0, 1) + "\n",
    )

    data = _run_repo(repo, home)
    session_log = data["session_log"]
    assert "tokens" not in session_log
    assert session_log["tokens_data_quality"] == "zero-filled"
    assert session_log["sessions"] == 1


def test_nonzero_tokens_reported(tmp_path):
    """A nonzero token figure -> token sums reported, no zero-filled note."""
    repo = _make_repo(tmp_path)
    home = tmp_path / "home"
    _write(
        repo / ".agentic" / "session-log" / "admin.jsonl",
        _SESSION_LOG_LINE % (100, 50, 20, 10, 5, 1) + "\n",
    )

    data = _run_repo(repo, home)
    session_log = data["session_log"]
    assert session_log["tokens"] == {
        "input": 50,
        "output": 20,
        "cache_creation": 10,
        "cache_read": 5,
    }
    assert "tokens_data_quality" not in session_log


def test_not_a_dinostack_repo_exit_1(tmp_path):
    """A repo without content/sections/ exits 1 with a clear message."""
    repo = tmp_path / "not-a-repo"
    repo.mkdir(parents=True, exist_ok=True)

    proc = _run(repo, home=tmp_path / "home")
    assert proc.returncode == 1
    assert "not a DinoStack checkout" in proc.stderr
    assert proc.stdout == ""


def test_help_flag(tmp_path):
    """--help prints usage and exits 0."""
    proc = _run(tmp_path / "irrelevant", "--help", home=tmp_path / "home")
    assert proc.returncode == 0
    assert "usage" in proc.stdout
    assert "--repo" in proc.stdout


def test_json_flag_accepted(tmp_path):
    """--json is accepted (it is the default) and output still parses."""
    repo = _make_repo(tmp_path)
    home = tmp_path / "home"
    _write(repo / "docs" / "overview" / "vision.md", _VISION_MD)

    data = _run_repo(repo, home, "--json")
    assert data["vision_pillars"] == [
        "1. Guard operator attention",
        "2. Produce verifiable outcomes autonomously",
    ]


def test_default_repo_is_cwd(tmp_path):
    """With no --repo, the collector uses the current working directory."""
    repo = _make_repo(tmp_path)
    home = tmp_path / "home"
    _write(repo / "docs" / "overview" / "vision.md", _VISION_MD)

    proc = _run(repo, home=home, cwd=repo)
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"
    data = json.loads(proc.stdout)
    assert data["vision_pillars"] == [
        "1. Guard operator attention",
        "2. Produce verifiable outcomes autonomously",
    ]


def test_budget_gates_omitted_when_scripts_missing(tmp_path):
    """A scripts/ dir lacking the gate scripts omits every gate (no crash)."""
    repo = _make_repo(tmp_path)
    home = tmp_path / "home"
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    _write(repo / "scripts" / "unrelated.sh", "#!/bin/bash\n")

    data = _run_repo(repo, home)
    assert "budget_gates" not in data
