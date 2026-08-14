#!/usr/bin/env python3
"""
Tests for bin/ds-measure-conductor-tool-calls: the calibration tool for
hooks/lib/overreach-detector.js's conductor_overreach threshold.

Public API covered:
  - _resolve_transcript_dir(): primary cwd-hash resolution AND the
    fallback-glob path when the primary directory does not exist (Skeptic
    Minor 3 on PR #730 - this had zero test coverage).
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


@pytest.fixture
def restore_env():
    """Restore CLAUDE_CONFIG_DIR and cwd after a test that mutates them."""
    old_cwd = os.getcwd()
    old_env = os.environ.get("CLAUDE_CONFIG_DIR")
    yield
    os.chdir(old_cwd)
    if old_env is None:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
    else:
        os.environ["CLAUDE_CONFIG_DIR"] = old_env


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


def test_resolve_transcript_dir_primary_path(tmp_path, restore_env):
    """Primary cwd-hash resolution path."""
    config_dir = tmp_path / "config"
    fake_cwd = tmp_path / "cwd"
    fake_cwd.mkdir()
    project_hash = str(fake_cwd).replace("/", "-")
    primary_dir = config_dir / "projects" / project_hash
    primary_dir.mkdir(parents=True)

    os.environ["CLAUDE_CONFIG_DIR"] = str(config_dir)
    os.chdir(fake_cwd)

    resolved = _mod._resolve_transcript_dir()
    assert resolved == primary_dir


def test_resolve_transcript_dir_fallback_glob_path(tmp_path, restore_env):
    """Skeptic Minor 3: the fallback-glob branch had zero prior coverage.
    Plants a project dir whose basename ENDS WITH the repo token but is not
    a literal cwd-hash match (e.g. a worktree subdirectory scenario) -
    exactly what the fallback glob exists to find."""
    config_dir = tmp_path / "config"
    real_cwd = os.getcwd()
    repo_token = Path(real_cwd).name.replace("/", "-")

    mismatched_dir = config_dir / "projects" / f"-some-other-prefix-{repo_token}"
    mismatched_dir.mkdir(parents=True)

    os.environ["CLAUDE_CONFIG_DIR"] = str(config_dir)

    resolved = _mod._resolve_transcript_dir()
    assert resolved == mismatched_dir


def test_resolve_transcript_dir_returns_none_when_nothing_matches(tmp_path, restore_env):
    config_dir = tmp_path / "config"
    (config_dir / "projects").mkdir(parents=True)

    os.environ["CLAUDE_CONFIG_DIR"] = str(config_dir)

    resolved = _mod._resolve_transcript_dir()
    assert resolved is None
