#!/usr/bin/env python3
"""
Tests for agentic-parse-subagent-usage: subagent transcript parser.

Public API: main([prog, session_uuid, agent_id])
  - Resolves transcript from ~/.claude/projects/<hash>/<session_uuid>/subagents/agent-<agent_id>.jsonl
  - Falls back to glob across all project hashes
  - Prints compact JSON {tokens, model, wall_seconds}
  - Always exits 0; errors via {"error": "..."} envelope

Run with: python3 bin/tests/test_agentic_parse_subagent_usage.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import tempfile
from io import StringIO
from pathlib import Path

_BIN_PATH = Path(__file__).parent.parent / "agentic-parse-subagent-usage"
_loader = importlib.machinery.SourceFileLoader("agentic_parse_subagent_usage", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_parse_subagent_usage", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-parse-subagent-usage from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)


def _capture_main(argv: list[str]) -> tuple[int, str]:
    old_stdout = sys.stdout
    captured = StringIO()
    sys.stdout = captured
    try:
        rc = _mod.main(argv)
    finally:
        sys.stdout = old_stdout
    return rc, captured.getvalue()


def _make_assistant_turn(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation: int = 0,
    cache_read: int = 0,
    timestamp: str = "2026-05-01T10:00:00Z",
) -> str:
    return json.dumps({
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
        },
    })


def _make_non_assistant_turn(ts: str = "2026-05-01T09:59:00Z") -> str:
    return json.dumps({"type": "user", "timestamp": ts, "content": "hello"})


def test_missing_args_returns_error_json():
    """Too few args -> exit 0 with {"error": "usage"}."""
    rc, out = _capture_main(["agentic-parse-subagent-usage"])
    assert rc == 0, f"Expected rc=0, got {rc}"
    data = json.loads(out)
    assert data.get("error") == "usage", f"Expected error='usage', got {data}"
    print("PASS test_missing_args_returns_error_json")


def test_transcript_not_found_returns_error_json():
    """Non-existent transcript -> exit 0 with {"error": "transcript_not_found"}."""
    rc, out = _capture_main(["agentic-parse-subagent-usage", "no-such-uuid", "deadbeef"])
    assert rc == 0, f"Expected rc=0, got {rc}"
    data = json.loads(out)
    assert data.get("error") == "transcript_not_found", (
        f"Expected error='transcript_not_found', got {data}"
    )
    print("PASS test_transcript_not_found_returns_error_json")


def test_parse_file_sums_tokens():
    """_parse_file sums tokens across all assistant turns."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_make_assistant_turn("claude-3", 100, 50, 10, 5,
                                     "2026-05-01T10:00:00Z") + "\n")
        f.write(_make_assistant_turn("claude-3", 200, 80, 20, 15,
                                     "2026-05-01T10:01:00Z") + "\n")
        path = f.name

    result = _mod._parse_file(path)
    assert result["tokens"]["input"] == 300, (
        f"Expected 300 input tokens, got {result['tokens']['input']}"
    )
    assert result["tokens"]["output"] == 130, (
        f"Expected 130 output tokens, got {result['tokens']['output']}"
    )
    assert result["tokens"]["cache_creation"] == 30, (
        f"Expected 30 cache_creation, got {result['tokens']['cache_creation']}"
    )
    assert result["tokens"]["cache_read"] == 20, (
        f"Expected 20 cache_read, got {result['tokens']['cache_read']}"
    )
    print("PASS test_parse_file_sums_tokens")


def test_parse_file_captures_model():
    """_parse_file captures model from first assistant turn."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_make_assistant_turn("claude-sonnet-4", 10, 5) + "\n")
        f.write(_make_assistant_turn("claude-opus-4", 20, 10) + "\n")
        path = f.name

    result = _mod._parse_file(path)
    assert result["model"] == "claude-sonnet-4", (
        f"Expected first model 'claude-sonnet-4', got {result['model']}"
    )
    print("PASS test_parse_file_captures_model")


def test_parse_file_wall_seconds():
    """_parse_file computes wall_seconds from first to last timestamp."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_make_assistant_turn("claude-3", 10, 5,
                                     timestamp="2026-05-01T10:00:00Z") + "\n")
        f.write(_make_non_assistant_turn("2026-05-01T10:00:30Z") + "\n")
        f.write(_make_assistant_turn("claude-3", 20, 8,
                                     timestamp="2026-05-01T10:01:00Z") + "\n")
        path = f.name

    result = _mod._parse_file(path)
    # wall = 10:01:00 - 10:00:00 = 60 seconds
    assert result["wall_seconds"] == 60.0, (
        f"Expected wall_seconds=60.0, got {result['wall_seconds']}"
    )
    print("PASS test_parse_file_wall_seconds")


def test_parse_file_single_turn_zero_wall():
    """Single turn -> wall_seconds == 0.0 (no interval)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_make_assistant_turn("claude-3", 50, 25,
                                     timestamp="2026-05-01T10:00:00Z") + "\n")
        path = f.name

    result = _mod._parse_file(path)
    assert result["wall_seconds"] == 0.0, (
        f"Expected wall_seconds=0.0 for single turn, got {result['wall_seconds']}"
    )
    print("PASS test_parse_file_single_turn_zero_wall")


def test_parse_file_skips_non_assistant_turns():
    """Non-assistant turns are ignored for token counting."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(_make_non_assistant_turn() + "\n")
        f.write(_make_assistant_turn("claude-3", 100, 50) + "\n")
        path = f.name

    result = _mod._parse_file(path)
    assert result["tokens"]["input"] == 100, (
        f"Expected exactly 100 input tokens (user turn ignored), got {result['tokens']['input']}"
    )
    print("PASS test_parse_file_skips_non_assistant_turns")


def test_parse_file_skips_malformed_lines():
    """Malformed JSONL lines are silently skipped."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write("NOT_VALID_JSON\n")
        f.write(_make_assistant_turn("claude-3", 10, 5) + "\n")
        path = f.name

    result = _mod._parse_file(path)
    assert result["tokens"]["input"] == 10, (
        f"Expected 10 input tokens after skipping malformed line, got {result['tokens']['input']}"
    )
    print("PASS test_parse_file_skips_malformed_lines")


def test_parse_file_empty_file():
    """Empty transcript -> zero tokens, None model, 0.0 wall."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name  # empty file

    result = _mod._parse_file(path)
    assert result["tokens"]["input"] == 0
    assert result["tokens"]["output"] == 0
    assert result["model"] is None
    assert result["wall_seconds"] == 0.0
    print("PASS test_parse_file_empty_file")


def test_project_hash_from_cwd_substitution():
    """_project_hash_from_cwd replaces '/' with '-'."""
    import os
    old_cwd = os.getcwd()
    try:
        # The function uses os.getcwd(), so we can test by checking the pattern
        h = _mod._project_hash_from_cwd()
        assert "/" not in h, f"Expected no '/' in hash, got: {h!r}"
        assert h.startswith("-") or h[0] != "/", "hash should start with '-' for absolute paths"
    finally:
        os.chdir(old_cwd)
    print("PASS test_project_hash_from_cwd_substitution")


def test_parse_iso_valid_timestamps():
    """_parse_iso parses valid ISO timestamps including Z suffix."""
    ts1 = _mod._parse_iso("2026-05-01T10:00:00Z")
    ts2 = _mod._parse_iso("2026-05-01T10:00:00+00:00")
    assert ts1 is not None, "Expected datetime for Z-suffixed timestamp"
    assert ts2 is not None, "Expected datetime for +00:00 timestamp"
    print("PASS test_parse_iso_valid_timestamps")


def test_parse_iso_invalid_returns_none():
    """_parse_iso returns None for invalid/empty input."""
    assert _mod._parse_iso("not-a-date") is None
    assert _mod._parse_iso("") is None
    assert _mod._parse_iso(None) is None
    print("PASS test_parse_iso_invalid_returns_none")


def test_resolve_transcript_primary_path(tmp_path: Path | None = None):
    """_resolve_transcript finds transcript at the primary path when it exists."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        import os
        # Build path matching primary resolution: ~/<hash>/<uuid>/subagents/agent-<id>.jsonl
        # We patch HOME to the tmp dir so _project_hash_from_cwd uses tmp
        session_uuid = "test-session-abc"
        agent_id = "test-agent-xyz"
        cwd_hash = os.getcwd().replace("/", "-")
        subagent_dir = tmp_p / ".claude" / "projects" / cwd_hash / session_uuid / "subagents"
        subagent_dir.mkdir(parents=True)
        transcript = subagent_dir / f"agent-{agent_id}.jsonl"
        transcript.write_text(_make_assistant_turn("claude-3", 5, 2) + "\n")

        # Patch HOME so Path("~").expanduser() resolves to tmp_p
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = tmp
        try:
            result = _mod._resolve_transcript(session_uuid, agent_id)
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home

        assert result is not None, "Expected transcript to be found at primary path"
        assert result == str(transcript), f"Unexpected path: {result}"
    print("PASS test_resolve_transcript_primary_path")


if __name__ == "__main__":
    test_missing_args_returns_error_json()
    test_transcript_not_found_returns_error_json()
    test_parse_file_sums_tokens()
    test_parse_file_captures_model()
    test_parse_file_wall_seconds()
    test_parse_file_single_turn_zero_wall()
    test_parse_file_skips_non_assistant_turns()
    test_parse_file_skips_malformed_lines()
    test_parse_file_empty_file()
    test_project_hash_from_cwd_substitution()
    test_parse_iso_valid_timestamps()
    test_parse_iso_invalid_returns_none()
    test_resolve_transcript_primary_path()
    print("All agentic-parse-subagent-usage tests passed.")
