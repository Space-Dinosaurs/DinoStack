"""
Purpose: Unit tests for evals/skill-comparison/canary/assert_canary.py.
         Covers: assert_canary() parse logic using synthetic JSONL fixtures,
         _find_task_spawn(), _find_task_result_with_agent_type(),
         and _check_tools_in_system_prompt() strategies.

Public API: pytest test module; no public symbols.

Upstream deps: canary.assert_canary (via conftest sys.path insertion),
               stdlib json, tempfile, pathlib.

Downstream consumers: pytest runner.

Failure modes: all tests use temp files; no network I/O; no side effects
               on the real transcript.

Performance: standard; synthetic fixtures are tiny.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# conftest.py inserts evals/skill-comparison/ into sys.path so we can import
# from the canary/ subdirectory directly.
sys.path.insert(0, str(Path(__file__).parent.parent / "canary"))
from assert_canary import (
    assert_canary,
    _find_task_spawn,
    _find_task_result_with_agent_type,
    _check_tools_in_system_prompt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(tmp: Path, events: list[dict]) -> Path:
    """Write events as JSONL to a temp file and return the path."""
    p = tmp / "transcript.jsonl"
    lines = [json.dumps(e) for e in events]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _make_agent_tool_use(agent_name: str, tool_id: str = "toolu_abc") -> dict:
    """Make an assistant event with an Agent tool_use block."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Agent",
                    "id": tool_id,
                    "input": {
                        "subagent_type": agent_name,
                        "prompt": "Test prompt.",
                    },
                }
            ],
        },
    }


def _make_task_tool_use(agent_name: str, tool_id: str = "toolu_abc") -> dict:
    """Make an assistant event with a Task tool_use block (older CLI name)."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Task",
                    "id": tool_id,
                    "input": {
                        "subagent_type": agent_name,
                        "prompt": "Test prompt.",
                    },
                }
            ],
        },
    }


def _make_task_result(agent_name: str, tool_use_id: str = "toolu_abc") -> dict:
    """Make the outer Task tool_result user event."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": [{"type": "text", "text": "Agent response here."}],
                }
            ],
        },
        "parent_tool_use_id": None,
        "tool_use_result": {"agentType": agent_name},
    }


def _make_inner_task_result(tool_use_id: str = "toolu_abc") -> dict:
    """Make a nested tool_result (from the inner agent's Read call etc.)."""
    return {
        "type": "user",
        "parent_tool_use_id": tool_use_id,  # nested, not the outer Task result
        "message": {"role": "user", "content": []},
    }


def _make_system_init(agents: list[str], tools: list[str] | None = None) -> dict:
    """Make a system/init event listing registered agents and tools."""
    event: dict = {
        "type": "system",
        "subtype": "init",
        "agents": agents,
        "session_id": "test-session",
        "model": "claude-test",
    }
    if tools is not None:
        event["tools"] = tools
    return event


def _make_result_event() -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "num_turns": 1,
        "result": "done",
        "total_cost_usd": 0.001,
    }


# ---------------------------------------------------------------------------
# Tests: _find_task_spawn
# ---------------------------------------------------------------------------

class TestFindTaskSpawn:
    def test_finds_agent_tool_use(self):
        events = [_make_agent_tool_use("skeptic")]
        block = _find_task_spawn(events, "skeptic")
        assert block is not None
        assert block["input"]["subagent_type"] == "skeptic"

    def test_finds_task_tool_use(self):
        """Older CLI used 'Task' as tool name; must still be recognized."""
        events = [_make_task_tool_use("skeptic")]
        block = _find_task_spawn(events, "skeptic")
        assert block is not None

    def test_case_insensitive_match(self):
        events = [_make_agent_tool_use("Skeptic")]
        block = _find_task_spawn(events, "skeptic")
        assert block is not None

    def test_wrong_agent_not_found(self):
        events = [_make_agent_tool_use("engineer")]
        block = _find_task_spawn(events, "skeptic")
        assert block is None

    def test_no_tool_use_events(self):
        events = [{"type": "assistant", "message": {"content": []}}]
        block = _find_task_spawn(events, "skeptic")
        assert block is None

    def test_non_spawn_tool_use_ignored(self):
        events = [{
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "name": "Read",
                    "id": "toolu_xyz",
                    "input": {"file_path": "/foo"},
                }]
            },
        }]
        block = _find_task_spawn(events, "skeptic")
        assert block is None


# ---------------------------------------------------------------------------
# Tests: _find_task_result_with_agent_type
# ---------------------------------------------------------------------------

class TestFindTaskResult:
    def test_finds_outer_task_result(self):
        events = [_make_task_result("skeptic")]
        result = _find_task_result_with_agent_type(events, "skeptic")
        assert result is not None

    def test_nested_result_excluded(self):
        """Nested tool_results (parent_tool_use_id set) must NOT match."""
        events = [_make_inner_task_result()]
        result = _find_task_result_with_agent_type(events, "skeptic")
        assert result is None

    def test_wrong_agent_type_not_found(self):
        events = [_make_task_result("engineer")]
        result = _find_task_result_with_agent_type(events, "skeptic")
        assert result is None

    def test_case_insensitive(self):
        events = [_make_task_result("Skeptic")]
        result = _find_task_result_with_agent_type(events, "skeptic")
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: assert_canary (end-to-end with synthetic transcripts)
# ---------------------------------------------------------------------------

class TestAssertCanary:
    def test_passes_on_complete_transcript(self):
        """Full synthetic transcript with Agent spawn + tool list in init."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [
                _make_system_init(
                    agents=["skeptic", "engineer"],
                    tools=["Read", "Grep", "Glob", "Bash", "Task"],
                ),
                _make_agent_tool_use("skeptic"),
                _make_task_result("skeptic"),
                _make_result_event(),
            ]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(p, agent_name="skeptic",
                                              expected_tools=["Read", "Grep", "Glob", "Bash"])
            assert passed, f"Expected pass, got failures: {failures}"

    def test_fails_when_no_spawn_event(self):
        """No Task/Agent tool_use in transcript."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [_make_result_event()]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(p, agent_name="skeptic")
            assert not passed
            assert any("Assertion 1 FAILED" in f for f in failures)

    def test_fails_when_wrong_agent_spawned(self):
        """Agent tool_use present but for a different agent."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [
                _make_agent_tool_use("engineer"),  # wrong agent
                _make_result_event(),
            ]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(p, agent_name="skeptic")
            assert not passed

    def test_fails_on_missing_transcript(self):
        """Non-existent transcript file returns failure."""
        p = Path("/tmp/no_such_file_canary_test.jsonl")
        passed, failures = assert_canary(p, agent_name="skeptic")
        assert not passed
        assert any("not found" in f for f in failures)

    def test_fails_on_empty_transcript(self):
        """Empty JSONL produces failure."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            p = tmp / "empty.jsonl"
            p.write_text("", encoding="utf-8")
            passed, failures = assert_canary(p, agent_name="skeptic")
            assert not passed

    def test_older_task_tool_name_accepted(self):
        """'Task' tool name (older CLI) also triggers assertion 1 pass."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [
                _make_system_init(
                    agents=["skeptic"],
                    tools=["Read", "Grep", "Glob", "Bash"],
                ),
                _make_task_tool_use("skeptic"),
                _make_task_result("skeptic"),
                _make_result_event(),
            ]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(p, agent_name="skeptic",
                                              expected_tools=["Read", "Grep", "Glob", "Bash"])
            assert passed, f"Expected pass with Task tool name, got: {failures}"

    def test_malformed_json_lines_skipped(self):
        """Malformed lines in JSONL are skipped without crash."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            p = tmp / "malformed.jsonl"
            lines = [
                json.dumps(_make_system_init(["skeptic"], ["Read", "Grep", "Glob", "Bash"])),
                "{not valid json",
                json.dumps(_make_agent_tool_use("skeptic")),
                json.dumps(_make_task_result("skeptic")),
                json.dumps(_make_result_event()),
            ]
            p.write_text("\n".join(lines), encoding="utf-8")
            # Should not raise; malformed line is skipped.
            passed, failures = assert_canary(p, agent_name="skeptic",
                                              expected_tools=["Read", "Grep", "Glob", "Bash"])
            assert passed, f"Expected pass despite malformed line, got: {failures}"

    def test_custom_agent_and_tools(self):
        """assert_canary works for agent_name != 'skeptic'."""
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            events = [
                _make_system_init(
                    agents=["engineer"],
                    tools=["Read", "Grep", "Glob", "Bash", "Write", "Edit"],
                ),
                _make_agent_tool_use("engineer"),
                _make_task_result("engineer"),
                _make_result_event(),
            ]
            p = _write_jsonl(tmp, events)
            passed, failures = assert_canary(p, agent_name="engineer",
                                              expected_tools=["Read", "Write", "Edit"])
            assert passed, f"Expected pass for engineer, got: {failures}"
