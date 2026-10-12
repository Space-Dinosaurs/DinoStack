#!/usr/bin/env python3
"""
Tests for bin/ds-measure-conductor-tool-calls: the calibration tool for
hooks/lib/overreach-detector.js's conductor_overreach threshold.

Public API covered:
  - _resolve_transcript_dirs() and the CLI's store set: every store under
    HOME is scanned by default, --store replaces that set, and no session in
    any store is reported absent (fixtures under a fake HOME; the operator's
    real transcripts are never read).
  - _measure_session(): the core per-session statistic (cumulative
    whole-transcript conductor_tool_calls / spawns / whitelisted_excluded),
    cross-checked against the shared JSON fixture also exercised by
    hooks/tests/test-overreach-detector.js (Skeptic Minor 2 - cross-language
    equivalence pinning).

Run with: python3 -m pytest bin/tests/test_ds_measure_conductor_tool_calls.py -q
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_BIN_PATH = Path(__file__).parent.parent / "ds-measure-conductor-tool-calls"
_loader = importlib.machinery.SourceFileLoader("ds_measure_conductor_tool_calls", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("ds_measure_conductor_tool_calls", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for ds-measure-conductor-tool-calls from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

_FIXTURE_PATH = (
    Path(__file__).parent.parent.parent
    / "hooks" / "tests" / "fixtures" / "overreach-shared-transcript.json"
)


def _write_transcript(tmp_dir: Path, lines: list[dict]) -> Path:
    transcript_path = tmp_dir / "transcript.jsonl"
    with transcript_path.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")
    return transcript_path


def _write_fixture_case(tmp_dir: Path, fixture_case: dict) -> Path:
    """Write a fixture case (either structured `lines` or literal
    `raw_lines`) to a real transcript file."""
    if "raw_lines" in fixture_case:
        transcript_path = tmp_dir / "transcript.jsonl"
        transcript_path.write_text(
            "\n".join(fixture_case["raw_lines"]) + "\n", encoding="utf-8"
        )
        return transcript_path
    return _write_transcript(tmp_dir, fixture_case.get("lines", []))


@pytest.mark.parametrize(
    "case_name",
    ["interleaved-non-agent-results", "empty-transcript", "malformed-transcript"],
)
def test_shared_fixture_equivalence(tmp_path, case_name):
    """Cross-language pin (Skeptic Minor 2, extended round-3 for the
    failure paths per Skeptic Minor 1): same fixture case, same result as
    the JS detector's hooks/tests/test-overreach-detector.js Test 1."""
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture_case = next(c for c in fixture["cases"] if c["name"] == case_name)
    transcript_path = _write_fixture_case(tmp_path, fixture_case)

    result = _mod._measure_session(transcript_path)
    expected = fixture_case["expected"]

    assert result["available"] == expected["available"]
    if not expected["available"]:
        assert result["conductor_tool_calls"] == 0
        assert result["spawns"] == 0
        assert result["whitelisted_excluded"] == 0
        return

    assert result["conductor_tool_calls"] == expected["conductor_tool_calls"]
    assert result["spawns"] == expected["live_or_completed_spawns"]
    assert result["whitelisted_excluded"] == expected["whitelisted_reads_excluded"]


def test_window_binds_to_agent_result_only(tmp_path):
    """Critical-2 regression, Python side: a non-Agent tool_result must
    never open or extend the post-spawn spot-check window."""
    lines = [
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "ls /repo"}},
        ]}},
        {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "b1"},
        ]}},
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": "/repo/x.js"}},
        ]}},
    ]
    transcript_path = _write_transcript(tmp_path, lines)
    result = _mod._measure_session(transcript_path)
    assert result["conductor_tool_calls"] == 2
    assert result["whitelisted_excluded"] == 0


def _session(store: Path, repo: Path, sid: str) -> Path:
    lines = [
        {"type": "user", "cwd": str(repo), "message": {"role": "user", "content": [
            {"type": "text", "text": "hi"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": "/x.js"}}]}},
    ]
    path = store / "projects" / _mod._transcripts.project_dir_prefix(repo) / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in lines),
                    encoding="utf-8")
    return path


def _two_stores(tmp_path: Path):
    home = tmp_path / "home"
    repo = Path(os.path.realpath(tmp_path)) / "repo"
    repo.mkdir()
    a, b = home / ".claude", home / ".claude-other"
    _session(a, repo, "aaaaaaaa-1")
    _session(b, repo, "bbbbbbbb-2")
    return home, repo, a, b


def _run(home: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for var in _mod._transcripts._lib.CONFIG_DIR_ENV:
        env.pop(var, None)
    env["HOME"] = str(home)
    result = subprocess.run([sys.executable, str(_BIN_PATH), *args], capture_output=True,
                            text=True, env=env, cwd=str(repo))
    assert result.returncode == 0, result.stderr
    return result


def test_resolve_transcript_dirs_maps_the_cwd_in_each_store(tmp_path, monkeypatch):
    home, repo, a, b = _two_stores(tmp_path)
    monkeypatch.chdir(repo)
    got = _mod._resolve_transcript_dirs([a / "projects", b / "projects", home])
    prefix = _mod._transcripts.project_dir_prefix(repo)
    assert got == {a / "projects": [a / "projects" / prefix],
                   b / "projects": [b / "projects" / prefix],
                   home: []}


def test_default_scans_every_store_under_home(tmp_path):
    """Named mutation: in main(), replace `_transcripts.stores(...)` with
    `[_transcripts._lib.resolve_claude_config_dir() / "projects"]` (the
    active dir only) and this reddens (sample_size 1, not 2)."""
    home, repo, a, b = _two_stores(tmp_path)
    payload = json.loads(_run(home, repo, "--json").stdout)
    assert payload["sample_size"] == 2
    assert payload["error"] is None
    assert {s["path"]: (s["sessions"], s["found"]) for s in payload["stores"]} == {
        os.path.realpath(a / "projects"): (1, 1),
        os.path.realpath(b / "projects"): (1, 1),
    }
    out = _run(home, repo).stdout
    assert "stores scanned (2):" in out
    assert os.path.realpath(b / "projects") in out


def test_store_flag_replaces_the_default_set(tmp_path):
    home, repo, a, b = _two_stores(tmp_path)
    payload = json.loads(_run(home, repo, "--json", "--store", str(b)).stdout)
    assert payload["sample_size"] == 1
    assert [s["path"] for s in payload["stores"]] == [os.path.realpath(b / "projects")]


def test_no_store_yields_a_session_is_absent_not_a_zero_sample(tmp_path):
    """P-R4. Mutation: drop the `if not files` early return in main() and
    this reddens (recommended_threshold 12 and no error)."""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in (".claude", ".claude-other"):
        (home / name / "projects").mkdir(parents=True)
    payload = json.loads(_run(home, repo, "--json").stdout)
    assert payload["error"] == "no_transcripts"
    assert payload["recommended_threshold"] is None
    assert [s["sessions"] for s in payload["stores"]] == [0, 0]
    out = _run(home, repo).stdout
    assert "stores scanned (2):" in out
    assert "No transcripts found." in out
    assert "Recommended THRESHOLD" not in out
