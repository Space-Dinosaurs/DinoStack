"""
Synthetic test for bin/agentic-parse-subagent-usage.

Exercises:
  - Token summation (input, output, cache_creation, cache_read) across
    multiple assistant turns in a JSONL transcript.
  - wall_seconds derived from first/last timestamps in the file.

Out of scope: path resolution from ~/.claude/projects/ (tested separately).

Pre-merge behavior: raises ImportError (bin script does not exist).
Post-merge behavior: all assertions pass.
"""
import json
import types
from pathlib import Path


def _load_bin(name: str) -> "types.ModuleType":
    import importlib.machinery
    # workspace root = parent.parent.parent.parent from this test file
    bin_path = Path(__file__).parent.parent.parent.parent / "bin" / name
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(bin_path))
    mod = types.ModuleType(name.replace("-", "_"))
    loader.exec_module(mod)
    return mod


def _write_transcript(path: Path, turns: list[dict]) -> None:
    with path.open("w") as fh:
        for obj in turns:
            fh.write(json.dumps(obj) + "\n")


def test_token_summation_and_wall_seconds(tmp_path: Path) -> None:
    """Sum tokens across three assistant turns; verify wall_seconds from timestamps."""
    transcript = tmp_path / "agent-abc.jsonl"

    turns = [
        # Non-assistant turn - tokens must NOT be counted
        {
            "type": "user",
            "timestamp": "2024-01-01T10:00:00.000Z",
            "message": {"role": "user", "content": "hello"},
        },
        # First assistant turn
        {
            "type": "assistant",
            "timestamp": "2024-01-01T10:00:01.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 5,
                },
            },
        },
        # Second assistant turn
        {
            "type": "assistant",
            "timestamp": "2024-01-01T10:00:02.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 80,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 15,
                },
            },
        },
        # Third assistant turn - last timestamp (10:00:11, delta = 10s from first assistant)
        {
            "type": "assistant",
            "timestamp": "2024-01-01T10:00:11.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 20,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        },
    ]
    _write_transcript(transcript, turns)

    mod = _load_bin("agentic-parse-subagent-usage")
    result = mod._parse_file(str(transcript))

    # Token sums across all three assistant turns
    assert result["tokens"]["input"] == 100 + 200 + 50
    assert result["tokens"]["output"] == 50 + 80 + 20
    assert result["tokens"]["cache_creation"] == 10 + 20 + 0
    assert result["tokens"]["cache_read"] == 5 + 15 + 0

    # wall_seconds: first timestamp is the user turn at 10:00:00,
    # last is the third assistant turn at 10:00:11 -> delta = 11.0s
    assert result["wall_seconds"] == 11.0


def test_wall_seconds_zero_for_single_event(tmp_path: Path) -> None:
    """Single entry produces wall_seconds == 0.0 (no delta possible)."""
    transcript = tmp_path / "agent-single.jsonl"
    turns = [
        {
            "type": "assistant",
            "timestamp": "2024-06-15T08:30:00.000Z",
            "message": {
                "role": "assistant",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        }
    ]
    _write_transcript(transcript, turns)

    mod = _load_bin("agentic-parse-subagent-usage")
    result = mod._parse_file(str(transcript))

    assert result["tokens"]["input"] == 10
    assert result["tokens"]["output"] == 5
    assert result["wall_seconds"] == 0.0


def test_non_assistant_turns_not_counted(tmp_path: Path) -> None:
    """user and tool_result turns must not contribute to token sums."""
    transcript = tmp_path / "agent-no-tokens.jsonl"
    turns = [
        {
            "type": "user",
            "timestamp": "2024-01-01T12:00:00.000Z",
            "message": {"role": "user", "content": "ping"},
        },
        {
            "type": "tool_result",
            "timestamp": "2024-01-01T12:00:05.000Z",
            "message": {"usage": {"input_tokens": 9999, "output_tokens": 9999}},
        },
    ]
    _write_transcript(transcript, turns)

    mod = _load_bin("agentic-parse-subagent-usage")
    result = mod._parse_file(str(transcript))

    assert result["tokens"]["input"] == 0
    assert result["tokens"]["output"] == 0
    # wall_seconds: 5s between first and last timestamp regardless of type
    assert result["wall_seconds"] == 5.0
